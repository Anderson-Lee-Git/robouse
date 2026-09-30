"""Hard tier (suite "hard") -> robouse tasks.

About 25 tabletop tasks built to remove the crutches that let frontier agent harnesses saturate the other suites
(exact object coordinates, calibrated cameras, the move_to skill, rules given as data, generous budgets). Each task
combines several of: long horizons, low-level control only (skills off, a small `max_repeat`), vision through a
wrist camera or a single uncalibrated camera, rules shown only as pictures, dynamics (sliding into an unreachable zone),
tight clearances, fragile handling, tight step budgets, and an implicit safety expectation.

Scenarios and reference solutions live in src/robouse/backends/tabletop_hard.py (HARD_SCENARIOS, oracle_main); the
scenes run on the ordinary tabletop backend. This script writes tasks/hard/<id>/ (task.md + oracle/ + verifier/), with
the full scenario embedded in the `robouse:` block, and checks that the YAML round trip reproduces it exactly.

Usage: python adapters/hard/generate.py [--out tasks/hard]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import yaml

from robouse.backends.tabletop.backend import WRIST_CAM_FOVY, WRIST_CAM_POS
from robouse.backends.tabletop.hard import HARD_SCENARIOS
from robouse.core.prompts import ROBO_USAGE
from robouse.tasks import write_task

ROOT = Path(__file__).resolve().parents[2]


def _tabletop_adapter():
    spec = importlib.util.spec_from_file_location("_tt_generate", ROOT / "adapters" / "tabletop" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TT = _tabletop_adapter()
VERIFY = TT.VERIFY  # identical verifier to every other suite
PRIVATE_KEYS = {"oracle", "meta", "suite", "robouse", "goal_extra", "timeout_sec", "wrist_geometry_given"}
LONG = {"hard-hanoi-4-lowlevel", "hard-hanoi-4-vision-lowlevel", "hard-sort-six-drawer", "hard-restack-reverse",
        "hard-uncal-hanoi-3", "hard-arc-img-quadrants", "hard-thin-plates"}

SCENE = ("A two-finger parallel gripper hangs over a table (a floating gripper, no arm; it cannot rotate). x points to the right as seen "
         "from the front of the table, y away from the front (toward the back of the table), z up; the table top is at z = 0 and spans "
         "x from -0.35 to 0.35 and y from -0.30 to 0.30. The gripper's tool point can reach x in [-0.34, 0.34], y in [-0.27, 0.28], z in "
         "[0.012, 0.35]. The fingers close along the y axis; the fully open gap is 10 cm.")


def _arc_goal(sc: dict) -> str:
    n = len(sc.get("image_examples", []))
    files = ", ".join(f"`observations/example_{i + 1}.png`" for i in range(n))
    g = sc["grid"]
    return (
        f"**Goal:** Coloured objects stand on a {g['rows']} x {g['cols']} grid of square cells marked on the table (cells {g['cell'] * 100:.0f} cm "
        f"apart, centre to centre; row 0 is the back row, col 0 the left column). The cell positions are NOT given as data: find the grid "
        f"in the camera image. A hidden rule transforms one "
        f"arrangement into another. The rule is shown ONLY as pictures: at the start of the episode the files {files} are placed in "
        "your working directory. Each picture shows one example, BEFORE on the left and AFTER on the right, seen from straight above "
        "(the back of the table is at the top of the picture) in this same scene with the gripper hidden. Nothing about the examples is "
        "given as data. Work out the rule and apply it to the objects in front of you by moving them. Objects of the same colour and "
        "shape are interchangeable. Only the final arrangement on the grid is judged: every object in the grid area must rest on the "
        "table within 2.5 cm of a cell centre, and objects off the grid are ignored. Objects must be released at the end.\n"
        + (f"\n{sc['goal_extra']}\n" if sc.get("goal_extra") else ""))


def _obs_section(sc: dict) -> str:
    rb = sc.get("robouse", {})
    mode = rb.get("obs_mode", "state")
    kinds = {f["kind"] for f in sc.get("fixtures", [])}
    if mode == "state":
        extra = []
        if sc.get("constraints"):
            extra.append("- `constraint_violations`: rules the server checks at every step; any entry here means the task has failed.")
        return TT.FIELDS.format(
            cell="", figure=", a figure" if "figure" in kinds else "", drawer="",
            extra="".join(e + "\n" for e in extra)).replace(
            "the drawer cabinet", "the drawer cabinet, the lane" if "lane" in kinds else "the drawer cabinet")
    fields = rb.get("visible_fields", [])
    cams = rb.get("cameras", [])
    unc = set(rb.get("uncalibrated_cameras", []))
    s = ["## What you can observe\n\n",
         f"`robo observe` does **not** give object or goal positions. It returns only {', '.join(f'`{f}`' for f in fields)} and saves one "
         f"image per camera ({', '.join(f'`{c}`' for c in cams)}; 320 x 320 pixels), printing the paths. Open the images to see the scene. "
         "`hand_pos` is the gripper's tool point (between the fingertips) in metres, `gripper_open` is 0 (closed) to 1 (10 cm gap)"
         + (", `holding` lists the (neutral) names of objects touching the fingers" if "holding" in fields else
            " (there is no contact sensor that says what the fingers hold: a finger opening above zero after closing means something "
            "is between them, and the images show what)")
         + (", `grid` gives the grid geometry" if "grid" in fields else "")
         + (", and `constraint_violations` lists broken rules (any entry means the task has failed)." if "constraint_violations" in fields else ".")
         + "\n"]
    if "wrist" in cams and not sc.get("wrist_geometry_given"):
        s.append(
            "\nThe only camera is `wrist`, an eye-in-hand camera fixed to the gripper and moving with it. It looks straight down; in its "
            "image, right is +x and up is +y (the back of the table). It is mounted to one side of the fingers, but its exact offset from the "
            "tool point is NOT given, and no projection matrix is given (`robo info` gives only its image size and field of view). You know "
            "`hand_pos`, and the task description gives the positions of some fixed things, so you can work out how image positions relate "
            "to world positions by moving the gripper and watching how the view changes. The higher the gripper, the more of the table you "
            "see. There is no other camera.\n")
    elif "wrist" in cams:
        cx, cy, cz = WRIST_CAM_POS
        s.append(
            f"\nThe only camera is `wrist`, an eye-in-hand camera fixed to the gripper: it sits {cx * 100:.0f} cm to the right (+x) of the tool "
            f"point and {cz * 100:.0f} cm above it (so at `hand_pos + [{cx}, {cy}, {cz}]`), and looks straight down. In its image, right is +x "
            f"and up is +y (the back of the table). Its vertical and horizontal field of view is {WRIST_CAM_FOVY} degrees (square pixels, "
            "no distortion), so a point at depth h metres below the camera and horizontal offset (dx, dy) from it appears at pixel "
            f"u = 160 + f * dx / h, v = 160 - f * dy / h with f = 160 / tan({WRIST_CAM_FOVY // 2} deg) (about 343 px). The camera moves with the "
            "gripper, so no projection matrix is given; the higher the gripper, the more of the table you see (at the top of the "
            "workspace the view is about 38 cm across). There is no other camera.\n")
    elif unc and len(cams) == 1:
        s.append(f"\nThere is only one camera, and `robo info` does NOT give its projection matrix (only its image size and field of view). "
                 "You know where the gripper is from `hand_pos`, so you can relate image positions to world positions by moving the gripper "
                 "and looking where it appears.\n")
    elif unc:
        s.append("\n`robo info` does NOT give the cameras' projection matrices (only each image's size and field of view). `front` looks at the "
                 "table from the front and above; `top` looks straight down from above the table, with the back of the table at the top of "
                 "the image. You know where the gripper is from `hand_pos`, so you can relate image positions to world positions by moving the "
                 "gripper and looking where it appears.\n")
    else:
        s.append("\n`robo info` lists each camera with a 3x4 `projection` matrix P: for a world point (x, y, z), `[u*w, v*w, w] = P @ [x, y, z, 1]` "
                 "gives its pixel (u, v) in that camera's saved image (u to the right, v down, origin at the top-left).\n")
    return "".join(s)


def _control_section(sc: dict) -> str:
    rb = sc.get("robouse", {})
    lines = []
    if rb.get("skills", True) is False:
        lines.append("- Skills are disabled on this task: `robo move-to` and `robo grip` return an error. Use `robo act DX DY DZ GRIP` only "
                     "(DX/DY/DZ move the tool point by about 1 cm per unit per step; GRIP +1 closes, -1 opens, values in between give a "
                     "partial opening: finger gap = 10 cm * (1 - GRIP) / 2).")
    if "max_repeat" in rb:
        lines.append(f"- `robo act --repeat N` is limited to N <= {rb['max_repeat']} on this task (larger values are cut to {rb['max_repeat']}).")
    lines.append(f"- Step budget: {sc['max_steps']} simulated steps (one step = 20 ms). Wall-clock limit: {sc.get('timeout_sec', 1200) // 60} minutes.")
    lines.append("- Objects must be released (not touching the fingers) when the episode is judged, about 10 steps after `robo done`.")
    return "## Task rules\n\n" + "\n".join(lines) + "\n"


def instruction(sc: dict) -> str:
    parts = [f"# {sc['title']}\n", SCENE + "\n"]
    if sc.get("image_examples"):
        parts.append(_arc_goal(sc))
    else:
        parts.append(f"**Goal:** {sc['goal']}\n" + (f"\n{sc['goal_extra']}\n" if sc.get("goal_extra") else ""))
    parts.append(_obs_section(sc))
    parts.append(TT.GRIP_NOTE.rstrip("\n") + "\n")
    parts.append(_control_section(sc))
    return "\n".join(parts) + "\n" + ROBO_USAGE


def meta_for(sc: dict) -> dict:
    m = sc["meta"]
    rb = sc.get("robouse", {})
    scen = {k: v for k, v in sc.items() if k not in PRIVATE_KEYS}
    robouse = {"id": sc["id"], "backend": "tabletop", "seed": 0, "max_steps": sc["max_steps"], "camera": sc.get("camera", "front"),
               "skills": rb.get("skills", True), "success_mode": "final"}
    for k in ("max_repeat", "obs_mode", "cameras", "uncalibrated_cameras", "visible_fields"):
        if k in rb:
            robouse[k] = rb[k]
    robouse["scenario"] = scen
    return {
        "task": {"name": f"robouse/{sc['id']}", "description": sc["title"]},
        "metadata": {"source_benchmark": m["source_benchmark"], "source_task": m["source_task"], "source_suite": m["source_suite"],
                     "suite": "hard", "category": m["category"], "difficulty": m["difficulty"], "tags": m["tags"]},
        "agent": {"timeout_sec": sc.get("timeout_sec", 1200)},
        "verifier": {"timeout_sec": 120},
        "robouse": robouse,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "tasks" / "hard"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for tid, sc in HARD_SCENARIOS.items():
        sc = dict(sc)
        sc["timeout_sec"] = 1800 if tid in LONG else 1200
        d = out / tid
        meta = meta_for(sc)
        write_task(d, meta, instruction(sc),
                   "#!/bin/bash\n# Reference solution: scripted controller through the robo socket (act only on tasks without skills).\n"
                   f"set -euo pipefail\npython -m robouse.oracle --backend tabletop_hard --env {tid}\n", VERIFY)
        text = (d / "task.md").read_text()
        fm = yaml.safe_load(text.split("---", 2)[1])
        want = json.loads(json.dumps(meta["robouse"]["scenario"]))
        assert fm["robouse"]["scenario"] == want, f"YAML round trip changed the scenario of {tid}"
    print(f"wrote {len(HARD_SCENARIOS)} tasks to {out}")


if __name__ == "__main__":
    main()
