"""Opt-in liquid contract 0.4.0; the historical solver and queries remain unchanged."""

import math

import numpy as np

from .domain_v1 import LiquidValidityError
from .scene import LiquidScene
from .solver import SPHFluid, sph


class ValidatedSPHFluid(SPHFluid):
    """Contract 0.4: explicit solid coverage and bounded numerical integration.

    Native DFSPH, materials, absorption, resolution and one-way coupling stay
    unchanged. Old contracts instantiate SPHFluid directly.
    """

    def __init__(self, *args, domain, **kwargs):
        self.domain = domain
        self.invalid_reason = None
        self.minimum_dt = math.inf
        super().__init__(*args, **kwargs)
        if self.params.z_sort or self.params.cfl_method or self.params.boundary_method:
            self.close()
            raise ValueError('contract 0.4 requires stable identities and external CFL with Akinci boundaries')
        self.boundary_radii = {
            b.name: float(np.linalg.norm(b.vertices, axis=1).max()) for b in self.boundaries if b.animated
        }
        self.validate()

    def fail(self, reason):
        self.invalid_reason = f'liquid 0.4 invalid at {self.time:.9f}s: {reason}'
        # Preserve the rejected state for host diagnostics. No particle is discarded.
        np.savez_compressed(
            self.workdir / 'invalid-state.npz',
            positions=self.positions(),
            velocities=self.velocities(),
            free_mask=self.free_mask,
        )
        raise LiquidValidityError(self.invalid_reason)

    def validate(self):
        if self.invalid_reason:
            raise LiquidValidityError(self.invalid_reason)
        x = self.positions()
        v = self.velocities()
        if x.shape != (self.n, 3) or v.shape != (self.n, 3) or not np.isfinite(x).all() or not np.isfinite(v).all():
            self.fail('nonfinite or inconsistent particle state')
        free = self.free_mask
        if not free.any():
            return
        try:
            self.domain.validate(x[free])
        except LiquidValidityError as e:
            self.fail(str(e))
        floor = self.domain.floor
        local = (x[free] - floor.centre) @ floor.rotation
        # The numerical domain is the actual modeled room floor footprint, with
        # one particle radius of roundoff/contact reach, not the neighbor grid.
        if np.any(np.abs(local[:, :2]) > floor.half[:2] + self.params.particle_radius):
            self.fail('free liquid left the modeled floor footprint')
        if np.any(local[:, 2] < floor.half[2] - 2e-6):
            self.fail('free liquid passed below the modeled floor')
        speed = np.linalg.norm(v[free], axis=1)
        if speed.max() * self.params.dt_min > self.params.cfl * self.params.spacing:
            self.fail('particle speed requires a time step below dt_min')

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
            # Reject unresolved impulses rather than clipping velocity or advancing
            # another unsafe neighborhood search. Ordinary gravity is in the CFL.
            displacement = np.linalg.norm(self.positions()[free] - old[free], axis=1)
            if displacement.size and displacement.max() > p.spacing:
                self.fail('native step moved a free particle more than one spacing')
            try:
                x, v = self.domain.resolve(old[free], self.positions()[free], self.velocities()[free])
            except LiquidValidityError as e:
                self.fail(str(e))
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
        # An explicit reset restores the entire initial state, including after a
        # rejected nonfinite state, before native code rebuilds neighborhoods.
        self.positions()[:] = self.x0
        self.velocities()[:] = 0
        super().reset()
        self.invalid_reason = None
        self.minimum_dt = math.inf
        self.domain.contacts.clear()
        self.validate()


class ValidatedLiquidScene(LiquidScene):
    def labels(self, film=0.02):
        self.fluid.validate()
        labels = super().labels(film)
        # Below a finite slab is not necessarily inside solid material: a drop
        # may arrive laterally from a real edge. Physical contacts and validity
        # are enforced by the solver, independently of the grading partition.
        labels[labels == 'below'] = 'elsewhere'
        return labels

    def wetting_ml(self, name, distance_m=None):
        self.fluid.validate()
        return super().wetting_ml(name, distance_m)

    def report(self):
        result = super().report()
        result['validity'] = {
            'static_contact_counts': dict(self.fluid.domain.contacts),
            'minimum_dt_s': self.fluid.minimum_dt if math.isfinite(self.fluid.minimum_dt) else None,
            'floor_geom': self.fluid.domain.floor.name,
        }
        return result
