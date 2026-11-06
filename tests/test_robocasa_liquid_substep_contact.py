"""Transient mesh contact must be accounted before another native pressure step."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from test_robocasa_liquid_resolved_step import fluid

from robouse.backends.robocasa.physics import load_liquid

V = load_liquid('validity_v4')
D = load_liquid('domain_v1')
C = load_liquid('contact')
M = load_liquid('meshes')


def transient_pose(t):
    # Both enclosing rigid-sync endpoints miss the unchanged 2.5 mm band.
    z = 0.2126 - 0.2 * min(t, 0.002 - t)
    return {'moving': (np.array([0, 0, z]), np.eye(3), np.array([0, 0, 0.2]), np.zeros(3))}


def contact_fluid(tmp_path):
    original, x, v = fluid(tmp_path)
    f = V.SubstepContactSPHFluid.__new__(V.SubstepContactSPHFluid)
    f.__dict__.update(original.__dict__)
    f.params = replace(f.params, dt_max=0.001, gravity=(0, 0, 0), surface_tension=0)
    f.previous_predicted_speed = 0.0
    absorber = C.Absorber('moving', C.MeshContact(*M.box((0.01, 0.01, 0.01))), 100, 0.0025)
    f.substep_absorbers = [absorber]
    f.tm = SimpleNamespace(setTimeStepSize=lambda _: None, setTime=lambda _: None)
    f.minimum_dt, f.log_steps = float('inf'), False
    f._update_boundaries = lambda: None
    f.set_pose = lambda *args: None
    f.base = SimpleNamespace(timeStepNoGUI=lambda: None)
    transfers = []

    def absorb(ids, owner):
        transfers.append((f.time, ids.copy(), owner))
        f.absorbed_by[ids] = owner
        x[ids] = [0, 0, -10]
        v[ids] = 0

    f.absorb = absorb
    return f, x, v, absorber, transfers


def test_transient_contact_uses_accepted_end_pose_and_retains_ownership(tmp_path):
    f, x, _, absorber, transfers = contact_fluid(tmp_path)
    for t in (0, 0.002):
        assert not absorber.mesh.within(x, *transient_pose(t)['moving'][:2], absorber.contact_m).any()
    assert f.advance(0.002, transient_pose) == 2
    assert len(transfers) == 1 and transfers[0][0] == 0.001
    assert f.n == 1 and not f.free_mask.any()
    assert f.absorbed_by.tolist() == ['moving']
    assert absorber.report(f.params.particle_volume)['absorbed_ml'] == pytest.approx(0.015625)
    assert absorber.update(f, *transient_pose(0.002)['moving'][:2]) == 0


@pytest.mark.parametrize('reason', ['remote', 'capacity'])
def test_substeps_cannot_clear_noncontact_or_exceed_capacity(tmp_path, reason):
    f, x, _, absorber, transfers = contact_fluid(tmp_path)
    if reason == 'remote':
        x[0, 0] = 0.1
    else:
        absorber.capacity_ml = f.params.particle_volume * 1e6 / 2
    before = x.copy()
    f.advance(0.002, transient_pose)
    np.testing.assert_array_equal(x, before)
    assert not transfers and absorber.particles == 0
    assert f.n == 1 and f.free_mask.all()


@pytest.mark.parametrize('bad', ['nonfinite', 'displacement', 'velocity'])
def test_invalid_prediction_fails_before_contact_can_absorb_it(tmp_path, bad):
    f, x, v, absorber, transfers = contact_fluid(tmp_path)

    def invalid_prediction():
        if bad == 'nonfinite':
            v[0, 0] = np.nan
        elif bad == 'displacement':
            x[0, 0] += 0.003  # Still within the sponge footprint.
        else:
            v[0, 0] = 100

    f.base.timeStepNoGUI = invalid_prediction
    with pytest.raises(D.LiquidValidityError):
        f.advance(0.002, transient_pose)
    assert not transfers and absorber.particles == 0 and f.free_mask.all()
    saved = np.load(tmp_path / 'invalid-state.npz')
    assert len(saved['positions']) == 1 and saved['free_mask'].all()
