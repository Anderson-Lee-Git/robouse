"""A local stand-in for TypeSafe's System One endpoint (POST /v1/systemone), for the `jev` harness's tests and for
running whole trials without a TypeSafe key. Standard library only. It is not Jev: it answers the nav profile's
questions by applying their criteria literally to the state (the steering bearing, then the drive axes and the task),
so a run against it checks the harness's loop, its records and the criteria's coherence, and says nothing about Jev.

    python tests/jev_stand_in.py --port 0 --log /tmp/jev-stand-in.jsonl     # prints the port it took
    TYPESAFE_BASE_URL=http://127.0.0.1:<port> TYPESAFE_API_KEY=stand-in robouse run --task nav-h01-oven --harness jev --out runs/jev

Answers have TypeSafe's shape: {"model", "answers": {id: {"type", "choice", "confidence", "probabilities"}},
"usage": {"input_tokens", "output_tokens"}}, with 0.9 on the picked option and TypeSafe's Choice confidence. Input
tokens are the request body's length / 4. Questions it has no rule for get their first option. Every request is
logged (question ids, state keys, whether an Authorization header came; never its value). `--fail N --status S`
(or StandIn.fail in tests) makes the first N requests fail with that HTTP status and retry-after 0.
On the 40 nav tasks (2026-10-20) this literal reading reached the target and answered finished on 19.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LEFT = ("ahead_left", "left", "behind_left")
RIGHT = ("ahead_right", "right", "behind_right")


def steering(state: dict) -> str:
    """The steering bearing, as the nav questions define it."""
    target, way = state.get("target") or {}, state.get("way_to_target") or {}
    if not way.get("blocked"):
        return str(target.get("bearing") or "ahead")
    sides = [o for o in way.get("open_sides") or [] if isinstance(o, dict)]
    if sides:
        going = next((o for o in sides if o.get("side") == way.get("going_around")), None)
        pick = going or min(sides, key=lambda o: abs(float(o.get("bearing_deg") or 0.0)))
        return str(pick.get("bearing"))
    free = state.get("free_space") or {}
    if (free.get("ahead") or {}).get("state") == "open":
        return "ahead"
    last = ((state.get("robot") or {}).get("last_drive") or {}).get("yaw")
    if last in ("turn_left", "turn_right"):  # keep turning that way
        return "left" if last == "turn_left" else "right"
    for ring in (("ahead_left", "ahead_right"), ("left", "right"), ("behind_left", "behind_right"), ("behind",)):
        opened = [k for k in ring if (free.get(k) or {}).get("state") == "open"]
        if opened:
            return opened[0]
    return "left"


def nav_answer(qid: str, state: dict) -> str | None:
    target, free, robot = state.get("target") or {}, state.get("free_space") or {}, state.get("robot") or {}
    arrived = bool(target.get("arrived"))
    steer = steering(state)
    ahead_blocked = (free.get("ahead") or {}).get("state") == "blocked"
    if qid == "task":
        return "finished" if arrived else "continue"
    if qid == "drive.yaw":
        if arrived or steer == "ahead":
            return "none"
        if steer == "behind":
            return "turn_left"
        return "turn_left" if steer in LEFT else "turn_right"
    if qid == "drive.x":
        if arrived:
            return "none"
        toward = steer in ("ahead", "ahead_left", "ahead_right")
        if (ahead_blocked and toward) or (robot.get("recent") or {}).get("pattern") == "stuck":
            return "backward"
        return "forward" if toward else "none"
    if qid == "drive.y":
        if steer != "ahead" or not ahead_blocked:
            return "none"
        for side in ("left", "right"):
            if (free.get(side) or {}).get("state") == "open":
                return side
        return "none"
    return None


def answer(qid: str, question: dict, state: dict) -> dict:
    if question.get("type") == "noul":
        return {"type": "noul", "noul": 0.1}
    options = list(question.get("criteria") or {})
    pick = nav_answer(qid, state)
    if pick not in options:
        pick = options[0]
    n = len(options)
    rest = 0.1 / (n - 1) if n > 1 else 0.0
    probs = {o: round(0.9 if o == pick else rest, 4) for o in options}
    confidence = (0.9 - 1 / n) / (1 - 1 / n) if n > 1 else 1.0
    return {"type": "choice", "choice": pick, "confidence": round(confidence, 4), "probabilities": probs}


class StandIn(BaseHTTPRequestHandler):
    log_path: str | None = None
    fail: list[tuple[int, dict]] = []  # (status, headers) for the next requests, first first
    requests: list[dict] = []  # every request body, for tests
    lock = threading.Lock()

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        auth = self.headers.get("Authorization") or ""
        with StandIn.lock:
            failing = StandIn.fail.pop(0) if StandIn.fail else None
            try:
                body = json.loads(raw.decode())
            except ValueError:
                body = None
            StandIn.requests.append({"body": body, "bearer": auth.startswith("Bearer ") and len(auth) > 7})
            if StandIn.log_path:
                with open(StandIn.log_path, "a") as f:
                    f.write(
                        json.dumps(
                            {
                                "path": self.path,
                                "bearer": auth.startswith("Bearer "),
                                "model": (body or {}).get("model"),
                                "questions": sorted((body or {}).get("questions") or {}),
                                "state_keys": sorted((body or {}).get("state") or {}),
                                "failed": failing[0] if failing else None,
                            }
                        )
                        + "\n"
                    )
        if failing is not None:
            return self._send(failing[0], {"detail": f"stand-in failure {failing[0]}"}, failing[1])
        if self.path != "/v1/systemone":
            return self._send(404, {"detail": "not found"})
        if not auth.startswith("Bearer ") or len(auth) <= 7:
            return self._send(401, {"detail": "missing API key"})
        if not isinstance(body, dict) or not all(k in body for k in ("model", "state", "questions")):
            return self._send(422, {"detail": [{"loc": ["body"], "msg": "model, state and questions are required"}]})
        state, questions = body["state"], body["questions"]
        answers = {qid: answer(qid, q, state if isinstance(state, dict) else {}) for qid, q in questions.items()}
        usage = {"input_tokens": max(1, len(raw) // 4), "output_tokens": 4 * len(questions)}
        self._send(200, {"model": "stand-in", "answers": answers, "usage": usage})

    def _send(self, status: int, payload: dict, headers: dict | None = None) -> None:
        out = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a) -> None:
        pass


def serve(port: int = 0) -> ThreadingHTTPServer:
    """A stand-in server on 127.0.0.1 in a background thread (port 0: any free port)."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), StandIn)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8790, help="0: any free port (printed)")
    ap.add_argument("--log", help="append one JSON line per request (no state values, no key)")
    ap.add_argument("--fail", type=int, default=0, help="fail the first N requests with --status")
    ap.add_argument("--status", type=int, default=429)
    a = ap.parse_args()
    StandIn.log_path = a.log
    StandIn.fail = [(a.status, {"retry-after": "0"})] * a.fail
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), StandIn)
    print(f"jev stand-in on http://127.0.0.1:{srv.server_address[1]}/v1/systemone", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
