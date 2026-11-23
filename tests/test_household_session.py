"""The household backend in robouse's episode session (core/session.py): physics extensions, the physical-state
trace, the settle, controller notes in replies, infrastructure errors, package resolution, the worker process and
policy blindness of everything the agent can read.

Needs the vendored Menagerie models (`python -m robouse.backends.household.assets fetch`); skips without them.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import shutil
import sys
import types

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

from robouse.backends.household import assets  # noqa: E402

try:
    assets.model_root()
except FileNotFoundError as e:  # pragma: no cover - depends on the machine
    pytest.skip(f"household models not fetched: {e}", allow_module_level=True)

from robouse.backends.household import extensions as X  # noqa: E402
from robouse.backends.household import package as P  # noqa: E402
from robouse.backends.household import testscene  # noqa: E402
from robouse.backends.household.backend import HouseholdBackend  # noqa: E402
from robouse.backends.household.sim import _digest  # noqa: E402

SLUG = "sa_9999_secret_slug"  # stands in for a task id: must never reach the agent
HANDLE = "ep-0123456789abcdef"
DOWN = (math.pi, 0.0, 0.0)
VISIBLE = ["hand_pos", "eef_quat", "eef_rpy", "gripper_open", "joint_pos", "robot_base_pos", "robot_forward"]


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    return testscene.write(tmp_path_factory.mktemp("pkgs") / SLUG / "package", behaviour=True)


def session(pkg, run_dir, control="eef", **kw):
    from robouse.core.session import Episode

    spec = {"backend": "household", "package": str(pkg), "control": control, "id": HANDLE, **kw}
    return Episode(spec, run_dir)


def edit_episode(root, fn) -> None:
    d = json.loads((root / "episode.json").read_text())
    fn(d)
    (root / "episode.json").write_text(json.dumps(d))


def read_trace(path) -> list[dict]:
    with gzip.open(path, "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---- physics extensions -------------------------------------------------------------------------------------------------
class ProbeExtension:
    """Counts its hook calls, pushes the cube up a little each step (it is physics: it may write data)."""

    prepared: list = []

    @staticmethod
    def prepare(spec, config, root):
        ProbeExtension.prepared.append(config)
        spec.worldbody.add_site(name="probe/marker", pos=[0, 0, 2], size=[0.01, 0.01, 0.01], group=5)

    def __init__(self, world, config):
        self.config = config
        self.cube = world.id("body", "cube")
        self.calls = {"before_step": 0, "before_substep": 0, "after_substep": 0, "after_step": 0}
        self.raise_at = config.get("raise_at")
        self.renders: list = []

    def before_step(self, world):
        self.calls["before_step"] += 1
        if self.raise_at and world.step + 1 >= self.raise_at:
            raise RuntimeError(f"probe failed in {SLUG}")

    def before_substep(self, world):
        self.calls["before_substep"] += 1

    def after_substep(self, world):
        self.calls["after_substep"] += 1

    def after_step(self, world):
        self.calls["after_step"] += 1

    def before_render(self, world, renderer):
        self.renders.append(type(renderer).__name__)

    def volume(self):  # a query a goal may call through world.extensions
        return 0.25

    def trace_state(self, world):
        return {"calls": dict(self.calls)}

    def summary(self):
        return {"calls": dict(self.calls)}


@pytest.fixture
def probe_registered(monkeypatch):
    monkeypatch.setitem(X.EXTENSIONS, "probe", f"{__name__}:ProbeExtension")
    ProbeExtension.prepared.clear()


def test_unregistered_extension_refused(tmp_path, pkg):
    bad = shutil.copytree(pkg, tmp_path / "liq")
    edit_episode(bad, lambda d: d.update(liquid={"x": 1}) if X.load_class("liquid") is None else d.update(nope={}))
    with pytest.raises(P.PackageError):
        P.load(bad)


def test_extension_hooks(tmp_path, pkg, probe_registered):
    ext = shutil.copytree(pkg, tmp_path / "ext")
    edit_episode(ext, lambda d: d.update(probe={"strength": 1}))
    assert P.load(ext).extensions == {"probe": {"strength": 1}}
    ep = session(ext, tmp_path / "run")
    sim = ep.backend.sim
    assert ProbeExtension.prepared == [{"strength": 1}]
    assert mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_SITE, "probe/marker") >= 0
    e = sim.extensions[0].obj
    rss = sim.ep.reset_settle_steps
    assert e.calls["before_step"] == rss  # constructed before the reset settling, which runs the hooks
    r = ep.handle({"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.0], "repeat": 5})
    assert r["ok"], r
    assert e.calls["before_step"] == e.calls["after_step"] == rss + 5
    assert e.calls["before_substep"] == e.calls["after_substep"] == (rss + 5) * 10
    ep.handle({"op": "done", "text": ""})
    assert ep.result["session"]["extensions"]["probe"]["calls"]["after_step"] == rss + 5 + 25
    states = [r for r in read_trace(tmp_path / "run" / "state-trace.jsonl.gz") if r["kind"] == "state"]
    assert states[-1]["probe"]["calls"]["after_step"] == rss + 5 + 25
    ep.close()


def test_extension_exception_ends_episode_as_infrastructure_error(tmp_path, pkg, probe_registered):
    ext = shutil.copytree(pkg, tmp_path / "ext")
    edit_episode(ext, lambda d: d.update(probe={"raise_at": 3}))
    ep = session(ext, tmp_path / "run")
    r = ep.handle({"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.0], "repeat": 10})
    assert not r["ok"] and "internal error" in r["error"] and SLUG not in json.dumps(r), r
    assert ep.finished and ep.outcome == "infrastructure_error"
    assert ep.result["success"] is False and ep.steps == 2
    assert SLUG in ep.result["session"]["infrastructure_error"]
    r = ep.handle({"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.0]})
    assert not r["ok"] and SLUG not in r["error"]
    ep.close()


# ---- the session: settle, notes, the built-in move_to and grip -------------------------------------------------------
def test_settle_and_absolute_rows_only(tmp_path, pkg):
    ep = session(pkg, tmp_path / "run")
    assert ep.settle_steps == 25
    r = ep.handle({"op": "act", "action": [0.01, 0.0, 0.0, 1.0]})  # the old [DX, DY, DZ, G] delta row is gone
    assert not r["ok"] and "7 numbers" in r["error"] and ep.steps == 0
    with pytest.raises(ValueError):
        ep.backend.step([0.01, 0.0, 0.0, 1.0])
    ep.handle({"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.0], "repeat": 3})
    ep.handle({"op": "done", "text": ""})
    assert ep.result["session"]["control_steps"] == 3 + 25
    ep.close()


def test_controller_notes_in_replies(tmp_path, pkg):
    ep = session(pkg, tmp_path / "run", "joint")
    b = ep.backend
    q = list(b.sim.q())
    q[0] = 9.0  # beyond joint 1's limit: clipped, and the reply says so
    r = ep.handle({"op": "act", "action": [*q, 1.0]})
    assert r["ok"] and r["result"]["notes"][0]["clipped_joints"], r
    r = ep.handle({"op": "act", "action": [*b.sim.q(), 1.5]})
    assert r["ok"] and r["result"]["notes"] == [{"clipped": "G", "to": 1.0}], r
    r = ep.handle({"op": "act", "action": [*b.sim.q(), 1.0]})
    assert r["ok"] and "notes" not in r["result"]
    ep.close()


def test_move_to_and_grip_are_absolute_row_skills(tmp_path, pkg):
    ep = session(pkg, tmp_path / "run")
    b = ep.backend
    st = b.observe()
    hp = st["hand_pos"]
    target = [hp[0] + 0.05, hp[1] - 0.05, hp[2] - 0.1]
    r = ep.handle({"op": "move_to", "pos": target})
    assert r["ok"] and r["result"]["reached"] and r["result"]["distance"] < 0.01, r
    assert r["result"]["executed_steps"] == ep.steps > 0
    q0, q1 = np.asarray(st["eef_quat"]), np.asarray(r["result"]["state"]["eef_quat"])
    assert abs(float(q0 @ q1)) > 0.9999  # the orientation is kept
    # a cap on the steps: stops there and holds
    n = ep.steps
    r = ep.handle({"op": "move_to", "pos": [hp[0], hp[1], hp[2]], "max_steps": 5})
    assert r["ok"] and not r["result"]["reached"] and "max_steps" in r["result"]["stopped"], r
    assert ep.steps == n + 5
    # out of reach: refused before anything moves
    n = ep.steps
    r = ep.handle({"op": "move_to", "pos": [3.0, 0.0, 1.0]})
    assert r["ok"] and r["result"]["refused"] == "unreachable" and ep.steps == n, r
    r = ep.handle({"op": "grip", "value": 0.0, "steps": 30})
    assert r["ok"] and r["result"]["state"]["gripper_open"] < 0.05
    assert b.sim.grip_open_cmd == 0.0
    ep.close()
    joint = session(pkg, tmp_path / "joint", "joint")
    r = joint.handle({"op": "move_to", "pos": target})
    assert not r["ok"] and "not available" in r["error"]
    joint.close()


# ---- package resolution ------------------------------------------------------------------------------------------------
def test_relative_package_resolves_against_the_task_folder(tmp_path, pkg, monkeypatch):
    from robouse.tasks import load_task

    task = tmp_path / "exports" / HANDLE
    shutil.copytree(pkg, task / "package")
    (task / "task.md").write_text(
        "---\nrobouse:\n  backend: household\n  package: package\n  control: eef\n"
        f"  id: {HANDLE}\nagent:\n  timeout_sec: 4800\n  max_turns: 400\n---\n\nMove the arm.\n"
    )
    monkeypatch.chdir(tmp_path)  # not the task folder: the working directory plays no part
    t = load_task(task)
    assert t.spec["task_dir"] == str(task.resolve()) and t.agent_max_turns == 400 and t.agent_timeout_s == 4800
    from robouse.core.session import Episode

    ep = Episode(t.spec, tmp_path / "run")
    info = ep.handle({"op": "info"})
    assert info["ok"] and "exports" not in json.dumps(info) and "task_dir" not in json.dumps(info)
    ep.close()
    with pytest.raises(ValueError, match="task folder"):
        HouseholdBackend({"backend": "household", "package": "package", "control": "eef"})
    b = HouseholdBackend({"backend": "household", "package": str(task / "package"), "control": "eef"})
    b.close()


# ---- plugin import isolation -------------------------------------------------------------------------------------------
def test_plugins_leave_the_host_modules_alone(tmp_path, pkg, monkeypatch):
    """A package's plugin/ vendors `tasks.common...` helpers; loading it must not leave sys.modules pointing the host's
    `tasks`, `goal` or `behaviour` at the package's copies."""
    vend = shutil.copytree(pkg, tmp_path / "vendored")
    helpers = vend / "plugin" / "tasks" / "common"
    helpers.mkdir(parents=True)
    (vend / "plugin" / "tasks" / "__init__.py").write_text("")
    (helpers / "__init__.py").write_text("")
    (helpers / "goals.py").write_text("WHO = 'package'\n")
    goal = (vend / "plugin" / "goal.py").read_text()
    goal = goal.replace("import numpy as np\n", "import numpy as np\n\nfrom tasks.common.goals import WHO\n", 1)
    goal = goal.replace("self.updates = 0", "self.updates = 0\n        self.who = WHO")
    (vend / "plugin" / "goal.py").write_text(goal)
    P.write_files_map(vend)
    host = {n: types.ModuleType(n) for n in ("tasks", "tasks.common", "tasks.common.goals", "goal", "behaviour")}
    host["tasks.common.goals"].WHO = "host"
    for n, m in host.items():
        monkeypatch.setitem(sys.modules, n, m)
    for _ in range(2):  # twice: the second load must again get the package's own copies
        b = HouseholdBackend({"backend": "household", "package": str(vend), "control": "eef"})
        b.reset(0)
        assert b.sim.goal_obj.who == "package"
        assert b.sim.goal_success() is False  # the plugin still works after the host's modules are back
        for n, m in host.items():
            assert sys.modules[n] is m, n
        assert not any(k.startswith("tasks.") and k not in host for k in sys.modules)
        b.close()
    import tasks.common.goals as g  # the host's import machinery still finds the host's module

    assert g.WHO == "host"


# ---- the physical-state trace ------------------------------------------------------------------------------------------
def _pick(ep):
    cx, cy, cz = testscene.CUBE_POS
    for args in ([cx, cy, cz + 0.15, *DOWN, 1], [cx, cy, cz + 0.005, *DOWN]):
        r = ep.handle({"op": "skill", "name": "move_to_pose", "args": args})
        assert r["ok"] and r["result"]["reached"], r
    r = ep.handle({"op": "act", "action": [cx, cy, cz + 0.005, *DOWN, 0.0], "repeat": 40})
    assert r["ok"], r
    r = ep.handle({"op": "move_to", "pos": [cx, cy, cz + 0.1]})
    assert r["ok"] and r["result"]["reached"], r


def test_state_trace(tmp_path, pkg):
    run = tmp_path / "trial" / "episode"
    ep = session(pkg, run)
    _pick(ep)
    steps = ep.steps
    ep.handle({"op": "done", "text": ""})
    ep.close()
    path = run / "state-trace.jsonl.gz"
    rows = read_trace(path)
    head, end = rows[0], rows[-1]
    assert head["kind"] == "header" and head["format"] == "robouse-state-trace" and head["version"] == "2.0.0"
    assert head["backend"] == "household" and head["package"] == P.load(pkg).identity and head["control"] == "eef"
    assert set(head["objects"]) == {"cube"} and set(head["fixtures"]) == {"table", "pad"}
    states = [r for r in rows if r["kind"] == "state"]
    assert end == {"kind": "end", "steps": steps + 25, "records": len(rows), "goal": False}
    # every control step, the settle, and the final state
    assert [s["step"] for s in states[:-1]] == list(range(0, steps + 26))
    phases = [s["phase"] for s in states]
    assert phases[0] == "reset" and set(phases[1 : steps + 1]) == {"control"}
    assert set(phases[steps + 1 : -1]) == {"settle"} and phases[-1] == "final"
    held = states[steps]  # the cube is held: grasped, with contact forces on both pads
    assert held["robot"]["grasped"] == ["cube"] and held["objects"]["cube"]["pos"][2] > testscene.CUBE_POS[2] + 0.05
    assert any(set(c) == {"cube", "robot:gripper"} for c in held["contacts"])
    forces = {tuple(sorted(f[:2])): f for f in held["contact_forces"]}
    n, normal, tangential, peak = forces[("cube", "robot:gripper")][2:]
    assert n >= 2 and normal > 10 and peak >= normal * 0.5 and tangential >= 0
    assert [c for c in held["contacts"]] == [f[:2] for f in held["contact_forces"][: len(held["contacts"])]]
    assert held["robot"]["pad_force"]["cube"] > 10
    # what the cube rested on before the grasp
    assert states[0]["objects"]["cube"]["on"] == ["table"]
    assert ep.result["session"]["state_trace"]["complete"] is True
    # the trace reader eval uses
    from robouse.backends.household.state_trace import read

    t = read(path)
    assert t["complete"] and len(t["states"]) == len(states)


def test_state_trace_changes_no_physics(tmp_path, pkg, monkeypatch):
    digests = []
    for flag in ("1", "0"):
        monkeypatch.setenv("ROBOUSE_STATE_TRACE", flag)
        ep = session(pkg, tmp_path / f"run{flag}")
        _pick(ep)
        digests.append(_digest(ep.backend.sim.data))
        ep.close()
    assert digests[0] == digests[1]
    assert (tmp_path / "run1" / "state-trace.jsonl.gz").exists()
    assert not (tmp_path / "run0" / "state-trace.jsonl.gz").exists()
    text = session(pkg, tmp_path / "text", "text")
    text.handle({"op": "done", "text": "plan"})
    text.close()
    assert not (tmp_path / "text" / "state-trace.jsonl.gz").exists()


# ---- the worker process (ROBOUSE_HOUSEHOLD_PYTHON) ---------------------------------------------------------------------
# another interpreter for the worker (e.g. liquid's Python 3.12 environment): HOUSEHOLD_TEST_PYTHON=<python>
WORKER_PYTHONS = [sys.executable] + (
    [os.environ["HOUSEHOLD_TEST_PYTHON"]] if os.environ.get("HOUSEHOLD_TEST_PYTHON") else []
)


@pytest.mark.parametrize("python", WORKER_PYTHONS)
def test_worker_process_matches_in_process(tmp_path, pkg, monkeypatch, python):
    from robouse.backends.household.remote import RemoteHouseholdBackend

    def episode(run):
        ep = session(pkg, run, obs_mode="vision", cameras=["camera_1", "camera_2"], visible_fields=VISIBLE)
        out = [ep.handle({"op": "info"})]
        _pick(ep)
        hp = ep.handle({"op": "observe"})["result"]["state"]["hand_pos"]
        out.append(ep.handle({"op": "skill", "name": "move_to_pose", "args": [3.0, 0.0, 1.0, *DOWN]}))
        out.append(ep.handle({"op": "act", "action": [3.0, 0.0, 1.0, *DOWN, 0.0]}))
        out.append(ep.handle({"op": "grip", "value": 1.0, "steps": 10}))
        out.append(ep.handle({"op": "observe"}))
        out.append(ep.handle({"op": "done", "text": ""}))
        ep.close()
        res = dict(ep.result)
        for k in ("wall_time_s", "metrics", "video_size"):
            res.pop(k, None)
        return ep, out, res, hp

    local, out_l, res_l, _ = episode(tmp_path / "local")
    monkeypatch.setenv("ROBOUSE_HOUSEHOLD_PYTHON", python)
    remote, out_r, res_r, _ = episode(tmp_path / "remote")
    assert isinstance(remote.backend, RemoteHouseholdBackend) and not hasattr(remote.backend, "sim")

    def clean(o):  # observation image paths differ by run folder
        return json.loads(
            json.dumps(o).replace(str(tmp_path / "remote"), "<run>").replace(str(tmp_path / "local"), "<run>")
        )

    assert clean(out_r) == clean(out_l)
    # out_r[0] is info; the refusals crossed the process boundary with their reasons
    assert "unreachable" in json.dumps(out_r[1])
    assert not out_r[2]["ok"] and "unreachable" in out_r[2]["error"]
    assert res_r == res_l
    a, b = (
        read_trace(tmp_path / "local" / "state-trace.jsonl.gz"),
        read_trace(tmp_path / "remote" / "state-trace.jsonl.gz"),
    )
    assert [r.get("digest") for r in a] == [r.get("digest") for r in b]


def test_worker_process_infrastructure_error(tmp_path, pkg, monkeypatch):
    bad = shutil.copytree(pkg, tmp_path / "raiser")
    g = (bad / "plugin" / "behaviour.py").read_text()
    (bad / "plugin" / "behaviour.py").write_text(
        g.replace("self.calls += 1", f"self.calls += 1\n        if self.calls > 30: raise RuntimeError('{SLUG}')")
    )
    P.write_files_map(bad)
    monkeypatch.setenv("ROBOUSE_HOUSEHOLD_PYTHON", sys.executable)
    ep = session(bad, tmp_path / "run")
    r = ep.handle({"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.0], "repeat": 10})
    assert not r["ok"] and r["error"] == "InternalError: an internal error occurred; the episode cannot continue", r
    assert ep.outcome == "infrastructure_error" and SLUG in ep.result["session"]["infrastructure_error"]
    ep.close()


# ---- policy blindness of the session layer -----------------------------------------------------------------------------
def test_session_layer_blindness(tmp_path, pkg, probe_registered):
    """Every reply the agent can get (info, observe, act, skills, move_to, grip, refusals, notes, errors, the
    infrastructure error, done) names neither the task, the package, its path, the run folder nor the trace."""
    ext = shutil.copytree(pkg, tmp_path / SLUG)
    edit_episode(ext, lambda d: d.update(probe={"raise_at": 400}))
    run = tmp_path / "trial-secret" / "episode"
    forbidden = [
        SLUG,
        str(ext),
        str(run),
        "trial-secret",
        "state-trace",
        "trace",
        "episode.json",
        "probe",
        "sa_",
        "cube",
        "table",
        "pad/",
        "goal:Goal",
        P.load(ext).identity[:16],
    ]
    texts = []
    ep = session(ext, run, obs_mode="vision", cameras=["camera_1", "camera_2"], visible_fields=VISIBLE)
    info = ep.handle({"op": "info"})
    assert info["result"].pop("task") == HANDLE
    texts.append(json.dumps(info))
    for req in (
        {"op": "observe"},
        {"op": "observe", "inline": {"cameras": ["camera_2"], "width": 32, "height": 24}},
        {"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.4]},  # a note
        {"op": "act", "action": [0.5, 0.0, 1.1, *DOWN]},  # malformed
        {"op": "act", "action": [3.0, 0.0, 1.1, *DOWN, 1.0]},  # refused
        {"op": "move_to", "pos": [0.5, 0.05, 1.05]},
        {"op": "move_to", "pos": [3.0, 0.0, 1.0]},
        {"op": "grip", "value": 0.5, "steps": 3},
        {"op": "skill", "name": "move_to_pose", "args": [0.5, 0.0, 1.0, *DOWN, 2.0]},
        {"op": "skill", "name": "nope", "args": []},
        {"op": "status"},
    ):
        texts.append(json.dumps(ep.handle(req)))
    while not ep.finished:  # until the probe extension fails at step 400
        texts.append(json.dumps(ep.handle({"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.0], "repeat": 50})))
    for req in ({"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.0]}, {"op": "done", "text": "x"}):
        texts.append(json.dumps(ep.handle(req)))
    assert ep.outcome == "infrastructure_error"
    ep.close()
    blob = "\n".join(t.replace(str(run / "observations"), "<obs>") for t in texts)
    for f in forbidden:
        assert f not in blob, f"{f!r} reached the agent"


# ---- policy blindness of a harness launch ------------------------------------------------------------------------------
AGENT = """#!/bin/bash
env > {report}/env.txt
printf '%s\\n' "$0" "$@" > {report}/argv.txt
pwd > {report}/pwd.txt
robo info > {report}/info.txt 2>&1
robo observe > {report}/observe.txt 2>&1
robo act 0.5 0.0 1.1 3.14159 0 0 1 > {report}/act.txt 2>&1
ls -la . .robouse > {report}/ls.txt 2>&1
robo done finished > {report}/done.txt 2>&1
"""


def test_harness_launch_blindness(tmp_path, pkg, monkeypatch):
    """A household export run through the runner: the agent's environment, argv, workspace and replies never name the
    task, its export root or the package, the turn cap reaches the harness and config.json, and the trace lands in
    <trial>/episode/."""
    from robouse import harnesses
    from robouse.harnesses import Launch
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    root = tmp_path / "secret_export_root"
    task = root / HANDLE
    shutil.copytree(pkg, task / "package")
    (task / "task.md").write_text(
        "---\nrobouse:\n  backend: household\n  package: package\n  control: eef\n"
        "agent:\n  timeout_sec: 300\n  max_turns: 400\n---\n\nMove the arm a little, then finish.\n"
    )
    report = tmp_path / "report"
    report.mkdir()
    seen = {}

    def agent(model, prompt, workspace, task_, env):
        seen["turns"] = env.get(harnesses.MAX_TURNS_ENV)
        script = workspace / ".robouse" / "agent.sh"
        script.write_text(AGENT.format(report=report))
        # declares itself a driver of Claude Code at the trial's cap, as program does
        return Launch(
            ["bash", str(script)],
            env,
            notes={"model": "none"},
            config={"agent": "claude-code", "agent_max_turns": int(seen["turns"])},
        )

    monkeypatch.setitem(harnesses.HARNESSES, "probe-agent", agent)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")  # the report folder must be writable; the sandbox has its own tests
    job = tmp_path / "job"
    res = run_trial(load_task(task), "probe-agent", "", job)
    assert res["exception"] is None, res
    assert seen["turns"] == "400"
    tdir = job / res["trial"]
    cfg = json.loads((tdir / "config.json").read_text())
    assert cfg["max_turns"] == 400 and cfg["harness_config"]["max_turns_enforced"] is True
    assert (tdir / "episode" / "state-trace.jsonl.gz").exists()
    result = json.loads((tdir / "episode" / "result.json").read_text())
    assert result["outcome"] == "done" and result["session"]["state_trace"]["complete"]
    seen_text = {p.name: p.read_text() for p in report.iterdir()}
    assert "executed_steps" in seen_text["act.txt"], seen_text["act.txt"]
    blob = "\n".join(seen_text.values())
    for f in (
        SLUG,
        "secret_export_root",
        str(root),
        str(job),
        "state-trace",
        "episode.json",
        "task_dir",
        harnesses.MAX_TURNS_ENV,
        harnesses.EFFORT_ENV,
        "ROBOUSE_HOUSEHOLD_PYTHON",
        "cube",
        "goal:Goal",
    ):
        assert f not in blob, f"{f!r} reached the agent"


def test_extension_render_hook_and_world_access(tmp_path, pkg, probe_registered):
    ext = shutil.copytree(pkg, tmp_path / "ext")
    edit_episode(ext, lambda d: d.update(probe={}))
    ep = session(ext, tmp_path / "run", obs_mode="vision", cameras=["camera_1", "camera_2"], visible_fields=VISIBLE)
    sim = ep.backend.sim
    e = sim.extensions[0].obj
    n = len(e.renders)
    ep.handle({"op": "observe"})
    assert e.renders[n:] == ["Renderer", "Renderer"]  # once per camera image, with the mujoco.Renderer
    w = sim.world
    assert w.extensions["probe"] is e and w.extensions["probe"].volume() == 0.25
    with pytest.raises(TypeError):
        w.extensions["probe"] = None  # read-only
    ep.close()
