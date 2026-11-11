"""Physical-state trace of a RoboCasa scenario episode (format `robouse-state-trace` 1.1.0).

A researcher-only record of what physically happened, written by the simulation worker into the episode's run folder
as `state-trace.jsonl.gz` (gzip, one JSON object per line). It is never part of an observation, a reply or anything a
policy can request: practice and development episodes do not write it, and run folders are denied to policies.

Lines, in order:
  header   {"kind": "header", "format", "version", "scenario", "control", "stride", "liquid_every", "precision",
            "objects": {name: {"body", "joints"?: {joint: "hinge"|"slide"}, "interior"?: true}},
            "fixtures": {key: {"type", "class", "joints": {joint: "hinge"|"slide"}, "parts", "box", "powered"}},
            "source": {"kind": "live"} (a replay adds its fidelity check here)}
  state    {"kind": "state", "step", "phase", "t", "digest", "robot", "objects", "fixtures", "contacts", "welds",
            "liquid"?}
  error    {"kind": "error", "step", "error"}: tracing stopped here; the trace is incomplete
  end      {"kind": "end", "steps", "records", "goal"}: the trace is complete

`phase` is `reset` (after reset settling, step 0), `control` (after each control of the episode), `settle` (the still
steps after `robo done`) or `final` (the state the episode was judged on, after the last step). A state is recorded
after every control (`stride` 1), or every `stride` controls and whenever the discrete state changes (a grasp, a
contact pair, a support, a fixture's power); `reset` and `final` are always recorded. Liquid counts are taken every
`liquid_every` controls and at reset and final.

State fields (positions in m, world frame; quaternions w, x, y, z; joints in rad or m; values rounded to `precision`
decimals, 1 um / 1e-6 rad):
  robot     {"eef": [x, y, z], "grip": opening 0..1, "grasped": [objects RoboCasa counts as grasped],
            "inside"?: {object: depth m} (1.1.0) for each object with an interior cylinder (its `reg_int` region) that
            a colliding geom of the moving arm or gripper reaches into: how far below the top of that interior (a jar's
            rim) the lowest such robot point is. Absent when the robot is in no interior}
  objects   {name: {"pos", "quat", "box": [[x, y, z] low, [x, y, z] high] world bounding box of its colliding geoms
            (0.1 mm), "on": [what supports it from below], "in": {fixture: fraction of that box inside the fixture's
            fixed body box}, "joints"?: {joint: value}, "speeds"?: {joint: rad/s or m/s} (1.1.0: the hinge and slide
            joints inside an object, e.g. an appliance's lever or its driven blades, named without the object's
            prefix)}}
  fixtures  {key: {"joints": {joint: value}, "parts": {part: [[x, y, z] low, [x, y, z] high] world box of a moving
            part, 0.1 mm}, "on": powered and running, "burners": {loc: lit}, "state": RoboCasa's own fixture state}}
  contacts  [[a, b], ...] active contact pairs, each side an object, a scenario fixture key (its fixed body), a
            moving part of one `<key>/<part>` (the bodies a fixture joint moves: `toaster_oven/door`,
            `toaster_oven/rack0`), since 1.1.0 a jointed part of an object `<object>/<part>` (the bodies one of its
            hinge or slide joints moves: `jar/blade_spin`, `blender/switch`), `robot:gripper`, `robot:arm`, `robot:base`, `floor`, `kitchen:<fixture>` or
            `world`; pairs without an object or a moving robot part, and pairs within one fixture, are left out
  welds     {name: active} for named equality constraints other than the parked-base lock (breakable attachments)
  liquid    {"counts": {region: particles}, "volumes_ml": {region: ml}}
  digest    the first 16 hex digits of SHA-256 over qpos and qvel: equal digests, equal physical state

Recording only reads simulator data that each control has already computed; it never calls mj_forward, sets state or
draws random numbers, so a traced episode's dynamics are bit-identical to an untraced one (tests prove it).

This module is loaded by path inside the simulation worker (numpy only) and imported by the robouse package to read
a trace (`read`).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os

import numpy as np

FORMAT = "robouse-state-trace"
VERSION = "1.1.0"  # 1.1.0: object joints and speeds, `<object>/<part>` contact labels, robot `inside` an interior
FILENAME = "state-trace.jsonl.gz"
PRECISION = 6
ROBOT_PARTS = (
    ("gripper0_", "robot:gripper"),
    ("mobilebase0_", "robot:base"),
    ("mount0_", "robot:base"),
    ("robot0_", "robot:arm"),
)
MOVING_ROBOT = ("robot:gripper", "robot:arm")
POWERED = {
    "microwave",
    "stove",
    "oven",
    "sink",
    "coffee_machine",
    "toaster",
    "toaster_oven",
    "dishwasher",
    "blender",
    "stand_mixer",
    "electric_kettle",
}
NOT_ENCLOSURES = {"counter", "counter_non_corner", "island"}  # surfaces: resting on them is `on`, not `in`
SUPPORT_NORMAL_Z = 0.7  # a contact normal at least this vertical, pushing the object up, supports it
BASE_LOCK_PREFIX = "robouse_base_lock_"
MAX_OBJECT_JOINTS = 8  # an object with more hinge/slide joints is loose contents, recorded as before 1.1.0


def _r(x, n: int = PRECISION):
    return [round(float(v), n) for v in np.asarray(x).ravel()]


def _plain(v):
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return round(float(v), PRECISION) if np.isfinite(v) else None
    if isinstance(v, dict):
        out = {str(k): _plain(x) for k, x in v.items()}
        return {k: x for k, x in out.items() if x is not None}
    if isinstance(v, (list, tuple, np.ndarray)) and len(v) <= 16:
        return [_plain(x) for x in v]
    return None


def digest(data) -> str:
    """Short fingerprint of the physical state (qpos and qvel), the same one every trace record carries."""
    h = hashlib.sha256(np.ascontiguousarray(data.qpos).tobytes())
    h.update(np.ascontiguousarray(data.qvel).tobytes())
    return h.hexdigest()[:16]


class Tracer:
    """Writes one episode's trace. `hooks` supplies the readings that need the worker's scenario module:
    power(key) -> bool, burners(key) -> {loc: bool}, grasped(obj) -> bool, robot() -> dict, goal() -> bool."""

    def __init__(
        self,
        env,
        spec: dict,
        path: str,
        control: str,
        hooks: dict,
        stride: int = 1,
        liquid_every: int = 10,
        source: dict | None = None,
    ):
        self.env, self.spec, self.hooks = env, spec, hooks
        self.stride, self.liquid_every = max(1, int(stride)), max(1, int(liquid_every))
        self.phase, self.records, self.last_step, self.failed = "control", 0, 0, None
        self._last_key = None
        self._index()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.f = gzip.open(path, "wt", compresslevel=6)  # noqa: SIM115 - open for the whole episode; finish() closes it
        header = {
            "kind": "header",
            "format": FORMAT,
            "version": VERSION,
            "scenario": spec.get("id"),
            "control": control,
            "stride": self.stride,
            "liquid_every": self.liquid_every,
            "precision": PRECISION,
            "objects": {
                n: {
                    "body": self.m.body_id2name(int(env.obj_body_id[n])),
                    **({"joints": {s: k for s, _, _, k in self.obj_joints[n]}} if self.obj_joints.get(n) else {}),
                    **({"interior": True} if n in self.interiors else {}),
                }
                for n in self.objects
            },
            "fixtures": self.fixture_meta,
            "source": source or {"kind": "live"},
        }
        self._write(header)

    # ---- static indexing ----------------------------------------------------------------------------------------
    def _index(self) -> None:
        env = self.env
        m, d = env.sim.model, env.sim.data
        self.m, self.d = m, d
        M = m._model
        nbody = int(M.nbody)
        parent = [int(M.body_parentid[b]) for b in range(nbody)]

        def subtree(root: int) -> set[int]:
            out = set()
            for b in range(nbody):
                k = b
                while k > 0 and k != root:
                    k = parent[k]
                if k == root:
                    out.add(b)
            return out

        self.objects = list(env.objects)
        body_label: dict[int, str] = {}
        self.obj_geoms: dict[str, list[int]] = {}
        for name in self.objects:
            for b in subtree(int(env.obj_body_id[name])):
                body_label[b] = name
        # fixtures: the scenario's own keys, then the rest of the kitchen; the longest naming prefix wins
        spec_fx = {}
        for key in self.spec.get("fixtures") or {}:
            fx = (getattr(env, "refs", None) or {}).get(key)
            if fx is not None:
                spec_fx[key] = fx
        prefixes = []
        named = {id(fx): key for key, fx in spec_fx.items()}
        for name, fx in (getattr(env, "fixtures", None) or {}).items():
            label = named.get(id(fx), "floor" if type(fx).__name__ == "Floor" else f"kitchen:{name}")
            for p in {getattr(fx, "naming_prefix", None), f"{getattr(fx, 'name', name)}_"}:
                if p:
                    prefixes.append((p, label))
        for key, fx in spec_fx.items():
            for p in {getattr(fx, "naming_prefix", None), f"{getattr(fx, 'name', key)}_"}:
                if p:
                    prefixes.append((p, key))
        prefixes.sort(key=lambda x: -len(x[0]))

        def fixture_label(b: int) -> str:
            if b in body_label:
                return body_label[b]
            name = m.body_id2name(b) or ""
            for p, lab in ROBOT_PARTS:
                if name.startswith(p):
                    return lab
            for p, lab in prefixes:
                if name.startswith(p):
                    return lab
            return "world"

        # a scenario fixture's moving parts (door, rack, knob: the bodies a hinge or slide joint moves) are labelled
        # `<key>/<part>` so that touching the rack differs from touching the cavity floor; the fixed body keeps `<key>`
        part_of: dict[int, str] = {}
        # 1.1.0: an object's own hinge and slide joints (a lever, driven blades) and the parts they move
        self.obj_joints: dict[str, list[tuple[str, int, int, str]]] = {}
        found: dict[str, list[tuple[int, tuple[str, int, int, str]]]] = {}
        for j in range(int(M.njnt)):
            jt = int(M.jnt_type[j])
            b = int(M.jnt_bodyid[j])
            if jt not in (2, 3) or b not in body_label:
                continue
            owner = body_label[b]
            short = m.joint_id2name(j) or str(j)
            for p in (f"{owner}_p_", f"{owner}_"):
                if short.startswith(p):
                    short = short[len(p) :]
                    break
            row = (short, int(M.jnt_qposadr[j]), int(M.jnt_dofadr[j]), "hinge" if jt == 3 else "slide")
            found.setdefault(owner, []).append((b, row))
        for owner, rows in found.items():
            if len(rows) > MAX_OBJECT_JOINTS:  # loose contents on their own joints (grains, drops): not a mechanism
                continue
            self.obj_joints[owner] = [row for _, row in rows]
            for b, row in rows:
                part_of.setdefault(b, row[0].removesuffix("_joint"))
        self.fixture_joints: dict[str, list[tuple[str, int]]] = {}
        joint_types: dict[str, dict[str, str]] = {}
        for j in range(int(M.njnt)):
            jt = int(M.jnt_type[j])
            if jt not in (2, 3):  # hinges and slides; free and ball joints belong to loose objects and the robot
                continue
            b = int(M.jnt_bodyid[j])
            lab = fixture_label(b)
            if lab not in spec_fx:
                continue
            jname = m.joint_id2name(j) or str(j)
            fx = spec_fx[lab]
            short = jname
            for p in (getattr(fx, "naming_prefix", ""), f"{getattr(fx, 'name', lab)}_"):
                if p and short.startswith(p):
                    short = short[len(p) :]
                    break
            self.fixture_joints.setdefault(lab, []).append((short, int(M.jnt_qposadr[j])))
            joint_types.setdefault(lab, {})[short] = "hinge" if jt == 3 else "slide"
            part_of.setdefault(b, short.removesuffix("_joint"))

        def label_of_body(b: int) -> str:
            lab = fixture_label(b)
            if lab in spec_fx or b in body_label:
                k = b
                while k > 0 and fixture_label(k) == lab:
                    if k in part_of:
                        return f"{lab}/{part_of[k]}"
                    k = parent[k]
            return lab

        self.geom_label = []
        for g in range(int(M.ngeom)):
            b = int(M.geom_bodyid[g])
            lab = label_of_body(b)
            gname = m.geom_id2name(g) or ""
            if lab == "world" and "floor" in gname.lower():
                lab = "floor"
            self.geom_label.append(lab)
            if b in body_label and (M.geom_contype[g] or M.geom_conaffinity[g]):
                self.obj_geoms.setdefault(body_label[b], []).append(g)
        # 1.1.0: interiors (an object's `reg_int` cylinder) and the moving robot's colliding geoms that may enter them
        self.interiors: dict[str, tuple[int, float, float]] = {}
        for name in self.objects:
            prefix = getattr(env.objects[name], "naming_prefix", f"{name}_")
            for g in range(int(M.ngeom)):
                if (m.geom_id2name(g) or "") == f"{prefix}reg_int" and int(M.geom_type[g]) == 5:
                    self.interiors[name] = (g, float(M.geom_size[g][0]), float(M.geom_size[g][1]))
        self.robot_geoms = [
            g
            for g in range(int(M.ngeom))
            if self.geom_label[g] in MOVING_ROBOT and (M.geom_contype[g] or M.geom_conaffinity[g])
        ]
        # the fixed part's box: its own colliding geoms (moving parts carry `<key>/<part>` labels)
        self.spec_fx = spec_fx
        self.fixture_box: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self.part_geoms: dict[str, dict[str, list[int]]] = {}
        self.fixture_meta = {}
        types = {k: (v or {}).get("type") for k, v in (self.spec.get("fixtures") or {}).items()}
        for key, fx in spec_fx.items():
            gs = [
                g
                for g in range(int(M.ngeom))
                if self.geom_label[g] == key and (M.geom_contype[g] or M.geom_conaffinity[g])
            ]
            box = self._box(gs) if gs and types.get(key) not in NOT_ENCLOSURES else None
            if box is not None:
                self.fixture_box[key] = box
            for g in range(int(M.ngeom)):  # each moving part's colliding geoms, for its box in every record
                lab = self.geom_label[g]
                if lab.startswith(f"{key}/") and (M.geom_contype[g] or M.geom_conaffinity[g]):
                    self.part_geoms.setdefault(key, {}).setdefault(lab.split("/", 1)[1], []).append(g)
            self.fixture_meta[key] = {
                "type": types.get(key),
                "class": type(fx).__name__,
                "joints": joint_types.get(key, {}),
                "parts": sorted({lab for lab in self.geom_label if lab.startswith(f"{key}/")}),
                "box": [_r(box[0]), _r(box[1])] if box is not None else None,
                "powered": types.get(key) in POWERED,
            }
        self.eq_names = []
        try:
            import mujoco

            for i in range(int(M.neq)):
                n = mujoco.mj_id2name(M, mujoco.mjtObj.mjOBJ_EQUALITY, i)
                if n and not n.startswith(BASE_LOCK_PREFIX):
                    self.eq_names.append((n, i))
        except Exception:  # noqa: BLE001 - welds are optional detail
            self.eq_names = []

    def _box(self, gs):
        M, d = self.m._model, self.d._data
        lo, hi = None, None
        for g in gs:
            R = np.asarray(d.geom_xmat[g]).reshape(3, 3)
            c = np.asarray(d.geom_xpos[g]) + R @ M.geom_aabb[g][:3]
            e = np.abs(R) @ M.geom_aabb[g][3:]
            lo = c - e if lo is None else np.minimum(lo, c - e)
            hi = c + e if hi is None else np.maximum(hi, c + e)
        return (lo, hi) if lo is not None else None

    # ---- recording ----------------------------------------------------------------------------------------------
    def _write(self, row: dict) -> None:
        self.f.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.records += 1

    def _contacts(self):
        d = self.d._data
        pairs, support = set(), {}
        objects = set(self.objects)
        n = int(d.ncon)
        con = d.contact
        g1s, g2s = np.asarray(con.geom1[:n]), np.asarray(con.geom2[:n])
        active, normal_z = np.asarray(con.efc_address[:n]) >= 0, np.asarray(con.frame[:n]).reshape(n, 9)[:, 2]
        for i in range(n):
            if not active[i]:  # inside the margin, exerting no force
                continue
            a, b = self.geom_label[int(g1s[i])], self.geom_label[int(g2s[i])]
            a0, b0 = a.split("/")[0], b.split("/")[0]  # an object's or fixture's own name, without a moving part
            if a0 == b0 or (a.startswith("robot:") and b.startswith("robot:")):
                continue  # within one fixture or object, or within the robot
            if a0 not in objects and b0 not in objects and a not in MOVING_ROBOT and b not in MOVING_ROBOT:
                continue
            pairs.add((a, b) if a < b else (b, a))
            nz = float(normal_z[i])  # the normal points from geom1 to geom2
            if b0 in objects and nz >= SUPPORT_NORMAL_Z:
                support.setdefault(b0, set()).add(a0 if a0 in objects else a)
            if a0 in objects and -nz >= SUPPORT_NORMAL_Z:
                support.setdefault(a0, set()).add(b0 if b0 in objects else b)
        return sorted([list(p) for p in pairs]), {k: sorted(v) for k, v in support.items()}

    def _robot_inside(self) -> dict:
        """{object: depth} for each interior cylinder a colliding geom of the moving robot reaches into: the depth of
        its lowest sampled point (box corners, face centres and centre of each geom) below the interior's top."""
        if not self.interiors or not self.robot_geoms:
            return {}
        M, d = self.m._model, self.d._data
        pts = []
        unit = np.array([[x, y, z] for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)], float)
        for g in self.robot_geoms:
            R = np.asarray(d.geom_xmat[g]).reshape(3, 3)
            c = np.asarray(d.geom_xpos[g]) + R @ M.geom_aabb[g][:3]
            pts.append(c + (unit * M.geom_aabb[g][3:]) @ R.T)
        pts = np.concatenate(pts)
        out = {}
        for name, (g, radius, half) in self.interiors.items():
            R, c = np.asarray(d.geom_xmat[g]).reshape(3, 3), np.asarray(d.geom_xpos[g])
            loc = (pts - c) @ R
            hit = (np.linalg.norm(loc[:, :2], axis=1) <= radius) & (np.abs(loc[:, 2]) <= half)
            if hit.any():
                out[name] = round(float(half - loc[hit, 2].min()), 4)
        return out

    def _inside(self, lo, hi) -> dict:
        if not self.fixture_box:
            return {}
        vol = float(np.prod(np.maximum(hi - lo, 1e-9)))
        out = {}
        for key, (flo, fhi) in self.fixture_box.items():
            ov = np.clip(np.minimum(hi, fhi) - np.maximum(lo, flo), 0, None)
            frac = float(np.prod(ov)) / vol
            if frac >= 0.01:
                out[key] = round(min(frac, 1.0), 2)
        return out

    def _fixtures(self) -> dict:
        qpos = self.d._data.qpos
        out = {}
        for key, fx in self.spec_fx.items():
            row: dict = {}
            joints = self.fixture_joints.get(key)
            if joints:
                row["joints"] = {s: round(float(qpos[a]), PRECISION) for s, a in joints}
            if self.part_geoms.get(key):
                row["parts"] = {}
                for part, gs in self.part_geoms[key].items():
                    lo, hi = self._box(gs)
                    row["parts"][part] = [_r(lo, 4), _r(hi, 4)]
            if self.fixture_meta[key]["powered"]:
                for field, hook in (("on", "power"), ("burners", "burners")):
                    try:
                        v = self.hooks[hook](key)
                        if v is not None and v != {}:
                            row[field] = v
                    except Exception as e:  # noqa: BLE001 - recorded, never read as "off"
                        row[f"{field}_error"] = f"{type(e).__name__}: {e}"[:160]
                try:
                    import inspect

                    st = fx.get_state
                    params = inspect.signature(st).parameters
                    raw = st(self.env) if "env" in params else st(self.env.sim) if "sim" in params else st()
                    state = _plain(raw) if isinstance(raw, dict) else None
                    if state:
                        row["state"] = state
                except Exception:  # noqa: BLE001 - RoboCasa's own state is optional detail
                    pass
            if row:
                out[key] = row
        return out

    def _liquid(self):
        ls = getattr(self.env, "_liquid_scene", None)
        if ls is None:
            return None
        try:
            labels = np.asarray(ls.labels())
            names, counts = np.unique(labels, return_counts=True)
            vol = ls.volumes_ml()
            return {
                "counts": {str(n): int(c) for n, c in zip(names, counts, strict=True)},
                "volumes_ml": {str(k): round(float(v), 3) for k, v in vol.items()},
            }
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"[:160]}

    def snapshot(self, step: int, phase: str, liquid: bool) -> dict:
        d = self.d._data
        contacts, support = self._contacts()
        objects = {}
        for n in self.objects:
            bid = int(self.env.obj_body_id[n])
            row = {"pos": _r(d.xpos[bid]), "quat": _r(d.xquat[bid])}
            if support.get(n):
                row["on"] = support[n]
            gs = self.obj_geoms.get(n)
            if gs:
                lo, hi = self._box(gs)
                row["box"] = [_r(lo, 4), _r(hi, 4)]
                inside = self._inside(lo, hi)
                if inside:
                    row["in"] = inside
            if self.obj_joints.get(n):
                row["joints"] = {s: round(float(d.qpos[qa]), PRECISION) for s, qa, _, _ in self.obj_joints[n]}
                row["speeds"] = {s: round(float(d.qvel[va]), 4) for s, _, va, _ in self.obj_joints[n]}
            objects[n] = row
        robot = dict(self.hooks["robot"]())
        robot["grasped"] = [n for n in self.objects if self._grasped(n)]
        reach = self._robot_inside()
        if reach:
            robot["inside"] = reach
        rec = {
            "kind": "state",
            "step": int(step),
            "phase": phase,
            "t": round(float(d.time), 4),
            "digest": digest(d),
            "robot": robot,
            "objects": objects,
            "fixtures": self._fixtures(),
            "contacts": contacts,
        }
        if self.eq_names:
            rec["welds"] = {n: bool(d.eq_active[i]) for n, i in self.eq_names}
        if liquid:
            lq = self._liquid()
            if lq is not None:
                rec["liquid"] = lq
        return rec

    def _grasped(self, n: str) -> bool:
        try:
            return bool(self.hooks["grasped"](n))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _key(rec: dict):
        """The discrete part of a state: a change is always recorded, whatever the stride."""
        return json.dumps(
            [
                rec["robot"].get("grasped"),
                sorted(rec["robot"].get("inside") or {}),
                rec["contacts"],
                {n: [o.get("on"), sorted(o.get("in", {}))] for n, o in rec["objects"].items()},
                {k: [f.get("on"), f.get("burners")] for k, f in rec["fixtures"].items()},
                rec.get("welds"),
            ],
            sort_keys=True,
        )

    def record(self, step: int, phase: str | None = None) -> None:
        """The state after control `step` (0: after reset)."""
        if self.failed or self.f is None:
            return
        try:
            phase = phase or ("reset" if step == 0 else self.phase)
            liquid = step == 0 or step % self.liquid_every == 0
            rec = self.snapshot(step, phase, liquid)
            key = self._key(rec)
            if step == 0 or step % self.stride == 0 or key != self._last_key:
                self._write(rec)
            self._last_key, self.last_step = key, int(step)
        except Exception as e:  # noqa: BLE001 - tracing never stops the episode; the trace says it is incomplete
            self.fail(step, e)

    def fail(self, step: int, e: BaseException) -> None:
        self.failed = f"{type(e).__name__}: {e}"[:300]
        try:
            self._write({"kind": "error", "step": int(step), "error": self.failed})
            self.f.close()
        except Exception:  # noqa: BLE001
            pass
        self.f = None

    def finish(self) -> dict:
        """The final state and the end line; closes the file. Idempotent."""
        if self.f is None:
            return {"file": os.path.basename(self.path), "complete": False, "error": self.failed}
        try:
            self._write(self.snapshot(self.last_step, "final", True))
            goal = None
            try:
                goal = bool(self.hooks["goal"]())
            except Exception:  # noqa: BLE001
                pass
            self._write({"kind": "end", "steps": self.last_step, "records": self.records + 1, "goal": goal})
            self.f.close()
            self.f = None
            return {"file": os.path.basename(self.path), "complete": True, "records": self.records}
        except Exception as e:  # noqa: BLE001
            self.fail(self.last_step, e)
            return {"file": os.path.basename(self.path), "complete": False, "error": self.failed}


# ---- reading (robouse package and research tools) ----------------------------------------------------------------
def read(path) -> dict:
    """{"header", "states", "end", "error", "complete"} of a trace file. `complete` is False for a trace without its
    end line or with an error line: such a trace is incomplete evidence."""
    header, states, end, error = None, [], None, None
    try:
        with gzip.open(path, "rt") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                kind = row.get("kind")
                if kind == "header":
                    header = row
                elif kind == "state":
                    states.append(row)
                elif kind == "end":
                    end = row
                elif kind == "error":
                    error = row
    except (OSError, EOFError, ValueError) as e:  # a truncated gzip stream: what was read so far, marked incomplete
        error = error or {"kind": "error", "error": f"unreadable trace: {type(e).__name__}: {e}"[:300]}
    ok = header is not None and header.get("format") == FORMAT and end is not None and error is None
    return {"header": header, "states": states, "end": end, "error": error, "complete": ok}
