"""The `robouse` command line: every command parses, and the planning paths work without a simulator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from robouse.cli import main, parser

ROOT = Path(__file__).resolve().parents[1]
VISIBLE = ["run", "run-many", "tasks", "components", "fetch-assets", "report", "summarize", "doctor"]
HIDDEN = ["serve", "grade", "estop", "operator", "hil-check", "robots", "export"]
COMMANDS = [c for c in VISIBLE + HIDDEN if c not in ("tasks", "components")]


@pytest.mark.parametrize("cmd", COMMANDS)
def test_help(cmd: str, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        main([cmd, "--help"])
    assert e.value.code == 0 and capsys.readouterr().out.startswith(f"usage: robouse {cmd}")


def test_top_level_help_lists_only_the_tested_commands(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    listed = {line.split()[0] for line in out.splitlines() if line.startswith("    ") and not line.startswith("     ")}
    assert out.count("Robo Use") == 1 and listed == set(VISIBLE)


def test_run_many_dry_run(capsys) -> None:
    rc = main(
        [
            "run-many",
            "--tasks",
            str(ROOT / "tasks" / "arc-style"),
            "--harness",
            "oracle",
            "--out",
            "/tmp/unused",
            "--sample",
            "2",
            "--seeds",
            "0-1",
            "--dry-run",
        ]
    )
    plan = json.loads(capsys.readouterr().out)
    assert rc == 0 and len(plan["tasks"]) == 2 and plan["trials"] == 4


def test_local_run_rejects_seeds(capsys) -> None:
    rc = main(["run", "--task", "arc-gravity", "--harness", "oracle", "--out", "/tmp/unused", "--seeds", "0-2"])
    assert rc == 2 and "run-many --seeds" in capsys.readouterr().err


def test_tasks_list_and_robots(capsys) -> None:
    assert main(["tasks", "list", str(ROOT / "tasks" / "arc-style")]) == 0
    assert "arc-gravity tabletop" in capsys.readouterr().out
    assert main(["robots"]) == 0
    out = capsys.readouterr().out
    assert "rosbridge" in out and "so100" in out


def test_record_size_is_validated(capsys) -> None:
    rc = main(["run", "--task", "arc-gravity", "--harness", "oracle", "--out", "/tmp/unused", "--record-size", "huge"])
    assert rc == 2 and "1280x720" in capsys.readouterr().err


def test_parser_builds() -> None:
    assert parser().prog == "robouse"
