"""robo-dev: develop and submit a robot program (the `program` harnesses of Robo Use; see PROGRAM.md).

  robo-dev run [FILE] [--keyframes N] [--label TEXT]   run FILE (default solution/solve.py) on a fresh reset
  robo-dev look                                         a fresh reset: both camera views and the robot's state
  robo-dev submit [FILE]                                submit FILE (default solution/solve.py); the last one counts
  robo-dev give-up "REASON"                             decline: nothing runs on the scored episode, which ends with
                                                        REASON (a later submission replaces it)
  robo-dev status                                       development runs used and left, submissions

Each run is a fresh reset of the scene the submission is scored on, through the trial's broker. A run reports what
the program printed, its error, its tool calls, the robot's state and camera keyframes (the task's cameras side by side),
under dev-runs/NNNN/. It is not scored and reports no judgment of the run.

Standard library, numpy and Pillow only: this file runs on Robo Use's own Python, without the robouse package.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aspire_programs as programs  # type: ignore[import-not-found]

WORKSPACE = Path(__file__).resolve().parents[2]
CALL = "\n\nresult = solve(robo)\n"
MOTION = ("act", "move_to", "grip", "skill")


class Timeout(Exception):
    pass


def _alarm(signum: int, frame: object) -> None:
    raise Timeout()


def base() -> str:
    url = os.environ.get("ROBOUSE_PRACTICE_URL", "").rstrip("/")
    if not url:
        sys.exit("robo-dev: no development broker in this session (ROBOUSE_PRACTICE_URL is not set)")
    return url


def next_run_dir() -> Path:
    """dev-runs/NNNN, the next number; created once its run has started."""
    root = WORKSPACE / "dev-runs"
    root.mkdir(exist_ok=True)
    n = 1 + max((int(p.name) for p in root.iterdir() if p.name.isdigit()), default=0)
    return root / f"{n:04d}"


def start(label: str) -> tuple[str, dict]:
    status, out = programs.http_json(f"{base()}/episodes", {"label": label}, timeout=7200)
    if status != 200:
        sys.exit(f"robo-dev: no development run: {out.get('error') or f'HTTP {status}'}")
    return str(out["id"]), out.get("info") or {}


def end(eid: str) -> dict:
    status, out = programs.http_json(f"{base()}/episodes/{eid}/finish", {"op": "give_up"}, timeout=900)
    return out if status == 200 else {"error": out.get("error")}


def cameras_of(info: dict) -> list[str]:
    """The task's cameras, as `robo.info()` lists them (empty: the episode's default camera)."""
    return [c["name"] for c in info.get("cameras") or [] if isinstance(c, dict) and c.get("name")]


class Keyframes:
    """The task's cameras side by side after reset, after motion calls (up to `limit`) and at the end, with the
    robot's state."""

    def __init__(self, send: Any, d: Path, cameras: list[str], limit: int):
        self.send, self.d, self.cameras, self.limit = send, d, cameras, limit
        self.n = 0
        self.names: list[str] = []  # the cameras in each sheet, left to right
        self.error = ""
        self.log = open(d / "keyframes.jsonl", "w")  # noqa: SIM115 - closed by close()
        (d / "frames").mkdir()

    def save(self, label: str, force: bool = False) -> None:
        if not force and self.n >= self.limit:
            return
        spec: dict[str, Any] = {"format": "png", **({"cameras": self.cameras} if self.cameras else {})}
        reply = self.send({"op": "observe", "inline": spec})
        res = reply.get("result") or {}
        if not reply.get("ok") or not res.get("images"):
            self.error = str(reply.get("error") or "the episode returned no picture")
            return
        from PIL import Image

        self.names = list(res["images"])
        imgs = [Image.open(io.BytesIO(base64.b64decode(res["images"][c]))).convert("RGB") for c in self.names]
        w = sum(i.width for i in imgs)
        h = max(i.height for i in imgs)
        sheet = Image.new("RGB", (w, h))
        x = 0
        for i in imgs:
            sheet.paste(i, (x, 0))
            x += i.width
        name = f"frames/k{self.n:03d}-{label}.png"
        sheet.save(self.d / name)
        row = {"k": self.n, "after": label, "file": name, "steps_used": res.get("steps_used"), "state": res.get("state")}
        self.log.write(json.dumps(row) + "\n")
        self.log.flush()
        self.n += 1

    def close(self) -> None:
        self.log.close()


def cmd_run(a: argparse.Namespace) -> int:
    path = Path(a.file)
    source = path.read_text()
    try:
        programs.validate(source + CALL)
    except programs.ProgramRejected as e:
        print(f"robo-dev: {e}", file=sys.stderr)
        return 2
    d = next_run_dir()
    eid, info = start(a.label or d.name)
    d.mkdir()
    (d / "program.py").write_text(source)
    send = programs.practice_transport(base(), eid)
    calls = open(d / "calls.jsonl", "w")  # noqa: SIM115 - written by the call hook, closed below
    keys = Keyframes(send, d, cameras_of(info), max(0, a.keyframes))

    def on_call(span: dict) -> None:
        calls.write(json.dumps(span) + "\n")
        calls.flush()

    keys.save("reset", force=True)
    api = programs.Api(send, info, on_call=on_call, after_motion=lambda name: keys.save(name))
    t0 = time.time()
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, float(a.timeout))
    try:
        ex = programs.execute(source + CALL, api)
    except Timeout:
        ex = programs.Execution(False, None, "", {"type": "Timeout", "message": f"the program ran over {a.timeout} s"})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
    wall = round(time.time() - t0, 1)
    keys.save("end", force=True)
    keys.close()
    calls.close()
    ended = end(eid)
    (d / "stdout.txt").write_text(ex.stdout)
    summary = {
        "run": d.name,
        "ok": ex.ok,
        "error": ex.error,
        "result": ex.result,
        "tool_calls": api.calls,
        "steps_used": api.steps_used,
        "max_steps": api.max_steps,
        "episode": api.finished or "running when the program returned",
        "wall_s": wall,
        "keyframes": keys.n,
        "keyframe_cameras": keys.names,
        **({"keyframe_error": keys.error} if keys.error else {}),
        "ended": ended.get("error") or "yes",
    }
    (d / "summary.json").write_text(json.dumps(summary, indent=2))
    tail = ex.stdout[-3000:]
    if tail:
        print("---- program output (tail) ----\n" + tail.rstrip())
    print("---- run ----")
    print(json.dumps(summary, indent=2))
    print(f"files: {d.relative_to(WORKSPACE)}/ (summary.json, stdout.txt, calls.jsonl, keyframes.jsonl, frames/)")
    return 0 if ex.ok else 1


def cmd_look(a: argparse.Namespace) -> int:
    d = next_run_dir()
    eid, info = start(f"{d.name} look")
    d.mkdir()
    send = programs.practice_transport(base(), eid)
    keys = Keyframes(send, d, cameras_of(info), 1)
    keys.save("reset", force=True)
    keys.close()
    (d / "info.json").write_text(json.dumps(info, indent=2))
    state = send({"op": "observe"}).get("result")
    end(eid)
    rel = d.relative_to(WORKSPACE)
    print(json.dumps({"state": (state or {}).get("state", state)}, indent=2))
    if keys.n:
        print(f"view: {rel}/frames/k000-reset.png (left to right: {', '.join(keys.names)})")
    else:
        print(f"no picture: {keys.error}")
    print(f"robo.info(): {rel}/info.json")
    return 0


def cmd_submit(a: argparse.Namespace) -> int:
    source = Path(a.file).read_text()
    status, out = programs.http_json(f"{base()}/submit", {"source": source}, timeout=120)
    if status != 200:
        print(f"robo-dev: not submitted: {out.get('error') or f'HTTP {status}'}", file=sys.stderr)
        return 1
    print(f"submitted {a.file} as submission {out['submission']} (sha256 {out['sha256'][:12]}); the last one counts")
    return 0


def cmd_give_up(a: argparse.Namespace) -> int:
    status, out = programs.http_json(f"{base()}/give_up", {"reason": a.reason}, timeout=60)
    if status != 200:
        print(f"robo-dev: not recorded: {out.get('error') or f'HTTP {status}'}", file=sys.stderr)
        return 1
    print("recorded: no program runs on the scored episode, which ends with your reason (a later submit replaces this)")
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    status, out = programs.http_json(f"{base()}/status", None, timeout=60)
    print(json.dumps(out, indent=2))
    return 0 if status == 200 else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="robo-dev", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a program on a fresh reset (not scored)")
    r.add_argument("file", nargs="?", default="solution/solve.py")
    r.add_argument("--keyframes", type=int, default=24, help="keyframes after motion calls (reset and end are extra)")
    r.add_argument("--label", default="")
    r.add_argument("--timeout", type=float, default=1800.0, help="seconds before the program is stopped")
    sub.add_parser("look", help="a fresh reset: both views and the robot's state")
    s = sub.add_parser("submit", help="submit a program; the last submission is scored")
    s.add_argument("file", nargs="?", default="solution/solve.py")
    g = sub.add_parser("give-up", help="decline: nothing runs on the scored episode; a later submission replaces it")
    g.add_argument("reason")
    sub.add_parser("status", help="runs used and left, submissions")
    a = p.parse_args()
    return {"run": cmd_run, "look": cmd_look, "submit": cmd_submit, "give-up": cmd_give_up, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
