"""Vision variants: the same scenes and goals, but the agent does not get object or goal coordinates.

`robo observe` returns only the robot's own state (gripper position and opening, plus task feedback fields such as
ARC examples or constraint violations) and two camera images. `robo info` gives each camera's 3x4 projection
matrix, so image points can be turned into world coordinates. The reference solution still works because the
server gives full state to requests carrying the per-episode oracle token, which only the reference solution gets.

Usage: python adapters/vision/generate.py   (reads tasks/<suite>, writes tasks/vision/<id>-vision)
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tasks" / "vision"

METAWORLD = ["reach", "reach-wall", "push", "push-back", "push-wall", "pick-place", "pick-place-wall", "bin-picking",
             "basketball", "soccer", "sweep", "sweep-into", "shelf-place", "hammer", "assembly", "disassemble",
             "pick-out-of-hole", "plate-slide", "coffee-push", "drawer-open", "door-open", "button-press",
             "dial-turn", "window-open"]
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
    if OUT.exists():
        shutil.rmtree(OUT)
    bases = [ROOT / "tasks" / "metaworld" / f"metaworld-{n}" for n in METAWORLD]
    for s in TABLETOP_SUITES:
        bases += sorted(p for p in (ROOT / "tasks" / s).iterdir() if (p / "task.toml").exists())
    n = 0
    for base in bases:
        toml = (base / "task.toml").read_text()
        backend = re.search(r'^backend = "(\w+)"', toml, re.M).group(1)
        old_id = re.search(r'^id = "([^"]+)"', toml, re.M).group(1)
        new_id = f"{old_id}-vision"
        d = OUT / new_id
        shutil.copytree(base, d)
        cams, vis = CAMS[backend], VISIBLE[backend]
        toml = toml.replace(f'id = "{old_id}"', f'id = "{new_id}"', 1)
        toml = re.sub(r'^name = "robouse/([^"]+)"', lambda m: f'name = "robouse/{m.group(1)}-vision"', toml, count=1, flags=re.M)
        toml = re.sub(r'^suite = "([^"]+)"', lambda m: f'suite = "vision"\nbase_suite = "{m.group(1)}"\nbase_task = "{old_id}"', toml, count=1, flags=re.M)
        toml = re.sub(r'^camera = "[^"]*"\n', "", toml, flags=re.M)
        block = (f'obs_mode = "vision"\ncameras = {cams!r}\nvisible_fields = {vis!r}\ncamera = "{cams[0]}"\n').replace("'", '"')
        toml = re.sub(r"^\[robouse\]\n", "[robouse]\n" + block, toml, count=1, flags=re.M)
        (d / "task.toml").write_text(toml)
        ins = (d / "instruction.md").read_text()
        note = NOTE.format(fields=", ".join(f"`{f}`" for f in vis), cams=", ".join(f"`{c}`" for c in cams))
        first_break = ins.find("\n\n") + 2
        (d / "instruction.md").write_text(ins[:first_break] + note + ins[first_break:])
        n += 1
    print(f"wrote {n} vision tasks to {OUT}")


if __name__ == "__main__":
    main()
