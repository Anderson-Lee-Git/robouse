"""LIBERO-PRO (Zhou et al. 2025) -> robouse tasks (suite "libero-pro"): the 80 pairs NVIDIA's ASPIRE reports on.

ASPIRE (github.com/NVlabs/ASPIRE, src/cap_harness/libero/registry.py, REQUIRED_SUITE_NAMES) evaluates LIBERO-Pro on
80 required (suite, task) pairs: the ten tasks of each of LIBERO-PRO's `swap` suites (the objects start in each
other's places) and `task` suites (the same scene with a new goal) for LIBERO-Goal, -Object, -Spatial and -Long
(`libero_10`). This writes them as tasks/libero-pro from LIBERO-PRO at the commit ASPIRE pins (uynitsuj/LIBERO-PRO
47aaa80, MIT), on Robo Use's LIBERO backend. Ids are libero-pro-<family>-<swap|task>-<k>, k being the task's index in
the LIBERO-PRO suite (LIBERO's standard order), so libero-pro-goal-task-8 is ASPIRE's `libero_goal_task:8`.

- Scene: LIBERO-PRO's BDDL file, verbatim in the task (`robouse.bddl`).
- Start: LIBERO-PRO's init file for the task (`robouse.init_states`: its URL at the pinned commit, its SHA-256 and the
  number of states; the backend downloads it at first use). The seed picks a state as ASPIRE's `--init-mode saved`
  does: seed n starts from state n - 1. The task's own seed is 1, and state 0 is copied into the task (`init_state`),
  so the task's default episode needs no download. Then 10 settle steps (ASPIRE's and LIBERO-PRO's).
- Success: LIBERO's check of the BDDL goal, the first time it holds (LIBERO-PRO's evaluation protocol).
- Instruction: the BDDL file's `(:language ...)`, the one ASPIRE gives its agents (LIBERO's task list derives an
  instruction from the file name, which in the task suites is the old goal).
- Budget: 1000 steps at 20 Hz, ASPIRE's episode length for LIBERO-Pro.
- Reference solution: the scripted solution (robouse.backends.libero.solver) on the privileged scene state, with
  per-task options in oracle/plan.json. The generator runs it in-process from the task's start before writing the task;
  a task it does not solve is not written, and the run says so. LEFT_OUT lists the seven pairs it does not solve, with
  the reasons, and the generator skips them.

Usage, in the LIBERO virtualenv (docs/suites/libero.md):

    python adapters/libero-pro/generate.py --root tasks [--only libero_goal_task:8,...] [--workers 8]

LIBERO-PRO's files are downloaded from GitHub at the pinned commit into <cache>/libero-pro-source, or read from a
checkout with --source PATH/TO/LIBERO-PRO.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import shutil
import textwrap
import time
import urllib.request
from pathlib import Path

REPO = "https://github.com/uynitsuj/LIBERO-PRO"
COMMIT = "47aaa8038930bcdc84ab9ea2867e2ffc8039ab4a"  # ASPIRE's third_party/LIBERO-PRO (configs/dependency-lock.json)
RAW = f"https://raw.githubusercontent.com/uynitsuj/LIBERO-PRO/{COMMIT}/libero/libero"
FAMILIES = {  # family -> (LIBERO suite, LIBERO suite title, difficulty, agent timeout)
    "goal": ("libero_goal", "LIBERO-Goal", "medium", 1800),
    "object": ("libero_object", "LIBERO-Object", "easy", 1800),
    "spatial": ("libero_spatial", "LIBERO-Spatial", "easy", 1800),
    "10": ("libero_10", "LIBERO-Long", "hard", 2400),
}
VARIANTS = {  # LIBERO-PRO perturbation -> what the scene differs in, for the instruction
    "swap": "the objects start in other places (LIBERO-PRO's position perturbation)",
    "task": "the goal is a new one (LIBERO-PRO's task perturbation)",
}
# The task files of LIBERO-PRO's swap and task suites: LIBERO's task names, in LIBERO's order (LIBERO-PRO's
# libero/libero/benchmark/libero_suite_task_map.py at the pinned commit)
NAMES = {
    "goal": [
        "open_the_middle_drawer_of_the_cabinet",
        "put_the_bowl_on_the_stove",
        "put_the_wine_bottle_on_top_of_the_cabinet",
        "open_the_top_drawer_and_put_the_bowl_inside",
        "put_the_bowl_on_top_of_the_cabinet",
        "push_the_plate_to_the_front_of_the_stove",
        "put_the_cream_cheese_in_the_bowl",
        "turn_on_the_stove",
        "put_the_bowl_on_the_plate",
        "put_the_wine_bottle_on_the_rack",
    ],
    "object": [
        f"pick_up_the_{x}_and_place_it_in_the_basket"
        for x in (
            "alphabet_soup",
            "cream_cheese",
            "salad_dressing",
            "bbq_sauce",
            "ketchup",
            "tomato_sauce",
            "butter",
            "milk",
            "chocolate_pudding",
            "orange_juice",
        )
    ],
    "spatial": [
        f"pick_up_the_black_bowl_{x}_and_place_it_on_the_plate"
        for x in (
            "between_the_plate_and_the_ramekin",
            "next_to_the_ramekin",
            "from_table_center",
            "on_the_cookie_box",
            "in_the_top_drawer_of_the_wooden_cabinet",
            "on_the_ramekin",
            "next_to_the_cookie_box",
            "on_the_stove",
            "next_to_the_plate",
            "on_the_wooden_cabinet",
        )
    ],
    "10": [
        "LIVING_ROOM_SCENE2_put_both_the_alphabet_soup_and_the_tomato_sauce_in_the_basket",
        "LIVING_ROOM_SCENE2_put_both_the_cream_cheese_box_and_the_butter_in_the_basket",
        "KITCHEN_SCENE3_turn_on_the_stove_and_put_the_moka_pot_on_it",
        "KITCHEN_SCENE4_put_the_black_bowl_in_the_bottom_drawer_of_the_cabinet_and_close_it",
        "LIVING_ROOM_SCENE5_put_the_white_mug_on_the_left_plate_and_put_the_yellow_and_white_mug_on_the_right_plate",
        "STUDY_SCENE1_pick_up_the_book_and_place_it_in_the_back_compartment_of_the_caddy",
        "LIVING_ROOM_SCENE6_put_the_white_mug_on_the_plate_and_put_the_chocolate_pudding_to_the_right_of_the_plate",
        "LIVING_ROOM_SCENE1_put_both_the_alphabet_soup_and_the_cream_cheese_box_in_the_basket",
        "KITCHEN_SCENE8_put_both_moka_pots_on_the_stove",
        "KITCHEN_SCENE6_put_the_yellow_and_white_mug_in_the_microwave_and_close_it",
    ],
}
# ASPIRE's order (REQUIRED_SUITE_NAMES): goal, object, spatial, long; swap before task
PAIRS = [(fam, var, k) for fam in FAMILIES for var in VARIANTS for k in range(10)]
# work surface per LIBERO scene class (the BDDL file's `(problem ...)`), as in adapters/libero/generate.py
SURFACE = {
    "LIBERO_Tabletop_Manipulation": ("works at a table", "The table surface is at about z = 0.90."),
    "LIBERO_Kitchen_Tabletop_Manipulation": ("works at a table", "The table surface is at about z = 0.90."),
    "LIBERO_Living_Room_Tabletop_Manipulation": ("works at a low table", "The table surface is at about z = 0.43."),
    "LIBERO_Study_Tabletop_Manipulation": ("works at a desk", "The desk surface is at about z = 0.88."),
    "LIBERO_Floor_Manipulation": ("works over the floor", "The objects stand on the floor, at about z = 0.0."),
}
MAX_STEPS = 1000  # ASPIRE's episode length for LIBERO-Pro (20 Hz ticks)
SETTLE_STEPS = 10  # ASPIRE's post-reset settle, and LIBERO-PRO's (OpenVLA-OFT's num_steps_wait)
SEED = 1  # ASPIRE's first seed: saved state 0
# Per-task options for the scripted reference solution (robouse.backends.libero.solver), written to oracle/plan.json.
# Keys are LIBERO-PRO suite:index; each entry says why the default does not do.
OPTIONS: dict[str, dict] = {}
# Pairs that are not written, and why (docs/suites/libero-pro.md lists them): the scripted reference solution does not
# reach their goal, so they have no sound reference solution.
LEFT_OUT: dict[str, str] = {
    "libero_goal_task:0": "the bottom drawer's handle is 5 cm above the table, under the middle drawer's handle: the "
    "solution's grasps of it (level, tilted down, and 16 variants of a hook from above) hit the table or the upper "
    "handle or miss the bar, and the drawer does not open",
    "libero_10_swap:3": "the solution puts the bowl in the open bottom drawer, but pushing the drawer shut stalls before "
    "it closes, with the bowl in it",
    "libero_10_task:3": "the wine bottle is 16 cm tall and the bottom drawer about 7 cm deep under the middle one: "
    "standing in the open drawer, the bottle keeps it from closing; it fits only lying down, which the solution's "
    "top-down grasps cannot do",
    "libero_10_swap:6": "the chocolate pudding starts 0.30 m from the robot's base, right under the arm: the hand cannot "
    "get above it pointing down or tilted away from the base (its moves stop 0.1 to 0.2 m short), so the solution "
    "never picks it up",
    "libero_10_swap:8": "the stove's cook region is 0.84 m from the robot's base: after the first moka pot is put down "
    "there the arm is stretched to its elbow limit, and robosuite's controller cannot bring it back for the second pot",
    "libero_10_swap:9": "the microwave opens sideways under its top, so a mug held from above cannot go in (the hand "
    "hits the top); LIBERO's operators held the mug by its handle with a tilted hand, which the solution does not do",
    "libero_10_task:9": "as libero_10_swap:9: the mug cannot be carried into the microwave by a top-down grasp",
}


def suite_of(fam: str, var: str) -> str:
    return f"{FAMILIES[fam][0]}_{var}"


def task_id(fam: str, var: str, k: int) -> str:
    return f"libero-pro-{fam}-{var}-{k}"


def fetch(rel: str, source: Path | None, cache: Path) -> bytes:
    """A file of LIBERO-PRO's libero/libero folder at the pinned commit: from a checkout, or downloaded once."""
    if source is not None:
        return (source / "libero" / "libero" / rel).read_bytes()
    dest = cache / COMMIT / rel
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{RAW}/{rel}", timeout=60) as r:
            data = r.read()
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
    return dest.read_bytes()


def load(fam: str, var: str, k: int, source: Path | None, cache: Path) -> dict:
    from robouse.backends.libero.backend import bddl_language, load_init_states

    suite, name = suite_of(fam, var), NAMES[fam][k]
    bddl = fetch(f"bddl_files/{suite}/{name}.bddl", source, cache).decode()
    init = fetch(f"init_files/{suite}/{name}.pruned_init", source, cache)
    tmp = cache / "tmp" / f"{suite}-{k}.pruned_init"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(init)
    states = load_init_states(tmp)
    problem = re.search(r"\(problem\s+([^\s)]+)\)", bddl)
    return {
        "family": fam,
        "variant": var,
        "index": k,
        "suite": suite,
        "name": name,
        "bddl": bddl,
        "language": bddl_language(bddl),
        "problem": problem.group(1) if problem else "",
        "init_url": f"{RAW}/init_files/{suite}/{name}.pruned_init",
        "init_sha256": hashlib.sha256(init).hexdigest(),
        "init_count": int(states.shape[0]),
        "init_state": [float(x) for x in states[(SEED - 1) % states.shape[0]]],
    }


def spec(t: dict) -> dict:
    """The task's robouse block."""
    return {
        "id": task_id(t["family"], t["variant"], t["index"]),
        "backend": "libero",
        "suite": t["suite"],
        "env": f"{t['suite']}:{t['index']}",
        "task_index": t["index"],
        "seed": SEED,
        "max_steps": MAX_STEPS,
        "camera": "agentview",
        "cameras": ["agentview", "robot0_eye_in_hand"],
        "image_size": 256,
        "settle_steps": SETTLE_STEPS,
        "skills": True,
        "success_mode": "first",
        "obs_mode": "vision",
        "visible_fields": ["hand_pos", "eef_quat", "eef_axis_angle", "gripper_qpos", "gripper_open"],
        "init_mode": "saved",
        "init_states": {"url": t["init_url"], "sha256": t["init_sha256"], "count": t["init_count"]},
        "init_index": (SEED - 1) % t["init_count"],
        "init_state": t["init_state"],
        "bddl": t["bddl"],
    }


# ---- checking the reference solution in-process ------------------------------------------------------------------------
PUBLIC = ("hand_pos", "eef_quat", "eef_axis_angle", "gripper_qpos", "gripper_open")


class InProcessArm:
    """The solver's arm interface on a backend in this process: the episode server's privileged observe and act, with
    LIBERO's first-success end and the step budget."""

    def __init__(self, backend, budget: int):
        self.b, self.budget, self.steps, self.success = backend, budget, 0, False

    def observe(self) -> dict:
        return {**self.b.observe(), **self.b.privileged_state()}

    def act(self, a, repeat: int = 1) -> dict:
        from robouse.backends.libero.solver import Done

        for _ in range(int(repeat)):
            self.steps += 1
            if self.b.step(a).success:
                self.success = True
                raise Done("success")
            if self.steps >= self.budget:
                raise Done("budget")
        o = self.b.observe()
        return {k: o[k] for k in PUBLIC}

    def done(self, text: str) -> None:
        pass


def check(t: dict, log_dir: Path | None = None) -> dict:
    """Run the reference solution on the task's own start: steps to success, or why not. The solution's log goes to
    `log_dir`/<suite>-<index>.log."""
    from robouse.backends.libero.backend import LiberoBackend
    from robouse.backends.libero.solver import Done, Solver

    s = spec(t)
    b = LiberoBackend(s)
    for cam in s["cameras"]:  # the solver reads state, not images: render nothing, which is several times faster
        for attr in ("enabled", "active"):
            b.env.env.modify_observable(f"{cam}_image", attr, False)
    try:
        b.reset(SEED)
        if b.success():
            return {"ok": False, "why": "the goal already holds at the start"}
        arm = InProcessArm(b, MAX_STEPS)
        opts = OPTIONS.get(f"{t['suite']}:{t['index']}", {})
        lines: list[str] = []
        try:
            Solver(arm, opts.get("options"), lambda *a: lines.append(f"[{arm.steps:4d}] " + " ".join(map(str, a)))).run(
                opts.get("steps")
            )
        except Done:
            pass
        finally:
            if log_dir is not None:
                log_dir.mkdir(parents=True, exist_ok=True)
                (log_dir / f"{t['suite']}-{t['index']}.log").write_text("\n".join(lines) + "\n")
        if not arm.success:
            return {"ok": False, "why": f"the reference solution did not reach the goal ({arm.steps} steps)"}
        return {"ok": True, "steps": arm.steps}
    finally:
        b.close()


# ---- writing -----------------------------------------------------------------------------------------------------------
def instruction(t: dict) -> str:
    from robouse.core.prompts import ROBO_USAGE

    lang = t["language"]
    title = lang[0].upper() + lang[1:]
    where, surface = SURFACE.get(t["problem"], ("works at a table", ""))
    suite_title = FAMILIES[t["family"]][1]
    return (
        textwrap.dedent(f"""\
    # {title}

    A Franka Panda arm with a parallel-jaw gripper {where} in a LIBERO scene (MuJoCo / robosuite). The task is from LIBERO-PRO's `{t['suite']}` suite: {suite_title}'s scene, where {VARIANTS[t['variant']]}.

    **Goal (LIBERO-PRO's language instruction):** {lang}

    The episode ends as solved the moment LIBERO's own success check (the goal's predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

    ## This robot

    - The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand about the world axes (1.0 asks for 0.5 rad); GRIPPER -1 opens, +1 closes.
    - `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
    - World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. {surface}
    - You see the scene only through the cameras. `robo observe` gives the robot's own state: `hand_pos` (end-effector position), `eef_quat` (orientation quaternion x, y, z, w) and `eef_axis_angle`, `gripper_qpos` (the two finger joints) and `gripper_open` (finger gap in metres, about 0.08 when fully open). It does not say where the objects are. Each `robo observe` also saves a 256x256 image from the front camera (`agentview`) and one from the wrist camera (`robot0_eye_in_hand`), and prints their paths; open them to look.
    - `robo info` lists each camera with a 3x4 `projection` matrix P: for a world point (x, y, z), `[u*w, v*w, w] = P @ [x, y, z, 1]` gives its pixel (u, v) in that camera's saved image (u to the right, v down, origin at the top-left). The wrist camera moves with the hand: its matrix is for the hand's pose when you call `robo info`.
    - The step budget is {MAX_STEPS} steps (50 seconds of simulated time).

    """)
        + ROBO_USAGE
    )


VERIFY = """\
#!/bin/bash
# Verifier: the episode server already judged success (LIBERO's check_success, first-success protocol); copy its verdict.
# ROBOUSE_EPISODE_DIR points at the trusted episode directory (result.json written by `robouse serve`).
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
# Reference solution: the scripted LIBERO solution (robouse.backends.libero.solver) through the robo socket, reading the
# scene from the reference solution's privileged observation; plan.json holds this task's options, if any.
set -euo pipefail
python -m robouse.oracle --backend libero_scripted --env "$(dirname "$0")/plan.json"
"""


def write(t: dict, out: Path) -> str:
    from robouse.tasks import write_task

    s = spec(t)
    tid = s["id"]
    lang = t["language"]
    meta = {
        "task": {"name": f"robouse/{tid}", "description": lang[0].upper() + lang[1:].rstrip(".") + "."},
        "metadata": {
            "source_benchmark": f"LIBERO-PRO (Zhou et al. 2025), {REPO.removeprefix('https://github.com/')} at "
            f"{COMMIT[:7]}, the commit NVIDIA's ASPIRE pins",
            "source_task": f"{t['suite']}/{t['name']}.bddl",
            "suite": "libero-pro",
            "libero_pro_suite": t["suite"],
            "libero_pro_task_index": t["index"],
            "aspire_task_ref": f"{t['suite']}:{t['index']}",
            "language_instruction": lang,
            "category": "manipulation",
            "difficulty": FAMILIES[t["family"]][2],
            "tags": ["franka", "mujoco", "robosuite", "single-arm", "language", "vision", "libero-pro"],
            "reference_solution": "scripted solution on the privileged scene state (robouse.backends.libero.solver, "
            "oracle kind libero_scripted)",
        },
        "agent": {"timeout_sec": FAMILIES[t["family"]][3]},
        "verifier": {"timeout_sec": 120},
        "robouse": s,
    }
    d = out / "libero-pro" / tid
    if d.exists():
        shutil.rmtree(d)
    write_task(d, meta, instruction(t), ORACLE, VERIFY)
    plan = OPTIONS.get(f"{t['suite']}:{t['index']}", {})
    (d / "oracle" / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    return tid


def job(fam: str, var: str, k: int, source: str | None, cache: str, run: bool = True) -> tuple[dict, dict]:
    t = load(fam, var, k, Path(source) if source else None, Path(cache))
    return t, check(t, Path(cache) / "logs") if run else {"ok": True, "steps": None}


def main() -> None:
    from robouse import config

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default="tasks", help="tasks folder; writes <root>/libero-pro")
    ap.add_argument("--source", help="a LIBERO-PRO checkout at the pinned commit (default: download its files)")
    ap.add_argument("--only", help="comma-separated LIBERO-PRO suite:index pairs to (re)generate")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--no-check",
        action="store_true",
        help="write the tasks without running the reference solution (no LIBERO needed); for text changes to tasks "
        "already checked",
    )
    a = ap.parse_args()
    cache = config.cache_dir() / "libero-pro-source"
    jobs = [p for p in PAIRS if not a.only or f"{suite_of(p[0], p[1])}:{p[2]}" in a.only.split(",")]
    jobs = [p for p in jobs if f"{suite_of(p[0], p[1])}:{p[2]}" not in LEFT_OUT]
    out = Path(a.root)
    written, left_out = [], []
    t0 = time.time()
    with cf.ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(job, *p, a.source, str(cache), not a.no_check): p for p in jobs}
        for f in cf.as_completed(futs):
            fam, var, k = futs[f]
            ref = f"{suite_of(fam, var)}:{k}"
            try:
                t, res = f.result()
            except Exception as e:  # keep going: the task is reported and left out
                left_out.append((ref, f"{type(e).__name__}: {e}"))
                print(f"FAILED  {ref}: {type(e).__name__}: {e}", flush=True)
                continue
            if not res["ok"]:
                left_out.append((ref, res["why"]))
                print(f"LEFT OUT {ref}: {res['why']}", flush=True)
                continue
            tid = write(t, out)
            written.append(tid)
            done = f"success@{res['steps']}" if res["steps"] is not None else "not run"
            print(f"{tid:<26} {ref:<22} {done:<12} {t['language']}", flush=True)
    print(f"wrote {len(written)} of {len(jobs)} tasks under {out / 'libero-pro'} in {time.time() - t0:.0f} s")
    for ref, why in sorted(left_out):
        print(f"  left out {ref}: {why}")


if __name__ == "__main__":
    main()
