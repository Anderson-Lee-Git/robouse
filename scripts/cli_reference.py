#!/usr/bin/env python3
"""Write docs/cli.md, the reference for the `robouse` and `robo` commands, from their real `--help` output.

    /path/to/venv/bin/python scripts/cli_reference.py            # uses that venv's `robouse` and `robo`
    python scripts/cli_reference.py --robouse /path/to/robouse   # or name the executable (robo is found next to it)

Run it against an installed release (not a checkout), so the page shows what users get. The list of commands is read
from `robouse --help`, and a command with subcommands gets one block per subcommand, so a new command appears on the
page without editing this script. Subcommands whose help starts with "(maintainers)" are left out. The few notes that
say more than the help text are in NOTES.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "cli.md"
NOTES = {
    "run": "Prints a JSON summary: `trial`, `reward`, `outcome`, `steps`, `wall_s`, `exception`. A non-null `exception` means the trial could not start; it is not scored.",
    "run-many": "Prints one line per finished trial, appends it to `OUT/run_log.jsonl`, and ends with the number solved. Examples: [Run a suite or dataset](run-a-suite.md).",
    "serve": "Runs one episode server until the episode ends, then prints the verdict as JSON. `robouse run` starts it for you; to drive a robot by hand, start it and set `ROBOUSE_SOCKET` to the socket path.",
}
ROBO_NOTE = (
    "Each call sends one JSON object to the episode server at `$ROBOUSE_SOCKET` and prints the response, for example "
    '`{"op": "act", "action": [0, 0, -1, 1], "repeat": 5}` and `{"ok": true, "result": {...}}`. '
    "Operations: `info`, `status`, `observe`, `act`, `move_to`, `grip`, `skill`, `done`, `give_up`. "
    "`robo info` also describes the robot's embodiment: its action groups, skills, cameras and budgets. "
    "Skills run on the server, and each simulated step they take counts against the budget. "
    "Without an episode, `robo` prints an error and exits 1."
)


def helptext(exe: str, *args: str) -> str:
    env = {**os.environ, "COLUMNS": "80"}
    return subprocess.run([exe, *args], capture_output=True, text=True, env=env, check=True).stdout.rstrip()


def subcommands(text: str) -> list[tuple[str, str]]:
    """(name, one-line help) for each subcommand listed under the first {a,b,...} group of an argparse help text."""
    m = re.search(r"^  \{([\w,-]+)\}\n((?:    .*\n?)*)", text, re.M)
    if not m:
        return []
    names = m.group(1).split(",")
    helps: dict[str, str] = {}
    cur = None
    for line in m.group(2).splitlines():
        mm = re.match(r"^    ([\w-]+)\s*(.*)$", line)
        if mm and mm.group(1) in names:
            cur = mm.group(1)
            helps[cur] = mm.group(2).strip()
        elif cur:
            helps[cur] += " " + line.strip()
    return [(n, helps.get(n, "")) for n in names]


def block(cmd: str, text: str) -> list[str]:
    return ["```console", f"$ {cmd}", text, "```"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--robouse", default=shutil.which("robouse", path=str(Path(sys.executable).parent)) or "robouse")
    a = ap.parse_args()
    robo = str(Path(a.robouse).with_name("robo"))
    version = helptext(a.robouse, "--version")
    top = helptext(a.robouse, "--help")
    out = ["# CLIs", "",
           f"`robouse` runs tasks, trials and runs; `robo` is the agent's only way to act. The help below is the output of `{version}`.",
           "", *block("robouse --help", top)]
    for name, desc in subcommands(top):
        if desc.startswith("(maintainers)"):
            continue
        text = helptext(a.robouse, name, "--help")
        out += ["", f"## robouse {name}", "", *block(f"robouse {name} --help", text)]
        subs = subcommands(text)
        for sub, sdesc in subs if any(d for _, d in subs) else []:  # a choice argument, not subcommands, has no help lines
            if not sdesc.startswith("(maintainers)"):
                out += ["", *block(f"robouse {name} {sub} --help", helptext(a.robouse, name, sub, "--help"))]
        if name in NOTES:
            out += ["", NOTES[name]]
    out += ["", "## robo", "", *block("robo help", helptext(robo, "help")), "", ROBO_NOTE]
    DOC.write_text("\n".join(out) + "\n")
    print(f"wrote {DOC} from {version}")


if __name__ == "__main__":
    main()
