"""Household liquid contract 1.2.0: the DFSPH step on a CUDA GPU (NVIDIA Warp), host-side validity and accounting.

Without Warp or CUDA only the configuration, package and refusal tests run; the simulation tests skip. The CPU/GPU
fixture gate (region and uptake volumes per sample, validity outcomes, GPU run-to-run identity) and timing are the
evidence report's, not these tests'. Measured numbers go to stdout as `HOUSEHOLD-GPU-METRIC name value` lines.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

from robouse.backends.household.liquid import config as C  # noqa: E402
from robouse.backends.household.liquid import testscene as T  # noqa: E402
from robouse.backends.household.liquid.gpu import solver as G  # noqa: E402

JUICE, WATER = [1.0, 0.56, 0.1, 0.93], [0.15, 0.45, 1.0, 0.8]


def metric(name, value):
    print(f"HOUSEHOLD-GPU-METRIC {name} {value}")


def _models_or_skip():
    from robouse.backends.household import assets

    try:
        assets.model_root()
    except FileNotFoundError as e:  # pragma: no cover
        pytest.skip(f"household models not fetched: {e}")


def _cuda():
    """(available, reason): Warp at the pinned version with a CUDA device."""
    try:
        G.warp_device(T.GPU_BACKEND)
    except Exception as e:
        return False, str(e)
    return True, ""


def _gpu_or_skip():
    _models_or_skip()
    ok, why = _cuda()
    if not ok:
        pytest.skip(f"no GPU liquid: {why}")


def _make(tmp_path, variant, liquid=None):
    from robouse.backends.household import package as P
    from robouse.backends.household.sim import HouseholdSim, InternalError

    root = T.write(tmp_path / variant, variant, liquid=liquid, gpu=True)
    sim = HouseholdSim(P.load(root))
    try:
        sim.reset()
    except InternalError:
        pytest.fail(f"reset failed: {sim.infra_error}")
    return sim


def _tick(sim, n=1):
    from robouse.backends.household.sim import InternalError

    for _ in range(n):
        try:
            sim.tick_tracker()
        except InternalError:
            pytest.fail(f"step failed at control {sim.world.step}: {sim.infra_error}")


def _ext(sim):
    return sim.world.extensions["liquid"]


# ---- configuration, package and backend pin (no GPU) -----------------------------------------------------------------
def test_gpu_contract_config():
    cfg = C.parse(T.gpu_block(T.liquid_block("pour")))
    assert cfg.contract == "1.2.0" and cfg.device == "gpu" and cfg.backend == T.GPU_BACKEND
    assert C.parse(T.liquid_block("pour")).device == "cpu"
    two = T.gpu_block(T.liquid_block("rest"))
    two["sources"].append({"name": "water", "puddle": {"polygon_xy": T.WIPE_PUDDLE, "volume_ml": 15}, "rgba": WATER})
    assert C.parse(two).per_source_colour  # 1.2.0 keeps 1.1.0's per-source colour
    bad = []
    d = T.liquid_block("pour")
    d["contract"] = "1.2.0"
    bad.append(d)  # 1.2.0 needs a GPU backend
    for contract in ("1.0.0", "1.1.0"):
        d = T.gpu_block(T.liquid_block("pour"))
        d["contract"] = contract
        bad.append(d)  # a GPU backend needs 1.2.0
    d = T.gpu_block(T.liquid_block("pour"))
    d["material"]["surface_tension"] = {"method": "akinci2013", "coefficient": 0.1, "boundary_adhesion": 0.0}
    bad.append(d)  # the GPU solver implements none and jeske2023 only
    d = T.gpu_block(T.liquid_block("pour"))
    d["material"]["surface_tension"] = {"method": "jeske2023", "coefficient": 0.1, "boundary_adhesion": 0.1}
    bad.append(d)  # and no adhesion
    for d in bad:
        with pytest.raises(C.LiquidConfigError):
            C.parse(d)
    ok = T.gpu_block(T.liquid_block("pour"))
    ok["material"]["surface_tension"] = {"method": "jeske2023", "coefficient": 0.1, "boundary_adhesion": 0.0}
    assert C.parse(ok).material.tension == 0.1


def test_compute_device_matches_liquid_contract(tmp_path):
    from robouse.backends.household import package as P
    from robouse.backends.household.package import PackageError

    ep = P.load(T.write(tmp_path / "gpu", "pour", gpu=True))
    assert ep.extensions["liquid"]["contract"] == "1.2.0"

    def edit(root, fn):
        d = json.loads((root / "episode.json").read_text())
        fn(d)
        (root / "episode.json").write_text(json.dumps(d))
        P.write_files_map(root)
        return root

    refused = [
        edit(T.write(tmp_path / "a", "pour", gpu=True), lambda d: d.update(compute={"device": "cpu"})),
        edit(T.write(tmp_path / "b", "pour"), lambda d: d.update(compute={"device": "gpu"})),
        edit(T.write(tmp_path / "c", "pour"), lambda d: (d.pop("liquid"), d.update(compute={"device": "gpu"}))),
        edit(T.write(tmp_path / "d", "pour", gpu=True), lambda d: d.update(compute={"device": "cuda"})),
    ]
    for root in refused:
        with pytest.raises(PackageError):
            P.load(root)


def test_gpu_backend_pin_and_kernel_sources():
    pn = G.check_backend(T.GPU_BACKEND)
    assert (
        pn["device"] == "cuda"
        and pn["warp"] == "1.19.0"
        and set(pn["sources"])
        == {
            "kernels.py",
            "sampling.py",
            "solver.py",
        }
    )
    assert G.pin_sources() == pn["sources"]
    assert G.is_gpu(T.GPU_BACKEND) and not G.is_gpu(T.liquid_block("pour")["backend"])
    # the kernels are the adopted RoboCasa liquid 0.5.0 GPU kernels, byte for byte (when that backend is present)
    adopted = Path(G.HERE).parents[2] / "robocasa" / "physics" / "liquid" / "gpu"
    if adopted.is_dir():
        for rel in ("kernels.py", "sampling.py"):
            assert hashlib.sha256((adopted / rel).read_bytes()).hexdigest() == pn["sources"][rel]
    with pytest.raises(ValueError):
        G.check_backend(T.liquid_block("pour")["backend"])


def test_no_cuda_is_an_infrastructure_error(tmp_path):
    """Without Warp or a CUDA device the GPU liquid refuses when the episode starts: an infrastructure error, never a
    CPU fallback."""
    _models_or_skip()
    ok, _ = _cuda()
    if ok:
        pytest.skip("a CUDA device is available")
    from robouse.backends.household import package as P
    from robouse.backends.household.sim import HouseholdSim, InternalError

    sim = HouseholdSim(P.load(T.write(tmp_path / "rest", "rest", gpu=True)))
    with pytest.raises(InternalError):
        sim.reset()
    metric("nocuda.infra_error", json.dumps(sim.infra_error))
    assert "CUDA" in sim.infra_error or "Warp" in sim.infra_error
    sim.close()


# ---- on the GPU ------------------------------------------------------------------------------------------------------
def test_gpu_static_containment_and_exact_reset(tmp_path):
    _gpu_or_skip()
    sim = _make(tmp_path, "rest")
    ext = _ext(sim)
    f = ext.fluid
    assert type(f).__name__ == "WarpFluid" and f.backend["device"] == "cuda"
    n = f.n
    _tick(sim, 25)
    s = sim.extension_summary()["liquid"]
    v = np.linalg.norm(f.velocities(), axis=1)
    metric("gpu.rest.counts", json.dumps(s["counts"]))
    metric("gpu.rest.max_speed_m_s", float(v.max()))
    metric("gpu.rest.device_timing", json.dumps(s["device_timing"], default=float))
    assert s["contract"] == "1.2.0" and s["counts"] == {"cup": n}
    assert s["validity"]["invalid_reason"] is None and float(v.max()) < 0.05
    x1 = f.positions().copy()
    sim.reset()
    assert _ext(sim).reused and _ext(sim).fluid is f
    _tick(sim, 25)
    assert np.array_equal(f.positions(), x1)  # an exact reset repeats bit for bit on the device
    sim.close()


def test_gpu_wipe_absorbs_and_accounts(tmp_path):
    _gpu_or_skip()
    sim = _make(tmp_path, "wipe")
    ext = _ext(sim)
    f = ext.fluid
    _tick(sim, int(round(sum(T.WIPE_PHASES) / 0.02)))
    s = sim.extension_summary()["liquid"]
    metric("gpu.wipe.volumes_ml", json.dumps(s["volumes_ml"]))
    metric("gpu.wipe.absorbers", json.dumps(s["absorbers"], default=float))
    assert s["validity"]["invalid_reason"] is None and "ledger_error" not in s["validity"]
    assert sum(s["counts"].values()) == f.n and s["counts"].get("nonfinite", 0) == 0
    assert s["counts"].get("absorbed:sponge", 0) > 0  # the sponge took up liquid
    assert s["volumes_ml"]["absorbed:sponge"] <= 20.0 + f.mat.particle_ml  # within its capacity
    assert s["source_counts"]["juice"] == {"cup": ext.source_ranges["juice"][1]}  # the tumbler's juice stays put
    sim.close()


def _hidden_render(sim, cam, hide):
    r = sim._renderers[(640, 480)]
    r.update_scene(sim.data, camera=cam)
    ids = {mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_GEOM, n) for n in hide}
    for i in range(r.scene.ngeom):
        g = r.scene.geoms[i]
        if g.objtype == mujoco.mjtObj.mjOBJ_GEOM and g.objid in ids:
            g.rgba[3] = 0.0
    return r.render().copy()


def _two_sources(colours=True) -> dict:
    d = T.gpu_block(T.liquid_block("rest"))
    poly = [[0.84, -0.14], [0.92, -0.14], [0.92, -0.06], [0.84, -0.06]]
    d["sources"] = copy.deepcopy(d["sources"]) + [{"name": "water", "puddle": {"polygon_xy": poly, "volume_ml": 15.0}}]
    if colours:
        d["sources"][1]["rgba"] = WATER
    return d


def test_gpu_two_sources_render_in_their_colours_physics_unchanged(tmp_path):
    """tests/test_household_liquid.py's per-source colour test on liquid contract 1.2.0."""
    _gpu_or_skip()
    snaps = {}
    for colours in (True, False):
        sim = _make(tmp_path / str(colours), "rest", liquid=_two_sources(colours))
        ext = _ext(sim)
        _tick(sim, 10)
        snaps[colours] = ext.fluid.positions().copy()
        counts = ext.source_counts()
        assert counts["juice"] == {"cup": 9600} and counts["water"].get("surface", 0) > 0.9 * 960
        img = sim.render("camera_2", 640, 480)
        s = sim.extension_summary()["liquid"]
        if not colours:
            assert [x[0] for x in ext.surfaces] == [None] and "sources" not in s["surface_mesh"]
            sim.close()
            continue
        assert [x[0] for x in ext.surfaces] == ["juice", "water"]
        mesh = s["surface_mesh"]["sources"]
        assert mesh["juice"]["faces"] > 0 and mesh["water"]["faces"] > 0
        for src, (a, b), r in ext.surfaces:
            v = sim.model.mesh_vert[r.va : r.va + mesh[src]["verts"]]
            x = ext.fluid.positions()[a:b]
            assert np.all(v.min(0) > x.min(0) - 0.01) and np.all(v.max(0) < x.max(0) + 0.01)
        for src, rgba in (("juice", JUICE), ("water", WATER)):
            bare = _hidden_render(sim, "camera_2", [f"liquid/surface/{src}"])
            diff = np.abs(img.astype(int) - bare.astype(int)).sum(axis=2) > 30
            metric(f"gpu.colour.camera_2_{src}_pixels", int(diff.sum()))
            assert diff.sum() > 500
            mean = img[diff].astype(float).mean(0)
            metric(f"gpu.colour.camera_2_{src}_mean_rgb", json.dumps([round(float(c), 1) for c in mean]))
            blue_minus_red = mean[2] - mean[0]
            assert (blue_minus_red if rgba[2] > rgba[0] else -blue_minus_red) > 30
        sim.close()
    assert np.array_equal(snaps[True], snaps[False])
