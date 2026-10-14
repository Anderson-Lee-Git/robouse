"""What a model harness offers its model and what its sandbox lets the agent reach (deep audit, 2026-10-14)."""

from __future__ import annotations

import os
import re
import shutil
import socket
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

from robouse import _maintainer, harnesses
from robouse.harnesses import interface as iface
from robouse.runner import sandbox

ROOT = Path(__file__).resolve().parents[1]


def _flags(cmd: list[str]) -> list[str]:
    """The `-c` overrides of a Codex command."""
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == "-c"]


def test_codex_turns_web_search_off(tmp_path) -> None:
    """Codex offers its model a web_search tool by default (0.155 and later); every Codex launch turns it off, on its
    own vendor and through the gateway (extra provider flags), and the MCP interface keeps it."""
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    native = harnesses._codex_cmd("TASK", "gpt-6-astra", ws)
    via_gateway = harnesses._codex_cmd("TASK", "m", ws, ["-c", 'model_provider="robouse"'])
    for cmd in (native, via_gateway):
        assert 'web_search="disabled"' in _flags(cmd)
        assert cmd.index('web_search="disabled"') < cmd.index("-m")
    launch = harnesses.Launch(list(native), {"PATH": f"{ws / '.robouse' / 'bin'}:/usr/bin"})
    iface.apply("codex", launch, "mcp", ws, "/tmp/x.sock")
    flags = _flags(launch.cmd)
    assert 'web_search="disabled"' in flags and any(f.startswith("mcp_servers.robo") for f in flags)


def test_codex_web_search_setting_is_valid_toml() -> None:
    """Codex parses each `-c` value as TOML: an unquoted value would be a different setting or an error."""
    assert tomllib.loads(harnesses.CODEX_WEB_SEARCH) == {"web_search": "disabled"}


def test_claude_code_gets_an_allowlist_of_tools(tmp_path) -> None:
    """Claude Code is offered only Bash, Read, Write, Edit, Glob and Grep (`--tools`), not a short deny list that left
    Workflow, Skill, SendMessage, CronCreate, EnterWorktree and others available. With the MCP interface the robo
    tools come from --mcp-config on top: `--tools` names built-in tools only (Claude Code 2.1.285 against a local
    stub offered exactly these six plus the eight mcp__robo__ tools)."""
    cmd = harnesses._claude_cmd("TASK", "claude-opus-5-5")
    assert "--disallowedTools" not in cmd and "--allowedTools" not in cmd
    assert cmd[cmd.index("--tools") + 1].split(",") == ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    launch = harnesses.Launch(cmd, {"PATH": f"{ws / '.robouse' / 'bin'}:/usr/bin"})
    iface.apply("claude-code", launch, "both", ws, "/tmp/x.sock")
    assert launch.cmd[launch.cmd.index("--tools") + 1] == harnesses.CLAUDE_TOOLS
    assert launch.cmd[launch.cmd.index("--mcp-config") + 2] == "--strict-mcp-config"


# ---- the sandbox: credential and task-copy locations --------------------------------------------------------------

SECRET = "SECRET-not-a-real-credential"
# a home folder's credential and task-copy locations, each holding SECRET (folders get a file inside)
PLANTED = [
    ".cache/uv/archive-v0/abc/robouse/bundled_tasks/arc-gravity/oracle/solve.sh",
    ".cache/pip/http-v2/a/robouse.whl",
    ".cache/benchflow/task-formats/robouse/tasks/arc-gravity/oracle/solve.sh",
    ".config/benchflow/provider.env",
    ".claude/.credentials.json",
    ".claude.json",
    ".claude-second/.credentials.json",
    ".codex/auth.json",
    ".codex/sessions/rollout.jsonl",
    ".config/mini-swe-agent/.env",
    ".config/gh/hosts.yml",
    ".ssh/id_ed25519",
    ".netrc",
    ".cache/huggingface/token",
    ".cache/robouse/claude-home/projects/other-trial.jsonl",
    ".cache/robouse/codex-home-other/auth.json",
    ".cache/robouse/dexjoco-venv/lib/site.py",
]


def _home(base: Path) -> dict[str, Path]:
    """A home folder with SECRET in every planted location, a program folder inside ~/.codex, the agent's own Codex
    home inside robouse's cache and a Claude Code home of the runner's own."""
    home = base / "home"
    for rel in PLANTED:
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(SECRET)
    tool = home / ".codex" / "packages" / "bin" / "tool"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\necho program-ok\n")
    tool.chmod(0o755)
    own = home / ".cache" / "robouse" / "codex-home-mine"
    own.mkdir(parents=True)
    (own / "auth.json").write_text("OWN")
    runner = base / "runner-claude-home"
    runner.mkdir()
    (runner / ".credentials.json").write_text(SECRET)
    return {"home": home, "tool": tool, "own": own, "runner": runner}


@pytest.fixture
def outside_tmp():
    """A folder outside /tmp, which bubblewrap replaces with an empty one (and Unix socket paths must be short)."""
    base = Path(tempfile.mkdtemp(dir="/var/tmp"))
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _isolate(monkeypatch, paths: dict[str, Path]) -> None:
    monkeypatch.setenv("HOME", str(paths["home"]))
    monkeypatch.delenv("ROBOUSE_CACHE_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(paths["runner"]))
    monkeypatch.setattr(_maintainer, "private_dirs", lambda: [])


def test_the_profile_and_bwrap_deny_credential_and_task_copy_locations(outside_tmp, monkeypatch) -> None:
    tmp_path = outside_tmp
    p = _home(tmp_path)
    _isolate(monkeypatch, p)
    real = {k: os.path.realpath(v) for k, v in p.items()}
    home = real["home"]
    denied = [f"{home}/{d}" for d in (".cache/uv", ".cache/benchflow", ".config/benchflow", ".claude", ".codex")]
    denied += [f"{home}/.claude-second", f"{home}/.claude.json", f"{home}/.cache/robouse", real["runner"]]
    own = sandbox.own_homes({"CODEX_HOME": str(p["own"]), "PATH": "/usr/bin"})
    assert own == [real["own"]]

    prof = sandbox.sandbox_profile(tmp_path / "ws", (), [], own)
    for d in denied:
        assert f'(deny file-read* file-write* (subpath "{d}"))' in prof, d
    programs = f"{home}/.codex/packages"
    assert f'(allow file-read* (subpath "{programs}"))' in prof  # the program folder: read only
    assert f'(allow file-read* file-write* (subpath "{programs}"))' not in prof
    own_rule = f'(allow file-read* file-write* (subpath "{real["own"]}"))'
    assert prof.index(own_rule) > prof.index(f'"{home}/.cache/robouse"')  # later rules win

    args = sandbox.bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [], own)
    pairs = list(zip(args, args[1:], strict=False))
    for d in denied:
        if os.path.isdir(d):
            assert ("--tmpfs", d) in pairs, d
    assert args[args.index(f"{home}/.claude.json") - 1] == "/dev/null"  # a file: /dev/null over it
    assert args[args.index(f"{home}/.netrc") - 2 : args.index(f"{home}/.netrc")] == ["--ro-bind", "/dev/null"]
    assert args.index(programs) > args.index(f"{home}/.codex") and ("--ro-bind", programs) in pairs
    assert ("--bind", real["own"]) in pairs and args.index(real["own"]) > args.index(f"{home}/.cache/robouse")


def test_a_source_checkout_s_tasks_runs_and_generators_are_denied(tmp_path, monkeypatch) -> None:
    """Run from a checkout, the agent could read every other task's reference solution in tasks/ (the Oct 13 Linux
    sandbox exposed 1,943 oracle files in /opt/robouse; deep audit, security item 3), other trials in runs/ and the
    generators in adapters/. An installed package is denied whole."""
    repo = tmp_path / "repo"
    (repo / "src" / "robouse").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("")
    monkeypatch.setattr(sandbox, "PKG", repo / "src" / "robouse")
    assert sandbox.checkout_denied() == [str(repo / d) for d in ("tasks", "runs", "adapters")]
    for d in ("tasks", "runs", "adapters"):
        assert os.path.realpath(repo / d) in sandbox._denied([])
    monkeypatch.setattr(sandbox, "PKG", tmp_path / "venv" / "lib" / "site-packages" / "robouse")
    assert sandbox.checkout_denied() == []


def test_the_runner_s_python_is_read_only_to_agents(tmp_path) -> None:
    """The episode server and the verifier run on the runner's Python, so an agent must not change it (deep audit,
    security item 10). bubblewrap binds it read-only before the denied folders, so a robouse install inside it stays
    hidden."""
    prefix = os.path.realpath(sys.prefix)
    assert prefix in sandbox.interpreters()
    assert f'(deny file-write* (subpath "{prefix}"))' in sandbox.sandbox_profile(tmp_path / "ws")
    args = sandbox.bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [])
    if not prefix.startswith("/tmp/"):
        i = args.index(prefix)
        assert args[i - 1 : i + 2] == ["--ro-bind", prefix, prefix] and i < args.index(os.path.realpath(sandbox.PKG))


def test_the_profile_refuses_sockets_of_denied_folders_other_trials_and_the_machine(tmp_path, monkeypatch) -> None:
    """Seatbelt's file rules do not stop a connection to a Unix socket (checked on macOS 26 with nc -U): every denied
    path also gets a network rule. Other trials' episode sockets are refused, the agent's own is not, and the SSH agent
    and container engine sockets are denied on both platforms."""
    p = _home(tmp_path)
    _isolate(monkeypatch, p)
    agent = tmp_path / "ssh-agent.sock"
    agent.write_text("")  # stands in for the socket: bubblewrap puts /dev/null over any denied file
    monkeypatch.setenv("SSH_AUTH_SOCK", str(agent))
    real_agent = os.path.realpath(agent)
    assert real_agent in sandbox._denied([]) and "/var/run/docker.sock" in sandbox.SOCKETS
    sock = "/tmp/robouse-0123456789.sock"
    prof = sandbox.sandbox_profile(tmp_path / "ws", (), [], [], sock)
    home = os.path.realpath(p["home"])
    for d in (f"{home}/.docker", f"{home}/.cache/robouse", real_agent, os.path.realpath("/var/run/docker.sock")):
        assert f'(deny network-outbound (remote unix-socket (subpath "{d}")))' in prof, d
    tmp = re.escape(os.path.realpath("/tmp"))
    deny_others = f'(deny network-outbound (remote unix-socket (path-regex #"^{tmp}/robouse-[0-9a-f]+\\.sock$")))'
    allow_own = f'(allow network-outbound (remote unix-socket (path-literal "{os.path.realpath(sock)}")))'
    assert prof.index(deny_others) < prof.index(allow_own)


def test_path_entries_the_agent_cannot_reach_are_dropped(tmp_path, monkeypatch) -> None:
    """`uvx` puts its environment, in the uv cache, first on PATH; inside the sandbox nothing there can run."""
    p = _home(tmp_path)
    _isolate(monkeypatch, p)
    uvx = p["home"] / ".cache" / "uv" / "archive-v0" / "abc" / "bin"
    uvx.mkdir(parents=True)
    path = os.pathsep.join([str(uvx), str(p["tool"].parent), "/usr/bin", "", str(p["own"])])
    kept = sandbox.reachable_path(path, [], [str(p["own"])]).split(os.pathsep)
    assert kept == [str(p["tool"].parent), "/usr/bin", "", str(p["own"])]


PEEK = r"""robo done peek >/dev/null
for f in {planted} {runner}/.credentials.json; do
  cat "$f" 2>/dev/null | grep -q {secret} && echo "LEAK $f"
done
grep -q OWN "$CODEX_HOME/auth.json" && echo own-readable
touch "$CODEX_HOME/new" && echo own-writable
{tool}
touch {tool_dir}/x 2>/dev/null && echo program-writable
touch {prefix}/.robouse-write-probe 2>/dev/null && echo prefix-writable
cat {other_oracle} >/dev/null 2>&1 && echo other-oracle-readable
echo "runner-home=${{CLAUDE_CONFIG_DIR:-unset}} ssh-agent=${{SSH_AUTH_SOCK:-unset}}"
for s in {sockets}; do
  python3 -c 'import socket, sys; s = socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect(sys.argv[1]); print("CONNECTED", sys.argv[1])' "$s" 2>/dev/null
done
exit 0
"""


def _listen(path: Path) -> socket.socket:
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.listen(8)
    return s


def test_a_sandboxed_agent_reads_no_credential_or_task_copy(tmp_path, outside_tmp, monkeypatch) -> None:
    """A whole trial under this platform's sandbox: a scripted agent tries every planted location and the runner's own
    Claude Code home, and connects to a Docker socket inside ~/.docker, a container engine socket, the SSH agent and
    another trial's episode socket. It can use only its own Codex home, run (not change) a program inside ~/.codex,
    and reach a socket nobody denied (the control). Everything sits in /var/tmp: bubblewrap replaces /tmp anyway, and
    a Unix socket path must be short."""
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    if not (sys.platform == "darwin" or (sys.platform.startswith("linux") and sandbox.bwrap_works())):
        pytest.skip("needs the macOS Seatbelt sandbox or working bubblewrap on Linux")
    base = outside_tmp
    other = Path(f"/tmp/robouse-{os.urandom(5).hex()}.sock")  # another trial's episode socket
    listening = []
    try:
        p = _home(base)
        _isolate(monkeypatch, p)
        monkeypatch.delenv("ROBOUSE_SANDBOX", raising=False)
        sockets = {
            "docker-desktop": p["home"] / ".docker" / "run" / "docker.sock",
            "engine": base / "run" / "docker.sock",
            "ssh-agent": base / "ssh" / "agent.sock",
            "other-trial": other,
            "control": base / "free" / "free.sock",
        }
        listening = [_listen(s) for s in sockets.values()]
        monkeypatch.setattr(sandbox, "SOCKETS", (str(sockets["engine"]),))
        monkeypatch.setenv("SSH_AUTH_SOCK", str(sockets["ssh-agent"]))
        script = PEEK.format(
            planted=" ".join(str(p["home"] / rel) for rel in PLANTED),
            runner=p["runner"],
            secret=SECRET,
            tool=p["tool"],
            tool_dir=p["tool"].parent,
            sockets=" ".join(str(s) for s in sockets.values()),
            prefix=sys.prefix,
            other_oracle=ROOT / "tasks" / "arc-style" / "arc-mirror" / "oracle" / "solve.sh",
        )

        def peek(model, prompt, workspace, task, env) -> harnesses.Launch:
            (workspace / ".robouse" / "peek.sh").write_text(script)
            env["CODEX_HOME"] = str(p["own"])
            return harnesses.Launch(["bash", str(workspace / ".robouse" / "peek.sh")], env, notes={"model": "none"})

        monkeypatch.setitem(harnesses.HARNESSES, "peek", peek)
        res = run_trial(load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"), "peek", "", tmp_path / "job")
        out = (tmp_path / "job" / res["trial"] / "agent" / "stdout.jsonl").read_text()
        cfg = (tmp_path / "job" / res["trial"] / "config.json").read_text()
        assert '"sandbox": "none"' not in cfg
        assert "LEAK" not in out, out
        assert "own-readable" in out and "own-writable" in out, out
        assert "program-ok" in out and "program-writable" not in out, out
        assert "prefix-writable" not in out, out  # the runner's Python, which the next episode server runs on
        if sandbox.checkout_denied():  # robouse runs from this checkout: the other tasks' oracles are out of reach
            assert "other-oracle-readable" not in out, out
        assert "runner-home=unset ssh-agent=unset" in out, out
        assert [line.split()[1] for line in out.splitlines() if line.startswith("CONNECTED")] == [
            str(sockets["control"])
        ], out
        assert res["exception"] is None, res
    finally:
        for s in listening:
            s.close()
        other.unlink(missing_ok=True)
        Path(sys.prefix, ".robouse-write-probe").unlink(missing_ok=True)


def test_mini_swe_agent_loads_no_global_env_of_the_user(tmp_path, monkeypatch) -> None:
    """mini-swe-agent loads `<global config dir>/.env` into its own environment, which the agent's shell inherits: a
    user's provider key there would reach the agent (and the sandbox now denies the folder). Each trial gets an empty
    one in its workspace."""
    from types import SimpleNamespace

    from robouse.harnesses import models

    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    gw = SimpleNamespace(url="http://127.0.0.1:1", key="k", model="m", stats={}, stop=lambda: None, stop_file=None)
    monkeypatch.setattr(harnesses, "_gateway", lambda ref, env, protocol: gw)
    monkeypatch.setattr(models, "resolve", lambda h, m: SimpleNamespace(bare="m", id="p/m", provider="p"))
    monkeypatch.setattr(harnesses.shutil, "which", lambda name, path=None: f"/opt/bin/{name}")
    launch = harnesses.HARNESSES["mini-swe-agent"]("p/m", "TASK", ws, None, {"PATH": "/usr/bin"})
    assert launch.env["MSWEA_GLOBAL_CONFIG_DIR"] == str(ws / ".robouse" / "mini-config")


def test_each_claude_code_trial_gets_its_own_config_home(tmp_path, monkeypatch) -> None:
    """Claude Code's config folder was one shared ~/.cache/robouse/claude-home, so a trial's auto-memory could reach the
    next (deep audit, security item 11). Each trial now gets an empty one inside its own workspace, on its own vendor
    and through the gateway."""
    from types import SimpleNamespace

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-key")
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: None)
    homes = []
    for name in ("a", "b"):
        ws = tmp_path / name
        (ws / ".robouse").mkdir(parents=True)
        launch = harnesses.HARNESSES["claude-code"]("claude-opus-5-5", "TASK", ws, None, {"PATH": "/usr/bin"})
        homes.append(Path(launch.env["CLAUDE_CONFIG_DIR"]))
        assert homes[-1] == ws / ".robouse" / "claude-home" and homes[-1].is_dir() and not any(homes[-1].iterdir())
    assert homes[0] != homes[1]

    gw = SimpleNamespace(url="http://127.0.0.1:1", key="k", model="m", stats={}, stop=lambda: None, stop_file=None)
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: SimpleNamespace(bare="m", id="p/m", provider="p"))
    monkeypatch.setattr(harnesses, "_gateway", lambda ref, env, protocol: gw)
    ws = tmp_path / "c"
    (ws / ".robouse").mkdir(parents=True)
    launch = harnesses.HARNESSES["claude-code"]("p/m", "TASK", ws, None, {"PATH": "/usr/bin"})
    assert launch.env["CLAUDE_CONFIG_DIR"] == str(ws / ".robouse" / "claude-home")
