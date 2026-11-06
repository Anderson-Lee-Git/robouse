"""The RoboCasa scenario backend's SPH liquid package (backends/robocasa/physics/liquid) and the scenario plugin
interface: one module identity per process, no import of any benchmark's package, container kinds and scene-specific
predicates registered from outside. The native solver itself needs RoboCasa's interpreter and is not run here."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from robouse.backends.robocasa import scenario as S
from robouse.backends.robocasa.physics import LIQUID, load_liquid
from robouse.backends.robocasa.scenario_backend import check_spec

ROBOCASA = Path(S.__file__).parent


def test_robouse_never_imports_a_benchmark_package() -> None:
    files = [ROBOCASA / "scenario.py", ROBOCASA / "worker.py", *sorted((ROBOCASA / "physics").rglob("*.py"))]
    assert not [str(f) for f in files if "omni_safety" in f.read_text()]


def test_the_liquid_package_loads_by_path_without_robouse_or_a_benchmark(tmp_path) -> None:
    # as in the worker: scenario.py loaded by path, nothing of robouse or any benchmark on sys.path
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('robouse_robocasa_scenario', {str(ROBOCASA / 'scenario.py')!r})\n"
        "S = importlib.util.module_from_spec(spec); sys.modules[spec.name] = S; spec.loader.exec_module(S)\n"
        "scene = S.load_liquid('scene')\n"
        "assert scene.__name__ == 'robouse_robocasa_liquid.scene', scene.__name__\n"
        "assert S.load_liquid() is sys.modules['robouse_robocasa_liquid']\n"
        "assert not [m for m in sys.modules if m.startswith(('robouse.', 'omni_safety'))] and 'robouse' not in sys.modules\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=120,
                       env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_one_module_identity_per_process() -> None:
    liquid = load_liquid()
    assert liquid.__name__ == LIQUID and liquid.__version__ == "0.3.0"
    assert S.load_liquid() is liquid and S.load_liquid("scene") is load_liquid("scene")
    assert load_liquid("scene").solver is load_liquid("solver")
    with pytest.raises(ImportError, match="load_liquid"):
        __import__("robouse.backends.robocasa.physics.liquid")


def test_container_kinds_are_registered_from_outside(monkeypatch) -> None:
    liquid = load_liquid()
    monkeypatch.setattr(liquid, "PROFILES", dict(liquid.PROFILES))
    monkeypatch.setattr(liquid, "VISUAL_GEOM", dict(liquid.VISUAL_GEOM))
    with pytest.raises(ValueError, match="ROBOUSE_ROBOCASA_PLUGINS"):
        liquid.container_kind("test_cup")
    queries = load_liquid("queries")

    def profile():
        return queries.Container("cup", [(0.03, 0.0), (0.03, 0.1)])

    liquid.register_container("test_cup", profile, None, "cup_visual")
    liquid.register_container("test_cup", profile, None, "cup_visual")  # the same again: no-op
    assert liquid.container_kind("test_cup") == (profile, None, "cup_visual")
    with pytest.raises(ValueError, match="different definition"):
        liquid.register_container("test_cup", profile, None, "other_visual")
    with pytest.raises(ValueError, match="visual mesh"):
        liquid.register_container("test_bowl", profile)


def test_plugins_add_predicates_and_never_replace_built_ins(tmp_path, monkeypatch) -> None:
    (tmp_path / "rl_test_plugin.py").write_text(
        "def held(env, p):\n    return bool(getattr(env, 'flag', False))\n\n"
        "def register(scenario):\n    scenario.register_predicate('test_flag', held)\n"
    )
    (tmp_path / "rl_bad_plugin.py").write_text("X = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(S, "PREDICATES", dict(S.PREDICATES))
    monkeypatch.setattr(S, "_loaded_plugins", set())
    spec = dict(id="t", kitchen={"layout": 1, "style": 1}, instruction="x", robot_anchor="counter",
                fixtures={"counter": {"type": "counter"}}, objects=[], goal={"pred": "test_flag"})
    monkeypatch.delenv("ROBOUSE_ROBOCASA_PLUGINS", raising=False)
    with pytest.raises(ValueError, match="bad predicate"):
        check_spec(spec)
    monkeypatch.setenv("ROBOUSE_ROBOCASA_PLUGINS", " rl_test_plugin ,")
    check_spec(spec)  # the host check loads the same plugins as the worker
    assert S.load_plugins() == []  # once per process
    assert S.evaluate(SimpleNamespace(flag=True), {"pred": "test_flag"})
    with pytest.raises(ValueError, match="built in"):
        S.register_predicate("liquid", lambda env, p: True)
    with pytest.raises(ValueError, match="already registered"):
        S.register_predicate("test_flag", lambda env, p: True)
    with pytest.raises(ValueError, match="register"):
        S.load_plugins(["rl_bad_plugin"])
    with pytest.raises(ModuleNotFoundError):
        S.load_plugins(["rl_no_such_plugin"])


def test_liquid_predicate_never_passes_without_physics() -> None:
    p = {"pred": "liquid", "region": "surface", "max_ml": 1}
    with pytest.raises(RuntimeError, match="attached"):
        S.evaluate(SimpleNamespace(), p)
    assert S.evaluate(SimpleNamespace(_liquid_initializing=True), p) is False  # pre-episode settling only
    fluid = SimpleNamespace(positions=lambda: np.zeros((1, 3)))
    ls = SimpleNamespace(fluid=fluid, containers={}, coupling=SimpleNamespace(absorbers=[]),
                         volumes_ml=lambda: {"surface": 0.5})
    assert S.evaluate(SimpleNamespace(_liquid_scene=ls), p)
    with pytest.raises(ValueError, match="unknown liquid region"):
        S.evaluate(SimpleNamespace(_liquid_scene=ls), {"pred": "liquid", "region": "sink", "max_ml": 1})
