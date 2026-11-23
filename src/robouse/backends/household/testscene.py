"""A trivial procedural scene package for the backend's tests (format `household-episode` 1.0.0): a table, a 4 cm cube
on it, a target pad, a goal plugin (the cube rests on the pad) and an optional behaviour plugin (a lamp lights while
the cube is on the pad).

    python -m robouse.backends.household.testscene <dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .package import write_files_map

TABLE_TOP = 0.75
CUBE_HALF = 0.02
CUBE_POS = (0.55, -0.15, TABLE_TOP + CUBE_HALF)
PLACE_POS = (0.55, 0.15, TABLE_TOP)
HOME = [0.0, -1.10, 0.0, -2.10, 0.0, 1.50, 1.5707963]

SCENE = f"""<mujoco model="neutral">
  <asset>
    <texture name="room/grid" type="2d" builtin="checker" rgb1=".55 .55 .55" rgb2=".45 .45 .45" width="256"
             height="256"/>
    <material name="room/floor" texture="room/grid" texrepeat="8 8"/>
  </asset>
  <worldbody>
    <light name="room/sun" pos="0 0 3" dir="0 0 -1" diffuse=".8 .8 .8" castshadow="true"/>
    <body name="room">
      <geom name="room/floor" type="plane" size="4 4 .05" material="room/floor"/>
    </body>
    <body name="table" pos="0.6 0 {TABLE_TOP / 2:.4f}">
      <geom name="table/top" type="box" size="0.4 0.6 {TABLE_TOP / 2:.4f}" rgba=".6 .45 .3 1"
            friction="0.8 0.005 0.0001"/>
      <geom name="table/lamp" type="sphere" size="0.02" pos="0.3 0.5 {TABLE_TOP / 2 + 0.02:.4f}" rgba=".2 .2 .2 1"
            contype="0" conaffinity="0"/>
    </body>
    <body name="pad" pos="{PLACE_POS[0]} {PLACE_POS[1]} {TABLE_TOP}">
      <geom name="pad/disc" type="cylinder" size="0.04 0.0005" pos="0 0 0.0005" rgba=".2 .7 .2 1" contype="0"
            conaffinity="0"/>
      <site name="pad/zone" pos="0 0 0" size="0.03" group="5"/>
    </body>
    <body name="cube" pos="{CUBE_POS[0]} {CUBE_POS[1]} {CUBE_POS[2]}">
      <freejoint name="cube/free"/>
      <geom name="cube/box" type="box" size="{CUBE_HALF} {CUBE_HALF} {CUBE_HALF}" mass="0.1" rgba=".8 .15 .15 1"
            friction="0.8 0.005 0.0001"/>
    </body>
  </worldbody>
</mujoco>
"""

GOAL = f'''import numpy as np


class Goal:
    """The cube rests on the pad: within 3 cm of its centre, on the table, at rest."""

    def __init__(self, world):
        self.cube = world.id("body", "cube")
        self.zone = world.id("site", "pad/zone")
        self.updates = 0

    def update(self, world):
        self.updates += 1

    def success(self, world):
        p = world.data.xpos[self.cube]
        z = world.data.site_xpos[self.zone]
        v = world.data.cvel[self.cube]
        return bool(np.hypot(p[0] - z[0], p[1] - z[1]) < 0.03 and abs(p[2] - {CUBE_POS[2]}) < 0.01
                    and np.linalg.norm(v) < 0.05)
'''

BEHAVIOUR = '''import numpy as np


class Behaviour:
    """A lamp on the table lights while the cube is on the pad (writes only scene-owned geom_rgba)."""

    def __init__(self, world, config):
        self.cube = world.id("body", config["cube"])
        self.zone = world.id("site", config["zone"])
        self.lamp = world.id("geom", config["lamp"])
        self.calls = 0

    def control(self, world):
        self.calls += 1
        p, z = world.data.xpos[self.cube], world.data.site_xpos[self.zone]
        on = np.hypot(p[0] - z[0], p[1] - z[1]) < 0.03 and abs(p[2] - z[2] - 0.02) < 0.01
        world.model.geom_rgba[self.lamp] = [1.0, 0.9, 0.2, 1.0] if on else [0.2, 0.2, 0.2, 1.0]
'''

CAMERA_2 = {"pos": [1.5, -0.9, 1.6], "quat": None, "fovy_deg": 55}


def write(root, *, goal: bool = True, behaviour: bool = False, reset_settle_steps: int = 25) -> Path:
    from .robot import look_at_quat

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "scene.xml").write_text(SCENE)
    plugin = root / "plugin"
    if goal or behaviour:
        plugin.mkdir(exist_ok=True)
    if goal:
        (plugin / "goal.py").write_text(GOAL)
    if behaviour:
        (plugin / "behaviour.py").write_text(BEHAVIOUR)
    cam = dict(CAMERA_2, quat=[round(v, 7) for v in look_at_quat(CAMERA_2["pos"], [0.5, 0.0, 0.8])])
    ep = {
        "format": "household-episode",
        "format_version": "1.0.0",
        "scene": "scene.xml",
        "robot": {
            "model": "fr3_2f85",
            "base": {"pos": [0.0, 0.0, TABLE_TOP], "quat": [1, 0, 0, 0]},
            "pedestal": {"half_extents_m": [0.12, 0.12], "height_m": TABLE_TOP, "rgba": [0.35, 0.35, 0.37, 1]},
            "initial_qpos": HOME,
            "initial_gripper_open": 1,
        },
        "cameras": {"camera_2": cam},
        "render": {"width": 640, "height": 480},
        "control": {"rate_hz": 50, "physics_dt_s": 0.002},
        "budgets": {"max_steps": 45000, "settle_steps": 25, "reset_settle_steps": reset_settle_steps},
        "plugins": {
            "path": "plugin",
            "goal": "goal:Goal" if goal else None,
            "behaviour": "behaviour:Behaviour" if behaviour else None,
            "behaviour_config": {"cube": "cube", "zone": "pad/zone", "lamp": "table/lamp"} if behaviour else {},
            "helpers": None,
        },
        "trace": {"objects": ["cube"], "fixtures": ["table", "pad"], "room": "room"},
        "compute": {"device": "cpu"},
        "files": {},
    }
    (root / "episode.json").write_text(json.dumps(ep, indent=2) + "\n")
    write_files_map(root)
    return root


if __name__ == "__main__":
    print(write(sys.argv[1]))
