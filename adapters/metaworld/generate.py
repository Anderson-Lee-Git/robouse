"""Meta-World (Farama, v3) -> robouse tasks.

One task per MT50 environment. Seed 0 picks the first of Meta-World's sampled goal/object layouts.
The reference solution is Meta-World's own scripted expert, run through the `robo` socket interface.

Usage: python adapters/metaworld/generate.py --out tasks/metaworld
"""
from __future__ import annotations

import argparse
import shutil
import textwrap
from pathlib import Path

from robouse.core.prompts import ROBO_USAGE
from robouse.tasks import to_native

# What each environment asks for, and what obj1/goal mean in its observation.
GOALS: dict[str, tuple[str, str]] = {
    "assembly-v3": ("Pick up the round nut by its handle and place it over the peg.", "obj1 = nut handle; goal = peg top"),
    "basketball-v3": ("Pick up the ball and dunk it into the basketball hoop.", "obj1 = ball; goal = hoop"),
    "bin-picking-v3": ("Pick the cube out of the left bin and place it in the right bin.", "obj1 = cube; goal = target in the right bin"),
    "box-close-v3": ("Pick up the box lid and place it on top of the box.", "obj1 = lid handle; goal = box top"),
    "button-press-topdown-v3": ("Press the button down from above.", "obj1 = button; goal = pressed position"),
    "button-press-topdown-wall-v3": ("Press the button down from above; a short wall stands in front of it.", "obj1 = button; goal = pressed position"),
    "button-press-v3": ("Press the button on the wall panel by pushing it horizontally.", "obj1 = button; goal = pressed position"),
    "button-press-wall-v3": ("Press the button horizontally; reach it past the short wall in front of it.", "obj1 = button; goal = pressed position"),
    "coffee-button-v3": ("Press the button on the coffee machine.", "obj1 = button; goal = pressed position"),
    "coffee-pull-v3": ("Pull the mug out from under the coffee machine to the target.", "obj1 = mug; goal = target"),
    "coffee-push-v3": ("Push the mug under the coffee machine to the target.", "obj1 = mug; goal = target"),
    "dial-turn-v3": ("Rotate the dial by pushing its handle around.", "obj1 = dial handle; goal = target handle position"),
    "disassemble-v3": ("Pick the nut off the peg by its handle and lift it clear.", "obj1 = nut handle; goal = target above the peg"),
    "door-close-v3": ("Close the open door by pushing it shut.", "obj1 = door handle; goal = closed handle position"),
    "door-lock-v3": ("Lock the door by turning the lock knob down.", "obj1 = lock knob; goal = locked position"),
    "door-open-v3": ("Open the door by pulling its handle.", "obj1 = door handle; goal = open handle position"),
    "door-unlock-v3": ("Unlock the door by turning the lock knob.", "obj1 = lock knob; goal = unlocked position"),
    "hand-insert-v3": ("Push or carry the block into the hole in the table (the block must end within 5 cm of the hole).", "obj1 = block; goal = hole"),
    "drawer-close-v3": ("Push the drawer closed.", "obj1 = drawer handle; goal = closed handle position"),
    "drawer-open-v3": ("Pull the drawer open by its handle.", "obj1 = drawer handle; goal = open handle position"),
    "faucet-open-v3": ("Turn the faucet handle to open it.", "obj1 = faucet handle; goal = open position"),
    "faucet-close-v3": ("Turn the faucet handle to close it.", "obj1 = faucet handle; goal = closed position"),
    "hammer-v3": ("Pick up the hammer and use it to hammer the nail into the wall.", "obj1 = hammer handle; goal = nail"),
    "handle-press-side-v3": ("Press the handle down, approaching from the side.", "obj1 = handle; goal = pressed position"),
    "handle-press-v3": ("Press the handle down.", "obj1 = handle; goal = pressed position"),
    "handle-pull-side-v3": ("Pull the handle up, approaching from the side.", "obj1 = handle; goal = raised position"),
    "handle-pull-v3": ("Pull the handle up.", "obj1 = handle; goal = raised position"),
    "lever-pull-v3": ("Pull the lever up to the goal.", "obj1 = lever end; goal = raised lever position"),
    "pick-place-wall-v3": ("Pick up the puck and place it at the goal on the other side of a wall.", "obj1 = puck; goal = target in the air"),
    "pick-out-of-hole-v3": ("Pick the peg out of the hole and lift it to the goal.", "obj1 = peg; goal = target above the hole"),
    "pick-place-v3": ("Pick up the puck and place it at the goal (the goal is in the air).", "obj1 = puck; goal = target"),
    "plate-slide-v3": ("Slide the plate into the goal net.", "obj1 = plate; goal = net"),
    "plate-slide-side-v3": ("Slide the plate sideways into the goal net.", "obj1 = plate; goal = net"),
    "plate-slide-back-v3": ("Slide the plate back out of the net to the goal.", "obj1 = plate; goal = target"),
    "plate-slide-back-side-v3": ("Slide the plate sideways out of the net to the goal.", "obj1 = plate; goal = target"),
    "peg-insert-side-v3": ("Pick up the peg and insert it sideways into the hole in the box.", "obj1 = peg; goal = hole"),
    "peg-unplug-side-v3": ("Pull the peg out sideways from the hole in the box.", "obj1 = peg; goal = target clear of the box"),
    "soccer-v3": ("Push the ball into the goal.", "obj1 = ball; goal = goal mouth"),
    "stick-push-v3": ("Pick up the stick and use it to push the thermos to the goal.", "obj1 = stick; obj2 = thermos; goal = target"),
    "stick-pull-v3": ("Pick up the stick and use it to pull the thermos to the goal.", "obj1 = stick; obj2 = thermos; goal = target"),
    "push-v3": ("Push the puck to the goal on the table.", "obj1 = puck; goal = target"),
    "push-wall-v3": ("Push the puck to the goal, around the wall between them.", "obj1 = puck; goal = target"),
    "push-back-v3": ("Pull the puck back toward the robot to the goal.", "obj1 = puck; goal = target"),
    "reach-v3": ("Move the gripper to the goal position.", "obj1 = (unused); goal = target"),
    "reach-wall-v3": ("Move the gripper to the goal position, reaching over the wall.", "obj1 = (unused); goal = target"),
    "shelf-place-v3": ("Pick up the block and place it on the shelf at the goal.", "obj1 = block; goal = shelf target"),
    "sweep-into-v3": ("Sweep the puck into the hole in the table.", "obj1 = puck; goal = hole"),
    "sweep-v3": ("Sweep the puck off the edge of the table.", "obj1 = puck; goal = off the table edge"),
    "window-open-v3": ("Slide the window open by pushing its handle sideways.", "obj1 = window handle; goal = open position"),
    "window-close-v3": ("Slide the window closed by pushing its handle sideways.", "obj1 = window handle; goal = closed position"),
}

TASK_TOML = """\
version = "1.0"

[task]
name = "robouse/metaworld-{slug}"
description = "{goal}"

[metadata]
source_benchmark = "Meta-World MT50 (Farama, v3)"
source_task = "{env}"
suite = "metaworld"
category = "manipulation"
difficulty = "{difficulty}"
tags = ["sawyer", "mujoco", "single-arm"]

[agent]
timeout_sec = 900

[verifier]
timeout_sec = 120

[robouse]
id = "metaworld-{slug}"
backend = "metaworld"
env = "{env}"
seed = {seed}
max_steps = 500
camera = "corner"
skills = true
success_mode = "first"  # Meta-World protocol: solved the first time the success signal fires
"""

# Rough difficulty from Meta-World's MT50 literature (single-task RL success tiers).
HARD = {"assembly-v3", "basketball-v3", "bin-picking-v3", "box-close-v3", "disassemble-v3", "hammer-v3",
        "hand-insert-v3", "pick-out-of-hole-v3", "pick-place-v3", "pick-place-wall-v3", "shelf-place-v3",
        "stick-pull-v3", "stick-push-v3", "peg-insert-side-v3", "soccer-v3", "sweep-into-v3", "lever-pull-v3"}
EASY = {"reach-v3", "button-press-v3", "button-press-topdown-v3", "drawer-close-v3", "door-close-v3",
        "window-open-v3", "window-close-v3", "plate-slide-v3", "handle-press-v3", "faucet-open-v3", "faucet-close-v3"}


def instruction(env: str) -> str:
    goal, fields = GOALS[env]
    return textwrap.dedent(f"""\
    # {env.removesuffix('-v3').replace('-', ' ').title()}

    A Sawyer robot arm with a two-finger gripper stands at a table (adapted from Meta-World, `{env}`).

    **Goal:** {goal}

    In `robo observe`: `hand_pos` is the gripper position, `gripper_open` its opening (1 = open), `obj1_pos`/`obj1_quat` and `obj2_pos` are the task objects ({fields}), and `goal_pos` is the target. The full 39-number observation vector is also given as `obs_vector`.

    """) + ROBO_USAGE


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks/metaworld")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for env, (goal, _) in GOALS.items():
        slug = env.removesuffix("-v3")
        d = out / f"metaworld-{slug}"
        (d / "solution").mkdir(parents=True)
        (d / "tests").mkdir()
        diff = "hard" if env in HARD else "easy" if env in EASY else "medium"
        (d / "task.toml").write_text(TASK_TOML.format(slug=slug, env=env, goal=goal.replace('"', "'"), seed=a.seed, difficulty=diff))
        (d / "instruction.md").write_text(instruction(env))
        (d / "solution" / "solve.sh").write_text(
            f"#!/bin/bash\n# Reference solution: Meta-World's scripted expert, through the robo socket.\n"
            f"set -euo pipefail\npython -m robouse.oracle --backend metaworld --env {env} --steps 450\n")
        (d / "tests" / "test.sh").write_text(VERIFY)
        for f in (d / "solution" / "solve.sh", d / "tests" / "test.sh"):
            f.chmod(0o755)
        to_native(d)
    print(f"wrote {len(GOALS)} tasks to {out}")


VERIFY = """\
#!/bin/bash
# Verifier: the episode server already judged the final physical state; copy its verdict.
# ROBOUSE_EPISODE_DIR points at the trusted episode directory (result.json written by `robouse serve`).
set -euo pipefail
mkdir -p /logs/verifier 2>/dev/null || true
OUT="${ROBOUSE_VERIFIER_DIR:-/logs/verifier}"
mkdir -p "$OUT"
python3 - "$ROBOUSE_EPISODE_DIR/result.json" "$OUT/reward.txt" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
open(sys.argv[2], "w").write("1" if r.get("success") else "0")
print("success" if r.get("success") else "fail", r.get("outcome"))
EOF
"""

if __name__ == "__main__":
    main()
