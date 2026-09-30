"""Franka Kitchen (Gymnasium-Robotics `FrankaKitchen-v1`) -> Robo Use tasks (suite "kitchen").

Seven single-subtask tasks (microwave, kettle, bottom burner, top burner, light switch, slide cabinet, hinge cabinet) and
three four-subtask tasks (the Minari/D4RL kitchen-complete and kitchen-mixed goal sets, and a burners + cabinets set).
The task list lives in `robouse.backends.kitchen.TASKS`; the backend adds an end-effector interface over the upstream
joint-velocity action. Reference solutions drive the robot only through the robo socket (`oracle_main` in the backend).

Usage: python adapters/kitchen/generate.py [--out tasks/kitchen]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.kitchen.backend import TASKS
from robouse.core.prompts import ROBO_USAGE
from robouse.tasks import write_task

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

# subtask -> (goal sentence, how it is judged, what the agent should know about the mechanism)
SUB = {
    "microwave": (
        "open the microwave door",
        "`subtasks.microwave.joints` is the door hinge angle (rad; 0 = closed, negative = open, limit -2.09); the goal is -0.75, so the door angle must end between -0.45 and -1.05 rad",
        "The microwave stands on the counter to the robot's left. Its door hinges on a vertical axis at `microwave_hinge_pos` (the door's left edge) and swings toward the robot; `microwave_handle_pos` is the middle of its vertical bar handle.",
    ),
    "kettle": (
        "move the kettle onto the back-left burner",
        "`subtasks.kettle.joints` is the kettle's position (x, y, z) followed by its orientation quaternion (w, x, y, z); the goal is position `kettle_goal_pos` = [-0.23, 0.75, 1.62] with orientation [0.99, 0, 0, -0.06] (upright, as it starts), and the whole 7-number vector must be within 0.3 of it (so the kettle must stand upright within about 0.25 m of the goal)",
        "The kettle stands on the front-left burner. Its handle (`kettle_handle_pos`) is a horizontal bar on top that runs along x, about 26 cm above the kettle's base; the kettle is about 25 cm wide. `kettle_pos` is the kettle's base position and `kettle_quat` its orientation.",
    ),
    "bottom burner": (
        "turn on the bottom burner (the lower-left knob)",
        "`subtasks.bottom_burner.joints` is the knob angle (rad; 0 = off, turning it on makes it negative, limit -1.57) and the burner's own switch position; the goal is [-0.88, -0.01], so the knob must be turned to between about -0.58 and -1.18 rad",
        "The four oven knobs are on the vertical panel above the stove, facing the robot (-y); each is a disc with a vertical grip bar (about 3 cm wide, 10 cm tall, 4 cm deep; the front face of the bar is at `..._knob_pos`). A knob turns about the y axis: turning it on is a clockwise turn as seen from the robot (the top of the bar moves toward +x).",
    ),
    "top burner": (
        "turn on the top burner (the upper-left knob)",
        "`subtasks.top_burner.joints` is the knob angle (rad; 0 = off, turning it on makes it negative, limit -1.57) and the burner's own switch position; the goal is [-0.92, -0.01], so the knob must be turned to between about -0.62 and -1.22 rad",
        "The four oven knobs are on the vertical panel above the stove, facing the robot (-y); each is a disc with a vertical grip bar (about 3 cm wide, 10 cm tall, 4 cm deep; the front face of the bar is at `..._knob_pos`). A knob turns about the y axis: turning it on is a clockwise turn as seen from the robot (the top of the bar moves toward +x).",
    ),
    "light switch": (
        "turn on the light switch",
        "`subtasks.light_switch.joints` is the switch lever angle (rad; 0 = off, limit -0.7) and the light's own position; the goal is [-0.69, -0.05], so the lever must be turned to below about -0.4 rad",
        "The light switch is a small lever on the panel left of the knobs; `light_switch_pos` is its tip. The lever pivots about a vertical axis 7 cm behind its tip; turning it on swings the tip toward -x (to the robot's left).",
    ),
    "slide cabinet": (
        "open the sliding cabinet door",
        "`subtasks.slide_cabinet.joints` is how far the door has slid (m; 0 = closed, limit 0.44); the goal is 0.37, so it must be open by more than 0.07 m",
        "The sliding cabinet is the wall cabinet on the right; its door slides along +x. `slide_handle_pos` is the middle of its vertical bar handle.",
    ),
    "hinge cabinet": (
        "open the hinged wall cabinet (its right-hand door)",
        "`subtasks.hinge_cabinet.joints` is the angle of the left door and of the right door (rad; 0 = closed, the right door opens to positive angles, limit 1.57); the goal is [0, 1.45], so the right door must be open past about 1.15 rad while the left door stays shut",
        "The hinged cabinet is the wall cabinet on the left, with two doors. Its right-hand door hinges on a vertical axis at `hinge_cabinet_hinge_pos` (the door's right edge) and swings toward the robot; `hinge_handle_pos` is the middle of that door's vertical bar handle.",
    ),
}

TITLES = {
    "kitchen-complete": "Kitchen: microwave, kettle, light, slide cabinet",
    "kitchen-mixed": "Kitchen: microwave, kettle, bottom burner, light",
    "kitchen-burners-cabinets": "Kitchen: both burners and both cabinets",
}

SCENE = (
    "A 7-joint Franka Panda arm with a two-finger parallel gripper stands in front of a kitchen (adapted from Gymnasium-Robotics `FrankaKitchen-v1`, "
    "the Relay Policy Learning / D4RL kitchen). World frame in metres: the robot's base is at (0, 0, 1.8); +y points from the robot into the kitchen, "
    "+x to the robot's right, +z up. The stove top is at about z = 1.6, the knob panel at y = 0.64 and the wall cabinets at z = 2.6. In front of the "
    "robot are: a microwave (left), the stove with four burners and a kettle, the oven knob panel with a light switch, and two wall cabinets above "
    "(hinged on the left, sliding on the right)."
)

CONTROL = (
    "**This task uses a 5-number action.** `robo act DX DY DZ DROLL GRIP [--repeat N]`, each in [-1, 1], one step = 80 ms: DX DY DZ move the "
    "gripper's commanded position by up to 3 cm per unit along world x, y, z; DROLL turns the gripper about its pointing axis by up to 0.1 rad "
    "(5.7 degrees) per unit (positive = clockwise as seen from the robot, the top of the gripper moving toward +x); GRIP +1 closes the fingers, -1 "
    "opens them. The backend turns this into joint motions with inverse kinematics; the commanded position never runs more than 6 cm ahead of the "
    "gripper, so pushing against furniture stalls rather than winding up. The gripper always points straight ahead (+y), horizontal. At roll 0 "
    "its two fingers are side by side along x (they close left-right, suited to vertical bars); at roll 1.57 (90 degrees) they are above and below "
    "each other (they close top-bottom, suited to horizontal bars). The roll is limited to +-1.6 rad. `robo move-to X Y Z [--grip G]` moves "
    "`hand_pos` to a point in a straight line at the current roll, and `robo grip G` holds position and sets the fingers; the `DX DY DZ GRIP` "
    "form in the general instructions below does not apply here (use 5 numbers). The arm cannot pass through furniture, and a move can stall if "
    "the arm or fingers touch something; check `hand_pos` after each move."
)

OBSERVE = (
    "In `robo observe`: `hand_pos` is the grasp centre between the finger pads (the fingertips reach about 5 cm further along +y; the fingers are "
    "about 2 cm thick and open to 8 cm), `hand_target` the commanded position, `hand_roll` / `hand_roll_target` the measured and commanded roll "
    "(rad), `gripper_open` (0 closed .. 1 open) and `gripper_width` (m), `arm_joints` the seven arm joint angles (rad). Landmarks (world "
    "positions, m): `microwave_handle_pos`, `microwave_hinge_pos`, `kettle_handle_pos`, `kettle_pos`, `kettle_quat` (w, x, y, z), "
    "`kettle_goal_pos`, `bottom_burner_knob_pos`, `top_burner_knob_pos`, `light_switch_pos`, `slide_handle_pos`, `hinge_handle_pos`, "
    "`hinge_cabinet_hinge_pos`. Under `subtasks`, each of the seven kitchen subtasks lists its current joint values (`joints`), its `goal`, "
    "`distance` (the norm of joints - goal), `complete` (distance < 0.3) and `required` (whether this task asks for it); `goals_complete` "
    "counts the required ones that are complete now."
)


def build(task_id: str, subs: list[str]) -> tuple[dict, str]:
    single = len(subs) == 1
    goals = [SUB[s][0] for s in subs]
    if single:
        title = "Kitchen: " + goals[0][0].upper() + goals[0][1:]
        goal = goals[0][0].upper() + goals[0][1:] + "."
        desc = goal
    else:
        title = TITLES[task_id]
        goal = "Do all of these, in any order: " + "; ".join(goals) + "."
        desc = "In the kitchen, " + ", ".join(goals[:-1]) + " and " + goals[-1] + "."
    max_steps = 500 if single else 1500
    judged = "\n".join(f"- {s}: {SUB[s][1]}." for s in subs)
    notes = []
    for s in subs:
        if SUB[s][2] not in notes:
            notes.append(SUB[s][2])
    upstream_goal = "; ".join(f"`{s}`" for s in subs)
    success = (
        f"Success is the upstream Franka Kitchen completion check for {'the subtask' if single else 'every one of these subtasks'} ({upstream_goal}): "
        "the subtask's joint values must be within 0.3 (Euclidean norm) of its goal values, judged on the physical state after you call `robo done` "
        "and the robot has held still for about 10 steps. Everything must still be in place at that moment (a door that swings shut again, or a "
        "kettle that falls over, does not count)."
        + ("" if single else " Other kitchen objects may be left in any state.")
    )
    meta = {
        "task": {"name": f"robouse/{task_id}", "description": desc},
        "metadata": {
            "source_benchmark": "Gymnasium-Robotics Franka Kitchen (Farama; Relay Policy Learning / D4RL kitchen)",
            "source_task": "FrankaKitchen-v1 tasks_to_complete=[" + ", ".join(subs) + "]",
            "suite": "kitchen",
            "category": "manipulation",
            "difficulty": "medium" if single else "hard",
            "tags": ["franka", "mujoco", "single-arm", "articulated", "kitchen"]
            + ([] if single else ["long-horizon", "multi-goal"]),
        },
        "agent": {"timeout_sec": 900 if single else 1800},
        "verifier": {"timeout_sec": 120},
        "robouse": {
            "id": task_id,
            "backend": "kitchen",
            "env": task_id,
            "seed": 0,
            "max_steps": max_steps,
            "camera": "front",
            "skills": True,
            "success_mode": "final",
        },
    }
    body = (
        f"# {title}\n\n{SCENE}\n\n**Goal:** {goal}\n\n{success}\n\n{judged}\n\n"
        + "\n\n".join(notes)
        + f"\n\n{OBSERVE}\n\n{CONTROL}\n\nThe step budget is {max_steps} steps.\n\n"
        + ROBO_USAGE
    )
    return meta, body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks/kitchen")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for task_id, subs in TASKS.items():
        meta, body = build(task_id, subs)
        oracle = (
            "#!/bin/bash\n# Reference solution: scripted end-effector waypoints per subtask, through the robo socket only (public observations).\n"
            f"set -euo pipefail\npython -m robouse.oracle --backend kitchen --env {task_id}\n"
        )
        write_task(out / task_id, meta, body, oracle, VERIFY)
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
