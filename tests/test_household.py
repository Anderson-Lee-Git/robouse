"""The household backend (FR3 + Robotiq 2F-85 in a compiled scene package, spec 1.0.0) on the procedural test scene:
package validation, joint tracking, inverse kinematics and its refusals, an EEF pick-and-place judged by the goal
plugin, the behaviour plugin, both cameras and their projection matrices, the step budget and policy blindness.

Needs the vendored Menagerie models (`python -m robouse.backends.household.assets fetch`); skips without them.
Measured numbers go to stdout (`pytest -s`) as `HOUSEHOLD-METRIC name value` lines.
"""

from __future__ import annotations

import json
import math
import shutil

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

from robouse.backends.household import assets  # noqa: E402

try:
    assets.model_root()
except FileNotFoundError as e:  # pragma: no cover - depends on the machine
    pytest.skip(f"household models not fetched: {e}", allow_module_level=True)

from robouse.backends.household import package as P  # noqa: E402
from robouse.backends.household import testscene  # noqa: E402
from robouse.backends.household.backend import HouseholdBackend  # noqa: E402
from robouse.backends.household.ik import rotvec  # noqa: E402
from robouse.backends.household.sim import InternalError  # noqa: E402

SLUG = "sa_9999-secret-slug"  # stands in for a task id: must never reach the agent
DOWN = (math.pi, 0.0, 0.0)  # the pinch frame's +z (out of the hand) pointing down


def metric(name: str, value) -> None:
    print(f"HOUSEHOLD-METRIC {name} {value}")


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    return testscene.write(tmp_path_factory.mktemp("pkgs") / SLUG / "package", behaviour=True)


def make(pkg, control="eef", **kw) -> HouseholdBackend:
    b = HouseholdBackend({"backend": "household", "package": str(pkg), "control": control, **kw})
    b.reset(0)
    return b


def session(pkg, tmp_path, control="eef", **kw):
    from robouse.core.session import Episode

    spec = {"backend": "household", "package": str(pkg), "control": control, "id": "ep-0123456789abcdef", **kw}
    return Episode(spec, tmp_path / f"run-{control}-{len(list(tmp_path.iterdir()))}")


def run_skill(b: HouseholdBackend, name: str, *args) -> tuple[dict, int]:
    """Drive a skill as the session does: one backend step per yielded action. Returns (result, steps)."""
    gen = b.start_skill(name, [str(a) for a in args])
    n = 0
    while True:
        try:
            a = next(gen)
        except StopIteration as e:
            return e.value or {}, n
        b.step(a)
        n += 1


def hold(b: HouseholdBackend, n: int) -> None:
    for _ in range(n):
        b.step([])


def copy_pkg(pkg, dst):
    shutil.copytree(pkg, dst)
    return dst


def edit_episode(root, fn) -> None:
    d = json.loads((root / "episode.json").read_text())
    fn(d)
    (root / "episode.json").write_text(json.dumps(d))


# ---- package -----------------------------------------------------------------------------------------------------------
def test_package_validation(tmp_path, pkg):
    ep = P.load(pkg)
    assert ep.base_pos == [0.0, 0.0, testscene.TABLE_TOP] and ep.max_steps == 45_000 and ep.goal == "goal:Goal"
    cases = [
        (lambda d: d["budgets"].update(max_steps=1000), "max_steps"),
        (lambda d: d["budgets"].update(settle_steps=10), "settle_steps"),
        (lambda d: d["control"].update(rate_hz=100), "rate_hz"),
        (lambda d: d["render"].update(width=320), "render"),
        (lambda d: d.update(format_version="2.0.0"), "format_version"),
        (lambda d: d.update(instruction="Put the cube on the pad."), "unknown fields"),
        (lambda d: d.update(not_an_extension={}), "unknown fields"),
        (lambda d: d["robot"]["base"].update(quat=[1, 1, 0, 0]), "unit quaternion"),
        (lambda d: d["cameras"].update(camera_1={}), "unknown fields"),
        (lambda d: d["plugins"].update(goal="other:Thing"), "plugins.goal"),
        (lambda d: d["plugins"].pop("helpers"), "missing"),
        (lambda d: d["plugins"].update(helpers={"goals": "1.0"}), "plugins.helpers"),
        (lambda d: d["plugins"].update(helpers={"goals": "1.0", "behaviours": "1.0.0"}), "semver"),
        (lambda d: d["compute"].update(device="gpu"), "compute.device"),
    ]
    for i, (fn, needle) in enumerate(cases):
        bad = copy_pkg(pkg, tmp_path / f"bad{i}")
        edit_episode(bad, fn)
        with pytest.raises(P.PackageError, match=needle):
            P.load(bad)
    # files: a changed file, an unlisted file, a missing file
    bad = copy_pkg(pkg, tmp_path / "tamper")
    (bad / "scene.xml").write_text((bad / "scene.xml").read_text() + "\n")
    with pytest.raises(P.PackageError, match="differs"):
        P.load(bad)
    bad = copy_pkg(pkg, tmp_path / "extra")
    (bad / "plugin" / "extra.py").write_text("x = 1\n")
    with pytest.raises(P.PackageError, match="does not list"):
        P.load(bad)
    bad = copy_pkg(pkg, tmp_path / "missing")
    (bad / "plugin" / "behaviour.py").unlink()
    with pytest.raises(P.PackageError, match="missing"):
        P.load(bad)
    # the scene leaves cameras and robot/ names to the backend
    xml = (pkg / "scene.xml").read_text()
    for i, evil in enumerate(('<camera name="cam" pos="0 0 2"/>', '<site name="robot/x" pos="0 0 2"/>')):
        bad = copy_pkg(pkg, tmp_path / f"evil{i}")
        (bad / "scene.xml").write_text(xml.replace("</worldbody>", evil + "</worldbody>"))
        P.write_files_map(bad)
        with pytest.raises(P.PackageError):
            HouseholdBackend({"package": str(bad), "control": "eef"})
    with pytest.raises(ValueError):
        HouseholdBackend({"package": str(pkg), "control": "eef", "max_steps": 45_001})
    with pytest.raises(ValueError):
        HouseholdBackend({"package": str(pkg), "control": "teleport"})


def test_physics_and_render_set_by_backend(tmp_path, pkg):
    alt = copy_pkg(pkg, tmp_path / "alt")
    xml = (alt / "scene.xml").read_text().replace("<asset>", '<option timestep="0.01" integrator="Euler"/><asset>', 1)
    (alt / "scene.xml").write_text(xml)
    P.write_files_map(alt)
    b = make(alt)
    m = b.sim.model
    assert m.opt.timestep == pytest.approx(0.002)
    assert m.opt.integrator == mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    assert m.opt.cone == mujoco.mjtCone.mjCONE_ELLIPTIC and m.opt.impratio == pytest.approx(100)
    assert m.opt.solver == mujoco.mjtSolver.mjSOL_NEWTON and m.opt.iterations == 100
    assert m.vis.quality.shadowsize == 4096 and m.vis.quality.offsamples == 4 and m.vis.headlight.active == 1
    j7 = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "robot/fr3_joint7")
    assert m.dof_armature[m.jnt_dofadr[j7]] == pytest.approx(0.2)
    b.close()


def test_robot_base_pose_and_pedestal(tmp_path, pkg):
    """The base goes anywhere, turned about z; the pedestal reaches down from the base to the floor."""
    alt = copy_pkg(pkg, tmp_path / "turned")
    yaw = math.radians(90)

    def fn(d):
        d["robot"]["base"] = {"pos": [0.6, -0.9, 0.5], "quat": [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]}
        d["robot"]["pedestal"]["height_m"] = 0.5

    edit_episode(alt, fn)
    b = make(alt)
    st = b.observe()
    assert st["robot_forward"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-4)
    m, d = b.mj_model_data()
    link0 = d.body("robot/fr3_link0")
    assert link0.xpos == pytest.approx([0.6, -0.9, 0.5], abs=1e-9)
    ped = d.geom("robot/pedestal")
    assert ped.xpos[2] == pytest.approx(0.25) and m.geom("robot/pedestal").size[2] == pytest.approx(0.25)
    # the hand is in front of the base (+y now) at home
    assert st["hand_pos"][1] > -0.9 + 0.15
    b.close()


@pytest.mark.parametrize("yaw_deg", [135, 120])
def test_off_axis_base_yaw_eef_rows(tmp_path, pkg, yaw_deg):
    """A base turned by a yaw that is not a multiple of 90 degrees: the arm, its IK model and the reported hand pose
    all turn with it. From home, 5 cm straight moves along every world axis and wrist turns about the vertical are
    accepted, and every pose relative to the base solves exactly as it does with the base unturned."""
    from robouse.backends.household.ik import mat_quat
    from robouse.backends.household.robot import quat_mat
    from robouse.backends.household.sim import rpy_to_quat

    yaw = math.radians(yaw_deg)
    alt = copy_pkg(pkg, tmp_path / f"yaw{yaw_deg}")
    edit_episode(alt, lambda d: d["robot"]["base"].update(quat=[math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]))
    b0, b = make(pkg), make(alt)
    Rb = quat_mat(b.sim.ep.base_quat)
    p0, q0 = b0.sim.hand_pose()
    p, q = b.sim.hand_pose()
    base0, base = np.asarray(b0.sim.ep.base_pos), np.asarray(b.sim.ep.base_pos)
    # the home hand pose is the unturned one carried round with the base, and eef_rpy reports the turn
    assert p - base == pytest.approx(Rb @ (p0 - base0), abs=1e-6)
    assert np.linalg.norm(rotvec(mat_quat(Rb @ quat_mat(q0)), q)) < 1e-6
    st0, st = b0.observe(), b.observe()
    assert math.remainder(st["eef_rpy"][2] - st0["eef_rpy"][2] - yaw, 2 * math.pi) == pytest.approx(0.0, abs=1e-3)
    for d in np.vstack([np.eye(3), -np.eye(3)]) * 0.05:
        path, rep = b.sim.solve_pose(p + d, q)
        assert path is not None, (d.tolist(), rep)
    for turn in (-0.6, -0.3, 0.3, 0.6):  # the wrist turned about the vertical, at home
        Rt = quat_mat(rpy_to_quat(0.0, 0.0, turn)) @ quat_mat(q)
        path, rep = b.sim.solve_pose(p, mat_quat(Rt))
        assert path is not None, (turn, rep)
    # pointing straight down, fingers along the base's forward axis (world yaw = the base yaw)
    path, rep = b.sim.solve_pose(p, rpy_to_quat(math.pi, 0.0, yaw))
    assert path is not None, rep
    # invariance: the same base-relative targets give the same verdicts and joint paths as the unturned base
    for k in range(12):
        Rrel = quat_mat(rpy_to_quat(math.pi, 0.0, math.radians(30 * k)))
        a, ra = b0.sim.solve_pose(p0, mat_quat(Rrel))
        c, rc = b.sim.solve_pose(p, mat_quat(Rb @ Rrel))
        assert (a is None) == (c is None) and ra["reason"] == rc["reason"], (k, ra, rc)
        if a is not None:
            assert c[-1] == pytest.approx(a[-1], abs=1e-4)
    # an executed row lands on the commanded pose
    target = p + np.array([0.0, 0.0, -0.05])
    row = [*target.tolist(), *st["eef_rpy"], 1.0]
    for _ in range(60):
        b.step(row)
    hold(b, 25)
    assert np.linalg.norm(b.sim.hand_pose()[0] - target) < 0.002
    b0.close()
    b.close()


# ---- joint mode --------------------------------------------------------------------------------------------------------
def test_joint_tracking(pkg):
    b = make(pkg, "joint")
    sim = b.sim
    home = sim.q()
    target = home + np.array([0.5, 0.3, -0.4, 0.4, 0.6, -0.3, 0.8])
    gen = b.start_skill("move_joints_to", [str(v) for v in target])
    lag, n = [], 0
    while True:
        try:
            a = next(gen)
        except StopIteration as e:
            res = e.value
            break
        b.step(a)
        n += 1
        lag.append(float(np.max(np.abs(sim.tracker.q - sim.q()))))
    assert res["reached"] and res["settled"], res
    metric("joint_move_steps", n)
    metric("joint_tracking_max_err_rad", round(max(lag), 5))
    metric("joint_tracking_rms_err_rad", round(float(np.sqrt(np.mean(np.square(lag)))), 5))
    metric("joint_final_err_rad", res["max_joint_error"])
    assert max(lag) < 0.03
    assert res["max_joint_error"] < 0.005
    b.close()


@pytest.mark.parametrize("delta", [[0.4, -0.3, 0.3, 0.3, -0.4, 0.3, -0.5], [-0.3, 0.2, 0.4, -0.3, 0.5, -0.2, 0.6]])
def test_joint_settle_time(pkg, delta):
    """After a planned move the arm comes to rest (the first target chattered at rest before wrist armature 0.2)."""
    b = make(pkg, "joint")
    sim = b.sim
    target = sim.q() + np.array(delta)
    pos, vel = sim.plan_joints(target)
    for k in range(len(pos)):
        b.step({"ref": pos[k], "vel": vel[k]})
    err_end = float(np.max(np.abs(target - sim.q())))
    t = 0
    while not sim.settled() and t < 200:
        b.step([])
        t += 1
    metric("joint_err_at_reference_end_rad", round(err_end, 5))
    metric("joint_settle_ticks_after_reference_end", t)
    assert sim.settled() and t < 50
    hold(b, 10)
    assert float(np.max(np.abs(sim.qd()))) < 0.02  # at rest: no limit cycle
    b.close()


def test_joint_rows(pkg):
    b = make(pkg, "joint")
    sim = b.sim
    q0 = sim.q()
    target = q0 + np.array([0.75, 0, 0, 0, 0, 0, 0])
    lag = []
    for _ in range(60):
        b.step(list(target) + [1.0])
        lag.append(float(abs(sim.tracker.q[0] - sim.q()[0])))
    metric("joint_row_tracking_max_err_rad", round(max(lag), 5))
    assert sim.q()[0] == pytest.approx(target[0], abs=0.01)
    assert max(lag) < 0.03
    assert b.pop_notes() == []
    # a row past a joint limit is clipped to the limit less the margin, and the clip is noted
    row = list(sim.q()) + [1.0]
    row[3] = -5.0
    for _ in range(150):
        b.step(row)
    hold(b, 30)
    assert sim.q()[3] == pytest.approx(sim.lo[3], abs=5e-3)
    assert {"clipped_joints": [4], "to_limits": "joint limits less 0.02 rad"} in b.pop_notes()
    with pytest.raises(ValueError, match="outside the joint limits"):
        b.start_skill("move_joints_to", ["0", "0", "0", "0", "0", "1.5", "0"])  # q4 = 0 is beyond its range
    b.close()


# ---- inverse kinematics ------------------------------------------------------------------------------------------------
def test_ik_accuracy_and_convergence(pkg):
    b = make(pkg)
    ik, home = b.sim.ik, b.sim.home
    rng = np.random.default_rng(0)
    ok, perr, rerr, iters = 0, [], [], []
    n = 200
    for _ in range(n):
        q = np.clip(home + rng.uniform(-0.3, 0.3, 7), ik.lo, ik.hi)
        p, r = ik.fk(q)
        seed = q + rng.uniform(-0.1, 0.1, 7)  # a nearby start
        res = ik.solve(p, r, seed, max_jump=0.5)
        if res.ok:
            ok += 1
            fp, fr = ik.fk(res.q)
            perr.append(float(np.linalg.norm(fp - p)))
            rerr.append(float(np.linalg.norm(rotvec(fr, r))))
            iters.append(res.iters)
    metric("ik_converged_fraction", ok / n)
    metric("ik_pos_err_max_m", f"{max(perr):.2e}")
    metric("ik_rot_err_max_rad", f"{max(rerr):.2e}")
    metric("ik_iters_median", int(np.median(iters)))
    assert ok / n >= 0.98
    assert max(perr) < 1e-4 and max(rerr) < 1e-3
    b.close()


def test_eef_row_accuracy(pkg):
    """Absolute EEF rows land the pinch point on the commanded pose."""
    b = make(pkg)
    errs = []
    for x, y, z, yaw in [(0.5, 0.0, 1.1, 0.0), (0.45, -0.2, 0.95, 0.4), (0.6, 0.2, 0.9, -0.3)]:
        row = [x, y, z, DOWN[0], DOWN[1], yaw, 1.0]
        for _ in range(100):
            b.step(row)
        hold(b, 25)
        st = b.observe()
        errs.append(float(np.linalg.norm(b.sim.hand_pose()[0] - np.array([x, y, z]))))
        assert st["eef_rpy"][2] == pytest.approx(yaw, abs=0.01)
    metric("eef_row_final_pos_err_max_m", f"{max(errs):.2e}")
    assert max(errs) < 0.002
    b.close()


def test_ik_branch_flip_refused(pkg):
    b = make(pkg)
    ik, home = b.sim.ik, b.sim.home
    q_far = home.copy()
    q_far[6] -= 1.2  # the same hand position with the wrist turned by 1.2 rad: only reachable by a large joint jump
    p, r = ik.fk(q_far)
    res = ik.solve(p, r, home, max_jump=0.35)
    assert not res.ok and res.reason == "branch_flip", res.report()
    assert np.array_equal(res.q, home)  # refused: the seed comes back unchanged
    assert ik.solve(p, r, home, max_jump=2.0).ok  # the pose itself is reachable
    res = ik.solve(np.array([2.0, 0.0, 1.0]), r, home)
    assert not res.ok and res.reason == "not_converged"
    b.close()


def test_eef_refusals_cost_no_step(tmp_path, pkg):
    ep = session(pkg, tmp_path)
    sim = ep.backend.sim
    q0 = sim.q()
    # out of reach
    r = ep.handle({"op": "act", "action": [2.0, 0.0, 1.0, *DOWN, 1.0], "repeat": 5})
    assert not r["ok"] and "unreachable" in r["error"] and "no step was used" in r["error"], r
    assert ep.steps == 0 and np.allclose(sim.q(), q0, atol=1e-6)
    # a turn of the wrist past joint 7's range
    st = ep.backend.observe()
    rpy = st["eef_rpy"]
    r = ep.handle({"op": "act", "action": [*st["hand_pos"], rpy[0], rpy[1], rpy[2] - 2.6, 1.0]})
    assert not r["ok"] and "joint_limit" in r["error"], r
    # the same refusal through move_to_pose: no step, nothing moved
    r = ep.handle({"op": "skill", "name": "move_to_pose", "args": [*st["hand_pos"], rpy[0], rpy[1], rpy[2] - 2.6]})
    assert r["ok"] and r["result"]["refused"] == "joint_limit" and r["result"]["executed_steps"] == 0, r
    assert ep.steps == 0 and np.allclose(sim.q(), q0, atol=1e-6)
    metric("eef_refusals", ep.backend.session_summary()["ik_refusals"])
    ep.backend.close()


# ---- pick and place (EEF), judged by the goal plugin -------------------------------------------------------------------
def test_eef_pick_and_place(tmp_path, pkg):
    ep = session(pkg, tmp_path)
    b = ep.backend
    sim = b.sim
    cx, cy, cz = testscene.CUBE_POS
    px, py, _ = testscene.PLACE_POS
    z_grasp = cz + 0.005

    def go(x, y, z, *g):
        r = ep.handle({"op": "skill", "name": "move_to_pose", "args": [x, y, z, *DOWN, *g]})
        assert r["ok"] and r["result"]["reached"], r
        return r

    go(cx, cy, cz + 0.15, 1)
    go(cx, cy, z_grasp)
    close_ticks, force = None, []
    for k in range(40):
        r = ep.handle({"op": "act", "action": [cx, cy, z_grasp, *DOWN, 0.0]})
        assert r["ok"], r
        force.append(sim.pad_force())
        if close_ticks is None and force[-1] > 5.0:
            close_ticks = k + 1
    metric("gripper_contact_after_ticks", close_ticks)
    metric("gripper_pad_force_total_n", round(float(np.mean(force[-10:])), 1))
    metric("gripper_open_on_cube", b.observe()["gripper_open"])
    assert force[-1] > 20.0
    go(cx, cy, cz + 0.15)
    assert sim.data.body("cube").xpos[2] > cz + 0.1, "the cube was not lifted"
    assert b.observe()["gripper_open"] < 0.6  # still holding it (move_to_pose without G keeps the command)
    go(px, py, cz + 0.15)
    go(px, py, z_grasp + 0.003)
    r = ep.handle({"op": "grip", "value": 1, "steps": 25})
    assert r["ok"]
    go(px, py, cz + 0.15)
    metric("pick_and_place_steps", ep.steps)
    lamp = sim.model.geom("table/lamp").id
    assert sim.model.geom_rgba[lamp][0] == pytest.approx(1.0)  # the behaviour plugin lit the lamp
    assert sim.goal_obj.updates == ep.steps
    r = ep.handle({"op": "done", "text": "placed"})
    assert r["ok"] and ep.result["success"] is True, ep.result
    assert ep.result["session"]["goal_success"] is True
    metric("control_steps_incl_settle", ep.result["session"]["control_steps"])
    assert ep.result["session"]["control_steps"] == ep.steps + 25  # the session settles the backend's 25 steps
    b.close()


def test_builtin_move_to_keeps_grip(tmp_path, pkg):
    ep = session(pkg, tmp_path)
    hp = ep.backend.observe()["hand_pos"]
    r = ep.handle({"op": "skill", "name": "move_to_pose", "args": [hp[0] + 0.1, hp[1], hp[2] - 0.2, *DOWN]})
    assert r["ok"] and r["result"]["reached"], r
    r = ep.handle({"op": "grip", "value": 0, "steps": 30})
    assert r["ok"] and r["result"]["state"]["gripper_open"] < 0.05
    r = ep.handle({"op": "move_to", "pos": [hp[0], hp[1], hp[2] - 0.1]})
    assert r["ok"] and r["result"]["reached"], r
    assert r["result"]["state"]["gripper_open"] < 0.05  # move_to without a grip kept the fingers closed
    ep.backend.close()


# ---- plugins -----------------------------------------------------------------------------------------------------------
def test_goal_plugin_must_be_read_only(tmp_path, pkg):
    bad = copy_pkg(pkg, tmp_path / "writer")
    g = (bad / "plugin" / "goal.py").read_text()
    (bad / "plugin" / "goal.py").write_text(
        g.replace("self.updates += 1", "self.updates += 1\n        world.data.qvel[0] += 0.1")
    )
    P.write_files_map(bad)
    b = make(bad)
    with pytest.raises(InternalError) as e:
        b.step([0.5, 0.0, 1.1, *DOWN, 1.0])
    assert "internal error" in str(e.value) and "goal" not in str(e.value)
    assert "changed the simulation state" in b.session_summary()["infrastructure_error"]
    with pytest.raises(InternalError):
        b.step([])
    b.close()


def test_plugin_exception_is_neutral(tmp_path, pkg):
    bad = copy_pkg(pkg, tmp_path / "raiser")
    g = (bad / "plugin" / "behaviour.py").read_text()
    (bad / "plugin" / "behaviour.py").write_text(
        g.replace("self.calls += 1", f"self.calls += 1\n        if self.calls > 30: raise RuntimeError('{SLUG}')")
    )
    P.write_files_map(bad)
    ep = session(bad, tmp_path)
    r = ep.handle({"op": "act", "action": [0.5, 0.0, 1.1, *DOWN, 1.0], "repeat": 10})
    assert not r["ok"] and SLUG not in json.dumps(r) and "internal error" in r["error"], r
    assert SLUG in ep.backend.session_summary()["infrastructure_error"]  # recorded for the researcher only
    ep.backend.close()


# ---- cameras -----------------------------------------------------------------------------------------------------------
def _project(cam: dict, p) -> tuple[float, float]:
    u, v, w = np.asarray(cam["projection"]) @ np.r_[p, 1.0]
    return u / w, v / w


def test_cameras_render_and_projection(tmp_path, pkg):
    from robouse.core.cameras import mujoco_camera

    b = make(pkg)
    try:
        b.render()
    except Exception as e:  # pragma: no cover - depends on the machine's OpenGL
        pytest.skip(f"no offscreen OpenGL: {e}")
    w, h = b.render_size
    assert (w, h) == (640, 480)
    m, d = b.mj_model_data()
    cube = np.asarray(testscene.CUBE_POS)
    for name in ("camera_1", "camera_2"):
        b.camera = name
        img = b.render()
        assert img.shape == (h, w, 3) and img.dtype == np.uint8 and img.std() > 5
        cam = mujoco_camera(m, d, name, w, h, image_flipped=b.image_flipped)
        u, v = _project(cam, cube)
        assert 0 <= u < w and 0 <= v < h, (name, u, v)
        r, g, bl = (int(c) for c in img[int(round(v)), int(round(u))])
        metric(f"{name}_cube_pixel_rgb", [r, g, bl])
        assert r > 1.5 * g and r > 1.5 * bl and r > 60, (name, (u, v), (r, g, bl))
        try:
            from PIL import Image

            Image.fromarray(img).save(tmp_path / f"{name}.png")
        except ImportError:  # pragma: no cover
            pass
    # camera_1 moves with the hand, rigidly; camera_2 never moves
    c1 = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "camera_1")
    c2 = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "camera_2")
    bid = int(m.cam_bodyid[c1])
    rel0 = d.xmat[bid].reshape(3, 3).T @ (d.cam_xpos[c1] - d.xpos[bid])
    p1, p2 = d.cam_xpos[c1].copy(), d.cam_xpos[c2].copy()
    for _ in range(60):
        b.step([0.45, 0.2, 1.0, math.pi, 0.2, 0.3, 1.0])
    rel1 = d.xmat[bid].reshape(3, 3).T @ (d.cam_xpos[c1] - d.xpos[bid])
    assert np.linalg.norm(d.cam_xpos[c1] - p1) > 0.05
    assert np.allclose(rel0, rel1, atol=1e-9)
    assert np.array_equal(d.cam_xpos[c2], p2)
    assert m.body(bid).name.startswith("robot/hand/")
    b.close()


# ---- budgets and the session -------------------------------------------------------------------------------------------
def test_budget_enforced_by_session(tmp_path, pkg):
    ep = session(pkg, tmp_path, max_steps=30)
    assert ep.max_steps == 30
    row = [0.5, 0.0, 1.1, *DOWN, 1.0]
    r = ep.handle({"op": "act", "action": row, "repeat": 20})
    assert r["ok"] and r["result"]["executed_steps"] == 20
    r = ep.handle({"op": "act", "action": row, "repeat": 20})
    assert r["ok"] and r["result"]["executed_steps"] == 10
    assert ep.finished and ep.outcome == "budget_exhausted"
    assert not ep.handle({"op": "act", "action": row})["ok"]
    ep.backend.close()
    full = session(pkg, tmp_path)
    assert full.max_steps == 45_000
    full.backend.close()


def test_text_mode_has_no_motion(tmp_path, pkg):
    b = make(pkg, "text")
    assert b.skills() == [] and b.sim.goal_obj is None
    with pytest.raises(ValueError, match="no motion"):
        b.step([0] * 7)
    assert set(b.observe()) >= {"hand_pos", "eef_quat", "eef_rpy", "gripper_open", "joint_pos"}
    b.close()


# ---- policy blindness --------------------------------------------------------------------------------------------------
def test_policy_blindness(tmp_path, pkg):
    """Nothing the agent can read names the package, its path, its files, the scene's names or a task id."""
    forbidden = [
        SLUG,
        str(pkg),
        "scene.xml",
        "episode.json",
        "plugin",
        "sa_",
        "household-episode",
        "cube",
        "table",
        "pad/zone",
        "goal:Goal",
        P.load(pkg).identity[:16],
    ]
    texts = []
    for control in ("eef", "joint", "text"):
        ep = session(
            pkg,
            tmp_path,
            control,
            obs_mode="vision",
            cameras=["camera_1", "camera_2"],
            visible_fields=[
                "hand_pos",
                "eef_quat",
                "eef_rpy",
                "gripper_open",
                "joint_pos",
                "robot_base_pos",
                "robot_forward",
            ],
        )
        info = ep.handle({"op": "info"})["result"]
        assert info.pop("task") == "ep-0123456789abcdef"
        texts.append(json.dumps(info))
        texts.append(json.dumps(ep.handle({"op": "observe"})))
        if control != "text":
            dim = ep.backend.action_spec.dim
            row = [0.5, 0.0, 1.1, *DOWN, 1.0] if control == "eef" else list(ep.backend.sim.q()) + [1.0]
            texts.append(json.dumps(ep.handle({"op": "act", "action": row})))
            texts.append(json.dumps(ep.handle({"op": "act", "action": [9.0] * dim})))
            texts.append(json.dumps(ep.handle({"op": "skill", "name": "nope", "args": []})))
            texts.append(json.dumps(ep.handle({"op": "skill", "name": ep.backend.skills()[-1], "args": ["a"]})))
        else:
            texts.append(json.dumps(ep.handle({"op": "act", "action": [0.0] * 7})))
        texts.append(json.dumps(ep.handle({"op": "done", "text": "finished"})))
        ep.backend.close()
    blob = "\n".join(texts)
    for f in forbidden:
        assert f not in blob, f"{f!r} reached the agent"
