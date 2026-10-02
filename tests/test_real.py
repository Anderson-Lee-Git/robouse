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
    assert ep.backend.stamp is not None  # the SDK's message time dates each reading
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


def _replay(ep, fx, until: float | None = None) -> list[tuple[dict, dict]]:
    """Send the recorded commands as `robo act`, each matched to the recorded step the mock serves next (a hold the
    safety layer commands takes a step too); returns (recorded step, response) for every error or reported contact."""
    robot = ep.backend.driver.robot
    out = []
    while robot.k + 1 < len(fx.steps) and not ep.finished:
        s = fx.steps[robot.k + 1]
        if until is not None and s["t"] > until:
            break
        r = ep.handle({"op": "act", "action": s["cmd"]})
        if not r["ok"] or "contact" in r["result"]:
            out.append((s, r))
    return out


# ---- gap 1: the loop watchdog acts; lost telemetry stops -----------------------------------------------------------------


def test_watchdog_one_stall_is_logged_and_the_episode_goes_on(tmp_path):
    ep = _episode(
        "real-metal-reach",
        tmp_path,
        envelope={"watchdog_s": 0.15, "watchdog_hard_s": 2.0, "watchdog_max_stalls": 3},
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


def test_watchdog_hard_limit_stops_and_holds_the_last_command(tmp_path):
    ep = _episode(
        "real-metal-reach",
        tmp_path,
        envelope={"watchdog_s": 0.1, "watchdog_hard_s": 0.3},
        mock_fault={"kind": "slow", "at_step": 3, "steps": 1, "seconds": 0.45},
    )
    q = list(ep.backend.q)
    assert ep.handle({"op": "act", "action": q})["ok"]
    r = ep.handle({"op": "act", "action": q})
    assert not r["ok"] and "watchdog: a control step took" in r["error"]
    assert ep.finished and ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "watchdog"
    ep.close()
    ev = _events(tmp_path / "ep")
    steps = [json.loads(l) for l in (tmp_path / "ep" / "session" / "log.jsonl").read_text().splitlines()]
    assert any(e["event"] == "stop" and e.get("kind") == "watchdog" and e["dt"] > 0.3 for e in ev)
    stop = next(e for e in ev if e["event"] == "stop" and e.get("cause") == "watchdog")
    assert np.allclose(stop["hold"], steps[-1]["cmd"], atol=0.006)  # the hold is the last command
    assert ep.result["safety_events"]


def test_watchdog_stalls_in_a_row_stop(tmp_path):
    ep = _episode(
        "real-metal-reach",
        tmp_path,
        envelope={"watchdog_s": 0.1, "watchdog_hard_s": 5.0, "watchdog_max_stalls": 3},
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
    stop = next(e for e in ev if e["event"] == "stop" and e.get("cause") == "telemetry_lost")
    assert np.allclose(stop["hold"], steps[-1]["cmd"], atol=0.006)  # the last command ...
    assert not np.allclose(stop["hold"], steps[-1]["pos"], atol=0.5)  # ... not the stale reading
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
    """The watch on synthetic streams: Sep 5 thresholds in a watched move, unwatched_factor x them elsewhere, gripper
    motion ignored, and the stall (the touchdown criterion) on settled poses."""
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
    grasp = [(0, 4 + 10 * i, drop * (i % 2)) for i in range(1, 6)]  # the gripper closes; the arm torque twitches
    assert feed(ContactWatch(METAL, METAL.contact), hold + grasp + hold, watched=True) == []

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


def test_contact_watch_quiet_on_recorded_motion_then_stops_at_the_elbow_stop(tmp_path, monkeypatch):
    """Verified contact (2026-09-05 13:16, fixture metal-hanoi-131602 from the recorder's log): 91 s of normal motion
    replay without a contact; then the elbow straightens against its mechanical stop, away from the table: a contact
    outside a watched move stops the episode, and the hold at the measured pose leaves no push against the stop. The
    guard no longer commands the elbow past 174 deg (Sep 5 commanded 180)."""
    ep, fx = _playback(tmp_path, monkeypatch, "metal-hanoi-131602")
    hits = _replay(ep, fx)
    assert len(hits) == 1
    step, r = hits[0]
    assert step["label"] == "peg1_s_3" and 91.8 <= step["t"] <= 92.0
    assert not r["ok"] and "contact outside a watched move" in r["error"]
    assert ep.outcome == "safety_stop" and ep.result["session"]["stop_kind"] == "contact"
    ep.close()
    ev = _events(tmp_path / "ep")
    (contact,) = [e for e in ev if e["event"] == "contact"]
    assert contact["watched"] is False and contact["change"]["elbow_flex"] > 5.0
    stop = next(e for e in ev if e["event"] == "stop" and e.get("cause") == "contact")
    steps = [json.loads(l) for l in (tmp_path / "ep" / "session" / "log.jsonl").read_text().splitlines()]
    assert max(s["cmd"][2] for s in steps) <= 174.0  # the elbow command stays under the soft limit ...
    assert max(s["pos"][2] for s in steps) > 176.0  # ... while the recorded arm sat at its stop
    assert stop["hold"][2] == pytest.approx(176.36, abs=0.05)  # held where the elbow is


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


def test_contacts_in_watched_moves_then_one_too_many(tmp_path, monkeypatch):
    """The HIL fixture's own recording (12:18:53): the Sep 5 watch flagged two contacts on the way down to a bead (the
    second, on the final descent, very likely real: the grasp that followed needs the tips at table level). The first
    stops the move and is reported to the agent; the second is one too many."""
    ep, fx = _playback(tmp_path, monkeypatch, "metal-bowl-121853")
    hits = _replay(ep, fx)
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
