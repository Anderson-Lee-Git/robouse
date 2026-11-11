"""Candidate contract 0.5.0: CPU 0.4.3 validity and contact timing on CUDA.

This is opt-in and unadopted until the P11 paired gate passes. The historical
Warp prototype and all CPU implementations are unchanged. Domain operations
stay on the host; DFSPH integration runs on CUDA. No process-wide patch.
"""

import math
import time

import numpy as np

from ..solver import SPHFluid
from ..validity_v1 import ValidatedSPHFluid
from ..validity_v2 import ResolvedSPHFluid
from ..validity_v4 import SubstepContactLiquidScene, SubstepContactSPHFluid
from .solver import WarpFluid


class ValidatedWarpFluid(WarpFluid):
    backend_id = 'warp-dfsph-0.5.0-candidate'
    reference_contract = '0.4.3'

    # Reuse the exact numerical guards and geometric contact implementation.
    fail = ValidatedSPHFluid.fail
    validate = ValidatedSPHFluid.validate
    absorb_at_accepted_time = SubstepContactSPHFluid.absorb_at_accepted_time
    settle = SPHFluid.settle

    def __init__(self, *args, domain, device=None, **kwargs):
        import warp as wp

        if wp.__version__ != '1.19.0':
            raise RuntimeError('liquid backend 0.5.0 candidate requires Warp 1.19.0')
        wp.init()
        selected = wp.get_device(device or 'cuda:0')
        if not selected.is_cuda:
            raise RuntimeError('liquid contract 0.5.0 requires CUDA; CPU fallback is forbidden')
        self.domain = domain
        self.invalid_reason = None
        self.minimum_dt = math.inf
        self.previous_predicted_speed = 0.0
        self.resolved_large_predictions = 0
        self.maximum_predicted_displacement = 0.0
        self.substep_absorbers = []
        super().__init__(*args, device=selected, **kwargs)
        try:
            if self.params.z_sort or self.params.cfl_method or self.params.boundary_method:
                raise ValueError('contract 0.5 requires stable identities and external CFL with Akinci boundaries')
            self.boundary_radii = {
                b.name: float(np.linalg.norm(b.vertices, axis=1).max()) for b in self.boundaries if b.animated
            }
            self.validate()
        except Exception:
            self.close()
            raise

    def resolve_prediction(self, old, free):
        speeds = np.linalg.norm(self.velocities()[free], axis=1)
        raw_speed = float(speeds.max()) if speeds.size else 0.0
        result = ResolvedSPHFluid.resolve_prediction(self, old, free)
        self.previous_predicted_speed = raw_speed
        return result

    def advance(self, t1, pose_at=None):
        if not np.isfinite(t1) or t1 < self.time - 1e-12:
            self.fail('invalid target time')
        self.validate()
        n0 = self.steps
        p = self.params
        while t1 - self._t > 1e-9:
            self.validate()
            poses = pose_at(self.time) if pose_at else self._initial_poses()
            for pose in poses.values():
                if not all(np.isfinite(a).all() for a in pose):
                    self.fail('nonfinite boundary pose/velocity')
            free = self.free_mask
            speed = float(np.linalg.norm(self.velocities()[free], axis=1).max()) if free.any() else 0.0
            wall_speed = self.wall_speed(poses, free, max(speed, self.previous_predicted_speed))
            relative = max(speed, self.previous_predicted_speed) + wall_speed + np.linalg.norm(p.gravity) * p.dt_max
            dt = min(p.dt_max, p.cfl * p.spacing / max(relative, 1e-12))
            if p.surface_tension:
                capillary = math.sqrt(p.density * p.spacing**3 / (2 * math.pi * p.surface_tension))
                dt = min(dt, (p.capillary_safety or 1.0) * capillary)
            if dt < p.dt_min:
                self.fail('relative boundary/particle speed requires a time step below dt_min')
            remaining = t1 - self.time
            if remaining <= dt:
                dt = remaining
            elif remaining < 2 * dt:
                dt = remaining / 2
            self.minimum_dt = min(self.minimum_dt, dt)
            for name, (pos, R, v, w) in poses.items():
                self.set_pose(name, pos, R, v, w)
            self._update_boundaries()
            old = self.positions().copy()
            self._upload()
            started = time.perf_counter()
            self.iterations = self._substep(float(dt))
            self._dev_dirty = True
            self.timing['launch_s'] += time.perf_counter() - started
            self.timing['substeps'] += 1
            if int(self.overflow.numpy()[0]):
                self.fail('GPU neighbour list capacity exceeded')
            if not np.isfinite(self.positions()).all() or not np.isfinite(self.velocities()).all():
                self.fail('nonfinite native step')
            x, v = self.resolve_prediction(old, free)
            self.positions()[free] = x
            self.velocities()[free] = v
            self._t += dt
            self.steps += 1
            # Do not absorb invalid particles to hide an unresolved impulse,
            # penetration, excessive velocity, or nonfinite state.
            self.validate()
            self.absorb_at_accepted_time(pose_at)
            self.validate()
            if self.log_steps:
                self.substeps_log.append((self.time, dt, *self.iterations[:2]))
        return self.steps - n0

    def wall_speed(self, poses, free, particle_speed):
        """Fastest boundary surface speed bound |v| + r |w| over every animated boundary (contracts 0.5.0, 0.6.0)."""
        wall_speed = 0.0
        for name, (_pos, _R, v, w) in poses.items():
            wall_speed = max(wall_speed, float(np.linalg.norm(v) + self.boundary_radii[name] * np.linalg.norm(w)))
        return wall_speed

    def sleep_until(self, t1, pose_at=None):
        self.validate()
        if not np.isfinite(t1) or t1 < self.time:
            self.fail('invalid sleep target time')
        if pose_at:
            poses = pose_at(t1)
            for pose in poses.values():
                if not all(np.isfinite(a).all() for a in pose):
                    self.fail('nonfinite sleeping boundary pose/velocity')
            super().sleep_until(t1, lambda _: poses)
        else:
            super().sleep_until(t1)
        self.validate()

    def reset(self):
        super().reset()
        self.invalid_reason = None
        self.minimum_dt = math.inf
        self.previous_predicted_speed = 0.0
        self.resolved_large_predictions = 0
        self.maximum_predicted_displacement = 0.0
        self.domain.contacts.clear()
        self.overflow.zero_()
        self.validate()


class ValidatedWarpLiquidScene(SubstepContactLiquidScene):
    def report(self):
        result = super().report()
        result['validity']['reference_contract'] = '0.4.3'
        if hasattr(self.fluid, 'gating'):
            result['validity']['wall_speed_gating'] = dict(self.fluid.gating)
        return result


class GatedWarpFluid(ValidatedWarpFluid):
    """Contract 0.7.0: the 0.5.0/0.6.0 GPU fluid with its time step limited only by boundaries that can reach the
    liquid within the step.

    CFL argument. The step must keep every particle-boundary interaction resolved: within one step no boundary sample
    may cross more than a fraction (cfl) of a particle spacing relative to a particle it interacts with. A particle
    interacts with a boundary sample only inside the kernel support h = 4 r. A boundary's samples lie on its mesh,
    inside the sphere of radius r_b (its largest vertex distance from the body origin) about its pose. Over a step of
    at most dt_max the boundary's points move at most s_b dt_max (s_b = |v| + r_b |w|, the bound 0.5.0 already uses)
    and a free particle at most (u + |g| dt_max) dt_max (u = the larger of the current and the previously predicted
    particle speed). So if, at the start of the step, every free particle is farther than
        h + (u + |g| dt_max + s_b) dt_max
    from that sphere, no particle can enter the boundary's kernel support during any step this rule can choose, the
    boundary exerts no force in the step, and its speed cannot affect the step's resolution. Such boundaries are
    excluded from the wall speed; all others enter it exactly as in 0.5.0. With no free particle, the wall speed is
    zero. The particle bound itself, gravity term, CFL number, dt_min and every validity check are unchanged.

    `gating['substeps_changed']` counts wall-speed evaluations (substeps) in which an excluded boundary was faster
    than every included one, i.e. the exclusion lowered the wall-speed term; the chosen step itself changes only when
    that term was the binding limit. `max_excluded*` name the fastest excluded boundary and its speed.
    """

    def __init__(self, *args, **kwargs):
        self.gating = {'substeps_changed': 0, 'max_excluded_wall_speed': 0.0, 'max_excluded': None}
        super().__init__(*args, **kwargs)
        self.support = 4.0 * float(self.params.particle_radius)

    def wall_speed(self, poses, free, particle_speed):
        if not free.any():
            return 0.0
        x = self.positions()[free]
        p = self.params
        drift = (particle_speed + float(np.linalg.norm(p.gravity)) * p.dt_max) * p.dt_max
        included = excluded = 0.0
        excluded_name = None
        for name, (pos, _R, v, w) in poses.items():
            r = self.boundary_radii[name]
            s = float(np.linalg.norm(v) + r * np.linalg.norm(w))
            gap = float(np.sqrt(((x - np.asarray(pos, float)) ** 2).sum(axis=1).min())) - r
            if gap <= self.support + drift + s * p.dt_max:
                included = max(included, s)
            elif s > excluded:
                excluded, excluded_name = s, name
        if excluded > included:
            self.gating['substeps_changed'] += 1
            if excluded > self.gating['max_excluded_wall_speed']:
                self.gating['max_excluded_wall_speed'] = excluded
                self.gating['max_excluded'] = excluded_name
        return included

    def reset(self):
        super().reset()
        self.gating = {'substeps_changed': 0, 'max_excluded_wall_speed': 0.0, 'max_excluded': None}
