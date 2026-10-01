"""RLE-Bench (Harvard, Georgia Tech; MIT; https://github.com/RLE-Bench/RLE-Bench) -> robouse tasks (suite "rle-bench").

Imports the interactive-control families that fit one agent-as-policy episode:

- family 03, tabletop reasoning: TowerMaxHeight, CantileverOverhang, BalanceCoins, and HiddenCOM as one task per sealed box.
  The scenes are RLE-Bench's own code (src/robouse/backends/rlebench/rlebench_upstream/), with RLE-Bench's seeds, action
  space, public observations, budgets and scoring; see src/robouse/backends/rlebench/backend.py for the adaptation.

Reference solutions: RLE-Bench's own RGB-based HiddenCOM solver, and closed-loop controllers of ours for the tabletop tasks
(RLE-Bench's recorded trajectories do not reproduce open-loop on this build; see src/robouse/backends/rlebench/oracles.py).

Usage: python adapters/rlebench/generate.py [--out tasks/rle-bench]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.rlebench.backend import TASKS
from robouse.tasks import write_task

ROOT = Path(__file__).resolve().parents[2]
RLE_COMMIT = "34a73aa3daebd92a4adc56142b87f2bccda4780d"
SOURCE = "RLE-Bench (RLE-Bench/RLE-Bench, commit 34a73aa)"

VERIFY = """\
#!/bin/bash
# Verifier: the episode server already judged the final scene with RLE-Bench's scoring; copy its verdict.
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

ORACLE_TABLETOP = """\
#!/bin/bash
# Reference solution: a closed-loop controller that reads the objects' poses (given only to the reference solution; never
# masses or which cube is heavy) and drives the robot with RLE-Bench's move skill and base actions. RLE-Bench's own
# recorded trajectory for this task does not reproduce when replayed open-loop on this build, so it is not used.
set -euo pipefail
python -m robouse.oracle --backend rlebench --env {tid}
"""

ORACLE_HIDDEN = """\
#!/bin/bash
# Reference solution: RLE-Bench's own HiddenCOM solver (tasks/task03/_template/hidden_com_solution/oracle.py): lift the box
# by its handle and read the ballast quadrant from the top camera's RGB image. Public observations only.
set -euo pipefail
python -m robouse.oracle --backend rlebench --env {tid}
"""

USAGE = """\
## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the scoring, or other files to succeed; the episode server judges the final scene itself.

```
robo info                                   # action layout, skills, cameras (intrinsics), step budget
robo observe                                # robot proprioception{extra_obs}, and one image per camera (paths printed; open them to look)
robo observe --camera C                     # one camera only: {cameras}
robo act {act_args} [--repeat N]   # one control step (applied N times, N <= 50)
robo skill move X Y Z QX QY QZ QW [G] [S]   # track a world-frame tool pose for S steps (1-200, default 40); gripper G (+1 closes, -1 opens, default +1)
{extra_skills}robo done "short summary"                   # end the episode{done_note}
robo give-up "reason"                       # end the episode without submitting (scores 0)
```

- Positions are in metres in the world frame, z up; quaternions are unit x, y, z, w.
- Every control step counts against the budget, including the steps `move` runs; observing is free.
- Skills are ordinary controllers: collisions and reach limits can stop the arm short. Use intermediate waypoints and re-observe.
"""

TABLETOP_SCENE = (
    "A PandaOmron robot (a Franka Panda arm with a two-finger gripper on a mobile base with a torso lift) stands at a 0.7 x 1.6 m "
    "table whose top is at z = 0.9 m, spanning x in [-0.35, 0.35] and y in [-0.8, 0.8] around the world origin. Control runs at 20 Hz."
)

TABLETOP_CONTROLS = (
    "**Controls.** `robo act` takes 12 numbers in [-1, 1] (RLE-Bench's layout): arm translation in the ROBOT BASE frame (3, scaled by "
    "0.05 m), arm axis-angle rotation in the base frame (3, scaled by 0.5 rad), gripper (+1 closes, -1 opens; the value is absolute, "
    "so 0 is half-way), base forward/lateral/yaw velocity (3), torso velocity (1) and mode (-1 arm, +1 base). Neutral hold: "
    "`robo act 0 0 0 0 0 0 -1 0 0 0 0 -1`. `robo skill move` instead tracks a world-frame tool pose through the same controller "
    "while the base and torso hold still. `robo skill reset` restores the same initial scene, discards progress and costs one step."
)

TABLETOP_OBS = (
    "**Observation.** `robo observe` gives RGB images from three cameras, `robot0_agentview_left` and `robot0_agentview_right` "
    "(mounted on the mobile base) and `robot0_eye_in_hand` (on the wrist), 512 x 512, and the robot's proprioception: `joint_pos`, "
    "`joint_vel`, `eef_pos`, `eef_quat`, `gripper_pos`, `base_pos`, `base_quat`, `eef_base_pos` and `eef_base_quat`. Positions are "
    "in metres; `eef_base_*` is relative to the robot base, the other poses are world-frame. `robo info` gives each camera's "
    "intrinsics. No depth, masses, contact readings or object poses are given{balance}: infer object locations and physical "
    "properties by observing and interacting with the scene."
)

TXT = {
    "TowerMaxHeight": dict(
        title="Tallest tower",
        goal="stack mixed pieces into the tallest stable tower",
        notes="Some pieces cannot be stacked on; choose which pieces to use and in what order. Leave the completed tower standing on "
        "the table without support from the robot. Retract the arm before calling `robo done`.",
        score="RLE-Bench scores the settled height of the tower (pieces resting on the table or on other pieces, none touching the "
        "robot, after the scene settles for 5 s) relative to the tallest tower the pieces allow. This task passes when that fraction "
        "is at least 0.5.",
        description="Stack mixed pieces into the tallest stable tower (RLE-Bench tabletop reasoning).",
        difficulty="hard",
        tags=["stacking", "physical-reasoning", "long-horizon"],
    ),
    "CantileverOverhang": dict(
        title="Cantilever overhang",
        goal="extend a stack of identical blocks past the table edge",
        notes="Build a stable stack extending beyond any table edge. Leave it supported by the table without support from the "
        "robot. Retract the arm before calling `robo done`.",
        score="RLE-Bench scores the settled horizontal overhang of the stack beyond the table edge (blocks resting on the table or "
        "on other blocks, none touching the robot, after the scene settles for 5 s) relative to the best overhang the blocks allow "
        "(the harmonic stack). This task passes when that fraction is at least 0.5, which one block alone cannot reach.",
        description="Stack identical blocks so they reach as far past the table edge as possible (RLE-Bench tabletop reasoning).",
        difficulty="hard",
        tags=["stacking", "physical-reasoning", "balance"],
    ),
    "BalanceCoins": dict(
        title="Find the heavy cube",
        goal="find the heavy cube with the balance and deliver it to the answer mat",
        notes="Exactly one of the visually identical cubes is heavier. The attempt succeeds when that cube -- and only it -- rests "
        "on the green answer mat. Use as few weighings as possible: among successful attempts, fewer weighings earn a higher "
        "score. Plan comparisons before moving cubes. Observations include `cube_positions` (coin_0 through coin_8 centers) and "
        "`pan_positions` (left and right upper-surface centers). All coordinates are live world-frame xyz in meters. Cube IDs "
        "persist across movement and reset; they do not encode weight. The enlarged pans have diameter 0.225 m and centers 0.5 m "
        "apart when level.",
        score="RLE-Bench's score is 0 unless exactly the heavy cube rests on the answer mat; then it is 1 with at most two "
        "weighings (the fewest that always suffice for nine cubes) and 2 / w with w weighings. A weighing is a comparison with the "
        "same non-zero number of cubes on both pans, held for 0.5 s. This task passes when the score is at least 0.5: the heavy "
        "cube alone on the mat, found with at most four weighings.",
        description="Find the one heavier cube of nine with a two-pan balance and put it alone on the answer mat (RLE-Bench tabletop reasoning).",
        difficulty="hard",
        tags=["balance", "hidden-mass", "physical-reasoning", "active-perception"],
    ),
}

HIDDEN_SCENE = (
    "A fixed Franka Panda arm with a two-finger gripper stands at a table (top at z = 0.75 m). In front of it, on a 4 mm mat, lies "
    "a sealed 0.15 x 0.15 x 0.05 m box, initially centred at (0, 0, 0.779) m. Its rigid centred handle runs along x: an 80 x 16 x "
    "12 mm bar at (0, 0, 0.860) m with 50 mm clearance below. The lid is marked with the letters A, B, C and D, one per quadrant. "
    "Inside, a hidden ballast sits in one quadrant; the box's mass and the ballast's mass and placement are not given. You may "
    "push, lift or rotate the box on the clear tabletop. You cannot open it. Control runs at 20 Hz."
)

HIDDEN_CONTROLS = (
    "**Controls.** `robo act` takes 7 numbers in [-1, 1]: three world-aligned end-effector position deltas (scaled by 0.05 m), "
    "three axis-angle deltas (scaled by 0.5 rad) and the gripper (+1 closes, -1 opens). `robo skill move` tracks a world-frame "
    "tool pose through the same controller. `robo skill submit A` (or B, C, D) commits your answer: once, final, with no "
    "correctness feedback and no step cost. Then call `robo done`."
)

HIDDEN_OBS = (
    "**Observation.** `robo observe` gives RGB images from three cameras, `workspace`, `closeup` and `top`, 512 x 512 (the top "
    "camera looks straight down from (0.03, 0, 1.71) m with a 43 degree vertical field of view), and `joint_pos`, `joint_vel`, "
    "`eef_pos`, `eef_quat` (x, y, z, w), `gripper_pos` and `submitted`. No force/torque, object-pose, mass or contact readings "
    "are given."
)


def tabletop(tid: str, t: dict) -> tuple[dict, str]:
    txt = TXT[t["task"]]
    balance = ", apart from the cube and pan positions below" if t["task"] == "BalanceCoins" else ""
    goal = txt["goal"]
    body = f"""# {txt['title']} (RLE-Bench)

Use the robot to {goal}. {txt['notes']}

{TABLETOP_SCENE}

**Scoring.** {txt['score']} The scene is submitted however the episode ends: `robo done`, running out of steps or time, or stopping without `robo done`; `robo give-up` scores 0.

You have **{t['max_steps']:,} control steps** in one attempt. Observe and experiment until satisfied, then call `robo done`.

{TABLETOP_CONTROLS}

{TABLETOP_OBS.format(balance=balance)}

""" + USAGE.format(
        extra_obs=" (and `cube_positions`, `pan_positions`)" if t["task"] == "BalanceCoins" else "",
        cameras="robot0_agentview_left, robot0_agentview_right, robot0_eye_in_hand",
        act_args="A1 ... A12      ",
        extra_skills="robo skill reset                            # restore the same initial scene (costs one step)\n",
        done_note=" and submit the scene",
    )
    meta = {
        "task": {"name": f"robouse/{tid}", "description": txt["description"]},
        "metadata": {
            "source_benchmark": SOURCE,
            "source_task": f"task03 {t['task']}",
            "suite": "rle-bench",
            "category": "manipulation",
            "difficulty": txt["difficulty"],
            "tags": ["mujoco", "robosuite", "panda", "mobile-manipulator", "vision", *txt["tags"]],
            "rle_bench": {
                "family": "task03 (interactive control: tabletop reasoning)",
                "task": t["task"],
                "seed": "RLE-Bench's evaluation seed for this task",
                "scoring": "RLE-Bench quality >= 0.5 passes (quality recorded in result.json)",
            },
        },
        "agent": {"timeout_sec": 32400},
        "verifier": {"timeout_sec": 600},
        "robouse": {
            "id": tid,
            "backend": "rlebench",
            "env": tid,
            "seed": 0,
            "max_steps": t["max_steps"],
            "obs_mode": "vision",
            "visible_fields": [
                "joint_pos",
                "joint_vel",
                "eef_pos",
                "eef_quat",
                "gripper_pos",
                "base_pos",
                "base_quat",
                "eef_base_pos",
                "eef_base_quat",
                *(["cube_positions", "pan_positions"] if t["task"] == "BalanceCoins" else []),
            ],
            "camera": "robot0_agentview_left",
            "cameras": ["robot0_agentview_left", "robot0_agentview_right", "robot0_eye_in_hand"],
            "skills": True,
            "success_mode": "final",
            "frame_every": 10,
        },
    }
    return meta, body


def hidden_com(tid: str, t: dict) -> tuple[dict, str]:
    box = t["case"] + 1
    body = f"""# Hidden centre of mass, box {box} of 3 (RLE-Bench)

Use the Panda robot to identify the hidden ballast quadrant of a sealed box. Identify the quadrant by the A/B/C/D markings on the box. RLE-Bench runs three such boxes, which look identical but have different masses, ballast placements and inertias; this task is box {box}. Determine the answer correctly using as few control steps as possible. You cannot open the box or reset the experiment.

{HIDDEN_SCENE}

**Scoring.** This task passes when the quadrant you submit is the one holding the ballast. RLE-Bench's score for its three boxes is the fraction answered correctly, so the mean over the three box tasks is RLE-Bench's score.

You have **{t['max_steps']:,} control steps**. The episode ends when they are used up, so submit before then; without a submission the task scores 0.

{HIDDEN_CONTROLS}

{HIDDEN_OBS}

""" + USAGE.format(
        extra_obs="",
        cameras="workspace, closeup, top",
        act_args="A1 ... A7       ",
        extra_skills="robo skill submit A                         # commit the quadrant (A, B, C or D): final, no feedback\n",
        done_note="",
    )
    meta = {
        "task": {
            "name": f"robouse/{tid}",
            "description": f"Find which quadrant of sealed box {box} holds the hidden ballast by handling it (RLE-Bench HiddenCOM).",
        },
        "metadata": {
            "source_benchmark": SOURCE,
            "source_task": f"task03 HiddenCOM, box {box} of 3",
            "suite": "rle-bench",
            "category": "manipulation",
            "difficulty": "medium",
            "tags": [
                "mujoco",
                "robosuite",
                "panda",
                "vision",
                "hidden-mass",
                "physical-reasoning",
                "active-perception",
            ],
            "rle_bench": {
                "family": "task03 (interactive control: tabletop reasoning)",
                "task": "HiddenCOM",
                "box": box,
                "scoring": "1 if the submitted quadrant is correct (RLE-Bench scores the fraction of its three boxes)",
            },
        },
        "agent": {"timeout_sec": 1200},
        "verifier": {"timeout_sec": 300},
        "robouse": {
            "id": tid,
            "backend": "rlebench",
            "env": tid,
            "seed": 0,
            "max_steps": t["max_steps"],
            "obs_mode": "vision",
            "visible_fields": ["joint_pos", "joint_vel", "eef_pos", "eef_quat", "gripper_pos", "submitted"],
            "camera": "workspace",
            "cameras": ["workspace", "closeup", "top"],
            "skills": True,
            "success_mode": "final",
            "frame_every": 5,
        },
    }
    return meta, body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "tasks" / "rle-bench"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for tid, t in TASKS.items():
        if t["task"] == "HiddenCOM":
            meta, body = hidden_com(tid, t)
            oracle = ORACLE_HIDDEN.format(tid=tid)
        else:
            meta, body = tabletop(tid, t)
            oracle = ORACLE_TABLETOP.format(tid=tid)
        write_task(out / tid, meta, body, oracle, VERIFY)
        print(tid)


if __name__ == "__main__":
    main()
