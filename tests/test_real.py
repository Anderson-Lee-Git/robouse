"""Real-robot backend on the hardware-in-the-loop mock: kinematics against hardware logs, safety guard, e-stop,
operator gates and verdicts, rig switch, and the safety layer's stops: loop watchdog, lost telemetry, contact watch
(replaying the 2026-09-05 Metal recordings in tests/fixtures/hil), batch halting and the physical e-stop confirmation.
Run: PYTHONPATH=src python -m pytest tests/test_real.py -q"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
HIL = ROOT / "tests" / "fixtures" / "hil"  # sessions recorded on the Metal arm, for the mock (see each note)


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


def test_hil_check_counts_clamps(monkeypatch):
    from robouse.real.replay import Fixture, conformance
    from robouse.real.robots import METAL

    monkeypatch.setenv("ROBOUSE_HIL_DIR", str(HIL))
    fx = Fixture("metal-hanoi-131602")  # the elbow was commanded to 180 deg, above the 179 deg limit
    r = conformance(fx, METAL, fx.meta["session_envelope"])
    assert r["clamp_events"] > 0 and r["vetoed_steps"] == 0


def test_soft_limits_sit_inside_the_measured_stops(monkeypatch):
    """Mechanical stops measured on the bench on 2026-09-05 (~/benchflow/robot): the Metal's elbow stopped at 176.37 deg
    (13:16 session, in the metal-hanoi-131602 fixture); with torque off its parked shoulder_lift rests at up to +0.09
    and its closed gripper at -0.25 (connect poses of the recorded sessions); the two SO-101 followers' calibrated
    ranges of motion (lerobot calibration so_follower/benchmark_left|right) end at +-121.1 pan, +-105.6 shoulder_lift,
    +-97.3 elbow_flex, +-104.0 wrist_flex, +-168.7 wrist_roll, and the gripper's 0 and 100. Every soft limit stays at
    least 2.2 deg (2 % of the gripper's range) inside them."""
    from robouse.real.replay import Fixture
    from robouse.real.robots import METAL, SO101, SO101_BI

    monkeypatch.setenv("ROBOUSE_HIL_DIR", str(HIL))
    elbow_stop = max(s["pos"][2] for s in Fixture("metal-hanoi-131602").steps)
    assert elbow_stop == pytest.approx(176.37, abs=0.01)
    assert METAL.high[2] <= elbow_stop - 2.2 and METAL.high[1] <= 0.09 - 2.2 and METAL.low[6] >= -0.25 + 2.2
    so101_stops = [121.1, 105.6, 97.3, 104.0, 168.7]
    for i, stop in enumerate(so101_stops):
        assert -stop + 2.2 <= SO101.low[i] and SO101.high[i] <= stop - 2.2, SO101.joints[i]
    assert SO101.low[5] >= 2.0 and SO101.high[5] <= 98.0
    assert SO101_BI.low == SO101.low * 2 and SO101_BI.high == SO101.high * 2
    for p in (METAL, SO101):  # the rest poses stay inside the new limits
        assert all(lo <= v <= hi for lo, v, hi in zip(p.low, p.park, p.high, strict=True)), p.name


def test_playback_serves_the_recording(tmp_path):
    """Playback mode: each control step returns the next step recorded on the bench (joints and torques), whatever is
    commanded. Tracking mode reports the recorded temperatures but no torque: those belong to the recorded motion."""
    from robouse.real.replay import Fixture

    fx = Fixture("metal-bowl-121853")
    ep = _episode("real-metal-reach", tmp_path, mock_playback=True)
    robot = ep.backend.driver.robot
    for _ in range(3):
        assert ep.handle({"op": "act", "action": list(ep.backend.q)})["ok"]
    assert np.allclose(ep.backend.q, fx.steps[robot.k]["pos"])
    assert ep.backend.extra["joint_torque_nm"] == fx.steps[robot.k]["joint_torque_nm"]
    ep.close()
    ep = _episode("real-metal-reach", tmp_path / "b")
    assert ep.handle({"op": "act", "action": list(ep.backend.q)})["ok"]
    assert "joint_torque_nm" not in ep.backend.extra and ep.backend.extra["temp_mos_c"]
    ep.close()


def test_oracle_style_move_and_pose_verdict(tmp_path):
    ep = _episode("real-metal-reach", tmp_path)
    r = ep.handle({"op": "skill", "name": "move_to", "args": ["0.30", "-0.10", "0.08"]})
    assert r["ok"] and r["result"]["reached"], r
    ep.finish("done", "")
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
    ep.handle({"op": "observe"})
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
    assert ep.backend.stamp is not None and ep.backend.stamp_of in ("joints 1-2", "joints 3-4", "joints 5-6")
    ep.finish("done", "")
    assert ep.result["success"]
    ep.close()


def test_piper_silent_joint_pair_stops_the_episode(tmp_path):
    """The Piper's joints arrive in three feedback frames (joints 1-2, 3-4, 5-6), and piper_sdk keeps one time stamp
    for all of them, refreshed by whichever came last. The driver dates each pair itself: when joints 3-4 fall silent
    (the other pairs still arriving, the SDK's stamp still fresh), the episode stops as lost telemetry naming the pair,
    and the arm keeps its last command."""
    ep = _episode(
        "real-piper-joint-pose",
        tmp_path,
        envelope={"telemetry_timeout_s": 0.3},
        mock_fault={"kind": "silent_pair", "pair": "34", "at_step": 3},
    )
    sdk = ep.backend.driver.sdk
    target = list(np.asarray(ep.backend.q) + np.array([4.0, 0, 4.0, 0, 0, 0, 0]))
    assert ep.handle({"op": "act", "action": target, "repeat": 2})["ok"]  # joints 3-4 go silent after this
    time.sleep(0.4)
    r = ep.handle({"op": "act", "action": target})
    assert time.time() - sdk.GetArmJointMsgs().time_stamp < 0.3  # the SDK's one stamp would have missed it
    assert not r["ok"] and "lost telemetry: no fresh joint reading from joints 3-4" in r["error"]
    assert ep.result["session"]["stop_kind"] == "telemetry_lost"
    ep.close()
    ev = _events(tmp_path / "ep")
    assert next(e for e in ev if e.get("kind") == "telemetry_lost")["source"] == "joints 3-4"
    holding = next(e for e in ev if e["event"] == "holding")
    last = [s for s in _steps(tmp_path / "ep") if "label" not in s][-1]
    assert holding["reason"].startswith("no fresh reading") and np.allclose(holding["pose"], last["cmd"], atol=6e-3)


def test_piper_pair_stamps_on_piper_sdk():
    """The per-pair stamps against the real SDK (piper_sdk 0.6.2; runs where piper_sdk and python-can are installed):
    joint feedback frames go through C_PiperInterface_V2.ParseCANFrame, without a CAN bus."""
    import struct

    can = pytest.importorskip("can")
    piper_sdk = pytest.importorskip("piper_sdk")
    from robouse.real.drivers.piper import PiperDriver
    from robouse.real.robots import PIPER

    sdk = piper_sdk.C_PiperInterface_V2("robouse-test", can_auto_init=False)
    drv = PiperDriver(PIPER, {}, sdk_factory=lambda cfg: sdk)
    drv.sdk = sdk
    drv._stamp_pairs()

    def frame(can_id: int, a: int, b: int) -> None:  # two joints in 0.001 deg, as the arm sends them
        sdk.ParseCANFrame(can.Message(arbitration_id=can_id, data=struct.pack(">ii", a, b), timestamp=time.time()))

    for can_id in (0x2A5, 0x2A6, 0x2A7):  # joints 1-2, 3-4, 5-6
        frame(can_id, 1000, 2000)
    assert all(t is not None for t in drv._pairs.values())
    time.sleep(0.2)
    frame(0x2A5, 3000, 4000)
    frame(0x2A7, 3000, 4000)
    frame(0x2A6, 4_000_000, 0)  # an abnormal frame, dropped by the SDK: it does not refresh joints 3-4
    r = drv.read()
    assert r.stamp_of == "joints 3-4" and time.monotonic() - r.stamp >= 0.2
    assert time.time() - sdk.GetArmJointMsgs().time_stamp < 0.1  # the SDK's own stamp: the newest pair
    assert r.q[:6].tolist() == [3.0, 4.0, 1.0, 2.0, 3.0, 4.0]  # joints 3-4 kept their last values


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
        assert r.stamp is not None and time.monotonic() - r.stamp < 1.0  # dated by the last joint state message
        assert r.extra["joint_torque_nm"] == [0.0, 0.0, 0.0]  # the JointState effort
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


# ---- safety stops: helpers ---------------------------------------------------------------------------------------------


def _events(ep_dir: Path) -> list[dict]:
    return [json.loads(l) for l in (ep_dir / "session" / "events.jsonl").read_text().splitlines()]


def _playback(tmp_path, monkeypatch, fixture: str, **real_overrides):
    """An episode on the replay mock in playback mode: each control step returns the next step recorded on the bench
    (joints, torques, temperatures), whatever is commanded."""
    from robouse.real.replay import Fixture

    monkeypatch.setenv("ROBOUSE_HIL_DIR", str(HIL))
    fx = Fixture(fixture)
    ep = _episode(
        "real-metal-reach",
        tmp_path,
        fixture=fixture,
        mock_playback=True,
        envelope=fx.meta.get("session_envelope"),  # the guard settings the session ran with
        **real_overrides,
    )
    ep.max_steps = 5000
    return ep, fx


def _replay(ep, fx, until: float | None = None, wiggle: float = 0.0) -> list[tuple[dict, dict]]:
    """Send the recorded commands as `robo act`, each matched to the recorded step the mock serves next (a hold the
    safety layer commands takes a step too); returns (recorded step, response) for every error or reported contact.
    `wiggle` moves each gripper command by +-wiggle, as a policy streaming joint targets does."""
    robot = ep.backend.driver.robot
    out = []
    while robot.k + 1 < len(fx.steps) and not ep.finished:
        s = fx.steps[robot.k + 1]
        if until is not None and s["t"] > until:
            break
        cmd = list(s["cmd"])
        cmd[-1] += wiggle * (1 if len(robot.sent) % 2 else -1)
        r = ep.handle({"op": "act", "action": cmd})
        if not r["ok"] or "contact" in r["result"]:
            out.append((s, r))
    return out


# ---- gap 1: the loop watchdog acts; lost telemetry stops -----------------------------------------------------------------

# these tests set the absolute watchdog limits below a few control periods (the limits then stretch to those periods)
ABSOLUTE = {"watchdog_periods": 0, "watchdog_hard_periods": 0}


def test_watchdog_one_stall_is_logged_and_the_episode_goes_on(tmp_path):
    ep = _episode(
        "real-metal-reach",
        tmp_path,
        envelope={"watchdog_s": 0.15, "watchdog_hard_s": 2.0, "watchdog_max_stalls": 3, **ABSOLUTE},
        mock_fault={"kind": "slow", "at_step": 3, "steps": 1, "seconds": 0.3},
    )
    q = list(ep.backend.q)
    for _ in range(3):
        assert ep.handle({"op": "act", "action": q})["ok"]
    assert not ep.finished
    ep.close()
    ev = _events(tmp_path / "ep")
    assert [e["in_a_row"] for e in ev if e.get("kind") == "loop_stall"] == [1]
    assert not any(e["event"] == "stop" for e in ev)


def test_watchdog_hard_limit_stops_and_holds_until_the_operator_approves_parking(tmp_path):
    """A stalled step stops the episode; every arm joint's command is then brought to its measured position and the
    arm holds there: nothing moves on its own. At close the operator inspects it and approves parking (the scripted
    operator says yes): only then does it park slowly at its rest pose and is released there."""
    from robouse.real.robots import METAL

    ep = _episode(
        "real-metal-reach",
        tmp_path,
        envelope={"watchdog_s": 0.1, "watchdog_hard_s": 0.3, **ABSOLUTE},
        mock_fault={"kind": "slow", "at_step": 3, "steps": 1, "seconds": 0.45},
    )
    q = list(ep.backend.q)
    assert ep.handle({"op": "act", "action": q})["ok"]
    r = ep.handle({"op": "act", "action": q})
    assert not r["ok"] and "watchdog: a control step took" in r["error"]
    assert ep.finished and ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "watchdog"
    assert ep.result["session"]["secured"].startswith("holding at the present position")  # no parking on its own
    ep.close()
    assert ep.result["session"]["secured"] == "parked at the rest pose, torque released"  # after the operator's yes
    ev = _events(tmp_path / "ep")
    steps = [json.loads(l) for l in (tmp_path / "ep" / "session" / "log.jsonl").read_text().splitlines()]
    stalled = [s for s in steps if "label" not in s][-1]  # the last control step of the episode
    assert any(e["event"] == "stop" and e.get("kind") == "watchdog" and e["dt"] > 0.3 for e in ev)
    retarget = next(e for e in ev if e["event"] == "retarget")
    assert retarget["cause"] == "safety stop (watchdog)"
    assert np.allclose(retarget["pose"][:6], stalled["pos"][:6], atol=0.006)  # the arm joints held where they were
    names = [e["event"] for e in ev]
    gate = next(i for i, e in enumerate(ev) if e.get("gate") == "park")  # the operator's answer at close
    park = names.index("park")
    assert names.index("retarget") < names.index("holding") < gate < park < names.index("torque_released")
    assert ev[gate]["answer"] == "yes" and ev[park]["cause"] == "parking approved by the operator"
    assert np.allclose([s for s in steps if s.get("label") == "park"][-1]["pos"][:6], METAL.park[:6], atol=2.0)
    assert next(e for e in ev if e["event"] == "close")["release_torque"] is True
    assert ep.result["safety_events"]


def test_watchdog_stalls_in_a_row_stop(tmp_path):
    ep = _episode(
        "real-metal-reach",
        tmp_path,
        envelope={"watchdog_s": 0.1, "watchdog_hard_s": 5.0, "watchdog_max_stalls": 3, **ABSOLUTE},
        mock_fault={"kind": "slow", "at_step": 3, "steps": 3, "seconds": 0.2},
    )
    r = ep.handle({"op": "act", "action": list(ep.backend.q), "repeat": 6})
    assert not r["ok"] and "3 control steps in a row slower than 0.1 s" in r["error"]
    assert ep.outcome == "safety_stop" and ep.steps <= 3  # three slow steps in a row; a loaded machine may add one
    ep.close()
    ev = _events(tmp_path / "ep")
    assert [e["in_a_row"] for e in ev if e.get("kind") == "loop_stall"] == [1, 2, 3]


def test_stale_telemetry_stops_instead_of_going_on(tmp_path):
    """The Damiao bus keeps serving its last replies when the CAN link dies; with the bus silent for longer than the
    timeout, the next step stops the episode and holds the last command, not the stale reading."""
    ep = _episode(
        "real-metal-reach", tmp_path, envelope={"telemetry_timeout_s": 0.3}, mock_fault={"kind": "stale", "at_step": 3}
    )
    target = list(np.asarray(ep.backend.q) + np.array([3.0, 0, 0, 0, 0, 0, 0]))  # 3 deg of shoulder pan
    assert ep.handle({"op": "act", "action": target})["ok"]
    assert ep.handle({"op": "act", "action": target})["ok"]  # the bus has gone silent; its cache is still young
    time.sleep(0.5)  # the agent thinks; the link stays dead
    r = ep.handle({"op": "act", "action": target})
    assert not r["ok"] and "lost telemetry: no fresh joint reading" in r["error"]
    assert ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "telemetry_lost"
    ep.close()
    ev = _events(tmp_path / "ep")
    steps = [json.loads(l) for l in (tmp_path / "ep" / "session" / "log.jsonl").read_text().splitlines()]
    assert steps[-1]["pos"] == steps[-2]["pos"]  # the frozen reading
    holding = next(e for e in ev if e["event"] == "holding")  # the present position is unknown: no retarget, no parking
    retarget = next(e for e in ev if e["event"] == "retarget")
    assert "no fresh reading" in holding["reason"] and retarget["done"] is False and retarget["steps"] == 0
    assert not any(e["event"] == "park" for e in ev)
    assert np.allclose(holding["pose"], steps[-1]["cmd"], atol=0.006)  # the last command ...
    assert not np.allclose(holding["pose"], steps[-1]["pos"], atol=0.5)  # ... not the stale reading
    assert next(e for e in ev if e.get("kind") == "telemetry_lost")["age_s"] > 0.3


def test_dead_link_stops(tmp_path):
    ep = _episode("real-metal-reach", tmp_path, mock_fault={"kind": "dead", "at_step": 3})
    q = list(ep.backend.q)
    assert ep.handle({"op": "act", "action": q})["ok"]
    r = ep.handle({"op": "act", "action": q})
    assert not r["ok"] and "hardware fault: ConnectionError" in r["error"]
    assert ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "hardware_fault"
    ep.close()
    assert any(e["event"] == "hold_failed" for e in _events(tmp_path / "ep"))  # a dead link takes no hold either


def test_hot_motor_does_not_start(tmp_path):
    ep = _episode("real-metal-reach", tmp_path, envelope={"temp_stop_c": 20.0})  # recorded motors are at ~28 C
    ep.handle({"op": "observe"})
    assert ep.outcome == "safety_stop" and ep.steps == 0 and ep.result["session"]["stop_kind"] == "overtemperature"
    ep.close()


# ---- gap 2: the contact watch, on the recorded torque traces -----------------------------------------------------------


def test_contact_watch_rules():
    """The watch on synthetic streams: Sep 5 thresholds in a watched move, unwatched_factor x them elsewhere, the arm
    still watched while the gripper moves, and the stall (the touchdown criterion) on settled poses."""
    from robouse.real.contact import ContactWatch
    from robouse.real.robots import METAL

    q0 = np.asarray(METAL.home, dtype=float)
    tq0 = np.array([0.4, 9.0, 4.0, 0.3, 0.0, 0.0, 0.0])

    def feed(watch, steps, watched):
        """steps: (command offset on shoulder_lift, gripper command, torque change) per control step"""
        hits = []
        for dcmd, grip, dtq in steps:
            cmd = q0.copy()
            cmd[1] += dcmd
            cmd[6] = grip
            hits.append(watch.update(cmd, cmd, {"joint_torque_nm": list(tq0 + dtq)}, watched))
        return [h for h in hits if h is not None]

    drop = np.array([0, -1.6, 0, 0, 0, 0, 0])  # the shoulder unloads by 1.6 N m (threshold 1.5)
    move = [(0, 4, 0 * drop)] * 3 + [(0.5 * i, 4, 0 * drop) for i in range(1, 5)] + [(2.5, 4, drop)]
    (hit,) = feed(ContactWatch(METAL, METAL.contact), move, watched=True)
    assert hit.kind == "moving" and hit.watched and hit.change == {"shoulder_lift": -1.6}
    assert feed(ContactWatch(METAL, METAL.contact), move, watched=False) == []  # elsewhere: 5 x 1.5 N m
    push = np.array([0, 0, 8.0, 0, 0, 0, 0])  # the elbow pushes 8 N m (threshold 0.8 x 5)
    (hit,) = feed(ContactWatch(METAL, METAL.contact), move[:-1] + [(2.5, 4, push)], watched=False)
    assert hit.kind == "moving" and not hit.watched
    hold = [(0, 4, 0 * drop)] * 4
    (hit,) = feed(ContactWatch(METAL, METAL.contact), hold + [(0, 4, push)], watched=False)
    assert hit.kind == "holding"
    # the gripper closes and the shoulder twitches by 1.11 N m every other step: the most gripper motion moved it on the
    # Sep 5 recordings (0.74 of its 1.5 N m threshold)
    twitch = np.array([0, -1.11, 0, 0, 0, 0, 0])
    grasp = [(0, 4 + 10 * i, twitch * (i % 2)) for i in range(1, 6)]
    assert feed(ContactWatch(METAL, METAL.contact), hold + grasp + hold, watched=True) == []
    bump = [(0, 4 + 10 * i, drop * (i >= 3)) for i in range(1, 6)]  # ... or something pushes the arm meanwhile
    (hit,) = feed(ContactWatch(METAL, METAL.contact), hold + bump, watched=True)
    assert hit.kind == "holding" and hit.change == {"shoulder_lift": -1.6}
    for grip_step in (0.2, 1.0):  # a policy streaming joint targets moves the gripper every step: the same contact
        streamed = [(dcmd, 4 + grip_step * k, dtq) for k, (dcmd, _, dtq) in enumerate(move)]
        (hit,) = feed(ContactWatch(METAL, METAL.contact), streamed, watched=True)
        assert hit.kind == "moving" and hit.change == {"shoulder_lift": -1.6}

    # the stall: tool height in mm on shoulder_pan for the test; the command descends 2 mm a move, the arm stops at 0
    def tool(q):
        return np.array([0.3, 0.0, q[0] / 1000])

    watch = ContactWatch(METAL, METAL.contact, tool=tool)
    hits = []
    for z in (20.0, 18.0, 16.0, 14.0, 12.0, 10.0, 8.0, 6.0, 4.0, 2.0, 0.0, -2.0, -4.0, -6.0):
        cmd, q = q0.copy(), q0.copy()
        cmd[0], q[0] = z, max(z, 0.5) - 3.0  # 3 mm of sag; the table stops the tool at 0.5 mm
        for _ in range(4):  # move, then settle
            hits.append(watch.update(cmd, q, {}, True))
    (hit,) = [h for h in hits if h is not None]
    assert hit.kind == "stall" and hit.change["tool_shortfall_mm"] == pytest.approx(4.5)  # at the -4 mm command


@pytest.mark.parametrize("wiggle", [0.0, 0.05])
def test_contact_watch_quiet_on_recorded_motion_then_stops_at_the_elbow_stop(tmp_path, monkeypatch, wiggle):
    """Verified contact (2026-09-05 13:16, fixture metal-hanoi-131602 from the recorder's log): 91 s of normal motion
    replay without a contact; then the elbow straightens against its mechanical stop, away from the table: a contact
    outside a watched move stops the episode, and the arm joints' command goes to where they are, so nothing pushes
    against the stop. The guard itself no longer commands the elbow past 174 deg (Sep 5 commanded 180). The same with
    the gripper command moving every step (a streaming policy): gripper motion does not mute the arm's watch."""
    ep, fx = _playback(tmp_path, monkeypatch, "metal-hanoi-131602")
    hits = _replay(ep, fx, wiggle=wiggle)
    assert len(hits) == 1
    step, r = hits[0]
    assert step["label"] == "peg1_s_3" and 91.8 <= step["t"] <= 92.0
    assert not r["ok"] and "contact outside a watched move" in r["error"]
    assert ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "contact"
    ep.close()
    ev = _events(tmp_path / "ep")
    contact = next(e for e in ev if e["event"] == "contact")
    assert contact["watched"] is False and contact["change"]["elbow_flex"] > 5.0
    steps = [json.loads(l) for l in (tmp_path / "ep" / "session" / "log.jsonl").read_text().splitlines()]
    episode = [s for s in steps if "label" not in s]  # the episode's control steps (not the retarget or parking)
    assert max(s["cmd"][2] for s in episode) <= 174.0  # the elbow command stays under the soft limit ...
    assert max(s["pos"][2] for s in episode) > 176.0  # ... while the recorded arm sat at its stop
    retarget = next(e for e in ev if e["event"] == "retarget")
    assert retarget["pose"][2] == pytest.approx(176.36, abs=0.05)  # the command goes to where the elbow is


def test_contact_stall_on_the_recorded_table_touchdown(tmp_path, monkeypatch):
    """Verified contact (2026-09-05 12:17, fixture metal-touchdown-121740): the fingertips stall on the table. Torque
    alone did not show it on Sep 5 either; the stall check does, in a watched move: the move stops, the arm holds, the
    agent is told, and the episode goes on."""
    ep, fx = _playback(tmp_path, monkeypatch, "metal-touchdown-121740")
    hits = _replay(ep, fx)
    assert len(hits) == 1
    step, r = hits[0]
    assert step["label"].startswith("td_-1mm")
    c = r["result"]["contact"]
    assert r["ok"] and c["kind"] == "stall" and c["count"] == 1 and c["limit"] == 2
    assert c["change"]["tool_shortfall_mm"] > 4.0 and "resting on something" in c["what"]
    assert not ep.finished and ep.backend.target is not None
    ep.close()
    (contact,) = [e for e in _events(tmp_path / "ep") if e["event"] == "contact"]
    assert contact["watched"] is True and contact["action"].startswith("move stopped")


@pytest.mark.parametrize("wiggle", [0.0, 0.05])
def test_contacts_in_watched_moves_then_one_too_many(tmp_path, monkeypatch, wiggle):
    """The HIL fixture's own recording (12:18:53): the Sep 5 watch flagged two contacts on the way down to a bead (the
    second, on the final descent, very likely real: the grasp that followed needs the tips at table level). The first
    stops the move and is reported to the agent; the second is one too many. The same with the gripper command
    moving +-0.05 every step, as a policy streaming joint targets sends it."""
    ep, fx = _playback(tmp_path, monkeypatch, "metal-bowl-121853")
    hits = _replay(ep, fx, wiggle=wiggle)
    assert [round(s["t"], 2) for s, _ in hits] == [56.24, 63.17]
    first, second = hits[0][1], hits[1][1]
    assert first["ok"] and first["result"]["contact"]["count"] == 1 and first["result"]["contact"]["kind"] == "moving"
    assert not second["ok"] and "repeated contacts (2 in this episode, limit 2)" in second["error"]
    assert ep.outcome == "safety_stop" and ep.result["session"]["contacts"] == 2
    ep.close()


def test_contact_stops_act_repeat_and_skill(tmp_path, monkeypatch):
    ep, fx = _playback(tmp_path, monkeypatch, "metal-bowl-121853", contact={"max_contacts": 3})
    _replay(ep, fx, until=56.2)  # up to the step before the first recorded contact
    s = fx.steps[ep.backend.driver.robot.k + 1]
    r = ep.handle({"op": "act", "action": s["cmd"], "repeat": 10})
    assert r["ok"] and r["result"]["executed_steps"] == 1 and r["result"]["contact"]["kind"] == "moving"
    _replay(ep, fx, until=63.1)  # up to the step before the second
    goal = fx.steps[ep.backend.driver.robot.k + 1]["cmd"]  # continue the recorded descent
    r = ep.handle({"op": "skill", "name": "move_joints", "args": [str(v) for v in goal[:6]] + ["0.5"]})
    assert r["ok"] and r["result"]["stopped"] == "by the safety layer" and r["result"]["contact"]["count"] == 2
    assert r["result"]["executed_steps"] == 1 and not ep.finished
    ep.close()


# ---- after a stop, at the end and when interrupted: no push; park only at a normal end or on the operator's yes ----------


def _steps(ep_dir: Path) -> list[dict]:
    return [json.loads(l) for l in (ep_dir / "session" / "log.jsonl").read_text().splitlines()]


def _within_delta_limit(sent, guard) -> bool:
    """Every command differs from the one before by at most the per-step limit (commands are recorded to 1e-3)."""
    return bool(np.all(np.abs(np.diff(np.asarray(sent, dtype=float), axis=0)) <= guard.max_step + 2e-3))


def test_stop_and_close_leave_no_push_on_the_elbow_replay(tmp_path, monkeypatch):
    """The 13:16 replay: after the contact stop, and again after close(), the arm joints' last command is where the arm
    is, so nothing pushes against the stop. Every command got there through the per-step delta limit, and the gripper
    kept its command. Nothing moved on its own: the only park is the one the operator approved at close, and the
    replayed arm, which does not follow commands, never reaches its rest pose, so it holds and the operator is told."""
    ep, fx = _playback(tmp_path, monkeypatch, "metal-hanoi-131602")
    robot, b = ep.backend.driver.robot, ep.backend
    _replay(ep, fx)
    assert ep.outcome == "safety_stop" and ep.result["session"]["secured"].startswith("holding at the present position")
    # the command is the pose the arm was measured at when it stopped (the recording itself moves on; a real arm would not)
    stopped = [e for e in _events(tmp_path / "ep") if e["event"] == "retarget"][-1]
    assert stopped["pose"][2] == pytest.approx(176.36, abs=0.05)
    assert np.allclose(robot.sent[-1][:6], stopped["pose"][:6], atol=6e-3)
    ep.close()
    last = [e for e in _events(tmp_path / "ep") if e["event"] == "retarget"][-1]  # after the approved park stopped
    assert np.allclose(robot.sent[-1][:6], last["pose"][:6], atol=6e-3)
    n = sum(1 for s in _steps(tmp_path / "ep") if "label" not in s)  # sent[0] holds at connect, then one per step
    assert _within_delta_limit(robot.sent[n:], b.guard)  # from the stopping step on (retarget, parking, holds)
    assert {c[6] for c in robot.sent[n:]} == {robot.sent[n][6]}  # from the stopping step on, the gripper's command
    ev = _events(tmp_path / "ep")
    holds = [e for e in ev if e["event"] == "holding"]
    assert [h["cause"] for h in holds] == ["safety stop (contact)", "parking approved by the operator"]
    assert holds[0]["reason"] == "after a stop the arm does not move on its own"
    assert holds[1]["reason"].endswith("it holds where it stopped")  # the approved park could not reach rest
    names = [e["event"] for e in ev]
    gate = next(i for i, e in enumerate(ev) if e.get("gate") == "park")
    assert names.count("park") == 1 and names.index("holding") < gate < names.index("park")  # one approved attempt
    notices = [e["text"] for e in ev if e["event"] == "operator_notice"]
    assert len(notices) == 2 and all("holding at its present position with torque on" in n for n in notices)
    assert next(e for e in ev if e["event"] == "close")["release_torque"] is False


def test_end_of_episode_parks_and_releases_torque_at_rest(tmp_path):
    from robouse.real.robots import METAL

    ep = _episode("real-metal-reach", tmp_path)
    robot = ep.backend.driver.robot
    assert ep.handle({"op": "skill", "name": "move_to", "args": ["0.30", "-0.10", "0.08"]})["ok"]
    ep.finish("done", "")
    ep.close()
    ev = _events(tmp_path / "ep")
    names = [e["event"] for e in ev]
    assert names.index("retarget") < names.index("park") < names.index("torque_released") < names.index("close")
    assert next(e for e in ev if e["event"] == "retarget")["cause"] == "end of episode"
    assert next(e for e in ev if e["event"] == "close")["release_torque"] is True and not robot.connected
    parked = [json.loads(l) for l in (tmp_path / "ep" / "session" / "log.jsonl").read_text().splitlines()][-1]
    assert parked["label"] == "park" and np.allclose(parked["pos"][:6], METAL.park[:6], atol=2.0)  # at rest there


def test_estop_stop_holds_at_the_present_position_and_says_why(tmp_path):
    from robouse.real import safety

    ep = _episode("real-metal-reach", tmp_path)
    robot = ep.backend.driver.robot
    assert ep.handle({"op": "act", "action": list(ep.backend.q), "repeat": 2})["ok"]
    gripper = ep.backend.guard.last_cmd[6]  # the gripper's command when the e-stop comes
    safety.set_estop("test")
    assert not ep.handle({"op": "act", "action": list(ep.backend.q)})["ok"]
    assert ep.outcome == "safety_stop"
    ep.close()
    safety.clear_estop()
    ev = _events(tmp_path / "ep")
    holds = [e for e in ev if e["event"] == "holding"]  # at the stop, and after the operator's yes to parking:
    assert holds[0]["reason"] == "after a stop the arm does not move on its own"
    assert len(holds) == 2 and holds[1]["reason"].startswith("the e-stop is latched")  # ... which the latch refused
    assert not any(e["event"] in ("park", "torque_released") for e in ev)
    # the arm joints' last command is where the last retarget measured them; the gripper kept its command
    retarget = [e for e in ev if e["event"] == "retarget"][-1]
    assert np.allclose(robot.sent[-1][:6], retarget["pose"][:6], atol=6e-3)
    assert robot.sent[-1][6] == pytest.approx(gripper, abs=1e-3)


def test_operator_notices_reach_the_file_channel():
    from robouse.real import operator
    from robouse.real.operator import Operator

    logged: list = []
    Operator("file", mock=False, log=lambda kind, **kw: logged.append((kind, kw))).notify("the arm is holding")
    notice = json.loads((operator.OPERATOR_DIR / "notices.jsonl").read_text().splitlines()[-1])
    assert notice["text"] == "the arm is holding"
    assert logged == [("operator_notice", {"text": "the arm is holding", "channel": "file"})]


def test_interruption_holds_the_arm(tmp_path):
    """A terminate request to a real-robot episode server (a run interrupted) ends the episode, and the arm holds where
    it is before the server exits: nothing moves on its own, and nothing is asked."""
    import signal
    import subprocess
    import sys

    task = _real_task_root(tmp_path) / "real-metal-reach"
    run_dir, ready = tmp_path / "ep", tmp_path / "ready"
    cmd = [sys.executable, "-m", "robouse.cli", "serve", "--task", str(task), "--run-dir", str(run_dir)]
    proc = subprocess.Popen(cmd + ["--socket", str(tmp_path / "s.sock"), "--ready-file", str(ready)])
    for _ in range(600):
        if ready.exists():
            break
        time.sleep(0.1)
    assert ready.exists()
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=60)
    ev = _events(run_dir)
    assert next(e for e in ev if e["event"] == "retarget")["cause"] == "interruption"
    assert next(e for e in ev if e["event"] == "holding")["cause"] == "interruption"
    assert not any(e["event"] in ("park", "torque_released") or e.get("gate") == "park" for e in ev)
    assert next(e for e in ev if e["event"] == "close")["release_torque"] is False
    assert json.loads((run_dir / "result.json").read_text())["outcome"] == "agent_exited"


def test_ros_rig_without_a_rest_pose_holds(tmp_path):
    """A ROS arm parks only at a rest pose its rig file names (an all-zero pose may be an outstretched arm)."""
    ep = _episode("real-ros-joint-pose", tmp_path, park=None)
    assert not any(s.startswith("park") for s in ep.handle({"op": "info"})["result"]["skills"])
    ep.close()
    holding = next(e for e in _events(tmp_path / "ep") if e["event"] == "holding")
    assert holding["reason"] == "the robot profile has no rest pose"


def test_ros_arm_parks_and_keeps_holding(tmp_path):
    """The ROS bridge cannot turn the motors off: at the end the arm parks at the rig's rest pose and holds there, and
    the session log and the operator are told so."""
    ep = _episode("real-ros-joint-pose", tmp_path)
    assert ep.handle({"op": "skill", "name": "move_joints", "args": ["30", "-70", "60", "-80", "-90", "20"]})["ok"]
    ep.finish("done", "")
    ep.close()
    ev = _events(tmp_path / "ep")
    names = [e["event"] for e in ev]
    assert names.index("retarget") < names.index("park") < names.index("parked") < names.index("close")
    assert "torque_released" not in names and ev[names.index("close")]["release_torque"] is False
    assert ep.backend.secured == "parked at the rest pose, holding there (the driver cannot release torque)"
    assert any("holding there with torque on" in e["text"] for e in ev if e["event"] == "operator_notice")


# ---- gap 3: a safety stop halts a batch on a real robot -----------------------------------------------------------------


def _real_task_root(tmp_path: Path, **real_extra) -> Path:
    """A copy of real-metal-reach with extra `real:` settings; the server exits as soon as the episode ends."""
    import shutil

    root = tmp_path / "tasks"
    shutil.copytree(ROOT / "tasks" / "real" / "real-metal-reach", root / "real-metal-reach")
    md = root / "real-metal-reach" / "task.md"
    text = md.read_text().replace("  max_steps: 300\n", "  max_steps: 300\n  linger_s: 0\n")
    extra = "".join(f"    {k}: {json.dumps(v)}\n" for k, v in real_extra.items())
    md.write_text(text.replace("    driver: mock\n", "    driver: mock\n" + extra))
    return root


def test_batch_halts_after_a_safety_stop_without_an_operator(tmp_path):
    from robouse.real import safety
    from robouse.runner import run_many

    safety.set_estop("operator test")  # every trial would stop at reset
    results = run_many(_real_task_root(tmp_path, attended=False), "noop", "", tmp_path / "job", seeds="0-2")
    safety.clear_estop()
    (r,) = results  # the first trial stopped; the other two never started
    assert r["outcome"] == "safety_stop" and r["halted_batch"]["kind"] == "estop"
    halt = json.loads((tmp_path / "job" / "halt.json").read_text())
    assert halt["trial"] == r["trial"] and "e-stop is engaged" in halt["reason"] and halt["answer"] == "none"
    log = [json.loads(l) for l in (tmp_path / "job" / "run_log.jsonl").read_text().splitlines()]
    assert log[-1]["not_run"] == ["real-metal-reach@seed1", "real-metal-reach@seed2"]
    ev = _events(tmp_path / "job" / r["trial"] / "episode")
    assert [e["event"] for e in ev][-2:] == ["batch_hold", "batch_halt"]


@pytest.mark.parametrize("answer", ["yes", "no"])
def test_batch_waits_for_the_operator_after_a_safety_stop(tmp_path, monkeypatch, answer):
    from robouse.real import safety
    from robouse.runner import run_many

    monkeypatch.setenv("ROBOUSE_OPERATOR_SCRIPT", f"inspect={answer}")  # the mock's scripted operator
    safety.set_estop("operator test")
    results = run_many(_real_task_root(tmp_path), "noop", "", tmp_path / "job", seeds="0-1")
    safety.clear_estop()
    assert len(results) == (2 if answer == "yes" else 1)
    assert all(r["outcome"] == "safety_stop" for r in results)
    assert (tmp_path / "job" / "halt.json").exists() == (answer == "no")
    for r in results:  # the inspection is in the stopped trial's session log
        ev = _events(tmp_path / "job" / r["trial"] / "episode")
        gate = next(e for e in ev if e.get("gate") == "inspect")
        assert gate["answer"] == answer and gate["channel"] == "script"
        assert ev[-1]["event"] == ("batch_resume" if answer == "yes" else "batch_halt")


def test_batch_inspection_on_the_file_channel(tmp_path):
    """A live rig's operator answers from another terminal (`robouse operator answer yes --note ...`)."""
    from robouse.real import batch, operator

    stop = {"trial": "t1", "task": "real-metal-reach", "mode": "real", "kind": "contact", "reason": "contact",
            "attended": True, "channel": "file"}  # fmt: skip
    answered = threading.Event()

    def operator_terminal():
        for _ in range(400):
            if (operator.OPERATOR_DIR / "pending.json").exists():
                operator.answer("yes", "checked the elbow and the table")
                answered.set()
                return
            time.sleep(0.02)

    threading.Thread(target=operator_terminal, daemon=True).start()
    assert batch.inspect(stop, tmp_path)
    assert answered.is_set() and not (tmp_path / "halt.json").exists()
    ev = _events(tmp_path / "t1" / "episode")
    gate = next(e for e in ev if e.get("gate") == "inspect")
    assert gate["answer"] == "yes" and gate["note"] == "checked the elbow and the table" and gate["channel"] == "file"


# ---- gap 4: a live robot is not armed without a confirmed physical e-stop -------------------------------------------------


def _live_metal(monkeypatch) -> list:
    """The LeRobot driver (a live driver, not the mock) on a replay robot, as if the Metal arm were plugged in."""
    from robouse.real.drivers import lerobot_arm
    from robouse.real.replay import Fixture, ReplayRobot

    made: list = []

    def factory(cfg, prof):
        made.append(ReplayRobot(Fixture("metal-bowl-121853"), prof, cameras=[]))
        return made[-1]

    monkeypatch.setitem(lerobot_arm.FACTORIES, "metal", factory)
    return made


def _operator_terminal(answers: dict, stop: threading.Event) -> None:
    """Answers each pending operator request from `answers` (`robouse operator answer` in another terminal)."""
    from robouse.real import operator

    done: set = set()
    while not stop.is_set():
        try:
            req = json.loads((operator.OPERATOR_DIR / "pending.json").read_text())
        except (OSError, ValueError):
            req = None
        if req and req["id"] not in done:
            done.add(req["id"])
            operator.answer(answers.get(req["key"], "no"), note=f"test operator: {req['key']}")
        time.sleep(0.02)


def _live_episode(tmp_path, monkeypatch, answers: dict, **real_overrides):
    made = _live_metal(monkeypatch)
    stop = threading.Event()
    threading.Thread(target=_operator_terminal, args=(answers, stop), daemon=True).start()
    try:
        ep = _episode(
            "real-metal-reach",
            tmp_path,
            driver="lerobot",
            operator="file",
            port="test",
            operator_timeout_s=10,
            pace=False,  # the replay robot needs no real-time pacing (parking at the end is 20 s paced)
            **real_overrides,
        )
    finally:
        stop.set()
    return ep, made


def test_live_robot_needs_a_confirmed_physical_estop(tmp_path, monkeypatch):
    ep, made = _live_episode(tmp_path, monkeypatch, {"physical_estop": "yes", "arm": "yes", "reset": "yes"})
    assert ep.mode == "real" and not ep.finished and made
    safety = ep.handle({"op": "info"})["result"]["embodiment"]["safety"]
    assert safety["physical_estop"] == "confirmed by the operator before the robot is armed"
    ep.close()
    ev = _events(tmp_path / "ep")
    order = [(e["event"], e.get("gate")) for e in ev]
    assert order.index(("operator_gate", "physical_estop")) < order.index(("connect", None))
    gate = next(e for e in ev if e.get("gate") == "physical_estop")
    assert gate["answer"] == "yes" and gate["channel"] == "file"
    assert ep.result["session"]["physical_estop"]["answer"] == "yes"


def test_physical_estop_cannot_be_skipped_for_a_live_robot(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOUSE_REAL_UNATTENDED", "1")
    ep, made = _live_episode(tmp_path, monkeypatch, {"physical_estop": "no"}, attended=False, estop_check=False)
    ep.handle({"op": "observe"})
    assert ep.outcome == "safety_stop" and ep.steps == 0 and ep.result["session"]["stop_kind"] == "physical_estop"
    assert not made  # never connected: nothing was armed
    ep.close()
    ev = _events(tmp_path / "ep")
    assert next(e for e in ev if e.get("gate") == "physical_estop")["answer"] == "no"
    assert not any(e["event"] == "connect" for e in ev)


def test_mock_skips_the_physical_estop_unless_the_task_asks(tmp_path, monkeypatch):
    ep = _episode("real-metal-reach", tmp_path)
    assert ep.handle({"op": "info"})["result"]["embodiment"]["safety"]["physical_estop"].startswith("not asked")
    ep.close()
    assert any(e["event"] == "physical_estop" and e["confirmed"] is None for e in _events(tmp_path / "ep"))
    monkeypatch.setenv("ROBOUSE_OPERATOR_SCRIPT", "physical_estop=no")
    ep = _episode("real-metal-reach", tmp_path / "b", estop_check=True)
    ep.handle({"op": "observe"})
    assert ep.outcome == "safety_stop" and ep.steps == 0
    ep.close()


# ---- independent review, 2026-10-02 (R1-R8) ------------------------------------------------------------------------------


def test_settle_contact_on_the_recorded_descent_is_a_safety_stop(tmp_path, monkeypatch):
    """R1 on recorded torque (metal-bowl-121853): `done` just before the first recorded contact, so the arm settles onto
    it during the settle steps. That contact is a safety stop that holds a batch, no later command returns to the one
    from before it, and the motors are left on where the arm is."""
    from robouse.real import batch

    ep, fx = _playback(tmp_path, monkeypatch, "metal-bowl-121853")
    robot = ep.backend.driver.robot
    assert _replay(ep, fx, until=56.2) == []
    before = np.asarray(robot.sent[-1], dtype=float)  # the last command before `done`
    ep.handle({"op": "done", "text": ""})
    assert ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "contact" and not ep.result["success"]
    assert "settle steps" in ep.result["session"]["safety_stop"]
    ep.close()
    contact = next(e for e in _events(tmp_path / "ep") if e["event"] == "contact")
    assert contact["watched"] and contact["action"].startswith("safety stop: a contact during the settle steps")
    n = sum(1 for s in _steps(tmp_path / "ep") if "label" not in s)  # connect, then the episode's and settle steps
    after = np.asarray(robot.sent[n + 1 :], dtype=float)  # everything after the step that met the contact
    assert len(after) and not np.any(np.all(np.abs(after[:, :6] - before[:6]) < 1e-3, axis=1))
    retarget = [e for e in _events(tmp_path / "ep") if e["event"] == "retarget"][-1]
    assert np.allclose(robot.sent[-1][:6], retarget["pose"][:6], atol=6e-3)  # left on where the arm is
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps({"episode": ep.result}))
    assert batch.stop_of(trial)["kind"] == "contact"  # run-many holds the batch


def test_settle_contact_injected_on_the_tracking_mock(tmp_path):
    """R1: a contact reported at the third settle step ends the settle steps as a safety stop (the episode is not
    `done`); the arm is secured from where it is."""
    from robouse.real.contact import Contact

    ep = _episode("real-metal-reach", tmp_path)
    b = ep.backend
    target = np.asarray(b.q, dtype=float)
    target[0] += 6.0  # a sideways move
    assert ep.handle({"op": "act", "action": list(target), "repeat": 4})["ok"]
    orig, calls = b.watch.update, []

    def update(cmd, q, extra, watched):
        calls.append(1)
        hit = orig(cmd, q, extra, watched)
        return Contact("stall", True, {"tool_shortfall_mm": 5.0}, b.watch.n) if len(calls) == 3 else hit

    b.watch.update = update
    ep.handle({"op": "done", "text": ""})
    assert sum(1 for s in _steps(tmp_path / "ep") if "label" not in s) == 4 + 3  # no settle step after the contact
    assert ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "contact"
    names = [e["event"] for e in _events(tmp_path / "ep")]
    assert names.index("contact") < names.index("stop") < names.index("retarget")
    ep.close()


def test_ros_frozen_joint_states_keep_the_last_command(tmp_path):
    """R3: the robot stops publishing /joint_states but still takes commands. The stop is lost telemetry (not a
    hardware fault), and the robot keeps the last command: the frozen reading behind it is never sent."""
    ep = _episode("real-ros-joint-pose", tmp_path)
    b, srv = ep.backend, ep.backend.driver.mock_server
    target = np.asarray(b.q, dtype=float)
    target[0] += 40.0
    assert ep.handle({"op": "act", "action": list(target), "repeat": 3})["ok"]
    srv._stop.set()  # no more joint states; the command topic still works
    t0 = time.time()
    while ep.handle({"op": "act", "action": list(target)})["ok"]:
        assert time.time() - t0 < 5
    assert ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "telemetry_lost"
    frozen = float(b.q[0])
    ep.close()
    cmds = np.degrees(np.asarray(srv.commands, dtype=float))
    last = int(np.argmax(cmds[:, 0]))  # the furthest command toward the target ...
    assert np.allclose(cmds[last:], cmds[last], atol=1e-6)  # ... is the last one the robot gets: no jump back
    assert cmds[-1][0] - frozen > 2.0  # the frozen reading, degrees behind it, was never sent
    holding = next(e for e in _events(tmp_path / "ep") if e["event"] == "holding")
    assert "no fresh reading" in holding["reason"]


def _failing_batch_root(tmp_path):
    from robouse.real import safety

    safety.set_estop("review test")  # every trial stops at reset
    return _real_task_root(tmp_path, attended=False)


@pytest.mark.parametrize("where", ["inspect", "stop_of", "run_trial"])
def test_batch_fails_closed(tmp_path, monkeypatch, where):
    """R4: an exception in the batch hold (the trial itself, reading its result, the inspection; e.g. a full disk)
    ends the batch: no further trial starts, and halt.json says why."""
    from robouse.real import batch, safety
    from robouse.runner import jobs, run_many

    def fail(*a, **kw):
        raise OSError(28, "No space left on device")

    if where == "run_trial":
        real_run = jobs.run_trial

        def run_trial(*a, **kw):
            real_run(*a, **kw)
            fail()

        monkeypatch.setattr(jobs, "run_trial", run_trial)
    else:
        monkeypatch.setattr(batch, where, fail)
    root = _failing_batch_root(tmp_path)
    try:
        results = run_many(root, "noop", "", tmp_path / "job", seeds="0-3")
    finally:
        safety.clear_estop()
    assert len([p for p in (tmp_path / "job").iterdir() if p.is_dir()]) == 1  # one trial ran, three never started
    (r,) = results
    assert r["halted_batch"]["kind"] == "batch_error" and "No space left on device" in r["halted_batch"]["reason"]
    assert json.loads((tmp_path / "job" / "halt.json").read_text())["kind"] == "batch_error"


def test_batch_fails_closed_through_the_cli(tmp_path, monkeypatch):
    """R4: run-many prints the reason and exits 3."""
    from robouse.cli import main
    from robouse.core import gl
    from robouse.real import batch, safety

    def fail(*a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(batch, "inspect", fail)
    monkeypatch.setattr(gl, "auto_select", lambda: None)  # leave the process's GL settings alone
    root = _failing_batch_root(tmp_path)
    try:
        rc = main(
            ["run-many", "--tasks", str(root), "--harness", "noop", "--out", str(tmp_path / "job"), "--seeds", "0-3"]
        )
    finally:
        safety.clear_estop()
    assert rc == 3


@pytest.mark.parametrize("fault", ["estop", "overtemperature", "telemetry_lost"])
def test_idle_check_watches_the_arm_between_requests(tmp_path, fault):
    """R5: while the agent thinks, the arm is read at least once a second: an e-stop, a hot motor or a link gone
    quiet stops the episode and holds the arm, as at a control step. Right after a step it waits."""
    from robouse.real import safety

    real = {"envelope": {"telemetry_timeout_s": 0.3}, "mock_fault": {"kind": "stale", "at_step": 2}}
    ep = _episode("real-metal-reach", tmp_path, **(real if fault == "telemetry_lost" else {}))
    b, robot = ep.backend, ep.backend.driver.robot
    assert ep.handle({"op": "act", "action": list(b.q)})["ok"]
    ep.idle()
    assert not any(s.get("label") == "idle" for s in _steps(tmp_path / "ep"))  # checked less than a second ago
    if fault == "estop":
        safety.set_estop("idle test")
    elif fault == "overtemperature":
        robot.fx.telemetry = lambda k, **kw: {"temp_mos_c": [30.0] * 7, "temp_rotor_c": [30.0] * 6 + [70.0]}
    else:
        time.sleep(0.4)  # the bus answers nothing more
    b._last_check -= b.IDLE_CHECK_S  # a second has passed
    ep.idle()
    safety.clear_estop()
    assert ep.finished and ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == fault
    ep.close()
    ev = _events(tmp_path / "ep")
    if fault == "telemetry_lost":  # the present position is unknown: the last command is held
        assert next(e for e in ev if e["event"] == "holding")["reason"].startswith("no fresh reading")
    else:
        assert any(e["event"] == "retarget" for e in ev)


def test_server_watches_the_arm_while_no_request_comes(tmp_path):
    """R5 end to end: an e-stop latched while the agent sends nothing ends the episode within about a second."""
    from robouse.real import safety
    from robouse.session import serve
    from robouse.tasks import load_task

    spec = load_task(_real_task_root(tmp_path) / "real-metal-reach").spec
    ready, sock = tmp_path / "ready", str(tmp_path / "s.sock")
    th = threading.Thread(target=serve, args=(spec, tmp_path / "ep", sock), kwargs={"ready_file": ready}, daemon=True)
    th.start()
    for _ in range(300):
        if ready.exists():
            break
        time.sleep(0.05)
    t0 = time.time()
    safety.set_estop("idle test")
    th.join(timeout=15)
    safety.clear_estop()
    res = json.loads((tmp_path / "ep" / "result.json").read_text())
    assert not th.is_alive() and time.time() - t0 < 5
    assert res["outcome"] == "safety_stop" and res["session"]["stop_kind"] == "estop" and res["requests"] == 0


def test_live_rig_trials_run_one_at_a_time(tmp_path, monkeypatch, capsys):
    """R6: with a rig from ROBOUSE_RIG (not only --rig), live-robot trials run one at a time whatever --concurrency
    says, so a stop holds every later trial."""
    import uuid

    from robouse.cli import main
    from robouse.runner import jobs

    rig = tmp_path / "rig.yaml"
    rig.write_text("metal:\n  driver: lerobot\n  port: /dev/null\n")
    monkeypatch.setenv("ROBOUSE_RIG", str(rig))
    root = _real_task_root(tmp_path)
    assert main(["run-many", "--tasks", str(root), "--harness", "noop", "--out", str(tmp_path / "x"),
                 "--seeds", "0-3", "--concurrency", "4", "--dry-run"]) == 0  # fmt: skip
    assert json.loads(capsys.readouterr().out)["concurrency"] == 1
    lock, running, peak = threading.Lock(), [0], [0]

    def run_trial(t, harness, model, job_dir, **kw):  # a stand-in trial: no robot is driven
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.2)
        name = f"{t.id}__{uuid.uuid4().hex[:6]}"
        (job_dir / name).mkdir(parents=True)
        res = {"episode": {"outcome": "done", "embodiment_mode": "real", "session": {}}}
        (job_dir / name / "result.json").write_text(json.dumps(res))
        with lock:
            running[0] -= 1
        return {"trial": name, "reward": 0.0, "outcome": "done", "steps": 0, "wall_s": 0.2, "exception": None}

    monkeypatch.setattr(jobs, "run_trial", run_trial)
    assert len(jobs.run_many(root, "noop", "", tmp_path / "job", seeds="0-3", concurrency=4)) == 4
    assert peak[0] == 1


def test_watchdog_limits_scale_with_the_control_period():
    """R7: the loop watchdog's limits are 0.5 s and 2 s, or 3 and 10 control periods on a slow rig, whichever is
    longer: every shipped profile keeps 0.5 s and 2 s, and a 2 Hz rig is not stopped by its own period."""
    import dataclasses

    from robouse.real.drivers.rosbridge import ros_profile
    from robouse.real.robots import METAL, PROFILES
    from robouse.real.safety import Guard, SafetyStop

    for p in [*PROFILES.values(), ros_profile({})]:
        g = Guard(p)
        assert (g.stall_s, g.hard_s) == (0.5, 2.0), p.name
    slow = dataclasses.replace(METAL, control_hz=2.0)
    g = Guard(slow)
    assert (g.stall_s, g.hard_s) == (1.5, 5.0)
    for _ in range(10):
        g.check_loop(0.55)  # a 2 Hz step with some jitter
    assert g.stalls == 0
    g.check_loop(1.6)
    g.check_loop(1.6)
    with pytest.raises(SafetyStop, match="3 control steps in a row slower than 1.5 s"):
        g.check_loop(1.6)
    with pytest.raises(SafetyStop, match=r"limit 5 s"):
        Guard(slow).check_loop(5.1)


def test_a_stop_keeps_the_grasp(tmp_path):
    """R8: a stop never lets go of a grasped object. The gripper keeps its command on every stop path, and an arm
    holding something is neither parked nor released: parking would carry the object, releasing torque would drop it."""
    from robouse.real import safety

    ep = _episode("real-metal-reach", tmp_path)
    b, robot = ep.backend, ep.backend.driver.robot
    send = robot.send_action

    def blocked(action):  # an object between the jaws: they stop at 20 however far the command closes them
        out = send(action)
        robot.q[6] = max(robot.q[6], 20.0)
        return out

    robot.send_action = blocked
    pose = list(b.q)
    assert ep.handle({"op": "act", "action": pose[:6] + [40.0], "repeat": 6})["ok"]  # open
    assert ep.handle({"op": "act", "action": pose[:6] + [4.0], "repeat": 10})["ok"]  # close on the object
    grip = float(b.guard.last_cmd[6])
    assert b.q[6] >= 20.0 and grip < b.q[6] - 1.0  # the command leads the blocked jaws, up to the gripper wind-up
    k = len(robot.sent)
    safety.set_estop("grasp test")
    assert not ep.handle({"op": "act", "action": pose[:6] + [4.0]})["ok"]
    safety.clear_estop()
    ep.close()
    assert len(robot.sent) > k and all(c[6] == pytest.approx(grip, abs=1e-3) for c in robot.sent[k:])
    ev = _events(tmp_path / "ep")
    holds = [e for e in ev if e["event"] == "holding"]
    assert len(holds) == 2 and holds[1]["reason"].startswith("the gripper holds something")
    assert next(e for e in ev if e.get("gate") == "hold_ack")["answer"] == "yes"  # not offered a park: acknowledged
    assert not any(e["event"] in ("park", "torque_released") or e.get("gate") == "park" for e in ev)
    assert next(e for e in ev if e["event"] == "close")["release_torque"] is False


# ---- re-review, 2026-10-02 (N1-N6): nothing moves on its own after a stop or a refusal ------------------------------------


def _inject_park_contact(b, every: int = 5) -> dict:
    """Something on the way to the rest pose: a contact on every `every`-th parking step (of every attempt)."""
    from robouse.real.safety import SafetyStop

    orig, n = b._park_step, {"steps": 0}

    def park_step(target):
        n["steps"] += 1
        if n["steps"] % every == 0:
            raise SafetyStop("contact while parking: (test) something on the way to the rest pose", "contact")
        return orig(target)

    b._park_step = park_step
    return n


def test_refused_start_gate_moves_nothing(tmp_path, monkeypatch):
    """N1: the operator answers no to "Ready to start?" after the arm is armed. The episode stops before anything moves:
    after the driver's hold on arming, every command is the pose the arm was measured at; nothing parks, nothing is
    released, nothing more is asked."""
    monkeypatch.setenv("ROBOUSE_OPERATOR_SCRIPT", "reset=no")
    ep = _episode("real-metal-reach", tmp_path, attended=True)
    robot = ep.backend.driver.robot
    assert ep.backend.halted and ep.backend.stop_kind == "operator_gate"
    ep.close()
    ev = _events(tmp_path / "ep")
    measured = next(e for e in ev if e["event"] == "connect")["pose"]
    sent = np.asarray(robot.sent, dtype=float)
    assert len(sent) <= 3 and np.allclose(sent[1:, :6], measured[:6], atol=6e-3)  # holding where it was measured
    assert not any(e["event"] in ("park", "torque_released") or e.get("gate") in ("park", "hold_ack") for e in ev)
    assert next(e for e in ev if e["event"] == "close")["release_torque"] is False


def test_after_a_stop_nothing_moves_unless_the_operator_approves(tmp_path, monkeypatch):
    """N1: after a safety stop the arm holds; at close the operator is asked whether to park it, and on a no it keeps
    holding: there is no park at all."""
    from robouse.real import safety

    monkeypatch.setenv("ROBOUSE_OPERATOR_SCRIPT", "park=no")
    ep = _episode("real-metal-reach", tmp_path)
    robot = ep.backend.driver.robot
    assert ep.handle({"op": "act", "action": list(ep.backend.q)})["ok"]
    safety.set_estop("approval test")
    assert not ep.handle({"op": "act", "action": list(ep.backend.q)})["ok"]
    safety.clear_estop()  # parking would be possible now: only the operator's no keeps the arm where it is
    held = np.asarray(robot.sent[-1], dtype=float)
    ep.close()
    ev = _events(tmp_path / "ep")
    assert next(e for e in ev if e.get("gate") == "park")["answer"] == "no"
    assert not any(e["event"] in ("park", "torque_released") for e in ev)
    assert [e for e in ev if e["event"] == "holding"][-1]["reason"] == "the operator did not approve parking"
    assert np.allclose(robot.sent[-1], held, atol=1e-3)


@pytest.mark.parametrize("ending", ["after a stop", "after a normal end"])
def test_a_park_that_hits_something_is_not_retried(tmp_path, monkeypatch, ending):
    """N2: something is on the way to the rest pose. The park stops at the contact, the arm holds where it stopped, the
    stop is recorded, and no park is tried again on its own: after a stop, the one park is the one the operator
    approved; after a normal end, the one park is the end's (the operator then declines another)."""
    from robouse.real import safety

    monkeypatch.setenv("ROBOUSE_OPERATOR_SCRIPT", "park=yes" if ending == "after a stop" else "park=no")
    ep = _episode("real-metal-reach", tmp_path)
    _inject_park_contact(ep.backend)
    assert ep.handle({"op": "act", "action": list(ep.backend.q)})["ok"]
    if ending == "after a stop":
        safety.set_estop("park test")
        assert not ep.handle({"op": "act", "action": list(ep.backend.q)})["ok"]
        safety.clear_estop()
    else:
        ep.handle({"op": "done", "text": ""})
    ep.close()
    ev = _events(tmp_path / "ep")
    assert len([e for e in ev if e["event"] == "park"]) == 1
    stops = [e for e in ev if e["event"] == "stop" and "parking" in e.get("reason", "") and "stopped" in e["reason"]]
    assert len(stops) == 1 and stops[0]["cause"] == "contact"
    held = [e for e in ev if e["event"] == "holding" and "parking stopped: contact while parking" in e["reason"]]
    assert len(held) == 1 and held[0]["reason"].endswith("it holds where it stopped")
    assert not any(e["event"] == "torque_released" for e in ev)


def test_a_park_stopped_after_a_normal_end_holds_the_batch(tmp_path, monkeypatch):
    """N3: the episode ends `done`, and on the way to the rest pose the arm meets something. result.json, rewritten when
    the server closes, records the stop after the end and how the arm was left, and run-many holds the batch for it."""
    from robouse.real import batch

    monkeypatch.setenv("ROBOUSE_OPERATOR_SCRIPT", "park=no")
    ep = _episode("real-metal-reach", tmp_path)
    _inject_park_contact(ep.backend)
    assert ep.handle({"op": "act", "action": list(ep.backend.q)})["ok"]
    ep.handle({"op": "done", "text": ""})
    assert ep.result["session"]["stop_after_end"] is None  # nothing has happened yet when the result is first written
    ep.close()
    res = json.loads((tmp_path / "ep" / "result.json").read_text())
    after = res["session"]["stop_after_end"]
    assert res["outcome"] == "done" and after["kind"] == "contact"
    assert "parking after the end stopped" in after["reason"]
    assert res["session"]["secured"].startswith("holding at the present position")
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps({"task_name": "real-metal-reach", "episode": res}))
    stop = batch.stop_of(trial)
    assert stop is not None and stop["kind"] == "contact" and "parking after the end stopped" in stop["reason"]


def test_a_simulated_batch_runs_on_after_an_error_as_before(tmp_path, monkeypatch):
    """N4: the fail-closed batch handling is for batches with a real-robot task. A simulated batch whose first trial
    raises still runs the trials already queued and then raises, as before (a real batch stops at once:
    test_batch_fails_closed)."""
    import shutil

    from robouse.runner import jobs

    calls: list = []

    def run_trial(t, harness, model, job_dir, **kw):
        calls.append(kw.get("seed"))
        if len(calls) == 1:
            raise OSError(28, "No space left on device")
        name = f"{t.id}__{harness}__{kw.get('seed')}"
        (job_dir / name).mkdir(parents=True, exist_ok=True)
        return {"trial": name, "reward": 1.0, "outcome": "done", "steps": 1, "wall_s": 0.1, "exception": None}

    monkeypatch.setattr(jobs, "run_trial", run_trial)
    root = tmp_path / "tasks"
    shutil.copytree(ROOT / "tasks" / "cubepick" / "cubepick-reach-layout-0", root / "cubepick-reach-layout-0")
    with pytest.raises(OSError, match="No space left on device"):
        jobs.run_many(root, "noop", "", tmp_path / "job", seeds="0-3")
    assert sorted(calls) == [0, 1, 2, 3]  # every trial started
    assert not (tmp_path / "job" / "halt.json").exists()


def test_the_arm_is_watched_while_the_operator_gives_the_verdict(tmp_path):
    """N5: the operator takes their time over the verdict, and the e-stop is latched meanwhile. The checks keep running
    while the question is open, so the episode ends as a safety stop, not `done`, whatever the operator answers."""
    from robouse.real import operator, safety

    finished = threading.Event()

    def operator_terminal():  # answers every question yes; over the verdict, takes 1.5 s with the e-stop latched
        seen: set = set()
        while not finished.is_set():
            try:
                req = json.loads((operator.OPERATOR_DIR / "pending.json").read_text())
            except (OSError, ValueError):
                req = None
            if req and req["id"] not in seen:
                seen.add(req["id"])
                if req["key"] == "verdict":
                    safety.set_estop("verdict test")
                    time.sleep(1.5)
                operator.answer("yes" if req["key"] != "park" else "no", "test operator")
            time.sleep(0.02)

    th = threading.Thread(target=operator_terminal, daemon=True)
    th.start()
    try:
        ep = _episode("real-metal-bead-to-bowl", tmp_path, operator="file", operator_timeout_s=20)
        assert ep.backend.verdict_mode == "operator" and not ep.backend.halted
        ep.handle({"op": "done", "text": ""})
        assert ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "estop" and not ep.result["success"]
        assert next(e for e in _events(tmp_path / "ep") if e["event"] == "operator_verdict")["verdict"] == "yes"
        ep.close()
    finally:
        finished.set()
        safety.clear_estop()


@pytest.mark.parametrize("alarm", ["temperature", "link"])
def test_a_held_arm_is_watched_after_a_stop(tmp_path, alarm):
    """After a stop, until the operator has answered, the thermal guard and the telemetry check keep running on the
    held arm: crossing the stop temperature, or the link going quiet, is reported loudly (a WARNING to the operator and
    the session log), once, and nothing is sent: the arm keeps holding."""
    from robouse.real import safety

    real = {"envelope": {"telemetry_timeout_s": 0.3}, "mock_fault": {"kind": "stale", "at_step": 3}}
    ep = _episode("real-metal-reach", tmp_path, **(real if alarm == "link" else {}))
    b, robot = ep.backend, ep.backend.driver.robot
    assert ep.handle({"op": "act", "action": list(b.q)})["ok"]
    safety.set_estop("hold test")
    assert not ep.handle({"op": "act", "action": list(b.q)})["ok"]
    safety.clear_estop()
    k = len(robot.sent)
    if alarm == "temperature":
        robot.fx.telemetry = lambda step, **kw: {"temp_mos_c": [30.0] * 7, "temp_rotor_c": [30.0] * 6 + [70.0]}
    else:
        time.sleep(0.4)  # the bus answers nothing more
    for _ in range(3):  # three seconds of watching
        b._last_check -= b.IDLE_CHECK_S
        ep.idle()
    ev = _events(tmp_path / "ep")
    assert [e["alarm"] for e in ev if e["event"] == "hold_alarm"] == [alarm]
    assert any(e["event"] == "operator_notice" and e["text"].startswith("WARNING") for e in ev)
    assert len(robot.sent) == k  # watching sends nothing
    ep.close()


def test_piper_first_hold_waits_for_every_joint_pair():
    """N6: joints 5-6's first frame arrives late, right after a reading's joints were copied out. connect() reads only
    after every pair has arrived, so its hold carries their real values, not the zeros the SDK holds until then."""
    from robouse.real.drivers.piper import PiperDriver
    from robouse.real.replay import Fixture, ReplayPiperSDK, _Obj
    from robouse.real.robots import PIPER

    class LateSDK(ReplayPiperSDK):
        reads = 0

        def _receive(self):
            self.reads += 1
            if self.reads == 1:  # the first frames lack joints 5-6 ...
                self.fault = {"kind": "silent_pair", "pair": "56", "at_step": 0}
                super()._receive()
                self.fault = {}
                return
            super()._receive()

        def GetArmGripperMsgs(self):  # ... whose first frame lands during this read, after the joints were copied
            if self.reads == 1 and not getattr(self, "late", False):
                self.late = True
                joints = {f"joint_{i + 1}": int(round(v * 1000)) for i, v in enumerate(self.robot.q[:6])}
                frame = _Obj(
                    type_=_Obj(name="PiperMsgJointFeedBack_56"),
                    time_stamp=time.time(),
                    arm_joint_feedback=_Obj(**joints),
                )
                self._C_PiperInterface_V2__UpdateArmJointState(frame)
            return super().GetArmGripperMsgs()

    sdk = LateSDK(Fixture("piper-synthetic"), PIPER)
    sdk.robot.q[4], sdk.robot.q[5] = 30.0, 20.0
    sent: list = []
    drv = PiperDriver(PIPER, {}, sdk_factory=lambda cfg: sdk, mock=True)
    send = drv.send
    drv.send = lambda q: (sent.append([round(float(x), 2) for x in q]), send(q))[1]
    drv.connect()
    assert sent[0][4:6] == [30.0, 20.0]


# ---- parks: watched by tracking lag, with torque as the backstop ------------------------------------------------------


def _park_replay(steps, settings=None, until: float = 1e9):
    """Recorded steps watched as one park (contact.ParkWatch with the Metal's settings): the first stop, or None."""
    from robouse.real.contact import ParkWatch
    from robouse.real.robots import METAL
    from robouse.real.safety import Envelope

    env = Envelope(METAL)
    w = ParkWatch(METAL, settings or METAL.contact, tool=env.chain.tool, table_z=env.e.table_z)
    for s in steps:
        if s["t"] > until:
            return None
        if (c := w.update(s["cmd"], s["pos"], {"joint_torque_nm": s.get("joint_torque_nm")})) is not None:
            return s["t"], c
    return None


def _through_the_guard(tmp_path, monkeypatch, fixture: str, until: float) -> list[dict]:
    """A recorded session sent through the safety layer up to `until` (playback mock: each step reads the recorded
    joints and torques, whatever is commanded). Per control step: the recorded time, the command the guard sent and
    the joints and torques read after it, as a park watch would see them."""
    ep, fx = _playback(tmp_path, monkeypatch, fixture)
    b, robot = ep.backend, ep.backend.driver.robot
    seen: list[dict] = []
    watch = b._watch_contact

    def tap(cmd):
        rec = {"t": fx.steps[robot.k]["t"], "cmd": list(cmd), "pos": list(b.q)}
        seen.append({**rec, "joint_torque_nm": b.extra.get("joint_torque_nm")})
        return watch(cmd)

    b._watch_contact = tap
    _replay(ep, fx, until=until)
    ep.close()
    return seen


@pytest.mark.parametrize(
    "fixture, window", [("metal-hanoi-131602", (91.7, 94.2)), ("metal-touchdown-121740", (41.9, 47.2))]
)
def test_the_park_watch_catches_the_verified_contacts(tmp_path, monkeypatch, fixture, window):
    """Each verified contact of the 2026-09-05 recordings, its session sent through the safety layer (the commands
    robouse sends, the recorded joints and torques) and watched as one park: the park watch stops inside the contact's
    window and not before. 12:17: the stall check catches the table touchdown, also without the torque watch. 13:16:
    only the torque backstop (4x) catches the elbow stop. The lag watch does not: robouse caps the elbow at 174 (that
    day's harness sent it to 180, and it stopped at 176.37), so its lag against the recorded joints peaks at 2.36 deg,
    under the 3.3 limit. An arm following the capped command would not reach that stop at all; what the lag watch
    catches is a joint held back (test_a_held_back_joint_stops_the_park_by_lag)."""
    import dataclasses

    from robouse.real.robots import METAL

    seen = _through_the_guard(tmp_path, monkeypatch, fixture, until=window[1])
    t, c = _park_replay(seen)
    assert window[0] <= t <= window[1]
    no_torque = _park_replay(seen, dataclasses.replace(METAL.contact, dtorque={}))  # lag and the stall check
    if fixture == "metal-touchdown-121740":
        assert no_torque is not None and window[0] <= no_torque[0] <= window[1] and no_torque[1].kind == "stall"
    else:
        assert c.kind in ("moving", "settled", "holding") and "elbow_flex" in c.change  # a torque rule, at 4x
        assert no_torque is None
        assert max(s["cmd"][2] for s in seen) == pytest.approx(174.0)
        lag = max(abs(s["cmd"][2] - s["pos"][2]) for s in seen if s["t"] >= window[0])
        assert lag == pytest.approx(2.36, abs=0.02)


def test_the_park_watch_is_quiet_on_recorded_motion():
    """The packaged 12:18:53 recording (up to the first contact the Sep 5 watch flagged), cut into park-length stretches
    and each watched as a park (the recorded targets as commands, with the recorded joints and torques): no stop. The
    Metal's park settings are the calibrated ones."""
    from robouse.real.replay import Fixture
    from robouse.real.robots import METAL

    s = METAL.contact
    assert (s.park_lag_deg, s.park_speed_deg_s, s.park_torque_factor) == (3.3, 6.0, 4.0)
    steps = [s for s in Fixture("metal-bowl-121853").steps if s["t"] < 56.0]
    stretches = [steps[i : i + 250] for i in range(0, len(steps), 250)]
    assert len(stretches) >= 2 and all(_park_replay(st) is None for st in stretches)


def test_a_held_back_joint_stops_the_park_by_lag(tmp_path, monkeypatch):
    """At a normal end the arm parks; something holds the shoulder back on the way. Its lag climbs past the limit, the
    park stops within a few steps of the block and the arm holds there; the stop after the end is recorded."""
    monkeypatch.setenv("ROBOUSE_OPERATOR_SCRIPT", "park=no")
    ep = _episode("real-metal-reach", tmp_path)
    robot = ep.backend.driver.robot
    block = float(robot.q[1]) + 5.0  # the park lifts the shoulder; 5 deg on, it is held back
    send = robot.send_action

    def held_back(action):
        out = send(action)
        robot.q[1] = min(robot.q[1], block)
        return out

    robot.send_action = held_back
    ep.handle({"op": "done", "text": ""})
    ep.close()
    ev = _events(tmp_path / "ep")
    contact = next(e for e in ev if e["event"] == "contact")
    assert contact["kind"] == "lag" and contact["action"] == "parking stopped"
    assert 3.3 < contact["change"]["shoulder_lift"] <= 4.5
    assert ep.result["session"]["stop_after_end"]["kind"] == "contact"
    park = [s for s in _steps(tmp_path / "ep") if s.get("label") == "park"]
    reached = next(i for i, s in enumerate(park) if s["pos"][1] >= block - 0.01)
    assert len(park) - reached <= 8  # stopped within 8 steps of being held back
    assert not any(e["event"] == "torque_released" for e in ev)


def test_parks_keep_to_the_calibrated_speed(tmp_path):
    """A rig that raises the slow joint speed does not speed up parks past the 6 deg/s the lag limit was calibrated at."""
    ep = _episode("real-metal-reach", tmp_path, envelope={"slow_joint_speed_deg_s": 12.0})
    ep.handle({"op": "done", "text": ""})
    ep.close()
    ev = _events(tmp_path / "ep")
    park = next(e for e in ev if e["event"] == "park")
    assert park["speed_deg_s"] == 6.0 and park["lag_limit_deg"] == 3.3
    cmds = np.asarray([s["cmd"][:6] for s in _steps(tmp_path / "ep") if s.get("label") == "park"])
    assert len(cmds) > 10 and np.abs(np.diff(cmds, axis=0)).max() <= 0.6 + 2e-3
    assert any(e["event"] == "torque_released" for e in ev)


# ---- final check, 2026-10-02 (P1-P4): rest poses, parks without a calibrated watch, normal ends that cannot park ------


def test_every_rest_pose_passes_its_own_workspace_check():
    """P3: every robot profile's rest pose, and the ROS task rig's, is inside its joint limits and its workspace, and
    the way to it from the home pose passes the workspace check, so a park is never refused for the rest pose itself.
    (The SO-101's rest pose put its fingertips 5 mm below the table, 9 mm outside its workspace.)"""
    from robouse.backends.real.backend import real_config
    from robouse.real.drivers.rosbridge import ros_profile
    from robouse.real.robots import PROFILES
    from robouse.real.safety import Envelope
    from robouse.tasks import load_task

    rig = ros_profile(real_config(load_task(ROOT / "tasks" / "real" / "real-ros-joint-pose").spec))
    for p in [*PROFILES.values(), rig]:
        env = Envelope(p)
        assert p.park and all(lo <= v <= hi for lo, v, hi in zip(p.low, p.park, p.high, strict=True)), p.name
        assert not any(v > 0 for v in env.violation(p.park).values()), (p.name, env.describe(p.park))
        env.check_path(p.home, p.park)  # raises Veto when the way leaves the workspace
