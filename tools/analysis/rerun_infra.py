"""Rerun trials that failed for infrastructure reasons (not the model's fault).

Reads runs/_audit/audit.json, moves each finished trial with an infra failure into <job>/_infra_failed/ (kept as
evidence), and runs the same task, harness and model again into the same job.

The pair re-run is the one the trial was recorded with (models.canonical: an empty model is the default of its time).
Not re-run, and left in place: a trial whose pair was served by Baseten (a legacy -glm harness name or a baseten/
model; those runs are history and no request goes to Baseten), and a trial whose pair cannot start here (the same
check `robouse run` makes: a missing provider setting or price). Every pair is checked before any trial is moved, and
a trial whose re-run raises is moved back.

  .venv/bin/python tools/analysis/rerun_infra.py [--jobs mw-codex-astra,...] [--concurrency 3] [--dry-run]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import shutil
from pathlib import Path

from robouse.harnesses import models
from robouse.runner import run_trial
from robouse.runner.trial import check_model
from robouse.tasks import load_task

ROOT = Path(__file__).resolve().parents[2]
MOLMO = {"lerobot-eval", "molmoact2-sim-eval"}


def not_rerun(harness: str, model: str) -> tuple[tuple[str, str], str | None]:
    """The recorded (harness, model) pair, and why it is not re-run (None: it is)."""
    h, m = models.canonical(harness, model)
    if harness in models.LEGACY_HARNESSES or models.split(m)[0] == "baseten":
        return (h, m), f"served by Baseten ({harness} {model or '(default)'}): history, not re-run"
    try:
        check_model(h, m)
    except (ValueError, RuntimeError) as e:
        return (h, m), f"cannot start here: {e}"
    return (h, m), None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", default=str(ROOT / "runs" / "_audit" / "audit.json"))
    ap.add_argument("--jobs", default="")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    jobs = set(filter(None, a.jobs.split(",")))
    recs = [
        r
        for r in json.load(open(a.audit))["trials"]
        if r.get("infra_failure")
        and not r.get("running")
        and r.get("harness") not in MOLMO
        and (not jobs or r["job"] in jobs)
    ]
    print(f"{len(recs)} infra-failed trials to rerun")
    todo, skipped = [], []
    for r in recs:  # every pair is checked before anything moves
        src = Path(r["path"])
        cfg = json.loads((src / "config.json").read_text())
        (harness, model), why = not_rerun(cfg["harness"], cfg.get("model") or "")
        if why:
            skipped.append((r, why))
            continue
        todo.append((r["job"], cfg["task_path"], harness, model, src))
        print(f"  {r['job']:<18} {r['trial']}")
    for r, why in skipped:
        print(f"  skip {r['job']:<13} {r['trial']}: {why}")
    print(f"{len(todo)} to rerun, {len(skipped)} skipped")
    if a.dry_run:
        return

    def one(item):
        job, task_path, harness, model, src = item
        dest = src.parent / "_infra_failed" / src.name
        dest.parent.mkdir(exist_ok=True)
        shutil.move(str(src), str(dest))
        try:
            res = run_trial(load_task(task_path), harness, model, src.parent)
        except Exception as e:  # the re-run did not start: the original trial goes back where it was
            shutil.move(str(dest), str(src))
            return job, {"trial": src.name, "error": f"{type(e).__name__}: {e}"}
        with open(src.parent / "run_log.jsonl", "a") as f:
            f.write(json.dumps({**res, "task": load_task(task_path).id, "rerun_of": src.name}) + "\n")
        return job, res

    with cf.ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for job, res in ex.map(one, todo):
            if "error" in res:
                print(f"{job:<18} {res['trial']:<55} not re-run, left in place: {res['error']}", flush=True)
            else:
                print(f"{job:<18} {res['trial']:<55} reward={res['reward']:.0f} {res['outcome']}", flush=True)


if __name__ == "__main__":
    main()
