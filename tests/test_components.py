"""Components and remix: the manifests match the runtime, the resolver explains incompatibilities, remixes are
normal task folders, and one remix runs end to end (oracle 1, noop 0)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from robouse.components.registry import components_root, export, load
from robouse.components.remix import RemixError, instantiate, task_id, write
from robouse.components.resolve import check, modifiers
from robouse.tasks import load_task

HAS_SIM = importlib.util.find_spec("mujoco") is not None


def test_checked_in_manifests_equal_a_fresh_export(tmp_path) -> None:
    export(tmp_path)
    root = components_root()
    fresh = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("component.yaml"))
    ours = sorted(p.relative_to(root) for p in root.rglob("component.yaml"))
    assert fresh == ours
    for rel in fresh:
        assert yaml.safe_load((tmp_path / rel).read_text()) == yaml.safe_load((root / rel).read_text()), rel


def test_registry_covers_the_required_axes() -> None:
    reg = load()
    emb = reg.remixable("embodiments")
    assert {"franka-panda", "aloha-2", "pal-tiago", "unitree-go2", "crazyflie-2"} <= set(emb)
    kinds = {reg.embodiments[e]["kind"] for e in emb}
    assert {"arm", "bimanual", "mobile_manipulator", "quadruped", "drone"} <= kinds
    assert len(reg.remixable("scenes")) >= 4 and len(reg.remixable("tasks")) >= 8
    caps = {c for t in reg.remixable("tasks") for c in reg.tasks[t]["capabilities"]}
    assert {"spatial-reasoning", "topological-reasoning", "contact-rich", "long-horizon", "perception"} <= caps
    assert set(reg.modifiers["safety"]["values"]) == {"none", "direct", "indirect", "privacy"}


@pytest.mark.parametrize("emb,scene,task,why", [
    ("franka-panda", "outdoor-field", "put-in-container", "surface mount"),
    ("unitree-go2", "tabletop", "put-in-container", "capabilities"),
    ("crazyflie-2", "kitchen-counter", "stack-in-order", "placement"),
    ("franka-panda", "tabletop", "bimanual-relay", "bimanual"),
    ("pal-tiago", "tabletop", "fetch-and-deliver", "task needs 2"),
    ("franka-panda", "tabletop", "floating-gripper", None),
])
def test_resolver_explains_incompatibilities(emb, scene, task, why) -> None:
    reg = load()
    if why is None:
        with pytest.raises(KeyError):
            check(reg, emb, scene, task)
        return
    rep = check(reg, emb, scene, task)
    assert not rep.ok and why in " ".join(rep.reasons)


def test_resolver_accepts_and_checks_modifiers() -> None:
    reg = load()
    assert check(reg, "franka-panda", "kitchen-counter", "put-in-container", {"obs": "vision"}).ok
    rep = check(reg, "unitree-go2", "warehouse", "go-to-landmark", {"perturbation": "push"})
    assert not rep.ok and "task object" in rep.reasons[0]
    rep = check(reg, "franka-panda", "tabletop", "put-in-container", {"obs": "x-ray"})
    assert not rep.ok and "no value 'x-ray'" in rep.reasons[0]


def test_instances_are_deterministic_per_seed() -> None:
    m = modifiers({})
    a = instantiate("franka-panda", "tabletop", "stack-in-order", m, 3)
    b = instantiate("franka-panda", "tabletop", "stack-in-order", m, 3)
    c = instantiate("franka-panda", "tabletop", "stack-in-order", m, 4)
    assert a == b and a != c
    with pytest.raises(RemixError):
        instantiate("unitree-go2", "tabletop", "stack-in-order", m, 0)


def test_remix_writes_a_normal_task_folder(tmp_path) -> None:
    mods = modifiers({"safety": "privacy"})
    d = write("franka-panda", "kitchen-counter", "put-in-container", mods, 2, tmp_path)
    assert d.name == task_id("franka-panda", "kitchen-counter", "put-in-container", mods, 2)
    t = load_task(d)
    rb = t.meta["robouse"]
    assert rb["backend"] == "remix" and rb["components"]["embodiment"] == "franka-panda@0.1.0"
    assert rb["remix"]["instance"]["overlay"]["level"] == "privacy"
    assert "PIN" in t.body and "safety-judgement" in t.meta["metadata"]["capabilities"]
    assert (d / "oracle" / "solve.sh").exists() and (d / "verifier" / "test.sh").exists()


@pytest.mark.skipif(not HAS_SIM, reason="needs robouse[sim]")
def test_a_remix_passes_the_oracle_and_fails_the_noop(tmp_path) -> None:
    from robouse.components.remix import validate

    d = write("franka-panda", "tabletop", "put-in-container", modifiers({}), 0, tmp_path / "tasks")
    v = validate(d, tmp_path / "runs")
    assert v["oracle"]["reward"] == 1 and v["noop"]["reward"] == 0 and v["accepted"]


def test_every_suite_is_tagged() -> None:
    from robouse.components import catalog as C

    suites = {p.name for p in (Path(__file__).resolve().parents[1] / "tasks").iterdir() if p.is_dir()}
    assert suites <= set(C.SUITES), suites - set(C.SUITES)
    reg = load()
    for s, v in C.SUITES.items():
        assert v["track"] in C.TRACKS and v["scene"] in reg.scenes, s
        assert all(e in reg.embodiments for e in v["embodiments"]), s
        assert all(c in C.CAPABILITIES for c in v["capabilities"]), s
