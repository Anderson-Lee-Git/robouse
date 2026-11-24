"""The researcher-only physical-state trace of a RoboCasa scenario episode (backends/robocasa/state_trace.py).

Reading a trace needs nothing; the episode tests need RoboCasa's interpreter ($ROBOUSE_ROBOCASA_PYTHON) and its
assets and are skipped without them (run them on a compute node).
"""

from __future__ import annotations

import gzip
import json

import numpy as np
import pytest

from robouse.backends.robocasa import state_trace as T

SPEC = {
    "id": "test-state-trace",
    "kitchen": {"layout": 1, "style": 1},
    "instruction": "Warm up the leftovers.",
    "robot_anchor": "microwave",
    "fixtures": {
        "microwave": {"type": "microwave"},
        "counter": {"type": "counter", "ref": "microwave", "size": [0.3, 0.3]},
    },
    "fixture_states": [{"fixture": "microwave", "set": "door", "value": 1.0}],
    "objects": [
        {
            "name": "box",
            "category": "tupperware",
            "placement": {
                "fixture": "counter",
                "sample_region_kwargs": {"ref": "microwave"},
                "size": [0.5, 0.3],
                "pos": ["ref", -1.0],
                "offset": [0.0, 0.15],
            },
        },
    ],
    "goal": {"pred": "inside", "obj": "box", "fixture": "microwave"},
}


def _write(path, rows, *, truncate: bool = False) -> None:
    data = "".join(json.dumps(r) + "\n" for r in rows).encode()
    blob = gzip.compress(data)
    path.write_bytes(blob[: len(blob) // 2] if truncate else blob)


HEADER = {"kind": "header", "format": T.FORMAT, "version": T.VERSION}
STATE = {"kind": "state", "step": 0, "phase": "reset", "objects": {}, "contacts": []}
END = {"kind": "end", "steps": 0, "records": 3, "goal": False}


def test_a_trace_is_complete_only_with_its_end_line(tmp_path) -> None:
    p = tmp_path / T.FILENAME
    _write(p, [HEADER, STATE, END])
    assert T.read(p)["complete"] and len(T.read(p)["states"]) == 1
    _write(p, [HEADER, STATE])  # the worker died before finish
    assert not T.read(p)["complete"]
    _write(p, [HEADER, STATE, {"kind": "error", "step": 4, "error": "boom"}, END])
    assert not T.read(p)["complete"]
    _write(p, [HEADER, STATE, END] * 200, truncate=True)
    out = T.read(p)
    assert not out["complete"] and "unreadable" in out["error"]["error"]
    _write(p, [{**HEADER, "format": "other"}, STATE, END])
    assert not T.read(p)["complete"]


def _robocasa_python() -> str | None:
    import os

    from robouse import config

    try:
        py = config.sim_python("robocasa", "robocasa")
    except Exception:
        return None
    return py if py and os.path.exists(py) else None


def _actions(n: int) -> list[list[float]]:
    """Reach down toward the counter, close the hand, lift: contacts, a grasp attempt and fixture proximity."""
    rng = np.random.default_rng(3)
    out = []
    for k in range(n):
        a = np.zeros(7)
        a[:3] = [0.0, 0.6, -0.8] if k < n // 2 else [0.0, 0.0, 0.8]
        a[:3] += rng.normal(0, 0.2, 3)
        a[6] = -1.0 if k < n // 2 else 1.0
        out.append([float(v) for v in a])
    return out


def _episode(run_dir, actions, monkeypatch, *, trace: bool):
    from robouse.backends.robocasa.scenario_backend import RobocasaScenarioBackend

    monkeypatch.setenv("ROBOUSE_STATE_TRACE", "1" if trace else "0")
    b = RobocasaScenarioBackend({"scenario": SPEC, "control": "eef", "max_steps": 200})
    b.attach_run_dir(run_dir)
    digests = []
    try:
        b.reset(0)
        digests.append(b._call("physics_digest")["digest"])
        for a in actions:
            b.step(a)
            digests.append(b._call("physics_digest")["digest"])
        b.begin_settle()
        for _ in range(3):
            b.step(b.hold_action())
            digests.append(b._call("physics_digest")["digest"])
    finally:
        b.close()
    return b, digests


@pytest.mark.skipif(not _robocasa_python(), reason="no RoboCasa interpreter")
def test_tracing_writes_every_control_and_changes_no_dynamics(tmp_path, monkeypatch) -> None:
    actions = _actions(40)
    traced, with_trace = _episode(tmp_path / "traced", actions, monkeypatch, trace=True)
    _, without = _episode(tmp_path / "plain", actions, monkeypatch, trace=False)
    # the same physical state after reset and after every control, bit for bit
    assert with_trace == without
    assert not (tmp_path / "plain" / T.FILENAME).exists()
    assert traced.trace and traced.trace["ok"], traced.trace

    out = T.read(tmp_path / "traced" / T.FILENAME)
    assert out["complete"], out["error"]
    h = out["header"]
    assert h["format"] == T.FORMAT and h["control"] == "eef" and h["source"] == {"kind": "live"}
    assert set(h["objects"]) == {"box"}
    mw = h["fixtures"]["microwave"]
    assert mw["powered"] and "hinge" in mw["joints"].values()  # the door
    assert mw["parts"] and all(p.startswith("microwave/") for p in mw["parts"])
    states = out["states"]
    steps = [s["step"] for s in states]
    # reset, every control (stride 1), the settle steps, and the final state
    assert steps[0] == 0 and states[0]["phase"] == "reset"
    assert [s["step"] for s in states if s["phase"] in ("control", "settle")] == list(range(1, 44))
    assert [s["phase"] for s in states[-4:]] == ["settle", "settle", "settle", "final"]
    assert out["end"]["steps"] == 43 and out["end"]["goal"] is False
    # each record's digest is the physics fingerprint at that step
    assert [s["digest"] for s in states[:-1]] == with_trace
    first = states[0]
    assert first["objects"]["box"]["on"] == ["counter"]  # resting on the counter at reset
    assert set(first["fixtures"]["microwave"]["joints"]) == set(mw["joints"])
    boxes = first["fixtures"]["microwave"]["parts"]  # each moving part's world box
    assert boxes and set(boxes) <= {p.split("/", 1)[1] for p in mw["parts"]}
    assert all(lo[k] <= hi[k] for lo, hi in boxes.values() for k in range(3))
    assert first["fixtures"]["microwave"]["on"] is False
    assert "liquid" not in first  # no liquid in this scene
    assert set(first["robot"]) == {"eef", "grip", "grasped"}
    assert all(len(s["objects"]["box"]["quat"]) == 4 for s in states)
    lo, hi = first["objects"]["box"]["box"]  # the object's world bounding box contains its root
    assert all(lo[k] - 1e-3 <= first["objects"]["box"]["pos"][k] <= hi[k] + 1e-3 for k in range(3))


def test_the_practice_broker_never_serves_a_trace() -> None:
    from robouse.harnesses.aspire import broker

    assert broker.STATE_TRACE_FILE == T.FILENAME
