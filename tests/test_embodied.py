"""robouse backends on BenchFlow's embodied layer: every backend declares a valid embodiment that covers its native
action vector, and the episode server reproduces robouse's protocol-1 behaviour."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from benchflow.embodied.spec import Embodiment

from robouse.backends import make_backend
from robouse.backends.base import ActionSpec
from robouse.tasks import find_tasks

ROOT = Path(__file__).resolve().parents[1] / "tasks"
LOCAL_SUITES = ["arc-style", "hard", "vision", "safety", "robo-use-families", "metaworld", "gymrobotics", "drone",
                "menagerie", "roboharm"]
HAVE_SIM = all(importlib.util.find_spec(m) for m in ("mujoco", "metaworld", "gymnasium_robotics"))


def _tasks():
    for suite in LOCAL_SUITES:
        yield from find_tasks(ROOT / suite)


def _check(backend) -> Embodiment:
    e = backend.embodiment().validate()
    assert e.dim == backend.action_spec.dim
    assert e.flat_names() == list(backend.action_spec.names)
    assert e.flat_low() == [float(x) for x in backend.action_spec.low]
    assert e.flat_high() == [float(x) for x in backend.action_spec.high]
    names = {s.name for s in e.skills} | {a for s in e.skills for a in s.aliases}
    for legacy in backend.skills():  # every protocol-1 skill is still reachable by its old name
        if backend.name != "behavior":
            assert legacy in names, (legacy, names)
    assert Embodiment.from_dict(json.loads(json.dumps(e.to_dict()))).validate().dim == e.dim
    return e


@pytest.mark.skipif(not HAVE_SIM, reason="needs robouse[metaworld,gymrobotics]")
def test_every_local_backend_declares_a_valid_embodiment() -> None:
    kinds = {}
    n = 0
    for t in _tasks():
        b = make_backend(t.spec)
        try:
            kinds.setdefault(_check(b).kind, t.id)
        finally:
            b.close()
        n += 1
    assert n > 100
    assert {"arm", "bimanual", "drone", "other"} <= set(kinds), kinds


def _bare(cls, **attrs):
    b = cls.__new__(cls)
    for k, v in attrs.items():
        setattr(b, k, v)
    return b


@pytest.mark.parametrize("bimanual", [False, True])
def test_dexjoco_hand_embodiment(bimanual: bool) -> None:
    """DexJoCo runs in its own virtualenv; the embodiment only needs the action layout."""
    from robouse.backends.dexjoco import HAND_LIM, POS_LIM, ROT_LIM, DexjocoBackend

    arms = ["R_", "L_"] if bimanual else [""]
    names = [n for a in arms for n in [f"{a}DX", f"{a}DY", f"{a}DZ", f"{a}RX", f"{a}RY", f"{a}RZ"] + [f"{a}F{i}" for i in range(16)]]
    lim = ([POS_LIM] * 3 + [ROT_LIM] * 3 + [HAND_LIM] * 16) * len(arms)
    b = _bare(DexjocoBackend, bimanual=bimanual, camera="front", max_steps=1000,
              action_spec=ActionSpec(names, [-x for x in lim], lim))
    e = _check(b)
    assert e.kind == ("bimanual" if bimanual else "hand")
    joints = [g for g in e.action_groups if g.name.endswith("hand.joints")]
    assert [g.dim for g in joints] == [16] * len(arms)
    assert {s.name for s in e.skills} == {"arm.move_to", "arm.grasp"}


def test_behavior_is_skill_only() -> None:
    from robouse.backends.behavior import BehaviorBackend

    b = _bare(BehaviorBackend, camera="follow", max_steps=60, _skills={},
              action_spec=ActionSpec(["wait"], [0.0], [1.0]))
    e = _check(b)
    assert e.kind == "skill_only" and e.dim == 1
    assert {"navigate_to", "grasp", "toggle_on", "release"} <= {s.name for s in e.skills}
    assert all(s.impl == "backend" for s in e.skills)


@pytest.mark.skipif(not HAVE_SIM, reason="needs robouse[metaworld,gymrobotics]")
def test_bimanual_menagerie_act_by_group(tmp_path) -> None:
    from robouse.embodied import episode_from_spec
    from robouse.tasks import load_task

    ep = episode_from_spec(load_task(ROOT / "menagerie" / "menagerie-aloha-opening-four").spec, tmp_path)
    info = ep.handle({"op": "info"})["result"]
    groups = [g["name"] for g in info["embodiment"]["action_groups"]]
    assert groups == ["left.ee_delta", "left.gripper", "right.ee_delta", "right.gripper"]
    assert info["action"]["names"] == ["L_DX", "L_DY", "L_DZ", "L_GRIP", "R_DX", "R_DY", "R_DZ", "R_GRIP"]
    before = ep.handle({"op": "observe"})["result"]["state"]["left_hand_pos"]
    r = ep.handle({"op": "act", "groups": {"left.ee_delta": [0, 0, 1]}, "repeat": 5})
    assert r["ok"], r
    after = r["result"]["state"]
    assert after["left_hand_pos"][2] > before[2] + 0.02
    ep.handle({"op": "give_up"})
    ep.close()
    rows = [json.loads(x) for x in (tmp_path / "steps.jsonl").read_text().splitlines()]
    assert rows[0]["action"]["right.ee_delta"] == [0.0, 0.0, 0.0]


@pytest.mark.skipif(not HAVE_SIM, reason="needs robouse[metaworld,gymrobotics]")
def test_metaworld_oracle_parity_in_process(tmp_path) -> None:
    """The Meta-World scripted expert through the new server ends exactly as on protocol 1 (step 51)."""
    import numpy as np
    from metaworld.policies import ENV_POLICY_MAP

    from robouse.embodied import episode_from_spec
    from robouse.tasks import load_task

    ep = episode_from_spec(load_task(ROOT / "metaworld" / "metaworld-reach").spec, tmp_path)
    pol = ENV_POLICY_MAP["reach-v3"]()
    for _ in range(450):
        st = ep.handle({"op": "observe"})
        if not st["ok"]:
            break
        a = np.clip(pol.get_action(np.asarray(st["result"]["state"]["obs_vector"])), -1, 1)
        r = ep.handle({"op": "act", "action": [float(x) for x in a]})
        if "episode" in r.get("result", {}):
            break
    assert ep.result["success"] and ep.result["outcome"] == "success_reached" and ep.result["steps_used"] == 51
    ep.close()
