"""`robouse`: trusted-side commands.

  robouse serve --task DIR --run-dir DIR --socket PATH [--workspace DIR]   run one episode server
  robouse run --task DIR --harness NAME [--model M] --out JOBDIR            run one trial end to end
  robouse run-many --tasks ROOT --harness NAME ... --out JOBDIR            run a set of trials
  robouse tasks ROOT                                                       list tasks
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .tasks import find_tasks, load_task


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="robouse")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve")
    s.add_argument("--task", required=True)
    s.add_argument("--run-dir", required=True)
    s.add_argument("--socket", required=True)
    s.add_argument("--workspace")
    s.add_argument("--seed", type=int)
    s.add_argument("--max-wall-s", type=float, default=1800)
    s.add_argument("--ready-file")

    r = sub.add_parser("run")
    r.add_argument("--task", required=True)
    r.add_argument("--harness", required=True)
    r.add_argument("--model", default="")
    r.add_argument("--out", required=True)
    r.add_argument("--timeout", type=float)
    r.add_argument("--seed", type=int)

    m = sub.add_parser("run-many")
    m.add_argument("--tasks", required=True)
    m.add_argument("--harness", required=True)
    m.add_argument("--model", default="")
    m.add_argument("--out", required=True)
    m.add_argument("--filter", default="")
    m.add_argument("--limit", type=int, default=0)
    m.add_argument("--concurrency", type=int, default=1)
    m.add_argument("--timeout", type=float)

    t = sub.add_parser("tasks")
    t.add_argument("root")

    a = ap.parse_args(argv)
    if a.cmd == "serve":
        from .session import serve

        task = load_task(a.task)
        spec = task.spec
        if a.seed is not None:
            spec["seed"] = a.seed
        res = serve(spec, Path(a.run_dir), a.socket, Path(a.workspace) if a.workspace else None,
                    max_wall_s=a.max_wall_s, ready_file=Path(a.ready_file) if a.ready_file else None)
        print(json.dumps(res))
        return 0
    if a.cmd == "run":
        from .runner import run_trial

        res = run_trial(load_task(a.task), a.harness, a.model, Path(a.out), timeout=a.timeout, seed=a.seed)
        print(json.dumps(res, indent=2))
        return 0
    if a.cmd == "run-many":
        from .runner import run_many

        run_many(Path(a.tasks), a.harness, a.model, Path(a.out), filt=a.filter, limit=a.limit,
                 concurrency=a.concurrency, timeout=a.timeout)
        return 0
    if a.cmd == "tasks":
        for task in find_tasks(a.root):
            print(task.id, task.spec.get("backend"), task.spec.get("env", ""))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
