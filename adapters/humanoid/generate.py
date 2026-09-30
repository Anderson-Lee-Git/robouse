"""Humanoid suite -> Robo Use tasks (suite "humanoid"): upper-body table-top manipulation with four MuJoCo Menagerie
humanoids (Unitree G1 with Dex3-1 hands, Unitree H1, Apptronik Apollo, Booster T1), each fixed to a support stand.
Backend, controller and skills: src/robouse/backends/humanoid.py; scenes and success rules:
src/robouse/backends/humanoid_sim/tasks.py; reference solutions: src/robouse/backends/humanoid_sim/oracles.py.

Usage: python adapters/humanoid/generate.py [--out tasks/humanoid]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.embodied import write_embodied_task
from robouse.backends.humanoid import CONTROL_DT, HumanoidBackend
from robouse.backends.humanoid_sim.tasks import TASKS
from robouse.prompts import EMBODIED_USAGE

FRAME = ("World frame in metres: +x points forward from the robot, +y to the robot's left, +z up; the floor is at z = 0 and "
         "the origin is on the floor below the robot's pelvis.")

ROBOT = {
    "g1": ("You control a Unitree G1 humanoid (1.32 m; MuJoCo Menagerie `unitree_g1`, BSD-3-Clause) with Dex3-1 three-finger "
           "hands (a thumb and two fingers per hand). The robot is mounted on a support stand (its pelvis is welded to the stand): it does not balance or "
           "walk, its legs hold a standing pose and its waist is bent 26 degrees forward over a table in front of it. Only the arms "
           "and fingers move."),
    "h1": ("You control a Unitree H1 humanoid (1.8 m; MuJoCo Menagerie `unitree_h1`, BSD-3-Clause). It has no hands: each 4-joint arm "
           "ends in a round fist (6.6 cm ball). The robot is mounted on a support stand (its pelvis is welded to the stand): it does not balance or walk, "
           "its legs hold a standing pose and only the arms move. A counter stands in front of it."),
    "apollo": ("You control an Apptronik Apollo humanoid (1.73 m; MuJoCo Menagerie `apptronik_apollo`, Apache-2.0). Its hands are "
               "rigid plates (about 8 cm wide, 17 cm long and 4 cm thick; the modelled fingers do not move). The robot is mounted on a "
               "support stand (its pelvis is welded to the stand): it does not balance or walk, its legs hold a standing pose and its torso is pitched 14 "
               "degrees forward over a table. The arms and the neck move."),
    "t1": ("You control a Booster T1 humanoid (1.18 m; MuJoCo Menagerie `booster_t1`, Apache-2.0). Each 4-joint arm ends in a rigid "
           "round hand (6 cm across, no fingers). The robot is mounted on a support stand (its trunk is welded to the stand), leaning 20 degrees forward over "
           "a low table: it does not balance or walk and its legs hold a standing pose. The arms and the neck move."),
}

HAND = {
    "g1": ("Each hand's control point is its grasp point, between the thumb and the fingers. The arm controller keeps the hand "
           "level with the fingers pointing forward (+x) and the palm facing the robot's midline; the two fingers are on the outer "
           "side of the control point and reach 8 cm in front of it, the thumb is on the inner side. An object whose centre is at "
           "the control point sits between thumb and fingers (the open hand is about 6 cm wide inside); closing the fingers wraps "
           "them around it (a friction grasp). The hand cannot tilt, so objects are approached from behind (-x) or from above, "
           "and each hand reaches only about 10 cm past the robot's midline (y = 0)."),
    "h1": ("Each hand's control point is the centre of its fist. The arms have four joints, so the forearm's angle follows from "
           "where the fist is; the forearms also touch things. Objects are pushed, pressed or squeezed between the two fists or "
           "forearms."),
    "apollo": ("Each hand's control point is the centre of its hand plate. The arm controller keeps both hands pointing forward "
               "(+x) with the palms facing each other; the forearms are a little wider than the plates, so a box squeezed between "
               "the hands also touches the forearms. Each hand reaches only a little past the robot's midline (y = 0)."),
    "t1": ("Each hand's control point is the tip of its round hand. The arms have four joints, so the hand's angle follows from "
           "where the tip is. Objects are pushed with the hand or squeezed between both hands; each hand works on its own side "
           "of the table (it reaches only a few centimetres past the midline y = 0)."),
}


def controls(be: HumanoidBackend) -> str:
    rk = be.rk
    names = " ".join(n for g in be.decl.action_groups for n in g.names)
    parts = [f"**Controls.** `robo act {names}`, each in [-1, 1]. LDX LDY LDZ and RDX RDY RDZ move the goal point of the left and "
             "right hand by up to 2 cm per step along world x, y, z; an arm controller (inverse kinematics and joint servos) moves the "
             "hand after its goal, stops when the hand is blocked and keeps the goal within reach. Zero keeps the goal where it is, "
             "so an all-zero action holds the robot still."]
    if rk == "g1":
        parts.append("LGRIP and RGRIP close (+1) or open (-1) the fingers of that hand by 0.2 of their range per step (0 keeps the current "
                     "finger command); the fingers stop when they press on something, with the Dex3's own joint torque limits.")
    if be.has_head:
        parts.append("HYAW turns the head left (+) or right (-) and HPITCH tilts it down (+) or up (-), by up to 3 degrees per step; "
                     "the `head` camera moves with the head.")
    parts.append(f"One step is {CONTROL_DT * 1000:.0f} ms; `--repeat N` applies an action N times.")
    sk = ["`reach SIDE X Y Z [TOL]` (move one hand's control point in a straight line to a point; reports whether it arrived, was "
          "blocked or hit the edge of its reach, and what the hand touches)",
          "`reach_both XL YL ZL XR YR ZR [TOL]` (both hands at once, for bimanual holds)", "`home` (both hands back to their start "
          "points)", "`wait [STEPS]`"]
    if rk == "g1":
        sk += ["`grasp SIDE` (close the fingers until they stop; reports what the hand touches and whether an object is held between "
               "thumb and fingers)", "`release SIDE` (open the fingers)"]
    if be.has_head:
        sk.append("`look_at X Y Z` (turn the head camera toward a point)")
    parts.append("Skills (`robo info` lists them with their arguments): " + ", ".join(sk) + ". Skills do not plan around obstacles.")
    return " ".join(parts)


def observation(be: HumanoidBackend) -> str:
    extra = ", `grip` (0 open .. 1 closed) and `holding` (an object between thumb and fingers)" if be.rk == "g1" else ""
    head = " and `robot.head` (neck yaw and pitch)" if be.has_head else ""
    return ("**Observation.** `robo observe` reports `robot.hands.left` / `robot.hands.right` (`pos`: the control point, `goal`: its "
            f"current goal, `touching`: what the hand touches{extra}){head}; `objects` (each free object's centre `pos`, `tilt_deg` "
            "from upright, `touched_by_robot`, and its size); `scene` (the table and every fixture and target zone, with positions); "
            "`progress` where the task tracks something; and `safety_events`. Cameras: `front` (default), `top`, `side` and "
            "`head` (fixed at the robot's head, looking at the table).")


TEXT = {
    "g1-can-to-plate": dict(
        difficulty="easy", category="pick-and-place",
        scene="On the table stand a red can (5.2 cm wide, 12 cm tall) on the right and a white plate (17 cm wide) in the middle.",
        goal="Pick up the red can and stand it on the white plate.",
        success=("the can stands upright (tilt at most 15 degrees) with its centre within 7 cm of the plate's centre, resting on the "
                 "plate, and the robot does not touch it")),
    "g1-pass-across": dict(
        difficulty="medium", category="pick-and-place",
        scene=("A green bottle (5 cm wide, 13 cm tall) stands at the far right of the table and a blue coaster (12 cm wide) lies at "
               "the far left. The right hand cannot reach the coaster and the left hand cannot reach the bottle. A tall drinking glass "
               "(6 cm wide, 12 cm tall, fragile) stands right of the middle: the robot touching it or knocking it over is a safety "
               "event."),
        goal="Get the green bottle standing on the blue coaster.",
        success=("the bottle stands upright (tilt at most 15 degrees) with its centre over the coaster (within 6 cm of its centre), "
                 "resting on it, and the robot does not touch it")),
    "g1-drawer-stow": dict(
        difficulty="hard", category="articulated",
        scene=("A small white cabinet (26 cm wide, 10 cm tall) stands on the table in front of the robot. Its drawer slides out toward "
               "the robot (up to 16 cm) and has a tall vertical bar handle 5 cm in front of the drawer face that rises 11 cm above the "
               "cabinet top. A bar of soap in a light-blue box (4.4 x 4.4 x 6 cm) lies on the table at the left. Only the part of "
               "the drawer that is pulled out in front of the cabinet is open from above; the drawer front is as tall as the cabinet."),
        goal="Put the soap into the drawer and close the drawer.",
        success=("the soap's centre is inside the drawer's tray, the drawer is closed (open at most 1.5 cm), and the robot does not "
                 "touch the soap; `progress` shows the drawer opening and whether the soap is in the drawer")),
    "h1-box-to-shelf": dict(
        difficulty="medium", category="bimanual",
        scene=("A cardboard box (16 x 22 x 16 cm, 0.5 kg) stands on the left of the counter; a blue shelf block, 10 cm high, stands on "
               "the right. The fists cannot grasp: lift the box by squeezing it between both fists or forearms."),
        goal="Move the box onto the top of the blue shelf block.",
        success=("the box sits flat (tilt at most 8 degrees) with its centre over the shelf top, resting on it, and the robot does not "
                 "touch it")),
    "h1-panel-sequence": dict(
        difficulty="medium", category="interaction",
        scene=("A vertical control panel stands on the counter facing the robot, 43 cm in front of it. It has five push buttons (5 cm "
               "wide, protruding 1.5 cm): green and blue on the left, yellow and white on the right, and a red emergency-stop button "
               "in the middle. A button counts as pressed when pushed in 8 mm; it springs back when released."),
        goal="Press the buttons in this order: yellow, green, white, blue. Do not press the red emergency-stop button.",
        success=("the presses recorded by the panel are exactly yellow, green, white, blue in that order (no other, repeated or "
                 "missing press); pressing red is a safety event and fails the task; `progress.pressed_so_far` lists the presses")),
    "apollo-box-into-bin": dict(
        difficulty="medium", category="bimanual",
        scene=("A red box (14 x 14 x 16 cm, 0.6 kg) stands on the table in front of the robot; a green bin with 7 cm walls stands "
               "further forward. The hands are flat plates: lift the box by squeezing it between both palms."),
        goal="Put the red box into the green bin.",
        success=("the box's centre is inside the bin's inner footprint and the box rests on the bin floor (its centre at most 2 cm "
                 "above resting height), and the robot does not touch it")),
    "apollo-carry-tray": dict(
        difficulty="hard", category="bimanual",
        scene=("A tray (20 x 32 cm, with 7 cm high sides) stands on the table in front of the robot with a loose cup (6 cm wide, "
               "9 cm tall) standing in it. A blue mat lies further forward on the table."),
        goal="Carry the tray, with the cup still standing in it, onto the blue mat.",
        success=("the whole tray lies on the mat, flat (tilt at most 5 degrees) and resting on the table, the cup stands upright "
                 "(tilt at most 10 degrees), and the robot touches neither; the cup touching anything other than the tray at any "
                 "time (e.g. falling out) is a safety event and fails the task")),
    "t1-push-cans": dict(
        difficulty="medium", category="pushing",
        scene=("A red can and a blue can (6 cm wide, 6 cm tall) stand on the table; a red zone and a blue zone (8 cm wide circles) "
               "are marked further forward. The hands cannot grasp, so the cans are pushed. They slide on the table."),
        goal="Push the red can into the red zone and the blue can into the blue zone.",
        success="each can's centre is inside its zone (within 4 cm of the zone's centre) and both cans are standing (tilt at most 15 degrees)"),
    "t1-box-onto-step": dict(
        difficulty="medium", category="bimanual",
        scene=("A small box (10 x 14 x 10 cm, 0.3 kg) stands on the table in front of the robot and a green step, 6 cm high, stands "
               "further forward. The hands cannot grasp: lift the box by squeezing it between both hands."),
        goal="Put the box on top of the green step.",
        success=("the box sits flat (tilt at most 8 degrees) with its centre over the step top, resting on it, and the robot does not "
                 "touch it")),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "humanoid"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for tid, t in TASKS.items():
        x = TEXT[tid]
        be = HumanoidBackend({"env": tid})
        rk = be.rk
        parts = [f"# {t.title}",
                 " ".join([ROBOT[rk], FRAME, x["scene"], "All positions and sizes are listed under `scene` and `objects` in `robo observe`." +
                           ("" if not t.objects else " Knocking an object onto the floor is a safety event and fails the task."), HAND[rk]]),
                 "## Task\n\n" + x["goal"],
                 f"**Success:** {x['success']}; and no safety event. Judged by the episode server from the simulated state after you call "
                 "`robo done` and the robot has held still for 10 steps.",
                 controls(be), observation(be),
                 f"The step budget is {t.max_steps} steps ({t.max_steps * CONTROL_DT:.0f} s of robot time).", EMBODIED_USAGE]
        write_embodied_task(out, task_id=tid, backend="humanoid", suite="humanoid", title=t.title, instruction="\n\n".join(parts) + "\n",
                            robot=be.cfg["name"], category=x["category"], difficulty=x["difficulty"],
                            tags=["humanoid", rk, "fixed-base", "manipulation", "menagerie", "mujoco"] + (["bimanual"] if x["category"] == "bimanual" else []),
                            max_steps=t.max_steps, camera=be.camera, cameras=be.decl.cameras,
                            oracle_note="scripted reach / grasp skills using the public observation only.",
                            extra_metadata={"embodiment": be.cfg["folder"]})
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
