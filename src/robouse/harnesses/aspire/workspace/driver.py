"""The process an aspire trial runs in the agent's sandbox: ASPIRE's practice phase, then its Stage 2.

1. Practice. Starts the coding agent (Claude Code or Codex, with ASPIRE's skills in the workspace) without the scored
   episode: ROBOUSE_SOCKET is removed from its environment, and the scored episode is locked: it serves only requests
   that carry the token the runner gave this process on its stdin, which the agent never sees. The episodes the agent
   drives are practice episodes, through `cap-harness` and the trial's practice broker. Its output goes straight to
   the trial's agent/stdout.jsonl. It is stopped, with its whole process group, at the practice deadline, and when this
   process is told to stop (SIGTERM, SIGINT, SIGHUP).
2. Freeze. Asks the broker to end practice, with the key only this process holds (read from `driver.key` and deleted
   before the agent starts): no more practice episodes, and the broker (outside the sandbox) copies the skill library
   and the selected program out of the workspace. The program comes back from the broker, so the program Stage 2 runs
   is the one the trial records.
3. Stage 2. Unlocks the scored episode and runs the frozen program once on it, under the contract practice runs use,
   then ends the episode with `robo done`; every request carries the token. With no program it gives up, a scored 0;
   but if the agent itself failed (a non-zero exit before selecting anything) it leaves the episode to the runner,
   which records an infrastructure failure, as for any harness that stops on an error.

The workspace is the agent's, so nothing in it is imported after the agent starts: this process runs with `python -I`
(no script folder, no working folder, no PYTHON* variables on its path), loads the program contract
(aspire_programs.py) and the modules Stage 2 needs (numpy, PIL) before the agent starts, and then takes the workspace
off its import path. Its own messages go to stderr (agent/stderr.txt).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent  # <workspace>/.robouse/aspire
WORKSPACE = HERE.parents[1]


def _in_workspace(p: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(p), str(WORKSPACE.resolve())]) == str(WORKSPACE.resolve())
    except ValueError:
        return False


# nothing the agent can write is ever on the import path: not this folder or the working folder (`python -I`), and
# the program contract is loaded from its file by name, before the agent starts, with numpy and PIL from Robo Use's
# own Python (Stage 2 needs them for camera images and imports nothing later)
sys.path[:] = [p for p in sys.path if p and not _in_workspace(p)]
_spec = importlib.util.spec_from_file_location("aspire_programs", WORKSPACE / ".robouse" / "bin" / "aspire_programs.py")
assert _spec is not None and _spec.loader is not None
programs: Any = importlib.util.module_from_spec(_spec)
sys.modules["aspire_programs"] = programs
_spec.loader.exec_module(programs)
try:
    import numpy  # noqa: F401
    from PIL import Image as _Image

    _Image.preinit()
except ImportError:  # pragma: no cover - numpy and Pillow are robouse dependencies
    pass
AGENT: subprocess.Popen | None = None  # the coding agent while it runs, for the signal handler


def say(msg: str) -> None:
    print(f"[aspire] {msg}", file=sys.stderr, flush=True)


def stop_group(proc: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, 15), (signal.SIGKILL, 15)):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            pass
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def on_signal(signum: int, frame: object) -> None:
    """Told to stop (the runner's timeout, Ctrl-C): the agent's process group goes first, then this process. No wait()
    here: the interrupted code may be inside one."""
    if AGENT is not None:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(AGENT.pid, sig)
            except OSError:
                break
            time.sleep(2)
    say(f"stopped by signal {signum}")
    os._exit(128 + signum)


def practice(cfg: dict, scored_socket: str | None) -> tuple[int | None, bool]:
    """Run the agent until it exits or the practice deadline passes: (its exit code, whether it was stopped)."""
    global AGENT
    env = {k: v for k, v in os.environ.items() if k not in ("ROBOUSE_SOCKET", "ROBO_SOCKET")}
    deadline = float(cfg["practice_deadline"])
    say(f"practice: {' '.join(cfg['agent_cmd'][:1])} until {time.strftime('%H:%M:%S', time.localtime(deadline))}")
    proc = subprocess.Popen(cfg["agent_cmd"], cwd=WORKSPACE, env=env, stdin=subprocess.DEVNULL, start_new_session=True)
    AGENT = proc
    stopped = False
    try:
        rc = proc.wait(timeout=max(1.0, deadline - time.time()))
    except subprocess.TimeoutExpired:
        say("practice deadline reached: stopping the agent")
        stopped = True
        stop_group(proc)
        rc = proc.returncode
    # anything the agent left running in its process group goes too: nothing may act during Stage 2
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    return rc, stopped


def stage2(send: Any, info: dict, program: str) -> dict:
    """The frozen program, once, on the scored episode; then `robo done`."""
    api = programs.Api(send, info)
    t0 = time.time()
    execution = programs.execute(program, api)
    status = send({"op": "status"})
    finished = bool((status.get("result") or {}).get("finished")) if status.get("ok") else True
    sha = hashlib.sha256(program.encode()).hexdigest()
    if not finished:
        text = f"aspire: frozen program {sha[:12]} " + ("finished" if execution.ok else "stopped on an error")
        send({"op": "done", "text": text})
    return {
        "ran": True,
        "program_sha256": sha,
        "program_ok": execution.ok,
        "error": execution.error,
        "result": execution.result,
        "stdout_tail": execution.stdout[-4000:],
        "tool_calls": api.calls,
        "steps_used": api.steps_used,
        "episode_finished_by_program": finished,
        "wall_s": round(time.time() - t0, 1),
    }


def main() -> int:
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, on_signal)
    # the scored episode's token, from the runner on this process's stdin: read and closed before the agent starts
    # (with its stdin closed too), held only in memory. Every request to the scored episode must carry it
    unlock = sys.stdin.readline().strip()
    sys.stdin.close()
    cfg = json.loads((HERE / "driver.json").read_text())
    key_file = HERE / "driver.key"  # the broker's freeze key: read and deleted before the agent starts
    freeze_key = key_file.read_text().strip() if key_file.is_file() else ""
    key_file.unlink(missing_ok=True)
    scored_socket = os.environ.get("ROBOUSE_SOCKET")
    for name in ("socket", "ready"):  # `robo` falls back to .robouse/socket; .robouse/ready names the socket too
        (WORKSPACE / ".robouse" / name).unlink(missing_ok=True)
    base = str(cfg["practice_url"]).rstrip("/")
    record: dict = {"agent": cfg.get("agent"), "stage1": "reused" if cfg.get("agent_cmd") is None else "ran"}

    def report(stage2_record: dict, code: int) -> int:
        record["stage2"] = stage2_record
        (HERE / "stage2.json").write_text(json.dumps(record, indent=2))
        return code

    rc: int | None = 0
    stopped = False
    if cfg.get("agent_cmd"):
        rc, stopped = practice(cfg, scored_socket)
        record.update(agent_exit=rc, agent_stopped_at_deadline=stopped)
    status, frozen = programs.http_json(f"{base}/freeze", {"by": "driver", "key": freeze_key}, timeout=600)
    if status != 200:
        say(f"freeze failed: {frozen.get('error')}")
        frozen = {}
    program = frozen.get("program")
    record["program_path"] = frozen.get("program_path")
    if not scored_socket:
        say("no scored episode socket")
        return report({"ran": False, "error": "no scored episode socket"}, 1)
    if not program and not stopped and rc not in (0, None):
        # the agent failed (an API or credential error, say) before selecting anything: an infrastructure failure,
        # which the runner records when it closes the episode itself
        say(f"the agent exited with code {rc} before selecting a program; leaving the episode to the runner")
        return report({"ran": False, "error": f"the agent exited with code {rc} and selected no program"}, int(rc))
    plain = programs.unix_transport(scored_socket)

    def send(req: dict) -> dict:  # every request carries the token: the episode serves nothing without it
        return plain({**req, "unlock": unlock} if unlock else req)

    if unlock:
        opened = send({"op": "unlock"})
        if not opened.get("ok"):
            say(f"the scored episode did not unlock: {opened.get('error')}")
    # Stage 2's first request after the unlock carries a marker, for the trace
    info = send({"op": "info", "aspire": "stage2"})
    if not info.get("ok"):
        say(f"the scored episode did not answer: {info.get('error')}")
        return report({"ran": False, "error": f"the scored episode did not answer: {info.get('error')}"}, 1)
    if program:
        say(f"stage 2: running {frozen.get('program_path')} on the scored episode")
        return report(stage2(send, info.get("result") or {}, program), 0)
    why = (
        "practice time ran out before a program was selected"
        if stopped
        else f"no program was selected ({cfg.get('program_hint')} is missing)"
    )
    say(f"stage 2: {why}; giving up the scored episode")
    send({"op": "give_up", "text": f"aspire: {why}"})
    return report({"ran": False, "error": why}, 0)


if __name__ == "__main__":
    sys.exit(main())
