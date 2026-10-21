"""`cap-harness` in an aspire trial's workspace: ASPIRE's program runner, on Robo Use practice episodes.

ASPIRE's skills run generated programs with `cap-harness run` (one seed) and `cap-harness run-batch` (many seeds), and
read what those record (ASPIRE's docs/run-artifacts.md: run.json, outcome.json, source/, trace/, media/). This command
takes the same options and writes the same layout, but each run is a Robo Use practice episode: the trial's practice
broker starts the task's episode server on the requested seed (only this trial's practice seeds, never the scored
one), the program runs against it under the program contract the scored run uses (aspire_programs.py), and the episode
server judges success after `robo done` and its still steps, as it judges the scored episode.

Only `run` and `run-batch` exist; `--benchmark`, `--suite` and `--task-id` must name this trial's task. `--init-mode`,
`--camera-width` and `--camera-height` are recorded, not applied (the seed alone picks the scene, and images come at
the task's own size); `--max-steps` cannot raise the task's step budget. Standard library only.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aspire_programs as programs  # type: ignore[import-not-found]

WORKSPACE = Path(__file__).resolve().parents[2]  # .robouse/bin/cap-harness
TRIAL_FILE = WORKSPACE / ".robouse" / "aspire" / "trial.json"
PROFILE = os.path.join("docs", "robouse.md")  # the workspace's page on how ASPIRE maps onto the trial


def trial() -> dict:
    return json.loads(TRIAL_FILE.read_text())


def broker_url(t: dict) -> str:
    return (os.environ.get("ROBOUSE_PRACTICE_URL") or t.get("practice_url") or "").rstrip("/")


def now() -> str:
    return datetime.now(UTC).isoformat()


def parse_seeds(values: list[str]) -> list[int]:
    """`51 52 53` and `51-65` alike (cap-harness's parse_seed_arguments)."""
    seeds: list[int] = []
    for value in values:
        text = str(value).strip()
        start, sep, end = text.partition("-")
        if sep and start.strip().isdigit() and end.strip().isdigit():
            lo, hi = int(start), int(end)
            if hi < lo:
                raise ValueError(f"seed range must not run backwards: {text}")
            seeds.extend(range(lo, hi + 1))
            continue
        try:
            seeds.append(int(text))
        except ValueError as e:
            raise ValueError(f"not a seed or seed range: {text!r}") from e
    out = sorted(set(seeds))
    if not out:
        raise ValueError("no seeds requested")
    return out


def check_task(a: argparse.Namespace, t: dict) -> str | None:
    """Why this workspace cannot run the requested task, or None."""
    want = (str(t["benchmark"]), str(t["suite"]), int(t["task_id"]))
    got = (str(a.benchmark), str(a.suite), int(a.task_id))
    if got != want:
        return (
            f"this workspace runs one task: --benchmark {want[0]} --suite {want[1]} --task-id {want[2]} "
            f"(Robo Use task {t['task']}); asked for {got[0]}/{got[1]}/task {got[2]}"
        )
    return None


# ---- one run --------------------------------------------------------------------------------------------------------
def run_dir_for(a: argparse.Namespace, t: dict, seed: int) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    rid = f"{stamp}-{secrets.token_hex(3)}"
    root = Path(a.output_root)
    if not a.flat_run_dir:
        root = root / str(a.benchmark) / str(a.suite) / f"{a.task_id}-{t['task']}"
    return root / f"{seed:04d}" / rid


def write_json(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(p)


class Recorder:
    """The run directory of one practice run, in cap-harness's layout."""

    def __init__(self, root: Path):
        self.root = root
        self.calls = 0
        self.keyframes = 0
        (root / "trace").mkdir(parents=True, exist_ok=True)
        self.events = open(root / "trace" / "events.jsonl", "a")  # noqa: SIM115 - open for the whole run

    def span(self, span: dict) -> None:
        self.calls += 1
        name = str(span.get("name"))
        call_dir = self.root / "trace" / "calls" / f"call-{self.calls:06d}-{name.replace('_', '-')}"
        write_json(call_dir / "input.json", {"args": span.get("args"), "kwargs": span.get("kwargs")})
        write_json(
            call_dir / "output.json", {"ok": span.get("ok"), "output": span.get("output"), "error": span.get("error")}
        )
        ev = {"event": "span_end", "type": "span_end", "index": self.calls, "t": now(), **span}
        ev.pop("args", None), ev.pop("kwargs", None), ev.pop("output", None)
        self.events.write(json.dumps(ev) + "\n")
        self.events.flush()

    def close(self) -> None:
        self.events.close()


def fetch(base: str, episode: str, name: str, dest: Path) -> bool:
    """Copy one file of a practice episode's record (kept by the broker, outside the sandbox) into the run."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{base}/episodes/{episode}/files/{name}", timeout=600) as r:
            data = r.read()
    except OSError:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def keyframe_saver(base: str, episode: str, rec: Recorder, api_box: list, camera: str):
    """After each call that stepped the robot: one camera image into media/keyframes/<NNNNNN>-after-<tool>/."""

    def save(label: str) -> None:
        api = api_box[0]
        try:
            reply = api.send({"op": "observe", "image": True})
        except Exception:
            return
        path = ((reply.get("result") or {}) if reply.get("ok") else {}).get("image_path")
        if isinstance(path, list):
            path = path[0] if path else None
        if not isinstance(path, str):
            return
        rec.keyframes += 1
        name = f"{rec.keyframes:06d}-after-{label.replace('_', '-')}"
        fetch(base, episode, path, rec.root / "media" / "keyframes" / name / f"{camera}.png")

    return save


def termination(execution: programs.Execution | None, verdict: dict, rejected: bool) -> str:
    """cap-harness's termination_reason for a Robo Use practice episode."""
    outcome = verdict.get("outcome")
    if rejected:
        return "program_error"
    if outcome == "budget_exhausted":
        return "step_limit"
    if outcome == "wall_time_exhausted":
        return "environment_truncated"
    if outcome == "success_reached":
        return "task_succeeded"
    if execution is not None and not execution.ok:
        return "program_error"
    return "program_completed"


class ProgramTimeout(Exception):
    pass


def run_one(a: argparse.Namespace, t: dict, seed: int) -> int:
    base = broker_url(t)
    t0 = time.time()
    root = run_dir_for(a, t, seed)
    root.mkdir(parents=True, exist_ok=True)
    camera = str(t.get("camera") or "camera")
    max_steps = int(a.max_steps or t["max_steps"])
    run_json: dict[str, Any] = {
        "schema_version": 1,
        "run_id": root.name,
        "benchmark": a.benchmark,
        "suite": a.suite,
        "task_id": int(a.task_id),
        "task_name": t["task"],
        "seed": seed,
        "init_mode": a.init_mode,
        "capture": {
            "max_steps": max_steps,
            "camera_width": a.camera_width,
            "camera_height": a.camera_height,
            "videos": not a.no_videos,
        },
        "status": "in_progress",
        "created_at": now(),
        "robouse": {"task": t["task"], "episode_max_steps": int(t["max_steps"]), "practice": True},
    }
    write_json(root / "run.json", run_json)
    program_path = Path(a.program)
    source = program_path.read_text()
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "source" / "program.py").write_text(source)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    rec = Recorder(root)
    execution: programs.Execution | None = None
    verdict: dict = {}
    rejected = False
    error: dict | None = None
    episode = None
    timing: dict[str, dict] = {}

    def charge(bucket: str, since: float) -> None:
        b = timing.setdefault(bucket, {"seconds": 0.0, "calls": 0})
        b["seconds"] = round(b["seconds"] + time.time() - since, 3)
        b["calls"] += 1

    try:
        programs.validate(source)
    except programs.ProgramRejected as e:
        rejected = True
        error = {"type": "ProgramRejected", "message": str(e)}
    if not rejected:
        ts = time.time()
        status, started = programs.http_json(f"{base}/episodes", {"seed": seed, "label": root.name}, timeout=7200)
        charge("setup", ts)
        if status != 200:
            rec.close()
            msg = str(started.get("error") or f"practice broker answered HTTP {status}")
            print(f"cap-harness: no practice episode for seed {seed}: {msg}", file=sys.stderr, flush=True)
            shutil.rmtree(root, ignore_errors=True)  # nothing ran: no artifact, as cap-harness leaves none
            return 3
        episode = str(started["id"])
        run_json["robouse"].update(episode=episode, scene=started.get("scene"))
        write_json(root / "run.json", run_json)
        send = programs.practice_transport(base, episode)
        api_box: list = []
        after = None if a.no_keyframes else keyframe_saver(base, episode, rec, api_box, camera)
        api = programs.Api(send, started.get("info") or {}, on_call=rec.span, after_motion=after)
        api_box.append(api)
        if after is not None:
            after("reset")
        ts = time.time()
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, float(t.get("program_timeout_s") or 1800))
        try:
            execution = programs.execute(source, api)
        except ProgramTimeout:
            execution = programs.Execution(False, None, "", {"type": "Timeout", "message": "the program ran too long"})
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
        charge("program", ts)
        if execution.error:
            error = execution.error
        ts = time.time()
        status, done = programs.http_json(
            f"{base}/episodes/{episode}/finish", {"op": "done", "text": f"cap-harness run {root.name}"}, timeout=900
        )
        charge("judge", ts)
        verdict = done.get("verdict") or {}
        if status != 200:
            error = error or {"type": "HarnessError", "message": str(done.get("error"))}
        ts = time.time()
        files = set(done.get("files") or [])
        for name, dest in (
            ("result.json", root / "episode" / "result.json"),
            ("trace.jsonl", root / "episode" / "robo-trace.jsonl"),
            ("physics.jsonl", root / "episode" / "physics.jsonl"),
            ("frames.jsonl", root / "media" / "frames.jsonl"),
        ):
            if name in files:
                fetch(base, episode, name, dest)
        if not a.no_videos and "recording.mp4" in files:
            if fetch(base, episode, "recording.mp4", root / "media" / "videos" / f"{camera}.mp4"):
                write_json(root / "media" / "video-index.json", {camera: {"file": f"videos/{camera}.mp4"}})
        charge("finalize", ts)
    rec.close()
    if execution is not None:
        (root / "logs" / "program.stdout").write_text(execution.stdout)
    (root / "logs" / "program.stderr").write_text("")
    write_json(
        root / "source" / "program-result.json",
        execution.as_dict() if execution else {"ok": False, "result": None, "error": error},
    )
    reason = termination(execution, verdict, rejected)
    task_success = bool(verdict.get("success")) if verdict else False
    program_ok = bool(execution and execution.ok) and reason != "step_limit"
    wall = round(time.time() - t0, 3)
    attributed = round(sum(b["seconds"] for b in timing.values()), 3)
    outcome = {
        "schema_version": 1,
        "program_ok": program_ok,
        "task_success": task_success,
        "protocol_success": None,
        "cumulative_reward": None,
        "termination_reason": reason,
        "steps_executed": int(verdict.get("steps_used") or 0),
        "error": error,
        "wall_duration_s": wall,
        "timing": {
            "wall_s": wall,
            "attributed_s": attributed,
            "unattributed_s": round(wall - attributed, 3),
            "buckets": timing,
        },
        "finalization_errors": [],
        "robouse": {
            "outcome": verdict.get("outcome"),
            "success_mode": verdict.get("success_mode"),
            "steps_used": verdict.get("steps_used"),
            "max_steps": verdict.get("max_steps"),
            "judge": verdict.get("judge_detail"),
        },
    }
    write_json(root / "outcome.json", outcome)
    run_json.update(status="finalized", finalized_at=now())
    write_json(root / "run.json", run_json)
    manifest = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            manifest.append(
                {
                    "path": str(p.relative_to(root)),
                    "size": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
            )
    write_json(root / "manifest.json", {"files": manifest})
    print(f"run: {root}", flush=True)
    print(
        f"program_ok={program_ok} task_success={task_success} protocol_success=None termination_reason={reason}",
        flush=True,
    )
    return 0 if program_ok else 1


def _alarm(signum: int, frame: Any) -> None:
    raise ProgramTimeout()


# ---- run-batch ------------------------------------------------------------------------------------------------------
def run_batch(a: argparse.Namespace, t: dict) -> int:
    seeds = parse_seeds(a.seeds)
    out_root = Path(a.output_root)
    results_jsonl = Path(a.results_jsonl) if a.results_jsonl else out_root / "batch-results.jsonl"
    summary_path = Path(a.summary) if a.summary else out_root / "batch.json"
    log_dir = Path(a.log_dir) if a.log_dir else out_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    results_jsonl.parent.mkdir(parents=True, exist_ok=True)
    passthrough = ["--benchmark", str(a.benchmark), "--suite", str(a.suite), "--task-id", str(a.task_id)]
    passthrough += ["--program", str(a.program), "--output-root", str(a.output_root), "--init-mode", a.init_mode]
    passthrough += ["--camera-width", str(a.camera_width), "--camera-height", str(a.camera_height)]
    if a.max_steps:
        passthrough += ["--max-steps", str(a.max_steps)]
    for flag in ("flat_run_dir", "no_videos", "no_keyframes"):
        if getattr(a, flag):
            passthrough.append("--" + flag.replace("_", "-"))
    results: list[dict] = []

    def one(seed: int) -> dict:
        t0 = time.time()
        log = log_dir / f"seed_{seed:02d}.log"
        with open(log, "w") as f:
            p = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "run", "--seed", str(seed), *passthrough],
                stdout=f,
                stderr=subprocess.STDOUT,
                check=False,
            )
        text = log.read_text(errors="replace")
        run_dir = next((ln[5:].strip() for ln in text.splitlines() if ln.startswith("run: ")), None)
        outcome = {}
        if run_dir and (Path(run_dir) / "outcome.json").is_file():
            outcome = json.loads((Path(run_dir) / "outcome.json").read_text())
        err = None
        if not run_dir:
            lines = [ln for ln in text.splitlines() if ln.strip()]
            err = lines[-1] if lines else f"cap-harness run exited {p.returncode}"
        return {
            "seed": seed,
            "ok": bool(run_dir),
            "run_dir": run_dir,
            "program_ok": outcome.get("program_ok") if outcome else None,
            "task_success": outcome.get("task_success") if outcome else None,
            "termination_reason": outcome.get("termination_reason") if outcome else None,
            "wall_s": round(time.time() - t0, 3),
            "worker_pid": os.getpid(),
            "worker_seed_index": 0,
            "max_rss_mb": 0.0,
            "error": err,
        }

    with cf.ThreadPoolExecutor(max_workers=max(1, int(a.workers))) as ex, open(results_jsonl, "a") as rj:
        for r in ex.map(one, seeds):  # in seed order; the broker queues what it cannot run at once
            results.append(r)
            rj.write(json.dumps(r) + "\n")
            rj.flush()
            if r["ok"]:
                print(
                    f"seed {r['seed']:02d}: task_success={r['task_success']} program_ok={r['program_ok']} {r['wall_s']:.1f}s",
                    flush=True,
                )
            else:
                print(f"seed {r['seed']:02d}: NO ARTIFACT ({r['error']})", flush=True)
    finished = [r for r in results if r["ok"]]
    passes = sum(1 for r in finished if r["task_success"])
    summary = {
        "seeds": len(results),
        "runs": len(finished),
        "missing": [r["seed"] for r in results if not r["ok"]],
        "passes": passes,
        "pass_rate": round(passes / len(results), 6) if results else 0.0,
        "program_errors": [r["seed"] for r in finished if r["program_ok"] is False],
        "seed_wall_s": round(sum(r["wall_s"] for r in results), 3),
        "results": results,
    }
    write_json(summary_path, summary)
    print(f"passed {passes} of {len(results)}; summary: {summary_path}", flush=True)
    return 0 if not summary["missing"] else 1


# ---- command line ---------------------------------------------------------------------------------------------------
def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--benchmark", required=True)
    p.add_argument("--suite", required=True)
    p.add_argument("--task-id", type=int, required=True)
    p.add_argument("--program", type=Path, required=True)
    p.add_argument("--output-root", type=Path, default=Path("outputs"))
    p.add_argument("--flat-run-dir", action="store_true", help="write runs as <output-root>/<seed>/<run-id>")
    p.add_argument("--no-videos", action="store_true", help="do not copy the episode video into the run")
    p.add_argument("--no-keyframes", action="store_true", help="no camera image after each motion call")
    p.add_argument("--max-steps", type=int, default=None, help="recorded; the task's step budget applies")
    p.add_argument("--camera-width", type=int, default=800, help="recorded; images come at the task's size")
    p.add_argument("--camera-height", type=int, default=512, help="recorded; images come at the task's size")
    p.add_argument(
        "--init-mode", choices=("saved", "seeded"), default="saved", help="recorded; the seed picks the scene"
    )
    p.add_argument("--model-trace", type=Path, help="accepted and ignored")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cap-harness", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="run a program on one practice seed and record it")
    _common(r)
    r.add_argument("--seed", type=int, default=None)
    b = sub.add_parser("run-batch", help="run a program on several practice seeds")
    _common(b)
    b.add_argument("--seeds", nargs="+", required=True, metavar="SEED")
    b.add_argument("--workers", type=int, default=1, help="seeds at once (the practice pool caps it)")
    b.add_argument("--recycle-after", type=int, default=10, help="accepted and ignored: every seed is its own process")
    b.add_argument("--log-dir", type=Path)
    b.add_argument("--results-jsonl", type=Path)
    b.add_argument("--summary", type=Path)
    for name in ("doctor", "manifest", "validate"):
        sub.add_parser(name, help=f"not available in Robo Use ({PROFILE})")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    if a.command in ("doctor", "manifest", "validate"):
        print(f"cap-harness {a.command} is not available in Robo Use: see {PROFILE}", file=sys.stderr)
        return 2
    t = trial()
    if why := check_task(a, t):
        print(f"cap-harness: {why}", file=sys.stderr)
        return 2
    if not Path(a.program).is_file():
        print(f"cap-harness: no such program: {a.program}", file=sys.stderr)
        return 2
    if a.command == "run":
        if a.seed is None:
            print(f"cap-harness: run needs --seed (a practice seed: {PROFILE})", file=sys.stderr)
            return 2
        return run_one(a, t, int(a.seed))
    return run_batch(a, t)


if __name__ == "__main__":
    sys.exit(main())
