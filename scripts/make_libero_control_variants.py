"""Write an image-only LIBERO suite's end-effector and joint-control versions, for comparing the two interfaces.

    python scripts/make_libero_control_variants.py libero-pro        # -> tasks/libero-pro-eef, tasks/libero-pro-joint
    python scripts/make_libero_control_variants.py libero-10-vision  # -> tasks/libero-10-eef, tasks/libero-10-joint
    python scripts/make_libero_control_variants.py libero-10-vision --controls eef-pose  # -> tasks/libero-10-eef-pose

Both versions of a task have the same scene, start state, goal, budget and cameras, and both observe the arm's joint
angles (`joint_pos`) besides the hand's pose, so they differ only in how the arm is commanded:

- eef: LIBERO's own delta end-effector action (OSC_POSE) and the `move-to` skill, as in the source suite.
- joint: delta joint positions (robosuite's JOINT_POSITION; kp 150 and 0.2 rad per unit, so a full command moves the
  hand about as fast as OSC_POSE's does) and the `move-joints-to` skill; no `move-to`.
- eef-pose: eef plus the `move-to-pose` skill (an absolute position and world-frame roll/pitch/yaw for the hand) and the
  hand's angles (`eef_rpy`) in the observation: whether an absolute orientation command closes the gap to joint control.

Task ids get a `-eef`, `-joint` or `-eef-pose` suffix. An eef or eef-pose task keeps the source task's reference solution (libero-pro's scripted
one; libero-10-vision has none). A joint task has none: the scripted solution commands the hand, not the joints, so its
oracle/solve.sh says so and fails, and an oracle run cannot pass for a reference.
"""

from __future__ import annotations

import argparse
import copy
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0.0"
OUT = {"libero-pro": "libero-pro", "libero-10-vision": "libero-10"}
VISIBLE = ["hand_pos", "eef_quat", "eef_axis_angle", "gripper_qpos", "gripper_open", "joint_pos"]

OBS_OLD = "`gripper_qpos` (the two finger joints) and `gripper_open` (finger gap in metres, about 0.08 when fully open)."
OBS_NEW = (
    "`gripper_qpos` (the two finger joints), `gripper_open` (finger gap in metres, about 0.08 when fully open) and "
    "`joint_pos` (the seven arm joint angles in rad, from joint 1 at the base to joint 7, which turns the hand)."
)
ACT_PREFIX = "- The action has 7 numbers, not 4:"
MOVE_OLD = "- `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).\n"
JOINT_ACT = (
    "- The action has 8 numbers, not 4: `robo act DQ1 DQ2 DQ3 DQ4 DQ5 DQ6 DQ7 GRIPPER`, each in [-1, 1]. It is a delta "
    "joint-position command for the arm's seven joints (robosuite's JOINT_POSITION controller, 20 steps per second): "
    "1.0 on DQi asks for 0.2 rad on joint i in one step, and the arm lags behind, so holding one DQi at 1.0 turns that "
    "joint about 0.045 rad per step; a full command on several joints moves the hand about 1 cm per step. GRIPPER -1 "
    "opens, +1 closes.\n"
)
NO_REFERENCE = "the scripted LIBERO solution commands the hand (OSC_POSE), and none is written for joint control"
NO_SOLVE = f"""#!/bin/bash
# No reference solution: {NO_REFERENCE}.
echo "no reference solution for this task: {NO_REFERENCE}" >&2
exit 1
"""
POSE_OBS = (
    "`gripper_qpos` (the two finger joints), `gripper_open` (finger gap in metres, about 0.08 when fully open), "
    "`joint_pos` (the seven arm joint angles in rad, from joint 1 at the base to joint 7, which turns the hand) and "
    "`eef_rpy` (the hand's orientation as roll, pitch, yaw in rad, the angles `robo move-to-pose` takes)."
)
POSE_MOVE = (
    "- `robo move-to X Y Z [--grip G]` (keeps the hand's orientation), `robo move-to-pose X Y Z ROLL PITCH YAW "
    "[--grip G]` (moves the hand to a position and an absolute orientation) and `robo grip G` are available. ROLL, PITCH "
    "and YAW are rotations in rad about the world x, y and z axes, applied in that order (R = Rz(YAW) Ry(PITCH) "
    "Rx(ROLL)), of the same hand frame as `eef_quat`; `eef_rpy` in `robo observe` gives the hand's current angles. The "
    "skill stops within 1 cm and 0.05 rad, when the hand stops moving, or after 200 steps.\n"
)
JOINT_MOVE = (
    "- `robo move-joints-to Q1 Q2 Q3 Q4 Q5 Q6 Q7 [--grip G]` (absolute joint angles in rad, within the limits `robo info` "
    "lists) and `robo grip G` are available. There is no `robo move-to`: the arm is commanded only through its joints.\n"
)


def split(text: str) -> tuple[dict, str]:
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


def variant(spec: dict, body: str, control: str, suite: str) -> tuple[dict, str]:
    spec = copy.deepcopy(spec)
    r, m = spec["robouse"], spec["metadata"]
    vid = f"{r['id']}-{control}"
    spec["task"]["name"] = f"robouse/{vid}"
    m.update(source_suite=m.get("suite"), suite=suite, suite_version=VERSION, control=control)
    m["tags"] = list(m.get("tags", [])) + [f"{control}-control"]
    r["id"] = vid
    r["control"] = control
    r["visible_fields"] = list(VISIBLE)
    if control in ("eef", "eef-pose"):
        r["control"] = "eef"
        r["joint_obs"] = True
    if control == "eef-pose":
        r["pose_skill"] = True
        r["visible_fields"].append("eef_rpy")
    else:
        r["joint_controller"] = {"kp": 150.0, "output_max": 0.2}
        m["reference_solution"] = f"none ({NO_REFERENCE})"
    assert r.get("obs_mode") == "vision", f"{vid}: the source task is not image-only"
    assert body.count(OBS_OLD) == 1, f"{vid}: observation text not found"
    body = body.replace(OBS_OLD, OBS_NEW)
    if control == "eef-pose":
        assert body.count(MOVE_OLD) == 1, f"{vid}: move-to text not found"
        body = body.replace(MOVE_OLD, POSE_MOVE).replace(OBS_NEW, POSE_OBS)
        body = body.replace(
            "robo move-to X Y Z [--grip G]     # skill: move the gripper toward a point (if enabled for this task)\n",
            "robo move-to X Y Z [--grip G]     # skill: move the gripper toward a point (if enabled for this task)\n"
            "robo move-to-pose X Y Z ROLL PITCH YAW [--grip G]  # skill: move the gripper to a position and orientation\n",
        )
    if control == "joint":
        lines = body.splitlines(keepends=True)
        act = [i for i, ln in enumerate(lines) if ln.startswith(ACT_PREFIX)]
        assert len(act) == 1 and MOVE_OLD in lines, f"{vid}: action text not found"
        lines[act[0]] = JOINT_ACT
        lines[lines.index(MOVE_OLD)] = JOINT_MOVE
        body = "".join(lines)
    return spec, body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=sorted(OUT))
    ap.add_argument("--controls", default="eef,joint", help="comma-separated: eef, joint, eef-pose")
    a = ap.parse_args()
    src = ROOT / "tasks" / a.source
    for control in a.controls.split(","):
        assert control in ("eef", "joint", "eef-pose"), control
        suite = f"{OUT[a.source]}-{control}"
        dst = ROOT / "tasks" / suite
        if dst.exists():
            shutil.rmtree(dst)
        n = 0
        for d in sorted(p for p in src.iterdir() if (p / "task.md").is_file()):
            spec, body = split((d / "task.md").read_text())
            spec, body = variant(spec, body, control, suite)
            out = dst / spec["robouse"]["id"]
            shutil.copytree(d, out)
            front = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120)
            (out / "task.md").write_text(f"---\n{front}---\n{body}")
            if control == "joint":
                shutil.rmtree(out / "oracle")
                (out / "oracle").mkdir()
                (out / "oracle" / "solve.sh").write_text(NO_SOLVE)
                (out / "oracle" / "solve.sh").chmod(0o755)
            n += 1
        print(f"wrote {n} tasks to {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
