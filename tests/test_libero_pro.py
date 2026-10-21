"""The libero-pro suite: its task folders are ASPIRE's 80 LIBERO-Pro pairs (or listed as left out), carry LIBERO-PRO's own
scene, instruction and start states, and hide what LIBERO-PRO hides; the LIBERO backend picks start states as ASPIRE's
saved mode does and loads init files without running code from them; and the scripted reference solution's control works
on a kinematic stand-in for the arm (no LIBERO or MuJoCo needed: the end-to-end checks are `robouse tasks check` in a
LIBERO environment, docs/suites/libero-pro.md)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import pickle
import re
import zipfile
from pathlib import Path

import numpy as np
import pytest

from robouse.backends.libero import backend as lb
from robouse.backends.libero.solver import (
    R_DOWN,
    Done,
    Solver,
    down,
    facing,
    mat2axisangle,
    quat2mat,
    yaw_for,
    yaw_of,
)
from robouse.tasks import find_tasks

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "tasks" / "libero-pro"
TASKS = find_tasks(SUITE) if SUITE.is_dir() else []
_spec = importlib.util.spec_from_file_location("libero_pro_generate", ROOT / "adapters" / "libero-pro" / "generate.py")
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _words(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


# ---- the task folders ----------------------------------------------------------------------------------------------
def test_the_suite_is_aspires_eighty_pairs() -> None:
    """Every one of ASPIRE's 80 required (suite, task) pairs is a task, or is listed as left out with a reason."""
    aspire = {
        f"libero_{f}_{v}:{k}" for f in ("goal", "object", "spatial", "10") for v in ("swap", "task") for k in range(10)
    }
    assert {f"{gen.suite_of(f, v)}:{k}" for f, v, k in gen.PAIRS} == aspire
    have = {t.metadata["aspire_task_ref"] for t in TASKS}
    assert have <= aspire
    assert have | set(gen.LEFT_OUT) == aspire and not have & set(gen.LEFT_OUT)
    assert all(why for why in gen.LEFT_OUT.values())
    assert {t.id for t in TASKS} == {gen.task_id(*p) for p in gen.PAIRS if f"{gen.suite_of(*p[:2])}:{p[2]}" in have}


@pytest.mark.parametrize("t", TASKS, ids=lambda t: t.id)
def test_the_task_carries_libero_pros_scene_and_start(t) -> None:
    s = t.spec
    assert s["backend"] == "libero" and s["suite"] == t.metadata["libero_pro_suite"]
    assert s["env"] == t.metadata["aspire_task_ref"] == f"{s['suite']}:{s['task_index']}"
    assert s["success_mode"] == "first" and s["max_steps"] == 1000 and s["settle_steps"] == 10
    assert s["seed"] == 1 and s["init_mode"] == "saved" and s["init_index"] == 0
    ref = s["init_states"]
    assert ref["url"].startswith(f"https://raw.githubusercontent.com/uynitsuj/LIBERO-PRO/{gen.COMMIT}/")
    assert ref["url"].endswith(f"/{s['suite']}/{Path(t.metadata['source_task']).stem}.pruned_init")
    assert re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) and ref["count"] >= 1
    assert len(s["init_state"]) > 9 and all(isinstance(x, float) for x in s["init_state"])
    assert "(:goal" in s["bddl"] and "(:language" in s["bddl"]
    assert t.metadata["language_instruction"] == lb.bddl_language(s["bddl"])
    plan = json.loads((t.path / "oracle" / "plan.json").read_text())
    assert isinstance(plan, dict)
    assert "--backend libero_scripted" in (t.path / "oracle" / "solve.sh").read_text()


@pytest.mark.parametrize("t", TASKS, ids=lambda t: t.id)
def test_the_prompt_gives_the_instruction_and_hides_the_scene(t) -> None:
    """The agent gets LIBERO-PRO's own instruction, sees only the cameras and its own state, and is never told the
    LIBERO task name, which in the task suites is the old goal."""
    s, body = t.spec, t.body
    assert t.metadata["language_instruction"] in body
    assert s["obs_mode"] == "vision"
    assert set(s["visible_fields"]) == {"hand_pos", "eef_quat", "eef_axis_angle", "gripper_qpos", "gripper_open"}
    name = Path(t.metadata["source_task"]).stem
    assert name not in body
    if s["suite"].endswith("_task"):
        assert _words(name.split("SCENE", 1)[-1].lstrip("0123456789_")) not in _words(body)


# ---- the backend: init files and start states ----------------------------------------------------------------------
def _init_file(path: Path, arr: np.ndarray, payload: bytes | None = None) -> Path:
    """A LIBERO init file as torch.save writes it: a zip archive whose data.pkl pickles the array."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("archive/data.pkl", payload if payload is not None else pickle.dumps(arr, protocol=4))
        z.writestr("archive/version", "3\n")
    return path


def test_init_files_load_without_torch(tmp_path) -> None:
    states = np.arange(12, dtype=np.float64).reshape(3, 4)
    got = lb.load_init_states(_init_file(tmp_path / "a.pruned_init", states))
    assert got.shape == (3, 4) and np.array_equal(got, states)


def test_an_init_file_that_names_other_code_is_refused(tmp_path) -> None:
    class Evil:
        def __reduce__(self):
            return (print, ("ran code from the init file",))

    bad = _init_file(tmp_path / "b.pruned_init", np.zeros(1), payload=pickle.dumps(Evil(), protocol=4))
    with pytest.raises(pickle.UnpicklingError, match="only a numpy array"):
        lb.load_init_states(bad)


def _backend(init_ref=None, init_state=None, init_index=0, mode="saved") -> lb.LiberoBackend:
    b = object.__new__(lb.LiberoBackend)  # no LIBERO here: only the start-state logic
    b._init_ref, b._init_state, b._init_index, b.init_mode = init_ref, init_state, init_index, mode
    return b


def test_the_seed_picks_a_saved_state_as_aspire_does(tmp_path, monkeypatch) -> None:
    states = np.arange(50 * 3, dtype=np.float64).reshape(50, 3)
    path = _init_file(tmp_path / "c.pruned_init", states)
    fetched = []
    monkeypatch.setattr(lb, "init_states_file", lambda ref: fetched.append(ref) or path)
    b = _backend({"url": "u", "sha256": "s", "count": 50}, init_state=np.array([-1.0, -1.0, -1.0]))
    assert np.array_equal(b._start_state(1), [-1.0, -1.0, -1.0]) and not fetched  # seed 1: the copy in the task
    assert np.array_equal(b._start_state(2), states[1]) and len(fetched) == 1  # seed n: state n - 1, downloaded
    assert np.array_equal(b._start_state(51), [-1.0, -1.0, -1.0]) and b.init_index == 0  # wraps round, as in ASPIRE
    assert b.placement_record == {"init_mode": "saved", "init_state": 0}
    seeded = _backend({"url": "u", "sha256": "s", "count": 50}, mode="seeded")
    assert seeded._start_state(7) is None and seeded.placement_record == {"init_mode": "seeded", "init_state": None}


def test_libero_tasks_keep_their_start(monkeypatch) -> None:
    """A libero suite task (one init_state, no init file) starts from it whatever the seed, and records nothing new."""
    b = _backend(init_state=np.array([1.0, 2.0]))
    assert np.array_equal(b._start_state(5), [1.0, 2.0]) and b.placement_record is None


def test_the_scene_file_is_kept_where_agents_cannot_read_it(tmp_path, monkeypatch) -> None:
    """A task that carries its scene has the BDDL text written to a file for LIBERO to load. The file names each object's
    start region, the layout a vision task hides, so it goes in robouse's cache, which the agent sandbox denies, not in
    the system's temporary folder, which the macOS sandbox leaves readable and writable; and it goes with the backend."""
    from robouse.runner import sandbox

    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(tmp_path / "cache"))
    loaded: list[tuple[str, str]] = []

    class Env:  # LIBERO's OffScreenRenderEnv, which parses the file when it is built
        def __init__(self, bddl_file_name: str, **kw) -> None:
            loaded.append((bddl_file_name, Path(bddl_file_name).read_text()))

        def close(self) -> None:
            pass

    monkeypatch.setattr(lb, "_quiet_imports", lambda: (None, None, Env))
    bddl = "(define (problem LIBERO_Tabletop_Manipulation)\n  (:language Put the bowl on the plate)\n)\n"
    b = lb.LiberoBackend({"bddl": bddl, "suite": "libero_goal_swap", "task_index": 8})
    ((path, text),) = loaded
    assert text == bddl and b.language == "Put the bowl on the plate"
    assert sandbox._inside(os.path.realpath(path), sandbox._denied([])), path
    b.close()
    assert not Path(path).exists()


def test_bddl_language_is_the_files_own() -> None:
    text = "(define (problem LIBERO_Tabletop_Manipulation)\n  ; a comment (:language no)\n  (:language Put the  wine\n   bottle on the plate)\n"
    assert lb.bddl_language(text) == "Put the wine bottle on the plate"
    assert lb.bddl_language("(define (problem x))") == ""


# ---- the scripted solution -----------------------------------------------------------------------------------------
def test_rotations() -> None:
    for yaw in (-1.2, 0.0, 0.7):
        R = down(yaw)
        assert np.allclose(R[:, 2], [0, 0, -1]) and np.allclose(R[:, 1], [np.sin(yaw), -np.cos(yaw), 0])
        assert np.allclose(mat2axisangle(R @ R_DOWN.T), [0, 0, yaw])
    u = np.array([np.cos(0.4), np.sin(0.4), 0.0])
    assert abs(abs(down(yaw_for(u))[:, 1] @ u) - 1) < 1e-9  # the fingers close along u
    F = facing([0, -1, 0])
    assert np.allclose(F[:, 2], [0, -1, 0]) and np.allclose(F[:, 1], [0, 0, 1]) and np.isclose(np.linalg.det(F), 1)
    q = [0.3, -0.2, 0.5, 0.78]
    Rq = quat2mat(q)
    assert np.allclose(Rq @ Rq.T, np.eye(3)) and np.isclose(np.linalg.det(Rq), 1)


def test_a_drawer_is_shut_after_what_goes_in() -> None:
    goal = [["close", "cab_bottom_region"], ["in", "bowl_1", "cab_bottom_region"]]
    assert Solver(None).plan(goal) == [goal[1], goal[0]]


TABLE = 0.90


def _quat(R: np.ndarray) -> list[float]:
    """Rotation matrix -> (x, y, z, w), from the largest component (a downward hand is a half turn: w = 0)."""
    if np.trace(R) > 0:
        w = np.sqrt(1 + np.trace(R)) / 2
        return [(R[2, 1] - R[1, 2]) / (4 * w), (R[0, 2] - R[2, 0]) / (4 * w), (R[1, 0] - R[0, 1]) / (4 * w), w]
    i = int(np.argmax(np.diag(R)))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = 2 * np.sqrt(max(1e-12, 1 + R[i, i] - R[j, j] - R[k, k]))
    q = np.zeros(4)
    q[i], q[j], q[k], q[3] = s / 4, (R[j, i] + R[i, j]) / s, (R[k, i] + R[i, k]) / s, (R[k, j] - R[j, k]) / s
    return q.tolist()


class KinematicArm:
    """A hand that moves 1 cm per unit of dx/dy/dz per step and turns a fifth of the commanded rotation, a gripper that
    takes a 4 cm box when it closes around it, a box that falls onto what is below it when let go, LIBERO's `On` check
    against a plate (origins within 3 cm, the box above it and touching) and the first-success end."""

    def __init__(self, box, plate, budget: int = 1000):
        self.hand, self.R = np.array([-0.2, 0.0, 1.17]), R_DOWN.copy()
        self.box, self.plate = np.asarray(box, dtype=float), np.asarray(plate, dtype=float)  # box: its bottom centre
        self.held, self.closed, self.steps, self.budget = False, False, 0, budget

    def _ents(self) -> dict:
        b, p = self.box, self.plate
        return {
            "box": {
                "kind": "object",
                "category": "Box",
                "pos": b.tolist(),
                "quat": [0, 0, 0, 1],
                "box_min": (b - [0.02, 0.02, 0]).tolist(),
                "box_max": (b + [0.02, 0.02, 0.04]).tolist(),
                "local_box_min": [-0.02, -0.02, 0],
                "local_box_max": [0.02, 0.02, 0.04],
            },
            "plate": {
                "kind": "object",
                "category": "Plate",
                "pos": p.tolist(),
                "quat": [0, 0, 0, 1],
                "box_min": (p - [0.08, 0.08, 0]).tolist(),
                "box_max": (p + [0.08, 0.08, 0.02]).tolist(),
                "local_box_min": [-0.08, -0.08, 0],
                "local_box_max": [0.08, 0.08, 0.02],
            },
        }

    def _public(self) -> dict:
        gap = 0.04 if self.held else (0.0 if self.closed else 0.08)
        return {"hand_pos": self.hand.tolist(), "eef_quat": _quat(self.R), "gripper_open": gap}

    def success(self) -> bool:
        top = self.plate[2] + 0.02
        return bool(np.all(np.abs(self.box[:2] - self.plate[:2]) < 0.03) and abs(self.box[2] - top) < 1e-6)

    def observe(self) -> dict:
        return {
            **self._public(),
            "articulated": {},
            "privileged": {"goal": [["on", "box", "plate"]], "entities": self._ents(), "sites": {}, "joints": {}},
        }

    def _floor(self, xy) -> float:
        return self.plate[2] + 0.02 if np.all(np.abs(xy - self.plate[:2]) < 0.08) else TABLE

    def act(self, a, repeat: int = 1) -> dict:
        a = np.asarray(a, dtype=float)
        for _ in range(repeat):
            w = np.clip(a[3:6], -1, 1) * 0.5 * 0.2
            ang = np.linalg.norm(w)
            if ang > 0:
                k = w / ang
                K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
                self.R = (np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K) @ self.R
            new = self.hand + np.clip(a[:3], -1, 1) * 0.01
            if self.held:  # the held box stops on whatever is under it
                new[2] = max(new[2], self._floor(new[:2]) + 0.03)
            self.hand = new
            if a[6] > 0 and not self.closed:
                self.closed = True
                inside = np.all(np.abs(self.hand[:2] - self.box[:2]) < 0.02)
                self.held = bool(inside and self.box[2] <= self.hand[2] <= self.box[2] + 0.04)
            elif a[6] < 0 and self.closed:
                self.closed = False
                if self.held:
                    self.held = False
                    self.box[2] = self._floor(self.box[:2])
            if self.held:
                self.box = self.hand - [0, 0, 0.03]
            self.steps += 1
            if self.success():
                raise Done("success")
            if self.steps >= self.budget:
                raise Done("budget")
        return self._public()


def test_the_solution_picks_and_places_on_a_kinematic_arm() -> None:
    arm = KinematicArm(box=[0.05, -0.15, TABLE], plate=[-0.05, 0.15, TABLE])
    with pytest.raises(Done, match="success"):
        Solver(arm).run()
    assert arm.success() and arm.steps < 400


class StillArm:
    """An arm that stays where it is: the hand pointing down, turned by `yaw`, the last joint at `q7` (or not given)."""

    def __init__(self, yaw: float, q7: float | None) -> None:
        self.yaw, self.q7 = yaw, q7

    def observe(self) -> dict:
        robot = {} if self.q7 is None else {"qpos": [0, 0, 0, -2, 0, 2, self.q7], "range": [[-2.8973, 2.8973]] * 7}
        priv = {"goal": [], "entities": {}, "sites": {}, "joints": {}, "robot": robot}
        return {
            "hand_pos": [0.0, 0.0, 1.0],
            "eef_quat": _quat(down(self.yaw)),
            "gripper_open": 0.08,
            "privileged": priv,
        }


def test_the_wrist_turns_the_way_its_joint_allows() -> None:
    """The Panda's last joint turns the hand about its axis, which points down: turned 3 rad from the start pose (joint
    at pi/4), the joint is at pi/4 - 3, 0.7 rad from its limit, so the hand turns further only the other way round."""
    s = Solver(StillArm(3.0, np.pi / 4 - 3.0))
    s.look()
    assert np.isclose(s.hand_yaw(), 3.0)
    assert not s.wrist_fits(down(3.0 + np.pi / 2)) and s.wrist_fits(down(3.0 - np.pi / 2))
    assert np.isclose(s.nearest_yaw(3.8), 3.8 - np.pi)
    assert np.isclose(yaw_of(s.nearest(down(3.8))), 3.8 - np.pi)
    free = Solver(StillArm(3.0, None))  # no joint angles: the nearest turn, as before
    free.look()
    assert np.isclose(free.nearest_yaw(3.8), 3.8)


def test_init_file_reading_matches_torch_layout(tmp_path) -> None:
    """The archive LIBERO's init files use: data.pkl inside a folder named after the file, found by its suffix."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("put_the_bowl_on_the_plate/data.pkl", pickle.dumps(np.ones((2, 2)), protocol=2))
    path = tmp_path / "d.pruned_init"
    path.write_bytes(buf.getvalue())
    assert lb.load_init_states(path).tolist() == [[1.0, 1.0], [1.0, 1.0]]
