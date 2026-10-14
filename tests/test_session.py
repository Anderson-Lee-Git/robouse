"""The episode server: request handling, budgets, judging, privileged state, recording and the socket protocol."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("imageio")

from fakes import FakeBackend

from robouse.core import session as S


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    monkeypatch.setattr(S, "make_backend", FakeBackend)
    monkeypatch.delenv("ROBOUSE_RECORD_SIZE", raising=False)


def episode(tmp_path: Path, **spec) -> S.Episode:
    return S.Episode({"id": "t", "backend": "fake", **spec}, tmp_path / "run")


def test_info_observe_and_action_checks(tmp_path) -> None:
    ep = episode(tmp_path)
    info = ep.handle({"op": "info"})["result"]
    assert info["action"]["names"] == ["dx", "dy", "dz", "grip"] and info["skills"] == ["move_to", "grip", "wiggle"]
    assert info["embodiment"]["action_groups"][0]["name"] == "arm.ee_delta"
    assert ep.handle({"op": "observe"})["result"]["state"]["hand_pos"] == [0.0, 0.0, 0.0]
    assert "4 numbers" in ep.handle({"op": "act", "action": [1, 2]})["error"]
    assert "finite" in ep.handle({"op": "act", "action": [float("nan"), 0, 0, 0]})["error"]
    assert "unknown op" in ep.handle({"op": "fly"})["error"]
    r = ep.handle({"op": "act", "action": [1, 0, 0, -1], "repeat": 3})["result"]
    assert r["executed_steps"] == 3 and r["steps_used"] == 3
    ep.close()


def test_done_settles_then_judges(tmp_path) -> None:
    ep = episode(tmp_path)
    ep.handle({"op": "act", "action": [1, 0, 0, -1], "repeat": 5})
    assert ep.handle({"op": "done", "text": "there"})["ok"]
    res = json.loads((tmp_path / "run" / "result.json").read_text())
    assert res["success"] and res["outcome"] == "done" and res["steps_used"] == 5 and "metrics" in res
    assert "finished" in ep.handle({"op": "act", "action": [0, 0, 0, 0]})["error"]
    ep.close()
    assert (tmp_path / "run" / "recording.mp4").stat().st_size > 0
    frames = (tmp_path / "run" / "frames.jsonl").read_text().splitlines()
    assert json.loads(frames[0])["step"] == 0 and len(frames) > 3


def test_give_up_scores_zero_even_at_the_goal(tmp_path) -> None:
    ep = episode(tmp_path)
    ep.handle({"op": "act", "action": [1, 0, 0, -1], "repeat": 5})
    ep.handle({"op": "give_up", "text": "no"})
    assert ep.result["success"] is False and ep.result["outcome"] == "gave_up"
    ep.close()


def test_budget_and_first_success_mode(tmp_path) -> None:
    ep = episode(tmp_path, max_steps=4)
    r = ep.handle({"op": "act", "action": [0, 1, 0, -1], "repeat": 10})["result"]
    assert r["executed_steps"] == 4 and r["episode"] == "finished: step budget exhausted"
    assert ep.result["outcome"] == "budget_exhausted" and not ep.result["success"]
    ep.close()
    ep = episode(tmp_path / "b", success_mode="first")
    r = ep.handle({"op": "act", "action": [1, 0, 0, -1], "repeat": 10})["result"]
    assert r["episode"].startswith("finished: goal reached") and ep.result["success"]
    ep.close()


def test_skills_move_to_grip_and_closed_loop(tmp_path) -> None:
    ep = episode(tmp_path)
    r = ep.handle({"op": "move_to", "pos": [0.05, 0, 0]})["result"]
    assert r["reached"] and r["distance"] < 0.011
    assert ep.handle({"op": "grip", "value": 1, "steps": 2})["result"]["executed_steps"] == 2
    r = ep.handle({"op": "skill", "name": "wiggle", "args": ["4"]})["result"]
    assert r["executed_steps"] == 4 and r["wiggled"] == 4
    assert "unknown skill" in ep.handle({"op": "skill", "name": "fly", "args": []})["error"]
    ep.close()
    ep = episode(tmp_path / "b", skills=False)
    assert "not available" in ep.handle({"op": "move_to", "pos": [0, 0, 0]})["error"]
    ep.close()


def test_privileged_state_needs_the_token_and_the_token_is_not_traced(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ROBOUSE_ORACLE_TOKEN", "tok")
    ep = episode(tmp_path, obs_mode="vision", visible_fields=["hand_pos"])
    assert ep.handle({"op": "observe"})["result"]["state"] == {"hand_pos": [0.0, 0.0, 0.0]}
    assert ep.handle({"op": "observe", "token": "tok"})["result"]["state"]["secret"] == 42
    assert ep.handle({"op": "observe", "token": "nope"})["result"]["state"].keys() == {"hand_pos"}
    ep.close()
    assert "tok" not in (tmp_path / "run" / "trace.jsonl").read_text()


def test_a_halted_robot_ends_the_episode_at_once(tmp_path) -> None:
    ep = episode(tmp_path)
    ep.backend.halted = "e-stop"
    ep.handle({"op": "observe"})
    assert ep.result["outcome"] == "safety_stop" and ep.result["agent_text"] == "e-stop"
    ep.close()


def test_a_judge_that_raises_scores_zero(tmp_path) -> None:
    ep = episode(tmp_path)

    def boom():
        raise RuntimeError("worker died")

    ep.backend.success = boom
    ep.handle({"op": "done"})
    assert ep.result["success"] is False and "worker died" in ep.result["judge_error"]
    ep.close()


def test_serve_over_the_socket(tmp_path, sock_dir, monkeypatch) -> None:
    from robouse.agent_cli import _send

    sock = str(sock_dir / "s.sock")
    ready = tmp_path / "ready"
    out: dict = {}
    th = threading.Thread(
        target=lambda: out.update(
            S.serve({"id": "t", "backend": "fake", "linger_s": 0}, tmp_path / "run", sock, ready_file=ready)
        )
    )
    th.start()
    for _ in range(200):
        if ready.exists():
            break
        time.sleep(0.02)
    monkeypatch.setenv("ROBOUSE_SOCKET", sock)
    monkeypatch.delenv("ROBOUSE_ORACLE_TOKEN", raising=False)
    assert _send({"op": "act", "action": [1, 0, 0, -1], "repeat": 5})["ok"]
    assert _send({"op": "done", "text": "ok"})["ok"]
    th.join(timeout=20)
    assert out["success"] and out["steps_used"] == 5
