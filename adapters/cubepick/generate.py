"""CubePick (inspect-robots' built-in `cubepick-reach` task, MIT) -> Robo Use tasks: layouts 0-4 = seeds 0-4, as in
upstream's quickstart (`Scene(id=f"layout-{i}", instruction="reach the cube", init_seed=i) for i in range(5)`).

Usage: python adapters/cubepick/generate.py [--out tasks/cubepick]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.embodied import VERIFY_SH
from robouse.prompts import EMBODIED_USAGE
from robouse.tasks import write_task

BODY = """# CubePick: reach the cube (layout {i})

A point end effector moves in the unit square (x from 0 to 1, y from 0 to 1). It starts at (0.1, 0.1); a cube lies somewhere in the far quadrant (both coordinates between 0.6 and 0.9). This is inspect-robots' built-in `cubepick-reach` benchmark, layout {i}.

## Task

Reach the cube.

**Success:** the episode is scored as solved the first time the end effector is within 0.05 of the cube (upstream's `success_at_end` with termination on success). Calling `robo done` earlier ends the episode unsolved.

**Controls.** `robo act DX DY` moves the end effector by (DX, DY), each clipped to +-0.1; positions stay inside the unit square. `--repeat N` applies the same move N times.

**Observation.** `robo observe` reports `eef_pos`, `cube_pos` and their `distance`. `robo observe --image` saves the top camera: the cube is the green square, the end effector the red one; +x points right and +y points down in the image.

The step budget is 80 steps.

""" + EMBODIED_USAGE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tasks" / "cubepick"))
    out = Path(ap.parse_args().out)
    if out.exists():
        shutil.rmtree(out)
    for i in range(5):
        tid = f"cubepick-reach-layout-{i}"
        meta = {"task": {"name": f"robouse/{tid}", "description": f"CubePick reach, layout {i}"},
                "metadata": {"source_benchmark": "inspect-robots cubepick-reach (robocurve/inspect-robots, MIT)",
                             "source_task": f"cubepick-reach/layout-{i}", "suite": "cubepick", "category": "reach",
                             "difficulty": "easy", "tags": ["mock-world", "inspect-robots"]},
                "agent": {"timeout_sec": 600}, "verifier": {"timeout_sec": 60},
                "robouse": {"id": tid, "backend": "cubepick", "env": tid, "seed": i, "max_steps": 80, "camera": "top",
                            "cameras": ["top"], "skills": False, "success_mode": "first", "frame_every": 1, "control_dt": 0.1}}
        oracle = "#!/bin/bash\n# Reference solution: upstream's scripted policy (step toward the cube).\nset -euo pipefail\npython -m robouse.oracle --backend cubepick\n"
        write_task(out / tid, meta, BODY.format(i=i), oracle, VERIFY_SH)
    print(f"5 tasks -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
