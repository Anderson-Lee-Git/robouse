"""Gymnasium-Robotics (Farama) -> robouse tasks.

Six Fetch manipulation tasks (Reach, Push, PickAndPlace; two seeded layouts each) and six PointMaze
navigation tasks (UMaze, Medium, Large; two seeded start/goal pairs each). The task list lives in
`robouse.backends.gymrobotics.TASKS`. Reference solutions drive the robot only through the robo socket
(`oracle_main` in the backend module).

Usage: python adapters/gymrobotics/generate.py --out tasks/gymrobotics
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.gymrobotics import TASKS
from robouse.prompts import ROBO_USAGE
from robouse.tasks import to_native


def _metaworld_verify() -> str:
    """The verifier is shared with the Meta-World adapter (it copies the episode server's verdict)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_mw_generate", Path(__file__).resolve().parents[1] / "metaworld" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.VERIFY


def _unwrap(text: str) -> str:
    """Join hard-wrapped prose lines into one line per paragraph."""
    return "\n\n".join(" ".join(line.strip() for line in para.splitlines()) for para in text.strip().split("\n\n"))


TASK_TOML = """\
version = "1.0"

[task]
name = "robouse/{id}"
description = "{desc}"

[metadata]
source_benchmark = "Gymnasium-Robotics (Farama)"
source_task = "{env}"
suite = "gymrobotics"
category = "{category}"
difficulty = "{difficulty}"
tags = {tags}

[agent]
timeout_sec = 900

[verifier]
timeout_sec = 120

[robouse]
id = "{id}"
backend = "gymrobotics"
env = "{env}"
seed = {seed}
max_steps = {max_steps}
camera = "{camera}"
skills = {skills}
success_mode = "{mode}"  # {mode_why}
"""

FETCH_INTRO = "A Fetch robot arm with a two-finger parallel gripper stands at a table (adapted from Gymnasium-Robotics, `{env}`, layout seed {seed})."
FETCH_FIELDS = """\
In `robo observe`: `hand_pos`/`hand_vel` are the gripper position (m) and velocity (m/s), `gripper_open`
is the finger opening (0 = closed, 1 = fully open) and `gripper_width` the gap in metres, `obj1_pos`,
`obj1_vel` and `obj1_rot` (Euler angles, rad) describe the block, and `goal_pos` is the target (shown as
a red sphere in camera images). The block is a 5 cm cube.

The action `robo act DX DY DZ GRIP` moves the gripper by up to 5 cm per step along world x/y/z
(DX = 1 means 5 cm); GRIP +1 closes the fingers and -1 opens them. The gripper always points down."""

FETCH = {
    "FetchReach-v4": dict(
        title="Fetch Reach", difficulty="easy", tags=["fetch", "mujoco", "single-arm", "reach"],
        goal="Move the gripper to the goal position and hold it there.",
        success="Success: the gripper centre (`hand_pos`) is within 5 cm of `goal_pos`, judged after you call "
                "`robo done` and the robot has held still for about 10 steps.",
        fields="""\
In `robo observe`: `hand_pos`/`hand_vel` are the gripper position (m) and velocity (m/s), and `goal_pos`
is the target (shown as a red sphere in camera images). The fingers are locked in this task, so GRIP has
no effect.

The action `robo act DX DY DZ GRIP` moves the gripper by up to 5 cm per step along world x/y/z
(DX = 1 means 5 cm).""",
    ),
    "FetchPush-v4": dict(
        title="Fetch Push", difficulty="medium", tags=["fetch", "mujoco", "single-arm", "push"],
        goal="Push the block across the table so it rests on the goal position.",
        success="Success: the block centre (`obj1_pos`) is within 5 cm of `goal_pos`, judged after you call "
                "`robo done` and the robot has held still for about 10 steps.",
        fields=FETCH_FIELDS,
    ),
    "FetchPickAndPlace-v4": dict(
        title="Fetch Pick and Place", difficulty="medium", tags=["fetch", "mujoco", "single-arm", "pick-place"],
        goal="Pick up the block and place it at the goal position. The goal may be on the table or in the air; "
             "if it is in the air, hold the block there.",
        success="Success: the block centre (`obj1_pos`) is within 5 cm of `goal_pos` in 3-D, judged after you call "
                "`robo done` and the robot has held still for about 10 steps (keeping the gripper as it was).",
        fields=FETCH_FIELDS,
    ),
}

MAZE = {
    "PointMaze_UMaze-v3": ("U-maze", "easy", 600),
    "PointMaze_Medium-v3": ("medium maze", "medium", 1000),
    "PointMaze_Large-v3": ("large maze", "hard", 1500),
}

MAZE_NOTES = """\
In `robo observe`: `agent_pos`/`agent_vel` are the ball's position (m) and velocity (m/s), `goal_pos`
is the goal (shown in red in camera images; the ball is green), and `maze_rows` is the maze layout, one
string per row from the top (+y) row down: `#` is a wall block, `.` is free floor. `cell_size` is the
width of one cell in metres, `cell_center` gives the world coordinates of the centre of cell (row, col),
and `agent_cell`/`goal_cell` are the [row, col] cells the ball and goal are in. Walls fill whole cells;
the ball (radius 0.1 m) cannot pass through them. Camera images are top-down with +x to the right and
+y up.

**This task uses a 2-D action.** `robo act FX FY [--repeat N]` applies a force (each in [-1, 1]) to the
ball along world x and y for N steps of 10 ms each; the ball keeps its momentum, so brake by pushing
the other way. `robo move-to` and `robo grip` are disabled here, and the `DX DY DZ GRIP` form in the
general instructions below does not apply."""


def _toml(**kw) -> str:
    kw["tags"] = "[" + ", ".join(f'"{t}"' for t in kw["tags"]) + "]"
    kw["skills"] = "true" if kw["skills"] else "false"
    return TASK_TOML.format(**kw)


def build(task_id: str, env: str, seed: int) -> tuple[str, str]:
    if env in FETCH:
        f = FETCH[env]
        toml = _toml(id=task_id, desc=f["goal"].replace('"', "'"), env=env, category="manipulation",
                     difficulty=f["difficulty"], tags=f["tags"], seed=seed, max_steps=300, camera="default",
                     skills=True, mode="final", mode_why="the goal must still hold after `robo done` and a settle period")
        instr = (f"# {f['title']} (seed {seed})\n\n" + FETCH_INTRO.format(env=env, seed=seed)
                 + f"\n\n**Goal:** {f['goal']}\n\n{f['success']}\n\n{_unwrap(f['fields'])}\n\n" + ROBO_USAGE)
        return toml, instr
    name, diff, max_steps = MAZE[env]
    goal = "Roll the ball through the maze to the goal."
    toml = _toml(id=task_id, desc=goal, env=env, category="navigation", difficulty=diff,
                 tags=["pointmaze", "mujoco", "navigation", "2d"], seed=seed, max_steps=max_steps, camera="top",
                 skills=False, mode="first", mode_why="reaching the goal ends the episode (PointMaze/D4RL episodic protocol)")
    instr = (f"# Point Maze: {name} (seed {seed})\n\n"
             f"A small ball moves on the floor of a walled {name}, pushed by a force you choose "
             f"(adapted from Gymnasium-Robotics, `{env}`, start/goal seed {seed}).\n\n"
             f"**Goal:** {goal}\n\n"
             "Success: the ball centre comes within 0.45 m of `goal_pos`. The episode ends as solved the moment "
             "this happens (you do not need to stop on the goal or call `robo done` afterwards).\n\n"
             f"{_unwrap(MAZE_NOTES)}\n\n" + ROBO_USAGE)
    return toml, instr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks/gymrobotics")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    verify = _metaworld_verify()
    for task_id, (env, seed) in TASKS.items():
        d = out / task_id
        (d / "solution").mkdir(parents=True)
        (d / "tests").mkdir()
        toml, instr = build(task_id, env, seed)
        (d / "task.toml").write_text(toml)
        (d / "instruction.md").write_text(instr)
        (d / "solution" / "solve.sh").write_text(
            "#!/bin/bash\n# Reference solution: scripted controller that uses only the robo socket and public observations.\n"
            f"set -euo pipefail\npython -m robouse.oracle --backend gymrobotics --env {task_id}\n")
        (d / "tests" / "test.sh").write_text(verify)
        for f in (d / "solution" / "solve.sh", d / "tests" / "test.sh"):
            f.chmod(0o755)
        to_native(d)
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
