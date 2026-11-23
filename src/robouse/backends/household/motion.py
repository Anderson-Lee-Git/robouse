"""Joint references for the arm's position servos, one per 50 Hz control tick (after Embodied Safety Exam's
`sim/motion.py`).

The FR3's Menagerie servos are kp (target - q) - kv qdot with kv / kp = `lead` (0.1 s), so a joint trails a moving
target by lead x its speed. The controller sends `ref + lead * ref_velocity` (`servo_target`), which cancels that lag.

- `Tracker`: a reference that chases a commanded goal at most at the joint velocity and acceleration limits, each
  joint on its own (Joint- and EEF-mode `act`: the goal moves every tick).
- `joint_move`: a straight line in joint space, all joints on one trapezoidal profile (`move_joints_to`).
- `path_move`: along a given row of joint configurations (the IK solutions of a straight hand path, `move_to_pose`),
  slowed down until every joint keeps its limits.
"""

from __future__ import annotations

import math

import numpy as np


def servo_target(ref: np.ndarray, vel: np.ndarray, lead: float, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return np.clip(ref + lead * vel, lo, hi)


class Tracker:
    """Per-joint time-optimal approach to a goal under velocity and acceleration limits."""

    def __init__(self, q0, vel_limits, acc_limits, dt: float):
        self.q = np.asarray(q0, dtype=np.float64).copy()
        self.v = np.zeros_like(self.q)
        self.goal = self.q.copy()
        self.vmax = np.asarray(vel_limits, dtype=np.float64)
        self.amax = np.asarray(acc_limits, dtype=np.float64)
        self.dt = float(dt)

    def reset(self, q) -> None:
        self.q = np.asarray(q, dtype=np.float64).copy()
        self.v[:] = 0.0
        self.goal = self.q.copy()

    def set_state(self, q, v) -> None:
        self.q = np.asarray(q, dtype=np.float64).copy()
        self.v = np.asarray(v, dtype=np.float64).copy()

    def step(self) -> tuple[np.ndarray, np.ndarray]:
        dt, a = self.dt, self.amax
        e = self.goal - self.q
        # the speed from which the joint can still stop at the goal, one tick of braking to spare
        v_stop = np.sign(e) * np.minimum(self.vmax, np.maximum(np.sqrt(2.0 * a * np.abs(e)) - a * dt, 0.0))
        v = np.clip(v_stop, self.v - a * dt, self.v + a * dt)
        q = self.q + v * dt
        # land on the goal instead of dithering around it
        close = (np.abs(self.goal - q) < a * dt * dt) & (np.abs(v) <= a * dt * 2)
        q = np.where(close, self.goal, q)
        v = np.where(close, 0.0, v)
        self.q, self.v = q, v
        return q.copy(), v.copy()

    @property
    def at_goal(self) -> bool:
        return bool(np.all(self.q == self.goal) and np.all(self.v == 0.0))


def trapezoid(duration: float, ramp: float, t: float) -> tuple[float, float]:
    """Progress s in [0, 1] and its rate at time t of a profile with linear ramps of length `ramp` at both ends."""
    if duration <= 0.0:
        return 1.0, 0.0
    ramp = min(max(ramp, 1e-9), duration / 2.0)
    peak = 1.0 / (duration - ramp)
    t = min(max(t, 0.0), duration)
    if t < ramp:
        return 0.5 * peak * t * t / ramp, peak * t / ramp
    if t <= duration - ramp:
        return peak * (t - 0.5 * ramp), peak
    u = duration - t
    return 1.0 - 0.5 * peak * u * u / ramp, peak * u / ramp


def joint_move(q0, q1, vel_limits, acc_limits, dt: float, speed: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Positions and velocities at t = dt, 2 dt, ..., ending exactly at q1 at rest."""
    q0, q1 = np.asarray(q0, dtype=np.float64), np.asarray(q1, dtype=np.float64)
    vmax = np.asarray(vel_limits, dtype=np.float64) * speed
    amax = np.asarray(acc_limits, dtype=np.float64) * speed * speed
    d = q1 - q0
    dist = np.abs(d)
    if float(np.max(dist)) < 1e-9:
        return q1[None, :].copy(), np.zeros((1, len(q1)))
    with np.errstate(divide="ignore"):
        v_s = float(np.min(np.where(dist > 0, vmax / dist, np.inf)))
        a_s = float(np.min(np.where(dist > 0, amax / dist, np.inf)))
    if v_s * v_s / a_s >= 1.0:  # triangular
        ramp = math.sqrt(1.0 / a_s)
        duration = 2.0 * ramp
    else:
        ramp = v_s / a_s
        duration = 1.0 / v_s + ramp
    n = max(int(math.ceil(duration / dt - 1e-9)), 1)
    stretch = n * dt / duration
    duration, ramp = duration * stretch, ramp * stretch
    pos, vel = np.zeros((n, len(q0))), np.zeros((n, len(q0)))
    for k in range(n):
        s, sd = trapezoid(duration, ramp, (k + 1) * dt)
        pos[k], vel[k] = q0 + d * s, d * sd
    pos[-1], vel[-1] = q1, 0.0
    return pos, vel


def path_move(q_path, vel_limits, acc_limits, dt: float, min_duration: float = 0.0, ramp_fraction: float = 0.25):
    """Follow `q_path` (rows equally spaced in path progress, first row = start); the duration is stretched until the
    sampled joint velocities and accelerations keep the limits."""
    q_path = np.asarray(q_path, dtype=np.float64)
    vmax, amax = np.asarray(vel_limits, dtype=np.float64), np.asarray(acc_limits, dtype=np.float64)
    m = q_path.shape[0] - 1
    if m < 1:
        return q_path[-1:].copy(), np.zeros((1, q_path.shape[1]))
    grid = np.linspace(0.0, 1.0, m + 1)
    seg = np.max(np.abs(np.diff(q_path, axis=0)) / vmax, axis=1).sum()  # time at full speed
    duration = max(float(min_duration), float(seg), 2 * dt)
    pos = vel = None
    for _ in range(12):
        n = max(int(math.ceil(duration / dt - 1e-9)), 2)
        total = n * dt
        ramp = total * ramp_fraction
        s = np.array([trapezoid(total, ramp, k * dt)[0] for k in range(n + 1)])
        full = np.column_stack([np.interp(s, grid, q_path[:, j]) for j in range(q_path.shape[1])])
        v = np.diff(full, axis=0) / dt
        a = np.diff(np.vstack([np.zeros((1, v.shape[1])), v, np.zeros((1, v.shape[1]))]), axis=0) / dt
        pos = full[1:]
        vel = np.vstack([(v[1:] + v[:-1]) / 2.0, np.zeros((1, v.shape[1]))])
        over = max(float(np.max(np.abs(v) / vmax)), math.sqrt(float(np.max(np.abs(a) / amax))))
        if over <= 1.0 + 1e-9:
            break
        duration = total * over * 1.02
    pos[-1] = q_path[-1]
    return pos, vel
