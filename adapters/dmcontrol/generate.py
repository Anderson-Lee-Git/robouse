"""dm_control -> Robo Use tasks (suite "dmcontrol"): tasks from DeepMind's dm_control 1.0.47 (Apache-2.0,
github.com/google-deepmind/dm_control): the DeepMind Control Suite (cart-pole, pendulum, acrobot, reacher, point mass,
finger, ball in cup, planar manipulator) and dm_control.manipulation (Kinova Jaco arm: reach, lift, place, stack).
Backend, task table, success rule and reference solutions: src/robouse/backends/dmcontrol.py (the simulator runs in its
own virtualenv through src/robouse/backends/dmcontrol_worker.py; setup in docs/suites/dmcontrol.md). The generator starts
each task once to read the start state it writes into the instruction, so it needs that virtualenv too.

Usage: python adapters/dmcontrol/generate.py [--out tasks/dmcontrol]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.dmcontrol.backend import DM_CONTROL_VERSION, DOMAINS, MUJOCO_VERSION, TASKS, DMControlBackend
from robouse.backends.embodied import write_embodied_task
from robouse.core.prompts import EMBODIED_USAGE

_SETTLE = (
    "- Success is judged about 10 steps after you call `robo done`, with the robot holding still (each action group's hold value: "
    "zero for velocity and delta commands, full brake for a car), so the goal must still be true when the robot stops."
)
assert _SETTLE in EMBODIED_USAGE
USAGE = EMBODIED_USAGE.replace(
    _SETTLE,
    "- The episode ends as solved the moment the task's success rule holds (see Success); `robo done` before that scores 0.",
)

PAUSED = (
    "Simulated time advances only when you act; the scene is paused while you think. A feedback controller can run as a script: "
    "Python 3 with numpy is available, and `robo observe --json` / `robo act ... --json` print machine-readable output."
)
HOLD_OBS = (
    "Every task also reports `reward` (dm_control's own reward for the last step, for information), `in_target` (whether the "
    "success condition holds right now), `hold_steps` (for how many consecutive steps it has held) and `hold_required`, and "
    "`time_s` (simulated time)."
)


def _f(v, n=3):
    return "(" + ", ".join(f"{round(float(x), n) + 0.0:.{n}f}" for x in v) + ")"


# ---------------------------------------------------------------------------------------------------------------------
# per domain: scene, controls, observation
# ---------------------------------------------------------------------------------------------------------------------

CARTPOLE = dict(
    scene=(
        "A cart-pole from the DeepMind Control Suite (MuJoCo). A cart (1 kg) slides on a rail along x (x = 0 in the middle, stops at "
        "x = +-1.8 m); a pole (1 m long, 0.1 kg) swings freely on an unactuated hinge on the cart, in the x-z plane (z up). "
        "`pole_angle` is in radians: 0 = pointing straight up, +-pi = hanging straight down; a positive angle tilts the top of the "
        "pole towards +x. The fixed camera looks along +y, so +x is to the right in the image."
    ),
    controls=(
        "**Controls.** `robo act F [--repeat N]` pushes the cart along x with a force of 10 N per unit, F in [-1, 1], for N steps "
        "of 10 ms (one step = one dm_control control step). There are no skills."
    ),
    obs=(
        "**Observation.** `robo observe` reports dm_control's own observation, `position` = [cart x (m), cos(pole angle), sin(pole "
        "angle)] and `velocity` = [cart velocity (m/s), pole angular velocity (rad/s)], plus the same values by name: `cart_x`, "
        "`cart_vel`, `pole_angle`, `pole_angvel`."
    ),
    rule=(
        "the cart within 0.25 m of the rail's centre (|`cart_x`| <= 0.25) and the pole within about 5.7 degrees of vertical (cosine "
        "of `pole_angle` >= 0.995), dm_control's sparse cart-pole condition (balance_sparse / swingup_sparse)"
    ),
)

PENDULUM = dict(
    scene=(
        "A torque-limited pendulum from the DeepMind Control Suite (MuJoCo): a 1 kg ball on a 0.5 m massless rod, swinging in the x-z "
        "plane (z up) about a hinge with light damping. `pole_angle` is in radians: 0 = pointing straight up, +-pi = hanging straight "
        "down; a positive angle tilts the ball towards +x. The motor is too weak to lift the pendulum directly (gravity's torque "
        "reaches 4.9 N m, the motor gives at most 1 N m), so it has to be swung up."
    ),
    controls=(
        "**Controls.** `robo act TAU [--repeat N]` applies a torque of TAU N m at the hinge, TAU in [-1, 1] (positive increases "
        "`pole_angle`), for N steps of 20 ms. There are no skills."
    ),
    obs=(
        "**Observation.** `robo observe` reports dm_control's own observation, `orientation` = [cos, sin] of the pole angle and "
        "`velocity` = [angular velocity (rad/s)], plus `pole_angle` and `pole_angvel` by name."
    ),
    rule="the pendulum within 30 degrees of upright (cosine of `pole_angle` >= cos 30 deg), the task's own reward condition",
)

ACROBOT = dict(
    scene=(
        "An acrobot from the DeepMind Control Suite (MuJoCo): a two-link pendulum in the x-z plane (z up). The upper arm hangs from an "
        "unactuated shoulder hinge at (x, z) = (0, 2); the lower arm is attached at the elbow, the only motor. Each link is 1 m long "
        "and weighs 1 kg; both joints have light damping. Angles are in radians: `shoulder_angle` 0 = upper arm pointing straight up "
        "(+-pi = hanging down), `elbow_angle` is the lower arm's angle relative to the upper arm (0 = straight); positive angles turn "
        "towards +x. The target is the point straight above the shoulder at full height, (0, 4)."
    ),
    controls=(
        "**Controls.** `robo act TAU [--repeat N]` applies a torque of 2 N m per unit at the elbow, TAU in [-1, 1] (positive "
        "increases `elbow_angle`), for N steps of 10 ms. The motor is weak: the acrobot has to be pumped up by swinging, and "
        "balancing it upright needs fast, precise feedback. There are no skills."
    ),
    obs=(
        "**Observation.** `robo observe` reports dm_control's own observation, `orientations` = [sin shoulder, sin(shoulder + elbow), "
        "cos shoulder, cos(shoulder + elbow)] and `velocity` = [shoulder, elbow angular velocity (rad/s)], plus `shoulder_angle`, "
        "`elbow_angle`, `shoulder_vel`, `elbow_vel`, the tip of the lower arm `tip_pos` and `target_pos` as (x, z) in metres, "
        "`target_radius` and `tip_to_target` (m)."
    ),
    rule="the tip of the lower arm inside the target sphere (`tip_to_target` <= 0.2 m, dm_control's swingup_sparse condition)",
)

REACHER = dict(
    scene=(
        "A planar two-link arm from the DeepMind Control Suite (MuJoCo) lies flat on a table (the x-y plane, z up), inside a square "
        "arena with walls at x, y = +-0.3 m. The shoulder is at the origin and turns without limit; the upper link is 0.12 m long, the "
        "wrist (range +-160 degrees) carries a 0.12 m link ending in the fingertip (a 1 cm sphere). Angles are in radians, "
        "counter-clockwise seen from above: `shoulder_angle` is the upper link's direction from +x, `wrist_angle` the lower link's "
        "angle relative to the upper link. The links are light, so the torques are small."
    ),
    controls=(
        "**Controls.** `robo act SHOULDER WRIST [--repeat N]` applies torques of 0.05 N m per unit at the shoulder and the wrist, "
        "each in [-1, 1] (positive = counter-clockwise), for N steps of 20 ms. There are no skills."
    ),
    obs=(
        "**Observation.** `robo observe` reports dm_control's own observation, `position` = [shoulder, wrist angle] (rad), `to_target` "
        "= target minus fingertip (x, y in m) and `velocity` = [shoulder, wrist angular velocity] (rad/s), plus `shoulder_angle`, "
        "`wrist_angle`, `shoulder_vel`, `wrist_vel`, `fingertip_pos`, `target_pos` (x, y in m), `target_radius` (the target "
        "sphere's radius plus the fingertip's) and `fingertip_to_target` (m)."
    ),
    rule="the fingertip within `target_radius` of the target's centre (`fingertip_to_target` <= `target_radius`, the task's own reward condition)",
)

POINT_MASS = dict(
    scene=(
        "A point mass from the DeepMind Control Suite (MuJoCo): a 0.3 kg ball (1 cm radius) slides on a table (the x-y plane, z up) "
        "inside a square arena with walls at x, y = +-0.3 m. The target is a small sphere at the origin."
    ),
    controls=(
        "**Controls.** `robo act FX FY [--repeat N]` pushes the mass with 0.1 N per unit along x and along y, each in [-1, 1], "
        "for N steps of 20 ms. There are no skills."
    ),
    obs=(
        "**Observation.** `robo observe` reports dm_control's own observation, `position` (x, y in m) and `velocity` (m/s), plus "
        "`mass_pos`, `mass_vel`, `target_pos`, `target_radius` and `mass_to_target` (m)."
    ),
    rule="the centre of the mass within the target's radius of its centre (`mass_to_target` <= `target_radius` = 0.015 m, the near-target condition of the task's reward)",
)

FINGER = dict(
    scene=(
        "The finger domain of the DeepMind Control Suite (MuJoCo), in the x-z plane (z up, no gravity). A two-link finger is mounted "
        "on a hinge at (x, z) = (-0.2, 0.4): the proximal link is 0.18 m long; the distal link ends in a rounded fingertip whose far "
        "end is 0.161 m from the distal joint (fingertip radius 3 cm). Both joints are damped and limited to +-110 degrees (+-1.92 "
        "rad). Angles are in radians: `proximal_angle` is the proximal link's direction measured counter-clockwise from +x in the x-z "
        "plane (0 = pointing towards +x, -pi/2 = pointing down), `distal_angle` the distal link's angle relative to it. The spinner is "
        "a free body on an unactuated, damped hinge at (0.2, 0.4): a bar 0.26 m long and 0.12 m wide made of two capsules, which "
        "stops turning almost at once when nothing pushes it. One end is marked: its tip (`spinner_tip_pos`) lies 0.13 m from the "
        "hinge. The target is a point on the same 0.13 m circle (`target_pos`). Only the fingertip and the proximal link collide; the "
        "finger can reach the spinner only on its left side."
    ),
    controls=(
        "**Controls.** `robo act PROXIMAL DISTAL [--repeat N]` applies torques of 30 N m and 15 N m per unit at the proximal and "
        "distal joints, each in [-1, 1] (positive increases the joint angle), for N steps of 20 ms. There are no skills."
    ),
    obs=(
        "**Observation.** `robo observe` reports dm_control's own observation, `position` (the two joint angles, then the spinner tip's "
        "x and z relative to the hinge), `velocity` (the two joints' and the hinge's angular velocities), `touch` (log(1 + force) of "
        "the fingertip's two touch sensors), `target_position` (target relative to the hinge) and `dist_to_target` (distance from the "
        "tip to the target minus the target radius), plus by name: `proximal_angle`, `distal_angle`, `proximal_vel`, `distal_vel`, "
        "`fingertip_pos` (centre of the fingertip), `fingertip_end_pos` (its far end), `spinner_center`, `spinner_angle` (the hinge "
        "angle, rad), `spinner_vel`, `spinner_tip_pos`, `target_pos`, `target_radius` and `tip_to_target` (all positions (x, z) in m)."
    ),
    rule="the spinner's marked tip inside the target circle (`dist_to_target` <= 0, the task's own reward condition)",
)

BALL_IN_CUP = dict(
    scene=(
        "Ball in cup from the DeepMind Control Suite (MuJoCo), in the x-z plane (z up, gravity on). A cup (0.065 kg; an open V-bottomed "
        "cup, about 8 cm wide inside the rim and 10 cm deep, opening upwards) is held by springs: it slides in x and z about its home "
        "position (0, 0.6) with a stiffness of 20 N/m and damping of 3 N s/m per axis. A ball (0.065 kg, 2.5 cm radius) hangs from the "
        "bottom of the cup on a 0.3 m string, which goes slack when the ball comes closer. The cup's position `cup_pos` is the centre "
        "of its rim (the bottom is 0.1 m lower). The ball starts at rest somewhere below the cup."
    ),
    controls=(
        "**Controls.** `robo act FX FZ [--repeat N]` pushes the cup with 5 N per unit along x and along z, each in [-1, 1], for N "
        "steps of 20 ms. The springs limit how far the cup can go (about 0.25 m from home at full force). There are no skills."
    ),
    obs=(
        "**Observation.** `robo observe` reports dm_control's own observation, `position` = [cup x, cup z, ball x, ball z] (joint "
        "positions: cup relative to its home, ball relative to its reference 0.2 m above the floor) and `velocity`, plus by name "
        "(world frame): `cup_pos`, `cup_vel`, `ball_pos`, `ball_vel`, `cup_target_center` (the middle of the inside of the cup) and "
        "`string_length`."
    ),
    rule=(
        "the ball entirely inside the cup: its centre within 0.025 m of `cup_target_center` along both x and z (dm_control's own "
        "in-target check: the target box's half-size 0.05 m minus the ball radius)"
    ),
)

MANIPULATOR = dict(
    scene=(
        "The planar manipulator of the DeepMind Control Suite (MuJoCo), in the x-z plane (z up, gravity on). An arm is mounted on a "
        "hinge at (x, z) = (0, 0.4) above a floor (z = 0) that is bounded by walls sloping up from x = +-0.4 m. Links: 0.18 m (root to "
        "shoulder), 0.15 m (shoulder to elbow), 0.12 m (elbow to wrist); the hand's grasp point (`grasp_site_pos`) is 0.065 m past the "
        "wrist and the pinch point between the fingertips 0.09 m. Joint angles are in radians; each joint turns about -y, so with 0 "
        "every link points straight up and a positive angle turns it towards -x: the direction of link k is (-sin Q, cos Q) with Q the "
        "sum of the joint angles up to it. `arm_root` turns without limit; `arm_shoulder` and `arm_elbow` are limited to +-160 degrees, "
        "`arm_wrist` to +-140 degrees. The hand has a thumb and a finger. A ball (2.2 cm radius) starts somewhere in the arena, "
        "possibly moving; it rolls freely on the floor."
    ),
    controls=(
        "**Controls.** `robo act ROOT SHOULDER ELBOW WRIST GRASP [--repeat N]` applies joint torques of 12, 8, 4 and 2 N m per unit "
        "(positive increases the joint angle) and a grip force of 2 N per unit on the fingers (positive closes them, negative opens "
        "them), each in [-1, 1], for N steps of 10 ms. There are no skills."
    ),
    obs=(
        "**Observation.** `robo observe` reports dm_control's own observation: `arm_pos` (sin and cos of the 8 joints: root, shoulder, "
        "elbow, wrist, finger, fingertip, thumb, thumbtip), `arm_vel`, `touch` (palm, finger, thumb, fingertip, thumbtip), and "
        "`hand_pos`, `object_pos`, `target_pos` as [x, z, qw, qy] (position and rotation about y), `object_vel`; plus by name: "
        "`joint_angles` and `joint_vels` (rad, rad/s), `grasp_site_pos`, `pinch_site_pos`, `ball_site_pos`, `target_ball_site_pos` "
        "((x, z) in m), `ball_angle` and `ball_to_target` (m)."
    ),
    rule="the ball's centre within 1 cm of the target's centre (`ball_to_target` <= 0.01 m, where the task's reward is 1)",
)

JACO = dict(
    scene=(
        "A Kinova Jaco robot arm (6 joints) with the three-finger Jaco hand stands at the edge of a table, its base at (0, 0.4, 0), "
        "from dm_control.manipulation (MuJoCo). World frame in metres, z up, the table top at z = 0. The hand is controlled at its pinch "
        "point, the point between the fingertips (dm_control's tool centre point), and always points straight down; you set its "
        "position and its yaw (turn about the vertical). The objects are Duplo 2x4 bricks (6.4 x 3.2 cm, 1.9 cm tall plus studs); a "
        "brick's `_pos` is the centre of its bottom face and `_yaw_deg` the direction of its long side. The fingers close along the "
        "hand's yaw direction: with `hand_yaw_deg` at a brick's yaw + 90 degrees they grip the brick across its 3.2 cm width."
    ),
    controls=(
        "**Controls.** `robo act DX DY DZ DYAW GRIP [--repeat N]` applies one 40 ms step N times. DX DY DZ in [-2, 2] move the "
        "commanded pinch point by 1 cm per unit along world x, y, z; DYAW in [-2, 2] turns the commanded hand yaw by 0.1 rad per "
        "unit (positive = counter-clockwise seen from above). A Jacobian controller drives the arm's joint velocities towards the "
        "command (the hand lags a fast command, and the command is kept within 8 cm of the hand and inside the box x, y in "
        "[-0.35, 0.35], z in [-0.02, 0.6]). GRIP in [-1, 1] is the fingers' velocity: +1 closes, -1 opens; at 0 the fingers stop "
        "where they are and no longer squeeze, so keep GRIP at +1 while you carry something. Skills (`robo info` lists their "
        "arguments): `move_to X Y Z [YAW] [GRIP]` moves the pinch point in a straight line to a point (and turns the hand to YAW "
        "degrees; 999 keeps it) while holding GRIP; `grip VALUE [STEPS]` sets the fingers without moving the arm."
    ),
    obs=(
        "**Observation.** `robo observe` reports `hand_pos` (the pinch point), `hand_target_pos` (the commanded point), `hand_yaw_deg`, "
        "`hand_target_yaw_deg`, `hand_z_axis` (the hand's pointing direction), `arm_joints` and `finger_joints` (rad; each finger "
        "ranges from 0.15, open, to 1.35, closed), `grip_command`, and for each brick `<name>_pos`, `<name>_quat_wxyz` and `<name>_yaw_deg`, "
        "plus the task fields below. `robo observe --image` saves a picture from the `front_close` camera."
    ),
    rule="",
)

DOMAIN_TEXT = {
    "cartpole": CARTPOLE,
    "pendulum": PENDULUM,
    "acrobot": ACROBOT,
    "reacher": REACHER,
    "point_mass": POINT_MASS,
    "finger": FINGER,
    "ball_in_cup": BALL_IN_CUP,
    "manipulator": MANIPULATOR,
    "jaco": JACO,
}


# ---------------------------------------------------------------------------------------------------------------------
# per task: title, goal (with the start state), rule for the Jaco tasks
# ---------------------------------------------------------------------------------------------------------------------


def task_text(tid: str, st: dict) -> dict:
    if tid == "dmcontrol-cartpole-swingup":
        return dict(
            title="Cart-pole swing-up",
            difficulty="medium",
            category="swing-up",
            upstream="cartpole-swingup",
            goal=(
                f"Swing the pole up from hanging down and balance it upright with the cart near the middle of the rail. The "
                f"pole starts hanging (`pole_angle` = {st['pole_angle']:.2f} rad) with the cart at x = {st['cart_x']:.3f} m."
            ),
        )
    if tid == "dmcontrol-cartpole-balance":
        return dict(
            title="Cart-pole balance",
            difficulty="easy",
            category="balance",
            upstream="cartpole-balance",
            goal=(
                f"Keep the pole balanced upright with the cart near the middle of the rail. The pole starts almost upright "
                f"(`pole_angle` = {st['pole_angle']:.3f} rad) and falls within about a second if nothing is done."
            ),
        )
    if tid == "dmcontrol-pendulum-swingup":
        return dict(
            title="Pendulum swing-up",
            difficulty="medium",
            category="swing-up",
            upstream="pendulum-swingup",
            goal=(
                f"Swing the pendulum up and keep it upright. It starts at rest near the bottom (`pole_angle` = "
                f"{st['pole_angle']:.2f} rad)."
            ),
        )
    if tid == "dmcontrol-acrobot-swingup":
        return dict(
            title="Acrobot swing-up",
            difficulty="hard",
            category="swing-up",
            upstream="acrobot-swingup_sparse",
            goal=(
                f"Swing the acrobot up until the tip of the lower arm reaches the target at the top and keep it there. It starts "
                f"hanging nearly straight down (`shoulder_angle` = {st['shoulder_angle']:.2f}, `elbow_angle` = "
                f"{st['elbow_angle']:.2f} rad), at rest."
            ),
        )
    if tid.startswith("dmcontrol-reacher"):
        hard = "hard" in tid
        return dict(
            title=f"Reacher ({'small' if hard else 'large'} target)",
            difficulty="easy",
            category="reaching",
            upstream="reacher-hard" if hard else "reacher-easy",
            goal=(
                f"Move the fingertip into the target sphere at {_f(st['target_pos'])} and keep it there. The arm starts at rest "
                f"with the fingertip at {_f(st['fingertip_pos'])}, {st['fingertip_to_target']:.3f} m from the target; "
                f"`target_radius` = {st['target_radius']} m."
            ),
        )
    if tid == "dmcontrol-point-mass-easy":
        return dict(
            title="Point mass to the target",
            difficulty="easy",
            category="reaching",
            upstream="point_mass-easy",
            goal=(
                f"Push the mass onto the target at the origin and keep it there. It starts at rest at {_f(st['mass_pos'])}."
            ),
        )
    if tid.startswith("dmcontrol-finger-turn"):
        hard = "hard" in tid
        return dict(
            title=f"Finger: turn the spinner ({'small' if hard else 'large'} target)",
            difficulty="hard" if hard else "medium",
            category="manipulation",
            upstream="finger-turn_hard" if hard else "finger-turn_easy",
            goal=(
                f"Turn the spinner with the fingertip until its marked tip lies in the target circle (radius "
                f"{st['target_radius']} m around {_f(st['target_pos'])}), and leave it there. At the start the marked tip is at "
                f"{_f(st['spinner_tip_pos'])}, {st['tip_to_target']:.3f} m from the target; the finger is at rest."
            ),
        )
    if tid == "dmcontrol-ball-in-cup-catch":
        return dict(
            title="Ball in cup",
            difficulty="hard",
            category="manipulation",
            upstream="ball_in_cup-catch",
            goal=(
                f"Swing the ball on its string into the cup and keep it there. The ball starts at {_f(st['ball_pos'])}, at rest, "
                f"and falls when the episode starts; the cup is at its home {_f(st['cup_pos'])}."
            ),
        )
    if tid == "dmcontrol-manipulator-bring-ball":
        return dict(
            title="Planar manipulator: bring the ball",
            difficulty="hard",
            category="manipulation",
            upstream="manipulator-bring_ball",
            goal=(
                f"Pick up the ball and hold it at the target, a ball-sized ghost at {_f(st['target_ball_site_pos'])} (x, z) in "
                f"mid-air. The ball starts at {_f(st['ball_site_pos'])} moving at {st['object_vel'][0]:.2f} m/s along x; it "
                f"falls to the floor and rolls."
            ),
        )
    t = TASKS[tid]["task"]
    if t.startswith("reach_site"):
        return dict(
            title="Jaco: reach the target",
            difficulty="easy",
            category="reaching",
            upstream="reach_site_features",
            goal=(
                f"Move the pinch point into the red target sphere centred at {_f(st['target_pos'])} (radius 0.05 m) and keep it "
                f"there. The hand starts at {_f(st['hand_pos'])}. Task fields: `target_pos`, `target_radius`, `hand_to_target`."
            ),
            rule="the pinch point within 5 cm of the target's centre (`hand_to_target` <= 0.05 m, where dm_control's reach reward is 1)",
        )
    if t.startswith("lift"):
        return dict(
            title="Jaco: lift the brick",
            difficulty="medium",
            category="pick",
            upstream="lift_brick_features",
            goal=(
                f"Pick up the brick and lift it 30 cm. The brick lies on the table at {_f(st['brick_pos'])} with its long side at "
                f"{st['brick_yaw_deg']:.0f} degrees. Task fields: `brick_lowest_point_z` (the lowest corner of the brick) and "
                f"`target_height` ({st['target_height']:.3f} m: 0.3 m above the brick's starting height)."
            ),
            rule="the brick's lowest corner at or above `target_height` (`brick_lowest_point_z` >= `target_height`, where dm_control's lift reward is 1)",
        )
    if t.startswith("place"):
        cradle = "cradle" in t
        what = (
            "a cradle of three spheres on top of a pedestal (a pillar about 0.2 m tall)"
            if cradle
            else "another Duplo brick fixed on top of a pedestal (a pillar about 0.2 m tall)"
        )
        return dict(
            title=f"Jaco: place the brick on the {'cradle' if cradle else 'pedestal brick'}",
            difficulty="medium",
            category="pick and place",
            upstream=t,
            goal=(
                f"Put the brick on {what}, let go and take the hand away. The brick lies on the table at "
                f"{_f(st['brick_pos'])} (long side at {st['brick_yaw_deg']:.0f} degrees); the target point on the pedestal is "
                f"{_f(st['target_pos'])}. Task fields: `target_pos`, `target_radius`, `brick_to_target` and `hand_to_target`."
            ),
            rule=(
                "the brick's `brick_pos` within 5 cm of the target point (`brick_to_target` <= 0.05 m) and the pinch point at "
                "least 20 cm away from it (`hand_to_target` >= 0.2 m), where dm_control's place reward is 1"
            ),
        )
    if t.startswith("stack"):
        o = st["desired_order_bottom_to_top"]
        return dict(
            title="Jaco: stack two bricks",
            difficulty="hard",
            category="assembly",
            upstream="stack_2_bricks_features",
            goal=(
                f"Stack brick_{o[1]} on top of brick_{o[0]} so that its holes click onto the other brick's studs. brick_{o[0]} "
                f"lies at {_f(st[f'brick_{o[0]}_pos'])} (long side at {st[f'brick_{o[0]}_yaw_deg']:.0f} degrees), brick_{o[1]} at "
                f"{_f(st[f'brick_{o[1]}_pos'])} (at {st[f'brick_{o[1]}_yaw_deg']:.0f} degrees). A brick looks the same turned by "
                "180 degrees, so the two long sides must be parallel. Task field: `desired_order_bottom_to_top`."
            ),
            rule=(
                f"brick_{o[1]} clicked onto brick_{o[0]}: the summed distance between two opposite corner studs of the bottom "
                "brick and the matching holes of the top brick below 1 mm (dm_control's stacking reward is 1; the bricks are "
                "symmetric, so either orientation counts)"
            ),
        )
    raise KeyError(tid)


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "dmcontrol"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for tid, t in TASKS.items():
        be = DMControlBackend({"env": tid})
        be.reset(0)
        st = be.observe()
        dom = be.domain
        cams = list(be.decl.cameras)
        be.close()
        d = DOMAIN_TEXT[dom]
        x = task_text(tid, st)
        dt = DOMAINS[dom]["dt"]
        steps, hold = int(t["max_steps"]), int(t["hold"])
        rule = x.get("rule") or d["rule"]
        succ = (
            f"**Success:** {rule}, held for {hold} consecutive steps ({hold * dt:g} s of simulated time), judged by the episode "
            "server from the simulated state after every step. The episode ends as solved the moment that happens; `robo done` "
            "before that scores 0."
        )
        cam_text = (
            f" Cameras: {', '.join(f'`{c}`' for c in cams)}; `robo observe --image [--camera C]` saves a picture."
            if dom != "jaco"
            else ""
        )
        parts = [
            f"# {x['title']} (dm_control)",
            d["scene"] + " " + PAUSED,
            "## Task\n\n" + x["goal"],
            succ,
            d["controls"],
            d["obs"] + " " + HOLD_OBS + cam_text,
            f"The step budget is {steps} steps ({steps * dt:g} s of simulated time).",
            USAGE,
        ]
        kind = "suite" if t["kind"] == "suite" else "manipulation"
        source = (
            f"dm_control Control Suite `{t['domain']}` / `{t['task']}`, random={t['seed']}"
            if kind == "suite"
            else f"dm_control.manipulation `{t['task']}`, seed={t['seed']}"
        )
        note = {
            "cartpole": "energy-based swing-up and LQR balancing from the public state.",
            "pendulum": "energy pumping and LQR balancing from the public state.",
            "acrobot": "sampling-based model-predictive control (cross-entropy method on the textbook acrobot model) and LQR at the top.",
            "reacher": "two-link inverse kinematics and joint PD torques.",
            "point_mass": "PD force control to the target.",
            "finger": "pushes a spinner arm with the fingertip (inverse kinematics and joint PD torques).",
            "ball_in_cup": "sampling-based model-predictive control on a point-mass model of the cup, ball and string.",
            "manipulator": "catches the rolling ball, grasps it from above and carries it (inverse kinematics, joint PID torques).",
            "jaco": "scripted pick and place with the move_to and grip skills.",
        }[dom]
        write_embodied_task(
            out,
            task_id=tid,
            backend="dmcontrol",
            suite="dmcontrol",
            title=x["title"],
            instruction="\n\n".join(parts) + "\n",
            robot=DOMAINS[dom]["robot"],
            category=x["category"],
            difficulty=x["difficulty"],
            tags=["dm_control", "mujoco", dom.replace("_", "-")],
            max_steps=steps,
            camera=t["camera"],
            cameras=cams,
            oracle_note=note,
            agent_timeout_s=2400,
            extra_robouse={"success_mode": "first", "skills": dom == "jaco", "seed": 0},
            extra_metadata={
                "source_benchmark": f"DeepMind dm_control {DM_CONTROL_VERSION} (google-deepmind/dm_control, Apache-2.0)",
                "source_task": source,
                "upstream_task": x["upstream"],
                "simulator": f"dm_control {DM_CONTROL_VERSION}, MuJoCo {MUJOCO_VERSION}",
            },
        )
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
