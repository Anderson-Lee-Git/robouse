"""Backend interface: one simulator family (Meta-World, custom MuJoCo scenes, ...) behind a common API.

The session server only talks to this interface. A backend exposes:
- a low-level action (a fixed-length vector with documented bounds),
- a public observation (named fields the agent may see, plus an optional camera image),
- a success predicate evaluated by the trusted server, never by the agent.
Skills (move_to, grip) are optional helpers built on the low-level action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class ActionSpec:
    names: list[str]
    low: list[float]
    high: list[float]
    doc: str = ""

    @property
    def dim(self) -> int:
        return len(self.names)

    def clip(self, a) -> np.ndarray:
        return np.clip(np.asarray(a, dtype=np.float64), self.low, self.high)


@dataclass
class StepInfo:
    success: bool
    reward: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class Backend:
    """Subclasses implement reset/step/observe/render/success."""

    name = "base"
    action_spec: ActionSpec
    max_steps: int = 500

    def reset(self, seed: int) -> None:
        raise NotImplementedError

    def step(self, action: np.ndarray) -> StepInfo:
        raise NotImplementedError

    def observe(self) -> dict[str, Any]:
        """Public, JSON-serialisable state. Must not leak anything the task hides from the agent."""
        raise NotImplementedError

    def render(self, width: int = 320, height: int = 320) -> np.ndarray:
        raise NotImplementedError

    # ---- episode video at a chosen size (ROBOUSE_RECORD_SIZE) -----------------------------------------------------
    # The recording uses its own renderer, so the images the agent sees (`render()`, `robo observe --image`) are
    # unchanged. The frame keeps the backend's camera; a wider frame shows more of the scene sideways (the camera's
    # vertical field of view is fixed), never a stretched image.
    def render_record(self, width: int, height: int) -> np.ndarray | None:
        """A video frame at width x height, or None when this backend can only record at its native size."""
        md = getattr(self, "mj_model_data", None)
        md = md() if callable(md) else None
        if not md:
            return None
        model, data = md
        return self._mj_record(model, data, self.record_camera(), width, height, self.record_scene_option(),
                               bool(getattr(self, "image_flipped", False)))

    def record_camera(self) -> Any:
        return getattr(self, "camera", None)

    def record_scene_option(self) -> Any:
        return None

    def _mj_record(self, model, data, camera, width: int, height: int, scene_option=None, flip: bool = False) -> np.ndarray:
        import mujoco

        cache = self.__dict__.setdefault("_record_renderers", {})
        key = (id(model), width, height)
        if key not in cache:
            g = model.vis.global_  # the offscreen buffer must hold the frame; visual-only, no effect on physics
            g.offwidth, g.offheight = max(g.offwidth, width), max(g.offheight, height)
            cache[key] = mujoco.Renderer(model, height=height, width=width)
        r = cache[key]
        if scene_option is not None:
            r.update_scene(data, camera=camera, scene_option=scene_option)
        else:
            r.update_scene(data, camera=camera)
        img = r.render()
        return (img[::-1] if flip else img).copy()

    def success(self) -> bool:
        raise NotImplementedError

    # Optional skills. Default implementations raise so tasks can disable them.
    def skills(self) -> list[str]:
        return []

    def close(self) -> None:
        pass
