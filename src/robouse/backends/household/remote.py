"""The household backend with its simulation in a worker process (ROBOUSE_HOUSEHOLD_PYTHON set; worker.py).

`HouseholdBackend(spec)` returns this class when the variable is set, so the episode server keeps no MuJoCo state of
its own: the worker interpreter (or a wrapper that runs it on a compute allocation) loads the package, steps the
physics, renders and writes the physical-state trace into the run folder (which must be on a filesystem the worker
sees). Replies, refusals and errors are the in-process backend's, unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from ..base import ActionSpec, Backend, StepInfo

WORKER = Path(__file__).with_name("worker.py")
SRC = Path(__file__).resolve().parents[3]  # the folder holding the `robouse` package, for the worker's import path

# the backend methods the worker serves through its generic `call` (session hooks and the rest of the interface)
PLAIN = frozenset(
    {
        "observe",
        "skills",
        "info_extra",
        "hold_action",
        "grip_action",
        "success",
        "session_summary",
        "pop_notes",
        "infrastructure_error",
        "hand_pos",
        "begin_settle",
    }
)


class _Pending(dict):
    """The row a worker-side skill produced: stepped in the worker, never sent over."""


class RemoteHouseholdBackend(Backend):
    name = "household"
    robot_name = "fr3-2f85"
    robot_kind = "arm"
    probe_success = False
    image_flipped = False

    def __init__(self, spec: dict):
        from ...workers.client import StdioWorker
        from .backend import resolve_package, worker_python

        self.spec = spec
        # paths resolve here, against the host's task folder, so the worker gets absolute ones
        local = {**spec, "package": str(resolve_package(spec).resolve())}
        local.pop("task_dir", None)
        python = worker_python()
        pp = os.environ.get("PYTHONPATH", "")
        self.worker = StdioWorker(
            "household",
            Path(python),
            WORKER,
            env={"ROBOUSE_HOUSEHOLD_PYTHON": "", "PYTHONPATH": os.pathsep.join(p for p in (str(SRC), pp) if p)},
            cwd=Path.cwd(),
            setup="ROBOUSE_HOUSEHOLD_PYTHON",
        )
        self._spec_local = local
        self._run_dir: str | None = None
        self._opened = False
        self._hand: np.ndarray | None = None

    # ---- transport ---------------------------------------------------------------------------------------------------
    def _r(self, out: dict):
        if "raise" in out:
            from .sim import InternalError, Refused, SimulationDiverged

            e = out["raise"]
            t = e["type"]
            if t == "Refused":
                raise Refused(e["reason"], e["detail"])
            if t == "InternalError":
                raise InternalError()
            if t == "SimulationDiverged":
                raise SimulationDiverged(e["message"])
            raise ValueError(e["message"])
        return out.get("value")

    def _call(self, name: str, *args):
        return self._r(self.worker.call("call", name=name, args=list(args)))

    def _open(self) -> None:
        if self._opened:
            return
        d = self._r(self.worker.call("open", spec=self._spec_local, run_dir=self._run_dir))
        s = d["action_spec"]
        self.action_spec = ActionSpec(names=s["names"], low=s["low"], high=s["high"], doc=s["doc"])
        self.max_steps = int(d["max_steps"])
        self.settle_steps = int(d["settle_steps"])
        self.camera = str(d["camera"])
        self.render_size = tuple(d["render_size"])
        self.control = d["control"]
        self._embodiment = d["embodiment"]
        self.hz = d["hz"]
        self._opened = True

    def __getattr__(self, name: str):
        # the static description (action_spec, max_steps, settle_steps, camera, ...) is read from the worker on first
        # use: after attach_run_dir, which the session calls right after construction, so the trace goes there
        if name.startswith("__") or name in ("worker", "_opened", "_spec_local", "_run_dir", "_hand"):
            raise AttributeError(name)
        if not self.__dict__.get("_opened") and "worker" in self.__dict__:
            self._open()
            return getattr(self, name)
        raise AttributeError(name)

    # ---- session hooks -----------------------------------------------------------------------------------------------
    def attach_run_dir(self, run_dir) -> None:
        if self._opened:
            raise RuntimeError("attach_run_dir must come before the episode starts")
        self._run_dir = str(Path(run_dir).resolve())
        self._open()

    def embodiment(self) -> dict:
        self._open()
        return dict(self._embodiment)

    def reset(self, seed: int) -> None:
        self._open()
        self._r(self.worker.call("reset", seed=int(seed)))
        self._hand = None

    def step(self, action) -> StepInfo:
        if isinstance(action, _Pending):
            r = self._r(self.worker.call("step", pending=True))
        else:
            if not isinstance(action, dict):
                action = [float(x) for x in np.asarray(action, dtype=float).ravel()]
            r = self._r(self.worker.call("step", action=action))
        self._hand = np.asarray(r["hand"], dtype=float)
        return StepInfo(success=bool(r["success"]))

    def observe(self) -> dict:
        return self._call("observe")

    def skills(self) -> list[str]:
        return self._call("skills")

    def info_extra(self) -> dict:
        return self._call("info_extra")

    def hold_action(self) -> list[float]:
        return self._call("hold_action")

    def grip_action(self, value: float) -> dict:
        return self._call("grip_action", float(value))

    def success(self) -> bool:
        return bool(self._call("success"))

    def session_summary(self) -> dict:
        if self.__dict__.get("_final_summary") is not None:  # after close: the worker has exited
            return self._final_summary
        return self._call("session_summary")

    def pop_notes(self) -> list[dict]:
        return self._call("pop_notes")

    def infrastructure_error(self) -> str | None:
        return self._call("infrastructure_error")

    def begin_settle(self) -> None:
        self._call("begin_settle")

    def hand_pos(self) -> np.ndarray:
        return np.asarray(self._call("hand_pos"), dtype=float)

    def metrics_point(self) -> np.ndarray | None:
        return self._hand

    @property
    def _grip(self) -> float:
        return float(self.worker.call("grip_value"))

    def render(self, width: int | None = None, height: int | None = None) -> np.ndarray:
        self._open()
        w, h = (width, height) if width and height else self.render_size
        return self.worker.call("render", camera=self.camera, width=int(w), height=int(h))

    def camera_info(self, cameras: list[str]) -> list[dict]:
        uncal = list(self.spec.get("uncalibrated_cameras", []))
        return self.worker.call("camera_info", cameras=list(cameras), uncalibrated=uncal)

    # ---- skills: the generator runs in the worker ----------------------------------------------------------------
    def start_skill(self, name: str, raw: list[str]):
        self._r(self.worker.call("start_skill", name=name, raw=[str(a) for a in raw]))
        return self._drive()

    def start_move_to(self, pos, grip, max_steps: int, tol: float):
        p = [float(x) for x in np.asarray(pos, dtype=float).ravel()]
        g = None if grip is None else float(grip)
        self._r(self.worker.call("start_move_to", pos=p, grip=g, max_steps=int(max_steps), tol=float(tol)))
        return self._drive()

    def _drive(self):
        try:
            while True:
                r = self.worker.call("skill_next")
                if "done" in r:
                    return r["done"]
                self._r(r)
                yield _Pending()
        finally:
            if self.worker.alive:
                self.worker.call("skill_close")

    def close(self) -> None:
        try:
            if self.worker.alive and self._opened:
                self._final_summary = self.worker.call("close_episode")
        finally:
            self.worker.close()
