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
         "horizontal direction the robot faces. The arm's reach from the parked base is limited (about 0.7 m forward of `robot_base_pos` "
         "at counter height, less low down or far to the side), and the arm and hand can collide with the counter and fixtures.")

CONTROL = ("**Controls.** `robo act DX DY DZ GRIP` moves the gripper's commanded target by DX, DY, DZ times 2 cm per step along the "
           "WORLD x, y, z axes (each in [-1, 1]); the gripper keeps its orientation ({tool}). GRIP 0 keeps the fingers as they are, "
           "any positive value closes them, and a negative value -f opens them to fraction f (-1 fully open). One step is 50 ms "
           "(RoboCasa's 20 Hz control rate). The arm follows the target through RoboCasa's operational-space controller; the target "
           "stays within 5 cm of the hand. `robo move-to X Y Z` and `robo grip G` work as described below.")

FIELDS = ("**Observation.** `robo observe` reports `hand_pos` (the point between the fingertips), `hand_target` (the commanded "
          "target), `gripper_open` (0 closed .. 1 open), `robot_base_pos`, `robot_forward`, `task_instruction` (RoboCasa's own "
          "language instruction) and the task fields listed above. `robo observe --image` saves a picture from the robot's shoulder camera "
          "(`--camera robot0_agentview_left`, `robot0_agentview_right`, `robot0_eye_in_hand` and `robot0_frontview` are also "
          "available).")

TXT = {
    "CloseDrawer": dict(
        title="Close the drawer", difficulty="medium", tags=["drawer", "articulated"],
        goal="One of the drawers next to the robot is pulled open. Close it fully.",
        success=("RoboCasa's own check for CloseDrawer: the drawer is at most 5 % open (`drawer_open_fraction` <= 0.05, where 1 "
                 "means pulled out by 55 % of the drawer's depth, as far as RoboCasa opens drawers)."),
        fields=("`drawer_handle_pos` (centre of the drawer handle; it moves with the drawer), `drawer_open_fraction` (0 closed .. 1 "
                "open as far as RoboCasa opens drawers) and `drawer_front_normal` (unit vector pointing out of the drawer front, toward where it opens).")),
    "PickPlaceCounterToSink": dict(
        title="Counter to sink", difficulty="medium", tags=["pick-place", "sink"],
        goal="Pick the object named in `task_instruction` up from the counter and put it in the sink.",
        success=("RoboCasa's own check for PickPlaceCounterToSink: the object lies inside the sink basin and the gripper is at "
                 "least 25 cm from it (the object is released)."),
        fields=("`object_pos` (centre of the object's bounding box), `object_size` (its bounding-box size [x, y, z] in m), "
                "`object_category`, `sink_basin_center`, `sink_basin_half_size` and `sink_basin_bottom_z`.")),
    "PickPlaceCounterToCabinet": dict(
        title="Counter to cabinet", difficulty="hard", tags=["pick-place", "cabinet"],
        goal=("Pick the object named in `task_instruction` up from the counter and put it inside the open wall cabinet above "
              "the counter (its door is already open)."),
        success=("RoboCasa's own check for PickPlaceCounterToCabinet: all eight corners of the object's bounding box are inside "
                 "one of the cabinet's shelf compartments (within 5 cm) and the gripper is at least 25 cm from the object."),
        fields=("`object_pos` (centre of the object's bounding box), `object_size` (its bounding-box size [x, y, z] in m), "
                "`object_category`; the lowest shelf compartment of the cabinet: `cabinet_interior_center`, "
                "`cabinet_interior_half_size` (half width, half depth, half height), `cabinet_interior_bottom_z` (the shelf "
                "surface), `cabinet_interior_top_z`, and `cabinet_front_normal` (unit vector pointing out of the cabinet's open "
                "front, toward the robot). The hand has to enter through the front opening; the cabinet's frame and the open "
                "door(s) are solid.")),
    "TurnOnToaster": dict(
        title="Turn on the toaster", difficulty="medium", tags=["appliance", "lever", "toaster"],
        goal="A slice of bread is in the toaster. Push the toaster's lever down to turn it on.",
        success=("RoboCasa's own check for TurnOnToaster: the toaster slot holding the bread is on. The toaster switches on when "
                 "its lever is pushed down to at least 90 % of its travel (about 6 cm), then holds the lever down by itself for "
                 "500 steps (25 s) and pops it back up, so call `robo done` soon after it is on."),
        fields=("`toaster_lever_pos` (centre of the lever tab of the slot holding the bread), `toaster_lever_size` (the tab's "
                "bounding-box size [x, y, z]), `toaster_lever_pressed` (0 up .. 1 fully down) and `toaster_on`.")),
    "CloseElectricKettleLid": dict(
        title="Close the kettle lid", difficulty="medium", tags=["appliance", "lid", "articulated"],
        goal="The lid of the electric kettle on the counter is open. Close it.",
        success=("RoboCasa's own check for CloseElectricKettleLid: the lid is at most 1 % of its travel from closed "
                 "(`kettle_lid_open` <= 0.01). The lid is sprung: while it is more than 90 % open it swings back to fully open, "
                 "so it has to be pushed past that point."),
        fields=("`kettle_pos` (the kettle's centre), `kettle_lid_pos` and `kettle_lid_size` (centre and bounding-box size of the "
                "lid), `kettle_lid_hinge_pos` and `kettle_lid_hinge_axis` (the lid's hinge; positive rotation about the axis by "
                "the right-hand rule), `kettle_lid_open` (0 closed .. 1 fully open, 90 degrees), and, for reference, "
                "`kettle_switch_pos`, `kettle_switch_size` and `kettle_on`.")),
    "TurnOffSinkFaucet": dict(
        title="Turn off the faucet", difficulty="medium", tags=["sink", "faucet", "lever"],
        goal="The sink faucet is running. Turn it off by moving its handle (a lever that tilts about a hinge).",
        success=("RoboCasa's own check for TurnOffSinkFaucet: the water is off, which means the handle's angle is at most "
                 "0.40 rad (the water runs while 0.40 < angle < pi; the handle's range is 0 .. 0.5 rad)."),
        fields=("`faucet_handle_pos` and `faucet_handle_size` (centre and bounding-box size of the handle), "
                "`faucet_handle_hinge_pos` and `faucet_handle_hinge_axis` (positive rotation about the axis by the right-hand "
                "rule increases the angle), `faucet_handle_angle` (rad) and `water_on`.")),
    "TurnOnStove": dict(
        title="Turn on a burner", difficulty="hard", tags=["stove", "knob", "appliance"],
        goal=("Turn on the burner named in `task_instruction` by rotating its control knob. The knob sits on the stovetop; it has "
              "a raised ridge across its top that can be pushed sideways."),
        success=("RoboCasa's own check for TurnOnStove: the burner is on, which means its knob's angle is between 0.35 rad and "
                 "2 pi - 0.35 rad (the knob turns from 0, off, to 3.67 rad)."),
        fields=("`stove_knob_pos` (centre of the knob, on its rotation axis), `stove_knob_axis` (positive rotation about it by "
                "the right-hand rule increases the angle), `stove_knob_ridge_dir` (unit vector along the ridge), "
                "`stove_knob_ridge_half_length`, `stove_knob_top_z` (top of the ridge), `stove_knob_angle` (rad) and "
                "`burner_on`.")),
    "TurnOffStove": dict(
        title="Turn off a burner", difficulty="hard", tags=["stove", "knob", "appliance"],
        goal=("Turn off the burner named in `task_instruction` by rotating its control knob back. The knob sits on the stovetop; "
              "it has a raised ridge across its top that can be pushed sideways."),
        success=("RoboCasa's own check for TurnOffStove: the burner is off, which means its knob's angle is below 0.35 rad "
                 "(or above 2 pi - 0.35 rad; the knob turns from 0, off, to 3.67 rad)."),
        fields=("`stove_knob_pos` (centre of the knob, on its rotation axis), `stove_knob_axis` (positive rotation about it by "
                "the right-hand rule increases the angle), `stove_knob_ridge_dir` (unit vector along the ridge), "
                "`stove_knob_ridge_half_length`, `stove_knob_top_z` (top of the ridge), `stove_knob_angle` (rad) and "
                "`burner_on`.")),
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
