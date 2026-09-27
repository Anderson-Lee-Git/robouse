
<job>/<task>__<harness>__<n>/
  config.json                 task, harness, model, seed, timeouts
  agent/stdout.jsonl          raw harness output (stream-json / codex --json / text)
  agent/stderr.txt
  agent/trajectory.json       ATIF trajectory converted from the raw output (see atif.py)
  episode/                    trusted episode server output (result.json, trace.jsonl, frames.jsonl)
  verifier/reward.txt         0 or 1, written by the task's tests/test.sh
  verifier/test-stdout.txt
  artifacts/recording.mp4     episode video
  artifacts/recording_index.json   video time for each trajectory step
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import harnesses
from .tasks import Task, find_tasks

AGENT_CLI = Path(__file__).with_name("agent_cli.py")


def sandbox_profile() -> str:
    """macOS Seatbelt profile for agent processes: everything is allowed except reading or writing the
    robouse repo, runs and episode data (all under ~/benchflow) and the owner's credential files.
    The agent still reaches the episode socket (/tmp) and the network (model APIs). Set ROBOUSE_SANDBOX=0 to disable."""
    home = str(Path.home())
    denied = [f"{home}/benchflow", f"{home}/.config/bf-agents"] + [p for p in os.environ.get("ROBOUSE_SANDBOX_DENY", "").split(":") if p]
    rules = "".join(f'(deny file-read* file-write* (subpath "{d}"))' for d in denied)
    return "(version 1)(allow default)" + rules


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_workspace(task: Task) -> Path:
    ws = Path(tempfile.mkdtemp(prefix=f"robouse-ws-{task.id[:24]}-"))
    (ws / ".robouse" / "bin").mkdir(parents=True)
    shim = ws / ".robouse" / "bin" / "robo"
    shim.write_text("#!/usr/bin/env python3\n" + AGENT_CLI.read_text())
    shim.chmod(0o755)
    (ws / "instruction.md").write_text(task.instruction)
    (ws / "observations").mkdir()
    return ws


def _wait_ready(p: Path, proc: subprocess.Popen, timeout: float = 120) -> None:
    t = time.time() + timeout
    while time.time() < t:
        if p.exists():
            return
        if proc.poll() is not None:
            raise RuntimeError(f"episode server exited early ({proc.returncode})")
        time.sleep(0.2)
    raise TimeoutError("episode server did not start")


def run_trial(task: Task, harness: str, model: str, job_dir: Path, timeout: float | None = None,
              seed: int | None = None, trial_name: str | None = None) -> dict:
    job_dir.mkdir(parents=True, exist_ok=True)
    trial_name = trial_name or f"{task.id}__{harness}__{uuid.uuid4().hex[:6]}"
    tdir = job_dir / trial_name
    for sub in ("agent", "episode", "verifier", "artifacts"):
        (tdir / sub).mkdir(parents=True, exist_ok=True)
    timeout = float(timeout or task.agent_timeout_s)
    ws = _make_workspace(task)
    sock = f"/tmp/robouse-{uuid.uuid4().hex[:10]}.sock"
    ready = ws / ".robouse" / "ready"
    started = _now()
    t0 = time.time()
    cfg = {"task": task.id, "task_path": str(task.path), "harness": harness, "model": model, "seed": seed,
           "agent_timeout_s": timeout, "trial_name": trial_name, "started_at": started, "workspace": str(ws),
           "metadata": task.metadata}
    (tdir / "config.json").write_text(json.dumps(cfg, indent=2))

    py = sys.executable
    server_cmd = [py, "-m", "robouse.cli", "serve", "--task", str(task.path), "--run-dir", str(tdir / "episode"),
                  "--socket", sock, "--workspace", str(ws), "--ready-file", str(ready), "--max-wall-s", str(timeout + 60)]
    if seed is not None:
        server_cmd += ["--seed", str(seed)]
    oracle_token = uuid.uuid4().hex
    server = subprocess.Popen(server_cmd, env={**os.environ, "ROBOUSE_ORACLE_TOKEN": oracle_token}, stdout=open(tdir / "episode" / "server.log", "w"), stderr=subprocess.STDOUT)
    exc = None
    launch = None
    agent_rc = None
    timed_out = False
    try:
        _wait_ready(ready, server)
        (ws / ".robouse" / "socket").write_text(sock)
        base_env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_OAUTH", "OPENAI_", "BASETEN"))}
        base_env["PATH"] = f"{ws / '.robouse' / 'bin'}:{Path(py).parent}:{base_env.get('PATH', '')}" if harness == "oracle" \
            else f"{ws / '.robouse' / 'bin'}:{base_env.get('PATH', '')}"
        base_env["ROBOUSE_SOCKET"] = sock
        base_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) if harness == "oracle" else ""
        base_env.pop("ROBOUSE_ORACLE_TOKEN", None)
        if harness == "oracle":  # only the reference solution may see privileged state in vision tasks
            base_env["ROBOUSE_ORACLE_TOKEN"] = oracle_token
        launch = harnesses.build(harness, model, task.instruction, ws, task.path, base_env)
        sandboxed = harness not in ("oracle", "noop") and sys.platform == "darwin" and os.environ.get("ROBOUSE_SANDBOX", "1") != "0"
        if sandboxed:
            launch.cmd = ["sandbox-exec", "-p", sandbox_profile(), *launch.cmd]
        cfg["sandbox"] = "macos-seatbelt: deny ~/benchflow, ~/.config/bf-agents" if sandboxed else "none"
        (tdir / "config.json").write_text(json.dumps(cfg, indent=2))
        with open(tdir / "agent" / "stdout.jsonl", "w") as out, open(tdir / "agent" / "stderr.txt", "w") as err:
            agent = subprocess.Popen(launch.cmd, cwd=ws, env=launch.env, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
            try:
                agent_rc = agent.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(agent.pid, signal.SIGTERM)
                try:
                    agent.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(agent.pid, signal.SIGKILL)
    except Exception as e:  # infrastructure failure, recorded in result.json
        exc = f"{type(e).__name__}: {e}"
    finally:
        # close the episode if the agent did not call `robo done`
        from .agent_cli import _send

        os.environ["ROBOUSE_SOCKET"] = sock
        os.environ.pop("ROBOUSE_ORACLE_TOKEN", None)
        st = _send({"op": "status"})
        if st.get("ok") and not st["result"]["finished"]:
            _send({"op": "give_up", "text": "[runner] agent timed out" if timed_out else "[runner] agent exited without robo done"})
        try:
            server.wait(timeout=60)
        except subprocess.TimeoutExpired:
            server.kill()

    ep = tdir / "episode" / "result.json"
    episode = json.loads(ep.read_text()) if ep.exists() else {}
    if timed_out and episode.get("outcome") == "gave_up":
        episode["outcome"] = "agent_timeout"
    # verifier: the task's own tests/test.sh turns the trusted verdict into reward.txt
    vt = subprocess.run(["bash", str(task.path / "tests" / "test.sh")], capture_output=True, text=True,
                        env={**os.environ, "ROBOUSE_EPISODE_DIR": str(tdir / "episode"), "ROBOUSE_VERIFIER_DIR": str(tdir / "verifier")})
    (tdir / "verifier" / "test-stdout.txt").write_text(vt.stdout + vt.stderr)
    rf = tdir / "verifier" / "reward.txt"
    reward = float(rf.read_text().strip()) if rf.exists() and rf.read_text().strip() else 0.0

    # artifacts: video + observation images the agent saw
    if (tdir / "episode" / "recording.mp4").exists():
        shutil.copy(tdir / "episode" / "recording.mp4", tdir / "artifacts" / "recording.mp4")
    for f in sorted((ws / "observations").glob("*.png")):
        (tdir / "artifacts" / "observations").mkdir(exist_ok=True)
        shutil.copy(f, tdir / "artifacts" / "observations" / f.name)
    if harness == "mini-swe-agent-glm" and (ws / ".robouse" / "mini_traj.json").exists():
        shutil.copy(ws / ".robouse" / "mini_traj.json", tdir / "agent" / "mini_traj.json")

    try:
        from .atif import write_trajectory

        write_trajectory(tdir, harness)
    except Exception as e:  # trajectory conversion is best effort; raw output is kept
        (tdir / "agent" / "trajectory_error.txt").write_text(f"{type(e).__name__}: {e}")

    res = {
        "task_name": task.id, "trial_name": trial_name, "source": task.metadata.get("source_benchmark"),
        "agent_info": {"name": harness, "model_info": {"name": (launch.notes.get("model") if launch else model)}},
        "verifier_result": {"rewards": {"reward": reward}},
        "episode": episode, "agent_return_code": agent_rc, "agent_timed_out": timed_out,
        "exception_info": {"exception_type": exc.split(":")[0], "exception_message": exc} if exc else None,
        "started_at": started, "finished_at": _now(), "wall_time_s": round(time.time() - t0, 1),
    }
    if launch and isinstance(launch.helper, dict):
        res["proxy_stats"] = launch.helper
    (tdir / "result.json").write_text(json.dumps(res, indent=2))
    shutil.rmtree(ws, ignore_errors=True)
    return {"trial": trial_name, "reward": reward, "outcome": episode.get("outcome"), "steps": episode.get("steps_used"),
            "wall_s": res["wall_time_s"], "exception": exc}


def run_many(root: Path, harness: str, model: str, job_dir: Path, filt: str = "", limit: int = 0,
             concurrency: int = 1, timeout: float | None = None, ids: list[str] | None = None) -> list[dict]:
    tasks = [t for t in find_tasks(root) if filt in t.id and (ids is None or t.id in ids)]
    if limit:
        tasks = tasks[:limit]
    job_dir.mkdir(parents=True, exist_ok=True)
    log = open(job_dir / "run_log.jsonl", "a")
    results = []

    def one(t: Task) -> dict:
        r = run_trial(t, harness, model, job_dir, timeout=timeout)
        r["task"] = t.id
        return r

    with cf.ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs = [ex.submit(one, t) for t in tasks]
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            log.write(json.dumps(r) + "\n")
            log.flush()
            print(f"{r['task']:<40} reward={r['reward']:.0f} outcome={r['outcome']} steps={r['steps']} {r['wall_s']}s"
                  + (f" EXC {r['exception']}" if r["exception"] else ""), flush=True)
    ok = sum(r["reward"] for r in results)
    print(f"{harness}/{model or '-'}: {ok:.0f}/{len(results)} solved")
    return results
