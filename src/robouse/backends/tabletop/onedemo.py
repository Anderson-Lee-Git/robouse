"""The one-demo suite (suite "one-demo"): in-context imitation from one demonstration, on another object.

Each task's instruction carries one demonstration of a skill on a demo object: the `robo` commands of an episode in which
this module's reference strategy did it, and frames of that episode, which the episode server renders into the agent's
workspace at the start. The agent then does the same skill on a different object of the same family. The part the
gripper touches (a knob, a cap, a handle) is the same on every object of a family; the object's size, shape and pose are
not, so the demonstration's numbers do not carry over to the agent's object, while its strategy does.

Families (the skill, then the contact):
  open-box        swing a hinged lid open by its ball knob, along the circle about the hinge, until it rests open
  lift-lid        lift a lid off its container by its knob, straight up past its plug, and set it down on a pad
  upright-bottle  stand a lying bottle up by its ball cap, swinging the cap about the base's bottom edge
  open-drawer     hook the closed fingers behind a drawer's handle bar and pull the drawer out along its slide

The scenes run on the ordinary tabletop backend. FAMILIES holds each family's demo scene and its target scenes; the
generator (adapters/one-demo/generate.py) runs the strategy on the demo scene, records its trace and frames, and writes
each target as a task. `oracle_main` (python -m robouse.oracle --backend tabletop_onedemo --env ID) runs the same strategy
on a task's scene through the robo socket, reading only the public observation.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from .scene import HAND_HI, HAND_LO, LID_KNOB, LID_SLAB_T

# --------------------------------------------------------------------------------------------------
# The robot, through the robo protocol
# --------------------------------------------------------------------------------------------------


class Finished(Exception):
    """The episode ended (a reply carries `episode`)."""


class Bot:
    """Sends robo requests with `send` (the socket by default, or an in-process episode's `handle`). `frame(label)` marks
    a moment the generator keeps as a demonstration frame; elsewhere it does nothing."""

    def __init__(self, send: Callable[[dict], dict] | None = None, on_frame: Callable[[str], None] | None = None):
        if send is None:
            from robouse.agent_cli import _send

            send = _send
        self._send: Callable[[dict], dict] = send
        self._on_frame = on_frame

    def req(self, r: dict) -> dict:
        resp = self._send(r)
        if not resp.get("ok"):
            if "finished" in str(resp.get("error", "")):
                raise Finished()
            raise RuntimeError(f"{r.get('op')}: {resp.get('error')}")
        res = resp.get("result") or {}
        if isinstance(res, dict) and "episode" in res and r.get("op") not in ("done", "give_up"):
            raise Finished()
        return res

    def obs(self) -> dict:
        return self.req({"op": "observe"})["state"]

    def move(self, p, grip: float | None = None, tol: float = 0.004, max_steps: int = 150) -> dict:
        p = [round(float(np.clip(p[i], HAND_LO[i], HAND_HI[i])), 4) for i in range(3)]
        return self.req({"op": "move_to", "pos": p, "grip": grip, "max_steps": max_steps, "tol": tol})

    def grip(self, value: float, steps: int = 15) -> dict:
        return self.req({"op": "grip", "value": float(value), "steps": int(steps)})

    def frame(self, label: str) -> None:
        if self._on_frame:
            self._on_frame(label)

    def done(self, text: str) -> None:
        self.req({"op": "done", "text": text})


OPEN = -0.3  # a partly open gripper: a 6.5 cm gap, enough to straddle a knob, a cap or a handle


def _arc(p0: np.ndarray, pivot: np.ndarray, deg: float) -> np.ndarray:
    """Point p0 turned by `deg` about the horizontal y axis through `pivot`, in the sense that lifts the side of p0 that
    lies away from the pivot (x away from the pivot rises toward +z)."""
    v = p0 - pivot
    s = 1.0 if v[0] >= 0 else -1.0
    a = math.radians(deg)
    x = v[0] * math.cos(a) - s * v[2] * math.sin(a)
    z = s * v[0] * math.sin(a) + v[2] * math.cos(a)
    return pivot + np.array([x, v[1], z])


# --------------------------------------------------------------------------------------------------
# Reference strategies: one per family, reading only the public observation
# --------------------------------------------------------------------------------------------------


def open_box(bot: Bot, name: str = "box") -> None:
    """Pinch the ball knob, swing it along its circle about the hinge line until the lid is past upright, let go so the
    lid falls onto its stop, and slide the open fingers off the knob, away from the lid."""
    f = bot.obs()["fixtures"][name]
    knob, hinge = np.array(f["knob_pos"]), np.array(f["hinge_pos"])
    bot.move(knob + [0, 0, 0.07], OPEN, tol=0.006)
    bot.frame("above the knob, fingers part open")
    bot.move(knob, OPEN, tol=0.003)
    bot.grip(1.0, 15)
    bot.frame("knob pinched between the fingers")
    for deg in range(15, 106, 15):
        bot.move(_arc(knob, hinge, deg), 1.0, tol=0.004)
        if deg == 60:
            bot.frame("lid swung up along the circle about the hinge")
    bot.frame("lid past upright")
    bot.grip(OPEN, 12)
    away = -1.0 if f["hinge_side"] == "left" else 1.0  # outward, over the hinge side
    h = np.array(bot.obs()["hand_pos"])
    bot.move(h + [away * 0.05, 0, 0], OPEN, tol=0.006)
    bot.move(h + [away * 0.05, 0, 0.08], OPEN, tol=0.01)
    bot.frame("released: the lid rests open on its stop")
    bot.done("lid open")


def lift_lid(bot: Bot, name: str = "lid", pad: str = "rest") -> None:
    """Pinch the knob, lift the lid straight up until its plug clears the rim, carry it over the pad, set it down flat
    and let go."""
    st = bot.obs()
    o = st["objects"][name]
    knob = np.array(o["knob_pos"])
    target = np.array(st["fixtures"][pad]["pos"])
    bot.move(knob + [0, 0, 0.07], OPEN, tol=0.006)
    bot.frame("above the knob, fingers part open")
    bot.move(knob, OPEN, tol=0.003)
    bot.grip(1.0, 15)
    bot.frame("knob pinched between the fingers")
    lift = o["plug_depth"] + 0.03
    bot.move(knob + [0, 0, lift], 1.0, tol=0.004)
    bot.frame("lid lifted straight up, plug clear of the rim")
    st = bot.obs()
    o, hand = st["objects"][name], np.array(st["hand_pos"])
    grasp = hand - np.array(o["pos"])  # where the hand holds the lid, from the lid's centre
    bottom = o["half_height"]
    over = np.array([target[0], target[1], hand[2]]) + [grasp[0], grasp[1], 0]
    bot.move(over, 1.0, tol=0.004)
    bot.frame("carried over the pad")
    bot.move([over[0], over[1], target[2] + bottom + grasp[2] + 0.004], 1.0, tol=0.003)
    bot.grip(OPEN, 12)
    bot.frame("set down on the pad and let go")
    h = np.array(bot.obs()["hand_pos"])
    bot.move(h + [0, 0, 0.08], OPEN, tol=0.01)
    bot.done("lid on the pad")


def upright_bottle(bot: Bot, name: str = "bottle") -> None:
    """Pinch the ball cap and swing it about the bottom edge of the base (the bottle pivots there) up to vertical, so the
    bottle stands on its base, then let go and lift the open fingers off the cap."""
    o = bot.obs()["objects"][name]
    cap, base = np.array(o["cap_pos"]), np.array(o["base_pos"])
    pivot = np.array([base[0], base[1], 0.0])
    bot.move(cap + [0, 0, 0.07], OPEN, tol=0.006)
    bot.frame("above the cap, fingers part open")
    bot.move(cap, OPEN, tol=0.003)
    bot.grip(1.0, 15)
    bot.frame("cap pinched between the fingers")
    for deg in range(10, 91, 10):
        bot.move(_arc(cap, pivot, deg), 1.0, tol=0.004)
        if deg == 40:
            bot.frame("cap swung up along the circle about the base's edge")
    bot.frame("bottle upright")
    bot.grip(OPEN, 12)
    h = np.array(bot.obs()["hand_pos"])
    bot.move(h + [0, 0, 0.07], OPEN, tol=0.01)
    bot.frame("released: the bottle stands on its base")
    bot.done("bottle standing")


def open_drawer(bot: Bot, name: str = "cabinet") -> None:
    """Lower the closed fingers into the gap between the handle bar and the drawer's face, pull along the drawer's slide
    to its stop, and lift the fingers out."""
    f = bot.obs()["fixtures"][name]
    u = np.array(f["pull_direction"])
    bar = np.array(f["handle_pos"])
    hook = bar - u * (0.005 + f["handle_gap"] / 2)  # mid-gap, behind the bar
    bot.move(hook + [0, 0, 0.08], 1.0, tol=0.006)
    bot.frame("closed fingers above the gap behind the handle")
    bot.move(hook, 1.0, tol=0.003)
    bot.frame("fingers down in the gap")
    pulled = hook + u * (f["max_opening"] + 0.01)
    bot.move(pulled, 1.0, tol=0.004)
    bot.frame("drawer pulled out to its stop")
    bot.move(pulled + [0, 0, 0.08], 1.0, tol=0.01)
    bot.frame("fingers lifted out of the handle")
    bot.done("drawer open")


STRATEGIES: dict[str, Callable[[Bot], None]] = {
    "open-box": open_box,
    "lift-lid": lift_lid,
    "upright-bottle": upright_bottle,
    "open-drawer": open_drawer,
}


# --------------------------------------------------------------------------------------------------
# Scenes: per family, the demonstration's object and the target objects
# --------------------------------------------------------------------------------------------------

WALL = 0.006  # wall thickness of trays and bowls (scene.py)
BOTTLE_KG = 0.8  # full bottles: the cap pinch cannot lift one clear of the table, but can tip it up about its base


def _box(size, hinge: str, pos, color: str, lid: str) -> dict:
    return {
        "name": "box",
        "kind": "hinged_box",
        "pos": list(pos),
        "size": list(size),
        "hinge": hinge,
        "color": color,
        "lid_color": lid,
    }


def _lidded(shape: str, opening, height: float, pos, pad, color: str, lid: str, plug: float = 0.012) -> dict:
    """A container (a tray, or an octagonal bowl for a round lid) with its lid on, and the grey pad the lid goes to.
    The lid's slab covers the walls; its plug fits inside the opening with 4 mm to spare."""
    if shape == "round":
        r_in = float(opening)
        slab = (r_in + WALL) / math.cos(math.pi / 8) + 0.003  # past the octagon's corners
        container = {"name": "container", "kind": "bowl", "pos": list(pos), "radius": r_in, "height": height}
        lid_obj = {"shape": "round", "size": [round(slab, 4)], "plug_inset": round(slab - (r_in - 0.004), 4)}
    else:
        hx, hy = opening
        container = {"name": "container", "kind": "tray", "pos": list(pos), "size": [hx, hy], "height": height}
        lid_obj = {"shape": "box", "size": [hx + WALL + 0.004, hy + WALL + 0.004], "plug_inset": WALL + 0.008}
    total = plug + LID_SLAB_T + LID_KNOB[1]
    return {
        "objects": [
            {
                "name": "lid",
                "kind": "lid",
                "color": lid,
                "pos": list(pos),
                "z": round(height + total / 2 - plug, 4),
                "plug": plug,
                **lid_obj,
            }
        ],
        "fixtures": [
            {**container, "color": color},
            {"name": "rest", "kind": "pad", "pos": list(pad), "size": [0.05, 0.05], "color": "grey"},
        ],
    }


def _bottle(body, neck, lying: str, pos, color: str, cap: str = "white") -> dict:
    return {
        "name": "bottle",
        "kind": "bottle",
        "pos": list(pos),
        "body": list(body),
        "neck": list(neck),
        "lying": lying,
        "mass": BOTTLE_KG,
        "color": color,
        "cap_color": cap,
    }


def _cabinet(size, facing: str, travel: float, pos, color: str) -> dict:
    return {
        "name": "cabinet",
        "kind": "cabinet",
        "pos": list(pos),
        "size": list(size),
        "facing": facing,
        "travel": travel,
        "color": color,
    }


def _fixtures(*f: dict) -> dict:
    return {"objects": [], "fixtures": list(f)}


def _objects(*o: dict) -> dict:
    return {"objects": list(o), "fixtures": []}


# Each family: the instruction's words for it, its goal predicates, its step budget, the observation field of the part the
# gripper touches (`contact`), the demonstration's scene (and the angle its frames are seen from, `view_azimuth`), and
# the targets (task id -> scene, and how the object differs from the demonstration's, for the docs and metadata).
FAMILIES: dict[str, dict] = {
    "open-box": {
        "title": "Open the box",
        "noun": "box",
        "goal": "A box with a hinged lid stands on the table. Open it: swing the lid open on its hinge so that it stays open "
        "by itself.",
        "success": "the lid is open at least 100 degrees (`lid_angle_deg`; it stops at 110) and the gripper is not "
        "touching it",
        "fields": "`fixtures.box`: `pos` (the centre of its base), `size` (outer x, y and height, closed lid included), "
        "`hinge_side` (`left`: the hinge runs along the box's top edge at smaller x, so the lid swings up and over to "
        "the left; `right`: the opposite), `hinge_pos` (the middle of the hinge line, which runs along y), "
        "`lid_angle_deg` (0 = shut), `max_angle_deg`, `knob_pos` (the centre of the ball knob on the lid, where it is "
        "now), `knob_diameter` and `gripper_touching` (whether the gripper touches the lid or its knob now; `holding` "
        "lists free objects only).",
        "goals": [{"type": "lid_open", "box": "box", "min_deg": 100}],
        "max_steps": 900,
        "contact": ["fixtures", "box", "knob_pos"],
        "demo": _fixtures(_box([0.14, 0.10, 0.06], "left", [0.08, 0.04], "tan", "brown")),
        "demo_is": "a 14 x 10 x 6 cm box hinged on the left",
        "view_azimuth": 90.0,
        "targets": {
            "one-demo-box-mirrored": (
                _fixtures(_box([0.12, 0.10, 0.06], "right", [-0.06, 0.02], "teal", "darkgrey")),
                "hinge on the right, so the lid swings the other way; 2 cm shorter",
            ),
            "one-demo-box-tall": (
                _fixtures(_box([0.10, 0.12, 0.13], "left", [0.10, 0.10], "white", "blue")),
                "a tall chest: hinge 7 cm higher, a 4 cm shorter lid, so a smaller circle",
            ),
            "one-demo-box-wide": (
                _fixtures(_box([0.22, 0.12, 0.045], "right", [0.02, -0.06], "grey", "red")),
                "a wide flat case with the hinge on the right: a lid 8 cm longer, swinging the other way",
            ),
            "one-demo-box-small": (
                _fixtures(_box([0.08, 0.07, 0.045], "left", [-0.16, -0.12], "yellow", "green")),
                "a small box near the front left corner: a lid 6 cm shorter, a lower hinge",
            ),
        },
    },
    "lift-lid": {
        "title": "Take the lid off",
        "noun": "container",
        "goal": "A container with a lid on it stands on the table. Take the lid off and put it down on the grey pad.",
        "success": "the lid's centre is over the grey pad (`fixtures.rest`), the lid rests on the table there, tilted "
        "less than 15 degrees, and the gripper has let go of it",
        "fields": "`objects.lid`: `shape` (`box` or `round`), `pos` (its centre), `size` (outer x, y and the height "
        "from the bottom of its plug to the top of its knob), `knob_pos` (the centre of the knob on top, where it is "
        "now), `knob_diameter`, `plug_depth` (how far the plug under the lid reaches down into the container), "
        "`half_height`, `tilt_deg`. `fixtures.container` is the container (a tray or an octagonal bowl, with `rim_z`), "
        "and `fixtures.rest` is the grey pad.",
        "goals": [{"type": "on_pad", "obj": "lid", "pad": "rest", "max_tilt": 15}],
        "max_steps": 800,
        "contact": ["objects", "lid", "knob_pos"],
        "demo": _lidded("box", [0.05, 0.05], 0.06, [0.10, 0.06], [-0.14, -0.08], "blue", "red"),
        "demo_is": "a square tin 6 cm tall, its pad to the front left",
        "view_azimuth": 90.0,
        "targets": {
            "one-demo-lid-pot": (
                _lidded("round", 0.065, 0.07, [-0.10, 0.08], [0.15, -0.10], "white", "orange"),
                "a round pot with a round lid; the pad lies the other way",
            ),
            "one-demo-lid-jar": (
                _lidded("round", 0.04, 0.13, [0.14, 0.12], [0.12, -0.14], "silver", "purple", plug=0.025),
                "a narrow jar twice as tall, with a deeper plug; the pad straight in front of it",
            ),
            "one-demo-lid-tin": (
                _lidded("box", [0.09, 0.045], 0.045, [-0.06, 0.12], [0.16, -0.10], "green", "yellow"),
                "a long, low tin; the pad to the front right",
            ),
            "one-demo-lid-dish": (
                _lidded("box", [0.065, 0.065], 0.03, [0.12, -0.08], [-0.12, 0.10], "cyan", "brown"),
                "a wide, shallow dish near the front; the pad behind it to the left",
            ),
        },
    },
    "upright-bottle": {
        "title": "Stand the bottle up",
        "noun": "bottle",
        "goal": f"A full bottle ({BOTTLE_KG} kg) lies on its side on the table. Stand it up on its base.",
        "success": "the bottle stands on its base on the table, tilted less than 10 degrees from upright, at rest, and "
        "the gripper has let go of it",
        "fields": "`objects.bottle`: `pos` (its centre), `size` (body diameter, body diameter, and the length from the "
        "base to the top of the cap), `axis` (unit vector from the base toward the cap), `base_pos` (the centre of the "
        "base), `cap_pos` (the centre of the ball cap), `body_diameter`, `neck_diameter`, `cap_diameter`, "
        "`half_height`, `tilt_deg` (90 lying, 0 upright). Nearly all of its mass is in the body.",
        "goals": [{"type": "standing", "obj": "bottle", "max_tilt": 10}],
        "max_steps": 900,
        "contact": ["objects", "bottle", "cap_pos"],
        "demo": _objects(_bottle([0.03, 0.11], [0.008, 0.035], "+x", [0.0, 0.05], "green")),
        "demo_is": "a 6 cm wide bottle with an 11 cm body, cap toward +x",
        "view_azimuth": 90.0,
        "targets": {
            "one-demo-bottle-mirrored": (
                _objects(_bottle([0.032, 0.10], [0.008, 0.035], "-x", [0.05, -0.05], "blue")),
                "lies the other way round (cap toward -x)",
            ),
            "one-demo-bottle-tall": (
                _objects(_bottle([0.03, 0.15], [0.008, 0.04], "+x", [-0.06, 0.10], "brown", "gold")),
                "4 cm longer body: a larger circle",
            ),
            "one-demo-bottle-jug": (
                _objects(_bottle([0.045, 0.09], [0.008, 0.03], "-x", [0.10, 0.12], "orange")),
                "a short, wide jug lying the other way round",
            ),
            "one-demo-bottle-long-neck": (
                _objects(_bottle([0.028, 0.10], [0.008, 0.10], "+x", [-0.10, -0.12], "purple", "silver")),
                "a neck three times as long (a larger circle), near the front left corner",
            ),
        },
    },
    "open-drawer": {
        "title": "Open the drawer",
        "noun": "cabinet",
        "goal": "A cabinet with one drawer stands on the table. Pull the drawer open.",
        "success": "the drawer is pulled out at least 75% of its travel (`max_opening`) and the gripper is not touching "
        "it",
        "fields": "`fixtures.cabinet`: `pos` (its centre), `size` (width across its face, depth, height), `facing` "
        "(`front`, `left` or `right`: the side the drawer comes out of), `pull_direction` (unit vector the drawer "
        "slides out along), `opening` (metres pulled out, 0 = shut), `max_opening` (its travel), `handle_pos` (the "
        "centre of the handle bar, where it is now), `handle_length`, `handle_gap` (the clear gap between the bar and "
        "the drawer's face) and `gripper_touching` (whether the gripper touches the drawer or its handle now).",
        "goals": [{"type": "drawer", "drawer": "cabinet", "min_open": None, "released": True}],
        "max_steps": 600,
        "contact": ["fixtures", "cabinet", "handle_pos"],
        "demo": _fixtures(_cabinet([0.18, 0.16, 0.10], "front", 0.10, [0.10, 0.12], "darkgrey")),
        "demo_is": "a cabinet facing the front with 10 cm of travel",
        "view_azimuth": 40.0,
        "targets": {
            "one-demo-drawer-left": (
                _fixtures(_cabinet([0.16, 0.16, 0.10], "left", 0.10, [-0.06, 0.10], "teal")),
                "faces left: the drawer comes out toward -x",
            ),
            "one-demo-drawer-right": (
                _fixtures(_cabinet([0.14, 0.18, 0.14], "right", 0.12, [0.0, 0.05], "brown")),
                "a taller cabinet facing right, with a higher handle and 2 cm more travel",
            ),
            "one-demo-drawer-deep": (
                _fixtures(_cabinet([0.24, 0.20, 0.07], "front", 0.16, [-0.06, 0.08], "grey")),
                "faces the front like the demonstration's, but low, with a lower handle and 6 cm more travel",
            ),
            "one-demo-drawer-small": (
                _fixtures(_cabinet([0.12, 0.12, 0.08], "left", 0.07, [0.18, -0.10], "red")),
                "a small cabinet facing left, with 3 cm less travel",
            ),
        },
    },
}


def goals_for(family: str, scene: dict) -> list[dict]:
    """The family's goal predicates for one scene (a drawer's threshold is 75% of that drawer's travel)."""
    out = []
    for g in FAMILIES[family]["goals"]:
        g = dict(g)
        if g["type"] == "drawer":
            travel = next(f for f in scene["fixtures"] if f["name"] == g["drawer"])["travel"]
            g["min_open"] = round(0.75 * travel, 4)
        out.append(g)
    return out


def scenario(family: str, tid: str, scene: dict) -> dict:
    """A scene of `family` as a tabletop scenario: its objects, fixtures, goals and step budget."""
    fam = FAMILIES[family]
    return {
        "id": tid,
        "title": fam["title"],
        "family": family,
        "objects": scene["objects"],
        "fixtures": scene["fixtures"],
        "goals": goals_for(family, scene),
        "max_steps": fam["max_steps"],
    }


ONE_DEMO_TASKS: dict[str, dict] = {
    tid: {**scenario(family, tid, scene), "differs": differs}
    for family, fam in FAMILIES.items()
    for tid, (scene, differs) in fam["targets"].items()
}


def run_strategy(family: str, send: Callable[[dict], dict] | None = None, on_frame=None) -> None:
    """Run `family`'s reference strategy until the episode ends."""
    try:
        STRATEGIES[family](Bot(send, on_frame))
    except Finished:
        return


def oracle_main(env: str) -> None:
    run_strategy(ONE_DEMO_TASKS[env]["family"])
