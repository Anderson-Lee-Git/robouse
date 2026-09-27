"""Gymnasium-Robotics (Farama) backend: Fetch manipulation and PointMaze navigation, in MuJoCo.

Fetch (FetchReach/Push/Slide/PickAndPlace-v4): a 7-DoF Fetch arm with a two-finger gripper at a table.
  Action: [dx, dy, dz, grip] in [-1, 1]. dx/dy/dz move the gripper's position target by 5 cm per unit
  per step (Fetch's native scaling; one step = 40 ms of simulation). grip: +1 close, -1 open. The grip
  sign is flipped relative to native Fetch (where +1 opens) so it matches the shared `robo grip` skill.
  Reach and Slide block the fingers, so grip has no effect there.
  Observation: hand_pos, hand_vel, gripper_open (0 closed .. 1 open), gripper_width (m), obj1_pos,
  obj1_vel, obj1_rot (Euler xyz, rad), goal_pos (Fetch's `desired_goal`). Success is Fetch's own
  `is_success`: the object (the gripper, for Reach) within 5 cm of the goal.

PointMaze (PointMaze_UMaze/Medium/Large-v3): a force-controlled ball in a walled maze.
  Action: [fx, fy] in [-1, 1], a force on the ball (one step = 10 ms; speed is capped at 5 m/s).
  Observation: agent_pos, agent_vel, goal_pos, the maze as rows of characters ('#' wall, '.' free),
  the cell size, and the mapping from (row, col) to world (x, y). Success is PointMaze's own
  `info["success"]`: the ball within 0.45 m of the goal.

Rendering uses mujoco.Renderer on the env's model/data (no gymnasium GL setup needed on macOS).
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .base import ActionSpec, Backend, StepInfo

# task id -> (env id, seed). The oracle only needs the env id; the episode server passes the seed.
TASKS: dict[str, tuple[str, int]] = {
    "gymrobotics-fetch-reach": ("FetchReach-v4", 0),
    "gymrobotics-fetch-slide": ("FetchSlide-v4", 0),
    "gymrobotics-fetch-push-s0": ("FetchPush-v4", 0),
    "gymrobotics-fetch-push-s1": ("FetchPush-v4", 1),
    "gymrobotics-fetch-pick-place-s0": ("FetchPickAndPlace-v4", 0),
    "gymrobotics-fetch-pick-place-s1": ("FetchPickAndPlace-v4", 1),
    "gymrobotics-pointmaze-umaze-s0": ("PointMaze_UMaze-v3", 0),
    "gymrobotics-pointmaze-umaze-s1": ("PointMaze_UMaze-v3", 1),
    "gymrobotics-pointmaze-medium-s0": ("PointMaze_Medium-v3", 0),
    "gymrobotics-pointmaze-medium-s1": ("PointMaze_Medium-v3", 1),
    "gymrobotics-pointmaze-large-s0": ("PointMaze_Large-v3", 0),
    "gymrobotics-pointmaze-large-s1": ("PointMaze_Large-v3", 1),
}

_R = lambda v: [round(float(x), 4) for x in np.ravel(v)]


def _make(env_id: str, **kw):
    import gymnasium as gym
    import gymnasium_robotics

    gym.register_envs(gymnasium_robotics)
    # the episode server enforces the step budget; disable gymnasium's own time limit
    return gym.make(env_id, max_episode_steps=10**9, **kw)


class GymRoboticsBackend(Backend):
    name = "gymrobotics"

    def __init__(self, spec: dict, width: int = 320, height: int = 320):
        self.env_id = str(spec["env"])
        self.max_steps = int(spec.get("max_steps", 300))
        self.camera = str(spec.get("camera", "default"))
        self._w, self._h = width, height
        self.is_maze = self.env_id.startswith("PointMaze")
        if self.is_maze:
            # episodic: reaching the goal terminates (no new goal is sampled), as in D4RL/Minari
            self.env = _make(self.env_id, continuing_task=False, reset_target=False)
            self.action_spec = ActionSpec(
                names=["fx", "fy"], low=[-1, -1], high=[1, 1],
                doc="fx/fy: force on the ball along world x/y (one step = 10 ms; speed capped at 5 m/s)",
            )
            self._grip = 0.0  # the settle period after `done` applies zero force
        else:
            self.env = _make(self.env_id)
            self.action_spec = ActionSpec(
                names=["dx", "dy", "dz", "grip"], low=[-1, -1, -1, -1], high=[1, 1, 1, 1],
                doc="dx/dy/dz: move the gripper 5 cm per unit per step; grip: +1 close, -1 open",
            )
            self._grip = -1.0
        self.u = self.env.unwrapped
        self._renderer = None
        self._obs: dict = {}
        self._info: dict = {}

    # ---- core API -------------------------------------------------------------------------------
    def reset(self, seed: int) -> None:
        self._obs, info = self.env.reset(seed=int(seed))
        self._info = dict(info)
        self._grip = 0.0 if self.is_maze else -1.0

    def step(self, action) -> StepInfo:
        a = self.action_spec.clip(action)
        if not self.is_maze:
            self._grip = float(a[3])
            a = a.copy()
            a[3] = -a[3]  # robouse: +1 close; native Fetch: +1 open
        self._obs, r, _term, _trunc, info = self.env.step(a.astype(np.float32))
        self._info = dict(info)
        return StepInfo(success=self.success(), reward=float(r),
                        extra={k: float(v) for k, v in info.items() if isinstance(v, (int, float, bool, np.floating, np.bool_))})

    def success(self) -> bool:
        if self.is_maze:
            return bool(np.linalg.norm(self._obs["achieved_goal"] - self._obs["desired_goal"]) <= 0.45)
        return bool(self.u._is_success(self._obs["achieved_goal"], self._obs["desired_goal"]) >= 1.0)

    def observe(self) -> dict:
        return self._observe_maze() if self.is_maze else self._observe_fetch()

    def _observe_fetch(self) -> dict:
        o = np.asarray(self._obs["observation"], dtype=float)
        dt = float(self.u.dt)
        grip_pos, fingers, grip_velp = o[0:3], o[9:11], o[20:23]
        out = {
            "hand_pos": _R(grip_pos),
            "hand_vel": _R(grip_velp / dt),
            "gripper_open": round(float(np.clip(fingers.sum() / 0.1, 0, 1)), 4),
            "gripper_width": round(float(fingers.sum()), 4),
        }
        if self.u.has_object:
            out["obj1_pos"] = _R(o[3:6])
            out["obj1_rot"] = _R(o[11:14])
            out["obj1_vel"] = _R((o[14:17] + grip_velp) / dt)  # Fetch stores it relative to the gripper
        out["goal_pos"] = _R(self._obs["desired_goal"])
        return out

    def _observe_maze(self) -> dict:
        m = self.u.maze
        o = np.asarray(self._obs["observation"], dtype=float)
        pos, goal = o[0:2], np.asarray(self._obs["desired_goal"], dtype=float)
        return {
            "agent_pos": _R(pos),
            "agent_vel": _R(o[2:4]),
            "goal_pos": _R(goal),
            "agent_cell": list(self.cell_of(pos)),
            "goal_cell": list(self.cell_of(goal)),
            "maze_rows": self.grid(),
            "cell_size": float(m.maze_size_scaling),
            "cell_center": f"x = (col + 0.5) * {m.maze_size_scaling:g} - {m.x_map_center:g}, "
                           f"y = {m.y_map_center:g} - (row + 0.5) * {m.maze_size_scaling:g}",
        }

    # ---- maze helpers (public information: the layout is part of the task) -----------------------
    def grid(self) -> list[str]:
        return ["".join("#" if c == 1 else "." for c in row) for row in self.u.maze.maze_map]

    def cell_of(self, xy) -> tuple[int, int]:
        m = self.u.maze
        col = int(np.floor((xy[0] + m.x_map_center) / m.maze_size_scaling))
        row = int(np.floor((m.y_map_center - xy[1]) / m.maze_size_scaling))
        return row, col

    # ---- rendering ------------------------------------------------------------------------------
    def render(self, width: int = 320, height: int = 320) -> np.ndarray:
        import mujoco

        if self.is_maze:
            model, data = self.u.point_env.model, self.u.point_env.data
        else:
            model, data = self.u.model, self.u.data
            self.u._render_callback()  # moves the goal marker site to the current goal
        if self._renderer is None:
            self._renderer = mujoco.Renderer(model, self._h, self._w)
            cam = mujoco.MjvCamera()
            cam.type = mujoco.mjtCamera.mjCAMERA_FREE
            if self.is_maze:  # top-down: +x right, +y up
                m = self.u.maze
                span = max(m.map_length, m.map_width) * m.maze_size_scaling
                cam.distance, cam.azimuth, cam.elevation = span * 1.25, 90.0, -90.0
                cam.lookat[:] = [0.0, 0.0, 0.0]
            elif self.env_id.startswith("FetchSlide"):  # the long table
                cam.distance, cam.azimuth, cam.elevation = 2.2, 160.0, -30.0
                cam.lookat[:] = [1.45, 0.75, 0.4]
            else:
                cam.distance, cam.azimuth, cam.elevation = 1.4, 150.0, -25.0
                cam.lookat[:] = [1.3, 0.75, 0.5]
            self._cam = cam
        mujoco.mj_forward(model, data)
        self._renderer.update_scene(data, camera=self._cam)
        return self._renderer.render().copy()

    # ---- skills ---------------------------------------------------------------------------------
    def skills(self) -> list[str]:
        return [] if self.is_maze else ["move_to", "grip"]

    def hand_pos(self) -> np.ndarray:
        return np.asarray(self._obs["observation"][0:3], dtype=float)

    def close(self) -> None:
        try:
            if self._renderer is not None:
                self._renderer.close()
            self.env.close()
        except Exception:
            pass


# ---- reference solutions (socket client only; public observation fields only) -------------------

def _call(req: dict) -> dict:
    from robouse.agent_cli import _send

    r = _send(req)
    if not r.get("ok"):
        raise RuntimeError(r.get("error"))
    return r["result"]


def _state() -> dict:
    return _call({"op": "observe"})["state"]


class _Finished(Exception):
    pass


def _act(a, repeat: int = 1) -> dict:
    r = _call({"op": "act", "action": [float(x) for x in a], "repeat": int(repeat)})
    if "episode" in r:
        raise _Finished(r["episode"])
    return r["state"]


def _move(pos, grip=None, tol=0.01, max_steps=100) -> dict:
    r = _call({"op": "move_to", "pos": [float(x) for x in pos], "grip": grip, "tol": tol, "max_steps": max_steps})
    if "episode" in r:
        raise _Finished(r["episode"])
    return r["state"]


def _grip(v: float, steps: int = 10) -> dict:
    r = _call({"op": "grip", "value": float(v), "steps": steps})
    if "episode" in r:
        raise _Finished(r["episode"])
    return r["state"]


def _fetch_reach() -> None:
    _move(_state()["goal_pos"], tol=0.005)


def _fetch_push() -> None:
    """Closed loop: stand behind the block on the block->goal line and push; re-approach when it drifts."""
    st = _grip(1.0, 5)
    for _ in range(12):
        obj, goal = np.array(st["obj1_pos"]), np.array(st["goal_pos"])
        d = goal[:2] - obj[:2]
        if np.linalg.norm(d) < 0.015:
            return
        u = d / np.linalg.norm(d)
        z = obj[2]
        behind = np.r_[obj[:2] - u * 0.06, z]
        hand = np.array(st["hand_pos"])
        _move(np.r_[hand[:2], z + 0.08], grip=1.0, tol=0.02)
        _move(np.r_[behind[:2], z + 0.08], grip=1.0, tol=0.01)
        _move(behind, grip=1.0, tol=0.01)
        # push along the line, stopping a little short so the block ends on the goal
        for _ in range(40):
            st = _state()
            obj = np.array(st["obj1_pos"])
            rem = goal[:2] - obj[:2]
            dist = np.linalg.norm(rem)
            if dist < 0.01 or rem @ u < 0:
                break
            hand = np.array(st["hand_pos"])
            # lateral error of the hand from the push line: re-approach if large
            rel = hand[:2] - obj[:2]
            if abs(rel[0] * u[1] - rel[1] * u[0]) > 0.02 or np.linalg.norm(rel) > 0.09:
                break
            v = u * min(1.0, dist * 6 + 0.05)
            st = _act([v[0], v[1], (z - hand[2]) * 10, 1.0])
        st = _act([0, 0, 0, 1.0], 5)


def _fetch_pick_place() -> None:
    st = _state()
    obj, goal = np.array(st["obj1_pos"]), np.array(st["goal_pos"])
    _move(obj + [0, 0, 0.1], grip=-1.0, tol=0.01)
    _move(obj + [0, 0, 0.0], grip=-1.0, tol=0.005)
    st = _grip(1.0, 10)
    _move(np.array(st["obj1_pos"]) + [0, 0, 0.08], grip=1.0, tol=0.01)
    for _ in range(4):
        st = _state()
        off = np.array(st["obj1_pos"]) - np.array(st["hand_pos"])
        st = _move(goal - off, grip=1.0, tol=0.005)
        if np.linalg.norm(np.array(st["obj1_pos"]) - goal) < 0.01:
            break


def _fetch_slide() -> None:
    """Closed loop: strike the puck toward the goal from behind, let it glide, re-aim and repeat.

    The puck keeps gliding slowly on the low-friction table; the task counts the first time it is on the goal.
    """
    st = _state()
    for _ in range(12):
        obj, goal = np.array(st["obj1_pos"]), np.array(st["goal_pos"])
        d = goal[:2] - obj[:2]
        dist = np.linalg.norm(d)
        u = d / dist
        z = obj[2]
        hand = np.array(st["hand_pos"])
        _move(np.r_[hand[:2], z + 0.08], tol=0.02)
        _move(np.r_[obj[:2] - u * 0.07, z + 0.08], tol=0.01)
        _move(np.r_[obj[:2] - u * 0.07, z + 0.01], tol=0.01)  # the fingertips cannot go lower
        speed = float(np.clip(0.2 + 0.5 * dist, 0.2, 0.6))
        _act([u[0] * speed, u[1] * speed, 0, 0], 8)
        _act([-u[0] * 0.5, -u[1] * 0.5, 0.5, 0], 2)  # back off and let the puck glide
        for _ in range(15):
            st = _act([0, 0, 0, 0], 4)
            if np.linalg.norm(st["obj1_vel"]) < 0.06:
                break


def _maze(env: str) -> None:
    st = _state()
    rows = st["maze_rows"]
    H, W = len(rows), len(rows[0])
    start, goal = tuple(st["agent_cell"]), tuple(st["goal_cell"])
    prev = {start: None}
    q = deque([start])
    while q:
        c = q.popleft()
        if c == goal:
            break
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dr, c[1] + dc)
            if 0 <= n[0] < H and 0 <= n[1] < W and rows[n[0]][n[1]] == "." and n not in prev:
                prev[n] = c
                q.append(n)
    path, c = [], goal
    while c is not None:
        path.append(c)
        c = prev[c]
    path.reverse()
    s = float(st["cell_size"])
    H0, W0 = H * s / 2, W * s / 2
    centers = [np.array([(col + 0.5) * s - W0, H0 - (row + 0.5) * s]) for row, col in path[1:-1]]
    waypoints = centers + [np.array(st["goal_pos"])]
    for i, wp in enumerate(waypoints):
        last = i == len(waypoints) - 1
        for _ in range(400):
            pos, vel = np.array(st["agent_pos"]), np.array(st["agent_vel"])
            e = wp - pos
            if np.linalg.norm(e) < (0.1 if last else 0.25 * s):
                break
            f = np.clip(e * 4.0 - vel * 1.0, -1, 1)
            st = _act(f, 5)


def oracle_main(env: str) -> None:
    env_id = TASKS[env][0] if env in TASKS else env
    try:
        if env_id.startswith("PointMaze"):
            _maze(env_id)
        elif env_id.startswith("FetchReach"):
            _fetch_reach()
        elif env_id.startswith("FetchPush"):
            _fetch_push()
        elif env_id.startswith("FetchPickAndPlace"):
            _fetch_pick_place()
        elif env_id.startswith("FetchSlide"):
            _fetch_slide()
        else:
            raise KeyError(env_id)
    except _Finished:
        return
    from robouse.agent_cli import _send

    _send({"op": "done", "text": "oracle finished"})
