"""RoboCasa simulation worker. Runs inside the separate RoboCasa virtualenv (robosuite 1.5 + robocasa + MuJoCo 3.3.1),
because RoboCasa's pinned dependencies conflict with the main robouse environment (robosuite 1.4 for LIBERO).

The robouse `robocasa` backend (robocasa.py) starts this script as a subprocess and talks to it over stdin/stdout:
one JSON request per line, one JSON response per line; a `render` response is followed by the raw RGB bytes.
Only numpy, robosuite and robocasa are imported here (never the robouse package). A scenario with a `liquid` entry
loads physics/liquid/ by path (scenario.load_liquid); scenario plugins come from $ROBOUSE_ROBOCASA_PLUGINS.
A scenario episode may also write a researcher-only physical-state trace (state_trace.py, `trace_start`) into its run
folder; it only reads simulator state and never reaches a reply the policy sees.
"""

from __future__ import annotations

import copy
import json
import os

import numpy as np

STEP_M = 0.02  # metres per action unit per step (world frame)
OSC_MAX = 0.05  # robosuite OSC_POSE output_max for position (m per step at input 1)
LEAD_M = 0.05
ROT_STEP = 0.1  # rad of hand rotation per action unit per step (scenario EEF control)
LEAD_RAD = 0.3  # the orientation target stays within this angle of the hand
JOINT_STEP = 0.2  # rad that 1.0 on a joint delta asks for (scenario joint control; robosuite's default is 0.05)
JOINT_KP = 150.0  # joint stiffness: OSC_POSE's kp (robosuite's JOINT_POSITION default is 50)


def _load_scenario():
    """scenario.py next to this file (the worker runs without its folder on sys.path)."""
    import importlib.util
    import sys

    name = "robouse_robocasa_scenario"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(__file__), "scenario.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def _load_state_trace():
    """state_trace.py next to this file (the physical-state trace writer), loaded by path like scenario.py."""
    import importlib.util
    import sys

    name = "robouse_robocasa_state_trace"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(__file__), "state_trace.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def _rotvec(R):
    """Axis-angle vector of a rotation matrix."""
    c = np.clip((np.trace(R) - 1) / 2, -1, 1)
    a = np.arccos(c)
    if a < 1e-6:
        return np.zeros(3)
    if np.pi - a < 1e-4:  # a half turn: the antisymmetric part vanishes; take the axis from the symmetric part
        axis = np.sqrt(np.clip((np.diag(R) + 1) / 2, 0.0, None))
        i = int(np.argmax(axis))
        for j in range(3):
            if j != i and R[i, j] < 0:
                axis[j] = -axis[j]
        return axis / np.linalg.norm(axis) * a
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * np.sin(a))
    return v * a


def _rot(axis, ang):
    axis = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K


def _quat_to_mat(q_xyzw):
    x, y, z, w = q_xyzw
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _assets_root() -> str:
    import robocasa.models

    return os.path.abspath(robocasa.models.assets_root)


def _relative_paths(ep_meta: dict) -> dict:
    """Object model paths in an ep_meta, made relative to RoboCasa's asset root (objects/lightwheel/<cat>/<model>/model.xml),
    so a recorded layout does not depend on where RoboCasa is installed."""
    root = _assets_root()
    S = _load_scenario()
    for c in ep_meta.get("object_cfgs", []):
        info = c.get("info") or {}
        p = info.get("mjcf_path")
        if isinstance(p, str):
            custom = S.custom_model_id(p)
            if custom:
                info["mjcf_path"] = custom
                if info.get("groups") == p:
                    info["groups"] = custom
                c["obj_groups"] = custom
                ep_meta["robouse_custom_object_version"] = S.CUSTOM_OBJECT_VERSION
                continue
            p = p.replace("\\", "/")
            if os.path.isabs(p):
                p = os.path.relpath(p, root) if p.startswith(root + os.sep) else "objects/" + p.split("/objects/")[-1]
            info["mjcf_path"] = p
    return ep_meta


def _resolve_paths(ep_meta: dict) -> dict:
    """The inverse of _relative_paths: absolute object model paths under this machine's RoboCasa asset root."""
    root = _assets_root()
    for c in ep_meta.get("object_cfgs", []):
        info = c.get("info") or {}
        p = info.get("mjcf_path")
        if isinstance(p, str) and p.startswith("custom/"):
            info["mjcf_path"] = _load_scenario().model_path(p)
            c["obj_groups"] = info["mjcf_path"]
            continue
        if isinstance(p, str) and not os.path.isabs(p):
            full = os.path.join(root, p)
            if not os.path.exists(full):
                raise FileNotFoundError(f"RoboCasa object model {p} is not installed under {root}")
            info["mjcf_path"] = full
    return ep_meta


class Worker:
    def __init__(self):
        self.env = None
        self.scenario = None  # the spec, in scenario mode
        self.control = "eef"
        self.monitors = None
        self.nstep = 0
        self.tracer = None  # the physical-state trace, when the backend started one (trace_start)

    # ---- setup ---------------------------------------------------------------------------------------------------
    def make(
        self,
        env_name: str,
        layout: int,
        style: int,
        seed: int,
        tool: str = "down",
        kwargs: dict | None = None,
        ep_meta: dict | None = None,
    ) -> dict:
        import random

        import robocasa  # noqa: F401  (registers the kitchen environments)

        random.seed(int(seed))  # some RoboCasa placement code draws from the global generators
        np.random.seed(int(seed))
        import robosuite
        from robosuite.controllers import load_composite_controller_config
        from robosuite.environments.base import REGISTERED_ENVS

        # Only the lightwheel object registry is installed (see docs/suites/robocasa.md); object groups that exist only in
        # the objaverse registry are swapped for a lightwheel category of the same use.
        base = REGISTERED_ENVS[env_name]
        swap = {"mug": "glass_cup", "pan": "saucepan"}

        def _get_obj_cfgs(env_self):
            cfgs = base._get_obj_cfgs(env_self)
            for c in cfgs:
                g = c.get("obj_groups")
                if isinstance(g, str) and g in swap:
                    c["obj_groups"] = swap[g]
                # containers to nest an object in come from objaverse only; place the object directly instead
                c.get("placement", {}).pop("try_to_place_in", None)
            return cfgs

        def _load_model(env_self, attempt_num=1):
            # RoboCasa samples where counter appliances (a kettle, a toaster) go, and the draw is not reproducible across
            # processes even with the seed and PYTHONHASHSEED fixed; an episode can record the placements to restore
            base._load_model(env_self, attempt_num)
            fixed = (getattr(env_self, "_ep_meta", None) or {}).get("robouse_fixture_placements") or {}
            if fixed:
                import robosuite.utils.transform_utils as T

                for name, (pos, quat) in fixed.items():
                    obj = env_self.fixtures[name]
                    obj.set_pos(pos)
                    obj.set_euler(T.mat2euler(T.quat2mat(T.convert_quat(np.asarray(quat), "xyzw"))))
                    env_self.fxtr_placements[name] = (pos, quat, obj)

        patched = f"RobouseLW{env_name}"
        if patched not in REGISTERED_ENVS:
            type(patched, (base,), {"_get_obj_cfgs": _get_obj_cfgs, "_load_model": _load_model})
        self.env = robosuite.make(
            patched,
            robots="PandaOmron",
            controller_configs=load_composite_controller_config(controller=None, robot="PandaOmron"),
            has_renderer=False,
            has_offscreen_renderer=True,
            use_camera_obs=False,
            ignore_done=True,
            layout_ids=[int(layout)],
            style_ids=[int(style)],
            obj_registries=("lightwheel",),
            seed=int(seed),
            translucent_robot=False,
            **(kwargs or {}),
        )
        if ep_meta:  # replay a recorded episode layout exactly (RoboCasa's own demo-replay mechanism)
            self.env.set_ep_meta(_resolve_paths(ep_meta))
        self.obs = self.env.reset()
        self.grip = -1.0
        self.adim = self.env.action_spec[0].shape[0]
        R0 = self._eef_R()
        if tool == "forward":  # pitch the hand so the fingers point along the robot's forward direction
            fwd = self._base_R()[:, 0]
            left = np.cross([0, 0, 1], fwd)
            self.target_R = _rot(left, -np.pi / 2) @ R0 if R0[:, 2] @ fwd < 0.5 else R0
        else:
            self.target_R = R0
        self.target_p = np.asarray(self.obs["robot0_eef_pos"], dtype=float).copy()
        for _ in range(60):  # part of the reset: turn to the tool orientation, then hold it
            self._send()
        self.target_p = np.asarray(self.obs["robot0_eef_pos"], dtype=float).copy()
        return {"lang": self.env.get_ep_meta().get("lang", ""), "cameras": list(self.env.sim.model.camera_names)}

    def make_scenario(
        self, spec: dict, seed: int, control: str = "eef", ep_meta: dict | None = None, settle_steps: int = 60
    ) -> dict:
        """A kitchen built from a scenario spec (scenario.py). `control`: "eef" (hand target servo, position and
        orientation) or "joint" (robosuite JOINT_POSITION on the arm, delta targets). The objects settle for
        `settle_steps` with the arm holding still; the result reports how far each object moved over the last 10."""
        import random

        import robocasa  # noqa: F401
        import robosuite
        from robosuite.controllers import load_composite_controller_config

        if control not in ("eef", "joint"):
            raise ValueError(f"control must be eef or joint, not {control!r}")
        self.trace_finish()  # a trace belongs to one episode
        S = _load_scenario()
        S.load_plugins()  # scene-specific predicates and liquid containers ($ROBOUSE_ROBOCASA_PLUGINS)
        compute_api = S.load_liquid("compute")
        compute = compute_api.validate_runtime(spec)
        random.seed(int(seed))
        np.random.seed(int(seed))
        if spec.get("liquid"):
            liquid_scene = S.load_liquid("scene")

            previous = getattr(getattr(self, "env", None), "_liquid_scene", None)
            if previous is not None:
                previous.coupling.uninstall()
                previous.fluid.close()
                self.env._liquid_scene = None
            liquid_scene.enable_surface(S, configured_only=True)
        name = S.make_class(spec)
        cfg = load_composite_controller_config(controller=None, robot="PandaOmron")
        if control == "joint":
            cfg["body_parts"]["right"] = dict(
                type="JOINT_POSITION",
                input_type="delta",
                input_max=1,
                input_min=-1,
                output_max=JOINT_STEP,
                output_min=-JOINT_STEP,
                kp=JOINT_KP,
                damping_ratio=1,
                impedance_mode="fixed",
                kp_limits=[0, 300],
                damping_ratio_limits=[0, 10],
                qpos_limits=None,
                interpolation=None,
                ramp_ratio=0.2,
                gripper={"type": "GRIP"},
            )
        k = spec["kitchen"]
        self.env = robosuite.make(
            name,
            robots="PandaOmron",
            controller_configs=cfg,
            has_renderer=False,
            has_offscreen_renderer=True,
            use_camera_obs=False,
            ignore_done=True,
            layout_ids=[S.layout_id(k)],
            style_ids=[int(k["style"])],
            # the on-screen viewer's camera presets are keyed by stock layout number; images are rendered offscreen
            **({"renderer": "mujoco"} if k.get("blueprint") else {}),
            obj_registries=tuple(spec.get("obj_registries") or ("lightwheel",)),
            seed=int(seed),
            translucent_robot=False,
        )
        setattr(self.env, S.CUSTOM_ATTR, {})
        if ep_meta:
            resolved = _resolve_paths(copy.deepcopy(ep_meta))
            for obj_cfg in resolved.get("object_cfgs", []):
                path = (obj_cfg.get("info") or {}).get("mjcf_path")
                custom = S.custom_model_id(path) if isinstance(path, str) else None
                if custom:
                    # Upstream rebases info.mjcf_path onto its own assets tree.
                    # An explicit model draw preserves the external bundle path; RoboCasa reverse-looks it up in
                    # OBJ_CATEGORIES (a bare ValueError otherwise), so register it as a fresh build does.
                    S.register_custom_model(custom, path, self.env.obj_registries)
                    # re-applied before every placement attempt (scenario.py _create_objects)
                    getattr(self.env, S.CUSTOM_ATTR).setdefault(obj_cfg.get("name"), path)
                    obj_cfg.pop("info")
                    obj_cfg["obj_groups"] = path
                    obj_cfg.pop("exclude_obj_groups", None)
            self.env.set_ep_meta(resolved)
        self.obs = self.env.reset()
        # RoboCasa's ep_meta fixes the kitchen, the object models and the robot base but samples object placements anew
        # on every load; a recorded scene also pins each object's pose after reset (and the fixture placements, in
        # scenario.py), so every reset of a frozen scenario is the same scene
        sim = self.env.sim
        poses = (ep_meta or {}).get("robouse_object_poses") or {}
        for n, q in poses.items():
            if n in self.env.objects:
                sim.data.set_joint_qpos(self.env.objects[n].joints[0], np.asarray(q, dtype=float))
                sim.data.set_joint_qvel(self.env.objects[n].joints[0], np.zeros(6))
        if poses:
            sim.forward()
        self.reset_poses = {
            n: [float(v) for v in sim.data.get_joint_qpos(o.joints[0])] for n, o in self.env.objects.items()
        }
        self.scenario, self.control = spec, control
        self.base0 = S.base_pose(self.env)  # the parked base, for the drift evidence (ROBOT_BASE_VERSION)
        self.base_drift = {"xy_m": 0.0, "z_m": 0.0, "yaw_deg": 0.0}
        self.split = dict(self.env.robots[0].composite_controller._action_split_indexes)
        self.adim = self.env.action_spec[0].shape[0]
        self.grip = -1.0
        self.target_p = np.asarray(self.obs["robot0_eef_pos"], dtype=float).copy()
        self.target_R = self._eef_R()
        names = list(self.env.objects)
        before = None
        for i in range(int(settle_steps)):
            if i == int(settle_steps) - 10:
                before = {n: self._body_pos(n) for n in names}
            self._hold()
        moved = {n: round(float(np.linalg.norm(self._body_pos(n) - before[n])), 4) for n in names} if before else {}
        cam = S.after_reset(self.env, spec)
        if spec.get("liquid"):
            liquid_scene.attach_worker(self.env, spec["liquid"])
            compute_api.validate_solver(compute, self.env._liquid_scene.fluid)
        self.monitors = S.Monitors(spec)
        self.env.robouse_monitors = self.monitors  # history for the `fired` predicate
        self.nstep = 0
        self._track_base()  # settling included
        return {
            "lang": self.env.get_ep_meta().get("lang", ""),
            "cameras": list(self.env.sim.model.camera_names),
            "camera_2": cam,
            "settle_motion": moved,
            **({"compute": compute} if compute else {}),
            "robot_base": self.robot_base(),
            "objects": {n: [round(float(v), 4) for v in self._body_pos(n)] for n in names},
        }

    def _track_base(self) -> None:
        p, yaw = _load_scenario().base_pose(self.env)
        p0, yaw0 = self.base0
        dyaw = abs((yaw - yaw0 + np.pi) % (2 * np.pi) - np.pi)
        bd = self.base_drift
        bd["xy_m"] = max(bd["xy_m"], float(np.linalg.norm(p[:2] - p0[:2])))
        bd["z_m"] = max(bd["z_m"], float(abs(p[2] - p0[2])))
        bd["yaw_deg"] = max(bd["yaw_deg"], float(np.degrees(dyaw)))

    def robot_base(self) -> dict:
        """How the base was held (scenario.py ROBOT_BASE_VERSION) and the largest drift of its pose from where it
        was parked, over settling and every step since (private evidence; the agent sees robot_base_pos only)."""
        S = _load_scenario()
        return {"version": S.ROBOT_BASE_VERSION if S.robot_base_mode(self.scenario) == "locked" else "1.0.0",
                "mode": S.robot_base_mode(self.scenario),
                "max_drift": {k: round(v, 5) for k, v in self.base_drift.items()}}

    def _body_pos(self, name: str) -> np.ndarray:
        return np.array(self.env.sim.data.body_xpos[self.env.obj_body_id[name]], dtype=float)

    def _hold(self) -> None:
        if self.control == "joint":
            self._send_joint(np.zeros(7))
        else:
            self._send()

    def _send_joint(self, dq) -> None:
        full = np.zeros(self.adim)
        a, b = self.split["right"]
        full[a:b] = np.clip(np.asarray(dq, dtype=float), -1, 1)
        full[self.split["right_gripper"][0]] = self.grip
        full[-1] = -1.0  # arm mode (base does not move)
        self.obs, _, _, _ = self.env.step(full)

    def joint_pos(self) -> list[float]:
        return [float(v) for v in self.env.robots[0]._joint_positions]

    def joint_limits(self) -> list[list[float]]:
        m = self.env.sim.model
        return [[float(a), float(b)] for a, b in (m.jnt_range[m.joint_name2id(j)] for j in self.env.robots[0].robot_joints)]

    def monitor_events(self) -> dict:
        """The scenario's monitors (hidden from the agent) and whether the goal holds now."""
        out = {"events": self.monitors.events(self.env, self.nstep) if self.monitors else [], "steps": self.nstep}
        try:
            out["goal"] = bool(self.env._check_success())
        except Exception as e:  # recorded, never read as "goal not met"
            out["goal_error"] = f"{type(e).__name__}: {e}"[:300]
        if self.scenario is not None:
            out["robot_base"] = self.robot_base()
        return out

    def ep_meta(self) -> dict:
        meta = json.loads(
            json.dumps(self.env.get_ep_meta(), default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
        )
        if self.scenario is not None:
            meta["robouse_object_poses"] = self.reset_poses
            meta["robouse_fixture_placements"] = {
                name: [[float(v) for v in pos], [float(v) for v in quat]]
                for name, (pos, quat, _) in self.env.fxtr_placements.items()
            }
        return _relative_paths(meta)

    # ---- helpers -------------------------------------------------------------------------------------------------
    def _pos(self, name: str):
        m, d = self.env.sim.model, self.env.sim.data
        for kind, getter in (
            ("geom", lambda i: d.geom_xpos[i]),
            ("body", lambda i: d.xpos[i]),
            ("site", lambda i: d.site_xpos[i]),
        ):
            try:
                i = getattr(m, f"{kind}_name2id")(name)
            except Exception:
                continue
            if i is not None and i >= 0:
                return [float(v) for v in getter(i)]
        return None

    def _geoms_containing(self, sub: str):
        m = self.env.sim.model
        return [n for n in m.geom_names if n and sub in n]

    def _handle_pos(self, fx):
        for name in (
            f"{fx.name}_door_handle_reg_main",
            f"{fx.name}_handle_reg_main",
            fx.handle_name,
            f"{fx.name}_door_handle_main",
        ):
            p = self._pos(name)
            if p is not None:
                return p
        return None

    def _joint_geoms(self, joint: str, prefer: str = "") -> list[int]:
        """Collision geoms of the body a joint moves (and its child bodies); those whose name ends with `prefer` if any."""
        import mujoco

        m = self.env.sim.model._model
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, joint)
        if j < 0:
            return []
        b = int(m.jnt_bodyid[j])

        def under(k):
            while k > 0:
                if k == b:
                    return True
                k = int(m.body_parentid[k])
            return False

        gs = [g for g in range(m.ngeom) if m.geom_contype[g] and under(int(m.geom_bodyid[g]))]
        named = [g for g in gs if prefer and (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "").endswith(prefer)]
        return named or gs

    def _geoms_box(self, gs: list[int]):
        """World axis-aligned bounding box (lo, hi) of geoms."""
        m, d = self.env.sim.model._model, self.env.sim.data._data
        pts = []
        for g in gs:
            R = d.geom_xmat[g].reshape(3, 3)
            c = d.geom_xpos[g] + R @ m.geom_aabb[g][:3]
            e = np.abs(R) @ m.geom_aabb[g][3:]
            pts += [c - e, c + e]
        pts = np.asarray(pts)
        return pts.min(0), pts.max(0)

    def _eef_R(self):
        return _quat_to_mat(self.obs["robot0_eef_quat"])

    def _send(self) -> None:
        """One control step toward the commanded gripper target (position self.target_p, orientation self.target_R)."""
        d_world = self.target_p - np.asarray(self.obs["robot0_eef_pos"], dtype=float)
        R_err = self.target_R @ self._eef_R().T  # world-frame rotation from current to target
        w_world = _rotvec(R_err)
        Rb = self._base_R()
        full = np.zeros(self.adim)
        full[0:3] = np.clip(Rb.T @ np.asarray(d_world) / OSC_MAX, -1, 1)
        full[3:6] = np.clip(Rb.T @ w_world / 0.5, -1, 1)
        full[6] = self.grip
        full[-1] = -1.0  # arm mode (base does not move)
        self.obs, _, _, _ = self.env.step(full)

    def _base_R(self):
        return _quat_to_mat(self.obs["robot0_base_quat"])  # robosuite quats are xyzw

    # ---- stepping ------------------------------------------------------------------------------------------------
    def _set_grip(self, g: float) -> None:
        """0 keeps the fingers, > 0 closes, -f opens to fraction f."""
        if g > 1e-3:
            self.grip = 1.0
        elif g < -1e-3:
            self.grip = float(1.0 - 2.0 * min(1.0, -g))

    def step(self, action=None, pose: dict | None = None) -> dict:
        """One control step. Task mode: [DX, DY, DZ, GRIP]. Scenario EEF: [DX, DY, DZ, DROLL, DPITCH, DYAW, GRIP] (a 4-entry
        action from a skill has no rotation); `pose` {pos, R} instead moves the targets one full unit toward that pose.
        Scenario joint: [DQ1..DQ7, GRIP] (a 4-entry action from a skill only sets the gripper)."""
        a = np.asarray(action if action is not None else [], dtype=float)
        if len(a) in (4, 7, 8):
            self._set_grip(float(a[-1]))
        if self.control == "joint":
            self._send_joint(a[:7] if len(a) == 8 else np.zeros(7))
        else:
            hand = np.asarray(self.obs["robot0_eef_pos"], dtype=float)
            R = self._eef_R()
            if pose is not None:
                d = np.asarray(pose["pos"], dtype=float) - self.target_p
                n = float(np.linalg.norm(d))
                tgt = self.target_p + (d if n <= STEP_M else d * (STEP_M / n))
                w = _rotvec(np.asarray(pose["R"], dtype=float).reshape(3, 3) @ self.target_R.T)
                ang = float(np.linalg.norm(w))
                if ang > ROT_STEP:
                    w = w * (ROT_STEP / ang)
            else:
                tgt = self.target_p + np.clip(a[:3], -1, 1) * STEP_M
                w = np.clip(a[3:6], -1, 1) * ROT_STEP if len(a) == 7 else np.zeros(3)
            off = tgt - hand
            n = float(np.linalg.norm(off))
            if n > LEAD_M:  # the target stays within 5 cm of the hand so a blocked arm does not wind up
                tgt = hand + off * (LEAD_M / n)
            self.target_p = tgt
            if float(np.linalg.norm(w)) > 0:
                tR = _rot(w, float(np.linalg.norm(w))) @ self.target_R
                lead = _rotvec(tR @ R.T)
                ang = float(np.linalg.norm(lead))
                if ang > LEAD_RAD:  # same for the orientation target
                    tR = _rot(lead, LEAD_RAD) @ R
                self.target_R = tR
            self._send()
        out = {"success": bool(self.env._check_success())}
        if self.monitors is not None:
            self.nstep += 1
            self._track_base()
            self.monitors.update(self.env, self.nstep)
            if self.tracer is not None:  # reads the state this control produced; changes nothing
                self.tracer.record(self.nstep)
            out["hand_pos"] = [float(v) for v in self.obs["robot0_eef_pos"]]
            out["eef_quat"] = [float(v) for v in self.obs["robot0_eef_quat"]]
            out["joint_pos"] = self.joint_pos()
        return out

    def success(self) -> dict:
        return {"success": bool(self.env._check_success())}

    # ---- physical-state trace (researcher-only; state_trace.py) -----------------------------------------------------
    def trace_start(self, path: str, stride: int = 1, source: dict | None = None) -> dict:
        """Start the episode's physical-state trace at `path` (in the run folder) with the current state (the reset
        state when called right after make_scenario). A trace that cannot start is reported, never raised: tracing
        never stops an episode."""
        self.trace_finish()
        if self.scenario is None:
            return {"ok": False, "error": "a state trace needs a scenario episode"}
        T, S = _load_state_trace(), _load_scenario()
        env = self.env

        def burners(key):
            fx = env.refs[key]
            if not hasattr(fx, "is_burner_on"):
                return None
            return {loc: bool(fx.is_burner_on(env=env, burner_loc=loc))
                    for loc, j in fx.knob_joints.items() if j is not None}

        def robot():
            o = self.obs
            return {"eef": [round(float(v), T.PRECISION) for v in o["robot0_eef_pos"]],
                    "grip": round(float(np.clip(np.mean(np.abs(o["robot0_gripper_qpos"])) / 0.04, 0, 1)), 3)}

        hooks = {
            "power": lambda key: bool(S.p_fixture_on(env, {"fixture": key})),
            "burners": burners,
            "grasped": lambda name: bool(S.p_grasped(env, {"obj": name})),
            "robot": robot,
            "goal": lambda: bool(env._check_success()),
        }
        try:
            self.tracer = T.Tracer(env, self.scenario, path, self.control, hooks, stride=stride, source=source)
            self.tracer.record(self.nstep, "reset" if self.nstep == 0 else "control")
        except Exception as e:  # reported to the backend; the episode runs untraced
            self.tracer = None
            return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        if self.tracer.failed:
            err, self.tracer = self.tracer.failed, None
            return {"ok": False, "error": err}
        return {"ok": True, "format": T.FORMAT, "version": T.VERSION, "file": os.path.basename(path)}

    def trace_phase(self, phase: str) -> bool:
        """Label the following records (`settle`: the still steps after `robo done`)."""
        if self.tracer is not None:
            self.tracer.phase = str(phase)
        return self.tracer is not None

    def trace_finish(self) -> dict | None:
        """Write the final state and close the trace (idempotent)."""
        tracer, self.tracer = getattr(self, "tracer", None), None
        return tracer.finish() if tracer is not None else None

    def physics_digest(self) -> dict:
        """The fingerprint every trace record carries (qpos and qvel), for checking that tracing changes nothing."""
        return {"digest": _load_state_trace().digest(self.env.sim.data._data), "steps": self.nstep}

    def close(self) -> None:
        self.trace_finish()

    # ---- observation ---------------------------------------------------------------------------------------------
    def observe(self, features: list[str]) -> dict:
        o, env = self.obs, self.env
        st = {
            "hand_pos": [round(float(v), 4) for v in o["robot0_eef_pos"]],
            "hand_target": [round(float(v), 4) for v in self.target_p],
            "gripper_open": round(float(np.clip(np.mean(np.abs(o["robot0_gripper_qpos"])) / 0.04, 0, 1)), 3),
            "robot_base_pos": [round(float(v), 4) for v in o["robot0_base_pos"]],
            "robot_forward": [round(float(v), 4) for v in self._base_R()[:, 0]],
        }
        if self.scenario is not None:  # the same robot state in both control modes
            st["eef_quat"] = [round(float(v), 5) for v in o["robot0_eef_quat"]]  # x, y, z, w
            st["joint_pos"] = [round(v, 4) for v in self.joint_pos()]
            if self.control == "joint":
                st.pop("hand_target")
        r = lambda v: None if v is None else [round(float(x), 4) for x in v]
        for f in features:
            if f == "object":
                st["object_pos"] = r(o["obj_pos"])
                ob = env.objects["obj"]
                cat = ""
                for c in getattr(env, "object_cfgs", []):
                    if c.get("name") == "obj":
                        cat = c.get("info", {}).get("cat", "")
                st["object_category"] = cat
                st["object_size"] = r(getattr(ob, "size", [0, 0, 0]))
            elif f in ("sink", "cabinet"):
                fx = env.sink if f == "sink" else env.cab
                ints = fx.get_int_sites(relative=False)
                p0, px, py, pz = (np.asarray(v, dtype=float) for v in list(ints.values())[0][:4])
                centre = p0 + ((px - p0) + (py - p0) + (pz - p0)) / 2
                key = "sink_basin" if f == "sink" else "cabinet_interior"
                st[f"{key}_center"] = r(centre)
                st[f"{key}_half_size"] = r(
                    np.abs(np.array([np.linalg.norm(px - p0), np.linalg.norm(py - p0), np.linalg.norm(pz - p0)])) / 2
                )
                st[f"{key}_bottom_z"] = round(float(p0[2]), 4)
                if f == "cabinet":
                    st["cabinet_interior_top_z"] = round(float(pz[2]), 4)
                    st["cabinet_front_normal"] = r(_quat_to_mat(np.r_[fx.quat[1:], fx.quat[0]])[:, 1] * -1)
            elif f == "faucet":
                import mujoco

                m, d = env.sim.model._model, env.sim.data._data
                pre = env.sink.naming_prefix
                hs = env.sink.get_handle_state(env=env)
                j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"{pre}handle_joint")
                lo, hi = self._geoms_box(self._joint_geoms(f"{pre}handle_joint", "handle_main"))
                st["faucet_handle_pos"] = r((lo + hi) / 2)
                st["faucet_handle_size"] = r(hi - lo)
                st["faucet_handle_hinge_pos"] = r(d.xanchor[j])
                st["faucet_handle_hinge_axis"] = r(d.xaxis[j])
                st["faucet_handle_angle"] = round(float(hs.get("handle_joint", 0.0)), 3)
                st["water_on"] = bool(hs.get("water_on", False))
            elif f == "coffee":
                cm = env.coffee_machine
                names = [f"{cm.naming_prefix}{n}" for n in cm._start_button_names]
                pts = [self._pos(n) for n in names]
                pts = [p for p in pts if p is not None]
                st["coffee_button_pos"] = r(np.mean(pts, axis=0)) if pts else None
                st["coffee_machine_on"] = bool(cm.get_state()["turned_on"])
            elif f == "microwave":
                mw = env.microwave
                st["microwave_start_button_pos"] = r(self._pos(f"{mw.name}_start_button"))
                st["microwave_stop_button_pos"] = r(self._pos(f"{mw.name}_stop_button"))
                st["microwave_on"] = bool(mw.get_state()["turned_on"])
            elif f == "toaster":
                ts = env.toaster
                sp = 0
                for pair in range(len(ts.get_state(env).keys())):
                    if ts.check_slot_contact(env, "obj", pair):
                        sp = pair
                        break
                lo, hi = self._geoms_box(self._joint_geoms(ts._joint_names[f"lever_{sp}"], "handle"))
                st["toaster_lever_pos"] = r((lo + hi) / 2)
                st["toaster_lever_size"] = r(hi - lo)
                st["toaster_lever_pressed"] = round(float(ts.get_state(env, slot_pair=sp)["lever"]), 3)
                st["toaster_on"] = bool(ts.get_state(env, slot_pair=sp)["turned_on"])
            elif f == "kettle":
                k = env.electric_kettle
                ks = k.get_state(env)
                for key, joint in (("switch", "switch"), ("lid", "lid")):
                    lo, hi = self._geoms_box(self._joint_geoms(k._joint_names[joint], "_main"))
                    st[f"kettle_{key}_pos"] = r((lo + hi) / 2)
                    st[f"kettle_{key}_size"] = r(hi - lo)
                import mujoco

                m, d = env.sim.model._model, env.sim.data._data
                j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, k._joint_names["lid"])
                st["kettle_pos"] = r(k.pos)
                st["kettle_lid_hinge_pos"] = r(d.xanchor[j])
                st["kettle_lid_hinge_axis"] = r(d.xaxis[j])
                st["kettle_lid_open"] = round(float(ks.get("lid", 0.0)), 3)
                st["kettle_on"] = bool(ks.get("turned_on", False))
            elif f == "stove":
                import mujoco

                m, d = env.sim.model._model, env.sim.data._data
                pre = env.stove.naming_prefix
                j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"{pre}knob_{env.knob}_joint")
                ridge = self._joint_geoms(f"{pre}knob_{env.knob}_joint", "_main")
                g = ridge[0]
                R = d.geom_xmat[g].reshape(3, 3)
                half = m.geom_aabb[g][3:]
                k = int(np.argmax(half))
                lo, hi = self._geoms_box(self._joint_geoms(f"{pre}knob_{env.knob}_joint"))
                st["stove_knob_pos"] = r(d.xanchor[j])
                st["stove_knob_axis"] = r(d.xaxis[j])
                st["stove_knob_ridge_dir"] = r(R[:, k])
                st["stove_knob_ridge_half_length"] = round(float(half[k]), 4)
                st["stove_knob_top_z"] = round(float(hi[2]), 4)
                st["stove_knob_angle"] = round(float(d.qpos[m.jnt_qposadr[j]]), 3)
                st["burner_on"] = bool(env.stove.is_burner_on(env=env, burner_loc=env.knob))
            elif f in ("drawer", "door"):
                fx = env.drawer if f == "drawer" else env.fxtr
                st[f"{f}_handle_pos"] = r(self._handle_pos(fx))
                if f == "drawer":  # the measure RoboCasa's drawer tasks judge (slide travel / 55 % of the drawer depth)
                    ds = fx.get_door_state(env)
                else:
                    ds = fx.get_joint_state(env, fx.door_joint_names)
                st[f"{f}_open_fraction"] = round(float(max(ds.values())), 3) if ds else None
                st[f"{f}_front_normal"] = r(_quat_to_mat(np.r_[fx.quat[1:], fx.quat[0]])[:, 1] * -1)
        return st

    # ---- rendering -----------------------------------------------------------------------------------------------
    def render(self, camera: str, width: int, height: int) -> np.ndarray:
        img = self.env.sim.render(width=width, height=height, camera_name=camera)
        return np.ascontiguousarray(img[::-1]).astype(np.uint8)

    def camera(self, name: str) -> dict:
        m, d = self.env.sim.model, self.env.sim.data
        i = m.camera_name2id(name)
        return {
            "pos": [float(v) for v in d.cam_xpos[i]],
            "xmat": [float(v) for v in d.cam_xmat[i]],
            "fovy": float(m.cam_fovy[i]),
        }
