"""ChemLab-Assets behaviour runtimes, driven by the MuJoCo scene.

Each instrument in ChemLab-Assets has a Python runtime: a time-stepped model of the instrument behind the contract's
`describe` / `read` / `invoke` calls, with an agent view and an evaluator view of its state slots. The episode server is
the runtime's trusted host here. After every control step it:
- turns the scene's joints into capability calls, as the contract's scene bindings say (a door's angle into
  `door.set`, the sash's travel into `sash.set`, ...): while the gripper touches the part, the scene leads; when the
  gripper lets go, the runtime may move the part on its own (the fume-hood sash creeping down above its stop), and the
  scene follows it;
- advances the runtime's clock by the control step.
`robo observe` shows the readouts the task names, from the agent view; tasks can be scored on the evaluator view.

The runtime modules are the release's own code (MIT), loaded from the download folder after their SHA-256 is checked
against the pinned manifest. They use only the Python standard library and read the instrument's JSON data files.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import assets


@dataclass(frozen=True)
class Bridge:
    """A joint bound to a runtime state slot: state = (q - offset) / scale, set with `capability`({arg: state, ...})."""

    slot: str
    capability: str
    arg: str
    scale: float = 1.0
    offset: float = 0.0
    held_arg: str = ""  # an argument that says whether the part is being held (the sash's `hold`)
    fixed: dict = field(default_factory=dict)  # further fixed arguments
    tol: float = 1e-4  # joint change (rad or m) that is worth a new call
    # the range the capability accepts; a joint pressed slightly past its limit is passed on at the limit, since the
    # runtime refuses a value outside it (and would keep the last one)
    limits: tuple[float, float] = (-math.inf, math.inf)


@dataclass(frozen=True)
class RuntimeSpec:
    module: str  # dataset path of the runtime module
    cls: str  # its runtime (host) class
    kind: str = "asset"  # "asset": one runtime per instrument; "xpr204e": the balance's multi-instance host
    setup: tuple[tuple[str, dict], ...] = ()  # capability calls after start, by the host
    joints: dict[str, Bridge] = field(default_factory=dict)
    readouts: tuple[str, ...] = ()  # agent-view slots shown by `robo observe`
    files: tuple[str, ...] = ()  # every dataset file the runtime needs (module, sibling modules, data)
    warmup_s: float = 0.0  # simulated time the runtime runs before the episode starts


PKG = "robouse_chemlab_upstream"


def _package(name: str, path: Path) -> None:
    """An empty package for the release's scripts/ folders (their __init__.py files are not run)."""
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = [str(path)]
        sys.modules[name] = m


def _load_module(spec: RuntimeSpec):
    """Import the runtime's module from the download folder, after checking the hash of every module it needs.
    scripts/ becomes one package, so a module's relative imports of its siblings (`from .balance_runtime import ...`)
    resolve inside it."""
    for f in spec.files:
        if f.endswith(".py"):
            assets.verified(f)
    path = assets.verified(spec.module)
    scripts = assets.root() / "scripts"
    rel = Path(spec.module).relative_to("scripts").with_suffix("")  # e.g. asset_runtime/esco_efa5uduvw
    _package(PKG, scripts)
    for i in range(1, len(rel.parts)):
        _package(".".join((PKG, *rel.parts[:i])), scripts.joinpath(*rel.parts[:i]))
    if rel.parts[0] == "asset_runtime":  # some runtimes import their helpers as `from asset_runtime import ...`
        sys.modules.setdefault("asset_runtime", sys.modules[f"{PKG}.asset_runtime"])
    name = ".".join((PKG, *rel.parts))
    if name in sys.modules:
        return sys.modules[name]
    mspec = importlib.util.spec_from_file_location(name, path)
    if mspec is None or mspec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(mspec)
    sys.modules[name] = mod
    try:
        mspec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


class Runtime:
    """One instrument's runtime and its two principals: `host` (evaluator view) and `agent` (agent view)."""

    INSTANCE = "chemlab_01"

    def __init__(self, spec: RuntimeSpec, module: Any = None):
        self.spec = spec
        mod = module if module is not None else _load_module(spec)
        self._n = 0
        if spec.kind == "xpr204e":
            # the scene leads the doors here, so the runtime's scene callback has nothing to do
            self.rt = getattr(mod, spec.cls)(scene_adapter=lambda instance_id, snapshot: None)
            self.rt.create_instance(self.INSTANCE)
            self.rt.register_principal("host", visibility="evaluator")
            self.rt.register_principal("agent", visibility="agent")
        else:
            self.rt = getattr(mod, spec.cls)(self.INSTANCE)
            self.rt.register_principal("host", "evaluator")
            self.rt.register_principal("agent", "agent")
        self.host = self.rt.session("host")
        self.agent = self.rt.session("agent")
        self.log: list[dict] = []  # capability calls the runtime refused (kept for the episode record)
        for cap, args in spec.setup:
            self.invoke(cap, dict(args), must=True)
        self._synced: dict[str, float] = {}  # joint positions last passed to the runtime
        self._held: dict[str, bool] = {}
        self._set_to: dict[str, float] = {}  # the runtime's state right after that
        self._leading: dict[str, Any] = {}  # parts the runtime leads -> its state at the last step

    # ---- calls ---------------------------------------------------------------------------------------------------
    def invoke(self, capability: str, arguments: dict, must: bool = False) -> dict:
        self._n += 1
        r = self.host.invoke(
            instance_id=self.INSTANCE, capability_id=capability, arguments=arguments, request_id=f"robouse-{self._n}"
        )
        if r.get("status") != "succeeded":
            err = (r.get("error") or {}).get("code", r.get("status"))
            if must:
                raise RuntimeError(f"ChemLab runtime refused {capability}({arguments}): {err}")
            if len(self.log) < 50:
                self.log.append({"capability": capability, "arguments": arguments, "error": err})
        return r

    def read(self, view: str = "host") -> dict[str, Any]:
        s = self.host if view == "host" else self.agent
        obs = s.read(instance_id=self.INSTANCE)["observations"]
        return {k: v.get("value") for k, v in obs.items()}

    def step(self, dt: float) -> None:
        if self.spec.kind == "xpr204e":
            self.rt.step(dt, pan_load_forces_N={self.INSTANCE: 0.0})  # an empty pan
        else:
            self.rt.step(dt)

    # ---- the scene ---------------------------------------------------------------------------------------------
    def value(self, joint: str, q: float) -> float:
        b = self.spec.joints[joint]
        return min(max((q - b.offset) / b.scale, b.limits[0]), b.limits[1])

    def joint_target(self, joint: str) -> float | None:
        """Where the runtime has the part, while the runtime leads it (it moved the part on its own and the gripper
        does not hold it: the sash creeping down to its stop); else None. The backend drives the joint there."""
        if joint not in self._leading:
            return None
        b = self.spec.joints[joint]
        v = self.read()[b.slot]
        return float(v) * b.scale + b.offset if isinstance(v, (int, float)) else None

    def sync(self, q: dict[str, float], held: set[str], dt: float) -> None:
        """One control step. The scene leads a bound part: each move of its joint by more than the binding's
        tolerance, and each time the gripper takes hold of it or lets go, becomes a capability call. Then the runtime's
        clock advances; a part it moved on its own meanwhile is led by the runtime, without calls that would set it
        back, until the gripper holds the part again or the part has come to rest where the runtime has it."""
        for joint, b in self.spec.joints.items():
            if joint not in q:
                continue
            h = joint in held
            if joint in self._leading:
                v = self.read()[b.slot]
                steady = v == self._leading[joint]
                if not h and not (steady and abs(q[joint] - self.joint_target(joint)) <= b.tol):  # type: ignore[operator]
                    self._leading[joint] = v
                    continue
                del self._leading[joint]  # back to the scene leading: set it from the joint now
                self._synced.pop(joint, None)
            moved = abs(q[joint] - self._synced.get(joint, math.inf)) > b.tol
            if moved or h != self._held.get(joint):
                args = {b.arg: self.value(joint, q[joint]), **b.fixed}
                if b.held_arg:
                    args[b.held_arg] = h
                self.invoke(b.capability, args)
                self._synced[joint] = q[joint]
                self._held[joint] = h
                v = self.read()[b.slot]
                self._set_to[joint] = float(v) if isinstance(v, (int, float)) else math.nan
        if dt > 0:
            self.step(dt)
        now = self.read() if self._set_to else {}
        for joint, b in self.spec.joints.items():
            v = now.get(b.slot)
            if joint in self._set_to and joint not in self._leading and not self._held.get(joint):
                if isinstance(v, (int, float)) and abs(v - self._set_to[joint]) > 1e-6:
                    self._leading[joint] = v  # the runtime moved the part on its own during this step

    def warm_up(self) -> None:
        t = self.spec.warmup_s
        while t > 1e-9:
            self.step(min(1.0, t))
            t -= 1.0

    def readouts(self) -> dict[str, Any]:
        view = self.read("agent")
        return {k: _round(view.get(k)) for k in self.spec.readouts if k in view}


def _round(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_round(x) for x in v]
    return v
