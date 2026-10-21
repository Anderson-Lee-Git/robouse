"""Tabletop scenes as MJCF: the table, the gripper, objects and fixtures, from a scenario dict."""

from __future__ import annotations

import math

import numpy as np

COLORS: dict[str, tuple[float, float, float]] = {
    "red": (0.85, 0.15, 0.15),
    "blue": (0.15, 0.32, 0.85),
    "green": (0.15, 0.62, 0.25),
    "yellow": (0.95, 0.80, 0.10),
    "orange": (0.97, 0.50, 0.10),
    "purple": (0.55, 0.25, 0.75),
    "violet": (0.62, 0.40, 0.90),
    "cyan": (0.10, 0.75, 0.80),
    "white": (0.93, 0.93, 0.93),
    "black": (0.10, 0.10, 0.10),
    "grey": (0.55, 0.55, 0.55),
    "darkgrey": (0.30, 0.30, 0.32),
    "brown": (0.50, 0.33, 0.20),
    "teal": (0.10, 0.55, 0.55),
    "gold": (0.85, 0.68, 0.20),
    "pink": (0.95, 0.55, 0.70),
    "silver": (0.78, 0.80, 0.84),
    "tan": (0.80, 0.68, 0.50),
}

TABLE_HX, TABLE_HY = 0.35, 0.30
FLOOR_Z = -0.2
HAND_LO = np.array([-0.34, -0.27, 0.012])
HAND_HI = np.array([0.34, 0.28, 0.35])
HAND_HOME = [0.0, 0.2, 0.25]
STEP_M = 0.01  # metres per action unit per step
SUBSTEPS = 10  # 10 x 2 ms = 20 ms per env step
FINGER_OPEN = 0.05  # per-finger travel; fully open gap = 0.10 m
SETTLE_SUBSTEPS = 150
WRIST_CAM_POS = (0.04, 0.0, 0.06)  # hard suite: eye-in-hand camera, relative to the tool point, looking straight down
WRIST_CAM_FOVY = 50

# collision classes: static world ct=4 ca=1; drawer ct=2 ca=1; objects + gripper ct=1 ca=7
STATIC = 'contype="4" conaffinity="1"'
DRAWER = 'contype="2" conaffinity="1"'
MOVING = 'contype="1" conaffinity="7"'
VISUAL = 'contype="0" conaffinity="0"'

# drawer geometry (cabinet frame = cabinet centre on the table)
DR_IN = 0.059  # drawer interior half size (x and y)
DR_FLOOR = 0.006  # drawer floor top
DR_WALL_TOP = 0.056
DR_HANDLE = (-0.117, 0.045)  # handle bar (y offset from cabinet centre when closed, z)
DR_TRAVEL = 0.12

# one-demo suite parts (onedemo.py): the part the gripper touches is the same on every object of a family, while the
# object's size, shape and pose change. A ball (the hinged lid's knob, the bottle's cap) pinched from above can turn
# about the pinch axis: it takes the box's or the bottle's contact parameters (priority) and has no torsional friction
# (condim 3), so a held lid or bottle can swing about a horizontal y axis while the fingers stay level.
BALL_R = 0.012
BALL = 'priority="1" friction="1.5 0.005 0.0001" condim="3"'
HB_LID_T = 0.008  # hinged lid: slab thickness
HB_WALL_T = 0.006
HB_STEM = 0.022  # height of the knob ball's centre above the lid's top face
HB_INSET = 0.025  # the knob ball's centre from the lid's free edge
HB_MAX_DEG = 110.0  # the lid's stop: past upright, so an opened lid rests open
LID_KNOB = (0.01, 0.022)  # lift-off lid: the knob, a vertical cylinder (radius, height)
LID_SLAB_T = 0.008
CAB_T = 0.008  # cabinet wall thickness
HANDLE_GAP = 0.035  # cabinet drawer handle: clear gap between the bar and the drawer face
HANDLE_BAR = (0.04, 0.005, 0.006)  # the bar's half length (along the face), half thickness (out from it), half height
CABINET_YAW = {"front": 0.0, "left": -90.0, "right": 90.0}  # the drawer slides out toward -y, -x or +x


def _f(*v) -> str:
    return " ".join(f"{float(x):.5g}" for x in v)


def _rgba(c: str, a: float = 1.0) -> str:
    return _f(*COLORS.get(c, COLORS["grey"]), a)


# --------------------------------------------------------------------------------------------------
# MJCF builder
# --------------------------------------------------------------------------------------------------


def _obj_xml(o: dict) -> str:
    n, kind, col = o["name"], o["kind"], o.get("color", "grey")
    x, y = o["pos"][:2]
    z = o.get("z", _obj_rest_half(o))
    yaw = o.get("yaw", 0.0)
    fr = (
        'friction="1.0 0.01 0.001" condim="4"'
        if "friction" not in o
        else f'friction="{_f(o["friction"])} 0.01 0.001" condim="4"'
    )
    head = f'<body name="obj_{n}" pos="{_f(x, y, z)}" euler="0 0 {yaw}"><freejoint name="fj_{n}"/>'
    if kind == "box":
        hx, hy, hz = o["size"]
        dens = o.get("density", 400)
        g = f'<geom name="g_{n}" type="box" size="{_f(hx, hy, hz)}" rgba="{_rgba(col)}" density="{dens}" {fr} {MOVING}/>'
        if o.get("label") == "heavy":  # dark band so the heavy blocks read as metal
            g += f'<geom type="box" size="{_f(hx + 0.0005, hy + 0.0005, hz * 0.25)}" rgba="0.15 0.15 0.15 1" {VISUAL}/>'
        return head + g + "</body>"
    if kind == "cyl":
        r, hh = o["size"]
        dens = o.get("density", 400)
        return (
            head
            + (
                f'<geom name="g_{n}" type="cylinder" size="{_f(r, hh)}" rgba="{_rgba(col, o.get("alpha", 1.0))}" '
                f'density="{dens}" {fr} {MOVING}/>'
            )
            + "</body>"
        )
    if kind == "knife":
        # origin = geometric centre; handle on local -x, blade on local +x
        return (
            head
            + (
                f'<geom name="g_{n}" type="box" pos="-0.04 0 0" size="0.035 0.011 0.012" rgba="{_rgba("brown")}" density="500" {fr} {MOVING}/>'
                f'<geom name="g_{n}_blade" type="box" pos="0.035 0 -0.004" size="0.04 0.0025 0.008" rgba="{_rgba("silver")}" density="300" {fr} {MOVING}/>'
            )
            + "</body>"
        )
    if kind == "lid":
        return _lid_xml(o, x, y, z, fr)
    if kind == "bottle":
        return _bottle_xml(o, x, y, z, fr)
    raise ValueError(f"unknown object kind {kind!r}")


def lid_dims(o: dict) -> dict:
    """A lift-off lid, from the bottom up: a plug that fits inside its container's opening, the slab that rests on the
    rim, and a knob on top. The body's origin is the centre of that stack, so its bottom is `height` / 2 below it."""
    plug = float(o.get("plug", 0.012))
    kr, kh = LID_KNOB
    return {"plug": plug, "slab": LID_SLAB_T, "knob_r": kr, "knob_h": kh, "height": plug + LID_SLAB_T + kh}


def _lid_xml(o: dict, x: float, y: float, z: float, fr: str) -> str:
    n, col = o["name"], o.get("color", "grey")
    d = lid_dims(o)
    h = d["height"]
    inset = float(o.get("plug_inset", 0.012))  # the plug is this much smaller than the slab on every side
    zp, zs, zk = -h / 2 + d["plug"] / 2, -h / 2 + d["plug"] + d["slab"] / 2, h / 2 - d["knob_h"] / 2
    dens = o.get("density", 400)
    if o.get("shape", "box") == "round":
        r = float(o["size"][0])
        slab = f'type="cylinder" pos="{_f(0, 0, zs)}" size="{_f(r, d["slab"] / 2)}"'
        plug = f'type="cylinder" pos="{_f(0, 0, zp)}" size="{_f(r - inset, d["plug"] / 2)}"'
    else:
        hx, hy = o["size"][:2]
        slab = f'type="box" pos="{_f(0, 0, zs)}" size="{_f(hx, hy, d["slab"] / 2)}"'
        plug = f'type="box" pos="{_f(0, 0, zp)}" size="{_f(hx - inset, hy - inset, d["plug"] / 2)}"'
    return (
        f'<body name="obj_{n}" pos="{_f(x, y, z)}" euler="0 0 {o.get("yaw", 0.0)}"><freejoint name="fj_{n}"/>'
        f'<geom name="g_{n}" {slab} rgba="{_rgba(col)}" density="{dens}" {fr} {MOVING}/>'
        f'<geom name="g_{n}_plug" {plug} rgba="{_rgba(col)}" density="{dens}" {fr} {MOVING}/>'
        f'<geom name="g_{n}_knob" type="cylinder" pos="{_f(0, 0, zk)}" size="{_f(d["knob_r"], d["knob_h"] / 2)}" '
        f'rgba="{_rgba(o.get("knob_color", "darkgrey"))}" density="{dens}" {fr} {MOVING}/>'
        "</body>"
    )


def bottle_dims(o: dict) -> dict:
    """A bottle along its local z axis, base to cap: the body, the neck and a ball cap whose centre is the neck's end.
    The body's origin is the middle of that length."""
    rb, lb = (float(v) for v in o["body"])
    rn, ln = (float(v) for v in o.get("neck", (0.008, 0.035)))
    return {"body_r": rb, "body_len": lb, "neck_r": rn, "neck_len": ln, "length": lb + ln + BALL_R}


def _bottle_xml(o: dict, x: float, y: float, z: float, fr: str) -> str:
    """A full bottle is heavy: `mass` (kg) sits in its body. The fingers' pinch on the cap holds less than its weight, so
    the cap cannot lift it clear of the table, but it can tip the bottle up about its base, which then carries most
    of the weight."""
    n, col = o["name"], o.get("color", "green")
    d = bottle_dims(o)
    z0 = -d["length"] / 2
    q = _f(*obj_quat(o))
    body = f'mass="{_f(o["mass"])}"' if "mass" in o else f'density="{o.get("density", 300)}"'
    return (
        f'<body name="obj_{n}" pos="{_f(x, y, z)}" quat="{q}"><freejoint name="fj_{n}"/>'
        f'<geom name="g_{n}" type="cylinder" pos="{_f(0, 0, z0 + d["body_len"] / 2)}" size="{_f(d["body_r"], d["body_len"] / 2)}" '
        f'rgba="{_rgba(col, o.get("alpha", 1.0))}" {body} {fr} {MOVING}/>'
        f'<geom name="g_{n}_neck" type="cylinder" pos="{_f(0, 0, z0 + d["body_len"] + d["neck_len"] / 2)}" '
        f'size="{_f(d["neck_r"], d["neck_len"] / 2)}" rgba="{_rgba(col, o.get("alpha", 1.0))}" density="300" {fr} {MOVING}/>'
        f'<geom name="g_{n}_cap" type="sphere" pos="{_f(0, 0, z0 + d["body_len"] + d["neck_len"])}" size="{BALL_R}" '
        f'rgba="{_rgba(o.get("cap_color", "white"))}" density="300" {BALL} {MOVING}/>'
        "</body>"
    )


def obj_quat(o: dict) -> list[float]:
    """An object's starting orientation (w, x, y, z): its yaw about z, after laying it on its side first if it is a bottle
    with `lying` "+x" or "-x" (its axis, local z, then points that way)."""
    yaw = math.radians(o.get("yaw", 0.0))
    qz = [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]
    if o.get("kind") != "bottle" or not o.get("lying"):
        return qz
    a = math.radians(90.0 if o["lying"] == "+x" else -90.0)
    w1, z1 = qz[0], qz[3]
    w2, y2 = math.cos(a / 2), math.sin(a / 2)  # a quarter turn about y, then the yaw: qz * qy
    return [w1 * w2, -z1 * y2, w1 * y2, z1 * w2]


def _obj_rest_half(o: dict) -> float:
    if o["kind"] == "box":
        return o["size"][2]
    if o["kind"] == "cyl":
        return o["size"][1]
    if o["kind"] == "knife":
        return 0.012
    if o["kind"] == "lid":
        return lid_dims(o)["height"] / 2
    if o["kind"] == "bottle":
        d = bottle_dims(o)
        return d["body_r"] if o.get("lying") else d["length"] / 2
    return 0.02


def _walls_xml(name: str, hx: float, hy: float, h: float, col: str, t: float = 0.006, floor: bool = True) -> str:
    s = []
    if floor:
        s.append(
            f'<geom name="{name}_floor" type="box" pos="0 0 0.003" size="{_f(hx + t, hy + t, 0.003)}" rgba="{_rgba(col)}" {STATIC}/>'
        )
    for sx in (-1, 1):
        s.append(
            f'<geom type="box" pos="{_f(sx * (hx + t / 2), 0, h / 2)}" size="{_f(t / 2, hy + t, h / 2)}" rgba="{_rgba(col)}" {STATIC}/>'
        )
    for sy in (-1, 1):
        s.append(
            f'<geom type="box" pos="{_f(0, sy * (hy + t / 2), h / 2)}" size="{_f(hx, t / 2, h / 2)}" rgba="{_rgba(col)}" {STATIC}/>'
        )
    return "".join(s)


def _fixture_xml(fx: dict, grid: dict | None) -> str:
    k, n = fx["kind"], fx["name"]
    col = fx.get("color", "grey")
    x, y = _fixture_xy(fx, grid)
    z0 = fx.get("z", 0.0)
    if k == "pad":
        hx, hy = fx.get("size", [0.04, 0.04])
        dz = 0.0012 if fx.get("cell") else 0.0008
        return f'<geom name="pad_{n}" type="box" pos="{_f(x, y, z0 + dz)}" size="{_f(hx, hy, dz)}" rgba="{_rgba(col)}" {VISUAL}/>'
    if k == "tray":
        hx, hy = fx.get("size", [0.07, 0.06])
        return (
            f'<body name="fx_{n}" pos="{_f(x, y, z0)}">'
            + _walls_xml(n, hx, hy, fx.get("height", 0.03), col)
            + "</body>"
        )
    if k == "bowl":  # octagonal low-walled bowl
        R, h, t = fx.get("radius", 0.07), fx.get("height", 0.035), 0.006
        s = [
            f'<body name="fx_{n}" pos="{_f(x, y, z0)}">',
            f'<geom name="{n}_floor" type="cylinder" pos="0 0 0.003" size="{_f(R + t, 0.003)}" rgba="{_rgba(col)}" {STATIC}/>',
        ]
        half_len = R * math.tan(math.pi / 8) + t / 2
        for i in range(8):
            a = i * math.pi / 4
            s.append(
                f'<geom type="box" pos="{_f((R + t / 2) * math.cos(a), (R + t / 2) * math.sin(a), h / 2)}" '
                f'euler="0 0 {math.degrees(a):.3f}" size="{_f(t / 2, half_len, h / 2)}" rgba="{_rgba(col)}" {STATIC}/>'
            )
        return "".join(s) + "</body>"
    if k == "plate":
        R = fx.get("radius", 0.065)
        return (
            f'<geom name="{n}_plate" type="cylinder" pos="{_f(x, y, z0 + 0.004)}" size="{_f(R, 0.004)}" rgba="{_rgba(col)}" {STATIC}/>'
            f'<geom type="cylinder" pos="{_f(x, y, z0 + 0.0085)}" size="{_f(R * 0.7, 0.0005)}" rgba="0.85 0.85 0.85 1" {VISUAL}/>'
        )
    if k == "socket":
        s = fx.get("inner", 0.022)
        return (
            f'<body name="fx_{n}" pos="{_f(x, y, z0)}">'
            + _walls_xml(n, s, s, fx.get("height", 0.035), col, t=0.01, floor=False)
            + "</body>"
        )
    if k == "drawer":
        return _drawer_xml(n, x, y, col)
    if k == "figure":
        return _figure_xml(n, x, y, z0, fx.get("yaw", 0.0))
    if k == "lane":  # hard suite: a raised low-friction slab (shuffleboard lane); may extend past the table edge
        hx, hy = fx.get("size", [0.1, 0.4])
        h = fx.get("height", 0.004)
        mu = fx.get("friction", 0.03)
        return (
            f'<geom name="lane_{n}" type="box" pos="{_f(x, y, z0 + h / 2)}" size="{_f(hx, hy, h / 2)}" rgba="{_rgba(col)}" '
            f'friction="{_f(mu)} 0.005 0.0001" condim="3" {STATIC}/>'
        )
    if k == "hinged_box":
        return _hinged_box_xml(fx, x, y)
    if k == "cabinet":
        return _cabinet_xml(fx, x, y)
    raise ValueError(f"unknown fixture kind {k!r}")


def hinged_box_dims(fx: dict) -> dict:
    """A hinged box's lid in its own frame: the hinge line runs along y through `hinge` (the box's top outer edge on the
    `hinge` side, at the lid's mid-thickness); the knob ball sits `knob` from it, measured along the closed lid toward its
    free edge (x) and up (z). `sign` is +1 when the free edge lies toward +x (a hinge on the left), -1 otherwise."""
    x, y = fx["pos"][:2]
    sx, sy, sz = fx["size"]
    s = 1.0 if fx.get("hinge", "left") == "left" else -1.0
    return {
        "sign": s,
        "hinge": [x - s * sx / 2, y, sz - HB_LID_T / 2],
        "knob": [sx - HB_INSET, HB_LID_T / 2 + HB_STEM],
        "max_deg": float(fx.get("max_deg", HB_MAX_DEG)),
    }


def _hinged_box_xml(fx: dict, x: float, y: float) -> str:
    """A box with a lid on a hinge along one of its top edges (a y axis), and a ball knob on a stem near the lid's free
    edge. Its joint limit holds the closed lid at angle 0, and an opened lid stops at `max_deg`, past upright, where it
    rests. The lid collides with the gripper and objects but not with its own box, so the hinge cannot jam."""
    n = fx["name"]
    sx, sy, sz = fx["size"]
    hx, hy, t = sx / 2, sy / 2, HB_WALL_T
    wall_h = sz - HB_LID_T
    col = _rgba(fx.get("color", "tan"))
    d = hinged_box_dims(fx)
    s = d["sign"]
    g = [
        f'<body name="fx_{n}" pos="{_f(x, y, 0)}">',
        f'<geom name="{n}_floor" type="box" pos="0 0 0.003" size="{_f(hx, hy, 0.003)}" rgba="{col}" {STATIC}/>',
    ]
    for side in (-1, 1):
        g.append(
            f'<geom type="box" pos="{_f(side * (hx - t / 2), 0, wall_h / 2)}" size="{_f(t / 2, hy, wall_h / 2)}" rgba="{col}" {STATIC}/>'
        )
        g.append(
            f'<geom type="box" pos="{_f(0, side * (hy - t / 2), wall_h / 2)}" size="{_f(hx - t, t / 2, wall_h / 2)}" rgba="{col}" {STATIC}/>'
        )
    g.append("</body>")
    kx, kz = s * d["knob"][0], d["knob"][1]
    lcol, metal = _rgba(fx.get("lid_color", fx.get("color", "tan"))), _rgba("silver")
    g += [
        f'<body name="lid_{n}" pos="{_f(*d["hinge"])}">',
        f'<joint name="hj_{n}" type="hinge" axis="0 {-s:g} 0" range="0 {d["max_deg"]:g}" damping="0.01" armature="0.0002" '
        'solreflimit="0.005 1"/>',
        f'<geom name="{n}_lid" type="box" pos="{_f(s * hx, 0, 0)}" size="{_f(hx + 0.002, hy + 0.002, HB_LID_T / 2)}" '
        f'rgba="{lcol}" density="400" {DRAWER}/>',
        f'<geom type="cylinder" fromto="{_f(kx, 0, HB_LID_T / 2 - 0.001, kx, 0, kz)}" size="0.004" rgba="{metal}" density="400" {DRAWER}/>',
        f'<geom name="{n}_knob" type="sphere" pos="{_f(kx, 0, kz)}" size="{BALL_R}" rgba="{metal}" density="400" {BALL} {DRAWER}/>',
        f'<geom type="cylinder" pos="0 0 0" euler="90 0 0" size="{_f(0.005, hy * 0.8)}" rgba="{metal}" {VISUAL}/>',
        "</body>",
    ]
    return "".join(g)


def cabinet_handle_local(fx: dict) -> list[float]:
    """The centre of a cabinet drawer's handle bar in the cabinet's frame, with the drawer shut (it slides along -y)."""
    w, d, h = fx["size"]
    return [0.0, -d / 2 - HANDLE_GAP - HANDLE_BAR[1], float(fx.get("handle_z", h - 0.04))]


def _cabinet_xml(fx: dict, x: float, y: float) -> str:
    """A cabinet with one drawer that slides out of its face, facing the front (-y), the left (-x) or the right (+x), up to
    `travel`. The handle is a bar on two posts with a HANDLE_GAP gap behind it. As with `drawer`, the drawer does not
    collide with its own cabinet, only with the gripper and objects."""
    n = fx["name"]
    w, d, h = fx["size"]
    t = CAB_T
    yaw = CABINET_YAW[fx.get("facing", "front")]
    c, metal = _rgba(fx.get("color", "darkgrey")), _rgba("silver")
    g = [f'<body name="fx_{n}" pos="{_f(x, y, 0)}" euler="0 0 {yaw:g}">']
    for side in (-1, 1):
        g.append(
            f'<geom type="box" pos="{_f(side * (w / 2 - t / 2), 0, h / 2)}" size="{_f(t / 2, d / 2, h / 2)}" rgba="{c}" {STATIC}/>'
        )
    g.append(
        f'<geom type="box" pos="{_f(0, d / 2 - t / 2, h / 2)}" size="{_f(w / 2 - t, t / 2, h / 2)}" rgba="{c}" {STATIC}/>'
    )
    g.append(
        f'<geom name="{n}_top" type="box" pos="{_f(0, 0, h - t / 2)}" size="{_f(w / 2, d / 2, t / 2)}" rgba="{c}" {STATIC}/>'
    )
    g.append("</body>")
    iw = w / 2 - t - 0.003  # drawer box: half width, its back, the top of its sides
    back = d / 2 - t - 0.004
    side_h = (h - t) * 0.7
    front_top = h - t - 0.003
    dc, fc = _rgba(fx.get("drawer_color", "tan")), _rgba(fx.get("front_color", fx.get("color", "darkgrey")))
    hx_, hy_, hz_ = HANDLE_BAR
    _, by, bz = cabinet_handle_local(fx)
    g += [
        f'<body name="drawer_{n}" pos="{_f(x, y, 0)}" euler="0 0 {yaw:g}">',
        f'<joint name="dj_{n}" type="slide" axis="0 -1 0" range="0 {float(fx.get("travel", 0.1)):g}" damping="4" frictionloss="0.3" armature="0.05"/>',
        f'<geom type="box" pos="{_f(0, (back - d / 2 + 0.008) / 2, 0.003)}" size="{_f(iw, (back + d / 2 - 0.008) / 2, 0.003)}" rgba="{dc}" density="300" {DRAWER}/>',
        f'<geom type="box" pos="{_f(0, back - 0.003, side_h / 2)}" size="{_f(iw, 0.003, side_h / 2)}" rgba="{dc}" density="300" {DRAWER}/>',
    ]
    for side in (-1, 1):
        g.append(
            f'<geom type="box" pos="{_f(side * (iw - 0.003), (back - d / 2 + 0.008) / 2, side_h / 2)}" '
            f'size="{_f(0.003, (back + d / 2 - 0.008) / 2, side_h / 2)}" rgba="{dc}" density="300" {DRAWER}/>'
        )
        g.append(
            f'<geom type="box" pos="{_f(side * (hx_ - 0.006), -d / 2 - HANDLE_GAP / 2, bz)}" size="{_f(0.004, HANDLE_GAP / 2, 0.005)}" '
            f'rgba="{metal}" density="300" {DRAWER}/>'
        )
    g += [
        f'<geom name="{n}_front" type="box" pos="{_f(0, -d / 2 + 0.004, (front_top + 0.004) / 2)}" '
        f'size="{_f(w / 2 - t - 0.002, 0.004, (front_top - 0.004) / 2)}" rgba="{fc}" density="300" {DRAWER}/>',
        f'<geom name="{n}_handle" type="box" pos="{_f(0, by, bz)}" size="{_f(hx_, hy_, hz_)}" rgba="{metal}" density="300" {DRAWER}/>',
        "</body>",
    ]
    return "".join(g)


def _drawer_xml(n: str, cx: float, cy: float, col: str) -> str:
    c = _rgba(col)
    cab = [f'<body name="fx_{n}" pos="{_f(cx, cy, 0)}">']
    for sx in (-1, 1):
        cab.append(
            f'<geom type="box" pos="{_f(sx * 0.075, 0.005, 0.045)}" size="0.005 0.075 0.045" rgba="{c}" {STATIC}/>'
        )
    cab.append(f'<geom type="box" pos="0 0.075 0.045" size="0.08 0.005 0.045" rgba="{c}" {STATIC}/>')
    cab.append(f'<geom name="{n}_top" type="box" pos="0 0.005 0.085" size="0.08 0.075 0.005" rgba="{c}" {STATIC}/>')
    cab.append("</body>")
    d = _rgba("tan")
    dr = [
        f'<body name="drawer_{n}" pos="{_f(cx, cy, 0)}">',
        f'<joint name="dj_{n}" type="slide" axis="0 -1 0" range="0 {DR_TRAVEL}" damping="4" frictionloss="0.3" armature="0.05"/>',
        f'<geom type="box" pos="0 0 0.003" size="0.065 0.065 0.003" rgba="{d}" density="300" {DRAWER}/>',
    ]
    for sx in (-1, 1):
        dr.append(
            f'<geom type="box" pos="{_f(sx * 0.062, 0, 0.031)}" size="0.003 0.065 0.025" rgba="{d}" density="300" {DRAWER}/>'
        )
    dr.append(f'<geom type="box" pos="0 0.062 0.031" size="0.065 0.003 0.025" rgba="{d}" density="300" {DRAWER}/>')
    dr.append(
        f'<geom name="{n}_front" type="box" pos="0 -0.068 0.04" size="0.072 0.004 0.036" rgba="{c}" density="300" {DRAWER}/>'
    )
    for sx in (-1, 1):
        dr.append(
            f'<geom type="box" pos="{_f(sx * 0.03, -0.092, DR_HANDLE[1])}" size="0.004 0.02 0.004" rgba="{_rgba("silver")}" density="300" {DRAWER}/>'
        )
    dr.append(
        f'<geom name="{n}_handle" type="box" pos="{_f(0, DR_HANDLE[0], DR_HANDLE[1])}" size="0.04 0.005 0.006" rgba="{_rgba("silver")}" density="300" {DRAWER}/>'
    )
    dr.append("</body>")
    return "".join(cab + dr)


def _figure_xml(n: str, x: float, y: float, z0: float, yaw: float) -> str:
    """A person-like figure (mannequin) lying on its back along local +x (head at +x)."""
    shirt, skin, pants = "0.30 0.45 0.62 1", "0.92 0.78 0.64 1", "0.25 0.25 0.32 1"
    g = [
        f'<body name="fx_{n}" pos="{_f(x, y, z0)}" euler="0 0 {yaw}">',
        f'<geom name="{n}_torso" type="capsule" fromto="0 0 0.034 0.1 0 0.034" size="0.034" rgba="{shirt}" {STATIC}/>',
        f'<geom name="{n}_neck" type="capsule" fromto="0.12 0 0.03 0.14 0 0.03" size="0.014" rgba="{skin}" {STATIC}/>',
        f'<geom name="{n}_head" type="sphere" pos="0.172 0 0.032" size="0.032" rgba="{skin}" {STATIC}/>',
    ]
    for s in (-1, 1):
        g.append(
            f'<geom type="capsule" fromto="{_f(-0.02, s * 0.018, 0.02, -0.17, s * 0.024, 0.02)}" size="0.02" rgba="{pants}" {STATIC}/>'
        )
        g.append(
            f'<geom type="capsule" fromto="{_f(0.1, s * 0.048, 0.016, -0.01, s * 0.062, 0.016)}" size="0.015" rgba="{shirt}" {STATIC}/>'
        )
    return "".join(g) + "</body>"


def _fixture_xy(fx: dict, grid: dict | None) -> tuple[float, float]:
    if "cell" in fx and grid:
        return _cell_xy(grid, *fx["cell"])
    return float(fx["pos"][0]), float(fx["pos"][1])


def _cell_xy(grid: dict, r: int, c: int) -> tuple[float, float]:
    x0, y0 = grid["origin"]
    cs = grid["cell"]
    return x0 + c * cs, y0 - r * cs


def _look(pos, target) -> str:
    p, t = np.asarray(pos, float), np.asarray(target, float)
    zc = p - t
    zc /= np.linalg.norm(zc)
    xc = np.cross([0, 0, 1.0], zc)
    xc /= np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    return f'pos="{_f(*p)}" xyaxes="{_f(*xc, *yc)}"'


def build_xml(sc: dict) -> str:
    grid = sc.get("grid")
    wb: list[str] = []
    wb.append(f'<geom name="floor" type="plane" pos="0 0 {FLOOR_Z}" size="2 2 0.1" material="floor" {STATIC}/>')
    wb.append(
        f'<geom name="table" type="box" pos="0 0 {FLOOR_Z / 2}" size="{_f(TABLE_HX, TABLE_HY, -FLOOR_Z / 2)}" material="wood" {STATIC}/>'
    )
    if grid:
        for r in range(grid["rows"]):
            for c in range(grid["cols"]):
                x, y = _cell_xy(grid, r, c)
                h = grid["cell"] / 2 - 0.004
                wb.append(
                    f'<geom type="box" pos="{_f(x, y, 0.0005)}" size="{_f(h, h, 0.0005)}" rgba="0.90 0.87 0.80 1" {VISUAL}/>'
                )
    for fx in sc.get("fixtures", []):
        wb.append(_fixture_xml(fx, grid))
    for o in sc.get("objects", []):
        wb.append(_obj_xml(_resolved_obj(o, grid)))
    hx, hy, hz = HAND_HOME
    fcol = "0.25 0.25 0.28 1"
    fr = 'friction="1.5 0.02 0.002" condim="4" solref="0.01 1"'
    wb.append(f'<body name="mocap" mocap="true" pos="{_f(hx, hy, hz)}"/>')
    wb.append(
        f'<body name="hand" pos="{_f(hx, hy, hz)}" gravcomp="1"><freejoint name="hand_free"/>'
        f'<geom name="palm" type="box" pos="0 0 0.074" size="0.022 0.065 0.012" rgba="0.18 0.18 0.2 1" mass="0.25" {MOVING}/>'
        f'<geom name="wrist" type="cylinder" pos="0 0 0.16" size="0.02 0.075" rgba="0.55 0.56 0.6 1" mass="0.05" {VISUAL}/>'
        f'<site name="tcp" pos="0 0 0" size="0.004" rgba="1 0 0 0"/>'
        + (
            f'<camera name="wrist" pos="{_f(*WRIST_CAM_POS)}" fovy="{WRIST_CAM_FOVY}"/>'
            if sc.get("wrist_camera")
            else ""
        )
        + f'<body name="finger_l" gravcomp="1"><joint name="fl" type="slide" axis="0 1 0" range="0 {FINGER_OPEN}" damping="30" armature="0.01"/>'
        f'<geom name="finger_l" type="box" pos="0 0.006 0.026" size="0.012 0.006 0.036" rgba="{fcol}" mass="0.03" {fr} {MOVING}/></body>'
        f'<body name="finger_r" gravcomp="1"><joint name="fr" type="slide" axis="0 -1 0" range="0 {FINGER_OPEN}" damping="30" armature="0.01"/>'
        f'<geom name="finger_r" type="box" pos="0 -0.006 0.026" size="0.012 0.006 0.036" rgba="{fcol}" mass="0.03" {fr} {MOVING}/></body>'
        f'</body>'
    )
    cams = {
        "front": _look([0, -0.52, 0.78], [0, 0.03, 0.0]),
        "top": _look([0, -0.001, 1.05], [0, 0, 0]),
        "wide": _look([0, -1.25, 1.15], [0, 0.0, -0.1]),
        "side": _look([0.85, -0.35, 0.45], [0, 0.02, 0]),
    }
    wb += [f'<camera name="{k}" {v} fovy="45"/>' for k, v in cams.items()]
    return f"""<mujoco model="robouse-tabletop">
  <option timestep="0.002" cone="elliptic" impratio="10" integrator="implicitfast"><flag multiccd="enable"/></option>
  <compiler angle="degree"/>
  <visual><global offwidth="640" offheight="640"/><quality shadowsize="4096"/><map shadowclip="0.8"/><headlight ambient="0.35 0.35 0.35" diffuse="0.45 0.45 0.45"/></visual>
  <asset>
    <texture name="tfloor" type="2d" builtin="checker" rgb1="0.82 0.84 0.86" rgb2="0.74 0.76 0.78" width="256" height="256"/>
    <material name="floor" texture="tfloor" texrepeat="6 6"/>
    <material name="wood" rgba="0.72 0.58 0.42 1"/>
  </asset>
  <worldbody>
    <light pos="0.3 -0.4 1.4" dir="-0.2 0.3 -1" diffuse="0.55 0.55 0.55" castshadow="true"/>
    {chr(10).join(wb)}
  </worldbody>
  <contact><exclude body1="finger_l" body2="finger_r"/></contact>
  <equality><weld body1="mocap" body2="hand" solref="0.01 1"/></equality>
  <actuator>
    <position name="a_fl" joint="fl" kp="300" ctrlrange="0 {FINGER_OPEN}" forcerange="-15 15"/>
    <position name="a_fr" joint="fr" kp="300" ctrlrange="0 {FINGER_OPEN}" forcerange="-15 15"/>
  </actuator>
</mujoco>"""


def _resolved_obj(o: dict, grid: dict | None) -> dict:
    if "cell" in o and grid:
        o = dict(o)
        o["pos"] = list(_cell_xy(grid, *o["cell"]))
    return o


# --------------------------------------------------------------------------------------------------
# Backend
