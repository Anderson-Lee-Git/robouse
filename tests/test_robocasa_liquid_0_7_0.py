"""Liquid contract 0.7.0: continuous flex patch rotations and a time step gated to boundaries that can reach the
liquid. Contract 0.6.0 behaviour (FlexPatches(continuous=False), ValidatedWarpFluid.wall_speed) is unchanged."""

from types import SimpleNamespace

import mujoco
import numpy as np
import pytest

from robouse.backends.robocasa.physics import load_liquid

FP = load_liquid('flex_patches')
CP = load_liquid('coupling')
CO = load_liquid('compute')
VG = load_liquid('gpu.validity_gpu')

NX, NY = 5, 3
CLOTH = f"""<mujoco><option timestep="0.002"/>
<worldbody><body name="root" pos="0 0 0.02"><freejoint/>
<inertial pos="0 0 0" mass="0.001" diaginertia="1e-7 1e-7 1e-7"/>
<flexcomp name="cloth" type="grid" dim="2" dof="full" count="{NX} {NY} 1" spacing="0.02 0.02 0.01" radius="0.001"
 mass="0.01"><pin id="7"/><edge equality="true"/></flexcomp>
</body></worldbody></mujoco>"""


def cloth():
    m = mujoco.MjModel.from_xml_string(CLOTH)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    return m, d


def rot(axis, a):
    return CP.rotmat(np.asarray(axis, float) / np.linalg.norm(axis) * a)


def at(x, t=0.0):
    return SimpleNamespace(flexvert_xpos=x, time=t)


def folded(x0, ids, angle):
    """Patch vertices folded by `angle` about the patch's middle grid line along y (x = its centre)."""
    x = x0.copy()
    p = x[ids]
    cx = p[:, 0].mean()
    right = p[:, 0] > cx + 1e-9
    q = p[right] - [cx, 0, p[:, 2].mean()]
    q = q @ rot([0, 1, 0], -angle).T + [cx, 0, p[:, 2].mean()]
    p[right] = q
    x[ids] = p
    return x


def test_continuous_fit_recovers_rigid_motions_including_turning_over():
    m, d = cloth()
    p = FP.FlexPatches(m, d, 'towel', 0, (NX, NY), (2, 2), continuous=True)
    x = p.vertices(d)
    for R in (rot([0, 0, 1], 0.5), rot([1, 0.3, 0], 2.0), rot([1, 0, 0], np.pi - 0.05)):  # last: turned over
        out = p.poses(at(x @ R.T + [0.1, 0, 0.2]))
        for name in p.names:
            assert np.allclose(out[name][1], R, atol=1e-9)
    assert p.degenerate == []


def test_folding_through_flat_holds_then_logs_the_release_angle():
    m, d = cloth()
    p = FP.FlexPatches(m, d, 'towel', 0, (NX, NY), (2, 2), continuous=True)
    x0, ids = p.vertices(d), p.index[0]
    angles = np.linspace(0, np.pi - 0.02, 400)
    prev, worst, k_held = None, 0.0, []
    for k, a in enumerate(angles):
        n0 = len(p.degenerate)
        R = p.poses(at(folded(x0, ids, a), k * 0.002))['towel#p0000'][1]
        if len(p.degenerate) > n0:
            k_held.append(k)
        if prev is not None:
            worst = max(worst, np.linalg.norm(CP.rotvec(R @ prev.T)))
        prev = R
    step = angles[1] - angles[0]
    assert worst <= step  # a symmetric fold: the fit turns at most half the fold increment, then holds
    assert k_held and all(r[2] == 'area' and r[1] == 'towel#p0000' for r in p.degenerate)
    # unfold the other way round (rotated 180 deg about z): the first regular fit logs the accumulated rotation
    flipped = x0.copy()
    c = x0[ids].mean(axis=0)
    flipped[ids] = (x0[ids] - c) @ rot([0, 0, 1], np.pi / 2).T + c
    held = p.held['towel#p0000']
    R = p.poses(at(flipped, 1.0))['towel#p0000'][1]
    assert np.allclose(R, rot([0, 0, 1], np.pi / 2), atol=1e-9)
    angle = np.linalg.norm(CP.rotvec(R @ held.T))
    assert p.degenerate[-1][2] == 'release' and p.degenerate[-1][4] == pytest.approx(angle, abs=1e-3)


def test_degenerate_fit_holds_the_previous_rotation_and_logs_once_per_time():
    m, d = cloth()
    p = FP.FlexPatches(m, d, 'towel', 0, (NX, NY), (2, 2), continuous=True)
    x0, ids = p.vertices(d), p.index[0]
    R0 = p.poses(at(x0 @ rot([0, 0, 1], 0.3).T, 0.0))['towel#p0000'][1]
    flat = folded(x0 @ rot([0, 0, 1], 0.3).T, ids, np.pi - 0.01)  # folded flat onto itself
    for _ in range(3):
        R = p.poses(at(flat, 0.002))['towel#p0000'][1]
        assert np.allclose(R, R0)
    assert len(p.degenerate) == 1 and p.degenerate[0][:2] == (0.002, 'towel#p0000')
    p.reset_hold()
    assert p.degenerate == [] and p.held == {}
    with pytest.raises(FloatingPointError, match='no previous rotation'):
        p.poses(at(flat, 0.004))


def test_coupling_reset_releases_held_rotations():
    m, d = cloth()
    p = FP.FlexPatches(m, d, 'towel', 0, (NX, NY), (2, 2), continuous=True)
    c = CP.LiquidCoupling.__new__(CP.LiquidCoupling)
    c.pose_sources, c.absorbers, c.sleep = [p.poses], [], None
    c.sim = SimpleNamespace(
        data=SimpleNamespace(flexvert_xpos=p.vertices(d), time=0.0, body_xpos=d.xpos, body_xmat=d.xmat)
    )
    c.bodies, c.fluid, c.resets = {}, SimpleNamespace(reset=lambda: None), 0
    c._capture_origin()
    c.initial_poses = dict(c._prev)
    p.degenerate.append((0.0, 'towel#p0000', 'area', 1, 0, 0))
    c.reset()
    assert p.degenerate == [] and set(p.held) == set(p.names)  # re-fitted at the captured origin


class FakeFluid:
    """The minimum of a GPU fluid that wall_speed reads."""

    def __init__(self, x, radii):
        self._x = np.asarray(x, float)
        self.params = SimpleNamespace(particle_radius=0.00125, dt_max=1e-3, gravity=np.array([0, 0, -9.81]))
        self.boundary_radii = radii
        self.support = 4 * 0.00125
        self.gating = {'substeps_changed': 0, 'max_excluded_wall_speed': 0.0, 'max_excluded': None}

    def positions(self):
        return self._x


def pose(pos, v=0.0, w=0.0):
    return (np.asarray(pos, float), np.eye(3), np.array([v, 0, 0]), np.array([0, 0, w]))


def test_gated_wall_speed_excludes_only_boundaries_that_cannot_reach_the_liquid_in_a_step():
    f = FakeFluid([[0, 0, 0], [0.01, 0, 0]], {'near': 0.03, 'far': 0.03, 'edge': 0.03})
    free = np.ones(2, bool)
    poses = {
        'near': pose([0.04, 0, 0], v=0.2),  # sphere surface 1 cm from a particle: inside support + drift
        'far': pose([0.5, 0, 0], w=1000.0),  # spurious spin 30 m/s, 47 cm away: cannot reach in 1 ms
        'edge': pose([0.0, 0.1, 0], v=80.0),  # 7 cm away but fast enough to arrive within dt_max: included
    }
    s = VG.GatedWarpFluid.wall_speed(f, poses, free, 0.05)
    assert s == pytest.approx(80.0)
    poses['edge'] = pose([0.0, 0.1, 0], v=1.0)
    s = VG.GatedWarpFluid.wall_speed(f, poses, free, 0.05)
    assert s == pytest.approx(0.2)
    assert f.gating['substeps_changed'] == 1 and f.gating['max_excluded'] == 'far'
    assert f.gating['max_excluded_wall_speed'] == pytest.approx(30.0)
    # contract 0.6.0 keeps the ungated maximum over all boundaries
    assert VG.ValidatedWarpFluid.wall_speed(f, poses, free, 0.05) == pytest.approx(30.0)
    # no free particle: no boundary constrains the step
    assert VG.GatedWarpFluid.wall_speed(f, poses, np.zeros(2, bool), 0.05) == 0.0


def test_gate_distance_is_support_plus_particle_and_boundary_step_displacement():
    f = FakeFluid([[0, 0, 0]], {'b': 0.0})
    free = np.ones(1, bool)
    u, s = 0.5, 2.0
    reach = f.support + (u + 9.81 * 1e-3) * 1e-3 + s * 1e-3
    assert VG.GatedWarpFluid.wall_speed(f, {'b': pose([reach - 1e-7, 0, 0], v=s)}, free, u) == pytest.approx(s)
    assert VG.GatedWarpFluid.wall_speed(f, {'b': pose([reach + 1e-7, 0, 0], v=s)}, free, u) == 0.0


def test_gpu_compute_accepts_contract_0_7_0():
    s = {
        'liquid': {'contract_version': '0.7.0', 'threads': 4},
        'compute': {'liquid_solver': 'gpu', 'liquid_backend_id': CO.GPU_BACKEND, 'threads': 4},
    }
    assert CO.requirement(s) == s['compute']
    with pytest.raises(ValueError, match='explicit compute'):
        CO.requirement({'liquid': {'contract_version': '0.7.0'}})
