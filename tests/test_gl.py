"""Offscreen rendering (robouse.core.gl): a machine without an OpenGL platform for MuJoCo gets a one-line message that
names the fix instead of MuJoCo's follow-on AttributeError; with MUJOCO_GL unset on Linux without a display, robouse
picks OSMesa or EGL when one renders; `robouse doctor` checks it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from robouse.cli import main
from robouse.core import gl

ARC = Path(__file__).resolve().parents[1] / "tasks" / "arc-style" / "arc-gravity"
FATAL = (
    "mujoco.FatalError: an OpenGL platform library has not been loaded into this process, this most likely means that "
    "a valid OpenGL context has not been created before mjr_makeContext was called"
)
FOLLOW_ON = "AttributeError: 'Renderer' object has no attribute '_mjr_context'"


def test_explain_names_the_fix() -> None:
    for err in (
        FATAL,
        FOLLOW_ON,
        "WorkerError: humanoidbench worker: " + FATAL,
        f"Traceback ...\n{FATAL}\n{FOLLOW_ON}",
    ):
        msg = gl.explain(err)
        assert msg and msg.startswith("offscreen rendering is not available")
        assert "MUJOCO_GL=osmesa" in msg and "libosmesa6" in msg and "MUJOCO_GL=egl" in msg and "MUJOCO_GL=cgl" in msg
    assert "Cause: mujoco.FatalError: an OpenGL platform library" in gl.explain(
        f"{FATAL}\n{FOLLOW_ON}"
    )  # not the follow-on
    assert gl.explain(ValueError("action values must be finite numbers")) is None
    assert gl.explain(KeyError("unknown robocasa task")) is None


@pytest.fixture
def headless(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "MUJOCO_GL"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_auto_select_picks_a_platform_that_renders(headless) -> None:
    tried = []
    headless.setattr(gl, "probe", lambda p=None, python=None: tried.append(p) or (None if p == "egl" else "no OSMesa"))
    assert gl.auto_select() == "egl" and tried == ["osmesa", "egl"]
    import os

    assert os.environ["MUJOCO_GL"] == "egl"
    assert gl.auto_select() is None  # already set: left alone


def test_auto_select_leaves_the_setting_alone(headless) -> None:
    import os

    headless.setattr(gl, "probe", lambda p=None, python=None: None)
    headless.setenv("DISPLAY", ":0")  # a display: GLFW works, nothing to choose
    assert gl.auto_select() is None and "MUJOCO_GL" not in os.environ
    headless.delenv("DISPLAY")
    headless.setattr(gl, "probe", lambda p=None, python=None: "nothing renders")
    assert gl.auto_select() is None and "MUJOCO_GL" not in os.environ


def test_doctor_reports_offscreen_rendering(monkeypatch, capsys) -> None:
    monkeypatch.setattr(gl, "auto_select", lambda: None)
    monkeypatch.setattr(gl, "probe", lambda p=None, python=None: gl.reason(f"{FATAL}\n{FOLLOW_ON}"))
    main(["doctor"])
    out = capsys.readouterr().out
    assert "-- MuJoCo cannot render offscreen" in out and "OpenGL platform library" in out and "libosmesa6" in out
    monkeypatch.setattr(gl, "probe", lambda p=None, python=None: None)
    main(["doctor"])
    assert "ok MuJoCo renders offscreen" in capsys.readouterr().out


linux_sim = pytest.mark.skipif(
    not sys.platform.startswith("linux") or __import__("importlib").util.find_spec("mujoco") is None,
    reason="needs MuJoCo on Linux",
)


@linux_sim
def test_a_trial_without_an_opengl_platform_says_what_to_install(tmp_path, monkeypatch, capsys) -> None:
    # GLFW without a display is what an unconfigured headless machine gets: the trial is an infrastructure failure
    # whose message is the fix, not MuJoCo's follow-on AttributeError
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("PYOPENGL_PLATFORM", raising=False)
    monkeypatch.setenv("MUJOCO_GL", "glfw")
    rc = main(["run", "--task", str(ARC), "--harness", "noop", "--out", str(tmp_path / "job")])
    res = json.loads(capsys.readouterr().out)
    assert rc == 1 and "offscreen rendering is not available" in res["exception"], res["exception"]
    assert "MUJOCO_GL=osmesa" in res["exception"] and "_mjr_context" not in res["exception"]


@linux_sim
def test_unset_mujoco_gl_is_chosen_on_headless_linux(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("MUJOCO_GL", raising=False)
    monkeypatch.delenv("PYOPENGL_PLATFORM", raising=False)
    if all(gl.probe(p) for p in gl.CANDIDATES):
        pytest.skip("neither OSMesa nor EGL is installed here")
    rc = main(["run", "--task", str(ARC), "--harness", "noop", "--out", str(tmp_path / "job")])
    res = json.loads(capsys.readouterr().out)
    import os

    assert rc == 0 and res["exception"] is None and os.environ["MUJOCO_GL"] in gl.CANDIDATES
