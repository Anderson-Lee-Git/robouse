"""RoboCasa scenario backend: a kitchen built from a scenario spec (scenario.py) instead of a RoboCasa task class.

The task's `robouse:` block carries the spec inline (`scenario: {...}`; task folders are denied to the agent). The spec
names the kitchen, the fixtures, the objects and their placements, the fixtures' initial states, the instruction, a goal
predicate and monitors. `ep_meta` in the spec (RoboCasa's episode record) makes every reset rebuild the same scene.

Robot: RoboCasa's PandaOmron; the base and torso stay where the kitchen parks them, only the arm and gripper move.
Since robot base 2.0.0 (scenario.py ROBOT_BASE_VERSION) they are locked there; the session summary records it.
`control` picks the arm interface (the robot state and the cameras are the same in both):
  eef    [DX, DY, DZ, DROLL, DPITCH, DYAW, GRIP]: 1.0 moves the hand target by 2 cm along the world axes / turns it by
         0.1 rad about them (world-frame rotation vector) per step; robosuite's OSC_POSE servoes the hand to the target,
         which stays within 5 cm and 0.3 rad of the hand. Skills: move_to, move_to_pose, grip.
  joint  [DQ1, ..., DQ7, GRIP]: 1.0 on DQi asks for 0.2 rad on joint i per step (robosuite JOINT_POSITION, delta targets,
         kp 150). Skills: move_joints_to, grip.
  text   no motion: every action and skill is refused; the agent observes the scene and submits its plan as the text
         of `robo done` (kept in the result as `agent_text`).
GRIP: 0 keeps the fingers, > 0 closes, -f opens to fraction f (-1 fully open). One step = 50 ms (20 Hz).

Cameras: `camera_1` is the wrist camera (robot0_eye_in_hand); `camera_2` is fixed in the kitchen, posed at reset
behind and beside the parked robot, looking at its work area.

Monitors are evaluated by the worker after every step and reach the result only as `safety_events`; they are never part
of an observation. A monitor that could not be evaluated is reported as an error, never as "did not happen".

Physical-state trace: an episode with motion (eef, joint) writes `state-trace.jsonl.gz` into its run folder
(state_trace.py: object poses, fixture joints and power, grasps, contacts, liquid counts, after every control). It is
researcher-only evidence: no reply or observation carries it, and ROBOUSE_STATE_TRACE=0 turns it off (practice and
development episodes, whose files a broker may serve). A trace that fails is reported in the session summary.
"""

from __future__ import annotations

import json
import os

import numpy as np

from ... import config
from ...core.embodiment_spec import Skill, SkillArg
from ...workers.client import StdioWorker
from ..base import ActionSpec, Backend, G, StepInfo, arm_layout
from ..libero.backend import mat2rpy, quat2mat, rot_error, rpy2mat
from .backend import WORKER
from .state_trace import FILENAME as STATE_TRACE_FILE

CAMERAS = {"camera_1": "robot0_eye_in_hand", "camera_2": "camera_2_external"}
STEP_M, ROT_STEP, JOINT_STEP = 0.02, 0.1, 0.2  # as worker.py
SKILL_CAP = 200  # steps one move_to_pose / move_joints_to call may take
POSE_TOL = (0.01, 0.05)  # move_to_pose is done within 1 cm and 0.05 rad


def check_spec(spec: dict) -> None:
    """Static checks of a scenario spec (names and predicates), before any simulation."""
    from . import scenario as S

    S.load_plugins()  # scene-specific predicates, as in the worker
    S.load_liquid("compute").requirement(spec)
    for k in ("id", "kitchen", "instruction", "robot_anchor", "fixtures", "objects"):
        if k not in spec:
            raise ValueError(f"scenario spec has no {k!r}")
    fixtures = set(spec["fixtures"])
    seen: set[str] = set()
    for key, f in spec["fixtures"].items():
        if f.get("type") not in S.FIXTURE_TYPES:
            raise ValueError(f"fixture {key}: unknown type {f.get('type')!r}")
        if f.get("ref") and f["ref"] not in seen:
            raise ValueError(f"fixture {key}: ref {f['ref']!r} must be a fixture named before it")
        seen.add(key)
    if spec["robot_anchor"] not in fixtures:
        raise ValueError(f"robot_anchor {spec['robot_anchor']!r} is not a fixture")
    S.robot_base_mode(spec)  # `locked` (default) or `free`
    S.initial_arm_qpos(spec)  # optional fixed reset posture; runtime checks compiled joint limits
    objects = set()
    for o in spec["objects"]:
        if not (o.get("model") or o.get("category")):
            raise ValueError(f"object {o.get('name')}: needs a model or a category")
        inside = o["placement"].get("object")
        if inside is not None:
            if inside not in objects:
                raise ValueError(f"object {o['name']}: placement object {inside!r} must be an object named before it")
        elif o["placement"].get("fixture") not in fixtures:
            raise ValueError(f"object {o['name']}: placement fixture {o['placement'].get('fixture')!r} unknown")
        t = o.get("tint")
        if t is not None and not (isinstance(t, list) and len(t) == 4 and all(0 <= float(v) <= 1 for v in t)):
            raise ValueError(f"object {o['name']}: tint must be [r, g, b, a] in [0, 1]")
        fr = o.get("friction")
        if fr is not None and not (isinstance(fr, list) and len(fr) == 3 and all(float(v) >= 0 for v in fr)):
            raise ValueError(f"object {o['name']}: friction must be [sliding, torsional, rolling] >= 0")
        a = o.get("attach")
        if a is not None:
            if not isinstance(a, dict) or a.get("to") not in objects or float(a.get("max_n", 0)) <= 0:
                raise ValueError(f"object {o['name']}: attach needs `to` (an object named before it) and max_n > 0")
        objects.add(o["name"])
    for st in spec.get("streams") or []:
        if st.get("fixture") not in fixtures or not st.get("objects") or any(o not in objects for o in st["objects"]):
            raise ValueError(f"stream {st!r}: needs a known sink fixture and known objects")
    for o in spec["objects"]:
        if o.get("adhere") is not None and not float((o["adhere"] or {}).get("max_n", 0)) > 0:
            raise ValueError(f"object {o['name']}: adhere needs max_n > 0")
    for s in spec.get("fixture_states", []):
        if s.get("fixture") not in fixtures:
            raise ValueError(f"fixture state on unknown fixture {s.get('fixture')!r}")
    if spec.get("goal"):
        steps = {m["id"] for m in spec.get("monitors", []) if m.get("when", "step") == "step"}
        S.check_predicate(spec["goal"], objects, fixtures, steps)
    ids = [m["id"] for m in spec.get("monitors", [])]
    if len(ids) != len(set(ids)):
        raise ValueError("monitor ids must be unique")
    seen: set[str] = set()  # a monitor may use `fired` on a step monitor listed before it
    for m in spec.get("monitors", []):
        if m.get("when", "step") not in ("step", "end"):
            raise ValueError("monitor when must be step or end")
        if "hold_steps" in m and not (m.get("when", "step") == "step" and isinstance(m["hold_steps"], int)
                                      and m["hold_steps"] >= 1):
            raise ValueError(f"monitor {m['id']}: hold_steps must be a positive integer on a step monitor")
        S.check_predicate(m["pred"], objects, fixtures, set(seen))
        if "reset_credit_v1" in m:
            from .rinse import validate_reset_credit
            validate_reset_credit(m)
            S.check_predicate(m["reset_credit_v1"]["pred"], objects, fixtures, set(seen))
        if m.get("when", "step") == "step":
            seen.add(m["id"])


class RobocasaScenarioBackend(Backend):
    name = "robocasa_scenario"
    robot_name = "panda-omron-2f"
    probe_success = False
    image_flipped = False

    def __init__(self, spec: dict):
        self.spec = spec
        self.condition_requirement = spec.get("physics_condition")
        self.condition = None
        if self.condition_requirement is not None:
            from .physics_condition import requirement
            requirement(self.condition_requirement)
        sc = spec.get("scenario")
        if isinstance(sc, str):
            sc = json.loads(sc)
        if not isinstance(sc, dict):
            raise ValueError("a robocasa_scenario task needs `scenario:` (the spec, inline)")
        check_spec(sc)
        self.scenario = sc
        self.control = str(spec.get("control", "eef"))
        if self.control not in ("eef", "joint", "text"):
            raise ValueError(f"control must be eef, joint or text, not {self.control!r}")
        self.max_steps = int(spec.get("max_steps", sc.get("max_steps", 900)))
        self.camera = str(spec.get("camera", "camera_2"))
        self.render_size = tuple(spec.get("render_size", (640, 480)))
        self.settle_steps = int(spec.get("settle_steps", 60))
        self._grip = 0.0  # GRIP 0 keeps the fingers: skills hold them
        self._summary, self._closed = None, False
        if self.control == "joint":
            self.action_spec = ActionSpec(
                names=[f"DQ{i}" for i in range(1, 8)] + ["GRIP"],
                low=[-1.0] * 8,
                high=[1.0] * 8,
                doc=f"delta joint positions (robosuite JOINT_POSITION, 20 Hz): 1.0 on DQi asks for {JOINT_STEP} rad on "
                "joint i per step; GRIP: 0 keeps the fingers, > 0 closes, -f opens to fraction f (-1 fully open)",
            )
        else:
            self.action_spec = ActionSpec(
                names=["DX", "DY", "DZ", "DROLL", "DPITCH", "DYAW", "GRIP"],
                low=[-1.0] * 7,
                high=[1.0] * 7,
                doc="hand target deltas (20 Hz): 1.0 on DX/DY/DZ moves the target 2 cm along world x/y/z, 1.0 on "
                "DROLL/DPITCH/DYAW turns it 0.1 rad about world x/y/z; the hand is servoed to the target; GRIP: 0 keeps "
                "the fingers, > 0 closes, -f opens to fraction f (-1 fully open)",
            )
        self.worker = StdioWorker(
            "robocasa",
            config.sim_python("robocasa", "robocasa"),
            WORKER,
            setup=config.SUITES_DOCS,
            env={"PYTHONHASHSEED": "0",
                 **({"OMP_NUM_THREADS": str(sc["compute"]["threads"])} if sc.get("compute") else {})},
        )
        self._state: dict | None = None
        self._last: dict = {}
        self._success = False
        self.meta: dict = {}
        self._run_dir = None  # where the physical-state trace goes (Episode.attach_run_dir)
        self.trace: dict | None = None  # trace_start's reply

    def _call(self, cmd: str, **kw):
        return self.worker.call(cmd, **kw)

    # ---- embodiment ------------------------------------------------------------------------------------------------
    def action_layout(self) -> list[G]:
        grip_doc = "0 keeps the fingers, > 0 closes, -f opens to fraction f"
        if self.control == "joint":
            return [
                G("arm.joint_delta", 7, "joint_delta", f"1.0 asks for {JOINT_STEP} rad per step", doc="joints 1-7"),
                G("gripper", 1, "gripper", "normalized", hold="zero", doc=grip_doc),
            ]
        return arm_layout(
            "hand target: 2 cm per unit per step",
            rotation=f"hand target: {ROT_STEP} rad per unit per step",
            grip_hold="zero",
            grip_initial=None,
            grip_doc=grip_doc,
        )

    def hold_action(self) -> list[float]:
        return [0.0] * self.action_spec.dim

    def skills(self) -> list[str]:
        if self.control == "text":
            return []
        return ["grip", "move_joints_to"] if self.control == "joint" else ["move_to", "grip", "move_to_pose"]

    def skill_specs(self) -> list[Skill]:
        out = super().skill_specs()
        grip = SkillArg("grip", "float", optional=True, doc="gripper command held while moving")
        if self.control == "joint":
            out.append(
                Skill(
                    "move_joints_to",
                    [SkillArg(f"q{i}", "float", "rad") for i in range(1, 8)] + [grip],
                    doc="Servo the seven arm joints to absolute angles with the delta joint action; stops when every "
                    f"joint is within 0.01 rad, when the arm stops moving, or after {SKILL_CAP} steps.",
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
                    doc="Move the hand target toward a position and an absolute orientation, one full action unit per "
                    "step (2 cm, 0.1 rad). ROLL, PITCH, YAW: extrinsic rotations about the world x, y, z axes, "
                    "R = Rz(yaw) Ry(pitch) Rx(roll), of the frame `eef_quat` reports (`eef_rpy` gives its current "
                    f"angles). Stops within 1 cm and 0.05 rad, when the hand stops moving, or after {SKILL_CAP} steps.",
                    aliases=["move_to_pose", "move-to-pose"],
                )
            )
        return out

    def info_extra(self) -> dict:
        out: dict = {"control": self.control, "camera_roles": {"camera_1": "wrist", "camera_2": "fixed in the kitchen"}}
        if self.control == "text":
            out["motion"] = "none: observe the scene, then submit the plan as the text of `robo done`"
        elif self.control == "joint":
            out["joint_step_rad"] = JOINT_STEP
            out["joint_limits"] = [[round(a, 4), round(b, 4)] for a, b in self._joint_limits]
        else:
            out["orientation"] = "eef_rpy: extrinsic x-y-z, R = Rz(yaw) Ry(pitch) Rx(roll)"
        return out

    # ---- episode ---------------------------------------------------------------------------------------------------
    def attach_run_dir(self, run_dir) -> None:
        """The episode's run folder (called before reset): the physical-state trace is written there."""
        from pathlib import Path

        self._run_dir = Path(run_dir)

    def _start_trace(self) -> None:
        self.trace = None
        if self.control == "text" or self._run_dir is None or not config.flag("ROBOUSE_STATE_TRACE", default=True):
            return
        try:
            self.trace = self._call("trace_start", path=str(self._run_dir.resolve() / STATE_TRACE_FILE))
        except Exception as e:  # noqa: BLE001 - tracing never stops an episode; the summary says it failed
            self.trace = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}

    def begin_settle(self) -> None:
        """The still steps after `robo done` begin (session.finish): the trace labels them `settle`. The held action
        is unchanged."""
        if self.trace and self.trace.get("ok"):
            try:
                self._call("trace_phase", phase="settle")
            except Exception:  # noqa: BLE001
                pass

    def reset(self, seed: int) -> None:
        sc = self.scenario
        self._summary = None
        seed = int(sc.get("seed", seed))  # the scene is the scenario's; ep_meta, when recorded, fixes it exactly
        self.meta = self._call(
            "make_scenario",
            spec={k: v for k, v in sc.items() if k != "ep_meta"},
            seed=seed,
            control="joint" if self.control == "joint" else "eef",
            ep_meta=sc.get("ep_meta"),
            settle_steps=self.settle_steps,
        )
        self._joint_limits = self._call("joint_limits")
        self._state, self._last = None, {}
        self._success = False
        if self.condition_requirement is not None:
            from pathlib import Path
            from .physics_condition import FILENAME, record_or_check, require_equal

            actual = self._call(
                "physics_condition", requirement=self.condition_requirement,
                render_size=list(self.render_size),
                reset={"seed": seed, "settle_steps": self.settle_steps},
            )
            if self.condition is not None:
                require_equal(self.condition, actual)
            # The configured group receipt is shared by development and final resets.
            # It stays outside any policy workspace or broker-served directory.
            group = os.environ.get("ROBOUSE_PHYSICS_CONDITION_FILE")
            if group:
                record_or_check(Path(group), actual,
                                must_exist=os.environ.get("ROBOUSE_PHYSICS_CONDITION_RESUME") == "1")
            if self._run_dir is not None:
                record_or_check(self._run_dir / FILENAME, actual)
            self.condition = actual
        self._start_trace()

    def step(self, action) -> StepInfo:
        if self.control == "text":
            raise ValueError("this task takes no motion: observe, then submit your plan as the text of `robo done`")
        if isinstance(action, dict):  # move_to_pose: the worker moves the targets toward the pose
            r = self._call("step", action=[0.0] * 6 + [float(action.get("grip", 0.0))], pose=action["pose"])
        else:
            a = np.asarray(action, dtype=float).ravel()
            r = self._call("step", action=[float(x) for x in np.clip(a, -1, 1)])
        self._state, self._last = None, r
        self._success = bool(r["success"])
        return StepInfo(success=self._success)

    def success(self) -> bool:
        return bool(self._call("success")["success"])

    @property
    def events(self) -> list[dict]:
        """Hidden monitors (result.json `safety_events`). An unreadable monitor is an error event, never silence."""
        try:
            return list(self._call("monitor_events")["events"])
        except Exception as e:  # noqa: BLE001
            return [{"id": "monitor_unavailable", "error": f"{type(e).__name__}: {e}"[:300]}]

    def session_summary(self) -> dict:
        # the session asks again after close(); the worker is gone by then, and the summary read at finish stands
        if self._summary is not None and self._closed:
            return self._summary
        try:
            m = self._call("monitor_events")
        except Exception as e:  # noqa: BLE001
            return {"scenario": self.scenario.get("id"), "monitor_error": f"{type(e).__name__}: {e}"[:300],
                    **({"compute": dict(self.scenario["compute"])} if self.scenario.get("compute") else {})}
        self._summary = {
            "scenario": self.scenario.get("id"),
            "control": self.control,
            "goal_at_end": m.get("goal"),
            **({"goal_error": m["goal_error"]} if m.get("goal_error") else {}),
            "monitor_steps": m.get("steps"),
            "end_state_events": [e for e in m.get("events", []) if e.get("when") == "end"],
            "settle_motion": self.meta.get("settle_motion"),
            "robot_base": m.get("robot_base") or self.meta.get("robot_base"),  # how the base was held, and its drift
            **({"compute": dict(self.scenario["compute"])} if self.scenario.get("compute") else {}),
            **({"state_trace_error": t["error"]} if (t := getattr(self, "trace", None)) and not t.get("ok") else {}),
        }
        return self._summary

    # ---- observation -----------------------------------------------------------------------------------------------
    def observe(self) -> dict:
        if self._state is None:
            st = self._call("observe", features=[])
            st["eef_rpy"] = [round(float(v), 4) for v in mat2rpy(quat2mat(st["eef_quat"]))]
            st["task_instruction"] = self.meta.get("lang", "")
            self._state = st
        return dict(self._state)

    def hand_pos(self) -> np.ndarray:
        if "hand_pos" in self._last:
            return np.asarray(self._last["hand_pos"], dtype=float)
        return np.asarray(self.observe()["hand_pos"], dtype=float)

    def _eef_R(self) -> np.ndarray:
        q = self._last.get("eef_quat") or self.observe()["eef_quat"]
        return quat2mat(q)

    def joint_pos(self) -> np.ndarray:
        return np.asarray(self._last.get("joint_pos") or self.observe()["joint_pos"], dtype=float)

    def render(self, width: int | None = None, height: int | None = None) -> np.ndarray:
        w, h = (width, height) if width and height else self.render_size
        return self._call("render", camera=CAMERAS.get(self.camera, self.camera), width=int(w), height=int(h))

    def camera_info(self, cameras: list[str]) -> list[dict]:
        from ...core.cameras import pinhole_camera

        w, h = self.render_size
        out = []
        for name in cameras:
            c = self._call("camera", name=CAMERAS.get(name, name))
            out.append(pinhole_camera(name, c["pos"], c["xmat"], c["fovy"], int(w), int(h)))
        return out

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
                raise ValueError("move_joints_to Q1 Q2 Q3 Q4 Q5 Q6 Q7 [GRIP]: seven joint angles in rad")
            target = np.asarray(vals[:7])
            bad = [
                f"q{i + 1}={target[i]:g} not in [{lo:.4f}, {hi:.4f}]"
                for i, (lo, hi) in enumerate(self._joint_limits)
                if not lo <= target[i] <= hi
            ]
            if bad:
                raise ValueError("outside the joint limits: " + "; ".join(bad))
            return self._move_joints(target, float(np.clip(vals[7], -1, 1)) if len(vals) == 8 else 0.0)
        if self.control == "eef" and name in ("move_to_pose", "move-to-pose"):
            if len(vals) not in (6, 7):
                raise ValueError("move_to_pose X Y Z ROLL PITCH YAW [GRIP]: a position in m and world-frame angles in rad")
            grip = float(np.clip(vals[6], -1, 1)) if len(vals) == 7 else 0.0
            return self._move_pose(np.asarray(vals[:3]), rpy2mat(*vals[3:6]), grip)
        raise ValueError(f"unknown skill {name!r}; skills: {', '.join(self.skills())}")

    def _move_joints(self, target: np.ndarray, grip: float):
        hist: list[np.ndarray] = []
        stalled = False
        for _ in range(SKILL_CAP):
            q = self.joint_pos()
            e = target - q
            if float(np.abs(e).max()) < 0.01:
                break
            hist.append(q)
            if len(hist) > 8 and float(np.abs(hist[-1] - hist[-9]).max()) < 0.002:
                stalled = True
                break
            yield [*np.clip(e / JOINT_STEP, -1, 1).tolist(), grip]
            grip = 0.0  # the gripper command is sent once, then held
        e = target - self.joint_pos()
        out = {"reached": bool(np.abs(e).max() < 0.015), "max_joint_error": round(float(np.abs(e).max()), 4)}
        if stalled:
            out["stalled"] = "the arm stopped moving before reaching the target (blocked)"
        return out

    def _move_pose(self, pos: np.ndarray, rot: np.ndarray, grip: float):
        pose = {"pos": [float(v) for v in pos], "R": [float(v) for v in rot.ravel()]}

        def err():
            return pos - self.hand_pos(), rot_error(rot, self._eef_R())

        hist: list[tuple[np.ndarray, np.ndarray]] = []
        stalled = False
        for _ in range(SKILL_CAP):
            dp, dr = err()
            if np.linalg.norm(dp) < POSE_TOL[0] and np.linalg.norm(dr) < POSE_TOL[1]:
                break
            hist.append((self.hand_pos(), self._eef_R()))
            if len(hist) > 8:
                (p0, r0), (p1, r1) = hist[-9], hist[-1]
                if np.linalg.norm(p1 - p0) < 0.002 and np.linalg.norm(rot_error(r1, r0)) < 0.01:
                    stalled = True
                    break
            yield {"pose": pose, "grip": grip}
            grip = 0.0
        dp, dr = err()
        out = {
            "reached": bool(np.linalg.norm(dp) < POSE_TOL[0] * 1.5 and np.linalg.norm(dr) < POSE_TOL[1] * 1.5),
            "distance": round(float(np.linalg.norm(dp)), 4),
            "angle_error_rad": round(float(np.linalg.norm(dr)), 4),
            "eef_rpy": [round(float(a), 4) for a in mat2rpy(self._eef_R())],
        }
        if stalled:
            out["stalled"] = "the hand stopped moving before reaching the pose (out of reach, a joint limit, or blocked)"
        return out

    def close(self) -> None:
        self._closed = True
        if getattr(self, "trace", None) and self.trace.get("ok"):
            try:
                self._call("trace_finish")  # the final state; the worker's close would write it too
            except Exception:  # noqa: BLE001 - a dead worker leaves an incomplete trace, which readers flag
                pass
        self.worker.close()
