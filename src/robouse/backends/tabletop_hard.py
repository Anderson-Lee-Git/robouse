"""Hard tier of tabletop tasks (suite "hard"): scenarios and reference solutions.

The scenes run on the ordinary tabletop backend (backend = "tabletop" in task.toml); this module only holds the
scenario definitions (HARD_SCENARIOS, written into each task.toml by adapters/hard/generate.py) and the reference
solutions (`oracle_main`, called as `python -m robouse.oracle --backend tabletop_hard --env <id>`).

Every reference solution drives the robot only through the robo socket. On `skills = false` tasks it uses only
`act`, with the task's `max_repeat` limit, through a small proportional controller (ActBot). On vision tasks it
reads object positions from `observe`, which returns full state only to the reference solution (oracle token).
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

from .tabletop import DR_HANDLE, DR_TRAVEL, HAND_HI, HAND_LO, _box, _cyl, _meta

HARD_SCENARIOS: dict[str, dict] = {}


# --------------------------------------------------------------------------------------------------
# Low-level controller (act only)
# --------------------------------------------------------------------------------------------------

class Finished(Exception):
    pass


class ActBot:
    """Moves the hand with `act` only (no move_to / grip skills), honouring a max repeat per call."""

    def __init__(self, send: Callable[[dict], dict] | None = None, max_repeat: int = 50):
        if send is None:
            from robouse.agent_cli import _send as send
        self._send = send
        self.R = max_repeat
        self.hand = None
        self.g = -1.0
        self.steps = 0

    def req(self, r: dict) -> dict:
        resp = self._send(r)
        if not resp.get("ok"):
            if "finished" in str(resp.get("error", "")):
                raise Finished()
            raise RuntimeError(f"{r.get('op')}: {resp.get('error')}")
        res = resp.get("result") or {}
        if isinstance(res, dict) and "episode" in res:
            raise Finished()
        return res

    def obs(self) -> dict:
        res = self.req({"op": "observe"})
        st = res["state"]
        self.hand = np.array(st["hand_pos"], float)
        self.steps = res.get("steps_used", self.steps)
        return st

    def act(self, a, n: int = 1) -> dict:
        n = int(max(1, min(self.R, n)))
        res = self.req({"op": "act", "action": [float(x) for x in a], "repeat": n})
        st = res.get("state", {})
        if "hand_pos" in st:
            self.hand = np.array(st["hand_pos"], float)
        self.steps = res.get("steps_used", self.steps)
        return st

    def grip(self, g: float, n: int = 12) -> None:
        self.g = float(g)
        left = n
        while left > 0:
            k = min(self.R, left)
            self.act([0, 0, 0, self.g], k)
            left -= k

    def goto(self, p, g: float | None = None, tol: float = 0.003, max_calls: int = 200, speed: float = 1.0) -> bool:
        """Proportional approach: each call moves the target by at most `speed` cm per step, for up to R steps."""
        if g is not None:
            self.g = float(g)
        p = np.clip(np.asarray(p, float), HAND_LO, HAND_HI)
        if self.hand is None:
            self.obs()
        for _ in range(max_calls):
            d = p - self.hand
            dist = float(np.max(np.abs(d)))
            if dist < tol:
                return True
            # far: full speed for several steps; near: short corrective steps
            n = max(1, min(self.R, int(dist / (0.01 * speed)) - 1)) if dist > 0.02 else 1
            a = np.clip(d / (0.01 * max(n, 1)), -speed, speed) if dist > 0.02 else np.clip(d * 60, -1, 1)
            self.act(list(a) + [self.g], n)
        return False


# --------------------------------------------------------------------------------------------------
# Reference behaviours built on ActBot
# --------------------------------------------------------------------------------------------------

CARRY = 0.15


def _objs(st):
    return st["objects"]


def pick(bot: ActBot, name: str, opt: dict | None = None) -> dict:
    opt = opt or {}
    st = bot.obs()
    o = _objs(st)[name]
    p = np.array(o["pos"], float)
    g_open = opt.get("open", -0.3)
    carry = opt.get("carry_z", CARRY)
    gz = max(p[2] + opt.get("grasp_dz", 0.0), 0.012)
    bot.goto([p[0], p[1], max(carry, bot.hand[2] if bot.hand is not None else carry)], g_open, tol=0.01)
    bot.goto([p[0], p[1], carry], g_open, tol=0.006)
    st = bot.obs()  # re-read in case it moved
    p = np.array(_objs(st)[name]["pos"], float)
    bot.goto([p[0], p[1], gz + 0.03], g_open, tol=0.004)
    bot.goto([p[0], p[1], gz], g_open, tol=0.003)
    bot.grip(1.0, opt.get("close_steps", 12))
    bot.goto([p[0], p[1], carry], 1.0, tol=0.006)
    return bot.obs()


def place(bot: ActBot, name: str, xy, surf_z: float, opt: dict | None = None) -> None:
    opt = opt or {}
    carry = opt.get("carry_z", CARRY)
    st = bot.obs()
    o = _objs(st)[name]
    off = np.array(o["pos"]) - bot.hand
    want_z = surf_z + o["half_height"] + opt.get("drop", 0.004)
    hx, hy = np.asarray(xy, float) - off[:2]
    hz = want_z - off[2]
    for wp in opt.get("via", []):
        bot.goto([wp[0], wp[1], carry], 1.0, tol=0.01)
    bot.goto([hx, hy, carry], 1.0, tol=0.004)
    if opt.get("slow"):
        lim = opt.get("slow_speed", 0.15)  # cm per step
        for _ in range(400):
            st = bot.obs()
            oz = _objs(st)[name]["pos"][2]
            gap = oz - (surf_z + o["half_height"])
            if gap < 0.0015:
                break
            bot.act([0, 0, -max(0.03, min(lim, gap * 20)), 1.0], 1 if gap < 0.01 else min(bot.R, 3))
    else:
        bot.goto([hx, hy, hz + 0.03], 1.0, tol=0.004)
        # fine alignment right above the target using the object's own position
        for _ in range(3):
            st = bot.obs()
            op = np.array(_objs(st)[name]["pos"])
            err = np.asarray(xy, float) - op[:2]
            if np.max(np.abs(err)) < opt.get("xy_tol", 0.002):
                break
            bot.goto([bot.hand[0] + err[0], bot.hand[1] + err[1], bot.hand[2]], 1.0, tol=0.0015)
        bot.goto([bot.hand[0], bot.hand[1], hz], 1.0, tol=0.003, speed=opt.get("down_speed", 1.0))
    bot.grip(opt.get("release", -0.3), 10)
    bot.goto([bot.hand[0], bot.hand[1], carry], opt.get("release", -0.3), tol=0.01)


def target_of(st: dict, tgt: dict):
    fx = st.get("fixtures", {})
    off = np.array(tgt.get("offset", [0.0, 0.0]), float)
    if "pad" in tgt:
        return np.array(fx[tgt["pad"]]["pos"][:2]) + off, fx[tgt["pad"]]["pos"][2]
    if "fixture" in tgt:
        f = fx[tgt["fixture"]]
        if f["kind"] == "plate":
            return np.array(f["pos"][:2]) + off, f["top_z"]
        if f["kind"] == "drawer":
            return np.array(f["interior_center"][:2]) + off, f["interior_center"][2]
        if f["kind"] == "socket":
            return np.array(f["pos"][:2]) + off, 0.0
        return np.array(f["pos"][:2]) + off, f["floor_z"]
    if "on" in tgt:
        b = st["objects"][tgt["on"]]
        return np.array(b["pos"][:2]) + off, b["pos"][2] + b["half_height"]
    if "cell" in tgt:
        r, c = tgt["cell"]
        return np.array(st["grid"]["cell_centers"][r][c][:2]), 0.0
    if "xy" in tgt:
        return np.array(tgt["xy"], float), tgt.get("z", 0.0)
    raise ValueError(tgt)


def pick_place(bot: ActBot, name: str, tgt: dict, opt: dict | None = None) -> None:
    opt = opt or {}
    pick(bot, name, opt)
    st = bot.obs()
    xy, surf = target_of(st, tgt)
    place(bot, name, xy, surf, opt)


def open_drawer(bot: ActBot, name: str, amount: float = DR_TRAVEL) -> None:
    f = bot.obs()["fixtures"][name]
    hx, hy, hz = f["handle_pos"]
    closed_y = hy + f["opening"]
    bot.goto([hx, hy, 0.13], 0.2, tol=0.006)
    bot.goto([hx, hy, hz], 0.2, tol=0.003)
    bot.grip(1.0, 12)
    bot.goto([hx, closed_y - amount - 0.004, hz], 1.0, tol=0.003, speed=0.6)
    bot.grip(0.2, 10)
    bot.goto([hx, bot.hand[1] - 0.006, 0.13], 0.2, tol=0.01)


def close_drawer(bot: ActBot, name: str) -> None:
    f = bot.obs()["fixtures"][name]
    hx, hy, hz = f["handle_pos"]
    closed_y = hy + f["opening"]
    bot.goto([hx, hy - 0.04, 0.13], 1.0, tol=0.006)
    bot.goto([hx, hy - 0.04, hz], 1.0, tol=0.004)
    bot.goto([hx, closed_y - 0.017 + 0.004, hz], 1.0, tol=0.003, speed=0.6)
    bot.goto([hx, closed_y - 0.06, hz], 1.0, tol=0.01)
    bot.goto([hx, closed_y - 0.06, 0.13], -0.3, tol=0.01)


def finish(bot: ActBot, text: str = "reference solution finished") -> None:
    bot.obs()
    bot.goto([bot.hand[0], bot.hand[1], max(bot.hand[2], 0.15)], None, tol=0.01)
    bot.req({"op": "done", "text": text})


# --------------------------------------------------------------------------------------------------
# Scenario helpers
# --------------------------------------------------------------------------------------------------

LOWLEVEL = {"skills": False, "max_repeat": 10}
VIS_FIELDS = ["hand_pos", "gripper_open", "holding", "constraint_violations"]
VISION2 = {"obs_mode": "vision", "cameras": ["front", "top"], "visible_fields": VIS_FIELDS}
TOPONLY = {"obs_mode": "vision", "cameras": ["top"], "visible_fields": VIS_FIELDS + ["grid"]}
WRIST = {"obs_mode": "vision", "cameras": ["wrist"], "uncalibrated_cameras": ["wrist"], "visible_fields": VIS_FIELDS}
ORACLES: dict[str, Callable] = {}
R_ORIG = "robouse original"


def task(sc: dict, oracle: Callable) -> None:
    sc.setdefault("suite", "hard")
    HARD_SCENARIOS[sc["id"]] = sc
    ORACLES[sc["id"]] = oracle


def plan_oracle(steps: list) -> Callable:
    """A fixed plan: ("pp", obj, target, opt) / ("open_drawer", name) / ("close_drawer", name)."""
    def run(bot: ActBot, sc: dict) -> None:
        for s in steps:
            if s[0] == "pp":
                pick_place(bot, s[1], s[2], s[3] if len(s) > 3 else {})
            elif s[0] == "open_drawer":
                open_drawer(bot, s[1])
            elif s[0] == "close_drawer":
                close_drawer(bot, s[1])
            else:
                raise ValueError(s)
        finish(bot)
    return run


def hanoi_moves(n: int, a: str, b: str, c: str) -> list[tuple[int, str, str]]:
    """Moves (disc index 0 = largest .. n-1 = smallest, from peg, to peg) for n discs from a to c via b."""
    out: list[tuple[int, str, str]] = []

    def rec(k: int, src: str, via: str, dst: str) -> None:  # move the k smallest discs
        if k == 0:
            return
        rec(k - 1, src, dst, via)
        out.append((n - k, src, dst))
        rec(k - 1, via, src, dst)

    rec(n, a, b, c)
    return out


def hanoi_oracle(discs: list[str], pads: dict[str, str]) -> Callable:
    def run(bot: ActBot, sc: dict) -> None:
        pegs = {"a": list(discs), "b": [], "c": []}
        for d, src, dst in hanoi_moves(len(discs), "a", "b", "c"):
            name = discs[d]
            assert pegs[src][-1] == name
            pegs[src].pop()
            tgt = {"on": pegs[dst][-1]} if pegs[dst] else {"pad": pads[dst]}
            pegs[dst].append(name)
            pick_place(bot, name, tgt, {"open": -1.0, "grasp_dz": 0.003, "release": -1.0})
        finish(bot)
    return run


def run_oracle(env: str, send: Callable | None = None) -> None:
    sc = HARD_SCENARIOS[env]
    rb = sc.get("robouse", {})
    bot = ActBot(send, int(rb.get("max_repeat", 50)))
    try:
        ORACLES[env](bot, sc)
    except Finished:
        return


def oracle_main(env: str) -> None:
    run_oracle(env)


# --------------------------------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------------------------------

def _hanoi(tid: str, rb: dict, title_extra: str, max_steps: int, tags: list[str]) -> None:
    sizes = [0.042, 0.035, 0.028, 0.021]
    cols = ["red", "yellow", "green", "blue"]
    names = ["disc_1", "disc_2", "disc_3", "disc_4"] if rb.get("obs_mode") == "vision" else ["large_disc", "medium_disc", "small_disc", "tiny_disc"]
    objs = [_box(n, c, -0.2, 0.04, half=[s, s, 0.01], z=0.01 + 0.0205 * i) for i, (n, c, s) in enumerate(zip(names, cols, sizes))]
    pads = {k: f"pad_{k}" for k in "abc"}
    task({
        "id": tid, "title": f"Tower of Hanoi, four discs{title_extra}",
        "goal": "Move the tower of four square discs (flat plates of four sizes: red 8.4 cm, yellow 7 cm, green 5.6 cm, blue 4.2 cm wide, "
                "each 2 cm thick) from the left grey pad (pad_a) to the right grey pad (pad_c), using the middle pad (pad_b) as a buffer. "
                "Move one disc at a time and never put a larger disc on a smaller one (checked at every step and reported in "
                "`constraint_violations`). At the end the four discs must be stacked on pad_c, largest at the bottom, each centred on the "
                "one below within 2 cm. The minimum solution is 15 moves.",
        "objects": objs,
        "fixtures": [{"name": f"pad_{k}", "kind": "pad", "pos": [x, 0.04], "size": [0.055, 0.055], "color": "grey", "label": k.upper()}
                     for k, x in (("a", -0.2), ("b", 0.0), ("c", 0.2))],
        "constraints": [{"type": "size_order", "objects": names}],
        "goals": [{"type": "stack", "order": names, "pad": "pad_c", "tol": 0.02}],
        "max_steps": max_steps, "robouse": rb,
        "meta": _meta("BenchFlow robo-use L-family (Tower of Hanoi), extended to four discs", "L-family long-horizon sequencing",
                      "hard", "sequencing", "hard", ["hanoi", "long-horizon", *tags]),
    }, hanoi_oracle(names, pads))


_hanoi("hard-hanoi-4-lowlevel", {**LOWLEVEL}, " (low-level control)", 3000, ["no-skills", "max-repeat-10", "tight-budget"])
_hanoi("hard-hanoi-4-vision-lowlevel", {**LOWLEVEL, **VISION2}, " (vision, low-level control)", 3000,
       ["no-skills", "max-repeat-10", "vision-only", "no-object-coordinates", "tight-budget"])


# ---- ARC-style rules shown only as images ------------------------------------------------------

GRID44 = {"rows": 4, "cols": 4, "cell": 0.07, "origin": [-0.105, 0.17]}
SUP_Y = -0.16
SUP_X = [-0.24, -0.16, -0.08, 0.0, 0.08, 0.16, 0.24]
BUFFER_XY = [[0.27, 0.12], [0.27, 0.02], [-0.27, 0.12], [-0.27, 0.02]]
EX_VIEW = {"center": [0.0, 0.03], "distance": 0.8}


def _cells(*cells, kind=None):
    """("red", r, c) or ("red", r, c, "cyl") -> [{"color", "cell", "kind"}]."""
    out = []
    for e in cells:
        d = {"color": e[0], "cell": [e[1], e[2]]}
        k = e[3] if len(e) > 3 else kind
        if k:
            d["kind"] = k
        out.append(d)
    return out


def _supply_items(colors, xs=SUP_X, y=SUP_Y):
    return [{"kind": "box", "color": c, "pos": [xs[i], y], "size": [0.018] * 3} for i, c in enumerate(colors) if c]


def grid_oracle(expected: list[dict], match_kind: bool = False, opt: dict | None = None) -> Callable:
    """Move blocks until the grid holds `expected` (cell, colour[, kind]); spare blocks may be used."""
    opt = {"open": -0.3, **(opt or {})}

    def key(o_or_e):
        return (o_or_e["color"], o_or_e.get("kind") if match_kind else None)

    def run(bot: ActBot, sc: dict) -> None:
        st = bot.obs()
        objs = st["objects"]
        kinds = {n: ("cyl" if o["kind"] == "cylinder" else "box") for n, o in objs.items()}
        cur = {n: (tuple(o["cell"]) if o.get("cell") else None) for n, o in objs.items()}
        col = {n: o["color"] for n, o in objs.items()}
        okey = lambda n: (col[n], kinds[n] if match_kind else None)
        want = {tuple(e["cell"]): key(e) for e in expected}
        assign: dict[str, tuple] = {}
        # keep blocks already on a correct cell
        for n, c in cur.items():
            if c in want and want[c] == okey(n) and c not in assign.values():
                assign[n] = c
        for c, k in want.items():
            if c in assign.values():
                continue
            cands = [n for n in objs if n not in assign and okey(n) == k]
            # prefer blocks on the grid in a wrong cell, then the nearest spare
            cands.sort(key=lambda n: (cur[n] is None, np.linalg.norm(np.array(objs[n]["pos"][:2]) - np.array(st["grid"]["cell_centers"][c[0]][c[1]][:2]))))
            assign[cands[0]] = c
        # blocks on the grid that are not part of the answer go to buffer spots
        extra = [n for n, c in cur.items() if c is not None and n not in assign]
        buf = list(BUFFER_XY)
        for n in extra:
            pick_place(bot, n, {"xy": buf.pop(0)}, opt)
            cur[n] = None
        todo = {n: c for n, c in assign.items() if cur[n] != c}
        while todo:
            occupied = {c for n, c in cur.items() if c is not None}
            ready = [n for n, c in todo.items() if c not in occupied]
            if ready:
                n = ready[0]
                pick_place(bot, n, {"cell": list(todo[n])}, opt)
                cur[n] = todo.pop(n)
            else:  # a cycle: park one block in a buffer spot
                n = next(iter(todo))
                pick_place(bot, n, {"xy": buf.pop(0)}, opt)
                cur[n] = None
        finish(bot)
    return run


def _arc_img(tid: str, title: str, objects: list, expected: list, examples: list, meta_task: str, max_steps: int,
             match_kind: bool = False, extra_tags=(), fixtures=(), rb_extra: dict | None = None, goal_extra: str = "") -> None:
    task({
        "id": tid, "title": title, "grid": GRID44, "objects": objects, "fixtures": list(fixtures),
        "goals": [{"type": "grid", "expected": expected, **({"match_kind": True} if match_kind else {})}],
        "image_examples": examples, "example_view": EX_VIEW, "goal_extra": goal_extra,
        "max_steps": max_steps, "camera": "top", "robouse": {**TOPONLY, **(rb_extra or {})},
        "meta": _meta("ARC-AGI (style), robouse original", meta_task, "hard", "rule-inference", "hard",
                      ["arc", "few-shot", "examples-as-images-only", "vision-only", "single-camera", *extra_tags]),
    }, grid_oracle(expected, match_kind))


def _g(name, color, cell, kind="box"):
    if kind == "cyl":
        return {"name": name, "kind": "cyl", "color": color, "cell": list(cell), "pos": [0.0, 0.0], "size": [0.018, 0.018]}
    return {"name": name, "kind": "box", "color": color, "cell": list(cell), "pos": [0.0, 0.0], "size": [0.018] * 3}


def _items(prefix: str, n0: int, specs):
    return [dict(_box(f"{prefix}_{n0 + i}", c, x, y, half=0.018)) for i, (c, x, y) in enumerate(specs)]


def _gravity(cells, side):
    """Blocks slide toward `side` (left/right/back/front) in their row/column, keeping order."""
    out = []
    lines = {}
    for col, r, c in cells:
        k = r if side in ("left", "right") else c
        lines.setdefault(k, []).append((col, r, c))
    for k, items in lines.items():
        if side == "left":
            items.sort(key=lambda e: e[2]); out += [(e[0], k, i) for i, e in enumerate(items)]
        elif side == "right":
            items.sort(key=lambda e: -e[2]); out += [(e[0], k, 3 - i) for i, e in enumerate(items)]
        elif side == "back":
            items.sort(key=lambda e: e[1]); out += [(e[0], i, k) for i, e in enumerate(items)]
        else:
            items.sort(key=lambda e: -e[1]); out += [(e[0], 3 - i, k) for i, e in enumerate(items)]
    return out


MARKER_XY = {"left": [-0.215, 0.065], "right": [0.215, 0.065], "back": [0.0, 0.245], "front": [0.0, -0.115]}


def _marker_item(side):
    return {"kind": "box", "color": "black", "pos": MARKER_XY[side], "size": [0.014, 0.014, 0.014]}


def _gravity_example(cells, side):
    return {"before": {"cells": _cells(*cells), "items": [_marker_item(side)]},
            "after": {"cells": _cells(*_gravity(cells, side)), "items": [_marker_item(side)]}}


_test = [("red", 0, 1), ("blue", 1, 0), ("green", 1, 2), ("yellow", 2, 3), ("red", 3, 0), ("blue", 3, 2), ("orange", 2, 1)]
_arc_img(
    "hard-arc-img-gravity-marker", "Rule inference from pictures: the black marker",
    [_g(f"item_{i + 1}", col, (r, c)) for i, (col, r, c) in enumerate(_test)] + [_box("item_8", "black", *MARKER_XY["right"], half=0.014)],
    _cells(*_gravity(_test, "right")),
    [_gravity_example([("red", 0, 2), ("blue", 2, 0), ("green", 2, 3), ("yellow", 3, 1)], "back"),
     _gravity_example([("green", 0, 3), ("red", 1, 1), ("blue", 1, 3), ("yellow", 3, 2), ("red", 3, 3)], "left"),
     _gravity_example([("blue", 0, 0), ("yellow", 1, 2), ("red", 2, 0), ("green", 2, 1), ("blue", 3, 1)], "right")],
    "gravity toward a marker", 1600)


def _connect(cells):
    """Two same-colour blocks in one row or column: the cells between them get blocks of that colour."""
    add = []
    for i, (c1, r1, k1) in enumerate(cells):
        for c2, r2, k2 in cells[i + 1:]:
            if c1 != c2:
                continue
            if r1 == r2:
                add += [(c1, r1, k) for k in range(min(k1, k2) + 1, max(k1, k2))]
            elif k1 == k2:
                add += [(c1, r, k1) for r in range(min(r1, r2) + 1, max(r1, r2))]
    return list(cells) + add


def _connect_example(cells, supply):
    after = _connect(cells)
    used = [c for c, _, _ in after[len(cells):]]
    left = list(supply)
    for c in used:
        left[left.index(c)] = None
    return {"before": {"cells": _cells(*cells), "items": _supply_items(supply)},
            "after": {"cells": _cells(*after), "items": _supply_items(left)}}


_test = [("red", 0, 0), ("red", 0, 3), ("blue", 1, 1), ("blue", 3, 1), ("green", 2, 3), ("yellow", 3, 3)]
_sup = ["blue", "red", "green", "yellow", "red", "blue", "green"]
_arc_img(
    "hard-arc-img-connect",
    "Rule inference from pictures: pairs",
    [_g(f"item_{i + 1}", col, (r, c)) for i, (col, r, c) in enumerate(_test)]
    + [_box(f"item_{7 + i}", c, SUP_X[i], SUP_Y, half=0.018) for i, c in enumerate(_sup)],
    _cells(*_connect(_test)),
    [_connect_example([("green", 1, 0), ("green", 1, 3), ("red", 3, 2)], ["green", "red", "green", "blue", "green", "red", "yellow"]),
     _connect_example([("blue", 0, 2), ("blue", 3, 2), ("yellow", 0, 0), ("red", 1, 0), ("red", 3, 0)],
                      ["yellow", "blue", "red", "blue", "red", "green", "blue"]),
     _connect_example([("yellow", 0, 1), ("yellow", 2, 1), ("green", 3, 0), ("blue", 1, 3)], ["green", "yellow", "yellow", "blue", "red", "blue", "green"])],
    "connect same-coloured pairs using spare blocks", 1200, extra_tags=("supply",),
    goal_extra="Spare blocks stand in a row in front of the grid; spare blocks that are not needed must stay off the grid.")


def _rot(cells):
    return [(c, k, 3 - r) for c, r, k in cells]


_test = [("red", 0, 0), ("blue", 0, 1), ("green", 2, 0), ("yellow", 3, 2), ("orange", 1, 2)]
_arc_img(
    "hard-arc-img-rotate", "Rule inference from pictures: turning",
    [_g(f"item_{i + 1}", col, (r, c)) for i, (col, r, c) in enumerate(_test)],
    _cells(*_rot(_test)),
    [{"before": {"cells": _cells(*e)}, "after": {"cells": _cells(*_rot(e))}} for e in (
        [("red", 0, 1), ("blue", 2, 3), ("green", 3, 0)],
        [("yellow", 0, 0), ("yellow", 0, 1), ("blue", 1, 3), ("red", 3, 3)],
        [("green", 1, 1), ("orange", 2, 2), ("red", 0, 3), ("blue", 3, 1)])],
    "rotate the arrangement a quarter turn", 1400)


def _quad(cells):
    out = []
    for c, r, k in cells:
        for rr, kk in ((r, k), (r, 3 - k), (3 - r, k), (3 - r, 3 - k)):
            out.append((c, rr, kk))
    return out


def _quad_example(cells, supply):
    after = _quad(cells)
    left = list(supply)
    for c, _, _ in after[:]:
        pass
    need = [c for c, r, k in after if (c, r, k) not in cells]
    for c in need:
        left[left.index(c)] = None
    return {"before": {"cells": _cells(*cells), "items": _supply_items(supply)},
            "after": {"cells": _cells(*after), "items": _supply_items(left)}}


_test = [("red", 0, 0), ("blue", 1, 1)]
_sup = ["red", "blue", "green", "blue", "red", "blue", "red"]
_arc_img(
    "hard-arc-img-quadrants", "Rule inference from pictures: completing a pattern",
    [_g(f"item_{i + 1}", col, (r, c)) for i, (col, r, c) in enumerate(_test)]
    + [_box(f"item_{3 + i}", c, SUP_X[i], SUP_Y, half=0.018) for i, c in enumerate(_sup)],
    _cells(*_quad(_test)),
    [_quad_example([("green", 0, 1)], ["green", "red", "green", "yellow", "green", "blue", "red"]),
     _quad_example([("yellow", 1, 0), ("red", 0, 1)], ["red", "yellow", "red", "yellow", "red", "yellow", "green"])],
    "complete a four-fold mirror pattern using spare blocks", 1500, extra_tags=("supply",),
    goal_extra="Spare blocks stand in a row in front of the grid; spare blocks that are not needed must stay off the grid.")


def _shape_rows(cells):
    return [(c, 0 if k == "cyl" else 3, col, k) for c, r, col, k in cells]


_test = [("red", 1, 0, "box"), ("red", 2, 1, "cyl"), ("blue", 1, 2, "cyl"), ("green", 0, 3, "box"), ("yellow", 2, 2, "box")]
_arc_img(
    "hard-arc-img-shapes", "Rule inference from pictures: shapes",
    [_g(f"item_{i + 1}", col, (r, c), k) for i, (col, r, c, k) in enumerate(_test)],
    _cells(*_shape_rows(_test)),
    [{"before": {"cells": _cells(*e)}, "after": {"cells": _cells(*_shape_rows(e))}} for e in (
        [("blue", 1, 1, "box"), ("red", 2, 3, "cyl"), ("green", 1, 0, "cyl")],
        [("yellow", 0, 2, "box"), ("blue", 2, 0, "box"), ("blue", 3, 1, "cyl"), ("red", 1, 3, "box")],
        [("green", 2, 2, "cyl"), ("red", 1, 1, "box"), ("yellow", 3, 0, "cyl")])],
    "sort by shape into rows", 1300, match_kind=True, extra_tags=("shape-perception",))


# ---- wrist (eye-in-hand) camera only ------------------------------------------------------------

def _wrist(tid, title, goal, objects, fixtures, goals, oracle, max_steps, rb_extra=None, tags=(), meta_task="", constraints=None):
    task({
        "id": tid, "title": title, "goal": goal, "objects": objects, "fixtures": fixtures, "goals": goals,
        "constraints": constraints or [], "wrist_camera": True, "max_steps": max_steps, "camera": "front",
        "robouse": {**WRIST, **(rb_extra or {})},
        "meta": _meta(R_ORIG, meta_task or title, "hard", "active-perception", "hard",
                      ["wrist-camera-only", "no-object-coordinates", "no-calibrated-world-camera", "search", *tags]),
    }, oracle)


_wrist("hard-wrist-find-red-cube", "Find the red cube with the wrist camera",
       "Somewhere on the table is exactly one red cube (a box about 4 cm wide). Find it and put it into the white bowl, whose centre is at "
       "x = 0.20, y = 0.15 (inner diameter 12 cm, rim 3.5 cm high). Other objects on the table are distractors: some have a similar colour "
       "or the same colour but a different shape; leave them alone (they are not judged).",
       [_box("item_1", "red", -0.22, -0.18), _cyl("item_2", "red", 0.13, -0.06, r=0.02, hh=0.02), _box("item_3", "orange", 0.04, 0.1),
        _box("item_4", "pink", -0.1, 0.03), _box("item_5", "blue", 0.26, -0.2), _cyl("item_6", "green", -0.25, 0.16, r=0.02, hh=0.03),
        _cyl("item_7", "orange", -0.02, -0.16, r=0.018, hh=0.02)],
       [{"name": "bowl", "kind": "bowl", "pos": [0.2, 0.15], "radius": 0.06, "color": "white"}],
       [{"type": "in", "obj": "item_1", "container": "bowl"}],
       plan_oracle([("pp", "item_1", {"fixture": "bowl"})]), 700, tags=("distractors",), meta_task="find an object by colour and shape")

_wrist("hard-wrist-shape-sort", "Sort by shape with the wrist camera (low-level control)",
       "Four white objects stand on the table: two cylinders and two boxes (all 4 cm wide and 4 cm tall), at unknown places. Put both "
       "cylinders into the LEFT tray (centre x = -0.20, y = 0.18) and both boxes into the RIGHT tray (centre x = 0.20, y = 0.18). Each tray is "
       "14 cm wide (x) and 10 cm deep (y) inside, with 3 cm high walls.",
       [_cyl("item_1", "white", 0.12, -0.12, r=0.02, hh=0.02), _box("item_2", "white", -0.18, -0.08), _box("item_3", "white", 0.02, 0.0),
        _cyl("item_4", "white", -0.06, -0.19, r=0.02, hh=0.02)],
       [{"name": "left_tray", "kind": "tray", "pos": [-0.2, 0.18], "size": [0.07, 0.05], "color": "grey"},
        {"name": "right_tray", "kind": "tray", "pos": [0.2, 0.18], "size": [0.07, 0.05], "color": "grey"}],
       [{"type": "in", "obj": "item_1", "container": "left_tray"}, {"type": "in", "obj": "item_4", "container": "left_tray"},
        {"type": "in", "obj": "item_2", "container": "right_tray"}, {"type": "in", "obj": "item_3", "container": "right_tray"}],
       plan_oracle([("pp", "item_1", {"fixture": "left_tray", "offset": [0.03, 0]}), ("pp", "item_4", {"fixture": "left_tray", "offset": [-0.03, 0]}),
                    ("pp", "item_2", {"fixture": "right_tray", "offset": [-0.03, 0]}), ("pp", "item_3", {"fixture": "right_tray", "offset": [0.03, 0]})]),
       1400, rb_extra=LOWLEVEL, tags=("shape-perception", "no-skills", "max-repeat-10"), meta_task="sort objects by shape")

_wrist("hard-wrist-stack-by-size", "Stack by size with the wrist camera (low-level control)",
       "Three grey cubes of different sizes (5 cm, 4 cm and 3 cm) are somewhere on the table. Stack all three on the gold pad (centre "
       "x = 0.0, y = 0.15, 8 cm square): largest at the bottom, resting on the pad, then the middle one, then the smallest on top, each "
       "centred on the one below within 1.5 cm.",
       [_box("item_1", "grey", 0.2, -0.15, half=0.015), _box("item_2", "grey", -0.22, -0.02, half=0.025), _box("item_3", "grey", 0.08, -0.05, half=0.02)],
       [{"name": "gold_pad", "kind": "pad", "pos": [0.0, 0.15], "size": [0.04, 0.04], "color": "gold"}],
       [{"type": "stack", "order": ["item_2", "item_3", "item_1"], "pad": "gold_pad", "tol": 0.015}],
       plan_oracle([("pp", "item_2", {"pad": "gold_pad"}), ("pp", "item_3", {"on": "item_2"}), ("pp", "item_1", {"on": "item_3"})]),
       1200, rb_extra=LOWLEVEL, tags=("size-perception", "no-skills", "max-repeat-10", "stacking"), meta_task="stack by size")

_COUNT_PADS = [[-0.25 + 0.1 * i, -0.235] for i in range(6)]
_wrist("hard-wrist-count-marker", "Count with the wrist camera",
       "Coloured blocks are scattered over the table. Count them (do not count the black marker cube or the numbered pads) and put the "
       "black marker cube onto the grey pad whose number equals the count. The six numbered pads lie in a row along the front edge of the table: "
       "pad 1 is centred at x = -0.25, pad 2 at x = -0.15, pad 3 at x = -0.05, pad 4 at x = 0.05, pad 5 at x = 0.15, pad 6 at x = 0.25, all at "
       "y = -0.235, each 6 cm square. The marker starts at x = 0.0, y = 0.0. Leave the coloured blocks where they are (each must stay within 2 cm "
       "of where it started).",
       [_box("item_1", "black", 0.0, 0.0, half=0.015), _box("item_2", "red", -0.28, 0.22), _box("item_3", "blue", 0.28, 0.2),
        _box("item_4", "green", 0.1, 0.08), _box("item_5", "yellow", -0.15, -0.1), _box("item_6", "purple", 0.29, -0.12),
        _box("item_7", "orange", -0.3, 0.02)],
       [{"name": f"pad_{i + 1}", "kind": "pad", "pos": p, "size": [0.03, 0.03], "color": "grey", "label": str(i + 1)} for i, p in enumerate(_COUNT_PADS)],
       [{"type": "on_pad", "obj": "item_1", "pad": "pad_6"}] + [{"type": "unmoved", "obj": f"item_{k}"} for k in range(2, 8)],
       plan_oracle([("pp", "item_1", {"pad": "pad_6"})]), 700, tags=("counting",), meta_task="count objects, then act on the count")

_wrist("hard-wrist-peg-in-socket", "Insert a peg found with the wrist camera",
       "An orange peg (a cylinder 3.2 cm in diameter and 8 cm tall, standing upright) is somewhere on the table. Insert it upright into the dark "
       "square socket centred at x = 0.15, y = 0.12: the socket is 3.8 cm wide inside (3 mm clearance on each side) with 3.5 cm high walls. "
       "Success: the peg stands on the table inside the socket, centre within 8 mm of the socket centre, tilt under 5 degrees, released.",
       [_cyl("item_1", "orange", -0.17, -0.13, r=0.016, hh=0.04), _cyl("item_2", "yellow", 0.05, -0.08, r=0.016, hh=0.04)],
       [{"name": "socket", "kind": "socket", "pos": [0.15, 0.12], "inner": 0.019, "height": 0.035, "color": "darkgrey"}],
       [{"type": "in_socket", "obj": "item_1", "socket": "socket", "xy_tol": 0.008, "max_bottom": 0.008, "max_tilt": 5}],
       plan_oracle([("pp", "item_1", {"fixture": "socket"}, {"grasp_dz": 0.02, "drop": 0.002, "carry_z": 0.2})]), 700,
       tags=("insertion", "tight-clearance"), meta_task="insertion")


# ---- dynamics and precision ---------------------------------------------------------------------

LANE_MU = 0.03
LANE = {"name": "lane", "kind": "lane", "pos": [0.0, 0.3], "size": [0.12, 0.55], "height": 0.004, "friction": LANE_MU, "color": "white"}
ZONE = [-0.1, 0.1, 0.44, 0.62]
LANE_NOTE = (
    "The lane is a smooth white slab 24 cm wide (x from -0.12 to 0.12) and 4 mm thick whose surface is very slippery (friction "
    "coefficient about 0.03 against the pucks); it runs from y = -0.25 past the back edge of the table and ends in mid-air at y = 0.85. A puck "
    "that slides past the end falls off. The gripper can only reach y <= 0.28, so the zone (the blue rectangle painted on the lane, x from "
    "-0.10 to 0.10, y from 0.44 to 0.62) cannot be reached: a puck must be pushed so that it slides there by itself, and a puck that stops "
    "beyond y = 0.28 can never be touched again. Each puck is a disc 5 cm across and 2 cm thick. Success is judged after `robo done`: the puck's "
    "centre must be inside the zone, resting on the lane and no longer moving.")


def _flick(bot: ActBot, name: str, v: float, start_y: float = 0.12) -> None:
    st = bot.obs()
    p = np.array(st["objects"][name]["pos"])
    x = p[0]
    bot.goto([x, p[1] - 0.1, 0.1], 1.0, tol=0.006)
    bot.goto([x, p[1] - 0.1, 0.018], 1.0, tol=0.003)
    for _ in range(200):  # slow push up the lane: the puck stays against the fingers
        st = bot.act([0, 0.3, 0, 1.0], 1)
        if bot.obs()["objects"][name]["pos"][1] >= start_y:
            break
    bot.act([0, 0, 0, 1.0], 20)
    bot.act([0, 0, 0, 1.0], 20)
    py = bot.obs()["objects"][name]["pos"][1]
    bot.goto([x, py - 0.087, 0.018], 1.0, tol=0.002)
    n = int(round(0.09 / (0.01 * v)))
    while n > 0:
        k = min(bot.R, n)
        bot.act([0, v, 0, 1.0], k)
        n -= k
    for _ in range(8):
        bot.act([0, 0, 0, 1.0], bot.R)
    bot.goto([bot.hand[0], bot.hand[1] - 0.03, 0.1], 1.0, tol=0.01)
    for _ in range(40):  # wait until it has stopped
        bot.act([0, 0, 0, 1.0], bot.R)
        st = bot.obs()
        if st["objects"][name]["pos"][1] > 0.3:
            break


def _puck(name, color, x):
    return _cyl(name, color, x, -0.1, r=0.025, hh=0.01, friction=LANE_MU, z=0.014)


def shuffle_oracle(pucks: list[str], v: float) -> Callable:
    def run(bot: ActBot, sc: dict) -> None:
        for n in pucks:
            _flick(bot, n, v)
        for _ in range(10):
            bot.act([0, 0, 0, 1.0], bot.R)
        finish(bot)
    return run


_DYN_TAGS = ["dynamics", "no-skills", "max-repeat-5", "one-shot"]
task({
    "id": "hard-shuffleboard", "title": "Shuffleboard: slide the puck into an unreachable zone",
    "goal": "Slide the red puck along the slippery lane so that it comes to rest inside the blue zone. " + LANE_NOTE,
    "objects": [_puck("puck", "red", 0.0)],
    "fixtures": [LANE, {"name": "zone", "kind": "pad", "pos": [0.0, 0.53], "size": [0.1, 0.09], "z": 0.004, "color": "blue"}],
    "goals": [{"type": "in_zone", "obj": "puck", "rect": ZONE, "z": 0.004}],
    "max_steps": 600, "robouse": {"skills": False, "max_repeat": 5},
    "meta": _meta(R_ORIG, "shuffleboard (dynamic release)", "hard", "dynamics", "hard", _DYN_TAGS + ["unreachable-goal"]),
}, shuffle_oracle(["puck"], 0.66))

task({
    "id": "hard-curling-two", "title": "Curling: two pucks into an unreachable zone",
    "goal": "Slide both pucks (red and yellow) along the slippery lane so that both come to rest inside the blue zone at the same time. A puck "
            "that hits the other can knock it out. " + LANE_NOTE,
    "objects": [_puck("red_puck", "red", -0.06), _puck("yellow_puck", "yellow", 0.06)],
    "fixtures": [LANE, {"name": "zone", "kind": "pad", "pos": [0.0, 0.53], "size": [0.1, 0.09], "z": 0.004, "color": "blue"}],
    "goals": [{"type": "in_zone", "obj": "red_puck", "rect": ZONE, "z": 0.004}, {"type": "in_zone", "obj": "yellow_puck", "rect": ZONE, "z": 0.004}],
    "max_steps": 1000, "robouse": {"skills": False, "max_repeat": 5},
    "meta": _meta(R_ORIG, "curling (dynamic release, two objects)", "hard", "dynamics", "hard", _DYN_TAGS + ["unreachable-goal", "multi-object"]),
}, shuffle_oracle(["red_puck", "yellow_puck"], 0.66))

task({
    "id": "hard-tight-peg", "title": "Tight-clearance peg insertion (low-level control)",
    "goal": "Pick up the orange peg (a cylinder 3.2 cm in diameter and 8 cm tall) and insert it upright into the dark square socket. The socket "
            "is 3.5 cm wide inside, so the clearance is only 1.5 mm on each side, and its walls are 3.5 cm high. Success: the peg stands on the "
            "table inside the socket, centre within 4 mm of the socket centre, tilt under 3 degrees, released.",
    "objects": [_cyl("peg", "orange", -0.15, -0.08, r=0.016, hh=0.04)],
    "fixtures": [{"name": "socket", "kind": "socket", "pos": [0.14, 0.1], "inner": 0.0175, "height": 0.035, "color": "darkgrey"}],
    "goals": [{"type": "in_socket", "obj": "peg", "socket": "socket", "xy_tol": 0.004, "max_bottom": 0.006, "max_tilt": 3}],
    "max_steps": 500, "robouse": {"skills": False, "max_repeat": 5},
    "meta": _meta("BenchFlow robo-use D03 Gentle Insertion, tightened", "D03 Gentle Insertion", "hard", "insertion", "hard",
                  ["insertion", "tight-clearance", "no-skills", "max-repeat-5", "tight-budget"]),
}, plan_oracle([("pp", "peg", {"fixture": "socket"}, {"grasp_dz": 0.02, "drop": 0.002, "carry_z": 0.2, "xy_tol": 0.0008, "down_speed": 0.5})]))

task({
    "id": "hard-fragile-tower", "title": "Build a tower and crown it with a fragile vial (low-level control)",
    "goal": "Stack the blue cube on the red cube on the grey pad (red at the bottom, resting on the pad), then stand the fragile white vial "
            "upright on top of the blue cube (tilt under 10 degrees). The vial must never move downward faster than 0.1 m/s (0.2 cm per "
            "step), measured at every step and reported in `constraint_violations`; even a drop of a few millimetres breaks this limit. Each "
            "item must be centred on the one below within 1.5 cm.",
    "objects": [_box("red_cube", "red", -0.18, -0.1, half=0.025), _box("blue_cube", "blue", 0.18, -0.12, half=0.022),
                _cyl("vial", "white", -0.05, -0.16, r=0.012, hh=0.03)],
    "fixtures": [{"name": "grey_pad", "kind": "pad", "pos": [0.0, 0.12], "size": [0.045, 0.045], "color": "grey"}],
    "constraints": [{"type": "max_down_speed", "object": "vial", "limit": 0.1}],
    "goals": [{"type": "stack", "order": ["red_cube", "blue_cube", "vial"], "pad": "grey_pad", "tol": 0.015}, {"type": "upright", "obj": "vial", "max_tilt": 10}],
    "max_steps": 900, "robouse": {**LOWLEVEL},
    "meta": _meta("BenchFlow robo-use D03 (impact-limited handling) combined with stacking", "D03 Gentle Insertion", "hard", "gentle", "hard",
                  ["fragile", "speed-limit", "stacking", "no-skills", "max-repeat-10"]),
}, plan_oracle([("pp", "red_cube", {"pad": "grey_pad"}), ("pp", "blue_cube", {"on": "red_cube"}),
                ("pp", "vial", {"on": "blue_cube"}, {"slow": True, "slow_speed": 0.08, "grasp_dz": 0.01})]))

_PL = [("plate_1", "red", 0.04), ("plate_2", "yellow", 0.033), ("plate_3", "green", 0.026), ("plate_4", "blue", 0.019)]
task({
    "id": "hard-thin-plates", "title": "Stack four thin plates precisely (low-level control)",
    "goal": "Stack the four thin square plates (1.2 cm thick; red 8 cm, yellow 6.6 cm, green 5.2 cm, blue 3.8 cm wide) on the grey pad in order of "
            "size: red at the bottom resting on the pad, then yellow, green, blue on top. Each plate must lie flat (tilt under 3 degrees) and "
            "be centred on the one below within 5 mm.",
    "objects": [_box(n, c, x, y, half=[h, h, 0.006]) for (n, c, h), (x, y) in zip(_PL, [(0.2, -0.15), (-0.2, -0.12), (0.05, -0.18), (-0.22, 0.12)])],
    "fixtures": [{"name": "grey_pad", "kind": "pad", "pos": [0.12, 0.12], "size": [0.05, 0.05], "color": "grey"}],
    "goals": [{"type": "stack", "order": [p[0] for p in _PL], "pad": "grey_pad", "tol": 0.005}]
             + [{"type": "on_top_level", "obj": _PL[i + 1][0], "base": _PL[i][0], "tol": 0.005, "max_tilt": 3} for i in range(3)],
    "max_steps": 1000, "robouse": {**LOWLEVEL},
    "meta": _meta(R_ORIG, "precise stacking of thin plates", "hard", "precision", "hard", ["precision", "stacking", "thin-objects", "no-skills", "max-repeat-10"]),
}, plan_oracle([("pp", n, {"pad": "grey_pad"} if i == 0 else {"on": _PL[i - 1][0]}, {"open": -1.0, "release": -1.0, "xy_tol": 0.001, "drop": 0.002})
                for i, (n, _, _) in enumerate(_PL)]))
