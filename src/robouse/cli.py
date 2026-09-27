"""`robouse`: trusted-side commands.

  robouse run --task TASK --agent NAME [--model M] --out JOBS         run one trial (a BenchFlow job)
  robouse run-many [--tasks ROOT] --agent NAME ... --out JOBS         run a set of trials (one BenchFlow job)
  robouse export --tasks ROOT... --out DIR [--noop]                   write native BenchFlow task packages
  robouse serve --task TASK --run-dir DIR --socket PATH               run one episode server (the simulator)
  robouse tasks [ROOT] [--path]                                       list tasks
  robouse fetch-assets [--dest DIR]                                   download robot meshes (menagerie, RoboHarm, drone)

`run` and `run-many` run on BenchFlow (`--engine benchflow`, the default): BenchFlow's agents, sandboxes, verifier
and trial layout; the same as `bench eval run --tasks-dir <tasks> --agent NAME --sandbox docker`. `--engine local`
is the older in-process runner (host processes under a macOS Seatbelt profile, no Docker), kept for machines
without Docker and for the local-only harnesses (claude-code-glm, codex-glm, mini-swe-agent-glm, molmoact2).

TASK is a task folder or the id of a bundled task (e.g. `arc-gravity`); ROOT defaults to the bundled tasks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .tasks import bundled_tasks_root, find_tasks, load_task, resolve_task_path

SIM_HINT = ("robouse: the simulator dependencies are not installed ({err}).\n"
            "Install the extra for this suite, e.g. `pip install 'robouse[sim]'` (MuJoCo tabletop suites), "
            "`robouse[metaworld]`, `robouse[gymrobotics]`, `robouse[robosuite]` or `robouse[all]`.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="robouse", description="robo-use: agent as a policy for embodied agents. "
                                 "Runs robot tasks with an agent harness as the policy. https://robouse.ai")
    ap.add_argument("--version", action="version", version=f"robouse {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run one trusted episode server (used by `run`)")
    s.add_argument("--task", required=True)
    s.add_argument("--run-dir", required=True)
    s.add_argument("--socket", required=True)
    s.add_argument("--workspace")
    s.add_argument("--seed", type=int)
    s.add_argument("--max-wall-s", type=float, default=1800)
    s.add_argument("--ready-file")

    def run_opts(p):
        p.add_argument("--agent", "--harness", dest="agent", required=True,
                       help="BenchFlow agent (oracle, noop, claude, codex, ... see `bench agent list`); "
                            "with --engine local a robouse harness")
        p.add_argument("--model", default="")
        p.add_argument("--out", required=True, help="jobs directory")
        p.add_argument("--timeout", type=float, help="agent timeout in seconds (default: the task's)")
        p.add_argument("--engine", choices=("benchflow", "local"), default="benchflow")
        p.add_argument("--sandbox", default="docker", help="BenchFlow sandbox (default docker)")
        p.add_argument("--reasoning-effort", help="agent reasoning effort (BenchFlow agents that expose one)")
        p.add_argument("--job-name", help="BenchFlow job name (default: a timestamp)")

    r = sub.add_parser("run", help="run one trial end to end")
    r.add_argument("--task", required=True)
    run_opts(r)
    r.add_argument("--seed", type=int)

    m = sub.add_parser("run-many", help="run a set of trials")
    m.add_argument("--tasks", help="task root (default: the bundled tasks)")
    run_opts(m)
    m.add_argument("--filter", default="")
    m.add_argument("--limit", type=int, default=0)
    m.add_argument("--concurrency", type=int, default=1)
    m.add_argument("--seed", type=int)
    m.add_argument("--task-list", help="file with one task id per line (subset of --tasks)")
    m.add_argument("--resume", action="store_true", help="(--engine local) skip tasks that already have a finished, non-infra-failed trial in --out")

    e = sub.add_parser("export", help="write robouse tasks as native BenchFlow task packages (a movable bundle)")
    e.add_argument("--tasks", required=True, nargs="+", help="task folders, suite folders or a task root")
    e.add_argument("--out", required=True, help="bundle directory: <out>/tasks/<id>/ and <out>/runtime-<hash>/")
    e.add_argument("--filter", default="", help="comma-separated substrings; keep tasks whose id matches one")
    e.add_argument("--noop", action="store_true", help="noop oracle (negative control: must score 0)")

    t = sub.add_parser("tasks", help="list tasks (default: the bundled tasks)")
    t.add_argument("root", nargs="?", help="task root (default: the bundled tasks)")
    t.add_argument("--path", action="store_true", help="print the bundled task directory and exit")

    f = sub.add_parser("fetch-assets", help="download the MuJoCo Menagerie meshes used by the menagerie, RoboHarm and drone suites")
    f.add_argument("--dest", help="target directory (default: ~/.cache/robouse/menagerie or $ROBOUSE_MENAGERIE_ASSETS)")

    a = ap.parse_args(argv)
    if a.cmd == "fetch-assets":
        from .assets import fetch

        fetch(Path(a.dest) if a.dest else None)
        return 0
    if a.cmd == "export":
        from .engine.format import materialize

        keys = [k for k in a.filter.split(",") if k]
        n = 0
        for root in a.tasks:
            for t in find_tasks(root):
                if keys and not any(k in t.id for k in keys):
                    continue
                print("exported", materialize(t.path, Path(a.out), noop=a.noop, flat=True))
                n += 1
        print(f"{n} task(s) -> {Path(a.out).resolve()}   run: bench eval run --tasks-dir {Path(a.out) / 'tasks'} --agent oracle --sandbox docker")
        return 0 if n else 1
    if a.cmd in ("run", "run-many") and a.engine == "benchflow":
        from .engine.run import run_job, select_tasks

        if a.cmd == "run":
            tasks = [load_task(resolve_task_path(a.task))]
        else:
            ids = [l.strip() for l in open(a.task_list) if l.strip() and not l.startswith("#")] if a.task_list else None
            tasks = select_tasks(Path(a.tasks) if a.tasks else bundled_tasks_root(), a.filter, ids, a.limit)
        res = run_job(tasks, a.agent, a.model, Path(a.out), sandbox=a.sandbox,
                      concurrency=getattr(a, "concurrency", 1), timeout=a.timeout, seed=a.seed,
                      job_name=a.job_name, reasoning_effort=a.reasoning_effort)
        return 0 if res["errored"] == 0 else 1
    if a.cmd in ("serve", "run", "run-many"):
        import importlib.util

        missing = [m for m in ("mujoco", "imageio", "PIL") if importlib.util.find_spec(m) is None]
        if missing:
            print(SIM_HINT.format(err="missing: " + ", ".join(missing)), file=sys.stderr)
            return 1
    if a.cmd == "serve":
        from .session import serve

        task = load_task(resolve_task_path(a.task))
        spec = task.spec
        if a.seed is not None:
            spec["seed"] = a.seed
        res = serve(spec, Path(a.run_dir), a.socket, Path(a.workspace) if a.workspace else None,
                    max_wall_s=a.max_wall_s, ready_file=Path(a.ready_file) if a.ready_file else None)
        print(json.dumps(res))
        return 0
    if a.cmd == "run":
        from .runner import run_trial

        res = run_trial(load_task(resolve_task_path(a.task)), a.agent, a.model, Path(a.out), timeout=a.timeout, seed=a.seed)
        print(json.dumps(res, indent=2))
        return 0
    if a.cmd == "run-many":
        from .runner import run_many

        ids = [l.strip() for l in open(a.task_list) if l.strip() and not l.startswith("#")] if a.task_list else None
        run_many(Path(a.tasks) if a.tasks else bundled_tasks_root(), a.agent, a.model, Path(a.out), filt=a.filter, limit=a.limit,
                 concurrency=a.concurrency, timeout=a.timeout, ids=ids, resume=a.resume, seed=a.seed)
        return 0
    if a.cmd == "tasks":
        if a.path:
            print(bundled_tasks_root())
            return 0
        for task in find_tasks(a.root or bundled_tasks_root()):
            print(task.id, task.spec.get("backend"), task.spec.get("env", ""))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
