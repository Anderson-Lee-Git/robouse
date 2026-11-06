"""Host-only per-scene liquid hardware requirements (P11, opt-in)."""

import ctypes
import os

GPU_CONTRACT = '0.5.0'
GPU_BACKEND = 'warp-dfsph-0.5.0-candidate'


def requirement(spec):
    """Validate without importing either solver or inspecting local hardware.

    An absent field preserves historical CPU conditions. GPU scenes require an
    explicit declaration. This record belongs to the trusted host, never observations.
    """
    liquid = spec.get('liquid') or {}
    contract = liquid.get('contract_version', liquid.get('version'))
    compute = spec.get('compute')
    if compute is None:
        if contract == GPU_CONTRACT:
            raise ValueError('liquid 0.5.0 requires an explicit compute field')
        return None
    if not liquid:
        raise ValueError('compute liquid requirements need a liquid scene')
    keys = {'liquid_solver', 'liquid_backend_id', 'threads'}
    if not isinstance(compute, dict) or set(compute) != keys:
        raise ValueError('compute must name liquid_solver, liquid_backend_id and threads only')
    threads = compute['threads']
    if type(threads) is not int or threads <= 0:
        raise ValueError('compute.threads must be a positive integer')
    if threads != liquid.get('threads', 4):
        raise ValueError('compute.threads differs from liquid.threads')
    solver = compute['liquid_solver']
    if solver == 'gpu':
        if contract != GPU_CONTRACT or compute['liquid_backend_id'] != GPU_BACKEND:
            raise ValueError('GPU compute requires contract 0.5.0 and its exact backend id')
    elif solver == 'cpu':
        if contract == GPU_CONTRACT:
            raise ValueError('GPU contract cannot run on CPU')
        backend = liquid.get('native_backend') or {}
        if not backend.get('id') or compute['liquid_backend_id'] != backend['id']:
            raise ValueError('CPU compute backend differs from liquid.native_backend.id')
    else:
        raise ValueError('compute.liquid_solver must be cpu or gpu')
    return dict(compute)


def validate_runtime(spec):
    """Refuse mismatches before constructing a simulator; never change settings."""
    compute = requirement(spec)
    if compute is None:
        return None
    threads = compute['threads']
    if os.environ.get('OMP_NUM_THREADS') != str(threads):
        raise RuntimeError('OMP_NUM_THREADS does not match compute.threads')
    if hasattr(os, 'sched_getaffinity') and len(os.sched_getaffinity(0)) < threads:
        raise RuntimeError('CPU allocation cannot meet compute.threads')
    if os.environ.get('MUJOCO_GL') != 'osmesa':
        raise RuntimeError('compute scenes require CPU rendering with MUJOCO_GL=osmesa')
    if compute['liquid_solver'] == 'gpu':
        import warp as wp

        wp.init()
        if not wp.is_cuda_available():
            raise RuntimeError('GPU scene requires CUDA; CPU fallback is forbidden')
        requested = os.environ.get('LIQUID_GPU_DEVICE', 'cuda:0')
        if not wp.get_device(requested).is_cuda:
            raise RuntimeError('GPU scene requires a CUDA device')
    return compute


def native_thread_count():
    """Read the same libgomp selected by solver.set_threads, without changing it."""
    candidates = set()
    library = None
    with open('/proc/self/maps') as stream:
        for line in stream:
            if '/libgomp' in line:
                candidates.add(line.split()[-1])
            if 'pysplishsplash.libs/libgomp' in line:
                library = line.split()[-1]
                break
    if library is None and len(candidates) == 1:
        library = candidates.pop()
    if library is None:
        raise RuntimeError('cannot identify the native liquid OpenMP runtime')
    runtime = ctypes.CDLL(library)
    runtime.omp_get_max_threads.restype = ctypes.c_int
    return int(runtime.omp_get_max_threads())


def validate_solver(compute, fluid):
    """Confirm the actual solver after creation, not just the requested config."""
    if compute is None:
        return
    if fluid.backend.get('id') != compute['liquid_backend_id']:
        raise RuntimeError('constructed liquid backend differs from compute requirement')
    threads = fluid.threads if compute['liquid_solver'] == 'gpu' else native_thread_count()
    if threads != compute['threads']:
        raise RuntimeError('constructed liquid thread count differs from compute requirement')
    if compute['liquid_solver'] == 'gpu' and not fluid.wp.get_device(fluid.device).is_cuda:
        raise RuntimeError('constructed GPU solver is not running on CUDA')
