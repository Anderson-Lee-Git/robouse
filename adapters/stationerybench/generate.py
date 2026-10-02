"""StationeryBench (robocurve/stationerybench, MIT; listed in the WorldEvals catalog) -> Robo Use real-robot tasks.

Five bimanual desk-stationery tasks, each with one fixed setup, the verbatim instruction and a 0-4 stage rubric,
judged by the operator watching the robot (upstream: 20 repetitions per task and model, binary success = stage 4). Here
they run on two SO-101 arms (LeRobot `bi_so_follower`) instead of upstream's I2RT YAM arms; the rubric verdict also gives
the progress metric (stage / 4). On the hardware-in-the-loop mock (default) nothing touches the objects, so the stand-in
operator credits stage 0: the mock checks the pipeline (gates, safety, rubric verdicts, recording), not the skill. Run on
the rig with `--rig rig.yaml --epochs 20` for the published protocol.

Usage: python adapters/stationerybench/generate.py [--src ~/benchflow/_refs/stationerybench] [--out tasks/stationerybench]
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from robouse.backends.embodied import VERIFY_SH
from robouse.core.prompts import EMBODIED_USAGE
from robouse.real.robots import PROFILES
from robouse.tasks import write_task

UPSTREAM_COMMIT = "43d5dd380eeb9f555fe691a896a076cf43d3b18b"  # robocurve/stationerybench, tasks built from this commit
MAX_SECONDS = 120  # upstream: 1200 steps at 10 Hz, the published VLA horizon


def parse(md: str) -> dict:
    title = md.splitlines()[0].lstrip("# ").strip()
    sec = lambda name: re.search(rf"## {name}\n\n(.*?)(?:\n## |\Z)", md, re.S).group(1).strip()
    instr = sec("Instruction").lstrip("> ").replace("\n> ", " ").strip()
    rubric = [r.split("|")[2].strip() for r in sec("Rubric").splitlines()[2:] if r.startswith("|")]
    return {"title": title, "objects": sec("Objects"), "setup": sec("Setup"), "instruction": instr, "rubric": rubric}


def body(key: str, t: dict, budget: int) -> str:
    p = PROFILES["so101-bimanual"]
    joints = ", ".join(p.joints)
    rub = "\n".join(f"| {i} | {d} |" for i, d in enumerate(t["rubric"]))
    return (
        f"# StationeryBench: {t['title']}\n\nYou control two SO-101 follower arms (real robots), standing at the far edge of "
        "a desk bench and facing the operator; left and right are the operator's left and right. Each arm has five joints "
        "and a gripper (LeRobot calibration: 0 deg at the middle of each joint's range; gripper 0 = closed, 100 = open). "
        "Cameras show the bench.\n\n## Task\n\n"
        f"> {t['instruction']}\n\nObjects: {t['objects'].replace(chr(10), ' ')}\n\nSetup (done by the operator before the "
        f"episode): {t['setup'].replace(chr(10), ' ')}\n\n**Success:** after you call `robo done`, the operator watching the "
        "robot reports the highest rubric stage reached; the task counts as solved at stage 4 and the stage over 4 is the "
        f"progress score.\n\n| Stage | Description |\n|---|---|\n{rub}\n\n"
        f"**Controls.** `robo act` takes one absolute target per joint in this order: {joints}. Targets are approached at "
        f"the safety speed limit over the following control steps ({p.control_hz:g} Hz). Skills: `move_joints` (both arms' "
        "ten arm joints, interpolated), `grip VALUE [left|right|both]`, `home`, `park`. The safety layer clamps joint limits, "
        "limits speed, bounds how far a command may lead the measured position, stops the episode on over-temperature, "
        "the operator's e-stop, a stalled control loop or joint readings that stop arriving (also checked between "
        "requests), and lets the operator gate every episode. Nothing detects an arm touching something: the arms "
        "report no joint torque and the rig has no kinematic model. After a stop the arms hold their measured "
        "positions and the grippers keep their commands, so a grasped object is not let go, and nothing moves until "
        "the operator has inspected them. When the episode ends otherwise, the arms hold where they are: their parks "
        "are not calibrated, so they park only when the operator approves.\n\n"
        "**Observation.** `robo observe` reports `joint_pos` by name, `gripper` per arm, `target`, `telemetry` and "
        "`mode` (`real` or `hil-mock`); `robo observe --image` shows the cameras. "
        f"Remarks from the operator appear under `operator_notes`.\n\nThe budget is {budget} control steps ({MAX_SECONDS} s, "
        "upstream's time limit).\n\n" + EMBODIED_USAGE
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(Path.home() / "benchflow/_refs/stationerybench"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tasks" / "stationerybench"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    budget = int(MAX_SECONDS * PROFILES["so101-bimanual"].control_hz)
    for md in sorted((Path(a.src) / "docs" / "tasks").glob("*.md")):
        key = md.stem
        t = parse(md.read_text())
        tid = f"stationerybench-{key.replace('_', '-')}"
        meta = {
            "task": {"name": f"robocurve/stationerybench/{key}", "description": t["title"]},
            "metadata": {
                "source_benchmark": "StationeryBench (robocurve/stationerybench, MIT)",
                "source_task": f"stationerybench/{key}",
                "upstream_commit": UPSTREAM_COMMIT,
                "suite": "stationerybench",
                "category": "bimanual manipulation",
                "difficulty": "hard",
                "tags": ["real-robot", "bimanual", "so101", "operator-judged"],
                "embodiment_mode": "real",
                "upstream_epochs": 20,
                "tested_on_hardware": False,
            },
            "agent": {"timeout_sec": 1800},
            "verifier": {"timeout_sec": 120},
            "robouse": {
                "id": tid,
                "backend": "real",
                "env": tid,
                "seed": 0,
                "max_steps": budget,
                "camera": "all",
                "cameras": ["all", "camera0", "camera1"],
                "skills": True,
                "success_mode": "final",
                "frame_every": 2,
                "real": {
                    "robot": "so101-bimanual",
                    "driver": "mock",
                    "fixture": "so101-bimanual-sort",
                    "cameras": ["camera0", "camera1"],
                    "rubric": t["rubric"],
                    "verdict": "operator",
                    "scene_setup": t["setup"].replace("\n", " "),
                    "goal_text": t["instruction"],
                },
            },
        }
        oracle = (
            "#!/bin/bash\n# No scripted solution exists for these real-world tasks (upstream's scripted policy reads its mock's\n"
            "# privileged state). This moves both arms home and opens the grippers, then ends the episode, which\n"
            "# exercises the pipeline; success needs a policy and a real rig.\nset -euo pipefail\n"
            "ROBOUSE_REAL_ORACLE='[[\"home\"], [\"grip\", 60, \"both\"]]' python -m robouse.oracle --backend real --env x\n"
        )
        write_task(out / tid, meta, body(key, t, budget), oracle, VERIFY_SH)
    print(f"{len(list(out.iterdir()))} tasks -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
