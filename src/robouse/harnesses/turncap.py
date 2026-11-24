"""The agent turn cap for Codex: the equivalent of Claude Code's `--max-turns N`.

What Claude Code counts. `claude -p --max-turns N` counts its agent loop's iterations: each one is a model request
whose answer asked for tools, followed by those tools' run. After the tools of the N-th answer have run it stops
without sending request N+1, ends its stream with a result event `{"subtype": "error_max_turns", "is_error": true}`
and exits. A retried request (an API error, an overload) is the same iteration; an answer without a tool call ends the
loop by itself.

What Codex does here (codex-cli 0.167.0 and later: the PreModelRequest and PostModelRequest hooks). The runner writes
a `hooks.json` into the trial's own CODEX_HOME and passes `--dangerously-bypass-hook-trust` (Robo Use wrote the hooks;
the policy did not). Two command hooks talk to a server in the runner process over a Unix socket in that home:

- PostModelRequest reports each attempt's `status`; only `completed` ones count (a failed or cancelled attempt that
  Codex retries is not a turn, as in Claude Code).
- PreModelRequest asks before each attempt. Below the cap the server answers at once. When N requests have
  completed it does not answer: the hook blocks (with a hook timeout far beyond any trial), so request N+1 is never
  sent, and the runner stops Codex (its process group: the whole agent for the `codex` harness, only the coding agent
  for a driver, program-codex and aspire-codex, which then goes on as it does after Claude Code's cap).

The count lives in the runner, not in any file the agent can reach: the hooks run inside the agent's sandbox, as the
agent's own commands do, so nothing they can write is out of the agent's reach. The agent could only add counts (end
its own trial sooner), never remove them. The hooks print nothing, so nothing reaches the model's context, and
hooks.json is read-only in the sandbox.

The tool calls of the N-th answer run to completion before Codex asks for request N+1, as in Claude Code. The trial
then ends as a trial at Claude Code's cap does: the runner closes the episode with "agent exited without robo done",
records no harness error, and result.json's `turn_cap` says the cap was reached.

Fallback (`json-stream`): a Codex without these hooks (older than 0.167.0), a shared account-pool home (one hooks.json
for many trials) or a home path too long for a Unix socket. The runner counts model answers in the `codex exec --json`
stream and stops Codex when answer N+1 begins. Approximate (the stream does not mark requests, and Codex may run one
answer's tool calls one after another), and request N+1 has been sent by then, so it is recorded as not enforced. The
same count backs up the hooks: when the stream shows more than N answers and no hook ever reported, the runner stops
Codex and records that the hooks never fired.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

HOOKS_MIN_VERSION = (0, 167, 0)  # the first codex-cli known to have PreModelRequest and PostModelRequest
HOOK_TIMEOUT_S = 7 * 24 * 3600  # a blocked PreModelRequest hook outlasts any trial; the runner stops Codex first
SOCKET_NAME = "h.sock"
MAX_SOCKET_PATH = 100  # bytes; AF_UNIX allows 104 (macOS) or 108 (Linux)
BYPASS_TRUST = "--dangerously-bypass-hook-trust"

METHOD_HOOKS = "codex-hooks"
METHOD_STREAM = "json-stream"

# The hook: one JSON line to the runner, then wait for its answer; no output at all. A PreModelRequest at the cap gets
# no answer and waits until Codex is stopped (its parent goes) or the runner closes the socket. Any failure exits
# silently: the runner's stream count backs the hooks up.
HOOK_SOURCE = r"""
import json, os, socket, sys
try:
    ev = json.loads(sys.stdin.read() or "{}")
except Exception:
    ev = {}
if not isinstance(ev, dict):
    ev = {}
msg = {"event": sys.argv[2], "status": ev.get("status"), "turn_id": ev.get("turn_id"), "agent_id": ev.get("agent_id")}
parent = os.getppid()
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sys.argv[1])
    s.sendall((json.dumps(msg) + "\n").encode())
    s.settimeout(1.0)
    while True:
        try:
            s.recv(64)  # the runner's answer, or the end of the connection
            break
        except socket.timeout:
            if os.getppid() != parent:
                break
except Exception:
    pass
"""


def codex_version(path: str | None = None) -> tuple[int, ...] | None:
    """The installed codex-cli's version (`codex --version`), or None."""
    exe = shutil.which("codex", path=path)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(x) for x in m.groups()) if m else None


def hooks_json(sock: str) -> dict:
    """The hooks.json the trial's Codex home gets."""

    def handler(event: str) -> dict:
        cmd = " ".join(shlex.quote(a) for a in (sys.executable, "-I", "-c", HOOK_SOURCE, sock, event))
        return {"hooks": [{"type": "command", "command": cmd, "timeout": HOOK_TIMEOUT_S}]}

    return {
        "hooks": {"PreModelRequest": [handler("PreModelRequest")], "PostModelRequest": [handler("PostModelRequest")]}
    }


class StreamCount:
    """Model answers in a `codex exec --json` stream. An answer begins with its first item (reasoning, a message or a
    tool call) once every tool call started before it has finished; the first item of the stream begins answer 1. A
    single answer whose tool calls Codex runs one after another counts more than once: the count errs high, so the
    fallback stops at the cap or before it, never after."""

    TOOLS = ("command_execution", "file_change", "mcp_tool_call", "web_search", "todo_list")

    def __init__(self) -> None:
        self.answers = 0
        self.running: set[str] = set()
        self.tool_done = False
        self.seen: set[str] = set()
        self._buf = b""
        self._pos = 0

    def feed(self, ev: dict) -> None:
        et = ev.get("type")
        if et not in ("item.started", "item.updated", "item.completed"):
            return
        it = ev.get("item") or {}
        iid, typ = str(it.get("id") or ""), it.get("type")
        if typ == "error":
            return
        if iid not in self.seen:
            self.seen.add(iid)
            if self.answers == 0 or (self.tool_done and not self.running):
                self.answers += 1
                self.tool_done = False
        if typ in self.TOOLS:
            if et == "item.completed":
                self.running.discard(iid)
                self.tool_done = True
            else:
                self.running.add(iid)

    def read(self, path: Path) -> int:
        """Feed the lines appended to `path` since the last call; the answer count."""
        try:
            with open(path, "rb") as f:
                f.seek(self._pos)
                chunk = f.read()
        except OSError:
            return self.answers
        self._pos += len(chunk)
        self._buf += chunk
        *lines, self._buf = self._buf.split(b"\n")
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                self.feed(ev)
        return self.answers


class CodexTurnCap:
    """One trial's Codex turn cap. `inner`: Codex runs under a driver (program-codex, aspire-codex), so only its own
    process group is stopped; otherwise the runner stops the whole agent."""

    def __init__(
        self, cap: int, home: str, method: str, inner: bool = False, why: str = "", version: str | None = None
    ) -> None:
        self.cap = int(cap)
        self.version = version  # codex-cli's
        self.home = home
        self.method = method
        self.why = why  # why the fallback is used
        self.inner = inner
        self.stream: Path | None = None  # set by the runner: the trial's agent/stdout.jsonl
        self.completed = 0  # model requests that completed (PostModelRequest status completed)
        self.attempts = 0  # PreModelRequest calls
        self.failed = 0  # PostModelRequest with another status
        self.hook_events = 0
        self.reached = False
        self.reached_by: str | None = None
        self.reached_at: float | None = None
        self.stopped = False
        self._forced = False
        self.count = StreamCount()
        self.sock: str | None = None
        self._server: socketserver.ThreadingUnixStreamServer | None = None
        self._lock = threading.Lock()
        self._held: list[socket.socket] = []

    # -- the hooks' server (runner side) ------------------------------------------------------------------------------

    def start(self) -> None:
        """Start the server and write hooks.json (codex-hooks only)."""
        if self.method != METHOD_HOOKS:
            return
        sock = os.path.join(self.home, SOCKET_NAME)
        cap = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                try:
                    msg = json.loads(self.rfile.readline() or b"{}")
                except ValueError:
                    return
                if not isinstance(msg, dict):
                    return
                if cap.event(msg):
                    self.wfile.write(b"ok\n")
                    return
                with cap._lock:  # held open: the hook waits until Codex is stopped or the server closes
                    cap._held.append(self.request)
                while not cap._closing.wait(1.0):
                    pass

            def finish(self) -> None:
                try:
                    super().finish()
                except OSError:
                    pass

        self._closing = threading.Event()
        self._server = socketserver.ThreadingUnixStreamServer(sock, Handler)
        self._server.daemon_threads = True
        os.chmod(sock, 0o600)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.sock = sock
        hooks = Path(self.home) / "hooks.json"
        hooks.write_text(json.dumps(hooks_json(sock), indent=2))

    def event(self, msg: dict) -> bool:
        """A hook's report; False to hold a PreModelRequest at the cap."""
        with self._lock:
            self.hook_events += 1
            if msg.get("event") == "PostModelRequest":
                if msg.get("status") == "completed":
                    self.completed += 1
                else:
                    self.failed += 1
                return True
            if msg.get("event") == "PreModelRequest":
                self.attempts += 1
                if self.completed >= self.cap:
                    if not self.reached:
                        self.reached, self.reached_by, self.reached_at = True, METHOD_HOOKS, time.time()
                    return False
            return True

    def close(self) -> None:
        if self._server is not None:
            self._closing.set()
            self._server.shutdown()
            self._server.server_close()
            with self._lock:
                for s in self._held:
                    try:
                        s.close()
                    except OSError:
                        pass
            self._server = None
        if self.sock:
            Path(self.sock).unlink(missing_ok=True)

    # -- the runner's watch ----------------------------------------------------------------------------------------

    def poll(self, agent_pid: int) -> bool:
        """Called by the runner while the agent runs. Reads the stream (the fallback, and the hooks' backup) and stops
        Codex once the cap is reached. True when the runner should stop the whole agent now (not `inner`)."""
        if self.stream is not None and not self.reached:
            answers = self.count.read(self.stream)
            if answers > self.cap and (self.method == METHOD_STREAM or self.hook_events == 0):
                self.reached, self.reached_at = True, time.time()
                self.reached_by = METHOD_STREAM if self.method == METHOD_STREAM else "json-stream (hooks never fired)"
        if not self.reached:
            return False
        if not self.inner:
            self.stopped = True
            return True
        if not self.stopped:
            self.stopped = stop_codex_under(agent_pid)
        elif not self._forced and time.time() - (self.reached_at or 0) > 15:
            self._forced = True  # still there 15 s on: SIGKILL
            stop_codex_under(agent_pid, force=True)
        return False

    def record(self) -> dict:
        return {
            "max_turns": self.cap,
            "method": self.method,
            **({"fallback_reason": self.why} if self.why else {}),
            "reached": self.reached,
            "reached_by": self.reached_by,
            "model_requests_completed": self.completed if self.method == METHOD_HOOKS else None,
            "model_requests_failed": self.failed if self.method == METHOD_HOOKS else None,
            "stream_answers": self.count.answers,
            "hook_events": self.hook_events if self.method == METHOD_HOOKS else None,
        }


def _processes() -> list[tuple[int, int, int, str]]:
    """(pid, ppid, pgid, command name) of every process (`ps`, on Linux and macOS)."""
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,pgid=,comm="], capture_output=True, text=True, timeout=10, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and all(p.isdigit() for p in parts[:3]):
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), os.path.basename(parts[3].strip())))
    return rows


def stop_codex_under(root: int, force: bool = False) -> bool:
    """Stop the Codex processes below `root` (a driver), each with its process group when that group is its own (the
    driver starts its agent in a new session); True when one was found. SIGTERM, or SIGKILL with `force`."""
    rows = _processes()
    kids: dict[int, list[int]] = {}
    info = {pid: (ppid, pgid, name) for pid, ppid, pgid, name in rows}
    for pid, ppid, _, _ in rows:
        kids.setdefault(ppid, []).append(pid)
    root_pgid = info.get(root, (0, root, ""))[1]
    found, todo = False, list(kids.get(root, []))
    sig = signal.SIGKILL if force else signal.SIGTERM
    while todo:
        pid = todo.pop()
        ppid, pgid, name = info[pid]
        if name.startswith("codex") and not info.get(ppid, (0, 0, ""))[2].startswith("codex"):
            found = True
            try:
                if pgid != root_pgid:
                    os.killpg(pgid, sig)
                else:
                    os.kill(pid, sig)
            except OSError:
                pass
            continue
        todo += kids.get(pid, [])
    return found


def plan(cap: int, home: str, path: str | None, pool: bool, inner: bool = False) -> CodexTurnCap:
    """The turn cap for one Codex launch: the hooks when this Codex has them and the home is the trial's own, else the
    stream fallback (with the reason)."""
    why = ""
    version = codex_version(path)
    if pool:
        why = "a shared account-pool Codex home (no per-trial hooks.json)"
    elif version is None:
        why = "codex --version gave no version"
    elif version < HOOKS_MIN_VERSION:
        why = f"codex-cli {'.'.join(map(str, version))} predates the model-request hooks (0.167.0)"
    elif len(os.path.join(home, SOCKET_NAME).encode()) > MAX_SOCKET_PATH:
        why = "the Codex home's path is too long for a Unix socket"
    shown = ".".join(map(str, version)) if version else None
    return CodexTurnCap(cap, home, METHOD_STREAM if why else METHOD_HOOKS, inner=inner, why=why, version=shown)


def claude_cap_reached(final: dict | None) -> bool:
    """Whether Claude Code's own final result event (runner/trial.py _final_result) says it stopped at --max-turns."""
    return bool(final) and final.get("subtype") == "error_max_turns"  # type: ignore[union-attr]


def describe(tc: CodexTurnCap) -> dict:
    """config.json's account of a Codex turn cap."""
    return {
        "max_turns_method": tc.method,
        "codex_version": tc.version,
        **({"max_turns_fallback_reason": tc.why} if tc.why else {}),
    }
