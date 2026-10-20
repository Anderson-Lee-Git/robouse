"""Dual YAM: Dream Labs' bimanual YAM station in simulation, the robot Dream-1 (dreamlabs/dream-1-beta) is trained on.

The scene is Dream Labs' own MuJoCo example from the `dreamlabs` wheel (1.0.0, Apache-2.0), unmodified: two I2RT YAM
arms with parallel grippers face a table from one side, with an apple, an orange, a banana, a water bottle, a ceramic
bowl and a plate on it, and three calibrated cameras: `top` (over the robots, looking across the table), and `left`
and `right` on the wrists. It needs MuJoCo 3.3.5 or later, so the simulation runs in its own virtualenv (default
~/.cache/robouse/yam-venv, override with ROBOUSE_YAM_PYTHON) as a subprocess (worker.py); this module is the bridge.
Setup: docs/suites/yam.md.

Frame: metres, +z up, the table top at z = 0.76. The robots stand at y = 0.24 and reach toward -y; the left arm's base
is at x = +0.305 and the right arm's at x = -0.305 (left and right as the top camera sees them).

Action (14 numbers, the layout of Dream's YAM embodiment): the right arm's six joint angles (rad, absolute position
targets), the right gripper's opening (0 closed, 1 open), then the same seven for the left arm. One step is 50 ms;
targets outside the joint limits are clipped. Skills: `reach ARM X Y Z [YAW]` moves an arm's tool point (between the
fingertips) along a straight line to a point with the gripper pointing down; `set_gripper ARM OPENING [STEPS]`;
`home ARM`. Success is the task's physical predicate (fruit in the bowl, or on the plate), judged after `robo done`
and a 10-step hold.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import numpy as np

from ... import config
from ...core.embodiment_spec import Budgets, Camera, Embodiment, Field, RewardSpec, Sensors, Skill, SkillArg
from ...workers.client import StdioWorker
from ..base import ActionSpec, Backend, G, StepInfo, groups_from_layout

WORKER = Path(__file__).with_name("worker.py")
SETUP = config.SUITES_DOCS
SIDES = ("right", "left")
JOINTS = [f"j{i}" for i in range(1, 7)]
NATIVE_W, NATIVE_H = 640, 360  # every camera image: the station's 640x360 crop of a 640x480 render
WAYPOINT_M = 0.02  # `reach` follows a straight line through IK waypoints this far apart
MAX_JOINT_STEP = 0.06  # rad per 50 ms step (1.2 rad/s; the YAM's own limit is 3 rad/s)
REACH_SETTLE = 6  # steps after the last waypoint, for the arm to catch up with its command
SKILL_CAP = 300  # steps a single skill call may run


class YamBackend(Backend):
    name = "yam"
    robot_kind = "bimanual"
    robot_name = "dual-yam"
    probe_success = False  # step() already returns the predicate
    proprioception = tuple(
        f"{s}_{f}" for s in SIDES for f in ("joint_pos", "gripper_open", "tcp_pos", "tcp_down_deg", "jaw_yaw_deg")
    )

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.max_steps = int(spec.get("max_steps", 1200))
        self.camera = str(spec.get("camera", "top"))
        self.goal = dict(spec.get("goal") or {})
        self.worker = StdioWorker("yam", config.sim_python("yam"), WORKER, setup=SETUP)
        layout = spec.get("layout") or {}
        self.meta = self.worker.call(
            "make",
            goal=self.goal,
            seed=int(spec.get("seed", 0)),
            jitter_m=float(layout.get("jitter_m", 0.03)),
            yaw_jitter_deg=float(layout.get("yaw_jitter_deg", 30.0)),
        )
        names = [f"{s}_{j}" for s in SIDES for j in [*JOINTS, "grip"]]
        doc = (
            "Absolute targets, Dream's YAM layout: the right arm's joints 1-6 (rad) and its gripper opening "
            "(0 closed, 1 open), then the left arm's. One step = 50 ms; joint targets are clipped to the limits."
        )
        self.action_spec = ActionSpec(names=names, low=self.meta["low"], high=self.meta["high"], doc=doc)
        self.cmd = self._home()
        self._state: dict | None = None
        self._tcp: dict[str, list[float]] = {}
        self._moved = "right"
        self.last_judge: dict | None = None

    # ---- simulator -------------------------------------------------------------------------------------------------
    def _home(self) -> dict[str, np.ndarray]:
        return {s: np.r_[np.zeros(6), 1.0] for s in SIDES}

    def reset(self, seed: int) -> None:
        self.meta = self.worker.call("reset", seed=int(seed))
        self.cmd = self._home()
        self._state = None

    def step(self, action: Any) -> StepInfo:
        a = self.action_spec.clip(action)
        new = {s: a[7 * i : 7 * i + 7].copy() for i, s in enumerate(SIDES)}
        moved = [s for s in SIDES if np.max(np.abs(new[s] - self.cmd[s])) > 1e-6]
        if moved:
            self._moved = moved[0]
        self.cmd = new
        r = self.worker.call("step", action=[float(x) for x in a])
        self._state = None
        return StepInfo(success=bool(r["success"]))

    def observe(self) -> dict:
        if self._state is None:
            self._state = self.worker.call("observe")
        return dict(self._state)

    def hold_action(self) -> list[float]:
        """Hold still: keep commanding the last joint targets and gripper openings."""
        return [float(x) for s in SIDES for x in self.cmd[s]]

    def metrics_point(self) -> list[float]:
        """The tool point of the arm that moved last (the physics probe's end-effector track)."""
        return list(self.observe()[f"{self._moved}_tcp_pos"])

    def render(self, width: int | None = None, height: int | None = None) -> np.ndarray:
        return self.worker.call("render", camera=self.camera, width=width, height=height)

    def camera_info(self, cameras: list[str]) -> list[dict]:
        return self.worker.call("camera_info", cameras=list(cameras), width=NATIVE_W, height=NATIVE_H)

    def success(self) -> bool:
        r = self.worker.call("success")
        self.last_judge = r.get("detail")
        return bool(r["success"])

    def close(self) -> None:
        self.worker.close()

    # ---- embodiment ------------------------------------------------------------------------------------------------
    def action_layout(self) -> list[G]:
        lay = []
        for s in SIDES:
            lay += [
                G(f"{s}_arm.joints", 6, "joint_pos", "rad", hold="last", initial=0.0, doc=f"{s} arm joints 1-6"),
                G(f"{s}_gripper", 1, "gripper", "opening", hold="last", initial=1.0, doc="0 closed, 1 open"),
            ]
        return lay

    def skills(self) -> list[str]:
        return ["reach", "set_gripper", "home"]

    def skill_specs(self) -> list[Skill]:
        arm = SkillArg("arm", "enum", choices=list(SIDES), doc="which arm (left and right as the top camera sees them)")
        return [
            Skill(
                "reach",
                [
                    arm,
                    SkillArg("x", "float", "m"),
                    SkillArg("y", "float", "m"),
                    SkillArg("z", "float", "m"),
                    SkillArg("yaw", "float", "deg", optional=True, doc="heading the fingers close along (mod 180)"),
                ],
                doc=(
                    "Move the arm's tool point (between the fingertips) along a straight line to (x, y, z), gripper "
                    f"pointing down, through inverse kinematics; at most {SKILL_CAP} steps per call. Reports the "
                    "distance left: an unreachable or blocked target is not reached."
                ),
            ),
            Skill(
                "set_gripper",
                [
                    arm,
                    SkillArg("opening", "float", doc="0 closed, 1 open"),
                    SkillArg("steps", "int", optional=True, default=10),
                ],
                doc="Open or close one gripper over STEPS steps while the arm holds; reports what its fingers touch.",
            ),
            Skill("home", [arm], doc="Move one arm back to its home pose (all joints at zero), gripper unchanged."),
        ]

    def embodiment(self) -> Embodiment:
        s = self.action_spec
        return Embodiment(
            name=self.robot_name,
            kind=self.robot_kind,
            action_groups=groups_from_layout(s, self.action_layout()),
            sensors=Sensors(
                cameras=[
                    Camera("top", "world", NATIVE_W, NATIVE_H, doc="over the robots, looking across the table"),
                    Camera("left", "wrist", NATIVE_W, NATIVE_H, doc="left wrist"),
                    Camera("right", "wrist", NATIVE_W, NATIVE_H, doc="right wrist"),
                ],
                proprioception=[Field(n) for n in self.proprioception],
            ),
            skills=self.skill_specs(),
            budgets=Budgets(max_steps=int(self.max_steps), max_skill_steps=SKILL_CAP),
            reward=RewardSpec(dense="sparse"),
            step_s=0.05,
            doc=s.doc,
        )

    def info_extra(self) -> dict:
        return {
            "goal": self.goal,
            "simulator": {"mujoco": self.meta.get("mujoco"), "dreamlabs": self.meta.get("dreamlabs")},
        }

    # ---- skills ----------------------------------------------------------------------------------------------------
    def start_skill(self, name: str, raw: list[str]) -> Generator[list[float], None, dict]:
        """Closed-loop skills: each yields one full action per step, which the episode server runs as an ordinary step.
        Arguments are checked here, before the first step."""
        args = [a.split("=", 1)[1] if "=" in a else a for a in raw]
        if name == "reach":
            if len(args) not in (4, 5):
                raise ValueError("reach ARM X Y Z [YAW]: ARM is left or right, X Y Z in metres, YAW in degrees")
            side, xyz = _arm(args[0]), [_num(v, "X Y Z") for v in args[1:4]]
            yaw = _num(args[4], "YAW") if len(args) == 5 else None
            return self._reach(side, np.asarray(xyz), yaw)
        if name == "set_gripper":
            if len(args) not in (2, 3):
                raise ValueError("set_gripper ARM OPENING [STEPS]: OPENING from 0 (closed) to 1 (open)")
            steps = int(_num(args[2], "STEPS")) if len(args) == 3 else 10
            return self._set_gripper(_arm(args[0]), float(np.clip(_num(args[1], "OPENING"), 0, 1)), max(1, steps))
        if name == "home":
            if len(args) != 1:
                raise ValueError("home ARM")
            return self._joint_move(_arm(args[0]), np.zeros(6))
        raise ValueError(f"unknown skill {name!r}; skills: reach, set_gripper, home")

    def _with(self, side: str, q: np.ndarray | None = None, grip: float | None = None) -> list[float]:
        cmd = {s: self.cmd[s].copy() for s in SIDES}
        if q is not None:
            cmd[side][:6] = q
        if grip is not None:
            cmd[side][6] = grip
        return [float(x) for s in SIDES for x in cmd[s]]

    def _reach(self, side: str, target: np.ndarray, yaw: float | None) -> Generator[list[float], None, dict]:
        start = np.asarray(self.observe()[f"{side}_tcp_pos"], dtype=float)
        n = max(1, int(np.ceil(np.linalg.norm(target - start) / WAYPOINT_M)))
        q, steps, sol = self.cmd[side][:6].copy(), 0, {}
        for k in range(1, n + 1):
            p = start + (target - start) * k / n
            sol = self.worker.call("ik", side=side, pos=[float(x) for x in p], yaw_deg=yaw, q0=[float(x) for x in q])
            goal = np.asarray(sol["q"], dtype=float)
            while np.max(np.abs(goal - q)) > 1e-4:
                if steps >= SKILL_CAP:
                    return self._reach_result(side, target, sol, steps, stopped="step cap")
                q = q + np.clip(goal - q, -MAX_JOINT_STEP, MAX_JOINT_STEP)
                yield self._with(side, q=q)
                steps += 1
        for _ in range(REACH_SETTLE):
            yield self._with(side, q=q)
            steps += 1
        return self._reach_result(side, target, sol, steps)

    def _reach_result(self, side: str, target: np.ndarray, sol: dict, steps: int, stopped: str = "") -> dict:
        st = self.observe()
        tcp = np.asarray(st[f"{side}_tcp_pos"], dtype=float)
        dist = float(np.linalg.norm(tcp - target))
        out = {
            "arm": side,
            "reached": dist < 0.01,
            "distance_m": round(dist, 4),
            "tcp_pos": st[f"{side}_tcp_pos"],
            "tcp_down_deg": st[f"{side}_tcp_down_deg"],
            "steps": steps,
        }
        if sol.get("pos_err_m", 0) > 0.01:
            out["unreachable"] = f"inverse kinematics misses the target by {sol['pos_err_m']} m (joint limits)"
        if stopped:
            out["stopped"] = stopped
        return out

    def _set_gripper(self, side: str, opening: float, steps: int) -> Generator[list[float], None, dict]:
        g0 = float(self.cmd[side][6])
        for i in range(1, min(steps, SKILL_CAP) + 1):
            yield self._with(side, grip=g0 + (opening - g0) * i / steps)
        for _ in range(5):
            yield self._with(side, grip=opening)
        st = self.observe()
        return {"arm": side, "gripper_open": st[f"{side}_gripper_open"], "touching": st[f"{side}_touching"]}

    def _joint_move(self, side: str, goal: np.ndarray) -> Generator[list[float], None, dict]:
        q, steps = self.cmd[side][:6].copy(), 0
        while np.max(np.abs(goal - q)) > 1e-4 and steps < SKILL_CAP:
            q = q + np.clip(goal - q, -MAX_JOINT_STEP, MAX_JOINT_STEP)
            yield self._with(side, q=q)
            steps += 1
        for _ in range(REACH_SETTLE):
            yield self._with(side, q=q)
        st = self.observe()
        return {"arm": side, "joint_pos": st[f"{side}_joint_pos"], "tcp_pos": st[f"{side}_tcp_pos"]}


def _arm(v: str) -> str:
    if v not in SIDES:
        raise ValueError(f"ARM must be left or right, got {v!r}")
    return v


def _num(v: str, what: str) -> float:
    try:
        x = float(v)
    except ValueError:
        raise ValueError(f"{what} must be numbers, got {v!r}") from None
    if not np.isfinite(x):
        raise ValueError(f"{what} must be finite")
    return x


# ---- reference solution -------------------------------------------------------------------------------------------
GRASP_DZ = 0.0  # tool point at the fruit's centre height
PRE_DZ = 0.12  # approach from this far above
CARRY_Z = 0.95  # carry height (the table is at 0.76; the bowl's rim at about 0.82)
DROP_DZ = {"in_bowl": 0.11, "on_plate": 0.06}  # release this far above the container's base


def oracle_main(env: str) -> None:
    """Pick the task's fruit with the nearer arm and put it where the goal says, using only the public skills; the
    object and container positions come from the privileged state the reference solution's token unlocks."""
    from ...agent_cli import _send

    def skill(*args: Any) -> dict:
        r = _send({"op": "skill", "name": args[0], "args": [str(a) for a in args[1:]]})
        if not r.get("ok"):
            raise SystemExit(f"oracle: {r.get('error')}")
        return r["result"]

    info = _send({"op": "info"})
    goal = (info.get("result") or {}).get("goal") or {}
    st = _send({"op": "observe"})["result"]["state"]
    obj, kind = goal["object"], goal["kind"]
    target = np.asarray(st["bowl_pos" if kind == "in_bowl" else "plate_pos"], dtype=float)
    p = np.asarray(st[f"{obj}_pos"], dtype=float)
    side = "left" if p[0] > 0 else "right"
    yaw = (st["banana_axis_yaw_deg"] + 90.0) % 180.0 if obj == "banana" else None
    yaw_args = [round(yaw, 1)] if yaw is not None else []
    skill("set_gripper", side, 1.0, 5)
    skill("reach", side, p[0], p[1], p[2] + PRE_DZ, *yaw_args)
    skill("reach", side, p[0], p[1], p[2] + GRASP_DZ, *yaw_args)
    skill("set_gripper", side, 0.0, 12)
    skill("reach", side, p[0], p[1], CARRY_Z, *yaw_args)
    skill("reach", side, target[0], target[1], CARRY_Z, *yaw_args)
    skill("reach", side, target[0], target[1], target[2] + DROP_DZ[kind], *yaw_args)
    skill("set_gripper", side, 1.0, 10)
    skill("reach", side, target[0], target[1], CARRY_Z, *yaw_args)
    skill("home", side)
    _send({"op": "done", "text": f"oracle: {obj} {kind.replace('_', ' ')}"})
