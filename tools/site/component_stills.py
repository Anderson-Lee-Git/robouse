"""Stills of the composable components for the hub: one image per embodiment, scene and task (at reset).

    .venv/bin/python tools/site/component_stills.py OUT_DIR [WxH]

Writes OUT_DIR/{embodiment,scene,task}-<id>.webp (640 x 400 unless WxH, for example 1280x800 for the hub's
tools/hub_stills/). Each still is a real composed task at seed 0, rendered from a scene camera right after the reset
(nothing is drawn by hand). A scene's still shows the scene alone: the robot it was composed with (every body under the
"robot/" prefix) is hidden, so Compose never shows one robot's scene still beside another robot's choice.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from robouse.backends.components.backend import ComposedBackend
from robouse.components.compose import ComposeError, instantiate
from robouse.components.registry import load
from robouse.components.resolve import check, modifiers

# the combination shown for each component: (embodiment, scene, task, camera)
EMB = {
    "franka-panda": ("tabletop", "stack-in-order", "front"),
    "aloha-2": ("tabletop", "bimanual-relay", "front"),
    "pal-tiago": ("tabletop", "put-in-container", "chase"),
    "google-robot": ("kitchen-counter", "put-in-container", "chase"),
    "unitree-go2": ("outdoor-field", "push-to-zone", "chase"),
    "crazyflie-2": ("warehouse", "inspect-tag", "overview"),
}
SCENE = {
    "tabletop": "franka-panda",
    "kitchen-counter": "google-robot",
    "workshop-bench": "aloha-2",
    "warehouse": "unitree-go2",
    "outdoor-field": "unitree-go2",
    "lab-bench": "franka-panda",
}
TASK_CAM = {"go-to-landmark": "overview", "inspect-tag": "overview", "fetch-and-deliver": "overview"}


def hide_robot(m) -> None:
    """Move every geom and site of the attached robot (a body named "robot/...", and everything under it) to a group the
    renderer does not draw (MjvOption shows groups 0 to 2)."""
    import mujoco

    name = lambda i: mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) or ""
    robot = set()
    for i in range(m.nbody):
        j = i
        while j > 0:
            if name(j).startswith("robot/"):
                robot.add(i)
                break
            j = m.body_parentid[j]
    for g in range(m.ngeom):
        if m.geom_bodyid[g] in robot:
            m.geom_group[g] = 5
    for s in range(m.nsite):
        if m.site_bodyid[s] in robot:
            m.site_group[s] = 5


def render(emb: str, scene: str, task: str, camera: str, w: int = 640, h: int = 400, robot: bool = True) -> np.ndarray:
    import mujoco

    inst = instantiate(emb, scene, task, modifiers({}), 0)
    b = ComposedBackend(
        {
            "id": "still",
            "instance": {
                "embodiment": {"id": emb},
                "scene": {"id": scene},
                "task": {"id": task},
                "modifiers": {},
                "seed": 0,
                "layout": inst,
            },
        }
    )
    b.reset(0)
    if not robot:
        hide_robot(b.model)
    cams = [c for c in (camera, "overview", "top") if c]
    cam = next(c for c in cams if mujoco.mj_name2id(b.model, mujoco.mjtObj.mjOBJ_CAMERA, c) >= 0)
    r = mujoco.Renderer(b.model, height=h, width=w)
    r.update_scene(b.data, camera=cam)
    img = r.render().copy()
    r.close()
    b.close()
    return img


SCENE_ORDER = ["tabletop", "workshop-bench", "lab-bench", "kitchen-counter", "warehouse", "outdoor-field"]
CLOSE_CAM = {
    "tabletop": "front",
    "workshop-bench": "bench_cam",
    "lab-bench": "bench_cam",
    "kitchen-counter": "counter_cam",
    "warehouse": "station_cam",
    "outdoor-field": "overview",
}


def first_ok(reg, emb=None, scene=None, task=None):
    for e in [emb] if emb else reg.composable("embodiments"):
        for s in [scene] if scene else [x for x in SCENE_ORDER if x in reg.composable("scenes")]:
            for t in [task] if task else reg.composable("tasks"):
                if check(reg, e, s, t).ok:
                    try:
                        instantiate(e, s, t, modifiers({}), 0)
                        return e, s, t
                    except ComposeError:
                        continue
    return None


def main() -> int:
    out = Path(sys.argv[1])
    w, h = (int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "640x400").split("x"))
    out.mkdir(parents=True, exist_ok=True)
    reg = load()
    jobs = []
    for e, (s, t, cam) in EMB.items():
        jobs.append((f"embodiment-{e}", e, s, t, cam))
    for s, e in SCENE.items():
        c = first_ok(reg, emb=e, scene=s)
        jobs.append((f"scene-{s}", *c, "overview"))
    for t in reg.composable("tasks"):
        c = first_ok(reg, task=t, emb="franka-panda") or first_ok(reg, task=t, emb="aloha-2") or first_ok(reg, task=t)
        jobs.append((f"task-{t}", *c, TASK_CAM.get(t) or CLOSE_CAM[c[1]]))
    for name, e, s, t, cam in jobs:
        Image.fromarray(render(e, s, t, cam, w, h, robot=not name.startswith("scene-"))).save(out / f"{name}.webp", quality=82)
        print(name, e, s, t, cam)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
