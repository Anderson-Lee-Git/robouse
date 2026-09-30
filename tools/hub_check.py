"""Would a re-export change any published hub task? Compares every task of the published datasets (a hub registry)
with its source folder in this checkout: the `robouse:` block (backend, simulator parameters, budgets, scoring) must be
equal and the instruction the agent reads must be unchanged. The vendored oracle code and the simulator runtime are
not compared: they change with the package, and publishing them means a new dataset version.

    python tools/hub_check.py --registry registry.json --hub ~/robohub [--repo .] [--json OUT]

Reads published packages from the hub's git history (`git show COMMIT:PATH/task.md`). Exit status 1 when a task
changed or has no source folder here.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def split(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, flags=re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def norm(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", required=True, type=Path)
    ap.add_argument("--hub", required=True, type=Path, help="a clone of the hub repository with the pinned commits")
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--json", type=Path, help="write the per-task findings here")
    a = ap.parse_args()
    sources: dict[str, tuple[dict, str, str]] = {}
    for md in sorted((a.repo / "tasks").glob("*/*/task.md")):
        meta, body = split(md.read_text())
        spec = meta.get("robouse") or {}
        sources[str(spec.get("id") or md.parent.name)] = (spec, body, md.parent.parent.name)
    report: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for ds in json.loads(a.registry.read_text()):
        name = f"{ds['name']}@{ds['version']}"
        for t in ds["tasks"]:
            r = subprocess.run(
                ["git", "-C", str(a.hub), "show", f"{t['git_commit_id']}:{t['path']}/task.md"],
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode != 0:
                report[name]["unreadable"].append(t["name"])
                continue
            meta, body = split(r.stdout)
            spec = (meta.get("metadata") or {}).get("robouse") or meta.get("robouse") or {}
            tid = str(spec.get("id") or t["path"].rsplit("/", 1)[-1])
            if tid not in sources:
                report[name]["no source"].append(tid)
                continue
            src_spec, src_body, suite = sources[tid]
            why = []
            if src_spec != spec:
                keys = sorted(k for k in set(src_spec) | set(spec) if src_spec.get(k) != spec.get(k))
                why.append("robouse block: " + ", ".join(keys))
            if norm(src_body) not in norm(body):
                why.append("instruction")
            report[name]["changed" if why else "unchanged"].append(tid + (f" ({'; '.join(why)})" if why else ""))
    bad = 0
    for name, groups in sorted(report.items()):
        n_bad = sum(len(v) for k, v in groups.items() if k != "unchanged")
        bad += n_bad
        print(
            f"{name:48} unchanged {len(groups['unchanged']):4}"
            + "".join(f"  {k} {len(v)}" for k, v in sorted(groups.items()) if k != "unchanged" and v)
        )
        for k, v in sorted(groups.items()):
            if k != "unchanged":
                for x in v[:5]:
                    print(f"    {k}: {x}")
    if a.json:
        a.json.write_text(json.dumps(report, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
