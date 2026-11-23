"""The `liquid` block of a household package's episode.json (liquid contract 1.0.0), validated strictly.

Every value is explicit: there are no defaults, so a package states its whole liquid condition (material, solver,
geometry, sources, absorbers, settling, sleep, threads, backend) and any change to it is visible in the package
identity. Errors name fields, never paths or task names.

    {"contract": "1.0.0",
     "backend": "splishsplash-2.19.0-tree-f32-avx2-v1",       a pin in backends/<id>.json
     "threads": 4,                                              SPlisHSPlasH OpenMP threads (results depend on it)
     "material": {"particle_radius_m": 0.00125, "density_kg_m3": 1000, "viscosity_m2_s": 1e-4,
                  "boundary_viscosity_m2_s": 1e-3,
                  "surface_tension": {"method": "none", "coefficient": 0, "boundary_adhesion": 0},
                  "rgba": [1, 0.56, 0.1, 0.93]},
     "solver": {"cfl": 0.5, "dt_min_s": 5e-5, "dt_max_s": 0.002, "max_density_error_pct": 0.05,
                "max_divergence_error_pct": 0.1, "max_iterations": 100},
     "domain": {"static_box_geoms": ["room/floor", "counter/top", ...], "floor_geom": "room/floor"},
     "containers": [{"name": "cup", "body": "cup", "boundary_geoms": ["cup/glass"],
                     "inside_profile": [[r, z], ...], "slack_m": 0.0015}],
     "boundaries": [{"name": "sponge", "body": "sponge", "geoms": ["sponge/foam"], "animated": true}],
     "surface": {"geom": "counter/top", "centre_xy": [x, y], "half_extent_m": 0.22, "film_m": 0.02} | null,
     "sources": [{"name": "juice", "container": "cup", "fill_ml": 150},
                 {"name": "spill", "puddle": {"polygon_xy": [[x, y], ...], "volume_ml": 40}}],
     "absorbers": [{"boundary": "sponge", "capacity_ml": 100, "contact_m": 0.0025}],
     "settle": {"seconds": 0.3, "damping": 0.9},
     "sleep": "none" | "puddle" | "containers",
     "initial_state": null | {"file": "liquid/initial_state.npy", "sha256": "...", "frame": "world"}}
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

CONTRACT = "1.0.0"
TENSION_METHODS = {"none": 0, "becker2007": 1, "akinci2013": 2, "he2014": 3, "jeske2023": 4}
SLEEP = ("none", "puddle", "containers")
MAX_THREADS = 64
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,127}")
_FILE = re.compile(r"liquid/[A-Za-z0-9_.\-]{1,96}\.npy")


class LiquidConfigError(ValueError):
    """The liquid block does not satisfy contract 1.0.0."""


def _fail(msg: str):
    raise LiquidConfigError(f"liquid: {msg}")


def _obj(v, what: str, keys: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(v, dict):
        _fail(f"{what} must be an object")
    if missing := keys - set(v):
        _fail(f"{what} is missing {sorted(missing)}")
    if extra := set(v) - keys - set(optional):
        _fail(f"{what} has unknown fields {sorted(extra)}")
    return v


def _num(v, what: str, lo: float | None = None, hi: float | None = None, lo_open=False) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        _fail(f"{what} must be a finite number")
    v = float(v)
    if lo is not None and (v < lo or (lo_open and v == lo)):
        _fail(f"{what} must be {'>' if lo_open else '>='} {lo}")
    if hi is not None and v > hi:
        _fail(f"{what} must be <= {hi}")
    return v


def _int(v, what: str, lo: int, hi: int) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        _fail(f"{what} must be an integer in [{lo}, {hi}]")
    return int(v)


def _name(v, what: str) -> str:
    if not isinstance(v, str) or not _NAME.fullmatch(v) or v.startswith("robot/") or v.startswith("liquid/"):
        _fail(f"{what} must be a scene element name (not robot/... or liquid/...)")
    return v


def _names(v, what: str, nonempty=True) -> list[str]:
    if not isinstance(v, list) or (nonempty and not v):
        _fail(f"{what} must be a {'nonempty ' if nonempty else ''}list of names")
    out = [_name(x, what) for x in v]
    if len(set(out)) != len(out):
        _fail(f"{what} has duplicates")
    return out


def _vec(v, n: int, what: str) -> list[float]:
    if not isinstance(v, list) or len(v) != n:
        _fail(f"{what} must be a list of {n} numbers")
    return [_num(x, what) for x in v]


@dataclass(frozen=True)
class Material:
    particle_radius: float
    density: float
    viscosity: float
    boundary_viscosity: float
    tension_method: str
    tension: float
    adhesion: float
    rgba: tuple

    @property
    def spacing(self) -> float:
        return 2 * self.particle_radius

    @property
    def particle_volume(self) -> float:
        """Liquid volume one particle stands for, m^3: (2r)^3 (a cubic lattice of pitch 2r is at rest density)."""
        return self.spacing**3

    @property
    def particle_ml(self) -> float:
        return self.particle_volume * 1e6


@dataclass(frozen=True)
class Solver:
    cfl: float
    dt_min: float
    dt_max: float
    max_error: float
    max_error_v: float
    max_iterations: int


@dataclass(frozen=True)
class Container:
    name: str
    body: str
    boundary_geoms: tuple
    profile: tuple  # ((r, z), ...) body frame, z increasing
    slack: float


@dataclass(frozen=True)
class Boundary:
    name: str
    body: str
    geoms: tuple
    animated: bool


@dataclass(frozen=True)
class Surface:
    geom: str
    centre_xy: tuple
    half_extent: float
    film: float


@dataclass(frozen=True)
class Source:
    name: str
    container: str | None
    fill_ml: float | None
    polygon_xy: tuple | None
    puddle_ml: float | None


@dataclass(frozen=True)
class Absorber:
    boundary: str
    capacity_ml: float
    contact_m: float


@dataclass(frozen=True)
class InitialState:
    file: str
    sha256: str


@dataclass(frozen=True)
class LiquidConfig:
    contract: str
    backend: str
    threads: int
    material: Material
    solver: Solver
    static_box_geoms: tuple
    floor_geom: str
    containers: tuple
    boundaries: tuple
    surface: Surface | None
    sources: tuple
    absorbers: tuple
    settle_seconds: float
    settle_damping: float
    sleep: str
    initial_state: InitialState | None

    def boundary_names(self) -> list[str]:
        return [c.name for c in self.containers] + [b.name for b in self.boundaries]


KEYS = {
    "contract",
    "backend",
    "threads",
    "material",
    "solver",
    "domain",
    "containers",
    "boundaries",
    "surface",
    "sources",
    "absorbers",
    "settle",
    "sleep",
    "initial_state",
}


def parse(d) -> LiquidConfig:
    """The validated configuration, or LiquidConfigError naming the first problem."""
    d = _obj(d, "the liquid block", KEYS)
    if d["contract"] != CONTRACT:
        _fail(f"contract must be {CONTRACT!r} (the only liquid contract this backend implements)")
    if not isinstance(d["backend"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9.\-]{0,95}", d["backend"]):
        _fail("backend must be a backend id")
    threads = _int(d["threads"], "threads", 1, MAX_THREADS)

    m = _obj(
        d["material"],
        "material",
        {
            "particle_radius_m",
            "density_kg_m3",
            "viscosity_m2_s",
            "boundary_viscosity_m2_s",
            "surface_tension",
            "rgba",
        },
    )
    st = _obj(m["surface_tension"], "material.surface_tension", {"method", "coefficient", "boundary_adhesion"})
    if st["method"] not in TENSION_METHODS:
        _fail(f"material.surface_tension.method must be one of {sorted(TENSION_METHODS)}")
    tension = _num(st["coefficient"], "material.surface_tension.coefficient", 0, 1)
    adhesion = _num(st["boundary_adhesion"], "material.surface_tension.boundary_adhesion", 0, 1)
    if st["method"] == "none" and (tension or adhesion):
        _fail("material.surface_tension: method none needs coefficient and boundary_adhesion 0")
    if st["method"] != "none" and not (tension or adhesion):
        _fail("material.surface_tension: a method needs a nonzero coefficient or boundary_adhesion")
    rgba = _vec(m["rgba"], 4, "material.rgba")
    if any(not 0 <= v <= 1 for v in rgba):
        _fail("material.rgba values must be in [0, 1]")
    material = Material(
        particle_radius=_num(m["particle_radius_m"], "material.particle_radius_m", 0.0005, 0.005),
        density=_num(m["density_kg_m3"], "material.density_kg_m3", 100, 5000),
        viscosity=_num(m["viscosity_m2_s"], "material.viscosity_m2_s", 0, 1),
        boundary_viscosity=_num(m["boundary_viscosity_m2_s"], "material.boundary_viscosity_m2_s", 0, 1),
        tension_method=st["method"],
        tension=tension,
        adhesion=adhesion,
        rgba=tuple(rgba),
    )

    s = _obj(
        d["solver"],
        "solver",
        {"cfl", "dt_min_s", "dt_max_s", "max_density_error_pct", "max_divergence_error_pct", "max_iterations"},
    )
    solver = Solver(
        cfl=_num(s["cfl"], "solver.cfl", 0, 1, lo_open=True),
        dt_min=_num(s["dt_min_s"], "solver.dt_min_s", 0, 0.002, lo_open=True),
        dt_max=_num(s["dt_max_s"], "solver.dt_max_s", 0, 0.002, lo_open=True),
        max_error=_num(s["max_density_error_pct"], "solver.max_density_error_pct", 0, 10, lo_open=True),
        max_error_v=_num(s["max_divergence_error_pct"], "solver.max_divergence_error_pct", 0, 10, lo_open=True),
        max_iterations=_int(s["max_iterations"], "solver.max_iterations", 1, 10000),
    )
    if solver.dt_min > solver.dt_max:
        _fail("solver.dt_min_s must not exceed solver.dt_max_s")

    dom = _obj(d["domain"], "domain", {"static_box_geoms", "floor_geom"})
    boxes = _names(dom["static_box_geoms"], "domain.static_box_geoms")
    floor = _name(dom["floor_geom"], "domain.floor_geom")
    if floor not in boxes:
        _fail("domain.floor_geom must be one of domain.static_box_geoms")

    if not isinstance(d["containers"], list):
        _fail("containers must be a list")
    containers = []
    for i, c in enumerate(d["containers"]):
        w = f"containers[{i}]"
        c = _obj(c, w, {"name", "body", "boundary_geoms", "inside_profile", "slack_m"})
        prof = c["inside_profile"]
        if not isinstance(prof, list) or len(prof) < 2:
            _fail(f"{w}.inside_profile must list at least two [r, z] points")
        pts = [tuple(_vec(p, 2, f"{w}.inside_profile")) for p in prof]
        if any(r < 0 for r, _ in pts) or any(b[1] <= a[1] for a, b in zip(pts, pts[1:], strict=False)):
            _fail(f"{w}.inside_profile needs r >= 0 and strictly increasing z")
        if max(r for r, _ in pts) <= 0:
            _fail(f"{w}.inside_profile has no opening")
        containers.append(
            Container(
                name=_name(c["name"], f"{w}.name"),
                body=_name(c["body"], f"{w}.body"),
                boundary_geoms=tuple(_names(c["boundary_geoms"], f"{w}.boundary_geoms")),
                profile=tuple(pts),
                slack=_num(c["slack_m"], f"{w}.slack_m", 0, 0.01),
            )
        )

    if not isinstance(d["boundaries"], list):
        _fail("boundaries must be a list")
    boundaries = []
    for i, b in enumerate(d["boundaries"]):
        w = f"boundaries[{i}]"
        b = _obj(b, w, {"name", "body", "geoms", "animated"})
        if not isinstance(b["animated"], bool):
            _fail(f"{w}.animated must be true or false")
        boundaries.append(
            Boundary(
                name=_name(b["name"], f"{w}.name"),
                body=_name(b["body"], f"{w}.body"),
                geoms=tuple(_names(b["geoms"], f"{w}.geoms")),
                animated=b["animated"],
            )
        )
    names = [c.name for c in containers] + [b.name for b in boundaries]
    if len(set(names)) != len(names):
        _fail("container and boundary names must be unique together")
    if "surface" in names:
        _fail("`surface` is reserved for the work surface's boundary")

    surface = None
    if d["surface"] is not None:
        sf = _obj(d["surface"], "surface", {"geom", "centre_xy", "half_extent_m", "film_m"})
        surface = Surface(
            geom=_name(sf["geom"], "surface.geom"),
            centre_xy=tuple(_vec(sf["centre_xy"], 2, "surface.centre_xy")),
            half_extent=_num(sf["half_extent_m"], "surface.half_extent_m", 0, 2, lo_open=True),
            film=_num(sf["film_m"], "surface.film_m", 0, 0.2, lo_open=True),
        )

    if not isinstance(d["sources"], list) or not d["sources"]:
        _fail("sources must be a nonempty list")
    sources = []
    cnames = {c.name for c in containers}
    for i, s in enumerate(d["sources"]):
        w = f"sources[{i}]"
        if not isinstance(s, dict):
            _fail(f"{w} must be an object")
        if "container" in s:
            s = _obj(s, w, {"name", "container", "fill_ml"})
            if s["container"] not in cnames:
                _fail(f"{w}.container must name one of the containers")
            sources.append(
                Source(
                    _name(s["name"], f"{w}.name"),
                    s["container"],
                    _num(s["fill_ml"], f"{w}.fill_ml", 0, 5000, lo_open=True),
                    None,
                    None,
                )
            )
        else:
            s = _obj(s, w, {"name", "puddle"})
            p = _obj(s["puddle"], f"{w}.puddle", {"polygon_xy", "volume_ml"})
            poly = p["polygon_xy"]
            if not isinstance(poly, list) or len(poly) < 3:
                _fail(f"{w}.puddle.polygon_xy must list at least three [x, y] points")
            if surface is None:
                _fail(f"{w}: a puddle source needs a surface")
            sources.append(
                Source(
                    _name(s["name"], f"{w}.name"),
                    None,
                    None,
                    tuple(tuple(_vec(q, 2, f"{w}.puddle.polygon_xy")) for q in poly),
                    _num(p["volume_ml"], f"{w}.puddle.volume_ml", 0, 5000, lo_open=True),
                )
            )
    if len({s.name for s in sources}) != len(sources):
        _fail("source names must be unique")

    if not isinstance(d["absorbers"], list):
        _fail("absorbers must be a list")
    absorbers = []
    for i, a in enumerate(d["absorbers"]):
        w = f"absorbers[{i}]"
        a = _obj(a, w, {"boundary", "capacity_ml", "contact_m"})
        animated = {b.name for b in boundaries if b.animated} | cnames
        if a["boundary"] not in animated:
            _fail(f"{w}.boundary must name an animated boundary or a container")
        absorbers.append(
            Absorber(
                a["boundary"],
                _num(a["capacity_ml"], f"{w}.capacity_ml", 0, 5000, lo_open=True),
                _num(a["contact_m"], f"{w}.contact_m", 0, 0.05),
            )
        )
    if len({a.boundary for a in absorbers}) != len(absorbers):
        _fail("a boundary has at most one absorber")

    se = _obj(d["settle"], "settle", {"seconds", "damping"})
    sleep = d["sleep"]
    if sleep not in SLEEP:
        _fail(f"sleep must be one of {list(SLEEP)}")
    if sleep == "puddle" and any(s.container for s in sources):
        _fail("sleep puddle needs puddle sources only")
    if sleep == "containers" and any(s.container is None for s in sources):
        _fail("sleep containers needs container sources only")

    init = None
    if d["initial_state"] is not None:
        it = _obj(d["initial_state"], "initial_state", {"file", "sha256", "frame"})
        if not isinstance(it["file"], str) or not _FILE.fullmatch(it["file"]):
            _fail("initial_state.file must be liquid/<name>.npy in the package")
        if not isinstance(it["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", it["sha256"]):
            _fail("initial_state.sha256 must be a sha256")
        if it["frame"] != "world":
            _fail("initial_state.frame must be world")
        init = InitialState(it["file"], it["sha256"])

    return LiquidConfig(
        contract=CONTRACT,
        backend=d["backend"],
        threads=threads,
        material=material,
        solver=solver,
        static_box_geoms=tuple(boxes),
        floor_geom=floor,
        containers=tuple(containers),
        boundaries=tuple(boundaries),
        surface=surface,
        sources=tuple(sources),
        absorbers=tuple(absorbers),
        settle_seconds=_num(se["seconds"], "settle.seconds", 0, 10),
        settle_damping=_num(se["damping"], "settle.damping", 0, 1, lo_open=True),
        sleep=sleep,
        initial_state=init,
    )
