"""One-demo suite -> robouse tasks: in-context imitation of one demonstration, on another object.

Inspired by DemoMimic ("One Demonstration, Many Objects: Generalizing Manipulation via Local Contact Geometry", Sharma,
Sahoo, Huang, Li, Wu, Sadigh and Bohg, arXiv 2609.01938): one demonstration of a skill transfers to objects whose local
contact geometry matches. No code or data of theirs is used. Scenes, reference strategies and targets live in
src/robouse/backends/tabletop/onedemo.py (FAMILIES).

For each family this script runs the reference strategy on the demonstration's scene in the episode server (in process:
the request handler and judge `robouse serve` uses, without its video), requires that the demonstration scores 1, and
keeps its `robo` requests, the server's replies and the simulator state at the moments the strategy marks. Every target
then becomes a task folder, tasks/one-demo/<id>/, whose `robouse.scenario` holds the target's scene and goals and the
demonstration (its scene, its commands and the states of its frames), and whose instruction carries the demonstration's
command trace. The episode server renders the frames into the agent's workspace when an episode starts
(TabletopBackend.workspace_images).

Before writing a task, the script checks four controls on it in process: the reference strategy scores 1, the no-op
control scores 0, the demonstration's own commands replayed verbatim score 0, and the same commands shifted by the
offset between the two objects' contact points (knob, cap or handle) score 0. `robouse tasks check` then runs the real
runner on the folders.

Usage: python adapters/one-demo/generate.py [--out tasks/one-demo] [--frames DIR]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import yaml

from robouse.agent_cli import format_reply
from robouse.backends.tabletop.onedemo import FAMILIES, ONE_DEMO_TASKS, run_strategy, scenario
from robouse.core.prompts import ROBO_USAGE
from robouse.tasks import write_task

ROOT = Path(__file__).resolve().parents[2]
SUITE = "one-demo"
STEPPING = ("move_to", "grip", "act")  # the requests that move the robot


def _tabletop_adapter():
    spec = importlib.util.spec_from_file_location("_tt_generate", ROOT / "adapters" / "tabletop" / "generate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TT = _tabletop_adapter()  # the verifier script and the gripper section are the tabletop suites' own

SCENE = (
    "A two-finger parallel gripper hangs over a table (a floating gripper, no arm; it cannot rotate). x points to the right "
    "as seen from the front of the table, y away from the front (toward the back of the table), z up; the table top is at "
    "z = 0 and spans x from -0.35 to 0.35 and y from -0.30 to 0.30. The gripper's tool point can reach x in [-0.34, 0.34], "
    "y in [-0.27, 0.28], z in [0.012, 0.35]. The fingers close along the y axis; the fully open gap is 10 cm."
)
MOVE_TO = (
    "`robo move-to` also takes `--max-steps N` (it moves for at most N steps, up to 150; default 100) and `--tol T` (it "
    "stops once the tool point is within T metres of the target; default 0.01), as the demonstration's commands do."
)
# what a shortened reply keeps of the demonstration's things, after the first `robo observe` (which shows all of them)
MOVING = {
    "open-box": ("fixtures", "box", ["lid_angle_deg", "knob_pos", "gripper_touching"]),
    "lift-lid": ("objects", "lid", ["pos", "knob_pos", "tilt_deg"]),
    "upright-bottle": ("objects", "bottle", ["cap_pos", "base_pos", "tilt_deg"]),
    "open-drawer": ("fixtures", "cabinet", ["opening", "handle_pos", "gripper_touching"]),
}


# --------------------------------------------------------------------------------------------------
# Episodes in process
# --------------------------------------------------------------------------------------------------


def _episode(sc: dict, run_dir: Path):
    """An episode of scenario `sc` in the episode server's own request handler, without the video."""
    from robouse.core.session import Episode

    class Unrecorded(Episode):
        def _record_frame(self, force: bool = False) -> None:
            pass

    spec = {"id": sc["id"], "backend": "tabletop", "scenario": sc, "max_steps": sc["max_steps"]}
    return Unrecorded(spec, run_dir)


def record_demo(family: str, work: Path) -> dict:
    """Run the family's reference strategy on the demonstration's scene. Returns the scene, every request with the
    server's reply, the marked frames (label, step, how many commands came before, the simulator state) and the
    verdict, which must be a success."""
    sc = scenario(family, f"{family}-demonstration", FAMILIES[family]["demo"])
    ep = _episode(sc, work / f"demo-{family}")
    log: list[tuple[dict, dict]] = []
    frames: list[dict] = []

    def send(req: dict) -> dict:
        resp = ep.handle(req)
        log.append((req, resp))
        return resp

    def on_frame(label: str) -> None:
        qpos = [round(float(v), 6) + 0.0 for v in ep.backend.data.qpos]  # + 0.0: no -0.0, which differs by platform
        frames.append({"label": label, "step": ep.steps, "after": len(log), "qpos": qpos})

    run_strategy(family, send, on_frame)
    ep.close()
    if not ep.result.get("success"):
        raise SystemExit(f"the {family} demonstration did not score 1 (outcome {ep.result.get('outcome')})")
    return {"scenario": sc, "log": log, "frames": frames, "steps": ep.steps}


def _run(sc: dict, work: Path, drive: Callable[[Callable[[dict], dict]], None]) -> dict:
    ep = _episode(sc, Path(tempfile.mkdtemp(dir=work)))
    drive(ep.handle)
    if not ep.finished:
        ep.handle({"op": "done", "text": ""})
    ep.close()
    return ep.result


def contact(sc: dict, family: str, work: Path) -> np.ndarray:
    """Where the part the gripper touches (`contact` in FAMILIES) is at the start of an episode of `sc`."""
    ep = _episode(sc, Path(tempfile.mkdtemp(dir=work)))
    st = ep.handle({"op": "observe"})["result"]["state"]
    ep.close()
    group, name, field = FAMILIES[family]["contact"]
    return np.array(st[group][name][field], dtype=float)


def replay(commands: list[dict], shift=(0.0, 0.0, 0.0)) -> Callable[[Callable[[dict], dict]], None]:
    """The demonstration's stepping commands, verbatim or with every `move_to` target moved by `shift`, then `done`."""

    def drive(send: Callable[[dict], dict]) -> None:
        for req in commands:
            if req["op"] in STEPPING:
                if req["op"] == "move_to":
                    req = {**req, "pos": [round(float(p + s), 4) for p, s in zip(req["pos"], shift, strict=True)]}
                if not send(req).get("ok"):
                    return
        send({"op": "done", "text": "copied the demonstration"})

    return drive


def controls(tid: str, family: str, demo: dict, work: Path) -> dict:
    """The four checks on a target, each a fresh episode: reference strategy, no-op, verbatim copy, shifted copy."""
    sc = ONE_DEMO_TASKS[tid]
    commands = [req for req, _ in demo["log"]]
    shift = contact(sc, family, work) - contact(demo["scenario"], family, work)
    oracle = _run(sc, work, lambda send: run_strategy(family, send))
    return {
        "oracle": oracle["success"],
        "oracle_steps": oracle["steps_used"],
        "noop": _run(sc, work, lambda send: None)["success"],
        "copy": _run(sc, work, replay(commands))["success"],
        "shifted_copy": _run(sc, work, replay(commands, shift))["success"],
    }


# --------------------------------------------------------------------------------------------------
# The instruction
# --------------------------------------------------------------------------------------------------


def _num(v: float) -> str:
    return f"{round(float(v), 4):g}"


def cli(req: dict) -> str:
    """A request as the `robo` command line that sends it."""
    op = req["op"]
    if op == "observe":
        return "robo observe"
    if op == "move_to":
        s = "robo move-to " + " ".join(_num(v) for v in req["pos"])
        if req.get("grip") is not None:
            s += f" --grip {_num(req['grip'])}"
        if int(req.get("max_steps", 100)) != 100:
            s += f" --max-steps {int(req['max_steps'])}"
        if float(req.get("tol", 0.01)) != 0.01:
            s += f" --tol {_num(req['tol'])}"
        return s
    if op == "grip":
        return f"robo grip {_num(req['value'])}" + (f" --steps {int(req['steps'])}" if int(req["steps"]) != 15 else "")
    if op == "act":
        return "robo act " + " ".join(_num(v) for v in req["action"]) + f" --repeat {int(req.get('repeat', 1))}"
    if op in ("done", "give_up"):
        return f"robo {op.replace('_', '-')} {json.dumps(req.get('text', ''))}"
    raise ValueError(op)


def _shorten(state: dict, family: str) -> dict:
    group, name, keys = MOVING[family]
    out = {k: state[k] for k in ("hand_pos", "gripper_open", "holding") if k in state}
    out[group] = {name: {k: state[group][name][k] for k in keys}}
    return out


def trace(log: list[tuple[dict, dict]], frames: list[dict], family: str) -> str:
    """The demonstration as a console session: each command, numbered, then what `robo` printed for its reply, with
    every `state` after the first `robo observe` cut down to the gripper and the moving parts; the frames are noted
    after the command they follow."""
    after = {fr["after"]: i for i, fr in enumerate(frames, 1)}
    lines, seen = [], False
    for k, (req, resp) in enumerate(log, 1):
        lines.append(f"$ {cli(req)}  # command {k}")
        r = json.loads(json.dumps(resp))
        res = r.get("result")
        if isinstance(res, dict) and isinstance(res.get("state"), dict):
            if seen:
                res["state"] = _shorten(res["state"], family)
            seen = True
        lines.append(format_reply(r)[0])
        if k in after:
            lines.append(f"# frame {after[k]}: observations/demo_{after[k]}.png")
    lines.append("# the episode server judged the final state: success, reward 1")
    return "\n".join(lines)


def instruction(tid: str, family: str, demo: dict) -> str:
    F = FAMILIES[family]
    noun, n = F["noun"], len(demo["frames"])
    az = F["view_azimuth"]
    side = "the front" if az == 90 else ("the front left" if az < 90 else "the front right")
    frames = "\n".join(
        f"{i}. `demo_{i}.png`, after command {fr['after']} (step {fr['step']}): {fr['label']}."
        for i, fr in enumerate(demo["frames"], 1)
    )
    sc = ONE_DEMO_TASKS[tid]
    parts = [
        f"# {F['title']}\n",
        SCENE + "\n",
        f"**Goal:** {F['goal']}\n",
        f"**Success:** {F['success']}, judged by the episode server about 10 steps after you call `robo done`, with the "
        "gripper holding still.\n",
        "## One demonstration\n",
        f"The same skill was demonstrated on another {noun} in this same scene, with only that {noun} on the table: a "
        "reference controller did it through `robo`, and the episode server scored it 1. Your "
        f"{noun} is a different one, in another place. Work out from the demonstration how the skill is done, and do "
        f"it on your {noun}.\n",
        f"At the start of your episode, {n} pictures of the demonstration are placed in your working directory, "
        f"`observations/demo_1.png` to `observations/demo_{n}.png`. Each shows one moment of it from two cameras: "
        f"from {side} and above (left), and from straight above (right; the back of the table is at the top, and the "
        "gripper is drawn see-through so that it does not hide what it holds).\n",
        frames + "\n",
        f"These are the demonstration's `robo` commands and what `robo` printed for each. From command 2 on, a reply's "
        f"`state` is shortened to the gripper and the parts of the {noun} that move.\n",
        "```console\n" + trace(demo["log"], demo["frames"], family) + "\n```\n",
        "## What `robo observe` shows\n",
        "- `hand_pos`: the gripper's tool point (between the fingertips), metres. `gripper_open`: 0 = closed, 1 = fully "
        "open (10 cm gap). `holding`: names of objects currently touching the fingers.\n"
        f"- {F['fields']}\n",
        TT.GRIP_NOTE.rstrip("\n") + "\n",
        MOVE_TO + "\n",
        "## Task rules\n",
        f"- Step budget: {sc['max_steps']} simulated steps (one step = 20 ms); the demonstration used {demo['steps']}. "
        "Wall-clock limit: 20 minutes.\n"
        "- `robo done` ends the episode; call it once, when you are finished.\n",
    ]
    return "\n".join(parts) + "\n" + ROBO_USAGE


# --------------------------------------------------------------------------------------------------
# Task folders
# --------------------------------------------------------------------------------------------------


def task_meta(tid: str, family: str, demo: dict) -> dict:
    F = FAMILIES[family]
    sc = ONE_DEMO_TASKS[tid]
    dsc = demo["scenario"]
    scen = {k: sc[k] for k in ("id", "title", "family", "objects", "fixtures", "goals", "max_steps")}
    scen["demo"] = {
        "objects": dsc["objects"],
        "fixtures": dsc["fixtures"],
        "view_azimuth": F["view_azimuth"],
        "steps": demo["steps"],
        "commands": [req for req, _ in demo["log"]],
        "frames": demo["frames"],
    }
    return {
        "task": {"name": f"robouse/{tid}", "description": f"{F['title']}, after one demonstration"},
        "metadata": {
            "source_benchmark": "robouse original, after DemoMimic (Sharma et al., arXiv 2609.01938)",
            "source_task": family,
            "source_suite": SUITE,
            "suite": SUITE,
            "category": "in-context-imitation",
            "difficulty": "medium",
            "tags": ["one-demo", "in-context", "imitation", family],
            "demonstration": F["demo_is"],
            "differs": sc["differs"],
        },
        "agent": {"timeout_sec": 1200},
        "verifier": {"timeout_sec": 120},
        "robouse": {
            "id": tid,
            "backend": "tabletop",
            "seed": 0,
            "max_steps": sc["max_steps"],
            "camera": "front",
            "skills": True,
            "success_mode": "final",
            "scenario": scen,
        },
    }


ORACLE = (
    "#!/bin/bash\n"
    "# Reference solution: the family's strategy (onedemo.py), the one the demonstration ran, on this task's object,\n"
    "# through the robo socket, reading only the public observation.\n"
    "set -euo pipefail\n"
    "python -m robouse.oracle --backend tabletop_onedemo --env {tid}\n"
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "tasks" / SUITE))
    ap.add_argument("--frames", help="also write each demonstration's frames to this folder, to look at them")
    a = ap.parse_args()
    if a.frames:
        from robouse.core import gl

        gl.auto_select()  # --frames renders; the episodes here record no video
    out = Path(a.out)
    work = Path(tempfile.mkdtemp(prefix="one-demo-"))
    rows, failed = [], []
    try:
        demos = {family: record_demo(family, work) for family in FAMILIES}
        for family, demo in demos.items():
            print(f"{family}: demonstration scored 1 in {demo['steps']} steps, {len(demo['log'])} commands")
            if a.frames:
                from PIL import Image

                from robouse.backends.tabletop.backend import demo_frames

                d = Path(a.frames)
                d.mkdir(parents=True, exist_ok=True)
                block = task_meta(next(iter(FAMILIES[family]["targets"])), family, demo)["robouse"]["scenario"]["demo"]
                for name, img in demo_frames(block).items():
                    Image.fromarray(img).save(d / f"{family}-{name}")
        if out.exists():
            shutil.rmtree(out)
        for tid, sc in ONE_DEMO_TASKS.items():
            family = sc["family"]
            c = controls(tid, family, demos[family], work)
            rows.append((tid, c))
            if not c["oracle"] or c["noop"] or c["copy"] or c["shifted_copy"]:
                failed.append(tid)
                continue
            meta = task_meta(tid, family, demos[family])
            d = out / tid
            write_task(d, meta, instruction(tid, family, demos[family]), ORACLE.format(tid=tid), TT.VERIFY)
            fm = yaml.safe_load((d / "task.md").read_text().split("---", 2)[1])
            want = json.loads(json.dumps(meta["robouse"]["scenario"]))
            assert fm["robouse"]["scenario"] == want, f"YAML round trip changed the scenario of {tid}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n| Task | Reference solution | No-op | Demonstration copied | Copied, shifted to the contact |")
    print("|---|---|---|---|---|")
    for tid, c in rows:
        print(
            f"| {tid} | {int(c['oracle'])} ({c['oracle_steps']} steps) | {int(c['noop'])} | {int(c['copy'])} | "
            f"{int(c['shifted_copy'])} |"
        )
    if failed:
        raise SystemExit(f"not written, a control failed: {', '.join(failed)}")
    print(f"\nwrote {len(rows)} tasks to {out}")


if __name__ == "__main__":
    main()
