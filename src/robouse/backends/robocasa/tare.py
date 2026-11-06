"""Opt-in mechanical scale calibration, private control-step evidence.

No benchmark imports. Joint angles and physical contacts supply the evidence;
evaluation is read-only, and only Monitors.update advances the state machine.
"""
import math


def metrics(env, a, scenario):
    m, d = env.sim.model, env.sim.data
    scale, bowl = a['obj'], a['container']
    sb = set(scenario._subtree(m, env.obj_body_id[scale]))
    bb = set(scenario._subtree(m, env.obj_body_id[bowl]))
    external = set()
    for name in a['other']:
        external.update(scenario._subtree(m, env.obj_body_id[name]))
    for robot in env.robots:
        external.update(scenario._subtree(m, m.body_name2id(robot.robot_model.root_body)))
    plates = {m.geom_name2id(env.objects[scale].naming_prefix + name)
              for name in a['support_geoms']}
    if not plates or any(g < 0 or int(m.geom_bodyid[g]) not in sb or
                         not (m.geom_contype[g] or m.geom_conaffinity[g]) for g in plates):
        raise ValueError('calibrated_zero_v1 requires physical scale support geoms')
    supported, loaded = False, False
    for c in d.contact[:d.ncon]:
        if c.efc_address < 0:
            continue
        g1, g2 = int(c.geom1), int(c.geom2)
        b1, b2 = int(m.geom_bodyid[g1]), int(m.geom_bodyid[g2])
        sign = 1 if g1 in plates and b2 in bb else -1 if g2 in plates and b1 in bb else 0
        supported |= bool(sign and sign * float(c.frame[2]) >= .9)
        loaded |= ((b1 in sb | bb and b2 in external) or
                   (b2 in sb | bb and b1 in external))
    def angle(joint):
        j = scenario._object_joint(env, scale, joint)
        return math.degrees(float(d.qpos[m.jnt_qposadr[j]]))
    ring = angle(a['ring_joint'])
    return {'dial_g': ring - angle(a['pointer_joint']), 'ring_deg': ring,
            'mass_g': scenario.contents_mass_g(env, a['a'], bowl),
            'supported': supported, 'external_load': bool(loaded)}


def advance(state, evidence, step, *, zero_g=5., hold_steps=10, onset_g=3.):
    """Acquire unloaded zero; expire on removal or off-zero ring adjustment.

    P3a: freeze existing credit at the first positive flour mass, before any
    same-control impact/support change. Only earlier controls can invalidate it.
    Publish the frozen decision at >= onset_g; no later calibration excuses it.
    Before flour, infer zero from the calibrated ring, not a loaded pointer.
    """
    if state.get('tare_step') == step:
        return bool(state.get('tare_valid', False))
    if not all(math.isfinite(float(evidence[k])) for k in ('dial_g', 'ring_deg', 'mass_g')):
        raise ValueError('calibrated_zero_v1: nonfinite scale evidence')
    state['tare_step'] = step
    state['tare_evidence'] = dict(evidence)
    if state.get('pour_step') is not None:
        return bool(state.get('tare_valid', False))
    valid = bool(state.get('tare_valid', False))
    if state.get('first_flour_step') is None and evidence['mass_g'] > 0:
        state.update(first_flour_step=step, first_flour_tare_valid=valid)
    if state.get('first_flour_step') is not None:
        valid = state['first_flour_tare_valid']
        state['tare_valid'] = valid
        if evidence['mass_g'] >= onset_g:
            state.update(pour_step=step, untared_pour=not valid)
        return valid
    if valid:
        inferred_zero = state['zero_g'] + evidence['ring_deg'] - state['ring_deg']
        if not evidence['supported'] or abs(inferred_zero) > zero_g:
            valid = False
            state['tare_invalidations'] = state.get('tare_invalidations', 0) + 1
            state['zero_run'] = 0
    eligible = (evidence['mass_g'] == 0 and evidence['supported'] and
                not evidence['external_load'] and abs(evidence['dial_g']) <= zero_g)
    state['zero_run'] = state.get('zero_run', 0) + 1 if eligible else 0
    if state['zero_run'] >= hold_steps:
        if not valid:
            state['tare_acquired_step'] = step
        valid = True
        state.update(zero_g=evidence['dial_g'], ring_deg=evidence['ring_deg'])
    state['tare_valid'] = valid
    return valid


def update(env, item, state, step, scenario):
    a = item['pred']
    return advance(state, metrics(env, a, scenario), step)


def predicate(env, a, *, onset=False):
    mons = getattr(env, 'robouse_monitors', None)
    if mons is None:
        if not hasattr(env, 'robouse_obj_z0'):
            return False
        raise RuntimeError('calibrated_zero_v1: missing monitor history')
    state = mons.state[a['monitor']]
    if state['error']:
        raise RuntimeError('calibrated_zero_v1: calibration evidence failed')
    return bool(state.get('untared_pour' if onset else 'tare_valid', False))
