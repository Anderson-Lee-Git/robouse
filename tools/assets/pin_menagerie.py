#!/usr/bin/env python3
"""Write assets/menagerie/embodiments.json: the MuJoCo Menagerie robots used by the embodiment suites (quadruped,
humanoid, mobile-manip, dexhand, crazyflie), pinned to one commit with a SHA-256 per file.

These meshes are not stored in git (about 330 MB); `robouse fetch-assets` downloads them into
~/.cache/robouse/menagerie and checks each hash.

  git init /tmp/menag && cd /tmp/menag && git remote add origin https://github.com/google-deepmind/mujoco_menagerie.git
  git sparse-checkout set --no-cone <robot dirs> && git fetch --depth 1 origin <COMMIT> && git checkout FETCH_HEAD
  python tools/assets/pin_menagerie.py /tmp/menag

Per robot: LICENSE, README.md, every MJCF file (*.xml) and everything under assets/ (meshes and textures).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

COMMIT = "8161bba264d7fa7c99ca301e91e7fb44737676ad"
REPO = "https://github.com/google-deepmind/mujoco_menagerie"
# robot folder -> (suite, licence as stated in the folder's README/LICENSE)
ROBOTS = {
    "unitree_go2": ("quadruped", "BSD-3-Clause"),
    "unitree_go1": ("quadruped", "BSD-3-Clause"),
    "boston_dynamics_spot": ("quadruped", "BSD-3-Clause"),
    "anybotics_anymal_c": ("quadruped", "BSD-3-Clause"),
    "unitree_g1": ("humanoid", "BSD-3-Clause"),
    "unitree_h1": ("humanoid", "BSD-3-Clause"),
    "apptronik_apollo": ("humanoid", "Apache-2.0"),
    "booster_t1": ("humanoid", "Apache-2.0"),
    "hello_robot_stretch_3": ("mobile-manip", "Apache-2.0"),
    "pal_tiago": ("mobile-manip", "Apache-2.0"),
    "google_robot": ("mobile-manip", "Apache-2.0"),
    "shadow_hand": ("dexhand", "Apache-2.0"),
    "leap_hand": ("dexhand", "MIT"),
    "bitcraze_crazyflie_2": ("crazyflie", "MIT"),
}


def main() -> None:
    src = Path(sys.argv[1])
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != COMMIT:
        raise SystemExit(f"{src} is at {head}, expected {COMMIT}")
    files = []
    for robot in ROBOTS:
        d = src / robot
        picks = [d / "LICENSE", d / "README.md", *sorted(d.glob("*.xml")), *sorted(p for p in (d / "assets").rglob("*") if p.is_file())]
        for p in picks:
            rel = p.relative_to(src).as_posix()
            data = p.read_bytes()
            files.append({"path": rel, "url": f"https://raw.githubusercontent.com/google-deepmind/mujoco_menagerie/{COMMIT}/{rel}",
                          "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    out = Path(__file__).resolve().parents[2] / "assets" / "menagerie" / "embodiments.json"
    out.write_text(json.dumps({"repository": REPO, "commit": COMMIT,
                               "note": "MuJoCo Menagerie robots for the embodiment suites. Not stored in git; `robouse fetch-assets` "
                                       "downloads them into ~/.cache/robouse/menagerie.",
                               "robots": {r: {"suite": s, "license": lic, "license_file": f"{r}/LICENSE"} for r, (s, lic) in ROBOTS.items()},
                               "files": files}, indent=2) + "\n")
    print(f"{len(files)} files, {sum(f['bytes'] for f in files) / 1e6:.1f} MB -> {out}")


if __name__ == "__main__":
    main()
