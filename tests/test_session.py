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


def test_inline_frames_come_in_the_reply_and_stay_out_of_the_trace(tmp_path) -> None:
    import base64
    import io

    from PIL import Image

    ep = episode(tmp_path)
    spec = {"cameras": ["front"], "format": "jpeg", "width": 32, "height": 16, "quality": 80}
    r = ep.handle({"op": "observe", "inline": spec})
    assert r["ok"] and r["result"]["format"] == "jpeg" and "hand_pos" in r["result"]["state"]
    img = Image.open(io.BytesIO(base64.b64decode(r["result"]["images"]["front"])))
    assert img.format == "JPEG" and img.size == (32, 16)
    png = ep.handle({"op": "observe", "inline": {"format": "png"}})["result"]["images"]["front"]
    assert Image.open(io.BytesIO(base64.b64decode(png))).format == "PNG"
    assert "task's cameras" in ep.handle({"op": "observe", "inline": {"cameras": ["side"]}})["error"]
    assert "format" in ep.handle({"op": "observe", "inline": {"format": "gif"}})["error"]
    assert "8 to" in ep.handle({"op": "observe", "inline": {"width": 4, "height": 4}})["error"]
    assert "quality" in ep.handle({"op": "observe", "inline": {"quality": 100}})["error"]
    assert "object" in ep.handle({"op": "observe", "inline": "jpeg"})["error"]
    assert not (tmp_path / "run" / "observations").exists()  # nothing written to disk
    ep.close()
    trace = (tmp_path / "run" / "trace.jsonl").read_text()
    assert "base64 characters" in trace and r["result"]["images"]["front"] not in trace


def test_a_locked_episode_serves_only_requests_with_its_token(tmp_path) -> None:
    """A harness that practises first (aspire) gets its scored episode locked: every request must carry the token,
    which only the runner and the harness's last phase hold. Before the unlock only the runner's status check and
    give-up are served; everything else is refused and counted, before the unlock and after it, and the count is in the
    signed verdict. A request's `runner` mark and the runner's give-up text authorize nothing."""
    from robouse.core.protocol import RUNNER_PREFIX, verify_result

    key = "u" * 32
    ep = S.Episode(
        {"id": "t", "backend": "fake", "goal": [0.0, 0.0, 0.0]},
        tmp_path / "run",
        secrets={"result_key": "k" * 64, "unlock_token": key},
    )
    refused = [
        {"op": "observe"},
        {"op": "act", "action": [1, 0, 0, 1]},
        {"op": "info", "aspire": "stage2"},
        {"op": "observe", "runner": True},  # anyone can mark a request as the runner's
        {"op": "act", "action": [1, 0, 0, 1], "runner": True},
        {"op": "status", "runner": True},
        {"op": "done", "text": f"{RUNNER_PREFIX} looks like the runner", "runner": True},
        {"op": "unlock", "unlock": "wrong"},
        {"op": "unlock", "unlock": "ü" * 32},  # not ASCII: still a counted refusal, not an error
        {"op": "unlock", "unlock": "\ud800"},  # does not even encode
        {"op": "unlock", "unlock": ["u"]},
        {"op": "observe", "unlock": key},  # the token, but not yet unlocked: only status and give-up
        {"op": "act", "action": [1, 0, 0, 1], "unlock": key},
    ]
    for req in refused:
        r = ep.handle(req)
        assert not r["ok"] and "locked" in r["error"], req
    assert ep.handle({"op": "status", "runner": True, "unlock": key})["ok"]  # the runner's status check
    assert ep.steps == 0 and not ep.finished and ep.lock == {"refused": len(refused), "unlocked_after_s": None}
    assert ep.handle({"op": "unlock", "unlock": key})["ok"]
    assert ep.handle({"op": "observe", "unlock": key})["ok"]
    assert ep.handle({"op": "act", "action": [1, 0, 0, 1], "unlock": key})["ok"] and ep.steps == 1
    # after the unlock, a request without the token (an agent process that outlived practice) is refused and counted
    for req in ({"op": "act", "action": [1, 0, 0, 1]}, {"op": "observe", "runner": True}, {"op": "done", "text": "x"}):
        assert not ep.handle(req)["ok"]
    assert ep.steps == 1 and not ep.finished
    ep.handle({"op": "done", "text": "x", "unlock": key})
    res = json.loads((tmp_path / "run" / "result.json").read_text())
    assert res["lock"]["refused"] == len(refused) + 3 and res["lock"]["unlocked_after_s"] is not None
    assert verify_result(res, "k" * 64)
    assert key not in (tmp_path / "run" / "trace.jsonl").read_text()  # the token never reaches the trace
    ep.close()
    # the runner closes a locked episode with its token; its give-up text alone does not
    locked = S.Episode({"id": "t", "backend": "fake"}, tmp_path / "run2", secrets={"unlock_token": key})
    assert not locked.handle({"op": "give_up", "text": f"{RUNNER_PREFIX} agent exited"})["ok"] and not locked.finished
    assert locked.handle({"op": "give_up", "text": f"{RUNNER_PREFIX} agent exited", "unlock": key})["ok"]
    assert locked.finished and locked.lock == {"refused": 1, "unlocked_after_s": None}
    locked.close()
    assert episode(tmp_path / "x").lock is None  # no unlock token: an ordinary, unlocked episode


def test_a_locked_episode_does_not_shut_down_without_its_token(tmp_path, sock_dir) -> None:
    """`serve` handles `shutdown` before the lock, so a locked scored episode must still refuse and count a `shutdown`
    that does not carry its token (an agent process that outlived its phase could otherwise end the scored episode
    uncounted); a `shutdown` that carries the token stops it, as the runner's does."""
    from robouse.agent_cli import _send

    key = "u" * 32
    sock = str(sock_dir / "s.sock")
    ready = tmp_path / "ready"
    out: dict = {}
    th = threading.Thread(
        target=lambda: out.update(
            S.serve(
                {"id": "t", "backend": "fake", "linger_s": 0},
                tmp_path / "run",
                sock,
                ready_file=ready,
                secrets={"result_key": "k" * 64, "unlock_token": key},
            )
        )
    )
    th.start()
    for _ in range(200):
        if ready.exists():
            break
        time.sleep(0.02)
    assert not _send({"op": "shutdown"}, path=sock)["ok"]  # no token: refused, not served
    assert not _send({"op": "shutdown", "unlock": "wrong"}, path=sock)["ok"]
    assert _send({"op": "status", "unlock": key}, path=sock)["ok"]  # the server is still running
    assert th.is_alive()
    assert _send({"op": "shutdown", "unlock": key}, path=sock)["ok"]  # the token stops it
    th.join(timeout=20)
    assert not th.is_alive()
    res = json.loads((tmp_path / "run" / "result.json").read_text())
    assert res["lock"]["refused"] == 2 and res["lock"]["unlocked_after_s"] is None  # the two tokenless shutdowns
