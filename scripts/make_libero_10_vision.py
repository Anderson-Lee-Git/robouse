"""Write tasks/libero-10-vision: LIBERO-Long (libero_10) image-only, from LIBERO's fixed benchmark start states.

The protocol of "LLM agents on LIBERO-10" (arXiv 2610.30051): the ten libero_10 tasks, each from LIBERO's first ten
benchmark init states (run with `run-many --seeds 0-9`: with no `init_state` in the task, seed n starts from benchmark
state n % 50), a 900-step budget, and the two 256x256 cameras plus the robot's own state, no object poses. The policy's
text is the libero-pro suite's image-only text (`obs_mode: vision`), so a run here and one on libero-pro differ only in
the scenes, the start states and the budget. The tasks have no reference solution: LIBERO's demonstrations, which the
`libero` suite replays, start from their own states, not the benchmark's, and the scripted LIBERO solution
(robouse.backends.libero.solver) is the libero-pro suite's, written and checked for those tasks only. oracle/solve.sh
says so and fails, so an oracle run cannot pass for a reference.

    python scripts/make_libero_10_vision.py
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC, DST = ROOT / "tasks" / "libero", ROOT / "tasks" / "libero-10-vision"
VERSION = "1.0.0"
MAX_STEPS = 900
VISIBLE = ["hand_pos", "eef_quat", "eef_axis_angle", "gripper_qpos", "gripper_open"]

BODY = """# {title}

A Franka Panda arm with a parallel-jaw gripper works at a low table in a LIBERO scene (MuJoCo / robosuite). The task is LIBERO-Long's (`libero_10`): long-horizon tasks, most with two sub-goals.

**Goal (LIBERO's language instruction):** {language}

The episode ends as solved the moment LIBERO's own success check (the goal's predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

## This robot

- The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand about the world axes (1.0 asks for 0.5 rad); GRIPPER -1 opens, +1 closes.
- `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
- World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. The table surface is at about z = 0.43.
- You see the scene only through the cameras. `robo observe` gives the robot's own state: `hand_pos` (end-effector position), `eef_quat` (orientation quaternion x, y, z, w) and `eef_axis_angle`, `gripper_qpos` (the two finger joints) and `gripper_open` (finger gap in metres, about 0.08 when fully open). It does not say where the objects are. Each `robo observe` also saves a 256x256 image from the front camera (`agentview`) and one from the wrist camera (`robot0_eye_in_hand`), and prints their paths; open them to look.
- `robo info` lists each camera with a 3x4 `projection` matrix P: for a world point (x, y, z), `[u*w, v*w, w] = P @ [x, y, z, 1]` gives its pixel (u, v) in that camera's saved image (u to the right, v down, origin at the top-left). The wrist camera moves with the hand: its matrix is for the hand's pose when you call `robo info`.
- The step budget is {steps} steps ({seconds:g} seconds of simulated time).

"""

NO_REFERENCE = "LIBERO publishes none for its benchmark start states, and robouse has none for them"
SOLVE = f"""#!/bin/bash
# No reference solution: {NO_REFERENCE}.
echo "no reference solution for this task: {NO_REFERENCE}" >&2
exit 1
"""


def split(text: str) -> tuple[dict, str]:
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


def main() -> None:
    _, pro_body = split((ROOT / "tasks/libero-pro/libero-pro-10-swap-0/task.md").read_text())
    control = pro_body[pro_body.index("## How to control the robot") :]  # the common robo text, as libero-pro has it
    if DST.exists():
        shutil.rmtree(DST)
    for i in range(10):
        spec, _ = split((SRC / f"libero-10-{i}" / "task.md").read_text())
        r, m = spec["robouse"], spec["metadata"]
        name = f"libero-10-vision-{i}"
        spec["task"]["name"] = f"robouse/{name}"
        m.update(
            suite="libero-10-vision",
            suite_version=VERSION,
            reference_solution=f"none ({NO_REFERENCE})",
            protocol="image-only (two 256x256 cameras and the robot's own state); LIBERO benchmark init state n for "
            f"seed n (run with --seeds 0-9); {MAX_STEPS} steps; as arXiv 2610.30051",
        )
        m["tags"] = [t for t in m["tags"] if t != "language"] + ["language", "vision"]
        spec["agent"]["timeout_sec"] = 2400
        r["id"] = name
        r["max_steps"] = MAX_STEPS
        r["settle_steps"] = 10
        r["obs_mode"] = "vision"
        r["visible_fields"] = list(VISIBLE)
        for k in ("init_state", "init_source"):
            r.pop(k, None)
        body = BODY.format(
            title=spec["task"]["description"].rstrip("."),
            language=m["language_instruction"],
            steps=MAX_STEPS,
            seconds=MAX_STEPS / 20,
        )
        d = DST / name
        (d / "oracle").mkdir(parents=True)
        (d / "verifier").mkdir()
        front = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120)
        (d / "task.md").write_text(f"---\n{front}---\n\n{body}{control}")
        (d / "oracle" / "solve.sh").write_text(SOLVE)
        shutil.copy(SRC / f"libero-10-{i}" / "verifier" / "test.sh", d / "verifier" / "test.sh")
        for f in (d / "oracle" / "solve.sh", d / "verifier" / "test.sh"):
            f.chmod(0o755)
        assert not re.search(r"\bobjects\b`?:", (d / "task.md").read_text().split("---\n", 2)[2])
    print(f"wrote {len(list(DST.iterdir()))} tasks to {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
