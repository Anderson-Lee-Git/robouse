"""Household backend: a compiled scene package (package.py) with a Franka FR3 + Robotiq 2F-85 on a fixed base.

No RoboCasa, no robosuite: MuJoCo 4 in this process. The task's `robouse:` block names the package and the mode:

  {"backend": "household", "package": "package", "control": "eef" | "joint" | "text",
   "obs_mode": "vision", "cameras": ["camera_1", "camera_2"], "visible_fields": [...]}

`package` is the compiled package directory, absolute or relative to the task folder (`task_dir`, which robouse's task
loader adds to every spec: the folder of the task.md). A relative path without `task_dir` is refused.

Action rows are absolute targets, one per 50 Hz control step (protocol 1.0.0, contracts.md "Action rows"):
  eef    [X, Y, Z, ROLL, PITCH, YAW, G]: the pinch point's pose in the world frame, R = Rz(YAW) Ry(PITCH) Rx(ROLL).
         A row inverse kinematics cannot solve safely is refused with the reason (`unreachable`, `branch_flip`,
         `joint_limit`): nothing moves, no step is used. Skills: move_to (the pinch point to a position, orientation
         kept), move_to_pose, grip; each a sequence of the same absolute rows.
  joint  [Q1, ..., Q7, G]: joint targets in rad, clipped to the joint ranges less 0.02 rad (the reply says so).
         Skills: move_joints_to, grip.
  text   no motion: the agent observes and submits its plan as the text of `robo done`.
G: commanded gripper opening, 1 fully open (85 mm) to 0 closed (the gripper stops on what it holds).
There are no delta rows: robouse's built-in `move_to` and `grip` requests run through `start_move_to` and
`grip_action` (session hooks), never through a 4-number row.

Episode: the session settles `settle_steps` (25) after `done`, then asks `success()` (the goal plugin, once). A plugin
or extension failure ends the episode as `infrastructure_error` (session hook `infrastructure_error`). Every Code /
EEF / Joint episode writes the researcher-only physical-state trace `state-trace.jsonl.gz` into its run folder
(state_trace.py; ROBOUSE_STATE_TRACE=0 turns it off). With ROBOUSE_HOUSEHOLD_PYTHON set, the simulation runs in a
worker process started with that interpreter (worker.py; e.g. a wrapper that runs it on a compute allocation).

Cameras: `camera_1` on the gripper (wrist), `camera_2` fixed in the room; both calibrated (`robo info`).

Policy blindness: nothing this backend returns (info, observation, replies, errors) names the package, its path, its
files, the scene's model or element names or a task; the exporter writes the opaque episode handle as the task id.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ... import config
from ...core.embodiment_spec import Camera, Embodiment, Skill, SkillArg
from ..base import ActionSpec, Backend, G, StepInfo
from . import package as P
from .ik import rotvec
from .robot import CONTROL_DT, PHYSICS, PHYSICS_VERSION, RENDER
from .sim import PATH_MAX_JUMP, HouseholdSim, quat_to_rpy, rpy_to_quat

SKILL_CAP = 3000  # control steps (60 s) one move_to_pose / move_joints_to call may take
POSE_TOL = (0.005, 0.03)  # move_to_pose: reached within 5 mm and 0.03 rad
JOINT_TOL = 0.01
REACH_M = 1.0  # published bounds of an EEF row's position: the base position +- this
CAMERA_ROLES = {"camera_1": "wrist (moves with the hand)", "camera_2": "fixed in the room"}
GRIP_DOC = "commanded opening: 1 fully open (85 mm), 0 closed; the gripper closes under a force limit"


def resolve_package(spec: dict) -> Path:
    """The package directory: `package` absolute, or relative to the task folder `task_dir`."""
    pkg = spec.get("package")
    if not pkg:
        raise ValueError("a household task needs `package:` (the compiled scene package directory)")
    pkg = Path(pkg)
    if not pkg.is_absolute():
        if not spec.get("task_dir"):
            raise ValueError("a relative `package:` needs the task folder (task_dir) to resolve against")
        pkg = Path(spec["task_dir"]) / pkg
    return pkg


def worker_python() -> str:
    """ROBOUSE_HOUSEHOLD_PYTHON: the interpreter (or wrapper) of the simulation worker; empty: in this process."""
    return config.env("ROBOUSE_HOUSEHOLD_PYTHON").strip()


class HouseholdBackend(Backend):
    name = "household"
    robot_name = "fr3-2f85"
    robot_kind = "arm"
    probe_success = False
    image_flipped = False
    proprioception = ("hand_pos", "eef_quat", "eef_rpy", "gripper_open", "joint_pos", "robot_base_pos", "robot_forward")

    def __new__(cls, spec: dict | None = None, *a, **kw):
        if cls is HouseholdBackend and worker_python():  # the simulation runs in a worker process (remote.py)
            from .remote import RemoteHouseholdBackend

            return RemoteHouseholdBackend(spec)  # not a HouseholdBackend, so Python does not call __init__ again
        return super().__new__(cls)

    def __init__(self, spec: dict):
        self.spec = spec
        self.ep = P.load(resolve_package(spec))
        self.control = str(spec.get("control", "eef"))
        if self.control not in ("eef", "joint", "text"):
            raise ValueError(f"control must be eef, joint or text, not {self.control!r}")
        self.max_steps = self.ep.max_steps
        if "max_steps" in spec and not 1 <= int(spec["max_steps"]) <= P.MAX_STEPS_CAP:
            raise ValueError(f"max_steps must be 1 to {P.MAX_STEPS_CAP}")
        self.camera = str(spec.get("camera", "camera_2"))
        self.render_size = self.ep.render_size
        self.settle_steps = self.ep.settle_steps
        self.sim = HouseholdSim(self.ep)
        if self.control == "text":  # Text episodes do not run the goal plugin
            self.sim.goal_cls = None
        self._notes: list[dict] = []
        self._summary: dict | None = None
        self._judged: bool | None = None
        self._run_dir: Path | None = None
        self.tracer = None
        self._trace_status: dict | None = None
        self._init_action_spec(self.sim.lo, self.sim.hi)

    def _init_action_spec(self, lo, hi) -> None:
        if self.control == "joint":
            self.action_spec = ActionSpec(
                names=[f"Q{i}" for i in range(1, 8)] + ["G"],
                low=[round(float(v), 4) for v in lo] + [0.0],
                high=[round(float(v), 4) for v in hi] + [1.0],
                doc="absolute joint targets in rad (joint 1 at the base to joint 7 at the flange), clipped to these "
                "limits (the reply says so) and approached within the joint speed limits; G: " + GRIP_DOC,
            )
        else:
            b = self.ep.base_pos
            self.action_spec = ActionSpec(
                names=["X", "Y", "Z", "ROLL", "PITCH", "YAW", "G"],
                low=[round(b[i] - REACH_M, 3) for i in range(3)] + [-math.pi] * 3 + [0.0],
                high=[round(b[i] + REACH_M, 3) for i in range(3)] + [math.pi] * 3 + [1.0],
                doc="absolute target pose of the pinch point (between the fingertips) in the world frame: X, Y, Z in "
                "m; ROLL, PITCH, YAW in rad, R = Rz(YAW) Ry(PITCH) Rx(ROLL) (the convention of eef_rpy). Inverse "
                "kinematics moves the arm there within the joint speed limits; a row it cannot solve safely is "
                "refused with the reason (unreachable, branch_flip, joint_limit): nothing moves and no step is used. "
                "G: " + GRIP_DOC,
            )

    # ---- embodiment ------------------------------------------------------------------------------------------------
    def action_layout(self) -> list[G]:
        grip = G("gripper", 1, "gripper", "opening, 1 open to 0 closed", hold="last", doc=GRIP_DOC)
        if self.control == "joint":
            return [G("arm.joint_pos", 7, "joint_pos", "rad", hold="last", doc="joints 1-7, absolute"), grip]
        return [
            G(
                "arm.ee_pose",
                6,
                "ee_pose",
                "m, rad",
                hold="last",
                frame="world",
                doc="pinch point pose, absolute; R = Rz(YAW) Ry(PITCH) Rx(ROLL)",
            ),
            grip,
        ]

    def embodiment(self) -> Embodiment:
        emb = super().embodiment()
        w, h = self.render_size
        emb.sensors.cameras = [
            Camera("camera_1", mount="hand", width=w, height=h, doc=CAMERA_ROLES["camera_1"]),
            Camera("camera_2", mount="world", width=w, height=h, doc=CAMERA_ROLES["camera_2"]),
        ]
        emb.step_s = CONTROL_DT
        return emb

    def hold_action(self) -> list[float]:
        """Holding still: an empty row keeps the current setpoint and gripper command (never sent by the agent)."""
        return []

    @property
    def _grip(self) -> float:
        """The commanded gripper opening (the fingers stay as commanded when a move gives no G)."""
        return float(self.sim.grip_open_cmd)

    def grip_action(self, value: float) -> dict:
        """Session hook (`grip`): the row that holds the arm's setpoint and commands the gripper opening (0-1)."""
        return {"grip": float(np.clip(value, 0.0, 1.0))}

    def start_move_to(self, pos, grip: float | None, max_steps: int, tol: float):
        """Session hook (`move_to`): the pinch point along a straight line to `pos`, orientation kept, as a sequence of
        planned absolute rows (the same as move_to_pose with the current target orientation). At most `max_steps`
        steps: a longer path stops there and holds. Refused before anything moves when IK cannot follow the path."""
        if self.control != "eef":
            raise ValueError("move_to is not available for this task; use act")
        g = None if grip is None else float(np.clip(grip, 0.0, 1.0))
        return self._run_move_to(np.asarray(pos, dtype=float), g, int(max_steps), float(tol))

    def _run_move_to(self, pos: np.ndarray, grip: float | None, max_steps: int, tol: float):
        sim = self.sim
        quat = sim.target_quat.copy()
        rows, report = sim.plan_pose(pos, quat)
        if rows is None:
            return {
                "reached": False,
                "refused": report["reason"],
                "why": report["why"],
                "note": "nothing moved; no step was used",
            }
        ref, vel = rows
        cut = len(ref) > max_steps
        n = 0
        if len(ref) == 0 and grip is not None:
            yield {"grip": grip}
            n += 1
        stop = None
        for k in range(min(len(ref), max_steps)):
            yield {"ref": ref[k], "vel": vel[k], "grip": grip if k == 0 else None}
            n += 1
            if sim.blocked():
                stop = "blocked"
                break
        if stop is None and not cut:
            sim.target_pos, sim.target_quat = pos.copy(), quat
            while n < max_steps and not sim.settled():
                yield {}
                n += 1
                if sim.blocked():
                    stop = "blocked"
                    break
        if stop is not None or cut:
            sim.hold_here()
        dist = float(np.linalg.norm(pos - sim.hand_pose()[0]))
        out = {"reached": dist < tol, "distance": round(dist, 4)}
        if stop == "blocked":
            out["stalled"] = "the arm was blocked before reaching the target; it holds where it stopped"
        elif cut:
            out["stopped"] = f"max_steps ({max_steps}) reached before the target; the arm holds where it stopped"
        return out

    def skills(self) -> list[str]:
        if self.control == "text":
            return []
        return ["grip", "move_joints_to"] if self.control == "joint" else ["move_to", "grip", "move_to_pose"]

    def skill_specs(self) -> list[Skill]:
        out = super().skill_specs()
        grip = SkillArg("grip", "float", optional=True, doc="gripper opening (1 open, 0 closed) set at the start")
        if self.control == "joint":
            out.append(
                Skill(
                    "move_joints_to",
                    [SkillArg(f"q{i}", "float", "rad") for i in range(1, 8)] + [grip],
                    doc="Move the seven arm joints to absolute angles along a straight line in joint space within the "
                    "joint speed limits, then wait (up to 1 s) for the arm to come to rest. Targets outside the "
                    "joint limits are refused. Stops early if the arm is blocked.",
                    aliases=["move_joints_to", "move-joints-to"],
                )
            )
        elif self.control == "eef":
            out.append(
                Skill(
                    "move_to_pose",
                    [SkillArg(a, "float", "m") for a in "xyz"]
                    + [SkillArg(a, "float", "rad") for a in ("roll", "pitch", "yaw")]
                    + [grip],
                    doc="Move the pinch point along a straight line to a position and an absolute orientation "
                    "(R = Rz(yaw) Ry(pitch) Rx(roll), the convention of eef_rpy; the hand's +z points out between "
                    "the fingers, +y is the closing direction). The whole path is solved before the arm moves: a "
                    "path the arm cannot follow is refused with the reason (unreachable, branch_flip, joint_limit) "
                    "and nothing moves. Stops early if the arm is blocked.",
                    aliases=["move_to_pose", "move-to-pose"],
                )
            )
        return out

    def info_extra(self) -> dict:
        rs = self.sim.rs
        out: dict = {
            "control": self.control,
            "control_hz": round(1.0 / CONTROL_DT),
            "camera_roles": dict(CAMERA_ROLES),
            "robot": "Franka FR3 arm, Robotiq 2F-85 gripper, fixed pedestal",
            "joint_limits": [
                [round(float(a), 4), round(float(b), 4)] for a, b in zip(self.sim.lo, self.sim.hi, strict=True)
            ],
            "joint_speed_limits_rad_s": list(rs.vel_limits),
            "joint_acceleration_limits_rad_s2": list(rs.acc_limits),
            "gripper": {
                "max_opening_m": rs.opening_table[0][1],
                "closing_force_per_pad_n": round(rs.gripper_force * rs.pad_n_per_force),
            },
            "skill_step_cap": SKILL_CAP,
        }
        if self.control == "text":
            out["motion"] = "none: observe the scene, then submit the plan as the text of `robo done`"
        elif self.control == "eef":
            out["orientation"] = "eef_rpy: R = Rz(yaw) Ry(pitch) Rx(roll); eef_quat: x, y, z, w"
            out["inverse_kinematics"] = (
                "damped least squares along the straight hand path from the current setpoint (5 mm / 0.05 rad "
                "waypoints); refused when it does not converge (unreachable), when a joint would come within 0.02 rad "
                f"of its limit (joint_limit) or jump more than {PATH_MAX_JUMP} rad between waypoints (branch_flip)"
            )
        return out

    # ---- episode ---------------------------------------------------------------------------------------------------
    def attach_run_dir(self, run_dir) -> None:
        """Session hook: the episode's run folder, where the physical-state trace goes."""
        self._run_dir = Path(run_dir)

    def reset(self, seed: int) -> None:
        self._finish_trace(None)
        self.sim.tracer = None
        self.sim.reset()
        self._notes, self._summary, self._judged = [], None, None
        self._trace_status = None
        if self.control != "text" and self._run_dir is not None and config.flag("ROBOUSE_STATE_TRACE", default=True):
            from .state_trace import FILENAME, Tracer

            self.tracer = Tracer(self.sim, self._run_dir / FILENAME, self.control)
            self.tracer.record(self.sim.tick)
            self.sim.tracer = self.tracer

    def begin_settle(self) -> None:
        """Session hook: the settle after `done` starts (the trace marks its records)."""
        if self.tracer is not None:
            self.tracer.phase = "settle"

    def infrastructure_error(self) -> str | None:
        """Session hook: why the episode cannot continue (a plugin or extension failed), researcher-only."""
        return self.sim.infra_error

    def _finish_trace(self, goal) -> None:
        if self.tracer is not None:
            try:
                self.tracer.finish(goal)
            finally:
                self._trace_status = self.tracer.status()
                self.tracer = None
                self.sim.tracer = None

    def mj_model_data(self):
        return self.sim.model, self.sim.data

    def step(self, action) -> StepInfo:
        if self.control == "text":
            raise ValueError("this task takes no motion: observe, then submit your plan as the text of `robo done`")
        sim = self.sim
        if isinstance(action, dict):  # a planned move's reference row (skills)
            if action.get("grip") is not None:
                sim.set_grip(action["grip"])
            if "ref" in action:
                sim.tick_reference(action["ref"], action["vel"])
            else:
                sim.tick_tracker()
            return StepInfo(success=False)
        a = np.asarray(action, dtype=float).ravel()
        if not np.all(np.isfinite(a)):
            raise ValueError("action values must be finite numbers")
        if a.size == 0:  # hold still (the session's settle)
            sim.tick_tracker()
            return StepInfo(success=False)
        if a.size != self.action_spec.dim:
            raise ValueError(f"action must have {self.action_spec.dim} numbers {self.action_spec.names}")
        g = float(a[-1])
        if not 0.0 <= g <= 1.0:
            self._note({"clipped": "G", "to": min(max(g, 0.0), 1.0)})
        if self.control == "joint":
            if clipped := sim.joint_row(a[:7]):
                self._note({"clipped_joints": clipped, "to_limits": "joint limits less 0.02 rad"})
        else:
            sim.eef_row(a[:3], rpy_to_quat(*a[3:6]))  # raises Refused before anything moves
        sim.set_grip(g)
        sim.tick_tracker()
        return StepInfo(success=False)

    def _note(self, n: dict) -> None:
        if n not in self._notes:
            self._notes.append(n)

    def pop_notes(self) -> list[dict]:
        """Session hook: what the controller changed in the rows since the last call (clipping), for the reply."""
        n, self._notes = self._notes, []
        return n

    def success(self) -> bool:
        """After `done` and the session's settle (`settle_steps`): the goal plugin's verdict, asked once."""
        if self._judged is None:
            self._judged = bool(self.sim.goal_success())
            self._finish_trace(self._judged)
        return self._judged

    def session_summary(self) -> dict:
        if self._summary is None:
            sim = self.sim
            self._summary = {
                "backend": "household",
                "package_identity": self.ep.identity,
                "package_format_version": self.ep.format_version,
                "control": self.control,
                "robot": sim.rs.type,
                "physics": {"version": PHYSICS_VERSION, **PHYSICS},
                "render": dict(RENDER),
                "robot_base": {
                    "pos": self.ep.base_pos,
                    "quat": self.ep.base_quat,
                    "pedestal_height": self.ep.pedestal_height,
                },
                "control_steps": sim.tick,
                "ik_refusals": sim.ik_refusals,
                "goal": self.ep.goal if self.control != "text" else None,
                "plugin_helpers": self.ep.helpers,
                "goal_success": self._judged,
                **({"extensions": ext} if (ext := sim.extension_summary()) else {}),
                **({"state_trace": self._trace_status} if self._trace_status else {}),
                **({"infrastructure_error": sim.infra_error} if sim.infra_error else {}),
            }
        return self._summary

    # ---- observation -----------------------------------------------------------------------------------------------
    def observe(self) -> dict:
        return self.sim.robot_state()

    def hand_pos(self) -> np.ndarray:
        return self.sim.hand_pose()[0]

    def render(self, width: int | None = None, height: int | None = None) -> np.ndarray:
        w, h = (width, height) if width and height else self.render_size
        return self.sim.render(self.camera, int(w), int(h))

    def metrics_point(self) -> np.ndarray:
        return self.hand_pos()

    # ---- skills ----------------------------------------------------------------------------------------------------
    def start_skill(self, name: str, raw: list[str]):
        args = [a.split("=", 1)[1] if "=" in a else a for a in raw]
        try:
            vals = [float(a) for a in args]
        except ValueError:
            raise ValueError(f"{name} takes numbers") from None
        if not all(np.isfinite(vals)):
            raise ValueError(f"{name} takes finite numbers")
        if self.control == "joint" and name in ("move_joints_to", "move-joints-to"):
            if len(vals) not in (7, 8):
                raise ValueError("move_joints_to Q1 Q2 Q3 Q4 Q5 Q6 Q7 [G]: seven joint angles in rad")
            target = np.asarray(vals[:7])
            sim = self.sim
            bad = [
                f"q{i + 1}={target[i]:g} not in [{sim.lo[i]:.4f}, {sim.hi[i]:.4f}]"
                for i in range(7)
                if not sim.lo[i] <= target[i] <= sim.hi[i]
            ]
            if bad:
                raise ValueError("outside the joint limits: " + "; ".join(bad))
            grip = float(np.clip(vals[7], 0, 1)) if len(vals) == 8 else None
            return self._run_joints(target, grip)
        if self.control == "eef" and name in ("move_to_pose", "move-to-pose"):
            if len(vals) not in (6, 7):
                raise ValueError("move_to_pose X Y Z ROLL PITCH YAW [G]: a position in m and angles in rad")
            grip = float(np.clip(vals[6], 0, 1)) if len(vals) == 7 else None
            return self._run_pose(np.asarray(vals[:3]), rpy_to_quat(*vals[3:6]), grip)
        raise ValueError(f"unknown skill {name!r}; skills: {', '.join(self.skills())}")

    def _execute(self, rows, grip):
        """Yield the planned reference rows, then wait for the arm to settle. Returns (stop reason, settled)."""
        pos, vel = rows
        if len(pos) > SKILL_CAP:
            return "too_long", False
        sim = self.sim
        for k in range(len(pos)):
            yield {"ref": pos[k], "vel": vel[k], "grip": grip if k == 0 else None}
            if sim.blocked():
                sim.hold_here()
                return "blocked", False
        if len(pos) == 0 and grip is not None:
            yield {"grip": grip}
        for _ in range(50):
            if sim.settled():
                return None, True
            yield {}
            if sim.blocked():
                sim.hold_here()
                return "blocked", False
        settled = sim.settled()
        if not settled:
            sim.hold_here()
        return None, settled

    def _run_joints(self, target: np.ndarray, grip: float | None):
        rows = self.sim.plan_joints(target)
        stop, settled = yield from self._execute(rows, grip)
        if stop is None:
            self.sim.joint_row(target)  # the EEF target follows the joints (target_pos, target_quat)
        e = float(np.max(np.abs(target - self.sim.q())))
        out = {"reached": e < JOINT_TOL, "max_joint_error": round(e, 4), "settled": settled}
        if stop == "blocked":
            out["stalled"] = "the arm was blocked before reaching the target; it holds where it stopped"
        elif stop == "too_long":
            out["refused"] = f"the move would take more than {SKILL_CAP} steps"
        return out

    def _run_pose(self, pos: np.ndarray, quat: np.ndarray, grip: float | None):
        sim = self.sim
        rows, report = sim.plan_pose(pos, quat)
        if rows is None:
            return {
                "reached": False,
                "refused": report["reason"],
                "why": report["why"],
                "note": "nothing moved; no step was used",
            }
        stop, settled = yield from self._execute(rows, grip)
        if stop is None:
            sim.target_pos, sim.target_quat = pos.copy(), quat.copy()
        hp, hq = sim.hand_pose()
        dist = float(np.linalg.norm(pos - hp))
        ang = float(np.linalg.norm(rotvec(hq, quat)))
        out = {
            "reached": dist < POSE_TOL[0] and ang < POSE_TOL[1],
            "distance": round(dist, 4),
            "angle_error_rad": round(ang, 4),
            "eef_rpy": [round(v, 4) for v in quat_to_rpy(hq)],
            "settled": settled,
        }
        if stop == "blocked":
            out["stalled"] = "the arm was blocked before reaching the pose; it holds where it stopped"
        elif stop == "too_long":
            out["refused"] = f"the move would take more than {SKILL_CAP} steps"
        return out

    def close(self) -> None:
        try:
            self._finish_trace(self._judged)
        finally:
            self._summary = None  # recomputed with the trace's final status
            self.session_summary()
            self.sim.close()
