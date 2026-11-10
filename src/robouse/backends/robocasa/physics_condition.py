"""Private actual-runtime receipts; loaded by path in the isolated simulator.

Capture is passive. It never forwards, steps, or edits a model. Receipt failures
are infrastructure errors, never policy observations or completion judgments.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
from pathlib import Path

FORMAT = "robouse-physics-condition"
VERSION = "1.0.0"
FILENAME = "physics-condition.json"
RELEASE = {"engine": "4.0.0", "protocol_version": "3.0.0", "export_version": "2.0.0"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def requirement(value):
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in RELEASE.items()):
        raise ValueError("unsupported physics-condition requirement")
    if not value.get("scene_id") or not value.get("scene_version"):
        raise ValueError("physics condition requires scene identity and version")
    return value


def seal(payload):
    payload = json.loads(json.dumps(payload, allow_nan=False))
    return {"format": FORMAT, "version": VERSION, "payload": payload, "condition_hash": digest(payload)}


def validate(receipt):
    if not isinstance(receipt, dict) or receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise ValueError("missing or unsupported physics-condition receipt")
    payload = receipt.get("payload")
    if not isinstance(payload, dict) or receipt.get("condition_hash") != digest(payload):
        raise ValueError("physics-condition digest mismatch")
    required = {
        "requirement",
        "engine",
        "sources",
        "packages",
        "compiled",
        "renderer",
        "liquid",
        "controller",
        "default_pins",
        "reset",
    }
    if not required <= payload.keys():
        raise ValueError("incomplete physics-condition receipt")
    requirement(payload["requirement"])
    if payload["engine"].get("library") != RELEASE["engine"] or payload["engine"].get("bindings") != RELEASE["engine"]:
        raise ValueError("actual engine does not match required engine")
    return receipt


def require_equal(expected, actual):
    validate(expected)
    validate(actual)
    if expected != actual:
        raise ValueError("physics condition changed; use a separately versioned run")


def record_or_check(path, receipt, *, must_exist=False):
    """Lock readers and writers; atomic publication avoids a partially written receipt.

    A missing receipt on resume is an error, including a deleted/corrupt receipt.
    The lock also serializes simultaneous program practice resets.
    """
    import fcntl
    import tempfile

    validate(receipt)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            require_equal(json.loads(path.read_text()), receipt)
            return
        if must_exist:
            raise ValueError("cannot resume without the actual physics-condition receipt")
        fd, name = tempfile.mkstemp(prefix=".condition-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def source(root):
    root = Path(root)
    files = {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob("*.py"))}
    provenance = root.parent / "mujoco-migration-source.json"
    return {
        "tree_sha256": digest(files),
        "files": files,
        "provenance": json.loads(provenance.read_text()) if provenance.is_file() else None,
    }


def portable(value):
    """Resource content, not its installation path, defines a condition."""
    if isinstance(value, dict):
        return {k: portable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [portable(v) for v in value]
    if isinstance(value, str) and Path(value).is_absolute():
        p = Path(value)
        if not p.is_file():
            raise ValueError("condition contains an unresolved absolute resource path")
        return {"resource_sha256": file_hash(p)}
    return value


def values(obj):
    import numpy as np

    out = {}
    for key in dir(obj):
        if key.startswith("_"):
            continue
        value = getattr(obj, key)
        if isinstance(value, np.ndarray) and value.dtype.kind in "biuf":
            out[key] = value.tolist()
        elif isinstance(value, (int, float, bool)):
            out[key] = value
    return out


def array_hashes(obj, names=None):
    import numpy as np

    out = {}
    for name in names if names is not None else dir(obj):
        if name.startswith("_") or name.endswith("pathadr"):
            continue
        a = getattr(obj, name, None)
        if isinstance(a, np.ndarray) and a.dtype.kind in "biuf":
            a = np.ascontiguousarray(a)
            out[name] = {
                "shape": list(a.shape),
                "dtype": str(a.dtype),
                "sha256": hashlib.sha256(a.tobytes()).hexdigest(),
            }
    return out


def capture(worker, requested, render_size, reset):
    import mujoco
    import numpy as np
    import robocasa
    import robosuite
    from OpenGL import GL

    requirement(requested)
    if mujoco.mj_versionString() != "4.0.0" or mujoco.__version__ != "4.0.0":
        raise ValueError("this export requires actual MuJoCo library and bindings 4.0.0")
    if requested["scene_id"] != worker.scenario["id"]:
        raise ValueError("physics requirement does not match scene identity")
    sim = worker.env.sim
    m, d = sim.model._model, sim.data._data
    context = sim._render_context_offscreen
    context.gl_ctx.make_current()
    renderer = {
        k: GL.glGetString(v).decode()
        for k, v in {"vendor": GL.GL_VENDOR, "renderer": GL.GL_RENDERER, "version": GL.GL_VERSION}.items()
    }
    renderer.update(
        {
            "backend": os.environ.get("MUJOCO_GL"),
            "render_size": list(render_size),
            "visual": {k: values(getattr(m.vis, k)) for k in ("global_", "quality", "headlight", "map", "scale")},
            "scene_flags": np.asarray(context.scn.flags).tolist(),
            "threads": {
                k: os.environ.get(k)
                for k in ("LP_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
            },
        }
    )
    mapped = set()
    for line in Path("/proc/self/maps").read_text().splitlines():
        name = line.split()[-1]
        if name.startswith("/") and any(
            s in Path(name).name for s in ("OSMesa", "LLVM", "libmujoco", "libcuda", "libnvidia", "pysplishsplash")
        ):
            mapped.add(name)
    renderer["libraries"] = sorted({(Path(p).name, file_hash(p)) for p in mapped})
    packages = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}
    sources = {
        "robosuite": source(Path(robosuite.__file__).parent),
        "robocasa": source(Path(robocasa.__file__).parent),
        "worker": source(Path(__file__).parent),
    }
    if any(sources[name]["provenance"] is None for name in ("robocasa", "robosuite")):
        raise ValueError("missing upstream revision and migration patch provenance; run the pinned setup")
    # Plugins are code conditions too, even though robouse must not import a task suite.
    for name in filter(None, os.environ.get("ROBOUSE_ROBOCASA_PLUGINS", "").split(",")):
        spec = importlib.util.find_spec(name.strip())
        if spec is None or spec.origin is None:
            raise ValueError("cannot identify scenario plugin source")
        package = importlib.util.find_spec(name.strip().split(".")[0])
        sources["plugin:" + name.strip()] = source(Path(next(iter(package.submodule_search_locations))))
    compiled = {
        "options": values(m.opt),
        "names_sha256": hashlib.sha256(m.names).hexdigest(),
        "counts": {k: int(getattr(m, k)) for k in ("nq", "nv", "nu", "na", "nbody", "ngeom", "njnt")},
        "arrays": array_hashes(m),
    }
    liquid = {"requested_sha256": digest(worker.scenario.get("liquid")), "actual": None}
    live = getattr(worker.env, "_liquid_scene", None)
    if worker.scenario.get("liquid"):
        if live is None:
            raise ValueError("liquid scene has no actual solver")
        liquid["actual"] = {
            "backend": portable(live.fluid.backend),
            "contract_version": live.cfg.get("contract_version", live.cfg.get("version", "0.2.0")),
            "threads": getattr(live.fluid, "threads", None),
        }
    pins = [
        {
            "field": "ccd_iterations",
            "value": 50,
            "evidence": "researcher D3; https://github.com/google-deepmind/mujoco/blob/3.3.1/src/engine/engine_io.c",
        },
        {
            "field": "island",
            "value": "disable",
            "evidence": "https://mujoco.readthedocs.io/en/4.0.0/changelog.html#version-3-3-6",
        },
        {"field": "headlight.active", "value": 1, "evidence": "https://mujoco.readthedocs.io/en/4.0.0/changelog.html"},
    ]
    if (
        int(m.opt.ccd_iterations) != 50
        or not (int(m.opt.disableflags) & int(mujoco.mjtDisableBit.mjDSBL_ISLAND))
        or int(m.vis.headlight.active) != 1
    ):
        raise ValueError("compiled default-preservation settings do not match the migration condition")
    payload = {
        "requirement": requested,
        "engine": {
            "name": "mujoco",
            "library": mujoco.mj_versionString(),
            "bindings": mujoco.__version__,
            "python": platform.python_version(),
        },
        "packages": packages,
        "sources": sources,
        "compiled": compiled,
        "renderer": renderer,
        "liquid": liquid,
        "reset": {
            **reset,
            "scenario_sha256": digest(portable(worker.scenario)),
            "arrays": array_hashes(
                d, ("qpos", "qvel", "act", "ctrl", "qacc_warmstart", "mocap_pos", "mocap_quat", "eq_active")
            ),
        },
        "controller": {
            "control": worker.control,
            "control_freq": worker.env.control_freq,
            "config_sha256": digest(portable(worker._condition_controller_config)),
        },
        "default_pins": pins,
    }
    return validate(seal(payload))
