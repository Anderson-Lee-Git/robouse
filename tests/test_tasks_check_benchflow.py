"""`robouse tasks check` runs BenchFlow's own `bench tasks check` only when the installed BenchFlow can read robouse
task folders (its task-format hook, and robouse's format on its embodied layer: BenchFlow's `robouse` branch today).
Otherwise it says which case it is: BenchFlow is not installed, or the installed BenchFlow (e.g. 0.7.9.dev2354 from
PyPI, what `robouse[benchflow]` installs) has no robouse task-format support. Before 0.3.1 both said "not installed"."""

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


def _check(capsys) -> tuple[int, str]:
    code = main(["tasks", "check", str(ARC), "--no-run"])
    return code, capsys.readouterr().out


def _must_not_run(*args, **kwargs):
    raise AssertionError("BenchFlow's check ran without robouse task-format support")


def _fake(monkeypatch, name: str, package: bool = False, **attrs) -> None:
    """Stand a module in for `name` for this test; a package's other submodules do not exist."""
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, None, is_package=package)
    if package:
        mod.__path__ = []
    vars(mod).update(attrs)
    monkeypatch.setitem(sys.modules, name, mod)


def test_benchflow_not_installed(monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "benchflow", None)  # find_spec finds nothing and `import benchflow` fails
    code, out = _check(capsys)
    assert code == 0 and NOT_INSTALLED in out and NO_SUPPORT not in out


@pytest.mark.parametrize("hook", [False, True], ids=["no-task-format-hook", "hook-without-embodied-layer"])
def test_benchflow_without_robouse_task_format_support(hook, monkeypatch, capsys) -> None:
    for name in [n for n in sys.modules if n == "benchflow" or n.startswith("benchflow.")]:
        monkeypatch.delitem(sys.modules, name)  # restored after the test
    monkeypatch.delitem(sys.modules, "robouse.engine.format", raising=False)  # loaded again, against this BenchFlow
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


def test_benchflow_with_robouse_task_format_support_runs_its_check(capsys) -> None:
    pytest.importorskip("benchflow.task.formats", reason="needs BenchFlow's task-format hook (its robouse branch)")
    pytest.importorskip("benchflow.embodied.sidecar", reason="needs BenchFlow's embodied layer (its robouse branch)")
    code, out = _check(capsys)
    assert code == 0 and "bench tasks check (structural): ok" in out
    assert NO_SUPPORT not in out and NOT_INSTALLED not in out
