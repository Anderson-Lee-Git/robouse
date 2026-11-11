"""One-way MuJoCo -> SPH coupling on a robosuite/RoboCasa `MjSim`.

After every MuJoCo step the fluid is advanced to the same simulated time. Within that step the animated boundaries
(the MuJoCo bodies holding or receiving liquid) move along the straight line between their pose before and after
the MuJoCo step (position interpolated linearly, rotation along the shortest arc), with the velocity of that motion,
so a boundary never jumps however many SPH steps one MuJoCo step takes. The fluid never acts on MuJoCo: no force, no
mass, no contact (a full bottle weighs what its MuJoCo model says, empty or not).

Rendering: the sim's `render` is wrapped so that, before a frame is drawn, the liquid surface is reconstructed from
the current particles (once per fluid state, shared by all cameras) and uploaded into the model's liquid mesh geom
(surface.py). Nothing else about the render changes: same cameras, lights, shadows, resolution and anti-aliasing.

Install it after the scene has settled (robouse's worker settles objects in make_scenario); the fluid's time zero is
the MuJoCo time at install, and its initial particles must already sit in the source container at its pose then.
"""

from __future__ import annotations

import time

import numpy as np

ATTR = "_liquid_coupling"


def rotvec(R) -> np.ndarray:
    """Axis * angle of a rotation matrix."""
    R = np.asarray(R, float)
    c = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    ang = float(np.arccos(c))
    if ang < 1e-9:
        return np.zeros(3)
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    s = np.linalg.norm(v)
    if s < 1e-9:  # ~pi: axis from the symmetric part
        w, U = np.linalg.eigh((R + np.eye(3)) / 2.0)
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


class LiquidCoupling:
    """Drives an `SPHFluid` from a MuJoCo sim. `bodies` maps each animated SPH boundary name to its MuJoCo body id
    (the boundary mesh must be in that body's frame). `renderer`: a SurfaceRenderer for the model, or None."""

    def __init__(self, sim, fluid, bodies: dict, renderer=None, max_lag_steps: int = 0, pose_sources=()):
        self.sim = sim
        self.fluid = fluid
        self.bodies = {k: int(v) for k, v in bodies.items()}
        # callables(data) -> {boundary name: (pos, R)} for boundaries that follow no single body (contract 0.6.0
        # flex patches); evaluated on the same data as the bodies, so they share the bodies' timing
        self.pose_sources = list(pose_sources)
        self.renderer = renderer
        self.pre_step = []  # callables(sim, t) run before each MuJoCo step (e.g. a scripted kinematic motion)
        self.absorbers = []
        self.sleep = None
        self.timing = {"sph_s": 0.0, "mj_steps": 0, "surface_s": 0.0, "upload_s": 0.0, "surfaces": 0}
        self._surface_key = None
        self.resets = 0
        self._capture_origin()
        self.initial_poses = dict(self._prev)

    # ---- poses ---------------------------------------------------------------------------------------------------
    def _poses(self) -> dict:
        d = self.sim.data
        out = {
            k: (np.array(d.body_xpos[b], float), np.array(d.body_xmat[b], float).reshape(3, 3))
            for k, b in self.bodies.items()
        }
        for source in self.pose_sources:
            for k, pose in source(d).items():
                if k in out:
                    raise ValueError(f"liquid boundary {k!r} has two pose sources")
                out[k] = pose
        return out

    def _capture_origin(self):
        self.t0 = float(self.sim.data.time)
        self._prev = self._poses()
        self._t_prev = 0.0

    def poses(self) -> dict:
        """{boundary name: (pos, R)} of the animated bodies now (for queries)."""
        return self._poses()

    # ---- stepping ------------------------------------------------------------------------------------------------
    def sync(self):
        """Advance the fluid to the MuJoCo time (called after every MuJoCo step once installed)."""
        t = float(self.sim.data.time) - self.t0
        if t <= self.fluid.time + 1e-12:
            return
        new = self._poses()
        ta, tb = self._t_prev, t
        span = max(tb - ta, 1e-12)
        motion = {}
        for k, (pa, Ra) in self._prev.items():
            pb, Rb = new[k]
            motion[k] = (pa, Ra, (pb - pa) / span, rotvec(Rb @ Ra.T) / span)

        def pose_at(ts):
            s = min(max(ts - ta, 0.0), span)
            return {k: (pa + v * s, rotmat(w * s) @ Ra, v, w) for k, (pa, Ra, v, w) in motion.items()}

        c0 = time.perf_counter()
        if self.sleep is not None:
            self.sleep.update(self.fluid, new)
        if self.sleep is not None and self.sleep.sleeping:
            self.fluid.sleep_until(t, pose_at)
        else:
            self.fluid.advance(t, pose_at)
        for absorber in self.absorbers:
            absorber.update_poses(self.fluid, new)
        self.timing["sph_s"] += time.perf_counter() - c0
        self.timing["mj_steps"] += 1
        self._prev, self._t_prev = new, t

    def reset(self, check_poses_m: float = 1e-3):
        """Fluid back to its exact initial state, and fluid time zero at the current MuJoCo time. Restore the MuJoCo
        state (the source container's pose) first: the particles are put back where they started, in the world."""
        for k, (p, R) in self._poses().items():
            p0, R0 = self.initial_poses[k]
            if np.linalg.norm(p - p0) > check_poses_m or np.linalg.norm(rotvec(R @ R0.T)) > 0.01:
                raise RuntimeError(f"liquid reset: body {k} is not at its initial pose ({p} vs {p0})")
        self.fluid.reset()
        for absorber in self.absorbers:
            absorber.reset()
        if self.sleep is not None:
            self.sleep.reset()
        self._capture_origin()
        self._surface_key = None
        self.resets += 1

    # ---- rendering -----------------------------------------------------------------------------------------------
    def refresh_surface(self, con=None):
        """Reconstruct the surface if the fluid moved since the last one, and upload it to `con` (an MjrContext)."""
        if self.renderer is None:
            return
        key = (self.resets, self.fluid.steps, self.fluid.revision)
        if key != self._surface_key:
            c0 = time.perf_counter()
            self.renderer.update(self.fluid.positions()[self.fluid.free_mask])
            self.timing["surface_s"] += time.perf_counter() - c0
            self.timing["surfaces"] += 1
            self._surface_key = key
            self._uploaded = set()
        if con is not None and id(con) not in self._uploaded:
            c0 = time.perf_counter()
            self.renderer.upload(con)
            self.timing["upload_s"] += time.perf_counter() - c0
            self._uploaded.add(id(con))

    # ---- installation --------------------------------------------------------------------------------------------
    def install(self):
        """Wrap the sim's step methods and render (once per sim; a later coupling replaces the earlier one)."""
        sim = self.sim
        setattr(sim, ATTR, self)
        if getattr(sim, "_liquid_wrapped", False):
            return self
        for meth in ("step", "step2"):
            orig = getattr(sim, meth)

            def wrapped(*a, _orig=orig, **k):
                cpl = getattr(sim, ATTR, None)
                if cpl is not None:
                    t = float(sim.data.time) - cpl.t0
                    for hook in cpl.pre_step:
                        hook(sim, t)
                out = _orig(*a, **k)
                if cpl is not None:
                    cpl.sync()
                return out

            setattr(sim, meth, wrapped)
        orig_render = sim.render

        def render(*a, **k):
            cpl = getattr(sim, ATTR, None)
            if cpl is not None:
                ctx = getattr(sim, "_render_context_offscreen", None)
                cpl.refresh_surface(getattr(ctx, "con", None))
            return orig_render(*a, **k)

        sim.render = render
        sim._liquid_wrapped = True
        return self

    def uninstall(self):
        setattr(self.sim, ATTR, None)
