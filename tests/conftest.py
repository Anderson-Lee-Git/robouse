"""MuJoCo picks its OpenGL platform when it is first imported, and test modules import it while they are collected, so
the session chooses the platform first, as `robouse run` does: with MUJOCO_GL unset on Linux without a display, OSMesa
or EGL, whichever renders (robouse.core.gl.auto_select). Tests that render skip with the reason when neither does."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from robouse.core import gl


def pytest_configure(config) -> None:
    gl.auto_select()


@pytest.fixture(scope="session")
def session_cache(tmp_path_factory) -> Path:
    """The session's own cache folder for vendor URDFs (robouse.real.kinematics.VENDOR_CHAINS): tests never read or
    write the user's cache (~/.cache/robouse). The first test that loads a vendor chain downloads its URDF here."""
    return tmp_path_factory.mktemp("robouse-cache")


@pytest.fixture(autouse=True)
def _vendor_urdfs_in_the_session_cache(session_cache: Path, monkeypatch) -> None:
    """Every test, in this process, keeps vendor URDFs in the session's cache folder."""
    from robouse.real import kinematics

    monkeypatch.setattr(kinematics, "chain_cache", lambda: session_cache / "real")


@pytest.fixture
def metal_chain(session_cache: Path, monkeypatch) -> dict:
    """The MakerMods Metal arm's kinematic chain. Robo Use does not ship it: it is built from the vendor's URDF, which the
    first test that needs it downloads into the session's cache folder. ROBOUSE_CACHE_DIR points there as well, for the
    episode servers a test starts as subprocesses. Without network access, the tests that need the chain skip with the
    reason, except in CI (CI is set), where they fail."""
    from robouse.real.kinematics import load_chain_file

    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(session_cache))
    try:
        return load_chain_file("metal_chain.json")
    except FileNotFoundError as e:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"no MakerMods Metal kinematic chain: {e}")


@pytest.fixture
def sock_dir() -> Iterator[Path]:
    """A short folder for Unix sockets: a socket path has at most 104 bytes on macOS (108 on Linux), and tmp_path under
    a long TMPDIR (macOS's /var/folders/...) exceeds it."""
    with tempfile.TemporaryDirectory(prefix="robo-", dir="/tmp") as d:
        yield Path(d)
