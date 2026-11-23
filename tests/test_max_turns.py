"""The agent turn cap (`--max-turns`, a task's agent.max_turns): passed to every harness explicitly, enforced by
Claude Code (also as the inner agent of program and aspire), recorded as not enforced for Codex, and never in the
agent's environment."""

from __future__ import annotations

import argparse

import pytest

from robouse import harnesses
from robouse.harnesses import Launch


@pytest.fixture
def claude_login(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-key")
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: None)


def _ws(tmp_path, name="ws"):
    ws = tmp_path / name
    (ws / ".robouse").mkdir(parents=True)
    return ws


def test_claude_code_gets_the_trial_s_turn_cap(tmp_path, claude_login):
    launch = harnesses.build(
        "claude-code",
        "claude-opus-5-5",
        "TASK",
        _ws(tmp_path),
        None,
        {"PATH": "/usr/bin", harnesses.MAX_TURNS_ENV: "37"},
    )
    assert harnesses._flag(launch.cmd, "--max-turns") == "37"
    assert launch.config["max_turns"] == 37 and launch.config["max_turns_enforced"] is True
    assert harnesses.MAX_TURNS_ENV not in launch.env
    # without one: Claude Code's harness default, nothing recorded
    launch = harnesses.build("claude-code", "claude-opus-5-5", "TASK", _ws(tmp_path, "b"), None, {"PATH": "/usr/bin"})
    assert harnesses._flag(launch.cmd, "--max-turns") == "400" and "max_turns" not in launch.config


def test_the_trial_s_cap_overrides_a_driver_s_own(tmp_path, claude_login):
    """program and aspire start Claude Code with their own caps (1000, 2000); the trial's cap wins."""
    from robouse.harnesses.program import agent_launch

    env = {"PATH": "/usr/bin", harnesses.MAX_TURNS_ENV: "400"}
    inner = agent_launch("claude-code", "claude-opus-5-5", "TASK", _ws(tmp_path), None, env)
    assert harnesses._flag(inner.cmd, "--max-turns") == "400"
    inner = agent_launch("claude-code", "claude-opus-5-5", "TASK", _ws(tmp_path, "b"), None, {"PATH": "/usr/bin"})
    assert harnesses._flag(inner.cmd, "--max-turns") == "1000"


def test_check_max_turns(monkeypatch, tmp_path):
    ok = Launch(["claude", "-p", "x", "--max-turns", "400"], {})
    harnesses.check_max_turns("claude-code", ok, 400)
    assert ok.config == {"max_turns": 400, "max_turns_enforced": True}
    with pytest.raises(RuntimeError, match="did not pass --max-turns 400"):
        harnesses.check_max_turns("x", Launch(["claude", "--max-turns", "1000"], {}), 400)
    codex = Launch(["codex", "exec", "x"], {})
    harnesses.check_max_turns("codex", codex, 400)
    assert codex.config == {"max_turns": 400, "max_turns_enforced": False}
    driver = Launch(["python", "driver.py"], {}, config={"agent": "claude-code", "agent_max_turns": 400})
    harnesses.check_max_turns("program", driver, 400)
    assert driver.config["max_turns_enforced"] is True
    driver = Launch(["python", "driver.py"], {}, config={"agent": "claude-code", "agent_max_turns": 1000})
    with pytest.raises(RuntimeError):
        harnesses.check_max_turns("program", driver, 400)
    driver = Launch(["python", "driver.py"], {}, config={"agent": "codex", "agent_max_turns": None})
    harnesses.check_max_turns("program-codex", driver, 400)
    assert driver.config["max_turns_enforced"] is False
    with pytest.raises(RuntimeError, match="cannot enforce"):
        harnesses.check_max_turns("vla", Launch(["python", "policy.py"], {}), 400)
    # a plugin harness that drops the cap is refused by build
    monkeypatch.setattr(harnesses, "plugin", lambda name: lambda *a: Launch(["claude", "--max-turns", "9"], {}))
    with pytest.raises(RuntimeError, match="did not pass --max-turns 400"):
        harnesses.build("other", "m", "TASK", tmp_path, None, {harnesses.MAX_TURNS_ENV: "400"})


def test_a_plugin_that_extends_claude_code_gets_the_cap(tmp_path, claude_login, monkeypatch):
    """A plugin (eval's claude-code-vision) builds claude-code itself with the environment it is given."""

    def vision(harness, model, prompt, workspace, task, env):
        return harnesses.build("claude-code", model, prompt, workspace, task, env)

    monkeypatch.setattr(harnesses, "plugin", lambda name: vision)
    launch = harnesses.build(
        "claude-code-vision", "claude-opus-5-5", "TASK", _ws(tmp_path), None, {harnesses.MAX_TURNS_ENV: "400"}
    )
    assert harnesses._flag(launch.cmd, "--max-turns") == "400" and launch.config["max_turns_enforced"] is True


def test_run_many_accepts_max_turns():
    from robouse.cli.run import _trial_opts

    for many in (True, False):
        p = argparse.ArgumentParser()
        _trial_opts(p, many=many)
        a = p.parse_args(["--harness", "claude-code", "--max-turns", "400"])
        assert a.max_turns == 400
        assert p.parse_args(["--harness", "claude-code"]).max_turns is None
        with pytest.raises(SystemExit):
            p.parse_args(["--harness", "claude-code", "--max-turns", "0"])
