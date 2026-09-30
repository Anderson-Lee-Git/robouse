"""Rerun trials that failed for infrastructure reasons (not the model's fault).

Reads runs/_audit/audit.json, moves each finished trial with an infra failure into <job>/_infra_failed/ (kept as
evidence), and runs the same task, harness and model again into the same job.

  .venv/bin/python tools/analysis/rerun_infra.py [--jobs mw-codex-astra,...] [--concurrency 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import shutil
from pathlib import Path

from robouse.runner import run_trial
from robouse.tasks import load_task

ROOT = Path(__file__).resolve().parents[2]
MOLMO = {"lerobot-eval", "molmoact2-sim-eval"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", default=str(ROOT / "runs" / "_audit" / "audit.json"))
    ap.add_argument("--jobs", default="")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    jobs = set(filter(None, a.jobs.split(",")))
    recs = [r for r in json.load(open(a.audit))["trials"]
            if r.get("infra_failure") and not r.get("running") and r.get("harness") not in MOLMO
            and (not jobs or r["job"] in jobs)]
    print(f"{len(recs)} infra-failed trials to rerun")
    todo = []
    for r in recs:
        src = Path(r["path"])
        cfg = json.loads((src / "config.json").read_text())
        todo.append((r["job"], cfg["task_path"], cfg["harness"], cfg.get("model") or "", src))
        print(f"  {r['job']:<18} {r['trial']}")
    if a.dry_run:
        return

    def one(item):
        job, task_path, harness, model, src = item
        dest = src.parent / "_infra_failed" / src.name
        dest.parent.mkdir(exist_ok=True)
        shutil.move(str(src), str(dest))
        res = run_trial(load_task(task_path), harness, model, src.parent)
        with open(src.parent / "run_log.jsonl", "a") as f:
            f.write(json.dumps({**res, "task": load_task(task_path).id, "rerun_of": src.name}) + "\n")
        return job, res

    with cf.ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for job, res in ex.map(one, todo):
            print(f"{job:<18} {res['trial']:<55} reward={res['reward']:.0f} {res['outcome']}", flush=True)


if __name__ == "__main__":
    main()
