"""The household physics extension for `liquid` (contracts 1.0.0 and 1.1.0): one-way MuJoCo -> SPH coupling, accounting and the
rendered surface, on the generic hooks of extensions.py.

- `prepare(spec, config, root)` validates the block, checks the pinned backend (ABI, sha256) and the initial-state
  file, and adds the visual-only surface mesh geom to the scene (one per source when a source gives its own rgba,
  contract 1.1.0; see surface.py).
- `__init__(world, config)` (every reset, before reset settling) builds the boundaries from the compiled scene, the
  domain, the initial particles (source fills, puddles or the package's initial state) and the fluid. The native fluid
  is kept for the process and reused through an exact reset when the configuration, boundary meshes, initial poses
  and particles are the same; otherwise it is rebuilt.
- `after_substep(world)` advances the fluid to the MuJoCo time. Within each 2 ms MuJoCo substep the animated
  boundaries move along the straight line between their poses before and after it (position linear, rotation along
  the shortest arc), with that motion's velocity.
- `trace_state(world)` records exact particle counts per label and per source; `summary()` the full report;
  `before_render(world, renderer)` reconstructs the surface (once per fluid state) and uploads it.
- Goals read the liquid through `world.extensions["liquid"]`, calling only its query methods: `counts`,
  `volumes_ml`, `volume_ml`, `source_counts`, `source_volumes_ml`, `puddle`, `wetting_ml`, `particle_ml`, `time_s`.
  Labels: each container's name, "surface", "elsewhere", "nonfinite" and "absorbed:<boundary>"; sources are the
  package's `sources` names; volumes are whole particles times `particle_ml`. A query on an invalid or closed liquid
  raises (the episode is an infrastructure error). Nothing here reaches the policy.

Any validity error raises: the session ends the episode as an infrastructure error, never as a task outcome.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np

from . import config as C
from . import meshes, queries
from .contact import Absorber, ContainerSleep, MeshContact, PuddleSleep
from .domain import LiquidValidityError, make_domain
from .solver import BoundaryMesh, Fluid, check_backend, rotmat, rotvec
from .surface import GEOM as SURFACE_GEOM
from .surface import SurfaceRenderer, add_to_spec

_INITIAL: dict[str, np.ndarray] = {}  # sha256 -> initial state checked by prepare
_FLUID: dict = {"fluid": None, "key": None, "workdir": None, "settle": None}


def _cleanup():
    w = _FLUID.get("workdir")
    if w and Path(w).is_dir() and not (Path(w) / "invalid-state.npz").exists():
        shutil.rmtree(w, ignore_errors=True)


atexit.register(_cleanup)


def release() -> None:
    """Close the process's native fluid (tests; a new process is the normal way to start over)."""
    f = _FLUID["fluid"]
    _FLUID.update(fluid=None, key=None, settle=None)
    if f is not None:
        f.close()
    _cleanup()
    _FLUID["workdir"] = None


def _id(model, kind, name):
    import mujoco

    i = mujoco.mj_name2id(model, kind, name)
    if i < 0:
        raise ValueError(f"liquid: no {kind.name[6:].lower()} {name!r} in the scene")
    return int(i)


class Extension:
    @staticmethod
    def prepare(spec, config, root) -> None:
        cfg = C.parse(config)
        check_backend(cfg.backend)
        if cfg.initial_state is not None:
            p = Path(root) / cfg.initial_state.file
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != cfg.initial_state.sha256:
                raise ValueError("liquid: initial_state file is missing or differs from its sha256")
            x = np.load(p, allow_pickle=False)
            if x.ndim != 2 or x.shape[1] != 3 or not np.isfinite(x).all():
                raise ValueError("liquid: initial_state must be a finite (N, 3) array")
            _INITIAL[cfg.initial_state.sha256] = np.asarray(x, float)
        if cfg.per_source_colour:
            for name, rgba in cfg.source_rgba().items():
                add_to_spec(spec, rgba, source=name)
        else:
            add_to_spec(spec, cfg.material.rgba)

    # ---- construction ------------------------------------------------------------------------------------------------
    def __init__(self, world, config):
        import mujoco

        t_start = time.perf_counter()
        self.cfg = cfg = C.parse(config)
        self.config_raw = config
        self.world = world
        model, data = world.model, world.data
        mat = cfg.material
        BODY, GEOM = mujoco.mjtObj.mjOBJ_BODY, mujoco.mjtObj.mjOBJ_GEOM

        # boundaries: containers and declared boundaries, each in its body's frame
        bms, self.bodies, self.containers = [], {}, {}
        for c in cfg.containers:
            bid = _id(model, BODY, c.body)
            v, f = meshes.geoms_mesh(model, data, bid, [_id(model, GEOM, g) for g in c.boundary_geoms])
            bms.append(BoundaryMesh(c.name, v, f, data.xpos[bid], data.xmat[bid], True))
            self.bodies[c.name] = bid
            self.containers[c.name] = queries.Container(c.body, [list(p) for p in c.profile], c.slack)
        for b in cfg.boundaries:
            bid = _id(model, BODY, b.body)
            if not b.animated:
                x = bid
                while x:
                    if model.body_jntnum[x] or model.body_mocapid[x] >= 0:
                        raise ValueError(f"liquid: static boundary {b.name!r} can move")
                    x = int(model.body_parentid[x])
            v, f = meshes.geoms_mesh(model, data, bid, [_id(model, GEOM, g) for g in b.geoms])
            bms.append(BoundaryMesh(b.name, v, f, data.xpos[bid], data.xmat[bid], b.animated))
            if b.animated:
                self.bodies[b.name] = bid

        # the work surface: a static boundary plate sampled on the support's top face, and its query region
        self.surface = None
        if cfg.surface is not None:
            sf = cfg.surface
            g = _id(model, GEOM, sf.geom)
            if model.geom_type[g] != mujoco.mjtGeom.mjGEOM_BOX:
                raise ValueError("liquid: surface.geom must be a box")
            R = np.asarray(data.geom_xmat[g]).reshape(3, 3)
            if not np.allclose(R[:, 2], [0, 0, 1], atol=1e-6):
                raise ValueError("liquid: surface.geom must have a horizontal top")
            if sf.geom not in cfg.static_box_geoms:
                raise ValueError("liquid: surface.geom must be one of domain.static_box_geoms")
            z = float(data.geom_xpos[g][2] + model.geom_size[g][2])
            rects = [(np.array(data.geom_xpos[g][:2]), R[:2, :2].copy(), np.array(model.geom_size[g][:2]))]
            cxy, half = np.asarray(sf.centre_xy, float), sf.half_extent
            pts = meshes.plate_samples(half, half, 0.0, 1.6 * mat.particle_radius, 2)
            pts[:, :2] += cxy
            pts[:, 2] += z
            c, Rr, h = rects[0]
            pts = pts[np.all(np.abs((pts[:, :2] - c) @ Rr) <= h + 1e-9, axis=1)]
            if not len(pts):
                raise ValueError("liquid: the surface patch does not overlap its geom")
            pv, pf = meshes.box((half, half, 0.005))
            origin = np.array([cxy[0], cxy[1], z - 0.005])
            bms.insert(0, BoundaryMesh("surface", pv, pf, origin, np.eye(3), False, samples=pts - origin))
            self.surface = queries.Surface(z, tuple(cxy - half), tuple(cxy + half), rects=rects)
        self.film = cfg.surface.film if cfg.surface else 0.0

        # initial particles, in source order (source identity = particle index range)
        self.source_ranges, parts, n0 = {}, [], 0
        for s in cfg.sources:
            ml = s.fill_ml if s.container else s.puddle_ml
            n = int(np.floor(ml / mat.particle_ml + 0.5))
            if n < 1:
                raise ValueError(f"liquid: source {s.name!r} is smaller than one particle")
            if s.container:
                c = next(c for c in cfg.containers if c.name == s.container)
                bid = self.bodies[c.name]
                local = meshes.profile_fill(c.profile, n, mat.spacing)
                parts.append(local @ np.asarray(data.xmat[bid]).reshape(3, 3).T + np.asarray(data.xpos[bid]))
            else:
                fill = meshes.puddle_fill(s.polygon_xy, n, self.surface.z, mat.spacing)
                if not self.surface.over(fill).all():
                    raise ValueError(f"liquid: puddle {s.name!r} extends beyond its surface")
                parts.append(fill)
            self.source_ranges[s.name] = (n0, n0 + n)
            n0 += n
        particles = np.concatenate(parts)
        if cfg.initial_state is not None:
            x = _INITIAL.get(cfg.initial_state.sha256)
            if x is None:
                raise RuntimeError("liquid: the initial state was not prepared")
            if x.shape != particles.shape:
                raise ValueError("liquid: initial_state does not hold the sources' particle count")
            particles = x

        self.domain_args = (list(cfg.static_box_geoms), cfg.floor_geom, mat.particle_radius)
        key = self._key(bms, particles)
        f = _FLUID["fluid"]
        self.reused = f is not None and _FLUID["key"] == key
        if self.reused:
            f.reset()
        else:
            release()
            root = os.environ.get("ROBOUSE_LIQUID_WORK_ROOT", "").strip() or None
            if root:
                Path(root).mkdir(parents=True, exist_ok=True)
            work = tempfile.mkdtemp(prefix="household-liquid-", dir=root)
            _FLUID["workdir"] = work
            domain = make_domain(model, data, *self.domain_args)
            f = Fluid(work, cfg.backend, cfg.threads, mat, cfg.solver, bms, particles, domain)
            settle = None
            try:
                if cfg.initial_state is None and cfg.settle_seconds > 0:
                    settle = f.settle(cfg.settle_seconds, cfg.settle_damping)
            except BaseException:
                f.close()  # a fluid that failed to settle is never reused
                raise
            _FLUID.update(fluid=f, key=key, settle=settle)
        self.fluid = f
        self.settle_report = _FLUID["settle"]
        self._label_cache = (None, None)
        self.closed = False  # set before sleep setup: _labels() reads it

        self.contact_meshes = {b.name: MeshContact(b.vertices, b.faces) for b in bms if b.animated}
        f.absorbers = [
            Absorber(a.boundary, self.contact_meshes[a.boundary], a.capacity_ml, a.contact_m) for a in cfg.absorbers
        ]
        self.t0 = float(data.time)
        self._prev = self._poses()
        self._t_prev = 0.0
        self.sleep = None
        if cfg.sleep == "puddle":
            if not np.all(self._labels() == "surface"):
                raise ValueError("liquid: sleep puddle needs every particle resting on the surface")
            self.sleep = PuddleSleep(self.contact_meshes, self._prev, mat.spacing)
        elif cfg.sleep == "containers":
            owners = set(self._labels())
            if not owners <= set(self.containers):
                raise ValueError("liquid: sleep containers needs all liquid inside containers")
            self.sleep = ContainerSleep(self.contact_meshes, self._prev, mat.spacing, owners)

        # rendered surfaces: [(source name or None, particle index range or None, renderer)]
        if cfg.per_source_colour:
            self.surfaces = [
                (s, self.source_ranges[s], SurfaceRenderer(model, mat.particle_radius, source=s))
                for s in self.source_ranges
            ]
        else:
            self.surfaces = [(None, None, SurfaceRenderer(model, mat.particle_radius))]
        self.renderer = self.surfaces[0][2]
        for _, _, r in self.surfaces:
            data.geom_xpos[r.geom] = 0.0
            data.geom_xmat[r.geom] = np.eye(3).ravel()
        self._surface_key = None
        self._uploaded: set = set()
        self.timing = {
            "init_s": time.perf_counter() - t_start,
            "sph_s": 0.0,
            "syncs": 0,
            "surface_s": 0.0,
            "surfaces": 0,
            "upload_s": 0.0,
        }

    def _key(self, bms, particles) -> str:
        h = hashlib.sha256(json.dumps(self.config_raw, sort_keys=True).encode())
        for b in bms:
            h.update(b.name.encode())
            for a in (b.vertices, b.faces, b.pos, b.R):
                h.update(np.ascontiguousarray(a).tobytes())
            if b.samples is not None:
                h.update(np.ascontiguousarray(b.samples).tobytes())
        h.update(np.ascontiguousarray(particles).tobytes())
        return h.hexdigest()

    # ---- coupling ------------------------------------------------------------------------------------------------------
    def _poses(self) -> dict:
        d = self.world.data
        return {
            k: (np.array(d.xpos[b], float), np.array(d.xmat[b], float).reshape(3, 3)) for k, b in self.bodies.items()
        }

    def after_substep(self, world) -> None:
        t = float(world.data.time) - self.t0
        if t <= self.fluid.time + 1e-12:
            return
        new = self._poses()
        ta, span = self._t_prev, max(t - self._t_prev, 1e-12)
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
        self.timing["sph_s"] += time.perf_counter() - c0
        self.timing["syncs"] += 1
        self._prev, self._t_prev = new, t

    # ---- queries -------------------------------------------------------------------------------------------------------
    def _state_key(self):
        f = self.fluid
        return (f.revision, f.steps, f.time, float(self.world.data.time))

    def _open(self):
        if self.closed:
            raise LiquidValidityError("the liquid of a closed episode")
        return self.fluid

    def _labels(self) -> np.ndarray:
        f = self._open()
        f.validate()
        k = self._state_key()
        if self._label_cache[0] == k:
            return self._label_cache[1]
        x = f.positions().astype(np.float64)
        lab = queries.partition(x, self.containers, self._poses(), self.surface, f.mat.particle_radius, self.film)
        absorbed = ~f.free_mask
        if absorbed.any():
            lab[absorbed] = ["absorbed:" + name for name in f.absorbed_by[absorbed]]
        self._label_cache = (k, lab)
        return lab

    def counts(self) -> dict:
        names, n = np.unique(np.asarray(self._labels(), dtype=str), return_counts=True)
        return {str(a): int(b) for a, b in zip(names, n, strict=True)}

    @property
    def particle_ml(self) -> float:
        return self._open().mat.particle_ml

    @property
    def time_s(self) -> float:
        return self._open().time

    def volumes_ml(self) -> dict:
        ml = self.particle_ml
        return {k: v * ml for k, v in self.counts().items()}

    def volume_ml(self, *labels: str) -> float:
        c = self.counts()
        return sum(c.get(x, 0) for x in labels) * self.particle_ml

    def source_volumes_ml(self) -> dict:
        ml = self.particle_ml
        return {s: {k: v * ml for k, v in d.items()} for s, d in self.source_counts().items()}

    def source_counts(self) -> dict:
        lab = np.asarray(self._labels(), dtype=str)
        out = {}
        for s, (a, b) in self.source_ranges.items():
            names, n = np.unique(lab[a:b], return_counts=True)
            out[s] = {str(x): int(y) for x, y in zip(names, n, strict=True)}
        return out

    def puddle(self) -> dict:
        lab = self._labels()
        return queries.puddle(
            self.fluid.positions().astype(np.float64),
            lab == "surface",
            self.fluid.mat.particle_radius,
            surface_z=None if self.surface is None else self.surface.z,
        )

    def wetting_ml(self, name: str, distance_m: float | None = None) -> float:
        """Free liquid within `distance_m` (default two spacings) of an animated boundary's mesh."""
        f = self._open()
        f.validate()
        if name not in self.contact_meshes:
            raise KeyError(f"no animated liquid boundary {name!r}")
        d = 2 * f.spacing if distance_m is None else float(distance_m)
        pos, R = self._poses()[name]
        free = f.positions()[f.free_mask].astype(np.float64)
        return float(self.contact_meshes[name].within(free, pos, R, d).sum()) * f.mat.particle_ml

    # ---- hooks: trace, summary, render ---------------------------------------------------------------------------------
    def trace_state(self, world) -> dict:
        return {"time_s": round(self.fluid.time, 6), "counts": self.counts(), "source_counts": self.source_counts()}

    def summary(self) -> dict:
        f = self.fluid
        out = {
            "contract": self.cfg.contract,
            "backend": f.backend,
            "threads": f.threads,
            "particles": f.n,
            "particle_ml": f.mat.particle_ml,
            "sources": {
                s: {"particles": b - a, "ml": (b - a) * f.mat.particle_ml} for s, (a, b) in self.source_ranges.items()
            },
            "time_s": f.time,
            "sph_steps": f.steps,
            "material_readback": f.material_readback,
            "validity": f.validity(),
            "settle": self.settle_report,
            "reused_native_fluid": self.reused,
            "timing": dict(self.timing),
            "surface_mesh": self._surface_report(),
            "sleep": None
            if self.sleep is None
            else {
                "sleeping": self.sleep.sleeping,
                "wake_time_s": self.sleep.wake_time,
                "wake_boundary": self.sleep.wake_body,
            },
            "absorbers": {a.name: a.report(f.mat.particle_volume) for a in f.absorbers},
        }
        if f.invalid_reason is None:
            counts = self.counts()
            out["counts"] = counts
            out["volumes_ml"] = {k: v * f.mat.particle_ml for k, v in counts.items()}
            out["source_counts"] = self.source_counts()
            out["puddle"] = self.puddle()
            if sum(counts.values()) != f.n:
                out["validity"]["ledger_error"] = "label counts differ from the particle count"
        return out

    def _surface_report(self) -> dict:
        if self.surfaces[0][0] is None:
            return dict(self.renderer.last)
        by = {s: dict(r.last) for s, _, r in self.surfaces}
        out = {k: sum(d[k] for d in by.values()) for k in ("verts", "faces", "seconds")}
        out["sources"] = by
        return out

    def before_render(self, world, renderer) -> None:
        f = self.fluid
        f.validate()
        k = self._state_key()[:3]
        if k != self._surface_key:
            c0 = time.perf_counter()
            x, free = f.positions(), f.free_mask
            for _, rng, r in self.surfaces:
                if rng is None:
                    r.update(x[free])
                else:
                    a, b = rng
                    r.update(x[a:b][free[a:b]])
            self.timing["surface_s"] += time.perf_counter() - c0
            self.timing["surfaces"] += 1
            self._surface_key = k
            self._uploaded = set()
        if id(renderer) not in self._uploaded:
            c0 = time.perf_counter()
            for _, _, r in self.surfaces:
                r.upload(renderer)
            self.timing["upload_s"] += time.perf_counter() - c0
            self._uploaded.add(id(renderer))

    def close(self) -> None:
        self.closed = True  # the native fluid stays for the process (an exact reset reuses it)


__all__ = ["Extension", "LiquidValidityError", "SURFACE_GEOM", "release"]
