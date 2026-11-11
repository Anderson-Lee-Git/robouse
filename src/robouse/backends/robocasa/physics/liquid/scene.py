"""Liquid in a RoboCasa kitchen built by robouse's worker: the opt-in glue between a scenario and the liquid package.

Two calls, both opt-in (nothing changes for a scene that does not make them):

1. `enable_surface(S)` before the kitchen is built, with S = the worker's scenario module (`W._load_scenario()`):
   every scenario class made afterwards gets the liquid surface mesh geom in its model (visual only, no physics).
2. `attach(env, cfg, workdir)` after `Worker.make_scenario` (the objects have settled): builds the SPH liquid with
   the named objects as moving boundaries and a counter-top plate, fills the source container, lets the fill come to
   rest, and installs the coupling on env.sim. Returns a `LiquidScene` (coupling, containers, queries).

`cfg` (what a spec's `liquid` entry would hold; researcher-side, never shown to a policy):
    {"source": "bottle", "fill_ml": 250, "containers": {"bottle": "liquid_juice_bottle", "glass": "liquid_tumbler"},
     "surface": {"fixture": "counter", "half_extent_m": 0.22, "centre_between": ["bottle", "glass"]},
     "particle_radius": 0.00125, "settle_s": 0.3, "rgba": [1.0, 0.56, 0.1, 1.0]}
`containers` maps object names to a registered container kind (`register_container` in this package; the kinds and
their inside profiles are scene assets, registered by a scenario plugin); the source must be one of them. Every
container's visual mesh is a boundary; the surface plate is a static boundary.
"""

from __future__ import annotations

import numpy as np

from . import PROFILES, VISUAL_GEOM, container_kind, meshes, queries, solver, surface  # noqa: F401 (registry views)
from .contact import Absorber, ContainerSleep, MeshContact, PatchAbsorber, PuddleSleep
from .coupling import LiquidCoupling


def enable_surface(S, max_verts: int = surface.MAX_VERTS, rgba=surface.JUICE_RGBA, configured_only=False):
    """Patch the worker's scenario module so each scenario class adds the liquid surface geom when its model loads."""
    if getattr(S, "_liquid_surface_enabled", False):
        return
    from robosuite.environments.base import REGISTERED_ENVS

    orig_make_class = S.make_class

    def make_class(spec):
        name = orig_make_class(spec)
        if configured_only and not spec.get("liquid"):
            return name
        cls = REGISTERED_ENVS[name]
        if not getattr(cls, "_liquid_surface", False):
            orig_load = cls._load_model

            def _load_model(self, attempt_num=1):
                self._liquid_initializing = True
                orig_load(self, attempt_num)
                if self.model.worldbody.find(f"./geom[@name='{surface.GEOM_NAME}']") is None:
                    surface.add_to_robosuite_model(self.model, max_verts, (spec.get("liquid") or {}).get("rgba", rgba))

            cls._load_model = _load_model
            cls._liquid_surface = True
        return name

    S.make_class = make_class
    S._liquid_surface_enabled = True


def _counter_top(env, fixture: str, geom: str | None = None):
    """(z, rects) of a fixture's top: robouse's support rectangles and the height of its `<name>_top*` slabs."""
    import importlib
    import sys

    S = sys.modules.get("robouse_robocasa_scenario") or importlib.import_module("robouse_robocasa_scenario")
    m, d = env.sim.model._model, env.sim.data
    import mujoco

    if geom is not None:
        g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, geom)
        if g < 0 or m.geom_type[g] != mujoco.mjtGeom.mjGEOM_BOX:
            raise ValueError(f"support geom {geom!r} must be an existing box")
        R = np.asarray(d.geom_xmat[g]).reshape(3, 3)
        if not np.allclose(R[:, 2], [0, 0, 1], atol=1e-6):
            raise ValueError("liquid support geom must have a horizontal top")
        return float(d.geom_xpos[g][2] + m.geom_size[g][2]), [
            (np.array(d.geom_xpos[g][:2]), R[:2, :2].copy(), np.array(m.geom_size[g][:2]))
        ]

    rects = S._support_rects(env, fixture)
    fx = S._fx(env, fixture)
    zs = [
        float(d.geom_xpos[g][2] + m.geom_size[g][2])
        for g in range(m.ngeom)
        if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "").startswith(f"{fx.name}_top")
        and m.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX
    ]
    if not zs:
        raise ValueError(f"fixture {fixture} has no top slabs to put the liquid's counter plate on")
    return max(zs), rects


def plate_in_rects(centre_xy, half: float, rects, z: float, spacing: float, layers: int = 2) -> np.ndarray:
    """Akinci samples of the counter top: a square of half side `half` around centre_xy, kept where it lies on one of
    the support rectangles (so the counter's real edge stays an edge). World frame."""
    pts = meshes.plate_samples(half, half, 0.0, spacing, layers)
    pts[:, :2] += np.asarray(centre_xy, float)
    pts[:, 2] += z
    keep = np.zeros(len(pts), bool)
    for c, R, h in rects:
        q = np.abs((pts[:, :2] - c) @ R)
        keep |= np.all(q <= h + 1e-9, axis=1)
    return pts[keep]


def map_plate_mesh(centre_xy, half, rects, thickness=0.01):
    """Closed mesh of the clipped support union, without fictitious gap floors.

    Maps use geometry instead of custom Akinci samples. Axis-aligned slab
    unions are supported; rotated slabs fail explicitly. Coordinates are local
    to (centre_xy, top_z - thickness/2).
    """
    centre_xy = np.asarray(centre_xy, float)
    slabs = []
    for c, R, h in rects:
        R = np.asarray(R)
        if not np.allclose(np.abs(R).sum(axis=0), 1, atol=1e-8) or not np.allclose(np.abs(R).sum(axis=1), 1, atol=1e-8):
            raise ValueError("map boundaries require axis-aligned support slabs")
        extent = np.abs(R) @ np.asarray(h)
        lo = np.maximum(np.asarray(c) - extent - centre_xy, -half)
        hi = np.minimum(np.asarray(c) + extent - centre_xy, half)
        if np.all(hi > lo):
            slabs.append((lo, hi))
    if not slabs:
        raise ValueError("map boundary has no support in the configured patch")
    xs, ys = [np.unique(np.round([p[k] for slab in slabs for p in slab], 12)) for k in (0, 1)]
    cells = set()
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            p = np.array([(xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2])
            if any(np.all(p >= lo) and np.all(p <= hi) for lo, hi in slabs):
                cells.add((i, j))
    vertices, faces, ids = [], [], {}

    def quad(corners):
        indices = []
        for i, j, k in corners:
            key = (i, j, k)
            if key not in ids:
                ids[key] = len(vertices)
                vertices.append([xs[i], ys[j], (k - 0.5) * thickness])
            indices.append(ids[key])
        faces.extend([[indices[0], indices[1], indices[2]], [indices[0], indices[2], indices[3]]])

    for i, j in sorted(cells):
        quad([(i, j, 1), (i + 1, j, 1), (i + 1, j + 1, 1), (i, j + 1, 1)])
        quad([(i, j, 0), (i, j + 1, 0), (i + 1, j + 1, 0), (i + 1, j, 0)])
        if (i - 1, j) not in cells:
            quad([(i, j, 0), (i, j, 1), (i, j + 1, 1), (i, j + 1, 0)])
        if (i + 1, j) not in cells:
            quad([(i + 1, j, 0), (i + 1, j + 1, 0), (i + 1, j + 1, 1), (i + 1, j, 1)])
        if (i, j - 1) not in cells:
            quad([(i, j, 0), (i + 1, j, 0), (i + 1, j, 1), (i, j, 1)])
        if (i, j + 1) not in cells:
            quad([(i, j + 1, 0), (i, j + 1, 1), (i + 1, j + 1, 1), (i + 1, j + 1, 0)])
    return np.asarray(vertices), np.asarray(faces, dtype=int)


class LiquidScene:
    def __init__(self, env, coupling: LiquidCoupling, containers: dict, surface_q: queries.Surface | None, cfg: dict):
        self.env, self.coupling, self.fluid = env, coupling, coupling.fluid
        self.containers, self.surface, self.cfg = containers, surface_q, cfg
        self.contact_meshes = {}
        self.patch_groups = {}  # contract 0.6.0: boundary name -> its flex patch boundary names

    def poses(self):
        return self.coupling.poses()

    def labels(self, film: float = 0.02):
        labels = queries.partition(
            self.fluid.positions(), self.containers, self.poses(), self.surface, self.fluid.params.particle_radius, film
        )
        absorbed = ~self.fluid.free_mask
        labels[absorbed] = ["absorbed:" + name for name in self.fluid.absorbed_by[absorbed]]
        return labels

    def wetting_ml(self, name, distance_m=None):
        """Free liquid within two particle spacings of the actual boundary mesh."""
        distance = 2 * self.fluid.params.spacing if distance_m is None else float(distance_m)
        free, poses = self.fluid.positions()[self.fluid.free_mask], self.poses()
        mask = np.zeros(len(free), bool)
        for part in self.patch_groups.get(name, [name]):
            mask |= self.contact_meshes[part].within(free, *poses[part], distance)
        return float(mask.sum()) * self.fluid.params.particle_volume * 1e6

    def volumes_ml(self) -> dict:
        return queries.volumes_ml(self.labels(), self.fluid.params.particle_volume)

    def puddle(self) -> dict:
        lab = self.labels()
        return queries.puddle(
            self.fluid.positions(),
            lab == "surface",
            self.fluid.params.particle_radius,
            surface_z=None if self.surface is None else self.surface.z,
        )

    def report(self) -> dict:
        v = self.volumes_ml()
        return {
            "time_s": self.fluid.time,
            "volumes_ml": {k: round(x, 2) for k, x in v.items()},
            "contract_version": self.cfg.get("contract_version", self.cfg.get("version", "0.2.0")),
            "native_backend": self.fluid.backend,
            "puddle": self.puddle(),
            "sph_steps": self.fluid.steps,
            "absorbers": {a.name: a.report(self.fluid.params.particle_volume) for a in self.coupling.absorbers},
            "sleeping": bool(self.coupling.sleep and self.coupling.sleep.sleeping),
            **({"flex_patches": {k: len(v) for k, v in self.patch_groups.items()}} if self.patch_groups else {}),
        }


def _object_flexes(m, root: int) -> list[int]:
    """Flexes whose vertex bodies all lie in the subtree of body `root` (a pinned-root cloth object)."""
    parent = m.body_parentid

    def under(b):
        b = int(b)
        while b > 0 and b != root:
            b = int(parent[b])
        return b == root

    return [
        f
        for f in range(int(getattr(m, "nflex", 0)))
        if int(m.flex_vertnum[f])
        and all(
            under(b)
            for b in m.flex_vertbodyid[int(m.flex_vertadr[f]) : int(m.flex_vertadr[f]) + int(m.flex_vertnum[f])]
        )
    ]


def attach(env, cfg: dict, workdir, threads: int | None = None, x0: np.ndarray | None = None) -> LiquidScene:
    """Build the liquid for a settled RoboCasa env and install the coupling (see the module docstring). `x0`: an
    initial particle state saved from an earlier attach (`scene.fluid.initial_state()`) to skip the fill and settle."""
    import mujoco

    m = env.sim.model._model
    r = float(cfg.get("particle_radius", 0.00125))
    params = solver.FluidParams(particle_radius=r, **cfg.get("params", {}))
    if cfg.get("absorbers") and params.z_sort:
        raise ValueError("absorption requires stable particle IDs: z_sort=False")
    boundaries, bodies, containers = [], {}, {}
    src = cfg.get("source")
    fill = None
    for name, kind in cfg.get("containers", {}).items():
        prof, filler, visual_geom = container_kind(kind)
        bid = int(env.obj_body_id[name])
        v, f = meshes.mujoco_body_mesh(m, bid, groups=(1,), name_contains=visual_geom, meshes_only=True)
        pos = np.array(env.sim.data.body_xpos[bid], float)
        quat = np.array(env.sim.data.body_xquat[bid], float)
        boundaries.append(solver.Boundary(name, v, f, pos=tuple(pos), quat=tuple(quat), animated=True))
        bodies[name] = bid
        c = prof()
        c.body = name
        containers[name] = c
        if name == src:
            if filler is None:
                raise ValueError(f"{kind} has no fill recipe")
            R = np.array(env.sim.data.body_xmat[bid], float).reshape(3, 3)
            fill = filler(float(cfg["fill_ml"]), params.spacing) @ R.T + pos
    if fill is None and "puddle" not in cfg:
        raise ValueError(f"source {src!r} is not among the containers and no puddle was supplied")
    surf = None
    sc = cfg.get("surface")
    if sc:
        z, rects = _counter_top(env, sc["fixture"], sc.get("geom"))
        names = sc.get("centre_between") or list(cfg.get("containers", {}))
        if "centre_xy" in sc:
            cxy = np.asarray(sc["centre_xy"], float)
        elif names:
            cxy = np.mean([env.sim.data.body_xpos[env.obj_body_id[n]][:2] for n in names], axis=0)
        else:
            cxy = np.mean(np.asarray(cfg["puddle"]["polygon_xy"]), axis=0)
        half = float(sc.get("half_extent_m", 0.22))
        pts = plate_in_rects(cxy, half, rects, z, 1.6 * r)
        pv, pf = meshes.box((half, half, 0.005))
        if params.boundary_method:
            pv, pf = map_plate_mesh(cxy, half, rects)
        origin = np.array([cxy[0], cxy[1], z - 0.005])
        # a boundary's particle file is in its body frame (SPlisHSPlasH moves it to the body's pose)
        boundaries.insert(
            0, solver.Boundary("counter", pv, pf, pos=tuple(origin), animated=False, extra={"samples": pts - origin})
        )
        surf = queries.Surface(z, tuple(cxy - half), tuple(cxy + half), rects=rects)
    if "puddle" in cfg:
        if src is not None or surf is None:
            raise ValueError("a puddle source requires a support surface and no container source")
        pc = cfg["puddle"]
        fill = meshes.puddle_fill(pc["polygon_xy"], float(pc["volume_ml"]), surf.z, params.spacing)
        if not surf.over(fill).all():
            raise ValueError("puddle footprint extends beyond its physical support boundary")
    # General moving objects (cloth, bags, jars, fingers) and fixed wall slabs.
    contract = cfg.get("contract_version", cfg.get("version"))
    pose_sources, patch_groups = [], {}
    for name, bc in cfg.get("boundaries", {}).items():
        if name in bodies or name in patch_groups:
            raise ValueError(f"duplicate liquid boundary {name!r}")
        if "flex_patches" in bc:
            # contract 0.6.0: a deformable flex cloth as piecewise-rigid patches (flex_patches.py)
            from .flex_patches import CONTRACT, FlexPatches

            if contract != CONTRACT:
                raise ValueError(f"flex patch boundaries require liquid contract {CONTRACT}")
            if "body" in bc or not bc.get("animated", True):
                raise ValueError("flex patch boundaries follow an object's flex and are always animated")
            fp = bc["flex_patches"]
            if set(fp) != {"grid", "cells"}:
                raise ValueError("flex_patches needs exactly grid and cells")
            root = int(env.obj_body_id[bc.get("object", name)])
            flexes = _object_flexes(m, root)
            if len(flexes) != 1:
                raise ValueError(f"boundary {name!r}: object must own exactly one flex, found {len(flexes)}")
            group = FlexPatches(m, env.sim.data, name, flexes[0], fp["grid"], fp["cells"])
            initial = group.poses(env.sim.data)
            for part, (v, f) in zip(group.names, group.meshes, strict=True):
                pos, R = initial[part]
                q = np.zeros(4)
                mujoco.mju_mat2Quat(q, np.ascontiguousarray(R).reshape(9))
                boundaries.append(solver.Boundary(part, v, f, pos=tuple(pos), quat=tuple(q), animated=True))
            pose_sources.append(group.poses)
            patch_groups[name] = list(group.names)
            continue
        if "body" in bc:
            bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, bc["body"])
        else:
            bid = int(env.obj_body_id[bc.get("object", name)])
        if bid < 0:
            raise ValueError(f"unknown boundary body {name!r}")
        v, f = meshes.mujoco_body_mesh(
            m,
            bid,
            groups=tuple(bc.get("groups", [0])),
            name_contains=bc.get("name_contains"),
            meshes_only=bc.get("meshes_only", False),
        )
        pos, quat = np.array(env.sim.data.body_xpos[bid]), np.array(env.sim.data.body_xquat[bid])
        animated = bool(bc.get("animated", True))
        boundaries.append(solver.Boundary(name, v, f, pos=tuple(pos), quat=tuple(quat), animated=animated))
        if animated:
            bodies[name] = bid
    if x0 is not None and np.asarray(x0).shape != fill.shape:
        raise ValueError("saved liquid state does not match the configured source volume")
    fluid_type, scene_type, fluid_options = solver.SPHFluid, LiquidScene, {}
    if cfg.get("contract_version", cfg.get("version")) == "0.4.0":
        from .domain_v1 import make_domain
        from .validity_v1 import ValidatedLiquidScene, ValidatedSPHFluid

        fluid_type, scene_type = ValidatedSPHFluid, ValidatedLiquidScene
        fluid_options["domain"] = make_domain(env, cfg["domain"], r)
    if cfg.get("contract_version", cfg.get("version")) == "0.4.1":
        from .domain_v1 import make_domain
        from .validity_v2 import ResolvedLiquidScene, ResolvedSPHFluid

        fluid_type, scene_type = ResolvedSPHFluid, ResolvedLiquidScene
        fluid_options["domain"] = make_domain(env, cfg["domain"], r)
    if cfg.get("contract_version", cfg.get("version")) == "0.4.2":
        from .domain_v1 import make_domain
        from .validity_v3 import PredictiveLiquidScene, PredictiveSPHFluid

        fluid_type, scene_type = PredictiveSPHFluid, PredictiveLiquidScene
        fluid_options["domain"] = make_domain(env, cfg["domain"], r)
    if cfg.get("contract_version", cfg.get("version")) == "0.4.3":
        from .domain_v1 import make_domain
        from .validity_v4 import SubstepContactLiquidScene, SubstepContactSPHFluid

        fluid_type, scene_type = SubstepContactSPHFluid, SubstepContactLiquidScene
        fluid_options["domain"] = make_domain(env, cfg["domain"], r)
    if contract in ("0.5.0", "0.6.0"):  # 0.6.0 = the 0.5.0 GPU solver plus flex patch boundaries
        from .domain_v1 import make_domain
        from .gpu.validity_gpu import ValidatedWarpFluid, ValidatedWarpLiquidScene

        fluid_type, scene_type = ValidatedWarpFluid, ValidatedWarpLiquidScene
        fluid_options["domain"] = make_domain(env, cfg["domain"], r)
    fluid = fluid_type(
        workdir,
        params,
        boundaries,
        fill if x0 is None else x0,
        threads=threads,
        backend=cfg.get("native_backend"),
        **fluid_options,
    )
    if x0 is None and cfg.get("settle_s", 0.3) > 0:
        fluid.settle(float(cfg.get("settle_s", 0.3)), float(cfg.get("settle_damping", 0.9)))
    renderer = None
    if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, surface.GEOM_NAME) >= 0:
        renderer = surface.SurfaceRenderer(m, r, strict=bool(cfg.get("strict_surface", False)))
        # The placeholder starts below the scene. Refresh its derived world pose
        # after SurfaceRenderer moves it to the world origin, before reset images.
        env.sim.forward()
    cpl = LiquidCoupling(env.sim, fluid, bodies, renderer, pose_sources=pose_sources).install()
    ls = scene_type(env, cpl, containers, surf, cfg)
    ls.contact_meshes = {b.name: MeshContact(b.vertices, b.faces) for b in boundaries if b.animated}
    ls.patch_groups = patch_groups
    for name, ac in cfg.get("absorbers", {}).items():
        if name in patch_groups:
            cpl.absorbers.append(
                PatchAbsorber(
                    name,
                    {p: ls.contact_meshes[p] for p in patch_groups[name]},
                    float(ac["capacity_ml"]),
                    float(ac.get("contact_m", params.spacing)),
                )
            )
            continue
        cpl.absorbers.append(
            Absorber(
                name, ls.contact_meshes[name], float(ac["capacity_ml"]), float(ac.get("contact_m", params.spacing))
            )
        )
    if cfg.get("contract_version", cfg.get("version")) == "0.4.3":
        fluid.substep_absorbers = cpl.absorbers
    if contract in ("0.5.0", "0.6.0"):
        fluid.substep_absorbers = cpl.absorbers
    if cfg.get("sleep", {}).get("initially_frozen", False):
        if "puddle" not in cfg or not np.all(ls.labels() == "surface"):
            cpl.uninstall()
            fluid.close()
            raise ValueError("initially_frozen requires every particle in a supported resting puddle")
        cpl.sleep = PuddleSleep(ls.contact_meshes, cpl.poses(), params.spacing)
    if cfg.get("sleep", {}).get("containers", False):
        owners = set(ls.labels())
        if cpl.sleep is not None or not owners <= set(containers):
            cpl.uninstall()
            fluid.close()
            raise ValueError("container sleep requires all liquid inside containers, without puddle sleep")
        cpl.sleep = ContainerSleep(ls.contact_meshes, cpl.poses(), params.spacing, owners)
    env._liquid_scene = ls
    env._liquid_initializing = False
    original_close = env.close

    def close():
        current = getattr(env, "_liquid_scene", None)
        if current is ls:
            cpl.uninstall()
            fluid.close()
            env._liquid_scene = None
        return original_close()

    env.close = close
    return ls


def predicate(env, p):
    """Host-only aggregate predicate. Missing/invalid physics raises, never passes."""
    for key in ("min_ml", "max_ml"):
        if key in p and (not np.isfinite(float(p[key])) or float(p[key]) < 0):
            raise ValueError(f"{key} must be finite and nonnegative")
    if float(p.get("min_ml", 0)) > float(p.get("max_ml", np.inf)):
        raise ValueError("liquid lower bound exceeds upper bound")
    if p.get("measure", "volume") not in ("volume", "wetting"):
        raise ValueError("unknown liquid measurement")
    ls = getattr(env, "_liquid_scene", None)
    if ls is None:
        if getattr(env, "_liquid_initializing", False):
            return False  # only the worker's pre-episode rigid-body settling
        raise RuntimeError("liquid predicate requires an attached liquid scene")
    if not np.isfinite(ls.fluid.positions()).all():
        raise FloatingPointError("nonfinite liquid state")
    volumes = ls.volumes_ml()
    if volumes.get("below", 0) > 0:
        raise RuntimeError("liquid leaked through its support")
    if p.get("measure") == "wetting":
        value = ls.wetting_ml(p["obj"], p.get("distance_m"))
    else:
        region = p["region"]
        valid = set(ls.containers) | {"surface", "elsewhere"} | {"absorbed:" + a.name for a in ls.coupling.absorbers}
        regions = [region] if isinstance(region, str) else region
        if not regions or any(r not in valid for r in regions):
            raise ValueError(f"unknown liquid region {region!r}")
        value = sum(volumes.get(r, 0.0) for r in regions)
    return float(p.get("min_ml", 0)) <= value <= float(p.get("max_ml", np.inf))


def attach_worker(env, cfg):
    """Opt-in worker entry point; initial-state files stay in host-owned asset roots."""
    import hashlib
    import os
    import tempfile
    from pathlib import Path

    root = os.environ.get("ROBOUSE_LIQUID_WORK_ROOT")
    if root:
        Path(root).mkdir(parents=True, exist_ok=True)
    work = tempfile.mkdtemp(prefix="liquid-", dir=root)
    x0 = None
    initial = cfg.get("initial_state")
    if initial:
        asset_root = Path(os.environ["ROBOUSE_ROBOCASA_OBJECT_ROOT"]).resolve()
        path = (asset_root / initial["file"]).resolve()
        if not path.is_relative_to(asset_root):
            raise ValueError("liquid initial state must lie inside the object asset root")
        if hashlib.sha256(path.read_bytes()).hexdigest() != initial["sha256"]:
            raise ValueError("liquid initial-state digest mismatch")
        x0 = np.load(path, allow_pickle=False)
        frame = initial.get("frame", "world")
        if frame == "body":
            body = initial["body"]
            bid = int(env.obj_body_id[body])
            pos = np.asarray(env.sim.data.body_xpos[bid])
            rotation = np.asarray(env.sim.data.body_xmat[bid]).reshape(3, 3)
            x0 = x0 @ rotation.T + pos
        elif frame != "world":
            raise ValueError(f"unknown liquid initial-state frame {frame!r}")
    return attach(env, cfg, work, threads=int(cfg.get("threads", 4)), x0=x0)
