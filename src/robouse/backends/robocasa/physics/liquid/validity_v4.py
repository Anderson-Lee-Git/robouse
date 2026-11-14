"""Opt-in 0.4.3: resolve absorber contact at accepted native-step boundaries.

The mesh-distance predicate, capacity and accounted reservoir are unchanged.
An invalid native prediction must fail before it can transfer into a reservoir.
Historical contracts retain their rigid-synchronization-only uptake cadence.
"""

import math

import numpy as np

from .solver import sph
from .validity_v3 import PredictiveLiquidScene, PredictiveSPHFluid


class SubstepContactSPHFluid(PredictiveSPHFluid):
    def __init__(self, *args, **kwargs):
        self.substep_absorbers = []
        super().__init__(*args, **kwargs)

    def absorb_at_accepted_time(self, pose_at):
        if not self.substep_absorbers:
            return
        # Geometry uses the actual end of the accepted fluid step, including
        # interpolation inside the enclosing MuJoCo interval.
        poses = pose_at(self.time) if pose_at else self._initial_poses()
        for absorber in self.substep_absorbers:
            for name in absorber.pose_names():
                pos, rotation, velocity, angular_velocity = poses[name]
                if not all(np.isfinite(a).all() for a in (pos, rotation, velocity, angular_velocity)):
                    self.fail('nonfinite absorber pose/velocity')
            absorber.update_poses(self, poses)

    def advance(self, t1, pose_at=None):
        if not np.isfinite(t1) or t1 < self.time - 1e-12:
            self.fail('invalid target time')
        self.validate()
        n0 = self.steps
        p = self.params
        while t1 - self._t > 1e-9:
            self.validate()
            poses = pose_at(self.time) if pose_at else self._initial_poses()
            wall_speed = 0.0
            for name, (pos, R, v, w) in poses.items():
                if not all(np.isfinite(a).all() for a in (pos, R, v, w)):
                    self.fail('nonfinite boundary pose/velocity')
                wall_speed = max(wall_speed, float(np.linalg.norm(v) + self.boundary_radii[name] * np.linalg.norm(w)))
            free = self.free_mask
            speed = float(np.linalg.norm(self.velocities()[free], axis=1).max()) if free.any() else 0.0
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
            self.tm.setTimeStepSize(dt)
            self.tm.setTime(self.time)
            for name, (pos, R, v, w) in poses.items():
                self.set_pose(name, pos, R, v, w)
            self._update_boundaries()
            old = self.positions().copy()
            self.base.timeStepNoGUI()
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
                ts, S = self.sim.getTimeStep(), sph()
                self.substeps_log.append(
                    (
                        self.time,
                        dt,
                        ts.getValueUInt(S.TimeStepDFSPH.SOLVER_ITERATIONS),
                        ts.getValueUInt(S.TimeStepDFSPH.SOLVER_ITERATIONS_V),
                    )
                )
        return self.steps - n0


class SubstepContactLiquidScene(PredictiveLiquidScene):
    def report(self):
        result = super().report()
        result['validity']['absorption_timing'] = 'accepted_native_substeps_and_rigid_sync'
        return result
