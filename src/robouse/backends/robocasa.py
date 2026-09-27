"""RoboCasa backend: household kitchen scenes (RoboCasa365 on robosuite 1.5) with a Franka Panda on a mobile base.

RoboCasa pins MuJoCo 3.3.1, numpy 2.2 and robosuite 1.5, which conflict with the main robouse environment (robosuite 1.4
for LIBERO), so the simulation runs in its own virtualenv (default ~/.cache/robouse/robocasa-venv, override with
ROBOUSE_ROBOCASA_PYTHON) as a subprocess (robocasa_worker.py). This module is the bridge: it starts the worker, forwards
steps, observations, renders and the success check. Setup: docs/suites/robocasa.md.

Robot: RoboCasa's default PandaOmron (a Franka Panda arm on an Omron mobile base with a torso lift). The base and torso
stay where RoboCasa's task initialisation puts them (facing the target fixture); only the arm and gripper move.

Action [DX, DY, DZ, GRIP] (each in [-1, 1]): DX/DY/DZ move the gripper by 2 cm per unit per step along the WORLD axes
(converted to the base frame for robosuite's OSC_POSE controller, orientation held); one step = 50 ms (20 Hz, RoboCasa's
control rate). GRIP: 0 keeps the fingers, > 0 closes, -f opens to fraction f (-1 fully open).
Observation: hand_pos (end-effector, world m), gripper_open (0..1), the robot base position and forward direction, and
task-specific fields (object and fixture handle/button positions, fixture state). Success is RoboCasa's own
`_check_success()` for the task, judged after `robo done` and a 10-step hold.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

from .base import ActionSpec, Backend, StepInfo

WORKER = Path(__file__).with_name("robocasa_worker.py")
DEFAULT_PY = Path.home() / ".cache" / "robouse" / "robocasa-venv" / "bin" / "python"

# task id -> RoboCasa env, kitchen layout/style (test split styles 1-10 need no AI-generated textures), seed, features
TASKS: dict[str, dict] = {
    "robocasa-pick-place-counter-to-sink": dict(env="PickPlaceCounterToSink", layout=1, style=1, seed=0, features=["object", "sink"], max_steps=500),
    "robocasa-start-coffee-machine": dict(env="StartCoffeeMachine", layout=1, style=1, seed=0, features=["coffee"], max_steps=300,
                                          tool="forward"),
    "robocasa-turn-on-microwave": dict(env="TurnOnMicrowave", layout=1, style=1, seed=0, features=["microwave"], max_steps=300),
    "robocasa-turn-on-sink-faucet": dict(env="TurnOnSinkFaucet", layout=1, style=1, seed=0, features=["faucet"], max_steps=300),
    "robocasa-close-drawer": dict(env="CloseDrawer", layout=1, style=1, seed=0, features=["drawer"], max_steps=300),
    "robocasa-open-drawer": dict(env="OpenDrawer", layout=1, style=1, seed=0, features=["drawer"], max_steps=400),
    "robocasa-close-cabinet": dict(env="CloseCabinet", layout=1, style=1, seed=0, features=["door"], max_steps=300),
    "robocasa-close-microwave": dict(env="CloseMicrowave", layout=1, style=1, seed=0, features=["door"], max_steps=300),
}


class RobocasaBackend(Backend):
    name = "robocasa"
    image_flipped = False

    def __init__(self, spec: dict):
        env = spec.get("env") or spec.get("id")
        if env not in TASKS:
            raise KeyError(f"unknown robocasa task {env!r}")
        self.task_id = env
        self.task = TASKS[env]
        self.max_steps = int(spec.get("max_steps", self.task.get("max_steps", 400)))
        self.camera = spec.get("camera", "robot0_agentview_center")
        self.render_size = tuple(spec.get("render_size", (384, 288)))
        self._grip = 0.0
        self.action_spec = ActionSpec(
            names=["DX", "DY", "DZ", "GRIP"], low=[-1.0] * 4, high=[1.0] * 4,
            doc="DX/DY/DZ move the gripper by 2 cm per unit per step along world x/y/z; GRIP: 0 keeps the fingers, > 0 closes, "
                "-f opens to fraction f (-1 fully open). One step = 50 ms.")
        py = os.environ.get("ROBOUSE_ROBOCASA_PYTHON", str(DEFAULT_PY))
        if not Path(py).exists():
            raise RuntimeError(f"RoboCasa virtualenv not found at {py}; see docs/suites/robocasa.md")
        self.proc = subprocess.Popen([py, str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL if os.environ.get("ROBOUSE_ROBOCASA_QUIET", "1") == "1" else None)
        self._state = None
        self._success = False

    def _call(self, cmd: str, **kw):
        self.proc.stdin.write((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("RoboCasa worker exited")
        hdr = json.loads(line)
        if not hdr.get("ok"):
            raise RuntimeError(hdr.get("error"))
        if cmd == "render":
            data = self.proc.stdout.read(hdr["nbytes"])
            return np.frombuffer(data, dtype=np.uint8).reshape(kw["height"], kw["width"], 3)
        return hdr["result"]

    def reset(self, seed: int) -> None:
        t = self.task
        self.meta = self._call("make", env_name=t["env"], layout=t["layout"], style=t["style"], seed=int(t.get("seed", seed)),
                               tool=t.get("tool", "down"))
        self._state = None

    def step(self, action) -> StepInfo:
        r = self._call("step", action=[float(x) for x in np.asarray(action, dtype=float)[:4]])
        self._state = None
        self._success = bool(r["success"])
        return StepInfo(success=self._success)

    def observe(self) -> dict:
        if self._state is None:
            st = self._call("observe", features=self.task["features"])
            st["task_instruction"] = self.meta.get("lang", "")
            self._state = st
        return dict(self._state)

    def hand_pos(self) -> np.ndarray:
        return np.asarray(self.observe()["hand_pos"], dtype=float)

    def skills(self) -> list[str]:
        return ["move_to", "grip"]

    def success(self) -> bool:
        return bool(self._call("success")["success"])

    def render(self, width: int | None = None, height: int | None = None) -> np.ndarray:
        w, h = (width, height) if width and height else self.render_size
        return self._call("render", camera=self.camera, width=int(w), height=int(h))

    def close(self) -> None:
        try:
            self.proc.stdin.write(b'{"cmd": "close"}\n')
            self.proc.stdin.flush()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def oracle_main(env: str) -> None:
    from .robocasa_oracles import run

    run(env)
