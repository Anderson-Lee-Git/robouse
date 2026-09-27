"""Backend registry. The `robouse:` block of a task's task.md names a backend and its parameters."""
from __future__ import annotations

from .base import Backend


def make_backend(spec: dict) -> Backend:
    kind = spec["backend"]
    if kind == "metaworld":
        from .metaworld_backend import MetaWorldBackend

        return MetaWorldBackend(spec["env"], camera=spec.get("camera", "corner"), max_steps=int(spec.get("max_steps", 500)))
    if kind == "tabletop":
        from .tabletop import TabletopBackend

        return TabletopBackend(spec)
    if kind == "gymrobotics":
        from .gymrobotics import GymRoboticsBackend

        return GymRoboticsBackend(spec)
    raise KeyError(f"unknown backend {kind!r}")
