"""What robouse says about BenchFlow support.

`robouse tasks check` runs BenchFlow's own `bench tasks check` only when the installed BenchFlow can read robouse
task folders (its task-format hook, and robouse's format on its embodied layer: an unreleased BenchFlow build today;
no release on PyPI has it). Otherwise it says which case it is: BenchFlow is not installed, or the installed
BenchFlow (e.g. 0.7.9.dev2354 from PyPI, what `robouse[benchflow]` installs) has no robouse task-format support.
Before 0.3.1 both said "not installed".

The hidden BenchFlow engine (`--engine benchflow`) and `robouse export` say what they need, BenchFlow's embodied
support, which is not in a PyPI release of BenchFlow yet, and what this environment has. Before 0.3.1 they said
"install robouse[benchflow]", which installs a BenchFlow without it."""

from __future__ import annotations

import importlib.machinery
import sys
import types
from pathlib import Path

import pytest

from robouse.cli import main

ARC = Path(__file__).resolve().parents[1] / "tasks" / "arc-style" / "arc-gravity"
NOT_INSTALLED = "bench tasks check: skipped (BenchFlow is not installed)"
NO_SUPPORT = "bench tasks check: installed BenchFlow has no robouse task-format support; skipped"
NEEDS = "needs BenchFlow's embodied support (benchflow.embodied), which is not in a PyPI release of BenchFlow yet"


def _engine(tmp: Path) -> list[str]:
    return ["run", "--task", str(ARC), "--harness", "oracle", "--engine", "benchflow", "--out", str(tmp / "job")]


def _export(tmp: Path) -> list[str]:
    return ["export", "--tasks", str(ARC), "--out", str(tmp / "bundle")]


COMMANDS = {"--engine benchflow": _engine, "export": _export}  # how each is named in its message


def _check(capsys) -> tuple[int, str]:
    code = main(["tasks", "check", str(ARC), "--no-run"])
    return code, capsys.readouterr().out


def _must_not_run(*args, **kwargs):
    raise AssertionError("BenchFlow's check ran without robouse task-format support")


def _forget(monkeypatch, package: str, itself: bool = True) -> None:
    """Drop `package`'s submodules, and the package itself, from sys.modules for this test; restored after."""
    for name in [n for n in sys.modules if n.startswith(package + ".") or (itself and n == package)]:
        monkeypatch.delitem(sys.modules, name)


def _no_benchflow(monkeypatch) -> None:
    """BenchFlow not installed, for this test: find_spec finds nothing and importing it, or any of its modules a test
    before this one loaded, fails."""
    _forget(monkeypatch, "benchflow")
    monkeypatch.setitem(sys.modules, "benchflow", None)


def _fake(monkeypatch, name: str, package: bool = False, **attrs) -> None:
    """Stand a module in for `name` for this test; a package's other submodules do not exist."""
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, None, is_package=package)
    if package:
        mod.__path__ = []
    vars(mod).update(attrs)
    monkeypatch.setitem(sys.modules, name, mod)


# ---- robouse tasks check ---------------------------------------------------------------------------------------------


def test_benchflow_not_installed(monkeypatch, capsys) -> None:
    _no_benchflow(monkeypatch)
    code, out = _check(capsys)
    assert code == 0 and NOT_INSTALLED in out and NO_SUPPORT not in out


@pytest.mark.parametrize("hook", [False, True], ids=["no-task-format-hook", "hook-without-embodied-layer"])
def test_benchflow_without_robouse_task_format_support(hook, monkeypatch, capsys) -> None:
    _forget(monkeypatch, "benchflow")
    _forget(monkeypatch, "robouse.engine", itself=False)  # loaded again, against this BenchFlow
    # PyPI's 0.7.9.dev2354: the task-authoring check, no task-format hook, no embodied layer
    _fake(monkeypatch, "benchflow", package=True)
    _fake(monkeypatch, "benchflow._utils", package=True)
    _fake(monkeypatch, "benchflow._utils.task_authoring", check_task=_must_not_run)
    if hook:  # a BenchFlow with the hook but not the embodied layer robouse's format is built on
        _fake(monkeypatch, "benchflow.task", package=True)
        _fake(
            monkeypatch, "benchflow.task.formats", detect_task_format=_must_not_run, materialize_task_dir=_must_not_run
        )
    code, out = _check(capsys)
    assert code == 0 and NO_SUPPORT in out and NOT_INSTALLED not in out


@pytest.mark.needs_benchflow_embodied
def test_benchflow_with_robouse_task_format_support_runs_its_check(capsys) -> None:
    pytest.importorskip("benchflow.task.formats", reason="needs BenchFlow's task-format hook (not released yet)")
    pytest.importorskip("benchflow.embodied.sidecar", reason="needs BenchFlow's embodied layer (not released yet)")
    code, out = _check(capsys)
    assert code == 0 and "bench tasks check (structural): ok" in out
    assert NO_SUPPORT not in out and NOT_INSTALLED not in out


# ---- the BenchFlow engine and export ---------------------------------------------------------------------------------


@pytest.mark.parametrize("what", COMMANDS)
def test_without_benchflow_the_engine_says_what_it_needs(what, tmp_path, monkeypatch, capsys) -> None:
    _no_benchflow(monkeypatch)
    _forget(monkeypatch, "robouse.engine", itself=False)
    assert main(COMMANDS[what](tmp_path)) == 1
    err = capsys.readouterr().err
    assert f"robouse: {what} {NEEDS}; BenchFlow is not installed" in err, err
    assert "robouse[benchflow]" not in err


def test_on_python_3_11_it_also_says_benchflow_needs_3_12(tmp_path, monkeypatch, capsys) -> None:
    _no_benchflow(monkeypatch)
    monkeypatch.setattr(sys, "version_info", (3, 11, 9, "final", 0))
    assert main(COMMANDS["--engine benchflow"](tmp_path)) == 1
    assert "BenchFlow is not installed, and it needs Python 3.12 or newer (this is 3.11)" in capsys.readouterr().err


@pytest.mark.parametrize("what", COMMANDS)
def test_a_benchflow_without_embodied_support_is_named(what, tmp_path, monkeypatch, capsys) -> None:
    _forget(monkeypatch, "benchflow")
    _forget(monkeypatch, "robouse.engine", itself=False)
    _fake(monkeypatch, "benchflow", package=True)  # PyPI's 0.7.9.dev2354 has no benchflow.embodied
    assert main(COMMANDS[what](tmp_path)) == 1
    err = capsys.readouterr().err
    assert f"robouse: {what} {NEEDS}; the installed BenchFlow" in err and "does not have it" in err, err
    assert "robouse[benchflow]" not in err


def test_with_embodied_support_another_import_failure_is_shown_as_it_is(tmp_path, monkeypatch, capsys) -> None:
    _forget(monkeypatch, "benchflow")
    _fake(monkeypatch, "benchflow", package=True)
    _fake(monkeypatch, "benchflow.embodied", package=True)  # embodied support, but not the module the engine needs
    assert main(COMMANDS["--engine benchflow"](tmp_path)) == 1
    err = capsys.readouterr().err
    assert "robouse: --engine benchflow could not load BenchFlow: ModuleNotFoundError" in err, err
    assert "benchflow.embodied.rollouts" in err and NEEDS not in err
