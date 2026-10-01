"""Every backend whose simulator this environment has: start one bundled task, take one step, observe, render and close.
Backends whose simulator (package, virtualenv, robot models or remote worker) is missing are skipped, not failed; the
release gate (tools/gate.py) runs the reference solutions in each simulator's own image.

Where MuJoCo cannot render offscreen (no OSMesa or EGL; tests/conftest.py chooses one as `robouse run` does), each
check runs in a child interpreter instead: a backend that renders some other way (PIL, its own worker) still passes,
and one whose MuJoCo renderer gets no OpenGL context is skipped with the reason, instead of failing, or aborting this
process (GLFW without a display can)."""

from __future__ import annotations

import functools
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from robouse.backends import BACKENDS, make_backend
from robouse.backends.base import embodiment_of
from robouse.core import gl
from robouse.tasks import find_tasks
from robouse.workers.client import WorkerError

ROOT = Path(__file__).resolve().parents[1] / "tasks"
REMOTE = {"behavior", "gpu", "robodojo"}  # remote GPU workers
CHILD = """
import json, sys
sys.path.insert(0, sys.argv[1])
import pytest
import test_backends_smoke as t
from robouse.tasks import load_task
try:
    t.exercise(load_task(sys.argv[2]))
    print(json.dumps({"outcome": "passed"}))
except pytest.skip.Exception as e:
    print(json.dumps({"outcome": "skipped", "reason": str(e.msg)}))
"""


@functools.cache
def _offscreen() -> str | None:
    """Why MuJoCo cannot render offscreen here, with MUJOCO_GL as tests/conftest.py chose it; None when it can. Checked
    in a fresh interpreter: rendering without an OpenGL platform can abort this one."""
    return gl.probe()


def _first_task(kind: str):
    for suite in sorted(ROOT.iterdir()):
        for t in find_tasks(suite):
            if t.spec["backend"] == kind:
                return t
    return None


def exercise(task) -> None:
    kind = task.spec["backend"]
    try:
        b = make_backend(task.spec)
        b.reset(int(task.spec.get("seed", 0)))
    except (ImportError, WorkerError, FileNotFoundError) as e:
        if gl.explain(e):  # a worker whose MuJoCo got no OpenGL context
            pytest.skip(f"MuJoCo cannot render offscreen here ({gl.reason(str(e))}). {gl.HINT}")
        pytest.skip(f"{kind}: simulator not available here ({type(e).__name__}: {str(e)[:120]})")
    try:
        emb = embodiment_of(b).validate()
        assert emb.dim == b.action_spec.dim
        hold = b.hold_action() if callable(getattr(b, "hold_action", None)) else [0.0] * b.action_spec.dim
        info = b.step(np.asarray(hold, dtype=float))
        assert isinstance(info.success, bool | np.bool_)
        json.dumps(b.observe())  # the public state is JSON
        img = np.asarray(b.render())
        assert img.ndim == 3 and img.shape[2] == 3 and img.dtype == np.uint8
    finally:
        b.close()


def _exercise_in_a_child(task, why: str) -> None:
    p = subprocess.run(
        [sys.executable, "-c", CHILD, str(Path(__file__).parent), str(task.path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=900,
    )
    last = (p.stdout.strip().splitlines() or ["{}"])[-1]
    res = json.loads(last) if p.returncode == 0 and last.startswith("{") else {}
    if res.get("outcome") == "passed":
        return
    if res.get("outcome") == "skipped":
        pytest.skip(res["reason"])
    if gl.explain(p.stderr) or p.returncode < 0:  # no OpenGL context for MuJoCo (an error, or the process aborted)
        pytest.skip(f"MuJoCo cannot render offscreen here ({why}). {gl.HINT}")
    pytest.fail(f"{task.spec['backend']}: exit code {p.returncode}\n{p.stderr[-3000:]}")


@pytest.mark.parametrize("kind", sorted(k for k in BACKENDS if k not in REMOTE and k != "remix"))
def test_start_step_observe_render(kind: str) -> None:
    task = _first_task(kind)
    if task is None:
        pytest.skip(f"no bundled {kind} task")
    if why := _offscreen():
        _exercise_in_a_child(task, why)
    else:
        exercise(task)
