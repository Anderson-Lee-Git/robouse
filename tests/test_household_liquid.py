"""The household liquid extension (liquid contract 1.0.0, CPU SPlisHSPlasH DFSPH) on the synthetic pour package
(household/liquid/testscene.py), following the liquid-validity procedure: configuration refusals, lattice and domain
units, a free-fall control, static containment, an active pour with a spill and a hold tail (ledger, per-label and
per-source volumes, puddle, validity counters, timing), exact reset repeatability, an invalid initial state, both
policy cameras with the reconstructed surface, and the trace/summary hooks.

The simulation tests need the vendored Menagerie models and the pinned SPlisHSPlasH backend (cp312); they skip
without them. Measured numbers go to stdout (`pytest -s`) as `HOUSEHOLD-METRIC name value` lines and, when
ROBOUSE_LIQUID_REPORT names a directory, into liquid_report.json and PNG renders there.
"""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

from robouse.backends.household.liquid import config as C  # noqa: E402
from robouse.backends.household.liquid import meshes, queries  # noqa: E402
from robouse.backends.household.liquid import testscene as T  # noqa: E402
from robouse.backends.household.liquid.domain import LiquidValidityError, SolidBox, StaticDomain  # noqa: E402

REPORT: dict = {}
OUT = os.environ.get("ROBOUSE_LIQUID_REPORT", "").strip()


def metric(name: str, value) -> None:
    print(f"HOUSEHOLD-METRIC {name} {value}")
    REPORT[name] = value


@pytest.fixture(scope="module", autouse=True)
def _report():
    yield
    if OUT and REPORT:
        Path(OUT).mkdir(parents=True, exist_ok=True)
        p = Path(OUT) / "liquid_report.json"
        old = json.loads(p.read_text()) if p.exists() else {}
        old.update(REPORT)
        p.write_text(json.dumps(old, indent=2, default=float) + "\n")


# ---- units (no backend) ----------------------------------------------------------------------------------------------
def test_config_parses_and_refuses():
    good = T.liquid_block("pour")
    cfg = C.parse(copy.deepcopy(good))
    assert cfg.contract == "1.0.0" and abs(cfg.material.particle_ml - 0.015625) < 1e-12
    bad = []
    d = copy.deepcopy(good)
    d["contract"] = "0.4.3"
    bad.append(d)
    d = copy.deepcopy(good)
    del d["settle"]
    bad.append(d)  # no defaults: every key is explicit
    d = copy.deepcopy(good)
    d["extra"] = 1
    bad.append(d)
    d = copy.deepcopy(good)
    d["solver"]["dt_max_s"] = 0.01
    bad.append(d)
    d = copy.deepcopy(good)
    d["domain"]["floor_geom"] = "counter/nowhere"
    bad.append(d)
    d = copy.deepcopy(good)
    d["containers"][0]["inside_profile"] = [[0.03, 0.05], [0.03, 0.01]]
    bad.append(d)  # z must increase
    d = copy.deepcopy(good)
    d["sources"].append({"name": "spill", "puddle": {"polygon_xy": [[0, 0], [0.1, 0], [0, 0.1]], "volume_ml": 5}})
    d["surface"] = None
    bad.append(d)  # a puddle needs a surface
    d = copy.deepcopy(good)
    d["sleep"] = "puddle"
    bad.append(d)  # container sources cannot sleep as a puddle
    d = copy.deepcopy(good)
    d["containers"][0]["name"] = "robot/cup"
    bad.append(d)
    d = copy.deepcopy(good)
    d["material"]["surface_tension"]["method"] = "magic"
    bad.append(d)
    for d in bad:
        with pytest.raises(C.LiquidConfigError):
            C.parse(d)


def test_profile_fill_keeps_clearance():
    prof = T.cup_inside()
    h = 0.0025
    x = meshes.profile_fill(prof, 9600, h)
    assert len(x) == 9600
    r = np.hypot(x[:, 0], x[:, 1])
    assert np.all(r <= meshes.radius_at(prof, x[:, 2]) - h + 1e-9)
    assert x[:, 2].min() >= prof[0][1] + h - 1e-12 and x[:, 2].max() <= prof[-1][1] - h / 2 + 1e-12
    d = np.linalg.norm(x[:200, None] - x[None, :200], axis=2) + np.eye(200)
    assert d.min() >= h - 1e-9
    with pytest.raises(ValueError):
        meshes.profile_fill(prof, 10**6, h)
    fill_h = x[:, 2].max() - x[:, 2].min() + h
    metric("unit.cup_fill_height_m", round(float(fill_h), 4))


def test_domain_contact_and_validity():
    floor = SolidBox("floor", [0, 0, -0.05], np.eye(3), [2, 2, 0.05])
    top = SolidBox("top", [0.6, 0, 0.375], np.eye(3), [0.35, 0.6, 0.375])
    dom = StaticDomain([floor, top], 0.00125, "floor")
    start = np.array([[0.6, 0.0, 0.76], [1.2, 0.0, 0.01]])
    end = np.array([[0.6, 0.0, 0.74], [1.2, 0.0, -0.01]])
    vel = np.array([[0.0, 0.0, -1.0], [0.3, 0.0, -1.0]])
    x, v = dom.resolve(start, end, vel)
    assert x[0, 2] >= 0.75 + 0.00125 - 1e-6 and x[1, 2] >= 0.00125 - 1e-6
    assert v[0, 2] == 0 and v[1, 2] == 0 and v[1, 0] == pytest.approx(0.3)  # only the inward normal is removed
    assert dom.contacts == {"top": 1, "floor": 1}
    with pytest.raises(LiquidValidityError):
        dom.validate([[0.6, 0.0, 0.5]])
    with pytest.raises(LiquidValidityError):
        dom.validate([[3.0, 0.0, 0.1]])
    dom.validate([[0.6, 0.0, 0.751]])


def test_partition_labels():
    cup = queries.Container("cup", T.cup_inside(), 0.0015)
    surf = queries.Surface(0.75, (0.45, -0.33), (0.95, 0.17))
    pose = (np.array([0.7, -0.2, 0.75]), np.eye(3))
    pts = np.array([[0.7, -0.2, 0.77], [0.6, 0.0, 0.752], [2.0, 2.0, 0.01], [0.7, 0.0, 0.70], [np.nan, 0, 0]])
    lab = queries.partition(pts, {"cup": cup}, {"cup": pose}, surf, 0.00125)
    assert list(lab) == ["cup", "surface", "elsewhere", "elsewhere", "nonfinite"]


# ---- simulation ------------------------------------------------------------------------------------------------------
def _sim_or_skip():
    from robouse.backends.household import assets

    try:
        assets.model_root()
    except FileNotFoundError as e:  # pragma: no cover
        pytest.skip(f"household models not fetched: {e}")
    from robouse.backends.household.liquid import solver

    try:
        solver.check_backend(T.liquid_block("pour")["backend"])
    except Exception as e:
        pytest.skip(f"liquid backend unavailable: {e}")


def _make(tmp_path, variant, **kw):
    from robouse.backends.household import package as P
    from robouse.backends.household.sim import HouseholdSim

    root = T.write(tmp_path / variant, variant, **kw)
    sim = HouseholdSim(P.load(root))
    t0 = time.perf_counter()
    try:
        sim.reset()
    except Exception:
        pytest.fail(f"reset failed: {sim.infra_error}")
    return sim, time.perf_counter() - t0


def _tick(sim):
    from robouse.backends.household.sim import InternalError

    try:
        sim.tick_tracker()
    except InternalError:
        pytest.fail(f"step failed at control {sim.world.step}: {sim.infra_error}")


def _ext(sim):
    return sim.world.extensions["liquid"]


def _render(sim, cam, name=None):
    """(image, liquid pixels): the liquid pixels are those that change when the liquid surface geom is hidden."""
    import mujoco

    img = sim.render(cam, 640, 480)  # the sim uploads the liquid surface (before_render)
    r = sim._renderers[(640, 480)]
    r.update_scene(sim.data, camera=cam)
    gid = mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_GEOM, "liquid/surface")
    for i in range(r.scene.ngeom):
        g = r.scene.geoms[i]
        if g.objtype == mujoco.mjtObj.mjOBJ_GEOM and g.objid == gid:
            g.rgba[3] = 0.0
    bare = r.render().copy()
    px = int((np.abs(img.astype(int) - bare.astype(int)).sum(axis=2) > 30).sum())
    if OUT and name:
        from PIL import Image

        Path(OUT).mkdir(parents=True, exist_ok=True)
        Image.fromarray(img).save(Path(OUT) / f"{name}.png")
    return img, px


def _volumes(sim):
    v = sim.world.extensions["liquid"]
    return {k: round(x, 3) for k, x in v.volumes_ml().items()}


def test_refuses_gpu_and_bad_backend(tmp_path):
    _sim_or_skip()
    from robouse.backends.household import package as P
    from robouse.backends.household.package import PackageError

    root = T.write(tmp_path / "gpu", "pour")
    ep = json.loads((root / "episode.json").read_text())
    ep["compute"] = {"device": "gpu"}
    (root / "episode.json").write_text(json.dumps(ep))
    from robouse.backends.household.package import write_files_map

    write_files_map(root)
    with pytest.raises(PackageError):
        P.load(root)
    bad = T.liquid_block("pour")
    bad["backend"] = "splishsplash-9.9.9-unknown"
    root = T.write(tmp_path / "badbackend", "pour", liquid=bad)
    with pytest.raises(PackageError):
        from robouse.backends.household.sim import HouseholdSim

        HouseholdSim(P.load(root))


def test_embedded_initial_state_is_infrastructure_error(tmp_path):
    _sim_or_skip()
    from robouse.backends.household import package as P
    from robouse.backends.household.sim import HouseholdSim, InternalError

    root = T.write(tmp_path / "embedded", "embedded")
    sim = HouseholdSim(P.load(root))
    with pytest.raises(InternalError):
        sim.reset()
    metric("embedded.infra_error", json.dumps(sim.infra_error))
    assert "static solid" in (sim.infra_error or "")
    sim.close()


def test_free_fall_control(tmp_path):
    _sim_or_skip()
    sim, init_s = _make(tmp_path, "invert")
    f = _ext(sim).fluid
    x0 = f.positions()
    zmin0 = float(x0[:, 2].min())
    # the front: the lowest two layers (at the mouth) near the axis, which touches no wall while it falls
    front = (x0[:, 2] < zmin0 + 1.5 * f.spacing) & (np.hypot(x0[:, 0] - T.CUP_XY[0], x0[:, 1] - T.CUP_XY[1]) < 0.02)
    ts, zs, zf = [0.0], [float(x0[:, 2].mean())], [float(x0[front, 2].mean())]
    while f.time < 0.14 - 1e-9:
        _tick(sim)
        x = f.positions()
        ts.append(f.time)
        zs.append(float(x[:, 2].mean()))
        zf.append(float(x[front, 2].mean()))
    t = np.array(ts)
    # z = z0 + v0 t - a t^2 / 2 (least squares)
    A = np.column_stack([np.ones_like(t), t, -0.5 * t**2])
    a = float(np.linalg.lstsq(A, np.array(zs), rcond=None)[0][2])
    af = float(np.linalg.lstsq(A, np.array(zf), rcond=None)[0][2])
    metric("freefall.lowest_drop_m", round(zmin0 - T.TOP, 4))
    metric("freefall.front_particles", int(front.sum()))
    metric("freefall.front_accel_over_g", round(af / 9.81, 4))
    metric("freefall.centroid_accel_over_g", round(a / 9.81, 4))
    assert abs(af / 9.81 - 1) < 0.05  # the free front falls at g
    assert 0.7 < a / 9.81 < 1.02  # the column is slowed by the wall it slides along (boundary viscosity), never sped up
    sim.close()


def test_drop_impact_stays_valid(tmp_path):
    """150 ml released upside down 3 cm above the counter: valid for 1 s, every particle accounted, mostly on the
    counter. (A 12 cm release is outside the validated envelope: its rebound jet trips the dt_min guard.)"""
    _sim_or_skip()
    sim, _ = _make(tmp_path, "drop")
    f = _ext(sim).fluid
    while f.time < 1.0 - 1e-9:
        _tick(sim)
    s = sim.extension_summary()["liquid"]
    vol = _volumes(sim)
    metric("drop.volumes_ml_1s", json.dumps(vol))
    metric("drop.validity", json.dumps(s["validity"], default=float))
    assert s["validity"]["invalid_reason"] is None and "ledger_error" not in s["validity"]
    assert sum(s["counts"].values()) == s["particles"] and s["counts"].get("nonfinite", 0) == 0
    assert vol.get("cup", 0) < 5.0  # an upside-down cup keeps a wall film only (2.1 ml measured)
    assert sum(vol.values()) == pytest.approx(T.FILL_ML, abs=0.01)
    # most of the impact stays on the counter footprint; SPH spray (no air drag) may leave it, within the walls
    assert vol.get("surface", 0) > 0.5 * T.FILL_ML
    sim.close()


def test_static_containment(tmp_path):
    _sim_or_skip()
    sim, init_s = _make(tmp_path, "rest")
    ext = _ext(sim)
    f = ext.fluid
    n = f.n
    metric("rest.particles", n)
    metric("rest.init_s", round(init_s, 2))
    metric("rest.settle", json.dumps(ext.settle_report, default=float))
    assert n * f.mat.particle_ml == pytest.approx(T.FILL_ML, abs=f.mat.particle_ml)
    z0 = f.positions()[:, 2].copy()
    c0 = time.perf_counter()
    while f.time < 0.5 - 1e-9:
        _tick(sim)
    wall = time.perf_counter() - c0
    v = np.linalg.norm(f.velocities(), axis=1)
    s = sim.extension_summary()["liquid"]
    metric("rest.volumes_ml_0_5s", json.dumps(_volumes(sim)))
    metric("rest.max_speed_end_m_s", round(float(v.max()), 5))
    metric("rest.mean_speed_end_m_s", round(float(v.mean()), 6))
    metric("rest.mean_level_change_mm", round(float((f.positions()[:, 2] - z0).mean() * 1000), 4))
    metric("rest.sph_steps", s["sph_steps"])
    metric("rest.wall_s_per_sim_s", round(wall / 0.5, 3))
    assert s["counts"] == {"cup": n}
    assert float(v.max()) < 0.05
    assert s["validity"]["invalid_reason"] is None
    _, px = _render(sim, "camera_2", "rest_camera_2")
    metric("rest.camera_2_liquid_pixels", px)
    assert px > 50
    sim.close()


REPEAT_AT = 60  # controls (1.2 s, mid-tilt): positions compared after an exact reset


def _run_pour(sim, *, record=True, frames=None, steps=None, snaps=None):
    ext = _ext(sim)
    f = ext.fluid
    steps = steps or int(round(sum(T.PHASES) / 0.02))
    timeline = []
    marks = {int(round(x / 0.02)) for x in np.cumsum(T.PHASES)}
    c0 = time.perf_counter()
    for k in range(1, steps + 1):
        _tick(sim)
        if record and (k % 25 == 0 or k in marks):
            timeline.append(
                {
                    "t": round(f.time, 3),
                    **{key: round(x, 2) for key, x in sim.world.extensions["liquid"].volumes_ml().items()},
                }
            )
        if snaps is not None and k == REPEAT_AT:
            snaps.append(f.positions().copy())
        if frames is not None and k in frames:
            for cam in ("camera_1", "camera_2"):
                frames[k][cam] = _render(sim, cam, f"pour_{cam}_{k:04d}")
    return timeline, time.perf_counter() - c0, steps


def test_pour_spill_and_reset_repeatability(tmp_path):
    _sim_or_skip()
    sim, init_s = _make(tmp_path, "pour")
    ext = _ext(sim)
    f = ext.fluid
    frames = {k: {} for k in (60, 110, 255)}
    snaps = []
    trace = sim.extension_trace()
    assert set(trace) == {"liquid"} and trace["liquid"]["counts"] == {"cup": f.n}
    timeline, wall, steps = _run_pour(sim, frames=frames, snaps=snaps)
    s = sim.extension_summary()["liquid"]
    vol = {k: round(v, 3) for k, v in s["volumes_ml"].items()}
    metric("pour.init_s", round(init_s, 2))
    metric("pour.control_steps", steps)
    metric("pour.wall_s", round(wall, 1))
    metric("pour.wall_s_per_sim_s", round(wall / (steps * 0.02), 3))
    metric("pour.particles", s["particles"])
    metric("pour.particle_ml", s["particle_ml"])
    metric("pour.volumes_ml_end", json.dumps(vol))
    metric("pour.source_counts_end", json.dumps(s["source_counts"]))
    metric("pour.puddle_end", json.dumps(s["puddle"], default=float))
    metric("pour.timeline", json.dumps(timeline))
    metric("pour.validity", json.dumps(s["validity"], default=float))
    metric("pour.timing", json.dumps(s["timing"], default=float))
    metric("pour.surface_mesh", json.dumps(s["surface_mesh"], default=float))
    metric("pour.sph_steps", s["sph_steps"])
    metric("pour.settle", json.dumps(s["settle"], default=float))
    for k, cams in frames.items():
        for cam, (_, px) in cams.items():
            metric(f"pour.{cam}_liquid_pixels_{k}", px)
    # ledger: every particle is counted once, nothing is lost or non-finite
    assert s["validity"]["invalid_reason"] is None and "ledger_error" not in s["validity"]
    assert sum(s["counts"].values()) == s["particles"] and s["counts"].get("nonfinite", 0) == 0
    assert sum(vol.values()) == pytest.approx(T.FILL_ML, abs=0.01)
    assert sum(s["source_counts"]["juice"].values()) == s["particles"]
    # the scripted route spills onto the counter and pours into the bowl; the cup keeps a remainder at most
    assert vol.get("surface", 0) > 1.0
    assert vol.get("bowl", 0) > 20.0
    assert s["validity"]["maximum_accepted_displacement_m"] <= f.spacing
    # the hold tail: the bowl's content is at rest at the end
    v = np.linalg.norm(f.velocities()[f.free_mask], axis=1)
    metric("pour.max_speed_end_m_s", round(float(v.max()), 4))
    metric("pour.p99_speed_end_m_s", round(float(np.percentile(v, 99)), 4))
    # the camera_2 view shows the liquid in mid-pour
    assert frames[110]["camera_2"][1] > 50

    # exact reset: the native fluid is reused and the same route gives bit-identical positions (checked mid-tilt)
    x1 = snaps[0]
    sim.reset()
    ext2 = _ext(sim)
    assert ext2.reused and ext2.fluid is f
    assert sim.world.extensions["liquid"].counts() == {"cup": f.n}
    _run_pour(sim, record=False, steps=REPEAT_AT)
    x2 = f.positions().copy()
    diff = float(np.abs(x2 - x1).max())
    metric("pour.reset_max_abs_diff_m", diff)
    assert diff == 0.0
    sim.close()


# ---- per-source colour (liquid contract 1.1.0) -----------------------------------------------------------------------
JUICE, WATER = [1.0, 0.56, 0.1, 0.93], [0.15, 0.45, 1.0, 0.8]


def _two_sources(colours=True, variant="rest") -> dict:
    """The test package's liquid with a second source (30 ml of water in the bowl); contract 1.1.0."""
    d = T.liquid_block(variant)
    d["contract"] = "1.1.0"
    d["sources"].append({"name": "water", "container": "bowl", "fill_ml": 30.0})
    if colours:
        d["sources"][1]["rgba"] = WATER
    return d


def test_source_rgba_config():
    cfg = C.parse(_two_sources())
    assert cfg.contract == "1.1.0" and cfg.per_source_colour
    assert cfg.sources[0].rgba is None and cfg.sources[1].rgba == tuple(WATER)
    assert cfg.source_rgba() == {"juice": tuple(JUICE), "water": tuple(WATER)}  # juice falls back to material.rgba
    plain = C.parse(_two_sources(colours=False))
    assert not plain.per_source_colour and all(s.rgba is None for s in plain.sources)
    old = C.parse(T.liquid_block("pour"))
    assert old.contract == "1.0.0" and not old.per_source_colour
    bad = []
    d = _two_sources()
    d["contract"] = "1.0.0"
    bad.append(d)  # a source rgba needs 1.1.0
    for v in ([0.1, 0.2, 0.3], [0.1, 0.2, 0.3, 1.5], "blue", [0.1, 0.2, float("nan"), 1]):
        d = _two_sources()
        d["sources"][1]["rgba"] = v
        bad.append(d)
    d = _two_sources()
    d["contract"] = "1.2.0"
    bad.append(d)
    for d in bad:
        with pytest.raises(C.LiquidConfigError):
            C.parse(d)


def _surface_spec(cfg):
    from robouse.backends.household.liquid import surface

    spec = mujoco.MjSpec()
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, 0.1])
    if cfg.per_source_colour:
        for name, rgba in cfg.source_rgba().items():
            surface.add_to_spec(spec, rgba, source=name)
    else:
        surface.add_to_spec(spec, cfg.material.rgba)
    return spec.compile()


def test_source_rgba_compiles_one_material_per_source():
    from robouse.backends.household.liquid import surface

    def named(m, kind, n):
        return [mujoco.mj_id2name(m, kind, i) for i in range(n)]

    M = mujoco.mjtObj
    m = _surface_spec(C.parse(_two_sources()))
    assert named(m, M.mjOBJ_MATERIAL, m.nmat) == ["liquid/surface/juice", "liquid/surface/water"]
    assert named(m, M.mjOBJ_MESH, m.nmesh) == ["liquid/surface/juice", "liquid/surface/water"]
    for src, rgba in (("juice", JUICE), ("water", WATER)):
        mesh, geom, mat = surface.names(src)
        g = mujoco.mj_name2id(m, M.mjOBJ_GEOM, geom)
        assert m.geom_matid[g] == mujoco.mj_name2id(m, M.mjOBJ_MATERIAL, mat)
        assert m.geom_contype[g] == 0 and m.geom_conaffinity[g] == 0
        np.testing.assert_allclose(m.mat_rgba[m.geom_matid[g]], rgba, atol=1e-6)
    # no per-source rgba (1.0.0, or 1.1.0 without one): the single surface of contract 1.0.0, unchanged
    for d in (T.liquid_block("pour"), _two_sources(colours=False)):
        m = _surface_spec(C.parse(d))
        assert named(m, M.mjOBJ_MATERIAL, m.nmat) == ["liquid/surface"]
        assert named(m, M.mjOBJ_MESH, m.nmesh) == ["liquid/surface"]
        assert mujoco.mj_name2id(m, M.mjOBJ_GEOM, "liquid/surface") >= 0
        np.testing.assert_allclose(m.mat_rgba[0], JUICE, atol=1e-6)


def _hidden_render(sim, cam, geoms):
    """camera render with the named geoms made transparent."""
    r = sim._renderers[(640, 480)]
    r.update_scene(sim.data, camera=cam)
    ids = {mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_GEOM, g) for g in geoms}
    for i in range(r.scene.ngeom):
        g = r.scene.geoms[i]
        if g.objtype == mujoco.mjtObj.mjOBJ_GEOM and g.objid in ids:
            g.rgba[3] = 0.0
    return r.render().copy()


def test_two_sources_render_in_their_colours_physics_unchanged(tmp_path):
    """Juice in the cup, water in the bowl: each source's surface is reconstructed from its own particles and drawn
    in its own colour, and the particles move bit for bit as without per-source colours."""
    _sim_or_skip()
    snaps = {}
    for colours in (True, False):
        sim, _ = _make(tmp_path / str(colours), "rest", liquid=_two_sources(colours))
        ext = _ext(sim)
        for _ in range(10):
            _tick(sim)
        snaps[colours] = ext.fluid.positions().copy()
        assert ext.source_counts() == {"juice": {"cup": 9600}, "water": {"bowl": 1920}}
        img = sim.render("camera_2", 640, 480)
        s = sim.extension_summary()["liquid"]
        if not colours:
            assert [x[0] for x in ext.surfaces] == [None] and "sources" not in s["surface_mesh"]
            sim.close()
            continue
        assert [x[0] for x in ext.surfaces] == ["juice", "water"]
        mesh = s["surface_mesh"]["sources"]
        metric("colour.surface_mesh", json.dumps(mesh, default=float))
        assert mesh["juice"]["faces"] > 0 and mesh["water"]["faces"] > 0
        # geometry: each surface encloses its own source's particles only
        for src, (a, b), r in ext.surfaces:
            v = sim.model.mesh_vert[r.va : r.va + mesh[src]["verts"]]
            x = ext.fluid.positions()[a:b]
            assert np.all(v.min(0) > x.min(0) - 0.01) and np.all(v.max(0) < x.max(0) + 0.01)
        # render: hiding one source's surface changes pixels towards that source's colour
        for src, rgba in (("juice", JUICE), ("water", WATER)):
            bare = _hidden_render(sim, "camera_2", [f"liquid/surface/{src}"])
            diff = np.abs(img.astype(int) - bare.astype(int)).sum(axis=2) > 30
            metric(f"colour.camera_2_{src}_pixels", int(diff.sum()))
            assert diff.sum() > 50
            mean = img[diff].astype(float).mean(0)
            blue_minus_red = mean[2] - mean[0]
            metric(f"colour.camera_2_{src}_mean_rgb", json.dumps([round(float(c), 1) for c in mean]))
            assert (blue_minus_red > 0) == (rgba[2] > rgba[0])
        if OUT:
            from PIL import Image

            Path(OUT).mkdir(parents=True, exist_ok=True)
            Image.fromarray(img).save(Path(OUT) / "colour_camera_2.png")
        sim.close()
    assert np.array_equal(snaps[True], snaps[False])
