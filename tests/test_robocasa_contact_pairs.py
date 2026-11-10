"""Versioned explicit pairs survive assembly without changing unspecified scenes."""

import copy
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import numpy as np
import pytest

from robouse.backends.robocasa.contact_pairs import add, validate

PAIR = dict(
    name='seat_pair',
    geom1='a',
    geom2='b',
    margin=0,
    gap=0.002,
    condim=3,
    friction=[1.1, 1.1, 0.005, 0.0001, 0.0001],
    solref=[0.001, 2.0],
    solimp=[0.998, 0.998, 0.001, 0.5, 2.0],
)
SPEC = {'contact_pairs_v1': {'version': '1.0.0', 'pairs': [PAIR]}}


def model():
    root = ET.fromstring(
        '<mujoco><worldbody><geom name="a" type="plane" size="1 1 .1"/>'
        '<body pos="0 0 .2"><freejoint/><geom name="b" type="sphere" '
        'size=".1" mass="1"/></body></worldbody><contact/></mujoco>'
    )
    return root, SimpleNamespace(worldbody=root.find('worldbody'), contact=root.find('contact'))


def test_absence_preserves_xml_and_explicit_values_compile():
    mujoco = pytest.importorskip('mujoco')
    root, assembled = model()
    before = ET.tostring(root)
    add(assembled, {})
    assert ET.tostring(root) == before
    add(assembled, SPEC)
    compiled = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding='unicode'))
    assert compiled.npair == 1
    assert compiled.pair(0).name == 'seat_pair'
    assert compiled.geom(int(compiled.pair_geom1[0])).name == 'a'
    assert compiled.geom(int(compiled.pair_geom2[0])).name == 'b'
    for key in ('margin', 'gap', 'dim', 'friction', 'solref', 'solimp'):
        np.testing.assert_array_equal(getattr(compiled, 'pair_' + key)[0], PAIR['condim' if key == 'dim' else key])


@pytest.mark.parametrize(
    'edit',
    [
        lambda d: d.update(version='2.0.0'),
        lambda d: d.update(extra=1),
        lambda d: d.update(pairs=[]),
        lambda d: d['pairs'].append(copy.deepcopy(d['pairs'][0])),
        lambda d: d['pairs'][0].pop('solref'),
        lambda d: d['pairs'][0].update(geom2='a'),
        lambda d: d['pairs'][0].update(condim=True),
        lambda d: d['pairs'][0].update(condim=2),
        lambda d: d['pairs'][0].update(margin=float('nan')),
        lambda d: d['pairs'][0].update(gap=-0.1),
        lambda d: d['pairs'][0].update(friction=[1, 1, 1]),
        lambda d: d['pairs'][0].update(solimp=[1, 1, 1, 1, float('inf')]),
        lambda d: d['pairs'][0].update(solref=['.001', 2]),
    ],
)
def test_invalid_descriptor_fails_closed(edit):
    spec = copy.deepcopy(SPEC)
    edit(spec['contact_pairs_v1'])
    with pytest.raises(ValueError, match='contact_pairs_v1'):
        validate(spec)


def test_missing_geom_and_existing_pair_are_rejected_without_partial_mutation():
    root, assembled = model()
    bad = copy.deepcopy(SPEC)
    bad['contact_pairs_v1']['pairs'].append({**PAIR, 'name': 'missing', 'geom2': 'absent'})
    before = ET.tostring(root)
    with pytest.raises(ValueError, match='unknown assembled geom'):
        add(assembled, bad)
    assert ET.tostring(root) == before

    add(assembled, SPEC)
    before = ET.tostring(root)
    # Reversed sides are still the same physical pair.
    bad['contact_pairs_v1']['pairs'] = [{**PAIR, 'name': 'another', 'geom1': 'b', 'geom2': 'a'}]
    with pytest.raises(ValueError, match='conflicts'):
        add(assembled, bad)
    assert ET.tostring(root) == before


def test_standalone_scenario_loader_needs_no_robouse_import(monkeypatch):
    import builtins

    from robouse.backends.robocasa import scenario

    original = builtins.__import__

    def isolated(name, *args, **kwargs):
        if name == 'robouse' or name.startswith('robouse.'):
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', isolated)
    root, assembled = model()
    scenario.load_contact_pairs().add(assembled, SPEC)
    assert root.find('contact/pair').get('geom1') == 'a'
