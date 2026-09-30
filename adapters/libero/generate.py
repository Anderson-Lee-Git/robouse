"""LIBERO (Liu et al. 2023) -> robouse tasks.

All 130 LIBERO tasks, in LIBERO's standard task order:
- tasks/libero: the four standard suites, 10 tasks each (libero_spatial, libero_object, libero_goal, libero_10).
  Ids: libero-spatial-0 ... libero-spatial-9, libero-object-<k>, libero-goal-<k>, libero-10-<k>.
- tasks/libero-90: LIBERO-90 (libero_90), 90 tasks. Ids: libero-90-0 ... libero-90-89.

LIBERO has no scripted experts, so the reference solution replays a human demonstration from LIBERO's own
demonstration dataset (HF `yifengzhu-hf/LIBERO-datasets`, one hdf5 file per task). Only the chosen demo's
`states` and `actions` are range-read from the hdf5 file (a few MB, not the 1+ GB file). The task's initial
state is that demonstration's first MuJoCo state, and oracle/demo_actions.json holds its recorded actions; the
oracle replays them open-loop through the `robo` socket. The adapter replays each candidate demonstration
in-process first and takes the first one (demo_0, demo_1, ...) whose replay reaches LIBERO's success check.

If no demonstration replays (one task, libero_90 51: its demonstrations were recorded with the robot about 14 cm
further back than in the released scene, so an open-loop replay reaches past the butter), the adapter falls back to
tracking the demonstration's recorded end-effector path: it closes the loop on the hand position (delta = remaining
offset to the next recorded `ee_pos`), keeps the demonstration's rotation and gripper commands, and records the
resulting actions as demo_actions.json. The oracle then replays those open-loop like any other task.

Usage: python adapters/libero/generate.py --root tasks [--suites libero_90] [--workers 3]
Needs hf-libero + robosuite 1.4.0 (see docs/suites/libero.md) and network access to the HF Hub.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import shutil
import textwrap
from pathlib import Path

from robouse.core.prompts import ROBO_USAGE
from robouse.tasks import write_task

SUITES = {  # suite -> (short id, difficulty, agent timeout, task folder under tasks/)
    "libero_spatial": ("spatial", "easy", 1200, "libero"),
    "libero_object": ("object", "easy", 1200, "libero"),
    "libero_goal": ("goal", "medium", 1200, "libero"),
    "libero_10": ("10", "hard", 1800, "libero"),
    "libero_90": ("90", "medium", 1500, "libero-90"),
}
SUITE_NOTES = {
    "libero_spatial": "LIBERO-Spatial: the same objects in different layouts; the instruction says which of two identical bowls to move.",
    "libero_object": "LIBERO-Object: the same layout with different grocery items; pick the named item and put it in the basket.",
    "libero_goal": "LIBERO-Goal: one fixed kitchen scene; the instruction sets the goal.",
    "libero_10": "LIBERO-Long (libero_10): long-horizon tasks, most with two sub-goals.",
    "libero_90": "LIBERO-90: 90 short-horizon tasks in 20 kitchen, living-room and study scenes (the task name starts with the scene); LIBERO uses them for pretraining.",
}
# work surface per LIBERO scene class (the BDDL file's `(define (problem ...)`), measured from the objects' resting heights
SURFACE = {
    "LIBERO_Tabletop_Manipulation": ("works at a table", "The table surface is at about z = 0.90."),
    "LIBERO_Kitchen_Tabletop_Manipulation": ("works at a table", "The table surface is at about z = 0.90."),
    "LIBERO_Living_Room_Tabletop_Manipulation": ("works at a low table", "The table surface is at about z = 0.43."),
    "LIBERO_Study_Tabletop_Manipulation": ("works at a desk", "The desk surface is at about z = 0.88."),
    "LIBERO_Floor_Manipulation": ("works over the floor", "The objects stand on the floor, at about z = 0.0."),
}
DATASET = "yifengzhu-hf/LIBERO-datasets"
DATASET_REVISION = "f13aa24a3da8c43c7225569f28c562979fa0e35a"  # pinned so regenerating gives the same demos
MAX_DEMO_TRIES = 50  # every task file holds 50 demonstrations


def fetch_demo(suite: str, task_name: str, k: int, ee: bool = False) -> tuple:
    """First MuJoCo state and all actions of demo_k (and its recorded end-effector path if `ee`), range-read from
    the HF hdf5 file."""
    import h5py
    from huggingface_hub import HfFileSystem

    path = f"datasets/{DATASET}@{DATASET_REVISION}/{suite}/{task_name}_demo.hdf5"
    with HfFileSystem().open(path, "rb", block_size=1 << 20, cache_type="bytes") as f:
        d = h5py.File(f, "r")["data"][f"demo_{k}"]
        out = (d["states"][0].tolist(), d["actions"][()].tolist())
        return out + (d["obs"]["ee_pos"][()].tolist(),) if ee else out


def track_demo(suite: str, index: int, init_state: list, actions: list, ee_path: list, max_steps: int) -> list:
    """Actions that follow the demonstration's recorded end-effector path from its first state: first move the hand
    to the path's start (gripper open, at most 40 steps), then per step aim at the next recorded position, with the
    demonstration's own rotation and gripper commands. Returns the actions taken (up to first success or budget)."""
    import numpy as np

    from robouse.backends.libero.backend import LiberoBackend

    b = LiberoBackend({"suite": suite, "env": index, "init_state": init_state})
    ee = np.asarray(ee_path, dtype=float)
    out: list = []

    def act(a) -> bool:
        a = [round(float(x), 6) for x in a]  # as stored in demo_actions.json
        out.append(a)
        return b.step(a).success or len(out) >= max_steps

    try:
        b.reset(0)
        for _ in range(40):
            if np.linalg.norm(ee[0] - b.hand_pos()) < 0.005:
                break
            if act(list(np.clip((ee[0] - b.hand_pos()) / 0.05, -1, 1)) + [0, 0, 0, -1]):
                return out
        for t, a in enumerate(actions):
            a = np.array(a, dtype=float)
            a[:3] = np.clip((ee[min(t + 1, len(ee) - 1)] - b.hand_pos()) / 0.05, -1, 1)
            if act(a):
                return out
        return out
    finally:
        b.close()


def replay_ok(suite: str, index: int, init_state: list, actions: list, max_steps: int) -> int | None:
    """Replay in-process, exactly as the oracle will through the socket; steps to first success or None."""
    from robouse.backends.libero.backend import LiberoBackend

    b = LiberoBackend({"suite": suite, "env": index, "init_state": init_state})
    try:
        b.reset(0)
        for i, a in enumerate(actions[:max_steps]):
            if b.step(a).success:
                return i + 1
        return None
    finally:
        b.close()


def scene_problem(task) -> str:
    """LIBERO scene class of a task, from its BDDL file."""
    import re

    from robouse.backends.libero.backend import _quiet_imports

    _, get_libero_path, _ = _quiet_imports()
    bddl = Path(get_libero_path("bddl_files"), task.problem_folder, task.bddl_file).read_text()
    return re.search(r"\(problem\s+([^\s)]+)\)", bddl).group(1)


CACHE = Path.home() / ".cache" / "robouse" / "libero-demos"  # picked demos, so re-writing the tasks skips the replays


def pick_demo(suite: str, index: int) -> dict | None:
    cached = CACHE / f"{DATASET_REVISION[:12]}-{suite}-{index}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    t = _pick_demo(suite, index)
    if t is not None:
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(t))
    return t


def _pick_demo(suite: str, index: int) -> dict | None:
    from robouse.backends.libero.backend import SUITE_MAX_STEPS, libero_task

    i, task, _ = libero_task(suite, index)
    problem = scene_problem(task)
    max_steps = SUITE_MAX_STEPS[suite]
    for k in range(MAX_DEMO_TRIES):
        init_state, actions = fetch_demo(suite, task.name, k)
        n = replay_ok(suite, i, init_state, actions, max_steps)
        if n:
            return {
                "suite": suite,
                "index": i,
                "name": task.name,
                "language": task.language,
                "demo": k,
                "problem": problem,
                "init_state": init_state,
                "actions": actions,
                "steps_to_success": n,
                "max_steps": max_steps,
                "file": f"{suite}/{task.name}_demo.hdf5",
            }
    print(
        f"no replayable demonstration among demo_0..{MAX_DEMO_TRIES - 1} for {suite}/{task.name}; "
        "tracking the recorded end-effector paths instead",
        flush=True,
    )
    for k in range(MAX_DEMO_TRIES):
        init_state, actions, ee_path = fetch_demo(suite, task.name, k, ee=True)
        tracked = track_demo(suite, i, init_state, actions, ee_path, max_steps)
        n = replay_ok(suite, i, init_state, tracked, max_steps)
        if n:
            return {
                "suite": suite,
                "index": i,
                "name": task.name,
                "language": task.language,
                "demo": k,
                "problem": problem,
                "init_state": init_state,
                "actions": tracked[:n],
                "steps_to_success": n,
                "max_steps": max_steps,
                "file": f"{suite}/{task.name}_demo.hdf5",
                "tracked": True,
            }
    print(f"no demonstration of {suite}/{task.name} works, replayed or tracked", flush=True)
    return None


def instruction(t: dict) -> str:
    lang = t["language"][0].upper() + t["language"][1:]
    where, surface = SURFACE[t["problem"]]
    return (
        textwrap.dedent(f"""\
    # {lang}

    A Franka Panda arm with a parallel-jaw gripper {where} in a LIBERO scene (MuJoCo / robosuite; LIBERO suite `{t['suite']}`, task `{t['name']}`). {SUITE_NOTES[t['suite']]}

    **Goal (LIBERO's language instruction):** {t['language']}.

    The episode ends as solved the moment LIBERO's own success check (the task's goal predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

    ## This robot

    - The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand (1.0 asks for 0.5 rad; usually leave them at 0). GRIPPER -1 opens, +1 closes.
    - `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
    - World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. {surface}
    - `robo observe` fields: `hand_pos` (end-effector position), `eef_quat` (orientation quaternion x, y, z, w) and `eef_axis_angle`, `gripper_qpos` (the two finger joints), `gripper_open` (finger gap in metres, about 0.08 when fully open), and `objects`: the position and quaternion of every object in the scene, under LIBERO's names (e.g. `akita_black_bowl_1`, `plate_1`; `..._1`, `..._2` number identical objects); `fixtures`: the position and quaternion of each piece of furniture (cabinet, stove, microwave, rack, shelf, ...); `articulated`: each movable part of a fixture (drawer slide, door hinge, stove knob), keyed by its joint name (e.g. `wooden_cabinet_1_top_level` is the cabinet's top drawer), with `qpos` (joint position), `range` (joint limits), LIBERO's thresholds for that fixture (`open_ranges` / `close_ranges`, or `turnon_ranges` / `turnoff_ranges` for a stove knob: the joint positions at which LIBERO counts the part as open / closed or on / off) and `box_min` / `box_max` (the world-frame bounding box of the moving part).
    - `robo observe --image` saves the front camera (`agentview`); add `--camera robot0_eye_in_hand` for the wrist camera. Both are 256x256.
    - The step budget is {t['max_steps']} steps (LeRobot's LIBERO evaluation budget for this suite).

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
# Reference solution: replay LIBERO demonstration {demo} of {file} ({dataset}) through the robo socket.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
"""

ORACLE_TRACKED = """\
#!/bin/bash
# Reference solution: follow the end-effector path of LIBERO demonstration {demo} of {file} ({dataset}) through the
# robo socket. Its recorded actions do not replay in the released scene (the robot sits about 14 cm further forward
# than when it was recorded), so the adapter tracked the recorded hand positions closed-loop and saved those actions.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
"""


def write(t: dict, out: Path) -> str:
    short, difficulty, timeout, folder = SUITES[t["suite"]]
    tid = f"libero-{short}-{t['index']}"
    meta = {
        "task": {"name": f"robouse/{tid}", "description": t["language"][0].upper() + t["language"][1:] + "."},
        "metadata": {
            "source_benchmark": "LIBERO (Liu et al. 2023)",
            "source_task": t["name"],
            "suite": folder,
            "libero_suite": t["suite"],
            "libero_task_index": t["index"],
            "language_instruction": t["language"],
            "category": "manipulation",
            "difficulty": difficulty,
            "tags": ["franka", "mujoco", "robosuite", "single-arm", "language"],
            "reference_solution": (
                f"end-effector path of LIBERO demonstration demo_{t['demo']} of {DATASET}/{t['file']}, "
                f"tracked closed-loop (the recorded actions do not replay in the released scene); "
                f"success at step {t['steps_to_success']}"
            )
            if t.get("tracked")
            else (
                f"LIBERO demonstration demo_{t['demo']} of {DATASET}/{t['file']} "
                f"(replay reaches success at step {t['steps_to_success']})"
            ),
        },
        "agent": {"timeout_sec": timeout},
        "verifier": {"timeout_sec": 120},
        "robouse": {
            "id": tid,
            "backend": "libero",
            "suite": t["suite"],
            "env": t["name"],
            "task_index": t["index"],
            "seed": 0,
            "max_steps": t["max_steps"],
            "camera": "agentview",
            "cameras": ["agentview", "robot0_eye_in_hand"],
            "image_size": 256,
            "settle_steps": 50,
            "skills": True,
            "success_mode": "first",
            "obs_mode": "state",
            "init_source": f"{DATASET}/{t['file']} demo_{t['demo']} states[0]",
            "init_state": [float(x) for x in t["init_state"]],
        },
    }
    d = out / folder / tid
    if d.exists():
        shutil.rmtree(d)
    write_task(
        d,
        meta,
        instruction(t),
        (ORACLE_TRACKED if t.get("tracked") else ORACLE).format(
            demo=f"demo_{t['demo']}", file=t["file"], dataset=DATASET
        ),
        VERIFY,
    )
    (d / "oracle" / "demo_actions.json").write_text(
        json.dumps(
            {
                "source": f"{DATASET}/{t['file']}",
                "demo": f"demo_{t['demo']}",
                "steps_to_success": t["steps_to_success"],
                **({"method": "tracked end-effector path"} if t.get("tracked") else {}),
                "actions": [[round(float(x), 6) for x in a] for a in t["actions"]],
            }
        )
    )
    return tid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tasks", help="tasks folder; writes <root>/libero and <root>/libero-90")
    ap.add_argument("--suites", default=",".join(SUITES), help="comma-separated LIBERO suites to (re)generate")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    from robouse.backends.libero.backend import libero_task

    out = Path(a.root)
    jobs = [(s, i) for s in a.suites.split(",") for i in range(libero_task(s, 0)[2].get_num_tasks())]
    written = 0
    with cf.ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(pick_demo, s, i): (s, i) for s, i in jobs}
        for f in cf.as_completed(futs):
            s, i = futs[f]
            try:
                t = f.result()
            except Exception as e:  # keep going; the task is reported and left out
                print(f"FAILED {s} task {i}: {e!r}", flush=True)
                continue
            if t is None:
                print(f"DROPPED {s} task {i}: no demonstration replays to success", flush=True)
                continue
            tid = write(t, out)
            written += 1
            print(
                f"{tid:<20} demo_{t['demo']} success@{t['steps_to_success']:<4} budget {t['max_steps']}  {t['language']}",
                flush=True,
            )
    print(f"wrote {written} of {len(jobs)} tasks under {out}")


if __name__ == "__main__":
    main()
