#!/usr/bin/env python3
"""Write the suites table in docs/suites.md from the task data of an installed robouse, and the reference-solution and
no-op columns from the job folders of a sweep.

    /path/to/venv/bin/python tools/docs/suites_reference.py --oracle runs/sweep-oracle --noop runs/sweep-noop

The bundled table is the text between the `<!-- suites-table -->` and `<!-- /suites-table -->` lines, the hub-only
suites (tools/docs/counts.py HUB_ONLY, counted from this checkout's task folders) are between `<!-- hub-only-table -->`
lines, and README.md gets the same "N tasks in M suites"; the rest of the page is hand-written. Bundled counts come from
the package (`robouse tasks --path`), so they cannot drift from the release; tests/test_counts.py checks all of it. A
suite without trials in a job folder shows "-". Run it against the release users install, from its checkout.
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
HUB_BEGIN, HUB_END = "<!-- hub-only-table -->", "<!-- /hub-only-table -->"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import counts  # noqa: E402  (tools/docs/counts.py: the counts README.md and docs say)

# The hub-only suites (not in the wheel), in a few words.
HUB_FROM = {
    "rle-bench": "RLE-Bench family 03, tabletop reasoning: tower, cantilever, balance, hidden centre of mass",
    "capx": "CaP-X's robosuite tasks, code as policy with CaP-X's privileged API (simulator object poses, no perception)",
    "capx-libero": "CaP-X on LIBERO-PRO's object-swap tasks, code as policy with CaP-X's privileged LIBERO API",
}

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
ASSETS_ALL = "`robouse fetch-assets --all`"
VENV = "own virtualenv (below)"
HUB = "[the hub](run-a-suite.md#a-dataset) only"
NEEDS = {
    "tabletop": "", "metaworld": "`[metaworld]`", "gymrobotics": "`[gymrobotics]`", "kitchen": "`[gymrobotics]`",
    "adroit": "`[gymrobotics]`", "robosuite": "`[robosuite]`", "libero": "[LIBERO setup](#libero)",
    "menagerie": ASSETS, "roboharm": ASSETS, "drone": ASSETS, "quadruped": ASSETS_ALL, "humanoid": ASSETS_ALL,
    "mobile_manip": ASSETS_ALL, "dexhand": ASSETS_ALL, "crazyflie": ASSETS_ALL, "components": ASSETS_ALL,
    "dexjoco": VENV, "driving": VENV, "dmcontrol": VENV, "myosuite": VENV, "humanoidbench": HUB, "maniskill": HUB,
    "robocasa": HUB, "nav": "", "cubepick": "", "real": "",
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
        return "-"
    return f"{sum(1 for t in ran if any(x == 1.0 for x in res[t]))}/{len(ran)}"


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
             "`pip install 'robouse[sim]'`. The last two columns count the tasks that scored 1 with the reference "
             "solution and with the no-op control.", "",
             "| Suite | What | Tasks | Needs | Reference solution | No-op control |", "|---|---|---|---|---|---|", *rows]
    hub_rows = []
    for suite in counts.HUB_ONLY:  # not in the wheel: their task folders in this checkout
        tasks = [frontmatter(t) for t in sorted((counts.REPO / "tasks" / suite).rglob("task.md"))]
        ids = [t["robouse"]["id"] for t in tasks]
        hub_rows.append(
            f"| `{suite}` | {HUB_FROM.get(suite, '')} | {len(ids)} | {cell(ids, oracle, 1.0)} | {cell(ids, noop, 0.0)} |"
        )
    hub = ["| Suite | What | Tasks | Reference solution | No-op control |", "|---|---|---|---|---|", *hub_rows]
    text = DOC.read_text(encoding="utf-8")
    for begin, end, lines in ((BEGIN, END, table), (HUB_BEGIN, HUB_END, hub)):
        if begin not in text or end not in text:
            sys.exit(f"{DOC} has no {begin} ... {end} block")
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
        text = head + begin + "\n" + "\n".join(lines) + "\n" + end + tail
    DOC.write_text(text, encoding="utf-8")
    changed = counts.rewrite()  # README.md says the same numbers
    print(f"wrote the suites tables in {DOC}: {len(rows)} suites, {total} tasks, from {version}; "
          f"{len(hub_rows)} hub-only suites; rewrote {', '.join(changed) or 'no other file'}")


if __name__ == "__main__":
    main()
