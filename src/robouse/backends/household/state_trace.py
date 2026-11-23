"""Physical-state trace of a household episode (format `robouse-state-trace` 2.0.0, backend `household`).

A researcher-only record of what physically happened, written by the simulation (in-process or in the worker) into
the episode's run folder as `state-trace.jsonl.gz` (gzip, one JSON object per line; `<trial>/episode/` in a runner
trial). It is never part of an observation, a reply or anything a policy can request: Text episodes and practice or
development episodes (ROBOUSE_STATE_TRACE=0) do not write it, and run folders are denied to policies. Same line
structure as the RoboCasa trace (backends/robocasa/state_trace.py, 1.1.0), so its readers work unchanged; 2.0.0 adds
contact forces and the robot's joint-level state, and names things by the package's instance names.

Lines, in order:
  header  {"kind": "header", "format", "version", "backend": "household", "package": identity (sha256 of
           episode.json), "control", "stride": 1, "precision", "room", "objects": {name: {"body", "joints"?: {joint:
           "hinge"|"slide"}}}, "fixtures": {name: {"joints": {joint: kind}, "parts": [...], "box"}}, "robot": {...},
           "extensions": [keys], "forces": how forces are measured, "source": {"kind": "live"}}
  state   {"kind": "state", "step", "phase", "t", "digest", "robot", "objects", "fixtures", "contacts",
           "contact_forces", "welds"?, <extension key>?}
  error   {"kind": "error", "step", "error"}: tracing stopped here; the trace is incomplete
  end     {"kind": "end", "steps", "records", "goal"}: the trace is complete

`phase`: `reset` (after reset settling, step 0), `control` (after each control step of the episode), `settle` (the
still steps after `robo done`), `final` (the state the episode was judged on). Every control step is recorded.

State fields (positions m, world frame; quaternions w, x, y, z; joints rad or m; rounded to `precision` = 6
decimals, boxes to 0.1 mm, forces to 1 mN):
  robot     {"eef": pinch point [x, y, z], "eef_quat", "grip": measured opening 0..1, "grip_cmd": commanded opening,
             "q": arm joints, "q_ref": the servo reference (the setpoint the joint limits let through), "q_goal":
             the controller's goal, "tau": arm actuator forces (N m), "grasped": [objects both finger pads press on],
             "pad_force": {label: N} normal force of the finger pads on each thing they touch}
  objects   {name: {"pos", "quat", "v": linear speed m/s (free objects), "box": world box of its colliding geoms,
             "on": [what supports it from below], "in": {fixture: fraction of its box inside the fixture's fixed box},
             "joints"?, "speeds"?: hinge/slide joints inside the object (at most 8), named without the instance}}
  fixtures  {name: {"joints": {joint: value}, "parts": {part: world box of a moving part}}}
  contacts  [[a, b], ...] active contact pairs (sorted, a < b). Sides: an object, a fixture (`<fixture>` its fixed
            body, `<fixture>/<part>` a body moved by one of its joints), `<object>/<part>` likewise, the room shell
            (`room`), `robot:gripper`, `robot:arm`, `robot:base` (link 0 and the pedestal), or `world`. Pairs within
            one instance or within the robot are left out, and so are pairs with neither an object nor the moving robot.
  contact_forces  [[a, b, n, normal_N, tangential_N, peak_normal_N], ...]: first one row per `contacts` pair, in the
            same order, then the pairs that touched only during the control step's earlier substeps (n = 0). n: the
            number of contact points, normal_N / tangential_N: their summed force magnitudes (mj_contactForce, contact
            frame) at the last physics substep of the control step, peak_normal_N: the largest summed normal force of
            the pair over all the control step's substeps (impacts shorter than 20 ms show here).
  welds     {name: active} for named equality constraints of the scene
  digest    the first 16 hex digits of SHA-256 over qpos and qvel

Recording only reads what the simulation computed; it never calls mj_forward, sets state or draws random numbers, so a
traced episode's dynamics are bit-identical to an untraced one (tests check the digests).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os

import mujoco
import numpy as np

FORMAT = "robouse-state-trace"
VERSION = "2.0.0"
FILENAME = "state-trace.jsonl.gz"
PRECISION = 6
FORCE_DECIMALS = 3
SUPPORT_NORMAL_Z = 0.7  # a contact normal at least this vertical, pushing the object up, supports it
GRASP_PAD_N = 0.5  # each finger's pads press on the object with at least this normal force: grasped
MAX_OBJECT_JOINTS = 8
MOVING_ROBOT = ("robot:gripper", "robot:arm")
FORCES_DOC = (
    "mj_contactForce in the contact frame at the last physics substep of each control step (N); peak_normal_N: the "
    "largest summed normal force of a pair over the control step's substeps (efc_force, elliptic cones)"
)


def _r(x, n: int = PRECISION):
    return [round(float(v), n) for v in np.asarray(x).ravel()]


def digest(data) -> str:
    h = hashlib.sha256(np.ascontiguousarray(data.qpos).tobytes())
    h.update(np.ascontiguousarray(data.qvel).tobytes())
    return h.hexdigest()[:16]


class Tracer:
    """One episode's trace of a HouseholdSim (`sim`). The sim calls `record(step)` after every counted control step and
    `substep()` after every physics substep while a tracer is attached; the backend calls `phase`, `finish`."""

    def __init__(self, sim, path: str, control: str):
        self.sim, self.m, self.d = sim, sim.model, sim.data
        self.phase, self.records, self.last_step, self.failed = "control", 0, 0, None
        self._index()
        self._peak: dict[tuple[int, int], float] = {}
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.f = gzip.open(path, "wt", compresslevel=6)  # noqa: SIM115 - open for the whole episode; finish() closes it
        self._write(
            {
                "kind": "header",
                "format": FORMAT,
                "version": VERSION,
                "backend": "household",
                "package": sim.ep.identity,
                "control": control,
                "stride": 1,
                "precision": PRECISION,
                "room": self.room,
                "objects": {
                    n: {
                        "body": n,
                        **({"joints": {s: k for s, _, _, k in self.obj_joints[n]}} if self.obj_joints.get(n) else {}),
                    }
                    for n in self.objects
                },
                "fixtures": self.fixture_meta,
                "robot": {
                    "model": sim.rs.type,
                    "parts": ["robot:arm", "robot:gripper", "robot:base"],
                    "joints": list(sim.rs.arm_joints),
                },
                "extensions": [e.key for e in sim.extensions],
                "forces": FORCES_DOC,
                "source": {"kind": "live"},
            }
        )

    # ---- static indexing ------------------------------------------------------------------------------------------
    def _index(self) -> None:
        m = self.m
        tr = self.sim.ep.trace
        self.objects = [str(n) for n in tr.get("objects") or []]
        fixtures = [str(n) for n in tr.get("fixtures") or []]
        self.room = str(tr.get("room") or "room")
        nbody = m.nbody
        parent = m.body_parentid
        names = [m.body(b).name for b in range(nbody)]
        roots = {}
        for inst in [*self.objects, *fixtures, self.room]:
            b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, inst)
            if b >= 0:
                roots[b] = inst
        self.obj_body = {n: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) for n in self.objects}
        self.objects = [n for n in self.objects if self.obj_body[n] >= 0]
        owner = [""] * nbody  # the instance a body belongs to (its nearest listed ancestor)
        for b in range(1, nbody):
            k = b
            while k > 0 and k not in roots:
                k = int(parent[k])
            owner[b] = roots.get(k, "")
        # the bodies a hinge or slide joint moves inside an object or fixture: `<instance>/<part>` (part: the body's
        # own name without the instance prefix)
        part_root: dict[int, str] = {}
        self.obj_joints: dict[str, list[tuple[str, int, int, str]]] = {}
        self.fixture_joints: dict[str, list[tuple[str, int]]] = {}
        joint_kinds: dict[str, dict[str, str]] = {}
        found: dict[str, list] = {}
        for j in range(m.njnt):
            jt = int(m.jnt_type[j])
            b = int(m.jnt_bodyid[j])
            inst = owner[b]
            if jt not in (mujoco.mjtJoint.mjJNT_HINGE, mujoco.mjtJoint.mjJNT_SLIDE) or not inst:
                continue
            short = (m.joint(j).name or str(j)).removeprefix(inst + "/")
            kind = "hinge" if jt == mujoco.mjtJoint.mjJNT_HINGE else "slide"
            found.setdefault(inst, []).append((b, (short, int(m.jnt_qposadr[j]), int(m.jnt_dofadr[j]), kind)))
        for inst, rows in found.items():
            if inst in self.objects:
                if len(rows) > MAX_OBJECT_JOINTS:  # loose contents on their own joints: not a mechanism
                    continue
                self.obj_joints[inst] = [r for _, r in rows]
            elif inst in fixtures:
                self.fixture_joints[inst] = [(r[0], r[1]) for _, r in rows]
                joint_kinds[inst] = {r[0]: r[3] for _, r in rows}
            for b, _ in rows:
                part_root[b] = (names[b] or str(b)).removeprefix(inst + "/")

        def label_of_body(b: int) -> str:
            name = names[b] or ""
            if name.startswith("robot/"):
                if name.startswith("robot/hand/"):
                    return "robot:gripper"
                return "robot:base" if name in ("robot/fr3_link0", "robot/pedestal", "robot/base") else "robot:arm"
            inst = owner[b]
            if not inst:
                return "world"
            k = b
            while k > 0 and owner[k] == inst:
                if k in part_root:
                    return f"{inst}/{part_root[k]}"
                k = int(parent[k])
            return inst

        self.labels: list[str] = []
        lid: dict[str, int] = {}

        def intern(s: str) -> int:
            if s not in lid:
                lid[s] = len(self.labels)
                self.labels.append(s)
            return lid[s]

        geom_label = []
        for g in range(m.ngeom):
            name = m.geom(g).name or ""
            lab = label_of_body(int(m.geom_bodyid[g]))
            if name.startswith("robot/") and not lab.startswith("robot:"):  # a robot geom on the world body (pedestal)
                lab = "robot:gripper" if name.startswith("robot/hand/") else "robot:base"
            geom_label.append(intern(lab))
        self.geom_label = np.asarray(geom_label, dtype=np.int64)
        flex_label = []
        for f in range(int(getattr(m, "nflex", 0))):
            flex_label.append(intern(label_of_body(int(m.flex_vertbodyid[int(m.flex_vertadr[f])]))))
        self.flex_label = np.asarray(flex_label, dtype=np.int64)
        self.root_of = [s.split("/")[0] if not s.startswith("robot:") else "robot" for s in self.labels]
        self._keep: dict[tuple[int, int], bool] = {}
        colliding = (m.geom_contype != 0) | (m.geom_conaffinity != 0)
        self.obj_geoms = {
            n: [g for g in range(m.ngeom) if colliding[g] and self.labels[geom_label[g]].split("/")[0] == n]
            for n in self.objects
        }
        self.part_geoms: dict[str, dict[str, list[int]]] = {}
        self.fixture_box: dict[str, tuple] = {}
        self.fixture_meta = {}
        for fx in fixtures:
            fixed = [g for g in range(m.ngeom) if colliding[g] and self.labels[geom_label[g]] == fx]
            for g in range(m.ngeom):
                lab = self.labels[geom_label[g]]
                if colliding[g] and lab.startswith(fx + "/"):
                    self.part_geoms.setdefault(fx, {}).setdefault(lab.split("/", 1)[1], []).append(g)
            box = self._box(fixed) if fixed else None
            if box is not None:
                self.fixture_box[fx] = box
            self.fixture_meta[fx] = {
                "joints": joint_kinds.get(fx, {}),
                "parts": sorted(self.part_geoms.get(fx, {})),
                "box": [_r(box[0], 4), _r(box[1], 4)] if box is not None else None,
            }
        self.free_dof = {}
        for n, b in self.obj_body.items():
            if b >= 0 and m.body_jntnum[b] >= 1:
                j = int(m.body_jntadr[b])
                if int(m.jnt_type[j]) == mujoco.mjtJoint.mjJNT_FREE:
                    self.free_dof[n] = int(m.jnt_dofadr[j])
        self.eq_names = [
            (m.equality(i).name, i)
            for i in range(m.neq)
            if m.equality(i).name and not m.equality(i).name.startswith("robot/")
        ]
        self.pad_left = np.asarray(sorted(self.sim.left_pads), dtype=np.int64)
        self.pad_right = np.asarray(sorted(self.sim.right_pads), dtype=np.int64)

    def _keep_pair(self, a: int, b: int) -> bool:
        key = (a, b)
        v = self._keep.get(key)
        if v is None:
            la, lb = self.labels[a], self.labels[b]
            ra, rb = self.root_of[a], self.root_of[b]
            objs = self.objects
            v = ra != rb and (ra in objs or rb in objs or la in MOVING_ROBOT or lb in MOVING_ROBOT)
            self._keep[key] = v
        return v

    def _box(self, gs):
        m, d = self.m, self.d
        lo = hi = None
        for g in gs:
            R = d.geom_xmat[g].reshape(3, 3)
            c = d.geom_xpos[g] + R @ m.geom_aabb[g][:3]
            e = np.abs(R) @ m.geom_aabb[g][3:]
            lo = c - e if lo is None else np.minimum(lo, c - e)
            hi = c + e if hi is None else np.maximum(hi, c + e)
        return (lo, hi) if lo is not None else None

    # ---- contacts -------------------------------------------------------------------------------------------------
    def _sides(self, n: int):
        d = self.d
        con = d.contact
        g1, g2 = np.asarray(con.geom1[:n]), np.asarray(con.geom2[:n])
        fl = np.asarray(con.flex[:n]).reshape(n, 2) if n else np.zeros((0, 2), np.int64)
        a = np.where(g1 >= 0, self.geom_label[np.maximum(g1, 0)], -1)
        b = np.where(g2 >= 0, self.geom_label[np.maximum(g2, 0)], -1)
        if len(self.flex_label):
            a = np.where(g1 >= 0, a, self.flex_label[np.maximum(fl[:, 0], 0)])
            b = np.where(g2 >= 0, b, self.flex_label[np.maximum(fl[:, 1], 0)])
        return a, b, g1, g2

    def substep(self) -> None:
        """After one physics substep: the largest summed normal force of each kept pair so far this control step."""
        try:
            d = self.d
            n = int(d.ncon)
            if not n:
                return
            adr = np.asarray(d.contact.efc_address[:n])
            act = adr >= 0
            if not act.any():
                return
            a, b, _, _ = self._sides(n)
            fn = np.zeros(n)
            fn[act] = np.asarray(d.efc_force)[adr[act]]
            sums: dict[tuple[int, int], float] = {}
            for i in np.nonzero(act)[0]:
                x, y = int(a[i]), int(b[i])
                if x < 0 or y < 0:
                    continue
                key = (x, y) if self.labels[x] < self.labels[y] else (y, x)
                if self._keep_pair(*key):
                    sums[key] = sums.get(key, 0.0) + abs(float(fn[i]))
            for key, v in sums.items():
                if v > self._peak.get(key, 0.0):
                    self._peak[key] = v
        except Exception as e:  # noqa: BLE001 - tracing never stops the episode
            self.fail(self.last_step, e)

    def _contacts(self):
        m, d = self.m, self.d
        n = int(d.ncon)
        pairs: dict[tuple[int, int], list[float]] = {}
        support: dict[str, set] = {}
        pad: dict[str, list[float]] = {}  # label -> [left N, right N]
        if n:
            a, b, g1, g2 = self._sides(n)
            adr = np.asarray(d.contact.efc_address[:n])
            frame = np.asarray(d.contact.frame[:n]).reshape(n, 9)
            f6 = np.zeros(6)
            lp, rp = set(self.pad_left.tolist()), set(self.pad_right.tolist())
            for i in range(n):
                if adr[i] < 0 or a[i] < 0 or b[i] < 0:
                    continue
                x, y = int(a[i]), int(b[i])
                la, lb = self.labels[x], self.labels[y]
                gi, gj = int(g1[i]), int(g2[i])
                mujoco.mj_contactForce(m, d, i, f6)
                fn, ft = abs(float(f6[0])), float(np.hypot(f6[1], f6[2]))
                for pg, other in ((gi, lb), (gj, la)):
                    if pg in lp or pg in rp:
                        if not other.startswith("robot:"):
                            pad.setdefault(other, [0.0, 0.0])[0 if pg in lp else 1] += fn
                key = (x, y) if la < lb else (y, x)
                if not self._keep_pair(*key):
                    continue
                row = pairs.setdefault(key, [0, 0.0, 0.0])
                row[0] += 1
                row[1] += fn
                row[2] += ft
                ra, rb = self.root_of[x], self.root_of[y]
                nz = float(frame[i, 2])  # the normal points from geom1's side to geom2's
                if rb in self.objects and nz >= SUPPORT_NORMAL_Z:
                    support.setdefault(rb, set()).add(ra if ra in self.objects else la)
                if ra in self.objects and -nz >= SUPPORT_NORMAL_Z:
                    support.setdefault(ra, set()).add(rb if rb in self.objects else lb)
        keys = sorted(set(pairs) | set(self._peak), key=lambda k: (self.labels[k[0]], self.labels[k[1]]))
        contacts, forces = [], []
        for k in keys:
            row = pairs.get(k, [0, 0.0, 0.0])
            la, lb = self.labels[k[0]], self.labels[k[1]]
            if row[0] == 0 and self._peak.get(k, 0.0) <= 0.0:
                continue
            if row[0]:
                contacts.append([la, lb])
            peak = max(self._peak.get(k, 0.0), row[1])
            forces.append(
                [
                    la,
                    lb,
                    row[0],
                    round(row[1], FORCE_DECIMALS),
                    round(row[2], FORCE_DECIMALS),
                    round(peak, FORCE_DECIMALS),
                ]
            )
        self._peak = {}
        # contact_forces stays aligned with contacts: pairs that touched only between records come after them
        forces.sort(key=lambda r: (r[2] == 0, r[0], r[1]))
        grasped = sorted(
            lab.split("/")[0]
            for lab, (fl, fr) in pad.items()
            if fl >= GRASP_PAD_N and fr >= GRASP_PAD_N and lab.split("/")[0] in self.objects
        )
        pad_out = {k: round(v[0] + v[1], FORCE_DECIMALS) for k, v in sorted(pad.items())}
        return contacts, forces, {k: sorted(v) for k, v in support.items()}, sorted(set(grasped)), pad_out

    def _inside(self, lo, hi) -> dict:
        out = {}
        if lo is None:
            return out
        vol = float(np.prod(np.maximum(hi - lo, 1e-9)))
        for key, (flo, fhi) in self.fixture_box.items():
            ov = np.clip(np.minimum(hi, fhi) - np.maximum(lo, flo), 0, None)
            frac = float(np.prod(ov)) / vol
            if frac >= 0.01:
                out[key] = round(min(frac, 1.0), 2)
        return out

    # ---- records --------------------------------------------------------------------------------------------------
    def snapshot(self, step: int, phase: str) -> dict:
        d, sim = self.d, self.sim
        contacts, forces, support, grasped, pad = self._contacts()
        objects = {}
        for n in self.objects:
            b = self.obj_body[n]
            row: dict = {"pos": _r(d.xpos[b]), "quat": _r(d.xquat[b])}
            if n in self.free_dof:
                a = self.free_dof[n]
                row["v"] = round(float(np.linalg.norm(d.qvel[a : a + 3])), 4)
            if support.get(n):
                row["on"] = support[n]
            gs = self.obj_geoms.get(n)
            if gs:
                lo, hi = self._box(gs)
                row["box"] = [_r(lo, 4), _r(hi, 4)]
                if inside := self._inside(lo, hi):
                    row["in"] = inside
            if self.obj_joints.get(n):
                row["joints"] = {s: round(float(d.qpos[qa]), PRECISION) for s, qa, _, _ in self.obj_joints[n]}
                row["speeds"] = {s: round(float(d.qvel[va]), 4) for s, _, va, _ in self.obj_joints[n]}
            objects[n] = row
        fixtures = {}
        for fx in self.fixture_meta:
            row = {}
            if self.fixture_joints.get(fx):
                row["joints"] = {s: round(float(d.qpos[a]), PRECISION) for s, a in self.fixture_joints[fx]}
            if self.part_geoms.get(fx):
                row["parts"] = {}
                for part, gs in self.part_geoms[fx].items():
                    lo, hi = self._box(gs)
                    row["parts"][part] = [_r(lo, 4), _r(hi, 4)]
            if row:
                fixtures[fx] = row
        p, q = sim.hand_pose()
        robot = {
            "eef": _r(p),
            "eef_quat": _r(q),
            "grip": round(float(sim.gripper_open()), 4),
            "grip_cmd": round(float(sim.grip_open_cmd), 4),
            "q": _r(sim.q()),
            "q_ref": _r(sim.tracker.q),
            "q_goal": _r(sim.tracker.goal),
            "tau": _r(d.actuator_force[sim.arm_ctrl], 4),
            "grasped": grasped,
            "pad_force": pad,
        }
        rec = {
            "kind": "state",
            "step": int(step),
            "phase": phase,
            "t": round(float(d.time), 4),
            "digest": digest(d),
            "robot": robot,
            "objects": objects,
            "fixtures": fixtures,
            "contacts": contacts,
            "contact_forces": forces,
        }
        if self.eq_names:
            rec["welds"] = {n: bool(d.eq_active[i]) for n, i in self.eq_names}
        rec.update(sim.extension_trace())
        return rec

    def _write(self, row: dict) -> None:
        self.f.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.records += 1

    def record(self, step: int, phase: str | None = None) -> None:
        """The state after control step `step` (0: after reset)."""
        if self.failed or self.f is None:
            return
        try:
            self._write(self.snapshot(step, phase or ("reset" if step == 0 else self.phase)))
            self.last_step = int(step)
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

    def finish(self, goal: bool | None) -> dict:
        """The final state and the end line; closes the file. Idempotent."""
        if self.f is None:
            return self.status()
        try:
            self._write(self.snapshot(self.last_step, "final"))
            self._write({"kind": "end", "steps": self.last_step, "records": self.records + 1, "goal": goal})
            self.f.close()
            self.f = None
        except Exception as e:  # noqa: BLE001
            self.fail(self.last_step, e)
        return self.status()

    def status(self) -> dict:
        if self.failed:
            return {"file": FILENAME, "complete": False, "error": self.failed}
        return {"file": FILENAME, "complete": self.f is None, "records": self.records}


def read(path) -> dict:
    """{"header", "states", "end", "error", "complete"} of a trace file (any backend)."""
    from ..robocasa.state_trace import read as _read

    return _read(path)
