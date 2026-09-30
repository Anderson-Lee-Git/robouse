#!/usr/bin/env python3
"""Write the suites table in docs/suites.md from the task data of an installed robouse, and the reference-solution and
no-op columns from the job folders of a sweep.

    /path/to/venv/bin/python tools/docs/suites_reference.py --oracle runs/sweep-oracle --noop runs/sweep-noop

The table is the text between the `<!-- suites-table -->` and `<!-- /suites-table -->` lines; the rest of the page is
hand-written. Counts come from the package (`robouse tasks --path`), so they cannot drift from the release. A suite
without trials in a job folder shows "not run". Run it against the release users install, not a checkout.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

DOC = Path(__file__).resolve().parents[2] / "docs" / "suites.md"
BEGIN, END = "<!-- suites-table -->", "<!-- /suites-table -->"

# What each suite is, in a few words (the task metadata's source strings are too long for a table).
FROM = {
    "metaworld": "Meta-World MT50", "gymrobotics": "Gymnasium-Robotics: Fetch, PointMaze", "kitchen": "Franka Kitchen",
    "adroit": "Adroit hand", "libero": "LIBERO: Spatial, Object, Goal, Long", "libero-90": "LIBERO-90",
    "robosuite": "robosuite 1.5, five arms", "libero-style": "LIBERO-like tabletop scenes", "arc-style": "ARC-style rules on a table",
    "robo-use-families": "Robo Use task families", "safety": "harmful requests and benign twins",
    "vision": "camera images, no coordinates", "hard": "low-level control, uncalibrated cameras",
    "menagerie": "dual Franka Panda, ALOHA 2", "roboharm": "10 harm scenarios, 4 configurations", "drone": "Skydio X2 over a town",
    "quadruped": "Unitree Go2 and Go1, Spot, ANYmal C", "humanoid": "Unitree G1 and H1, Apollo, Booster T1",
    "mobile-manip": "Stretch 3, TIAGo, Google Robot", "dexhand": "Shadow Hand, LEAP Hand", "crazyflie": "Crazyflie 2, one or three",
    "composed": "composed from components", "dexjoco": "DexJoCo: Allegro hand tool use", "driving": "MetaDrive car in traffic",
    "dmcontrol": "dm_control: Control Suite, Jaco arm", "myosuite": "MyoSuite: muscle-driven arm and hand",
    "humanoidbench": "HumanoidBench: H1 with two hands", "maniskill": "ManiSkill3 on the CPU", "robocasa": "RoboCasa kitchens",
    "nav": "object-goal navigation in homes", "cubepick": "cube pick-and-reach", "real": "real arms, on the mock by default",
}
# What a suite needs beyond `pip install 'robouse[sim]'`, by backend.
ASSETS = "`robouse fetch-assets`"
VENV = "own virtualenv (below)"
NEEDS = {
    "tabletop": "", "metaworld": "`[metaworld]`", "gymrobotics": "`[gymrobotics]`", "kitchen": "`[gymrobotics]`",
    "adroit": "`[gymrobotics]`", "robosuite": "`[robosuite]`", "libero": "[LIBERO setup](#libero)",
    "menagerie": ASSETS, "roboharm": ASSETS, "drone": ASSETS, "quadruped": ASSETS, "humanoid": ASSETS,
    "mobile_manip": ASSETS, "dexhand": ASSETS, "crazyflie": ASSETS, "components": ASSETS,
    "dexjoco": VENV, "driving": VENV, "dmcontrol": VENV, "myosuite": VENV, "humanoidbench": VENV, "maniskill": VENV,
    "robocasa": VENV, "nav": "", "cubepick": "", "real": "",
}


def frontmatter(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8").split("\n---", 1)[0].removeprefix("---"))


def results(job: Path | None) -> dict[str, list[float]]:
    """task id -> rewards of the finished trials in a job folder (infrastructure failures left out)."""
    out: dict[str, list[float]] = defaultdict(list)
    if not job:
        return out
    for r in job.glob("*/result.json"):
        d = json.loads(r.read_text())
        if d.get("exception_info"):
            continue
        reward = ((d.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if reward is not None:
            out[d.get("task_name") or r.parent.name.split("__")[0]].append(float(reward))
    return out


def cell(ids: list[str], res: dict[str, list[float]], want: float) -> str:
    ran = [t for t in ids if res.get(t)]
    if not ran:
        return "not run"
    ok = sum(1 for t in ran if all(x == want for x in res[t]))
    solved = sum(1 for t in ran if any(x == 1.0 for x in res[t]))
    return f"{solved}/{len(ran)}" if ok == len(ran) else f"{solved}/{len(ran)} (check)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--robouse", default=shutil.which("robouse", path=str(Path(sys.executable).parent)) or "robouse")
    ap.add_argument("--oracle", type=Path, action="append", default=[], help="job folder(s) of a reference-solution sweep")
    ap.add_argument("--noop", type=Path, action="append", default=[], help="job folder(s) of a no-op sweep")
    a = ap.parse_args()
    root = Path(subprocess.run([a.robouse, "tasks", "--path"], capture_output=True, text=True, check=True).stdout.strip())
    version = subprocess.run([a.robouse, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    oracle, noop = defaultdict(list), defaultdict(list)
    for j in a.oracle:
        for k, v in results(j).items():
            oracle[k] += v
    for j in a.noop:
        for k, v in results(j).items():
            noop[k] += v
    rows, total = [], 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        tasks = [frontmatter(t) for t in sorted(d.rglob("task.md"))]
        if not tasks:
            continue
        ids = [t["robouse"]["id"] for t in tasks]
        backends = Counter(t["robouse"]["backend"] for t in tasks)
        needs = sorted({NEEDS.get(b, "?") for b in backends} - {""})
        rows.append(f"| `{d.name}` | {FROM.get(d.name, '')} | {len(ids)} | {', '.join(needs) or '-'} | "
                    f"{cell(ids, oracle, 1.0)} | {cell(ids, noop, 0.0)} |")
        total += len(ids)
    table = [f"{version} bundles {total} tasks in {len(rows)} suites. \"Needs\" is what a suite needs beyond "
             "`pip install 'robouse[sim]'`. The last two columns count the tasks whose reference solution scored 1, "
             "and whose no-op control scored 1 (it must be 0).", "",
             "| Suite | What | Tasks | Needs | Reference solution | No-op control |", "|---|---|---|---|---|---|", *rows]
    text = DOC.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        sys.exit(f"{DOC} has no {BEGIN} ... {END} block")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    DOC.write_text(head + BEGIN + "\n" + "\n".join(table) + "\n" + END + tail, encoding="utf-8")
    print(f"wrote the suites table in {DOC}: {len(rows)} suites, {total} tasks, from {version}")


if __name__ == "__main__":
    main()
