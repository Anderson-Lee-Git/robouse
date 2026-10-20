"""Dual YAM (Dream Labs' bimanual YAM station scene, from the `dreamlabs` wheel 1.0.0) -> Robo Use tasks.

The three tasks of Dream's own simulation example ("put apple into the bowl", "put orange into the bowl", "put banana
on the plate"), each on Dream's layout (layout 0) and on two layouts with the fruit moved by up to 3 cm and turned by
up to 30 degrees (layouts 1 and 2). Agents see the robot's joints and tool points and the three cameras, like Dream-1;
the fruit, bowl and plate must be found in the images.

Usage: python adapters/yam/generate.py [--out tasks/yam]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.embodied import VERIFY_SH
from robouse.core.prompts import EMBODIED_USAGE
from robouse.tasks import write_task

# (task id stem, Dream's instruction, goal, the sentence that says what counts)
GOALS = [
    (
        "apple-to-bowl",
        "put apple into the bowl",
        {"kind": "in_bowl", "object": "apple"},
        "the apple rests inside the bowl (its centre within 6.5 cm of the bowl's axis, below the rim height plus 5 cm)",
    ),
    (
        "orange-to-bowl",
        "put orange into the bowl",
        {"kind": "in_bowl", "object": "orange"},
        "the orange rests inside the bowl (its centre within 6.5 cm of the bowl's axis, below the rim height plus 5 cm)",
    ),
    (
        "banana-to-plate",
        "put banana on the plate",
        {"kind": "on_plate", "object": "banana"},
        "the banana rests on the plate (it touches the plate and its centre is within 7 cm of the plate's centre)",
    ),
]
VISIBLE = [
    f"{s}_{f}"
    for s in ("right", "left")
    for f in ("joint_pos", "gripper_open", "tcp_pos", "tcp_down_deg", "jaw_yaw_deg")
]

BODY = (
    """# Dual YAM: {instruction}

Two I2RT YAM arms with parallel grippers stand side by side at one edge of a table, in the simulated station that Dream Labs' Dream-1 policy is trained for (Dream Labs' own MuJoCo scene). On the table are an apple, an orange, a banana, a water bottle, a white bowl and a white plate. {layout_text}

## Task

{instruction_cap}.

**Success:** after you call `robo done` and the robot holds still for 10 steps, {success}, released (no fingertip touches it) and at rest. Any other ending scores 0.

**Frame.** Metres, +z up; the table top is at z = 0.76. The robots stand at y = 0.24 and reach toward -y. The left arm's base is at x = +0.305 and the right arm's at x = -0.305, left and right as the `top` camera sees them (+x is to the left in its image).

**Controls.** `robo act` takes 14 numbers: the right arm's six joint angles in radians (absolute targets, clipped to the joint limits that `robo info` lists), the right gripper's opening (0 closed, 1 open), then the same seven numbers for the left arm. One step is 50 ms; the joints move toward their targets under position control. Skills, all closed-loop and counted against the budget:
- `robo skill reach ARM X Y Z [YAW]` moves an arm's tool point (the point between the fingertips) along a straight line to (X, Y, Z) with the gripper pointing straight down. YAW (degrees, optional) is the heading the fingers close along, measured from +x toward +y. It reports the distance left; a target outside the arm's reach is not reached.
- `robo skill set_gripper ARM OPENING [STEPS]` opens or closes one gripper (0 closed, 1 open, about 9.5 cm wide) while the arm holds.
- `robo skill home ARM` moves one arm back to its home pose.

**Observation.** `robo observe` reports, per arm, the joint angles (`*_joint_pos`), the gripper opening (`*_gripper_open`), the tool point (`*_tcp_pos`), how far the gripper is tilted from pointing down (`*_tcp_down_deg`) and the heading the fingers close along (`*_jaw_yaw_deg`). It does not report where the objects are: find them in the camera images. `robo observe --image` saves all three cameras: `top` (over the robots, looking across the table; `robo info` gives its 3x4 projection matrix, which maps a world point to its pixel), and `left` and `right` on the wrists (they move with the arms, so no matrix is given).

The step budget is {max_steps} steps ({seconds} s of simulated time).

"""
    + EMBODIED_USAGE
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tasks" / "yam"))
    out = Path(ap.parse_args().out)
    if out.exists():
        shutil.rmtree(out)
    max_steps = 1200
    n = 0
    for stem, instruction, goal, success in GOALS:
        for layout in (0, 1, 2):
            tid = f"yam-{stem}" + (f"-layout-{layout}" if layout else "")
            layout_text = (
                "The objects are where Dream's scene puts them."
                if layout == 0
                else f"The fruit are moved by up to 3 cm and turned by up to 30 degrees from Dream's layout (layout {layout})."
            )
            meta = {
                "task": {"name": f"robouse/{tid}", "description": f"Dual YAM: {instruction} (layout {layout})"},
                "metadata": {
                    "source_benchmark": "Dream Labs YAM MuJoCo example (dreamlabs 1.0.0, dream_examples/yam_mujoco, Apache-2.0)",
                    "source_task": instruction,
                    "language_instruction": instruction,
                    "suite": "yam",
                    "category": "pick-and-place",
                    "difficulty": "medium",
                    "tags": ["bimanual", "yam", "dream-labs", "vision"],
                },
                "agent": {"timeout_sec": 1800},
                "verifier": {"timeout_sec": 60},
                "robouse": {
                    "id": tid,
                    "backend": "yam",
                    "env": tid,
                    "seed": layout,
                    "goal": goal,
                    "max_steps": max_steps,
                    "camera": "top",
                    "cameras": ["top", "left", "right"],
                    "uncalibrated_cameras": ["left", "right"],
                    "obs_mode": "vision",
                    "visible_fields": VISIBLE,
                    "frame_every": 2,
                    "control_dt": 0.05,
                },
            }
            body = BODY.format(
                instruction=instruction,
                instruction_cap=instruction[0].upper() + instruction[1:],
                layout_text=layout_text,
                success=success,
                max_steps=max_steps,
                seconds=int(max_steps * 0.05),
            )
            oracle = (
                "#!/bin/bash\n# Reference solution: pick the fruit with the nearer arm and place it, with the public skills"
                " (object positions from the reference solution's privileged state).\nset -euo pipefail\n"
                "python -m robouse.oracle --backend yam\n"
            )
            write_task(out / tid, meta, body, oracle, VERIFY_SH)
            n += 1
    print(f"{n} tasks -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
