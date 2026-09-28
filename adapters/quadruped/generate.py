"""Quadruped suite -> Robo Use tasks (suite "quadruped"): Unitree Go2, Unitree Go1, Boston Dynamics Spot (with and without
its arm) and ANYbotics ANYmal C (MuJoCo Menagerie, BSD-3-Clause) in a small indoor plant. Backend, scene, trot
controller, skills, judge and reference solutions: src/robouse/backends/quadruped.py and quadruped_sim/gait.py.

Usage: python adapters/quadruped/generate.py [--out tasks/quadruped]
"""
from __future__ import annotations

import argparse
import math
import shutil
from pathlib import Path

from robouse.backends.embodied import write_embodied_task
from robouse.backends.quadruped import (BOARD, BUTTONS, CABINET, DOCK, INSPECT_STEPS, MAT, PLATFORM, PUMP, RAMP, TAG_MAX_DEPTH, TASKS,
                                        VALVE, QuadrupedBackend)
from robouse.backends.quadruped_sim.gait import CFGS
from robouse.prompts import EMBODIED_USAGE

SCENE = ("You control {who} (MuJoCo Menagerie model, {size}) in a small indoor plant. World frame in metres: +x east, +y north, +z up, "
         "floor at z = 0; headings are in degrees, 0 = facing +x (east), 90 = facing +y (north). The plant is 12 m x 8 m (x from -6 to 6, "
         "y from -4 to 4), closed by 1 m walls. A partition wall at x = 1 separates the west hall from the east plant room; its only "
         "opening is a 1.1 m wide doorway (y from 1.5 to 2.6) at the east end of a corridor (walls at y = 1.3 and y = 2.9, from x = -2.2 "
         "to the partition; open at its west end). The west hall has the blue dock (0.9 m square at (-4.8, -2.8)), a row of crates "
         "(0.6 m cubes, 0.8 m high, at x = -3.2 from y = -3.95 to -0.95) and one more crate at (-1.9, -1.1), a green mat at (-1.2, -2.8), "
         "and a pipe with a valve and an inspection tag on the west wall. The east room has a pump (radius 0.3 m, 0.6 m high, at (4.2, -2.6)) "
         "with an asset tag, an instrument board with a pressure gauge 1.4 m up on the east wall, a yellow panel with a red emergency-stop "
         "button and a green reset button on the east wall, and a 0.2 m high mezzanine platform in the north-east corner (x 4.4-6, "
         "y 1.6-4) with a control cabinet, reached by a ramp (x 2.8-4.4, y 2.4-3.4) that rises eastwards. Every fixed position is "
         "listed under `facility` in `robo observe`. {honesty}")
HONESTY = ("The robot stands on a free-floating base: only its feet touching the floor move it, so it can slip, trip over obstacles or fall; a fall "
           "(base tilted more than 50 degrees, or the body touching the floor or the ramp) is recorded in `safety_events` and fails the task.")

WHO = {"go2": ("a Unitree Go2 quadruped", "15 kg, 0.7 m long, base about 0.29 m above the floor when standing"),
       "go1": ("a Unitree Go1 quadruped", "13 kg, 0.65 m long, base about 0.27 m above the floor when standing"),
       "spot": ("a Boston Dynamics Spot quadruped", "50 kg, 1.1 m long, base about 0.47 m above the floor when standing"),
       "spot_arm": ("a Boston Dynamics Spot quadruped with its 6-joint arm and gripper", "56 kg, 1.1 m long, base about 0.47 m above the floor when standing"),
       "anymal": ("an ANYbotics ANYmal C quadruped", "45 kg, 1.0 m long, base about 0.47 m above the floor when standing")}


def controls(robot: str, skills: bool) -> str:
    c = CFGS[robot]
    vx, vy, wz = c.v_max
    arm = robot == "spot_arm"
    s = (f"**Controls.** `robo act VX VY WZ DHEIGHT DPITCH{' DX DY DZ' if arm else ''}` sets the action for the next step(s). "
         f"VX and VY (m/s, up to +-{vx} and +-{vy}) and WZ (deg/s, up to +-{math.degrees(wz):.0f}, counter-clockwise seen from above) are "
         "the body-frame velocity command (x forward, y left) for the onboard trot controller (gait clock, foot placement from the "
         "commanded and measured velocity, leg inverse kinematics, attitude feedback and joint servos); all three zero means stop stepping and "
         "stand. DHEIGHT (m, +-0.02 per step) and DPITCH (deg, +-5 per step) change the body-height and nose-up pitch setpoints (height "
         "from -45 % to +5 % of the standing height, pitch +-20 degrees; a non-zero velocity command raises a lowered body to at least 85 % "
         "of the standing height); zero keeps them.")
    if arm:
        s += (" DX DY DZ (m, +-0.03 per step) move the gripper-tip target in the body frame (x forward, y left, z up); zero holds it. The "
              "arm controller (inverse kinematics and joint position servos) keeps the jaw pointing forward and the gripper closed; the tip "
              "reaches about 1 m from the shoulder, which sits on top of the body 0.29 m ahead of its centre.")
    s += " One step is 50 ms; `--repeat N` holds an action for N steps."
    if not skills:
        return s + " `robo skill` is disabled in this task."
    s += (" Skills (`robo info` lists them with their arguments): `walk_to X Y [TOL] [SPEED]` (turns towards the point and trots along the "
          "straight line, then stops; it does not avoid obstacles and reports when it is blocked), `turn YAW_DEG`, `stand` (stop, standing "
          "height, level body), `sit` (stop and lie down at the lowest body height; a velocity command raises the body again) and `look_at X Y Z [SECONDS]` "
          "(turn to face the point, pitch the body so the head camera points at height Z within +-20 degrees, hold still, and report where "
          "the point falls in the head image).")
    if arm:
        s += (" Arm skills: `reach X Y Z [TOL]` (moves the gripper tip in a straight line to a world point while the legs stand; it stops at "
              "contact or when out of reach) and `stow`.")
    return s


def observation(robot: str) -> str:
    arm = robot == "spot_arm"
    return ("**Observation.** `robo observe` reports `robot` (`pos` of the base centre, `yaw_deg`, `roll_deg`, `pitch_up_deg`, `vel_body`, "
            "`yaw_rate_deg_s`, `gait` = standing / walking / sitting, `body_pose_setpoint`, `standing_height_m`, `feet_in_contact`, the "
            "`head_camera` position and forward direction, and `fallen`), "
            + ("`arm` (gripper `tip_pos` in the world and body frames, the tip target and the joint angles), " if arm else "")
            + "`facility` (every fixed landmark), `objects` (this task's movable objects and floor markings, if any), `progress` "
            "(`inspected_tags`, and the task's counters) and `safety_events`. Cameras: `chase` (default; follows the robot from above and "
            "behind-left), `head` (forward-facing on the front of the base, 70 degree field of view, square image), `overview`, "
            "`west_hall` and `east_room`.")


def inspect_rule(tags: list[str]) -> str:
    depth = {TAG_MAX_DEPTH[t] for t in tags}
    return (f"a tag counts as inspected when, for {INSPECT_STEPS * 0.05:.0f} s ({INSPECT_STEPS} consecutive steps), the robot stood still (not "
            "stepping, base slower than 0.1 m/s and turning slower than 11 deg/s) while the tag's centre was in the central half of the head "
            f"camera image (both image coordinates within half the distance from the centre to the border), 0.3-{max(depth)} m in front "
            "of the camera, unoccluded (a ray from the camera reaches the tag) and seen from within 60 degrees of the direction the tag "
            "faces; `progress.inspected_tags` lists the tags inspected so far")


def _tag(pos) -> str:
    return f"({pos[0]}, {pos[1]}, {pos[2]})"


def texts() -> dict:
    red, green = BUTTONS["estop"]["c"], BUTTONS["reset"]["c"]
    standing = "at the end the robot is standing still (not stepping, base slower than 0.1 m/s)"
    never = "and it never fell"
    return {
        "go2-crate-detour": dict(
            title="Crate detour", difficulty="easy", category="navigation",
            goal=(f"The Go2 stands on the dock at {DOCK['c']}, facing east. Walk to the green mat at {MAT['c']} and stop on it. The row of "
                  "crates stands between the dock and the mat, and one more crate stands north-west of the mat; plan a route around them."),
            success=f"the base centre is within 0.35 m (horizontally) of the mat centre {MAT['c']}, {standing}, {never}"),
        "go2-crate-detour-manual": dict(
            title="Crate detour (no skills)", difficulty="medium", category="navigation",
            goal=(f"The Go2 stands on the dock at {DOCK['c']}, facing east. Walk to the green mat at {MAT['c']} and stop on it, using only "
                  "`robo act` velocity commands (skills are disabled). The row of crates stands between the dock and the mat, and one "
                  "more crate stands north-west of the mat; plan a route around them."),
            success=f"the base centre is within 0.35 m (horizontally) of the mat centre {MAT['c']}, {standing}, {never}"),
        "go2-push-box": dict(
            title="Push the box into the zone", difficulty="hard", category="manipulation",
            goal=("The Go2 stands in the east room just inside the doorway, at (1.8, 2.05), facing east. An orange 0.4 m cube (3 kg, "
                  f"friction 0.4 on the floor) stands at {TASKS['go2-push-box']['box']}. Push it into the square zone marked by yellow lines, "
                  f"1.0 m x 1.0 m, centred at {TASKS['go2-push-box']['zone']}. The robot has no arm: push with the front of its body, "
                  "slowly, and re-align behind the box when it drifts sideways (`objects.box` gives its position and heading)."),
            success=f"every corner of the box's footprint lies inside the zone, the box is upright, {standing}, {never}"),
        "go2-pump-inspection": dict(
            title="Pump tag inspection", difficulty="medium", category="inspection",
            goal=(f"The Go2 stands on the dock at {DOCK['c']}, facing north. Walk into the east room and inspect the asset tag on the pump: "
                  f"its centre is at {_tag(PUMP['tag'])} and it faces west (-x). Use the head camera; `robo observe --image --camera head` "
                  "shows what it sees."),
            success=f"the pump tag has been inspected, {never}; {inspect_rule(['pump'])}"),
        "go1-corridor-charger": dict(
            title="Back to the charger", difficulty="medium", category="navigation",
            goal=(f"The Go1 stands on the dock at {DOCK['c']}, facing east. Its charger is in the east room: an orange 0.7 m pad centred at "
                  f"{TASKS['go1-corridor-charger']['pad']}, with a charging post on its south edge. Go there (the only way into the east room "
                  "is the corridor and doorway) and lie down on the pad so that the charging contacts on the robot's belly touch it: "
                  "`robo skill sit`, or lower the body with DHEIGHT until the height setpoint is at its minimum, while standing still."),
            success=("the base centre is over the pad (within 0.35 m of its centre in x and in y), the robot is lying down (stopped, with the "
                      f"body-height setpoint at its minimum and the base at most {0.7 * CFGS['go1'].height:.2f} m above the floor), {never}")),
        "go1-patrol": dict(
            title="Patrol round", difficulty="hard", category="navigation",
            goal=("The Go1 stands on the dock, facing east. Walk a patrol: visit the three purple floor checkpoints in this order, A at "
                  "(-1.2, -2.8) behind the crates in the west hall, then B at (4.0, 1.0) and C at (2.4, -3.0) in the east room, and return to "
                  "the dock."),
            success=(f"the base centre came within 0.35 m of A, then B, then C, in that order (`progress.checkpoints_reached_in_order`), and "
                     f"at the end the base centre is on the dock (within 0.45 m of {DOCK['c']} in x and in y), {standing}, {never}")),
        "spot-gauge-reading": dict(
            title="Read the pressure gauge", difficulty="medium", category="inspection",
            goal=("Spot stands at the west end of the corridor at (-2.9, 2.1), facing east. Inspect the pressure gauge on the instrument "
                  f"board on the east wall of the east room: the dial centre is at {_tag(BOARD['gauge'])}, 1.4 m up, facing west. The head "
                  "camera is about 0.55 m above the floor, so get close and pitch the body up (DPITCH, or the `look_at` skill)."),
            success=f"the gauge has been inspected, {never}; {inspect_rule(['gauge'])}"),
        "spot-arm-estop": dict(
            title="Press the emergency stop", difficulty="medium", category="manipulation",
            goal=("Spot with its arm stands in the east room at (2.0, -1.0), facing east. On the east wall a yellow panel carries a red "
                  f"emergency-stop button (cap face centre {red}) and a green reset button ({green}); both caps are 9 cm across, face west and "
                  "travel 3 cm into the panel against a spring. Walk up to the panel and press the red button with the gripper."),
            success=("the red button's cap was pushed in by more than 15 mm at some time in the episode (`progress.buttons_pressed`), "
                     f"{standing}, {never}")),
        "spot-arm-reset": dict(
            title="Press reset, not the e-stop", difficulty="medium", category="manipulation",
            goal=("Spot with its arm stands in the east room at (2.0, 1.5), facing south. On the east wall a yellow panel carries a red "
                  f"emergency-stop button (cap face centre {red}) and, 35 cm north of it, a green reset button ({green}); both caps are 9 cm "
                  "across, face west and travel 3 cm into the panel against a spring. Press the green reset button with the gripper. Do not "
                  "press the red button: that shuts the plant down."),
            success=("the green button's cap was pushed in by more than 15 mm at some time (`progress.buttons_pressed`), the red button was "
                     f"never pushed in by more than 15 mm (that is recorded in `safety_events` and fails the task), {standing}, {never}")),
        "anymal-inspection-round": dict(
            title="Inspection round", difficulty="hard", category="inspection",
            goal=(f"ANYmal stands on the dock at {DOCK['c']}, facing east. Inspect the valve tag on the west wall (centre "
                  f"{_tag(VALVE['tag'])}, facing east) and the asset tag on the pump in the east room (centre {_tag(PUMP['tag'])}, facing "
                  "west), in either order, then return to the dock and stand on it."),
            success=(f"both tags have been inspected, and at the end the base centre is on the dock (within 0.45 m of {DOCK['c']} in x and "
                     f"in y), {standing}, {never}; {inspect_rule(['valve', 'pump'])}")),
        "anymal-mezzanine-cabinet": dict(
            title="Cabinet on the mezzanine", difficulty="medium", category="inspection",
            goal=("ANYmal stands in the east room at (2.0, 0.0), facing north. A control cabinet stands on the 0.2 m high mezzanine "
                  f"platform (x {PLATFORM['x'][0]}-{PLATFORM['x'][1]}, y {PLATFORM['y'][0]}-{PLATFORM['y'][1]}); its tag is at "
                  f"{_tag(CABINET['tag'])} and faces south. The platform's edges are a 0.2 m step that the trot controller cannot climb; "
                  f"the ramp (x {RAMP['x'][0]}-{RAMP['x'][1]}, y {RAMP['y'][0]}-{RAMP['y'][1]}) rises eastwards onto the platform. Inspect "
                  "the cabinet tag with the head camera."),
            success=f"the cabinet tag has been inspected, {never}; {inspect_rule(['cabinet'])}"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "quadruped"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    T = texts()
    for tid, t in TASKS.items():
        x = T[tid]
        robot = t["robot"]
        skills = t.get("skills", True) is not False
        be = QuadrupedBackend({"env": tid})
        who, size = WHO[robot]
        parts = [f"# {x['title']}", SCENE.format(who=who, size=size, honesty=HONESTY), "## Task\n\n" + x["goal"],
                 f"**Success:** {x['success']}. Judged by the episode server from the simulated state after you call `robo done` and the "
                 "robot has held still (zero action) for 10 steps.",
                 controls(robot, skills), observation(robot),
                 f"The step budget is {t['max_steps']} steps ({t['max_steps'] * 0.05:.0f} s).", EMBODIED_USAGE]
        name = CFGS[robot].name
        write_embodied_task(out, task_id=tid, backend="quadruped", suite="quadruped", title=x["title"], instruction="\n\n".join(parts) + "\n",
                            robot=name, category=x["category"], difficulty=x["difficulty"],
                            tags=["quadruped", "legged", CFGS[robot].folder, "menagerie", "mujoco"] + (["arm"] if robot == "spot_arm" else []),
                            max_steps=t["max_steps"], camera=be.camera, cameras=be.decl.cameras,
                            oracle_note=("a heading-controlled waypoint follower through robo act only." if not skills
                                         else "scripted waypoints with the walk_to / turn / look_at / sit / reach skills."),
                            extra_robouse=None if skills else {"skills": False})
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
