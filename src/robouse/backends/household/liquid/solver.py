"""A DFSPH liquid (SPlisHSPlasH, pinned native build) with kinematic rigid boundaries and validated integration: the
fluid half of the one-way MuJoCo coupling (household liquid contract 1.0.0, CPU).

One fluid per process: SPlisHSPlasH keeps its simulation in process-wide singletons. The fluid lives in MuJoCo's
world frame (metres, z up, gravity -z). Boundaries are closed triangle meshes in their body's frame; an animated
boundary is moved before every SPH step to the pose the caller gives, a static one stays where it was created. The
fluid never pushes back.

Contract 1.0.0 is the RoboCasa 0.4.3 CPU semantics collapsed into one class:
- time step: dt = min(dt_max, cfl * spacing / (max(free speed, previous raw predicted speed) + boundary speed +
  g * dt_max)) (and the capillary bound with surface tension); a dt below dt_min is a validity error;
- after each native step the raw prediction is checked (speed bound), resolved against the static domain by
  continuous contact, and the accepted displacement must stay within one spacing;
- absorbers take particles at accepted substeps, after validation, so absorption cannot hide an invalid state;
- every error latches (`LiquidValidityError`), saves `invalid-state.npz` in the work folder and stays until reset.
Native CFL control, z-sorting and density/volume-map boundaries are off; Akinci boundary sampling is used.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

from . import meshes
from .domain import LiquidValidityError

PINS = Path(__file__).resolve().parent / "backends"
ENV_BACKEND = "ROBOUSE_HOUSEHOLD_LIQUID_BACKEND"
REST_Z = -10.0  # absorbed particles are parked on a sparse lattice around this height, out of every scene

_SPH = None
_SPH_FILE: Path | None = None
_CHECKED: dict = {}
_LIVE = None


def pin(backend_id: str) -> dict:
    p = PINS / f"{backend_id}.json"
    if not p.is_file():
        raise ValueError(f"unknown liquid backend {backend_id!r}")
    return json.loads(p.read_text())


def backend_dir(backend_id: str) -> Path:
    env = os.environ.get(ENV_BACKEND, "").strip()
    if env:
        return Path(env)
    from .... import config

    return config.cache_dir() / "household" / "liquid" / backend_id


def check_backend(backend_id: str) -> Path:
    """The pinned native module's path after its ABI and sha256 checks (cached per file state); raises otherwise."""
    pn = pin(backend_id)
    abi = f"cp{sys.version_info.major}{sys.version_info.minor}"
    if pn["python_abi"] != abi:
        raise RuntimeError(f"the liquid backend {backend_id} needs Python {pn['python_abi']}, this is {abi}")
    path = (backend_dir(backend_id) / pn["file"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"liquid backend {backend_id} not found (set {ENV_BACKEND} to its folder)")
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if _CHECKED.get(key) != pn["sha256"]:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != pn["sha256"]:
            raise ValueError(f"liquid backend {backend_id} differs from its pinned sha256")
        _CHECKED[key] = pn["sha256"]
    return path


def sph(backend_id: str | None = None):
    """Import the pinned pysplishsplash (once per process). Its build may bundle a libGLdispatch that crashes the
    system libGLX at import; loading the system libGLdispatch first, globally, makes both bind to it."""
    global _SPH, _SPH_FILE
    if backend_id is None:
        if _SPH is None:
            raise RuntimeError("the liquid backend is not loaded")
        return _SPH
    path = check_backend(backend_id)
    if _SPH is not None:
        if path != _SPH_FILE:
            raise RuntimeError("changing the liquid backend needs a fresh process")
        return _SPH
    if "pysplishsplash" in sys.modules:
        raise RuntimeError("another pysplishsplash is already imported in this process")
    try:
        ctypes.CDLL("libGLdispatch.so.0", mode=ctypes.RTLD_GLOBAL)
    except OSError:
        pass
    spec = importlib.util.spec_from_file_location("pysplishsplash", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["pysplishsplash"] = module
    _SPH, _SPH_FILE = module, path
    return _SPH


def set_threads(n: int) -> int:
    """Set the OpenMP thread count of the runtime SPlisHSPlasH links (OMP_NUM_THREADS is read only once, when the
    first OpenMP runtime starts). Returns the count the runtime reports."""
    libs = set()
    with open("/proc/self/maps") as fh:
        for line in fh:
            if "/libgomp" in line:
                libs.add(line.split()[-1])
    if not libs:
        raise RuntimeError("no OpenMP runtime is loaded")
    got = set()
    for lib in sorted(libs):
        gomp = ctypes.CDLL(lib)
        gomp.omp_set_num_threads(int(n))
        got.add(int(gomp.omp_get_max_threads()))
    if got != {int(n)}:
        raise RuntimeError(f"OpenMP reports {sorted(got)} threads, {n} were requested")
    return int(n)


def quat_to_mat(q):
    w, x, y, z = map(float, q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def mat_to_axis_angle(R):
    R = np.asarray(R, float)
    c = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    ang = float(np.arccos(c))
    if ang < 1e-12:
        return [1.0, 0.0, 0.0], 0.0
    w = rotvec(R)
    return list(w / np.linalg.norm(w)), ang


def rotvec(R) -> np.ndarray:
    """Axis * angle of a rotation matrix."""
    R = np.asarray(R, float)
    c = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    ang = float(np.arccos(c))
    if ang < 1e-9:
        return np.zeros(3)
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    s = np.linalg.norm(v)
    if s < 1e-9:  # ~pi: the axis from the symmetric part
        _, U = np.linalg.eigh((R + np.eye(3)) / 2.0)
        return U[:, -1] * ang
    return v / s * ang


def rotmat(w) -> np.ndarray:
    w = np.asarray(w, float)
    a = float(np.linalg.norm(w))
    if a < 1e-12:
        return np.eye(3)
    k = w / a
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


class BoundaryMesh:
    def __init__(self, name, vertices, faces, pos, R, animated, samples=None):
        self.name = name
        self.vertices = np.asarray(vertices, float)
        self.faces = np.asarray(faces, np.int64)
        self.pos = np.asarray(pos, float)
        self.R = np.asarray(R, float).reshape(3, 3)
        self.animated = bool(animated)
        self.samples = samples  # custom Akinci samples in the body frame (the work surface's top face)


class Fluid:
    """The validated SPH fluid. `material`, `solver` from config.LiquidConfig; `domain` a domain.StaticDomain."""

    def __init__(self, workdir, backend_id, threads, material, solver, boundaries, particles, domain):
        global _LIVE
        if _LIVE is not None:
            raise RuntimeError("SPlisHSPlasH holds one simulation per process; close the previous fluid first")
        particles = np.asarray(particles, float)
        if particles.ndim != 2 or particles.shape[1] != 3 or not len(particles) or not np.isfinite(particles).all():
            raise ValueError("the liquid needs a nonempty finite (N, 3) particle array")
        S = sph(backend_id)
        self.backend = {"id": backend_id, "sha256": pin(backend_id)["sha256"]}
        self.mat, self.sol, self.domain = material, solver, domain
        self.spacing = material.spacing
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.threads = set_threads(int(threads))
        self.boundaries = sorted(boundaries, key=lambda b: b.animated)  # static first, as SimulatorBase orders them
        rigid = []
        for b in self.boundaries:
            obj = meshes.write_obj(self.workdir / f"b{len(rigid)}.obj", b.vertices, b.faces)
            axis, angle = mat_to_axis_angle(b.R)
            samples = {}
            if b.samples is not None:
                meshes.write_bgeo(self.workdir / f"b{len(rigid)}_samples.bgeo", b.samples)
                samples = {"particleFile": f"b{len(rigid)}_samples.bgeo"}
            rigid.append(
                {
                    **samples,
                    "geometryFile": obj.name,
                    "translation": [float(v) for v in b.pos],
                    "rotationAxis": axis,
                    "rotationAngle": angle,
                    "scale": [1, 1, 1],
                    "isDynamic": False,
                    "isWall": False,
                    "isAnimated": b.animated,
                    "samplingMode": 1,
                    "mapResolution": [40, 40, 40],
                    "color": [0.5, 0.5, 0.5, 1.0],
                }
            )
        self.n = int(len(particles))
        meshes.write_bgeo(self.workdir / "fluid.bgeo", particles)
        m, s = material, solver
        tension_on = m.tension_method != "none"
        from .config import TENSION_METHODS

        self.tension_id = TENSION_METHODS[m.tension_method]
        scene = {
            "Configuration": {
                "particleRadius": m.particle_radius,
                "numberOfStepsPerRenderUpdate": 1,
                "density0": m.density,
                "simulationMethod": 4,
                "gravitation": [0.0, 0.0, -9.81],
                "cflMethod": 0,
                "timeStepSize": s.dt_max,
                "cflFactor": s.cfl,
                "cflMinTimeStepSize": s.dt_min,
                "cflMaxTimeStepSize": s.dt_max,
                "maxIterations": s.max_iterations,
                "maxError": s.max_error,
                "maxIterationsV": s.max_iterations,
                "maxErrorV": s.max_error_v,
                "enableDivergenceSolver": True,
                "boundaryHandlingMethod": 0,
                "enableZSort": False,
                "stopAt": -1,
                "enablePartioExport": False,
                "enableVTKExport": False,
                "enableRigidBodyExport": False,
                "enableStateExport": False,
                "dataExportFPS": 25,
            },
            "Materials": [
                {
                    "id": "Fluid",
                    "density0": m.density,
                    "viscosityMethod": 6,
                    "viscosity": m.viscosity,
                    "viscosityBoundary": m.boundary_viscosity,
                    "viscoMaxIter": 100,
                    "viscoMaxError": 0.01,
                    "surfaceTensionMethod": self.tension_id if tension_on else 0,
                    "surfaceTension": m.tension,
                    "surfaceTensionBoundary": m.adhesion,
                    "xsph": 0.0,
                    "xsphBoundary": 0.0,
                }
            ],
            "RigidBodies": rigid,
            "FluidModels": [
                {"particleFile": "fluid.bgeo", "id": "Fluid", "translation": [0, 0, 0], "scale": [1, 1, 1]}
            ],
        }
        (self.workdir / "scene.json").write_text(json.dumps(scene, indent=1))
        self.base = S.Exec.SimulatorBase()
        self.base.init(
            sceneFile=str(self.workdir / "scene.json"),
            useGui=False,
            outputDir=str(self.workdir / "out"),
            useCache=False,
            initialPause=False,
            stopAt=-1.0,
        )
        self.base.initSimulation()
        _LIVE = self
        try:
            self.sim = S.Simulation.getCurrent()
            self.tm = S.TimeManager.getCurrent()
            self.fluid = self.sim.getFluidModel(0)
            # Boundary data (Akinci samples, volumes) is built in SimulatorBase::deferredInit, reached from Python only
            # through runSimulation(): one tiny step, then reset.
            self.tm.setTimeStepSize(1e-7)
            self.base.setValueFloat(self.base.STOP_AT, 5e-8)
            self.base.runSimulation()
            self.base.setValueFloat(self.base.STOP_AT, -1.0)
            self._set_material()
            self.base.reset()
            if self.fluid.numActiveParticles() != self.n:
                raise RuntimeError(f"SPlisHSPlasH loaded {self.fluid.numActiveParticles()} of {self.n} particles")
            self.rbos = {}
            for i, b in enumerate(self.boundaries):
                rbo = self.sim.getBoundaryModel(i).getRigidBodyObject()
                got = np.array(rbo.getPosition(), float).ravel()
                if not np.allclose(got, b.pos, atol=1e-5) or bool(rbo.isAnimated()) != b.animated:
                    raise RuntimeError(f"boundary order mismatch at {i} ({b.name})")
                self.rbos[b.name] = rbo
            self.boundary_radii = {
                b.name: float(np.linalg.norm(b.vertices, axis=1).max()) for b in self.boundaries if b.animated
            }
            self.x0 = self.positions().astype(np.float64)
            if not np.allclose(self.x0, particles, atol=1e-5):
                raise RuntimeError("SPlisHSPlasH read different initial particle positions than were written")
            self.absorbed_by = np.full(self.n, "", dtype=object)
            self.absorbers = []  # contact.Absorber, uptake at accepted substeps
            self.revision = 0
            self._clear_run_state()
            self.validate()
        except BaseException:
            self.close()  # a failed construction must not keep the process's one simulation
            raise

    # ---- native material -------------------------------------------------------------------------------------------
    def _set_material(self):
        """Without the GUI SPlisHSPlasH does not read a material's non-pressure coefficients from the scene file:
        set every coefficient here and read them back."""
        S, m, s, fm = sph(), self.mat, self.sol, self.fluid
        fm.setValueInt(fm.VISCOSITY_METHOD, 6)
        visc = fm.getViscosityBase()
        visc.setValueFloat(S.Viscosity_Weiler2018.VISCOSITY_COEFFICIENT, m.viscosity)
        visc.setValueFloat(S.Viscosity_Weiler2018.VISCOSITY_COEFFICIENT_BOUNDARY, m.boundary_viscosity)
        visc.setValueUInt(S.Viscosity_Weiler2018.MAX_ITERATIONS, 100)
        visc.setValueFloat(S.Viscosity_Weiler2018.MAX_ERROR, 0.01)
        fm.setValueInt(fm.SURFACE_TENSION_METHOD, self.tension_id)
        st = fm.getSurfaceTensionBase()
        tension = adhesion = 0.0
        if self.tension_id:
            # parameter IDs belong to the instantiated class (another class's IDs are -1 in the bindings)
            cls = {
                1: S.SurfaceTension_Becker2007,
                2: S.SurfaceTension_Akinci2013,
                3: S.SurfaceTension_He2014,
                4: S.SurfaceTension_Jeske2023,
            }[self.tension_id]
            if st is None:
                raise RuntimeError("SPlisHSPlasH did not instantiate the surface tension model")
            st.setValueFloat(cls.SURFACE_TENSION, m.tension)
            st.setValueFloat(cls.SURFACE_TENSION_BOUNDARY, m.adhesion)
            tension = st.getValueFloat(cls.SURFACE_TENSION)
            adhesion = st.getValueFloat(cls.SURFACE_TENSION_BOUNDARY)
        xs = fm.getXSPH()
        if xs is not None:
            xs.setValueFloat(S.XSPH.FLUID_COEFFICIENT, 0.0)
            xs.setValueFloat(S.XSPH.BOUNDARY_COEFFICIENT, 0.0)
        ts = self.sim.getTimeStep()
        ts.setValueFloat(S.TimeStepDFSPH.MAX_ERROR, s.max_error)
        ts.setValueFloat(S.TimeStepDFSPH.MAX_ERROR_V, s.max_error_v)
        ts.setValueUInt(S.TimeStepDFSPH.MAX_ITERATIONS, s.max_iterations)
        ts.setValueUInt(S.TimeStepDFSPH.MAX_ITERATIONS_V, s.max_iterations)
        ts.setValueBool(S.TimeStepDFSPH.USE_DIVERGENCE_SOLVER, True)
        self.material_readback = {
            "viscosity": visc.getValueFloat(S.Viscosity_Weiler2018.VISCOSITY_COEFFICIENT),
            "boundary_viscosity": visc.getValueFloat(S.Viscosity_Weiler2018.VISCOSITY_COEFFICIENT_BOUNDARY),
            "surface_tension": tension,
            "adhesion": adhesion,
            "max_error": ts.getValueFloat(S.TimeStepDFSPH.MAX_ERROR),
        }
        want = (m.viscosity, m.boundary_viscosity, m.tension, m.adhesion)
        got = tuple(
            self.material_readback[k] for k in ("viscosity", "boundary_viscosity", "surface_tension", "adhesion")
        )
        if not np.allclose(got, want, rtol=1e-5, atol=1e-12):
            raise RuntimeError("SPlisHSPlasH did not take the configured material coefficients")

    # ---- state -----------------------------------------------------------------------------------------------------
    def _buf(self, name):
        return np.asarray(self.fluid.getFieldBuffer(name)).reshape(-1, 3)[: self.n]

    def positions(self) -> np.ndarray:
        """(N, 3) float32 view of the particle positions (world frame). Do not keep it across reset()."""
        return self._buf("position")

    def velocities(self) -> np.ndarray:
        return self._buf("velocity")

    @property
    def free_mask(self) -> np.ndarray:
        return self.absorbed_by == ""

    @property
    def time(self) -> float:
        return self._t

    def _clear_run_state(self):
        self._t = 0.0  # float64 clock: SPlisHSPlasH's own is float32 and cannot land on a target time
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
        """Back to the initial state (or a new one, `x0`, of the same size): boundaries to their initial poses,
        SPlisHSPlasH's own reset, positions and zero velocities, the neighbourhood search rebuilt from scratch, every
        particle free. Runs from reset() are bit-identical for a fixed thread count."""
        if x0 is not None:
            x0 = np.asarray(x0, float)
            if x0.shape != (self.n, 3) or not np.isfinite(x0).all():
                raise ValueError("a new initial state must have the fluid's shape")
            self.x0 = x0.astype(np.float32).astype(np.float64)
        self.positions()[:] = self.x0
        self.velocities()[:] = 0
        for b in self.boundaries:
            if b.animated:
                self.set_pose(b.name, b.pos, b.R, np.zeros(3), np.zeros(3))
        self.base.updateBoundaryParticles(True)
        self.base.reset()
        S = sph()
        for i in range(self.n):
            if self.absorbed_by[i]:
                self.fluid.setParticleState(i, S.ParticleState.Active)
        self.positions()[:] = self.x0
        self.velocities()[:] = 0.0
        self.sim.getNeighborhoodSearch().setSearchRadius(self.sim.getSupportRadius())
        self.tm.setTime(0.0)
        self.tm.setTimeStepSize(self.sol.dt_max)
        self.absorbed_by[:] = ""
        for a in self.absorbers:
            a.reset()
        self._clear_run_state()
        self.revision += 1
        self.validate()

    def set_initial_boundary_poses(self, poses: dict):
        """New initial poses {name: (pos, R)} of animated boundaries (applied by the next reset())."""
        for b in self.boundaries:
            if b.name in poses:
                b.pos = np.asarray(poses[b.name][0], float)
                b.R = np.asarray(poses[b.name][1], float)

    def settle(self, seconds: float, damping: float):
        """Bring a freshly sampled fill to rest and make that the initial state: step `seconds` with every velocity
        scaled by `damping` after each step, then take the result as x0 and reset. Returns diagnostics."""
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

    # ---- absorption --------------------------------------------------------------------------------------------------
    def absorb(self, indices, owner):
        """Move contacting particles into an accounted, isolated reservoir (not deletion): stable indices, positions
        on a sparse lattice far below the scene (farther apart than the kernel support), state AnimatedByEmitter so
        the solver does not integrate them. Neither queries nor the renderer treat them as free liquid."""
        ids = np.asarray(indices, int)
        if not owner or np.any(~self.free_mask[ids]):
            raise ValueError("absorption needs a named owner and free particles")
        self.absorbed_by[ids] = owner
        side = int(np.ceil(self.n ** (1 / 3))) + 1
        ijk = np.column_stack((ids % side, ids // side % side, ids // side**2))
        self.positions()[ids] = ijk * (16 * self.mat.particle_radius) + [0, 0, REST_Z]
        self.velocities()[ids] = 0
        S = sph()
        for i in ids:
            self.fluid.setParticleState(int(i), S.ParticleState.AnimatedByEmitter)
        self.sim.getNeighborhoodSearch().setSearchRadius(self.sim.getSupportRadius())
        self.revision += 1

    def _absorb_at(self, poses):
        for a in self.absorbers:
            pos, R = poses[a.name][:2]
            if not (np.isfinite(pos).all() and np.isfinite(R).all()):
                self.fail("nonfinite absorber pose")
            a.update(self, pos, R)

    # ---- stepping ----------------------------------------------------------------------------------------------------
    def set_pose(self, name, pos, R, v, w):
        rbo = self.rbos[name]
        rbo.setPosition(np.asarray(pos, np.float32))
        rbo.setWorldSpaceRotation(np.asarray(R, np.float32))
        rbo.setVelocity(np.asarray(v, np.float32))
        rbo.setAngularVelocity(np.asarray(w, np.float32))

    def _static_poses(self):
        return {b.name: (b.pos, b.R, np.zeros(3), np.zeros(3)) for b in self.boundaries if b.animated}

    def advance(self, t1: float, pose_at=None) -> int:
        """Step to fluid time t1. `pose_at(t)` -> {name: (pos, R, v, w)} of every animated boundary at time t."""
        if not np.isfinite(t1) or t1 < self.time - 1e-12:
            self.fail("invalid target time")
        self.validate()
        n0 = self.steps
        s, g = self.sol, 9.81
        S = sph()
        ts = self.sim.getTimeStep()
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
            self.tm.setTimeStepSize(dt)
            self.tm.setTime(self.time)
            for name, (pos, R, v, w) in poses.items():
                self.set_pose(name, pos, R, v, w)
            self.base.updateBoundaryParticles(False)
            old = self.positions().astype(np.float64)
            self.base.timeStepNoGUI()
            if not np.isfinite(self.positions()).all() or not np.isfinite(self.velocities()).all():
                self.fail("nonfinite native step")
            x, v = self._resolve_prediction(old, free)
            self.positions()[free] = x
            self.velocities()[free] = v
            self._t += dt
            self.steps += 1
            it, itv = (
                ts.getValueUInt(S.TimeStepDFSPH.SOLVER_ITERATIONS),
                ts.getValueUInt(S.TimeStepDFSPH.SOLVER_ITERATIONS_V),
            )
            self.iterations["density_max"] = max(self.iterations["density_max"], int(it))
            self.iterations["divergence_max"] = max(self.iterations["divergence_max"], int(itv))
            self.iterations["density_sum"] += int(it)
            self.iterations["divergence_sum"] += int(itv)
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
        self.previous_predicted_speed = raw  # a wall removes normal velocity, not the next pressure response
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
            self.base.updateBoundaryParticles(False)
        self._t = float(t1)
        self.tm.setTime(self._t)
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
        try:
            self.base.cleanup()
        finally:
            _LIVE = None
