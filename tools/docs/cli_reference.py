#!/usr/bin/env python3
"""Write docs/cli.md, the `robouse` command reference, from the real `--help` output of an installed robouse.

    /path/to/venv/bin/python tools/docs/cli_reference.py            # uses that venv's `robouse`
    python tools/docs/cli_reference.py --robouse /path/to/robouse   # or name the executable

Run it against the release users install from PyPI (not a checkout), so the page shows what they get. The help
blocks are pasted verbatim; the short notes under each command are kept in NOTES below.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DOC = Path(__file__).resolve().parents[2] / "docs" / "cli.md"
COMMANDS = ["run", "run-many", "report", "summarize", "tasks", "tasks init", "tasks check", "components", "components check",
            "export", "robots", "estop", "operator", "hil-check", "fetch-assets", "serve"]
NOTES = {
    "run": """`--model` names the model for model harnesses and the preset for `vla` ([VLA policies](vla.md)). `--rig` runs a real-robot task on live hardware instead of the hardware-in-the-loop mock ([Real robots](real-robots.md)). The command prints a JSON summary (`trial`, `reward`, `outcome`, `steps`, `wall_s`, `exception`). A non-null `exception` means the trial could not start; it is not a score.""",
    "run-many": """`--tasks` is searched recursively. The command prints one line per finished trial, appends it to `OUT/run_log.jsonl`, and ends with the number solved. Seeds, epochs, splits, sampling and retries: [Metrics, splits, repeats and reports](metrics.md).""",
    "report": """Metrics with 95% intervals over job folders; see [Metrics](metrics.md).""",
    "summarize": """A deterministic digest of one trial (outcome, judge detail, safety events, robot errors, last requests) as markdown, for `--prior-learnings`.""",
    "robots": """Real-robot profiles, drivers and hardware-in-the-loop fixtures ([Real robots](real-robots.md)).""",
    "estop": """Latches the e-stop: every real-robot episode stops at its next command and the arm holds. `--clear` releases it.""",
    "operator": """The operator's side of an attended real-robot run: `status` (the pending gate or verdict), `answer` (yes / no / partial / skip or a rubric stage), `say` (a remark the policy sees in its next observation).""",
    "hil-check": """Strict replay of recorded real sessions through the safety guard, and the fitted tracking model's error.""",
    "tasks": """`robouse tasks` alone is `robouse tasks list`: one line per task (id, backend, simulator env id, empty for tabletop tasks).""",
    "fetch-assets": """Downloads the MuJoCo Menagerie robot models that the Menagerie-based suites and composed tasks need, each checked by SHA-256 (`--robot` limits it to some robots). Files already present are skipped. The episode server looks in `$ROBOUSE_MENAGERIE_ASSETS`, else `~/.cache/robouse/menagerie`.""",
    "tasks init": """With `--embodiment`, `--scene` and `--task`, composes a task from components and keeps it only if the reference solution scores 1 and the no-op control 0 ([Components](components.md)). `--grid` takes comma-separated values in any of those flags and composes every compatible combination. `--from DIR` regenerates a composed task from its recorded instance. With only `DIR`, it scaffolds a blank task folder (`task.md`, `oracle/solve.sh`, `verifier/test.sh`) for a backend of your own.""",
    "tasks check": """Checks the task.md schema, runs `bench tasks check` on the task, then runs the reference solution (must score 1) and the no-op control (must score 0) with the local engine. Exits 1 on any problem.""",
    "components": """`robouse components list [KIND] [--all]` lists the components (`--all` adds the fixed ones that describe existing suites); `robouse components show ID [--compatible]` prints one manifest.""",
    "components check": """Says whether the embodiment, scene and task template fit together with these modifiers, and lays the task out for the seed; exits 1 with the reasons if not.""",
    "export": """Writes each task as a native BenchFlow task package under `OUT/tasks/`, plus the simulator runtime they build from, so `bench eval run --tasks-dir OUT/tasks` runs them.""",
    "serve": """Runs one episode server on a Unix socket until the episode ends, then prints the verdict as JSON. `run` starts it for you; use it directly to drive a robot by hand with `robo` (set `ROBOUSE_SOCKET` to the socket path).""",
}


def helptext(exe: str, *args: str) -> str:
    env = {**os.environ, "COLUMNS": "80"}
    return subprocess.run([exe, *args, "--help"], capture_output=True, text=True, env=env, check=True).stdout.rstrip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--robouse", default=shutil.which("robouse", path=str(Path(sys.executable).parent)) or "robouse")
    a = ap.parse_args()
    version = subprocess.run([a.robouse, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    out = ["# robouse CLI", "",
           f"`robouse` runs tasks, episodes and trials. The help blocks below are the output of `{version}`, generated by `tools/docs/cli_reference.py`.",
           "", "```console", "$ robouse --help", helptext(a.robouse), "```"]
    for c in COMMANDS:
        out += ["", f"## robouse {c}", "", "```console", f"$ robouse {c} --help", helptext(a.robouse, *c.split()), "```", "", NOTES[c]]
    DOC.write_text("\n".join(out) + "\n")
    print(f"wrote {DOC} from {version}")


if __name__ == "__main__":
    main()
