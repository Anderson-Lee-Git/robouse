"""Adroit hand (Gymnasium-Robotics `AdroitHand{Door,Hammer,Pen,Relocate}-v1`) -> Robo Use tasks (suite "adroit").

Three tasks per env. Each starts from the initial state of one DAPG human demonstration in Farama's Minari dataset
`D4RL/<env>/human-v2` (Hugging Face `farama-minari/D4RL`, pinned revision below), restored with the env's own
`set_env_state`; the reference solution (oracle/demo.json) replays that demonstration's actions through the robo socket.
The episodes were chosen where the replay in gymnasium-robotics 1.4.2 / MuJoCo 3.3.0 ends in success, holding the
targets does not already succeed, and the start states differ (door position, nail height, pen goal, ball and target).

Usage: python adapters/adroit/generate.py [--out tasks/adroit] [--minari DIR]
(DIR holds <env>/main_data.hdf5; missing files are downloaded from the pinned revision, 3-6 MB each.)
"""
from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from pathlib import Path

import numpy as np

from robouse.backends.adroit.backend import AdroitBackend
from robouse.core.prompts import EMBODIED_USAGE
from robouse.tasks import write_task

HF_REPO = "farama-minari/D4RL"
HF_REVISION = "a0fd465d1d9d253b075d532b270e03d8fb4f46e6"

# task id -> (env kind, Minari human-v2 episode index, step budget)
TASKS = {
    "adroit-door-e11": ("door", 11, 1000),
    "adroit-door-e18": ("door", 18, 1000),
    "adroit-door-e23": ("door", 23, 1000),
    "adroit-hammer-e14": ("hammer", 14, 1500),
    "adroit-hammer-e18": ("hammer", 18, 1500),
    "adroit-hammer-e19": ("hammer", 19, 1500),
    "adroit-pen-e1": ("pen", 1, 600),
    "adroit-pen-e7": ("pen", 7, 600),
    "adroit-pen-e11": ("pen", 11, 600),
    "adroit-relocate-e0": ("relocate", 0, 1500),
    "adroit-relocate-e5": ("relocate", 5, 1500),
    "adroit-relocate-e17": ("relocate", 17, 1500),
}

VERIFY = """\
#!/bin/bash
# Verifier: the episode server already judged the final physical state; copy its verdict.
# ROBOUSE_EPISODE_DIR points at the trusted episode directory (result.json written by `robouse serve`).
set -euo pipefail
mkdir -p /logs/verifier 2>/dev/null || true
OUT="${ROBOUSE_VERIFIER_DIR:-/logs/verifier}"
mkdir -p "$OUT"
python3 - "$ROBOUSE_EPISODE_DIR/result.json" "$OUT/reward.txt" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
open(sys.argv[2], "w").write("1" if r.get("success") else "0")
print("success" if r.get("success") else "fail", r.get("outcome"))
EOF
"""

HAND = (
    "The robot is the ADROIT hand: a 24-joint, human-sized, Shadow-style right hand (wrist WRJ1 side-to-side and WRJ0 up-down; first "
    "(FF), middle (MF) and ring (RF) fingers with J3 spread, J2 knuckle, J1 middle and J0 tip joints; the little finger (LF) with an extra "
    "J4 palm joint; the thumb (TH) with J4 rotation, J3, J2, J1 and J0 tip joints). Finger joints J2, J1, J0 bend the finger toward the "
    "palm as they increase (0 = straight, 1.6 rad = fully bent). Every joint is driven by a position servo toward its target (the "
    "joint position it should settle at). The arm servos are weak (upstream gains): an arm joint settles near, not exactly at, its "
    "target, and gravity makes the hand sag (the vertical slide and the tilt settle a little low). "
    "World frame in metres: z up, the table top at z = 0, the forearm lies along +y behind the hand and the straight fingers point "
    "along +y, about 10 cm beyond the palm."
)

ENV_TEXT = {
    "door": dict(
        title="Adroit Door", upstream="AdroitHandDoor-v1",
        arm="The hand is on an arm with 4 actuators: ARTz (slide, m: moves the whole arm along world +y, toward the door), ARRx (tilts "
            "the forearm about world x at its base, 0.5 m behind the palm: increasing it lowers the hand), ARRy (swings the forearm about the "
            "vertical: increasing it moves the hand toward -x) and ARRz (rolls the forearm about its own axis, world y), all rad except ARTz.",
        scene="A door stands on the table in front of the hand. It is shut by a latch: its lever handle (`handle_pos`) must be turned "
              "down (the `latch` angle increases from 0 as it turns; the latch has strong dry friction and a spring that holds the door "
              "shut) before the door can swing. The door opens by pulling it toward the hand (the hinge is on the door's left edge).",
        goal="Unlatch the door and swing it open.",
        success="`door_hinge` (the door angle, rad) is at least 1.35 (the door touches its stopper), which is the env's own success signal "
                "(`info['success']`).",
        fields="`handle_pos` (the lever handle), `door_hinge` (rad, 0 = shut), `latch` (rad, 0 = latched), `door_open` (`door_hinge` >= 1.35)",
        difficulty="hard",
    ),
    "hammer": dict(
        title="Adroit Hammer", upstream="AdroitHandHammer-v1",
        arm="The hand is on an arm with 2 actuators (rad): ARRx (tilts the forearm about world x at its base, 0.5 m behind the palm: "
            "increasing it lowers the hand) and ARRy (swings the forearm about the vertical: increasing it moves the hand toward -x); the arm "
            "cannot slide.",
        scene="A hammer lies on the table under the hand, its handle along x (`hammer_pos` is its centre, `hammer_head_pos` the striking "
              "face of its head). A board stands to the side with a nail sticking out of it toward the hammer (`nail_pos` is the nail head; "
              "`nail_goal_pos` is where the nail head is when it is driven fully in). Pick up the hammer and strike the nail head along the "
              "nail's axis.",
        goal="Pick up the hammer and drive the nail into the board.",
        success="the nail head is within 1 cm of its fully-driven position (`nail_goal_distance` < 0.01), which is the env's own success "
                "signal (`info['success']`).",
        fields="`hammer_pos`, `hammer_rot` (Euler xyz, rad), `hammer_head_pos`, `nail_pos`, `nail_goal_pos`, `nail_goal_distance` (m)",
        difficulty="hard",
    ),
    "pen": dict(
        title="Adroit Pen", upstream="AdroitHandPen-v1",
        arm="The hand has no arm joints: the forearm is fixed and only the wrist and fingers move.",
        scene="The hand is held palm-up and holds a pen (a cylinder about 23 cm long) lying across its fingers. A second, floating pen "
              "beside the hand (the target, not touchable) shows the goal orientation. Turn the pen in the hand (in-hand manipulation) so "
              "it points the same way, without dropping it or letting it drift away.",
        goal="Rotate the pen in the hand to match the target orientation.",
        success="the pen's direction matches the target's (`orientation_similarity`, the dot product of the two unit vectors, above 0.95) "
                "and the pen's centre is within 7.5 cm of its starting point `pen_home_pos` (`pen_home_distance` < 0.075), which is the env's "
                "own success signal (`info['success']`).",
        fields="`pen_pos` (centre), `pen_dir` and `target_dir` (unit vectors along the pen and the target, from the bottom end to the top "
               "end), `orientation_similarity`, `pen_home_pos`, `pen_home_distance` (m)",
        difficulty="hard",
    ),
    "relocate": dict(
        title="Adroit Relocate", upstream="AdroitHandRelocate-v1",
        arm="The hand is on an arm with 6 actuators: three slides (m) that move the whole arm, ARTx along world -x (increasing it moves "
            "the hand toward -x), ARTy along world +z (up) and ARTz along world +y (away from the forearm), and three rotations (rad), ARRx "
            "(tilts the forearm about world x at its base, 0.5 m behind the palm: increasing it lowers the hand), ARRy (swings the forearm "
            "about the vertical: increasing it moves the hand toward -x) and ARRz (rolls the forearm about its own axis, world y).",
        scene="A ball (radius 3.5 cm) lies on the table (`ball_pos`); the green sphere shows the target (`target_pos`) in the air above "
              "the table. Grasp the ball, lift it and hold it at the target.",
        goal="Pick up the ball and move it to the target position.",
        success="the ball's centre is within 10 cm of the target (`ball_target_distance` < 0.1), which is the env's own success signal "
                "(`info['success']`).",
        fields="`ball_pos`, `target_pos`, `ball_target_distance` (m)",
        difficulty="hard",
    ),
}

def _controls(b: AdroitBackend) -> str:
    names = " ".join(b.act_names)
    skills = ("`robo skill set NAME VALUE [NAME VALUE ...] [steps=N]` moves the named targets (absolute, rad or m) there in a straight "
              "ramp over N steps (default 10); `robo skill hand open|close|pinch [AMOUNT] [steps=N]` sets a finger synergy (open: all finger "
              "and thumb joints straight; close AMOUNT 0..1: the four fingers curl and the thumb swings across, a power grasp; pinch: "
              "only the first finger and the thumb); `robo skill wait [N]` holds the targets for N steps (default 10).")
    if b.kind == "relocate":
        skills += (" `robo skill move_palm X Y Z [SPEED]` moves `palm_pos` in a straight line to (X, Y, Z) with the arm slides and the "
                   "forearm tilt (SPEED m/s, default 0.1), keeping the fingers' targets, and reports `reached` and `remaining_m`; the "
                   "palm can reach down to the table top.")
    return (
        f"**Controls.** `robo act` takes {len(b.act_names)} numbers, one per actuator in this order: {names}. Each number is the change of "
        "that actuator's position target this step, in rad (m for the ARTx/ARTy/ARTz slides); the target is clipped to the actuator's range "
        "(`robo info` lists every range). All zeros keeps the targets, so `robo act 0 0 ... 0 --repeat N` waits N steps. One step is "
        f"{b.u.dt * 1000:.0f} ms. The servos need several steps to reach a new target, and fingers stop where they touch something. "
        f"{skills} Every skill step counts against the budget. `robo move-to` and `robo grip` are not available. All angles in this task "
        "are in radians."
    )


def _observe(b: AdroitBackend, fields: str) -> str:
    return ("**Observation.** `robo observe` reports `palm_pos` (the grasp point just below the palm, where a held object sits), `fingertips` (ff, mf, rf, "
            "lf, th tip positions), `joints` (every actuated joint's position, rad or m) and `targets` (its current target), plus "
            f"{fields}. Camera images (`robo observe --image`) are taken from above the table, looking along +y.")


def _load(minari: Path, kind: str):
    import h5py

    f = minari / kind / "main_data.hdf5"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{HF_REPO}/resolve/{HF_REVISION}/{kind}/human-v2/data/main_data.hdf5"
        print("downloading", url)
        urllib.request.urlretrieve(url, f)
    return h5py.File(f, "r")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks/adroit")
    ap.add_argument("--minari", default=str(Path.home() / ".cache" / "robouse" / "minari-d4rl-human-v2"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for task_id, (kind, ep_i, max_steps) in TASKS.items():
        h = _load(Path(a.minari), kind)
        ep = h[f"episode_{ep_i}"]
        init = {k.split("/")[-1]: [float(x) for x in np.asarray(v, dtype=np.float64).ravel()]
                for k, v in ep.attrs.items() if k.startswith("options/initial_state_dict/")}
        actions = [[round(float(x), 5) for x in row] for row in np.asarray(ep["actions"])]
        t = ENV_TEXT[kind]
        b = AdroitBackend({"env": kind, "init_state": init})
        b.reset(0)
        st = b.observe()
        b.close()
        start = {"door": lambda s: f"The door's handle starts at {s['handle_pos']}.",
                 "hammer": lambda s: f"The nail head starts at {s['nail_pos']}, {s['nail_goal_distance']} m out of the board; the hammer lies at {s['hammer_pos']}.",
                 "pen": lambda s: f"At the start the pen points along {s['pen_dir']} and the target along {s['target_dir']} (similarity {s['orientation_similarity']}).",
                 "relocate": lambda s: f"The ball starts at {s['ball_pos']} and the target is at {s['target_pos']}."}[kind](st)
        source = f"{HF_REPO}@{HF_REVISION[:12]} {kind}/human-v2 episode_{ep_i}"
        meta = {
            "task": {"name": f"robouse/{task_id}", "description": t["goal"]},
            "metadata": {"source_benchmark": "Gymnasium-Robotics Adroit hand (Farama; DAPG, Rajeswaran et al. 2018)",
                         "source_task": t["upstream"], "suite": "adroit", "category": "dexterous-manipulation",
                         "difficulty": t["difficulty"], "tags": ["adroit", "mujoco", "dexterous-hand", kind]},
            "agent": {"timeout_sec": 1800},
            "verifier": {"timeout_sec": 120},
            "robouse": {"id": task_id, "backend": "adroit", "env": t["upstream"], "seed": 0, "max_steps": max_steps,
                        "camera": "fixed", "frame_every": 5, "skills": True, "success_mode": "final",
                        "init_source": f"Minari {source} (options/initial_state_dict)", "init_state": init},
        }
        body = (
            f"# {t['title']} (start state {ep_i})\n\n{HAND} {t['arm']}\n\n{t['scene']} {start}\n\n**Goal:** {t['goal']}\n\n"
            f"Success: {t['success']} It is judged after you call `robo done` and the hand has held its targets for 10 more steps, so the "
            f"goal must still hold then. The step budget is {max_steps} steps ({max_steps * b.u.dt:.0f} s of simulated time).\n\n"
            f"This task is adapted from Gymnasium-Robotics `{t['upstream']}` and starts from the initial state of human demonstration "
            f"{ep_i} of the Minari dataset `D4RL/{kind}/human-v2`.\n\n"
            f"{_observe(b, t['fields'])}\n\n{_controls(b)}\n\n" + EMBODIED_USAGE
        )
        oracle = ("#!/bin/bash\n# Reference solution: replays the recorded DAPG human demonstration (oracle/demo.json, the upstream "
                  "normalised absolute targets)\n# through the robo socket as target changes (src/robouse/backends/adroit.py, oracle_main).\n"
                  f"set -euo pipefail\npython -m robouse.oracle --backend adroit --env \"$(cd \"$(dirname \"$0\")\" && pwd)/demo.json\"\n")
        d = out / task_id
        write_task(d, meta, body, oracle, VERIFY)
        (d / "oracle" / "demo.json").write_text(json.dumps({"source": f"Minari {source}", "licence": "CC-BY-4.0 (D4RL datasets)",
                                                             "steps": len(actions), "actions": actions}, separators=(",", ":")))
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
