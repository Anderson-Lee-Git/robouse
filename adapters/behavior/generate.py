"""BEHAVIOR-1K (Stanford Vision and Learning Lab; OmniGibson on NVIDIA Isaac Sim) -> Robo Use tasks.

Activities from the 2026 BEHAVIOR Challenge task list (challenge_tasks.json: all 100, with the challenge's scene, loaded
rooms and instruction) whose BDDL goal the skill set can reach, each in its challenge scene with the Galaxea R1Pro
mobile manipulator. The agent drives the robot with symbolic skills (`robo skill ...`, see
src/robouse/backends/behavior.py); success is BEHAVIOR's BDDL goal. The simulator runs remotely on an RTX GPU; see
docs/suites/behavior.md.

Variants written per activity (plans.py holds the plans and instructions; the lists below pick the variants):
  behavior-<activity>               the challenge's task instance 0, full state in `robo observe`
  behavior-<activity>-instance-<k>  challenge task instance k (other object placements and robot start), full state
  behavior-<activity>-vision        instance 0, vision only: `robo observe` gives the robot's own state and the task
                                    objects' names; poses, open/on states and relations come from the cameras
The reference solution is a scripted skill sequence (oracle/plan.json) sent through the robo socket.

Usage: python adapters/behavior/generate.py --out tasks/behavior [--bddl <BEHAVIOR-1K>/bddl3/bddl/activity_definitions]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from robouse.tasks import write_task

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from plans import TASKS  # noqa: E402

SOURCE = "BEHAVIOR-1K (Li et al. 2022/2024), 2026 BEHAVIOR Challenge task list; OmniGibson 3.9.3 on Isaac Sim 5.1"
CHALLENGE = json.loads((HERE / "challenge_tasks.json").read_text())

# activities whose oracle did not pass in BEHAVIOR's own goal check, with the reason (kept out of the suite)
DROPPED: dict[str, str] = {
    "clearing_food_from_table_into_fridge": "place_inside finds no spot for the half chicken inside either tupperware "
    "container (BEHAVIOR's Inside sampler, 4 draws), so the goal cannot be reached",
    "boxing_books_up_for_storage": "the six books do not reliably fit into the box: in 3 of 4 reference runs one book "
    "found no spot inside it",
    "can_meat": "the two hinged jars do not fit back inside the cabinet (Inside sampler), and the bratwursts on the "
    "chopping board are out of reach from every free spot next to the counter",
    "preparing_lunch_box": "the bottle of tea does not fit inside the packing box (Inside sampler, 4 draws), in "
    "either order of packing",
    "sorting_bottles_cans_and_paper": "the newspaper and the magazine do not fit inside a bucket (Inside sampler)",
    "assembling_gift_baskets": "every skill succeeds, but the placed items do not stay inside the small wicker baskets "
    "on the floor: after settling none of the 16 items counts as inside",
    "outfit_a_basic_toolbox": "the toolbox lid falls shut again after `open` (place_inside then reports it closed), and "
    "the drill finds no spot inside the toolbox",
    "sorting_vegetables": "the mixing bowls cannot hold the vegetables: with two bok choy in a bowl, placing the third "
    "found no spot and the sampler ran past the robo client's 120 s timeout",
    "make_rose_centerpieces": "the roses do not fit inside the vase: the second rose found no spot (Inside sampler)",
    "bringing_paper_to_recycling": "the newspaper finds no spot inside the recycling bin (Inside sampler)",
    "clean_up_your_desk": "the child's room is too cramped for the base: navigate_to finds no free spot (0.38 m "
    "clearance) within reach of the desk, the bookcase or the items on them",
    "cleaning_up_branches_and_twigs": "the branches find no spot inside the recycling bin (Inside sampler; 4 of 4 "
    "branches failed with the bin open)",
    "put_together_a_basic_pruning_kit": "the shears find no spot inside the toolbox (Inside sampler)",
    "packing_meal_for_delivery": "the three paper sacks do not fit on top of the storage container: the second found "
    "no spot (OnTop sampler)",
    "store_batteries": "the battery on the kitchen countertop is out of reach: navigate_to finds no free spot next to it",
    "make_gift_bags_for_baby_showers": "the wafers find no spot inside the paper sacks (Inside sampler)",
    "organizing_school_stuff": "the folder finds no spot inside the tote bag (Inside sampler)",
    "boxing_food_after_dinner": "the second plate finds no spot on the kitchen sink (OnTop sampler)",
    "composting_waste": "the half banana finds no spot inside the kitchen trash can (Inside sampler; 2 of 2 runs)",
    "dispose_of_batteries": "every skill succeeds, but after settling the goal (batteries inside the trash can, the "
    "can on the copy-room floor) does not hold",
}
# extra challenge instances written for these activities (generalisation across object placements / start poses)
INSTANCES = {
    "picking_up_trash": [1],
    "bringing_water": [1, 2],
    "store_produce": [1],
    "turning_out_all_lights_before_sleep": [1],
}
# vision-only variants (instance 0)
VISION = [
    "picking_up_trash",
    "rearranging_kitchen_furniture",
    "putting_dishes_away_after_cleaning",
    "bringing_water",
    "turning_out_all_lights_before_sleep",
    "tidying_bathroom",
    "store_produce",
    "freeze_fruit",
]

OBSERVE_STATE = (
    "robo observe                       # robot pose, held object, and every task object (name, category, "
    "room, position, distance, open/on state, inside/on-top relations)\n"
)
OBSERVE_VISION = (
    "robo observe                       # the robot's own state (position, heading, room, held object), the "
    "task objects' names, and one picture per camera\n"
)
USAGE = """\
## How to control the robot

You are the robot's high-level policy. You act only through the `robo` command in your shell; you cannot read or change the simulator, the scoring, or other files to succeed. The episode server checks BEHAVIOR's goal conditions on the final simulated state itself.

```
robo info                          # skills, step budget
{observe}robo observe --image               # also saves a third-person camera image and prints its path (open it to look)
robo observe --image --camera head # the robot's own head camera instead
robo skill navigate_to OBJ         # drive next to OBJ (a held object comes along)
robo skill grasp OBJ               # pick up OBJ (hand must be empty, OBJ within reach); things resting in or on OBJ come along
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
- The robot is an R1Pro wheeled mobile manipulator that carries one object at a time. Manipulation skills only work on objects within reach (about 1.25 m from the robot base); use `navigate_to` first. Objects inside a closed container must be taken out after opening it.
- A skill can fail (the response says why, with `ok: False`); a failed skill still costs one step. Every skill call counts against the step budget (`robo info`).
- Success is judged after you call `robo done`, with the robot holding still: every goal condition must hold at that moment. Call `robo done` exactly once when finished.
"""
VISION_NOTE = (
    "Vision only: `robo observe` does not report where objects are, whether they are open or switched on, or "
    "what they rest on or in. It lists the task objects' names (what skills take) and the robot's own state, "
    "and saves one picture from each camera (`follow`, behind the robot, and `head`, the robot's own view). "
    "Look at the pictures to find out the state of the scene; skill responses also say when an action fails "
    "and why.\n\n"
)

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
# Reference solution: a scripted sequence of BEHAVIOR skills (plan.json), sent through the robo socket exactly like an
# agent's `robo skill` calls.
set -euo pipefail
ROBOUSE_BEHAVIOR_PLAN="$(dirname "$0")/plan.json" python -m robouse.oracle --backend behavior --env {activity}
"""


def bddl_goal(activity: str, bddl_root: Path | None) -> str:
    if bddl_root is None:
        return ""
    text = (bddl_root / activity / "problem0.bddl").read_text()
    return text[text.index("(:goal") :].rstrip().rstrip(")").rstrip()


def budget(plan: list) -> int:
    """About twice the reference plan plus 15, rounded up to a multiple of 5 (at least 20)."""
    return max(20, 5 * -(-(2 * len(plan) + 15) // 5))


def difficulty(plan: list) -> str:
    return "easy" if len(plan) <= 6 else "medium" if len(plan) <= 20 else "hard"


def instruction(t: dict, goal: str) -> str:
    name = t["activity"].replace("_", " ")
    s = f"# BEHAVIOR: {name}{' (vision only)' if t['vision'] else ''}\n\n{t['instruction']}\n\n"
    s += (
        f"This is the BEHAVIOR-1K activity `{t['activity']}` in the `{t['scene']}` scene (rooms loaded: "
        f"{', '.join(t['rooms'])}), BEHAVIOR Challenge task instance {t['instance']}. The robot starts where the "
        f"challenge places it for that instance. The step budget is {t['max_steps']} skill calls.\n\n"
    )
    if t["vision"]:
        s += VISION_NOTE
    if goal:
        s += (
            "BEHAVIOR's formal goal (BDDL; `?x` are variables, `_1`, `_2` number objects of one category) is:\n\n"
            f"```\n{goal}\n```\n\n"
        )
    return s + USAGE.format(observe=OBSERVE_VISION if t["vision"] else OBSERVE_STATE)


def task_id(activity: str, instance: int, vision: bool) -> str:
    tid = "behavior-" + activity.replace("_", "-").lower()
    return tid + (f"-instance-{instance}" if instance else "") + ("-vision" if vision else "")


def write(t: dict, out: Path, bddl_root: Path | None) -> str:
    tid = task_id(t["activity"], t["instance"], t["vision"])
    tags = [
        "behavior-1k",
        "omnigibson",
        "isaac-sim",
        "r1pro",
        "mobile-manipulation",
        "symbolic-skills",
        "remote-gpu",
        "gpu-required",
    ] + (["vision-only"] if t["vision"] else [])
    block = {
        "id": tid,
        "backend": "behavior",
        "env": t["activity"],
        "scene": t["scene"],
        "rooms": t["rooms"],
        "instance": t["instance"],
        "seed": 0,
        "max_steps": t["max_steps"],
        "camera": "follow",
        "cameras": ["follow", "head"],
        "skills": True,
        "success_mode": "final",
        "obs_mode": "state",
        "frame_every": 1,
        "linger_s": 5,
        "ready_timeout_s": 900,
        "rpc_timeout_s": 600,
    }
    if t["vision"]:
        block.update(obs_mode="vision", visible_fields=["robot", "object_names"])
    meta = {
        "task": {"name": f"robouse/{tid}", "description": t["instruction"]},
        "metadata": {
            "source_benchmark": SOURCE,
            "source_task": t["activity"],
            "suite": "behavior",
            "behavior_scene": t["scene"],
            "behavior_instance": t["instance"],
            "behavior_challenge_task_id": t["index"],
            "challenge_instruction": t["official"],
            "category": "household-long-horizon",
            "difficulty": difficulty(t["plan"]),
            "language_instruction": t["instruction"],
            "tags": tags,
            "requires_gpu": "NVIDIA RTX GPU with RT cores, for the remote simulator worker",
            "reference_solution": f"scripted skill plan, {len(t['plan'])} skills (oracle/plan.json)",
        },
        "agent": {"timeout_sec": 2400 if t["vision"] else 1800},
        "verifier": {"timeout_sec": 120},
        "robouse": block,
    }
    d = out / tid
    if d.exists():
        shutil.rmtree(d)
    write_task(
        d, meta, instruction(t, bddl_goal(t["activity"], bddl_root)), ORACLE.format(activity=t["activity"]), VERIFY
    )
    (d / "oracle" / "plan.json").write_text(json.dumps(t["plan"], indent=1))
    return tid


def variants():
    for act, t in TASKS.items():
        if act in DROPPED:
            continue
        c = CHALLENGE[act]
        base = {
            "activity": act,
            "scene": c["scene"],
            "rooms": c["rooms"],
            "index": c["index"],
            "official": c["official"],
            "instruction": t["instruction"],
            "max_steps": t.get("max_steps") or budget(t["plan"]),
        }
        yield {**base, "plan": t["plan"], "instance": 0, "vision": False}
        for k in INSTANCES.get(act, []):
            yield {**base, "plan": t.get("plans_by_instance", {}).get(k, t["plan"]), "instance": k, "vision": False}
        if act in VISION:
            yield {**base, "plan": t["plan"], "instance": 0, "vision": True}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks/behavior")
    ap.add_argument(
        "--bddl",
        default="",
        help="path to bddl3/bddl/activity_definitions of a BEHAVIOR-1K checkout "
        "(to include the formal goal in the instruction)",
    )
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("behavior-*"):  # the generator owns the whole suite folder
        shutil.rmtree(old)
    for t in variants():
        print(write(t, out, Path(a.bddl) if a.bddl else None))


if __name__ == "__main__":
    main()
