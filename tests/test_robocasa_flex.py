"""Deformable flex objects (MuJoCo `flexcomp`): liquid contract 0.6.0 patch boundaries and absorber, object
friction/condim on flexes, flex contact sides (geom -1) in predicates and the state trace."""

from types import SimpleNamespace

import mujoco
import numpy as np
import pytest

from robouse.backends.robocasa import scenario as S
from robouse.backends.robocasa.physics import load_liquid
from robouse.backends.robocasa.scenario_backend import check_spec

FP = load_liquid('flex_patches')
C = load_liquid('contact')
CP = load_liquid('coupling')
CO = load_liquid('compute')

NX, NY = 5, 3
CLOTH = f"""<mujoco><option timestep="0.002"/>
<worldbody><geom name="floor" type="plane" size="1 1 .1"/>
<body name="other" pos="0.3 0 0.5"><geom name="block" type="box" size=".01 .01 .01"/></body>
<body name="root" pos="0 0 0.02"><freejoint/>
<inertial pos="0 0 0" mass="0.001" diaginertia="1e-7 1e-7 1e-7"/>
<flexcomp name="cloth" type="grid" dim="2" dof="full" count="{NX} {NY} 1" spacing="0.02 0.02 0.01" radius="0.001"
 mass="0.01"><pin id="7"/><edge equality="true"/><contact condim="4" friction="0.9 0.01 0.001"/></flexcomp>
</body></worldbody></mujoco>"""


def cloth():
    m = mujoco.MjModel.from_xml_string(CLOTH)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    return m, d


def rot_z(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def test_kabsch_recovers_a_rigid_motion():
    rest = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 0]], float) * 0.01
    R = rot_z(0.7) @ np.array([[1, 0, 0], [0, np.cos(0.3), -np.sin(0.3)], [0, np.sin(0.3), np.cos(0.3)]])
    t = np.array([0.1, -0.2, 0.3])
    c, Rf = FP.kabsch(rest, rest @ R.T + t)
    assert np.allclose(c, t) and np.allclose(Rf, R) and np.isclose(np.linalg.det(Rf), 1)


def test_patches_tile_the_grid_and_follow_a_rigid_motion_of_the_cloth():
    m, d = cloth()
    p = FP.FlexPatches(m, d, 'towel', 0, (NX, NY), (2, 2))
    assert p.names == ['towel#p0000', 'towel#p0100']  # (5-1)/2 x (3-1)/2 patches, fixed order
    assert [len(i) for i in p.index] == [9, 9]
    v, _ = p.meshes[0]
    assert np.allclose(np.abs(v).max(0), [0.021, 0.021, 0.001])  # rest extent + radius; radius thick
    before = p.poses(d)
    assert np.allclose(before['towel#p0000'][1], np.eye(3))
    R, t = rot_z(0.5), np.array([0.05, 0.02, 0.1])
    x = p.vertices(d)
    moved = SimpleNamespace(flexvert_xpos=np.vstack([x @ R.T + t]))
    after = p.poses(moved)
    for name in p.names:
        assert np.allclose(after[name][0], R @ before[name][0] + t)
        assert np.allclose(after[name][1], R)


@pytest.mark.parametrize(
    'grid,cells,message',
    [
        ((3, 5), (2, 2), 'ordered'),  # transposed: neighbours are not one spacing apart
        ((5, 4), (2, 2), 'grid'),
        ((5, 3), (3, 2), 'divide'),
    ],
)
def test_patch_layout_errors(grid, cells, message):
    m, d = cloth()
    with pytest.raises(ValueError, match=message):
        FP.FlexPatches(m, d, 'towel', 0, grid, cells)


class Fluid:
    def __init__(self, x):
        self.x = np.asarray(x, float)
        self.free_mask = np.ones(len(x), bool)
        self.params = SimpleNamespace(particle_volume=1e-6)  # 1 ml per particle
        self.absorbed_by = [''] * len(x)

    def positions(self):
        return self.x

    def absorb(self, ids, owner):
        self.free_mask[ids] = False
        for i in ids:
            self.absorbed_by[i] = owner


def test_patch_absorber_shares_one_capacity_and_attributes_by_patch():
    box = C.MeshContact(*FP.meshes.box((0.01, 0.01, 0.001)))
    a = C.PatchAbsorber('towel', {'towel#p0000': box, 'towel#p0100': box}, 3, 0.0025)
    assert a.pose_names() == ('towel#p0000', 'towel#p0100')
    poses = {'towel#p0000': (np.zeros(3), np.eye(3)), 'towel#p0100': (np.array([0.05, 0, 0]), np.eye(3))}
    # overlapping patches: one on the first, one on both (counted for the first), one on the second, two away
    f = Fluid([[0, 0, 0.002], [0.005, 0, 0.002], [0.025, 0, 0], [0.05, 0, 0.002], [1, 1, 1]])
    poses_overlap = dict(poses, **{'towel#p0100': (np.array([0.015, 0, 0]), np.eye(3))})
    assert a.update_poses(f, poses_overlap) == 3  # capacity 3 ml: the lowest ids first
    assert f.absorbed_by == ['towel', 'towel', 'towel', '', '']
    assert a.by_patch == {'towel#p0000': 2, 'towel#p0100': 1}
    assert a.update_poses(f, poses) == 0  # full: the shared reservoir is not per patch
    r = a.report(1e-6)
    assert r['absorbed_ml'] == pytest.approx(3) and r['patches'] == 2
    assert r['by_patch_ml'] == {'towel#p0000': pytest.approx(2), 'towel#p0100': pytest.approx(1)}
    with pytest.raises(TypeError):
        a.update(f, np.zeros(3), np.eye(3))


def test_a_rigid_absorber_reads_its_own_pose_from_the_pose_map():
    a = C.Absorber('cloth', C.MeshContact(*FP.meshes.box((0.01, 0.01, 0.01))), 10, 0.0025)
    f = Fluid([[0.1, 0, 0.012], [1, 0, 0]])  # contact is with the mesh surface
    assert a.pose_names() == ('cloth',)
    assert a.update_poses(f, {'cloth': (np.array([0.1, 0, 0]), np.eye(3), 'ignored')}) == 1


def test_coupling_merges_pose_sources_and_refuses_duplicates():
    m, d = cloth()
    c = CP.LiquidCoupling.__new__(CP.LiquidCoupling)
    c.sim, c.bodies = SimpleNamespace(data=SimpleNamespace(body_xpos=d.xpos, body_xmat=d.xmat)), {'root': 2}
    c.pose_sources = [lambda data: {'towel#p0000': (np.ones(3), np.eye(3))}]
    poses = c._poses()
    assert set(poses) == {'root', 'towel#p0000'} and np.allclose(poses['towel#p0000'][0], 1)
    c.pose_sources.append(lambda data: {'root': (np.zeros(3), np.eye(3))})
    with pytest.raises(ValueError, match='two pose sources'):
        c._poses()


def test_gpu_compute_accepts_contract_0_6_0_and_cpu_refuses_it():
    s = {
        'liquid': {'contract_version': '0.6.0', 'threads': 4},
        'compute': {'liquid_solver': 'gpu', 'liquid_backend_id': CO.GPU_BACKEND, 'threads': 4},
    }
    assert CO.requirement(s) == s['compute']
    s['compute'].update(liquid_solver='cpu', liquid_backend_id='pinned-cpu')
    s['liquid']['native_backend'] = {'id': 'pinned-cpu'}
    with pytest.raises(ValueError):
        CO.requirement(s)
    with pytest.raises(ValueError, match='explicit compute'):
        CO.requirement({'liquid': {'contract_version': '0.6.0'}})


def env_for(m, d, **bodies):
    return SimpleNamespace(
        sim=SimpleNamespace(model=SimpleNamespace(_model=m), data=d),
        obj_body_id={k: m.body(v).id for k, v in bodies.items()},
    )


def test_object_friction_and_condim_reach_its_flex_and_only_its_own():
    m, d = cloth()
    env = env_for(m, d, towel='root', block='other')
    assert S.object_flexes(m, m.body('root').id) == [0] and S.object_flexes(m, m.body('other').id) == []
    block = m.geom('block').id
    S.apply_object_friction(env, {'objects': [{'name': 'towel', 'friction': [0.7, 0.005, 0.0001], 'condim': 3}]})
    assert np.allclose(m.flex_friction[0], [0.7, 0.005, 0.0001]) and m.flex_condim[0] == 3
    assert m.geom_condim[block] == 3 and np.allclose(m.geom_friction[block], [1, 0.005, 0.0001])  # untouched
    S.apply_object_friction(env, {'objects': [{'name': 'block', 'condim': 1}]})
    assert m.geom_condim[block] == 1 and np.allclose(m.geom_friction[block], [1, 0.005, 0.0001])
    assert m.flex_condim[0] == 3


@pytest.mark.parametrize('condim', [2, 5, 3.0, True])
def test_condim_must_be_a_mujoco_contact_dimensionality(condim):
    spec = {
        "id": "t",
        "kitchen": {"layout": 1, "style": 1},
        "instruction": "x",
        "robot_anchor": "counter",
        "fixtures": {"counter": {"type": "counter"}},
        "objects": [
            {
                "name": "towel",
                "category": "towel",
                "condim": condim,
                "placement": {"fixture": "counter", "size": [0.3, 0.3], "pos": [0, 0]},
            }
        ],
    }
    with pytest.raises(ValueError, match='condim'):
        check_spec(spec)


def settled_cloth():
    m, d = cloth()
    for _ in range(200):
        mujoco.mj_step(m, d)
    flex = [i for i in range(d.ncon) if int(d.contact[i].geom[1]) < 0 or int(d.contact[i].geom[0]) < 0]
    assert flex, 'the cloth rests on the floor through flex contacts'
    return m, d, flex


def test_flex_contact_sides_resolve_to_vertex_bodies():
    m, d, flex = settled_cloth()
    cloth_bodies = set(int(b) for b in m.flex_vertbodyid)
    floor = m.geom('floor').id
    for i in flex:
        c = d.contact[i]
        b1, b2 = S.contact_bodies(m, c)
        assert {int(c.geom[0]), int(c.geom[1])} == {floor, -1}
        assert (b1 == 0 and b2 in cloth_bodies) or (b2 == 0 and b1 in cloth_bodies)
    fake = SimpleNamespace(geom=(-1, floor), flex=(0, -1), vert=(-1, -1), elem=(1, -1))
    e = int(m.flex_elem[int(m.flex_elemdataadr[0]) + 3])  # element 1, first vertex (dim 2: 3 per element)
    assert S.contact_bodies(m, fake) == (int(m.flex_vertbodyid[e]), 0)
    with pytest.raises(ValueError):
        S.contact_bodies(m, SimpleNamespace(geom=(-1, floor), flex=(-1, -1), vert=(-1, -1), elem=(-1, -1)))


def test_contents_contact_measures_flex_sides_by_their_vertex_bodies(monkeypatch):
    m, d, _ = settled_cloth()
    env = SimpleNamespace(sim=SimpleNamespace(model=m, data=d))
    monkeypatch.setattr(S, '_fx', lambda env, f: SimpleNamespace(contact_geoms=['floor']))
    monkeypatch.setattr(S, '_particles', lambda env, obj, only: [m.body('other').id])
    # the block is fixed in the air; only cloth-floor flex contacts exist, and they are not the block's
    assert S.p_contents_contact(env, {'obj': 'o', 'fixture': 'f'}) is False
    monkeypatch.setattr(S, '_particles', lambda env, obj, only: sorted(set(int(b) for b in m.flex_vertbodyid)))
    assert S.p_contents_contact(env, {'obj': 'o', 'fixture': 'f'}) is True


def test_impact_and_moving_contact_trackers_refuse_flex_objects():
    m, d = cloth()
    env = SimpleNamespace(
        sim=SimpleNamespace(model=SimpleNamespace(_model=m), data=SimpleNamespace(_data=d)),
        obj_body_id={'towel': m.body('root').id, 'block': m.body('other').id},
    )
    with pytest.raises(ValueError, match='flex'):
        S.ImpactTracker(env, ['towel'])
    with pytest.raises(ValueError, match='flex'):
        S.MovingContactTracker(env, [('block', 'towel', None, None, False)])
    tracker = S.ImpactTracker(env, ['block'])
    for _ in range(200):
        mujoco.mj_step(m, d)
        tracker.substep()  # cloth-floor flex contacts are skipped, not misread as geom -1
    assert tracker.impact_speed('block') == 0.0


def test_geom_name_contact_predicates_refuse_flex_objects():
    m, d = cloth()
    env = env_for(m, d, towel='root', block='other')
    for pred, args in ((S.p_contact, {'a': 'block', 'b': 'towel'}), (S.p_on_fixture, {'obj': 'towel', 'fixture': 'c'})):
        with pytest.raises(ValueError, match='flex'):
            pred(env, args)


ON_CLOTH = f"""<mujoco><option timestep="0.002"/>
<worldbody><geom name="floor" type="plane" size="1 1 .1"/>
<body name="side" pos="0.3 0 0.0101"><freejoint/><geom name="side_box" type="box" size=".01 .01 .01" mass="0.01"/></body>
<body name="root" pos="0 0 0.002"><freejoint/>
<inertial pos="0 0 0" mass="0.001" diaginertia="1e-7 1e-7 1e-7"/>
<flexcomp name="cloth" type="grid" dim="2" dof="full" count="{NX} {NY} 1" spacing="0.02 0.02 0.01" radius="0.001"
 mass="0.01"><pin id="7"/><edge equality="true"/></flexcomp>
</body>
<body name="top" pos="0 0 0.02"><freejoint/><geom name="top_box" type="box" size=".012 .012 .004" mass="0.001"/></body>
</worldbody></mujoco>"""


class Names:
    """robosuite-style binding: `model.geom_id2name` raises on -1, as robosuite's does."""

    def __init__(self, m):
        self._model = m

    def geom_id2name(self, i):
        if i < 0:
            raise ValueError(f"No geom with id {i} exists.")
        return mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_GEOM, i)


def on_cloth():
    m = mujoco.MjModel.from_xml_string(ON_CLOTH)
    d = mujoco.MjData(m)
    for _ in range(300):
        mujoco.mj_step(m, d)
    assert any(int(d.contact[i].geom[0]) < 0 or int(d.contact[i].geom[1]) < 0 for i in range(d.ncon))
    data = SimpleNamespace(_data=d, ncon=d.ncon, contact=d.contact, body_xpos=d.xpos)
    return m, d, SimpleNamespace(model=Names(m), data=data)


def test_geom_contact_check_skips_flex_sides_instead_of_raising():
    m, d, sim = on_cloth()
    # the side box rests on the floor (geom-geom); the top box rests on the cloth only (flex-geom)
    assert S.check_geom_contact(sim, 'side_box', 'floor') is True
    assert S.check_geom_contact(sim, ['floor'], SimpleNamespace(contact_geoms=['side_box'])) is True
    assert S.check_geom_contact(sim, 'top_box', 'floor') is False
    assert S.check_geom_contact(sim, 'top_box') is True  # any other side, the cloth included
    assert S.check_geom_contact(sim, 'top_box', 'side_box') is False


def test_in_receptacle_measures_a_flex_receptacle_natively():
    m, d, sim = on_cloth()
    sim.model._model = m
    env = SimpleNamespace(
        sim=sim,
        obj_body_id={k: m.body(k).id for k in ('root', 'top', 'side')},
        objects={'root': SimpleNamespace(horizontal_radius=0.05), 'side': SimpleNamespace(horizontal_radius=0.05)},
    )
    assert S.object_body_contact(env, 'top', 'root') is True
    assert S.object_body_contact(env, 'side', 'root') is False
    assert S.p_in_receptacle(env, {'obj': 'top', 'receptacle': 'root'}) is True
    env.objects['root'] = SimpleNamespace(horizontal_radius=0.0)  # touching but outside 0.7 x radius
    assert S.p_in_receptacle(env, {'obj': 'top', 'receptacle': 'root'}) is False
