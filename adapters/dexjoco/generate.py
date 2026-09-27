"""DexJoCo (github.com/brave-eai/dexjoco, MIT) -> robouse tasks (suite "dexjoco").

Each task is one DexJoCo task started from the initial scene of one recorded human demonstration; the reference solution
replays that demonstration through the robo socket (src/robouse/backends/dexjoco.py, oracle_main). Only demonstrations
that replay to success through the socket are used (see DEMOS below and docs/suites/dexjoco.md).

Prerequisites: the DexJoCo virtualenv and the exported demonstrations (docs/suites/dexjoco.md, "Setup").
Usage: python adapters/dexjoco/generate.py [--demos ~/.cache/robouse/dexjoco-demos/json] [--out tasks/dexjoco]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

from robouse.prompts import ROBO_USAGE
from robouse.tasks import write_task

ROOT = Path(__file__).resolve().parents[2]


def _verify() -> str:
    spec = importlib.util.spec_from_file_location("_mw_generate", ROOT / "adapters" / "metaworld" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.VERIFY  # identical verifier to every other suite


SCENE_SINGLE = ("A Franka Emika Panda arm stands at a table (table top about 0.93-1.0 m above the floor, raised by a random amount per scene) with a "
                "four-fingered Allegro robot hand (16 joints) mounted on its flange instead of a gripper. The hand is about 25 cm "
                "long and 10 cm wide; its fingers are index, middle, ring and thumb. World frame in metres, z up.")
SCENE_BI = ("Two Franka Emika Panda arms stand side by side at a table (table top about 0.93-1.0 m above the floor, "
            "raised by a random amount per scene), each with a four-fingered Allegro robot hand (16 joints) mounted on its flange instead of a gripper. The hands "
            "are about 25 cm long and 10 cm wide; their fingers are index, middle, ring and thumb. World frame in metres, z up.")

CONTROL = ("**Controls.** `robo act` takes {n} numbers{bi}. Per arm: `DX DY DZ` move the commanded hand pose by 2 cm per unit "
           "along world x, y, z (up to +-8 units = 16 cm per step); `RX RY RZ` rotate the commanded hand orientation by 0.2 rad "
           "per unit about the world x, y, z axes (up to +-3); `F0 .. F15` change the commanded finger joint angles by 0.3 rad per "
           "unit (up to +-6): F0-F3 index, F4-F7 middle, F8-F11 ring, F12-F15 thumb. For index, middle and ring, joint 0 spreads "
           "the finger sideways and joints 1-3 curl it (positive = flex toward the palm); for the thumb, joint 0 swings it across "
           "the palm (opposition) and joints 1-3 rotate and curl it. Commands are targets: the arm's operational-space controller "
           "and the finger position servos track them, so the hand lags a fast command and stops where contact blocks it. `robo "
           "info` lists each joint's range (the commanded angle is clipped to it). One step is 20 ms of simulated time. Actions "
           "are deltas, so `--repeat N` applies the same change N times. `robo move-to X Y Z` moves the {arm} hand (the point "
           "`hand_pos`) toward a point without changing its orientation or fingers, and `robo grip G` sets the {arm} hand to a "
           "generic power grasp (G > 0 closes to fraction G of it, G < 0 opens all fingers, 0 keeps them); the grasp preset does "
           "not suit every object, so finger-level `robo act` control is often needed. The `DX DY DZ GRIP` form in the general "
           "instructions below does not apply: every `robo act` needs all {n} numbers.")
LEFT_ORDER = (" In the left hand, DexJoCo orders the three fingers the other way round: L_F0-L_F3 drive the joints DexJoCo "
              "names ring, L_F4-L_F7 middle, L_F8-L_F11 index (thumb stays L_F12-L_F15); take a wrist-camera picture to see "
              "which physical finger moves.")
BI_ACTIVE = ("the *active* arm's; the right arm is active at the start and any `robo act` that moves only one arm makes that arm "
             "active (`active_arm` in `robo observe`)")

FIELDS = ("**Observation.** `robo observe` reports {per}: `hand_pos` and `hand_quat_wxyz` (measured flange position and "
          "orientation, quaternion w, x, y, z), `hand_target_pos` and `hand_target_quat_wxyz` (the commanded pose), "
          "`finger_joints` and `finger_joint_targets` (16 measured and commanded joint angles in radians, in F0..F15 order); "
          "for objects, `<name>_pos` (body origin), `<name>_quat_wxyz`, `<name>_tilt_deg` (angle of the body's z axis from "
          "vertical) and `<name>_yaw_deg`; plus the task fields listed above. `robo observe --image` saves a "
          "picture from the {cam} camera; `--camera` picks another ({cams}). The hand's orientation matters: at the start the "
          "palm faces down; look at a picture before you reach.")

T: dict[str, dict] = {
    "water_plant": dict(
        title="Water the Plant", difficulty="hard", tags=["tool-use", "trigger", "single-arm"],
        goal=("A trigger sprayer (a hand-held spray bottle with a trigger under its nozzle) stands on the table and a potted plant "
              "stands a little further away. Pick up the sprayer, bring its nozzle to the plant, and squeeze the trigger to "
              "water the plant."),
        success=("the trigger is pulled (`sprayer_trigger_angle` above 0.34 rad; it counts as released again below 0.25) while "
                 "`nozzle_ref_point` is within 20 cm of the plant's centre line horizontally and within 20 cm of `plant_pos` "
                 "vertically, continuously for 30 steps (0.6 s). **Failure:** pulling the trigger while the nozzle is outside that "
                 "zone ends any chance of success (`task_failed` appears)."),
        fields=("`sprayer_*` (bottle pose), `sprayer_trigger_angle` (rad; 0 released), `nozzle_ref_point` (a point at the "
                "nozzle) and `plant_*`.")),
    "hammer_nail": dict(
        title="Hammer the Nail", difficulty="hard", tags=["tool-use", "impact", "single-arm"],
        goal=("A hammer stands on the table and a nail sticks up out of a wooden block. Pick up the hammer by its handle and drive "
              "the nail into the wood by striking its head."),
        success=("the nail has been driven `nail_success_depth` (4 cm) deep. Each strike of the hammer on the nail while the hammer "
                 "is moving downward (faster than 2 cm/s just before contact) drives it 8 mm, so it takes about five separate "
                 "strikes; pressing or resting the hammer on the nail does nothing."),
        fields="`hammer_*` (hammer pose), `nail_head` (position of the nail), `nail_depth` and `nail_success_depth` (m)."),
    "click_mouse": dict(
        title="Click the Mouse", difficulty="hard", tags=["tool-use", "button", "single-arm"],
        goal=("A computer mouse lies on the table next to a monitor and a round mousepad. Move the mouse onto the mousepad and "
              "click its left button, which turns the monitor blue."),
        success=("the mouse is on the mousepad (its centre within `mousepad_radius` of the pad centre horizontally and within 5 "
                 "cm vertically) when its left button is pressed (`mouse_left_button`, the button's slide "
                 "position in metres, rises more than 1 mm above its value at the start), which sets `display_blue`; then the mouse stays on the pad with the display blue for 10 steps."),
        fields=("`mouse_*` (mouse pose), `mouse_left_button` (button slide position, m), `mousepad` (pad centre), `mousepad_radius`, "
                "`monitor_*` and `display_blue`.")),
    "pick_bucket": dict(
        title="Fill and Lift the Bucket", difficulty="hard", tags=["tool-use", "handle", "single-arm", "two-stage"],
        goal=("A small bucket with a swinging wire handle and a boxed food item stand on the table. Put the food box into the "
              "bucket, then lift the bucket by its handle."),
        success=("the food box's centre is inside the bucket and every point of the bucket's bottom is at least 15 cm above where "
                 "it started."),
        fields="`bucket_*` (bucket pose), `bucket_handle_angle` (rad) and `food_box_*`."),
    "pinch_tongs": dict(
        title="Pinch the Tongs", difficulty="hard", tags=["tool-use", "articulated", "single-arm"],
        goal=("A pair of kitchen tongs lies on the table. Pick them up, hold them at least 10 cm above the table, and squeeze "
              "them shut three times."),
        success=("the tongs are at or above `lift_height_z` and `pinch_count` is at least 3, continuously for 30 steps (0.6 s). "
                 "A pinch counts when `tongs_opening` (hinge angle, rad) first rises above 0.1 (open) and then drops to -0.07 or "
                 "below (squeezed shut)."),
        fields="`tongs_*` (tongs pose), `tongs_opening` (rad), `pinch_count` and `lift_height_z`."),
    "fold_glasses": dict(
        title="Fold the Glasses", difficulty="hard", tags=["articulated", "precision", "single-arm"],
        goal=("A pair of glasses lies open on the table next to an open box. Fold both temples (the arms of the glasses) shut "
              "and put the folded glasses into the box."),
        success=("both temple hinge angles (`left_temple_angle`, `right_temple_angle`) are above 1.1 rad and the glasses' centre is "
                 "inside the box's inner cavity (within 14.5 cm of the box centre along x and y, between 4.5 cm below and 2.75 cm "
                 "above it), continuously for 50 steps (1 s)."),
        fields="`glasses_*` (frame pose), `left_temple_angle`, `right_temple_angle` (rad; 0 = open) and `open_box_*`."),
    "bimanual_microwave_cook": dict(
        title="Cook a Hot Dog in the Microwave", difficulty="hard", tags=["bimanual", "articulated", "long-horizon", "appliance"],
        goal=("A microwave oven and a hot dog stand on the table. Open the microwave door, put the hot dog inside, close the door, "
              "and press the start button."),
        success=("the hot dog is inside the microwave's cavity, the door is closed (`microwave_door_angle` within 0.01 rad of 0) "
                 "and the start button is being touched, all at the same time."),
        fields=("`hot_dog_*`, `microwave_*` (oven body pose), `microwave_door_angle` (rad; 0 = closed) and `start_button` "
                "(button position).")),
    "bimanual_photograph": dict(
        title="Take a Photograph", difficulty="hard", tags=["bimanual", "tool-use", "camera", "aiming"],
        goal=("A compact camera lies on the table and a logo is displayed in front of the robots. Pick the camera up, aim it at "
              "the logo from the marked shooting position, and press the shutter button."),
        success=("the shutter button is pressed (touched by something other than the camera itself) while the camera's view point "
                 "(`camera_view_point`) is within 16 cm of `target_region_center` sideways and 10 cm vertically, and the lens axis "
                 "points within 10 degrees of world +x."),
        fields=("`camera_*` (camera body pose), `shutter_button` (button position), `camera_view_point` and "
                "`target_region_center` (the shooting position).")),
    "bimanual_unlock_ipad": dict(
        title="Unlock the iPad", difficulty="hard", tags=["bimanual", "buttons", "sequence", "failure-event"],
        goal=("An iPad stands in a stand on the table, its lock screen facing the robots and showing a keypad of digit buttons. Enter the passcode "
              "1, 2, 3 by pressing those digit buttons in that order with the fingertips."),
        success=("the three digits are entered in order and the screen unlocks, then stays unlocked for 10 steps. A press is a new "
                 "fingertip contact with a button. **Failure:** touching any wrong digit button at any time ends any chance of "
                 "success (`task_failed` appears), so keep the hands clear of the other buttons."),
        fields=("`ipad_*`, `stand_*`, `button_0` .. `button_9` (button centre positions; buttons hide once unlocked), "
                "`digits_entered` and `unlocked`.")),
    "bimanual_assembly": dict(
        title="Peg-in-Hole Assembly", difficulty="hard", tags=["bimanual", "insertion", "precision"],
        goal=("A round peg (8 mm across) and a socket block with a matching hole lie on the table. Pick them up and insert the peg "
              "fully into the socket's hole."),
        success="the peg touches the bottom of the socket's hole continuously for 30 steps (0.6 s).",
        fields="`peg_*` and `socket_*` (poses of the two parts)."),
}

DESC = {
    "water_plant": "Pick up a trigger sprayer with a dexterous hand and water a plant without spraying elsewhere.",
    "hammer_nail": "Pick up a hammer with a dexterous hand and drive a nail with repeated strikes.",
    "click_mouse": "Slide a mouse onto its pad and click its left button with a dexterous hand.",
    "pick_bucket": "Put a food box into a bucket, then lift the bucket by its wire handle.",
    "pinch_tongs": "Pick up kitchen tongs, hold them up and squeeze them shut three times.",
    "fold_glasses": "Fold both temples of a pair of glasses and put them into a box.",
    "bimanual_microwave_cook": "With two dexterous hands, open a microwave, put a hot dog in, close it and press start.",
    "bimanual_photograph": "With two dexterous hands, aim a camera at a logo from a marked position and press the shutter.",
    "bimanual_unlock_ipad": "With two dexterous hands, press an iPad's passcode 1-2-3 without touching a wrong digit.",
    "bimanual_assembly": "With two dexterous hands, insert an 8 mm peg into a socket.",
}

# (robouse task id, DexJoCo task, timestamp suffix of the demonstration folder whose initial scene and actions it uses). Demonstrations were chosen among those that replay to success
# through the robo socket on macOS (docs/suites/dexjoco.md lists which ones do not).
DEMO_LIST = [
    ("dexjoco-water-plant", "water_plant", "2026-02-05_19-50-27_886249"),
    ("dexjoco-water-plant-b", "water_plant", "2026-02-05_21-14-32_009457"),
    ("dexjoco-hammer-nail", "hammer_nail", "2026-02-05_19-18-55_029010"),
    ("dexjoco-hammer-nail-b", "hammer_nail", "2026-02-05_19-19-09_111243"),
    ("dexjoco-click-mouse", "click_mouse", "2026-03-10_20-07-29_950914"),
    ("dexjoco-click-mouse-b", "click_mouse", "2026-03-12_12-49-21_742058"),
    ("dexjoco-pick-bucket", "pick_bucket", "2026-03-11_20-12-38_921506"),
    ("dexjoco-pick-bucket-b", "pick_bucket", "2026-03-11_21-13-52_454537"),
    ("dexjoco-pinch-tongs", "pinch_tongs", "2026-03-12_16-30-04_442884"),
    ("dexjoco-fold-glasses", "fold_glasses", "2026-03-16_09-48-20_469064"),
    ("dexjoco-microwave-cook", "bimanual_microwave_cook", "2026-02-09_17-09-31_847162"),
    ("dexjoco-photograph", "bimanual_photograph", "2026-03-16_14-31-13_305518"),
    ("dexjoco-unlock-ipad", "bimanual_unlock_ipad", "2026-03-22_14-10-52_406095"),
    ("dexjoco-assembly", "bimanual_assembly", "2026-03-19_17-36-54_867270"),
]


def build(tid: str, task: str, rec: dict) -> tuple[dict, str]:
    info = T[task]
    bi = task.startswith("bimanual_")
    n = 44 if bi else 22
    ctrl = CONTROL.format(n=n, bi=(": the right arm's 22 (`R_DX .. R_F15`), then the left arm's 22 (`L_DX .. L_F15`)" if bi else
                                   " (`DX DY DZ RX RY RZ F0 .. F15`)"),
                          arm=BI_ACTIVE if bi else "")
    ctrl = ctrl.replace("moves the  hand", "moves the hand").replace("sets the  hand", "sets the hand")
    if bi:
        ctrl = ctrl.replace("F12-F15 thumb.", "F12-F15 thumb." + LEFT_ORDER)
    cam = "back" if bi else "front"
    cams = "`back`, `handcam_rgb_right`, `handcam_rgb_left`" if bi else "`front`, `top0` (overhead), `left`, `right`, `handcam_rgb` (wrist)"
    per = ("for each arm, prefixed `right_` / `left_`" if bi else "for the arm")
    max_steps = 3000 if bi else 2500
    body = (f"# {info['title']} (DexJoCo)\n\n{SCENE_BI if bi else SCENE_SINGLE}\n\n"
            f"**Goal:** {info['goal']}\n\n"
            f"**Success:** {info['success'][0].upper() + info['success'][1:]} The episode ends as solved the moment this "
            f"condition is met; `robo done` before that scores 0.\n\n"
            f"**Task fields in `robo observe`:** {info['fields']}\n\n"
            f"{ctrl}\n\n{FIELDS.format(per=per, cam=cam, cams=cams)}\n\n"
            f"The step budget is {max_steps} steps ({max_steps * 0.02:.0f} s of simulated time). A human teleoperator needed "
            f"{len(rec['actions'])} steps for this scene.\n\n" + ROBO_USAGE)
    meta = {
        "task": {"name": f"robouse/{tid}", "description": DESC[task]},
        "metadata": {"source_benchmark": "DexJoCo (brave-eai/dexjoco, MIT; arXiv 2605.16257)", "source_task": task,
                     "source_demo": rec["source"], "suite": "dexjoco", "category": "manipulation",
                     "difficulty": info["difficulty"],
                     "tags": ["mujoco", "dexterous", "allegro", "panda", *info["tags"]]},
        "agent": {"timeout_sec": 2400},
        "verifier": {"timeout_sec": 120},
        "robouse": {"id": tid, "backend": "dexjoco", "env": task, "seed": 0, "max_steps": max_steps, "camera": cam,
                    "cameras": ["back", "handcam_rgb_right", "handcam_rgb_left"] if bi else ["front", "top0", "left", "right", "handcam_rgb"],
                    "skills": True, "success_mode": "first", "max_repeat": 50,
                    "init_state": [round(x, 7) for x in rec["init_state"]]},
    }
    return meta, body


ORACLE = """#!/bin/bash
# Reference solution: replays one recorded DexJoCo human demonstration (oracle/demo.json, absolute hand-pose and finger
# targets) through the robo socket, converted to the task's delta actions (src/robouse/backends/dexjoco.py, oracle_main).
set -euo pipefail
python -m robouse.oracle --backend dexjoco --env "$(cd "$(dirname "$0")" && pwd)/demo.json"
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demos", default=str(Path.home() / ".cache/robouse/dexjoco-demos/json"))
    ap.add_argument("--out", default=str(ROOT / "tasks" / "dexjoco"))
    a = ap.parse_args()
    out = Path(a.out)
    verify = _verify()
    for tid, task, demo in DEMO_LIST:
        hits = sorted(Path(a.demos).glob(f"{task}__*{demo}.json"))  # demo: the recording's timestamp suffix
        if len(hits) != 1:
            raise SystemExit(f"{tid}: expected one demonstration matching {task}__*{demo}.json, found {len(hits)}")
        rec = json.loads(hits[0].read_text())
        meta, body = build(tid, task, rec)
        d = out / tid
        if d.exists():
            shutil.rmtree(d)
        write_task(d, meta, body, ORACLE, verify)
        (d / "oracle" / "demo.json").write_text(json.dumps({"task": task, "demo": rec["demo"], "source": rec["source"],
                                                             "actions": rec["actions"], "extra_steps": 120}))
        print("wrote", d)


if __name__ == "__main__":
    main()
