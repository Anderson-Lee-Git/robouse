"""Opt-in physical seating evidence for a convex plug and cap; no dynamics edits.

The scene supplies its measured circular mouth and explicit tolerances. This is
neither a fluid seal nor an appliance interlock. Legacy covers is independent.
"""
from __future__ import annotations

import numpy as np


def _number(a, key, *, positive=False):
    v = a[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v):
        raise ValueError(f"seated_cover_v1: {key} must be finite")
    if v < 0 or (positive and v == 0):
        raise ValueError(f"seated_cover_v1: invalid {key}")
    return float(v)


def _hull(points):
    """CCW convex hull, retaining the full projection, without a sampling grid."""
    pts = sorted(set(map(tuple, np.asarray(points, float))))
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    halves = []
    for seq in (pts, pts[::-1]):
        h = []
        for p in seq:
            while len(h) >= 2 and cross(h[-2], h[-1], p) <= 1e-15:
                h.pop()
            h.append(p)
        halves.append(h[:-1])
    hull = np.asarray(halves[0]+halves[1])
    if len(hull) < 3:
        raise ValueError("seated_cover_v1: degenerate cap projection")
    return hull


def geometry_metrics(plug, cap, axis, mouth_radius, mouth_z):
    """Vertices and axis expressed in the jar frame; mouth is centered on z."""
    plug, cap, axis = (np.asarray(x, float) for x in (plug, cap, axis))
    if (plug.ndim != 2 or cap.ndim != 2 or plug.shape[1] != 3 or cap.shape[1] != 3
            or len(plug) < 4 or len(cap) < 4 or axis.shape != (3,)
            or not all(np.isfinite(x).all() for x in (plug, cap, axis))):
        raise ValueError("seated_cover_v1: malformed or nonfinite physical geometry")
    hull = _hull(np.asarray(cap)[:, :2])
    edges = np.roll(hull, -1, axis=0)-hull
    # Distance from the mouth axis to each inward half-plane of the projected
    # solid cap. Every point of a circular mouth fits iff each distance >= r.
    margins = (edges[:, 0]*(-hull[:, 1])-edges[:, 1]*(-hull[:, 0])) / np.linalg.norm(edges, axis=1)
    plug = np.asarray(plug)
    return {
        "coverage_margin_m": float(margins.min()-mouth_radius),
        "plug_radial_excess_m": float(np.linalg.norm(plug[:, :2], axis=1).max()-mouth_radius),
        "plug_top_above_mouth_m": float(plug[:, 2].max()-mouth_z),
        "engagement_m": float(mouth_z-plug[:, 2].min()),
        "cap_lowest_above_mouth_m": float(np.asarray(cap)[:, 2].min()-mouth_z),
        "tilt_deg": float(np.degrees(np.arccos(np.clip(axis[2], -1., 1.)))),
    }


def _mesh(env, obj, local):
    m, d = env.sim.model, env.sim.data
    name = env.objects[obj].naming_prefix + local
    try:
        g = m.geom_name2id(name)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"seated_cover_v1: missing collision mesh {name}") from exc
    if g < 0 or int(m.geom_bodyid[g]) != env.obj_body_id[obj] or int(m.geom_type[g]) != 7 or not (m.geom_contype[g] or m.geom_conaffinity[g]):
        raise ValueError(f"seated_cover_v1: expected rigid root collision mesh {name}")
    mesh = int(m.geom_dataid[g]); start = int(m.mesh_vertadr[mesh]); count = int(m.mesh_vertnum[mesh])
    verts = np.asarray(m.mesh_vert[start:start+count], float)
    if len(verts) < 4:
        raise ValueError(f"seated_cover_v1: empty mesh {name}")
    return g, verts @ np.asarray(d.geom_xmat[g]).reshape(3, 3).T + np.asarray(d.geom_xpos[g])


def seating_metrics(env, a):
    radius = _number(a, "mouth_radius_m", positive=True)
    height = a["mouth_z_m"]
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not np.isfinite(height):
        raise ValueError("seated_cover_v1: mouth_z_m must be finite")
    clearance = _number(a, "radial_tolerance_m")
    seat_tol = _number(a, "seat_tolerance_m")
    engagement = _number(a, "min_engagement_m", positive=True)
    max_tilt = _number(a, "max_tilt_deg")
    if max_tilt >= 90:
        raise ValueError("seated_cover_v1: max_tilt_deg must be below 90")
    names = a["plug_geoms"]
    if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names):
        raise ValueError("seated_cover_v1: nonempty unique plug_geoms required")
    if not isinstance(a["cap_geom"], str) or not a["cap_geom"] or a["cap_geom"] in names:
        raise ValueError("seated_cover_v1: distinct cap_geom required")
    m, d = env.sim.model, env.sim.data
    lb, jb = env.obj_body_id[a["a"]], env.obj_body_id[a["b"]]
    jr = np.asarray(d.body_xmat[jb]).reshape(3, 3)
    lr = np.asarray(d.body_xmat[lb]).reshape(3, 3)
    origin = np.asarray(d.body_xpos[jb])
    plug = np.concatenate([_mesh(env, a["a"], name)[1] for name in names])
    cap_id, cap = _mesh(env, a["a"], a["cap_geom"])
    result = geometry_metrics((plug-origin)@jr, (cap-origin)@jr, jr.T@lr[:, 2], radius, height)
    # Active upward cap/rim contact is support. Side-only plug contact does not
    # count. A jar may have collision geoms on child bodies; walk their ancestry.
    def in_jar(body):
        while body != 0 and body != jb:
            body = int(m.body_parentid[body])
        return body == jb
    supported = False
    for c in d.contact[:d.ncon]:
        g1, g2 = int(c.geom1), int(c.geom2)
        sign = (1 if g2 == cap_id and in_jar(int(m.geom_bodyid[g1])) else
                -1 if g1 == cap_id and in_jar(int(m.geom_bodyid[g2])) else 0)
        if sign and not np.isfinite(np.asarray(c.frame)[:3]).all():
            raise ValueError("seated_cover_v1: nonfinite support normal")
        if sign and c.efc_address >= 0 and sign*np.dot(np.asarray(c.frame)[:3], jr[:, 2]) >= .7:
            supported = True
    result["supported"] = supported
    result["valid"] = bool(supported and result["coverage_margin_m"] >= -1e-9
        and result["plug_radial_excess_m"] <= clearance
        and result["plug_top_above_mouth_m"] <= seat_tol
        and result["engagement_m"] >= engagement
        and abs(result["cap_lowest_above_mouth_m"]) <= seat_tol
        and result["tilt_deg"] <= max_tilt)
    return result


def p_seated_cover_v1(env, a):
    return seating_metrics(env, a)["valid"]
