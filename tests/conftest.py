"""MuJoCo picks its OpenGL platform when it is first imported, and test modules import it while they are collected, so
the session chooses the platform first, as `robouse run` does: with MUJOCO_GL unset on Linux without a display, OSMesa
or EGL, whichever renders (robouse.core.gl.auto_select). Tests that render skip with the reason when neither does."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from robouse.core import gl


def pytest_configure(config) -> None:
    gl.auto_select()


@pytest.fixture
def sock_dir() -> Iterator[Path]:
    """A short folder for Unix sockets: a socket path has at most 104 bytes on macOS (108 on Linux), and tmp_path under
    a long TMPDIR (macOS's /var/folders/...) exceeds it."""
    with tempfile.TemporaryDirectory(prefix="robo-", dir="/tmp") as d:
        yield Path(d)
