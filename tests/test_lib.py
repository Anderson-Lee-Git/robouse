"""Shared helpers: pinned downloads, the video recorder, camera calibration, placement splits."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from robouse.core.recording import record_size
from robouse.lib.download import ChecksumError, fetch, sha256_file


def test_fetch_checks_the_hash_and_leaves_nothing_on_a_mismatch(tmp_path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"robot mesh")
    good = hashlib.sha256(b"robot mesh").hexdigest()
    dest = tmp_path / "out" / "mesh.bin"
    assert fetch(src.as_uri(), dest, good) is True
    assert sha256_file(dest) == good
    assert fetch(src.as_uri(), dest, good) is False  # already there
    bad = tmp_path / "out" / "other.bin"
    with pytest.raises(ChecksumError):
        fetch(src.as_uri(), bad, "0" * 64)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["mesh.bin"]


def test_record_size() -> None:
    assert record_size("1281x721") == (1280, 720)
    assert record_size("") is None
    with pytest.raises(ValueError, match="1280x720"):
        record_size("big")
    with pytest.raises(ValueError, match="out of range"):
        record_size("8x8")


def test_video_recorder_resizes_later_frames(tmp_path) -> None:
    pytest.importorskip("imageio")
    from robouse.core.recording import VideoRecorder

    v = VideoRecorder(tmp_path, t0=0.0)
    v.add(np.zeros((32, 48, 3), np.uint8), step=0)
    v.add(np.zeros((64, 64, 3), np.uint8), step=2)
    v.close()
    assert v.size == (48, 32) and (tmp_path / "recording.mp4").stat().st_size > 0
    assert [json.loads(x)["step"] for x in (tmp_path / "frames.jsonl").read_text().splitlines()] == [0, 2]


def test_mujoco_camera_projects_its_look_at_point_to_the_image_centre() -> None:
    mujoco = pytest.importorskip("mujoco")
    from robouse.core.cameras import mujoco_camera

    m = mujoco.MjModel.from_xml_string(
        '<mujoco><worldbody><camera name="c" pos="0 -1 1" xyaxes="1 0 0 0 0.7071 0.7071" fovy="45"/>'
        '<geom type="sphere" size="0.01" pos="0 0 0"/></worldbody></mujoco>')
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    cam = mujoco_camera(m, d, "c", 64, 48)
    fwd = -d.cam_xmat[0].reshape(3, 3)[:, 2]
    u, v, w = np.asarray(cam["projection"]) @ np.r_[d.cam_xpos[0] + fwd, 1.0]
    assert abs(u / w - 32) < 1 and abs(v / w - 24) < 1
    assert mujoco_camera(m, d, "missing", 64, 48) is None
    assert mujoco_camera(m, d, "c", 64, 48, calibrated=False)["projection"] is None


def test_placement_splits() -> None:
    import math

    from robouse.lib.placement import NOMINAL, offset

    assert offset("interpolation", 3, "cube") == offset("interpolation", 3, "cube")
    assert offset("nominal", 1, "cube") in NOMINAL
    dx, dy = offset("interpolation", 7, "cube")
    assert max(abs(dx), abs(dy)) <= 0.02 and min(math.hypot(dx - a, dy - b) for a, b in NOMINAL) > 0.005
    assert 0.03 <= math.hypot(*offset("extrapolation", 7, "cube")) <= 0.06
    with pytest.raises(ValueError, match="placement split"):
        offset("far", 0, "cube")
