"""A compiled scene package: what the household backend loads for one episode (`household-episode`, spec 1.1.0; the
benchmark's `docs/specification.md` "Compiled package" and `episode.schema.json` own the format).

    <package>/episode.json   entry point (below); its sha256 is the package's identity
    <package>/scene.xml      the scene's MJCF: z up, metres, paths relative to the package; no robot, cameras,
                             <option>, <size>, <visual>, <statistic>, nor any name starting with `robot/`
    <package>/assets/...     what scene.xml refers to
    <package>/plugin/...     goal.py (`goal:Goal`), behaviour.py (`behaviour:Behaviour`) and their vendored helpers

episode.json: {"format": "household-episode", "format_version": "1.n.y" (n <= 1), "scene": "scene.xml",
  "robot": {"model": "fr3_2f85", "base": {"pos": [3], "quat": [w x y z]},
            "pedestal": {"half_extents_m": [2], "height_m": h, "rgba": [4]},
            "initial_qpos": [7], "initial_gripper_open": 0..1},
  "cameras": {"camera_2": {"pos": [3], "quat": [w x y z] (MuJoCo camera frame: looks along -z, +y up), "fovy_deg": f}},
  "render": {"width": 640, "height": 480}, "control": {"rate_hz": 50, "physics_dt_s": 0.002},
  "budgets": {"max_steps": 45000, "settle_steps": 25, "reset_settle_steps": n},
  "plugins": {"path": "plugin", "goal": null | "goal:Goal", "behaviour": null | "behaviour:Behaviour",
              "behaviour_config": {}, "helpers": null | {"goals": semver, "behaviours": semver}},
  "trace": {"objects": [...], "fixtures": [...], "room": "room"},
  "compute": {"device": "cpu" | "gpu"},  "gpu" exactly when the liquid is on a GPU liquid contract (1.2.0)
  "files": {relpath: sha256, ...},   every other file of the package
  <extension key>: {...}}            optional physics extensions (extensions.py), e.g. a liquid; each key must be
                                     registered there and its module importable

`format_version` follows the spec's minor rule: a minor only adds optional fields or enum values, so this backend
reads any 1.n.y with n <= 1 unchanged (1.0.0 packages included) and refuses a newer minor or another major. Spec 1.1
added liquid contracts 1.1.0 and 1.2.0 and `compute.device` "gpu".

The protocol constants (render, control, budgets other than reset_settle_steps) must equal the backend's own. Nothing
here is shown to the policy; errors name fields, never paths or task names.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import extensions as X
from .robot import CONTROL_DT, PHYSICS_DT, RENDER

FORMAT = "household-episode"
SPEC_MAJOR_MINOR = (1, 1)  # newest spec this backend reads; it reads 1.0.x to 1.1.x
MAX_STEPS_CAP = 45_000  # technical cap: 900 s of robot time at 50 Hz
SETTLE_STEPS = 25  # holding still after `done`, before the goal check
RESERVED_CAMERAS = ("camera_1", "camera_2")


def spec_readable(major: int, minor: int) -> bool:
    """The spec's minor rule: the same major and an earlier or equal minor."""
    return major == SPEC_MAJOR_MINOR[0] and minor <= SPEC_MAJOR_MINOR[1]


_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")
_KEYS = {
    "format",
    "format_version",
    "scene",
    "robot",
    "cameras",
    "render",
    "control",
    "budgets",
    "plugins",
    "trace",
    "compute",
    "files",
}


class PackageError(ValueError):
    """A scene package that does not follow the format (an authoring error, raised before any episode starts)."""


@dataclass
class Episode:
    root: Path
    identity: str  # sha256 of episode.json
    format_version: str
    base_pos: list[float]
    base_quat: list[float]
    pedestal_height: float
    pedestal_half_size: list[float]
    pedestal_rgba: list[float]
    initial_qpos: list[float]
    initial_gripper_open: float
    camera_2: dict  # pos, quat, fovy
    render_size: tuple[int, int]
    max_steps: int
    settle_steps: int
    reset_settle_steps: int
    plugin_dir: Path
    goal: str | None
    behaviour: str | None
    behaviour_config: dict
    helpers: dict | None
    trace: dict
    files: dict = field(default_factory=dict)
    extensions: dict = field(default_factory=dict)  # episode.json key -> that extension's config (extensions.py)

    @property
    def scene_xml(self) -> Path:
        return self.root / "scene.xml"


def _vec(x, n: int, what: str) -> list[float]:
    if not (
        isinstance(x, list) and len(x) == n and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x)
    ):
        raise PackageError(f"{what} must be a list of {n} numbers")
    return [float(v) for v in x]


def _quat(x, what: str) -> list[float]:
    q = _vec(x, 4, what)
    n = sum(v * v for v in q) ** 0.5
    if abs(n - 1.0) > 1e-3:
        raise PackageError(f"{what} must be a unit quaternion (w, x, y, z)")
    return [v / n for v in q]


def _obj(d, key: str, keys: set[str]) -> dict:
    v = d.get(key)
    if not isinstance(v, dict):
        raise PackageError(f"episode.json needs an object `{key}`")
    if missing := keys - set(v):
        raise PackageError(f"`{key}` is missing {sorted(missing)}")
    if extra := set(v) - keys:
        raise PackageError(f"`{key}` has unknown fields {sorted(extra)}")
    return v


def _const(v, want, what: str) -> None:
    if v != want:
        raise PackageError(f"{what} must be {want} (the protocol's), not {v!r}")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_files(root: Path, files: dict) -> None:
    """Every listed file exists with its sha256, and the package holds no other file (Python's caches aside)."""
    if not isinstance(files, dict) or "scene.xml" not in files:
        raise PackageError("`files` must map every package file (scene.xml included) to its sha256")
    for rel, digest in files.items():
        if not (isinstance(rel, str) and _FILE_RE.match(rel) and ".." not in rel.split("/")):
            raise PackageError("`files` has a path that is not a plain relative path")
        if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise PackageError("`files` has a value that is not a sha256")
        p = root / rel
        if not p.is_file() or p.is_symlink():
            raise PackageError("a file listed in `files` is missing")
        if sha256_file(p) != digest:
            raise PackageError("a package file differs from its sha256 in `files`")
    listed = set(files) | {"episode.json"}
    for p in root.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            if p.relative_to(root).as_posix() not in listed:
                raise PackageError("the package holds a file that `files` does not list")


def load(root, *, verify_files: bool = True) -> Episode:
    root = Path(root)
    ep_file = root / "episode.json"
    if not ep_file.is_file():
        raise PackageError("a scene package needs episode.json")
    raw = ep_file.read_bytes()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        raise PackageError("episode.json is not valid JSON") from None
    if not isinstance(d, dict):
        raise PackageError("episode.json must be an object")
    if extra := set(d) - _KEYS - set(X.EXTENSIONS):
        raise PackageError(f"episode.json has unknown fields {sorted(extra)}")
    if d.get("format") != FORMAT:
        raise PackageError(f"episode.json format must be {FORMAT!r}")
    ver = d.get("format_version")
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", ver) if isinstance(ver, str) else None
    if not m or not spec_readable(int(m[1]), int(m[2])):
        raise PackageError(
            f"format_version must be {SPEC_MAJOR_MINOR[0]}.0.x to {SPEC_MAJOR_MINOR[0]}.{SPEC_MAJOR_MINOR[1]}.x"
        )
    ext = {k: d[k] for k in X.EXTENSIONS if k in d}
    for k in ext:
        if X.load_class(k) is None:
            raise PackageError(f"{k} packages are not supported by this backend version")
    _const(d.get("scene"), "scene.xml", "scene")
    r = _obj(d, "robot", {"model", "base", "pedestal", "initial_qpos", "initial_gripper_open"})
    _const(r["model"], "fr3_2f85", "robot.model")
    base = _obj(r, "base", {"pos", "quat"})
    ped = _obj(r, "pedestal", {"half_extents_m", "height_m", "rgba"})
    half = _vec(ped["half_extents_m"], 2, "robot.pedestal.half_extents_m")
    height = ped["height_m"]
    if not isinstance(height, (int, float)) or height < 0 or any(v <= 0 for v in half):
        raise PackageError("robot.pedestal sizes must be positive (height_m may be 0: no pedestal)")
    rgba = _vec(ped["rgba"], 4, "robot.pedestal.rgba")
    g0 = r["initial_gripper_open"]
    if not isinstance(g0, (int, float)) or not 0 <= g0 <= 1:
        raise PackageError("robot.initial_gripper_open must be in [0, 1]")
    cams = _obj(d, "cameras", {"camera_2"})
    c2 = _obj(cams, "camera_2", {"pos", "quat", "fovy_deg"})
    fovy = c2["fovy_deg"]
    if not isinstance(fovy, (int, float)) or not 20 <= fovy <= 100:
        raise PackageError("camera_2.fovy_deg must be in [20, 100]")
    rs = _obj(d, "render", {"width", "height"})
    _const([rs["width"], rs["height"]], [RENDER["width"], RENDER["height"]], "render width, height")
    ctl = _obj(d, "control", {"rate_hz", "physics_dt_s"})
    _const(ctl["rate_hz"], round(1 / CONTROL_DT), "control.rate_hz")
    _const(ctl["physics_dt_s"], PHYSICS_DT, "control.physics_dt_s")
    b = _obj(d, "budgets", {"max_steps", "settle_steps", "reset_settle_steps"})
    _const(b["max_steps"], MAX_STEPS_CAP, "budgets.max_steps")
    _const(b["settle_steps"], SETTLE_STEPS, "budgets.settle_steps")
    rss = b["reset_settle_steps"]
    if not isinstance(rss, int) or isinstance(rss, bool) or not 0 <= rss <= 500:
        raise PackageError("budgets.reset_settle_steps must be an integer in [0, 500]")
    pl = _obj(d, "plugins", {"path", "goal", "behaviour", "behaviour_config", "helpers"})
    _const(pl["path"], "plugin", "plugins.path")
    if pl["goal"] not in (None, "goal:Goal"):
        raise PackageError("plugins.goal must be null or 'goal:Goal'")
    if pl["behaviour"] not in (None, "behaviour:Behaviour"):
        raise PackageError("plugins.behaviour must be null or 'behaviour:Behaviour'")
    if not isinstance(pl["behaviour_config"], dict):
        raise PackageError("plugins.behaviour_config must be an object")
    helpers = pl["helpers"]  # versions of the vendored helper packages; part of the package identity
    if helpers is not None:
        if not isinstance(helpers, dict) or set(helpers) != {"goals", "behaviours"}:
            raise PackageError("plugins.helpers must be null or {goals, behaviours}")
        if not all(isinstance(v, str) and _SEMVER_RE.match(v) for v in helpers.values()):
            raise PackageError("plugins.helpers versions must be semver strings")
    tr = _obj(d, "trace", {"objects", "fixtures", "room"})
    comp = _obj(d, "compute", {"device"})
    if comp["device"] not in ("cpu", "gpu"):
        raise PackageError("compute.device must be cpu or gpu")
    if comp["device"] != _device(ext):
        raise PackageError(
            "compute.device gpu needs a liquid on a GPU liquid contract, and a GPU liquid contract needs compute.device"
            " gpu"
        )
    files = d.get("files")
    if verify_files:
        check_files(root, files)
    return Episode(
        root=root,
        identity=hashlib.sha256(raw).hexdigest(),
        format_version=ver,
        base_pos=_vec(base["pos"], 3, "robot.base.pos"),
        base_quat=_quat(base["quat"], "robot.base.quat"),
        pedestal_height=float(height),
        pedestal_half_size=half,
        pedestal_rgba=rgba,
        initial_qpos=_vec(r["initial_qpos"], 7, "robot.initial_qpos"),
        initial_gripper_open=float(g0),
        camera_2={
            "pos": _vec(c2["pos"], 3, "camera_2.pos"),
            "quat": _quat(c2["quat"], "camera_2.quat"),
            "fovy": float(fovy),
        },
        render_size=(RENDER["width"], RENDER["height"]),
        max_steps=MAX_STEPS_CAP,
        settle_steps=SETTLE_STEPS,
        reset_settle_steps=int(rss),
        plugin_dir=root / "plugin",
        goal=pl["goal"],
        behaviour=pl["behaviour"],
        behaviour_config=dict(pl["behaviour_config"]),
        helpers=dict(helpers) if helpers is not None else None,
        trace=dict(tr),
        files=dict(files or {}),
        extensions=ext,
    )


def _device(ext: dict) -> str:
    """The device the package's physics extensions need: "gpu" only for a liquid on a GPU liquid contract (liquid
    contract 1.2.0; only the liquid runs there, rigid MuJoCo and rendering stay on the CPU)."""
    liquid = ext.get("liquid")
    if isinstance(liquid, dict):
        from .liquid.config import GPU_CONTRACTS

        if liquid.get("contract") in GPU_CONTRACTS:
            return "gpu"
    return "cpu"


def check_scene(spec) -> None:
    """The scene leaves the robot's namespace, the cameras and the physics and rendering options to the backend."""
    for kind in (
        "bodies",
        "geoms",
        "sites",
        "joints",
        "cameras",
        "actuators",
        "frames",
        "tendons",
        "equalities",
        "sensors",
        "lights",
        "materials",
        "textures",
        "meshes",
    ):
        for el in getattr(spec, kind, ()):
            name = el.name or ""
            if name.startswith("robot/"):
                raise PackageError(f"scene.xml must not name anything robot/... ({kind[:-1]})")
    if len(spec.cameras):
        raise PackageError("scene.xml must not define cameras (the backend adds camera_1 and camera_2)")


def write_files_map(root) -> dict:
    """Fill `files` of <root>/episode.json with every other file's sha256 (for tests and hand-made packages)."""
    root = Path(root)
    files = {
        p.relative_to(root).as_posix(): sha256_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "episode.json" and "__pycache__" not in p.parts
    }
    d = json.loads((root / "episode.json").read_text())
    d["files"] = files
    (root / "episode.json").write_text(json.dumps(d, indent=2) + "\n")
    return files
