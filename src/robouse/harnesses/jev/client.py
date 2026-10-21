"""`jev` harness: TypeSafe's Jev drives a Robo Use episode with typed decisions. Standard library only.

Jev is TypeSafe's System One model: it answers typed questions about a state (a Choice among named options, a Score on
an ordered rubric, a Noul yes/no probability) with a probability for every option, and generates no text, code or tool
calls. So the loop is this client's, and every decision in it is Jev's. The runner copies this file into the trial
workspace and runs it inside the agent sandbox, on its own Python in isolated mode (`-I -S`); it reaches the robot only
through the `robo` socket, like every harness, and Jev sees only what `robo observe` returned.

One decision:
  1. `observe`, the state any agent gets;
  2. the profile builds Jev's state from it (below);
  3. one request to TypeSafe's System One endpoint (POST <base>/v1/systemone) asks the profile's questions about it;
  4. the profile turns the answers into one `robo` command, which the client sends.
Until Jev answers that the task is finished (then `robo done`) or the episode ends (step budget, wall clock). The
simulation waits while a request is out: the episode server steps only when asked. Only Jev's own "finished" sends
`robo done`. The client never gives up itself (on a task that rewards refusing, a give-up counts as one), and an API
failure, or a `robo` request that fails while the episode is open, leaves the episode open for the runner to close: an
infrastructure failure, not a score.

Profile `nav`, Robo Use's nav suite, in the protocol of Dimensional's "Can Jev Nav?" study
(research.dimensional.org/system-one-navigation; its TypeSafe agent is in dimensionalOS/dimos, Apache-2.0):
- One decision per 0.5 s of simulated time, the study's 2 Hz, executed as the task's `drive X Y YAW 0.5` skill
  (Dimensional's discrete command: 0.5 m/s, 0.3 m/s sideways, 0.8 rad/s).
- Four questions per decision: `drive.x` (forward, none, backward), `drive.y` (left, none, right) and `drive.yaw`
  (turn_left, none, turn_right), each a Choice, and `task` (continue or finished). The study also asked `stop` (a Noul)
  and `target` (which detected object the goal names). Robo Use's observation names the target and carries the
  episode's own arrival check, so neither is asked: stopping is finishing, and holding still without finishing only
  spends the budget.
- The state is the observation, filtered and with the arithmetic done here, since Jev reads words better than numbers
  and does best with only what the questions need (TypeSafe's notes on Jev 1.13): the target's bearing says which way
  round is shorter when it is behind, each way past a blocked line to the target carries its own bearing, the last
  drive command is given in words, and `going_around` keeps the side the robot's own decisions began to go round (Jev
  is stateless; the study's state keeps the same memory). The list of visible furniture is left out: no question
  reads it.

Environment: ROBOUSE_SOCKET (from the runner), TYPESAFE_API_KEY and, when set, TYPESAFE_BASE_URL (the harness passes
them to this process only), ROBOUSE_JEV_CONFIG ({"model", "profile", "prices"}: USD per 1M tokens by model id, for
the cost of each decision), ROBOUSE_TASK_LANGUAGE (the goal sentence). Output: one JSON line per event on stdout
(agent/stdout.jsonl): start (the questions), decision (the state Jev saw, each answer with its probabilities and
confidence, the token usage and cost, and the robo requests made for it), retry, end and error.
"""

from __future__ import annotations

import http.client
import json
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.typesafe.ai"  # TypeSafe's SDK default; TYPESAFE_BASE_URL overrides it, as in the SDK
TIMEOUT_S = 60.0
# Retried as TypeSafe's SDK retries: 408, 429 (rate limit), 5xx and 529 (overloaded), and connection failures, with
# exponential backoff that honours retry-after; at most MAX_ATTEMPTS tries and MAX_RETRY_WAIT_S of waiting in all
MAX_ATTEMPTS = 6
MAX_RETRY_WAIT_S = 120.0
STEPPING = ("act", "move_to", "grip", "skill", "done", "give_up")


def emit(**kw) -> None:
    print(json.dumps(kw, default=str), flush=True)


def now() -> float:
    return round(time.time(), 3)


# ======================================================================================================================
# The episode socket
# ======================================================================================================================


class Robot:
    """The `robo` socket, with every request recorded in order: each event lists the requests made for it, so the
    trajectory converter gives each decision its own entries of the episode trace."""

    def __init__(self, sock: str):
        self.sock = sock
        self.requests: list[str] = []
        self.finished = ""  # why the episode ended, once it has
        self.steps_used = 0

    def send(self, req: dict) -> dict:
        self.requests.append(label(req))
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3600 if req.get("op") in STEPPING else 120)
        try:
            s.connect(self.sock)
            s.sendall((json.dumps(req) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
            resp = json.loads(buf.decode() or '{"ok": false, "error": "empty response"}')
        except (FileNotFoundError, ConnectionRefusedError):
            resp = {"ok": False, "error": "episode server is not running"}
        except (OSError, ValueError) as e:  # a timeout, a reset connection, a reply cut short or not JSON
            resp = {"ok": False, "error": f"robo request failed: {type(e).__name__}: {e}"[:500]}
        finally:
            s.close()
        if not isinstance(resp, dict):
            resp = {"ok": False, "error": f"robo reply is not an object: {str(resp)[:200]}"}
        r: dict = resp["result"] if isinstance(resp.get("result"), dict) else {}
        if isinstance(r.get("steps_used"), int):
            self.steps_used = r["steps_used"]
        if "episode" in r:
            self.finished = str(r["episode"])
        elif not resp.get("ok") and any(
            w in str(resp.get("error")) for w in ("episode finished", "episode server is not running")
        ):
            self.finished = str(resp.get("error"))
        return resp

    def take_requests(self) -> list[str]:
        out, self.requests = self.requests, []
        return out


def label(req: dict) -> str:
    """The `robo` command line a request corresponds to."""
    op = req.get("op")
    if op == "skill":
        return " ".join(["robo skill", str(req.get("name")), *(str(a) for a in req.get("args") or [])])
    if op in ("done", "give_up"):
        return f"robo {op.replace('_', '-')} {json.dumps(req.get('text', ''))}"
    return f"robo {op}"


# ======================================================================================================================
# TypeSafe's System One endpoint
# ======================================================================================================================


class ApiError(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(f"TypeSafe {'HTTP ' + str(status) if status else 'request'} failed: {message}")
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are not followed: urllib would resend the Authorization header to wherever one points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def header_safe(key: str) -> bool:
    """Whether a key can go in the Authorization header as it is: printable ASCII without spaces. For a line break
    inside, http.client raises an error that quotes the whole header value, key and all."""
    return all(33 <= ord(c) <= 126 for c in key)


class SystemOne:
    """One POST per decision: {"model", "state", "questions"} in, {"model", "answers", "usage"} out."""

    def __init__(self, base_url: str, key: str, model: str, timeout: float = TIMEOUT_S):
        self.url = base_url.rstrip("/") + "/v1/systemone"
        self.key, self.model, self.timeout = key, model, timeout
        self.attempts = 0  # of the last call

    def ask(self, state: dict, questions: dict) -> dict:
        request = {"model": self.model, "state": finite(state), "questions": questions}
        body = json.dumps(request, allow_nan=False).encode()
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "User-Agent": "robouse-jev",
        }
        waited = 0.0
        self.attempts = 0
        while True:
            self.attempts += 1
            status: int | None = None
            retry_after = None
            try:
                req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
                with OPENER.open(req, timeout=self.timeout) as r:
                    raw = r.read().decode("utf-8", "replace")
                try:
                    out = json.loads(raw)
                except ValueError:
                    raise ApiError(200, f"the response is not JSON: {raw[:300]!r}") from None
                if not isinstance(out, dict):
                    raise ApiError(200, "the response is not a JSON object")
                return out
            except urllib.error.HTTPError as e:
                status, retry_after = e.code, e.headers.get("retry-after") if e.headers else None
                try:
                    detail = e.read().decode("utf-8", "replace")[:500] if e.fp is not None else str(e.reason)
                except (OSError, http.client.HTTPException):  # the body was cut short
                    detail = str(e.reason)
                if status not in (408, 429, 529) and not 500 <= status < 600:
                    raise ApiError(status, detail) from None
            # connection refused or reset, DNS, TLS, timeouts, a response cut short
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                detail = str(getattr(e, "reason", e))[:500]
            if self.attempts >= MAX_ATTEMPTS:
                raise ApiError(status, f"{detail} (after {self.attempts} attempts)")
            wait = backoff(self.attempts, retry_after)
            if waited + wait > MAX_RETRY_WAIT_S:
                raise ApiError(status, f"{detail} (stopped retrying after {waited:.0f} s)")
            emit(type="retry", t=now(), status=status, attempt=self.attempts, wait_s=round(wait, 2), error=detail[:300])
            time.sleep(wait)
            waited += wait


def finite(value):
    """`value` with every NaN or infinity replaced by null: TypeSafe accepts finite numbers only (HTTP 400)."""
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    return value


def backoff(attempt: int, retry_after: str | None) -> float:
    """Seconds before the next try: the server's retry-after when it gives one (at most 60), else 0.5 s doubling up
    to 8 s, with a little jitter."""
    try:
        if retry_after is not None:
            return max(0.0, min(60.0, float(retry_after)))
    except ValueError:  # an HTTP date: back off as usual
        pass
    return min(8.0, 0.5 * 2 ** (attempt - 1)) * (1 + 0.25 * random.random())


def _number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def check_answers(resp: dict, questions: dict) -> dict:
    """The response's answers, after checking that each question got an answer of its own type: for a Choice, one of
    its options, with a number for each option's probability and for the confidence; for a Noul, a probability.
    Anything else raises ApiError, and nothing is executed."""
    answers = resp.get("answers")
    if not isinstance(answers, dict):
        raise ApiError(200, f"the response has no answers: {json.dumps(resp)[:300]}")
    for qid, q in questions.items():
        a = answers.get(qid)
        if not isinstance(a, dict) or a.get("type") != q["type"]:
            raise ApiError(200, f"no {q['type']} answer for {qid!r}: {json.dumps(a)[:300]}")
        if q["type"] == "choice":
            probs = a.get("probabilities")
            if not isinstance(a.get("choice"), str) or a["choice"] not in q["criteria"]:
                raise ApiError(200, f"the answer for {qid!r} is not one of its options: {json.dumps(a)[:300]}")
            if not isinstance(probs, dict) or not all(_number(v) for v in probs.values()):
                raise ApiError(200, f"the answer for {qid!r} has no probabilities: {json.dumps(a)[:300]}")
            if "confidence" in a and not _number(a["confidence"]):
                raise ApiError(200, f"the answer for {qid!r} has a confidence that is not a number")
        elif q["type"] == "noul" and not _number(a.get("noul")):
            raise ApiError(200, f"the answer for {qid!r} has no probability: {json.dumps(a)[:300]}")
    return answers


def tokens(usage: dict, name: str) -> int:
    """A token count from a response's usage; 0 when it is missing or not a number."""
    v = usage.get(name)
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def usage_cost(usage: dict, prices: dict, *models: str) -> float | None:
    """USD for one response: its tokens at the first listed model's price per 1M tokens (the version that answered,
    then the model asked for). TypeSafe bills input tokens; output tokens are free."""
    price = next((prices[m] for m in models if m in prices), None)
    if price is None:
        return None
    tokens_in, tokens_out = tokens(usage, "input_tokens"), tokens(usage, "output_tokens")
    return round((tokens_in * float(price["input"]) + tokens_out * float(price.get("output", 0.0))) / 1e6, 10)


def compact(answer: dict) -> dict:
    """An answer as recorded per decision: the choice (or the Noul's probability), the probabilities, the confidence."""
    keep = ("type", "choice", "probabilities", "confidence", "noul", "score")
    return {k: answer[k] for k in keep if k in answer}


# ======================================================================================================================
# Profile nav: the nav suite, Dimensional's "Can Jev Nav?" protocol
# ======================================================================================================================

SECTORS = ("ahead", "ahead_left", "left", "behind_left", "behind", "behind_right", "right", "ahead_right")
NAV_SECONDS = 0.5  # simulated time per decision: the study's 2 Hz
FORGET_SIDE_S = 3.0  # the line to the target clear this long: the side being gone round is forgotten (the study's)
AXES = {
    "x": ("forward", "none", "backward"),
    "y": ("left", "none", "right"),
    "yaw": ("turn_left", "none", "turn_right"),
}

NAV_TASK = (
    "You are a mobile robot base in a home of rooms joined by doorways, with furniture along the walls. Everything "
    "here is relative to the robot; there is no map. `goal`: what to do. `target`: the thing to reach: `bearing` is "
    "ahead, ahead_left, left, behind_left, behind_right, right or ahead_right (ahead means within 22.5 degrees; "
    "behind_left and behind_right say which way round is shorter), `distance` is touching (under 0.5 m), "
    "near (under 1.5 m), mid (under 4 m) or far, `visible` says whether a straight line to it is free, and `arrived` "
    "is the episode's own check that the robot is within 1 m of it and can see it. `way_to_target`: whether the "
    "straight line to the target is `blocked`, by what (`blocked_by`), and the ways past (`open_sides`, left or right "
    "of that line, each with its own `bearing`); `going_around` is the side the robot already began to go round. "
    "`free_space`: how far the robot can drive in each of the eight directions (`state` open, narrow or blocked). "
    "`robot`: its motion, the drive command it was last given, what happened over the last 8 seconds "
    "(`recent.pattern`: progressing, not_progressing, or stuck when it drives without moving) and its collisions so far."
)
NAV_STEER = (
    "The steering bearing is `target.bearing` while `way_to_target.blocked` is false. While it is true, it is the "
    "`bearing` of one entry of `way_to_target.open_sides`: the one whose `side` is `way_to_target.going_around` when "
    "that is given, else the one nearer to ahead. With no entry, it is ahead while `free_space.ahead.state` is open; "
    "otherwise it is on the side `robot.last_drive.yaw` turned to (keep turning that way), and when the robot did not "
    "turn, it is the open direction of `free_space` nearest to ahead. Turn toward the steering bearing, and drive when "
    "it is ahead."
)


def _opt(what: str, not_for: str, examples: list[str]) -> dict:
    return {"what": what, "not_for": not_for, "examples": examples}


def nav_questions() -> dict:
    """The four questions of one decision. Option names are the `drive` skill's own arguments; each option says what
    it is for, what it is not for, and examples, as in the study's questions."""
    return {
        "drive.x": {
            "type": "choice",
            "instructions": {
                "question": "Should the robot drive forward, drive backward, or neither, to get closer to the target "
                "named in `goal`?",
                "context": NAV_STEER,
            },
            "criteria": {
                "forward": _opt(
                    "the steering bearing is ahead, ahead_left or ahead_right, and `free_space.ahead.state` is not "
                    "blocked",
                    "the steering bearing is left, right, behind_left or behind_right (turn first); "
                    "`target.arrived` is true; `free_space.ahead.state` is blocked",
                    ["target ahead, mid, way not blocked", "way blocked by a wall, open side ahead_left, ahead open"],
                ),
                "none": _opt(
                    "the steering bearing is left, right, behind_left, behind_right or on one side, so the robot turns "
                    "first; or `target.arrived` is true",
                    "the steering bearing is ahead, ahead_left or ahead_right",
                    ["target behind_right, far", "target ahead, near, arrived"],
                ),
                "backward": _opt(
                    "`free_space.ahead.state` is blocked while the steering bearing is ahead, ahead_left or "
                    "ahead_right, or `robot.recent.pattern` is stuck: back away to make room",
                    "`free_space.ahead.state` is narrow or open and the robot is not stuck",
                    ["open side ahead, ahead blocked", "ahead blocked, pattern stuck"],
                ),
            },
        },
        "drive.y": {
            "type": "choice",
            "instructions": {
                "question": "Should the robot slide sideways to its left, to its right, or not at all, to step past "
                "something right in front of it?",
                "context": "The steering bearing is the one the other drive questions use: `target.bearing`, or "
                "while `way_to_target.blocked` is true the `bearing` of an entry of `way_to_target.open_sides`.",
            },
            "criteria": {
                "left": _opt(
                    "a sidestep: the steering bearing is ahead, `free_space.ahead.state` is blocked and "
                    "`free_space.left.state` is open",
                    "the steering bearing is off to a side (turn instead); `free_space.ahead.state` is not blocked; "
                    "`free_space.left.state` is not open",
                    ["target ahead, ahead blocked, left open, right narrow"],
                ),
                "none": _opt(
                    "every other case",
                    "the steering bearing is ahead, `free_space.ahead.state` is blocked and one side is open",
                    ["target left, far", "target ahead, ahead open"],
                ),
                "right": _opt(
                    "a sidestep: the steering bearing is ahead, `free_space.ahead.state` is blocked and "
                    "`free_space.right.state` is open",
                    "the steering bearing is off to a side (turn instead); `free_space.ahead.state` is not blocked; "
                    "`free_space.right.state` is not open",
                    ["target ahead, ahead blocked, right open, left blocked"],
                ),
            },
        },
        "drive.yaw": {
            "type": "choice",
            "instructions": {
                "question": "Should the robot turn left (counter-clockwise), turn right (clockwise), or not turn, so "
                "that the steering bearing comes ahead?",
                "context": NAV_STEER,
            },
            "criteria": {
                "turn_left": _opt(
                    "the steering bearing is ahead_left, left or behind_left, or on the left side",
                    "the steering bearing is ahead or on the right; `target.arrived` is true",
                    ["target left, far, way not blocked", "way blocked by a wall, open side ahead_left"],
                ),
                "none": _opt(
                    "the steering bearing is ahead, or `target.arrived` is true",
                    "the steering bearing is off to either side or behind",
                    ["target ahead, mid", "target ahead_left, arrived"],
                ),
                "turn_right": _opt(
                    "the steering bearing is ahead_right, right or behind_right, or on the right side",
                    "the steering bearing is ahead or on the left; `target.arrived` is true",
                    ["target behind_right, near", "way blocked by a bed, open side right"],
                ),
            },
        },
        # continue first: Jev 1.13 leans toward a Choice's first option, and a wrong "finished" ends the episode
        "task": {
            "type": "choice",
            "instructions": {
                "question": "Is the task in `goal` complete, or should the robot keep going?",
                "context": "`target.arrived` is the episode's own check: within 1 m of the target with a clear line "
                "of sight to it.",
            },
            "criteria": {
                "continue": _opt(
                    "`target.arrived` is false",
                    "`target.arrived` is true",
                    ["target ahead, near, not arrived", "target behind a wall, touching, not arrived"],
                ),
                "finished": _opt(
                    "`target.arrived` is true: the robot is next to the target and can see it",
                    "`target.arrived` is false, however near the target is",
                    ["target ahead, touching, arrived"],
                ),
            },
        },
    }


def bearing_word(deg: float) -> str:
    """The nav backend's 8-way word for a robot-frame bearing in degrees (counter-clockwise positive; ahead within 22.5
    degrees, then 45-degree sectors), except that behind says which way round is shorter, as in the study's state."""
    d = (float(deg) + 180.0) % 360.0 - 180.0
    word = SECTORS[int(((d + 22.5) % 360.0) // 45.0)]
    if word == "behind":
        return "behind_left" if d >= 0 else "behind_right"
    return word


def wrap(deg: float) -> float:
    return round((float(deg) + 180.0) % 360.0 - 180.0, 1)


class NavMemory:
    """What the client keeps between decisions (Jev is stateless): the last drive command, and the side of the
    blocked line to the target that the robot's own decisions began to go round."""

    def __init__(self) -> None:
        self.last_drive = {axis: "none" for axis in AXES}
        self.side: str | None = None
        self.offered: dict[str, float] = {}  # open side -> its bearing_deg, as the last decision saw them
        self.clear_s = 0.0

    def going_around(self, way: dict) -> str | None:
        """The side the last decision steered to, when exactly one listed side fits it (it turned toward that side's
        bearing, or drove at it while it was ahead). Kept while the way stays blocked and the side stays listed;
        forgotten once the line has been clear for longer than FORGET_SIDE_S, as in the study."""
        sides = {
            str(o.get("side")): float(o.get("bearing_deg") or 0.0)
            for o in way.get("open_sides") or []
            if isinstance(o, dict)
        }
        if self.side is None and self.offered:
            turn = {"turn_left": 1, "turn_right": -1}.get(self.last_drive["yaw"], 0)
            fits = [
                side
                for side, deg in self.offered.items()
                if (turn and turn * deg > 22.5) or (not turn and self.last_drive["x"] == "forward" and abs(deg) <= 22.5)
            ]
            if len(fits) == 1:
                self.side = fits[0]
        self.offered = sides
        if not way.get("blocked"):
            self.clear_s += NAV_SECONDS
            if self.clear_s > FORGET_SIDE_S:
                self.side = None
            return None
        self.clear_s = 0.0
        if self.side not in sides:
            self.side = None  # that way past has closed
        return self.side


def nav_state(observed: dict, goal: str, memory: NavMemory) -> dict:
    """Jev's state from one observation (`robo observe` -> state): the target, the way to it, the free space around
    and the robot's own motion, with the arithmetic done here (see the module docstring). Nothing is added that the
    observation does not hold, apart from the client's own last command and the side it began going round."""
    target = dict(observed.get("goal") or {})
    deg = target.get("bearing_deg")
    if isinstance(deg, (int, float)):
        target["bearing"] = bearing_word(deg)
    way = dict(observed.get("way_to_target") or {})
    if isinstance(deg, (int, float)) and isinstance(way.get("open_sides"), list):
        # the backend lists a way past 45 degrees to either side of the line to the target (counter-clockwise is left)
        way["open_sides"] = [
            {"side": s, "bearing": bearing_word(deg + off), "bearing_deg": wrap(deg + off)}
            for s, off in (("left", 45.0), ("right", -45.0))
            if s in way["open_sides"]
        ]
    going = memory.going_around(way)
    if going:
        way["going_around"] = going
    robot = dict(observed.get("robot") or {})
    robot["last_drive"] = dict(memory.last_drive)
    label = target.get("label") or "target"
    return {
        "task": NAV_TASK,
        "goal": goal or f"Drive to the {label} and stop next to it.",
        "target": target,
        "way_to_target": way,
        "free_space": observed.get("free_space") or {},
        "robot": robot,
    }


def nav_check(info: dict) -> str | None:
    """Why the nav profile cannot drive this task, or None: it needs the nav backend's `drive` skill."""
    if info.get("backend") != "nav":
        return (
            f"the jev harness's nav profile drives the nav suite; this task runs on the {info.get('backend')!r} backend"
        )
    skills = {s.get("name"): s for s in (info.get("embodiment") or {}).get("skills") or [] if isinstance(s, dict)}
    args = {a.get("name"): tuple(a.get("choices") or ()) for a in (skills.get("drive") or {}).get("args") or []}
    offered = any(str(s).startswith("drive ") for s in info.get("skills") or [])
    if not offered or any(args.get(axis) != choices for axis, choices in AXES.items()):
        return (
            "the nav profile needs the task's `drive` skill (Dimensional's discrete command), which it does not offer"
        )
    return None


def nav_command(answers: dict) -> dict:
    """The `robo` request the answers make: `done` when Jev answers finished, else the drive skill for one decision."""
    task = answers["task"]
    if task["choice"] == "finished":
        p = (task.get("probabilities") or {}).get("finished")
        return {"op": "done", "text": "jev: the task is finished" + (f" (p {float(p):.2f})" if p is not None else "")}
    picks = [answers[f"drive.{axis}"]["choice"] for axis in AXES]
    return {"op": "skill", "name": "drive", "args": [*picks, f"{NAV_SECONDS:g}"]}


# ======================================================================================================================
# main
# ======================================================================================================================


def main() -> int:
    robot = Robot(os.environ["ROBOUSE_SOCKET"])
    try:
        return run(robot)
    except Exception as e:  # noqa: BLE001 - reported; the episode is left open for the runner to close
        emit(
            type="error",
            t=now(),
            error=f"{type(e).__name__}: {e}"[:1000],
            requests=robot.take_requests(),
            steps_used=robot.steps_used,
        )
        return 1


def run(robot: Robot) -> int:
    """The loop; returns the exit code: 0 when the episode ended (Jev's `robo done` included), 1 on a failure, 2 when
    this task has no profile."""
    cfg = json.loads(os.environ.get("ROBOUSE_JEV_CONFIG") or "{}")
    model = str(cfg.get("model") or "jev-latest")
    prices = cfg.get("prices") or {}
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    goal = os.environ.get("ROBOUSE_TASK_LANGUAGE", "").strip()
    if not key:
        emit(type="error", t=now(), error="no TypeSafe key (TYPESAFE_API_KEY)")
        return 1
    if not header_safe(key):  # http.client's error for it would quote the whole header, key and all
        emit(type="error", t=now(), error="TYPESAFE_API_KEY has a space, line break or other character no key has")
        return 1
    if (cfg.get("profile") or "nav") != "nav":
        emit(type="error", t=now(), error=f"unknown profile {cfg.get('profile')!r}; profiles: nav")
        return 2
    info_resp = robot.send({"op": "info"})
    if not info_resp.get("ok"):
        emit(type="error", t=now(), error=f"info failed: {info_resp.get('error')}", requests=robot.take_requests())
        return 1
    info = info_resp["result"]
    if why := nav_check(info):
        emit(type="error", t=now(), error=why, requests=robot.take_requests())
        return 2
    questions = nav_questions()
    jev = SystemOne(os.environ.get("TYPESAFE_BASE_URL") or API_URL, key, model)
    emit(
        type="start",
        t=now(),
        model=model,
        profile="nav",
        server=jev.url,
        backend=info.get("backend"),
        task=info.get("task"),
        goal=goal,
        max_steps=info.get("max_steps"),
        seconds_per_decision=NAV_SECONDS,
        questions=questions,
        requests=robot.take_requests(),
    )
    memory = NavMemory()
    tokens_in, tokens_out, spent, priced = 0, 0, 0.0, True
    versions: list[str] = []
    i, reason, claimed = 0, "", False
    while not robot.finished:
        i += 1
        t0 = now()
        obs = robot.send({"op": "observe"})
        if not obs.get("ok"):
            if robot.finished:
                break
            emit(
                type="error", t=now(), i=i, error=f"observe failed: {obs.get('error')}", requests=robot.take_requests()
            )
            return 1
        state = nav_state(obs["result"].get("state") or {}, goal, memory)
        started = time.time()
        try:
            resp = jev.ask(state, questions)
            answers = check_answers(resp, questions)
        except ApiError as e:
            emit(
                type="error",
                t=now(),
                i=i,
                error=str(e)[:1000],
                status=e.status,
                attempts=jev.attempts,
                state=state,
                requests=robot.take_requests(),
                steps_used=robot.steps_used,
            )
            return 1
        latency = round(time.time() - started, 3)
        usage: dict = resp["usage"] if isinstance(resp.get("usage"), dict) else {}
        answered_by = str(resp.get("model") or "")
        if answered_by and answered_by not in versions:
            versions.append(answered_by)
        cost = usage_cost(usage, prices, answered_by, model)
        tokens_in += tokens(usage, "input_tokens")
        tokens_out += tokens(usage, "output_tokens")
        if cost is None:
            priced = False
        else:
            spent += cost
        command = nav_command(answers)
        result = robot.send(command)
        if command["op"] == "skill":
            memory.last_drive = {axis: command["args"][k] for k, axis in enumerate(AXES)}
        else:
            claimed = bool(result.get("ok"))
        emit(
            type="decision",
            i=i,
            t=t0,
            model=answered_by,
            latency_s=latency,
            attempts=jev.attempts,
            usage=usage,
            cost_usd=cost,
            answers={qid: compact(a) for qid, a in answers.items() if qid in questions},
            command=label(command),
            ok=bool(result.get("ok")),
            error=None if result.get("ok") else result.get("error"),
            state=state,
            requests=robot.take_requests(),
            steps_used=robot.steps_used,
            episode=robot.finished or None,
        )
        # a drive or done that failed (refused, or no reply) with the episode still open: a harness failure, which the
        # runner records as one, not as a score
        if not result.get("ok") and not robot.finished:
            what = "drive" if command["op"] == "skill" else "done"
            emit(type="error", t=now(), i=i, error=f"{what} failed: {result.get('error')}", steps_used=robot.steps_used)
            return 1
        if command["op"] == "done":
            reason = "jev answered finished" if claimed else f"done failed: {result.get('error')}"
            break
    emit(
        type="end",
        t=now(),
        reason=reason or f"episode ended: {robot.finished}",
        claimed_done=claimed,
        episode=robot.finished or None,
        decisions=i,
        models=versions,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cost_usd=round(spent, 10) if priced else None,
        requests=robot.take_requests(),
        steps_used=robot.steps_used,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
