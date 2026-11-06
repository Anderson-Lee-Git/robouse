"""Geometric and query controls for the opt-in liquid contract; no native binding needed."""

from types import SimpleNamespace

import numpy as np
import pytest

from robouse.backends.robocasa.physics import load_liquid

D = load_liquid('domain_v1')
V = load_liquid('validity_v1')
Q = load_liquid('queries')
S = load_liquid('scene')


def slab():
    return D.SolidBox('slab', np.array([0, 0, -0.01]), np.eye(3), np.array([1, 1, 0.01]))


def test_continuous_collision_retains_particles_and_tangential_velocity():
    domain = D.StaticDomain([slab()], 0.00125)
    start = np.array([[0.0, 0, 0.01], [2, 0, 0.01]])
    end = np.array([[0.002, 0, -0.01], [2.002, 0, -0.01]])
    velocity = np.array([[0.2, 0, -1.0], [0.2, 0, -1.0]])
    x, v = domain.resolve(start, end, velocity)
    assert x.shape == start.shape
    assert x[0, 2] == pytest.approx(0.001251)
    assert x[0, 0] == pytest.approx(0.002)
    np.testing.assert_array_equal(x[1], end[1])
    np.testing.assert_array_equal(v, [[0.2, 0, 0], [0.2, 0, -1]])
    assert np.all(np.linalg.norm(v, axis=1) <= np.linalg.norm(velocity, axis=1))


def test_lateral_entry_below_slab_is_valid_but_entry_through_side_collides():
    domain = D.StaticDomain([slab()], 0.00125)
    x, v = domain.resolve(
        np.array([[-2.0, 0, -0.1], [-2, 0, -0.01]]),
        np.array([[0.0, 0, -0.1], [0, 0, -0.01]]),
        np.array([[1.0, 0, 0], [1, 0, 0]]),
    )
    np.testing.assert_array_equal(x[0], [0, 0, -0.1])
    np.testing.assert_array_equal(v[0], [1, 0, 0])
    assert x[1, 0] == pytest.approx(-1.001251)
    np.testing.assert_array_equal(v[1], [0, 0, 0])


def test_real_gap_remains_open():
    boxes = [D.SolidBox(str(x), [x, 0, -0.01], np.eye(3), [0.45, 1, 0.01]) for x in [-0.55, 0.55]]
    domain = D.StaticDomain(boxes, 0.00125)
    end, v = domain.resolve(np.array([[0.0, 0, 0.1]]), np.array([[0.0, 0, -0.1]]), np.array([[0.0, 0, -1.0]]))
    np.testing.assert_array_equal(end, [[0.0, 0, -0.1]])
    np.testing.assert_array_equal(v, [[0.0, 0, -1.0]])


def test_rotated_box_contact_is_equivariant():
    a = 0.37
    R = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    offset = np.array([2.0, -1, 0.5])
    box = slab()
    other = D.SolidBox('rotated', box.centre @ R.T + offset, R, box.half)
    start, end, vel = np.array([[0.0, 0, 0.01]]), np.array([[0.002, 0, -0.01]]), np.array([[0.2, 0, -1.0]])
    x, v = D.StaticDomain([box], 0.00125).resolve(start, end, vel)
    y, w = D.StaticDomain([other], 0.00125).resolve(start @ R.T + offset, end @ R.T + offset, vel @ R.T)
    np.testing.assert_allclose(y, x @ R.T + offset, atol=1e-12)
    np.testing.assert_allclose(w, v @ R.T, atol=1e-12)


def test_embedded_state_is_an_error_not_a_teleport():
    with pytest.raises(D.LiquidValidityError, match='inside'):
        D.StaticDomain([slab()], 0.00125).resolve(
            np.array([[0.0, 0, -0.01]]), np.array([[0.0, 0, -0.02]]), np.zeros((1, 3))
        )


def test_gravity_drop_stops_at_floor_without_deletion():
    domain = D.StaticDomain([slab()], 0.00125)
    x, v = np.array([[0.0, 0, 0.9]]), np.zeros((1, 3))
    for _ in range(1000):
        v[:, 2] -= 0.00981
        x, v = domain.resolve(x, x + 0.001 * v, v)
    assert x.shape == (1, 3) and 0.00125 <= x[0, 2] < 0.00126
    assert v[0, 2] == 0


@pytest.mark.parametrize('n,omitted', [(127, False), (128, True), (129, True)])
def test_valid_below_slab_water_retains_exact_combined_omission_volume(n, omitted):
    fluid = SimpleNamespace(
        positions=lambda: np.tile([0.0, 0, -0.1], (n, 1)),
        free_mask=np.ones(n, bool),
        absorbed_by=np.full(n, '', object),
        params=SimpleNamespace(particle_radius=0.00125, particle_volume=0.0025**3),
        validate=lambda: None,
    )
    coupling = SimpleNamespace(fluid=fluid, poses=lambda: {}, absorbers=[])
    old = S.LiquidScene(None, coupling, {}, Q.Surface(0.0), {})
    new = V.ValidatedLiquidScene(None, coupling, {}, Q.Surface(0.0), {'contract_version': '0.4.0'})
    p = {'region': ['surface', 'elsewhere'], 'min_ml': 2}
    with pytest.raises(RuntimeError, match='leaked'):
        S.predicate(SimpleNamespace(_liquid_scene=old), p)
    assert new.volumes_ml() == {'elsewhere': n * 0.0025**3 * 1e6}
    assert S.predicate(SimpleNamespace(_liquid_scene=new), p) is omitted

    def invalid():
        raise D.LiquidValidityError('invalid particle state')

    fluid.validate = invalid
    with pytest.raises(D.LiquidValidityError):
        S.predicate(SimpleNamespace(_liquid_scene=new), p)


def validation_fluid(tmp_path):
    # Exercise guards without loading a native singleton; advance must reject
    # invalid inputs before touching its absent native fields.
    f = V.ValidatedSPHFluid.__new__(V.ValidatedSPHFluid)
    x, v = np.array([[0.0, 0.0, 0.2]]), np.zeros((1, 3))
    f.positions, f.velocities = lambda: x, lambda: v
    f.n, f._t, f.steps = 1, 0.0, 0
    f.workdir, f.invalid_reason = tmp_path, None
    f.absorbed_by = np.full(1, "", object)
    f.params = load_liquid('solver').FluidParams()
    floor = slab()
    f.domain = D.StaticDomain([floor], f.params.particle_radius)
    f.domain.floor = floor
    f.boundary_radii = {'moving': 0.1}
    return f, x, v


@pytest.mark.parametrize(
    'bad', ['nan_position', 'nan_velocity', 'solid', 'below_floor', 'outside_floor', 'excess_speed']
)
def test_invalid_state_is_latched_and_preserves_every_particle(tmp_path, bad):
    f, x, v = validation_fluid(tmp_path)
    if bad == 'nan_position':
        x[0, 0] = np.nan
    elif bad == 'nan_velocity':
        v[0, 0] = np.nan
    elif bad == 'solid':
        x[0, 2] = -0.01
    elif bad == 'below_floor':
        x[0, 2] = -0.1
    elif bad == 'outside_floor':
        x[0, 0] = 1.1
    elif bad == 'excess_speed':
        v[0, 0] = 100
    with pytest.raises(D.LiquidValidityError):
        f.validate()
    saved = np.load(tmp_path / 'invalid-state.npz')
    assert saved['positions'].shape == (1, 3) and saved['free_mask'].all()
    x[:] = [0.0, 0.0, 0.2]
    v[:] = 0
    for operation in (f.validate, lambda: f.advance(0), lambda: f.sleep_until(0.1)):
        with pytest.raises(D.LiquidValidityError):
            operation()


def test_fast_boundary_rejects_instead_of_clamping_dt_up(tmp_path):
    f, _, _ = validation_fluid(tmp_path)
    with pytest.raises(D.LiquidValidityError, match='relative boundary/particle speed'):
        f.advance(0.002, lambda _: {'moving': (np.zeros(3), np.eye(3), np.array([100.0, 0, 0]), np.zeros(3))})


@pytest.mark.parametrize('target', [float('nan'), float('inf'), -0.1])
def test_invalid_target_time_is_an_explicit_error(tmp_path, target):
    f, _, _ = validation_fluid(tmp_path)
    with pytest.raises(D.LiquidValidityError, match='target time'):
        f.advance(target)


def test_static_solid_query_guard_accepts_real_gap_and_below_slab():
    domain = D.StaticDomain([slab()], 0.00125)
    domain.validate(np.array([[2.0, 0, -0.01], [0.0, 0, -0.1]]))
    with pytest.raises(D.LiquidValidityError, match='inside'):
        domain.validate(np.array([[0.0, 0, -0.01]]))
