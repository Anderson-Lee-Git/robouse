"""Mobile-manip suite -> Robo Use tasks (suite "mobile-manip"): three mobile manipulators from MuJoCo Menagerie (Hello
Robot Stretch 3, PAL TIAGo, Google Robot; all Apache-2.0) in a small apartment. Backend, scene, controllers, skills,
judge and reference solutions: src/robouse/backends/mobile_manip.py and src/robouse/backends/mobile_manip_sim/.

Usage: python adapters/mobile-manip/generate.py [--out tasks/mobile-manip]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.embodied import write_embodied_task
from robouse.backends.mobile_manip import BASE_HIT_N, HIT_N, TASKS, TIP_DEG, MobileManipBackend
from robouse.prompts import EMBODIED_USAGE

ROBOT = {
    "stretch": ("a Hello Robot Stretch 3 (MuJoCo Menagerie `hello_robot_stretch_3`, Apache-2.0): a differential-drive base 0.34 m "
                "wide, a lift that moves along a vertical mast, and a telescoping arm that sticks out to the robot's right (the -y side "
                "of the robot frame) with a wrist (yaw, pitch) and a two-finger gripper with rubber fingertips (opens to about 16 cm). "
                "The arm works in the vertical plane through the base centre perpendicular to the heading: to reach something, park "
                "with the robot's right side towards it, 0.40 to 0.91 m away (grasp heights 0.11 to 1.21 m). The upstream model's wheel speed limit is raised from "
                "0.1 to 0.25 m/s, close to the real robot's driving speed; everything else (masses, joints, actuators) is upstream."),
    "tiago": ("a PAL TIAGo (MuJoCo Menagerie `pal_tiago`, Apache-2.0): a round differential-drive base 0.54 m across, a torso lift, a "
              "7-joint arm and a parallel two-finger gripper that opens to about 9 cm. The gripper reaches about 0.6 to 0.95 m in "
              "front of the base centre, from about 0.45 m to 1.2 m high. Each finger collides through a flat rubber pad on its inner "
              "face (the upstream finger meshes are kept for looks)."),
    "google": ("the Google Robot (MuJoCo Menagerie `google_robot`, Apache-2.0): a 7-joint arm with a two-finger gripper (opens to "
               "about 12 cm) on a mobile base. Its Menagerie model has no mobile-base joints (the real robot drives on two wheels), "
               "so this suite adds a planar base: x, y and yaw joints on the robot's root, driven by force-limited velocity "
               "actuators. This is a holonomic abstraction: the base can move sideways, which the real robot cannot, and its wheels "
               "hover 3 mm above the floor. The base is about 0.75 m long (0.45 m of it behind the base centre) and 0.8 m wide. The "
               "gripper reaches about 0.55 to 0.9 m in front of the base centre, from about 0.45 m to 1.2 m high."),
}

SCENE = ("You control {robot}\n\nThe robot is in a small apartment simulated with MuJoCo physics. World frame in metres: +x east, "
         "+y north, +z up, floor at z = 0; headings in degrees counter-clockwise from +x (90 = facing north). The apartment spans x "
         "-4..4 and y -2.5..2.5, with 2 m high walls. The living room (x 0..4) is in the east, the kitchen (x -4..0, y 0..2.5) in "
         "the north-west and the study (x -4..0, y -2.5..0) in the south-west. The wall at x = 0 has two 1 m wide doorways: into "
         "the kitchen centred at (0, 1.4) and into the study centred at (0, -1.4). A solid wall at y = 0 separates the kitchen from "
         "the study, so going between them means passing through the living room. Furniture: the dining table (top 1.0 x 0.7 m, "
         "0.75 m high, centred at (2.0, 1.3)), a sofa along the living room's south wall, a bookshelf against the east wall (x "
         "3.55..3.95, y -0.45..0.45, open towards the west, shelves at z = 0.40 and 0.80), a waste bin (0.4 x 0.4 m, 0.35 m high, "
         "centred at (3.3, -1.0)); in the kitchen a counter along the north wall (front face at y = 1.85, top at z = 0.90) with a "
         "drawer in it (a vertical bar handle at (-2.0, 1.78, 0.77) when closed; pull it towards -y, it slides out up to 0.40 m) "
         "and a kitchen table (0.7 x 0.5 m, 0.75 m high, centred at (-3.35, 0.55)); in the study a desk against the south wall "
         "(1.2 x 0.6 m, 0.74 m high, centred at (-2.4, -2.15)). `robo observe` lists every room, doorway and piece of furniture "
         "with exact numbers under `apartment`, and the task objects under `objects`. Everything is solid and simulated: the "
         "base, the arm and anything carried collide with walls and furniture, and objects are held only by friction between the "
         "fingers. The robot starts at {start}, with its arm stowed.")

def safety(rk: str) -> str:
    tilt = "" if rk == "google" else f", or the base tilting more than {TIP_DEG:.0f} degrees"
    return (f"no safety event happened: a hard collision (a contact force above {BASE_HIT_N:.0f} N between a wall, furniture or "
            f"the drawer and the robot's base or body (wheels, mast or torso, head), or above {HIT_N:.0f} N between them and the "
            f"arm or gripper; the fingers are exempt only on the drawer, which they may grip and pull), a task object touching "
            f"the floor, a can, cup or bottle knocked over on a table, shelf or counter{tilt}; `safety_events` in `robo observe` "
            f"lists them")


CONTROLS = {
    "stretch": ("**Controls.** `robo act V WZ DLIFT DEXT DYAW DPITCH POSE G` (8 values, each in [-1, 1]; one step is 50 ms; "
                "`--repeat N` holds it for N steps). `base.twist` V, WZ: forward speed (x 0.25 m/s) and turn rate (x 60 deg/s, "
                "positive = counter-clockwise); the wheel speeds follow from the wheel radius and track, and the base moves by "
                "wheel-floor friction. `arm.lift` DLIFT: sets the lift target to its current height + DLIFT x 2 cm; `arm.extend` "
                "DEXT: sets the telescope target to its current extension + DEXT x 4 cm (0 to 0.52 m); `wrist` DYAW, DPITCH: wrist "
                "yaw and pitch targets = current angle + value x 15 deg (yaw 0 and pitch 0 point the gripper straight along the "
                "arm, fingers closing horizontally). `arm.posture` POSE: above 0.5 starts the move to the ready pose (wrist "
                "straight, gripper open), below -0.5 to the stowed pose (wrist folded in); the move runs by itself unless another "
                "arm command interrupts it. `gripper` G: > 0 closes, < 0 opens (1 = 10 % of the stroke per step); closing stops "
                "squeezing at a bounded force when the fingers meet something. Zero holds everything (the base brakes). Skills "
                "(`robo info` lists their arguments): `drive_to X Y [YAW_DEG] [TOL]` (turns towards the point, drives there in a "
                "straight line, then turns to YAW_DEG; it does not plan around walls or furniture, so give it waypoints through "
                "the doorways, and it stops if the base is blocked), `turn YAW_DEG`, `reach X Y Z` (moves the grasp point, between "
                "the fingertips, to a world point: sets the lift height, drives the base forward or back along its heading to put "
                "the point on the arm's line, then extends; it fails if the point is not 0.40 to 0.91 m to the robot's right), "
                "`grasp`, `open_gripper`, `ready` and `stow`."),
    "tiago": ("**Controls.** `robo act V WZ DX DY DZ POSE G` (7 values, each in [-1, 1]; one step is 50 ms; `--repeat N` holds "
              "it for N steps). `base.twist` V, WZ: forward speed (x 0.45 m/s) and turn rate (x 60 deg/s, positive = "
              "counter-clockwise); the wheel speeds follow from the wheel radius and track, and the base moves by wheel-floor "
              "friction. `arm.ee_delta` DX, DY, DZ: moves the gripper target by that many x 2 cm along the world axes; an "
              "inverse-kinematics controller (arm joints and torso lift) follows it while keeping the gripper level and pointing "
              "along the robot's heading, fingers closing horizontally. The target is held in the robot's frame, so it moves with "
              "the base. `arm.posture` POSE: above 0.5 starts the move to the ready pose (gripper about 0.7 m in front at 0.83 m "
              "height, open), below -0.5 to the stowed pose (arm folded at the side); the move runs by itself unless an "
              "`arm.ee_delta` command interrupts it. `gripper` G: > 0 closes, < 0 opens (1 = 10 % of the stroke per step); the "
              "fingers squeeze with at most about 5 N each. Zero holds everything (the base brakes). Skills (`robo info` lists "
              "their arguments): `drive_to X Y [YAW_DEG] [TOL]` (turns towards the point, drives there in a straight line, then "
              "turns to YAW_DEG; it does not plan around walls or furniture, so give it waypoints through the doorways, and it "
              "stops if the base is blocked), `turn YAW_DEG`, `reach X Y Z` (moves the grasp point, between the fingertips, to a "
              "world point in a straight line; from the stowed pose it goes to the ready pose first), `grasp`, `open_gripper`, "
              "`ready` and `stow`."),
    "google": ("**Controls.** `robo act VX VY WZ DX DY DZ POSE G` (8 values, each in [-1, 1]; one step is 50 ms; `--repeat N` "
               "holds it for N steps). `base.twist` VX, VY, WZ: forward and leftward speed in the robot frame (x 0.5 m/s) and "
               "turn rate (x 60 deg/s, positive = counter-clockwise) of the added planar base. `arm.ee_delta` DX, DY, DZ: moves "
               "the gripper target by that many x 2 cm along the world axes; an inverse-kinematics controller follows it while "
               "keeping the gripper level and pointing along the robot's heading, fingers closing horizontally. The target is "
               "held in the robot's frame, so it moves with the base. The upstream joint servos are soft, so the arm settles "
               "slowly (about a second). `arm.posture` POSE: above 0.5 starts the move to the ready pose (gripper about 0.65 m "
               "in front at 0.8 m height, open), below -0.5 to the stowed pose (arm folded up); the move runs by itself unless an "
               "`arm.ee_delta` command interrupts it. `gripper` G: > 0 closes, < 0 opens (1 = 10 % of the stroke per step). "
               "Zero holds everything. Skills (`robo info` lists their arguments): `drive_to X Y [YAW_DEG] [TOL]` (a straight "
               "line to the point while turning to YAW_DEG; it does not plan around walls or furniture, so give it waypoints "
               "through the doorways, and it stops if the base is blocked), `turn YAW_DEG`, `reach X Y Z` (moves the grasp "
               "point, between the fingertips, to a world point in a straight line; from the stowed pose it goes to the ready "
               "pose first), `grasp`, `open_gripper`, `ready` and `stow`."),
}

OBS = ("**Observation.** `robo observe` reports `robot` (`base` x, y, yaw_deg; `base_velocity`; `gripper` with `pos` (the grasp "
       "point between the fingertips), `opening` (0 closed to 1 open), `holding` (objects touched by both fingers) and "
       "`touching`; `arm_posture`; and {arm}), `objects` (per object: kind, colour, centre position, tilt from upright, "
       "`resting_on`, size and mass), `apartment` (rooms, doorways, furniture with positions and sizes, the drawer's current "
       "`opening_m` and handle position) and `safety_events`. Cameras (`robo observe --image --camera NAME`): `chase` "
       "(default, above and behind the robot, looking north), {own}`overview` (the whole apartment from above, north up), "
       "`living_room_cam`, `kitchen_cam` and `study_cam`.")
ARM_OBS = {"stretch": "`arm` with the lift height, extension and wrist angles",
           "tiago": "`arm.gripper_target`, the IK target",
           "google": "`arm.gripper_target`, the IK target"}
OWN_CAMS = {"stretch": "`robot/head` (the head camera), `robot/wrist` (the gripper camera), ", "tiago": "`robot/head` (the head camera), ",
            "google": "`robot/head` (a camera on the head), "}


def _place_rule(obj: str, where: str) -> str:
    o = obj.replace("_", " ")
    if where == "bin":
        return f"the {o}'s centre is inside the waste bin (within its walls, below its rim) and the robot does not touch it"
    if where == "drawer":
        return (f"the {o}'s centre is inside the drawer (between its walls, at most 5 cm above their top), it touches the drawer, "
                f"and the robot does not touch it (the drawer may stay open)")
    surf = {"shelf": "a shelf of the bookshelf (either one)", "shelf_upper": "the upper shelf of the bookshelf",
            "shelf_lower": "the lower shelf of the bookshelf", "dining_table": "the dining table", "kitchen_table": "the kitchen table"}[where]
    return (f"the {o} stands on {surf}: it touches that surface, its centre is above it, it is upright (tilted less than 20 degrees) "
            f"and the robot does not touch it")


TEXT = {
    "stretch-fetch-cup": dict(
        title="Fetch the cup from the study", difficulty="medium", category="fetch",
        goal="A blue cup stands on the desk in the study. Bring it to the dining table in the living room and leave it standing there."),
    "stretch-open-drawer": dict(
        title="Open the kitchen drawer", difficulty="medium", category="articulated",
        goal="Open the kitchen drawer (in the counter along the kitchen's north wall) by at least 0.25 m, and let go of the handle."),
    "stretch-shelve-two": dict(
        title="Put two things on the bookshelf", difficulty="hard", category="tidy",
        goal=("A red can and a yellow box stand on the dining table. Put both on the bookshelf in the living room (either shelf), "
              "standing upright.")),
    "tiago-fetch-juice": dict(
        title="Fetch the juice box from the kitchen counter", difficulty="medium", category="fetch",
        goal=("A green juice box stands on the kitchen counter. Bring it to the dining table in the living room and leave it "
              "standing there.")),
    "tiago-drawer-stow": dict(
        title="Put the spice box in the drawer", difficulty="hard", category="articulated",
        goal=("An orange spice box stands on the kitchen counter, east of the drawer. Put it inside the kitchen drawer. The drawer is "
              "closed and the robot has one gripper, so plan the order.")),
    "tiago-bin-cans": dict(
        title="Throw the cans away", difficulty="hard", category="tidy",
        goal=("On the dining table are a red can, a white cup and a green can. Throw both cans into the waste bin; the cup must stay "
              "standing on the dining table.")),
    "tiago-study-to-kitchen": dict(
        title="Take the mug to the kitchen", difficulty="hard", category="fetch",
        goal=("A purple mug stands on the desk in the study. Take it to the kitchen table. There is no door between the study and "
              "the kitchen.")),
    "google-fetch-can": dict(
        title="Fetch the can from the kitchen", difficulty="medium", category="fetch",
        goal="A red can stands on the kitchen table. Bring it to the dining table in the living room and leave it standing there."),
    "google-open-drawer": dict(
        title="Open the kitchen drawer", difficulty="easy", category="articulated",
        goal="Open the kitchen drawer (in the counter along the kitchen's north wall) by at least 0.25 m, and let go of the handle."),
    "google-sort-bottle-can": dict(
        title="Sort a bottle and a can", difficulty="hard", category="tidy",
        goal=("A blue bottle and a green can stand on the dining table. Put the bottle on the upper shelf of the bookshelf (standing "
              "upright) and throw the can into the waste bin.")),
}

HEADINGS = {0: "east", 90: "north", 180: "west", -90: "south", 270: "south"}


def success_text(t: dict, rk: str) -> str:
    parts = []
    if "drawer_min" in t:
        parts.append(f"the drawer is open at least {t['drawer_min']:.2f} m (`apartment.furniture.drawer.opening_m`) and no part of "
                     f"the robot touches the drawer (you have let go of the handle)")
    for k, w in t.get("place", {}).items():
        parts.append(_place_rule(k, w))
    for k, w in t.get("keep", {}).items():
        parts.append(f"the {k.replace('_', ' ')} still stands upright on the {w.replace('_', ' ')} and the robot does not touch it")
    parts.append(safety(rk))
    return "; ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "mobile-manip"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for tid, t in TASKS.items():
        x = TEXT[tid]
        rk = t["robot"]
        be = MobileManipBackend({"env": tid})
        sx, sy, syaw = t["start"]
        start = f"({sx:g}, {sy:g}) in the {'living room' if sx > 0 else ('kitchen' if sy > 0 else 'study')}, facing {HEADINGS[int(syaw)]}"
        parts = [f"# {x['title']}",
                 SCENE.format(robot=ROBOT[rk], start=start),
                 "## Task\n\n" + x["goal"],
                 f"**Success:** {success_text(t, rk)}. Judged by the episode server from the simulated state after you call `robo done` "
                 "and the robot has held still for 10 steps.",
                 CONTROLS[rk], OBS.format(arm=ARM_OBS[rk], own=OWN_CAMS[rk]),
                 f"The step budget is {t['max_steps']} steps ({t['max_steps'] * 0.05:.0f} s of simulated time).", EMBODIED_USAGE]
        write_embodied_task(out, task_id=tid, backend="mobile_manip", suite="mobile-manip", title=x["title"],
                            instruction="\n\n".join(parts) + "\n", robot=be.decl.robot, category=x["category"],
                            difficulty=x["difficulty"],
                            tags=["mobile-manipulation", rk, "menagerie", "mujoco", "apartment", x["category"]],
                            max_steps=t["max_steps"], camera=be.camera, cameras=be.decl.cameras,
                            oracle_note="scripted drive_to / reach / grasp skills with waypoints through the doorways.", agent_timeout_s=2700)
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
