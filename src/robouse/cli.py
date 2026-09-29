"""`robouse`: trusted-side commands.

  robouse serve --task TASK --run-dir DIR --socket PATH [--workspace DIR]  run one episode server
  robouse run --task TASK --harness NAME [--model M] --out JOBDIR           run one trial end to end
  robouse run-many [--tasks ROOT] --harness NAME ... --out JOBDIR          run a set of trials
  robouse tasks [ROOT] [--path]                                            list tasks
  robouse fetch-assets [--dest DIR] [--robot NAME]                        download robot meshes (MuJoCo Menagerie)
  robouse estop [--clear] [REASON]                                         latch (or clear) the real-robot e-stop
  robouse operator status|answer yes|no|partial|skip [--note T]|say TEXT   the human operator's side of a real-robot run
  robouse hil-check [FIXTURE ...]                                          replay recorded sessions through the safety guard
  robouse robots                                                           real-robot profiles, drivers and fixtures

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
    ap = argparse.ArgumentParser(prog="robouse", description="robo-use: agent as a policy for embodied agents. "
                                 "Runs robot tasks with an agent harness as the policy. https://robouse.ai")
    ap.add_argument("--version", action="version", version=f"robouse {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run one trusted episode server (used by `run`)")
    s.add_argument("--task", required=True, help="task folder or bundled task id")
    s.add_argument("--run-dir", required=True, help="where the episode record is written")
    s.add_argument("--socket", required=True, help="Unix socket path to listen on")
    s.add_argument("--workspace", help="agent workspace (camera images are saved in its observations/)")
    s.add_argument("--seed", type=int, help="override the task's seed")
    s.add_argument("--max-wall-s", type=float, default=1800, help="wall-clock budget in seconds (default 1800)")
    s.add_argument("--ready-file", help="file created once the server is listening")

    r = sub.add_parser("run", help="run one trial end to end")
    r.add_argument("--task", required=True, help="task folder or bundled task id")
    r.add_argument("--harness", required=True, help=HARNESS_HELP)
    r.add_argument("--model", default="", help="model for the harness (default: the harness's default)")
    r.add_argument("--out", required=True, help="job folder; the trial is written to OUT/<task>__<harness>__<id>/")
    r.add_argument("--timeout", type=float, help="agent wall-clock limit in seconds (default: the task's agent.timeout_sec)")
    r.add_argument("--seed", type=int, help="override the task's seed")
    r.add_argument("--rig", help="real-robot rig file (YAML, keyed by robot): runs real tasks on live hardware instead of the mock")

    m = sub.add_parser("run-many", help="run a set of trials")
    m.add_argument("--tasks", help="task root (default: the bundled tasks)")
    m.add_argument("--harness", required=True, help=HARNESS_HELP)
    m.add_argument("--model", default="", help="model for the harness (default: the harness's default)")
    m.add_argument("--out", required=True, help="job folder; one trial folder per task")
    m.add_argument("--filter", default="", help="only task ids containing this substring")
    m.add_argument("--limit", type=int, default=0, help="run at most this many tasks (0: all)")
    m.add_argument("--concurrency", type=int, default=1, help="trials run in parallel (default 1)")
    m.add_argument("--timeout", type=float, help="agent wall-clock limit per trial in seconds (default: each task's)")
    m.add_argument("--task-list", help="file with one task id per line (subset of --tasks)")
    m.add_argument("--resume", action="store_true", help="skip tasks that already have a finished, non-infra-failed trial in --out")
    m.add_argument("--rig", help="real-robot rig file (YAML, keyed by robot): real tasks run on live hardware, one at a time")

    e = sub.add_parser("estop", help="latch the real-robot e-stop (every real episode stops at its next command); --clear releases it")
    e.add_argument("reason", nargs="?", default="operator e-stop")
    e.add_argument("--clear", action="store_true")

    o = sub.add_parser("operator", help="answer a pending operator gate or verdict, or send the policy a remark")
    o.add_argument("action", choices=["status", "answer", "say"])
    o.add_argument("value", nargs="?", default="")
    o.add_argument("--note", default="")

    hc = sub.add_parser("hil-check", help="strict replay of recorded real sessions through the safety guard + tracking-model fit")
    hc.add_argument("fixtures", nargs="*", help="fixture names under assets/hil (default: all)")

    sub.add_parser("robots", help="list real-robot profiles, drivers and hardware-in-the-loop fixtures")

    t = sub.add_parser("tasks", help="list tasks (default: the bundled tasks)")
    t.add_argument("root", nargs="?", help="task root (default: the bundled tasks)")
    t.add_argument("--path", action="store_true", help="print the bundled task directory and exit")

    f = sub.add_parser("fetch-assets", help="download the MuJoCo Menagerie robot models (menagerie, RoboHarm, drone and embodiment suites)")
    f.add_argument("--dest", help="target directory (default: ~/.cache/robouse/menagerie or $ROBOUSE_MENAGERIE_ASSETS)")
    f.add_argument("--robot", action="append", help="only this Menagerie robot folder (repeatable), e.g. unitree_go2")

    a = ap.parse_args(argv)
    if getattr(a, "rig", None):
        os.environ["ROBOUSE_RIG"] = str(Path(a.rig).resolve())
    if a.cmd in ("estop", "operator", "hil-check", "robots"):
        return _real_cmd(a)
    if a.cmd == "fetch-assets":
        from .assets import fetch

        fetch(Path(a.dest) if a.dest else None, robots=a.robot)
        return 0
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

        res = run_trial(load_task(resolve_task_path(a.task)), a.harness, a.model, Path(a.out), timeout=a.timeout, seed=a.seed)
        print(json.dumps(res, indent=2))
        return 0
    if a.cmd == "run-many":
        from .runner import run_many

        ids = [l.strip() for l in open(a.task_list) if l.strip() and not l.startswith("#")] if a.task_list else None
        run_many(Path(a.tasks) if a.tasks else bundled_tasks_root(), a.harness, a.model, Path(a.out), filt=a.filter, limit=a.limit,
                 concurrency=1 if a.rig else a.concurrency, timeout=a.timeout, ids=ids, resume=a.resume)
        return 0
    if a.cmd == "tasks":
        if a.path:
            print(bundled_tasks_root())
            return 0
        try:
            for task in find_tasks(a.root or bundled_tasks_root()):
                print(task.id, task.spec.get("backend"), task.spec.get("env", ""))
            sys.stdout.flush()
        except BrokenPipeError:  # e.g. `robouse tasks | head`
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    return 2


def _real_cmd(a) -> int:
    from .real import safety

    if a.cmd == "estop":
        if a.clear:
            print("e-stop cleared" if safety.clear_estop() else "e-stop was not engaged")
        else:
            print(f"e-stop latched: {safety.set_estop(a.reason)}")
        return 0
    if a.cmd == "operator":
        from .real import operator

        if a.action == "status":
            p = safety.OPERATOR_DIR / "pending.json"
            print(p.read_text() if p.exists() else "no pending operator request")
            print("e-stop:", safety.estop_engaged() or "clear")
        elif a.action == "answer":
            print(operator.answer(a.value, a.note))
        else:
            print(f"remark queued for the policy: {operator.say(a.value)}")
        return 0
    if a.cmd == "hil-check":
        from .real.replay import HIL_DIR, Fixture, conformance
        from .real.robots import profile

        names = a.fixtures or sorted(p.name for p in HIL_DIR.iterdir() if (p / "fixture.json").exists())
        for n in names:
            fx = Fixture(n)
            if len(fx.steps) < 2:
                print(json.dumps({"fixture": n, "robot": fx.robot, "steps": len(fx.steps), "note": fx.meta.get("note", "")}))
                continue
            print(json.dumps(conformance(fx, profile(fx.robot), fx.meta.get("session_envelope"))))
        return 0
    from .real.replay import HIL_DIR
    from .real.robots import PROFILES

    for name, p in PROFILES.items():
        print(f"{name:7} {p.display}: {len(p.joints)} joints, {p.control_hz:g} Hz, kinematics {'yes' if p.chain_file else 'joint limits only'}, "
              f"{'tested on hardware' if p.tested_on_hardware else 'UNTESTED on hardware'}")
    print("drivers: mock (hardware-in-the-loop replay), lerobot (Metal, SO-100/SO-101), piper (piper_sdk), robouse.drivers entry points")
    for f in sorted(HIL_DIR.glob("*/fixture.json")):
        d = json.loads(f.read_text())
        print(f"fixture {f.parent.name}: {d['robot']}, {len(d.get('steps', []))} recorded steps, {len(d.get('keyframes', []))} keyframes, "
              f"cameras {d.get('cameras')}, source {d.get('source')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
