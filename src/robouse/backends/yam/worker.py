"""Simulator worker for the `yam` backend: Dream Labs' dual-YAM MuJoCo scene, run in its own virtualenv.

The scene is Dream Labs' own simulation example, `dream_examples/yam_mujoco/yam_env.py` from the `dreamlabs` wheel
(1.0.0, Apache-2.0), loaded unmodified from the installed wheel: two I2RT YAM arms (meshes MIT, I2RT Robotics) with
parallel grippers, three calibrated cameras (`top` over the table, `left` and `right` on the wrists), an apple and a
banana (YCB scans, CC BY 4.0), an orange, a water bottle, a ceramic bowl and a plate. Control is Dream's: joint position
servos, one step = 50 ms (25 physics steps of 2 ms). The scene needs MuJoCo 3.3.5 or later; Robo Use's own environment
pins 3.3.0, which refuses the scene's massless arm bases, so it runs here (setup: docs/suites/yam.md).

This file runs inside that virtualenv, where robouse is not installed: standard library, numpy, mujoco and Pillow.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path

import mujoco
import numpy as np

SIDES = ("right", "left")  # the order of the action and of the state: Dream's YAM embodiment (right arm first)
FRUIT = ("apple", "orange", "banana")
OBJECTS = (*FRUIT, "water_bottle", "bowl", "plate")
FREE_JOINTS = {"apple": "apple_free", "orange": "orange_free", "banana": "banana_free", "water_bottle": "bottle_free"}
CAMERAS = ("top", "left", "right")
RENDER_W, RENDER_H, CROP = 640, 480, (60, 420)  # each camera renders 640x480; rows 60:420 are the station's crop
SETTLE_STEPS = 20  # after a reset the arms hold at home this long, so an episode starts with the objects at rest
FRUIT_RADIUS = {"apple": 0.035, "orange": 0.033, "banana": 0.075}  # footprints for the layout's no-overlap check
DOWN = np.array([0.0, 0.0, -1.0])
# Goal predicates (metres). A fruit is in the bowl when its centre is within IN_BOWL_XY of the bowl's axis and between
# IN_BOWL_Z of the bowl's base; on the plate when it touches the plate and its centre is within ON_PLATE_XY of the
# plate's centre. Either way it must be released (no finger touches it) and at rest (slower than REST_SPEED).
IN_BOWL_XY, IN_BOWL_Z = 0.065, (0.005, 0.11)
ON_PLATE_XY = 0.07
REST_SPEED = 0.05


def _load_yam_env():
    """Dream's yam_env module from the installed `dreamlabs` wheel, loaded by path (it has no package __init__)."""
    import dream_examples.yam_mujoco as pkg

    path = Path(list(pkg.__path__)[0]) / "yam_env.py"
    spec = importlib.util.spec_from_file_location("dream_yam_env", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _r(v, n: int = 4) -> list[float]:
    return [round(float(x), n) for x in np.ravel(v)]


class Worker:
    def __init__(self) -> None:
        self.ye = _load_yam_env()
        self.env = None
        self.goal: dict = {}
        self.renderer = None
        self.cmd = {s: np.r_[np.zeros(6), 1.0] for s in SIDES}

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    def make(
        self, goal: dict | None = None, seed: int = 0, jitter_m: float = 0.03, yaw_jitter_deg: float = 30.0
    ) -> dict:
        """Build the scene once; `goal` is the task's predicate ({"kind": "in_bowl" | "on_plate", "object": ...})."""
        self.goal = dict(goal or {})
        self.jitter_m, self.yaw_jitter = float(jitter_m), float(yaw_jitter_deg)
        if self.env is None:
            self.env = self.ye.YamEnv()
            self.m, self.d = self.env.model, self.env.data
            self.scratch = mujoco.MjData(self.m)
            self.qadr = {s: np.array([self.m.joint(f"{s}_joint{i}").qposadr[0] for i in range(1, 7)]) for s in SIDES}
            self.dadr = {s: np.array([self.m.joint(f"{s}_joint{i}").dofadr[0] for i in range(1, 7)]) for s in SIDES}
            self.qrange = {s: np.array([self.m.joint(f"{s}_joint{i}").range for i in range(1, 7)]) for s in SIDES}
            self.tcp = {s: self.m.site(f"{s}_tcp").id for s in SIDES}
            self.body = {n: self.m.body(n).id for n in OBJECTS}
            self.fingers = {s: {self.m.body(f"{s}_tip_left").id, self.m.body(f"{s}_tip_right").id} for s in SIDES}
            self.jaw_local = {s: self._jaw_in_tcp_frame(s) for s in SIDES}
        return self.reset(seed)

    def reset(self, seed: int = 0) -> dict:
        """Dream's reset (joints at zero, grippers open, objects where the scene puts them), then for seeds other than 0
        the fruit moved by up to `jitter_m` and turned by up to `yaw_jitter_deg` about the vertical; then a settle."""
        self.env.reset()
        if seed:
            self._jitter(np.random.default_rng(int(seed)))
        mujoco.mj_forward(self.m, self.d)
        self.cmd = {s: np.r_[np.zeros(6), 1.0] for s in SIDES}
        for _ in range(SETTLE_STEPS):
            self.env.step(self.cmd["left"], self.cmd["right"])
        return self.meta()

    def _jitter(self, rng: np.random.Generator) -> None:
        base = {n: self.d.body(n).xpos[:2].copy() for n in FRUIT}
        for _ in range(1000):
            xy = {n: base[n] + rng.uniform(-self.jitter_m, self.jitter_m, 2) for n in FRUIT}
            if all(
                np.linalg.norm(xy[a] - xy[b]) > FRUIT_RADIUS[a] + FRUIT_RADIUS[b] + 0.01
                for i, a in enumerate(FRUIT)
                for b in FRUIT[i + 1 :]
            ):
                break
        else:
            return  # no layout without overlaps: keep Dream's
        for n in FRUIT:
            adr = self.m.joint(FREE_JOINTS[n]).qposadr[0]
            self.d.qpos[adr : adr + 2] = xy[n]
            yaw = np.deg2rad(rng.uniform(-self.yaw_jitter, self.yaw_jitter))
            turn = np.array([np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)])
            q = np.empty(4)
            mujoco.mju_mulQuat(q, turn, self.d.qpos[adr + 3 : adr + 7].copy())
            self.d.qpos[adr + 3 : adr + 7] = q

    def meta(self) -> dict:
        low, high = [], []
        for s in SIDES:
            low += [float(x) for x in self.qrange[s][:, 0]] + [0.0]
            high += [float(x) for x in self.qrange[s][:, 1]] + [1.0]
        return {
            "low": low,
            "high": high,
            "cameras": list(CAMERAS),
            "mujoco": mujoco.__version__,
            "dreamlabs": importlib.metadata.version("dreamlabs"),
        }

    # ---- control ---------------------------------------------------------------------------------------------------
    def step(self, action: list[float]) -> dict:
        """One 50 ms step: [right joints 1-6 (rad), right grip (0 closed .. 1 open), left joints 1-6, left grip]."""
        a = np.asarray(action, dtype=np.float64)
        for i, s in enumerate(SIDES):
            v = a[7 * i : 7 * i + 7].copy()
            v[:6] = np.clip(v[:6], self.qrange[s][:, 0], self.qrange[s][:, 1])
            v[6] = float(np.clip(v[6], 0.0, 1.0))
            self.cmd[s] = v
        self.env.step(self.cmd["left"], self.cmd["right"])
        return {"success": self._judge()[0]}

    # ---- observation -----------------------------------------------------------------------------------------------
    def observe(self) -> dict:
        st = self.env.state()
        touching = self._touching()
        out: dict = {}
        for s in SIDES:
            out[f"{s}_joint_pos"] = _r(st[s][:6])
            out[f"{s}_gripper_open"] = round(float(st[s][6]), 3)
            out[f"{s}_tcp_pos"] = _r(self.d.site_xpos[self.tcp[s]])
            out[f"{s}_tcp_down_deg"] = round(self._tilt_deg(s), 1)
            out[f"{s}_jaw_yaw_deg"] = round(self._jaw_yaw_deg(s), 1)
            out[f"{s}_touching"] = sorted(touching[s])
        for n in OBJECTS:
            out[f"{n}_pos"] = _r(self.d.xpos[self.body[n]])
        out["banana_axis_yaw_deg"] = round(self._banana_yaw_deg(), 1)
        return out

    def render(self, camera: str = "top", width: int | None = None, height: int | None = None) -> np.ndarray:
        if self.renderer is None:
            self.renderer = mujoco.Renderer(self.m, height=RENDER_H, width=RENDER_W)
        self.renderer.update_scene(self.d, camera=camera)
        img = self.renderer.render()[CROP[0] : CROP[1]]
        if width and height and (int(width), int(height)) != (img.shape[1], img.shape[0]):
            from PIL import Image

            img = np.asarray(Image.fromarray(img).resize((int(width), int(height)), Image.BILINEAR))
        return np.ascontiguousarray(img, dtype=np.uint8)

    def camera_info(self, cameras: list[str], width: int, height: int) -> list[dict]:
        """Per camera, the 3x4 projection P with [u*w, v*w, w] = P @ [x, y, z, 1] in an image of width x height pixels
        (the 640x360 crop, scaled). From the camera's own focal lengths and principal point, which the scene sets from
        the station calibration (focalpixel, principalpixel)."""
        out = []
        for name in cameras:
            cid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_CAMERA, name)
            if cid < 0:
                continue
            res = self.m.cam_resolution[cid].astype(float)
            sensor = self.m.cam_sensorsize[cid].astype(float)
            fx_l, fy_l, px_l, py_l = self.m.cam_intrinsic[cid]
            fx, fy = fx_l / sensor[0] * res[0], fy_l / sensor[1] * res[1]
            cx, cy = res[0] / 2 - px_l / sensor[0] * res[0], res[1] / 2 + py_l / sensor[1] * res[1]
            cy -= CROP[0]
            sx, sy = width / res[0], height / (CROP[1] - CROP[0])
            k = np.array([[fx * sx, 0.0, cx * sx], [0.0, fy * sy, cy * sy], [0.0, 0.0, 1.0]])
            rot, pos = self.d.cam_xmat[cid].reshape(3, 3), self.d.cam_xpos[cid]
            to_cv = np.diag([1.0, -1.0, -1.0])  # MuJoCo cameras look down -z with +y up; image rows grow downward
            ext = to_cv @ np.hstack([rot.T, (-rot.T @ pos)[:, None]])
            proj = k @ ext
            out.append(
                {
                    "name": name,
                    "width": int(width),
                    "height": int(height),
                    "position": _r(pos),
                    "projection": [[round(float(x), 5) for x in row] for row in proj],
                }
            )
        return out

    # ---- judging ---------------------------------------------------------------------------------------------------
    def success(self) -> dict:
        ok, detail = self._judge()
        return {"success": ok, "detail": detail}

    def _judge(self) -> tuple[bool, dict]:
        kind, obj = self.goal.get("kind"), self.goal.get("object")
        if kind not in ("in_bowl", "on_plate") or obj not in self.body:
            return False, {"error": f"unknown goal {self.goal}"}
        p = self.d.xpos[self.body[obj]]
        held = sorted(s for s, objs in self._touching().items() if obj in objs)
        speed = float(np.linalg.norm(self._velocity(obj)))
        if kind == "in_bowl":
            c = self.d.xpos[self.body["bowl"]]
            xy, z = float(np.linalg.norm(p[:2] - c[:2])), float(p[2] - c[2])
            placed = xy < IN_BOWL_XY and IN_BOWL_Z[0] < z < IN_BOWL_Z[1]
            detail = {"xy_from_bowl_axis_m": round(xy, 4), "height_above_bowl_base_m": round(z, 4)}
        else:
            c = self.d.xpos[self.body["plate"]]
            xy = float(np.linalg.norm(p[:2] - c[:2]))
            touches = self._contact(self.body[obj], self.body["plate"])
            placed = touches and xy < ON_PLATE_XY
            detail = {"xy_from_plate_centre_m": round(xy, 4), "touches_plate": touches}
        ok = bool(placed and not held and speed < REST_SPEED)
        return ok, {**detail, "held_by": held, "speed_m_s": round(speed, 4), "object_pos": _r(p)}

    def _touching(self) -> dict[str, set[str]]:
        """Per arm, the scene objects one of its fingertips touches."""
        names = {v: k for k, v in self.body.items()}
        out: dict[str, set[str]] = {s: set() for s in SIDES}
        for i in range(self.d.ncon):
            c = self.d.contact[i]
            b1, b2 = self.m.geom_bodyid[c.geom1], self.m.geom_bodyid[c.geom2]
            for s in SIDES:
                for a, b in ((b1, b2), (b2, b1)):
                    if a in self.fingers[s] and b in names:
                        out[s].add(names[b])
        return out

    def _contact(self, body_a: int, body_b: int) -> bool:
        for i in range(self.d.ncon):
            c = self.d.contact[i]
            pair = {self.m.geom_bodyid[c.geom1], self.m.geom_bodyid[c.geom2]}
            if pair == {body_a, body_b}:
                return True
        return False

    def _velocity(self, obj: str) -> np.ndarray:
        v = np.zeros(6)
        mujoco.mj_objectVelocity(self.m, self.d, mujoco.mjtObj.mjOBJ_BODY, self.body[obj], v, 0)
        return v[3:]

    def _banana_yaw_deg(self) -> float:
        """The heading of the banana's long axis in the table plane (its scan is longest along its local y)."""
        axis = self.d.xmat[self.body["banana"]].reshape(3, 3)[:, 1]
        return float(np.rad2deg(np.arctan2(axis[1], axis[0])) % 180.0)

    # ---- kinematics (the skills' inverse kinematics) ---------------------------------------------------------------
    def _jaw_in_tcp_frame(self, side: str) -> np.ndarray:
        """The direction the fingers close along, in the tool frame (constant: the fingers slide in the gripper)."""
        a = self.d.xpos[self.m.body(f"{side}_tip_right").id] - self.d.xpos[self.m.body(f"{side}_tip_left").id]
        local = self.d.site_xmat[self.tcp[side]].reshape(3, 3).T @ a
        local[2] = 0.0  # the jaw is across the approach axis (the tool frame's z)
        return local / np.linalg.norm(local)

    def _tilt_deg(self, side: str, data=None) -> float:
        """Angle between the gripper's approach axis and straight down."""
        d = self.d if data is None else data
        z = d.site_xmat[self.tcp[side]].reshape(3, 3)[:, 2]
        return float(np.rad2deg(np.arccos(np.clip(np.dot(z, DOWN), -1.0, 1.0))))

    def _jaw_yaw_deg(self, side: str, data=None) -> float:
        d = self.d if data is None else data
        jaw = d.site_xmat[self.tcp[side]].reshape(3, 3) @ self.jaw_local[side]
        return float(np.rad2deg(np.arctan2(jaw[1], jaw[0])) % 180.0)

    def ik(self, side: str, pos: list[float], yaw_deg: float | None = None, q0: list[float] | None = None) -> dict:
        """Joint angles that put the arm's tool point at `pos` with the gripper pointing straight down and, when given,
        the jaw closing along heading `yaw_deg` (degrees in the table plane; a jaw is symmetric, so modulo 180).
        Damped least squares from `q0` (default: the arm's measured joints), within the joint limits."""
        m, d = self.m, self.scratch
        qa, da, rng, sid = self.qadr[side], self.dadr[side], self.qrange[side], self.tcp[side]
        d.qpos[:] = self.d.qpos
        if q0 is not None:
            d.qpos[qa] = np.clip(np.asarray(q0, dtype=float), rng[:, 0], rng[:, 1])
        target = np.asarray(pos, dtype=float)
        want = None
        if yaw_deg is not None:
            t = np.deg2rad(float(yaw_deg))
            want = np.array([np.cos(t), np.sin(t), 0.0])
        jp, jr = np.zeros((3, m.nv)), np.zeros((3, m.nv))
        for _ in range(400):
            mujoco.mj_kinematics(m, d)
            mujoco.mj_comPos(m, d)
            rot = d.site_xmat[sid].reshape(3, 3)
            ep = target - d.site_xpos[sid]
            er = np.cross(rot[:, 2], DOWN)
            if want is not None:
                jaw = rot @ self.jaw_local[side]
                jaw = jaw - np.dot(jaw, DOWN) * DOWN
                jaw /= np.linalg.norm(jaw) + 1e-9
                if np.dot(jaw, want) < 0:  # either way round closes the same
                    jaw = -jaw
                er = er + np.cross(jaw, want)
            if np.linalg.norm(ep) < 2e-4 and np.linalg.norm(er) < 2e-3:
                break
            mujoco.mj_jacSite(m, d, jp, jr, sid)
            jac = np.vstack([jp[:, da], 0.5 * jr[:, da]])
            err = np.r_[ep, 0.5 * er]
            dq = jac.T @ np.linalg.solve(jac @ jac.T + 0.05**2 * np.eye(6), err)
            d.qpos[qa] = np.clip(d.qpos[qa] + np.clip(dq, -0.2, 0.2), rng[:, 0], rng[:, 1])
        mujoco.mj_kinematics(m, d)
        return {
            "q": _r(d.qpos[qa], 5),
            "pos_err_m": round(float(np.linalg.norm(target - d.site_xpos[sid])), 4),
            "tilt_deg": round(self._tilt_deg(side, d), 1),
        }

    def close(self) -> None:
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        if self.env is not None:
            self.env.close()
