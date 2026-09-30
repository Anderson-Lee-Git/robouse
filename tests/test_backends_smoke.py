"""Every backend whose simulator this environment has: start one bundled task, take one step, observe, render and close.
Backends whose simulator (package, virtualenv, robot models or remote worker) is missing are skipped, not failed; the
release gate (tools/gate.py) runs the reference solutions in each simulator's own image."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from robouse.backends import BACKENDS, make_backend
from robouse.backends.base import embodiment_of
from robouse.tasks import find_tasks
from robouse.workers.client import WorkerError

ROOT = Path(__file__).resolve().parents[1] / "tasks"
REMOTE = {"behavior", "gpu", "robodojo"}  # remote GPU workers


def _first_task(kind: str):
    for suite in sorted(ROOT.iterdir()):
        for t in find_tasks(suite):
            if t.spec["backend"] == kind:
                return t
    return None


@pytest.mark.parametrize("kind", sorted(k for k in BACKENDS if k not in REMOTE and k != "remix"))
def test_start_step_observe_render(kind: str) -> None:
    task = _first_task(kind)
    if task is None:
        pytest.skip(f"no bundled {kind} task")
    try:
        b = make_backend(task.spec)
        b.reset(int(task.spec.get("seed", 0)))
    except (ImportError, WorkerError, FileNotFoundError) as e:
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
