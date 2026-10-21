"""A RoboEnv-compatible device service for one Robo Use episode, and the Kinex workspace that reaches it. Standard
library only: it runs inside the agent's sandbox, from its copy in the trial workspace (`.robouse/bin`).

Kinex (github.com/stacx-lab/kinex) drives simulators through RoboEnv (github.com/stacx-lab/RoboEnv): `roboenv launch`
serves a simulated robot's devices over loopback HTTP (protocol `roboenv/1`), and `roboenv setup` writes the robot's
device profiles and drivers into the workspace's `.kinex/`, where Kinex finds them. This module does both for a Robo Use
episode. It follows RoboEnv's documented wire protocol and contains none of RoboEnv's code, which has no licence.

It is a client of the episode socket on the agent's side of the trust boundary, like `robo mcp`: every device call
becomes `robo` requests (info, observe, status, act, done), sent without a token and marked `"via": "roboenv-bridge"`
with the time sent (`"sent"`, epoch seconds) in the episode's trace. So the episode server keeps the step budget, the recording and the verdict, and a device shows only
what `robo info` and `robo observe` show: on a vision task, the visible fields (the hand) and camera images, never the
objects.

Devices, from `robo info` and the first observation:
  world          the episode's clock. One control step is the task's `embodiment.step_s` seconds of device time (0.05 s
                 when the task does not declare it). read gives time_s and the step budget in seconds; wait(duration_s)
                 runs the simulator for that many steps, the actuators following their references meanwhile. Like
                 RoboEnv's stepped mode, nothing moves between waits.
  arm            a single arm whose action is an end-effector velocity in the world frame (an `ee_delta_pos` group) and
                 whose observation has `hand_pos`: a joint device with three prismatic joints x, y, z, the hand position
                 in metres in the world frame. Writes are position references, spread over their duration as Kinex's own
                 drivers spread them; each step asks the hand to cover part of the way to its current reference (below).
  gripper        that arm's gripper action: a position gripper, normalized -1 (open) to +1 (closed), as `robo` takes it.
  <name>_camera  each task camera: an RGB camera whose read is `robo observe --image --camera NAME`. Its calibration
                 (from `robo info`) is in the profile only where `robo info` gives it: on vision tasks.
Other action groups (rotation, a second arm, a base) send their hold command while the bridge steps; `robo` drives them.

How a step moves the hand: the action asks for CATCH_UP of the distance to the reference, divided by the hand's measured
response (metres per unit of action per step, the median over its recent moves). Until the bridge has measured that, it
uses `robo move-to`'s law (10 times the distance, clipped to the action bounds). An arm that the agent moves with `robo`
itself gets a new reference where the hand now is; the gripper keeps the last value a device write gave it.

Wire protocol (roboenv/1, loopback HTTP; the bridge checks the Host header and refuses browser requests):
  GET /                                  {"protocol": "roboenv/1", "generation": 0}; unlike RoboEnv, no session: the
                                         session is this endpoint's capability, so another trial's agent that finds the
                                         port cannot drive this robot. Clients take it from ROBOENV_SESSION or a
                                         device's connection.json.
  GET /artifacts/SESSION/0/ID.png        a camera image a read returned
  POST /  one JSON request {protocol, session, generation, request_id, deadline_s, op, args}; ops: health,
          environment.describe, devices.list, devices.describe, devices.call {device, action, args},
          devices.cancel {execution_id}, simulation.status, simulation.stop (= `robo done`).
  Replies: {protocol, session, generation, request_id, ok, result | error {code, message, retryable, details}}.

  python3 roboenv_bridge.py [--kinex-dir DIR] --run CMD ...
Writes DIR (default ./.kinex): workspace.yaml and devices/<name>/{profile.yaml, driver.py, connection.json}, the
profiles as JSON (which is YAML), then serves on $ROBOENV_ENDPOINT with session $ROBOENV_SESSION while CMD runs, and
exits with its return code. The episode socket is $ROBOUSE_SOCKET.
"""

from __future__ import annotations

import base64
import hmac
import json
import math
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

PROTOCOL = "roboenv/1"
CONTRACT = "roboenv/devices/1"
VIA = "roboenv-bridge"  # the episode server records it in trace.jsonl, so trajectories can tell these requests apart
DEFAULT_STEP_S = 0.05
GENERATION = 0  # one episode per bridge: no reset
MAX_BODY = 8 * 1024 * 1024
READ_ACTIONS = frozenset({"read", "status", "load", "unload", "fk", "ik"})
HOLD_TOL_M = 0.0005  # a hand this close to its reference, with no reference moving, holds still (batched steps)
CATCH_UP = 0.5  # the share of the distance to the reference one step asks for, once the hand's response is measured
MOVE_TO_GAIN = 10.0  # until then: robo move-to's law, action = 10 x distance, clipped to the action bounds
SCALE_SAMPLES = 9  # the hand's response is the median over this many recent moves
MIN_MOVE_M = 2e-4  # a move shorter than this (a blocked hand, a tiny command) does not update the response
MIN_RESPONSE = 0.002  # metres per unit per step: a floor, so a hand that barely moved never gets a huge gain
ARM_SPAN_M = 2.0  # the arm's declared joint limits: its start position +- this (the simulator bounds the real motion)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")
DEVICE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


class BridgeError(Exception):
    """A device or protocol failure, with RoboEnv's error code."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finite(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def _vector(value: Any, n: int, what: str) -> list[float]:
    if not isinstance(value, list) or len(value) != n or not all(_finite(v) for v in value):
        raise BridgeError("invalid_args", f"{what} must be a list of {n} finite numbers")
    return [float(v) for v in value]


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def png_size(data: bytes) -> tuple[int, int]:
    """(width, height) of a PNG, from its IHDR chunk."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG image")
    w, h = struct.unpack(">II", data[16:24])
    return int(w), int(h)


# ---- camera calibration -------------------------------------------------------------------------------------------


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _quat(r: list[list[float]]) -> list[float]:
    """The unit quaternion [x, y, z, w] of a rotation matrix."""
    t = r[0][0] + r[1][1] + r[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [(r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s, 0.25 * s]
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2
        q = [0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s, (r[2][1] - r[1][2]) / s]
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2
        q = [(r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s, (r[0][2] - r[2][0]) / s]
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2
        q = [(r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s, (r[1][0] - r[0][1]) / s]
    n = math.sqrt(sum(v * v for v in q))
    q = [v / n for v in q]
    return q if q[3] >= 0 else [-v for v in q]


def _rq(m: list[list[float]]) -> tuple[list[float], list[list[float]]]:
    """M = K R for a 3x3 M: K upper triangular with a positive diagonal ([k11, k12, k13, k22, k23, k33]), R
    orthonormal (rows r1, r2, r3), by Gram-Schmidt from the last row up."""
    k33 = math.sqrt(_dot(m[2], m[2]))
    r3 = [v / k33 for v in m[2]]
    k23 = _dot(m[1], r3)
    r2_ = [a - k23 * b for a, b in zip(m[1], r3, strict=True)]
    k22 = math.sqrt(_dot(r2_, r2_))
    r2 = [v / k22 for v in r2_]
    k13, k12 = _dot(m[0], r3), _dot(m[0], r2)
    r1_ = [a - k12 * b - k13 * c for a, b, c in zip(m[0], r2, r3, strict=True)]
    k11 = math.sqrt(_dot(r1_, r1_))
    r1 = [v / k11 for v in r1_]
    return [k11, k12, k13, k22, k23, k33], [r1, r2, r3]


def calibration(projection: list[list[float]]) -> tuple[dict, dict]:
    """Kinex's pinhole intrinsics and the camera's optical-frame mount in the world, from the 3x4 matrix `robo info`
    gives, P with [u*w, v*w, w] = P @ [x, y, z, 1].

    P = K [R | t] is split by RQ decomposition (K upper triangular with a positive diagonal, R the world-to-optical
    rotation: x right, y down, z forward, as Kinex's cameras are). P is defined up to scale, so its sign is the one that
    makes R a rotation. Robo Use's pixel coordinates have the image edges at 0 and the size, so a pixel's centre is at
    +0.5; Kinex puts pixel centres at whole numbers, hence the half pixel off the principal point."""
    p = [[float(v) for v in row] for row in projection]
    k, rot = _rq([row[:3] for row in p])
    r1, r2, r3 = rot
    cross = [r2[1] * r3[2] - r2[2] * r3[1], r2[2] * r3[0] - r2[0] * r3[2], r2[0] * r3[1] - r2[1] * r3[0]]
    if _dot(r1, cross) < 0:
        p = [[-v for v in row] for row in p]
        k, rot = _rq([row[:3] for row in p])
    k11, k12, k13, k22, k23, k33 = k
    # t = K^-1 p4 (back substitution), then the camera centre C = -R^T t
    p4 = [row[3] for row in p]
    t3 = p4[2] / k33
    t2 = (p4[1] - k23 * t3) / k22
    t1 = (p4[0] - k12 * t2 - k13 * t3) / k11
    t = [t1, t2, t3]
    centre = [-sum(rot[i][j] * t[i] for i in range(3)) for j in range(3)]
    intrinsics = {
        "model": "pinhole",
        "fx": k11 / k33,
        "fy": k22 / k33,
        "cx": k13 / k33 - 0.5,
        "cy": k23 / k33 - 0.5,
        "skew": k12 / k33,
    }
    camera_to_world = [[rot[j][i] for j in range(3)] for i in range(3)]  # R^T
    mount = {
        "parent": "world",
        "parent_frame": "world",
        "translation_m": centre,
        "rotation_xyzw": _quat(camera_to_world),
    }
    return intrinsics, mount


# ---- position references ------------------------------------------------------------------------------------------


class Buffer:
    """Position references for one actuator, as Kinex's drivers hold them: `actions` spread evenly over `duration_s` of
    device time from `start_s`, the last one kept afterwards."""

    def __init__(self, actions: list[list[float]], duration_s: float, start_s: float, owner: str) -> None:
        self.actions, self.duration_s, self.start_s, self.owner = actions, duration_s, start_s, owner
        self.varies = len({tuple(a) for a in actions}) > 1

    def at(self, t: float) -> list[float]:
        if t >= self.start_s + self.duration_s:
            return self.actions[-1]
        i = int((t - self.start_s) * len(self.actions) / self.duration_s)
        return self.actions[min(max(i, 0), len(self.actions) - 1)]

    def moving(self, t: float) -> bool:
        """Whether the reference still changes after time t."""
        return self.varies and t < self.start_s + self.duration_s


# ---- the bridge ---------------------------------------------------------------------------------------------------


class Bridge:
    """One episode's devices. `send` sends one episode request and returns the reply ({"ok": ..., "result": ...})."""

    def __init__(self, send: Callable[[dict], dict], session: str, endpoint: str) -> None:
        if not IDENTIFIER.match(session):
            raise ValueError("the session must be a RoboEnv identifier: letters, digits and _.:@+-")
        self._send = send
        self.session, self.endpoint = session, endpoint
        self.lock = threading.RLock()  # the cached episode state, references and catalog
        self.motion = threading.Lock()  # one stepper at a time; concurrent waits share the world's time
        # one episode request at a time: the server answers them in turn anyway, and its listen backlog is short, so
        # a burst of concurrent device reads must not open many connections at once
        self.wire = threading.Lock()
        self.devices: dict[str, dict] = {}
        self.steps = 0
        self.max_steps = 0
        self.finished = False
        self.outcome: str | None = None
        self.state: dict = {}
        self.state_steps = -1
        self.moved_elsewhere = False  # the step count rose without a bridge `act`: the agent moved the robot with robo
        self.buffers: dict[str, Buffer] = {}
        self.holds: dict[str, list[float]] = {}
        self.waits: dict[str, threading.Event] = {}
        self.artifacts: dict[str, str] = {}
        self.responses: list[float] = []  # the hand's measured response, metres per unit of action per step
        self.sequence = 0
        # from `robo info` (start)
        self.info: dict = {}
        self.embodiment: dict = {}
        self.task = "task"
        self.max_repeat = 50
        self.step_s = DEFAULT_STEP_S
        self.vision = False
        self.groups: list[dict] = []
        self.arm_group: dict | None = None
        self.grip_group: dict | None = None
        self.arm = ""  # the arm and gripper devices' names, when the robot has them
        self.gripper = ""

    # ---- episode requests ---------------------------------------------------------------------------------------

    def robo(self, req: dict) -> dict:
        with self.wire:  # `sent`: the wall-clock time, so a trajectory can place the request among Kinex's tool calls
            resp = self._send({**req, "via": VIA, "sent": round(time.time(), 3)})
        if not isinstance(resp, dict):
            resp = {"ok": False, "error": "no reply from the episode server"}
        with self.lock:
            self._note(req, resp)
        return resp

    def _note(self, req: dict, resp: dict) -> None:
        """Keep the newest step count, state and ending a reply shows (replies to concurrent requests can arrive in
        any order: an older state never replaces a newer one)."""
        op = req.get("op")
        if not resp.get("ok"):
            m = re.search(r"episode finished \((\w+)\)", str(resp.get("error", "")))
            if m:
                self.finished = True
                self.outcome = self.outcome or m.group(1)
            return
        r = resp.get("result")
        if not isinstance(r, dict):
            return
        steps = r.get("steps") if op == "status" else r.get("steps_used")
        if isinstance(steps, int) and steps >= self.steps:
            self.moved_elsewhere = self.moved_elsewhere or (steps > self.steps and op != "act")
            self.steps = steps
            if isinstance(r.get("state"), dict) and steps >= self.state_steps:
                self.state, self.state_steps = r["state"], steps
        if isinstance(r.get("max_steps"), int):
            self.max_steps = r["max_steps"]
        ended = op in ("done", "give_up") or (op == "status" and r.get("finished"))
        if ended or str(r.get("episode", "")).startswith("finished"):
            self.finished = True
            self.outcome = self.outcome or r.get("outcome")

    def _must(self, req: dict) -> dict:
        resp = self.robo(req)
        if not resp.get("ok"):
            raise BridgeError("robo_error", str(resp.get("error", "the episode server refused the request")))
        return resp["result"]

    # ---- start-up: the catalog ------------------------------------------------------------------------------------

    def start(self) -> None:
        """Read `robo info` and the first observation, and decide the devices."""
        info = self._must({"op": "info"})
        self.info = info
        self.task = str(info.get("task") or "task")
        self.max_steps = int(info.get("max_steps") or 0)
        self.steps = int(info.get("steps_used") or 0)
        self.max_repeat = max(1, int(info.get("max_repeat") or 50))
        emb: dict = info["embodiment"] if isinstance(info.get("embodiment"), dict) else {}
        self.embodiment = emb
        self.step_s = float(emb.get("step_s") or DEFAULT_STEP_S)
        self.vision = info.get("observation_mode") == "vision"
        self.groups = self._groups(info, emb)
        self._observe_state()
        names: set[str] = set()
        self.devices = {"world": {"type": "world", "kind": "world"}}
        names.add("world")
        hand = self.state.get("hand_pos")
        ee = [
            g
            for g in self.groups
            if g.get("mode") == "ee_delta_pos"
            and len(g["components"]) == 3
            and g.get("frame", "world") in ("world", "")
        ]
        grips = [g for g in self.groups if g.get("mode") == "gripper" and len(g["components"]) == 1]
        if len(ee) == 1 and isinstance(hand, list) and len(hand) == 3 and all(_finite(v) for v in hand):
            self.arm_group = ee[0]
            self.arm = self._name(str(ee[0]["name"]).split(".")[0] or "arm", names)
            self.devices[self.arm] = {"type": "joint", "kind": "arm", "start": [float(v) for v in hand]}
            self.holds[self.arm] = [float(v) for v in hand]
            if len(grips) == 1:
                self.grip_group = grips[0]
                self.gripper = self._name(str(grips[0]["name"]).split(".")[-1] or "gripper", names)
                self.devices[self.gripper] = {"type": "gripper", "kind": "gripper"}
                self.holds[self.gripper] = [self._hold(grips[0])[0]]
        for cam in self._cameras(info, emb):
            self.devices[self._name(self._camera_name(cam["camera"]), names)] = {"type": "rgb", "kind": "camera", **cam}

    @staticmethod
    def _groups(info: dict, emb: dict) -> list[dict]:
        action = info.get("action") or {}
        names = list(action.get("names") or [])
        groups = [g for g in emb.get("action_groups") or [] if isinstance(g, dict) and g.get("components")]
        if sum(len(g["components"]) for g in groups) != len(names):  # no usable declaration: one opaque group
            groups = [
                {
                    "name": "action",
                    "components": names,
                    "low": list(action.get("low") or [-1.0] * len(names)),
                    "high": list(action.get("high") or [1.0] * len(names)),
                    "mode": "other",
                    "hold": "zero",
                }
            ]
        return groups

    @staticmethod
    def _hold(g: dict) -> list[float]:
        """A group's command for holding still, as the embodiment declares it (the bridge never sent it one)."""
        if g.get("hold") == "value" and isinstance(g.get("hold_value"), list):
            return [float(v) for v in g["hold_value"]]
        if g.get("hold") == "last" and isinstance(g.get("initial"), list):
            return [float(v) for v in g["initial"]]
        return [0.0] * len(g["components"])

    @staticmethod
    def _name(want: str, taken: set[str]) -> str:
        base = DEVICE_NAME.sub("_", want).strip("_") or "device"
        name, i = base, 2
        while name in taken:
            name, i = f"{base}_{i}", i + 1
        taken.add(name)
        return name

    @staticmethod
    def _camera_name(name: str) -> str:
        return name if "cam" in name.lower() else f"{name}_camera"

    def _observe_state(self) -> None:
        """The state now. On a vision task a plain observe renders and saves every camera's image, so the state comes
        with one small inline frame instead, which writes nothing."""
        req: dict = {"op": "observe"}
        if self.vision:
            req["inline"] = {"format": "png", "width": 8, "height": 8}
        self._must(req)

    def _cameras(self, info: dict, emb: dict) -> list[dict]:
        """Each camera's name, size and, where `robo info` gives it, calibration."""
        out = []
        if self.vision:
            for c in info.get("cameras") or []:
                if not isinstance(c, dict) or not c.get("name") or not c.get("width") or not c.get("height"):
                    continue
                cam = {"camera": str(c["name"]), "width": int(c["width"]), "height": int(c["height"])}
                if isinstance(c.get("projection"), list) and len(c["projection"]) == 3:
                    cam["projection"], cam["mount"] = calibration(c["projection"])
                out.append(cam)
            return out
        names = [str(c["name"]) for c in (emb.get("sensors") or {}).get("cameras") or [] if c.get("name")]
        for name in dict.fromkeys(names):
            resp = self.robo({"op": "observe", "inline": {"cameras": [name], "format": "png"}})
            img = ((resp.get("result") or {}).get("images") or {}).get(name) if resp.get("ok") else None
            if not img:
                continue  # not one of the task's cameras
            w, h = png_size(base64.b64decode(img))
            out.append({"camera": name, "width": w, "height": h})
        return out

    # ---- time -----------------------------------------------------------------------------------------------------

    def now_s(self) -> float:
        return self.steps * self.step_s

    def budget(self) -> dict:
        return {"used_s": self.steps * self.step_s, "max_s": self.max_steps * self.step_s if self.max_steps else None}

    def _ending(self) -> None:
        """Learn why the episode ended: a motion's reply says only that it did; `status` gives the outcome."""
        if self.finished and self.outcome is None:
            self.robo({"op": "status"})

    def simulation(self, verdict: bool = False) -> dict:
        """RoboEnv's simulation status. Robo Use never tells the agent whether it succeeded: `success` stays null."""
        self._ending()
        out = {
            "schema": "roboenv/simulation-status/1",
            "session": self.session,
            "generation": GENERATION,
            "state": "terminal" if self.finished else "ready",
            "terminal": self.finished,
            "reason": self.outcome,
            "budget": {"used": self.steps, "max": self.max_steps or None, "unit": "steps", **self.budget()},
            "simulation_time_s": self.now_s(),
            "capabilities": {"terminal_feedback": True, "bounded_episodes": True},
        }
        if verdict:
            out["success"] = None
        return out

    # ---- state ----------------------------------------------------------------------------------------------------

    def fresh_state(self) -> dict:
        """The latest state. While a wait steps the robot, its replies keep the cache current; otherwise `status` (no
        render) shows whether anyone moved the robot since, and only then is it observed again."""
        if not (self.motion.locked() or self.finished):
            self.robo({"op": "status"})
            with self.lock:
                stale = not self.finished and self.state_steps != self.steps
            if stale:
                try:
                    self._observe_state()
                except BridgeError:  # the episode ended meanwhile: the last state stands
                    pass
            self._resync()
        with self.lock:
            return dict(self.state)

    def _resync(self) -> None:
        """After the robot moved without the bridge (the agent used `robo`), hold the arm where it is now rather than
        pull it back to the reference it had. The gripper keeps its last command: the bridge cannot see the one `robo`
        sent."""
        with self.lock:
            if not self.moved_elsewhere or self.state_steps != self.steps:
                return
            self.moved_elsewhere = False
            hand = self.state.get("hand_pos")
            if self.arm and isinstance(hand, list) and len(hand) == 3:
                self.buffers.pop(self.arm, None)
                self.holds[self.arm] = [float(v) for v in hand]

    # ---- readings -------------------------------------------------------------------------------------------------

    def _arm_reading(self, state: dict) -> dict:
        hand = state.get("hand_pos")
        if isinstance(hand, list) and len(hand) == 3:
            pos, faults = [float(v) for v in hand], []
        else:  # the task hides the hand now: the last reference, and a fault that says so
            pos, faults = list(self.holds.get(self.arm, [0.0, 0.0, 0.0])), [{"code": "no_feedback"}]
        return {"positions": pos, "velocities": [], "efforts": [], "faults": faults, "timestamp": self.now_s()}

    def _gripper_reading(self, state: dict) -> dict:
        out: dict[str, Any] = {"aperture_m": None, "faults": [], "timestamp": self.now_s()}
        if "gripper_open" in state:
            out["gripper_open"] = state["gripper_open"]  # what `robo observe` reports, in the task's own units
        buf = self.buffers.get(self.gripper)
        out["command"] = (buf.at(self.now_s()) if buf else self.holds[self.gripper])[0]
        return out

    # ---- device calls ---------------------------------------------------------------------------------------------

    def describe(self, name: str) -> dict:
        d = self.devices.get(name)
        if d is None:
            raise BridgeError("unknown_device", f"unknown device: {name!r}")
        actions = {
            "world": ("read", "wait"),
            "arm": ("read", "write", "stop"),
            "gripper": ("read", "write", "stop"),
            "camera": ("read",),
        }[d["kind"]]
        table: dict[str, dict[str, Any]] = {
            a: {"supported": True, "read_only": a in READ_ACTIONS} for a in (*actions, "load", "unload", "status")
        }
        if d["kind"] == "arm":  # computed by the Kinex driver from the profile, as RoboEnv's exported drivers do
            for a in ("fk", "ik"):
                table[a] = {"supported": False, "read_only": True, "reason": "computed by the driver from the profile"}
        return {
            "schema_version": CONTRACT,
            "name": name,
            "type": d["type"],
            "actions": table,
            "execution": {"mode": "stepped", "interruptible": d["kind"] in ("arm", "gripper", "world")},
            "implementation": "robouse " + VIA,
        }

    def call(self, name: str, action: str, args: dict, request_id: str) -> dict:
        d = self.devices.get(name)
        if d is None:
            raise BridgeError("unknown_device", f"unknown device: {name!r}")
        if not isinstance(args, dict):
            raise BridgeError("invalid_args", "args must be an object")
        kind = d["kind"]
        if action in ("load", "unload", "status"):
            if args:
                raise BridgeError("invalid_args", f"{action} takes no arguments")
            if action == "unload" and kind in ("arm", "gripper"):
                self._stop(name)
            return {"load": {"loaded": True}, "unload": {"unloaded": True}}.get(
                action, {"ready": True, "serving": True, "terminal": self.finished}
            )
        if kind == "world" and action == "read":
            if args:
                raise BridgeError("invalid_args", "world read takes no arguments")
            self.fresh_state()
            return {"time_s": self.now_s(), "budget": self.budget()}
        if kind == "world" and action == "wait":
            if set(args) != {"duration_s"} or not _finite(args["duration_s"]) or args["duration_s"] < 0:
                raise BridgeError("invalid_args", "wait takes duration_s, a non-negative number of seconds")
            return self.wait(float(args["duration_s"]), request_id)
        if kind in ("arm", "gripper") and action == "read":
            if args:
                raise BridgeError("invalid_args", "read takes no arguments")
            state = self.fresh_state()
            return self._arm_reading(state) if kind == "arm" else self._gripper_reading(state)
        if kind in ("arm", "gripper") and action == "write":
            return self.write(name, kind, args, request_id)
        if kind in ("arm", "gripper") and action == "stop":
            if args:
                raise BridgeError("invalid_args", "stop takes no arguments")
            self._stop(name)
            return {"stopped": True, "behavior": "hold", "affected_devices": [name]}
        if kind == "camera" and action == "read":
            if set(args) - {"output"}:  # the image format is the client's choice (the driver converts the file)
                raise BridgeError("invalid_args", "camera read takes no arguments")
            return self.capture(name, d)
        raise BridgeError("unsupported_action", f"{name} ({d['type']}) has no action {action!r}")

    def write(self, name: str, kind: str, args: dict, request_id: str) -> dict:
        if set(args) != {"actions", "duration_s"}:
            raise BridgeError("invalid_args", "write takes actions and duration_s")
        if not _finite(args["duration_s"]) or args["duration_s"] <= 0:
            raise BridgeError("invalid_args", "duration_s must be a positive number")
        raw = args["actions"]
        if not isinstance(raw, list) or not raw:
            raise BridgeError("invalid_args", "actions must be a nonempty list")
        if kind == "arm":
            actions = [_vector(a, 3, "each arm target [x, y, z]") for a in raw]
        else:
            vals = _vector(raw, len(raw), "gripper actions")
            g = self.grip_group or {}
            lo, hi = float((g.get("low") or [-1])[0]), float((g.get("high") or [1])[0])
            if any(v < lo or v > hi for v in vals):
                raise BridgeError("invalid_args", f"gripper targets must be within [{lo:g}, {hi:g}]")
            actions = [[v] for v in vals]
        self.fresh_state()
        with self.lock:
            if self.finished:
                raise self._finished_error()
            self.buffers[name] = Buffer(actions, float(args["duration_s"]), self.now_s(), request_id)
            state = dict(self.state)
        reading = self._arm_reading(state) if kind == "arm" else self._gripper_reading(state)
        return {"execution_id": request_id, "state": reading}

    def _stop(self, name: str) -> None:
        """Hold where the actuator is now: the arm at its measured position, the gripper at its current command."""
        with self.lock:
            buf = self.buffers.pop(name, None)
            if name == self.arm:
                hand = self.state.get("hand_pos")
                if isinstance(hand, list) and len(hand) == 3:
                    self.holds[name] = [float(v) for v in hand]
            elif buf is not None:
                self.holds[name] = list(buf.at(self.now_s()))

    def cancel(self, execution_id: str) -> dict:
        """Stop what one submission still owns: a reference buffer (the actuator then holds), or a wait in progress."""
        with self.lock:
            ev = self.waits.get(execution_id)
            owned = [n for n, b in self.buffers.items() if b.owner == execution_id]
        if ev is not None:
            ev.set()
            return {"stopped": False}
        for n in owned:
            self._stop(n)
        return {"stopped": bool(owned)}

    def _finished_error(self) -> BridgeError:
        self._ending()
        return BridgeError(
            "episode_finished",
            f"the episode has finished ({self.outcome or 'ended'}); devices can still be read",
            {**self.simulation(), "effects": "none"},
        )

    def capture(self, name: str, d: dict) -> dict:
        resp = self.robo({"op": "observe", "image": True, "camera": d["camera"]})
        if not resp.get("ok"):
            raise self._finished_error() if self.finished else BridgeError("robo_error", str(resp.get("error")))
        path = resp["result"].get("image_path")
        path = path[0] if isinstance(path, list) else path
        if not isinstance(path, str) or not os.path.isfile(path):
            raise BridgeError("capture_unavailable", "the episode server returned no image")
        ident = os.urandom(8).hex()
        with self.lock:
            self.artifacts[ident] = path
        return {"file": path, "artifact": f"{ident}.png", "timestamp": self.now_s(), "camera": d["camera"]}

    # ---- stepping -------------------------------------------------------------------------------------------------

    def wait(self, duration_s: float, request_id: str) -> dict:
        """Run the episode for `duration_s` of device time: whole control steps, each sending the actuators' references.
        Concurrent waits share the world's time (each ends when its own end time has passed), and a cancelled wait
        returns at the next step."""
        ev = threading.Event()
        self.fresh_state()  # moves made with robo since the last call: the arm holds where they left it
        with self.lock:
            self.waits[request_id] = ev
            begin = self.steps
            end = begin + max(0, round(duration_s / self.step_s))
        try:
            with self.motion:
                while True:
                    with self.lock:
                        if self.finished or ev.is_set() or self.steps >= end:
                            break
                        action, repeat, arm_part = self._command(end - self.steps)
                        before = list(self.state.get("hand_pos") or [])
                    resp = self.robo({"op": "act", "action": action, "repeat": repeat})
                    if not resp.get("ok"):
                        if self.finished:
                            break
                        raise BridgeError("robo_error", str(resp.get("error")))
                    if arm_part is not None:
                        self._learn(arm_part, before)
        finally:
            with self.lock:
                self.waits.pop(request_id, None)
        self._ending()
        with self.lock:
            out = {"time_s": self.now_s(), "waited_s": max(0, self.steps - begin) * self.step_s}
            if self.finished:
                out["terminal"] = True
            return out

    def _command(self, remaining: int) -> tuple[list[float], int, list[float] | None]:
        """The next act request (action, repeat), and the arm's part of the action when one step moves the hand."""
        t_next = (self.steps + 1) * self.step_s
        action: list[float] = []
        moving = False
        arm_part: list[float] | None = None
        for g in self.groups:
            lo = [float(v) for v in g.get("low") or [-1.0] * len(g["components"])]
            hi = [float(v) for v in g.get("high") or [1.0] * len(g["components"])]
            if g is self.arm_group:
                buf = self.buffers.get(self.arm)
                ref = buf.at(t_next) if buf else self.holds[self.arm]
                hand = self.state.get("hand_pos")
                if not (isinstance(hand, list) and len(hand) == 3):
                    action += [0.0, 0.0, 0.0]
                    continue
                err = [r - float(p) for r, p in zip(ref, hand, strict=True)]
                if (buf and buf.moving(t_next)) or max(abs(e) for e in err) > HOLD_TOL_M:
                    moving = True
                    response = self.response()
                    gain = CATCH_UP / response if response else MOVE_TO_GAIN
                    arm_part = [_clip(gain * e, a, b) for e, a, b in zip(err, lo, hi, strict=True)]
                    action += arm_part
                else:
                    action += [0.0, 0.0, 0.0]
            elif g is self.grip_group:
                buf = self.buffers.get(self.gripper)
                if buf and buf.moving(t_next):
                    moving = True
                ref = buf.at(t_next) if buf else self.holds[self.gripper]
                action += [_clip(v, a, b) for v, a, b in zip(ref, lo, hi, strict=True)]
            else:
                action += self._hold(g)
        return action, (1 if moving else min(remaining, self.max_repeat)), arm_part

    def response(self) -> float | None:
        """The hand's measured response, metres per unit of action per step (the median of recent moves)."""
        return max(MIN_RESPONSE, statistics.median(self.responses)) if len(self.responses) >= 3 else None

    def _learn(self, action: list[float], before: list) -> None:
        with self.lock:
            after = self.state.get("hand_pos")
            if not (isinstance(after, list) and len(after) == 3 and len(before) == 3):
                return
            move = [float(a) - float(b) for a, b in zip(after, before, strict=True)]
            aa = _dot(action, action)
            if aa < 1e-4 or math.sqrt(_dot(move, move)) < MIN_MOVE_M:
                return
            r = _dot(move, action) / aa
            if r > 0:
                self.responses = [*self.responses, r][-SCALE_SAMPLES:]

    # ---- protocol -------------------------------------------------------------------------------------------------

    def handle(self, raw: Any) -> dict:
        """One request envelope to its reply."""
        req = raw if isinstance(raw, dict) else {}
        rid = req.get("request_id")
        base = {
            "protocol": PROTOCOL,
            "session": self.session,
            "generation": GENERATION,
            "request_id": rid if isinstance(rid, str) else None,
        }
        try:
            self._check(req)
            result = self._op(str(req["op"]), req["args"], str(rid))
            return {**base, "ok": True, "result": result}
        except BridgeError as e:
            err = {"code": e.code, "message": e.message, "retryable": False}
            if e.details is not None:
                err["details"] = e.details
            return {**base, "ok": False, "error": err}
        except Exception as e:  # noqa: BLE001 - a bounded error goes back to the client
            return {
                **base,
                "ok": False,
                "error": {"code": "internal_error", "message": f"{type(e).__name__}: {e}"[:500], "retryable": False},
            }

    def _check(self, req: dict) -> None:
        missing = {"protocol", "session", "generation", "request_id", "deadline_s", "op", "args"} - set(req)
        if missing:
            raise BridgeError("invalid_request", f"request is missing {', '.join(sorted(missing))}")
        if req["protocol"] != PROTOCOL:
            raise BridgeError("protocol_mismatch", f"expected protocol {PROTOCOL!r}")
        if not isinstance(req["session"], str) or not hmac.compare_digest(req["session"], self.session):
            raise BridgeError("session_mismatch", "not this episode's session")
        if req["generation"] != GENERATION:
            raise BridgeError("episode_changed", "not this episode's generation")
        if not isinstance(req["request_id"], str) or not IDENTIFIER.match(req["request_id"]):
            raise BridgeError("invalid_request", "request_id must be a RoboEnv identifier")
        if not isinstance(req["args"], dict):
            raise BridgeError("invalid_request", "args must be an object")

    def _op(self, op: str, args: dict, rid: str) -> Any:
        if op == "health":
            return {"worker": {"state": "ready"}, "device_service": {"ready": True, "contract": CONTRACT}}
        if op == "environment.describe":
            return {
                "task": {"id": self.task, "instruction": "", "native_instruction": "", "context": {}},
                "devices": sorted(self.devices),
                "device_contract": CONTRACT,
                "session": self.session,
                "generation": GENERATION,
                "execution": {"mode": "stepped", "artifact_transport": "shared-filesystem"},
            }
        if op == "devices.list":
            return {"schema_version": CONTRACT, "devices": [self.describe(n) for n in sorted(self.devices)]}
        if op == "devices.describe":
            if set(args) != {"device"}:
                raise BridgeError("invalid_args", "expected device name only")
            return self.describe(args["device"])
        if op == "devices.call":
            if set(args) != {"device", "action", "args"}:
                raise BridgeError("invalid_args", "expected exactly device, action and args")
            with self.lock:
                self.sequence += 1
                seq = self.sequence
            data = self.call(str(args["device"]), str(args["action"]), args["args"], rid)
            out = {
                "schema_version": CONTRACT,
                "device": args["device"],
                "action": args["action"],
                "sequence": seq,
                "read_only": args["action"] in READ_ACTIONS,
                "data": data,
                "budget": {"used": self.steps, "max": self.max_steps or None, "unit": "steps"},
            }
            if self.finished:
                out["simulation"] = self.simulation()
            return out
        if op == "devices.cancel":
            if set(args) != {"execution_id"} or not isinstance(args["execution_id"], str):
                raise BridgeError("invalid_args", "cancel requires a nonempty execution_id")
            return {"data": self.cancel(args["execution_id"])}
        if op == "simulation.status":
            if args:
                raise BridgeError("invalid_args", "simulation.status takes no arguments")
            self.fresh_state()
            return self.simulation()
        if op == "simulation.stop":
            if args:
                raise BridgeError("invalid_args", "simulation.stop takes no arguments")
            if not self.finished:
                self.robo({"op": "done", "text": "simulation.stop through the RoboEnv bridge"})
            return self.simulation(verdict=True)
        raise BridgeError("unsupported_op", f"operation {op!r} is not offered")

    # ---- the Kinex workspace --------------------------------------------------------------------------------------

    def profiles(self) -> dict[str, dict]:
        """Each device's Kinex profile (devices/<name>/profile.yaml)."""
        meta = {"created_at": _now_iso(), "updated_at": _now_iso()}
        out = {}
        for name, d in self.devices.items():
            kind = d["kind"]
            access: dict[str, Any] = {"source": "introspected", "method": "introspection"}
            if kind == "world":
                access["connection"] = {"kind": "url", "url": self.endpoint, "device": name}
                # a wait steps the simulator: allow for slow simulators and long waits
                access["driver"] = {"entry": "driver.py", "actions": ["read", "wait", "load", "unload", "status"]}
                access["driver"].update(persistent=True, timeout_s=1800)
                out[name] = {
                    "name": name,
                    "type": "world",
                    "loaded": True,
                    "access": access,
                    "intrinsics": {"source": "introspected", "method": "introspection", "bounds": None, "surfaces": []},
                    "meta": meta,
                }
            elif kind == "arm":
                start = d["start"]
                joints = [
                    {
                        "name": axis,
                        "type": "prismatic",
                        "limits": {"min": s - ARM_SPAN_M, "max": s + ARM_SPAN_M},
                        "max_velocity": None,
                        "max_effort": None,
                    }
                    for axis, s in zip("xyz", start, strict=True)
                ]
                identity = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
                chain: list[dict] = [
                    {"origin": identity, "joint": i, "axis": axis, "anchor": [0.0, 0.0, 0.0], "reference": 0.0}
                    for i, axis in enumerate(([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]))
                ]
                chain.append({"origin": identity})
                access["connection"] = {"kind": "url", "url": self.endpoint, "device": name}
                access["driver"] = {
                    "entry": "driver.py",
                    "actions": ["read", "write", "stop", "load", "unload", "status", "fk", "ik"],
                    "persistent": True,
                    "timeout_s": 120,
                }
                out[name] = {
                    "name": name,
                    "type": "joint",
                    "loaded": True,
                    "access": access,
                    "intrinsics": {
                        "source": "introspected",
                        "method": "introspection",
                        "frames": {},
                        "model": {"format": "serial_chain", "joints": joints, "chain": chain},
                        # the hand frame keeps the world's orientation: the bridge moves the hand, never turns it
                        "kinematics": {
                            "frame": "hand",
                            "fk": "numerical",
                            "ik": {
                                "backend": "numerical",
                                "method": "damped_least_squares",
                                "position_tolerance_m": 0.0005,
                                "rotation_tolerance_rad": 0.001,
                                "max_iterations": 100,
                                "damping": 0.001,
                            },
                            "frame_to_reported": identity,
                        },
                        "home": dict(zip("xyz", start, strict=True)),
                        "control": {"mode": "position", "limit_handling": "native"},
                        "feedback": {"velocities": False, "efforts": False},
                        "stop": {"behavior": "hold", "affected_devices": [name]},
                    },
                    "extrinsics": {
                        "source": "introspected",
                        "method": "introspection",
                        "mount": {
                            "parent": "world",
                            "parent_frame": "world",
                            "translation_m": [0.0, 0.0, 0.0],
                            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                        },
                    },
                    "meta": meta,
                }
            elif kind == "gripper":
                access["connection"] = {"kind": "url", "url": self.endpoint, "device": name}
                access["driver"] = {
                    "entry": "driver.py",
                    "actions": ["read", "write", "stop", "load", "unload", "status"],
                    "persistent": True,
                    "timeout_s": 120,
                }
                g = self.grip_group or {}
                lo, hi = float((g.get("low") or [-1])[0]), float((g.get("high") or [1])[0])
                out[name] = {
                    "name": name,
                    "type": "gripper",
                    "loaded": True,
                    "access": access,
                    "intrinsics": {
                        "source": "introspected",
                        "method": "introspection",
                        "aperture_m": None,
                        "control": {
                            "mode": "position",
                            "units": "normalized",
                            "bounds": {"min": lo, "max": hi},
                            "resolution": None,
                            "open_target": lo,
                            "close_target": hi,
                            "speed": None,
                        },
                        "feedback": {"aperture_m": False},
                        "stop": {"behavior": "hold", "affected_devices": [name]},
                    },
                    "extrinsics": {
                        "source": "introspected",
                        "method": "introspection",
                        "mount": {
                            "parent": self.arm,
                            "parent_frame": "hand",
                            "translation_m": [0.0, 0.0, 0.0],
                            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                        },
                    },
                    "meta": meta,
                }
            else:
                access["connection"] = {"kind": "url", "url": self.endpoint, "camera": name}
                access["driver"] = {
                    "entry": "driver.py",
                    "actions": ["read", "load", "unload", "status"],
                    "persistent": True,
                    "timeout_s": 120,
                }
                color = {
                    "width": d["width"],
                    "height": d["height"],
                    "fps": None,
                    "pixel_format": "rgb8",
                    "image_format": "png",
                    "projection": d.get("projection", "???"),
                    "distortion": {"model": "none"},  # a simulator's pinhole renderer
                    "fov": "???",  # Kinex derives it from the projection
                }
                out[name] = {
                    "name": name,
                    "type": "rgb",
                    "loaded": True,
                    "access": access,
                    "intrinsics": {"source": "introspected", "method": "introspection", "color": color},
                    "extrinsics": {"source": "introspected", "method": "introspection", "mount": d.get("mount", "???")},
                    "meta": meta,
                }
        return out

    def manifest(self) -> dict:
        """The robot's workspace.yaml."""
        kinds = {"arm": "arm", "bimanual": "arm", "mobile_manipulator": "mobile", "quadruped": "quadruped"}
        kinds["humanoid"] = "humanoid"
        backend = str(self.info.get("backend") or "robouse")
        return {
            "identity": {
                "source": "introspected",
                "id": self.task,
                "name": str(self.embodiment.get("name") or self.task),
                "platform": "sim",
                "kind": kinds.get(str(self.embodiment.get("kind")), "other"),
                "model": str(self.embodiment.get("name") or "???"),
            },
            "sim": {
                "source": "introspected",
                "simulator": backend,
                "notes": f"Robo Use episode of task {self.task}, served through robouse's RoboEnv-compatible bridge; "
                f"one control step is {self.step_s:g} s of device time",
            },
            "devices": {"source": "introspected"},
            "safety": {
                "source": "default",
                "max_cartesian_velocity": None,
                "max_joint_velocity": None,
                "keep_out_zones": [],
            },
            "meta": {"created_at": _now_iso(), "updated_at": _now_iso()},
        }

    def catalog(self) -> str:
        """One line per device: what the agent was offered (the bridge prints it to the agent's stderr, which the trial
        keeps, since the workspace with the profiles is removed after the trial)."""
        lines = []
        for name, d in self.devices.items():
            extra = ""
            if d["kind"] == "arm":
                extra = f" from {self.arm_group['name'] if self.arm_group else '?'}, hand at {d['start']}"
            elif d["kind"] == "gripper":
                extra = f" from {self.grip_group['name'] if self.grip_group else '?'}"
            elif d["kind"] == "camera":
                calib = "calibrated" if "projection" in d else "no calibration"
                extra = f" from camera {d['camera']}, {d['width']}x{d['height']}, {calib}"
            lines.append(f"  {name}: {d['type']}{extra}")
        head = f"roboenv bridge: task {self.task}, {self.step_s:g} s per step, {self.max_steps} steps, devices:"
        return "\n".join([head, *lines])

    def write_kinex(self, root: Path, driver: str) -> None:
        """Write the Kinex workspace: the manifest, and each device's profile, driver and connection (endpoint and
        session; the world's also has the step length)."""
        devices = root / "devices"
        devices.mkdir(parents=True, exist_ok=True)
        (root / "workspace.yaml").write_text(json.dumps(self.manifest(), indent=2) + "\n")
        for name, prof in self.profiles().items():
            d = devices / name
            d.mkdir(exist_ok=True)
            (d / "profile.yaml").write_text(json.dumps(prof, indent=2) + "\n")
            (d / "driver.py").write_text(driver)
            conn = {
                "endpoint": self.endpoint,
                "session": self.session,
                "generation": GENERATION,
                "device": name,
                "kind": self.devices[name]["kind"],
                "step_s": self.step_s,
            }
            (d / "connection.json").write_text(json.dumps(conn, indent=2) + "\n")
            (d / "connection.json").chmod(0o600)


# ---- HTTP -----------------------------------------------------------------------------------------------------------


def port_of(server: Any) -> int:
    return int(server.server_address[1])


def http_server(bridge: Bridge, host: str, port: int) -> ThreadingHTTPServer:
    """The bridge on loopback HTTP, as `roboenv launch` serves its devices."""
    artifact_path = re.compile(r"^/artifacts/([A-Za-z0-9_.:@+-]+)/(\d+)/([0-9a-f]{16})\.png$")

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a: Any) -> None:
            pass

        def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self) -> bool:
            # a browser page cannot reach it, and a name that resolves elsewhere (DNS rebinding) is refused
            if self.headers.get("Origin") is not None:
                self._send(403, b'{"error": "browser requests are not served"}\n')
                return False
            if self.headers.get("Host") != f"{host}:{port_of(self.server)}":
                self._send(403, b'{"error": "use the advertised loopback endpoint"}\n')
                return False
            return True

        def do_GET(self) -> None:
            if not self._allowed():
                return
            if self.path == "/":
                self._send(200, json.dumps({"protocol": PROTOCOL, "generation": GENERATION}).encode() + b"\n")
                return
            m = artifact_path.match(self.path)
            with bridge.lock:
                path = bridge.artifacts.get(m.group(3)) if m else None
            if (
                not m
                or not hmac.compare_digest(m.group(1), bridge.session)
                or int(m.group(2)) != GENERATION
                or not path
            ):
                self._send(404, b'{"error": "unknown artifact"}\n')
                return
            self._send(200, Path(path).read_bytes(), "image/png")

        def do_POST(self) -> None:
            if not self._allowed():
                return
            if self.path != "/":
                self._send(404, b'{"error": "unknown endpoint"}\n')
                return
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= MAX_BODY:
                self._send(413, b'{"error": "request size out of range"}\n')
                return
            try:
                raw = json.loads(self.rfile.read(n))
            except ValueError:
                raw = None
            reply = bridge.handle(raw)
            self._send(200, json.dumps(reply, allow_nan=False).encode() + b"\n")

    return ThreadingHTTPServer((host, port), H)


# ---- running it -----------------------------------------------------------------------------------------------------


def _client() -> Any:
    """The `robo` client module: robo_cli.py next to this script (the workspace copy), else the installed package's."""
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isfile(os.path.join(here, "robo_cli.py")):
        sys.path.insert(0, here)
        import robo_cli

        return robo_cli
    from robouse import agent_cli

    return agent_cli


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    own = args[: args.index("--run")] if "--run" in args else args
    if any(a in ("-h", "--help") for a in own) or "--run" not in args:
        print(__doc__)
        return 0 if "--run" in args else 2
    run = args[args.index("--run") + 1 :]
    if run[:1] == ["--"]:
        run = run[1:]
    kinex_dir = Path(own[own.index("--kinex-dir") + 1]) if "--kinex-dir" in own else Path.cwd() / ".kinex"
    sock = os.environ.get("ROBOUSE_SOCKET", "")
    endpoint = os.environ.get("ROBOENV_ENDPOINT", "")
    session = os.environ.get("ROBOENV_SESSION", "")
    url = urlsplit(endpoint)
    if not (sock and session and url.scheme == "http" and url.hostname == "127.0.0.1" and url.port):
        print("roboenv bridge: needs ROBOUSE_SOCKET, ROBOENV_SESSION and ROBOENV_ENDPOINT=http://127.0.0.1:PORT")
        return 2
    client = _client()
    bridge = Bridge(lambda req: client._send(req, path=sock), session, endpoint)
    bridge.start()
    driver = Path(__file__).with_name("kinex_driver.py")
    bridge.write_kinex(kinex_dir, driver.read_text())
    print(bridge.catalog(), file=sys.stderr, flush=True)
    srv = http_server(bridge, "127.0.0.1", url.port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        exe = shutil.which(run[0]) or run[0]
        return subprocess.call([exe, *run[1:]])
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
