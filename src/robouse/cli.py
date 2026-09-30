"""`robouse`: trusted-side commands.

  robouse run --task TASK --agent NAME [--model M] --out JOBS         run one trial (a BenchFlow job)
  robouse run-many [--tasks ROOT] --agent NAME ... --out JOBS         run a set of trials (one BenchFlow job)
  robouse export --tasks ROOT... --out DIR [--noop]                   write native BenchFlow task packages
  robouse serve --task TASK --run-dir DIR --socket PATH               run one episode server (the simulator)
  robouse tasks [list] [ROOT] [--path]                                list tasks
  robouse tasks init --embodiment E --scene S --task T [...] --out DIR  compose a task from components (validated)
  robouse tasks init DIR | --grid ... | --from DIR                    scaffold a blank task, compose a grid, regenerate
  robouse tasks check DIR                                             schema, bench tasks check, reference 1, no-op 0
  robouse fetch-assets [--dest DIR] [--robot NAME]                    download robot meshes (MuJoCo Menagerie)
  robouse components list|show ID|check E S T                         the component registry

`run` and `run-many` run on BenchFlow (`--engine benchflow`, the default): BenchFlow's agents, sandboxes, verifier
and trial layout; the same as `bench eval run --tasks-dir <tasks> --agent NAME --sandbox docker`. `--engine local`
is the older in-process runner (host processes under a macOS Seatbelt profile, no Docker), kept for machines
without Docker and for the local-only harnesses (claude-code-glm, codex-glm, mini-swe-agent-glm, molmoact2).

TASK is a task folder or the id of a bundled task (e.g. `arc-gravity`); ROOT defaults to the bundled tasks.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .tasks import bundled_tasks_root, find_tasks, load_task, resolve_task_path

HARNESS_HELP = ("oracle, noop, claude-code, codex, claude-code-glm, codex-glm, mini-swe-agent-glm or molmoact2 "
                "(see https://robouse.ai/docs/harnesses/)")
SIM_HINT = ("robouse: the simulator dependencies are not installed ({err}).\n"
            "Install the extra for this suite, e.g. `pip install 'robouse[sim]'` (MuJoCo tabletop suites), "
            "`robouse[metaworld]`, `robouse[gymrobotics]`, `robouse[robosuite]` or `robouse[all]`.")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("tasks", "components", "remix"):  # these parse their own arguments (subcommands and --help)
        from . import tasks_cli

        return {"tasks": tasks_cli.tasks_main, "components": tasks_cli.components_main,
                "remix": tasks_cli.remix_alias}[args[0]](args[1:])
    ap = argparse.ArgumentParser(prog="robouse", description="Robo Use: agent as a policy for embodied agents. "
                                 "Runs robot tasks with an agent harness as the policy. https://robouse.ai")
    ap.add_argument("--version", action="version", version=f"robouse {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{serve,run,run-many,export,tasks,components,fetch-assets}")

    s = sub.add_parser("serve", help="run one trusted episode server (used by `run`)")
    s.add_argument("--task", required=True, help="task folder or bundled task id")
    s.add_argument("--run-dir", required=True, help="where the episode record is written")
    s.add_argument("--socket", required=True, help="Unix socket path to listen on")
    s.add_argument("--workspace", help="agent workspace (camera images are saved in its observations/)")
    s.add_argument("--seed", type=int, help="override the task's seed")
    s.add_argument("--max-wall-s", type=float, default=1800, help="wall-clock budget in seconds (default 1800)")
    s.add_argument("--ready-file", help="file created once the server is listening")

    def run_opts(p, many: bool):
        p.add_argument("--agent", "--harness", dest="agent", required=True,
                       help="BenchFlow agent (oracle, noop, claude, codex, ... see `bench agent list`; claude-code is "
                            "an alias for claude); with --engine local, a robouse harness: " + HARNESS_HELP)
        p.add_argument("--model", default="", help="model for the agent (default: the agent's default)")
        p.add_argument("--out", required=True,
                       help="jobs folder; the BenchFlow job is written to OUT/<job>/<task>__<id>/ "
                            "(--engine local: OUT/<task>__<harness>__<id>/)")
        p.add_argument("--timeout", type=float, help="agent wall-clock limit in seconds (default: "
                       + ("each task's" if many else "the task's agent.timeout_sec") + ")")
        p.add_argument("--seed", type=int, help="override the task's seed")
        p.add_argument("--seeds", help="seeded rollouts (BenchFlow engine): one trial per task and seed, e.g. 0-4 or "
                       "0,3,7; summary.json gets pass@k, mean and std per task")
        p.add_argument("--engine", choices=("benchflow", "local"), default="benchflow",
                       help="benchflow (default): BenchFlow with Docker; local: host processes, macOS Seatbelt "
                            "sandbox, no Docker")
        p.add_argument("--sandbox", default="docker", help="BenchFlow sandbox (default docker)")
        p.add_argument("--reasoning-effort", help="agent reasoning effort (BenchFlow agents that expose one)")
        p.add_argument("--job-name", help="BenchFlow job name (default: a timestamp)")

    r = sub.add_parser("run", help="run one trial end to end")
    r.add_argument("--task", required=True, help="task folder or bundled task id")
    run_opts(r, many=False)

    m = sub.add_parser("run-many", help="run a set of trials")
    m.add_argument("--tasks", help="task root (default: the bundled tasks)")
    run_opts(m, many=True)
    m.add_argument("--filter", default="", help="only task ids containing this substring")
    m.add_argument("--limit", type=int, default=0, help="run at most this many tasks (0: all)")
    m.add_argument("--concurrency", type=int, default=1, help="trials run in parallel (default 1)")
    m.add_argument("--task-list", help="file with one task id per line (subset of --tasks)")
    m.add_argument("--resume", action="store_true", help="(--engine local) skip tasks that already have a finished, non-infra-failed trial in --out")

    e = sub.add_parser("export", help="write robouse tasks as native BenchFlow task packages (a movable bundle)")
    e.add_argument("--tasks", required=True, nargs="+", help="task folders, suite folders or a task root")
    e.add_argument("--out", required=True, help="bundle directory: <out>/tasks/<id>/ and <out>/runtime-<hash>/")
    e.add_argument("--filter", default="", help="comma-separated substrings; keep tasks whose id matches one")
    e.add_argument("--noop", action="store_true", help="noop oracle (negative control: must score 0)")

    t = sub.add_parser("tasks", help="list, compose (init), scaffold and check tasks; `robouse tasks --help`", add_help=False)
    t.add_argument("rest", nargs=argparse.REMAINDER)
    f = sub.add_parser("fetch-assets", help="download the MuJoCo Menagerie robot models (Menagerie-based suites and composed tasks)")
    f.add_argument("--dest", help="target directory (default: ~/.cache/robouse/menagerie or $ROBOUSE_MENAGERIE_ASSETS)")
    f.add_argument("--robot", action="append", help="only this Menagerie robot folder (repeatable), e.g. unitree_go2")

    c = sub.add_parser("components", help="list, show and check components; `robouse components --help`", add_help=False)
    c.add_argument("rest", nargs=argparse.REMAINDER)
    x = sub.add_parser("remix", add_help=False)  # renamed to `tasks init`; hidden alias for one release
    x.add_argument("rest", nargs=argparse.REMAINDER)

    a = ap.parse_args(argv)
    if a.cmd in ("tasks", "components", "remix"):
        from . import tasks_cli

        return {"tasks": tasks_cli.tasks_main, "components": tasks_cli.components_main, "remix": tasks_cli.remix_alias}[a.cmd](a.rest)
    if a.cmd == "fetch-assets":
        from .assets import fetch

        fetch(Path(a.dest) if a.dest else None, robots=a.robot)
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
        from benchflow.embodied.rollouts import parse_seeds

        from .engine.run import run_job, select_tasks

        seeds = parse_seeds(a.seeds) if a.seeds else None
        if seeds and a.seed is not None:
            print("robouse: use --seed or --seeds, not both", file=sys.stderr)
            return 2

        if a.cmd == "run":
            tasks = [load_task(resolve_task_path(a.task))]
        else:
            ids = [l.strip() for l in open(a.task_list) if l.strip() and not l.startswith("#")] if a.task_list else None
            tasks = select_tasks(Path(a.tasks) if a.tasks else bundled_tasks_root(), a.filter, ids, a.limit)
        res = run_job(tasks, a.agent, a.model, Path(a.out), sandbox=a.sandbox,
                      concurrency=getattr(a, "concurrency", 1), timeout=a.timeout, seed=a.seed,
                      job_name=a.job_name, reasoning_effort=a.reasoning_effort, seeds=seeds)
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
    if getattr(a, "seeds", None):
        print("robouse: --seeds needs the BenchFlow engine (drop --engine local, or use --seed)", file=sys.stderr)
        return 2
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
    return 2


if __name__ == "__main__":
    sys.exit(main())
