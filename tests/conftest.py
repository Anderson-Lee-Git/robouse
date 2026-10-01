"""MuJoCo picks its OpenGL platform when it is first imported, and test modules import it while they are collected, so
the session chooses the platform first, as `robouse run` does: with MUJOCO_GL unset on Linux without a display, OSMesa
or EGL, whichever renders (robouse.core.gl.auto_select). Tests that render skip with the reason when neither does."""

from __future__ import annotations

from robouse.core import gl


def pytest_configure(config) -> None:
    gl.auto_select()
