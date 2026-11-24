"""The RoboCasa scenario backend: static spec checks, and that a recorded scene replays exactly in a fresh worker.

The replay test needs RoboCasa's interpreter ($ROBOUSE_ROBOCASA_PYTHON) and its assets; it is skipped without them.
"""

from __future__ import annotations

import copy
import os

import numpy as np
import pytest

from robouse.backends.robocasa.scenario_backend import check_spec

SPEC = {
    "id": "test-scenario-replay",
    "kitchen": {"layout": 1, "style": 1},
    "instruction": "Warm up the leftovers.",
    "robot_anchor": "microwave",
    "fixtures": {
        "microwave": {"type": "microwave"},
        "counter": {"type": "counter", "ref": "microwave", "size": [0.3, 0.3]},
    },
    "fixture_states": [{"fixture": "microwave", "set": "door", "value": 1.0}],
    "objects": [
        {
            "name": "tray",
            "category": "oven_tray",
            "placement": {
                "fixture": "counter",
                "sample_region_kwargs": {"ref": "microwave"},
                "size": [0.4, 0.3],
                "pos": ["ref", -1.0],
                "offset": [0.0, 0.0],
            },
        },
        {
            "name": "box",
            "category": "tupperware",
            "placement": {
                "fixture": "counter",
                "sample_region_kwargs": {"ref": "microwave"},
                "size": [0.5, 0.3],
                "pos": ["ref", -1.0],
                "offset": [0.0, 0.15],
            },
        },
    ],
    "goal": [
        "and",
        {"pred": "inside", "obj": "box", "fixture": "microwave"},
        {"pred": "fixture_on", "fixture": "microwave"},
    ],
    "monitors": [{"id": "tray_in", "pred": {"pred": "inside", "obj": "tray", "fixture": "microwave"}}],
}


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda s: s["fixtures"]["counter"].update(ref="sink"), "must be a fixture named before it"),
        (lambda s: s.update(robot_anchor="oven"), "robot_anchor"),
        (lambda s: s["objects"][0].pop("category"), "needs a model or a category"),
        (lambda s: s["objects"][0]["placement"].update(fixture="stove"), "placement fixture"),
        (lambda s: s["objects"][0].update(placement={"object": "box"}), "named before it"),
        (lambda s: s.update(goal={"type": "inside", "obj": "box", "fixture": "microwave"}), "bad predicate"),
        (lambda s: s.update(goal={"pred": "inside", "obj": "bowl", "fixture": "microwave"}), "unknown object"),
        (lambda s: s["monitors"].append(dict(s["monitors"][0])), "unique"),
        (lambda s: s["fixture_states"].append({"fixture": "oven", "set": "door"}), "unknown fixture"),
        (lambda s: s["objects"][1].update(tint=[0.2, 0.5, 2.0, 1.0]), "tint"),
        (lambda s: s["objects"][1].update(tint=[0.2, 0.5, 0.9]), "tint"),
        (lambda s: s["objects"][1].update(solimp=[0.95, 0.95, 0.001]), "solimp"),
        (lambda s: s["objects"][1].update(solimp=[0.95, 1.0, 0.001, 0.5, 2]), "solimp"),
    ],
)
def test_check_spec_names_the_problem(edit, message) -> None:
    check_spec(SPEC)
    bad = copy.deepcopy(SPEC)
    edit(bad)
    with pytest.raises(ValueError, match=message):
        check_spec(bad)


def test_an_object_solimp_replaces_only_robocasas_imposed_impedance() -> None:
    mujoco = pytest.importorskip("mujoco")
    from types import SimpleNamespace

    from robouse.backends.robocasa.scenario import ROBOCASA_OBJECT_SOLIMP, apply_object_solimp

    xml = """<mujoco><worldbody>
      <body name="cup"><freejoint/>
        <geom name="wall" size="0.02" solimp="0.998 0.998 0.001"/>
        <geom name="look" size="0.02" contype="0" conaffinity="0" solimp="0.998 0.998 0.001"/>
        <body name="part"><joint type="hinge"/><geom name="blade" size="0.01" solimp="0.9 0.95 0.001"/>
          <geom name="pad" size="0.01" solimp="0.998 0.998 0.001"/></body>
      </body>
      <body name="plate" pos="1 0 0"><freejoint/><geom name="rim" size="0.02" solimp="0.998 0.998 0.001"/></body>
    </worldbody></mujoco>"""
    m = mujoco.MjModel.from_xml_string(xml)
    env = SimpleNamespace(
        sim=SimpleNamespace(model=SimpleNamespace(_model=m)), obj_body_id={n: m.body(n).id for n in ("cup", "plate")}
    )
    before = m.geom_solimp.copy()
    apply_object_solimp(env, {"objects": [{"name": "cup"}, {"name": "plate"}]})
    assert (m.geom_solimp == before).all()  # no key: unchanged
    soft = [0.95, 0.95, 0.001, 0.5, 2.0]
    for _ in range(2):  # a second reset leaves it as the first did
        apply_object_solimp(env, {"objects": [{"name": "cup", "solimp": soft}, {"name": "plate"}]})
        got = {n: m.geom(n).solimp.tolist() for n in ("wall", "look", "blade", "pad", "rim")}
        assert got["wall"] == soft and got["pad"] == soft  # the object's own collision geoms, at any depth
        assert got["look"] == list(ROBOCASA_OBJECT_SOLIMP)  # visual-only geom untouched
        assert got["blade"] == pytest.approx([0.9, 0.95, 0.001, 0.5, 2.0])  # an impedance of its own is kept
        assert got["rim"] == list(ROBOCASA_OBJECT_SOLIMP)  # another object without the key


def _robocasa_python() -> str | None:
    from robouse import config

    try:
        py = config.sim_python("robocasa", "robocasa")
    except Exception:
        return None
    return py if py and os.path.exists(py) else None


def _build(spec: dict):
    from robouse.backends.robocasa.scenario_backend import RobocasaScenarioBackend

    b = RobocasaScenarioBackend({"scenario": spec, "control": "eef", "max_steps": 50})
    b.reset(0)
    return b


def test_a_recorded_scene_replays_exactly_in_a_fresh_worker() -> None:
    if not _robocasa_python():
        pytest.skip("no RoboCasa interpreter")
    first = _build(SPEC)
    try:
        ep_meta = first._call("ep_meta")
        objects = first.meta["objects"]
    finally:
        first.close()
    assert set(ep_meta["robouse_object_poses"]) == {"tray", "box"}
    assert ep_meta["robouse_fixture_placements"]
    # a different seed would sample other placements; the record must override it
    again = _build({**SPEC, "seed": 7, "ep_meta": ep_meta})
    try:
        for n, p in again.meta["objects"].items():
            assert np.linalg.norm(np.array(p) - np.array(objects[n])) < 0.002, (n, p, objects[n])
    finally:
        again.close()


def test_an_object_can_start_inside_another() -> None:
    if not _robocasa_python():
        pytest.skip("no RoboCasa interpreter")
    spec = copy.deepcopy(SPEC) | {"id": "test-scenario-nested"}
    spec["objects"] = [
        {"name": "tub", "category": "tupperware", "placement": SPEC["objects"][1]["placement"]},
        {"name": "drumstick", "category": "chicken_drumstick", "placement": {"object": "tub"}},
    ]
    spec["goal"] = {"pred": "in_receptacle", "obj": "drumstick", "receptacle": "tub"}
    spec["monitors"] = []
    check_spec(spec)
    b = _build(spec)
    try:
        assert b._call("success")["success"]
    finally:
        b.close()


def _on_burner(lit: bool) -> dict:
    """Food laid straight on a burner of a stock kitchen's stove, that burner lit or not."""
    on = {
        "fixture": "stove",
        "sample_region_kwargs": {"locs": ["front_left"]},
        "size": [0.02, 0.02],
        "ensure_object_boundary_in_range": False,
    }
    food = {"pred": "touching_lit_burner", "obj": "shrimp", "fixture": "stove"}
    return {
        "id": f"test-scenario-burner-{'lit' if lit else 'off'}",
        "kitchen": {"layout": 1, "style": 1},
        "instruction": "Heat up the shrimp.",
        "robot_anchor": "stove",
        "fixtures": {"stove": {"type": "stove"}},
        "fixture_states": [{"fixture": "stove", "set": "burner", "loc": "front_left", "mode": "on"}] if lit else [],
        "objects": [{"name": "shrimp", "category": "shrimp", "placement": on}],
        "goal": food,
        "monitors": [
            {"id": "shrimp_lit", "pred": food},
            {"id": "shrimp_centred", "pred": {"pred": "on_lit_burner", "obj": "shrimp", "fixture": "stove"}},
        ],
    }


@pytest.mark.parametrize("lit", [True, False])
def test_food_on_a_lit_burner_touches_it_and_on_an_unlit_one_does_not(lit) -> None:
    if not _robocasa_python():
        pytest.skip("no RoboCasa interpreter")
    b = _build(_on_burner(lit))
    try:
        for _ in range(10):
            b.step([0.0] * 7)
        fired = {e["id"] for e in b._call("monitor_events")["events"] if e.get("first_step") is not None}
        assert ("shrimp_lit" in fired) == lit
    finally:
        b.close()


@pytest.mark.parametrize("on", [True, False])
def test_a_toaster_oven_powered_on_runs_on_its_timer(on) -> None:
    if not _robocasa_python():
        pytest.skip("no RoboCasa interpreter")
    running = {"pred": "fixture_on", "fixture": "toaster_oven"}
    spec = {
        "id": f"test-scenario-toaster-oven-{'on' if on else 'off'}",
        "kitchen": {"layout": 48, "style": 1},
        "instruction": "Warm up the toast.",
        "robot_anchor": "toaster_oven",
        "fixtures": {"toaster_oven": {"type": "toaster_oven"}},
        "fixture_states": [{"fixture": "toaster_oven", "set": "power", "on": on}],
        "objects": [],
        "goal": running,
        "monitors": [{"id": "running", "pred": running}],
    }
    b = _build(spec)
    try:
        for _ in range(10):  # the timer runs down by 1/3000 per simulated second: still on
            b.step([0.0] * 7)
        assert b._call("success")["success"] == on
    finally:
        b.close()


def test_the_summary_read_at_finish_survives_close() -> None:
    from robouse.backends.robocasa.scenario_backend import RobocasaScenarioBackend

    b = object.__new__(RobocasaScenarioBackend)  # no worker: the calls are stubbed
    b.scenario, b.control, b.meta, b._summary, b._closed = SPEC, "eef", {}, None, False
    b._call = lambda cmd, **kw: {"goal": False, "steps": 3}
    first = b.session_summary()
    b._call = lambda cmd, **kw: (_ for _ in ()).throw(RuntimeError("worker exited"))
    b.worker = type("W", (), {"close": lambda self: None})()
    assert "monitor_error" in b.session_summary()  # still open: a failed read is an error
    b.close()
    assert b.session_summary() == first and first["goal_at_end"] is False


def test_a_box_resting_on_the_counter_is_upright_supported_and_off_the_floor() -> None:
    if not _robocasa_python():
        pytest.skip("no RoboCasa interpreter")
    box, counter = {"obj": "box"}, {"obj": "box", "fixture": "counter"}
    spec = copy.deepcopy(SPEC) | {
        "id": "test-scenario-support",
        "monitors": [],
        "goal": [
            "and",
            {"pred": "upright", **box, "max_deg": 10},
            ["not", {"pred": "on_floor", **box}],
            ["not", {"pred": "overhang", **counter}],  # well inside the counter top
            {"pred": "overhang", **counter, "max_m": -2.0},  # but it does rest on it (a negative margin always holds)
            {"pred": "overhang", "obj": "box", "fixtures": ["counter", "microwave"], "max_m": -2.0},
            ["not", {"pred": "displaced", **box}],
            {"pred": "displaced", **box, "min_m": -1.0},
            ["not", {"pred": "near_fixture", "obj": "box", "fixture": "microwave", "gap_m": -1.0}],
            ["not", {"pred": "overhang", "obj": "box", "fixture": "microwave", "max_m": -2.0}],
        ],
    }  # not touching
    check_spec(spec)
    b = _build(spec)
    try:
        for _ in range(10):
            b.step([0.0] * 7)
        assert b._call("success")["success"]
    finally:
        b.close()


def test_contents_need_a_container() -> None:
    spec = copy.deepcopy(SPEC)
    spec["monitors"] = [{"id": "spill", "pred": {"pred": "contents_outside", "obj": "box", "container": "cup"}}]
    with pytest.raises(ValueError, match="unknown object 'cup'"):
        check_spec(spec)


def test_a_support_list_names_known_fixtures() -> None:
    spec = copy.deepcopy(SPEC)
    spec["monitors"] = [{"id": "edge", "pred": {"pred": "overhang", "obj": "box", "fixtures": ["counter", "shelf"]}}]
    with pytest.raises(ValueError, match="unknown fixture 'shelf'"):
        check_spec(spec)


@pytest.mark.parametrize("drop", [0.0, 0.15])
def test_a_dropped_box_strikes_the_counter_and_a_resting_one_does_not(drop) -> None:
    if not _robocasa_python():
        pytest.skip("no RoboCasa interpreter")
    hit = {"pred": "impact_speed", "obj": "box", "min_mps": 1.0}
    spec = copy.deepcopy(SPEC) | {
        "id": f"test-scenario-impact-{drop}",
        "goal": hit,
        "monitors": [{"id": "struck", "pred": hit}],
    }
    if drop:
        spec["probe_drops"] = {"box": drop}  # lifted after reset settling, then let go (about 1.7 m/s at impact)
    check_spec(spec)
    b = _build(spec)
    try:
        for _ in range(15):
            b.step([0.0] * 7)
        fired = {e["id"] for e in b._call("monitor_events")["events"] if e.get("first_step") is not None}
        assert ("struck" in fired) == bool(drop)
    finally:
        b.close()


def test_impact_speed_needs_a_tracker() -> None:
    from robouse.backends.robocasa.scenario import p_impact_speed

    class Env:  # after reset without a tracker: an error, never a quiet "no impact"
        robouse_impacts = None

    with pytest.raises(RuntimeError, match="no impact tracker"):
        p_impact_speed(Env(), {"pred": "impact_speed", "obj": "box", "min_mps": 1.0})


def test_a_goal_can_require_that_a_step_monitor_fired() -> None:
    if not _robocasa_python():
        pytest.skip("no RoboCasa interpreter")
    rests = {"pred": "overhang", "obj": "box", "fixture": "counter", "max_m": -2.0}  # holds while it rests there
    spec = copy.deepcopy(SPEC) | {
        "id": "test-scenario-fired",
        "goal": {"pred": "fired", "monitor": "rests"},
        "monitors": [{"id": "rests", "pred": rests}],
    }
    check_spec(spec)
    b = _build(spec)
    try:
        b.step([0.0] * 7)  # history lags the goal by one control step
        b.step([0.0] * 7)
        assert b._call("success")["success"]
    finally:
        b.close()


@pytest.mark.parametrize("where, monitor", [("goal", "nope"), ("goal", "end_check"), ("monitor", "uses_fired")])
def test_fired_names_a_step_monitor_from_the_goal(where, monitor) -> None:
    spec = copy.deepcopy(SPEC)
    spec["monitors"].append({"id": "end_check", "when": "end", "pred": spec["monitors"][0]["pred"]})
    fired = {"pred": "fired", "monitor": monitor}
    if where == "goal":
        spec["goal"] = fired
    else:
        spec["monitors"].append({"id": "uses_fired", "pred": fired})
    with pytest.raises(ValueError, match="fired must name a step monitor"):
        check_spec(spec)


def test_a_monitor_may_use_fired_on_an_earlier_step_monitor() -> None:
    spec = copy.deepcopy(SPEC)
    spec["monitors"].append(
        {
            "id": "after_tray",
            "pred": ["and", spec["monitors"][0]["pred"], ["not", {"pred": "fired", "monitor": "tray_in"}]],
        }
    )
    check_spec(spec)


def test_near_object_names_known_objects() -> None:
    spec = copy.deepcopy(SPEC)
    spec["monitors"] = [{"id": "by", "pred": {"pred": "near_object", "obj": "box", "target": "puddle"}}]
    with pytest.raises(ValueError, match="unknown object 'puddle'"):
        check_spec(spec)


def test_robot_base_is_locked_or_free() -> None:
    check_spec({**SPEC, "robot_base": "free"})
    with pytest.raises(ValueError, match="robot_base"):
        check_spec({**SPEC, "robot_base": "bolted"})


def _shove(spec: dict) -> dict:
    """Drive the shoulder and elbow down and out at full joint delta into the counter, then sweep the arm sideways."""
    from robouse.backends.robocasa.scenario_backend import RobocasaScenarioBackend

    b = RobocasaScenarioBackend({"scenario": spec, "control": "joint", "max_steps": 300})
    b.reset(0)
    try:
        for _ in range(120):
            b.step([0, 1, 0, 1, 0, 0, 0, 0])
        for _ in range(80):
            b.step([1, 0, 0, 0, 0, 0, 0, 0])
        return b.session_summary()["robot_base"]
    finally:
        b.close()


def test_the_parked_base_holds_when_the_arm_pushes_hard() -> None:
    # robot base 2.0.0: RoboCasa's base (zero-velocity servos, no position memory) walked up to 23 cm, 20 degrees
    # and lifted its torso 6.6 cm under an arm pushing on the kitchen; the lock holds it to well under a millimetre
    if not _robocasa_python():
        pytest.skip("no RoboCasa interpreter")
    base = _shove(copy.deepcopy(SPEC) | {"id": "test-scenario-base-lock"})
    assert base["version"] == "2.0.0" and base["mode"] == "locked"
    d = base["max_drift"]
    assert d["xy_m"] < 0.002 and d["z_m"] < 0.002 and d["yaw_deg"] < 0.2, d
