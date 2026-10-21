"""The one-demo suite (tasks/one-demo/): in-context imitation of one demonstration, on another object.

The task folders match the families in src/robouse/backends/tabletop/onedemo.py, as adapters/one-demo/generate.py
writes them. On every task the reference strategy scores 1, while the no-op control and the demonstration's own
commands, replayed verbatim or shifted to the task object's contact point, score 0. Wrong endings that look close score 0,
a full bottle cannot be lifted by its cap, the trace's commands are `robo` command lines, and the frames render. The
episodes run in the episode server's request handler, in process and without the video, so they need no OpenGL; only
the frames test renders.
"""

from __future__ import annotations

import importlib.util
import json
import shlex
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("mujoco")

from robouse.agent_cli import build_request
from robouse.backends.tabletop import onedemo as OD
from robouse.core.session import Episode
from robouse.tasks import find_tasks

ROOT = Path(__file__).resolve().parents[1]
TASKS = {t.id: t for t in find_tasks(ROOT / "tasks" / "one-demo")}
_spec = importlib.util.spec_from_file_location("one_demo_generate", ROOT / "adapters" / "one-demo" / "generate.py")
assert _spec and _spec.loader
GEN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GEN)


class Unrecorded(Episode):
    def _record_frame(self, force: bool = False) -> None:  # no video: these tests need no OpenGL
        pass


def episode(tmp_path: Path, scenario: dict, name: str = "run") -> Episode:
    spec = {"id": scenario.get("id", "t"), "backend": "tabletop", "scenario": scenario, "max_steps": 900}
    return Unrecorded(spec, tmp_path / name)


def verdict(tmp_path: Path, scenario: dict, drive: Callable[[Callable[[dict], dict]], None], name: str = "run") -> dict:
    ep = episode(tmp_path, scenario, name)
    drive(ep.handle)
    if not ep.finished:
        ep.handle({"op": "done", "text": ""})
    ep.close()
    return ep.result


def demo_scenario(task) -> dict:
    d = task.spec["scenario"]["demo"]
    return {"id": "demo", "objects": d["objects"], "fixtures": d["fixtures"], "goals": [], "max_steps": 900}


def test_the_task_folders_are_the_families() -> None:
    assert set(TASKS) == set(OD.ONE_DEMO_TASKS) and len(TASKS) == 16
    for tid, task in TASKS.items():
        sc, want = task.spec["scenario"], OD.ONE_DEMO_TASKS[tid]
        assert {k: sc[k] for k in ("objects", "fixtures", "goals", "family")} == json.loads(
            json.dumps({k: want[k] for k in ("objects", "fixtures", "goals", "family")})
        ), f"{tid}: regenerate with adapters/one-demo/generate.py"
        assert f"--backend tabletop_onedemo --env {tid}" in task.oracle_script.read_text()
        demo = sc["demo"]
        assert demo["fixtures"] != sc["fixtures"] or demo["objects"] != sc["objects"]
        n = len(demo["frames"])
        assert 3 <= n <= 6 and f"observations/demo_{n}.png" in task.instruction
        assert task.instruction.count("  # command ") == len(demo["commands"])


@pytest.mark.parametrize("tid", sorted(OD.ONE_DEMO_TASKS))
def test_reference_one_noop_zero_and_copying_the_numbers_zero(tmp_path, tid) -> None:
    task = TASKS[tid]
    sc, family = task.spec["scenario"], task.spec["scenario"]["family"]
    commands = sc["demo"]["commands"]
    assert verdict(tmp_path, sc, lambda send: OD.run_strategy(family, send), "oracle")["success"]
    assert not verdict(tmp_path, sc, lambda send: None, "noop")["success"]
    assert not verdict(tmp_path, sc, GEN.replay(commands), "copy")["success"]
    shift = GEN.contact(sc, family, tmp_path) - GEN.contact(demo_scenario(task), family, tmp_path)
    assert np.linalg.norm(shift) > 0.02
    assert not verdict(tmp_path, sc, GEN.replay(commands, shift), "shifted")["success"]


def test_each_demonstration_replays_to_its_goal(tmp_path) -> None:
    """The demonstration's recorded commands, run again on its own scene, reach the family's goal."""
    for family, fam in OD.FAMILIES.items():
        task = TASKS[next(iter(fam["targets"]))]
        sc = {**demo_scenario(task), "goals": OD.goals_for(family, fam["demo"])}
        assert verdict(tmp_path, sc, GEN.replay(task.spec["scenario"]["demo"]["commands"]), family)["success"], family


def _bot(send: Callable[[dict], dict]) -> OD.Bot:
    return OD.Bot(send)


def test_endings_that_look_close_score_zero(tmp_path) -> None:
    sc = OD.ONE_DEMO_TASKS

    def box(end_deg: int, release: bool) -> Callable:
        def drive(send):
            bot = _bot(send)
            f = bot.obs()["fixtures"]["box"]
            knob, hinge = np.array(f["knob_pos"]), np.array(f["hinge_pos"])
            bot.move(knob + [0, 0, 0.07], OD.OPEN)
            bot.move(knob, OD.OPEN, tol=0.003)
            bot.grip(1.0)
            for deg in range(15, end_deg + 1, 15):
                bot.move(OD._arc(knob, hinge, deg), 1.0)
            if release:
                bot.grip(OD.OPEN, 12)
                h = np.array(bot.obs()["hand_pos"])
                away = -0.05 if f["hinge_side"] == "left" else 0.05
                bot.move(h + [away, 0, 0], OD.OPEN)
                bot.move(h + [away, 0, 0.08], OD.OPEN)

        return drive

    # a lid let go short of upright falls shut; a lid held open past upright is not resting open
    assert not verdict(tmp_path, sc["one-demo-box-tall"], box(75, True), "box75")["success"]
    assert not verdict(tmp_path, sc["one-demo-box-tall"], box(105, False), "held")["success"]
    assert verdict(tmp_path, sc["one-demo-box-tall"], box(105, True), "box105")["success"]

    def drawer(fraction: float, lift: bool) -> Callable:
        def drive(send):
            bot = _bot(send)
            f = bot.obs()["fixtures"]["cabinet"]
            u, bar = np.array(f["pull_direction"]), np.array(f["handle_pos"])
            hook = bar - u * (0.005 + f["handle_gap"] / 2)
            bot.move(hook + [0, 0, 0.08], 1.0)
            bot.move(hook, 1.0, tol=0.003)
            bot.move(hook + u * f["max_opening"] * fraction, 1.0)
            if lift:
                bot.move(hook + u * f["max_opening"] * fraction + [0, 0, 0.08], 1.0)

        return drive

    # half open, or open with the fingers still pulling on the handle against the drawer's stop
    assert not verdict(tmp_path, sc["one-demo-drawer-left"], drawer(0.5, True), "half")["success"]
    assert not verdict(tmp_path, sc["one-demo-drawer-left"], drawer(1.3, False), "hooked")["success"]
    assert verdict(tmp_path, sc["one-demo-drawer-left"], drawer(1.05, True), "open")["success"]

    def lid(dx: float) -> Callable:
        def drive(send):
            bot = _bot(send)
            st = bot.obs()
            knob, pad = np.array(st["objects"]["lid"]["knob_pos"]), np.array(st["fixtures"]["rest"]["pos"])
            bot.move(knob + [0, 0, 0.07], OD.OPEN)
            bot.move(knob, OD.OPEN, tol=0.003)
            bot.grip(1.0)
            bot.move(knob + [0, 0, 0.05], 1.0)
            above = [pad[0] + dx, pad[1], knob[2] + 0.05]
            bot.move(above, 1.0)
            bot.move([above[0], above[1], knob[2] - st["objects"]["lid"]["pos"][2] + 0.025], 1.0, tol=0.003)
            bot.grip(OD.OPEN, 12)

        return drive

    # set down beside the pad
    assert not verdict(tmp_path, sc["one-demo-lid-pot"], lid(0.12), "beside")["success"]
    assert verdict(tmp_path, sc["one-demo-lid-pot"], lid(0.0), "on")["success"]


def test_a_full_bottle_tips_up_but_cannot_be_lifted_by_its_cap(tmp_path) -> None:
    """Lifted by its cap, a light bottle would hang straight down and could be set on its base without the
    demonstrated tip-up; a full one slips out of the fingers and stays lying."""

    def hang(send):
        bot = _bot(send)
        o = bot.obs()["objects"]["bottle"]
        cap = np.array(o["cap_pos"])
        bot.move(cap + [0, 0, 0.07], OD.OPEN)
        bot.move(cap, OD.OPEN, tol=0.003)
        bot.grip(1.0)
        bot.move(cap + [0, 0, o["size"][2] + 0.03], 1.0)
        o = bot.obs()["objects"]["bottle"]
        h = np.array(bot.obs()["hand_pos"])
        bot.move(h - [0, 0, o["base_pos"][2] - 0.003], 1.0)  # lower it until its base would touch the table
        bot.grip(OD.OPEN, 12)

    for tid in OD.FAMILIES["upright-bottle"]["targets"]:
        ep = episode(tmp_path, OD.ONE_DEMO_TASKS[tid], tid)
        hang(ep.handle)
        tilt = ep.handle({"op": "observe"})["result"]["state"]["objects"]["bottle"]["tilt_deg"]
        ep.handle({"op": "done", "text": ""})
        ep.close()
        assert not ep.result["success"] and tilt > 60, (tid, tilt)


def test_released_is_refused_on_a_drawer_that_is_not_a_cabinet() -> None:
    """`released` on a drawer goal checks that the gripper has let go of a cabinet's drawer. The older `drawer` fixture
    has no such part, so there the option would silently do nothing: the backend refuses it instead."""
    from robouse.backends.tabletop.backend import TabletopBackend

    drawer = {"name": "drawer", "kind": "drawer", "pos": [0.15, 0.17], "color": "darkgrey", "open": 0.0}
    goal = {"type": "drawer", "drawer": "drawer", "min_open": 0.05, "released": True}
    sc = {"id": "t", "objects": [], "fixtures": [drawer], "goals": [goal], "max_steps": 100}
    with pytest.raises(ValueError, match="released"):
        TabletopBackend({"id": "t", "scenario": sc})
    del goal["released"]
    TabletopBackend({"id": "t", "scenario": sc}).close()


def test_observations_start_closed_lying_and_on() -> None:
    from robouse.backends.tabletop.backend import TabletopBackend

    for tid, sc in OD.ONE_DEMO_TASKS.items():
        b = TabletopBackend({"id": tid, "scenario": sc})
        b.reset(0)
        st = json.loads(json.dumps(b.observe()))
        family = sc["family"]
        group, name, field = OD.FAMILIES[family]["contact"]
        assert len(st[group][name][field]) == 3
        if family == "open-box":
            assert st["fixtures"]["box"]["lid_angle_deg"] == 0.0 and st["fixtures"]["box"]["gripper_touching"] is False
        elif family == "open-drawer":
            assert st["fixtures"]["cabinet"]["opening"] == 0.0
        elif family == "upright-bottle":
            assert st["objects"]["bottle"]["tilt_deg"] > 89
        else:
            assert st["objects"]["lid"]["pos"][2] > 0.03  # on its container
        assert not b.success()
        b.close()


def test_the_trace_is_robo_command_lines() -> None:
    """Each command line in an instruction's trace is what `robo` would send as the demonstration's request."""
    for task in TASKS.values():
        for req in task.spec["scenario"]["demo"]["commands"]:
            words = shlex.split(GEN.cli(req))
            assert words[0] == "robo"
            back = build_request(words[1], words[2:])
            assert {k: back[k] for k in req} == req


def test_the_frames_render_and_check_their_scene() -> None:
    from robouse.backends.tabletop.backend import TabletopBackend, demo_frames
    from robouse.core import gl

    if why := gl.probe():
        pytest.skip(f"MuJoCo cannot render offscreen here ({why})")
    task = TASKS["one-demo-drawer-left"]
    b = TabletopBackend(task.spec)
    b.reset(0)
    imgs = b.workspace_images()
    b.close()
    demo = task.spec["scenario"]["demo"]
    assert sorted(imgs) == [f"demo_{i}.png" for i in range(1, len(demo["frames"]) + 1)]
    assert all(img.ndim == 3 and img.shape[2] == 3 and img.dtype == np.uint8 for img in imgs.values())
    broken = {**demo, "frames": [{**demo["frames"][0], "qpos": demo["frames"][0]["qpos"][:-1]}]}
    with pytest.raises(ValueError, match="positions"):
        demo_frames(broken)
