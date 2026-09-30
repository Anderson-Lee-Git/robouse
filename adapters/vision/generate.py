"""Vision variants: the same scenes and goals, but the agent does not get object or goal coordinates.

`robo observe` returns only the robot's own state (gripper position and opening, plus task feedback fields such as
ARC examples or constraint violations) and two camera images. `robo info` gives each camera's 3x4 projection
matrix, so image points can be turned into world coordinates. The reference solution still works because the
server gives full state to requests carrying the per-episode oracle token, which only the reference solution gets.

Usage: python adapters/vision/generate.py   (reads tasks/<suite>, writes tasks/vision/<id>-vision)
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tasks" / "vision"

METAWORLD = [
    "reach",
    "reach-wall",
    "push",
    "push-back",
    "push-wall",
    "pick-place",
    "pick-place-wall",
    "bin-picking",
    "basketball",
    "soccer",
    "sweep",
    "sweep-into",
    "shelf-place",
    "hammer",
    "assembly",
    "disassemble",
    "pick-out-of-hole",
    "plate-slide",
    "coffee-push",
    "drawer-open",
    "door-open",
    "button-press",
    "dial-turn",
    "window-open",
]
TABLETOP_SUITES = ["libero-style", "arc-style", "robo-use-families"]

CAMS = {"metaworld": ["corner", "topview"], "tabletop": ["front", "top"]}
VISIBLE = {
    "metaworld": ["hand_pos", "gripper_open"],
    "tabletop": ["hand_pos", "gripper_open", "holding", "examples", "grid", "constraint_violations"],
}

NOTE = """\
## Vision variant

This is the vision version of the task. `robo observe` does **not** give object or goal positions: you get only the robot's own state ({fields}) and two camera images ({cams}), saved on every `robo observe` and printed as paths. Open the images to see the scene. `robo info` lists each camera with a 3x4 `projection` matrix P: for a world point (x, y, z), `[u*w, v*w, w] = P @ [x, y, z, 1]` gives its pixel (u, v) in that camera's saved image (u to the right, v down, origin at the top-left). With two cameras you can triangulate a point you see in both, or intersect a pixel's ray with a known height. Any field names in the description below that are not in your observation are hidden in this variant.

"""


def main() -> None:
    import copy

    from robouse.tasks import load_task, write_task

    if OUT.exists():
        shutil.rmtree(OUT)
    bases = [ROOT / "tasks" / "metaworld" / f"metaworld-{n}" for n in METAWORLD]
    for s in TABLETOP_SUITES:
        bases += sorted(p for p in (ROOT / "tasks" / s).iterdir() if p.is_dir())
    n = 0
    for base in bases:
        t = load_task(base)
        meta = copy.deepcopy(t.meta)
        rb, md = meta["robouse"], meta.setdefault("metadata", {})
        backend, old_id = rb["backend"], rb["id"]
        new_id = f"{old_id}-vision"
        cams, vis = CAMS[backend], VISIBLE[backend]
        rb.update(id=new_id, obs_mode="vision", cameras=cams, visible_fields=vis, camera=cams[0])
        meta["robouse"] = {"id": new_id, **{k: v for k, v in rb.items() if k != "id"}}
        meta.setdefault("task", {})["name"] = f"robouse/{new_id}"
        md.update(base_suite=md.get("suite"), base_task=old_id, suite="vision")
        note = NOTE.format(fields=", ".join(f"`{f}`" for f in vis), cams=", ".join(f"`{c}`" for c in cams))
        body = t.instruction
        first_break = body.find("\n\n") + 2
        write_task(
            OUT / new_id,
            meta,
            body[:first_break] + note + body[first_break:],
            t.oracle_script.read_text(),
            t.verifier_script.read_text(),
        )
        n += 1
    print(f"wrote {n} vision tasks to {OUT}")


if __name__ == "__main__":
    main()
