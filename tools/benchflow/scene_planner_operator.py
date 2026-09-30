"""Two roles on one robot: a BenchFlow scene with a planner and an operator sharing one simulator sidecar.

The planner may only look (`robo info`, `robo observe`, images) and writes a plan to /app/plan.md; the operator
carries it out and calls `robo done`. The task's `roles:` block makes the episode server refuse the planner's
step-taking requests (each role's requests carry ROBO_ROLE from its environment), and the server records the role on
every trace line and step. This is a guard rail and an attribution record, not a security boundary: the roles share
a container, so a role could unset its own ROBO_ROLE.

    python tools/benchflow/scene_planner_operator.py --task tasks/arc-style/arc-gravity --agent codex --model gpt-6-astra \
        --jobs runs/scene

The task is copied with a `roles:` block added (the published task folder is not changed). Codex credentials come
from the maintainers' account pool (CODEX_AUTH_JSON), as for `robouse run`; they are never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import yaml

PLANNER = ("You are the PLANNER. You may only look at the robot: `robo info`, `robo observe`, `robo observe --image` "
           "(open the saved image). Do not move the robot and do not call `robo done` (the episode server refuses "
           "those requests from your role). Work out a complete step-by-step plan with concrete coordinates and robo "
           "commands, and write it to /app/plan.md. Then stop.")
OPERATOR = ("You are the OPERATOR. A planner inspected the scene and wrote a plan to /app/plan.md. Read it, re-check "
            "the state with `robo observe`, carry the plan out with `robo`, fix it where reality differs, and call "
            "`robo done` once the task is complete.")


def with_roles(task_dir: Path, out: Path) -> Path:
    dst = out / task_dir.name
    shutil.copytree(task_dir, dst)
    text = (dst / "task.md").read_text()
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm)
    meta["robouse"]["roles"] = {"planner": {"allow": ["info", "status", "observe"]}, "operator": {"allow": "all"}}
    (dst / "task.md").write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, width=10**6) + "---" + body)
    return dst


def main() -> int:
    import benchflow as bf
    from benchflow import RolloutConfig
    from benchflow._types import Role, Scene, Turn

    from robouse.engine.run import _agent_env

    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--agent", default="codex")
    ap.add_argument("--model", default="gpt-6-astra")
    ap.add_argument("--jobs", default="runs/scene")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="robouse-scene-"))
    try:
        task = with_roles(Path(a.task).resolve(), tmp)
        # provider-routed models (e.g. vllm/<model> with BENCHFLOW_PROVIDER_BASE_URL) take their key from the
        # environment; otherwise use the maintainers' pools like `robouse run`
        creds = {} if "/" in a.model else _agent_env(a.agent)
        roles = [Role(name=n, agent=a.agent, model=a.model, env={**creds, "ROBO_ROLE": n}) for n in ("planner", "operator")]
        from robouse.harnesses import PROMPT_PREFIX
        from robouse.tasks import load_task

        goal = PROMPT_PREFIX + load_task(task).instruction.strip()  # explicit turn prompts replace the task prompt
        scene = Scene(name="plan-then-act", roles=roles,
                      turns=[Turn(role="planner", prompt=f"{PLANNER}\n\n{goal}"),
                             Turn(role="operator", prompt=f"{OPERATOR}\n\n{goal}")])
        cfg = RolloutConfig(task_path=task, scenes=[scene], environment="docker", jobs_dir=Path(a.jobs).resolve())
        res = asyncio.run(bf.run(cfg))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"rewards": res.rewards, "error": res.error, "rollout": getattr(res, "rollout_name", None)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
