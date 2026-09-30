"""Navigation suite -> Robo Use tasks (suite "nav"): object-goal navigation in procedurally generated homes, in the
protocol of Dimensional's "Can Jev Nav?" study (robot-frame WorldState in spatial language, discrete drive commands,
SPL / SoftSPL / arrival / collisions / time to target / path ratio / excess turning). Backend: src/robouse/backends/nav.py.

Homes are generated here from a seed (rooms on a grid, interior walls with doorways, labelled furniture); every task is
checked reachable and its geodesic shortest path is stored. Difficulty follows the detour ratio (geodesic / straight line).
Dimensional's own 327 tasks (HSSD scenes) can be converted locally with adapters/nav/import_dimensional.py.

Usage: python adapters/nav/generate.py [--out tasks/nav] [--homes 10] [--per-home 4]
"""

from __future__ import annotations

import argparse
import math
import random
import shutil
from pathlib import Path

from robouse.backends.embodied import VERIFY_SH
from robouse.backends.nav.backend import NavBackend
from robouse.core.prompts import EMBODIED_USAGE
from robouse.tasks import write_task

WALL = 0.15
FURNITURE = {  # label: (size x, size y) in metres, the room kinds it appears in
    "bed": ((2.0, 1.6), "bedroom"),
    "wardrobe": ((1.2, 0.6), "bedroom"),
    "nightstand": ((0.5, 0.45), "bedroom"),
    "sofa": ((2.1, 0.9), "living"),
    "tv stand": ((1.6, 0.45), "living"),
    "coffee table": ((1.1, 0.6), "living"),
    "armchair": ((0.85, 0.85), "living"),
    "bookshelf": ((1.0, 0.35), "living"),
    "plant": ((0.45, 0.45), "any"),
    "fridge": ((0.8, 0.7), "kitchen"),
    "oven": ((0.7, 0.65), "kitchen"),
    "dining table": ((1.6, 0.9), "kitchen"),
    "kitchen counter": ((2.0, 0.6), "kitchen"),
    "desk": ((1.3, 0.65), "office"),
    "office chair": ((0.6, 0.6), "office"),
    "filing cabinet": ((0.5, 0.6), "office"),
    "toilet": ((0.45, 0.7), "bathroom"),
    "sink": ((0.6, 0.5), "bathroom"),
    "bathtub": ((1.7, 0.8), "bathroom"),
    "washing machine": ((0.65, 0.65), "bathroom"),
    "trash can": ((0.4, 0.4), "any"),
}
KINDS = ["living", "kitchen", "bedroom", "bathroom", "office", "bedroom"]


def make_home(seed: int) -> dict:
    rng = random.Random(seed)
    cols, rows = rng.choice([(2, 2), (3, 2), (3, 2), (2, 3)])
    cw = [rng.uniform(3.4, 5.2) for _ in range(cols)]
    rh = [rng.uniform(3.2, 4.6) for _ in range(rows)]
    W, H = sum(cw), sum(rh)
    xs = [0.0] + [sum(cw[: i + 1]) for i in range(cols)]
    ys = [0.0] + [sum(rh[: j + 1]) for j in range(rows)]
    walls = [
        [W / 2, 0, W + WALL, WALL],
        [W / 2, H, W + WALL, WALL],
        [0, H / 2, WALL, H + WALL],
        [W, H / 2, WALL, H + WALL],
    ]
    doors = []

    def wall_with_door(x0, y0, x1, y1, door: bool):
        horizontal = abs(y1 - y0) < 1e-9
        length = (x1 - x0) if horizontal else (y1 - y0)
        if not door or length < 2.0:
            walls.append(
                [
                    (x0 + x1) / 2,
                    (y0 + y1) / 2,
                    (length + WALL) if horizontal else WALL,
                    WALL if horizontal else (length + WALL),
                ]
            )
            return
        dw = rng.uniform(0.9, 1.2)
        c = rng.uniform(0.6 + dw / 2, length - 0.6 - dw / 2)
        for a, b in ((0.0, c - dw / 2), (c + dw / 2, length)):
            if b - a > 0.05:
                if horizontal:
                    walls.append([x0 + (a + b) / 2, y0, b - a, WALL])
                else:
                    walls.append([x0, y0 + (a + b) / 2, WALL, b - a])
        doors.append((x0 + c, y0) if horizontal else (x0, y0 + c))

    # interior walls: a spanning tree of doorways keeps every room reachable, plus a few extra doors
    edges = []
    for i in range(cols):
        for j in range(rows):
            if i + 1 < cols:
                edges.append(((i, j), (i + 1, j)))
            if j + 1 < rows:
                edges.append(((i, j), (i, j + 1)))
    rng.shuffle(edges)
    parent = {(i, j): (i, j) for i in range(cols) for j in range(rows)}

    def find(a):
        while parent[a] != a:
            a = parent[a]
        return a

    for a, b in edges:
        door = find(a) != find(b) or rng.random() < 0.3
        if find(a) != find(b):
            parent[find(a)] = find(b)
        (i, j), (i2, _j2) = a, b
        if i2 == i + 1:
            wall_with_door(xs[i + 1], ys[j], xs[i + 1], ys[j + 1], door)
        else:
            wall_with_door(xs[i], ys[j + 1], xs[i + 1], ys[j + 1], door)
    # furniture against room walls, away from doorways
    kinds = KINDS[:]
    rng.shuffle(kinds)
    objects, rooms = [], []
    for i in range(cols):
        for j in range(rows):
            kind = kinds[(i * rows + j) % len(kinds)]
            rooms.append(
                {
                    "kind": kind,
                    "box": [(xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2, xs[i + 1] - xs[i], ys[j + 1] - ys[j]],
                }
            )
            labels = [l for l, (_, k) in FURNITURE.items() if k == kind] + [
                l for l, (_, k) in FURNITURE.items() if k == "any"
            ]
            rng.shuffle(labels)
            placed = []
            for lab in labels[: rng.randint(2, 4)]:
                sx, sy = FURNITURE[lab][0]
                if rng.random() < 0.5:
                    sx, sy = sy, sx
                for _ in range(40):
                    side = rng.choice("NSEW")
                    m = WALL / 2 + 0.02
                    if side in "NS":
                        x = rng.uniform(xs[i] + m + sx / 2, xs[i + 1] - m - sx / 2)
                        y = ys[j + 1] - m - sy / 2 if side == "N" else ys[j] + m + sy / 2
                    else:
                        y = rng.uniform(ys[j] + m + sy / 2, ys[j + 1] - m - sy / 2)
                        x = xs[i + 1] - m - sx / 2 if side == "E" else xs[i] + m + sx / 2
                    box = [round(x, 3), round(y, 3), sx, sy]
                    clear_doors = all(abs(x - dx) > sx / 2 + 1.0 or abs(y - dy) > sy / 2 + 1.0 for dx, dy in doors)
                    clear_objs = all(
                        abs(x - b[0]) > (sx + b[2]) / 2 + 0.5 or abs(y - b[1]) > (sy + b[3]) / 2 + 0.5 for b in placed
                    )
                    if clear_doors and clear_objs:
                        placed.append(box)
                        objects.append(
                            {"id": f"{lab.replace(' ', '_')}_{len(objects)}", "label": lab, "box": box, "room": kind}
                        )
                        break
    return {
        "bounds": [-0.5, -0.5, W + 0.5, H + 0.5],
        "walls": [[round(v, 3) for v in w] for w in walls],
        "objects": objects,
        "rooms": rooms,
        "seed": seed,
    }


def make_tasks(home_id: str, home: dict, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed * 7919 + 1)
    counts: dict[str, int] = {}
    for o in home["objects"]:
        counts[o["label"]] = counts.get(o["label"], 0) + 1
    targets = [o for o in home["objects"] if counts[o["label"]] == 1]
    rng.shuffle(targets)
    tasks = []
    for tgt in targets:
        if len(tasks) >= n:
            break
        spec = {"id": "probe", "max_steps": 1200, "nav": {"scene": home, "target": tgt, "spawn": [0, 0]}}
        b = NavBackend(spec)
        want = ("easy", "medium", "hard")[len(tasks) % 3]
        cands = []
        for _ in range(300):
            x0, y0, x1, y1 = home["bounds"]
            p = (rng.uniform(x0, x1), rng.uniform(y0, y1))
            if not b._free(p):
                continue
            g = b.geodesic(p)
            straight = math.hypot(p[0] - tgt["box"][0], p[1] - tgt["box"][1])
            if math.isfinite(g) and 3.0 <= g <= 18.0 and straight > 1.5:
                d = g / max(0.1, straight - 0.5)
                cands.append(((p, g, straight), "easy" if d < 1.25 else "medium" if d < 1.7 else "hard", d))
        match = [c for c in cands if c[1] == want]
        best = (match or sorted(cands, key=lambda c: -c[2]))[0][0] if cands else None
        if not best:
            continue
        p, g, straight = best
        detour = g / max(0.1, straight - 0.5)
        diff = "easy" if detour < 1.25 else "medium" if detour < 1.7 else "hard"
        yaw = rng.choice([0, 90, 180, 270])
        tasks.append(
            {
                "id": f"nav-{home_id}-{tgt['label'].replace(' ', '-')}",
                "target": tgt,
                "spawn": [round(p[0], 3), round(p[1], 3)],
                "spawn_yaw_deg": yaw,
                "geodesic_m": round(g, 2),
                "detour": round(detour, 2),
                "difficulty": diff,
            }
        )
    return tasks


def instruction(t: dict, label: str, budget: int) -> str:
    return (
        f"# Find the {label}\n\nYou control a mobile robot base (0.25 m radius) in a home: rooms joined by doorways, "
        "with furniture along the walls. You do not get a map or world coordinates: `robo observe` describes the scene "
        "from the robot's point of view.\n\n## Task\n\n"
        f"Drive to the {label} and stop next to it.\n\n**Success:** after you call `robo done`, the robot is within 1.0 m "
        f"of the {label}'s footprint and can see it (a straight line from the robot to the nearest point of the {label} "
        "crosses no wall or furniture). Judged by the episode server after the robot has held still for 10 steps. Scored as "
        "in Dimensional's study: success, SPL (success weighted by the shortest path over the path driven), SoftSPL, "
        "collisions, time to target and path smoothness are all recorded.\n\n"
        f"**Controls.** `robo act VX VY WZ` sets the body-frame velocity for the next step(s): VX forward (m/s, up to +-{0.5}), "
        "VY to the left (m/s, up to +-0.3) and WZ counter-clockwise (deg/s, up to +-46); one step is 0.1 s and `--repeat N` "
        "holds it for N steps. Moves into walls or furniture slide along them or stop. Skills: `drive X Y YAW [SECONDS]` "
        "(Dimensional's discrete command: X forward|none|backward, Y left|none|right, YAW turn_left|none|turn_right, at "
        "0.5 m/s and 0.8 rad/s, held for SECONDS, default 0.5), `turn DEG` (in place, counter-clockwise positive) and "
        "`forward METRES` (straight ahead; stops when blocked).\n\n**Observation.** `robo observe` returns a WorldState: "
        "`goal` (label, `bearing` as one of ahead, ahead_left, left, behind_left, behind, behind_right, right, "
        "ahead_right, `bearing_deg`, `distance` as touching < 0.5 m, near < 1.5 m, mid < 4 m or far, `distance_m`, "
        "`visible`, `arrived`), `objects` (furniture the robot can see within 6 m, with bearing and distance), "
        "`way_to_target` (whether the straight line toward the goal is `blocked`, `blocked_by` what, `clear_m`, and "
        "`open_sides`), `free_space` (clear distance and open / narrow / blocked along the eight bearings) and `robot` "
        "(motion, last command, what happened over the last 8 s: `moved_m`, `turned_deg`, `target_closer_m`, `pattern` "
        "stuck / progressing / not_progressing, and `collisions`). `robo observe --image` saves an egocentric top-down "
        "view of what the robot can see (ahead is up; the target is red).\n\n"
        f"The step budget is {budget} steps ({budget * 0.1:.0f} s).\n\n" + EMBODIED_USAGE
    )


def write(out: Path, tasks: list[dict], home: dict, suite: str, source: str, org_note: str, budget: int = 1200) -> None:
    for t in tasks:
        meta = {
            "task": {"name": f"robouse/{t['id']}", "description": f"Find the {t['target']['label']}"},
            "metadata": {
                "source_benchmark": source,
                "source_task": t.get("source_task", t["id"]),
                "suite": suite,
                "category": "object-goal navigation",
                "difficulty": t["difficulty"],
                "tags": ["navigation", "mobile-base", "spatial-language"],
                "geodesic_m": t["geodesic_m"],
                "detour": t["detour"],
                **({"licence_note": org_note} if org_note else {}),
            },
            "agent": {"timeout_sec": 1800},
            "verifier": {"timeout_sec": 120},
            "robouse": {
                "id": t["id"],
                "backend": "nav",
                "env": t["id"],
                "seed": 0,
                "max_steps": budget,
                "camera": "local",
                "cameras": ["local"],
                "skills": True,
                "success_mode": "final",
                "frame_every": 2,
                "nav": {
                    "scene": home,
                    "target": t["target"],
                    "spawn": t["spawn"],
                    "spawn_yaw_deg": t["spawn_yaw_deg"],
                    "geodesic_m": t["geodesic_m"],
                    "success_radius": 1.0,
                    **({"reference": t["reference"]} if t.get("reference") else {}),
                },
            },
        }
        oracle = (
            "#!/bin/bash\n# Reference solution: follow the geodesic distance field to the target with `robo act`, then `robo done`.\n"
            "set -euo pipefail\npython -m robouse.oracle --backend nav --env \"$(dirname \"$0\")/nav_spec.json\"\n"
        )
        write_task(out / t["id"], meta, instruction(t, t["target"]["label"], budget), oracle, VERIFY_SH)
        import json

        (out / t["id"] / "oracle" / "nav_spec.json").write_text(json.dumps({**meta["robouse"]}, separators=(",", ":")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tasks" / "nav"))
    ap.add_argument("--homes", type=int, default=10)
    ap.add_argument("--per-home", type=int, default=4)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    n = 0
    for h in range(a.homes):
        home = make_home(1000 + h)
        tasks = make_tasks(f"h{h:02d}", home, a.per_home, 1000 + h)
        write(
            out,
            tasks,
            home,
            "nav",
            "robouse original (nav suite; procedurally generated homes, protocol of Dimensional's Can Jev Nav?)",
            "",
        )
        n += len(tasks)
    print(f"{n} tasks -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
