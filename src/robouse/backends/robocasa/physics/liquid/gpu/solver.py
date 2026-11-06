"""`WarpFluid`: the liquid contract 0.3.0 solver on the GPU (NVIDIA Warp), with `liquid.solver.SPHFluid`'s interface.

Same model as the native backend: DFSPH (Bender & Koschier 2017, SPlisHSPlasH 2.19.0 formulation with warm start),
Akinci 2012 boundary particles sampled from the same meshes (regular triangle sampling at 1.5 r, or a caller's custom
samples), Weiler 2018 implicit viscosity (block-Jacobi CG) and Jeske 2023 implicit surface tension (CG), cubic
spline kernel with support 4 r, float32 state, our float64 clock and CFL schedule landing on every MuJoCo step.

Differences from the native build that are known and documented in the P2-G report: the analytic cubic kernel is
used everywhere (the native scalar paths read a 10000-sample lookup table, its AVX paths are analytic); boundary
neighbour order follows the hash grid, so float32 sums differ in rounding order from CompactNSearch/TreeNSearch; the
host-side `positions()`/`velocities()` are mirrors synchronised on demand rather than views of the solver's memory.
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

import numpy as np

from .. import solver as cpu_solver
from ..solver import Boundary, FluidParams, quat_to_mat
from . import kernels as K
from .sampling import regular_triangle_sampling

_LIVE = None
DEFAULT_KF = 64
DEFAULT_KB = 128


def _device():
    import warp as wp

    wp.init()
    dev = os.environ.get("LIQUID_GPU_DEVICE")
    if dev:
        return dev
    return "cuda:0" if wp.is_cuda_available() else "cpu"


class _FieldShim:
    """`checks._density_error` reads `fluid.fluid.getFieldBuffer("density")`: serve the GPU density."""

    def __init__(self, owner):
        self._o = owner

    def getFieldBuffer(self, name):
        if name == "density":
            return self._o.rho.numpy()
        if name == "position":
            return self._o.positions()
        if name == "velocity":
            return self._o.velocities()
        raise KeyError(name)


class WarpFluid:
    backend_id = "warp-dfsph-prototype-p2g"

    def __init__(self, workdir, params: FluidParams, boundaries: list[Boundary], particles: np.ndarray,
                 threads: int | None = None, backend: dict | None = None, kf: int = DEFAULT_KF, kb: int = DEFAULT_KB,
                 device: str | None = None):
        global _LIVE
        import warp as wp

        if _LIVE is not None:
            raise RuntimeError("one WarpFluid per process in the prototype; close() the previous one first")
        particles = np.asarray(particles, float)
        if particles.ndim != 2 or particles.shape[1] != 3 or not len(particles) or not np.isfinite(particles).all():
            raise ValueError("SPH requires a nonempty finite (N, 3) particle array")
        if not 0 < params.dt_min <= params.dt_max or params.particle_radius <= 0 or params.density <= 0:
            raise ValueError("invalid SPH time step, radius or density")
        if params.boundary_method != 0 or params.cfl_method != 0:
            raise ValueError("the GPU prototype implements Akinci boundaries and the contract's own CFL schedule only")
        if params.surface_tension and params.surface_tension_method != 4:
            raise ValueError("the GPU prototype implements Jeske 2023 surface tension only")
        if params.adhesion or params.xsph:
            raise ValueError("adhesion and XSPH are not part of contract 0.3.0 and are not implemented")
        self.wp = wp
        self.device = device or _device()
        self.params = params
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.backend = {"id": self.backend_id, "device": str(self.device), "warp": wp.__version__,
                        **({"requested": dict(backend)} if backend else {})}
        self.threads = threads
        self.timing = {}
        self.kf, self.kb = int(kf), int(kb)
        p = params
        self.h = 4.0 * p.particle_radius
        self.vol = p.particle_volume
        self.mass = p.density * self.vol
        # ---- boundaries: static first (SimulatorBase orders them that way) -------------------------------------
        self.boundaries = sorted(list(boundaries), key=lambda b: b.animated)
        samples, body_ids, self.boundary_particles = [], [], {}
        self.anim_names = []
        for bi, b in enumerate(self.boundaries):
            if b.extra.get("samples") is not None:
                s = np.asarray(b.extra["samples"], float)
            else:
                s = regular_triangle_sampling(b.vertices, b.faces, 1.5 * p.particle_radius)
            samples.append(s)
            body_ids.append(np.full(len(s), bi, np.int32))
            self.boundary_particles[b.name] = int(len(s))
            if b.animated:
                self.anim_names.append(b.name)
        self.n_static = int(sum(len(s) for s, b in zip(samples, self.boundaries) if not b.animated))
        xb0 = np.concatenate(samples).astype(np.float32)
        self.nb = int(len(xb0))
        self.xb0 = wp.array(xb0, dtype=wp.vec3, device=self.device)
        self.bbody = wp.array(np.concatenate(body_ids), dtype=int, device=self.device)
        self.xb = wp.zeros(self.nb, dtype=wp.vec3, device=self.device)
        self.velb = wp.zeros(self.nb, dtype=wp.vec3, device=self.device)
        self.vb = wp.zeros(self.nb, dtype=float, device=self.device)
        nbod = len(self.boundaries)
        self._bpos = np.zeros((nbod, 3), np.float32)
        self._brot = np.zeros((nbod, 3, 3), np.float32)
        self._bvel = np.zeros((nbod, 3), np.float32)
        self._bang = np.zeros((nbod, 3), np.float32)
        self.body_index = {b.name: i for i, b in enumerate(self.boundaries)}
        for b in self.boundaries:
            self.set_pose(b.name, b.pos, quat_to_mat(b.quat))
        self.bpos = wp.array(self._bpos, dtype=wp.vec3, device=self.device)
        self.brot = wp.array(self._brot, dtype=wp.mat33, device=self.device)
        self.bvel = wp.array(self._bvel, dtype=wp.vec3, device=self.device)
        self.bang = wp.array(self._bang, dtype=wp.vec3, device=self.device)
        self.grid_s = wp.HashGrid(128, 128, 128, device=self.device)
        self.grid_d = wp.HashGrid(64, 64, 64, device=self.device)
        self.grid_f = wp.HashGrid(64, 64, 64, device=self.device)
        self._update_all_boundaries()
        self._boundary_volumes()
        # ---- fluid ------------------------------------------------------------------------------------------------
        self.n = int(len(particles))
        n = self.n
        self.x0 = particles.astype(np.float32).copy()
        self.x = wp.array(self.x0, dtype=wp.vec3, device=self.device)
        self.v = wp.zeros(n, dtype=wp.vec3, device=self.device)
        self.a = wp.zeros(n, dtype=wp.vec3, device=self.device)
        self.rho = wp.zeros(n, dtype=float, device=self.device)
        self.factor = wp.zeros(n, dtype=float, device=self.device)
        self.dadv = wp.zeros(n, dtype=float, device=self.device)
        self.p = wp.zeros(n, dtype=float, device=self.device)
        self.pv = wp.zeros(n, dtype=float, device=self.device)
        self.pacc = wp.zeros(n, dtype=wp.vec3, device=self.device)
        self.err = wp.zeros(n, dtype=float, device=self.device)
        self.pstate = wp.zeros(n, dtype=int, device=self.device)
        self.nn_f = wp.zeros((n, self.kf), dtype=int, device=self.device)
        self.cnt_f = wp.zeros(n, dtype=int, device=self.device)
        self.gw_f = wp.zeros((n, self.kf), dtype=wp.vec3, device=self.device)
        self.w_f = wp.zeros((n, self.kf), dtype=float, device=self.device)
        self.nn_b = wp.zeros((n, self.kb), dtype=int, device=self.device)
        self.cnt_b = wp.zeros(n, dtype=int, device=self.device)
        self.gw_b = wp.zeros((n, self.kb), dtype=wp.vec3, device=self.device)
        self.w_b = wp.zeros((n, self.kb), dtype=float, device=self.device)
        self.overflow = wp.zeros(1, dtype=int, device=self.device)
        self.flag = wp.zeros(1, dtype=int, device=self.device)
        self.vmax_dev = wp.zeros(1, dtype=float, device=self.device)
        self.grad_rho = wp.zeros(n, dtype=float, device=self.device)
        self.vdiff_st = wp.zeros(n, dtype=wp.vec3, device=self.device)
        self.vdiff_visc = wp.zeros(n, dtype=wp.vec3, device=self.device)
        self.inv_diag = wp.zeros(n, dtype=wp.mat33, device=self.device)
        self.cg = {k: wp.zeros(n, dtype=wp.vec3, device=self.device) for k in ("x", "r", "p", "z", "tmp", "b")}
        self.sc = {k: wp.zeros(1, dtype=float, device=self.device) for k in ("rhs2", "res2", "abs_new", "abs_old", "p_ap")}
        self._x_host = self.x0.copy()
        self._v_host = np.zeros((n, 3), np.float32)
        self._host_dirty = False  # host arrays may have been written by a caller
        self._dev_dirty = False  # device arrays changed since the last download
        self.absorbed_by = np.full(n, "", dtype=object)
        self.steps = 0
        self._t = 0.0
        self.substeps_log = []
        self.log_steps = False
        self.revision = 0
        self.iterations = (0, 0, 0, 0)  # pressure, divergence, surface tension CG, viscosity CG of the last substep
        self.fluid = _FieldShim(self)
        self.material = {"viscosity": p.viscosity, "surface_tension": p.surface_tension, "adhesion": p.adhesion,
                         "max_error": p.max_error}
        self.timing = {"substeps": 0, "launch_s": 0.0}
        _LIVE = self
        self.sim = None  # no native singleton
        self.rbos = {}

    # ---- boundaries -----------------------------------------------------------------------------------------------
    def _initial_poses(self, t=0.0):
        return {b.name: (np.asarray(b.pos, float), quat_to_mat(b.quat), np.zeros(3), np.zeros(3))
                for b in self.boundaries if b.animated}

    def set_pose(self, name, pos, R, v=(0, 0, 0), w=(0, 0, 0)):
        i = self.body_index[name]
        self._bpos[i] = np.asarray(pos, np.float32)
        self._brot[i] = np.asarray(R, np.float32)
        self._bvel[i] = np.asarray(v, np.float32)
        self._bang[i] = np.asarray(w, np.float32)

    def _upload_poses(self):
        wp = self.wp
        wp.copy(self.bpos, wp.array(self._bpos, dtype=wp.vec3, device=self.device))
        wp.copy(self.brot, wp.array(self._brot, dtype=wp.mat33, device=self.device))
        wp.copy(self.bvel, wp.array(self._bvel, dtype=wp.vec3, device=self.device))
        wp.copy(self.bang, wp.array(self._bang, dtype=wp.vec3, device=self.device))

    def _update_all_boundaries(self):
        """Static and animated samples to their poses; build the static grid once."""
        wp = self.wp
        self._upload_poses()
        wp.launch(K.boundary_update, dim=self.nb, inputs=[self.xb0, self.bbody, self.bpos, self.brot, self.bvel,
                                                           self.bang, 0, self.xb, self.velb], device=self.device)
        if self.n_static:
            self.grid_s.build(self.xb[: self.n_static], self.h)
        self._update_boundaries(True)

    def _update_boundaries(self, force=False):
        wp = self.wp
        nd = self.nb - self.n_static
        if nd == 0:
            return
        self._upload_poses()
        wp.launch(K.boundary_update, dim=nd, inputs=[self.xb0, self.bbody, self.bpos, self.brot, self.bvel, self.bang,
                                                      self.n_static, self.xb, self.velb], device=self.device)
        self.grid_d.build(self.xb[self.n_static:], self.h)

    def _boundary_volumes(self):
        """Akinci volumes: static bodies together, each animated body on its own (Simulation::updateBoundaryVolume)."""
        wp = self.wp
        if self.n_static:
            wp.launch(K.boundary_volume, dim=self.n_static, inputs=[self.grid_s.id, self.xb[: self.n_static], self.h,
                                                                    self.vb[: self.n_static]], device=self.device)
        off = self.n_static
        for b in self.boundaries:
            if not b.animated:
                continue
            m = self.boundary_particles[b.name]
            sub = self.xb[off:off + m]
            g = wp.HashGrid(64, 64, 64, device=self.device)
            g.build(sub, self.h)
            wp.launch(K.boundary_volume, dim=m, inputs=[g.id, sub, self.h, self.vb[off:off + m]], device=self.device)
            off += m

    # ---- host/device mirrors ----------------------------------------------------------------------------------------
    def _download(self):
        if self._dev_dirty:
            self._x_host[:] = self.x.numpy()
            self._v_host[:] = self.v.numpy()
            self._dev_dirty = False

    def _upload(self):
        if self._host_dirty:
            wp = self.wp
            wp.copy(self.x, wp.array(self._x_host, dtype=wp.vec3, device=self.device))
            wp.copy(self.v, wp.array(self._v_host, dtype=wp.vec3, device=self.device))
            self._host_dirty = False

    def positions(self) -> np.ndarray:
        """(N, 3) float32 host mirror; writes are uploaded before the next step."""
        self._download()
        self._host_dirty = True
        return self._x_host

    def velocities(self) -> np.ndarray:
        self._download()
        self._host_dirty = True
        return self._v_host

    @property
    def free_mask(self):
        return self.absorbed_by == ""

    @property
    def time(self) -> float:
        return self._t

    def volume_m3(self) -> float:
        return self.n * self.params.particle_volume

    def state(self) -> dict:
        return {"time": self.time, "x": self.positions().copy(), "v": self.velocities().copy(), "steps": self.steps,
                "absorbed_by": self.absorbed_by.copy()}


    def initial_state(self) -> np.ndarray:
        return self.x0.copy()

    def absorb(self, indices, owner):
        if self.params.z_sort:
            raise ValueError("absorption requires z_sort=False for stable particle identities")
        ids = np.asarray(indices, int)
        if not owner or np.any(~self.free_mask[ids]):
            raise ValueError("absorption requires a named owner and free particles")
        self.absorbed_by[ids] = owner
        side = int(np.ceil(self.n ** (1 / 3))) + 1
        ijk = np.column_stack((ids % side, ids // side % side, ids // side ** 2))
        self.positions()[ids] = ijk * (16 * self.params.particle_radius) + [0, 0, -10]
        self.velocities()[ids] = 0
        st = self.pstate.numpy()
        st[ids] = 1
        self.wp.copy(self.pstate, self.wp.array(st, dtype=int, device=self.device))
        self.revision += 1

    # ---- reset / settle ---------------------------------------------------------------------------------------------
    def reset(self):
        wp = self.wp
        for name, (pos, R, v, w) in self._initial_poses().items():
            self.set_pose(name, pos, R, v, w)
        self._update_boundaries(True)
        self._x_host[:] = self.x0
        self._v_host[:] = 0.0
        self._host_dirty, self._dev_dirty = True, False
        self._upload()
        for arr in (self.p, self.pv, self.grad_rho):
            arr.zero_()
        for arr in (self.vdiff_st, self.vdiff_visc, self.a):
            arr.zero_()
        self.pstate.zero_()
        self._t = 0.0
        self.steps = 0
        self.substeps_log = []
        self.absorbed_by[:] = ""
        self.revision += 1

    def settle(self, seconds: float = 0.3, damping: float = 0.9, pose_at=None, log=None) -> dict:
        n0 = 0
        while seconds - self.time > 1e-6:
            n0 += self.advance(min(seconds, self.time + self.params.dt_max), pose_at)
            self.wp.launch(K.scale_vec, dim=self.n, inputs=[self.v, float(damping)], device=self.device)
            self._dev_dirty = True
            if log is not None:
                log(self)
        v = self.velocities()
        ke = float(0.5 * np.mean(np.einsum("ij,ij->i", v, v)))
        self.x0 = self.positions().copy()
        self.reset()
        return {"steps": n0, "mean_ke_per_kg": ke}

    # ---- stepping ---------------------------------------------------------------------------------------------------
    def _vmax(self) -> float:
        wp = self.wp
        self.vmax_dev.zero_()
        wp.launch(K.vmax2, dim=self.n, inputs=[self.v, self.vmax_dev], device=self.device)
        return float(math.sqrt(max(0.0, float(self.vmax_dev.numpy()[0]))))

    def _cfl_dt(self) -> float:
        vmax = self._vmax()
        p = self.params
        dt = p.dt_max if vmax < 1e-9 else p.cfl * p.spacing / vmax
        return min(p.dt_max, max(p.dt_min, dt))

    def advance(self, t1: float, pose_at=None):
        n0 = self.steps
        self._upload()
        while t1 - self._t > 1e-6:
            dt = min(self._cfl_dt(), self.params.dt_max)
            rem = t1 - self._t
            if rem <= dt * 1.0001 + 1e-6:
                dt = rem
            elif rem < 2 * dt:
                dt = rem / 2
            if pose_at is not None:
                for name, (pos, R, v, w) in pose_at(self.time).items():
                    self.set_pose(name, pos, R, v, w)
                self._update_boundaries()
            c0 = time.perf_counter()
            it = self._substep(float(dt))
            self.timing["launch_s"] += time.perf_counter() - c0
            self.timing["substeps"] += 1
            self._dev_dirty = True
            self._t += dt
            self.steps += 1
            self.iterations = it
            if self.log_steps:
                self.substeps_log.append((self.time, dt, it[0], it[1]))
        self.flag.zero_()
        self.wp.launch(K.nonfinite, dim=self.n, inputs=[self.x, self.v, self.flag], device=self.device)
        bad, over = int(self.flag.numpy()[0]), int(self.overflow.numpy()[0])
        if bad:
            raise FloatingPointError(f"SPH diverged at {self._t:.6f} s")
        if over:
            raise RuntimeError(f"neighbour list capacity exceeded (kf={self.kf}, kb={self.kb})")
        return self.steps - n0

    def sleep_until(self, t1, pose_at=None):
        if t1 < self._t:
            raise ValueError("liquid time cannot run backwards")
        if pose_at:
            for name, (pos, R, v, w) in pose_at(t1).items():
                self.set_pose(name, pos, R, v, w)
            self._update_boundaries()
        self._t = float(t1)
        self.velocities()[:] = 0

    # ---- one DFSPH step (TimeStepDFSPH::step) -----------------------------------------------------------------------
    def _substep(self, dt: float):
        wp, p, n, dev = self.wp, self.params, self.n, self.device
        L = wp.launch
        prof = getattr(self, "profile", None)  # {phase: seconds}; synchronises after each phase when set

        def mark(name, t0):
            if prof is not None:
                wp.synchronize_device(dev)
                t = time.perf_counter()
                prof[name] = prof.get(name, 0.0) + t - t0
                return t
            return t0

        t0 = time.perf_counter()
        self.grid_f.build(self.x, self.h)
        has_d = 1 if self.nb > self.n_static else 0
        L(K.build_neighbours, dim=n, inputs=[self.grid_f.id, self.grid_s.id, self.grid_d.id, self.x, self.xb,
                                             self.n_static, has_d, self.h, self.nn_f, self.cnt_f, self.gw_f, self.w_f,
                                             self.nn_b, self.cnt_b, self.gw_b, self.w_b, self.overflow], device=dev)
        t0 = mark("neighbours", t0)
        L(K.density, dim=n, inputs=[self.cnt_f, self.w_f, self.nn_b, self.cnt_b, self.w_b, self.vb, self.vol,
                                    p.density, self.h, self.rho], device=dev)
        L(K.dfsph_factor, dim=n, inputs=[self.cnt_f, self.gw_f, self.nn_b, self.cnt_b, self.gw_b, self.vb, self.vol,
                                         1e-5, self.factor], device=dev)
        t0 = mark("density_factor", t0)
        it_v = self._pressure_solve(dt, mode=1)
        t0 = mark("divergence", t0)
        g = wp.vec3(*[float(c) for c in p.gravity])
        L(K.clear_accel, dim=n, inputs=[self.a, self.pstate, g], device=dev)
        it_st = self._surface_tension(dt) if p.surface_tension else 0
        t0 = mark("surface_tension", t0)
        it_vi = self._viscosity(dt)
        t0 = mark("viscosity", t0)
        L(K.add_scaled_active, dim=n, inputs=[self.v, self.a, dt, self.pstate], device=dev)
        it_p = self._pressure_solve(dt, mode=0)
        t0 = mark("pressure", t0)
        L(K.add_scaled_active, dim=n, inputs=[self.x, self.v, dt, self.pstate], device=dev)
        mark("integrate", t0)
        return it_p, it_v, it_st, it_vi

    def _pressure_solve(self, dt: float, mode: int) -> int:
        """mode 0: constant density solve on `p` (min 2 iterations); mode 1: divergence-free solve on `pv` (min 1)."""
        wp, p, n, dev = self.wp, self.params, self.n, self.device
        L = wp.launch
        pr = self.p if mode == 0 else self.pv
        common = [self.nn_f, self.cnt_f, self.gw_f, self.nn_b, self.cnt_b, self.gw_b, self.vb, self.vol]
        L(K.density_adv, dim=n, inputs=[self.v, self.nn_f, self.cnt_f, self.gw_f, self.nn_b, self.cnt_b, self.gw_b,
                                        self.vb, self.velb, self.vol, self.rho, p.density, dt, mode, self.factor, pr,
                                        self.dadv], device=dev)
        rho0 = p.density
        if mode == 0:
            eta, min_it, max_it, dt_pow = p.max_error * 0.01 * rho0, 2, p.max_iterations, dt * dt
        else:
            eta, min_it, max_it, dt_pow = (1.0 / dt) * p.max_error_v * 0.01 * rho0, 1, p.max_iterations, dt
        it = 0
        chk = False
        while (not chk or it < min_it) and it < max_it:
            L(K.pressure_accel, dim=n, inputs=[pr, self.pstate, *common, 1e-5, self.pacc], device=dev)
            L(K.pressure_iter, dim=n, inputs=[self.pacc, self.dadv, self.factor, self.pstate, *common, dt_pow, mode,
                                              rho0, pr, self.err], device=dev)
            avg = float(wp.utils.array_sum(self.err)) / n
            chk = avg <= eta
            it += 1
        L(K.pressure_accel, dim=n, inputs=[pr, self.pstate, *common, 1e-5, self.pacc], device=dev)
        L(K.add_scaled, dim=n, inputs=[self.v, self.pacc, dt], device=dev)
        if mode == 0:
            L(K.scale, dim=n, inputs=[pr, dt * dt], device=dev)
        else:
            L(K.scale, dim=n, inputs=[self.factor, dt], device=dev)
            L(K.scale, dim=n, inputs=[pr, dt], device=dev)
        return it

    def _cg(self, matvec, precond, b, x, tol: float, max_iters: int) -> int:
        """Eigen::ConjugateGradient::solveWithGuess on vec3 unknowns; scalars stay on the device except the test."""
        wp, n, dev, sc, c = self.wp, self.n, self.device, self.sc, self.cg
        L = wp.launch
        wp.utils.array_inner(b, b, out=sc["rhs2"])
        rhs2 = float(sc["rhs2"].numpy()[0])
        if rhs2 == 0.0:
            x.zero_()
            return 0
        threshold = max(tol * tol * rhs2, np.finfo(np.float32).tiny)
        matvec(x, c["tmp"])
        L(K.cg_residual, dim=n, inputs=[b, c["tmp"], c["r"]], device=dev)
        wp.utils.array_inner(c["r"], c["r"], out=sc["res2"])
        if float(sc["res2"].numpy()[0]) < threshold:
            return 0
        precond(c["r"], c["p"])
        wp.utils.array_inner(c["r"], c["p"], out=sc["abs_new"])
        i = 0
        while i < max_iters:
            matvec(c["p"], c["tmp"])
            wp.utils.array_inner(c["p"], c["tmp"], out=sc["p_ap"])
            L(K.cg_update_xr, dim=n, inputs=[x, c["r"], c["p"], c["tmp"], sc["abs_new"], sc["p_ap"]], device=dev)
            wp.utils.array_inner(c["r"], c["r"], out=sc["res2"])
            if float(sc["res2"].numpy()[0]) < threshold:
                break
            precond(c["r"], c["z"])
            wp.copy(sc["abs_old"], sc["abs_new"])
            wp.utils.array_inner(c["r"], c["z"], out=sc["abs_new"])
            L(K.cg_update_p, dim=n, inputs=[c["p"], c["z"], sc["abs_new"], sc["abs_old"]], device=dev)
            i += 1
        return i

    def _surface_tension(self, dt: float) -> int:
        wp, p, n, dev, c = self.wp, self.params, self.n, self.device, self.cg
        L = wp.launch
        w_min = float(K.cubic_w_py(p.spacing, self.h))
        diam2 = p.spacing * p.spacing
        coh = float(p.surface_tension)
        L(K.st_grad_rho, dim=n, inputs=[self.v, self.nn_f, self.cnt_f, self.gw_f, self.mass, self.grad_rho], device=dev)
        L(K.st_rhs, dim=n, inputs=[self.x, self.v, self.rho, self.grad_rho, self.nn_f, self.cnt_f, self.w_f, self.gw_f,
                                   self.vdiff_st, dt, coh, w_min, diam2, c["b"], c["x"]], device=dev)

        def matvec(vec, out):
            L(K.st_matvec, dim=n, inputs=[vec, self.x, self.v, self.rho, self.grad_rho, self.nn_f, self.cnt_f, self.w_f,
                                          self.gw_f, dt, coh, w_min, diam2, out], device=dev)

        def precond(r, z):
            L(K.cg_precond_identity, dim=n, inputs=[r, z], device=dev)

        it = self._cg(matvec, precond, c["b"], c["x"], 0.001, 100)
        L(K.apply_vdiff, dim=n, inputs=[self.a, c["x"], self.v, dt, self.vdiff_st], device=dev)
        return it

    def _viscosity(self, dt: float) -> int:
        wp, p, n, dev, c = self.wp, self.params, self.n, self.device, self.cg
        L = wp.launch
        d_mu = 10.0 * p.viscosity * p.density
        d_mub = 10.0 * p.viscosity_boundary * p.density
        h2_001 = 0.01 * self.h * self.h
        L(K.visc_diag, dim=n, inputs=[self.x, self.rho, self.nn_f, self.cnt_f, self.gw_f, self.nn_b, self.cnt_b,
                                      self.gw_b, self.xb, self.vb, self.mass, dt, d_mu, d_mub, h2_001, p.density,
                                      self.inv_diag], device=dev)
        L(K.visc_rhs, dim=n, inputs=[self.x, self.v, self.rho, self.nn_b, self.cnt_b, self.gw_b, self.xb, self.velb,
                                     self.vb, self.vdiff_visc, dt, d_mub, h2_001, p.density, c["b"], c["x"]], device=dev)

        def matvec(vec, out):
            L(K.visc_matvec, dim=n, inputs=[vec, self.x, self.rho, self.nn_f, self.cnt_f, self.gw_f, self.nn_b,
                                            self.cnt_b, self.gw_b, self.xb, self.vb, self.mass, dt, d_mu, d_mub, h2_001,
                                            p.density, out], device=dev)

        def precond(r, z):
            L(K.cg_precond_block, dim=n, inputs=[self.inv_diag, r, z], device=dev)

        it = self._cg(matvec, precond, c["b"], c["x"], 0.01, 100)
        L(K.apply_vdiff, dim=n, inputs=[self.a, c["x"], self.v, dt, self.vdiff_visc], device=dev)
        return it

    # ---- misc ---------------------------------------------------------------------------------------------------------
    def density(self) -> np.ndarray:
        return self.rho.numpy()

    def memory_bytes(self) -> int:
        total = 0
        for v in self.__dict__.values():
            if hasattr(v, "capacity") and hasattr(v, "device"):
                total += int(v.capacity)
        return total

    def close(self):
        global _LIVE
        _LIVE = None


def cubic_w_py(r: float, h: float) -> float:
    k = 8.0 / (math.pi * h ** 3)
    q = r / h
    if q > 1.0:
        return 0.0
    if q <= 0.5:
        return k * (6 * q ** 3 - 6 * q ** 2 + 1)
    return k * 2 * (1 - q) ** 3


K.cubic_w_py = cubic_w_py


def params_dict(p: FluidParams) -> dict:
    return cpu_solver.params_dict(p)
