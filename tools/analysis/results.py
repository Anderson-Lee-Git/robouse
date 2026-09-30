"""Results tables from all trials under runs/ -> docs/results.md.

Uses runs/_audit/audit.json (run tools/analysis/audit.py first). One row per harness + model, one column per suite:
solved / scored trials, where scored excludes infrastructure failures and still-running trials. If a task was run
more than once by the same harness + model, the latest trial counts.

  .venv/bin/python tools/analysis/results.py

It takes no arguments: any argument, including --help, is ignored and docs/results.md is rewritten.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITES = [
    "metaworld",
    "gymrobotics",
    "libero",
    "libero-style",
    "arc-style",
    "robo-use-families",
    "safety",
    "vision",
    "hard",
    "robosuite",
]
# keys are the canonical (harness, model) pairs audit.py records (robouse.harnesses.models.canonical)
LABEL = {
    "claude-code/claude-opus-5-5": "Claude Code + Opus 5.5",
    "codex/gpt-6-astra": "Codex + GPT-6 Astra",
    "claude-code/baseten/zai-org/GLM-5.3": "Claude Code + GLM-5.3",
    "codex/baseten/zai-org/GLM-5.3": "Codex + GLM-5.3",
    "mini-swe-agent/baseten/zai-org/GLM-5.3": "mini-swe-agent + GLM-5.3 (no image input)",
    "claude-code/baseten/moonshotai/Kimi-K3": "Claude Code + Kimi K3",
    "codex/baseten/moonshotai/Kimi-K3": "Codex + Kimi K3",
    "mini-swe-agent/baseten/moonshotai/Kimi-K3": "mini-swe-agent + Kimi K3 (no image input)",
    "oracle/scripted": "Reference solutions",
    "noop/none": "No-op control",
}
ORDER = list(LABEL)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Write docs/results.md from runs/_audit/audit.json.")
    ap.add_argument("--jobs", default="", help="comma-separated job prefixes to include (default: all)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "results.md"))
    args = ap.parse_args()
    prefixes = tuple(p for p in args.jobs.split(",") if p)
    audit = json.loads((ROOT / "runs" / "_audit" / "audit.json").read_text())
    latest: dict[tuple, dict] = {}
    for r in audit["trials"]:
        if r.get("running") or r.get("harness") in ("lerobot-eval", "molmoact2-sim-eval"):
            continue
        if prefixes and not r.get("job", "").startswith(prefixes):
            continue
        key = (f"{r['harness']}/{r['model']}", r["task"])
        prev = latest.get(key)
        if (
            prev is None
            or (r.get("path", "") > prev.get("path", "") and not r.get("infra_failure"))
            or prev.get("infra_failure")
        ):
            latest[key] = r
    table: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))  # solved, scored, infra
    for (hm, _task), r in latest.items():
        cell = table[hm][r.get("suite") or "?"]
        if r.get("infra_failure"):
            cell[2] += 1
            continue
        cell[1] += 1
        cell[0] += 1 if r.get("solved") else 0
    rows = sorted(table, key=lambda k: ORDER.index(k) if k in ORDER else 99)
    out = [
        "# Results",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `tools/analysis/results.py` from `runs/_audit/audit.json`. "
        "Each cell is solved / scored trials (one trial per task; infrastructure failures excluded and counted separately; "
        "a trial stopped at the spend cap counts as not solved). "
        "Tasks per suite: see docs/suites/.",
        "",
        "| Harness + model | " + " | ".join(SUITES) + " | All | Infra failures |",
        "|---|" + "---|" * (len(SUITES) + 2),
    ]
    for hm in rows:
        if "?" in hm or not any(sum(v) for v in table[hm].values()):
            continue
        cells, tot_s, tot_n, tot_i = [], 0, 0, 0
        for s in SUITES:
            sv, n, inf = table[hm].get(s, [0, 0, 0])
            tot_s, tot_n, tot_i = tot_s + sv, tot_n + n, tot_i + inf
            cells.append(f"{sv}/{n}" if n else "-")
        pct = f" ({100 * tot_s / tot_n:.0f}%)" if tot_n else ""
        out.append(f"| {LABEL.get(hm, hm)} | " + " | ".join(cells) + f" | {tot_s}/{tot_n}{pct} | {tot_i} |")
    molmo = [r for r in audit["trials"] if r.get("harness") in ("lerobot-eval", "molmoact2-sim-eval")]
    if molmo:
        out += [
            "",
            "## MolmoAct2 (VLA, remote GPU)",
            "",
            "| Harness | Model | Benchmark | Solved |",
            "|---|---|---|---|",
        ]
        by = defaultdict(lambda: [0, 0])
        for r in molmo:
            k = (r["harness"], r["model"], r.get("source_benchmark") or "")
            by[k][1] += 1
            by[k][0] += 1 if r.get("solved") else 0
        for (h, m, b), (sv, n) in sorted(by.items()):
            out.append(f"| {h} | {m} | {b} | {sv}/{n} |")
        out += ["", "These run on LIBERO and ManiSkill scenes, not robo-use's own tasks; see docs/molmoact2.md."]
    Path(args.out).write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
