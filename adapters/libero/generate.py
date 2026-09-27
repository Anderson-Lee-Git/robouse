"""LIBERO (Liu et al. 2023) -> robouse tasks.

20 tasks: 5 per suite, LIBERO task indices 0, 2, 4, 6, 8 of libero_spatial, libero_object, libero_goal and
libero_10 (LIBERO's standard task order). Ids: libero-spatial-0, libero-object-2, libero-goal-4, libero-10-6, ...

LIBERO has no scripted experts, so the reference solution replays a human demonstration from LIBERO's own
demonstration dataset (HF `yifengzhu-hf/LIBERO-datasets`, one hdf5 file per task). Only the chosen demo's
`states` and `actions` are range-read from the hdf5 file (a few MB, not the 1+ GB file). The task's initial
state is that demonstration's first MuJoCo state, and oracle/demo_actions.json holds its recorded actions; the
oracle replays them open-loop through the `robo` socket. The adapter replays each candidate demonstration
in-process first and takes the first one (demo_0, demo_1, ...) whose replay reaches LIBERO's success check.

Usage: python adapters/libero/generate.py --out tasks/libero [--workers 4]
Needs hf-libero + robosuite 1.4.0 (see docs/suites/libero.md) and network access to the HF Hub.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import shutil
import textwrap
from pathlib import Path

from robouse.prompts import ROBO_USAGE
from robouse.tasks import write_task

INDICES = [0, 2, 4, 6, 8]
SUITES = {  # suite -> (short id, difficulty, agent timeout)
    "libero_spatial": ("spatial", "easy", 1200),
    "libero_object": ("object", "easy", 1200),
    "libero_goal": ("goal", "medium", 1200),
    "libero_10": ("10", "hard", 1800),
}
SUITE_NOTES = {
    "libero_spatial": "LIBERO-Spatial: the same objects in different layouts; the instruction says which of two identical bowls to move.",
    "libero_object": "LIBERO-Object: the same layout with different grocery items; pick the named item and put it in the basket.",
    "libero_goal": "LIBERO-Goal: one fixed kitchen scene; the instruction sets the goal.",
    "libero_10": "LIBERO-Long (libero_10): long-horizon tasks, most with two sub-goals.",
}
DATASET = "yifengzhu-hf/LIBERO-datasets"
MAX_DEMO_TRIES = 10


def fetch_demo(suite: str, task_name: str, k: int) -> tuple[list, list]:
    """First MuJoCo state and all actions of demo_k, range-read from the HF hdf5 file."""
    import h5py
    from huggingface_hub import HfFileSystem

    path = f"datasets/{DATASET}/{suite}/{task_name}_demo.hdf5"
    with HfFileSystem().open(path, "rb", block_size=1 << 20, cache_type="bytes") as f:
        d = h5py.File(f, "r")["data"][f"demo_{k}"]
        return d["states"][0].tolist(), d["actions"][()].tolist()


def replay_ok(suite: str, index: int, init_state: list, actions: list, max_steps: int) -> int | None:
    """Replay in-process, exactly as the oracle will through the socket; steps to first success or None."""
    from robouse.backends.libero import LiberoBackend

    b = LiberoBackend({"suite": suite, "env": index, "init_state": init_state})
    try:
        b.reset(0)
        for i, a in enumerate(actions[:max_steps]):
            if b.step(a).success:
                return i + 1
        return None
    finally:
        b.close()


def pick_demo(suite: str, index: int) -> dict:
    from robouse.backends.libero import SUITE_MAX_STEPS, libero_task

    i, task, _ = libero_task(suite, index)
    max_steps = SUITE_MAX_STEPS[suite]
    for k in range(MAX_DEMO_TRIES):
        init_state, actions = fetch_demo(suite, task.name, k)
        n = replay_ok(suite, i, init_state, actions, max_steps)
        if n:
            return {"suite": suite, "index": i, "name": task.name, "language": task.language, "demo": k,
                    "init_state": init_state, "actions": actions, "steps_to_success": n, "max_steps": max_steps,
                    "file": f"{suite}/{task.name}_demo.hdf5"}
    raise RuntimeError(f"no replayable demonstration among demo_0..{MAX_DEMO_TRIES - 1} for {suite}/{task.name}")


def instruction(t: dict) -> str:
    lang = t["language"][0].upper() + t["language"][1:]
    return textwrap.dedent(f"""\
    # {lang}

    A Franka Panda arm with a parallel-jaw gripper works at a table in a LIBERO scene (MuJoCo / robosuite; LIBERO suite `{t['suite']}`, task `{t['name']}`). {SUITE_NOTES[t['suite']]}

    **Goal (LIBERO's language instruction):** {t['language']}.

    The episode ends as solved the moment LIBERO's own success check (the task's goal predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

    ## This robot

    - The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand (1.0 asks for 0.5 rad; usually leave them at 0). GRIPPER -1 opens, +1 closes.
    - `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
    - World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. The table surface is at about z = 0.90.
    - `robo observe` fields: `hand_pos` (end-effector position), `eef_quat` (orientation quaternion x, y, z, w) and `eef_axis_angle`, `gripper_qpos` (the two finger joints), `gripper_open` (finger gap in metres, about 0.08 when fully open), and `objects`: the position and quaternion of every object in the scene, under LIBERO's names (e.g. `akita_black_bowl_1`, `plate_1`; `..._1`, `..._2` number identical objects).
    - `robo observe --image` saves the front camera (`agentview`); add `--camera robot0_eye_in_hand` for the wrist camera. Both are 256x256.
    - The step budget is {t['max_steps']} steps (LeRobot's LIBERO evaluation budget for this suite).

    """) + ROBO_USAGE


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


def write(t: dict, out: Path) -> str:
    short, difficulty, timeout = SUITES[t["suite"]]
    tid = f"libero-{short}-{t['index']}"
    meta = {
        "task": {"name": f"robouse/{tid}", "description": t["language"][0].upper() + t["language"][1:] + "."},
        "metadata": {"source_benchmark": "LIBERO (Liu et al. 2023)", "source_task": t["name"], "suite": "libero",
                     "libero_suite": t["suite"], "libero_task_index": t["index"],
                     "language_instruction": t["language"], "category": "manipulation",
                     "difficulty": difficulty, "tags": ["franka", "mujoco", "robosuite", "single-arm", "language"],
                     "reference_solution": f"LIBERO demonstration demo_{t['demo']} of {DATASET}/{t['file']} "
                                           f"(replay reaches success at step {t['steps_to_success']})"},
        "agent": {"timeout_sec": timeout},
        "verifier": {"timeout_sec": 120},
        "robouse": {"id": tid, "backend": "libero", "suite": t["suite"], "env": t["name"], "task_index": t["index"],
                    "seed": 0, "max_steps": t["max_steps"], "camera": "agentview",
                    "cameras": ["agentview", "robot0_eye_in_hand"], "image_size": 256, "settle_steps": 50,
                    "skills": True, "success_mode": "first", "obs_mode": "state",
                    "init_source": f"{DATASET}/{t['file']} demo_{t['demo']} states[0]",
                    "init_state": [float(x) for x in t["init_state"]]},
    }
    d = out / tid
    write_task(d, meta, instruction(t), ORACLE.format(demo=f"demo_{t['demo']}", file=t["file"], dataset=DATASET), VERIFY)
    (d / "oracle" / "demo_actions.json").write_text(json.dumps(
        {"source": f"{DATASET}/{t['file']}", "demo": f"demo_{t['demo']}", "steps_to_success": t["steps_to_success"],
         "actions": [[round(float(x), 6) for x in a] for a in t["actions"]]}))
    return tid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks/libero")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    out = Path(a.out)
    jobs = [(s, i) for s in SUITES for i in INDICES]
    with cf.ProcessPoolExecutor(a.workers) as ex:
        picked = list(ex.map(pick_demo, *zip(*jobs)))
    if out.exists():
        shutil.rmtree(out)
    for t in picked:
        tid = write(t, out)
        print(f"{tid:<20} demo_{t['demo']} success@{t['steps_to_success']:<4} budget {t['max_steps']}  {t['language']}")
    print(f"wrote {len(picked)} tasks to {out}")


if __name__ == "__main__":
    main()
