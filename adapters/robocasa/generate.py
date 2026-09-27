"""RoboCasa (RoboCasa365 kitchens on robosuite 1.5) -> robouse tasks (suite "robocasa").

The task list, kitchen layouts and recorded episode layouts live in src/robouse/backends/robocasa.py (TASKS) and
src/robouse/backends/robocasa_episodes/; the simulation runs in a separate virtualenv (see docs/suites/robocasa.md).
Reference solutions (robocasa_oracles.py) drive the robot only through the robo socket.

Usage: python adapters/robocasa/generate.py [--out tasks/robocasa]
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
from pathlib import Path

from robouse.backends.robocasa import TASKS
from robouse.prompts import ROBO_USAGE
from robouse.tasks import write_task

ROOT = Path(__file__).resolve().parents[2]


def _verify() -> str:
    spec = importlib.util.spec_from_file_location("_mw_generate", ROOT / "adapters" / "metaworld" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.VERIFY


SCENE = ("A household kitchen from RoboCasa (kitchen layout {layout}, style {style}): counters, cabinets, drawers, a sink and "
         "appliances, simulated in MuJoCo. The robot is a Franka Panda arm on a mobile base (RoboCasa's PandaOmron), parked where "
         "RoboCasa's task set-up puts it, facing the relevant fixture; the base and torso do not move in this task, only the arm "
         "and its two-finger gripper (fingers open to 8 cm). World frame in metres, z up; `robot_forward` in `robo observe` is the "
         "horizontal direction the robot faces. The arm's reach from the parked base is limited (roughly 0.4 m forward of the base "
         "at counter height), and the arm can collide with the counter and fixtures.")

CONTROL = ("**Controls.** `robo act DX DY DZ GRIP` moves the gripper's commanded target by DX, DY, DZ times 2 cm per step along the "
           "WORLD x, y, z axes (each in [-1, 1]); the gripper keeps its orientation ({tool}). GRIP 0 keeps the fingers as they are, "
           "any positive value closes them, and a negative value -f opens them to fraction f (-1 fully open). One step is 50 ms "
           "(RoboCasa's 20 Hz control rate). The arm follows the target through RoboCasa's operational-space controller; the target "
           "stays within 5 cm of the hand. `robo move-to X Y Z` and `robo grip G` work as described below.")

FIELDS = ("**Observation.** `robo observe` reports `hand_pos` (the point between the fingertips), `hand_target` (the commanded "
          "target), `gripper_open` (0 closed .. 1 open), `robot_base_pos`, `robot_forward`, `task_instruction` (RoboCasa's own "
          "language instruction) and the task fields below. `robo observe --image` saves a picture from the robot's shoulder camera "
          "(`--camera robot0_agentview_left`, `robot0_agentview_right`, `robot0_eye_in_hand` and `robot0_frontview` are also "
          "available).")

TXT = {
    "CloseDrawer": dict(
        title="Close the drawer", difficulty="medium", tags=["drawer", "articulated"],
        goal="One of the drawers next to the robot is pulled open. Close it fully.",
        success=("RoboCasa's own check for CloseDrawer: the drawer's slide joint is at most 0.5 % of its travel from closed "
                 "(`drawer_open_fraction` <= 0.005)."),
        fields=("`drawer_handle_pos` (centre of the drawer handle; it moves with the drawer), `drawer_open_fraction` (0 closed .. 1 "
                "fully open) and `drawer_front_normal` (unit vector pointing out of the drawer front, toward where it opens).")),
    "PickPlaceCounterToSink": dict(
        title="Counter to sink", difficulty="medium", tags=["pick-place", "sink"],
        goal="Pick the object named in `task_instruction` up from the counter and put it in the sink.",
        success=("RoboCasa's own check for PickPlaceCounterToSink: the object lies inside the sink basin and the gripper is away "
                 "from it (the object is released)."),
        fields=("`object_pos` (centre of the object's bounding box), `object_size` (its bounding-box size [x, y, z] in m), "
                "`object_category`, `sink_basin_center`, `sink_basin_half_size` and `sink_basin_bottom_z`.")),
}


def build(tid: str) -> tuple[dict, str]:
    t = TASKS[tid]
    x = TXT[t["env"]]
    body = (f"# {x['title']} (RoboCasa kitchen {t['layout']})\n\n" + SCENE.format(layout=t["layout"], style=t["style"]) + "\n\n"
            f"**Goal:** {x['goal']}\n\n**Success:** {x['success']} Success is judged by the episode server after you call "
            "`robo done` and the robot has held still for about 10 steps.\n\n"
            f"**Task fields in `robo observe`:** {x['fields']}\n\n"
            + CONTROL.format(tool="pointing straight down" if t.get("tool", "down") == "down" else "pointing forward")
            + "\n\n" + FIELDS + f"\n\nThe step budget is {t['max_steps']} steps ({t['max_steps'] * .05:.0f} s of simulated time).\n\n"
            + ROBO_USAGE)
    meta = {
        "task": {"name": f"robouse/{tid}", "description": f"{x['title']} in RoboCasa kitchen layout {t['layout']} (Franka Panda on a mobile base)."},
        "metadata": {"source_benchmark": "RoboCasa (RoboCasa365, robosuite 1.5)", "source_task": t["env"], "suite": "robocasa",
                     "category": "manipulation", "difficulty": x["difficulty"],
                     "tags": ["mujoco", "robocasa", "kitchen", "panda", "mobile-manipulator", *x["tags"]]},
        "agent": {"timeout_sec": 1800},
        "verifier": {"timeout_sec": 120},
        "robouse": {"id": tid, "backend": "robocasa", "env": tid, "seed": int(t["seed"]), "max_steps": int(t["max_steps"]),
                    "camera": "robot0_agentview_left",
                    "cameras": ["robot0_agentview_left", "robot0_agentview_right", "robot0_agentview_center", "robot0_eye_in_hand",
                                "robot0_frontview"],
                    "skills": True, "success_mode": "final"},
    }
    return meta, body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "tasks" / "robocasa"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    verify = _verify()
    for tid in TASKS:
        meta, body = build(tid)
        oracle = ("#!/bin/bash\n# Reference solution: scripted controller that uses only the robo socket (robocasa_oracles.py).\n"
                  f"set -euo pipefail\npython -m robouse.oracle --backend robocasa --env {tid}\n")
        write_task(out / tid, meta, body, oracle, verify)
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
