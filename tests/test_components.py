"""Components and composed tasks: the manifests match the runtime, the resolver explains incompatibilities, composed
tasks are normal task folders, and the `robouse tasks` / `robouse components` commands (init, grid, check, --from, the
pre-rename keys and the `remix` alias) work end to end."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from robouse.components.compose import ComposeError, instantiate, task_id, write
from robouse.components.registry import components_root, export, load
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
    emb = reg.composable("embodiments")
    assert {"franka-panda", "aloha-2", "pal-tiago", "unitree-go2", "crazyflie-2"} <= set(emb)
    kinds = {reg.embodiments[e]["kind"] for e in emb}
    assert {"arm", "bimanual", "mobile_manipulator", "quadruped", "drone"} <= kinds
    assert len(reg.composable("scenes")) >= 4 and len(reg.composable("tasks")) >= 8
    caps = {c for t in reg.composable("tasks") for c in reg.tasks[t]["capabilities"]}
    assert {"spatial-reasoning", "topological-reasoning", "contact-rich", "long-horizon", "perception"} <= caps
    assert set(reg.modifiers["safety"]["values"]) == {"none", "direct", "indirect", "privacy"}


@pytest.mark.parametrize(
    "emb,scene,task,why",
    [
        ("franka-panda", "outdoor-field", "put-in-container", "surface mount"),
        ("unitree-go2", "tabletop", "put-in-container", "capabilities"),
        ("crazyflie-2", "kitchen-counter", "stack-in-order", "placement"),
        ("franka-panda", "tabletop", "bimanual-relay", "bimanual"),
        ("pal-tiago", "tabletop", "fetch-and-deliver", "task needs 2"),
        ("franka-panda", "tabletop", "floating-gripper", None),
    ],
)
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
    with pytest.raises(ComposeError):
        instantiate("unitree-go2", "tabletop", "stack-in-order", m, 0)


def test_compose_writes_a_normal_task_folder(tmp_path) -> None:
    mods = modifiers({"safety": "privacy"})
    d = write("franka-panda", "kitchen-counter", "put-in-container", mods, 2, tmp_path)
    assert d.name == task_id("franka-panda", "kitchen-counter", "put-in-container", mods, 2)
    t = load_task(d)
    rb = t.meta["robouse"]
    assert rb["backend"] == "components" and "remix" not in rb
    ins = rb["instance"]
    assert ins["embodiment"] == {"id": "franka-panda", "version": "0.1.0"} and ins["seed"] == 2
    assert ins["modifiers"]["safety"] == "privacy" and ins["layout"]["overlay"]["level"] == "privacy"
    assert "PIN" in t.body and "safety-judgement" in t.meta["metadata"]["capabilities"]
    assert t.meta["metadata"]["suite"] == "composed"
    assert (d / "oracle" / "solve.sh").exists() and (d / "verifier" / "test.sh").exists()


def _cli(argv, capsys):
    from robouse.cli import main

    code = main(argv)
    return code, capsys.readouterr()


def test_components_check_explains(capsys) -> None:
    code, out = _cli(["components", "check", "unitree-go2", "tabletop", "put-in-container"], capsys)
    assert code == 1 and "incompatible" in out.out and "needs capabilities reach, grasp" in out.out
    code, out = _cli(
        ["components", "check", "franka-panda", "tabletop", "put-in-container", "--perturb", "push"], capsys
    )
    assert code == 0 and out.out.startswith("compatible")


def test_tasks_lists_with_and_without_the_verb(capsys) -> None:
    root = Path(__file__).resolve().parents[1] / "tasks" / "composed"
    a = _cli(["tasks", str(root)], capsys)[1].out
    b = _cli(["tasks", "list", str(root)], capsys)[1].out
    assert a == b and "components" in a


def test_init_scaffolds_a_blank_task_that_check_rejects(tmp_path, capsys) -> None:
    code, out = _cli(["tasks", "init", str(tmp_path / "mine")], capsys)
    assert (
        code == 0 and (tmp_path / "mine" / "task.md").exists() and (tmp_path / "mine" / "oracle" / "solve.sh").exists()
    )
    code, out = _cli(["tasks", "check", str(tmp_path / "mine"), "--no-run"], capsys)
    assert code == 1 and "[REPLACE" in out.out


def test_init_refuses_several_values_without_grid(tmp_path, capsys) -> None:
    code, out = _cli(
        [
            "tasks",
            "init",
            "--embodiment",
            "franka-panda,aloha-2",
            "--scene",
            "tabletop",
            "--task",
            "put-in-container",
            "--out",
            str(tmp_path),
        ],
        capsys,
    )
    assert code == 2 and "--grid" in out.err


def test_grid_reports_accepted_and_rejected(tmp_path, capsys) -> None:
    code, out = _cli(
        [
            "tasks",
            "init",
            "--grid",
            "--no-validate",
            "--embodiment",
            "franka-panda,unitree-go2",
            "--scene",
            "tabletop",
            "--task",
            "put-in-container,go-to-landmark",
            "--out",
            str(tmp_path),
        ],
        capsys,
    )
    assert code == 0 and "2 accepted, 2 rejected, of 4 combinations" in out.out and out.out.count("rejected ") == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "go-to-landmark--unitree-go2--tabletop--s0",
        "put-in-container--franka-panda--tabletop--s0",
    ]


def test_from_regenerates_the_recorded_instance(tmp_path, capsys) -> None:
    d = write("aloha-2", "workshop-bench", "stack-in-order", modifiers({"obs": "noisy"}), 4, tmp_path / "a")
    code, out = _cli(["tasks", "init", "--from", str(d), "--out", str(tmp_path / "b"), "--no-validate"], capsys)
    assert code == 0 and "same layout as recorded" in out.out
    assert yaml.safe_load((tmp_path / "b" / d.name / "task.md").read_text().split("---")[1]) == yaml.safe_load(
        (d / "task.md").read_text().split("---")[1]
    )
    # a recorded version that differs from the installed one needs --upgrade
    text = (d / "task.md").read_text().replace("version: 0.1.0", "version: 0.0.9", 1)
    (d / "task.md").write_text(text)
    code, out = _cli(["tasks", "init", "--from", str(d), "--out", str(tmp_path / "c"), "--no-validate"], capsys)
    assert code == 1 and "--upgrade" in out.err
    code, out = _cli(
        ["tasks", "init", "--from", str(d), "--out", str(tmp_path / "c"), "--no-validate", "--upgrade"], capsys
    )
    assert code == 0


def test_pre_rename_keys_load_with_a_warning(tmp_path) -> None:
    from robouse.backends.components.backend import read_block

    d = write("franka-panda", "tabletop", "put-in-container", modifiers({}), 1, tmp_path)
    spec = load_task(d).spec
    ins = spec.pop("instance")
    legacy = {
        **spec,
        "backend": "remix",
        "components": {k: f"{ins[k]['id']}@{ins[k]['version']}" for k in ("embodiment", "scene", "task")},
        "remix": {
            "embodiment": "franka-panda",
            "scene": "tabletop",
            "task": "put-in-container",
            "seed": 1,
            "modifiers": ins["modifiers"],
            "instance": ins["layout"],
        },
    }
    with pytest.warns(DeprecationWarning, match="pre-rename"):
        rec = read_block(legacy)
    assert (
        rec["embodiment"] == "franka-panda" and rec["instance"] == ins["layout"] and rec["versions"]["task"] == "0.1.0"
    )


def test_remix_alias_prints_the_new_name(tmp_path, capsys) -> None:
    code, out = _cli(
        ["remix", "--embodiment", "unitree-go2", "--scene", "tabletop", "--task", "put-in-container", "--check"], capsys
    )
    assert code == 1 and "renamed to `robouse tasks init`" in out.err and "incompatible" in out.out
    code, out = _cli(
        [
            "remix",
            "--embodiment",
            "franka-panda",
            "--scene",
            "tabletop",
            "--task",
            "put-in-container",
            "--out",
            str(tmp_path),
            "--no-validate",
        ],
        capsys,
    )
    assert code == 0 and (tmp_path / "put-in-container--franka-panda--tabletop--s0" / "task.md").exists()


@pytest.mark.skipif(not HAS_SIM, reason="needs robouse[sim]")
def test_init_and_check_run_the_reference_and_the_noop(tmp_path, capsys) -> None:
    code, out = _cli(
        [
            "tasks",
            "init",
            "--embodiment",
            "franka-panda",
            "--scene",
            "tabletop",
            "--task",
            "put-in-container",
            "--out",
            str(tmp_path),
        ],
        capsys,
    )
    assert code == 0 and "accepted: reference solution 1, no-op control 0" in out.out
    d = tmp_path / "put-in-container--franka-panda--tabletop--s0"
    code, out = _cli(["tasks", "check", str(d)], capsys)
    assert code == 0 and "reference solution: reward 1.0" in out.out and "no-op control: reward 0.0" in out.out
    assert out.out.rstrip().endswith("valid")


def test_every_suite_is_tagged() -> None:
    from robouse.components import catalog as C

    suites = {p.name for p in (Path(__file__).resolve().parents[1] / "tasks").iterdir() if p.is_dir()}
    assert suites <= set(C.SUITES), suites - set(C.SUITES)
    reg = load()
    for s, v in C.SUITES.items():
        assert v["track"] in C.TRACKS and v["scene"] in reg.scenes, s
        assert all(e in reg.embodiments for e in v["embodiments"]), s
        assert all(c in C.CAPABILITIES for c in v["capabilities"]), s
