"""HumanoidBench -> Robo Use tasks (suite "humanoidbench"): whole-body tasks for a Unitree H1 humanoid with two Shadow
hands, from HumanoidBench (Sferrazza et al. 2024, MIT licence, github.com/carlosferrazza/humanoid-bench, pinned commit
cb11890). Backend, skills and verdict: src/robouse/backends/humanoidbench.py (the simulator runs in its own virtualenv
through src/robouse/backends/humanoidbench_worker.py; setup in docs/suites/humanoidbench.md). Reference solutions:
src/robouse/backends/humanoidbench_oracles.py. The generator starts each task once to read the scene facts it writes into
the instruction, so it needs that virtualenv too.

Usage: python adapters/humanoidbench/generate.py [--out tasks/humanoidbench]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.embodied import write_embodied_task
from robouse.backends.humanoidbench.backend import CONTROL_DT, TASKS, HumanoidBenchBackend
from robouse.backends.humanoidbench.oracles import ORACLES
from robouse.core.prompts import EMBODIED_USAGE

_SETTLE = (
    "- Success is judged about 10 steps after you call `robo done`, with the robot holding still (each action group's hold value: "
    "zero for velocity and delta commands, full brake for a car), so the goal must still be true when the robot stops."
)
assert _SETTLE in EMBODIED_USAGE
USAGE = EMBODIED_USAGE.replace(
    _SETTLE,
    "- The episode ends as solved the moment the task's success rule holds (see Success); `robo done` before that scores 0.",
)

ROBOT = (
    "You are the policy of a Unitree H1 humanoid robot (about 1.8 m tall, 5-joint legs, 4-joint arms) with a Shadow dexterous "
    "hand on each arm, simulated in MuJoCo by HumanoidBench (the `h1hand` robot). The robot is free-standing: it must keep its "
    "balance and it can fall. A walking controller keeps it balanced for you: it is Unitree's pretrained H1 locomotion policy, "
    "which drives the legs from a velocity command and steps in place when the command is zero. World frame in metres, +z up, the "
    "floor at z = 0; `heading_deg` is the robot's facing direction (0 = +x, counter-clockwise positive). The robot starts at the "
    "origin facing +x. Simulated time advances only when you act; the scene is paused while you think."
)

CONTROLS = (
    "**Controls.** `robo act FORWARD LEFT TURN LDX LDY LDZ RDX RDY RDZ [--repeat N]` applies one 20 ms control step N times "
    "(N <= 50). FORWARD in [-1, 1] m/s and LEFT in [-0.5, 0.5] m/s are the walking velocity in the robot's heading frame, TURN in "
    "[-1, 1] rad/s the turn rate (+ = counter-clockwise). The robot reaches a new velocity within about half a second; at FORWARD "
    "1 it walks at about 0.9 m/s, and the walking policy treats sideways-plus-forward speeds below about 0.2 m/s as zero. An "
    "all-zero FORWARD LEFT TURN holds the robot's current spot and heading: it keeps stepping in place and walks back when it "
    "drifts more than about 4 cm. LDX LDY LDZ and RDX RDY RDZ in [-1, 1] move the goal point of the left and right hand by 2 cm "
    "per step in the heading frame (x forward, y left, z up, origin on the floor under the pelvis); inverse kinematics on the 4 "
    "arm joints makes the hand follow its goal, so the hands move with the body when it walks. Zero holds the goal. The arms are "
    "about 0.64 m long from the shoulder (at about 1.48 m height, 0.2 m to each side of the pelvis), so a hand reaches about "
    "0.55 m ahead of the pelvis at 1 m height; the fingers and wrists hold their start pose. Skills (`robo info` lists their "
    "arguments): `walk_to X Y [HEADING_DEG] [TOL]` walks to a floor point (it does not avoid obstacles), `walk FORWARD LEFT TURN "
    "STEPS` holds a velocity command, `turn_to HEADING_DEG`, `stand STEPS` holds the spot, `reach left|right X Y Z [TOL]` moves a "
    "hand to a world point and keeps it there while the body sways, `hands_home`, and `sit_down` (one-way: stops the walking "
    "controller and sits down where the robot stands, the pelvis ending about 0.2 m further back)."
)

OBSERVATION = (
    "**Observation.** `robo observe` reports `robot` (`pelvis` position, `heading_deg`, `head_height`, `torso_upright` (1 = "
    "upright), `com_velocity` (world x, y) and `com_velocity_body` (forward, left), the current velocity `command`, and per hand "
    "`pos` (world), `pos_body` and `goal_body` (heading frame) and `anchored_at` (the world point a `reach` holds), `fallen`), "
    "`scene` (the task's objects and goals) and `progress`: HumanoidBench's `return` so far, `last_reward` and its "
    "`reward_terms`, `steps` of `episode_steps`, the `success_bar` for return-based tasks and `solved`. Camera images: "
    "`robo observe --image` (HumanoidBench's view for the task, following the robot)."
)

RETURN_RULE = (
    "HumanoidBench scores every 20 ms step with the task's reward ({per_step} for this task; the terms are in "
    "`progress.reward_terms`) and counts the task as solved when the episode return reaches its success bar of {bar:.0f}. "
    "The episode ends as solved the moment `progress.return` reaches {bar:.0f}; calling `robo done` earlier scores 0. If the "
    "robot falls (HumanoidBench's termination: {fall}), the episode can no longer succeed."
)

TEXT = {
    "humanoidbench-stand": dict(
        title="Stand",
        difficulty="easy",
        category="locomotion",
        goal=(
            "Stand upright and still. HumanoidBench's stand reward is the product of: standing (head at least 1.65 m above the "
            "floor), upright (torso vertical), small control (small joint forces) and not moving (centre-of-mass speed near zero)."
        ),
        fall="pelvis below 0.2 m",
        tags=["stand", "balance"],
    ),
    "humanoidbench-walk": dict(
        title="Walk",
        difficulty="easy",
        category="locomotion",
        goal=(
            "Walk forward along +x at 1 m/s or faster while staying upright. HumanoidBench's walk reward is the product of: standing "
            "(head at least 1.65 m above the floor), upright, small control, and moving (the centre of mass's world-x velocity: 1 when it "
            "is at least 1 m/s, falling linearly to 1/6 at 0 m/s). Only the velocity along the world x axis counts, so keep the heading "
            "near 0."
        ),
        fall="pelvis below 0.2 m",
        tags=["walk", "locomotion"],
    ),
    "humanoidbench-maze": dict(
        title="Maze",
        difficulty="medium",
        category="navigation",
        goal=(
            "Walk through a maze of 1.5 m wall blocks (1.2 m high) along its corridor, through the checkpoints (3, 0), (3, 6) and "
            "(6, 6) in that order (`scene.checkpoints`, `scene.next_checkpoint`; the wall blocks are listed under `scene.walls` as x "
            "and y ranges). A checkpoint counts when the pelvis comes within 0.4 m of it and gives a one-off bonus of 100 x the number "
            "of checkpoints reached so far (the start point (0, 0) counts as the first, so the four bonuses add up to 1000). Every step "
            "also rewards standing upright, moving toward the next checkpoint at 2 m/s and being close to it (after the last "
            "checkpoint, staying near it); touching a wall multiplies that step's reward by 0.1."
        ),
        fall="pelvis below 0.2 m",
        tags=["maze", "navigation"],
    ),
    "humanoidbench-pole": dict(
        title="Pole forest",
        difficulty="medium",
        category="navigation",
        goal=(
            "Walk forward (+x) through a forest of thin vertical poles without touching them. The poles (radius 5 cm, 2 m tall, "
            "positions under `scene.poles`) stand in rows 1 m apart from x = 1 m, 1.5 m apart within a row, alternate rows offset by "
            "0.75 m; the corridor is closed by walls at y = +-3 m (their inner faces) and behind the start at x = -0.45 m. Each step's "
            "reward is 0.5 x (standing: head at least 1.65 m high, upright, small control) + 0.5 x (moving: the centre of mass's "
            "world-x velocity, 1 at 1 m/s or faster, falling linearly to 1/6 at 0 m/s), multiplied by 0.1 while any part of the "
            "robot touches a pole."
        ),
        fall="pelvis below 0.5 m",
        tags=["obstacles", "navigation"],
    ),
    "humanoidbench-sit-simple": dict(
        title="Sit on the chair",
        difficulty="medium",
        category="whole-body",
        goal=(
            "Sit down on the chair behind you and stay seated, upright and still. The chair (`scene.chair`: its position is the "
            "centre of its footprint on the floor) has a 0.42 x 0.42 m seat 0.475 m high and a backrest on its -x side; its seat "
            "centre is 0.25 m behind the robot's start position. HumanoidBench's sit reward is the product of: small control, not "
            "moving, upright (torso within about 18 degrees of vertical), a seated posture (head 0.35-0.45 m above the torso's IMU, "
            "which holds whenever the torso is upright) and 0.5 x sitting (pelvis 0.68-0.72 m above the floor) + 0.5 x on the chair "
            "(pelvis x within 0.19 m of the chair's x, and pelvis y at the chair's y: the term falls to 0.1 at 0.1 m sideways)."
        ),
        fall="pelvis below 0.5 m",
        tags=["sit", "whole-body"],
    ),
    "humanoidbench-reach": dict(
        title="Reach a point with the left hand",
        difficulty="medium",
        category="loco-manipulation",
        goal=(
            "Put the left hand on the target point `scene.target` and keep it there (`scene.left_hand_to_target_m` is the distance "
            "from the left hand to it). HumanoidBench's reach reward per step is 5 x torso uprightness (5 when upright) + 5 while the "
            "left hand is within 1 m of the target + 10 while it is within 5 cm of it, minus a tiny penalty on joint speeds: at most "
            "about 20 per step. Only the left hand counts."
        ),
        per_step="at most about 20 per step",
        fall=None,
        tags=["reach", "loco-manipulation"],
    ),
    "humanoidbench-push": dict(
        title="Push the box to the goal",
        difficulty="hard",
        category="loco-manipulation",
        goal=(
            "Move the box on the table to the goal point `scene.goal` (the red marker in the camera view). The table top spans x "
            "0.4-1.4 m, y -1-1 m, at 0.95 m height; the box is a 0.2 m cube (0.3 kg) starting near (0.70, 0.0), resting on the table "
            "with its centre at z = 1.0, and the goal is on the table surface at the same height (`scene.box_to_goal_m` is the "
            "distance). The robot starts 0.4 m from the table edge, too far to reach the box; its legs meet the table when the pelvis is "
            "about 0.1 m from the edge (x = 0.3). The box may be pushed, slid or held between the hands; the Shadow hands' fingers "
            "stay straight and can snag the box's edges."
        ),
        rule=(
            "HumanoidBench's own success signal: the box's centre within 5 cm of the goal point (3D distance). The episode ends as "
            "solved the moment that holds; `robo done` before that scores 0."
        ),
        tags=["push", "loco-manipulation", "table"],
    ),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "humanoidbench"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    n = 0
    for tid, t in TASKS.items():
        if tid not in TEXT or tid not in ORACLES:
            continue
        x = TEXT[tid]
        be = HumanoidBenchBackend({"id": tid})
        be.reset(int(t["seed"]))
        meta = be.meta
        be.close()
        steps = int(t["max_steps"])
        rule = (
            RETURN_RULE.replace(
                " If the robot falls (HumanoidBench's termination: {fall}), the episode can no longer succeed.",
                " This task has no fall termination, but a fallen robot cannot keep its hand on the target.",
            )
            if x.get("fall", "") is None
            else RETURN_RULE
        )
        rule = (
            rule.format(
                bar=meta["success_bar"], fall=x.get("fall"), per_step=x.get("per_step", "at most about 1 per step")
            )
            if meta["success"] == "return"
            else x["rule"]
        )
        parts = [
            f"# {x['title']} (HumanoidBench)",
            ROBOT,
            "## Task\n\n" + x["goal"],
            f"**Success:** {rule}",
            CONTROLS,
            OBSERVATION,
            f"The step budget is {steps} steps ({steps * CONTROL_DT:.0f} s of simulated time), HumanoidBench's episode length for "
            "this task.",
            USAGE,
        ]
        write_embodied_task(
            out,
            task_id=tid,
            backend="humanoidbench",
            suite="humanoidbench",
            title=x["title"],
            instruction="\n\n".join(parts) + "\n",
            robot="Unitree H1 + Shadow hands",
            category=x["category"],
            difficulty=x["difficulty"],
            tags=["humanoid", "h1", "humanoidbench"] + x["tags"],
            max_steps=steps,
            camera=meta["camera"],
            cameras=list(dict.fromkeys([meta["camera"], "cam_default"])),
            oracle_note="scripted with the walking skills and the public observation.",
            extra_robouse={"env": t["task"], "seed": int(t["seed"]), "success_mode": "first"},
            extra_metadata={
                "source_benchmark": "HumanoidBench (carlosferrazza/humanoid-bench, MIT)",
                "source_task": meta["env"],
                "simulator": "MuJoCo 3.1.6 (HumanoidBench's pin)",
            },
        )
        n += 1
    print(f"wrote {n} tasks to {out}")


if __name__ == "__main__":
    main()
