"""Opt-in 0.4.1: validate accepted motion after physical swept contact.

Historical 0.4.0 remains in validity_v1. A native unconstrained prediction may
cross a wall; its physically resolved motion must still obey the same spacing
bound. Unresolved free-flight impulses and all other validity errors still fail.
"""

import math

import numpy as np

from .domain_v1 import LiquidValidityError
from .solver import sph
from .validity_v1 import ValidatedLiquidScene, ValidatedSPHFluid


class ResolvedSPHFluid(ValidatedSPHFluid):
    def __init__(self, *args, **kwargs):
        self.resolved_large_predictions = 0
        self.maximum_predicted_displacement = 0.0
        super().__init__(*args, **kwargs)

    def resolve_prediction(self, old, free):
        predicted = self.positions()[free]
        speed = np.linalg.norm(self.velocities()[free], axis=1)
        if speed.size and speed.max() * self.params.dt_min > self.params.cfl * self.params.spacing:
            self.fail('native predicted speed requires a time step below dt_min')
        displacement = np.linalg.norm(predicted - old[free], axis=1)
        maximum = float(displacement.max()) if displacement.size else 0.0
        try:
            x, v = self.domain.resolve(old[free], predicted, self.velocities()[free])
        except LiquidValidityError as error:
            self.fail(str(error))
        accepted = np.linalg.norm(x - old[free], axis=1)
        if accepted.size and accepted.max() > self.params.spacing:
            self.fail('resolved native step moved a free particle more than one spacing')
        self.maximum_predicted_displacement = max(self.maximum_predicted_displacement, maximum)
        if maximum > self.params.spacing:
            if self.resolved_large_predictions == 0:
                np.savez_compressed(
                    self.workdir / 'resolved-prediction-first.npz',
                    old_positions=old,
                    predicted_positions=self.positions(),
                    predicted_velocities=self.velocities(),
                    free_mask=free,
                    resolved_free_positions=x,
                    resolved_free_velocities=v,
                    time_s=self.time,
                )
            self.resolved_large_predictions += 1
        return x, v

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
            # Bound relative displacement including gravity acquired during a step.
            relative = speed + wall_speed + np.linalg.norm(p.gravity) * p.dt_max
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

    def reset(self):
        super().reset()
        self.resolved_large_predictions = 0
        self.maximum_predicted_displacement = 0.0


class ResolvedLiquidScene(ValidatedLiquidScene):
    def report(self):
        result = super().report()
        result['validity']['resolved_large_predictions'] = self.fluid.resolved_large_predictions
        result['validity']['maximum_predicted_displacement_m'] = self.fluid.maximum_predicted_displacement
        return result
