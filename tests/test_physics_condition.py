"""Fail-closed condition receipts, common reset path and private broker boundary."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from robouse.backends.robocasa import physics_condition as C


def receipt():
    return C.seal(
        {
            "requirement": {**C.RELEASE, "scene_id": "test", "scene_version": "2.0.0"},
            "engine": {"library": "4.0.0", "bindings": "4.0.0"},
            **{k: {} for k in ("sources", "packages", "compiled", "renderer", "liquid", "controller", "reset")},
            "default_pins": [],
        }
    )


def test_receipt_is_canonical_and_detects_tampering(tmp_path):
    r = receipt()
    assert C.validate(json.loads(json.dumps(r))) == r
    path = tmp_path / C.FILENAME
    with pytest.raises(ValueError, match="cannot resume"):
        C.record_or_check(path, r, must_exist=True)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: C.record_or_check(path, r), range(12)))
    C.record_or_check(path, r, must_exist=True)
    changed = copy.deepcopy(r)
    changed["payload"]["renderer"] = {"version": "different"}
    with pytest.raises(ValueError, match="digest"):
        C.validate(changed)
    changed = C.seal(changed["payload"])
    with pytest.raises(ValueError, match="changed"):
        C.record_or_check(path, changed)
    assert json.loads(path.read_text()) == r
    path.write_text("{")
    with pytest.raises(ValueError):
        C.record_or_check(path, r)


@pytest.mark.parametrize(
    "field", ["engine", "sources", "packages", "compiled", "renderer", "liquid", "controller", "reset", "default_pins"]
)
def test_changed_conditions_cannot_resume(tmp_path, field):
    r = receipt()
    C.record_or_check(tmp_path / C.FILENAME, r)
    r["payload"][field] = {"library": "3.3.1", "bindings": "3.3.1"} if field == "engine" else {"changed": True}
    with pytest.raises(ValueError):
        C.record_or_check(tmp_path / C.FILENAME, C.seal(r["payload"]))


def test_resource_identity_does_not_depend_on_installation(tmp_path):
    a, b = tmp_path / "one", tmp_path / "two"
    a.write_bytes(b"same resource")
    b.write_bytes(a.read_bytes())
    assert C.portable({"path": str(a)}) == C.portable({"path": str(b)})
    b.write_bytes(b"different resource")
    assert C.portable(str(a)) != C.portable(str(b))


@pytest.mark.parametrize("mode", ["eef", "joint", "text"])
def test_every_reset_checks_shared_receipt_before_observation(tmp_path, monkeypatch, mode):
    from robouse.backends.robocasa.scenario_backend import RobocasaScenarioBackend

    # Exercise the real backend.reset used by direct, Text, program practice and final servers.
    backend = object.__new__(RobocasaScenarioBackend)
    backend.scenario = {"id": "test", "seed": 7}
    backend.control, backend.settle_steps, backend.render_size = mode, 60, (640, 480)
    backend._run_dir = tmp_path / "episode"
    backend.condition_requirement = receipt()["payload"]["requirement"]
    backend.condition = None
    calls = []
    actual = receipt()

    def call(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return actual if cmd == "physics_condition" else {}

    backend._call = call
    backend._start_trace = lambda: calls.append(("trace", {}))
    monkeypatch.setenv("ROBOUSE_PHYSICS_CONDITION_FILE", str(tmp_path / "group.json"))
    backend.reset(0)
    assert [c[0] for c in calls] == ["make_scenario", "joint_limits", "physics_condition", "trace"]
    assert calls[2][1]["reset"] == {"seed": 7, "settle_steps": 60}
    # Practice and final episodes are independent backend instances, sharing the group receipt.
    backend.condition = None
    actual = C.seal({**actual["payload"], "compiled": {"mass": "changed"}})
    with pytest.raises(ValueError, match="changed"):
        backend.reset(0)
    assert "physics_condition" not in backend.info_extra()


def test_practice_broker_denies_private_condition_files(tmp_path):
    from robouse.harnesses.aspire.broker import PracticeBroker
    from robouse.harnesses.program import ProgramBroker

    ep = SimpleNamespace(run_dir=tmp_path)
    for name in (C.FILENAME, C.FILENAME + ".lock", "public.txt"):
        (tmp_path / name).write_text("private" if name != "public.txt" else "public")
    for cls in (PracticeBroker, ProgramBroker):
        broker = object.__new__(cls)
        broker.episodes = {"test": ep}
        assert C.FILENAME not in broker.files(ep)
        assert broker.file("test", C.FILENAME)[0] == 404
        assert broker.file("test", C.FILENAME + ".lock")[0] == 404


def test_receipt_path_is_removed_from_policy_environment():
    from robouse.runner.trial import agent_env

    assert agent_env(
        {
            "ROBOUSE_PHYSICS_CONDITION_FILE": "/private/run/physics-condition.json",
            "ROBOUSE_PHYSICS_CONDITION_RESUME": "1",
            "KEEP": "yes",
        }
    ) == {"KEEP": "yes"}
