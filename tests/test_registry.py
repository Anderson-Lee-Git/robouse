"""The backend registry, reference-solution dispatch, harness launchers and trial selection."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from robouse.backends import BACKENDS, backend_class
from robouse.oracle import oracle_module
from robouse.tasks import find_tasks

ROOT = Path(__file__).resolve().parents[1]


def test_every_backend_package_exists_and_exports_its_class_and_reference_solution() -> None:
    for kind, (pkg, cls) in BACKENDS.items():
        init = ROOT / "src" / "robouse" / "backends" / pkg / "__init__.py"
        text = init.read_text()
        assert cls in text, kind
        if kind != "remix":
            assert importlib.util.find_spec(f"robouse.backends.{pkg}") is not None


def test_every_bundled_task_names_a_known_backend_and_reference_solution() -> None:
    oracles = set()
    for t in find_tasks(ROOT / "tasks"):
        assert t.spec["backend"] in BACKENDS, t.id
        m = re.search(r"robouse\.oracle --backend (\w+)", (t.path / "oracle" / "solve.sh").read_text())
        if m:
            oracles.add(m.group(1))
    for kind in oracles:
        assert oracle_module(kind).startswith("robouse.backends."), kind
    with pytest.raises(KeyError):
        oracle_module("warp-drive")


def test_unknown_backend_names_the_known_ones() -> None:
    with pytest.raises(KeyError, match="built in: adroit"):
        backend_class("warp-drive")


def test_harness_launchers(tmp_path, monkeypatch) -> None:
    from robouse import harnesses
    from robouse.harnesses import credentials

    class T:
        oracle_script = tmp_path / "solve.sh"
        metadata: dict = {}
        meta: dict = {"task": {"description": "put the cube in the bowl"}}
        spec: dict = {}

    (tmp_path / ".robouse").mkdir()
    assert harnesses.build("oracle", "", "p", tmp_path, T, {}).cmd == ["bash", str(tmp_path / "solve.sh")]
    launch = harnesses.build("noop", "", "p", tmp_path, T, {"X": "1"})
    assert launch.cmd == ["robo", "done", "noop control"] and launch.env == {"X": "1"}
    with pytest.raises(KeyError, match="unknown harness"):
        harnesses.build("telepathy", "", "p", tmp_path, T, {})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(tmp_path / "cache"))
    launch = harnesses.build("claude-code", "", "do it", tmp_path, T, {})
    assert launch.env["ANTHROPIC_API_KEY"] == "k" and launch.cmd[0] == "claude" and "do it" in launch.cmd[2]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(credentials._maintainer, "claude_tokens", lambda: [])
    with pytest.raises(RuntimeError, match="no Claude credentials"):
        harnesses.build("claude-code", "", "p", tmp_path, T, {})
    monkeypatch.delenv("ROBOUSE_VLA_URL", raising=False)
    with pytest.raises(RuntimeError, match="ROBOUSE_VLA_URL"):
        harnesses.build("vla", "openpi/pi05_libero", "p", tmp_path, T, {})


def test_seeds_selection_and_cost(tmp_path, monkeypatch) -> None:
    from robouse.runner import parse_seeds, select_tasks
    from robouse.runner.cost import trial_cost

    assert parse_seeds("0-2,7") == [0, 1, 2, 7] and parse_seeds(None) == [None]
    root = ROOT / "tasks" / "arc-style"
    all_ids = [t.id for t in find_tasks(root)]
    picked = select_tasks(root, include=["arc-*"], exclude=[all_ids[0]], sample=3, sample_seed=1)
    assert len(picked) == 3 and all_ids[0] not in [t.id for t in picked]
    assert [t.id for t in picked] == [t.id for t in select_tasks(root, include=["arc-*"], exclude=[all_ids[0]], sample=3,
                                                                  sample_seed=1)]
    tdir = tmp_path / "trial"
    (tdir / "agent").mkdir(parents=True)
    (tdir / "agent" / "trajectory.json").write_text(json.dumps({"final_metrics": {
        "total_prompt_tokens": 1_000_000, "total_completion_tokens": 100_000, "total_cached_tokens": 0}}))
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"m": {"input": 1.0, "output": 10.0, "source": "test"}}))
    monkeypatch.setenv("ROBOUSE_PRICING", str(prices))
    c = trial_cost(tdir, "m", None)
    assert c["cost_usd"] == 2.0 and c["cost_source"].startswith("pricing.json")
    assert trial_cost(tmp_path / "none", "scripted", None)["cost_usd"] == 0.0
