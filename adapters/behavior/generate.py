"""BEHAVIOR-1K (Stanford Vision and Learning Lab; OmniGibson on NVIDIA Isaac Sim) -> robouse tasks.

Five long-horizon household activities from the 2026 BEHAVIOR Challenge task list, each in its challenge scene with
the challenge's task instance 0 (the cached `*_0_0_template` activity scene) and the R1Pro mobile manipulator.
The agent drives the robot with BEHAVIOR's symbolic action primitives (`robo skill ...`, see
src/robouse/backends/behavior.py); success is BEHAVIOR's BDDL goal. The simulator runs remotely on an RTX GPU; see
docs/suites/behavior.md.

The reference solution is a scripted primitive sequence (oracle/plan.json) sent through the robo socket.

Usage: python adapters/behavior/generate.py --out tasks/behavior
"""
from __future__ import annotations

import argparse
import json
import shutil
import textwrap
from pathlib import Path

from robouse.tasks import write_task

SOURCE = "BEHAVIOR-1K (Li et al. 2022/2024), 2026 BEHAVIOR Challenge task list; OmniGibson 3.9.3 on Isaac Sim 5.1"

# id, activity, scene, rooms loaded, difficulty, budget (skills), official challenge instruction, oracle plan
TASKS = [
    dict(activity="turning_on_radio", scene="house_double_floor_lower", difficulty="easy", max_steps=20,
         instruction="Turn on the radio receiver that's on the table in the living room.",
         plan=[["navigate_to", "radio_receiver.n.01_1"], ["toggle_on", "radio_receiver.n.01_1"]]),
    dict(activity="picking_up_trash", scene="house_double_floor_lower", difficulty="medium", max_steps=40,
         instruction="Put the three cans of soda from the living room inside the trash can in the kitchen.",
         plan=[step for i in (1, 2, 3) for step in (
             ["navigate_to", f"can__of__soda.n.01_{i}"], ["grasp", f"can__of__soda.n.01_{i}"],
             ["navigate_to", "ashcan.n.01_1"], ["place_inside", "ashcan.n.01_1"])]),
    dict(activity="rearranging_kitchen_furniture", scene="house_double_floor_lower", difficulty="medium", max_steps=45,
         instruction="Move the toaster, food processor, and French press from the kitchen countertop into the same kitchen "
                     "cabinet, and make sure that cabinet is closed at the end.",
         plan=None),  # filled in below once the cabinet is chosen
    dict(activity="bringing_water", scene="house_single_floor", difficulty="medium", max_steps=40,
         instruction="Retrieve the two bottles from the refrigerator in the kitchen, bring them to the living room, and "
                     "place both on the coffee table. Make sure the refrigerator is closed at the end.",
         plan=[["navigate_to", "electric_refrigerator.n.01_1"], ["open", "electric_refrigerator.n.01_1"],
               ["grasp", "bottle.n.01_1"], ["navigate_to", "coffee_table.n.01_1"], ["place_on_top", "coffee_table.n.01_1"],
               ["navigate_to", "electric_refrigerator.n.01_1"], ["grasp", "bottle.n.01_2"],
               ["close", "electric_refrigerator.n.01_1"],
               ["navigate_to", "coffee_table.n.01_1"], ["place_on_top", "coffee_table.n.01_1"]]),
    dict(activity="putting_dishes_away_after_cleaning", scene="house_single_floor", difficulty="hard", max_steps=90,
         instruction="In the kitchen, gather all eight plates from the two countertops, place them all inside a single "
                     "cabinet (either one), and make sure all cabinets are closed when you are done.",
         plan=None),
]
ROOMS = {"house_double_floor_lower": ["corridor_0", "garden_0", "kitchen_0", "living_room_0"],
         "house_single_floor": ["corridor_0", "dining_room_0", "entryway_0", "garden_0", "kitchen_0", "living_room_0",
                                "living_room_1"]}

USAGE = """\
## How to control the robot

You are the robot's high-level policy. You act only through the `robo` command in your shell; you cannot read or change the simulator, the scoring, or other files to succeed. The episode server checks BEHAVIOR's goal conditions on the final simulated state itself.

```
robo info                          # skills, step budget
robo observe                       # robot pose, held object, and every task-relevant object (name, category, room, position, distance, open/on state, inside/on-top relations)
robo observe --image               # also saves a third-person camera image and prints its path (open it to look)
robo observe --image --camera head # the robot's own head camera instead
robo skill navigate_to OBJ         # drive next to OBJ (a held object comes along)
robo skill grasp OBJ               # pick up OBJ (hand must be empty, OBJ within reach)
robo skill place_on_top OBJ        # put the held object on top of OBJ
robo skill place_inside OBJ        # put the held object inside OBJ (open OBJ first if it has a door or lid)
robo skill open OBJ                # open OBJ (hand must be empty)
robo skill close OBJ               # close OBJ (hand must be empty)
robo skill toggle_on OBJ           # switch OBJ on (hand must be empty)
robo skill toggle_off OBJ          # switch OBJ off (hand must be empty)
robo skill release                 # drop the held object where the hand is
robo done "short summary"          # end the episode and ask for scoring
robo give-up "reason"              # end the episode without claiming success
```

- OBJ is an object name exactly as `robo observe` lists it (BEHAVIOR's BDDL instance names, e.g. `bottle.n.01_1`). Identical objects are numbered `_1`, `_2`, ...
- The robot is an R1Pro wheeled mobile manipulator that carries one object at a time. Manipulation skills only work on objects within reach (`in_reach` in `robo observe`, about 1.25 m); use `navigate_to` first. Objects inside a closed container must be taken out after opening it.
- A skill can fail (the response says why, with `ok: False`); a failed skill still costs one step. Every skill call counts against the step budget (`robo info`).
- Success is judged after you call `robo done`, with the robot holding still: every goal condition must hold at that moment. Call `robo done` exactly once when finished.
"""

VERIFY = """\
#!/bin/bash
# Verifier: the episode server already judged success (BEHAVIOR's BDDL goal conditions, checked after `robo done`);
# copy its verdict. ROBOUSE_EPISODE_DIR points at the trusted episode directory (result.json from `robouse serve`).
set -euo pipefail
OUT="${ROBOUSE_VERIFIER_DIR:-/logs/verifier}"
mkdir -p "$OUT"
python3 - "$ROBOUSE_EPISODE_DIR/result.json" "$OUT/reward.txt" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
open(sys.argv[2], "w").write("1" if r.get("success") else "0")
print("success" if r.get("success") else "fail", r.get("outcome"))
EOF
"""

ORACLE = """\
#!/bin/bash
# Reference solution: a scripted sequence of BEHAVIOR symbolic primitives (plan.json), sent through the robo socket
# exactly like an agent's `robo skill` calls.
set -euo pipefail
ROBOUSE_BEHAVIOR_PLAN="$(dirname "$0")/plan.json" python -m robouse.oracle --backend behavior --env {activity}
"""


def bddl_goal(activity: str, bddl_root: Path | None) -> str:
    if bddl_root is None:
        return ""
    text = (bddl_root / activity / "problem0.bddl").read_text()
    return text[text.index("(:goal"):].rstrip().rstrip(")").rstrip()


def instruction(t: dict, goal: str) -> str:
    name = t["activity"].replace("_", " ")
    s = f"# BEHAVIOR: {name}\n\n{t['instruction']}\n\n"
    s += (f"This is the BEHAVIOR-1K activity `{t['activity']}` in the `{t['scene']}` house (rooms loaded: "
          f"{', '.join(ROOMS[t['scene']])}). The robot starts where the BEHAVIOR Challenge places it. "
          f"The step budget is {t['max_steps']} skill calls.\n\n")
    if goal:
        s += ("BEHAVIOR's formal goal (BDDL; `?x` are variables, `_1`, `_2` number objects of one category) is:\n\n"
              f"```\n{goal}\n```\n\n")
    return s + USAGE


def write(t: dict, out: Path, bddl_root: Path | None) -> str:
    tid = "behavior-" + t["activity"].replace("_", "-").lower()
    meta = {
        "task": {"name": f"robouse/{tid}", "description": t["instruction"]},
        "metadata": {"source_benchmark": SOURCE, "source_task": t["activity"], "suite": "behavior",
                     "behavior_scene": t["scene"], "behavior_instance": 0, "category": "household-long-horizon",
                     "difficulty": t["difficulty"], "language_instruction": t["instruction"],
                     "tags": ["behavior-1k", "omnigibson", "isaac-sim", "r1pro", "mobile-manipulation", "symbolic-primitives",
                              "remote-gpu"],
                     "reference_solution": f"scripted primitive plan, {len(t['plan'])} skills (oracle/plan.json)"},
        "agent": {"timeout_sec": 1800},
        "verifier": {"timeout_sec": 120},
        "robouse": {"id": tid, "backend": "behavior", "env": t["activity"], "scene": t["scene"],
                    "rooms": ROOMS[t["scene"]], "instance": 0, "seed": 0, "max_steps": t["max_steps"],
                    "camera": "follow", "cameras": ["follow", "head"], "skills": True, "success_mode": "final",
                    "obs_mode": "state", "frame_every": 1, "linger_s": 5},
    }
    d = out / tid
    if d.exists():
        shutil.rmtree(d)
    write_task(d, meta, instruction(t, bddl_goal(t["activity"], bddl_root)), ORACLE.format(activity=t["activity"]), VERIFY)
    (d / "oracle" / "plan.json").write_text(json.dumps(t["plan"], indent=1))
    return tid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks/behavior")
    ap.add_argument("--bddl", default="", help="path to bddl3/bddl/activity_definitions of a BEHAVIOR-1K checkout "
                                               "(to include the formal goal in the instruction)")
    ap.add_argument("--plans", default="", help="JSON file {activity: plan} overriding the built-in plans")
    a = ap.parse_args()
    extra = json.loads(Path(a.plans).read_text()) if a.plans else {}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for t in TASKS:
        t = {**t, "plan": extra.get(t["activity"], t["plan"])}
        if not t["plan"]:
            raise SystemExit(f"no plan for {t['activity']}")
        print(write(t, out, Path(a.bddl) if a.bddl else None))


if __name__ == "__main__":
    main()
