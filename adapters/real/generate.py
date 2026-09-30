"""Real-robot suite -> Robo Use tasks (suite "real"): MakerMods Metal, SO-101 and AgiLeX Piper arms.

Every task runs on the hardware-in-the-loop mock by default (a session recorded on the bench, replayed behind the
LeRobot / piper_sdk seam; assets/hil/). The same task runs on the live arm with a rig file:
`robouse run --task real-metal-reach --harness ... --rig rig.yaml` (docs/real-robots.md). Backend, safety guard and
operator channel: src/robouse/backends/real.py and src/robouse/real/.

Usage: python adapters/real/generate.py [--out tasks/real]
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from robouse.backends.embodied import VERIFY_SH
from robouse.core.prompts import EMBODIED_USAGE
from robouse.real.drivers.rosbridge import ros_profile
from robouse.real.robots import PROFILES

ROS_ARM = {
    "display": "6-joint ROS arm (rosbridge)",
    "joints": [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    ],
    "low": [-180, -180, -160, -180, -180, -180],
    "high": [180, 0, 160, 180, 180, 180],
    "units": "deg",
    "home": [0, -90, 90, -90, -90, 0],
    "park": [0, -90, 90, -90, -90, 0],
    "control_hz": 10,
    "notes": "Joint names follow the ROS arm's /joint_states; positions in degrees (converted to radians on the wire). "
    "No kinematic chain: the safety layer enforces joint limits, speed and wind-up.",
}


def prof_of(t: dict):
    return ros_profile(ROS_ARM) if t["robot"] == "ros" else PROFILES[t["robot"]]


from robouse.tasks import write_task

SAFETY = (
    "**Safety layer.** Every command passes the episode server's safety guard before it reaches the motors: joint "
    "targets are clamped to the joint limits; a move whose straight joint-space path would take the elbow, wrist, "
    "flange or fingertips below the table, outside the workspace box or low behind the base is vetoed before anything "
    "moves (`robo` prints the reason and no step is used); speed is limited per control step (slower within 7.6 cm of "
    "the table); a joint command never leads the measured position by more than a few degrees; over-temperature, an "
    "operator e-stop or a hardware fault stops the episode at once (outcome `safety_stop`, score 0). `robo info` lists "
    "the limits under `embodiment.safety`."
)

TASKS = [
    {
        "id": "real-metal-reach",
        "robot": "metal",
        "fixture": "metal-bowl-121853",
        "cameras": ["gripper", "overhead"],
        "title": "Metal arm: bring the fingertips to a point above the bead tray",
        "difficulty": "easy",
        "category": "reach",
        "goal": {"tool": [0.30, -0.10, 0.08], "tol": 0.02},
        "task": (
            "Move the fingertips (the tool point) to (0.30, -0.10, 0.08) m in the base frame, 8 cm above the table over "
            "the bead tray, and hold them there."
        ),
        "success": (
            "the measured tool point (forward kinematics of the measured joints, `tool_pos` in `robo observe`) is within "
            "2 cm of (0.30, -0.10, 0.08) when judged."
        ),
        "oracle": [["move_to", 0.30, -0.10, 0.08]],
        "max_steps": 300,
    },
    {
        "id": "real-metal-bead-to-bowl",
        "robot": "metal",
        "fixture": "metal-bowl-121853",
        "cameras": ["gripper", "overhead"],
        "title": "Metal arm: put a green bead into the bowl",
        "difficulty": "hard",
        "category": "pick-and-place",
        "scene_setup": "one green glass bead on the table at (0.30, -0.15) m; the white ceramic bowl centred near (0.49, -0.13) m.",
        "task": (
            "A green glass bead lies on the table at about (0.30, -0.15) m in the base frame (table surface at z = -0.009 m). "
            "The white bowl is centred near (0.49, -0.13) m, past straight-down reach; release over its near rim at about "
            "(0.42, -0.13, 0.12) m. Pick up the bead and drop it into the bowl."
        ),
        "success": (
            "the operator watching the robot confirms that the bead ended up in the bowl (on the hardware-in-the-loop "
            "mock, the stand-in operator says yes only if the fingertips went, in order, above the bead with the gripper "
            "open, down to the bead, closed there, lifted, moved over the bowl and opened)."
        ),
        "stages": [
            {"name": "above bead, open", "tool": [0.30, -0.15, 0.06], "tol": 0.02, "gripper": "open"},
            {"name": "at bead", "tool": [0.30, -0.15, 0.005], "tol": 0.012},
            {"name": "closed on bead", "tool": [0.30, -0.15, 0.005], "tol": 0.015, "gripper": "closed"},
            {"name": "lifted", "tool": [0.30, -0.15, 0.08], "tol": 0.025, "gripper": "closed"},
            {"name": "over bowl", "tool": [0.42, -0.13, 0.12], "tol": 0.025, "gripper": "closed"},
            {"name": "released over bowl", "tool": [0.42, -0.13, 0.12], "tol": 0.03, "gripper": "open"},
        ],
        "oracle": [
            ["grip", 60],
            ["move_to", 0.30, -0.15, 0.06],
            ["move_to", 0.30, -0.15, 0.005, 0.4],
            ["grip", 4],
            ["move_to", 0.30, -0.15, 0.08, 0.5],
            ["move_to", 0.42, -0.13, 0.12, 0.6],
            ["grip", 60],
        ],
        "max_steps": 900,
    },
    {
        "id": "real-so101-reach",
        "robot": "so101",
        "fixture": "so101-sort-left",
        "cameras": ["camera0", "camera1"],
        "title": "SO-101 arm: bring the gripper tip to a point above the table",
        "difficulty": "easy",
        "category": "reach",
        "goal": {"tool": [0.20, 0.05, 0.08], "tol": 0.02},
        "task": "Move the gripper tip (the tool point) to (0.20, 0.05, 0.08) m in the base frame and hold it there.",
        "success": "the measured tool point (`tool_pos`) is within 2 cm of (0.20, 0.05, 0.08) when judged.",
        "oracle": [["move_to", 0.20, 0.05, 0.08]],
        "max_steps": 300,
    },
    {
        "id": "real-so101-block-lift",
        "robot": "so101",
        "fixture": "so101-sort-left",
        "cameras": ["camera0", "camera1"],
        "title": "SO-101 arm: pick up the block and hold it up",
        "difficulty": "medium",
        "category": "pick",
        "scene_setup": "one 2.5 cm cube on the table at (0.22, -0.05) m.",
        "task": (
            "A 2.5 cm cube stands on the table at about (0.22, -0.05) m in the base frame (table at z = 0). Grasp it and "
            "lift it 8 cm off the table."
        ),
        "success": (
            "the operator confirms the cube is held clear of the table (mock: the stand-in operator says yes only if "
            "the tip went, in order, above the cube with the gripper open, down to the cube, closed there and lifted)."
        ),
        "stages": [
            {"name": "above cube, open", "tool": [0.22, -0.05, 0.08], "tol": 0.02, "gripper": "open"},
            {"name": "at cube", "tool": [0.22, -0.05, 0.02], "tol": 0.012},
            {"name": "closed on cube", "tool": [0.22, -0.05, 0.02], "tol": 0.015, "gripper": "closed"},
            {"name": "lifted", "tool": [0.22, -0.05, 0.08], "tol": 0.02, "gripper": "closed"},
        ],
        "oracle": [
            ["grip", 60],
            ["move_to", 0.22, -0.05, 0.08],
            ["move_to", 0.22, -0.05, 0.02, 0.4],
            ["grip", 2],
            ["move_to", 0.22, -0.05, 0.08, 0.5],
        ],
        "max_steps": 600,
    },
    {
        "id": "real-ros-joint-pose",
        "robot": "ros",
        "fixture": None,
        "cameras": ["wrist"],
        "title": "ROS arm via rosbridge: move to a joint-space pose",
        "difficulty": "easy",
        "category": "reach",
        "goal": {"joints": [30.0, -70.0, 60.0, -80.0, -90.0, 20.0], "tol": 3.0},
        "task": "Move the six joints to (30, -70, 60, -80, -90, 20) degrees and hold.",
        "success": "every measured joint is within 3 degrees of its target when judged.",
        "oracle": [["move_joints", 30, -70, 60, -80, -90, 20]],
        "max_steps": 300,
    },
    {
        "id": "real-piper-joint-pose",
        "robot": "piper",
        "fixture": "piper-synthetic",
        "cameras": [],
        "title": "Piper arm: move to a joint-space pose",
        "difficulty": "easy",
        "category": "reach",
        "goal": {"joints": [20.0, 40.0, -50.0, 0.0, 20.0, 0.0], "tol": 3.0},
        "task": "Move the six arm joints to (20, 40, -50, 0, 20, 0) degrees and hold.",
        "success": "every measured arm joint is within 3 degrees of its target when judged.",
        "oracle": [["move_joints", 20, 40, -50, 0, 20, 0]],
        "max_steps": 300,
    },
]


def instruction(t: dict) -> str:
    p = prof_of(t)
    joints = ", ".join(
        f"{n} [{lo:g}, {hi:g}] {u}" for n, lo, hi, u in zip(p.joints, p.low, p.high, p.units, strict=False)
    )
    cams = (
        f"Cameras: {', '.join('`' + c + '`' for c in t['cameras'])} (`robo observe --image` shows all of them side by side; "
        "`--camera NAME` shows one)."
        if t["cameras"]
        else "This rig has no camera."
    )
    fk = (
        "`tool_pos` / `tool_axis` (the fingertip point and approach direction by forward kinematics of the measured joints, "
        "base frame, metres), "
        if p.chain_file
        else ""
    )
    skills = (
        "`move_joints "
        + " ".join(n.upper() for i, n in enumerate(p.joints) if i != p.gripper)
        + " [SPEED]` (interpolated "
        "move to a joint pose; SPEED is a fraction of the speed limit), "
        + (
            "`move_to X Y Z [SPEED]` (fingertips to a point in the base frame by inverse kinematics, position only), "
            if p.chain_file
            else ""
        )
        + "`grip VALUE`, `home` (reach-ready pose) and `park` (rest pose). Every skill checks its whole path first "
        "and is refused with the reason if the path leaves the workspace."
    )
    return (
        f"# {t['title']}\n\nYou control a {p.display}, a real robot arm. {p.notes} {cams}\n\n## Task\n\n{t['task']}\n\n"
        f"**Success:** {t['success']} Judged by the episode server after you call `robo done` and the arm has held still "
        f"for 10 control steps.\n\n**Controls.** `robo act` takes one absolute target per joint, in this order: {joints}. "
        f"The gripper is the last value ({p.gripper_closed:g} = closed, {p.gripper_open:g} = open). The target is approached at "
        f"the safety speed limit over the following control steps ({p.control_hz:g} Hz); `--repeat N` keeps commanding it for "
        f"N steps. Skills (`robo info` lists them with their arguments): {skills}\n\n{SAFETY}\n\n**Observation.** "
        f"`robo observe` reports `joint_pos` (measured, by joint name), `gripper`, {fk}`target` (the current joint target), "
        f"`telemetry` (maximum motor temperature, veto count, e-stop and stop state) and `mode` (`real` on hardware, "
        f"`hil-mock` on the hardware-in-the-loop mock, which replays a session recorded on this arm: it follows commands "
        f"the way the real arm did and shows the recorded camera view nearest to the current pose, but models no contact "
        f"with objects). Remarks typed by the operator appear under `operator_notes`.\n\nThe step budget is {t['max_steps']} "
        f"control steps.\n\n" + EMBODIED_USAGE
    )


def oracle_sh(t: dict) -> str:
    return (
        "#!/bin/bash\n# Reference solution: a fixed sequence of the task's skills, sent through the episode socket like an agent.\n"
        "set -euo pipefail\n"
        f"ROBOUSE_REAL_ORACLE='{json.dumps(t['oracle'])}' python -m robouse.oracle --backend real --env {t['id']}\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tasks" / "real"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for t in TASKS:
        p = prof_of(t)
        real = {
            "robot": t["robot"],
            "driver": "mock",
            "fixture": t["fixture"],
            "cameras": t["cameras"] or None,
            **({k: v for k, v in ROS_ARM.items()} if t["robot"] == "ros" else {}),
            **({"goal": t["goal"]} if "goal" in t else {}),
            **({"stages": t["stages"]} if "stages" in t else {}),
            **({"scene_setup": t["scene_setup"]} if "scene_setup" in t else {}),
            "goal_text": t["task"],
        }
        meta = {
            "task": {"name": f"robouse/{t['id']}", "description": t["title"]},
            "metadata": {
                "source_benchmark": "robouse original (real suite; real arm, hardware-in-the-loop mock by default)",
                "source_task": t["id"],
                "suite": "real",
                "category": t["category"],
                "difficulty": t["difficulty"],
                "tags": ["real-robot", p.name, "hil-mock"],
                "embodiment_mode": "real",
                "tested_on_hardware": p.tested_on_hardware,
            },
            "agent": {"timeout_sec": 1800},
            "verifier": {"timeout_sec": 120},
            "robouse": {
                "id": t["id"],
                "backend": "real",
                "env": t["id"],
                "seed": 0,
                "max_steps": t["max_steps"],
                "camera": "all" if t["cameras"] else "",
                "cameras": (["all"] + t["cameras"]) if t["cameras"] else [""],
                "skills": True,
                "success_mode": "final",
                "frame_every": 2,
                "real": {k: v for k, v in real.items() if v is not None},
            },
        }
        write_task(out / t["id"], meta, instruction(t), oracle_sh(t), VERIFY_SH)
    print(f"{len(TASKS)} tasks -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
