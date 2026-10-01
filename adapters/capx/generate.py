"""CaP-X (NVIDIA, UC Berkeley, Stanford, CMU; MIT; https://github.com/capgym/cap-x) -> robouse tasks (suite "capx").

CaP-Bench's seven RoboSuite tasks with CaP-X's privileged API, as code-as-policy tasks: the agent writes Python that
calls CaP-X's API (through capx_api.py, which the instruction gives it). The task text is CaP-X's own prompt for the
task, and the API documentation is CaP-X's own (adapters/capx/api_docs.json, written by api_docs.py from the vendored
CaP-X code). Reference solutions are CaP-X's own reference code (ORACLE_CODE of each task class). Each task is one
fixed layout (`seed`); CaP-X samples a new layout per trial.

Usage: python adapters/capx/generate.py --capx PATH/TO/cap-x [--out tasks/capx] [--seeds 1-5]
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
from pathlib import Path

from robouse.backends.capx.backend import TASKS
from robouse.tasks import write_task

ROOT = Path(__file__).resolve().parents[2]
CAPX_COMMIT = "53e9966d7a8e2fa7494676772bccc35280f5c0ed"
SOURCE = "CaP-X (capgym/cap-x, commit 53e9966)"

# task -> (CaP-X task module, title, description, tags)
META = {
    "cube_lifting": ("franka_lift.py", "Lift the cube", "Pick up the red cube and lift it.", ["lift", "single-arm"]),
    "cube_stack": (
        "franka_pick_place.py",
        "Stack the cubes",
        "Stack the red cube on the green cube and release it.",
        ["stack", "single-arm"],
    ),
    "cube_restack": (
        "franka_cube_restack.py",
        "Restack the cubes",
        "The green cube starts on the red cube: put the red cube on top of the green cube instead.",
        ["stack", "single-arm", "long-horizon"],
    ),
    "spill_wipe": (
        "franka_spill_wipe.py",
        "Wipe the spill",
        "Wipe up a brown spill on the table with a sponge on the gripper.",
        ["wipe", "single-arm", "contact-rich"],
    ),
    "nut_assembly": (
        "franka_nut_assembly.py",
        "Nut on the peg",
        "Grasp the square nut by its handle and put it onto the square peg.",
        ["assembly", "single-arm", "precision"],
    ),
    "two_arm_lift": (
        "two_arm_lift.py",
        "Lift the pot with two arms",
        "Two Franka arms on opposite sides of the table grasp a pot's two handles and lift it together.",
        ["bimanual", "lift"],
    ),
    "two_arm_handover": (
        "two_arm_handover.py",
        "Hand over the hammer",
        "One Franka arm picks up a hammer and hands it to the other.",
        ["bimanual", "handover"],
    ),
}

SUCCESS = {
    "cube_lifting": "the cube is more than 4 cm above the table.",
    "cube_stack": "the red cube rests on the green cube, lifted more than 4 cm above the table, and is no longer grasped.",
    "cube_restack": "the red cube rests on the green cube and is no longer grasped, and the two cubes are not both lifted "
    "more than 4 cm above the table.",
    "spill_wipe": "every dirt marker of the spill has been wiped.",
    "nut_assembly": "the square nut is on the square peg and the gripper has moved away from it.",
    "two_arm_lift": "the pot's bottom is more than 10 cm above the table.",
    "two_arm_handover": "the second arm holds the hammer by its handle, the first arm holds nothing, and the hammer is more "
    "than 10 cm above the table.",
}

# Lines of CaP-X's prompts about its own single-turn code submission (the agent here runs code in a shell instead).
DROP = (
    "ONLY write the executable Python code",
    "Write ONLY executable Python code",
    "functions (APIs) below are already imported",
    "functions (APIs) above are already imported",
)

# Changes to CaP-X's reference code where it does not solve the task as written (each is stated in the task's oracle).
ORACLE_FIXES = {
    # CaP-X's code wipes at z = 0 (its prompt says the table is at z = 0 in the base frame), but with the wiping
    # gripper's shorter reach that keeps the sponge about 8 cm above the table in CaP-X's own environment, so nothing is
    # wiped; the sponge reaches the table at z = -0.10.
    "spill_wipe": (("z_wipe = 0.0", "z_wipe = -0.10  # Robo Use: the sponge reaches the table at z = -0.10 (CaP-X's code: 0.0)"),),
}

VERIFY = """\
#!/bin/bash
# Verifier: the episode server already judged success with CaP-X's task_completed(); copy its verdict.
# ROBOUSE_EPISODE_DIR points at the trusted episode directory (result.json written by `robouse serve`).
set -euo pipefail
OUT="${ROBOUSE_VERIFIER_DIR:-/logs/verifier}"
mkdir -p "$OUT"
python3 - "$ROBOUSE_EPISODE_DIR/result.json" "$OUT/reward.txt" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
open(sys.argv[2], "w").write("1" if r.get("success") else "0")
print("success" if r.get("success") else "fail", r.get("outcome"))
EOF
"""

ORACLE = """\
#!/bin/bash
# Reference solution: CaP-X's own reference code for this task (ORACLE_CODE, or PRIVILEGED_ORACLE_CODE, of capx/envs/tasks/franka/{module} at CaP-X
# 53e9966, MIT; copied as oracle_code.py), run against the API through capx_api like an agent's code, then `robo done`.{note}
set -euo pipefail
python -m robouse.oracle --backend capx --env "$(dirname "$0")/oracle_code.py"
"""


def upstream_strings(path: Path) -> dict:
    tree = ast.parse(path.read_text())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("PROMPT", "ORACLE_CODE", "PRIVILEGED_ORACLE_CODE"):
                if isinstance(node.value, ast.Constant):
                    out[node.targets[0].id] = node.value.value
    # the privileged API's reference code where the task has one for each API (two_arm_handover)
    out["ORACLE_CODE"] = out.pop("PRIVILEGED_ORACLE_CODE", None) or out["ORACLE_CODE"]
    return out


def prompt_text(prompt: str) -> str:
    lines = [ln for ln in prompt.strip().splitlines() if not any(d in ln for d in DROP)]
    return "\n".join(lines).strip()


def instruction(task: str, prompt: str, api_doc: str, max_steps: int, seed: int) -> str:
    shim = (ROOT / "src/robouse/backends/capx/capx_api.py").read_text()
    return f"""# {META[task][1]} (CaP-X, privileged API)

This is a code-as-policy task from CaP-X: you control the robot by writing Python code that calls the task's API. The task text and the API documentation below are CaP-X's own.

## Task (CaP-X's prompt)

```text
{prompt}
```

**Success:** CaP-X's own check for this task: {SUCCESS[task]} It is judged after you call `robo done` and the robot has held still for about 10 control steps.

## API (CaP-X's documentation)

```text
{api_doc.strip()}
```

## How you run code here

Each API function is a skill of the robot: `robo skill NAME ARG ...` runs it, with one JSON value per argument (a number, a list for an array, `true`/`false`, a string) or `name=VALUE` for a keyword argument, for example `robo skill goto_pose "[0.5, 0.0, 0.2]" "[0, 0, 1, 0]" z_approach=0.1`. It prints what the function returns and anything it printed. To write ordinary Python instead, save this module as `capx_api.py` in your working folder and `from capx_api import *`: it defines every API function of the task under CaP-X's name and signature, returns numpy arrays (a tuple when a function returns several values), and raises `RuntimeError` when a call fails.

```python
{shim.strip()}
```

- You may run code as many times as you like and look at what each call returns and prints; the robot keeps its state between calls. `robo observe` gives the robot's joint positions and gripper opening, and `robo observe --image` saves a picture from the scene camera. The API is the only way to move the robot (`robo act 0` only holds it still for one step).
- Poses are in the robot's base frame, in metres, with quaternions as w, x, y, z, as the API documentation says.
- Python 3 with numpy is installed; install other packages with pip if your code needs them.
- The episode has a budget of **{max_steps:,} control steps** (CaP-X's horizon for this task); every step an API call takes counts. When it is used up the episode ends.
- Call `robo done` exactly once when finished; `robo give-up "reason"` ends without claiming success.

This task is one fixed scene layout (seed {seed}); CaP-X samples a new layout for every trial.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capx", required=True, help=f"a CaP-X checkout at commit {CAPX_COMMIT[:7]}")
    ap.add_argument("--out", default=str(ROOT / "tasks" / "capx"))
    ap.add_argument("--seeds", default="1-5")
    a = ap.parse_args()
    lo, _, hi = a.seeds.partition("-")
    seeds = range(int(lo), int(hi or lo) + 1)
    docs = json.loads((ROOT / "adapters/capx/api_docs.json").read_text())
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for task, (module, title, desc, tags) in META.items():
        up = upstream_strings(Path(a.capx) / "capx/envs/tasks/franka" / module)
        t = TASKS[task]
        for seed in seeds:
            tid = f"capx-{task.replace('_', '-')}-s{seed}"
            meta = {
                "task": {"name": f"robouse/{tid}", "description": f"{desc} Code as policy with CaP-X's privileged API."},
                "metadata": {
                    "source_benchmark": SOURCE,
                    "source_task": f"{task} (capx/envs/tasks/franka/{module})",
                    "suite": "capx",
                    "category": "code-as-policy",
                    "difficulty": "medium",
                    "tags": ["mujoco", "robosuite", "panda", "code-as-policy", *tags],
                    "capx": {
                        "tier": "privileged API (the API of CaP-Bench's S1 tier), multi-turn: not one of CaP-Bench's eight tiers",
                        "api": docs[task]["functions"],
                        "layout_seed": seed,
                    },
                },
                "agent": {"timeout_sec": 1800},
                "verifier": {"timeout_sec": 300},
                "robouse": {
                    "id": tid,
                    "backend": "capx",
                    "env": task,
                    "seed": seed,
                    "max_steps": t["max_steps"],
                    "camera": t["camera"],
                    "cameras": [t["camera"]],
                    "skills": True,
                    "success_mode": "final",
                    "frame_every": 4,
                },
            }
            body = instruction(task, prompt_text(up["PROMPT"]), docs[task]["combined_doc"], t["max_steps"], seed)
            note = (
                "\n# Changed from CaP-X's code: it wipes at z = -0.10 instead of 0.0 (at 0.0 the sponge stays above the table)."
                if task in ORACLE_FIXES
                else ""
            )
            write_task(out / tid, meta, body, ORACLE.format(module=module, note=note), VERIFY)
            code = up["ORACLE_CODE"].strip() + "\n"
            for old, new in ORACLE_FIXES.get(task, ()):
                if old not in code:
                    raise SystemExit(f"{task}: reference code no longer contains {old!r}")
                code = code.replace(old, new)
            (out / tid / "oracle" / "oracle_code.py").write_text(code)
            print(tid)


if __name__ == "__main__":
    main()
