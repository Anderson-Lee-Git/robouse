"""Opt-in finite stream geometry and renewable procedure credit, version 1.

These are contact-history abstractions, not pathogen or fluid simulations.
Legacy under_water and fired semantics are deliberately independent.
"""
from __future__ import annotations

import numpy as np


def finite_stream_metrics(env, a, scenario):
    """First collision hit on the visible water site's axis must be the object.

    Use group 0, the same physical-geometry ray group as StreamTracker. Unlike
    that particle-force helper, robot geometry also blocks this interaction.
    The root must be within xy_m and between the actual site's end planes.
    """
    import mujoco
    _fx, _subtree = scenario._fx, scenario._subtree

    radius = a.get("xy_m", 0.05)
    if isinstance(radius, bool) or not isinstance(radius, (float, int)) or not np.isfinite(radius) or radius <= 0:
        raise ValueError("finite_stream_v1 xy_m must be positive finite metres")
    fx = _fx(env, a["fixture"])
    m, d = env.sim.model._model, env.sim.data._data
    sid = m.site(f"{fx.naming_prefix}water").id
    if int(m.site_type[sid]) not in (mujoco.mjtGeom.mjGEOM_CYLINDER, mujoco.mjtGeom.mjGEOM_CAPSULE):
        raise ValueError("finite_stream_v1 requires a cylindrical water site")
    half = float(m.site_size[sid][1])
    axis = d.site_xmat[sid].reshape(3, 3)[:, 2].copy()
    if axis[2] < 0:
        axis *= -1
    if axis[2] < .999 or half <= 0:
        raise ValueError("finite_stream_v1 requires a vertical finite water site")
    center = np.array(d.site_xpos[sid])
    root = np.array(d.xpos[env.obj_body_id[a["obj"]]])
    delta = root - center
    along = float(delta @ axis)
    radial = float(np.linalg.norm(delta - along * axis))
    offset = a.get("outlet_offset_m", 0.0)
    if (isinstance(offset, bool) or not isinstance(offset, (float, int))
            or not np.isfinite(offset) or not 0 <= offset < half):
        raise ValueError("finite_stream_v1 outlet_offset_m must be finite and within the upper half")
    start = center + axis * (half - offset - 1e-5)  # below the calibrated outlet surface
    gid = np.array([-1], dtype=np.int32)
    distance = float(mujoco.mj_ray(m, d, start, -axis, np.array([1, 0, 0, 0, 0, 0], np.uint8), 1, -1, gid))
    hit = int(gid[0])
    own = _subtree(m, env.obj_body_id[a["obj"]])
    physical = hit >= 0 and bool(m.geom_contype[hit] or m.geom_conaffinity[hit])
    valid = (bool(fx.get_handle_state(env)["water_on"]) and -half <= along <= half - offset
             and radial <= radius and 0 <= distance <= 2 * half - offset - 1e-5
             and physical and int(m.geom_bodyid[hit]) in own)
    return {"valid": bool(valid), "root_axial_m": along, "root_radial_m": radial,
            "half_length_m": half, "outlet_offset_m": offset, "hit_geom": m.geom(hit).name if hit >= 0 else None,
            "hit_distance_m": distance}


def validate_reset_credit(item):
    c = item["reset_credit_v1"]
    if (not isinstance(c, dict) or set(c) != {"pred", "hold_steps"}
            or item.get("when", "step") != "step"
            or type(c["hold_steps"]) is not int or c["hold_steps"] < 1):
        raise ValueError("reset_credit_v1 requires pred and positive integer hold_steps on a step monitor")


def update_credit(env, item, state, held, step, run, evaluate):
    """Update once per monitor control step; history is retained after revocation."""
    validate_reset_credit(item)
    config = item["reset_credit_v1"]
    invalid = evaluate(env, config["pred"])
    state.setdefault("credit_valid", False)
    state["invalid_run"] = state.get("invalid_run", 0) + 1 if invalid else 0
    if invalid:  # even a brief contact interrupts acquisition of a new rinse
        held = False
    if state["invalid_run"] >= config["hold_steps"] and state["credit_valid"]:
        state["credit_valid"] = False
        state["invalidated_at"] = step
        state["invalidations"] = state.get("invalidations", 0) + 1
    if held and run + 1 >= int(item.get("hold_steps", 1)) and not state["credit_valid"]:
        state["credit_valid"] = True
        state["restored_at"] = step
    return held


def p_credit_valid_v1(env, a):
    mons = getattr(env, "robouse_monitors", None)
    if mons is None:
        if not hasattr(env, "robouse_obj_z0"):
            return False
        raise RuntimeError("credit_valid_v1: missing monitor history")
    name = a["monitor"]
    item = next(m for m in mons.items if m["id"] == name)
    if "reset_credit_v1" not in item:
        raise ValueError("credit_valid_v1 requires a reset_credit_v1 monitor")
    state = mons.state[name]
    if state["error"]:
        raise RuntimeError("credit_valid_v1: referenced monitor has an error")
    return state.get("credit_valid", False)
