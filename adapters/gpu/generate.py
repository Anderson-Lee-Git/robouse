"""GPU track -> Robo Use tasks (ManiSkill3, Genesis, MuJoCo Playground, Isaac Lab).

Every task runs its simulator in a remote GPU worker (src/robouse/backends/gpu_worker/, see docs/suites/gpu-track.md);
the task folder only names the simulator family (`sim`) and the task key (`env`) in that family's module. The
reference solution is the task's scripted or planner-based policy, which runs next to the simulator on the privileged
state and sends its actions through the robo socket (robouse.backends.gpu.oracle_main).

Usage: python adapters/gpu/generate.py --out tasks
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from tasks_genesis import GENESIS, GS_USAGE
from tasks_isaaclab import IL_USAGE, ISAACLAB
from tasks_maniskill import MANISKILL, MS_USAGE
from tasks_playground import PG_USAGE, PLAYGROUND

from robouse.tasks import write_task

SUITES = {
    "maniskill": (MANISKILL, MS_USAGE),
    "genesis": (GENESIS, GS_USAGE),
    "playground": (PLAYGROUND, PG_USAGE),
    "isaaclab": (ISAACLAB, IL_USAGE),
}

ORACLE = """#!/bin/bash
# Reference solution: the task's {kind} policy runs next to the simulator on the privileged state (oracle token) and
# hands its next action to this loop, which sends it through the robo socket like an agent's `robo act` / `robo skill`.
set -euo pipefail
python -m robouse.oracle --backend gpu --env {env}
"""

VERIFIER = """#!/bin/bash
# Verifier: the episode server already judged success (the simulator's own physical success check, evaluated by the
# GPU worker after `robo done` and a settle period); copy its verdict.
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


def build(t: dict, sim: str, usage: str) -> tuple[dict, str]:
    spec = {
        "id": t["id"],
        "backend": "gpu",
        "sim": sim,
        "env": t["env"],
        "seed": t.get("seed", 0),
        "max_steps": t["max_steps"],
        "skills": True,
        "success_mode": "final",
        "obs_mode": t.get("obs_mode", "state"),
        "frame_every": 1,
        "linger_s": 5,
        "ready_timeout_s": t.get("ready_timeout_s", 900),
        "rpc_timeout_s": 900,
    }
    if t.get("obs_mode") == "vision":
        spec["visible_fields"] = t["visible_fields"]
        spec["cameras"] = t["cameras"]
    if t.get("opts"):
        spec["opts"] = t["opts"]
    meta = {
        "task": {"name": f"robouse/{t['id']}", "description": t["summary"]},
        "metadata": {
            "source_benchmark": t["source"],
            "source_task": t.get("source_task", ""),
            "suite": f"gpu-{sim}",
            "category": t["category"],
            "difficulty": "hard",
            "hard_because": t["hard"],
            "language_instruction": t["summary"],
            "tags": ["gpu-required", sim] + t.get("tags", []),
            "reference_solution": t["oracle"],
            "gpu": "required (NVIDIA RTX, remote worker)",
        },
        "agent": {"timeout_sec": t.get("timeout_sec", 2400)},
        "verifier": {"timeout_sec": 120},
        "robouse": spec,
    }
    body = f"# {t['title']}\n\n{t['instruction'].strip()}\n\nThe step budget is {t['max_steps']} steps: every `robo act` step and every `robo skill` call counts as one.\n\n{usage.strip()}\n"
    return meta, body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tasks")
    ap.add_argument("--only", default="", help="comma-separated simulator families")
    a = ap.parse_args()
    for sim, (tasks, usage) in SUITES.items():
        if a.only and sim not in a.only.split(","):
            continue
        root = Path(a.out) / f"gpu-{sim}"
        if root.exists():
            shutil.rmtree(root)
        for t in tasks:
            meta, body = build(t, sim, usage)
            write_task(
                root / t["id"], meta, body, ORACLE.format(kind=t.get("oracle_kind", "scripted"), env=t["env"]), VERIFIER
            )
        print(f"gpu-{sim}: {len(tasks)} tasks -> {root}")


if __name__ == "__main__":
    main()
