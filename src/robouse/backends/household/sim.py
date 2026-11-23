"""The household simulation: a scene package with the FR3 + 2F-85 in it, its plugins, and the 50 Hz controller.

One control step (`CONTROL_DT` = 20 ms): the behaviour plugin's `control`, the action, the physics extensions'
`before_step`, `SUBSTEPS` physics steps (each wrapped by the extensions' `before_substep` / `after_substep`), their
`after_step`, the goal plugin's `update`, the physical-state trace (docs/specification.md "Loading"; extensions.py).

Arm. Every interface ends in the same place: a joint setpoint goal, which a `motion.Tracker` reference chases within
the joint velocity and acceleration limits; the Menagerie position servos get `reference + lead * reference velocity`.
- Joint rows: absolute joint targets, clipped to the joint ranges less the margin (the clip is reported).
- EEF rows: an absolute pinch-point pose. Inverse kinematics solves the straight hand path from the current setpoint's
  pose to it (5 mm / 0.05 rad waypoints, each seeded by the one before); the end becomes the joint goal. A path that
  does not converge, needs a joint at its limit or jumps to another arm configuration is refused with the reason
  (`unreachable`, `joint_limit`, `branch_flip`): nothing moves.
- Planned moves (skills) follow time-parameterized rows of the same reference.
Gripper: G is the commanded opening, 1 fully open (85 mm) to 0 closed; it closes under the force limit (~88 N a pad).
"""

from __future__ import annotations

import hashlib
import importlib
import math
import sys
from types import SimpleNamespace

import mujoco
import numpy as np

from . import extensions as X
from . import motion
from .assets import model_root
from .ik import IK, mat_quat, straight_poses
from .package import Episode, PackageError, check_scene
from .robot import (
    ARM_PREFIX,
    CONTROL_DT,
    FR3_2F85,
    HAND_PREFIX,
    SUBSTEPS,
    add_robot,
    apply_render,
    gripper_ctrl,
    gripper_width,
    quat_mat,
    robot_only_model,
)

PATH_MAX_JUMP = 0.35  # rad: largest joint change between consecutive 5 mm / 0.05 rad waypoints of a hand path
BLOCKED_RAD = 0.15  # a planned move stops when a joint trails its reference by more than this (something is in the way)
SETTLE_RAD, SETTLE_VEL = 2e-3, 2e-2
REASONS = {"not_converged": "unreachable", "joint_limit": "joint_limit", "branch_flip": "branch_flip"}
PLUGIN_MODULES = ("goal", "behaviour", "tasks")


class SimulationDiverged(RuntimeError):
    pass


class Refused(ValueError):
    """An action row the controller will not execute (nothing moved, no step used). The message is for the agent."""

    def __init__(self, reason: str, detail: dict):
        self.reason, self.detail = reason, detail
        super().__init__(f"refused ({reason}): {detail.get('why', '')}. Nothing moved; no step was used.")


class InternalError(RuntimeError):
    """A plugin failed or broke a rule: an infrastructure error. Its message never names the task."""

    def __init__(self) -> None:
        super().__init__("an internal error occurred; the episode cannot continue")


def _quat_xyzw(q_wxyz) -> list[float]:
    return [float(q_wxyz[1]), float(q_wxyz[2]), float(q_wxyz[3]), float(q_wxyz[0])]


def rpy_to_quat(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """R = Rz(yaw) Ry(pitch) Rx(roll) (extrinsic x, y, z) as a quaternion (w, x, y, z)."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    R = np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ]
    )
    return mat_quat(R)


def quat_to_rpy(q_wxyz) -> list[float]:
    R = quat_mat(q_wxyz)
    pitch = math.asin(max(-1.0, min(1.0, -R[2, 0])))
    if abs(R[2, 0]) < 1 - 1e-9:
        roll = math.atan2(R[2, 1], R[2, 2])
        yaw = math.atan2(R[1, 0], R[0, 0])
    else:  # gimbal lock: yaw carries the whole turn about the vertical
        roll = 0.0
        yaw = math.atan2(-R[0, 1], R[1, 1])
    return [roll, pitch, yaw]


_OBJ = {
    "body": mujoco.mjtObj.mjOBJ_BODY,
    "geom": mujoco.mjtObj.mjOBJ_GEOM,
    "site": mujoco.mjtObj.mjOBJ_SITE,
    "joint": mujoco.mjtObj.mjOBJ_JOINT,
    "actuator": mujoco.mjtObj.mjOBJ_ACTUATOR,
    "equality": mujoco.mjtObj.mjOBJ_EQUALITY,
    "material": mujoco.mjtObj.mjOBJ_MATERIAL,
    "light": mujoco.mjtObj.mjOBJ_LIGHT,
    "tendon": mujoco.mjtObj.mjOBJ_TENDON,
    "sensor": mujoco.mjtObj.mjOBJ_SENSOR,
    "mesh": mujoco.mjtObj.mjOBJ_MESH,
}


class World:
    """What the plugins get: `model`, `data`, `step` (control steps since reset settling ended), `id(kind, ref)` and
    `robot` (geom ids, left/right pad geom ids, pinch-point pose, gripper opening)."""

    def __init__(self, sim: HouseholdSim):
        self._sim = sim
        self.model, self.data = sim.model, sim.data

    @property
    def step(self) -> int:
        return self._sim.tick

    def id(self, kind: str, ref: str) -> int:
        """MuJoCo id of a scene element by its instance-scoped name ("phone", "pad/charge_zone"); KeyError if none."""
        if kind not in _OBJ:
            raise KeyError(f"unknown element kind {kind!r}; kinds: {', '.join(_OBJ)}")
        i = mujoco.mj_name2id(self.model, _OBJ[kind], ref)
        if i < 0 or ref.startswith("robot/"):
            raise KeyError(f"no {kind} {ref!r} in the scene")
        return int(i)

    @property
    def robot(self) -> SimpleNamespace:
        s = self._sim
        p, q = s.hand_pose()
        return SimpleNamespace(
            geom_ids=frozenset(s.robot_geoms),
            left_pad_geom_ids=frozenset(s.left_pads),
            right_pad_geom_ids=frozenset(s.right_pads),
            pinch_pos=p,
            pinch_quat=q,
            gripper_open=s.gripper_open(),
        )


def _digest(d) -> str:
    h = hashlib.sha256()
    for a in (d.qpos, d.qvel, d.ctrl, d.act, d.eq_active):
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def _plugin_modules() -> dict:
    return {n: m for n, m in sys.modules.items() if n.split(".")[0] in PLUGIN_MODULES}


def _load_plugins(ep: Episode):
    """Import the package's entry points with plugin/ first on the import path. The import is isolated: modules named
    like the plugins (`goal`, `behaviour`, the vendored `tasks.*` helpers) are taken out of sys.modules for the
    import, so the package's own copies load fresh, and afterwards sys.modules is restored to the host's, so the
    host's `tasks.*` (or another package's plugins) are untouched. The loaded classes keep their own modules through
    their globals; a plugin must import its helpers at module level (an import inside a method would see the host's
    sys.modules). Returns (Goal class or None, Behaviour class or None)."""
    if not (ep.goal or ep.behaviour):
        return None, None
    saved = _plugin_modules()
    for name in saved:
        del sys.modules[name]
    path = str(ep.plugin_dir)
    sys.path.insert(0, path)
    old_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # never write into the package
    try:
        out = []
        for entry in (ep.goal, ep.behaviour):
            if entry is None:
                out.append(None)
                continue
            mod, cls = entry.split(":")
            try:
                out.append(getattr(importlib.import_module(mod), cls))
            except Exception as e:  # noqa: BLE001 - an authoring error; never shown to the policy
                raise PackageError(f"plugin {entry} does not import: {type(e).__name__}") from None
        return tuple(out)
    finally:
        sys.dont_write_bytecode = old_bytecode
        try:
            sys.path.remove(path)
        except ValueError:
            pass
        for name in _plugin_modules():  # the package's modules leave; the host's come back
            del sys.modules[name]
        sys.modules.update(saved)
        importlib.invalidate_caches()


class HouseholdSim:
    def __init__(self, episode: Episode):
        self.ep = episode
        self.rs = FR3_2F85
        root = model_root()
        try:
            s = mujoco.MjSpec.from_file(str(episode.scene_xml))
        except Exception:  # noqa: BLE001 - an authoring error; the parser's text names files
            raise PackageError("scene.xml does not parse") from None
        check_scene(s)
        s.modelname = "household"  # the scene file's own model name is not carried into the episode
        add_robot(
            s,
            root,
            episode.base_pos,
            episode.base_quat,
            episode.pedestal_height,
            episode.pedestal_half_size,
            pedestal_rgba=episode.pedestal_rgba,
        )
        c2 = episode.camera_2
        s.worldbody.add_camera(name="camera_2", pos=c2["pos"], quat=c2["quat"], fovy=c2["fovy"])
        apply_render(s)
        self.ext_classes = {k: X.load_class(k) for k in episode.extensions}
        for k, cls in self.ext_classes.items():
            if cls is None:
                raise PackageError(f"{k} packages are not supported by this backend version")
            prep = getattr(cls, "prepare", None)
            if callable(prep):
                try:
                    prep(s, episode.extensions[k], episode.root)
                except Exception as e:  # noqa: BLE001 - an authoring error, raised before the episode starts
                    raise PackageError(f"extension {k} could not prepare the scene: {type(e).__name__}") from None
        w, h = episode.render_size
        g = s.visual.global_
        g.offwidth, g.offheight = max(w, 1280), max(h, 960)
        try:
            self.model = s.compile()
        except Exception as e:  # noqa: BLE001 - an authoring error, raised before the episode starts
            raise PackageError(f"scene does not compile with the robot: {str(e)[:200]}") from None
        self.data = mujoco.MjData(self.model)
        m = self.model
        jid = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, ARM_PREFIX + j) for j in self.rs.arm_joints]
        self.arm_qadr = np.array([m.jnt_qposadr[j] for j in jid])
        self.arm_dadr = np.array([m.jnt_dofadr[j] for j in jid])
        self.arm_range = np.array([m.jnt_range[j] for j in jid])
        self.arm_ctrl = np.array(
            [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_ACTUATOR, ARM_PREFIX + a) for a in self.rs.arm_actuators]
        )
        self.ctrl_lo, self.ctrl_hi = m.actuator_ctrlrange[self.arm_ctrl, 0], m.actuator_ctrlrange[self.arm_ctrl, 1]
        self.grip_ctrl_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_ACTUATOR, HAND_PREFIX + self.rs.gripper_actuator)
        self.driver_qadr = [
            m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, HAND_PREFIX + j)]
            for j in self.rs.driver_joints
        ]
        self.site = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, HAND_PREFIX + self.rs.tool_site)
        self.lo = self.arm_range[:, 0] + self.rs.limit_margin
        self.hi = self.arm_range[:, 1] - self.rs.limit_margin
        self.ik = IK(
            robot_only_model(root, episode.base_pos, episode.base_quat),
            [ARM_PREFIX + j for j in self.rs.arm_joints],
            HAND_PREFIX + self.rs.tool_site,
            self.rs.limit_margin,
        )
        self.robot_bodies = {i for i in range(m.nbody) if m.body(i).name.startswith(ARM_PREFIX)}
        self.robot_geoms = {
            i
            for i in range(m.ngeom)
            if int(m.geom_bodyid[i]) in self.robot_bodies or m.geom(i).name.startswith(ARM_PREFIX)
        }  # the pedestal included
        pad = {g: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, HAND_PREFIX + g) for g in self.rs.pads}
        self.pad_geoms = set(pad.values())
        self.left_pads = {i for g, i in pad.items() if g.startswith("left")}
        self.right_pads = {i for g, i in pad.items() if g.startswith("right")}
        fwd = quat_mat(episode.base_quat)[:, 0].copy()
        fwd[2] = 0.0
        self.forward = fwd / max(float(np.linalg.norm(fwd)), 1e-9)
        q0 = np.asarray(episode.initial_qpos)
        if np.any(q0 < self.lo) or np.any(q0 > self.hi):
            raise PackageError("robot.initial_qpos is outside the joint ranges less the margin")
        self.goal_cls, self.behaviour_cls = _load_plugins(episode)
        self.world = World(self)
        self.goal_obj = self.behaviour_obj = None
        self.extensions: list[X.Active] = []
        self.tracer = None  # the physical-state trace (state_trace.Tracer), set by the backend
        self.infra_error: str | None = None
        self._renderers: dict = {}
        self.tick = 0
        self.ik_refusals = 0
        self.last_ik: dict | None = None
        self._row_cache: tuple | None = None
        self.grip_open_cmd = 1.0
        self.grip_cmd = 0.0
        self.tracker = motion.Tracker(self.home, self.rs.vel_limits, self.rs.acc_limits, CONTROL_DT)

    # ---- state -------------------------------------------------------------------------------------------------------
    @property
    def home(self) -> np.ndarray:
        return np.asarray(self.ep.initial_qpos, dtype=np.float64)

    def q(self) -> np.ndarray:
        return self.data.qpos[self.arm_qadr].copy()

    def qd(self) -> np.ndarray:
        return self.data.qvel[self.arm_dadr].copy()

    def hand_pose(self) -> tuple[np.ndarray, np.ndarray]:
        d = self.data
        return d.site_xpos[self.site].copy(), mat_quat(d.site_xmat[self.site])

    def driver_angle(self) -> float:
        return float(np.mean([self.data.qpos[a] for a in self.driver_qadr]))

    def gripper_open(self) -> float:
        w = gripper_width(self.driver_angle(), self.rs)
        return min(max(w / self.rs.opening_table[0][1], 0.0), 1.0)

    def pad_force(self) -> float:
        """Total normal force (N) of the finger pads' contacts with anything that is not the robot."""
        m, d = self.model, self.data
        f6 = np.zeros(6)
        total = 0.0
        for i in range(d.ncon):
            c = d.contact[i]
            g1, g2 = int(c.geom1), int(c.geom2)
            if (g1 in self.pad_geoms) == (g2 in self.pad_geoms):
                continue
            other = g2 if g1 in self.pad_geoms else g1
            if other in self.robot_geoms:
                continue
            mujoco.mj_contactForce(m, d, i, f6)
            total += abs(float(f6[0]))
        return total

    # ---- plugins -----------------------------------------------------------------------------------------------------
    def _plugin(self, fn, *args, read_only: bool = False):
        if self.infra_error:
            raise InternalError()
        before = _digest(self.data) if read_only else None
        try:
            out = fn(*args)
        except Exception as e:  # noqa: BLE001 - recorded for the researcher; the agent sees a neutral error
            self.infra_error = f"plugin {getattr(fn, '__qualname__', fn)}: {type(e).__name__}: {e}"[:500]
            raise InternalError() from None
        if read_only and _digest(self.data) != before:
            self.infra_error = f"plugin {getattr(fn, '__qualname__', fn)} changed the simulation state"
            raise InternalError()
        return out

    # ---- episode -----------------------------------------------------------------------------------------------------
    def reset(self) -> None:
        m, d = self.model, self.data
        mujoco.mj_resetData(m, d)
        home = self.home
        d.qpos[self.arm_qadr] = home
        d.ctrl[self.arm_ctrl] = home
        self.set_grip(self.ep.initial_gripper_open)
        angle = self.grip_cmd / self.rs.gripper_ctrl_max * self.rs.gripper_max  # the fingers start where commanded
        for a in self.driver_qadr:
            d.qpos[a] = angle
        mujoco.mj_forward(m, d)
        self.tracker.reset(home)
        self._row_cache = None
        self.target_pos, self.target_quat = self.ik.fk(home)
        self.infra_error = None
        self.tick = 0
        self.behaviour_obj = self.goal_obj = None
        self._close_extensions()
        for k, cls in self.ext_classes.items():
            self.extensions.append(X.Active(k, self._plugin(cls, self.world, self.ep.extensions[k])))
        if self.behaviour_cls is not None:
            self.behaviour_obj = self._plugin(self.behaviour_cls, self.world, dict(self.ep.behaviour_config))
        for _ in range(self.ep.reset_settle_steps):  # the scene comes to rest; part of the reset, not the budget
            self._control_step(home, np.zeros(7), count=False)
        self.tick = 0
        self.ik_refusals = 0
        self.last_ik = None
        if self.goal_cls is not None:
            self.goal_obj = self._plugin(self.goal_cls, self.world, read_only=True)

    def _control_step(self, ref, vel, count: bool = True) -> None:
        d = self.data
        if self.infra_error:
            raise InternalError()
        if self.behaviour_obj is not None:
            self._plugin(self.behaviour_obj.control, self.world)
        d.ctrl[self.arm_ctrl] = motion.servo_target(ref, vel, self.rs.lead, self.ctrl_lo, self.ctrl_hi)
        d.ctrl[self.grip_ctrl_id] = self.grip_cmd
        ext = self.extensions
        for e in ext:
            if e.before_step:
                self._plugin(e.before_step, self.world)
        sub = [e for e in ext if e.before_substep or e.after_substep]
        tracer = self.tracer if count else None
        for _ in range(SUBSTEPS):
            for e in sub:
                if e.before_substep:
                    self._plugin(e.before_substep, self.world)
            mujoco.mj_step(self.model, d)
            for e in sub:
                if e.after_substep:
                    self._plugin(e.after_substep, self.world)
            if tracer is not None:
                tracer.substep()
        for e in ext:
            if e.after_step:
                self._plugin(e.after_step, self.world)
        if d.warning[mujoco.mjtWarning.mjWARN_BADQACC].number > 0 or not np.all(np.isfinite(d.qpos)):
            self.infra_error = "the simulation became unstable"
            raise SimulationDiverged("the simulation became unstable")
        if count:
            self.tick += 1
            if self.goal_obj is not None:
                self._plugin(self.goal_obj.update, self.world, read_only=True)
            if self.tracer is not None:
                self.tracer.record(self.tick)

    def extension_trace(self) -> dict:
        """{key: state} of the extensions that report one (for the state trace; read-only)."""
        out = {}
        for e in self.extensions:
            if e.trace_state:
                v = self._plugin(e.trace_state, self.world, read_only=True)
                if v is not None:
                    out[e.key] = v
        return out

    def extension_summary(self) -> dict:
        out = {}
        for e in self.extensions:
            if e.summary:
                try:
                    out[e.key] = e.summary()
                except Exception as err:  # noqa: BLE001 - researcher-only detail
                    out[e.key] = {"error": f"{type(err).__name__}: {err}"[:300]}
        return out

    def _close_extensions(self) -> None:
        for e in self.extensions:
            if e.close:
                try:
                    e.close()
                except Exception:  # noqa: BLE001
                    pass
        self.extensions = []

    def goal_success(self) -> bool | None:
        """The goal plugin's verdict (None: the package has no goal)."""
        if self.goal_obj is None:
            return None
        return bool(self._plugin(self.goal_obj.success, self.world, read_only=True))

    def set_grip(self, open_fraction: float) -> None:
        """Commanded opening: 1 fully open, 0 closed (under the force limit)."""
        f = min(max(float(open_fraction), 0.0), 1.0)
        self.grip_open_cmd = f
        self.grip_cmd = gripper_ctrl(f, self.rs)

    def tick_tracker(self) -> None:
        """One control step: the reference moves toward the goal, the servos follow it."""
        ref, vel = self.tracker.step()
        self._control_step(ref, vel)

    def tick_reference(self, ref, vel) -> None:
        """One control step on a planned reference row (skills); the tracker is kept consistent with it."""
        self.tracker.set_state(ref, vel)
        self.tracker.goal = np.asarray(ref, dtype=np.float64).copy()
        self._row_cache = None
        self._control_step(ref, vel)

    def hold_here(self) -> None:
        """Make the measured posture the goal (after a blocked move, so the arm stops pushing)."""
        q = np.clip(self.q(), self.lo, self.hi)
        self.tracker.reset(q)
        self._row_cache = None
        self.target_pos, self.target_quat = self.ik.fk(q)

    # ---- joint rows --------------------------------------------------------------------------------------------------
    def joint_row(self, q) -> list[int]:
        """Absolute joint targets as the goal, clipped to the joint ranges less the margin. Returns the clipped joints
        (1-based)."""
        q = np.asarray(q, dtype=np.float64)
        clipped = [i + 1 for i in range(7) if q[i] < self.lo[i] or q[i] > self.hi[i]]
        self.tracker.goal = np.clip(q, self.lo, self.hi)
        self._row_cache = None
        self.target_pos, self.target_quat = self.ik.fk(self.tracker.goal)
        return clipped

    # ---- EEF rows ----------------------------------------------------------------------------------------------------
    def solve_pose(self, pos, quat) -> tuple[np.ndarray | None, dict]:
        """Joint path from the current setpoint to the pinch-point pose (rows include the start), or None and the
        refusal: {"reason": unreachable | joint_limit | branch_flip, "why": ...}."""
        seed = self.tracker.goal.copy()
        p0, q0 = self.ik.fk(seed)
        poses = straight_poses(p0, q0, pos, quat)
        path, res = self.ik.solve_path(poses, seed, max_jump=PATH_MAX_JUMP)
        self.last_ik = {**res.report(), "reason": REASONS.get(res.reason, res.reason)}
        if res.ok:
            return path, self.last_ik
        self.ik_refusals += 1
        reason = REASONS[res.reason]
        done = (len(path) - 1) / max(len(poses), 1)
        where = f"{done:.0%} of the way along the straight hand path"
        why = {
            "unreachable": f"the pose is out of the arm's reach (the hand path leaves it {where})",
            "joint_limit": f"a joint would come within 0.02 rad of its limit {where}",
            "branch_flip": f"the arm would have to jump to another configuration ({res.jump:.2f} rad on one joint) {where}",
        }[reason]
        return None, {"reason": reason, "why": why, "refused_at_fraction_of_path": round(done, 3)}

    def eef_row(self, pos, quat) -> None:
        """An absolute pinch-point pose as the goal; raises Refused (nothing changes) when it cannot be solved."""
        pos, quat = np.asarray(pos, dtype=np.float64), np.asarray(quat, dtype=np.float64)
        key = (tuple(np.round(pos, 9)), tuple(np.round(quat, 9)))
        if self._row_cache is not None and self._row_cache == key:  # the same row again (`--repeat`)
            return
        path, rep = self.solve_pose(pos, quat)
        if path is None:
            raise Refused(rep["reason"], rep)
        self.tracker.goal = path[-1].copy()
        self.target_pos, self.target_quat = pos, quat
        self._row_cache = key

    # ---- planned moves (skills) --------------------------------------------------------------------------------------
    def plan_pose(self, pos, quat) -> tuple[tuple | None, dict]:
        """Time-parameterized rows taking the hand along a straight line to the pose, or None and the refusal."""
        path, rep = self.solve_pose(pos, quat)
        if path is None:
            return None, rep
        return motion.path_move(path, self.rs.vel_limits, self.rs.acc_limits, CONTROL_DT), rep

    def plan_joints(self, target) -> tuple[np.ndarray, np.ndarray]:
        return motion.joint_move(self.tracker.goal, target, self.rs.vel_limits, self.rs.acc_limits, CONTROL_DT)

    def blocked(self) -> bool:
        return bool(np.max(np.abs(self.tracker.q - self.q())) > BLOCKED_RAD)

    def settled(self) -> bool:
        return bool(
            np.max(np.abs(self.tracker.goal - self.q())) < SETTLE_RAD and np.max(np.abs(self.qd())) < SETTLE_VEL
        )

    # ---- observation -------------------------------------------------------------------------------------------------
    def robot_state(self) -> dict:
        p, q = self.hand_pose()
        return {
            "hand_pos": [round(float(v), 4) for v in p],
            "eef_quat": [round(v, 5) for v in _quat_xyzw(q)],  # x, y, z, w
            "eef_rpy": [round(v, 4) for v in quat_to_rpy(q)],
            "gripper_open": round(self.gripper_open(), 3),
            "joint_pos": [round(float(v), 4) for v in self.q()],
            "robot_base_pos": [round(float(v), 4) for v in self.ep.base_pos],
            "robot_forward": [round(float(v), 4) for v in self.forward],
        }

    def render(self, camera: str, width: int, height: int) -> np.ndarray:
        key = (width, height)
        r = self._renderers.get(key)
        if r is None:
            r = self._renderers[key] = mujoco.Renderer(self.model, height=height, width=width)
        r.update_scene(self.data, camera=camera)
        return r.render().copy()

    def close(self) -> None:
        self._close_extensions()
        for r in self._renderers.values():
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass
        self._renderers.clear()
