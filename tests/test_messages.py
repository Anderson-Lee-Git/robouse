"""User-facing text points at the published docs (https://robouse.ai/docs/), never at files under docs/ in the
repository, which are not published; and numbers in it come from the package's own data."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from robouse import config
from robouse.cli import main

SRC = Path(__file__).resolve().parents[1] / "src" / "robouse"
REPO_DOCS = re.compile(r"(?<![\w./:-])docs/[\w./-]+")  # docs/suites/x.md, not https://robouse.ai/docs/...
COMMANDS = [
    ["--help"],
    *[[c, "--help"] for c in ("run", "run-many", "fetch-assets", "report", "summarize", "doctor")],
    *[[c, "--help"] for c in ("serve", "grade", "estop", "operator", "hil-check", "robots", "export")],
    ["tasks", "--help"],
    *[["tasks", c, "--help"] for c in ("list", "init", "check")],
    ["components", "--help"],
    *[["components", c, "--help"] for c in ("list", "show", "check")],
]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: " ".join(a))
def test_help_has_no_repository_paths(argv, capsys) -> None:
    with pytest.raises(SystemExit):
        main(argv)
    out = capsys.readouterr().out
    assert out.startswith("usage: robouse") and not REPO_DOCS.findall(out), REPO_DOCS.findall(out)


def test_fetch_assets_sizes_come_from_the_manifests(capsys) -> None:
    from robouse.assets import about_mb, download_bytes, manifests

    every = sum(f["bytes"] for m in manifests() for f in __import__("json").loads(m.read_text())["files"])
    assert download_bytes(everything=True) == every and 300e6 < every < 500e6  # 0.2.0: 390,856,432 bytes
    assert 40e6 < download_bytes() < 50e6  # the base robots: 43,485,260 bytes
    with pytest.raises(SystemExit):
        main(["fetch-assets", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert f"({about_mb(every)})" in out and "GB" not in out


def _strings(path: Path) -> list[tuple[int, str]]:
    """String constants of a module that are not docstrings (f-string parts included)."""
    tree = ast.parse(path.read_text())
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    return [
        (n.lineno, n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    ]


def test_messages_have_no_repository_paths() -> None:
    found = [
        f"{p.relative_to(SRC)}:{line}: {m}"
        for p in sorted(SRC.rglob("*.py"))
        if "bundled_tasks" not in p.parts
        for line, s in _strings(p)
        for m in REPO_DOCS.findall(s)
    ]
    assert not found, found


def test_missing_simulator_virtualenv_points_at_the_suites_page(tmp_path) -> None:
    from robouse.workers.client import StdioWorker, WorkerError

    with pytest.raises(WorkerError) as e:
        StdioWorker("robocasa", tmp_path / "no-venv" / "bin" / "python", tmp_path / "w.py", setup=config.SUITES_DOCS)
    assert "see https://robouse.ai/docs/suites/" in str(e.value)


def test_composed_task_error_points_at_the_task_format_page() -> None:
    from robouse.backends.components.backend import read_block

    with pytest.raises(KeyError) as e:
        read_block({"backend": "components"})
    assert "https://robouse.ai/docs/task-format/" in str(e.value)
