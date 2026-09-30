"""Real-robot backend on the hardware-in-the-loop mock: kinematics against hardware logs, safety guard, e-stop,
operator gates and verdicts, rig switch. Run: PYTHONPATH=src python -m pytest tests/test_real.py -q"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _operator_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOUSE_OPERATOR_DIR", str(tmp_path / "op"))
    monkeypatch.setenv("ROBOUSE_ESTOP_FILE", str(tmp_path / "op" / "ESTOP"))
    monkeypatch.delenv("ROBOUSE_OPERATOR_SCRIPT", raising=False)
    monkeypatch.delenv("ROBOUSE_RIG", raising=False)
    import importlib

    import robouse.real.safety as s

    importlib.reload(s)
    import robouse.real.operator as o

    importlib.reload(o)
    import robouse.backends.real.backend as r

    importlib.reload(r)
    yield


def _episode(task_id: str, tmp_path, **real_overrides):
    from robouse.session import Episode
    from robouse.tasks import load_task

    spec = load_task(ROOT / "tasks" / "real" / task_id).spec
    spec["real"] = {**spec["real"], **real_overrides}
    return Episode(spec, tmp_path / "ep")


def test_metal_fk_matches_recorded_hardware_poses():
    from robouse.real.replay import Fixture
    from robouse.real.robots import METAL

    fx, ch = Fixture("metal-bowl-121853"), METAL.chain()
    err = [
        np.linalg.norm(ch.frames(s["pos"][:6])["link6"][:3, 3] - np.asarray(s["link6"]))
        for s in fx.steps
        if "link6" in s
    ]
    assert len(err) > 800 and max(err) < 0.0005


def test_hil_conformance_no_vetoes_on_recorded_session():
    from robouse.real.replay import Fixture, conformance
    from robouse.real.robots import METAL

    fx = Fixture("metal-bowl-121853")
    r = conformance(fx, METAL, fx.meta["session_envelope"])
    assert r["vetoed_steps"] == 0 and r["tracking_open_loop_rms_deg"] < 0.5


def test_oracle_style_move_and_pose_verdict(tmp_path):
    ep = _episode("real-metal-reach", tmp_path)
    r = ep.handle({"op": "skill", "name": "move_to", "args": ["0.30", "-0.10", "0.08"]})
    assert r["ok"] and r["result"]["reached"], r
    res = ep.finish("done", "")
    assert ep.result["success"] and ep.result["embodiment_mode"] == "hil-mock"
    ep.close()


def test_veto_below_table_moves_nothing(tmp_path):
    ep = _episode("real-metal-reach", tmp_path)
    before = ep.steps
    r = ep.handle({"op": "skill", "name": "move_to", "args": ["0.30", "-0.10", "-0.05"]})  # 4 cm under the table
    assert not r["ok"] or not r["result"].get("reached")
    # a raw joint target that folds the arm into the table is vetoed before any step
    q = [-40.0, -150.0, 60.0, -60.0, 0.0, 0.0, 4.0]
    r = ep.handle({"op": "act", "action": q})
    assert not r["ok"] and "workspace" in r["error"] and ep.steps == before
    ep.close()
    ev = [json.loads(l) for l in (tmp_path / "ep" / "session" / "events.jsonl").read_text().splitlines()]
    assert any(e["event"] == "veto" for e in ev)


def test_estop_ends_episode_with_safety_stop(tmp_path):
    from robouse.real import safety

    ep = _episode("real-metal-reach", tmp_path)
    assert ep.handle({"op": "act", "action": list(ep.backend.q), "repeat": 2})["ok"]
    safety.set_estop("test")
    r = ep.handle({"op": "act", "action": list(ep.backend.q)})
    assert not r["ok"]
    assert ep.finished and ep.outcome == "safety_stop" and ep.result["success"] is False
    assert ep.result["safety_events"]
    ep.close()
    safety.clear_estop()


def test_refused_arm_gate_stops_before_motion(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOUSE_OPERATOR_SCRIPT", "arm=no")
    ep = _episode("real-metal-reach", tmp_path)
    r = ep.handle({"op": "observe"})
    assert ep.finished and ep.outcome == "safety_stop" and ep.steps == 0
    ep.close()


def test_overtemperature_stops(tmp_path):
    ep = _episode("real-metal-reach", tmp_path, envelope={"temp_stop_c": 20.0})  # recorded motors are at ~28 C
    ep.handle({"op": "act", "action": list(ep.backend.q)})
    assert ep.finished and ep.outcome == "safety_stop"
    ep.close()


def test_operator_verdict_mock_proxy_and_feedback(tmp_path):
    from robouse.real import operator

    ep = _episode("real-metal-bead-to-bowl", tmp_path)
    operator.say("the bead is a bit further left")
    r = ep.handle({"op": "observe"})
    assert r["result"]["state"]["operator_notes"] == ["the bead is a bit further left"]
    ep.finish("done", "")  # nothing done: the stand-in operator says no
    assert ep.result["success"] is False and ep.result["judge_detail"]["answer"] == "no"
    ep.close()


def test_scripted_operator_refused_for_live_driver(tmp_path):
    from robouse.real.safety import SafetyStop

    with pytest.raises(SafetyStop):
        _episode("real-metal-reach", tmp_path, driver="lerobot", operator="script")


def test_file_operator_channel(tmp_path):
    import threading
    import time

    from robouse.real import operator
    from robouse.real.operator import Operator

    op = Operator("file", mock=False, timeout_s=10)

    def answer():
        for _ in range(100):
            if (operator.OPERATOR_DIR / "pending.json").exists():
                operator.answer("yes", "looks good")
                return
            time.sleep(0.05)

    threading.Thread(target=answer).start()
    assert op.verdict("ok?") == ("yes", "looks good")


def test_rig_switch_selects_driver(tmp_path, monkeypatch):
    rig = tmp_path / "rig.yaml"
    rig.write_text("metal:\n  driver: mock\n  fixture: metal-bowl-121853\n  envelope: {z_max: 0.5}\n")
    monkeypatch.setenv("ROBOUSE_RIG", str(rig))
    ep = _episode("real-metal-reach", tmp_path)
    assert ep.backend.guard.e.z_max == 0.5
    ep.close()


def test_piper_driver_on_mock_sdk(tmp_path):
    ep = _episode("real-piper-joint-pose", tmp_path)
    r = ep.handle({"op": "skill", "name": "move_joints", "args": ["20", "40", "-50", "0", "20", "0"]})
    assert r["ok"] and r["result"]["arrived"]
    ep.finish("done", "")
    assert ep.result["success"]
    ep.close()


def test_rosbridge_driver_against_mock_server():
    import math
    import time

    from robouse.real.drivers.rosbridge import RosbridgeDriver, ros_profile
    from robouse.real.rosbridge_mock import MockRosbridge

    cfg = {
        "joints": ["j1", "j2", "j3"],
        "low": [-90, -90, -90],
        "high": [90, 90, 90],
        "units": "deg",
        "cameras": {"cam": "/cam/compressed"},
    }
    prof = ros_profile(cfg)
    for ctype in ("trajectory_msgs/JointTrajectory", "std_msgs/Float64MultiArray"):
        srv = MockRosbridge(prof.joints, [0.1, -0.2, 0.3], cameras=["/cam/compressed"])
        drv = RosbridgeDriver(prof, {**cfg, "url": srv.url, "command_type": ctype, "command_topic": "/cmd"})
        drv.connect()
        r = drv.read()
        assert np.allclose(r.q, np.degrees([0.1, -0.2, 0.3]), atol=0.5)  # radians on the wire, degrees to the agent
        drv.send([10.0, 20.0, 30.0])
        time.sleep(1.0)
        r = drv.read()
        assert np.allclose(r.q, [10, 20, 30], atol=1.0), r.q
        assert np.allclose(srv.commands[-1], [math.radians(10), math.radians(20), math.radians(30)])
        assert "cam" in r.images and r.images["cam"].shape[2] == 3
        srv._stop.set()  # the robot stops publishing: reads fail once the joint state is stale
        time.sleep(1.3)
        with pytest.raises(RuntimeError):
            drv.read()
        drv.disconnect(False)


def test_ros_task_on_mock_rosbridge(tmp_path):
    ep = _episode("real-ros-joint-pose", tmp_path)
    r = ep.handle({"op": "skill", "name": "move_joints", "args": ["30", "-70", "60", "-80", "-90", "20"]})
    assert r["ok"] and r["result"]["arrived"], r
    ep.finish("done", "")
    assert ep.result["success"] and ep.result["embodiment_mode"] == "hil-mock"
    ep.close()
