"""Scripted reference solution for LIBERO tasks that no LIBERO demonstration fits (the libero-pro suite).

LIBERO-PRO moves LIBERO's objects to new places (its `_swap` suites) and gives LIBERO's scenes new goals (its `_task`
suites), so LIBERO's recorded demonstrations, which the `libero` suite replays, no longer reach the goal. This solution
drives the arm through the robo socket, as an agent does, with LIBERO's own 7-D delta end-effector action, and reads the
scene through the reference solution's privileged view (`LiberoBackend.privileged_state`: the goal predicates and the
pose and bounding box of every object, fixture, region and joint). It is closed loop: it reads the scene again before
every motion.

The plan comes from the goal predicates, in an order that works (an `In` before the `Close` of the same drawer or door):

- `On` and `In`: pick the object (top-down; across the narrow side of a box, can or bottle, on the rim of a bowl, plate
  or mug) and lower it onto or into the target until LIBERO's check passes, opening a closed drawer first when the target
  is inside it. A pick that does not lift the object is tried again from the other side.
- `Open` and `Close` of a drawer: grasp the handle with the hand turned towards the cabinet and pull it out, or push the
  front in with the closed hand.
- `Close` of the microwave: sweep the hand against the open door, from its free edge towards the hinge.
- `Turnon` and `Turnoff` of the stove: lower the closed fingers beside the knob's fin and sweep round the knob's axis.

A task's oracle/plan.json may set options for a step (`grasp`, `yaw`, `approach`, `offset`, ...) where the default does
not work; the generator writes it, and records why.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

STEP = 0.05  # metres that 1.0 on dx/dy/dz asks for
ROT = 0.5  # radians that 1.0 on droll/dpitch/dyaw asks for
OPEN, CLOSE = -1.0, 1.0
FINGERS = 0.075  # widest object the open fingers take across (the gap is about 8 cm)
R_DOWN = np.diag([1.0, -1.0, -1.0])  # the hand pointing down, fingers closing along world y (the start pose)
# LIBERO objects whose bounding box misleads a top-down grasp (it takes in a handle or a spout): where to grasp them, in
# the object's own frame: the axis the fingers close along, the grasp point's offset from the origin, and its height
# above the origin
GRASPS = {
    "MokaPot": {
        "axis": 0,
        "at": [0.0, 0.0, 0.042],
    },  # across the pot's body, under the lid (the box takes in the handle)
    "Chefmate8Frypan": {"axis": 1, "at": [0.16, 0.0, 0.044]},  # the handle, near the pan
}


class Done(Exception):
    """The episode finished: the goal was reached (first-success protocol) or the step budget ran out."""


# ---- rotations -------------------------------------------------------------------------------------------------------
def quat2mat(q) -> np.ndarray:
    """(x, y, z, w) quaternion -> rotation matrix."""
    x, y, z, w = np.asarray(q, dtype=float) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def mat2axisangle(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> axis * angle."""
    c = float(np.clip((np.trace(R) - 1) / 2, -1.0, 1.0))
    angle = float(np.arccos(c))
    if angle < 1e-6:
        return np.zeros(3)
    if np.pi - angle < 1e-4:  # half turn: the axis is the eigenvector for eigenvalue 1
        w, v = np.linalg.eigh((R + np.eye(3)) / 2)
        return v[:, int(np.argmax(w))] * angle
    axis = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * np.sin(angle))
    return axis * angle


def rot_z(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def down(yaw: float = 0.0) -> np.ndarray:
    """The hand pointing down, turned by `yaw` about the vertical: the fingers close along (sin yaw, -cos yaw, 0)."""
    return rot_z(yaw) @ R_DOWN


def yaw_of(R) -> float:
    """The turn about the vertical of a hand orientation, relative to the start pose (meaningful while the hand points
    down, or tilted from there)."""
    M = np.asarray(R, dtype=float) @ R_DOWN.T
    return float(np.arctan2(M[1, 0], M[0, 0]))


def yaw_for(u) -> float:
    """The smallest turn of the downward hand that closes the fingers along the table-plane direction `u`."""
    a = float(np.arctan2(u[0], -u[1]))
    return (a + np.pi / 2) % np.pi - np.pi / 2


def facing(direction, closing=(0.0, 0.0, 1.0)) -> np.ndarray:
    """The hand pointing along `direction` (its z axis), the fingers closing along `closing` (its y axis)."""
    z = np.asarray(direction, dtype=float)
    z = z / np.linalg.norm(z)
    y = np.asarray(closing, dtype=float)
    y = y - z * (y @ z)
    y = y / np.linalg.norm(y)
    return np.column_stack([np.cross(y, z), y, z])


# ---- the arm -----------------------------------------------------------------------------------------------------------
class SocketArm:
    """The robo socket, with the reference solution's token (so `observe` returns the privileged view)."""

    def __init__(self) -> None:
        from ...agent_cli import _send

        self._send = _send
        self.steps = 0

    def observe(self) -> dict:
        r = self._send({"op": "observe"})
        if not r.get("ok"):
            raise Done(r.get("error"))
        return r["result"]["state"]

    def act(self, a, repeat: int = 1) -> dict:
        r = self._send({"op": "act", "action": [float(x) for x in a], "repeat": int(repeat)})
        if not r.get("ok"):
            raise Done(r.get("error"))
        res = r["result"]
        self.steps = int(res.get("steps_used", self.steps))
        if "episode" in res:
            raise Done(res["episode"])
        return res["state"]

    def done(self, text: str) -> None:
        self._send({"op": "done", "text": text})


# ---- the solution ------------------------------------------------------------------------------------------------------
class Solver:
    def __init__(self, arm, options: dict | None = None, log=None) -> None:
        self.arm = arm
        self.opts = options or {}
        self.log = log or (lambda *a: None)
        self.grip = OPEN
        self.pub: dict = {}
        self.view: dict = {}
        self.start: np.ndarray | None = None

    # -- reading the scene ------------------------------------------------------------------------------------------
    def look(self) -> dict:
        st = self.arm.observe()
        self.pub, self.view = st, st["privileged"]
        return self.view

    def ent(self, name: str, fresh: bool = True) -> dict:
        return (self.look() if fresh else self.view)["entities"][name]

    def site(self, name: str, fresh: bool = True) -> dict:
        return (self.look() if fresh else self.view)["sites"][name]

    def hand(self) -> np.ndarray:
        return np.asarray(self.pub["hand_pos"], dtype=float)

    def R(self) -> np.ndarray:
        return quat2mat(self.pub["eef_quat"])

    def gap(self) -> float:
        return float(self.pub.get("gripper_open", 0.0))

    def qpos(self, joint: str) -> float:
        self.look()
        return float(self.pub["articulated"][joint]["qpos"])

    # -- motion -------------------------------------------------------------------------------------------------------
    def act(self, v=(0.0, 0.0, 0.0), w=(0.0, 0.0, 0.0), grip: float | None = None, repeat: int = 1) -> dict:
        if grip is not None:
            self.grip = float(grip)
        a = np.concatenate([np.clip(np.asarray(v, dtype=float), -1, 1), np.clip(np.asarray(w, dtype=float), -1, 1)])
        self.pub = self.arm.act([*a.tolist(), self.grip], repeat)
        return self.pub

    def set_gap(self, gap: float, max_n: int = 12) -> None:
        """Open the fingers fully, close them until the gap is about `gap` (metres), and keep them there (LIBERO's
        gripper command moves the fingers' target by a step in the command's direction; 0 leaves it where it is)."""
        self.hold(10, OPEN)
        for _ in range(max_n):
            if self.gap() <= gap:
                break
            self.act(grip=CLOSE)
        self.grip = 0.0

    def nearest(self, R: np.ndarray) -> np.ndarray:
        """`R`, or `R` turned half a turn about its approach axis (the fingers are symmetric), whichever is nearer the
        hand's orientation now and keeps the wrist inside its range."""
        flip = R @ np.diag([-1.0, -1.0, 1.0])
        self.look()
        now = self.R()
        return min(
            (R, flip),
            key=lambda M: (not self.wrist_fits(M, fresh=False), np.linalg.norm(mat2axisangle(M @ now.T))),
        )

    def wrist_fits(self, R: np.ndarray, margin: float = 0.15, fresh: bool = True) -> bool:
        """Whether turning the hand to `R` keeps the arm's last joint (it turns the hand about its axis) inside its
        range, or at least moves it away from its limit. robosuite's controller turns the hand the short way round
        and, past the limit, stalls the whole arm."""
        rob = (self.look() if fresh else self.view).get("robot") or {}
        if "qpos" not in rob or "range" not in rob:
            return True
        q = float(rob["qpos"][6])
        lo, hi = (float(x) for x in rob["range"][6])
        d = (yaw_of(R) - yaw_of(self.R()) + np.pi) % (2 * np.pi) - np.pi
        qn = q - d  # the joint turns the hand about its own axis, which points down
        return lo + margin <= qn <= hi - margin or abs(qn - (lo + hi) / 2) <= abs(q - (lo + hi) / 2)

    def hold(self, n: int, grip: float | None = None) -> None:
        while n > 0:
            self.act(grip=grip, repeat=min(n, 50))
            n -= 50

    def move(
        self,
        pos,
        R: np.ndarray | None = None,
        tol: float = 0.006,
        rtol: float = 0.05,
        max_n: int = 150,
        speed: float = 1.0,
        grip: float | None = None,
        stall_n: int = 8,
    ) -> bool:
        """Servo the hand to `pos` (and the orientation `R`) with LIBERO's delta commands. True when it got there, False
        when the hand stopped short (something is in the way) or the steps ran out."""
        pos = np.asarray(pos, dtype=float)
        if grip is not None:
            self.grip = float(grip)
        hist: list[np.ndarray] = []
        for _ in range(max_n):
            e = pos - self.hand()
            we = mat2axisangle(R @ self.R().T) if R is not None else np.zeros(3)
            if np.linalg.norm(e) < tol and np.linalg.norm(we) < rtol:
                return True
            v = e / STEP * 2.0
            n = np.linalg.norm(v)
            if n > speed:
                v *= speed / n
            w = we / ROT * 1.5
            m = np.abs(w).max()
            if m > 1.0:
                w /= m
            self.act(v, w)
            hist.append(self.hand())
            if (
                len(hist) > stall_n
                and np.linalg.norm(hist[-1] - hist[-1 - stall_n]) < 0.002
                and np.linalg.norm(we) < rtol
            ):
                self.log(
                    f"  move stopped {np.linalg.norm(pos - self.hand()):.3f} m short of {np.round(pos, 3).tolist()}"
                )
                return False
        self.log(
            f"  move ran out: {np.linalg.norm(pos - self.hand()):.3f} m and {np.linalg.norm(we):.2f} rad short of "
            f"{np.round(pos, 3).tolist()}"
        )
        return False

    def lift_to(self, z: float, R: np.ndarray | None = None, **kw) -> bool:
        h = self.hand()
        return self.move([h[0], h[1], z], R, **kw)

    # -- geometry -------------------------------------------------------------------------------------------------------
    @staticmethod
    def axes(e: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(world rotation of the body, half extents of its box in the body frame, box centre in the world)."""
        Rb = quat2mat(e["quat"])
        lo, hi = np.asarray(e["local_box_min"]), np.asarray(e["local_box_max"])
        centre = np.asarray(e["pos"]) + Rb @ ((lo + hi) / 2)
        return Rb, (hi - lo) / 2, centre

    def top_of(self, e: dict) -> float:
        return float(e["box_max"][2])

    def path_top(self, a, b, radius: float, skip: set[str]) -> float:
        """Highest point of anything (object or fixture, except `skip`) within `radius` of the table-plane segment a-b."""
        a, b = np.asarray(a, dtype=float)[:2], np.asarray(b, dtype=float)[:2]
        pts = [a + (b - a) * t for t in np.linspace(0.0, 1.0, max(2, int(np.linalg.norm(b - a) / 0.01) + 1))]
        top = 0.0
        for k, x in self.view["entities"].items():
            if k in skip:
                continue
            lo, hi = np.asarray(x["box_min"])[:2], np.asarray(x["box_max"])[:2]
            if min(np.linalg.norm(p - np.clip(p, lo, hi)) for p in pts) < radius:
                top = max(top, self.top_of(x))
        return top

    # -- picking ------------------------------------------------------------------------------------------------------
    def hand_yaw(self) -> float:
        """The hand's turn about the vertical, relative to the start pose (meaningful while it points down)."""
        return yaw_of(self.R())

    def nearest_yaw(self, yaw: float) -> float:
        """`yaw` or `yaw` +- pi (the fingers are symmetric), whichever turns the wrist least from where it is without
        taking it out of its range."""
        self.look()
        now = self.hand_yaw()
        return min(
            (yaw + k * np.pi for k in (-2, -1, 0, 1, 2)),
            key=lambda a: (not self.wrist_fits(down(a), fresh=False), abs(a - now)),
        )

    def hand_hits(self, g, yaw: float, skip: set[str]) -> float:
        """How far (metres) the downward hand at `g`, turned by `yaw`, overlaps anything else: the open fingers (1 cm
        below the grasp point to 4.5 cm above it) and the hand above them (about 21 x 7 cm, along the closing axis)."""
        u = np.array([np.sin(yaw), -np.cos(yaw)])  # closing axis in the table plane
        w = np.array([-u[1], u[0]])
        g = np.asarray(g, dtype=float)
        parts = [  # (centre, half length along u, half width along w, lowest z)
            (g[:2] + u * 0.044, 0.008, 0.012, g[2] - 0.011),
            (g[:2] - u * 0.044, 0.008, 0.012, g[2] - 0.011),
            (g[:2], 0.105, 0.035, g[2] + 0.045),
        ]
        worst = 0.0
        for k, x in self.view["entities"].items():
            if k in skip:
                continue
            lo, hi = np.asarray(x["box_min"]), np.asarray(x["box_max"])
            for c, hu, hw, z in parts:
                if hi[2] <= z:
                    continue
                # overlap of the oriented part rectangle with the box, measured along u and w (conservative)
                corners = np.array([[a, b] for a in (lo[0], hi[0]) for b in (lo[1], hi[1])]) - c
                du, dw = corners @ u, corners @ w
                ou = min(hu, du.max()) - max(-hu, du.min())
                ow = min(hw, dw.max()) - max(-hw, dw.min())
                if ou > 0 and ow > 0:
                    worst = max(worst, min(ou, ow))
        return worst

    def grasps(self, name: str, e: dict) -> list[tuple[np.ndarray, float, str]]:
        """Top-down grasps of `e`, best first: across the narrow side of an object the open fingers take (or across the
        other side if it fits too), else on the rim, one finger inside and one outside the wall, around the object.
        Grasps where the hand would hit something come last; among the rest, the robot's side and the least wrist turn
        come first."""
        o = self.opts.get(name, {})
        Rb, half, c = self.axes(e)
        lo, hi = np.asarray(e["box_min"]), np.asarray(e["box_max"])
        height = hi[2] - lo[2]
        ex, ey = Rb[:, 0].copy(), Rb[:, 1].copy()  # horizontal axes of the body (objects stand upright)
        ex[2] = ey[2] = 0.0
        ex /= np.linalg.norm(ex) or 1.0
        ey /= np.linalg.norm(ey) or 1.0
        wx, wy = 2 * half[0], 2 * half[1]
        kind = o.get("grasp") or ("centre" if min(wx, wy) <= FINGERS - 0.01 else "rim")
        floor = lo[2] + 0.014  # the fingertips stay off whatever the object stands on
        cands = []
        known = GRASPS.get(e.get("category", ""))
        if known and "grasp" not in o:
            g = np.asarray(e["pos"], dtype=float) + Rb @ np.asarray(known["at"], dtype=float)
            u = Rb[:, known["axis"]].copy()
            u[2] = 0.0
            cands.append((g, yaw_for(u / (np.linalg.norm(u) or 1.0)), e["category"], 0.0))
        elif kind == "centre":
            z = max(hi[2] - min(float(o.get("depth", 0.03)), 0.5 * height), floor)
            for u, width in sorted(((ex, wx), (ey, wy)), key=lambda t: t[1]):
                if width <= FINGERS - 0.01:
                    cands.append((np.array([c[0], c[1], z]), yaw_for(u), "centre", 0.0))
        else:
            r = 0.5 * min(wx, wy)
            z = max(hi[2] - float(o.get("rim_depth", 0.02)), floor)
            for a in o.get("rim_angles", range(180, 540, 30)):
                d = np.array([np.cos(np.radians(a)), np.sin(np.radians(a)), 0.0])
                g = np.array([c[0], c[1], 0.0]) + d * (r - float(o.get("wall", 0.012)))
                g[2] = z
                cands.append((g, yaw_for(d), "rim", abs(((a - 180) + 180) % 360 - 180) / 180.0))
        out = []
        for g, yaw, kind_, side in cands:
            g = g + np.asarray(o.get("offset", [0, 0, 0]), dtype=float)
            yaw = self.nearest_yaw(float(o.get("yaw", yaw)))
            hit = self.hand_hits(g, yaw, {name})
            out.append((hit > 0.002, hit, side + 0.3 * abs(yaw - self.hand_yaw()), g, yaw, kind_))
        out.sort(key=lambda t: (t[0], t[1] if t[0] else 0.0, t[2]))
        return [(g, yaw, k) for _, _, _, g, yaw, k in out]

    def grasp_rotation(self, g, yaw: float, name: str) -> np.ndarray:
        """The hand's orientation for a grasp at `g`: pointing down, or, close to the robot's base, where the arm cannot
        fold far enough to point straight down, tilted away from the base about the closing axis (`tilt` option)."""
        R = down(yaw)
        base = (self.view.get("robot") or {}).get("base")
        tilt = float(self.opts.get(name, {}).get("tilt", 0.0))
        if base is not None and "tilt" not in self.opts.get(name, {}):
            d = float(np.linalg.norm(np.asarray(g[:2]) - np.asarray(base[:2])))
            tilt = 35.0 if d < float(self.opts.get("near_base", 0.30)) else 0.0
        if tilt <= 0.0:
            return R
        c = R[:, 1]
        t = np.cross(c, [0.0, 0.0, 1.0])
        if base is not None and t[:2] @ (np.asarray(g[:2]) - np.asarray(base[:2])) < 0:
            t = -t
        a = t * np.sin(np.radians(tilt)) - np.array([0.0, 0.0, np.cos(np.radians(tilt))])
        return facing(a, c)

    def pick(self, name: str, tries: int = 3) -> bool:
        for k in range(tries):
            v = self.look()
            e = v["entities"][name]
            p0 = np.asarray(e["pos"], dtype=float)
            cands = self.grasps(name, e)
            g, yaw, kind = cands[k % len(cands)]
            Rg = self.grasp_rotation(g, yaw, name)
            a = Rg[:, 2]  # the approach direction (straight down unless tilted)
            self.log(
                f"pick {name} try {k} {kind} at {np.round(g, 3).tolist()} yaw {yaw:.2f} approach {np.round(a, 2).tolist()}"
            )
            h = self.hand()
            above = max(g[2] + 0.10, self.path_top(h, g, 0.07, {name}) + 0.08, self.top_of(e) + 0.05)
            pre = np.array([g[0], g[1], above]) - a * 0.04 * (
                a[2] > -0.99
            )  # above the grasp (a tilted hand: a little back)
            self.hold(3, OPEN)
            self.lift_to(max(h[2], above), max_n=60)
            self.move(pre, Rg, tol=0.01, max_n=120)
            self.move(g - a * 0.04, Rg, tol=0.006, max_n=60, speed=0.8)
            self.move(g, Rg, tol=0.005, max_n=50, speed=0.5)
            self.hold(12, CLOSE)
            self.lift_to(g[2] + 0.12, Rg, max_n=50, speed=0.8)
            e = self.ent(name)
            if float(e["pos"][2]) > p0[2] + 0.05 and self.gap() > 0.003:
                return True
            self.log(f"  not held (object z {e['pos'][2]:.3f}, gap {self.gap():.3f})")
            self.hold(8, OPEN)
            self.lift_to(self.hand()[2] + 0.05, max_n=30)
        return False

    # -- placing ------------------------------------------------------------------------------------------------------
    def region_box(self, site: dict) -> tuple[np.ndarray, np.ndarray]:
        """World-frame box of a region site as LIBERO's `In` check measures it (half sizes rotated by the site's frame)."""
        c = np.asarray(site["pos"], dtype=float)
        half = np.abs(np.asarray(site["xmat"], dtype=float).reshape(3, 3) @ np.asarray(site["size"], dtype=float))
        return c - half, c + half

    def place(self, name: str, target: str, how: str) -> None:
        """Carry the held object over the target, clear of everything on the way, and lower it onto (`on`) or into
        (`in`) the target until it touches down (LIBERO's check usually passes on contact), then let go."""
        v = self.look()
        o = self.opts.get(f"{name}->{target}", {})
        if target in v["entities"]:  # On another object: origins within 3 cm, touching
            goal = np.asarray(v["entities"][target]["pos"], dtype=float)
            low = goal[2] + 0.005  # the origin may not go below the target's
            spots = [goal[:2]]
        else:
            s = v["sites"][target]
            goal = np.asarray(s["pos"], dtype=float)
            size = np.asarray(s["size"], dtype=float)
            # On a region (LIBERO's `under`): the origin over its footprint and up to 10 cm above it, touching its
            # fixture; In a region: the origin inside its box
            low = goal[2] + size[2] - 0.003 if how == "on" else goal[2] - 0.5 * size[2]
            if how == "in":
                lo, hi = self.region_box(s)
            else:
                half = np.abs(np.asarray(s["xmat"], dtype=float).reshape(3, 3)[:2, :2] @ size[:2])
                lo, hi = goal - np.r_[half, 0], goal + np.r_[half, 0]
            m = np.minimum(float(o.get("margin", 0.015)), (hi[:2] - lo[:2]) / 2 - 0.002)
            xs = np.linspace(lo[0] + m[0], hi[0] - m[0], 5)
            ys = np.linspace(lo[1] + m[1], hi[1] - m[1], 5)
            base = np.asarray((v.get("robot") or {}).get("base", goal), dtype=float)[:2]

            def rank(p) -> float:  # near the region's centre, but not where the arm would be stretched out
                p = np.asarray(p, dtype=float)
                return float(np.linalg.norm(p - goal[:2]) + 2.0 * max(0.0, np.linalg.norm(p - base) - 0.70))

            spots = sorted(([x, y] for x in xs for y in ys), key=rank)
        if "offset" in o:
            spots = [np.asarray(goal[:2]) + np.asarray(o["offset"][:2], dtype=float)]
        site = v["sites"].get(target, {})
        skip = {target, site.get("parent") or target, *site.get("joints", [])}
        self.log(f"place {name} {how} {target}: origin to about {np.round(goal, 3).tolist()}")
        self.put(name, spots, low, skip=skip, max_carry=float(o.get("max_carry", 1.40)))

    def put_blocked(self, name: str, xy, yaw: float, low: float, off_r: np.ndarray, skip: set[str]) -> float:
        """How far the held object, put down with its origin at `xy` and the hand turned to `yaw`, or the hand above it,
        would overlap anything: objects, fixtures and the moving parts of fixtures, except `skip` (the target, the
        fixture or object a target region belongs to, and the drawer a target region moves with)."""
        v = self.view
        e = v["entities"][name]
        lo, hi = np.asarray(e["box_min"]), np.asarray(e["box_max"])
        o = np.asarray(e["pos"], dtype=float)
        bottom = low + (lo[2] - o[2])
        obj_lo = np.r_[np.asarray(xy) - (o[:2] - lo[:2]), bottom]
        obj_hi = np.r_[np.asarray(xy) + (hi[:2] - o[:2]), bottom + (hi[2] - lo[2])]
        hand = np.r_[np.asarray(xy) - off_r[:2], low - off_r[2]]
        boxes = [(k, x["box_min"], x["box_max"]) for k, x in v["entities"].items()]
        boxes += [(k, p["box_min"], p["box_max"]) for k, p in self.pub.get("articulated", {}).items() if "box_min" in p]
        u = np.array([np.sin(yaw), -np.cos(yaw)])  # the hand's closing axis
        w = np.array([-u[1], u[0]])
        worst = 0.0
        for k, a, b in boxes:
            if k == name or k in skip:
                continue
            a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
            if b[2] > obj_lo[2] + 0.005 and a[2] < obj_hi[2]:  # the object itself
                ov = np.minimum(obj_hi[:2], b[:2]) - np.maximum(obj_lo[:2], a[:2])
                if np.all(ov > 0):
                    worst = max(worst, float(ov.min()))
            if b[2] > hand[2] + 0.045:  # the hand's body above it (the fingers are round the object)
                corners = np.array([[p, q] for p in (a[0], b[0]) for q in (a[1], b[1])]) - hand[:2]
                du, dw = corners @ u, corners @ w
                ou = min(0.105, du.max()) - max(-0.105, du.min())
                ow = min(0.035, dw.max()) - max(-0.035, dw.min())
                if ou > 0 and ow > 0:
                    worst = max(worst, min(ou, ow))
        return worst

    def put(self, name: str, spots, low: float, skip: set[str] = frozenset(), max_carry: float = 1.40) -> None:
        """Carry the held object until its origin is over one of `spots` (the first one where neither it nor the hand
        hits anything, turning the wrist by up to 90 degrees if that helps, or the other way round where the wrist
        cannot turn that far), clear of everything on the way, lower it until it touches down or its origin reaches
        `low`, and let go."""
        v = self.look()
        e = v["entities"][name]
        hand = self.hand()
        off = np.asarray(e["pos"]) - hand  # the object's origin relative to the hand while held
        bottom = float(e["box_min"][2]) - hand[2]
        lo, hi = np.asarray(e["box_min"]), np.asarray(e["box_max"])
        radius = 0.5 * float(np.max(hi[:2] - lo[:2])) + 0.03
        yaw0 = self.hand_yaw()
        turns: list[float] = []
        for t in (0.0, np.pi / 2, -np.pi / 2, np.pi / 4, -np.pi / 4):
            if not self.wrist_fits(down(yaw0 + t), fresh=False):  # the other way round, if the wrist turns that far
                t = t - np.pi if t > 0 else t + np.pi
                if not self.wrist_fits(down(yaw0 + t), fresh=False):
                    continue
            if all(abs(t - u) > 1e-6 for u in turns):
                turns.append(t)
        choice = None
        for turn in turns:
            off_r = rot_z(turn) @ off
            free = [xy for xy in spots if self.put_blocked(name, xy, yaw0 + turn, low, off_r, set(skip)) <= 0.002]
            if free:
                choice = (np.asarray(free[0], dtype=float), turn)
                break
        if choice is None:  # the estimate is cautious (it lowers the object all the way): go as the first spot says
            self.log("  every spot looks blocked; using the first")
            choice = (np.asarray(spots[0], dtype=float), 0.0)
        xy, turn = choice
        self.log(f"  put down at {np.round(xy, 3).tolist()}, wrist turned {np.degrees(turn):.0f} degrees")
        tilted = float(self.R()[:, 2] @ np.array([0.0, 0.0, -1.0])) < np.cos(np.radians(10))
        Rh = down(yaw0 + turn) if abs(turn) > 1e-6 or tilted else self.R()  # carry and put down with the hand upright
        over = xy - (rot_z(turn) @ off)[:2]
        carry = max(self.path_top(hand, over, radius, {name}) + 0.03 - bottom, hand[2], low - off[2] + 0.08)
        carry = min(carry, max_carry)
        self.lift_to(carry, Rh, max_n=60)
        off = np.asarray(self.ent(name)["pos"]) - self.hand()  # after any turn of the wrist
        over = xy - off[:2]
        self.move([over[0], over[1], carry], Rh, tol=0.008, max_n=150)
        for _ in range(3):  # line up the object itself (it may hang a little off where it was)
            err = xy - np.asarray(self.ent(name)["pos"][:2])
            if np.linalg.norm(err) < 0.006:
                break
            h = self.hand()
            self.move([h[0] + err[0], h[1] + err[1], h[2]], Rh, tol=0.004, max_n=40)
        h = self.hand()
        self.move([h[0], h[1], low - off[2]], Rh, tol=0.004, max_n=100, speed=0.4, stall_n=5)
        self.hold(10, OPEN)
        h = self.hand()
        self.move([h[0], h[1], h[2] + 0.08], Rh, max_n=40)

    def free_spot(self, name: str, zone=None) -> np.ndarray | None:
        """A place on the work surface near the robot for object `name`: as far as possible from everything else, out
        of `zone` (see front_zone), and not far from where it is."""
        v = self.look()
        e = v["entities"][name]
        lo, hi = np.asarray(e["box_min"]), np.asarray(e["box_max"])
        r = 0.5 * float(np.max(hi[:2] - lo[:2]))
        here = np.asarray(e["pos"][:2], dtype=float)
        best, best_score = None, -1e9
        for x in np.arange(-0.25, 0.16, 0.025):
            for y in np.arange(-0.28, 0.29, 0.025):
                p = np.array([x, y])
                if zone is not None and self.in_zone(p - r, p + r, zone):
                    continue
                gaps = [
                    np.linalg.norm(p - np.clip(p, np.asarray(q["box_min"][:2]), np.asarray(q["box_max"][:2])))
                    for k, q in v["entities"].items()
                    if k != name
                ]
                clear = (min(gaps) if gaps else 1.0) - r
                if clear < 0.04:
                    continue
                score = min(clear, 0.10) - 0.2 * np.linalg.norm(p - here)
                if score > best_score:
                    best, best_score = p, score
        return best

    def move_aside(self, name: str, zone=None) -> None:
        """Pick an object up and put it down out of the way (and out of `zone`)."""
        spot = self.free_spot(name, zone)
        if spot is None:
            self.log(f"no free spot for {name}")
            return
        self.log(f"move {name} aside to {np.round(spot, 3).tolist()}")
        if self.pick(name):
            self.put(name, [spot], float(self.ent(name)["box_min"][2]) - 0.05)

    # -- drawers ------------------------------------------------------------------------------------------------------
    def drawer(self, region: str) -> tuple[str, dict]:
        """(joint name, its part) of the drawer a cabinet region site moves with."""
        v = self.look()
        joint = v["sites"][region]["joints"][0]
        return joint, {**self.pub["articulated"][joint], **v["joints"][joint]}

    def front_zone(self, part: dict, reach: float = 0.20, half: float = 0.06) -> tuple[np.ndarray, ...]:
        """The table-plane rectangle in front of a drawer's handle that a hand reaching for it and pulling it sweeps
        through: (front centre, out, across, half width, depth)."""
        out = -np.asarray(part["axis"], dtype=float)[:2]
        out /= np.linalg.norm(out)
        across = np.array([-out[1], out[0]])
        lo, hi = np.asarray(part["box_min"]), np.asarray(part["box_max"])
        corners = np.array([[a, b] for a in (lo[0], hi[0]) for b in (lo[1], hi[1])])
        c = (lo[:2] + hi[:2]) / 2
        front = c + out * float((corners - c).dot(out).max())
        return front, out, across, half, reach

    def in_zone(self, box_min, box_max, zone) -> bool:
        front, out, across, half, reach = zone
        corners = np.array([[a, b] for a in (box_min[0], box_max[0]) for b in (box_min[1], box_max[1])]) - front
        do, da = corners @ out, corners @ across
        return do.max() > 0 and do.min() < reach and da.max() > -half and da.min() < half

    def clear_front(self, region: str) -> None:
        """Move aside any object standing in front of the drawer, where the hand must go."""
        joint, part = self.drawer(region)
        zone = self.front_zone(part)
        handle_z = (float(part["box_min"][2]) + float(part["box_max"][2])) / 2
        for name, e in list(self.view["entities"].items()):
            # the fingers reach about 5 cm below the handle
            if e["kind"] == "object" and float(e["box_max"][2]) > handle_z - 0.05:
                if self.in_zone(e["box_min"], e["box_max"], zone):
                    self.move_aside(name, self.front_zone(part, reach=0.30, half=0.12))

    def open_drawer(self, region: str) -> None:
        """Pull a drawer open by its handle (a bar across the drawer's front, standing off it on two posts). A handle
        well above the table is grasped with the hand turned towards the cabinet, the fingers closing on the bar from
        above and below. A low one, where that hand would hit the table, is hooked as LIBERO's human operators did: the
        hand tilted down towards the cabinet, the nearly closed fingers between the posts and behind the bar."""
        if self.opts.get(f"open:{region}", {}).get("clear", True):
            self.clear_front(region)
        joint, part = self.drawer(region)
        out = -np.asarray(part["axis"])  # LIBERO's open range is negative: the drawer comes out along -axis
        lo, hi = np.asarray(part["box_min"]), np.asarray(part["box_max"])
        o = self.opts.get(f"open:{region}", {})
        # the handle is the part of the drawer that sticks out furthest along `out`, at the drawer's middle
        c = (lo + hi) / 2
        front = c + out * (np.abs(out) @ (hi - lo) / 2)
        handle = front - out * float(o.get("depth", 0.006)) + np.asarray(o.get("offset", [0, 0, 0.0]), dtype=float)
        floor = float(self.view["entities"][self.view["sites"][region]["parent"]]["box_min"][2])
        style = o.get("style", "front")
        low = handle[2] - floor < 0.10  # a hand level with a low handle would hit the table: tilt it down
        self.log(f"open {region} ({style}): handle {np.round(handle, 3).tolist()} qpos {part['qpos']}")
        self.hold(3, OPEN)
        self.lift_to(max(self.hand()[2], hi[2] + 0.08), max_n=60)
        if style == "front":
            tilt = np.radians(float(o.get("tilt", 50 if low else 0)))
            approach = -out * np.cos(tilt) - np.array([0.0, 0.0, np.sin(tilt)])
            Rf = self.nearest(facing(approach, (0.0, 0.0, 1.0)))
            self.move(handle - approach * 0.12 + np.array([0, 0, 0.05]), Rf, tol=0.01, rtol=0.08, max_n=150)
            self.move(handle - approach * 0.10, Rf, tol=0.008, max_n=80)
            self.move(handle, Rf, tol=0.005, max_n=60, speed=0.5)
            self.hold(12, CLOSE)
        else:  # "hook"
            tilt = np.radians(float(o.get("tilt", 55)))
            approach = -out * np.cos(tilt) - np.array([0.0, 0.0, np.sin(tilt)])
            Rf = self.nearest(
                facing(approach, np.cross([0.0, 0.0, 1.0], out))
            )  # the fingers side by side along the bar
            self.set_gap(float(o.get("gap", 0.012)))
            gap = front - out * float(o.get("behind", 0.0255)) + np.array([0, 0, float(o.get("dz", 0.0))])
            self.move(gap - approach * 0.12, Rf, tol=0.01, rtol=0.08, max_n=150)
            self.move(gap - approach * 0.05, Rf, tol=0.006, max_n=60, speed=0.6)
            self.move(gap, Rf, tol=0.005, max_n=40, speed=0.4)
        target = float(np.mean(part["open_ranges"]))
        for _ in range(4):
            if part["qpos"] <= part["open_ranges"][1]:
                break
            h = self.hand()
            self.move(h + out * (part["qpos"] - target + 0.02), Rf, tol=0.005, max_n=60, speed=0.6)
            joint, part = self.drawer(region)
        self.hold(6, OPEN)
        h = self.hand()
        self.move(h + out * 0.08 + np.array([0, 0, 0.04]), Rf, max_n=40)

    def close_drawer(self, region: str) -> None:
        if self.opts.get(f"close:{region}", {}).get("clear", True):
            self.clear_front(region)
        joint, part = self.drawer(region)
        out = -np.asarray(part["axis"])
        lo, hi = np.asarray(part["box_min"]), np.asarray(part["box_max"])
        o = self.opts.get(f"close:{region}", {})
        c = (lo + hi) / 2
        front = c + out * (np.abs(out) @ (hi - lo) / 2)
        z = float(o.get("z", c[2]))
        push = front.copy()
        push[2] = z
        Rd = down(self.hand_yaw())  # the closed hand pushes; no need to turn the wrist
        self.log(f"close {region}: front {np.round(front, 3).tolist()} qpos {part['qpos']}")
        self.hold(3, CLOSE)
        self.lift_to(max(self.hand()[2], hi[2] + 0.06), Rd, max_n=60)
        self.move(push + out * 0.06 + np.array([0, 0, hi[2] - z + 0.04]), Rd, tol=0.01, max_n=120)
        self.move(push + out * 0.05, Rd, tol=0.006, max_n=60)
        for _ in range(4):
            depth = float(part["qpos"]) - float(part["close_ranges"][0])  # metres still out (negative qpos)
            if part["close_ranges"][0] <= part["qpos"] <= part["close_ranges"][1]:
                break
            h = self.hand()
            self.move(h - out * (abs(depth) + 0.03), Rd, tol=0.005, max_n=80, speed=0.6)
            joint, part = self.drawer(region)
        h = self.hand()
        self.move(h + out * 0.06, Rd, max_n=30)

    # -- the stove's knob ---------------------------------------------------------------------------------------------
    def turn_knob(self, stove: str, on: bool) -> None:
        """Turn the knob (a hinge about the vertical) on, counter-clockwise from above, or off, as LIBERO's human
        operators did: grasp its fin with the fingers across it and turn the wrist."""
        v = self.look()
        joint = next(j for j in v["joints"] if j.startswith(stove))
        info = v["joints"][joint]
        ax = np.asarray(info["anchor"], dtype=float)
        part = self.pub["articulated"][joint]
        o = self.opts.get(f"knob:{stove}", {})
        # LIBERO's flat stove: the fin runs along the knob body's y axis, through the axis
        fin = np.asarray(info["body_xmat"], dtype=float).reshape(3, 3)[:, 1]
        across = np.array([-fin[1], fin[0], 0.0])
        top = float(part["box_max"][2])
        g = ax + fin * float(o.get("along", 0.0))
        g[2] = top - float(o.get("depth", 0.026))
        Rg = down(yaw_for(across))
        sign = 1.0 if on else -1.0
        self.log(f"knob {stove} {'on' if on else 'off'}: axis {np.round(ax, 3).tolist()} qpos {part['qpos']}")
        self.hold(3, OPEN)
        self.lift_to(max(self.hand()[2], top + 0.08), max_n=60)
        self.move([g[0], g[1], top + 0.06], Rg, tol=0.008, max_n=100)
        self.move(g, Rg, tol=0.005, max_n=50, speed=0.5)
        self.hold(10, CLOSE)
        for _ in range(int(o.get("turns", 8))):
            for _ in range(4):
                e = g - self.hand()
                self.act(e / STEP * 2.0, (0.0, 0.0, sign * float(o.get("rate", 0.6))))
            q = self.qpos(joint)
            if (on and q >= float(o.get("on_qpos", 0.9))) or (not on and q < -0.001):
                break
        self.hold(6, OPEN)
        self.lift_to(top + 0.08, max_n=30)

    # -- the microwave's door -----------------------------------------------------------------------------------------
    def close_door(self, fixture: str) -> None:
        v = self.look()
        joint = next(j for j in v["joints"] if j.startswith(fixture))
        info = v["joints"][joint]
        part = self.pub["articulated"][joint]
        hinge = np.asarray(info["anchor"], dtype=float)
        lo, hi = np.asarray(part["box_min"]), np.asarray(part["box_max"])
        c = (lo + hi) / 2
        o = self.opts.get(f"close:{fixture}", {})
        z = float(o.get("z", c[2]))
        # the free edge: the corner of the door's box furthest from the hinge, in the table plane
        corners = [np.array([x, y]) for x in (lo[0], hi[0]) for y in (lo[1], hi[1])]
        edge = max(corners, key=lambda p: np.linalg.norm(p - hinge[:2]))
        rad = float(np.linalg.norm(edge - hinge[:2]))
        a_edge = float(np.arctan2(edge[1] - hinge[1], edge[0] - hinge[0]))
        sign = -np.sign(part["qpos"]) if part["qpos"] else 1.0  # rotate back towards 0
        self.log(f"close {fixture}: hinge {np.round(hinge, 3).tolist()} edge angle {a_edge:.2f} qpos {part['qpos']}")
        self.hold(3, CLOSE)
        self.lift_to(max(self.hand()[2], hi[2] + 0.06), max_n=60)
        r = rad * float(o.get("radius", 0.8))
        a = a_edge - sign * float(np.radians(o.get("behind", 12)))  # just outside the door, on the side it closes from
        p = hinge[:2] + r * np.array([np.cos(a), np.sin(a)])
        self.move([p[0], p[1], hi[2] + 0.04], down(), tol=0.01, max_n=120)
        self.move([p[0], p[1], z], down(), tol=0.008, max_n=60, speed=0.6)
        for i in range(1, 30):
            q = float(self.arm.observe()["articulated"][joint]["qpos"]) if i % 4 == 0 else None
            if q is not None and part["close_ranges"][0] <= q <= part["close_ranges"][1]:
                break
            b = a + sign * i * np.radians(6)
            p = hinge[:2] + r * np.array([np.cos(b), np.sin(b)])
            self.move([p[0], p[1], z], down(), tol=0.008, max_n=12, speed=0.8)
        self.lift_to(hi[2] + 0.06, max_n=40)

    # -- goals --------------------------------------------------------------------------------------------------------
    def plan(self, goal: list[list[str]]) -> list[list[str]]:
        """The goal predicates in an order that works: a drawer or door is shut after what goes into it."""
        first = [g for g in goal if g[0] not in ("close",)]
        return first + [g for g in goal if g[0] == "close"]

    def home(self) -> None:
        """Back to where the hand started, pointing down, so the arm leaves a stretched pose before the next step
        (robosuite's controller cannot steer the arm away from a joint limit on its own)."""
        if self.start is None:
            return
        h = self.hand()
        self.lift_to(max(h[2], self.start[2]), max_n=40)
        self.move(self.start, down(self.nearest_yaw(0.0)), tol=0.02, rtol=0.1, max_n=80)

    def run(self, steps: list[list[str]] | None = None) -> None:
        v = self.look()
        self.start = self.hand().copy()
        steps = steps or self.plan(v["goal"])
        self.log(f"goal {v['goal']} plan {steps} robot {v.get('robot')}")
        for i, g in enumerate(steps):
            op = g[0].lower()
            if i:
                self.home()
            if op in ("on", "in"):
                target = g[2]
                s = v["sites"].get(target)
                if s and s.get("joints"):  # a drawer region: open the drawer first if it is shut
                    joint, part = self.drawer(target)
                    if part["qpos"] > part.get("open_ranges", [-1, -0.1])[1] + 0.03:
                        self.open_drawer(target)
                if self.pick(g[1]):
                    self.place(g[1], target, op)
            elif op == "open":
                self.open_drawer(g[1])
            elif op == "close":
                if g[1] in v["sites"]:
                    self.close_drawer(g[1])
                else:
                    self.close_door(g[1])
            elif op in ("turnon", "turnoff"):
                self.turn_knob(g[1], op == "turnon")
            v = self.look()
        self.hold(20, OPEN)


def oracle_main(env: str = "") -> None:
    """Reference solution for a libero-pro task: `env` is the task's oracle/plan.json ({"steps": [...]} to override
    the plan derived from the goal, and per-step options)."""
    plan = json.loads(Path(env).read_text()) if env and Path(env).is_file() else {}
    arm = SocketArm()
    try:
        Solver(arm, plan.get("options")).run(plan.get("steps"))
    except Done:
        return
    arm.done("scripted reference solution finished")
