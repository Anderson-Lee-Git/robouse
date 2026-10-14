"""The vendored embodiment spec matches BenchFlow's (when BenchFlow is installed) and round-trips."""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from robouse.core import embodiment_spec as ours


def test_round_trip_and_validation() -> None:
    e = ours.Embodiment(
        name="arm",
        kind="arm",
        action_groups=[*ours.ee_delta_group(), ours.gripper_group()],
        skills=[ours.move_to_skill(), ours.grip_skill()],
    ).validate()
    assert ours.Embodiment.from_dict(e.to_dict()).validate().dim == 4
    assert e.pack({"arm.ee_delta": [2, 0, 0]}) == [1.0, 0.0, 0.0, -1.0]  # clipped; the gripper holds its initial
    with pytest.raises(ours.SpecError, match="unknown action group"):
        e.pack({"legs": [1]})
    with pytest.raises(ours.SpecError, match="kind"):
        ours.Embodiment(name="x", kind="submarine", action_groups=e.action_groups).validate()


@pytest.mark.needs_benchflow_embodied
def test_same_as_benchflow() -> None:
    theirs = pytest.importorskip("benchflow.embodied.spec")
    for name, obj in inspect.getmembers(ours, dataclasses.is_dataclass):
        other = getattr(theirs, name)
        assert [f.name for f in dataclasses.fields(obj)] == [f.name for f in dataclasses.fields(other)], name
    assert ours.KINDS == theirs.KINDS and ours.SPEC_VERSION == theirs.SPEC_VERSION
