"""Task and suite counts for README.md and the docs, from the package's own data: the suites pyproject.toml puts in the
wheel ([tool.hatch.build.targets.wheel.force-include]) and their task.md files, plus the hub-only suites, which have
task folders but are not in the wheel.

    python tools/docs/counts.py           # rewrite every "N tasks in M suites" in README.md and docs/suites.md
    python tools/docs/counts.py --check   # exit 1 and list them if any disagrees with the package

tools/docs/suites_reference.py writes the suites tables; tests/test_counts.py checks all of it, so the numbers cannot
drift from the package.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Suites with task folders whose simulators run in their own hub images (the upstream projects' pinned stacks), not in
# the wheel. The suites page lists them in a table of their own.
HUB_ONLY = ("rle-bench", "capx", "capx-libero")
PHRASE = re.compile(r"\b\d+ tasks in \d+ suites\b")
FILES = ("README.md", "docs/suites.md")


def _count(repo: Path, suite: str) -> int:
    return sum(1 for _ in (repo / "tasks" / suite).rglob("task.md"))


def bundled(repo: Path = REPO) -> dict[str, int]:
    """suite -> number of tasks, for every suite the wheel bundles."""
    wheel = tomllib.loads((repo / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]["wheel"]
    suites = sorted(k.removeprefix("tasks/") for k in wheel.get("force-include", {}) if k.startswith("tasks/"))
    return {s: _count(repo, s) for s in suites}


def hub_only(repo: Path = REPO) -> dict[str, int]:
    return {s: _count(repo, s) for s in HUB_ONLY}


def phrase(counts: dict[str, int]) -> str:
    return f"{sum(counts.values())} tasks in {len(counts)} suites"


def mismatches(repo: Path = REPO) -> list[str]:
    want = phrase(bundled(repo))
    return [
        f"{name}: says '{m.group(0)}', the package has {want}"
        for name in FILES
        for m in PHRASE.finditer((repo / name).read_text(encoding="utf-8"))
        if m.group(0) != want
    ]


def rewrite(repo: Path = REPO) -> list[str]:
    want = phrase(bundled(repo))
    changed = []
    for name in FILES:
        p = repo / name
        text = p.read_text(encoding="utf-8")
        new = PHRASE.sub(want, text)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed.append(name)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="only report counts that disagree with the package")
    a = ap.parse_args()
    if a.check:
        bad = mismatches()
        for line in bad:
            print(line)
        return 1 if bad else 0
    changed = rewrite()
    print(f"{phrase(bundled())}; rewrote {', '.join(changed) or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
