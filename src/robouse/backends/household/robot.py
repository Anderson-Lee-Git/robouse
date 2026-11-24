"""The household robot: a Franka FR3 arm with a Robotiq 2F-85 gripper on a fixed base, and how it is put into a scene.

Both models are MuJoCo Menagerie's, unmodified on disk (assets.py pins and checks them); everything below is changed
in memory only. The design follows Embodied Safety Exam's `FR3_2F85` (its `sim/robots.py` and `sim/world.py`), whose
numbers were measured on the same model files:

- the arm is attached at a frame (any position and orientation; +x of that frame is where the arm faces) under the
  prefix `robot/`, the gripper on the arm's `attachment_site` under `robot/hand/`, a box pedestal below the base;
- joints 5-7 get a rotor inertia (armature) of 0.2 kg m^2, as joints 1-4 have in the model (0.195): with the model's
  0.074 the wrist's position servos (kv 200) chatter in a two-substep limit cycle at rest in some postures (about
  0.16 rad/s, +-37 N m on joint 7), so the arm never settles; 0.15 and up removes it;
- every robot body has gravity compensation (the real controller carries the robot's own weight);
- the gripper's tendon force limit is 10 (about 88 N on each pad; the model's own 5 is about 44 N) and its finger pads
  meet things with `PAD_CONTACT`;
- the wrist camera `camera_1` is fixed on the gripper body, beside the palm, looking past the fingertips.

Physics (`PHYSICS`) and rendering (`RENDER`) of every household episode are versioned conditions (protocol 1.0.0),
set on the combined model; they override anything the scene file says.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

PHYSICS_VERSION = "1.0.0"
PHYSICS_DT = 0.002
SUBSTEPS = 10
CONTROL_DT = PHYSICS_DT * SUBSTEPS  # 0.02 s: 50 Hz
PHYSICS = {
    "timestep": PHYSICS_DT,
    "substeps": SUBSTEPS,
    "control_hz": 50,
    "integrator": "implicitfast",
    "cone": "elliptic",
    "impratio": 100.0,
    "solver": "newton",
    "iterations": 100,
    "tolerance": 1e-8,
    "gravity": [0.0, 0.0, -9.81],
    "wrist_armature": 0.2,
}
# Rendering, identical for policy views and recorded video: shadows on, 4x multisampling, 4096 shadow map, headlight,
# and a fixed 1 cm near clipping distance. MuJoCo's default near plane is 1% of the model's extent, which in a room-sized
# scene (extent 7-42 m) clipped surfaces 7-42 cm in front of the wrist camera as the hand approached them.
RENDER = {
    "shadows": True,
    "multisamples": 4,
    "shadow_map": 4096,
    "headlight": True,
    "width": 640,
    "height": 480,
    "near_clip_m": 0.01,
}

ARM_PREFIX = "robot/"
HAND_PREFIX = "robot/hand/"


@dataclass(frozen=True)
class RobotSpec:
    type: str
    arm_file: str
    hand_file: str
    attach_site: str
    arm_joints: tuple
    arm_actuators: tuple
    vel_limits: tuple  # rad/s, what the controller lets a joint target move at
    acc_limits: tuple  # rad/s^2
    lead: float  # s: kv / kp of the arm servos; target = q + lead * qdot cancels their lag
    limit_margin: float  # rad: targets stay this far inside the joint ranges
    gripper_actuator: str
    gripper_ctrl_max: float  # actuator control of the closed gripper (0 = open)
    gripper_max: float  # rad: driver joint angle of the closed gripper
    gripper_force: float  # tendon force limit (N on the tendon)
    pad_n_per_force: float  # N on each pad per unit of the tendon force limit (measured)
    driver_joints: tuple
    opening_table: tuple  # ((driver angle, free distance between the pads in m), ...), open first
    tool_site: str  # pinch point: +z out of the hand, +y the closing direction
    hand_body: str
    pads: tuple
    home: tuple
    wrist_camera: dict  # in the frame of hand_body
    armature: tuple = ()  # (joint, kg m^2) set on the arm's joints


# How the finger pads meet what they hold (ESE robots.PAD_CONTACT): rubber-like sliding friction, torsional and rolling
# resistance (condim 6), stiff impedance within 1 mm of penetration, priority over what they touch.
PAD_CONTACT = {
    "friction": (1.0, 0.005, 0.0001),
    "condim": 6,
    "solref": (0.004, 1.0),
    "solimp": (0.99, 0.9999, 0.001, 0.5, 2.0),
    "priority": 1,
}

FR3_2F85 = RobotSpec(
    type="fr3_2f85",
    arm_file="franka_fr3/fr3.xml",
    hand_file="robotiq_2f85/2f85.xml",
    attach_site="attachment_site",
    arm_joints=tuple(f"fr3_joint{i}" for i in range(1, 8)),
    arm_actuators=tuple(f"fr3_joint{i}" for i in range(1, 8)),
    vel_limits=(1.5, 1.5, 1.5, 1.5, 2.0, 2.0, 2.0),
    acc_limits=(4.0, 4.0, 4.0, 4.0, 6.0, 6.0, 6.0),
    lead=0.1,
    limit_margin=0.02,
    gripper_actuator="fingers_actuator",
    gripper_ctrl_max=255.0,
    gripper_max=0.8,
    gripper_force=10.0,
    pad_n_per_force=8.8,
    driver_joints=("right_driver_joint", "left_driver_joint"),
    opening_table=((0.0, 0.0852), (0.2, 0.0657), (0.4, 0.0440), (0.6, 0.0209), (0.7824, 0.0004)),
    tool_site="pinch",
    hand_body="base",
    pads=("left_pad1", "left_pad2", "right_pad1", "right_pad2"),
    armature=(("fr3_joint5", 0.2), ("fr3_joint6", 0.2), ("fr3_joint7", 0.2)),
    # rest: upright over the base, the hand high and tipped forward over the work area (ESE FR3 home)
    home=(0.0, -1.10, 0.0, -2.10, 0.0, 1.50, math.pi / 2),
    wrist_camera={"pos": (0.085, 0.0, 0.045), "target": (0.0, 0.0, 0.30), "up": (1.0, 0.0, 0.0), "fovy": 62.0},
)


def look_at_quat(pos, target, up=(0.0, 0.0, 1.0)) -> list[float]:
    """Quaternion (w, x, y, z) of a MuJoCo camera at `pos` looking at `target` (the camera looks along its -z, +y up)."""
    p, t, u = (np.asarray(v, dtype=np.float64) for v in (pos, target, up))
    f = t - p
    f /= np.linalg.norm(f)
    right = np.cross(f, u)
    if np.linalg.norm(right) < 1e-9:
        raise ValueError("camera up direction is parallel to its viewing direction")
    right /= np.linalg.norm(right)
    y = np.cross(right, f)
    return mat_to_quat(np.column_stack([right, y, -f]))


def mat_to_quat(R) -> list[float]:
    import mujoco

    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.asarray(R, dtype=np.float64).reshape(9))
    return [float(v) for v in q]


def yaw_quat(yaw_deg: float) -> list[float]:
    h = math.radians(float(yaw_deg)) / 2.0
    return [math.cos(h), 0.0, 0.0, math.sin(h)]


def quat_mat(q) -> np.ndarray:
    import mujoco

    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(q, dtype=np.float64) / np.linalg.norm(q))
    return R.reshape(3, 3)


def apply_render(s) -> None:
    """The protocol's rendering on an MjSpec (the offscreen buffer is sized by the caller)."""
    s.visual.quality.shadowsize = RENDER["shadow_map"]
    s.visual.quality.offsamples = RENDER["multisamples"]
    s.visual.headlight.active = 1 if RENDER["headlight"] else 0


def apply_near_clip(m) -> None:
    """The protocol's near clipping distance on a compiled model: MuJoCo stores it as a fraction of `stat.extent`."""
    m.vis.map.znear = RENDER["near_clip_m"] / float(m.stat.extent)


def _apply_physics(s) -> None:
    import mujoco

    o = s.option
    o.timestep = PHYSICS_DT
    o.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    o.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
    o.impratio = PHYSICS["impratio"]
    o.solver = mujoco.mjtSolver.mjSOL_NEWTON
    o.iterations = PHYSICS["iterations"]
    o.tolerance = PHYSICS["tolerance"]
    o.gravity = PHYSICS["gravity"]


def _match_options(child, parent) -> None:
    """Child options equal to the parent's, so attaching reports no conflict (the parent's are the ones used)."""
    for k in ("integrator", "cone", "impratio", "timestep"):
        setattr(child.option, k, getattr(parent.option, k))


def add_robot(
    s,
    root,
    base_pos,
    base_quat=(1.0, 0.0, 0.0, 0.0),
    pedestal_height: float = 0.0,
    pedestal_half_size=(0.12, 0.12),
    spec: RobotSpec = FR3_2F85,
    camera: bool = True,
    pedestal_rgba=(0.22, 0.23, 0.26, 1.0),
) -> None:
    """Attach the robot to the MjSpec `s` (a scene, or an empty spec for a robot-only model).

    `base_pos`, `base_quat` (w, x, y, z): where the base of the arm stands (the top of the pedestal) and how it is
    turned; `pedestal_height`: how far down from there the pedestal goes, along world z (0: none). `root`: the verified
    model folder (assets.model_root()).
    """
    import mujoco

    _apply_physics(s)
    pos = [float(v) for v in base_pos]
    quat = [float(v) for v in np.asarray(base_quat, dtype=np.float64) / np.linalg.norm(base_quat)]
    wb = s.worldbody
    if pedestal_height > 0:
        hx, hy = (float(v) for v in pedestal_half_size)
        h = float(pedestal_height)
        wb.add_geom(
            name=ARM_PREFIX + "pedestal",
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=[hx, hy, h / 2.0],
            pos=[pos[0], pos[1], pos[2] - h / 2.0],
            quat=yaw_quat(math.degrees(math.atan2(quat_mat(quat)[1, 0], quat_mat(quat)[0, 0]))),
            rgba=[float(v) for v in pedestal_rgba],
        )
    arm = mujoco.MjSpec.from_file(str(root / spec.arm_file))
    for jname, inertia in spec.armature:
        arm.joint(jname).armature = float(inertia)
    hand = mujoco.MjSpec.from_file(str(root / spec.hand_file))
    _match_options(arm, s)
    _match_options(hand, s)
    s.attach(arm, frame=wb.add_frame(pos=pos, quat=quat), prefix=ARM_PREFIX)
    s.attach(hand, site=s.site(ARM_PREFIX + spec.attach_site), prefix=HAND_PREFIX)
    for b in s.bodies:
        if b.name.startswith(ARM_PREFIX):
            b.gravcomp = 1.0
    act = s.actuator(HAND_PREFIX + spec.gripper_actuator)
    act.forcerange = [-spec.gripper_force, spec.gripper_force]
    act.forcelimited = mujoco.mjtLimited.mjLIMITED_TRUE
    for gname in spec.pads:
        g = s.geom(HAND_PREFIX + gname)
        g.friction = list(PAD_CONTACT["friction"])
        g.condim = PAD_CONTACT["condim"]
        g.solref = list(PAD_CONTACT["solref"])
        g.solimp = list(PAD_CONTACT["solimp"])
        g.priority = PAD_CONTACT["priority"]
    if camera:
        c = spec.wrist_camera
        s.body(HAND_PREFIX + spec.hand_body).add_camera(
            name="camera_1", pos=list(c["pos"]), quat=look_at_quat(c["pos"], c["target"], c["up"]), fovy=c["fovy"]
        )


def robot_only_model(root, base_pos, base_quat, spec: RobotSpec = FR3_2F85):
    """The robot alone at the same base pose: the inverse kinematics' model (no scene, no contacts needed)."""
    import mujoco

    s = mujoco.MjSpec()
    s.modelname = "robot"
    add_robot(s, root, base_pos, base_quat, 0.0, spec=spec, camera=False)
    return s.compile()


def gripper_ctrl(open_fraction: float, spec: RobotSpec = FR3_2F85) -> float:
    """Actuator control for a free distance between the pads of `open_fraction` of the full opening (1 open, 0 shut)."""
    f = min(max(float(open_fraction), 0.0), 1.0)
    angles = [a for a, _ in spec.opening_table]
    widths = [w for _, w in spec.opening_table]
    width = f * widths[0]
    angle = float(np.interp(width, widths[::-1], angles[::-1]))
    if f <= 0.0:
        angle = spec.gripper_max
    return angle / spec.gripper_max * spec.gripper_ctrl_max


def gripper_width(driver_angle: float, spec: RobotSpec = FR3_2F85) -> float:
    """Free distance between the pads (m) at a driver joint angle, from the measured opening table."""
    angles = [a for a, _ in spec.opening_table]
    widths = [w for _, w in spec.opening_table]
    return float(np.interp(driver_angle, angles, widths))
