"""`WarpFluid`: the household liquid's DFSPH integration on a CUDA GPU (NVIDIA Warp), liquid contract 1.2.0.

It has the interface and the validity semantics of the CPU `solver.Fluid` (contract 1.0.0/1.1.0): the same time-step
schedule (free speed, previous raw predicted speed, boundary surface speed, gravity term, capillary bound, dt_min
guard), the same host-side continuous contact against the static domain with the one-spacing accepted-displacement
bound, absorption at accepted substeps after validation, latched validity errors with `invalid-state.npz`, exact
reset, settling and sleeping. Only the native DFSPH step moves to the GPU: kernels.py and sampling.py are the adopted
RoboCasa liquid 0.5.0 Warp kernels (a re-implementation of SPlisHSPlasH 2.19.0's DFSPH with warm start, Akinci 2012
boundary samples at 1.5 r, Weiler 2018 implicit viscosity and Jeske 2023 surface tension; float32 state), copied
byte for byte; their sha256 are pinned in backends/<id>.json.

Host/device protocol: the particle state lives on the device; `positions()`/`velocities()` return host float32
mirrors downloaded on demand. A caller's writes to a mirror (continuous-contact resolution, damping, absorption,
reset) are uploaded before the next device step, so the device always integrates the resolved host state.

No fallback: without NVIDIA Warp at the pinned version or without a CUDA device the constructor raises (the episode is
an infrastructure error). Rigid MuJoCo and rendering stay on the CPU.

Known, documented differences from the CPU backend (the fixture gate in the liquid-gpu report bounds their effect):
the analytic cubic kernel everywhere; hash-grid neighbour order, so float32 sums round in another order; fixed
neighbour capacities (64 fluid, 128 boundary neighbours; exceeding them is a validity error, never a truncation).
"""

from __future__ import annotations

import hashlib
import importlib
import math
import time
from pathlib import Path

import numpy as np

from ..domain import LiquidValidityError
from ..solver import pin
from .sampling import regular_triangle_sampling

HERE = Path(__file__).resolve().parent
KF, KB = 64, 128  # neighbour capacities: fluid, boundary
REST_Z = -10.0  # as the CPU solver: absorbed particles are parked on a sparse lattice around this height

_LIVE = None
_CHECKED: dict = {}


def is_gpu(backend_id: str) -> bool:
    return pin(backend_id).get("device") == "cuda"


def check_backend(backend_id: str) -> dict:
    """The GPU backend's pin after checking that the kernel sources it names are the pinned ones (no Warp import, no
    device query: those happen when the fluid is built, where a missing GPU is an infrastructure error)."""
    pn = pin(backend_id)
    if pn.get("device") != "cuda":
        raise ValueError(f"liquid backend {backend_id} is not a GPU backend")
    for rel, sha in pn["sources"].items():
        p = HERE / rel
        if _CHECKED.get(rel) != sha:
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
                raise ValueError(f"liquid backend {backend_id}: {rel} differs from its pinned sha256")
            _CHECKED[rel] = sha
    return pn


def warp_device(backend_id: str):
    """(warp module, CUDA device) for the pinned backend, or RuntimeError: never a CPU fallback."""
    pn = check_backend(backend_id)
    try:
        wp = importlib.import_module("warp")
    except ImportError:
        raise RuntimeError(f"liquid backend {backend_id} needs NVIDIA Warp {pn['warp']} (not installed)") from None
    if wp.__version__ != pn["warp"]:
        raise RuntimeError(f"liquid backend {backend_id} needs NVIDIA Warp {pn['warp']}, found {wp.__version__}")
    wp.config.log_level = wp.LOG_WARNING  # no greeting or module-load lines on stdout
    wp.init()
    if not wp.is_cuda_available():
        raise RuntimeError(f"liquid backend {backend_id} needs a CUDA device; CPU fallback is refused")
    dev = wp.get_device("cuda:0")
    if not dev.is_cuda:
        raise RuntimeError(f"liquid backend {backend_id} needs a CUDA device; CPU fallback is refused")
    return wp, dev


class WarpFluid:
    """The validated SPH fluid on the GPU; the constructor's arguments are the CPU `solver.Fluid`'s."""

    def __init__(self, workdir, backend_id, threads, material, solver, boundaries, particles, domain):
        global _LIVE
        if _LIVE is not None:
            raise RuntimeError("one liquid per process; close the previous fluid first")
        particles = np.asarray(particles, float)
        if particles.ndim != 2 or particles.shape[1] != 3 or not len(particles) or not np.isfinite(particles).all():
            raise ValueError("the liquid needs a nonempty finite (N, 3) particle array")
        wp, dev = warp_device(backend_id)
        from . import kernels as K  # imports warp

        if material.tension_method not in ("none", "jeske2023") or material.adhesion:
            raise ValueError("the GPU liquid implements surface tension none or jeske2023 without adhesion")
        self.wp, self.K, self.device = wp, K, dev
        self.backend = {
            "id": backend_id,
            "device": "cuda",
            "gpu": dev.name,
            "warp": wp.__version__,
            "sources_sha256": dict(pin(backend_id)["sources"]),
        }
        self.mat, self.sol, self.domain = material, solver, domain
        self.spacing = material.spacing
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.threads = int(threads)  # host threads of the condition (the GPU solver uses no OpenMP)
        self.h = 4.0 * material.particle_radius
        self.vol = material.particle_volume
        self.mass = material.density * self.vol
        self.gravity = (0.0, 0.0, -9.81)
        self.timing = {"substeps": 0, "device_s": 0.0}
        try:
            self._build(boundaries, particles)
            _LIVE = self
            self.material_readback = {  # what the kernels are given (there is no native parameter store to read)
                "viscosity": material.viscosity,
                "boundary_viscosity": material.boundary_viscosity,
                "surface_tension": material.tension,
                "adhesion": 0.0,
                "max_error": solver.max_error,
            }
            self.boundary_radii = {
                b.name: float(np.linalg.norm(b.vertices, axis=1).max()) for b in self.boundaries if b.animated
            }
            self.absorbed_by = np.full(self.n, "", dtype=object)
            self.absorbers = []
            self.revision = 0
            self._clear_run_state()
            self.validate()
        except BaseException:
            self.close()
            raise

    # ---- construction ----------------------------------------------------------------------------------------------
    def _build(self, boundaries, particles):
        wp, K, dev, r = self.wp, self.K, self.device, self.mat.particle_radius
        self.boundaries = sorted(boundaries, key=lambda b: b.animated)  # static first, as the CPU solver
        samples, body_ids, self.boundary_particles = [], [], {}
        for bi, b in enumerate(self.boundaries):
            s = b.samples if b.samples is not None else regular_triangle_sampling(b.vertices, b.faces, 1.5 * r)
            s = np.asarray(s, float)
            samples.append(s)
            body_ids.append(np.full(len(s), bi, np.int32))
            self.boundary_particles[b.name] = int(len(s))
        self.n_static = int(sum(len(s) for s, b in zip(samples, self.boundaries, strict=True) if not b.animated))
        xb0 = np.concatenate(samples).astype(np.float32)
        self.nb = int(len(xb0))
        self.xb0 = wp.array(xb0, dtype=wp.vec3, device=dev)
        self.bbody = wp.array(np.concatenate(body_ids), dtype=int, device=dev)
        self.xb = wp.zeros(self.nb, dtype=wp.vec3, device=dev)
        self.velb = wp.zeros(self.nb, dtype=wp.vec3, device=dev)
        self.vb = wp.zeros(self.nb, dtype=float, device=dev)
        nbod = len(self.boundaries)
        self._bpos = np.zeros((nbod, 3), np.float32)
        self._brot = np.zeros((nbod, 3, 3), np.float32)
        self._bvel = np.zeros((nbod, 3), np.float32)
        self._bang = np.zeros((nbod, 3), np.float32)
        self.body_index = {b.name: i for i, b in enumerate(self.boundaries)}
        for b in self.boundaries:
            self.set_pose(b.name, b.pos, b.R, np.zeros(3), np.zeros(3))
        self.bpos = wp.array(self._bpos, dtype=wp.vec3, device=dev)
        self.brot = wp.array(self._brot, dtype=wp.mat33, device=dev)
        self.bvel = wp.array(self._bvel, dtype=wp.vec3, device=dev)
        self.bang = wp.array(self._bang, dtype=wp.vec3, device=dev)
        self.grid_s = wp.HashGrid(128, 128, 128, device=dev)
        self.grid_d = wp.HashGrid(64, 64, 64, device=dev)
        self.grid_f = wp.HashGrid(64, 64, 64, device=dev)
        self._upload_poses()
        wp.launch(
            K.boundary_update,
            dim=self.nb,
            inputs=[self.xb0, self.bbody, self.bpos, self.brot, self.bvel, self.bang, 0, self.xb, self.velb],
            device=dev,
        )
        if self.n_static:
            self.grid_s.build(self.xb[: self.n_static], self.h)
        self._update_boundaries()
        # Akinci volumes: static bodies together, each animated body on its own (Simulation::updateBoundaryVolume)
        if self.n_static:
            wp.launch(
                K.boundary_volume,
                dim=self.n_static,
                inputs=[self.grid_s.id, self.xb[: self.n_static], self.h, self.vb[: self.n_static]],
                device=dev,
            )
        off = self.n_static
        for b in self.boundaries:
            if not b.animated:
                continue
            m = self.boundary_particles[b.name]
            sub = self.xb[off : off + m]
            g = wp.HashGrid(64, 64, 64, device=dev)
            g.build(sub, self.h)
            wp.launch(K.boundary_volume, dim=m, inputs=[g.id, sub, self.h, self.vb[off : off + m]], device=dev)
            off += m

        self.n = n = int(len(particles))
        self.x0 = particles.astype(np.float32).astype(np.float64)
        self.x = wp.array(self.x0.astype(np.float32), dtype=wp.vec3, device=dev)
        self.v = wp.zeros(n, dtype=wp.vec3, device=dev)
        self.a = wp.zeros(n, dtype=wp.vec3, device=dev)
        self.rho = wp.zeros(n, dtype=float, device=dev)
        self.factor = wp.zeros(n, dtype=float, device=dev)
        self.dadv = wp.zeros(n, dtype=float, device=dev)
        self.p = wp.zeros(n, dtype=float, device=dev)
        self.pv = wp.zeros(n, dtype=float, device=dev)
        self.pacc = wp.zeros(n, dtype=wp.vec3, device=dev)
        self.err = wp.zeros(n, dtype=float, device=dev)
        self.pstate = wp.zeros(n, dtype=int, device=dev)
        self.nn_f = wp.zeros((n, KF), dtype=int, device=dev)
        self.cnt_f = wp.zeros(n, dtype=int, device=dev)
        self.gw_f = wp.zeros((n, KF), dtype=wp.vec3, device=dev)
        self.w_f = wp.zeros((n, KF), dtype=float, device=dev)
        self.nn_b = wp.zeros((n, KB), dtype=int, device=dev)
        self.cnt_b = wp.zeros(n, dtype=int, device=dev)
        self.gw_b = wp.zeros((n, KB), dtype=wp.vec3, device=dev)
        self.w_b = wp.zeros((n, KB), dtype=float, device=dev)
        self.overflow = wp.zeros(1, dtype=int, device=dev)
        self.grad_rho = wp.zeros(n, dtype=float, device=dev)
        self.vdiff_st = wp.zeros(n, dtype=wp.vec3, device=dev)
        self.vdiff_visc = wp.zeros(n, dtype=wp.vec3, device=dev)
        self.inv_diag = wp.zeros(n, dtype=wp.mat33, device=dev)
        self.cg = {k: wp.zeros(n, dtype=wp.vec3, device=dev) for k in ("x", "r", "p", "z", "tmp", "b")}
        self.sc = {k: wp.zeros(1, dtype=float, device=dev) for k in ("rhs2", "res2", "abs_new", "abs_old", "p_ap")}
        self._x_host = self.x0.astype(np.float32)
        self._v_host = np.zeros((n, 3), np.float32)
        self._host_dirty = False  # a host mirror may have been written: upload before the next device step
        self._dev_dirty = False  # the device state changed since the last download
        self._pstate_host = np.zeros(n, np.int32)

    # ---- host/device mirrors ---------------------------------------------------------------------------------------
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
        """(N, 3) float32 host mirror of the particle positions (world frame); writes reach the next device step."""
        self._download()
        self._host_dirty = True
        return self._x_host

    def velocities(self) -> np.ndarray:
        self._download()
        self._host_dirty = True
        return self._v_host

    @property
    def free_mask(self) -> np.ndarray:
        return self.absorbed_by == ""

    @property
    def time(self) -> float:
        return self._t

    def _set_pstate(self):
        self.wp.copy(self.pstate, self.wp.array(self._pstate_host, dtype=int, device=self.device))

    # ---- run state and validity (as solver.Fluid) ------------------------------------------------------------------
    def _clear_run_state(self):
        self._t = 0.0
        self.steps = 0
        self.invalid_reason = None
        self.minimum_dt = math.inf
        self.previous_predicted_speed = 0.0
        self.resolved_large_predictions = 0
        self.maximum_predicted_displacement = 0.0
        self.maximum_accepted_displacement = 0.0
        self.maximum_speed = 0.0
        self.iterations = {"density_max": 0, "divergence_max": 0, "density_sum": 0, "divergence_sum": 0}
        self.domain.contacts.clear()

    def fail(self, reason):
        self.invalid_reason = f"liquid invalid at {self.time:.9f} s: {reason}"
        try:
            np.savez_compressed(
                self.workdir / "invalid-state.npz",
                positions=self.positions(),
                velocities=self.velocities(),
                free_mask=self.free_mask,
                time_s=self.time,
            )
        except Exception:  # noqa: BLE001 - diagnostics must not mask the validity error
            pass
        raise LiquidValidityError(self.invalid_reason)

    def validate(self):
        if self.invalid_reason:
            raise LiquidValidityError(self.invalid_reason)
        x, v = self.positions(), self.velocities()
        if x.shape != (self.n, 3) or v.shape != (self.n, 3) or not np.isfinite(x).all() or not np.isfinite(v).all():
            self.fail("nonfinite or inconsistent particle state")
        free = self.free_mask
        if not free.any():
            return
        try:
            self.domain.validate(x[free])
        except LiquidValidityError as e:
            self.fail(str(e))
        speed = np.linalg.norm(v[free], axis=1)
        if speed.max() * self.sol.dt_min > self.sol.cfl * self.spacing:
            self.fail("particle speed requires a time step below dt_min")

    def reset(self, x0=None):
        """Back to the initial state (or a new one, `x0`, of the same size): boundaries to their initial poses, the
        device solver's warm starts cleared, positions and zero velocities, every particle free. Runs from reset()
        are bit-identical on the same device and build."""
        if x0 is not None:
            x0 = np.asarray(x0, float)
            if x0.shape != (self.n, 3) or not np.isfinite(x0).all():
                raise ValueError("a new initial state must have the fluid's shape")
            self.x0 = x0.astype(np.float32).astype(np.float64)
        for b in self.boundaries:
            if b.animated:
                self.set_pose(b.name, b.pos, b.R, np.zeros(3), np.zeros(3))
        self._update_boundaries()
        self._x_host[:] = self.x0
        self._v_host[:] = 0.0
        self._host_dirty, self._dev_dirty = True, False
        self._upload()
        for arr in (self.p, self.pv, self.grad_rho, self.vdiff_st, self.vdiff_visc, self.a, self.overflow):
            arr.zero_()
        self._pstate_host[:] = 0
        self._set_pstate()
        self.absorbed_by[:] = ""
        for a in self.absorbers:
            a.reset()
        self._clear_run_state()
        self.revision += 1
        self.validate()

    def set_initial_boundary_poses(self, poses: dict):
        for b in self.boundaries:
            if b.name in poses:
                b.pos = np.asarray(poses[b.name][0], float)
                b.R = np.asarray(poses[b.name][1], float)

    def settle(self, seconds: float, damping: float):
        """As solver.Fluid.settle: damp the resolved host velocities after each step, then take the result as x0."""
        while seconds - self.time > 1e-9:
            self.advance(min(seconds, self.time + self.sol.dt_max))
            self.velocities()[:] *= damping
        v = self.velocities()
        out = {
            "seconds": self.time,
            "steps": self.steps,
            "mean_ke_per_kg": float(0.5 * np.mean(np.einsum("ij,ij->i", v, v))),
            "minimum_dt_s": self.minimum_dt if math.isfinite(self.minimum_dt) else None,
        }
        self.reset(self.positions().astype(np.float64))
        return out

    # ---- absorption ---------------------------------------------------------------------------------------------------
    def absorb(self, indices, owner):
        """As solver.Fluid.absorb: an accounted reservoir far below the scene; the device stops integrating them."""
        ids = np.asarray(indices, int)
        if not owner or np.any(~self.free_mask[ids]):
            raise ValueError("absorption needs a named owner and free particles")
        self.absorbed_by[ids] = owner
        side = int(np.ceil(self.n ** (1 / 3))) + 1
        ijk = np.column_stack((ids % side, ids // side % side, ids // side**2))
        self.positions()[ids] = ijk * (16 * self.mat.particle_radius) + [0, 0, REST_Z]
        self.velocities()[ids] = 0
        self._pstate_host[ids] = 1
        self._set_pstate()
        self.revision += 1

    def _absorb_at(self, poses):
        for a in self.absorbers:
            pos, R = poses[a.name][:2]
            if not (np.isfinite(pos).all() and np.isfinite(R).all()):
                self.fail("nonfinite absorber pose")
            a.update(self, pos, R)

    # ---- boundaries ---------------------------------------------------------------------------------------------------
    def set_pose(self, name, pos, R, v, w):
        i = self.body_index[name]
        self._bpos[i] = np.asarray(pos, np.float32)
        self._brot[i] = np.asarray(R, np.float32).reshape(3, 3)
        self._bvel[i] = np.asarray(v, np.float32)
        self._bang[i] = np.asarray(w, np.float32)

    def _upload_poses(self):
        wp = self.wp
        wp.copy(self.bpos, wp.array(self._bpos, dtype=wp.vec3, device=self.device))
        wp.copy(self.brot, wp.array(self._brot, dtype=wp.mat33, device=self.device))
        wp.copy(self.bvel, wp.array(self._bvel, dtype=wp.vec3, device=self.device))
        wp.copy(self.bang, wp.array(self._bang, dtype=wp.vec3, device=self.device))

    def _update_boundaries(self):
        """Animated samples to their poses and velocities; the animated hash grid rebuilt."""
        wp = self.wp
        nd = self.nb - self.n_static
        if nd == 0:
            return
        self._upload_poses()
        wp.launch(
            self.K.boundary_update,
            dim=nd,
            inputs=[
                self.xb0,
                self.bbody,
                self.bpos,
                self.brot,
                self.bvel,
                self.bang,
                self.n_static,
                self.xb,
                self.velb,
            ],
            device=self.device,
        )
        self.grid_d.build(self.xb[self.n_static :], self.h)

    def _static_poses(self):
        return {b.name: (b.pos, b.R, np.zeros(3), np.zeros(3)) for b in self.boundaries if b.animated}

    # ---- stepping (solver.Fluid.advance with the native step on the device) -------------------------------------------
    def advance(self, t1: float, pose_at=None) -> int:
        """Step to fluid time t1. `pose_at(t)` -> {name: (pos, R, v, w)} of every animated boundary at time t."""
        if not np.isfinite(t1) or t1 < self.time - 1e-12:
            self.fail("invalid target time")
        self.validate()
        n0 = self.steps
        s, g = self.sol, 9.81
        while t1 - self._t > 1e-9:
            poses = pose_at(self.time) if pose_at else self._static_poses()
            wall = 0.0
            for name, (pos, R, v, w) in poses.items():
                if not all(np.isfinite(a).all() for a in (pos, R, v, w)):
                    self.fail("nonfinite boundary pose or velocity")
                wall = max(wall, float(np.linalg.norm(v) + self.boundary_radii[name] * np.linalg.norm(w)))
            free = self.free_mask
            speed = float(np.linalg.norm(self.velocities()[free], axis=1).max()) if free.any() else 0.0
            relative = max(speed, self.previous_predicted_speed) + wall + g * s.dt_max
            dt = min(s.dt_max, s.cfl * self.spacing / max(relative, 1e-12))
            if self.mat.tension:
                dt = min(dt, math.sqrt(self.mat.density * self.spacing**3 / (2 * math.pi * self.mat.tension)))
            if dt < s.dt_min:
                self.fail("relative boundary/particle speed requires a time step below dt_min")
            remaining = t1 - self.time
            if remaining <= dt:
                dt = remaining
            elif remaining < 2 * dt:
                dt = remaining / 2
            self.minimum_dt = min(self.minimum_dt, dt)
            for name, (pos, R, v, w) in poses.items():
                self.set_pose(name, pos, R, v, w)
            self._update_boundaries()
            old = self.positions().astype(np.float64)
            self._upload()
            c0 = time.perf_counter()
            it = self._substep(float(dt))
            self._dev_dirty = True
            x_new = self.positions()  # downloads (synchronises)
            self.timing["device_s"] += time.perf_counter() - c0
            self.timing["substeps"] += 1
            if int(self.overflow.numpy()[0]):
                self.fail("GPU neighbour list capacity exceeded")
            if not np.isfinite(x_new).all() or not np.isfinite(self.velocities()).all():
                self.fail("nonfinite native step")
            x, v = self._resolve_prediction(old, free)
            self.positions()[free] = x
            self.velocities()[free] = v
            self._t += dt
            self.steps += 1
            self.iterations["density_max"] = max(self.iterations["density_max"], int(it[0]))
            self.iterations["divergence_max"] = max(self.iterations["divergence_max"], int(it[1]))
            self.iterations["density_sum"] += int(it[0])
            self.iterations["divergence_sum"] += int(it[1])
            self.validate()  # before uptake: absorption must not hide an invalid incoming state
            if self.absorbers:
                self._absorb_at(pose_at(self.time) if pose_at else self._static_poses())
                self.validate()
        return self.steps - n0

    def _resolve_prediction(self, old, free):
        predicted = self.positions()[free].astype(np.float64)
        vel = self.velocities()[free].astype(np.float64)
        speeds = np.linalg.norm(vel, axis=1)
        raw = float(speeds.max()) if speeds.size else 0.0
        if raw * self.sol.dt_min > self.sol.cfl * self.spacing:
            self.fail("native predicted speed requires a time step below dt_min")
        disp = np.linalg.norm(predicted - old[free], axis=1)
        dmax = float(disp.max()) if disp.size else 0.0
        try:
            x, v = self.domain.resolve(old[free], predicted, vel)
        except LiquidValidityError as e:
            self.fail(str(e))
        accepted = np.linalg.norm(x - old[free], axis=1)
        amax = float(accepted.max()) if accepted.size else 0.0
        if amax > self.spacing:
            self.fail("an accepted step moved a free particle more than one spacing")
        self.maximum_predicted_displacement = max(self.maximum_predicted_displacement, dmax)
        self.maximum_accepted_displacement = max(self.maximum_accepted_displacement, amax)
        self.maximum_speed = max(self.maximum_speed, raw)
        if dmax > self.spacing:
            self.resolved_large_predictions += 1
        self.previous_predicted_speed = raw
        return x, v

    def sleep_until(self, t1, pose_at=None):
        """Advance only the clock of an explicitly frozen liquid (boundaries follow; velocities stay zero)."""
        self.validate()
        if not np.isfinite(t1) or t1 < self.time:
            self.fail("invalid sleep target time")
        if pose_at:
            for name, (pos, R, v, w) in pose_at(t1).items():
                if not all(np.isfinite(a).all() for a in (pos, R, v, w)):
                    self.fail("nonfinite sleeping boundary pose")
                self.set_pose(name, pos, R, v, w)
            self._update_boundaries()
        self._t = float(t1)
        self.velocities()[:] = 0
        self.validate()

    def validity(self) -> dict:
        return {
            "invalid_reason": self.invalid_reason,
            "static_contact_counts": dict(self.domain.contacts),
            "minimum_dt_s": self.minimum_dt if math.isfinite(self.minimum_dt) else None,
            "maximum_speed_m_s": self.maximum_speed,
            "maximum_predicted_displacement_m": self.maximum_predicted_displacement,
            "maximum_accepted_displacement_m": self.maximum_accepted_displacement,
            "resolved_large_predictions": self.resolved_large_predictions,
            "previous_predicted_speed_m_s": self.previous_predicted_speed,
            "solver_iterations": dict(self.iterations),
            "floor_geom": self.domain.floor.name,
        }

    def close(self):
        global _LIVE
        if _LIVE is self:
            _LIVE = None
        try:
            self.wp.synchronize_device(self.device)
        except Exception:  # noqa: BLE001 - closing must not raise over a device error already reported
            pass

    # ---- one DFSPH step (TimeStepDFSPH::step), as the adopted RoboCasa 0.5.0 GPU solver -------------------------------
    def _substep(self, dt: float):
        wp, K, n, dev, mat = self.wp, self.K, self.n, self.device, self.mat
        L = wp.launch
        self.grid_f.build(self.x, self.h)
        has_d = 1 if self.nb > self.n_static else 0
        L(
            K.build_neighbours,
            dim=n,
            inputs=[
                self.grid_f.id,
                self.grid_s.id,
                self.grid_d.id,
                self.x,
                self.xb,
                self.n_static,
                has_d,
                self.h,
                self.nn_f,
                self.cnt_f,
                self.gw_f,
                self.w_f,
                self.nn_b,
                self.cnt_b,
                self.gw_b,
                self.w_b,
                self.overflow,
            ],
            device=dev,
        )
        L(
            K.density,
            dim=n,
            inputs=[
                self.cnt_f,
                self.w_f,
                self.nn_b,
                self.cnt_b,
                self.w_b,
                self.vb,
                self.vol,
                mat.density,
                self.h,
                self.rho,
            ],
            device=dev,
        )
        L(
            K.dfsph_factor,
            dim=n,
            inputs=[self.cnt_f, self.gw_f, self.nn_b, self.cnt_b, self.gw_b, self.vb, self.vol, 1e-5, self.factor],
            device=dev,
        )
        it_v = self._pressure_solve(dt, mode=1)
        L(K.clear_accel, dim=n, inputs=[self.a, self.pstate, wp.vec3(*self.gravity)], device=dev)
        it_st = self._surface_tension(dt) if mat.tension else 0
        it_vi = self._viscosity(dt)
        L(K.add_scaled_active, dim=n, inputs=[self.v, self.a, dt, self.pstate], device=dev)
        it_p = self._pressure_solve(dt, mode=0)
        L(K.add_scaled_active, dim=n, inputs=[self.x, self.v, dt, self.pstate], device=dev)
        return it_p, it_v, it_st, it_vi

    def _pressure_solve(self, dt: float, mode: int) -> int:
        """mode 0: constant density solve on `p` (min 2 iterations); mode 1: divergence-free solve on `pv` (min 1)."""
        wp, K, n, dev, s = self.wp, self.K, self.n, self.device, self.sol
        L = wp.launch
        pr = self.p if mode == 0 else self.pv
        common = [self.nn_f, self.cnt_f, self.gw_f, self.nn_b, self.cnt_b, self.gw_b, self.vb, self.vol]
        L(
            K.density_adv,
            dim=n,
            inputs=[
                self.v,
                self.nn_f,
                self.cnt_f,
                self.gw_f,
                self.nn_b,
                self.cnt_b,
                self.gw_b,
                self.vb,
                self.velb,
                self.vol,
                self.rho,
                self.mat.density,
                dt,
                mode,
                self.factor,
                pr,
                self.dadv,
            ],
            device=dev,
        )
        rho0 = self.mat.density
        if mode == 0:
            eta, min_it, max_it, dt_pow = s.max_error * 0.01 * rho0, 2, s.max_iterations, dt * dt
        else:
            eta, min_it, max_it, dt_pow = (1.0 / dt) * s.max_error_v * 0.01 * rho0, 1, s.max_iterations, dt
        it = 0
        chk = False
        while (not chk or it < min_it) and it < max_it:
            L(K.pressure_accel, dim=n, inputs=[pr, self.pstate, *common, 1e-5, self.pacc], device=dev)
            L(
                K.pressure_iter,
                dim=n,
                inputs=[self.pacc, self.dadv, self.factor, self.pstate, *common, dt_pow, mode, rho0, pr, self.err],
                device=dev,
            )
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
        wp, K, n, dev, sc, c = self.wp, self.K, self.n, self.device, self.sc, self.cg
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
        wp, K, n, dev, c, mat = self.wp, self.K, self.n, self.device, self.cg, self.mat
        L = wp.launch
        w_min = float(cubic_w(mat.spacing, self.h))
        diam2 = mat.spacing * mat.spacing
        coh = float(mat.tension)
        L(K.st_grad_rho, dim=n, inputs=[self.v, self.nn_f, self.cnt_f, self.gw_f, self.mass, self.grad_rho], device=dev)
        L(
            K.st_rhs,
            dim=n,
            inputs=[
                self.x,
                self.v,
                self.rho,
                self.grad_rho,
                self.nn_f,
                self.cnt_f,
                self.w_f,
                self.gw_f,
                self.vdiff_st,
                dt,
                coh,
                w_min,
                diam2,
                c["b"],
                c["x"],
            ],
            device=dev,
        )

        def matvec(vec, out):
            L(
                K.st_matvec,
                dim=n,
                inputs=[
                    vec,
                    self.x,
                    self.v,
                    self.rho,
                    self.grad_rho,
                    self.nn_f,
                    self.cnt_f,
                    self.w_f,
                    self.gw_f,
                    dt,
                    coh,
                    w_min,
                    diam2,
                    out,
                ],
                device=dev,
            )

        def precond(r, z):
            L(K.cg_precond_identity, dim=n, inputs=[r, z], device=dev)

        it = self._cg(matvec, precond, c["b"], c["x"], 0.001, 100)
        L(K.apply_vdiff, dim=n, inputs=[self.a, c["x"], self.v, dt, self.vdiff_st], device=dev)
        return it

    def _viscosity(self, dt: float) -> int:
        wp, K, n, dev, c, mat = self.wp, self.K, self.n, self.device, self.cg, self.mat
        L = wp.launch
        d_mu = 10.0 * mat.viscosity * mat.density
        d_mub = 10.0 * mat.boundary_viscosity * mat.density
        h2_001 = 0.01 * self.h * self.h
        L(
            K.visc_diag,
            dim=n,
            inputs=[
                self.x,
                self.rho,
                self.nn_f,
                self.cnt_f,
                self.gw_f,
                self.nn_b,
                self.cnt_b,
                self.gw_b,
                self.xb,
                self.vb,
                self.mass,
                dt,
                d_mu,
                d_mub,
                h2_001,
                mat.density,
                self.inv_diag,
            ],
            device=dev,
        )
        L(
            K.visc_rhs,
            dim=n,
            inputs=[
                self.x,
                self.v,
                self.rho,
                self.nn_b,
                self.cnt_b,
                self.gw_b,
                self.xb,
                self.velb,
                self.vb,
                self.vdiff_visc,
                dt,
                d_mub,
                h2_001,
                mat.density,
                c["b"],
                c["x"],
            ],
            device=dev,
        )

        def matvec(vec, out):
            L(
                K.visc_matvec,
                dim=n,
                inputs=[
                    vec,
                    self.x,
                    self.rho,
                    self.nn_f,
                    self.cnt_f,
                    self.gw_f,
                    self.nn_b,
                    self.cnt_b,
                    self.gw_b,
                    self.xb,
                    self.vb,
                    self.mass,
                    dt,
                    d_mu,
                    d_mub,
                    h2_001,
                    mat.density,
                    out,
                ],
                device=dev,
            )

        def precond(r, z):
            L(K.cg_precond_block, dim=n, inputs=[self.inv_diag, r, z], device=dev)

        it = self._cg(matvec, precond, c["b"], c["x"], 0.01, 100)
        L(K.apply_vdiff, dim=n, inputs=[self.a, c["x"], self.v, dt, self.vdiff_visc], device=dev)
        return it


def cubic_w(r: float, h: float) -> float:
    k = 8.0 / (math.pi * h**3)
    q = r / h
    if q > 1.0:
        return 0.0
    if q <= 0.5:
        return k * (6 * q**3 - 6 * q**2 + 1)
    return k * 2 * (1 - q) ** 3


def pin_sources() -> dict:
    """{relative source path: sha256} of the kernel sources (to write a backend pin)."""
    return {
        rel: hashlib.sha256((HERE / rel).read_bytes()).hexdigest() for rel in ("kernels.py", "sampling.py", "solver.py")
    }


__all__ = ["WarpFluid", "check_backend", "is_gpu", "pin_sources", "warp_device"]
