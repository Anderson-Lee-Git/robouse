"""The `dream` harness: the client's helpers (embodiment check, observation keys, chunk checks) and the builder's
credentials. Dream's client library and DreamAPI are not needed; the live loop is checked by running the yam suite."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from robouse.harnesses import dream as D

spec = importlib.util.spec_from_file_location("dream_client", Path(D.__file__).with_name("client.py"))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

YAM_INFO = {
    "backend": "yam",
    "action": {"names": [f"{s}_{j}" for s in ("right", "left") for j in [*(f"j{i}" for i in range(1, 7)), "grip"]]},
    "embodiment": {
        "name": "dual-yam",
        "action_groups": [
            {"name": "right_arm.joints", "components": list("abcdef")},
            {"name": "right_gripper", "components": ["g"]},
            {"name": "left_arm.joints", "components": list("abcdef")},
            {"name": "left_gripper", "components": ["g"]},
        ],
        "sensors": {"cameras": [{"name": "top"}, {"name": "left"}, {"name": "right"}]},
    },
}
STATE = {
    "right_joint_pos": [0.1] * 6,
    "right_gripper_open": 1.0,
    "left_joint_pos": [0.2] * 6,
    "left_gripper_open": 0.5,
}


def test_only_a_dual_yam_with_three_cameras_is_driven() -> None:
    assert C.check_embodiment(YAM_INFO) is None
    panda = {"backend": "menagerie", "action": {"names": ["dx", "dy", "dz", "grip"]}, "embodiment": {"name": "panda"}}
    assert "bimanual YAM" in C.check_embodiment(panda)
    no_wrist = json.loads(json.dumps(YAM_INFO))
    no_wrist["embodiment"]["sensors"]["cameras"] = [{"name": "top"}]
    assert "['left', 'right']" in C.check_embodiment(no_wrist)


def test_observation_keys_station_and_model() -> None:
    st = C.observation(STATE, "put apple into the bowl", station=True)
    assert st["state.arm_r.joint_pos"] == [0.1] * 6 and st["state.arm_l.gripper_pos"] == [0.5]
    assert st["robot.arm"] == "yam" and st["prompt"] == "put apple into the bowl"
    own = C.observation(STATE, "x", station=False)
    assert own["state.right_arm"] == [0.1] * 6 and own["state.left_gripper"] == [0.5] and "robot.arm" not in own
    assert C.frame_key("top", True) == "image_window.top" and C.frame_key("left", False) == "video.wrist_l"


def test_policy_config_never_records_and_checks_own_keys_only() -> None:
    cfg = C.policy_config("dreamlabs/dream-1-beta", station=True)
    assert cfg["_record"] is False and cfg["strict"] is False and "embodiment" not in cfg
    assert C.policy_config("m", station=False)["embodiment"] == C.YAM_EMBODIMENT


def test_rows_map_clip_and_refuse_malformed_chunks() -> None:
    low, high = np.full(14, -1.0), np.full(14, 1.0)
    low[[6, 13]], high[[6, 13]] = 0.0, 1.0
    right, left = np.zeros((48, 7)), np.zeros((48, 7))
    right[:, 0], left[:, 0], left[:, 6] = 2.0, -0.5, 0.7
    acts, clipped = C.rows({"q_r_chunk": right.tolist(), "q_l_chunk": left.tolist()}, low, high, limit=24)
    assert acts.shape == (24, 14) and clipped == 24  # right joint 1 clipped to its limit in every row
    assert acts[0, 0] == 1.0 and acts[0, 7] == -0.5 and acts[0, 13] == 0.7
    with pytest.raises(ValueError, match="shape"):
        C.rows({"q_r_chunk": right[:, :6].tolist(), "q_l_chunk": left.tolist()}, low, high, 48)
    bad = right.copy()
    bad[3, 6] = 2.0
    with pytest.raises(ValueError, match="gripper"):
        C.rows({"q_r_chunk": bad.tolist(), "q_l_chunk": left.tolist()}, low, high, 48)
    bad[3, 6], bad[5, 2] = 0.5, np.nan
    with pytest.raises(ValueError, match="non-finite"):
        C.rows({"q_r_chunk": bad.tolist(), "q_l_chunk": left.tolist()}, low, high, 48)


def test_needs_poses_reads_the_refusal() -> None:
    assert C.needs_poses(type("E", (Exception,), {"reason": "error"})("EEF checkpoint: send ik.arm or [state.*_eef_*]"))
    assert not C.needs_poses(type("E", (Exception,), {"reason": "rate_limited"})("_eef_"))


def test_credentials_environment_first_then_the_file(tmp_path, monkeypatch) -> None:
    f = tmp_path / "credentials"
    f.write_text('# Dream\nexport DREAM_GATEWAY_URL="https://gw.example"\nDREAM_API_KEY=dl_live_file\nOTHER=1\n')
    monkeypatch.setenv("DREAM_CREDENTIALS", str(f))
    for k in D.NAMES:
        monkeypatch.delenv(k, raising=False)
    assert D.credentials() == {"DREAM_GATEWAY_URL": "https://gw.example", "DREAM_API_KEY": "dl_live_file"}
    monkeypatch.setenv("DREAM_API_KEY", "dl_live_env")
    assert D.credentials()["DREAM_API_KEY"] == "dl_live_env"
    f.write_text("DREAM_GATEWAY_URL=https://gw.example\n")
    monkeypatch.delenv("DREAM_API_KEY")
    with pytest.raises(RuntimeError, match="no Dream Labs key"):
        D.credentials()


def test_build_passes_the_key_to_the_client_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DREAM_CREDENTIALS", str(tmp_path / "none"))
    monkeypatch.setenv("DREAM_API_KEY", "dl_live_test")
    (tmp_path / "ws" / ".robouse").mkdir(parents=True)
    task = SimpleNamespace(metadata={"language_instruction": "put apple into the bowl"}, meta={}, spec={})
    launch = D.build("", "", tmp_path / "ws", task, {})
    env = launch.env
    assert env["DREAM_API_KEY"] == "dl_live_test" and env["ROBOUSE_TASK_LANGUAGE"] == "put apple into the bowl"
    assert json.loads(env["ROBOUSE_DREAM_CONFIG"]) == {"model": "dreamlabs/dream-1-beta", "actions": 48}
    assert not Path(env["DREAM_CREDENTIALS"]).exists() and str(tmp_path / "ws") in env["DREAM_CREDENTIALS"]
    assert launch.cmd[1].endswith("dream_client.py") and Path(launch.cmd[1]).is_file()
    assert launch.notes["provider"] == "dreamlabs" and "dl_live" not in json.dumps(launch.notes)
