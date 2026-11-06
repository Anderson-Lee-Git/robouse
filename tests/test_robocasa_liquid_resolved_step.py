"""Contact precedes the accepted-motion guard only in liquid contract 0.4.1."""

import numpy as np
import pytest
from test_robocasa_liquid_validity import validation_fluid

from robouse.backends.robocasa.physics import load_liquid

D = load_liquid('domain_v1')
V = load_liquid('validity_v2')


def fluid(tmp_path):
    original, x, v = validation_fluid(tmp_path)
    f = V.ResolvedSPHFluid.__new__(V.ResolvedSPHFluid)
    f.__dict__.update(original.__dict__)
    f.resolved_large_predictions = 0
    f.maximum_predicted_displacement = 0.0
    return f, x, v


def test_large_normal_prediction_is_a_resolved_contact_not_free_flight(tmp_path):
    f, x, v = fluid(tmp_path)
    old = np.array([[0.0, 0.0, 0.0013]])
    x[:] = [0.0002, 0.0, -0.005]
    v[:] = [0.2, 0.0, -6.0]
    accepted, velocity = f.resolve_prediction(old, f.free_mask)
    assert len(accepted) == f.n == 1
    assert 0.00125 <= accepted[0, 2] <= 0.001252
    np.testing.assert_allclose(velocity, [[0.2, 0.0, 0.0]])
    assert np.linalg.norm(accepted - old) < f.params.spacing
    assert f.resolved_large_predictions == 1
    saved = np.load(tmp_path / 'resolved-prediction-first.npz')
    np.testing.assert_array_equal(saved['predicted_positions'], x)
    np.testing.assert_array_equal(saved['old_positions'], old)
    np.testing.assert_array_equal(saved['resolved_free_positions'], accepted)


@pytest.mark.parametrize('normal_contact', [False, True])
def test_unresolved_large_displacement_still_fails_and_preserves_state(tmp_path, normal_contact):
    f, x, v = fluid(tmp_path)
    old = np.array([[0.0, 0.0, 0.0013 if normal_contact else 0.2]])
    x[:] = old + [0.01, 0.0, -0.005 if normal_contact else 0.0]
    v[:] = [10.0, 0.0, -5.0 if normal_contact else 0.0]
    with pytest.raises(D.LiquidValidityError, match='resolved native step'):
        f.resolve_prediction(old, f.free_mask)
    saved = np.load(tmp_path / 'invalid-state.npz')
    np.testing.assert_array_equal(saved['positions'], x)
    np.testing.assert_array_equal(saved['velocities'], v)
    assert saved['free_mask'].all()
    assert f.resolved_large_predictions == 0


def test_contact_cannot_hide_an_invalid_native_normal_velocity(tmp_path):
    f, x, v = fluid(tmp_path)
    old = np.array([[0.0, 0.0, 0.0013]])
    x[:] = [0.0, 0.0, -0.005]
    v[:] = [0.0, 0.0, -100.0]
    with pytest.raises(D.LiquidValidityError, match='native predicted speed'):
        f.resolve_prediction(old, f.free_mask)
    saved = np.load(tmp_path / 'invalid-state.npz')
    np.testing.assert_array_equal(saved['velocities'], v)
    assert f.resolved_large_predictions == 0
