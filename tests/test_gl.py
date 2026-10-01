"""Offscreen rendering (robouse.core.gl): a machine without an OpenGL platform for MuJoCo gets a one-line message that
names the fix instead of MuJoCo's follow-on AttributeError; with MUJOCO_GL unset on Linux without a display, robouse
picks OSMesa or EGL when one renders; `robouse doctor` checks it; the test suite picks it the same way
(tests/conftest.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from robouse.cli import main
from robouse.core import gl

REPO = Path(__file__).resolve().parents[1]
ARC = REPO / "tasks" / "arc-style" / "arc-gravity"
RENDER_SMOKE = "tests/test_backends_smoke.py::test_start_step_observe_render[tabletop]"
FATAL = (
    "mujoco.FatalError: an OpenGL platform library has not been loaded into this process, this most likely means that "
    "a valid OpenGL context has not been created before mjr_makeContext was called"
)
FOLLOW_ON = "AttributeError: 'Renderer' object has no attribute '_mjr_context'"


def _says_install_and_doctor(msg: str) -> None:
    # install OSMesa or EGL and check with doctor: robouse picks it; MUJOCO_GL is mentioned only as an override
    assert "install OSMesa (`apt install libosmesa6`) or EGL (`apt install libegl1 libgl1`)" in msg
    assert "robouse picks whichever renders" in msg and "MUJOCO_GL, if set, overrides that choice" in msg
    assert "set MUJOCO_GL" not in msg


def test_explain_names_the_fix(monkeypatch) -> None:
    monkeypatch.delenv("MUJOCO_GL", raising=False)  # tests/conftest.py may have chosen it for this session
    for err in (
        FATAL,
        FOLLOW_ON,
        "WorkerError: humanoidbench worker: " + FATAL,
        f"Traceback ...\n{FATAL}\n{FOLLOW_ON}",
    ):
        msg = gl.explain(err)
        assert msg and msg.startswith("offscreen rendering is not available")
        _says_install_and_doctor(msg)
        assert "and run `robouse doctor`" in msg and "cgl on macOS" in msg and "here it is set to" not in msg
    monkeypatch.setenv("MUJOCO_GL", "egl")  # an override in effect is named
    assert "overrides that choice (osmesa, egl, or cgl on macOS); here it is set to egl. Cause:" in gl.explain(FATAL)
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
    assert os.environ["MUJOCO_GL"] == "egl"
    assert gl.auto_select() is None  # already set: left alone


def test_auto_select_leaves_the_setting_alone(headless) -> None:
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
    assert "-- MuJoCo cannot render offscreen" in out and "OpenGL platform library" in out
    _says_install_and_doctor(out)
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
    _says_install_and_doctor(res["exception"])
    assert "run `robouse doctor`" in res["exception"] and "here it is set to glfw" in res["exception"]
    assert "_mjr_context" not in res["exception"]


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
    assert rc == 0 and res["exception"] is None and os.environ["MUJOCO_GL"] in gl.CANDIDATES


@linux_sim
@pytest.mark.parametrize("setting", [None, "glfw"], ids=["unset", "glfw-without-a-display"])
def test_the_render_smoke_test_on_a_machine_without_a_display(setting) -> None:
    # MuJoCo fixes its OpenGL platform when it is first imported, while the tests are collected: tests/conftest.py
    # chooses it as `robouse run` does, and the render smoke test skips with the reason when MuJoCo cannot render
    # offscreen, instead of aborting the whole run (GLFW without a display)
    gone = ("MUJOCO_GL", "PYOPENGL_PLATFORM", "DISPLAY", "WAYLAND_DISPLAY")
    env = {k: v for k, v in os.environ.items() if k not in gone} | {"COLUMNS": "200"}
    if setting:
        env["MUJOCO_GL"] = setting
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", RENDER_SMOKE],
        cwd=REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = p.stdout + p.stderr
    assert p.returncode == 0 and "Fatal Python error" not in out, out[-3000:]
    skipped = "1 skipped" in out and "MuJoCo cannot render offscreen here" in out
    if setting == "glfw":  # GLFW needs a display: nothing renders, and the skip says why
        assert skipped, out[-3000:]
    else:  # chosen as `robouse run` chooses: it renders, or skips with the reason where neither OSMesa nor EGL does
        assert "1 passed" in out or skipped, out[-3000:]
