"""The Codex turn cap (harnesses/turncap.py), Claude Code's `--max-turns` for Codex: no real Codex runs.

A stand-in `codex` (FAKE_CODEX) reads the hooks.json in its CODEX_HOME and runs those hooks as Codex 0.167 does, with
the documented hook input on stdin: PreModelRequest before each model request attempt, PostModelRequest after it with
its `status`. Each completed request is one answer that runs one tool call. The tests show that request N+1 is never
sent, that the N-th answer's tool call runs, that retried attempts do not count, that the hooks print nothing, and that
a trial at the cap ends as a Claude Code trial at --max-turns does: "agent exited without robo done", no harness error,
result.json `turn_cap.reached`.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from robouse import _maintainer, harnesses
from robouse.harnesses import Launch, turncap

ROOT = Path(__file__).resolve().parents[1]
CUBEPICK = ROOT / "tasks" / "cubepick"

FAKE_CODEX = r'''
import json, os, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
plan = json.loads((HERE / "plan.json").read_text())
log = HERE / "log.jsonl"


def note(**k):
    with open(log, "a") as f:
        f.write(json.dumps(k) + "\n")


if sys.argv[1:] == ["--version"]:
    print(f"codex-cli {plan['version']}")
    sys.exit(0)
args = sys.argv[1:]
assert args[0] == "exec", args
note(argv=args, home=os.environ.get("CODEX_HOME"))
hooks = {}
home = Path(os.environ["CODEX_HOME"])
if (home / "hooks.json").exists() and "--dangerously-bypass-hook-trust" in args:  # untrusted hooks never run
    hooks = json.loads((home / "hooks.json").read_text()).get("hooks", {})


def run_hooks(event, extra):
    payload = {"session_id": "sess-1", "transcript_path": None, "cwd": os.getcwd(), "hook_event_name": event,
               "model": "gpt-test", "turn_id": "turn-1", **extra}
    for group in hooks.get(event, []):
        for h in group["hooks"]:
            r = subprocess.run(h["command"], shell=True, input=json.dumps(payload), capture_output=True, text=True,
                               timeout=h.get("timeout", 600))
            note(hook=event, stdout=r.stdout, stderr=r.stderr, rc=r.returncode)


def emit(ev):
    print(json.dumps(ev), flush=True)


emit({"type": "thread.started", "thread_id": "sess-1"})
emit({"type": "turn.started"})
for n in range(1, plan["requests"] + 1):
    fails = plan.get("fail", {}).get(str(n), 0)
    for attempt in range(fails + 1):
        run_hooks("PreModelRequest", {})
        note(sent=n, attempt=attempt)
        status = "failed" if attempt < fails else "completed"
        run_hooks("PostModelRequest", {"status": status, "error": None if status == "completed" else "HTTP 500",
                                       "token_usage": None})
    emit({"type": "item.completed", "item": {"id": f"r{n}", "type": "reasoning", "text": f"step {n}"}})
    cmd = plan.get("tools", {}).get(str(n), plan.get("tool", "true"))
    emit({"type": "item.started", "item": {"id": f"c{n}", "type": "command_execution", "command": cmd,
                                           "status": "in_progress"}})
    time.sleep(plan.get("tool_s", 0))
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    note(tool=n, rc=r.returncode)
    emit({"type": "item.completed", "item": {"id": f"c{n}", "type": "command_execution", "command": cmd,
                                             "aggregated_output": r.stdout, "exit_code": r.returncode,
                                             "status": "completed"}})
emit({"type": "item.completed", "item": {"id": "m-last", "type": "agent_message", "text": "finished"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})
'''


@pytest.fixture
def short() -> Iterator[Path]:
    """A short folder: the Codex home holds the turn cap's Unix socket (at most 104 bytes on macOS)."""
    with tempfile.TemporaryDirectory(prefix="tc-", dir="/tmp") as d:
        yield Path(d)


def _fake_codex(d: Path, version: str = "0.167.0", **plan) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    exe = d / "codex"
    exe.write_text(f"#!{sys.executable}\n" + FAKE_CODEX)
    exe.chmod(0o755)
    (d / "plan.json").write_text(json.dumps({"version": version, "requests": 50, **plan}))
    return d


def _log(d: Path) -> list[dict]:
    p = d / "log.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _run(cmd: list[str], env: dict, tc: turncap.CodexTurnCap, stream: Path, timeout: float = 60) -> int | None:
    """What the runner does (runner/trial.py _wait_agent): the agent in a session of its own, polled until it exits."""
    tc.stream = stream
    with open(stream, "w") as out:
        p = subprocess.Popen(cmd, env=env, stdout=out, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + timeout
        while True:
            try:
                return p.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                if tc.poll(p.pid) or time.time() > deadline:
                    os.killpg(p.pid, signal.SIGTERM)
                    return p.wait()


@pytest.mark.parametrize("cap", [1, 3])
def test_the_hooks_stop_codex_before_request_n_plus_1(short, cap) -> None:
    bin_dir = _fake_codex(short / "bin", fail={"2": 2})  # request 2 fails twice and is retried: one turn
    home = short / "home"
    home.mkdir()
    tc = turncap.plan(cap, str(home), str(bin_dir), pool=False)
    assert tc.method == "codex-hooks" and tc.version == "0.167.0"
    tc.start()
    try:
        hooks = json.loads((home / "hooks.json").read_text())["hooks"]
        assert set(hooks) == {"PreModelRequest", "PostModelRequest"}
        assert all(g[0]["hooks"][0]["timeout"] >= 24 * 3600 for g in hooks.values())
        env = {**os.environ, "CODEX_HOME": str(home)}
        cmd = [str(bin_dir / "codex"), "exec", "--json", turncap.BYPASS_TRUST, "PROMPT"]
        rc = _run(cmd, env, tc, short / "stdout.jsonl")
    finally:
        tc.close()
    log = _log(bin_dir)
    completed = [e["sent"] for e in log if "sent" in e]
    assert max(completed) == cap, log  # request cap+1 was never sent
    assert sorted({e["tool"] for e in log if "tool" in e}) == list(range(1, cap + 1))  # the cap-th answer's tools ran
    if cap >= 2:
        assert completed.count(2) == 3  # two failed attempts and the retry, one turn
    assert all(e["stdout"] == "" and e["stderr"] == "" for e in log if "hook" in e)  # nothing reaches the model
    assert rc is not None and rc < 0  # stopped by the runner
    rec = tc.record()
    assert rec["reached"] and rec["reached_by"] == "codex-hooks" and rec["model_requests_completed"] == cap
    assert rec["method"] == "codex-hooks" and not (home / turncap.SOCKET_NAME).exists()


def test_untrusted_hooks_do_not_run_and_the_stream_backs_them_up(short) -> None:
    """Without --dangerously-bypass-hook-trust Codex skips the hooks: the runner's stream count stops it anyway, and
    says the hooks never fired."""
    bin_dir = _fake_codex(short / "bin", tool_s=0.3)
    home = short / "home"
    home.mkdir()
    tc = turncap.plan(2, str(home), str(bin_dir), pool=False)
    tc.start()
    try:
        _run([str(bin_dir / "codex"), "exec", "--json", "P"], {**os.environ, "CODEX_HOME": str(home)}, tc, short / "o")
    finally:
        tc.close()
    rec = tc.record()
    assert rec["reached"] and rec["reached_by"] == "json-stream (hooks never fired)" and rec["hook_events"] == 0
    assert max(e["sent"] for e in _log(bin_dir) if "sent" in e) <= 4


def test_an_older_codex_falls_back_to_the_stream(short) -> None:
    bin_dir = _fake_codex(short / "bin", version="0.150.0", tool_s=0.3)
    home = short / "home"
    home.mkdir()
    tc = turncap.plan(3, str(home), str(bin_dir), pool=False)
    assert tc.method == "json-stream" and "0.150.0" in tc.why
    tc.start()
    assert not (home / "hooks.json").exists()
    _run([str(bin_dir / "codex"), "exec", "--json", "P"], {**os.environ, "CODEX_HOME": str(home)}, tc, short / "o")
    rec = tc.record()
    assert rec["reached"] and rec["reached_by"] == "json-stream" and rec["stream_answers"] == 4
    tools = {e["tool"] for e in _log(bin_dir) if "tool" in e}
    assert tools >= {1, 2, 3} and 5 not in tools
    # a pool home, or a home path too long for a socket, falls back as well
    assert turncap.plan(3, str(home), str(_fake_codex(short / "b2")), pool=True).method == "json-stream"
    assert turncap.plan(3, "/" + "x" * 120, str(short / "b2"), pool=False).method == "json-stream"


def test_stream_count() -> None:
    c = turncap.StreamCount()
    evs = [
        ("item.completed", "r1", "reasoning"),
        ("item.started", "c1", "command_execution"),
        ("item.started", "c2", "command_execution"),  # a parallel call of the same answer
        ("item.completed", "c1", "command_execution"),
        ("item.completed", "c2", "command_execution"),
        ("item.completed", "m2", "agent_message"),
        ("item.started", "c3", "command_execution"),
        ("item.completed", "c3", "command_execution"),
        ("item.started", "c4", "command_execution"),
    ]
    for et, iid, typ in evs:
        c.feed({"type": et, "item": {"id": iid, "type": typ}})
    assert c.answers == 3


# -- the harness and the runner ------------------------------------------------------------------------------------


@pytest.fixture
def codex_env(short, tmp_path, monkeypatch):
    """A Codex login in a stand-in home (never the user's), the per-trial homes in a short cache folder, and the fake
    codex first on PATH."""
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text("LOGIN")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(short / "c"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(_maintainer, "codex_accounts", lambda: [])
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: None)
    bin_dir = short / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return bin_dir


def test_the_codex_harness_carries_the_cap(tmp_path, codex_env) -> None:
    _fake_codex(codex_env)
    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    launch = harnesses.build(
        "codex", "gpt-6-astra", "TASK", ws, None, {"PATH": os.environ["PATH"], "_ROBOUSE_MAX_TURNS": "7"}
    )
    try:
        assert turncap.BYPASS_TRUST in launch.cmd and launch.turn_cap.cap == 7
        home = Path(launch.env["CODEX_HOME"])
        assert (home / "hooks.json") in launch.read_only
        assert launch.config["max_turns"] == 7 and launch.config["max_turns_enforced"] is True
        assert launch.config["max_turns_method"] == "codex-hooks" and launch.config["codex_version"] == "0.167.0"
        assert harnesses.MAX_TURNS_ENV not in launch.env
    finally:
        launch.stop()
    assert not home.exists()
    # without a cap: no hooks, no flag
    launch = harnesses.build("codex", "gpt-6-astra", "TASK", ws, None, {"PATH": os.environ["PATH"]})
    assert launch.turn_cap is None and turncap.BYPASS_TRUST not in launch.cmd
    assert not (Path(launch.env["CODEX_HOME"]) / "hooks.json").exists()
    launch.stop()
    # an older Codex: the stream count, recorded as not enforced
    _fake_codex(codex_env, version="0.160.0")
    launch = harnesses.build(
        "codex", "gpt-6-astra", "TASK", ws, None, {"PATH": os.environ["PATH"], "_ROBOUSE_MAX_TURNS": "7"}
    )
    assert launch.config["max_turns_method"] == "json-stream" and launch.config["max_turns_enforced"] is False
    assert "0.160.0" in launch.config["max_turns_fallback_reason"] and turncap.BYPASS_TRUST not in launch.cmd
    launch.stop()


def test_check_max_turns_for_codex(short) -> None:
    with pytest.raises(RuntimeError, match="did not give its Codex agent the turn cap 400"):
        harnesses.check_max_turns("codex", Launch(["codex", "exec", "x"], {}), 400)
    tc = turncap.CodexTurnCap(400, str(short), "codex-hooks")
    with pytest.raises(RuntimeError, match="hook-trust"):
        harnesses.check_max_turns("codex", Launch(["codex", "exec", "x"], {}, turn_cap=tc), 400)
    ok = Launch(["codex", "exec", turncap.BYPASS_TRUST, "x"], {}, turn_cap=tc)
    harnesses.check_max_turns("codex", ok, 400)
    assert ok.config["max_turns_enforced"] is True and ok.config["max_turns_method"] == "codex-hooks"
    with pytest.raises(RuntimeError, match="turn cap 300"):
        harnesses.check_max_turns("codex", ok, 300)
    driver = Launch(["python", "driver.py"], {}, config={"agent": "codex", "agent_max_turns": 400}, turn_cap=tc)
    harnesses.check_max_turns("program-codex", driver, 400)
    assert driver.config["max_turns_enforced"] is True
    stream = turncap.CodexTurnCap(400, str(short), "json-stream", why="old")
    driver = Launch(["python", "driver.py"], {}, config={"agent": "codex", "agent_max_turns": 400}, turn_cap=stream)
    harnesses.check_max_turns("aspire-codex", driver, 400)
    assert driver.config["max_turns_enforced"] is False and driver.config["max_turns_fallback_reason"] == "old"


def _trial(harness: str, task: str, job: Path, turns: int, monkeypatch, sandbox: bool = False) -> tuple[dict, Path]:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    if not sandbox:
        monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    res = run_trial(load_task(CUBEPICK / task), harness, "gpt-6-astra", job, timeout=600, max_turns=turns)
    return res, job / res["trial"]


def test_a_codex_trial_at_the_cap_ends_as_a_claude_code_trial_at_max_turns(tmp_path, codex_env, monkeypatch) -> None:
    _fake_codex(codex_env, tool="robo observe > /dev/null")
    res, tdir = _trial("codex", "cubepick-reach-layout-0", tmp_path / "job", 3, monkeypatch)
    assert res["exception"] is None, res
    assert res["outcome"] == "gave_up" and res["reward"] == 0.0
    ep = json.loads((tdir / "episode" / "result.json").read_text())
    assert ep["agent_text"].endswith("agent exited without robo done")
    out = json.loads((tdir / "result.json").read_text())
    assert out["turn_cap"]["reached"] and out["turn_cap"]["model_requests_completed"] == 3
    assert out["turn_cap"]["method"] == "codex-hooks" and out["agent_timed_out"] is False
    cfg = json.loads((tdir / "config.json").read_text())
    assert cfg["max_turns"] == 3 and cfg["harness_config"]["max_turns_enforced"] is True
    log = _log(codex_env)
    assert max(e["sent"] for e in log if "sent" in e) == 3 and {e["tool"] for e in log if "tool" in e} == {1, 2, 3}


def test_a_codex_trial_that_finishes_first_is_not_capped(tmp_path, codex_env, monkeypatch) -> None:
    _fake_codex(codex_env, requests=2, tools={"2": "robo done finished"})
    res, tdir = _trial("codex", "cubepick-reach-layout-0", tmp_path / "job", 5, monkeypatch)
    assert res["exception"] is None and res["outcome"] == "done", res
    out = json.loads((tdir / "result.json").read_text())
    assert out["turn_cap"]["reached"] is False and out["turn_cap"]["model_requests_completed"] == 2


def test_the_cap_holds_in_the_sandbox(tmp_path, codex_env, monkeypatch) -> None:
    """In the sandbox the hooks reach the runner's socket in the Codex home, and the agent cannot change hooks.json."""
    from robouse.runner import sandbox

    if sys.platform.startswith("linux") and not sandbox.bwrap_works():
        pytest.skip("no bubblewrap here")
    # the stand-in codex outside /tmp, which the sandbox replaces with a fresh one
    with tempfile.TemporaryDirectory(prefix=".tc-", dir=ROOT) as d:
        bin_dir = Path(d)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
        _fake_codex(bin_dir, tools={"1": 'echo x >> "$CODEX_HOME/hooks.json"'}, tool="robo observe > /dev/null")
        res, tdir = _trial("codex", "cubepick-reach-layout-1", tmp_path / "job", 2, monkeypatch, sandbox=True)
        cfg = json.loads((tdir / "config.json").read_text())
        if cfg["sandbox"] == "none":
            pytest.skip("no sandbox")
        assert res["exception"] is None, (res, (tdir / "agent" / "stderr.txt").read_text())
        out = json.loads((tdir / "result.json").read_text())
        assert out["turn_cap"]["reached"] and out["turn_cap"]["model_requests_completed"] == 2
        assert out["turn_cap"]["reached_by"] == "codex-hooks"
        tools = {e["tool"]: e["rc"] for e in _log(bin_dir) if "tool" in e}
        assert tools[1] != 0 and tools[2] == 0  # hooks.json is read-only; robo works


def _program_codex(codex_bin: Path, submit: bool) -> None:
    from test_program import SOLVE

    _fake_codex(codex_bin)
    (codex_bin / "solve.py").write_text(SOLVE)
    tools = {"1": f"cp {codex_bin / 'solve.py'} solution/solve.py && robo-dev submit > /dev/null" if submit else "true"}
    plan = json.loads((codex_bin / "plan.json").read_text())
    (codex_bin / "plan.json").write_text(json.dumps({**plan, "tools": tools}))


@pytest.mark.parametrize("submit", [True, False])
def test_program_codex_at_the_cap_runs_the_last_submission(tmp_path, codex_env, monkeypatch, submit) -> None:
    """The driver's Codex is stopped at the cap, not the driver: it goes on to run the last submission once, as after
    Claude Code's --max-turns. Without one, the episode ends as Claude Code's would."""
    _program_codex(codex_env, submit)
    res, tdir = _trial("program-codex", f"cubepick-reach-layout-{2 if submit else 0}", tmp_path / "job", 2, monkeypatch)
    assert res["exception"] is None, res
    out = json.loads((tdir / "result.json").read_text())
    assert out["turn_cap"]["reached"] and out["turn_cap"]["model_requests_completed"] == 2
    cfg = json.loads((tdir / "config.json").read_text())
    assert cfg["harness_config"]["agent_max_turns"] == 2 and cfg["harness_config"]["max_turns_enforced"] is True
    rec = out["harness_record"]
    if submit:
        assert res["reward"] == 1.0 and rec["stage2"]["ran"] and rec["stage2"]["program_ok"], rec
    else:
        assert res["outcome"] == "gave_up" and not rec["program"]["submitted"]
    assert max(e["sent"] for e in _log(codex_env) if "sent" in e) == 2


# -- Claude Code at --max-turns -----------------------------------------------------------------------------------

FAKE_CLAUDE = r"""
import json, subprocess, sys
args = sys.argv[1:]
turns = int(args[args.index("--max-turns") + 1])
print(json.dumps({"type": "system", "subtype": "init", "session_id": "s-1"}), flush=True)
for n in range(turns):
    subprocess.run("robo observe > /dev/null", shell=True)
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": f"turn {n}"}]}}), flush=True)
print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": turns + 1,
                  "errors": [f"Reached maximum number of turns ({turns})"], "session_id": "s-1"}), flush=True)
sys.exit(1)
"""


def test_claude_code_at_max_turns_is_not_a_harness_error(tmp_path, short, monkeypatch) -> None:
    """Claude Code ends at --max-turns with an error result (`error_max_turns`, is_error true): the turn cap, not a
    failed harness."""
    bin_dir = short / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(f"#!{sys.executable}\n" + FAKE_CLAUDE)
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-key")
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(short / "c"))
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: None)
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    job = tmp_path / "job"
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-1"), "claude-code", "claude-opus-5-5", job, max_turns=2)
    assert res["exception"] is None and res["outcome"] == "gave_up", res
    out = json.loads((job / res["trial"] / "result.json").read_text())
    assert out["turn_cap"] == {"max_turns": 2, "method": "claude-code --max-turns", "reached": True}
    ep = json.loads((job / res["trial"] / "episode" / "result.json").read_text())
    assert ep["agent_text"].endswith("agent exited without robo done")
