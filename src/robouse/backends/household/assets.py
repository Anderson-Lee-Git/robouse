"""The household robot's model files: MuJoCo Menagerie's Franka FR3 and Robotiq 2F-85 at a pinned commit.

The manifest `assets/household/provenance.json` (in git) lists every file with its URL, size and SHA-256; the files
themselves are not in git. `python -m robouse.backends.household.assets fetch` downloads them (on a machine with
network access) into `$ROBOUSE_HOUSEHOLD_ASSETS`, else `<robouse cache>/household`, checking each hash before it is
moved into place. `model_root()` checks every file against the manifest each time a backend is built: a missing or
changed file is an error, never a silent substitute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ... import config
from ...lib.download import fetch as fetch_file
from ...lib.download import sha256_file

MANIFEST = Path(__file__).resolve().parents[4] / "assets" / "household" / "provenance.json"


def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def asset_root() -> Path:
    override = config.env("ROBOUSE_HOUSEHOLD_ASSETS").strip()
    if override:
        return Path(override)
    return config.cache_dir() / "household" / "menagerie"


def _check(root: Path) -> list[str]:
    bad = []
    for f in manifest()["files"]:
        p = root / f["path"]
        if not p.is_file():
            bad.append(f"missing {f['path']}")
        elif sha256_file(p) != f["sha256"]:
            bad.append(f"sha256 mismatch {f['path']}")
    return bad


_VERIFIED: set[Path] = set()


def model_root() -> Path:
    """The verified folder holding `franka_fr3/` and `robotiq_2f85/` (checked once per process)."""
    root = asset_root()
    if root in _VERIFIED:
        return root
    bad = _check(root)
    if bad:
        raise FileNotFoundError(
            f"household robot model files not ready ({len(bad)} problems, first: {bad[0]}); run "
            "`python -m robouse.backends.household.assets fetch` on a machine with network access"
        )
    _VERIFIED.add(root)
    return root


def fetch(root: Path | None = None) -> int:
    """Download every manifest file that is missing or differs. Returns the number downloaded."""
    root = Path(root) if root else asset_root()
    n = 0
    for f in manifest()["files"]:
        n += int(fetch_file(f["url"], root / f["path"], f["sha256"]))
    return n


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd == "fetch":
        n = fetch()
        print(f"fetched {n} files into {asset_root()}")
    bad = _check(asset_root())
    for b in bad:
        print(b)
    print("ok" if not bad else f"{len(bad)} problems", "-", asset_root())
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
