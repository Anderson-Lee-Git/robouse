"""Release gate: reference solution (must score 1) and no-op (must score 0) on a seeded sample of every CPU suite.

    python tools/gate.py --out /tmp/gate [--repo .] [--python PY] [--per-suite 3] [--suites a,b] [--concurrency 4]

Runs `robouse run-many` (local engine) from the checkout at --repo with the interpreter --python (default: this one),
so two checkouts can be compared with the same environment. Writes <out>/summary.json (task -> reward, outcome, steps
for each harness) and prints one line per suite. Exit status 1 when any sampled task breaks the oracle=1 / noop=0 rule.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Suites whose simulator runs on this machine's CPU (in the main environment or a simulator virtualenv). Left out:
# behavior, robodojo and gpu-* (remote GPU workers).
CPU_SUITES = [
    "adroit",
    "arc-style",
    "crazyflie",
    "cubepick",
    "dexhand",
    "dexjoco",
    "dmcontrol",
    "driving",
    "drone",
    "gymrobotics",
    "hard",
    "humanoid",
    "humanoidbench",
    "kitchen",
    "libero",
    "libero-90",
    "libero-style",
    "maniskill",
    "menagerie",
    "metaworld",
    "mobile-manip",
    "myosuite",
    "nav",
    "quadruped",
    "real",
    "composed",
    "robo-use-families",
    "robocasa",
    "roboharm",
    "robosuite",
    "safety",
    "stationerybench",
    "vision",
]


def trials(job: Path) -> dict[str, dict]:
    out = {}
    for rj in sorted(job.glob("*/result.json")):
        r = json.loads(rj.read_text())
        e = r.get("episode") or {}
        task = r.get("task_name") or rj.parent.name.split("__")[0]
        out[task] = {
            "reward": (r.get("verifier_result") or {}).get("rewards", {}).get("reward", r.get("reward")),
            "outcome": e.get("outcome"),
            "steps": e.get("steps_used"),
            "exception": bool(r.get("exception_info")),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--repo", type=Path, help="the checkout under test (default: this one)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--per-suite", type=int, default=3)
    ap.add_argument("--suites", help="comma-separated subset of the CPU suites")
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args(argv)
    repo = (a.repo or Path(__file__).resolve().parents[1]).resolve()
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    suites = a.suites.split(",") if a.suites else CPU_SUITES
    summary: dict[str, dict] = {}
    bad = []
    for suite in suites:
        if not (repo / "tasks" / suite).is_dir():
            continue
        for harness in ("oracle", "noop"):
            job = a.out / suite / harness
            cmd = [
                a.python,
                "-m",
                "robouse.cli",
                "run-many",
                "--tasks",
                str(repo / "tasks" / suite),
                "--harness",
                harness,
                "--out",
                str(job),
                "--sample",
                str(a.per_suite),
                "--sample-seed",
                "0",
                "--concurrency",
                str(a.concurrency),
                "--resume",
            ]
            subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            for task, r in trials(job).items():
                summary.setdefault(suite, {}).setdefault(task, {})[harness] = r
        rows = summary.get(suite, {})
        ok = [
            t
            for t, r in rows.items()
            if (r.get("oracle") or {}).get("reward") == 1 and (r.get("noop") or {}).get("reward") == 0
        ]
        bad += [f"{suite}/{t}" for t in rows if t not in ok]
        print(f"{suite:18} oracle=1 & noop=0 on {len(ok)}/{len(rows)}", flush=True)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    if bad:
        print("failed:", " ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
