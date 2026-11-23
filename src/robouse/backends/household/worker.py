"""The household simulation in a worker process (ROBOUSE_HOUSEHOLD_PYTHON; the host side is remote.py).

Started by robouse's StdioWorker as `<interpreter> wire.py worker.py`, where the interpreter may be a wrapper that runs
it on another machine (a compute allocation). It runs an ordinary in-process HouseholdBackend and serves its methods;
the host never imports MuJoCo. Errors the policy may see (refusals, invalid rows, internal errors) come back as
{"raise": {...}} results and are raised again on the host with the same type and message.
"""

from __future__ import annotations

import os

import numpy as np


def _raise_info(e: Exception) -> dict | None:
    from robouse.backends.household.sim import InternalError, Refused, SimulationDiverged

    if isinstance(e, Refused):
        return {"type": "Refused", "reason": e.reason, "detail": e.detail}
    if isinstance(e, InternalError):
        return {"type": "InternalError"}
    if isinstance(e, SimulationDiverged):
        return {"type": "SimulationDiverged", "message": str(e)}
    if isinstance(e, ValueError):
        return {"type": "ValueError", "message": str(e)}
    return None


def _guard(fn, *a, **kw):
    try:
        return {"value": fn(*a, **kw)}
    except Exception as e:  # known kinds go back to the host as data, the rest as worker errors
        info = _raise_info(e)
        if info is None:
            raise
        return {"raise": info}


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, np.generic):
        return x.item()
    return x


def _row(action):
    """A row from JSON: a planned move's reference row (dict, arrays as lists) or a flat action list."""
    if isinstance(action, dict):
        return {k: (np.asarray(v, dtype=float) if k in ("ref", "vel") else v) for k, v in action.items()}
    return action


class Worker:
    def __init__(self) -> None:
        os.environ.pop("ROBOUSE_HOUSEHOLD_PYTHON", None)  # this process runs the simulation itself
        self.b = None
        self.gen = None
        self.pending = None

    def open(self, spec: dict, run_dir: str | None = None) -> dict:
        from robouse.backends.household.backend import HouseholdBackend

        def make():
            b = HouseholdBackend(spec)
            if run_dir:
                b.attach_run_dir(run_dir)
            return b

        r = _guard(make)
        if "raise" in r:
            return r
        b = self.b = r["value"]
        from robouse.backends.base import embodiment_dict

        s = b.action_spec
        return {
            "value": _jsonable(
                {
                    "action_spec": {"names": s.names, "low": s.low, "high": s.high, "doc": s.doc},
                    "max_steps": b.max_steps,
                    "settle_steps": b.settle_steps,
                    "camera": b.camera,
                    "render_size": list(b.render_size),
                    "control": b.control,
                    "embodiment": embodiment_dict(b),
                    "hz": round(1.0 / b.embodiment().step_s),
                }
            )
        }

    # ---- episode
    def reset(self, seed: int) -> dict:
        return _guard(self.b.reset, seed)

    def step(self, action=None, pending: bool = False) -> dict:
        row = self.pending if pending else _row(action)
        self.pending = None
        r = _guard(self.b.step, row)
        if "value" in r:
            r["value"] = {"success": bool(r["value"].success), "hand": self.b.hand_pos().tolist()}
        return r

    def call(self, name: str, args: list | None = None) -> dict:
        """One of the backend's plain methods (the list in remote.PLAIN)."""
        from robouse.backends.household.remote import PLAIN

        if name not in PLAIN:
            raise ValueError(f"not a household worker method: {name}")
        r = _guard(getattr(self.b, name), *(args or []))
        if "value" in r:
            r["value"] = _jsonable(r["value"])
        return r

    def grip_value(self) -> float:
        return float(self.b._grip)

    def render(self, camera: str, width: int | None = None, height: int | None = None):
        old = self.b.camera
        try:
            self.b.camera = camera
            return np.ascontiguousarray(self.b.render(width, height))
        finally:
            self.b.camera = old

    def camera_info(self, cameras: list[str], uncalibrated: list[str] | None = None) -> list[dict]:
        from robouse.core.cameras import mujoco_camera

        model, data = self.b.mj_model_data()
        w, h = self.b.render_size
        out = []
        for name in cameras:
            cam = mujoco_camera(
                model, data, name, w, h, image_flipped=False, calibrated=name not in (uncalibrated or [])
            )
            if cam is not None:
                out.append(_jsonable(cam))
        return out

    # ---- skills: a generator lives here; the host asks for its next row, then steps it
    def start_skill(self, name: str, raw: list[str]) -> dict:
        return self._start(self.b.start_skill, name, raw)

    def start_move_to(self, pos: list, grip, max_steps: int, tol: float) -> dict:
        return self._start(self.b.start_move_to, np.asarray(pos, dtype=float), grip, max_steps, tol)

    def _start(self, fn, *a) -> dict:
        self.skill_close()
        r = _guard(fn, *a)
        if "value" in r:
            self.gen, r["value"] = r["value"], None
        return r

    def skill_next(self) -> dict:
        try:
            r = _guard(next, self.gen)
        except StopIteration as e:
            self.gen = None
            return {"done": _jsonable(e.value or {})}
        if "value" in r:
            self.pending = _row(_jsonable(r.pop("value")))
            r["row"] = True
        else:
            self.gen = None
        return r

    def skill_close(self) -> None:
        if self.gen is not None:
            self.gen.close()
        self.gen, self.pending = None, None

    def close_episode(self) -> dict | None:
        """Close the episode (finishes the trace) and return the final session summary."""
        self.skill_close()
        if self.b is None:
            return None
        b, self.b = self.b, None
        b.close()
        return _jsonable(b.session_summary())

    def close(self) -> None:
        self.skill_close()
        if self.b is not None:
            self.b.close()
            self.b = None
