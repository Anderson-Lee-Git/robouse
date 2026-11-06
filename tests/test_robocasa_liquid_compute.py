"""Hardware declarations must not silently change a benchmark condition."""

from types import SimpleNamespace

import pytest

from robouse.backends.robocasa.physics import load_liquid

C = load_liquid('compute')


def spec(solver='cpu'):
    backend = C.GPU_BACKEND if solver == 'gpu' else 'pinned-cpu'
    return {
        'liquid': {
            'contract_version': '0.5.0' if solver == 'gpu' else '0.4.3',
            'native_backend': {'id': 'pinned-cpu'},
            'threads': 4,
        },
        'compute': {'liquid_solver': solver, 'liquid_backend_id': backend, 'threads': 4},
    }


def test_absent_field_preserves_historical_scenes():
    assert C.requirement({}) is None
    assert C.requirement({'liquid': {'contract_version': '0.4.3'}}) is None


@pytest.mark.parametrize('solver', ['cpu', 'gpu'])
def test_exact_requirement_round_trip(solver):
    s = spec(solver)
    result = C.requirement(s)
    assert result == s['compute'] and result is not s['compute']


@pytest.mark.parametrize(
    'field,value',
    [
        ('threads', 2),
        ('threads', True),
        ('threads', 0),
        ('threads', '4'),
        ('liquid_backend_id', 'different'),
        ('liquid_solver', 'automatic'),
    ],
)
def test_schema_mismatches_fail(field, value):
    s = spec()
    s['compute'][field] = value
    with pytest.raises(ValueError):
        C.requirement(s)


def test_gpu_requires_declaration_and_matching_contract():
    s = spec('gpu')
    del s['compute']
    with pytest.raises(ValueError, match='explicit compute'):
        C.requirement(s)
    s = spec('gpu')
    s['liquid']['contract_version'] = '0.4.3'
    with pytest.raises(ValueError):
        C.requirement(s)
    s = spec()
    s['liquid']['contract_version'] = '0.5.0'
    with pytest.raises(ValueError):
        C.requirement(s)


def test_nonliquid_scene_cannot_declare_a_liquid_solver():
    s = spec()
    del s['liquid']
    with pytest.raises(ValueError):
        C.requirement(s)


def test_runtime_refuses_thread_and_render_mismatches(monkeypatch):
    monkeypatch.setenv('OMP_NUM_THREADS', '2')
    monkeypatch.setenv('MUJOCO_GL', 'osmesa')
    monkeypatch.setattr(C.os, 'sched_getaffinity', lambda _: set(range(4)))
    with pytest.raises(RuntimeError, match='OMP_NUM_THREADS'):
        C.validate_runtime(spec())
    monkeypatch.setenv('OMP_NUM_THREADS', '4')
    assert C.validate_runtime(spec()) == spec()['compute']
    monkeypatch.setenv('MUJOCO_GL', 'egl')
    with pytest.raises(RuntimeError, match='CPU rendering'):
        C.validate_runtime(spec())
    monkeypatch.setenv('MUJOCO_GL', 'osmesa')
    monkeypatch.setattr(C.os, 'sched_getaffinity', lambda _: {0, 1})
    with pytest.raises(RuntimeError, match='allocation'):
        C.validate_runtime(spec())


def test_no_gpu_is_an_error_not_cpu_fallback(monkeypatch):
    import sys

    monkeypatch.setenv('OMP_NUM_THREADS', '4')
    monkeypatch.setenv('MUJOCO_GL', 'osmesa')
    monkeypatch.setattr(C.os, 'sched_getaffinity', lambda _: set(range(4)))
    monkeypatch.setitem(sys.modules, 'warp', SimpleNamespace(init=lambda: None, is_cuda_available=lambda: False))
    with pytest.raises(RuntimeError, match='fallback is forbidden'):
        C.validate_runtime(spec('gpu'))


def test_actual_backend_and_threads_are_checked(monkeypatch):
    compute = spec()['compute']
    fluid = SimpleNamespace(backend={'id': 'different'}, threads=4)
    monkeypatch.setattr(C, 'native_thread_count', lambda: fluid.threads)
    with pytest.raises(RuntimeError, match='backend differs'):
        C.validate_solver(compute, fluid)
    fluid.backend['id'] = 'pinned-cpu'
    fluid.threads = 2
    with pytest.raises(RuntimeError, match='thread count differs'):
        C.validate_solver(compute, fluid)
    fluid.threads = 4
    C.validate_solver(compute, fluid)
