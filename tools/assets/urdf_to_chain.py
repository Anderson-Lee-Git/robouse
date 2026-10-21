"""Write a real arm's kinematic chain (src/robouse/real/data/<robot>_chain.json) from its vendor URDF.

  python tools/assets/urdf_to_chain.py URDF --robot so101 --source "TheRobotStudio/SO-ARM100@<commit> Simulation/SO101/so101_new_calib.urdf"

Only chains from URDFs that Robo Use may redistribute belong there. The MakerMods Metal chain is not shipped: Robo Use
builds it on first use from the vendor's URDF (makermods-robotics/metal-python-ros @ ef4181f) with the same converter;
see VENDOR_CHAINS in src/robouse/real/kinematics.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from robouse.real.kinematics import urdf_to_chain  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urdf")
    ap.add_argument("--robot", required=True)
    ap.add_argument("--source", default="")
    a = ap.parse_args()
    chain = urdf_to_chain(a.urdf, a.robot, a.source)
    chain["sources"]["sha256"] = hashlib.sha256(Path(a.urdf).read_bytes()).hexdigest()
    out = Path(__file__).resolve().parents[2] / "src/robouse/real/data" / f"{a.robot}_chain.json"
    out.write_text(json.dumps(chain, indent=1) + "\n")
    print(out, len(chain["joints"]), "joints")
    return 0


if __name__ == "__main__":
    sys.exit(main())
