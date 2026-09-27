"""robouse verifier for BenchFlow. Runs inside the trusted `simulator` service, never in the agent container.

1. Close the episode. If the agent ended with `robo done` / `robo give-up`, or the step or wall budget ran
   out, the episode server has already judged it and exits on its own. Otherwise (the agent stopped
   without calling `robo done`) we send `shutdown`, which the server scores as outcome `agent_exited`
   after the usual settle period: the physical state is judged exactly as in a local `robouse run`.
2. Wait for the server to exit (it writes the video on the way out; /episode/serve.exit marks the end).
3. Copy the episode record (result.json, trace, frames, video, observations) to /logs/verifier/episode
   and write /logs/verifier/reward.txt: 1 if the episode server judged success, else 0.

A missing result.json is an infrastructure error (exit 1, no reward), not a zero score.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

EPISODE = Path(os.environ.get("ROBOUSE_EPISODE_DIR", "/episode"))
SOCKET = os.environ.get("ROBOUSE_SOCKET", "/rpc/episode.sock")
OUT = Path(os.environ.get("ROBOUSE_VERIFIER_DIR", "/logs/verifier"))
WAIT_S = float(os.environ.get("ROBOUSE_VERIFIER_WAIT_S", "240"))


def _send(req: dict) -> dict | None:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(60)
    try:
        s.connect(SOCKET)
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode() or "{}")
    except OSError:
        return None
    finally:
        s.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    exit_marker = EPISODE / "serve.exit"
    closed_by = "episode_server"
    if not exit_marker.exists():
        status = _send({"op": "status"})
        print("status before close:", status)
        if status and not (status.get("result") or {}).get("finished"):
            closed_by = "verifier_shutdown"
        # shutdown is harmless if the episode already finished (the server is only lingering)
        print("shutdown:", _send({"op": "shutdown"}))
    deadline = time.time() + WAIT_S
    while not exit_marker.exists() and time.time() < deadline:
        time.sleep(0.5)
    result_path = EPISODE / "result.json"
    evidence = OUT / "episode"
    if EPISODE.exists():
        shutil.copytree(EPISODE, evidence, dirs_exist_ok=True)
    if not result_path.exists():
        print(f"error: no episode result at {result_path} (episode server did not finish)", file=sys.stderr)
        return 1
    r = json.loads(result_path.read_text())
    success = bool(r.get("success"))
    (OUT / "reward.txt").write_text("1" if success else "0")
    details = {"reward": 1.0 if success else 0.0, "closed_by": closed_by,
               "server_exit_code": exit_marker.read_text().strip() if exit_marker.exists() else None, **r}
    (OUT / "reward-details.json").write_text(json.dumps(details, indent=2))
    print(("success" if success else "fail"), r.get("outcome"), f"steps={r.get('steps_used')}/{r.get('max_steps')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
