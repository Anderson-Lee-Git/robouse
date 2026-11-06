"""A resolved normal impulse must still bound the following native timestep."""

from types import SimpleNamespace

import numpy as np
from test_robocasa_liquid_resolved_step import fluid

from robouse.backends.robocasa.physics import load_liquid

V = load_liquid('validity_v3')


def test_contact_prediction_bounds_next_pressure_response(tmp_path):
    original, x, v = fluid(tmp_path)
    f = V.PredictiveSPHFluid.__new__(V.PredictiveSPHFluid)
    f.__dict__.update(original.__dict__)
    f.previous_predicted_speed = 0.0
    old = np.array([[0.0, 0.0, 0.0013]])
    x[:] = [0.0, 0.0, -0.005]
    v[:] = [0.0, 0.0, -6.0]
    accepted, velocity = f.resolve_prediction(old, f.free_mask)
    x[:], v[:] = accepted, velocity
    assert f.previous_predicted_speed == 6.0
    assert not np.any(v)
    timesteps = []
    f.tm = SimpleNamespace(setTimeStepSize=lambda dt: timesteps.append(dt), setTime=lambda _: None)
    f.minimum_dt, f.log_steps = float('inf'), False
    f._update_boundaries = lambda: None

    def upward_pressure():
        v[:] = [0.0, 0.0, 6.0]
        x[:] += v * timesteps[-1]

    f.base = SimpleNamespace(timeStepNoGUI=upward_pressure)
    f.advance(0.001, lambda _: {})
    assert len(timesteps) > 1
    assert max(timesteps) <= f.params.cfl * f.params.spacing / 6.0
    assert f.n == 1 and f.free_mask.all()
    assert x[0, 2] > 0.00125
    assert f.time == 0.001
    np.testing.assert_array_equal(v, [[0.0, 0.0, 6.0]])
