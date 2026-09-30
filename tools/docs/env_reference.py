"""Write docs/configuration.md, the environment variables robouse reads, from robouse.config.ENV.

    python tools/docs/env_reference.py [--check]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from robouse.config import ENV  # noqa: E402

HEAD = """# Configuration

Robo Use reads its settings from environment variables; every one is listed here, generated from `robouse.config`. Paths default to `~/.cache/robouse` (the cache) and `~/.config/robouse` (private settings such as remote worker endpoints, which the local runner's sandbox keeps from agents).

| Variable | Meaning |
|---|---|
"""


def render() -> str:
    return HEAD + "".join(f"| `{k}` | {v} |\n" for k, v in ENV.items())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail when the file is out of date")
    a = ap.parse_args()
    out = REPO / "docs" / "configuration.md"
    if a.check:
        return 0 if out.exists() and out.read_text() == render() else 1
    out.write_text(render())
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
