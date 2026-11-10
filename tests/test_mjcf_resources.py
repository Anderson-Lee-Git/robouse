"""Attached resource identity, inheritance and collision controls without changing assets."""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from robouse.backends.robocasa.mjcf_resources import resolve


def make_child(folder, name, value):
    folder.mkdir(parents=True)
    (folder / "meshes").mkdir()
    (folder / "meshes" / "part.obj").write_text(value)
    child = folder / "child.xml"
    child.write_text(f'<mujoco><asset><mesh name="{name}" file="part.obj"/></asset><worldbody/></mujoco>')
    return child


def parent(*paths):
    return (
        '<mujoco><compiler meshdir="meshes/"/><asset>'
        + ''.join(f'<model name="child{i}" file="{path}"/>' for i, path in enumerate(paths))
        + '</asset><worldbody/></mujoco>'
    )


def test_distinct_basename_and_relocation_preserve_content_identity(tmp_path):
    a = make_child(tmp_path / "original/a", "a", "mesh one")
    b = make_child(tmp_path / "original/b", "b", "mesh two")
    before = {p: p.read_bytes() for p in (tmp_path / "original").rglob('*') if p.is_file()}
    xml, assets = resolve(parent(a, b))
    assert len(assets) == 2
    for data in assets.values():
        path = ET.fromstring(data).find('./asset/mesh').get('file')
        assert Path(path).is_file()
    shutil.copytree(tmp_path / "original", tmp_path / "relocated")
    other_xml, other_assets = resolve(parent(tmp_path / "relocated/a/child.xml", tmp_path / "relocated/b/child.xml"))
    assert xml == other_xml
    assert set(assets) == set(other_assets)
    assert all(p.read_bytes() == content for p, content in before.items())


def test_unattached_xml_unchanged_and_missing_resources_fail(tmp_path):
    xml = '<mujoco><worldbody/></mujoco>'
    assert resolve(xml) == (xml, {})
    with pytest.raises(FileNotFoundError):
        resolve(parent(tmp_path / "missing.xml"))


def test_recursive_child_and_include_fail_closed(tmp_path):
    child = tmp_path / "child.xml"
    child.write_text('<mujoco><asset><model name="self" file="child.xml"/></asset></mujoco>')
    with pytest.raises(ValueError, match="cycle"):
        resolve(parent(child))
    child.write_text('<mujoco><include file="other.xml"/></mujoco>')
    with pytest.raises(ValueError, match="scope audit"):
        resolve(parent(child))
