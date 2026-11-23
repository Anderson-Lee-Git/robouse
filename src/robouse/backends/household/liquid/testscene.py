"""A synthetic liquid package for the extension's tests and validation (format household-episode 1.0.0, liquid
contract 1.0.0): a counter on a floor, a tumbler (the source) and a bowl on the counter, the FR3 beside it. The
tumbler is welded to a mocap driver that a behaviour plugin moves along a scripted route.

The room is a 4 m x 4 m floor with 1 m walls, all static liquid domain boxes, so a splash stays in the domain.

Variants:
    pour      lift, tilt to 72 deg over the counter (a spill), sweep the stream into the bowl while tilting on to
              115 deg, hold, set upright, 1.5 s hold tail
    rest      the full tumbler stands still (containment control)
    invert    the tumbler starts upside down, its mouth 12 cm above the counter (free-fall control)
    drop      the same with the mouth 3 cm above the counter (impact and containment control)
    embedded  a static shelf box cuts through the fill (must be refused as invalid)
    wipe      the full tumbler stands still while a mocap sponge (an animated boundary with an absorber) is lowered
              onto a 30 ml counter puddle, wipes across it and lifts (puddle, moving boundary and uptake)

`gpu_block(block)` turns any variant's liquid block into liquid contract 1.2.0 on the GPU backend (and `write(...,
gpu=True)` writes such a package, with compute.device gpu).

    python -m robouse.backends.household.liquid.testscene <dir> [variant]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from ..package import write_files_map
from .meshes import revolve

TOP = 0.75  # counter top
CUP_XY = (0.70, -0.20)
BOWL_XY = (0.70, 0.0)
CUP_R_BOTTOM, CUP_R_TOP, CUP_H, CUP_WALL, CUP_BASE = 0.032, 0.037, 0.11, 0.0025, 0.006
HOME = [0.0, -1.10, 0.0, -2.10, 0.0, 1.50, 1.5707963]
FILL_ML = 150.0
LIFT = 0.12
SWEEP = 0.12
TILT1_DEG, TILT_DEG = 72.0, 115.0
# phases (s): hold, lift, tilt over the counter, sweep into the bowl, hold, upright, hold tail
DROP_M = {"invert": 0.12, "drop": 0.03}  # mouth height above the counter of the upside-down variants
PHASES = (0.2, 0.5, 0.8, 1.0, 0.6, 0.5, 1.5)  # 5.1 s: the CPU contract runs ~100x slower than real time
GPU_BACKEND = "warp-1.19.0-dfsph-cuda-f32-v1"
# wipe: a 30 ml puddle in front of the tumbler; a 8 x 5 x 2.4 cm sponge, lowered, wiped along +y, lifted
WIPE_PUDDLE = [[0.83, -0.17], [0.91, -0.17], [0.91, -0.07], [0.83, -0.07]]
WIPE_ML = 30.0
SPONGE_HALF = (0.04, 0.025, 0.012)
WIPE_X, WIPE_Y = 0.87, (-0.24, -0.01)
WIPE_PHASES = (0.2, 0.4, 1.2, 0.4, 0.3)  # 2.5 s: hold, lower, wipe, lift, hold
WIPE_CLEARANCE = 0.0005  # sponge underside above the counter top while wiping


def cup_profile():
    """Outer/inner (r, z) section of the tumbler, body frame at the centre of its bottom (a closed revolve)."""
    rb, rt, h, w, b = CUP_R_BOTTOM, CUP_R_TOP, CUP_H, CUP_WALL, CUP_BASE
    lip = [(rt - w / 2 + w / 2 * math.cos(a), h - w / 2 + w / 2 * math.sin(a)) for a in np.linspace(0, math.pi, 5)]
    return [(0.0, 0.0), (rb - 0.002, 0.0), (rb, 0.002), *lip, (rb - w + (rt - rb) * b / h, b), (0.0, b)]


def cup_inside():
    rb, rt, h, w, b = CUP_R_BOTTOM, CUP_R_TOP, CUP_H, CUP_WALL, CUP_BASE
    return [[round(rb - w + (rt - rb) * b / h, 6), b], [rt - w, h]]


BOWL_SECTION = [(0.0, 0.0), (0.040, 0.0), (0.080, 0.065), (0.077, 0.065), (0.0425, 0.005), (0.0, 0.005)]
BOWL_INSIDE = [[0.0425, 0.005], [0.077, 0.065]]


def _mesh_xml(name, section, segments=48):
    v, f = revolve(section, segments)
    vs = " ".join(f"{x:.6f}" for x in v.ravel())
    fs = " ".join(str(int(i)) for i in f.ravel())
    return f'<mesh name="{name}" vertex="{vs}" face="{fs}" inertia="shell"/>'


def scene_xml(variant: str) -> str:
    cx, cy = CUP_XY
    cup_z, cup_quat = TOP, "1 0 0 0"
    if variant in DROP_M:
        cup_z, cup_quat = TOP + DROP_M[variant] + CUP_H, "0 1 0 0"  # upside down, the mouth above the counter
    shelf = ""
    if variant == "wipe":
        hx, hy, hz = SPONGE_HALF
        shelf = (
            f'<body name="sponge" mocap="true" pos="{WIPE_X} {WIPE_Y[0]} {TOP + 0.05 + hz}"><geom name="sponge/foam" '
            f'type="box" size="{hx} {hy} {hz}" rgba=".95 .85 .2 1" contype="0" conaffinity="0" group="1"/></body>'
        )
    if variant == "embedded":
        shelf = (
            f'<body name="shelf" pos="{cx} {cy} {TOP + 0.03}"><geom name="shelf/board" type="box" '
            f'size="0.01 0.06 0.004" rgba=".5 .4 .3 1"/></body>'
        )
    return f"""<mujoco model="liquid-test">
  <asset>
    <texture name="room/grid" type="2d" builtin="checker" rgb1=".55 .55 .55" rgb2=".45 .45 .45" width="256"
             height="256"/>
    <material name="room/floor" texture="room/grid" texrepeat="8 8"/>
    <material name="cup/glass" rgba=".85 .92 .95 .35" specular=".8" shininess=".9"/>
    <material name="bowl/glaze" rgba=".93 .93 .9 1"/>
    {_mesh_xml("cup/glass", cup_profile())}
    {_mesh_xml("bowl/shell", BOWL_SECTION)}
  </asset>
  <worldbody>
    <light name="room/sun" pos="0.6 -0.3 2.6" dir="0 0 -1" diffuse=".8 .8 .8" castshadow="true"/>
    <body name="room">
      <geom name="room/floor" type="box" size="2 2 0.05" pos="0 0 -0.05" material="room/floor"/>
      <geom name="room/wall_px" type="box" size="0.05 2.1 0.5" pos="2.05 0 0.5" rgba=".7 .7 .68 1"/>
      <geom name="room/wall_nx" type="box" size="0.05 2.1 0.5" pos="-2.05 0 0.5" rgba=".7 .7 .68 1"/>
      <geom name="room/wall_py" type="box" size="2 0.05 0.5" pos="0 2.05 0.5" rgba=".7 .7 .68 1"/>
      <geom name="room/wall_ny" type="box" size="2 0.05 0.5" pos="0 -2.05 0.5" rgba=".7 .7 .68 1"/>
    </body>
    <body name="counter" pos="0.6 0 {TOP / 2:.4f}">
      <geom name="counter/top" type="box" size="0.35 0.6 {TOP / 2:.4f}" rgba=".62 .6 .56 1"
            friction="0.8 0.005 0.0001"/>
    </body>
    {shelf}
    <body name="cup_driver" mocap="true" pos="{cx} {cy} {cup_z}" quat="{cup_quat}"/>
    <body name="cup" pos="{cx} {cy} {cup_z}" quat="{cup_quat}">
      <freejoint name="cup/free"/>
      <inertial pos="0 0 0.04" mass="0.25" diaginertia="4e-4 4e-4 2e-4"/>
      <geom name="cup/glass" type="mesh" mesh="cup/glass" material="cup/glass" contype="0" conaffinity="0"
            group="1"/>
      <geom name="cup/base" type="cylinder" size="0.03 0.003" pos="0 0 0.003" rgba="0 0 0 0" group="3"/>
    </body>
    <body name="bowl" pos="{BOWL_XY[0]} {BOWL_XY[1]} {TOP}">
      <freejoint name="bowl/free"/>
      <inertial pos="0 0 0.02" mass="0.4" diaginertia="8e-4 8e-4 1.2e-3"/>
      <geom name="bowl/shell" type="mesh" mesh="bowl/shell" material="bowl/glaze" contype="0" conaffinity="0"
            group="1"/>
      <geom name="bowl/base" type="cylinder" size="0.04 0.0025" pos="0 0 0.0025" rgba="0 0 0 0" group="3"/>
    </body>
  </worldbody>
  <equality>
    <weld name="cup/drive" body1="cup_driver" body2="cup" solref="0.02 1"/>
  </equality>
</mujoco>
"""


BEHAVIOUR = '''import math

import numpy as np

PHASES = {phases}
LIFT, SWEEP, TILT1, TILT = {lift}, {sweep}, math.radians({tilt1}), math.radians({tilt})
RT, H = {rt}, {h}


def smooth(s):
    s = min(max(s, 0.0), 1.0)
    return s * s * (3 - 2 * s)


class Behaviour:
    """Moves the tumbler's mocap driver along the scripted pour (a function of the control step only)."""

    def __init__(self, world, config):
        self.mocap = int(world.model.body_mocapid[world.id("body", config["driver"])])
        self.p0 = np.array(world.data.mocap_pos[self.mocap])
        self.active = config["route"] == "pour"

    def control(self, world):
        if not self.active:
            return
        t = world.step * 0.02
        e = np.cumsum(PHASES)
        lift = smooth((t - e[0]) / PHASES[1])
        sweep = smooth((t - e[2]) / PHASES[3])
        tilt = TILT1 * smooth((t - e[1]) / PHASES[2]) + (TILT - TILT1) * sweep
        a = -tilt * (1.0 - smooth((t - e[4]) / PHASES[5]))  # negative about x: the mouth turns toward +y
        # rotate about the rim point on the +y side (the pouring lip), which moves with lift and sweep
        pivot = self.p0 + np.array([0.0, RT + SWEEP * sweep, H + LIFT * lift])
        rel = np.array([0.0, -RT, -H])
        c, s = math.cos(a), math.sin(a)
        rot = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
        world.data.mocap_pos[self.mocap] = pivot + rot @ rel
        world.data.mocap_quat[self.mocap] = [math.cos(a / 2), math.sin(a / 2), 0.0, 0.0]
'''


WIPE_BEHAVIOUR = '''import numpy as np

PHASES = {phases}
X, Y0, Y1, Z0, Z1 = {x}, {y0}, {y1}, {z0}, {z1}


def smooth(s):
    s = min(max(s, 0.0), 1.0)
    return s * s * (3 - 2 * s)


class Behaviour:
    """Lowers the mocap sponge onto the puddle, wipes it along +y and lifts it (a function of the control step only)."""

    def __init__(self, world, config):
        self.mocap = int(world.model.body_mocapid[world.id("body", config["driver"])])

    def control(self, world):
        t = world.step * 0.02
        e = np.cumsum(PHASES)
        down = smooth((t - e[0]) / PHASES[1]) - smooth((t - e[2]) / PHASES[3])
        y = Y0 + (Y1 - Y0) * smooth((t - e[1]) / PHASES[2])
        world.data.mocap_pos[self.mocap] = [X, y, Z1 + (Z0 - Z1) * down]
'''


def gpu_block(block: dict) -> dict:
    """The same liquid on liquid contract 1.2.0 (GPU backend); every other field unchanged."""
    return {**block, "contract": "1.2.0", "backend": GPU_BACKEND}


def liquid_block(variant: str, threads: int = 4) -> dict:
    walls = [f"room/wall_{w}" for w in ("px", "nx", "py", "ny")]
    boxes = ["room/floor", *walls, "counter/top"] + (["shelf/board"] if variant == "embedded" else [])
    return {
        "contract": "1.0.0",
        "backend": "splishsplash-2.19.0-tree-f32-avx2-v1",
        "threads": threads,
        "material": {
            "particle_radius_m": 0.00125,
            "density_kg_m3": 1000.0,
            "viscosity_m2_s": 1e-4,
            "boundary_viscosity_m2_s": 1e-3,
            "surface_tension": {"method": "none", "coefficient": 0.0, "boundary_adhesion": 0.0},
            "rgba": [1.0, 0.56, 0.1, 0.93],
        },
        "solver": {
            "cfl": 0.5,
            "dt_min_s": 5e-5,
            "dt_max_s": 0.002,
            "max_density_error_pct": 0.05,
            "max_divergence_error_pct": 0.1,
            "max_iterations": 100,
        },
        "domain": {"static_box_geoms": boxes, "floor_geom": "room/floor"},
        "containers": [
            {
                "name": "cup",
                "body": "cup",
                "boundary_geoms": ["cup/glass"],
                "inside_profile": cup_inside(),
                "slack_m": 0.0015,
            },
            {
                "name": "bowl",
                "body": "bowl",
                "boundary_geoms": ["bowl/shell"],
                "inside_profile": BOWL_INSIDE,
                "slack_m": 0.0015,
            },
        ],
        "boundaries": [],
        "surface": {"geom": "counter/top", "centre_xy": [0.70, -0.08], "half_extent_m": 0.25, "film_m": 0.02},
        "sources": [{"name": "juice", "container": "cup", "fill_ml": FILL_ML}],
        "absorbers": [],
        **(
            {
                "boundaries": [{"name": "sponge", "body": "sponge", "geoms": ["sponge/foam"], "animated": True}],
                "sources": [
                    {"name": "juice", "container": "cup", "fill_ml": FILL_ML},
                    {"name": "spill", "puddle": {"polygon_xy": WIPE_PUDDLE, "volume_ml": WIPE_ML}},
                ],
                "absorbers": [{"boundary": "sponge", "capacity_ml": 20.0, "contact_m": 0.0025}],
            }
            if variant == "wipe"
            else {}
        ),
        "settle": {"seconds": 0.0 if variant in DROP_M else 0.3, "damping": 0.9},
        "sleep": "none",
        "initial_state": None,
    }


def write(root, variant: str = "pour", threads: int = 4, liquid: dict | None = None, gpu: bool = False) -> Path:
    from ..robot import look_at_quat

    root = Path(root)
    (root / "plugin").mkdir(parents=True, exist_ok=True)
    (root / "scene.xml").write_text(scene_xml(variant))
    if variant == "wipe":
        hz = SPONGE_HALF[2]
        behaviour = WIPE_BEHAVIOUR.format(
            phases=WIPE_PHASES, x=WIPE_X, y0=WIPE_Y[0], y1=WIPE_Y[1], z0=TOP + hz + WIPE_CLEARANCE, z1=TOP + 0.05 + hz
        )
    else:
        behaviour = BEHAVIOUR.format(
            phases=PHASES, lift=LIFT, sweep=SWEEP, tilt1=TILT1_DEG, tilt=TILT_DEG, rt=CUP_R_TOP, h=CUP_H
        )
    (root / "plugin" / "behaviour.py").write_text(behaviour)
    c2 = {"pos": [1.30, -0.70, 1.20], "fovy_deg": 50}
    c2["quat"] = [round(v, 7) for v in look_at_quat(c2["pos"], [0.70, -0.10, 0.80])]
    ep = {
        "format": "household-episode",
        "format_version": "1.0.0",
        "scene": "scene.xml",
        "robot": {
            "model": "fr3_2f85",
            "base": {"pos": [0.0, 0.0, TOP], "quat": [1, 0, 0, 0]},
            "pedestal": {"half_extents_m": [0.12, 0.12], "height_m": TOP, "rgba": [0.35, 0.35, 0.37, 1]},
            "initial_qpos": HOME,
            "initial_gripper_open": 1,
        },
        "cameras": {"camera_2": c2},
        "render": {"width": 640, "height": 480},
        "control": {"rate_hz": 50, "physics_dt_s": 0.002},
        "budgets": {"max_steps": 45000, "settle_steps": 25, "reset_settle_steps": 0},
        "plugins": {
            "path": "plugin",
            "goal": None,
            "behaviour": "behaviour:Behaviour",
            "behaviour_config": {"driver": "sponge"}
            if variant == "wipe"
            else {"driver": "cup_driver", "route": "pour" if variant == "pour" else "hold"},
            "helpers": None,
        },
        "trace": {"objects": ["cup", "bowl"], "fixtures": ["counter"], "room": "room"},
        "compute": {"device": "gpu" if gpu else "cpu"},
        "files": {},
        "liquid": liquid if liquid is not None else liquid_block(variant, threads),
    }
    if gpu and liquid is None:
        ep["liquid"] = gpu_block(ep["liquid"])
    (root / "episode.json").write_text(json.dumps(ep, indent=2) + "\n")
    write_files_map(root)
    return root


if __name__ == "__main__":
    print(write(sys.argv[1], *(sys.argv[2:3] or [])))
