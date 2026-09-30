"""ManiSkill3 (Hao Su Lab / Hillbot, SAPIEN 3) -> robouse tasks (suite "maniskill").

ManiSkill3's tabletop tasks with a Franka Panda, on ManiSkill's CPU physics backend and SAPIEN's Vulkan renderer (no GPU
needed). The task list lives in src/robouse/backends/maniskill.py (TASKS); the simulation runs in a separate virtualenv
(maniskill_worker.py, see docs/suites/maniskill.md). Object layouts are ManiSkill's own randomisation, fixed per task by
the `seed` in the `robouse:` block. Success is ManiSkill's own `evaluate()["success"]`. Reference solutions
(maniskill_oracles.py) drive the robot only through the robo socket.

Usage: python adapters/maniskill/generate.py [--out tasks/maniskill]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.embodied import VERIFY_SH
from robouse.backends.maniskill.backend import TASKS
from robouse.core.prompts import ROBO_USAGE
from robouse.tasks import write_task

ROOT = Path(__file__).resolve().parents[2]

WRISTCAM = {"StackCube-v1", "StackPyramid-v1", "PegInsertionSide-v1", "PlugCharger-v1"}  # ManiSkill's panda_wristcam robot

SCENE = ("A Franka Emika Panda arm (7 joints, two-finger parallel gripper that opens to 8 cm) stands at a wooden table in ManiSkill3's "
         "`{env}` task, simulated with SAPIEN 3 (PhysX). {base} The table top is the plane z = 0.")
BASE = "The robot's base is at x = -0.615, y = 0 and faces +x, so +x points away from the robot and +y to its left."
BASE_ROLL = ("In this task the robot's base is at x = -0.1, y = 1.0 and faces -y (toward the far end of the table), so the ball has to be "
             "sent in the -y direction, away from the robot.")

CONTROL = (
    "**Controls.** The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIP`, each in [-1, 1], in the WORLD frame. "
    "DX/DY/DZ move the gripper's commanded position by 2 cm per unit per step. DROLL/DPITCH/DYAW turn its commanded orientation by "
    "0.1 rad (5.7 degrees) per unit per step about the world x, y and z axes, around the point between the fingertips; leave them at 0 "
    "unless you need to turn the hand (for example DYAW to line the fingers up with an object's faces). GRIP: any positive value closes "
    "the fingers, a negative value -f opens them to fraction f (-1 fully open), 0 keeps them as they are (they take about 5 steps to "
    "move). One step is 50 ms (ManiSkill's 20 Hz control rate). The arm follows the commanded pose through inverse kinematics and "
    "ManiSkill's joint position controller; the commanded position stays within 5 cm of the measured hand (and the orientation within "
    "0.35 rad), so pushing against something stalls instead of winding up. Some orientations are out of the arm's reach (the last "
    "wrist joint turns about 166 degrees each way): turning the fingers by 90 or 180 degrees about the vertical gives the same grasp "
    "on a cube, so prefer the smaller turn. `robo move-to X Y Z [--grip G]` and `robo grip G` also work; they move only the position "
    "and keep the hand's orientation, and `move-to` stops within 1 cm of the point unless you pass a tighter `--tol` (e.g. "
    "`--tol 0.002`).")

HAND = (
    "**Observation.** `robo observe` reports `hand_pos` (the point between the fingertips, metres), `hand_quat` (hand orientation "
    "quaternion w, x, y, z), `hand_down_axis` (unit vector the fingers point along; [0, 0, -1] is straight down), `finger_axis` (unit "
    "vector along which the fingers close), `hand_target_pos` and `hand_target_quat` (the commanded pose the arm is moving to), "
    "`gripper_open` (0 closed .. 1 fully open) and `gripper_width` (distance between the fingers, metres), plus the task fields below. "
    "Every `<object>_quat` is (w, x, y, z); `<object>_yaw_deg` is the object's heading about the vertical (its local x axis, degrees "
    "from +x). `grasped`, where present, is ManiSkill's own grasp test (both fingers pressing on the object). "
    "`robo observe --image` saves a {size}x{size} picture from the `render_camera` view; `--camera base_camera`{hand} gives other views.")

TXT = {
    "PickCube-v1": dict(
        title="Pick up the cube and hold it at the goal", difficulty="easy", tags=["pick-place"],
        goal="Pick up the red cube (4 cm) and hold it so that its centre is at the goal point `goal_pos`, which floats in the air above the table (the green sphere in the images).",
        success="ManiSkill's own PickCube check: the cube's centre is within 2.5 cm of `goal_pos` and the robot is static (every arm joint slower than 0.2 rad/s). Keep holding the cube at the goal when you call `robo done`.",
        fields="`cube_pos`, `cube_quat`, `cube_yaw_deg`, `cube_half_size` (0.02 m), `goal_pos`, `goal_radius` (0.025 m) and `grasped`.",
        oracle="grasp the cube across two faces, carry it to the goal and correct with the observed cube position"),
    "StackCube-v1": dict(
        title="Stack the red cube on the green cube", difficulty="easy", tags=["pick-place", "stacking"],
        goal="Pick up the red cube and put it on top of the green cube (both 4 cm), then let go.",
        success="ManiSkill's own StackCube check: the red cube's centre is within 3.3 cm of the green cube's centre horizontally and 4 cm (+-5 mm) above it, the red cube is at rest, and the gripper is not holding it.",
        fields="`red_cube_pos`, `red_cube_quat`, `red_cube_yaw_deg`, `green_cube_pos`, `green_cube_quat`, `green_cube_yaw_deg`, `cube_half_size` (0.02 m) and `grasped` (the red cube).",
        oracle="grasp the red cube, align it with the green cube, set it down on top and release"),
    "StackPyramid-v1": dict(
        title="Build a three-cube pyramid", difficulty="hard", tags=["pick-place", "stacking", "multi-step"],
        goal="Build a pyramid from the three 4 cm cubes: the red and green cubes side by side on the table, and the blue cube on top, resting on both.",
        success="ManiSkill's own StackPyramid check: the red and green cube centres are within 6.2 cm of each other horizontally; the blue cube is higher than both (by more than 2 cm) and within 6.2 cm of each horizontally; all three are at rest and none is held.",
        fields="`red_cube_pos`, `green_cube_pos`, `blue_cube_pos` with their `_quat` and `_yaw_deg`, and `cube_half_size` (0.02 m).",
        oracle="place the red cube against a face of the green one, then set the blue cube across the pair"),
    "PushCube-v1": dict(
        title="Push the cube into the goal region", difficulty="easy", tags=["pushing", "non-prehensile"],
        goal="Push the blue cube along the table into the red-and-white target region (radius 10 cm) centred at `goal_pos`, in front of it (+x).",
        success="ManiSkill's own PushCube check: the cube's centre is within 10 cm of the target centre in the table plane and the cube is still on the table.",
        fields="`cube_pos`, `cube_quat`, `cube_yaw_deg`, `cube_half_size` (0.02 m), `goal_pos` and `goal_radius` (0.1 m).",
        oracle="close the fingers, lower the hand behind the cube and push it along +x into the target"),
    "PullCube-v1": dict(
        title="Pull the cube into the goal region", difficulty="easy", tags=["pulling", "non-prehensile"],
        goal="Pull the blue cube along the table toward the robot into the red-and-white target region (radius 10 cm) centred at `goal_pos`, which lies behind the cube (-x, on the robot's side).",
        success="ManiSkill's own PullCube check: the cube's centre is within 10 cm of the target centre in the table plane.",
        fields="`cube_pos`, `cube_quat`, `cube_yaw_deg`, `cube_half_size` (0.02 m), `goal_pos` and `goal_radius` (0.1 m).",
        oracle="reach over the cube, lower the closed fingers on its far side and drag it along -x"),
    "PullCubeTool-v1": dict(
        title="Use the L-shaped tool to pull the cube closer", difficulty="hard", tags=["tool-use", "non-prehensile"],
        goal="The blue cube lies out of comfortable reach. Grasp the red L-shaped tool and use its hook to pull the cube toward the robot's base until the cube is less than 0.6 m from the base.",
        success="ManiSkill's own PullCubeTool check: the cube's centre is less than 0.6 m from the robot base (`robot_base_pos`) in the table plane.",
        fields="`cube_pos`, `cube_quat`, `cube_yaw_deg`, `cube_half_size`, `tool_pos` (the end of the handle away from the hook, at the handle's centre line), `tool_quat`, `tool_yaw_deg`, `tool_handle_axis` (unit vector from `tool_pos` along the handle toward the hook end), `tool_hook_end_pos` (the far end of the handle), `tool_handle_length` (0.2 m), `tool_hook_length` (0.05 m, the hook's extent along the handle), `tool_width` (0.05 m; the hook sticks out 0.1 m sideways, to the left of the handle axis when looking along it), `tool_height` (0.05 m), `robot_base_pos` and `grasped` (the tool).",
        oracle="grasp the handle, hook the cube from beyond and drag the tool back toward the base"),
    "PokeCube-v1": dict(
        title="Poke the cube with the peg", difficulty="medium", tags=["tool-use", "non-prehensile"],
        goal="Grasp the blue peg and use its head end to push the red cube into the red-and-white target region (radius 5 cm) centred at `goal_pos`.",
        success="ManiSkill's own PokeCube check: the cube's centre is within 5 cm of the target centre in the table plane and the robot is static (every arm joint slower than 0.2 rad/s).",
        fields="`peg_pos`, `peg_quat`, `peg_yaw_deg` (the peg's long axis), `peg_head_pos` (centre of the head end), `peg_half_length` (0.12 m), `peg_half_width` (0.025 m), `cube_pos`, `cube_quat`, `cube_yaw_deg`, `cube_half_size` (0.02 m), `goal_pos`, `goal_radius` (0.05 m) and `grasped` (the peg).",
        oracle="grasp the peg's tail half and drive its head against the cube toward the target"),
    "PlaceSphere-v1": dict(
        title="Place the sphere in the bin", difficulty="medium", tags=["pick-place"],
        goal="Pick up the blue ball (2 cm radius) and place it in the small square bin, then let go.",
        success="ManiSkill's own PlaceSphere check: the ball's centre is within 5 mm of the bin's centre horizontally and resting on the bin floor (within 5 mm of the right height), the ball is at rest, and the gripper is not holding it.",
        fields="`sphere_pos`, `sphere_quat`, `sphere_radius` (0.02 m), `bin_pos` (centre of the bin floor block), `bin_floor_top_z` (height of the bin floor's top surface), `bin_inner_half_size` (0.02 m: the inside is 4 cm square) and `grasped`.",
        oracle="grasp the ball, lower it into the bin and release"),
    "RollBall-v1": dict(
        title="Roll the ball into the goal region", difficulty="medium", tags=["dynamic", "non-prehensile"],
        goal="Push the blue ball (3.5 cm radius) so that it rolls across the table into the red-and-white target region (radius 10 cm) centred at `goal_pos`, more than a metre away, far out of the arm's reach.",
        success="ManiSkill's own RollBall check: the ball's centre is within 10 cm of the target centre in the table plane. This task uses success mode `first`: the episode ends as solved the moment the ball is over the target (it may roll on afterwards), matching ManiSkill's own success-once evaluation.",
        fields="`ball_pos`, `ball_quat`, `ball_radius` (0.035 m), `ball_vel` (m/s), `goal_pos` and `goal_radius` (0.1 m).",
        oracle="lower the closed fingers behind the ball on the line to the goal and push it through its centre at a steady speed"),
    "LiftPegUpright-v1": dict(
        title="Stand the peg upright", difficulty="hard", tags=["reorientation"],
        goal="A peg (a 24 cm long, 5 cm square bar) lies on its side on the table. Stand it upright on one of its ends and let go.",
        success="ManiSkill's own LiftPegUpright check: the peg's long axis is vertical (within 0.08 rad) and the peg's centre is 12 cm (+-5 mm) above the table, i.e. it stands on an end on the table.",
        fields="`peg_pos` (centre), `peg_quat`, `peg_axis` (unit vector along the long axis), `peg_half_length` (0.12 m), `peg_half_width` (0.025 m), `robot_base_pos` and `grasped`.",
        oracle="grasp the middle, lift, turn the hand 90 degrees about the finger axis, straighten, lower onto the table and release"),
    "PegInsertionSide-v1": dict(
        title="Insert the peg into the side hole", difficulty="hard", tags=["insertion", "precision"],
        goal="Pick up the peg (a square bar, orange head end and white tail end) and insert its orange head end sideways into the hole in the box, at least halfway in.",
        success="ManiSkill's own PegInsertionSide check: the peg's head is inside the hole, no more than 1.5 cm short of the hole centre along the hole axis and within the hole's radius of the axis sideways. The hole has only 3 mm of clearance around the peg.",
        fields="`peg_pos` (centre), `peg_quat`, `peg_yaw_deg`, `peg_axis` (unit vector from the tail toward the head), `peg_head_pos` (centre of the head end face), `peg_half_length`, `peg_radius` (half the peg's width), `hole_pos` (centre of the hole, halfway through the box), `hole_axis` (unit vector along which the peg goes in; the hole's entrance is at `hole_pos` - `peg_half_length` x `hole_axis`), `hole_radius` and `grasped`.",
        oracle="grasp the tail half, turn the peg parallel to the hole axis, centre it in front of the hole and push it in a centimetre at a time"),
    "PlugCharger-v1": dict(
        title="Plug the charger into the receptacle", difficulty="hard", tags=["insertion", "precision"],
        goal="Pick up the charger (a small white block with two metal pins) and plug its pins into the wall receptacle that stands on the table.",
        success="ManiSkill's own PlugCharger check: the charger's pose is within 5 mm and 0.2 rad of the fully plugged-in pose (`goal_pos`, `goal_quat`). The pin slots leave only 0.5 mm of clearance.",
        fields="`charger_pos` (the point where the pins leave the base, on the pins' centre line), `charger_quat`, `charger_yaw_deg`, `charger_plug_axis` (unit vector along the pins, pointing out of the base), `charger_base_pos` (centre of the 4 x 3 x 2.4 cm base block), `charger_base_half_size`, `goal_pos` and `goal_quat` (where `charger_pos` and the charger's orientation must end up), `goal_plug_axis` (the pin direction at the goal, pointing into the receptacle), `receptacle_pos`, `receptacle_quat`, `receptacle_yaw_deg` and `grasped` (the charger).",
        oracle="grasp the back of the base with the hand tilted back, align the pins with the slots and push in along the slot axis while re-centring"),
}


def build(tid: str) -> tuple[dict, str]:
    t = TASKS[tid]
    env = t["env"]
    x = TXT[env]
    mode = t.get("success_mode", "final")
    size = 384
    cams = ["render_camera", "base_camera"] + (["hand_camera"] if env in WRISTCAM else [])
    judged = ("" if mode == "first" else
              " Success is judged by the episode server after you call `robo done` and the robot has held still for about 10 steps, so the result must last.")
    body = (f"# {x['title']} (ManiSkill3 {env})\n\n"
            + SCENE.format(env=env, base=BASE_ROLL if env == "RollBall-v1" else BASE) + "\n\n"
            f"**Goal:** {x['goal']}\n\n**Success:** {x['success']}{judged}\n\n"
            f"**Task fields in `robo observe`:** {x['fields']}\n\n"
            + CONTROL + "\n\n"
            + HAND.format(size=size, hand=", `--camera hand_camera` (on the wrist)" if env in WRISTCAM else "")
            + f"\n\nThe step budget is {t['max_steps']} steps ({t['max_steps'] * .05:.0f} s of simulated time).\n\n"
            + ROBO_USAGE)
    meta = {
        "task": {"name": f"robouse/{tid}", "description": f"{x['title']} (ManiSkill3 {env}, Franka Panda, CPU physics)."},
        "metadata": {"source_benchmark": "ManiSkill3 (Hao Su Lab / Hillbot; mani-skill 3.0.1, SAPIEN 3.0.3)", "source_task": env,
                     "suite": "maniskill", "category": "manipulation", "difficulty": x["difficulty"],
                     "tags": ["sapien", "maniskill", "panda", "tabletop", *x["tags"]],
                     "success_rule": f"ManiSkill {env} evaluate()['success']",
                     "reference_solution": f"scripted end-effector controller: {x['oracle']}"},
        "agent": {"timeout_sec": 1800},
        "verifier": {"timeout_sec": 120},
        "robouse": {"id": tid, "backend": "maniskill", "env": tid, "seed": int(t["seed"]), "max_steps": int(t["max_steps"]),
                    "camera": "render_camera", "cameras": cams, "skills": True, "success_mode": mode, "obs_mode": "state"},
    }
    return meta, body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "tasks" / "maniskill"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for tid in TASKS:
        meta, body = build(tid)
        oracle = ("#!/bin/bash\n# Reference solution: scripted end-effector controller (maniskill_oracles.py) that drives the robot only\n"
                  f"# through the robo socket and reads only the public observation.\nset -euo pipefail\n"
                  f"python -m robouse.oracle --backend maniskill --env {tid}\n")
        write_task(out / tid, meta, body, oracle, VERIFY_SH)
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
