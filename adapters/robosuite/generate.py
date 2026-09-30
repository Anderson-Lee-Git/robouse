"""robosuite (Zhu et al.; ARISE / Stanford, v1.5) -> robouse tasks.

Realistic robot arms (Franka Panda, UR5e, Kinova Gen3, KUKA IIWA, Rethink Sawyer; one or two arms) in robosuite's
MuJoCo manipulation scenes, driven through robosuite's BASIC composite controller (OSC_POSE end-effector deltas plus
the gripper). Placement randomisation is robosuite's own, fixed per task by the `seed` in the `robouse:` block.
Success is robosuite's own `_check_success()`. The backend is `robouse.backends.robosuite_backend`; reference
solutions (`robouse.backends.robosuite_oracle`) drive the robot only through the robo socket.

Usage: python adapters/robosuite/generate.py --out tasks/robosuite
Needs robosuite 1.5 (see docs/suites/robosuite.md for the isolated install next to LIBERO's robosuite 1.4).
"""

from __future__ import annotations

import argparse
import shutil
import textwrap
from pathlib import Path

from robouse.core.prompts import ROBO_USAGE
from robouse.tasks import write_task

VERIFY = """\
#!/bin/bash
# Verifier: the episode server already judged success with robosuite's own _check_success(); copy its verdict.
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
# Reference solution: scripted end-effector controller ({what}) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env {solver}
"""

ROBOT_NAMES = {
    "Panda": "Franka Emika Panda (7-DoF) with its parallel-jaw gripper",
    "UR5e": "Universal Robots UR5e (6-DoF) with a Robotiq 2F-85 gripper",
    "Kinova3": "Kinova Gen3 (7-DoF) with a Robotiq 2F-85 gripper",
    "IIWA": "KUKA LBR IIWA 7 (7-DoF) with a Robotiq 2F-140 gripper",
    "Sawyer": "Rethink Robotics Sawyer (7-DoF) with the Rethink electric parallel gripper",
}

HAND_FIELDS = (
    "`hand_pos` (the gripper's grasp point between the fingertips, metres), `hand_quat` (hand orientation quaternion x, y, z, w; "
    "about [1, 0, 0, 0] when the gripper points straight down), `gripper_open` (distance between the two finger pads in metres: "
    "largest when open, smallest when closed on nothing, in between when holding something), `gripper_yaw_deg` (direction of the "
    "line through the two fingertips in the table plane, degrees from +x, in [-90, 90); the fingers close along this line)"
)
TWO_HAND_FIELDS = (
    "for each robot i in 0, 1: `roboti_hand_pos`, `roboti_hand_quat` (x, y, z, w), and, if it has a gripper, "
    "`roboti_gripper_open` (finger-pad distance, metres) and `roboti_gripper_yaw_deg` (direction of the fingertip line in the "
    "table plane, degrees from +x, in [-90, 90))"
)
YAW_NOTE = "Every `<object>_quat` (x, y, z, w) comes with `<object>_yaw_deg`, the object's heading about the vertical axis (its local x axis, degrees from +x)."

# success-mode reasons
FIRST_LIFT = (
    "first",
    "Lifting is a transient act: robosuite's evaluation (robomimic rollouts) ends an episode at the first "
    "step where the object is above the threshold, so the episode is scored the same way.",
)
FINAL_DOOR = (
    "final",
    "The door must stay open: success is judged after `robo done` and a 10-step settle with the robot "
    "holding still (it may keep holding the handle), so a door that swings back shut does not count.",
)
FINAL_PEG = (
    "final",
    "The peg must stay through the hole: success is judged after `robo done` and a 10-step settle with "
    "both arms holding still.",
)
FINAL_HANDOVER = (
    "final",
    "The handover must be complete and stable: success is judged after `robo done` and a 10-step "
    "settle, so robot1 must really hold the hammer by its handle with robot0 clear of it.",
)
FINAL_PLACE = (
    "final",
    "A placement must last: success is judged after `robo done` and a 10-step settle, with the robot "
    "holding still, so the object has to stay where it was put (and robosuite also requires the gripper to "
    "have let go and moved away).",
)


def T(**kw):
    return kw


TASKS = [
    # ---- Lift: one cube, five embodiments -------------------------------------------------------------------------
    *[
        T(
            id=f"robosuite-lift-{r.lower()}",
            env="Lift",
            robots=r,
            seed=s,
            max_steps=400,
            camera="agentview",
            mode=FIRST_LIFT,
            difficulty="easy" if r == "Panda" else "medium",
            category="manipulation",
            solver="Lift:norot" if r == "Sawyer" else "Lift",
            title=f"Lift the cube ({r})",
            desc=f"Pick up the red cube from the table with a {r} arm.",
            goal="Pick up the red cube from the table and lift it. The task is solved the moment the cube's centre is more "
            "than 4 cm above the table top (robosuite's Lift check); the episode then ends by itself.",
            fields=f"{HAND_FIELDS}; `cube_pos`, `cube_quat`, `cube_yaw_deg` (the cube, about 4 cm on a side); `table_height` "
            f"(z of the table top). {YAW_NOTE}",
            notes="Grasp the cube from above with the fingers closing on two opposite faces; a lift of a few centimetres is enough."
            + (
                " This Sawyer's hand does not point exactly straight down at rest; aggressive orientation commands can "
                "drive its wrist into an awkward pose."
                if r == "Sawyer"
                else ""
            ),
            oracle_what="grasp from above with the fingers across two faces, then lift"
            + (" (position control only)" if r == "Sawyer" else ""),
        )
        for r, s in (("Panda", 0), ("UR5e", 1), ("Kinova3", 2), ("IIWA", 3), ("Sawyer", 4))
    ],
    # ---- Stack ----------------------------------------------------------------------------------------------------
    *[
        T(
            id=f"robosuite-stack-{r.lower()}",
            env="Stack",
            robots=r,
            seed=s,
            max_steps=400,
            camera="agentview",
            mode=FINAL_PLACE,
            difficulty="medium",
            category="manipulation",
            solver="Stack",
            title=f"Stack the cubes ({r})",
            desc="Put the red cube on top of the green cube.",
            goal="Put the red cube (cubeA, 4 cm) on top of the green cube (cubeB, 5 cm) and let go. robosuite's Stack check: the red "
            "cube is lifted off the table, touching the green cube, and no longer held by the gripper.",
            fields=f"{HAND_FIELDS}; `cubea_pos`, `cubea_quat`, `cubea_yaw_deg` (red cube A), `cubeb_pos`, `cubeb_quat`, `cubeb_yaw_deg` "
            f"(green cube B); `table_height`. {YAW_NOTE}",
            notes="Open the gripper after placing and move the hand up before `robo done`.",
            oracle_what="pick the red cube, place it on the green cube, release, retreat",
        )
        for r, s in (("Panda", 0), ("UR5e", 1))
    ],
    # ---- PickPlace: the four grocery objects -----------------------------------------------------------------------
    *[
        T(
            id=f"robosuite-pickplace-{o}-{r.lower()}",
            env=f"PickPlace{o.capitalize()}",
            robots=r,
            seed=s,
            max_steps=400,
            camera="agentview",
            mode=FINAL_PLACE,
            difficulty=d,
            category="manipulation",
            solver=f"PickPlace{o.capitalize()}",
            title=f"Put the {o} in its bin ({r})",
            desc=f"Move the {o} from the bin on the robot's right into its compartment of the divided bin on its left.",
            goal=f"Pick up the {what} from the bin on the robot's right (bin 1, at -y) and put it into its target compartment of the "
            f"divided bin on the robot's left (bin 2, at +y). robosuite's PickPlace check: the {o}'s centre lies inside the "
            f"target compartment (x inside `target_bin_x_range`, y inside `target_bin_y_range`, z between `bin_floor_z` and "
            f"`bin_floor_z` + 0.1) and the gripper is at least about 4 cm away from it.",
            fields=f"{HAND_FIELDS}; `{o}_pos`, `{o}_quat`, `{o}_yaw_deg` (the {o}; {size}); `target_bin_center`, "
            f"`target_bin_x_range`, `target_bin_y_range` (the target compartment), `bin_floor_z` (z of the bins' floor). {YAW_NOTE}",
            notes="Lift the object well above the bin walls (z around 1.05 or higher) before carrying it over; release it low inside "
            "the compartment, then move the hand up and away before `robo done`.",
            oracle_what=f"grasp the {o} from above, carry it over the target compartment at a safe height, lower, release, retreat",
        )
        for o, r, s, d, what, size in (
            ("can", "Panda", 0, "medium", "soda can", "a cylinder about 5 cm wide and 12 cm tall"),
            (
                "milk",
                "Panda",
                1,
                "medium",
                "milk carton",
                "about 5 x 5 x 16 cm; its reported position is about 8 cm above its bottom",
            ),
            ("bread", "Panda", 2, "medium", "loaf of bread", "about 6 x 6 cm, low"),
            (
                "cereal",
                "Panda",
                3,
                "hard",
                "cereal box",
                "about 8 x 6 x 13 cm; the fingers only fit across its 6 cm side, which is the box's local y axis",
            ),
            ("can", "Kinova3", 4, "medium", "soda can", "a cylinder about 5 cm wide and 12 cm tall"),
        )
    ],
    # ---- NutAssembly -----------------------------------------------------------------------------------------------
    *[
        T(
            id=f"robosuite-nut-{k}-panda",
            env=f"NutAssembly{k.capitalize()}",
            robots="Panda",
            seed=s,
            max_steps=500,
            camera="agentview",
            mode=FINAL_PLACE,
            difficulty="hard",
            category="manipulation",
            solver=f"NutAssembly{k.capitalize()}",
            title=f"Put the {k} nut on its peg",
            desc=f"Fit the {k} nut over the {k} peg.",
            goal=f"Pick up the {k} nut by its handle and fit it over the {k} peg so that it slides down around the peg to the table. "
            f"robosuite's NutAssembly check: the nut's centre is within 3 cm of the peg's axis in x and y, below "
            f"`table_height` + 0.05, and the gripper is at least about 4 cm away from it."
            + (
                " The square nut's hole only fits the square peg when the nut is turned to match it (the peg's faces are "
                "aligned with the x and y axes)."
                if k == "square"
                else ""
            ),
            fields=f"{HAND_FIELDS}; `{k}nut_pos`, `{k}nut_quat`, `{k}nut_yaw_deg` (the nut's centre, i.e. its hole; the nut's local x axis "
            f"points from the hole toward the handle), `{k}nut_handle_pos` (the flat handle tab, about 5.4 cm from the centre); "
            f"`square_peg_pos`, `round_peg_pos` (the two pegs; use the {k} one); `table_height`. {YAW_NOTE}",
            notes="Holding the nut by its handle, the hole hangs about 5 cm from the hand, so align the nut's centre (not the hand) "
            "over the peg. The pegs are near the far edge of the robot's reach: reaching past them is hard, so turn the nut so "
            "its handle points toward the robot or sideways. Lower it slowly; if it jams on the peg top, lift and re-centre.",
            oracle_what="grasp the handle, turn the nut so the handle faces the robot or sideways, servo the nut's centre over the peg, "
            "lower, release, retreat",
        )
        for k, s in (("square", 2), ("round", 3))
    ],
    # ---- Door ------------------------------------------------------------------------------------------------------
    *[
        T(
            id=f"robosuite-door-{r.lower()}",
            env="Door",
            robots=r,
            seed=s,
            max_steps=400,
            camera="sideview",
            mode=FINAL_DOOR,
            difficulty="hard",
            category="articulated",
            solver="Door",
            title=f"Open the door ({r})",
            desc="Turn the door's lever handle to release the latch, then pull the door open.",
            goal="Open the door. It is latched: first turn its lever handle far enough to release the latch, then swing the door "
            "open toward the robot. robosuite's Door check: the hinge angle `hinge_qpos` is above 0.3 rad (the hinge stops at "
            "0.4 rad). The door must still be open when the robot stops after `robo done`.",
            fields=f"{HAND_FIELDS}; `door_pos` (centre of the door panel), `handle_pos` (the end of the lever handle), `hinge_qpos` "
            f"(door opening angle, radians, 0 = closed), `handle_qpos` (lever rotation, radians; it is spring-loaded back "
            f"to 0), `door_hinge_pos` (a point on the door's vertical hinge axis; the door swings about it); `table_height`.",
            notes="The lever sits on the robot's side of the door; the latch only releases once the lever has turned past about "
            "1.2 rad, and it catches again if the lever springs back before the door has opened a little. The handle end "
            "moves on a circle about the hinge as the door opens, so pull along that circle rather than in a straight line.",
            oracle_what="grasp the lever from above, turn it along its arc until the latch releases, pull along the door's arc",
        )
        for r, s in (("Panda", 1), ("IIWA", 2))
    ],
    # ---- Wipe ------------------------------------------------------------------------------------------------------
    T(
        id="robosuite-wipe-panda",
        env="Wipe",
        robots="Panda",
        seed=0,
        max_steps=600,
        camera="agentview",
        mode=(
            "first",
            "Wiping is monotone (a wiped marker never comes back) and robosuite's Wipe environment itself "
            "terminates the episode at the first step where every marker is wiped.",
        ),
        difficulty="hard",
        category="contact",
        solver="Wipe",
        title="Wipe the dirt off the table",
        desc="Wipe a line of dirt off the table with a sponge-like tool.",
        goal="Wipe all the dirt (100 small markers along a line on the table) off the table with the wiping tool mounted on the "
        "arm. A marker counts as wiped when the tool's bottom face passes over it while pressed flat on the table. "
        "robosuite's Wipe check: every marker is wiped. The episode ends by itself when the last marker goes.",
        fields="`hand_pos` (the tool's reference point, a few millimetres above the middle of its face, metres), `hand_quat` (x, y, z, w); `markers_left`, `dirt_markers_xy` "
        "(x, y of every marker still on the table), `proportion_wiped`, `wipe_centroid` and `wipe_radius` (centre and "
        "spread of the remaining dirt), `hand_force_N` (force on the tool, newtons; it rises when the tool presses on the "
        "table); `table_height`.",
        notes="The action has 6 numbers (there is no gripper). Keep the tool flat (pointing straight down) and pressed lightly "
        "onto the table while sweeping; wiping does not count while any other part of the arm touches the table or a "
        "joint is at its limit. `move_to` is available; `grip` is not.",
        oracle_what="press the tool onto the table, then sweep to the nearest remaining marker, repeatedly",
    ),
    # ---- two arms --------------------------------------------------------------------------------------------------
    *[
        T(
            id=f"robosuite-twoarm-lift-{r.lower()}",
            env="TwoArmLift",
            robots=[r, r],
            env_configuration="opposed",
            seed=s,
            max_steps=400,
            camera="frontview",
            mode=FIRST_LIFT,
            difficulty="hard",
            category="bimanual",
            solver="TwoArmLift",
            title=f"Lift the pot with two arms ({r})",
            desc="Two robots, facing each other across the table, lift a pot by its two handles.",
            goal="Lift the pot together: robot0 holds `handle0`, robot1 holds `handle1`. robosuite's TwoArmLift check: the pot's "
            "bottom is more than 10 cm above the table. The episode ends by itself at that moment.",
            fields=f"{TWO_HAND_FIELDS}; `pot_pos`, `pot_quat`, `pot_yaw_deg`; `handle0_pos` (robot0's handle), `handle1_pos` "
            f"(robot1's handle); `table_height`. {YAW_NOTE}",
            notes="Each handle is a bar; close the fingers across it (the fingertip line along the direction from the pot's centre "
            "to that handle). Lift both hands at the same rate, or the pot tips.",
            oracle_what="both arms grasp their handles from above, then rise together",
        )
        for r, s in (("Panda", 0), ("IIWA", 1))
    ],
    T(
        id="robosuite-twoarm-peginhole-panda",
        env="TwoArmPegInHole",
        robots=["Panda", "Panda"],
        env_configuration="opposed",
        seed=0,
        max_steps=500,
        camera="frontview",
        mode=FINAL_PEG,
        difficulty="hard",
        category="bimanual",
        solver="TwoArmPegInHole",
        title="Put the peg through the hole (two arms)",
        desc="One robot holds a peg, the other a plate with a hole; get the peg through the hole.",
        goal="Robot0 holds a peg (a cylinder fixed to its hand) and robot1 holds a square plate with a hole (fixed to its hand). "
        "Bring them together so the peg passes through the hole. robosuite's TwoArmPegInHole check: the peg's axis is nearly "
        "parallel to the hole's axis (|cos| > 0.95), the peg's centre is within 6 cm of the hole's axis, and it sits between "
        "12 cm in front of and 14 cm behind the hole. Both must still hold after `robo done`.",
        fields=f"{TWO_HAND_FIELDS} (neither robot has a gripper); `peg_pos` (centre of the peg), `peg_axis` (unit vector along "
        f"the peg), `peg_quat`, `hole_pos`, `hole_quat`, `hole_center` (centre of the hole), `hole_axis` (unit normal of the "
        f"plate through the hole), and robosuite's own alignment numbers: `peg_hole_cos` (|cos| of the angle between the "
        f"two axes), `peg_hole_d` (distance of the peg's centre from the hole's axis, m), `peg_hole_t` (position of the "
        f"hole's centre along the peg's axis relative to the peg's centre, m).",
        notes="The action has 12 numbers: 6 for robot0, then 6 for robot1 (no grippers). At the start the peg points down and the "
        "plate stands upright, so the axes are about 90 degrees apart; turning one wrist the whole way is hard, so share the "
        "turn between the two arms.",
        oracle_what="both arms turn about 45 degrees to a shared axis, then robot0 lines the peg up and pushes it through",
    ),
    T(
        id="robosuite-twoarm-handover-panda",
        env="TwoArmHandover",
        robots=["Panda", "Panda"],
        env_configuration="opposed",
        seed=2,
        max_steps=700,
        camera="frontview",
        mode=FINAL_HANDOVER,
        difficulty="hard",
        category="bimanual",
        solver="TwoArmHandover",
        title="Hand over the hammer (two arms)",
        desc="Robot0 picks up a hammer and hands it to robot1.",
        goal="The hammer lies on the table on robot0's side. Robot0 picks it up and hands it to robot1. robosuite's "
        "TwoArmHandover check: robot1 grasps the hammer's handle, robot0 no longer touches the hammer, and the hammer is "
        "more than 10 cm above the table. This must still hold after `robo done`.",
        fields=f"{TWO_HAND_FIELDS}; `hammer_pos` (centre of the handle), `hammer_quat`, `hammer_yaw_deg`, `handle_pos` (same "
        f"point), `hammer_handle_axis` (unit vector along the handle, pointing toward the head), `hammer_head_pos`, "
        f"`hammer_handle_length` (m); `table_height`.",
        notes="Robot0 stands at -y and robot1 at +y. Both robots must hold the handle at the same time for a moment, so leave "
        "room for two hands on it. Close the fingers across the handle. Move robot1 in from above, not through the "
        "hammer.",
        oracle_what="robot0 grasps its end of the handle and brings the hammer to the middle, robot1 grasps the other end from "
        "above, robot0 releases and backs away",
    ),
]


def instruction(t: dict) -> str:
    robots = t["robots"] if isinstance(t["robots"], list) else [t["robots"]]
    two = len(robots) > 1
    who = (
        f"Two {ROBOT_NAMES[robots[0]]} arms face each other across a table: robot0 on the -y side, robot1 on the +y side."
        if two
        else f"A {ROBOT_NAMES[robots[0]]} works at a table; its base is at the -x end, facing +x."
    )
    mode, why = t["mode"]
    ending = (
        "The episode ends as solved the moment the check first passes (you do not need to call `robo done` then). "
        if mode == "first"
        else "Call `robo done` when finished; the check is made after the robot then holds still for 10 steps, so the result must last. "
    )
    if t["env"] == "Wipe":
        action = (
            "The action has 6 numbers: `robo act DX DY DZ DROLL DPITCH DYAW`, each in [-1, 1]: robosuite's OSC_POSE end-effector "
            "command, 20 steps per second, in the world frame. DX/DY/DZ = 1.0 asks for a 5 cm move (held at 1.0 the hand "
            "travels about 1.1 cm per step); DROLL/DPITCH/DYAW rotate the hand about the world x/y/z axes (1.0 asks for 0.5 rad)."
        )
    elif t["env"] == "TwoArmPegInHole":
        action = (
            "The action has 12 numbers: robot0's `DX DY DZ DROLL DPITCH DYAW`, then robot1's, each in [-1, 1]: robosuite's "
            "OSC_POSE end-effector commands, 20 steps per second, all in the world frame. DX/DY/DZ = 1.0 asks for a 5 cm move "
            "(held at 1.0 a hand travels about 1.1 cm per step); DROLL/DPITCH/DYAW rotate that hand about the world x/y/z "
            "axes (1.0 asks for 0.5 rad)."
        )
    elif two:
        action = (
            "The action has 14 numbers: robot0's `DX DY DZ DROLL DPITCH DYAW GRIP`, then robot1's, each in [-1, 1]: robosuite's "
            "OSC_POSE end-effector commands plus the gripper, 20 steps per second, all in the world frame (the same frame for "
            "both robots). DX/DY/DZ = 1.0 asks for a 5 cm move (held at 1.0 a hand travels about 1.1 cm per step); "
            "DROLL/DPITCH/DYAW rotate that hand about the world x/y/z axes (1.0 asks for 0.5 rad); GRIP +1 closes, -1 opens, "
            "0 keeps the fingers as they are (they move over about 5 steps)."
        )
    else:
        action = (
            "The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIP`, each in [-1, 1]: robosuite's OSC_POSE "
            "end-effector command plus the gripper, 20 steps per second, in the world frame. DX/DY/DZ = 1.0 asks for a 5 cm "
            "move (held at 1.0 the hand travels about 1.1 cm per step); DROLL/DPITCH/DYAW rotate the hand about the world "
            "x/y/z axes (1.0 asks for 0.5 rad; leave them at 0 unless you need to turn the hand, e.g. DYAW to line the "
            "fingers up with an object); GRIP +1 closes, -1 opens, 0 keeps the fingers as they are (they move over about 5 steps)."
        )
    skills = (
        "`robo move-to` and `robo grip` are not available (two robots); use `robo act`."
        if two
        else "`robo move-to X Y Z [--grip G]` and `robo grip G` are available; they move only the position and keep the hand's orientation "
        "(it can drift slowly under load; correct it with DROLL/DPITCH/DYAW)."
        if t["env"] != "Wipe"
        else "`robo move-to X Y Z` is available (it keeps the tool's orientation); `robo grip` is not."
    )
    cams = f"`robo observe --image` saves the `{t['camera']}` camera; add `--camera robot0_eye_in_hand` for the wrist camera. Images are 320x320."
    body = f"""\
    # {t['title']}

    {who} The scene is robosuite's `{t['env']}` environment (MuJoCo).

    **Goal:** {t['goal']}

    {ending}

    ## This robot

    - {action}
    - {skills}
    - World frame, metres: +x points away from the {'table edge between the robots' if two else "robot's base"}, +y to the {'robot1 side' if two else "robot's left"}, +z up.
    - `robo observe` fields: {t['fields']}
    - {cams}
    - The step budget is {t['max_steps']} steps.
    - {t['notes']}

    """
    return textwrap.dedent(body) + ROBO_USAGE


def write(t: dict, out: Path) -> None:
    mode, why = t["mode"]
    robots = t["robots"] if isinstance(t["robots"], list) else [t["robots"]]
    tags = sorted({r.lower() for r in robots}) + ["mujoco", "robosuite", "two-arm" if len(robots) > 1 else "single-arm"]
    meta = {
        "task": {"name": f"robouse/{t['id']}", "description": t["desc"]},
        "metadata": {
            "source_benchmark": "robosuite (Zhu et al.)",
            "source_task": t["env"],
            "suite": "robosuite",
            "category": t["category"],
            "difficulty": t["difficulty"],
            "tags": tags,
            "robots": robots,
            "success_rule": f"robosuite {t['env']}._check_success()",
            "success_mode_reason": why,
            "reference_solution": f"scripted end-effector controller: {t['oracle_what']}",
        },
        "agent": {"timeout_sec": 1800 if t["max_steps"] > 400 else 1200},
        "verifier": {"timeout_sec": 120},
        "robouse": {
            "id": t["id"],
            "backend": "robosuite",
            "env": t["env"],
            "robots": t["robots"],
            **({"env_configuration": t["env_configuration"]} if t.get("env_configuration") else {}),
            "controller": "BASIC",
            "seed": t["seed"],
            "max_steps": t["max_steps"],
            "camera": t["camera"],
            "cameras": [t["camera"], "robot0_eye_in_hand"],
            "image_size": 320,
            "skills": len(robots) == 1,
            "success_mode": mode,
            "obs_mode": "state",
        },
    }
    write_task(out / t["id"], meta, instruction(t), ORACLE.format(what=t["oracle_what"], solver=t["solver"]), VERIFY)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks/robosuite")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for t in TASKS:
        write(t, out)
        print(f"{t['id']:<36} {t['env']:<18} seed {t['seed']}  {t['mode'][0]:<5} budget {t['max_steps']}")
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
