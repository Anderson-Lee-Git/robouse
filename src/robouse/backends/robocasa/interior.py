"""Opt-in, researcher-configured tapered interior regions (metres, container frame)."""
from __future__ import annotations

import numpy as np


def tapered_contains_v1(points, config):
    """Point membership in a capped circular frustum, with explicit face tolerance.

    z/radius endpoints describe the *interior*, in the container root frame.
    tolerance_m expands the floor and mouth along z and the cone along its unit
    normal, not along unnormalised axes. It is mandatory; no particle tolerance
    is inherited. This tests points, not intersection of arbitrary tool geometry.
    """
    keys = {"z_min_m", "z_max_m", "radius_min_m", "radius_max_m", "tolerance_m"}
    if not isinstance(config, dict) or set(config) != keys:
        raise ValueError("interior_v1 requires z/radius endpoints and tolerance_m")
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not np.isfinite(v) for v in config.values()):
        raise ValueError("interior_v1 parameters must be finite numbers")
    z0, z1 = config["z_min_m"], config["z_max_m"]
    r0, r1 = config["radius_min_m"], config["radius_max_m"]
    tol = config["tolerance_m"]
    if z1 <= z0 or min(r0, r1) <= 0 or tol < 0:
        raise ValueError("interior_v1 requires increasing heights, positive radii and nonnegative tolerance")
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or not np.isfinite(p).all():
        raise ValueError("interior_v1 requires finite Nx3 points")
    slope = (r1 - r0) / (z1 - z0)
    signed_side_distance = (np.linalg.norm(p[:, :2], axis=1)
                            - r0 - slope * (p[:, 2] - z0)) / np.hypot(1., slope)
    return ((p[:, 2] >= z0 - tol) & (p[:, 2] <= z1 + tol)
            & (signed_side_distance <= tol))


def contents_metrics_v1(env, obj, container, only, config, scenario):
    """Jointed marker/body positions in one explicit container's tapered interior."""
    import re

    if not isinstance(container, str):
        raise ValueError("interior_v1 requires one container, not a container list")
    m, d = env.sim.model, env.sim.data
    bodies = [b for b in scenario._subtree(m, env.obj_body_id[obj]) if m.body_jntnum[b] > 0
              and (not only or re.search(only, m.body(b).name or ""))]
    if not bodies:
        raise ValueError(f"contents_outside: {obj!r} has no matching jointed bodies")
    root = env.obj_body_id[container]
    local = (np.asarray(d.xpos[bodies]) - d.xpos[root]) @ np.asarray(d.xmat[root]).reshape(3, 3)
    outside = ~tapered_contains_v1(local, config)
    return {"bodies": len(bodies), "outside": int(outside.sum()),
            "fraction": float(outside.mean()), "tilt_deg": scenario._tilt_deg(env, container)}
