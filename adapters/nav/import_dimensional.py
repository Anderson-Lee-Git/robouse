"""Convert Dimensional's "Can Jev Nav?" tasks into Robo Use nav tasks, locally.

The study's 327 tasks (133 HSSD homes) are published as JSON on research.dimensional.org/system-one-navigation
(paths.json: bounds, 2-D wall and obstacle boxes, spawn, goal, reference shortest path; data/tasks/<id>.json: target box,
geodesic, difficulty). The dimos code is Apache-2.0, but the task geometry is derived from HSSD scenes (CC-BY-NC-4.0) and
the site data carries no licence of its own, so converted tasks are written to a local folder (default tasks-local/,
gitignored) and are not redistributed until Dimensional confirms the terms.

Geometry-only: the simulator uses the published 2-D boxes (walls and furniture footprints) instead of the navigation
mesh, so geodesics can differ from the study's; the study's geodesic is kept in metadata, ours is used for SPL.

Usage: python adapters/nav/import_dimensional.py [--out tasks-local/dimensional-nav] [--limit N] [--sample N --seed S]
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import urllib.request
from pathlib import Path

from generate import write

BASE = "https://research.dimensional.org/system-one-navigation"


def fetch(url: str, cache: Path) -> dict:
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        with urllib.request.urlopen(url, timeout=60) as r:
            cache.write_bytes(r.read())
    return json.loads(cache.read_text())


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tasks-local" / "dimensional-nav"))
    ap.add_argument("--cache", default=str(Path.home() / ".cache" / "robouse" / "dimensional-nav"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    cache = Path(a.cache)
    paths = fetch(f"{BASE}/paths.json", cache / "paths.json")
    ids = sorted(paths)
    if a.sample:
        ids = sorted(random.Random(a.seed).sample(ids, a.sample))
    if a.limit:
        ids = ids[: a.limit]
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    from robouse.backends.nav import NavBackend

    n = 0
    for tid in ids:
        p = paths[tid]
        meta = fetch(f"{BASE}/data/tasks/{tid}.json", cache / "tasks" / f"{tid}.json")
        tb = _j(meta["target"])  # cx, cy, cz, sx, sy, sz
        target = {"id": f"target_{tid}", "label": meta["label"], "box": [tb[0], tb[1], tb[3], tb[4]]}
        walls = [list(map(float, w[:4])) for w in _j(p["walls"])]
        x0, y0, x1, y1 = _j(p["bounds"])
        home = {"bounds": [x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5], "walls": walls,
                "objects": [dict(target, passable=True)], "source": f"dimensional {meta['scene']}"}
        spawn = _j(p["spawn"])[:2]
        spec = {"id": "probe", "max_steps": 3000, "nav": {"scene": home, "target": target, "spawn": spawn}}
        try:
            g = NavBackend(spec).geodesic(tuple(spawn))
        except Exception:  # noqa: BLE001
            g = float("inf")
        if not g < 1e9:
            print(f"skip {tid}: spawn cannot reach the target in the box geometry")
            continue
        t = {"id": f"dimnav-{tid.replace('_', '-').replace(' ', '-')}", "source_task": tid, "target": target, "spawn": spawn,
             "spawn_yaw_deg": 0, "geodesic_m": round(g, 2), "detour": _j(meta.get("cov") or "{}").get("detour") if isinstance(_j(meta.get("cov") or "{}"), dict) else None,
             "difficulty": meta.get("difficulty", "medium"), "reference": _j(p["reference"])}
        write(out, [t], home, "dimensional-nav", f"Dimensional Can Jev Nav? task {tid} (HSSD scene {meta['scene']}; study geodesic {meta.get('geodesic')} m)",
              "HSSD-derived geometry (CC-BY-NC-4.0); converted locally, not redistributed", budget=3000)
        n += 1
    print(f"{n} tasks -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
