"""A DFSPH liquid (SPlisHSPlasH) with kinematic rigid boundaries: the fluid half of the one-way MuJoCo coupling.

One `SPHFluid` per process: SPlisHSPlasH keeps its simulation in process-wide singletons. The fluid lives in MuJoCo's
world frame (metres, z up, gravity -z). Boundaries are closed triangle meshes in their body's frame; an animated
boundary is moved every SPH step to the pose a caller provides (MuJoCo's body pose), a static one stays where it was
created. The fluid never pushes back (one-way).

By default native CFL control is off: dt = clamp(cfl * 2r / max particle speed,
dt_min, dt_max), shortened to land on the target MuJoCo time. Experimental native
CFL methods are explicit opt-ins and still land on every synchronization point.
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import meshes

_SPH = None
_BACKEND_FILE = None


def sph(backend=None):
    """Import pysplishsplash. Its wheel bundles a libGLdispatch that crashes the system libGLX at import (SIGSEGV in
    __glDispatchInit); loading the system libGLdispatch first, globally, makes both bind to it. The GUI is never used."""
    global _SPH, _BACKEND_FILE
    module_path = None
    if backend is not None:
        abi = f"cp{sys.version_info.major}{sys.version_info.minor}"
        if backend.get("python_abi", abi) != abi:
            raise RuntimeError("native liquid backend Python ABI mismatch")
        root = Path(os.environ["ROBOUSE_ROBOCASA_OBJECT_ROOT"]).resolve()
        module_path = (root / backend["file"]).resolve()
        if not module_path.is_relative_to(root):
            raise ValueError("native liquid module must stay inside the asset root")
        if hashlib.sha256(module_path.read_bytes()).hexdigest() != backend["sha256"]:
            raise ValueError("native liquid module digest mismatch")
        loaded = _SPH or sys.modules.get("pysplishsplash")
        if loaded is not None and Path(loaded.__file__).resolve() != module_path:
            raise RuntimeError("changing native liquid backend requires a fresh process")
        if loaded is not None:
            _SPH, _BACKEND_FILE = loaded, module_path
    if _SPH is None:
        try:
            ctypes.CDLL("libGLdispatch.so.0", mode=ctypes.RTLD_GLOBAL)
        except OSError:
            pass
        if module_path is None:
            import pysplishsplash
            _SPH = pysplishsplash
        else:
            spec = importlib.util.spec_from_file_location("pysplishsplash", module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules["pysplishsplash"] = module
            _SPH, _BACKEND_FILE = module, module_path
    return _SPH


def set_threads(n: int) -> int:
    """Set the OpenMP thread count of SPlisHSPlasH's own (bundled) libgomp. OMP_NUM_THREADS is read once, when the
    first OpenMP runtime of the process starts, so setting the variable later has no effect. Returns the count."""
    sph()
    lib = None
    candidates = set()
    with open("/proc/self/maps") as fh:
        for line in fh:
            if "/libgomp" in line:
                candidates.add(line.split()[-1])
            if "pysplishsplash.libs/libgomp" in line:
                lib = line.split()[-1]
                break
    if lib is None and len(candidates) == 1:
        lib = candidates.pop()  # isolated source build uses the system runtime
    if lib is None:
        raise RuntimeError("pysplishsplash's libgomp is not loaded")
    gomp = ctypes.CDLL(lib)
    gomp.omp_set_num_threads(int(n))
    return int(gomp.omp_get_max_threads())


@dataclass
class FluidParams:
    """Material and solver settings. Defaults: water-like juice at 1.25 mm particle radius (2.5 mm spacing)."""

    particle_radius: float = 0.00125
    density: float = 1000.0
    # Weiler et al. 2018 implicit viscosity (kinematic, m^2/s). Water is 1e-6; at 1e-5 the solver does nothing (0 CG
    # iterations) and, with no surface tension, a spill races across the counter as a monolayer at > 1 m/s and off
    # its edge. 1e-4 (a thin syrup) with wall friction 1e-3 gives a puddle that spreads and stops (checks.py puddle).
    # It is an effective value for 2.5 mm particles without surface tension, not juice's real viscosity.
    viscosity: float = 1e-4
    viscosity_boundary: float = 1e-3
    # Akinci et al. 2013 cohesion (surfaceTension) and adhesion to walls (surfaceTensionBoundary). OFF by default: in
    # pysplishsplash 2.19 at this resolution any nonzero value (down to 0.01) blew the resting fill up within 0.05 s
    # (docs/suites/robocasa.md, liquid limitations). Juice then has no cohesion or wetting film beyond what SPH gives.
    surface_tension: float = 0.0
    adhesion: float = 0.0
    # SPlisHSPlasH surface tension method: 1 Becker2007, 2 Akinci2013, 3 He2014, 4 Jeske2023 (0 off)
    surface_tension_method: int = 2
    xsph: float = 0.0
    max_error: float = 0.05  # DFSPH density error, percent
    max_error_v: float = 0.1  # DFSPH divergence error, percent
    max_iterations: int = 100
    cfl: float = 0.5
    dt_min: float = 5e-5
    dt_max: float = 2e-3
    # Opt-in speed-up experiments; zero retains the 0.2 contract exactly.
    cfl_method: int = 0
    boundary_method: int = 0
    map_resolution: tuple = (40, 40, 40)
    capillary_safety: float = 0.0
    gravity: tuple = (0.0, 0.0, -9.81)
    # SPlisHSPlasH's z-curve particle reordering (cache locality). It permutes the particle arrays during a run.
    # Off: with it on, an in-process reset is not bit-identical (it permutes the particle arrays during a run).
    z_sort: bool = False

    @property
    def particle_volume(self) -> float:
        """Liquid volume one particle stands for: (2r)^3, so a particle's mass is density x (2r)^3 (what SPlisHSPlasH
        assigns to particles read from a file) and a cubic lattice of pitch 2r is the liquid at rest density."""
        return (2 * self.particle_radius) ** 3

    @property
    def spacing(self) -> float:
        return 2 * self.particle_radius


@dataclass
class Boundary:
    name: str
    vertices: np.ndarray  # (V, 3) in the body frame
    faces: np.ndarray  # (F, 3)
    pos: tuple = (0.0, 0.0, 0.0)  # initial world pose
    quat: tuple = (1.0, 0.0, 0.0, 0.0)  # wxyz
    animated: bool = True
    extra: dict = field(default_factory=dict)


def quat_to_mat(q):
    w, x, y, z = map(float, q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _axis_angle(q):
    w, x, y, z = map(float, q)
    s = math.sqrt(max(0.0, x * x + y * y + z * z))
    if s < 1e-12:
        return [1.0, 0.0, 0.0], 0.0
    return [x / s, y / s, z / s], 2.0 * math.atan2(s, w)


class SPHFluid:
    def __init__(self, workdir, params: FluidParams, boundaries: list[Boundary], particles: np.ndarray,
                 threads: int | None = None, backend: dict | None = None):
        global _LIVE
        if _LIVE is not None:
            raise RuntimeError("SPlisHSPlasH holds one simulation per process; close() the previous SPHFluid first")
        particles = np.asarray(particles, float)
        if particles.ndim != 2 or particles.shape[1] != 3 or not len(particles) or not np.isfinite(particles).all():
            raise ValueError("SPH requires a nonempty finite (N, 3) particle array")
        if not 0 < params.dt_min <= params.dt_max or params.particle_radius <= 0 or params.density <= 0:
            raise ValueError("invalid SPH time step, radius or density")
        if params.cfl_method not in (0, 1, 2) or params.boundary_method not in (0, 1, 2):
            raise ValueError("unsupported CFL or boundary method")
        if not 0 <= params.capillary_safety <= 1:
            raise ValueError("capillary safety factor must be in [0, 1]")
        if backend is None and _BACKEND_FILE is not None:
            raise RuntimeError("returning to the default liquid backend requires a fresh process")
        S = sph(backend)
        self.backend = dict(backend) if backend else {
            "id": "python-import", "sha256": hashlib.sha256(Path(S.__file__).read_bytes()).hexdigest()}
        self.params = params
        self.workdir = Path(workdir).resolve()  # SPlisHSPlasH resolves relative paths against its executable
        self.workdir.mkdir(parents=True, exist_ok=True)
        if threads:
            os.environ["OMP_NUM_THREADS"] = str(int(threads))
            set_threads(int(threads))
        self.boundaries = list(boundaries)
        # static bodies first, animated after: SimulatorBase sorts them that way, and for this input the order is kept
        order = sorted(range(len(self.boundaries)), key=lambda i: self.boundaries[i].animated)
        self.boundaries = [self.boundaries[i] for i in order]
        rigid = []
        for b in self.boundaries:
            obj = meshes.write_obj(self.workdir / f"{b.name}.obj", b.vertices, b.faces)
            axis, angle = _axis_angle(b.quat)
            samples = {}
            if b.extra.get("samples") is not None and params.boundary_method == 0:  # a custom Akinci sampling (e.g. only a counter's top face)
                meshes.write_bgeo(self.workdir / f"{b.name}_samples.bgeo", b.extra["samples"])
                samples = {"particleFile": f"{b.name}_samples.bgeo"}
            rigid.append({
                **samples,
                "geometryFile": obj.name, "translation": [float(v) for v in b.pos], "rotationAxis": axis,
                "rotationAngle": angle, "scale": [1, 1, 1], "isDynamic": False, "isWall": False,
                "isAnimated": bool(b.animated), "samplingMode": 1,
                "mapResolution": list(b.extra.get("map_resolution", params.map_resolution)), "color": [0.5, 0.5, 0.5, 1.0],
            })
        self.n = int(len(particles))
        meshes.write_bgeo(self.workdir / "fluid.bgeo", particles)
        p = params
        scene = {
            "Configuration": {
                "particleRadius": p.particle_radius, "numberOfStepsPerRenderUpdate": 1, "density0": p.density,
                "simulationMethod": 4, "gravitation": list(p.gravity), "cflMethod": p.cfl_method, "timeStepSize": p.dt_max,
                "cflFactor": p.cfl, "cflMinTimeStepSize": p.dt_min, "cflMaxTimeStepSize": p.dt_max,
                "maxIterations": p.max_iterations, "maxError": p.max_error, "maxIterationsV": p.max_iterations,
                "maxErrorV": p.max_error_v, "enableDivergenceSolver": True, "boundaryHandlingMethod": p.boundary_method,
                "enableZSort": bool(p.z_sort), "stopAt": -1, "enablePartioExport": False, "enableVTKExport": False,
                "enableRigidBodyExport": False, "enableStateExport": False, "dataExportFPS": 25,
            },
            "Materials": [{
                "id": "Fluid", "density0": p.density, "viscosityMethod": 6, "viscosity": p.viscosity,
                "viscosityBoundary": p.viscosity_boundary, "viscoMaxIter": 100, "viscoMaxError": 0.01,
                "surfaceTensionMethod": p.surface_tension_method if (p.surface_tension or p.adhesion) else 0,
                "surfaceTension": p.surface_tension, "surfaceTensionBoundary": p.adhesion,
                "xsph": p.xsph, "xsphBoundary": 0.0,
            }],
            "RigidBodies": rigid,
            "FluidModels": [{"particleFile": "fluid.bgeo", "id": "Fluid", "translation": [0, 0, 0], "scale": [1, 1, 1]}],
        }
        (self.workdir / "scene.json").write_text(json.dumps(scene, indent=1))
        self.base = S.Exec.SimulatorBase()
        self.base.init(sceneFile=str(self.workdir / "scene.json"), useGui=False, outputDir=str(self.workdir / "out"),
                       useCache=False, initialPause=False, stopAt=-1.0)
        self.base.initSimulation()
        _LIVE = self
        self.timing = {}
        self.sim = S.Simulation.getCurrent()
        self.tm = S.TimeManager.getCurrent()
        self.fluid = self.sim.getFluidModel(0)
        # Boundary data (Akinci samples, boundary volumes) is built in SimulatorBase::deferredInit, which Python reaches
        # only through runSimulation(): run it with stopAt set so it takes exactly one tiny step, then reset.
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
            if not np.allclose(got, b.pos, atol=1e-5) or bool(rbo.isAnimated()) != bool(b.animated):
                raise RuntimeError(f"boundary order mismatch at {i} ({b.name}): {got} vs {b.pos}")
            self.rbos[b.name] = rbo
        self.boundary_particles = {b.name: getattr(self.sim.getBoundaryModel(i), "numberOfParticles", lambda: 0)()
                                   for i, b in enumerate(self.boundaries)}
        self.mass = float(self.fluid.getMass(0))
        self.x0 = self.positions().copy()
        lo, hi = np.asarray(particles).min(0), np.asarray(particles).max(0)
        if not (np.allclose(self.x0.min(0), lo, atol=1e-5) and np.allclose(self.x0.max(0), hi, atol=1e-5)):
            raise RuntimeError("SPlisHSPlasH read different initial particle positions than were written")
        self.steps = 0
        self._t = 0.0  # simulated time, float64: SPlisHSPlasH's own clock is float32 and cannot land on a target time
        self.substeps_log = []
        self.log_steps = False
        self.absorbed_by = np.full(self.n, "", dtype=object)
        self.revision = 0

    @property
    def free_mask(self):
        return self.absorbed_by == ""

    def absorb(self, indices, owner):
        """Transfer contacting particles into an accounted, isolated absorbed reservoir.

        Keep solver indices stable (z-sort must be off). AnimatedByEmitter prevents
        integration of reservoir particles; their separated off-domain positions
        prevent pressure/cohesion forces on the remaining free liquid. Neither the
        renderer nor spatial queries may use reservoir positions as free liquid.
        """
        if self.params.z_sort:
            raise ValueError("absorption requires z_sort=False for stable particle identities")
        ids = np.asarray(indices, int)
        if not owner or np.any(~self.free_mask[ids]):
            raise ValueError("absorption requires a named owner and free particles")
        self.absorbed_by[ids] = owner
        # Sparse 3-D lattice, farther apart than the kernel support; stays compact
        # enough for float32 and cannot interact with the kitchen around z=1 m.
        side = int(np.ceil(self.n ** (1 / 3))) + 1
        ijk = np.column_stack((ids % side, ids // side % side, ids // side ** 2))
        self.positions()[ids] = ijk * (16 * self.params.particle_radius) + [0, 0, -10]
        self.velocities()[ids] = 0
        for i in ids:
            self.fluid.setParticleState(int(i), sph().ParticleState.AnimatedByEmitter)
        self.sim.getNeighborhoodSearch().setSearchRadius(self.sim.getSupportRadius())
        self.revision += 1

    def _initial_poses(self, t=0.0):
        return {b.name: (np.asarray(b.pos, float), quat_to_mat(b.quat), np.zeros(3), np.zeros(3))
                for b in self.boundaries if b.animated}

    def _set_material(self):
        """Without the GUI SPlisHSPlasH does not read a material's non-pressure-force coefficients from the scene file
        (SimulatorBase::deferredInit reads them only when a GUI exists), so set every coefficient here."""
        S, p, fm = sph(), self.params, self.fluid
        fm.setValueInt(fm.VISCOSITY_METHOD, 6)
        visc = fm.getViscosityBase()
        visc.setValueFloat(S.Viscosity_Weiler2018.VISCOSITY_COEFFICIENT, p.viscosity)
        visc.setValueFloat(S.Viscosity_Weiler2018.VISCOSITY_COEFFICIENT_BOUNDARY, p.viscosity_boundary)
        visc.setValueUInt(S.Viscosity_Weiler2018.MAX_ITERATIONS, 100)
        visc.setValueFloat(S.Viscosity_Weiler2018.MAX_ERROR, 0.01)
        fm.setValueInt(fm.SURFACE_TENSION_METHOD, p.surface_tension_method if (p.surface_tension or p.adhesion) else 0)
        st = fm.getSurfaceTensionBase()
        if st is not None:
            # Parameter IDs belong to the selected class. An uninstantiated class's
            # IDs are -1 in the Python bindings, which is not a valid parameter.
            st_class = {1: S.SurfaceTension_Becker2007, 2: S.SurfaceTension_Akinci2013,
                        3: S.SurfaceTension_He2014, 4: S.SurfaceTension_Jeske2023}[p.surface_tension_method]
            st.setValueFloat(st_class.SURFACE_TENSION, p.surface_tension)
            st.setValueFloat(st_class.SURFACE_TENSION_BOUNDARY, p.adhesion)
        xs = fm.getXSPH()
        if xs is not None:
            xs.setValueFloat(S.XSPH.FLUID_COEFFICIENT, p.xsph)
            xs.setValueFloat(S.XSPH.BOUNDARY_COEFFICIENT, 0.0)
        ts = self.sim.getTimeStep()
        ts.setValueFloat(S.TimeStepDFSPH.MAX_ERROR, p.max_error)
        ts.setValueFloat(S.TimeStepDFSPH.MAX_ERROR_V, p.max_error_v)
        ts.setValueUInt(S.TimeStepDFSPH.MAX_ITERATIONS, p.max_iterations)
        ts.setValueUInt(S.TimeStepDFSPH.MAX_ITERATIONS_V, p.max_iterations)
        ts.setValueBool(S.TimeStepDFSPH.USE_DIVERGENCE_SOLVER, True)
        self.material = {
            "viscosity": visc.getValueFloat(S.Viscosity_Weiler2018.VISCOSITY_COEFFICIENT),
            "surface_tension": st.getValueFloat(st_class.SURFACE_TENSION) if st is not None else 0.0,
            "adhesion": st.getValueFloat(st_class.SURFACE_TENSION_BOUNDARY) if st is not None else 0.0,
            "max_error": ts.getValueFloat(S.TimeStepDFSPH.MAX_ERROR),
        }

    # ---- state -------------------------------------------------------------------------------------------------
    def _buf(self, name):
        return np.asarray(self.fluid.getFieldBuffer(name)).reshape(-1, 3)[: self.n]

    def positions(self) -> np.ndarray:
        """(N, 3) float32 view of the particle positions (world frame). Do not keep it across reset()."""
        return self._buf("position")

    def velocities(self) -> np.ndarray:
        return self._buf("velocity")

    @property
    def time(self) -> float:
        return self._t

    def volume_m3(self) -> float:
        """Liquid volume of all particles (count x (2r)^3). Particles are never created or deleted, so this is constant;
        mass conservation is checked as the count of finite particles."""
        return self.n * self.params.particle_volume

    def state(self) -> dict:
        return {"time": self.time, "x": self.positions().copy(), "v": self.velocities().copy(), "steps": self.steps,
                "absorbed_by": self.absorbed_by.copy()}

    def reset(self):
        """Back to the exact initial state: boundaries to their initial poses, SPlisHSPlasH's own reset (time, solver
        state, boundary volumes, neighbourhood search), the initial positions and zero velocities written again, and
        the neighbourhood search rebuilt from scratch. Every run from reset() is then bit-identical for a fixed thread
        count (see docs/suites/robocasa.md, liquid, for what differs across thread counts)."""
        # SPlisHSPlasH's reset leaves animated bodies where the last run left them and recomputes the boundary volumes
        # with them there; put them back first.
        for name, (pos, R, v, w) in self._initial_poses().items():
            self.set_pose(name, pos, R, v, w)
        self._update_boundaries(True)
        self.base.reset()
        self.positions()[:] = self.x0
        self.velocities()[:] = 0.0
        # CompactNSearch updates its cell lists incrementally: rebuild them (setting the radius re-inits the search, in
        # point order) so neighbours come in the same order as on every other run.
        self.sim.getNeighborhoodSearch().setSearchRadius(self.sim.getSupportRadius())
        self.tm.setTime(0.0)
        self.tm.setTimeStepSize(self.params.dt_max)
        self._t = 0.0
        self.steps = 0
        self.substeps_log = []
        self.absorbed_by[:] = ""
        self.revision += 1

    def settle(self, seconds: float = 0.3, damping: float = 0.9, pose_at=None, log=None) -> dict:
        """Bring a freshly sampled fill to rest and make that the initial state: step `seconds` with every particle
        velocity scaled by `damping` after each step (a lattice cut by curved walls starts locally compressed, and
        undamped its first pressure kick sloshes for a long time), then take the result as x0 and reset. Returns the
        final kinetic energy per particle and the step count. Deterministic for a fixed thread count; to share one
        initial state across processes and thread counts, save `x0` (initial_state) and pass it as `particles`."""
        n0 = 0
        while seconds - self.time > 1e-6:
            n0 += self.advance(min(seconds, self.time + self.params.dt_max), pose_at)
            self.velocities()[:] *= damping
            if not np.isfinite(self.positions()).all():
                raise FloatingPointError(f"liquid diverged while settling (t={self.time:.4f}s)")
            if log is not None:
                log(self)
        v = self.velocities()
        ke = float(0.5 * np.mean(np.einsum("ij,ij->i", v, v)))
        self.x0 = self.positions().copy()
        self.reset()
        return {"steps": n0, "mean_ke_per_kg": ke}

    def initial_state(self) -> np.ndarray:
        return self.x0.copy()

    # ---- stepping ----------------------------------------------------------------------------------------------
    def _cfl_dt(self) -> float:
        v = self.velocities()
        vmax = float(np.sqrt(np.max(np.einsum("ij,ij->i", v, v)))) if len(v) else 0.0
        p = self.params
        dt = p.dt_max if vmax < 1e-9 else p.cfl * p.spacing / vmax
        return min(p.dt_max, max(p.dt_min, dt))

    def set_pose(self, name, pos, R, v=(0, 0, 0), w=(0, 0, 0)):
        rbo = self.rbos[name]
        rbo.setPosition(np.asarray(pos, np.float32))
        rbo.setWorldSpaceRotation(np.asarray(R, np.float32))
        rbo.setVelocity(np.asarray(v, np.float32))
        rbo.setAngularVelocity(np.asarray(w, np.float32))

    def _update_boundaries(self, force=False):
        # Native updateBoundaryParticles casts to Akinci's class; calling it
        # on a density/volume map is invalid even when it happens not to crash.
        if self.params.boundary_method == 0:
            self.base.updateBoundaryParticles(force)
        elif self.params.boundary_method == 1:
            self.base.updateDMVelocity()
        else:
            self.base.updateVMVelocity()

    def advance(self, t1: float, pose_at=None):
        """Step the fluid to time t1. `pose_at(t)` returns {name: (pos, R, v, w)} for the animated boundaries at time t
        (the start of each step); the boundary particles are moved there before the step."""
        n0 = self.steps
        # a remainder shorter than 1 us is dropped (folded into the step before): no sub-microsecond steps
        while t1 - self._t > 1e-6:
            dt = self._cfl_dt() if self.params.cfl_method == 0 else max(self.params.dt_min, float(self.tm.getTimeStepSize()))
            dt = min(dt, self.params.dt_max)
            if self.params.capillary_safety and self.params.surface_tension:
                capillary = math.sqrt(self.params.density * self.params.spacing**3 /
                                      (2 * math.pi * self.params.surface_tension))
                dt = min(dt, self.params.capillary_safety * capillary)
            rem = t1 - self._t
            if rem <= dt * 1.0001 + 1e-6:
                dt = rem
            elif rem < 2 * dt:
                dt = rem / 2
            self.tm.setTimeStepSize(dt)
            self.tm.setTime(self._t)
            if pose_at is not None:
                for name, (pos, R, v, w) in pose_at(self.time).items():
                    self.set_pose(name, pos, R, v, w)
                self._update_boundaries()
            self.base.timeStepNoGUI()
            if not np.isfinite(self.positions()).all() or not np.isfinite(self.velocities()).all():
                raise FloatingPointError(f"SPH diverged at {self._t + dt:.6f} s")
            self._t += dt
            self.steps += 1
            if self.log_steps:
                ts, S = self.sim.getTimeStep(), sph()
                self.substeps_log.append((self.time, dt, ts.getValueUInt(S.TimeStepDFSPH.SOLVER_ITERATIONS),
                                          ts.getValueUInt(S.TimeStepDFSPH.SOLVER_ITERATIONS_V)))
        return self.steps - n0

    def sleep_until(self, t1, pose_at=None):
        """Advance only the clock of an explicitly frozen initial puddle."""
        if t1 < self._t:
            raise ValueError("liquid time cannot run backwards")
        if pose_at:
            for name, (pos, R, v, w) in pose_at(t1).items():
                self.set_pose(name, pos, R, v, w)
            self._update_boundaries()
        self._t = float(t1)
        self.tm.setTime(self._t)
        self.velocities()[:] = 0

    def close(self):
        global _LIVE
        try:
            self.base.cleanup()
        finally:
            _LIVE = None


_LIVE = None


def params_dict(p: FluidParams) -> dict:
    return asdict(p)
