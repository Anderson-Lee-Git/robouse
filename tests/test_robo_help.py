"""`robo` help: -h or --help anywhere in the arguments prints the help and sends nothing. Before this, `robo give-up
--help` sent {"op": "give_up", "text": "--help"} and ended the episode (deep audit, trial 933196)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from robouse import agent_cli, mcp_server

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.mark.parametrize(
    "argv",
    [
        ["give-up", "--help"],
        ["give_up", "-h"],
        ["done", "--help"],
        ["done", "-h"],
        ["done", "all", "set", "--help"],
        ["--json", "give-up", "--help"],
        ["act", "0", "0", "-1", "1", "--repeat", "5", "--help"],
        ["move-to", "0.1", "0", "0.2", "-h"],
        ["skill", "wiggle", "--help"],
        ["observe", "--image", "--help"],
        ["help"],
        ["-h"],
        ["--help"],
        [],
    ],
)
def test_a_help_flag_anywhere_prints_help_and_sends_nothing(argv, monkeypatch, capsys) -> None:
    sent: list = []
    monkeypatch.setattr(agent_cli, "_send", lambda req, path=None: sent.append(req) or {"ok": True, "result": {}})
    assert agent_cli.main(argv) == 0
    assert sent == []
    out = capsys.readouterr().out
    assert "robo give-up" in out and "-h or --help anywhere" in out


def test_messages_that_only_mention_help_are_still_sent(monkeypatch) -> None:
    sent: list = []
    monkeypatch.setattr(agent_cli, "_send", lambda req, path=None: sent.append(req) or {"ok": True, "result": {}})
    assert agent_cli.main(["give-up", "see --help for why"]) == 0
    assert agent_cli.main(["done", "help"]) == 0
    assert sent == [{"op": "give_up", "text": "see --help for why"}, {"op": "done", "text": "help"}]


def test_robo_mcp_help_anywhere_before_run_serves_nothing(capsys) -> None:
    assert mcp_server.main(["--http", "127.0.0.1:0", "--help"]) == 0  # would otherwise serve until killed
    assert "Transports" in capsys.readouterr().out


def test_give_up_help_leaves_a_live_episode_running(tmp_path, sock_dir, monkeypatch) -> None:
    """The installed command against a real episode server: the episode is still open after `robo give-up --help` and
    `robo done -h`, and ends only on a real give-up."""
    pytest.importorskip("imageio")
    from fakes import FakeBackend

    from robouse.core import session as S

    monkeypatch.setattr(S, "make_backend", FakeBackend)
    monkeypatch.delenv("ROBOUSE_ORACLE_TOKEN", raising=False)
    monkeypatch.delenv("ROBOUSE_SEND_VIA", raising=False)
    sock, ws, ready = str(sock_dir / "e.sock"), tmp_path / "ws", tmp_path / "ready"
    ws.mkdir()
    out: dict = {}
    th = threading.Thread(
        target=lambda: out.update(
            S.serve({"id": "t", "backend": "fake", "linger_s": 1}, tmp_path / "run", sock, ws, ready_file=ready)
        ),
        daemon=True,
    )
    th.start()
    for _ in range(500):
        if ready.exists():
            break
        time.sleep(0.01)
    env = {**os.environ, "PYTHONPATH": str(SRC), "ROBOUSE_SOCKET": sock}
    for argv in (["give-up", "--help"], ["done", "-h"], ["give-up", "--json", "--help"]):
        p = subprocess.run([sys.executable, "-m", "robouse.agent_cli", *argv], env=env, capture_output=True, text=True)
        assert p.returncode == 0 and "robo give-up" in p.stdout, (argv, p.stdout, p.stderr)
        status = agent_cli._send({"op": "status", "runner": True}, path=sock)
        assert status["ok"] and not status["result"]["finished"], argv
    assert agent_cli._send({"op": "give_up", "text": "test over"}, path=sock)["ok"]
    th.join(timeout=20)
    assert out.get("outcome") == "gave_up" and out.get("agent_text") == "test over"
