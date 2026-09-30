"""Which files share duplicated code (the windows tools/metrics.py counts), most shared first.

python tools/dup_report.py [--repo .] [--top 30]
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter, defaultdict
from pathlib import Path

from metrics import WINDOW, code_lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()
    src = a.repo / "src" / "robouse"
    windows: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(src.rglob("*.py")):
        cl = code_lines(p)
        for k in range(len(cl) - WINDOW + 1):
            chunk = "\n".join(t for _, t in cl[k : k + WINDOW])
            if len(chunk) >= 120:
                windows[hashlib.sha1(chunk.encode()).hexdigest()].append(p)
    groups: Counter[str] = Counter()
    for files in windows.values():
        if len(files) > 1:
            groups[" | ".join(sorted({str(f.relative_to(src)) for f in files}))] += 1
    for g, n in groups.most_common(a.top):
        print(n, g)


if __name__ == "__main__":
    main()
