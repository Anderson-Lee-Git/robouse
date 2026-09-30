"""Unit tests for the stdlib VLA client: codecs, image helpers, action mapping, chunk controllers, compatibility check.
Wire interoperability with the upstream libraries is covered end to end by tools/ops/vla_dogfood.sh."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("vla_client", Path(__file__).resolve().parents[1] / "src/robouse/harnesses/vla/client.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def test_msgpack_roundtrip_with_numpy_conventions():
    obj = {"a": [1, -5, 300, -70000, 2 ** 40, 1.5, None, True, "x" * 40], "img": np.arange(12, dtype=np.uint8).reshape(2, 2, 3),
           "s": np.float32(2.5), b"k": b"\x00\x01"}
    for default in (C.np_default_openpi, C.np_default_mnp):
        out = C.mp_unpack(C.mp_pack(obj, default), C.np_hook)
        assert out["a"] == obj["a"] and np.array_equal(out["img"], obj["img"]) and float(out["s"]) == 2.5 and out[b"k"] == b"\x00\x01"


def test_png_roundtrip_and_resize(tmp_path):
    img = (np.random.default_rng(0).random((30, 40, 3)) * 255).astype(np.uint8)
    p = tmp_path / "x.png"
    import base64
    p.write_bytes(base64.b64decode(C.png_b64(img)))
    assert np.array_equal(C.decode_png(str(p)), img)
    assert C.resize(img, (20, 15)).shape == (15, 20, 3)
    padded = C.resize_with_pad(img, (64, 64))
    assert padded.shape == (64, 64, 3) and padded[0].sum() == 0  # letterboxed


def test_openvla_gripper_and_clip():
    info = {"action": {"names": list("abcdefg"), "low": [-1] * 7, "high": [1] * 7}}
    m = C.ActionMap({"action": {"gripper": {"index": 6, "mode": "openvla"}, "clip": [-1, 1]}}, info)
    assert m([0.1, 0, 0, 0, 0, 0, 1.0])[6] == -1.0 and m([0.1, 0, 0, 0, 0, 0, 0.0])[6] == 1.0
    assert m([5, 0, 0, 0, 0, 0, 1.0])[0] == 1.0


def test_temporal_ensembling_and_replan():
    ens = C.Controller({"controller": {"mode": "ensemble", "m": 0.0}})
    ens.plan(0, np.array([[0.0], [0.0], [0.0]]))
    out = ens.plan(1, np.array([[1.0], [1.0]]))  # step 1 now has two predictions: 0 (old) and 1 (new), equal weights
    assert abs(out[0][0] - 0.5) < 1e-9
    ol = C.Controller({"controller": {"mode": "open_loop", "replan": 2}})
    assert len(ol.plan(0, np.zeros((10, 3)))) == 2
    sm = C.Controller({"controller": {"smooth": 0.5}})
    assert sm.plan(0, np.array([[0.0], [1.0]]))[1][0] == 0.5


def test_compat_check_catches_dimension_and_mode():
    info = {"backend": "real", "action": {"names": list("abcdefg"), "low": [-1] * 7, "high": [1] * 7},
            "embodiment": {"action_groups": [{"mode": "joint_pos"}, {"mode": "gripper"}]}}
    m = C.ActionMap({"action": {}}, info)
    assert "values but the task takes 7" in C.check_compat({"action": {}}, info, m, np.zeros((4, 6)))
    assert C.check_compat({"action": {"mode": "ee_delta_pose"}}, info, m, np.zeros((4, 7))).startswith("policy outputs")
    assert C.check_compat({"backends": ["libero"]}, info, m, np.zeros((4, 7))).startswith("policy preset is for")
    assert C.check_compat({"action": {"mode": "joint_pos"}}, info, m, np.zeros((4, 7))) is None


def test_presets_resolve():
    from robouse.harnesses import vla

    for name in vla.presets():
        cfg = vla.resolve(name)
        assert cfg["wire"] in C.WIRES, name


def test_state_transforms_for_zero_shot_mappings():
    # gripper pointing straight down: quaternion (1, 0, 0, 0) -> axis-angle (pi, 0, 0), as robosuite's quat2axisangle
    assert np.allclose(C.quat_to_axis_angle([1.0, 0.0, 0.0, 0.0]), [np.pi, 0, 0])
    assert np.allclose(C.quat_to_axis_angle([0.0, 0.0, 0.0, 1.0]), [0, 0, 0])
    assert np.allclose(C.STATE_FNS["width_to_fingers"](np.array([0.08])), [0.04, -0.04])
    cfg = {"obs": {"s": {"state": ["hand_quat"], "fn": "quat_to_axis_angle"}, "g": {"state": ["gripper_open"], "fn": "width_to_fingers"}}}
    out = C.Observer(cfg, {}, "x").build({}, {"hand_quat": [1.0, 0.0, 0.0, 0.0], "gripper_open": 0.06})
    assert out["s"].shape == (3,) and np.allclose(out["g"], [0.03, -0.03])


def test_state_fields_const_scale_and_fn():
    st = {"hand_pos": [0.1, 0.2, 0.3], "gripper_open": 1.0}
    v = C._state_vector(st, ["hand_pos", {"const": [np.pi, 0, 0]}, {"field": "gripper_open", "scale": 0.08, "fn": "width_to_fingers"}])
    assert np.allclose(v, [0.1, 0.2, 0.3, np.pi, 0, 0, 0.04, -0.04])

