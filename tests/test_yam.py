"""The dual-YAM backend (Dream Labs' scene in its own virtualenv): action layout, skills, judging and camera
calibration. Needs the yam virtualenv (docs/suites/yam.md); skipped without it."""

from __future__ import annotations

import numpy as np
import pytest

from robouse import config

pytestmark = pytest.mark.skipif(not config.sim_python("yam").exists(), reason="no yam virtualenv")


@pytest.fixture()
def backend():
    from robouse.backends.yam import YamBackend

    b = YamBackend({"goal": {"kind": "in_bowl", "object": "apple"}, "seed": 0, "max_steps": 400})
    b.reset(0)
    yield b
    b.close()


def run(b, gen) -> dict:
    try:
        while True:
            b.step(next(gen))
    except StopIteration as e:
        return e.value


def test_layout_embodiment_and_hold(backend) -> None:
    b = backend
    assert b.action_spec.dim == 14 and b.action_spec.names[:7][-1] == "right_grip"
    emb = b.embodiment().validate()
    assert [g.name for g in emb.action_groups] == [
        "right_arm.joints",
        "right_gripper",
        "left_arm.joints",
        "left_gripper",
    ]
    assert {c.name for c in emb.sensors.cameras} == {"top", "left", "right"}
    assert b.hold_action() == [0.0] * 6 + [1.0] + [0.0] * 6 + [1.0]
    assert not b.success() and b.last_judge["held_by"] == []


def test_reach_grasp_and_judge(backend) -> None:
    b = backend
    apple = np.asarray(b.observe()["apple_pos"])
    out = run(b, b.start_skill("reach", ["left", *(str(x) for x in apple + [0, 0, 0.12])]))
    assert out["reached"] and out["tcp_down_deg"] < 3
    run(b, b.start_skill("reach", ["left", *(str(x) for x in apple)]))
    out = run(b, b.start_skill("set_gripper", ["left", "0", "12"]))
    assert "apple" in out["touching"] and 0.5 < out["gripper_open"] < 0.85
    with pytest.raises(ValueError, match="ARM"):
        b.start_skill("reach", ["middle", "0", "0", "1"])
    with pytest.raises(ValueError, match="unknown skill"):
        b.start_skill("wave", [])


def test_top_camera_projection_lands_on_the_orange(backend) -> None:
    b = backend
    cam = b.camera_info(["top"])[0]
    p = np.asarray(cam["projection"]) @ np.r_[b.observe()["orange_pos"], 1.0]
    u, v = p[:2] / p[2]
    img = b.render().astype(int)
    mask = (img[..., 0] > 180) & (img[..., 1] > 60) & (img[..., 1] < 140) & (img[..., 2] < 60)
    ys, xs = np.nonzero(mask)
    assert len(xs) > 100 and abs(xs.mean() - u) < 6 and abs(ys.mean() - v) < 6
