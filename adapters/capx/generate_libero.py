"""CaP-X's LIBERO-PRO tasks -> robouse tasks (suite "capx-libero"), code as policy with CaP-X's privileged LIBERO API.

LIBERO-PRO tasks whose task files ship in CaP-X's pinned LIBERO-PRO (uynitsuj/LIBERO-PRO 5368540) and that CaP-X's batch
runs use (capx/envs/scripts/run_libero_batch.py): the libero_object_swap tasks that CaP-X's privileged reference code solves
(INCLUDE below), each with LIBERO's first initial state (CaP-X's trial 1). The task text is CaP-X's LIBERO prompt
(env_configs/libero/franka_libero_spatial_0_privileged.yaml) with the task's BDDL language as the goal. The reference
solution is CaP-X's privileged reference code for LIBERO (env_configs/human_oracle_code/libero/
franka_libero_object_swap_7_privileged_oracle.yaml), with the task's object and target in place of the milk and the basket.

Two steps: first, with the CaP-X LIBERO worker's Python (the capx-libero runtime, which has LIBERO-PRO installed), write
the API documentation and the task list; then generate the tasks with the robouse environment's Python:

    $ROBOUSE_CAPX_LIBERO_PYTHON adapters/capx/generate_libero.py --write-docs adapters/capx/libero_docs.json
    python adapters/capx/generate_libero.py [--out tasks/capx-libero]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITES = ("libero_object_swap", "libero_spatial_swap")
# Generated: the tasks CaP-X's privileged LIBERO reference code solves. Its code (written for object_swap task 7, the milk)
# solves 8 of the 10 object_swap tasks with the object's name swapped in; it does not get the ketchup (task 4) or the
# chocolate pudding (task 8) into the basket, and it grasps the spatial_swap bowls at their centre, which fails. CaP-X
# has no reference code for those, so they are left out.
INCLUDE = [f"libero_object_swap:{i}" for i in range(10) if i not in (4, 8)]

PROMPT = """You are controlling a Franka Emika robot with API described below.
Goal: {goal}
You may write python code comments for reasoning but ONLY write the executable Python code and do not write it in code fences.
After this code executes, you will be able to get a new observation of the environment and write new code to complete the task if needed.
The functions (APIs) below are already imported to the environment. If you want to use numpy, you need to import it explicitly."""

# CaP-X's privileged LIBERO reference code (object_swap task 7), with {obj}, {target} and {approach} filled in per task.
# `import viser.transforms as vtf`, which it imports but does not use, is left out (viser is not in the agent image).
REFERENCE = """import numpy as np
open_gripper()
grasp_pos, grasp_quat = sample_grasp_pose("{obj}")
grasp_quat = np.array([0.0, 1.0, 0.0, 0.0])
goto_pose(grasp_pos, grasp_quat, z_approach=0.1)
close_gripper()
goto_pose(grasp_pos+np.array([0.0, 0.0, 0.2]), grasp_quat)

{target}_pos, {target}_quat = get_object_pose("{target}")
{target}_quat = np.array([0.0, 1.0, 0.0, 0.0])
goto_pose({target}_pos, {target}_quat, z_approach={approach})
open_gripper()
"""


def write_docs(out: Path) -> None:
    """In the worker environment: API docs and each task's language, objects and goal."""
    import runpy

    W = runpy.run_path(str(ROOT / "src/robouse/backends/capx/worker.py"))
    from libero import benchmark  # type: ignore[import-not-found]
    from libero.utils import get_libero_path  # type: ignore[import-not-found]

    tasks = {}
    for suite in SUITES:
        s = benchmark.get_benchmark_dict()[suite]()
        for i in range(s.n_tasks):
            t = s.get_task(i)
            bddl = (Path(get_libero_path("bddl_files")) / t.problem_folder / t.bddl_file).read_text()
            goal = re.search(r"\(:goal\s*\(And\s*\((\w+)\s+(\w+)\s+(\w+)\)\)", bddl)
            lang = re.search(r"\(:language\s+(.*?)\)", bddl, re.S)
            tasks[f"{suite}:{i}"] = {
                "suite": suite,
                "index": i,
                "name": t.name,
                "language": (lang.group(1).strip() if lang else t.language),
                "goal": goal.groups() if goal else None,
            }
    w = W["Worker"]()
    w.make("libero:libero_object_swap:0", 1)
    d = w.docs()
    w.close()
    out.write_text(
        json.dumps({"combined_doc": d["combined_doc"], "functions": d["functions"], "tasks": tasks}, indent=1) + "\n"
    )


def generate(docs: dict, out: Path) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "adapters" / "capx"))
    from generate import VERIFY, prompt_text

    from robouse.tasks import write_task

    shim = (ROOT / "src/robouse/backends/capx/capx_api.py").read_text()
    if out.exists():
        shutil.rmtree(out)
    for key, t in docs["tasks"].items():
        if key not in INCLUDE:
            continue
        rel, obj, target = t["goal"]
        obj, target = re.sub(r"_\d+(_.*)?$", "", obj), re.sub(r"_\d+(_.*)?$", "", target)
        short = t["suite"].replace("libero_", "").replace("_", "-")
        tid = f"capx-libero-{short}-{t['index']}"
        goal = t["language"]
        body = f"""# {goal[0].upper() + goal[1:]} (CaP-X LIBERO-PRO, privileged API)

This is a code-as-policy task from CaP-X on LIBERO-PRO ({t['suite']}, task {t['index']}): you control the robot by writing Python code that calls the task's API. The task text and the API documentation below are CaP-X's own.

## Task (CaP-X's prompt)

```text
{prompt_text(PROMPT.format(goal=goal))}
```

**Success:** LIBERO's own check for this task, the goal of its BDDL file: `({rel} {t['goal'][1]} {t['goal'][2]})`. It is judged after you call `robo done` and the robot has held still for about 10 control steps.

## API (CaP-X's documentation)

```text
{docs['combined_doc'].strip()}
```

CaP-X's LIBERO API also has `goto_pose_interactive_cartesian`, which takes a Python function as its target; a function cannot be passed through `robo`, so it is not offered here.

## How you run code here

Each API function is a skill of the robot: `robo skill NAME ARG ...` runs it, with one JSON value per argument (a number, a list for an array, `true`/`false`, a string) or `name=VALUE` for a keyword argument, for example `robo skill goto_pose "[0.5, 0.0, 0.2]" "[0, 1, 0, 0]" z_approach=0.1`. It prints what the function returns and anything it printed. A call that takes more than 40 control steps returns `running: True` after 40 of them; `robo skill capx_continue` goes on with it, 40 steps at a time, until it returns. To write ordinary Python instead, save this module as `capx_api.py` in your working folder and `from capx_api import *`: it defines every API function of the task under CaP-X's name and signature, returns numpy arrays (a tuple when a function returns several values; dictionaries stay dictionaries), and goes on with long calls by itself, and raises `RuntimeError` when a call fails.

```python
{shim.strip()}
```

- You may run code as many times as you like and look at what each call returns and prints; the robot keeps its state between calls. `robo observe` gives the robot's joint positions and gripper opening, and `robo observe --image` saves a picture from the scene camera. The API is the only way to move the robot (`robo act 0` only holds it still for one step).
- Poses are in the robot's base frame, in metres, with quaternions as w, x, y, z. Object names are LIBERO's, lowercase with underscores (`get_all_object_poses()` lists them).
- Python 3 with numpy is installed; install other packages with pip if your code needs them.
- The episode has a budget of **4,000 control steps** (CaP-X's LIBERO horizon); every step an API call takes counts. When it is used up the episode ends.
- Call `robo done` exactly once when finished; `robo give-up "reason"` ends without claiming success.

The scene is LIBERO's first initial state for this task (CaP-X's trial 1).
"""
        meta = {
            "task": {
                "name": f"robouse/{tid}",
                "description": f"{goal[0].upper() + goal[1:]}. LIBERO-PRO, code as policy with CaP-X's privileged API.",
            },
            "metadata": {
                "source_benchmark": "CaP-X (capgym/cap-x, commit 53e9966) on LIBERO-PRO (uynitsuj/LIBERO-PRO, commit 5368540)",
                "source_task": f"{t['suite']} task {t['index']} ({t['name']})",
                "suite": "capx-libero",
                "category": "code-as-policy",
                "difficulty": "medium",
                "tags": ["mujoco", "libero", "libero-pro", "panda", "code-as-policy", "pick-place"],
                "capx": {
                    "tier": "privileged API (the API of CaP-Bench's S1 tier), multi-turn: not one of CaP-Bench's eight tiers",
                    "api": docs["functions"],
                    "initial_state": 0,
                },
            },
            "agent": {"timeout_sec": 1800},
            "verifier": {"timeout_sec": 300},
            "robouse": {
                "id": tid,
                "backend": "capx_libero",
                "env": f"libero:{t['suite']}:{t['index']}",
                "seed": 1,
                "max_steps": 4000,
                "camera": "agentview",
                "cameras": ["agentview"],
                "skills": True,
                "success_mode": "final",
                "frame_every": 8,
            },
        }
        oracle = f"""#!/bin/bash
# Reference solution: CaP-X's privileged LIBERO reference code (env_configs/human_oracle_code/libero/
# franka_libero_object_swap_7_privileged_oracle.yaml at CaP-X 53e9966, MIT) with this task's object ({obj}) and target
# ({target}) in place of the milk and the basket; copied as oracle_code.py and run through capx_api, then `robo done`.
set -euo pipefail
python -m robouse.oracle --backend capx_libero --env "$(dirname "$0")/oracle_code.py"
"""
        write_task(out / tid, meta, body, oracle, VERIFY)
        approach = 0.3 if target == "basket" else 0.1
        (out / tid / "oracle" / "oracle_code.py").write_text(
            REFERENCE.format(obj=obj, target=target, approach=approach)
        )
        print(tid)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-docs", help="in the worker environment: write the docs JSON to this file")
    ap.add_argument("--docs", default=str(ROOT / "adapters/capx/libero_docs.json"))
    ap.add_argument("--out", default=str(ROOT / "tasks" / "capx-libero"))
    a = ap.parse_args()
    if a.write_docs:
        write_docs(Path(a.write_docs))
        return
    generate(json.loads(Path(a.docs).read_text()), Path(a.out))


if __name__ == "__main__":
    main()
