"""Inverse kinematics of the arm's pinch point by damped least squares, on a robot-only model (never the live data).

After Embodied Safety Exam's `sim/ik.py`. A 7-joint arm reaches most hand poses in a continuum of postures and, for
large moves, on other branches (elbow or wrist flipped). A solution that lies far from the posture it was seeded from
asks the arm to swing through itself; the servos would then drive it at full torque. So every solution is checked
against its seed and refused with a reason instead of being executed:

  not_converged  the pose is out of reach (or the solver stalled): position or orientation error above tolerance
  joint_limit    the solution needs a joint closer than the margin to (or beyond) its limit
  branch_flip    the solution is more than `max_jump` rad from the seed on some joint

A refused solve returns the seed unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np


@dataclass
class IKResult:
    q: np.ndarray  # joint positions (the seed when not ok)
    ok: bool
    reason: str  # "ok" | "not_converged" | "joint_limit" | "branch_flip"
    pos_err: float  # m
    rot_err: float  # rad
    iters: int
    jump: float  # largest joint displacement from the seed, rad

    def __bool__(self) -> bool:
        return self.ok

    def report(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "position_error_m": round(self.pos_err, 5),
            "angle_error_rad": round(self.rot_err, 5),
            "largest_joint_jump_rad": round(self.jump, 4),
        }


def rotvec(q_from, q_to) -> np.ndarray:
    """World-frame rotation vector that turns orientation `q_from` into `q_to` (quaternions w, x, y, z)."""
    # mju_subQuat gives the rotation in the frame of q_from: q_to = q_from * exp(v); rotate it into the world
    v = np.zeros(3)
    mujoco.mju_subQuat(v, np.asarray(q_to, dtype=np.float64), np.asarray(q_from, dtype=np.float64))
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(q_from, dtype=np.float64))
    return R.reshape(3, 3) @ v


def mat_quat(R) -> np.ndarray:
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.asarray(R, dtype=np.float64).reshape(9))
    return q


class IK:
    def __init__(self, model: mujoco.MjModel, arm_joints: list[str], site: str, margin: float, nullspace: float = 0.05):
        self.model = model
        self.data = mujoco.MjData(model)
        self.site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, site)
        if self.site < 0:
            raise ValueError(f"no site {site!r} in the robot model")
        jids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j) for j in arm_joints]
        self.qadr = np.array([model.jnt_qposadr[j] for j in jids])
        self.dadr = np.array([model.jnt_dofadr[j] for j in jids])
        rng = np.array([model.jnt_range[j] for j in jids])
        self.range = rng
        self.lo = rng[:, 0] + margin
        self.hi = rng[:, 1] - margin
        self.nullspace = float(nullspace)
        self._jp = np.zeros((3, model.nv))
        self._jr = np.zeros((3, model.nv))

    def fk(self, q) -> tuple[np.ndarray, np.ndarray]:
        """Pinch point position and orientation (w, x, y, z) for arm joints `q`."""
        d = self.data
        d.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.model, d)
        return d.site_xpos[self.site].copy(), mat_quat(d.site_xmat[self.site])

    def _jacobian(self, q) -> np.ndarray:
        d = self.data
        d.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.model, d)
        mujoco.mj_comPos(self.model, d)
        mujoco.mj_jacSite(self.model, d, self._jp, self._jr, self.site)
        return np.vstack([self._jp[:, self.dadr], self._jr[:, self.dadr]])

    def solve(
        self,
        pos,
        quat,
        q_seed,
        *,
        max_jump: float = 0.35,
        pos_tol: float = 1e-4,
        rot_tol: float = 1e-3,
        damping: float = 1e-3,
        max_iters: int = 100,
        max_step: float = 0.2,
    ) -> IKResult:
        """Joint positions near `q_seed` that put the pinch point at (`pos`, `quat` w, x, y, z).

        Levenberg-Marquardt-style damping that grows with the error: short safe steps far from the goal or near a
        singularity, Newton steps close to it. A redundant arm's free motion is pulled back towards the seed.
        """
        pos = np.asarray(pos, dtype=np.float64)
        quat = np.asarray(quat, dtype=np.float64)
        quat = quat / np.linalg.norm(quat)
        seed = np.asarray(q_seed, dtype=np.float64).copy()
        q = seed.copy()
        d = self.data
        pe = re = float("inf")
        it = 0
        eye = np.eye(6)
        for it in range(1, max_iters + 1):  # noqa: B007 - `it` is reported after the loop
            jac = self._jacobian(q)
            ep = pos - d.site_xpos[self.site]
            er = rotvec(mat_quat(d.site_xmat[self.site]), quat)
            pe, re = float(np.linalg.norm(ep)), float(np.linalg.norm(er))
            if pe < pos_tol and re < rot_tol:
                break
            err = np.concatenate([ep, er])
            lam2 = damping * damping + 0.05 * float(err @ err)
            inv = np.linalg.solve(jac @ jac.T + lam2 * eye, np.eye(6))
            dq = jac.T @ (inv @ err)
            if self.nullspace > 0.0:
                pull = self.nullspace * (seed - q)
                dq = dq + pull - jac.T @ (inv @ (jac @ pull))
            big = float(np.max(np.abs(dq)))
            if big > max_step:
                dq *= max_step / big
            q = q + dq
        else:
            p, r = self.fk(q)
            pe, re = float(np.linalg.norm(pos - p)), float(np.linalg.norm(rotvec(r, quat)))
        jump = float(np.max(np.abs(q - seed)))
        if not (pe < pos_tol and re < rot_tol):
            return IKResult(seed, False, "not_converged", pe, re, it, jump)
        if np.any(q < self.lo) or np.any(q > self.hi):
            return IKResult(seed, False, "joint_limit", pe, re, it, jump)
        if jump > max_jump:
            return IKResult(seed, False, "branch_flip", pe, re, it, jump)
        return IKResult(q, True, "ok", pe, re, it, jump)

    def solve_path(self, poses, q_seed, *, max_jump: float = 0.35) -> tuple[np.ndarray, IKResult]:
        """Solve nearby poses in order, each seeded by the solution before it. Returns the rows solved (start
        included) and the last result; a path stops at its first refused pose."""
        q = np.asarray(q_seed, dtype=np.float64).copy()
        out = [q.copy()]
        res = IKResult(q, True, "ok", 0.0, 0.0, 0, 0.0)
        for p, r in poses:
            res = self.solve(p, r, q, max_jump=max_jump)
            if not res.ok:
                break
            q = res.q
            out.append(q.copy())
        return np.array(out), res


def slerp(q0, q1, t: float) -> np.ndarray:
    q0, q1 = np.asarray(q0, dtype=np.float64), np.asarray(q1, dtype=np.float64)
    dot = float(q0 @ q1)
    if dot < 0.0:
        q1, dot = -q1, -dot
    if dot > 0.9995:
        q = q0 + t * (q1 - q0)
        return q / np.linalg.norm(q)
    th = np.arccos(dot)
    return (np.sin((1 - t) * th) * q0 + np.sin(t * th) * q1) / np.sin(th)


def straight_poses(
    p0, q0, p1, q1, step_m: float = 0.005, step_rad: float = 0.05
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Poses from just after (p0, q0) to (p1, q1): a straight line for the position, slerp for the orientation."""
    p0, p1 = np.asarray(p0, dtype=np.float64), np.asarray(p1, dtype=np.float64)
    ang = float(np.linalg.norm(rotvec(q0, q1)))
    n = max(int(np.ceil(float(np.linalg.norm(p1 - p0)) / step_m)), int(np.ceil(ang / step_rad)), 1)
    return [(p0 + (p1 - p0) * (k / n), slerp(q0, q1, k / n)) for k in range(1, n + 1)]
