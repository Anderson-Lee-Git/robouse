"""A Kinex device driver for one device of a Robo Use episode, served by the trial's RoboEnv-compatible bridge.

The bridge (roboenv_bridge.py) copies this file into each `.kinex/devices/<name>/` folder with the device's
`connection.json` (endpoint, session, device, kind). Kinex runs it as a persistent driver through its own
`kinex.driver_protocol.run`, which handles the JSON-lines dialog, request ids, interrupts and cleanup; this file only
forwards each action to the bridge as a `roboenv/1` `devices.call`. Two actions are done here, as RoboEnv's exported
drivers do them: FK and IK, with Kinex's numerical kinematics on the profile's model; and long world waits, sent in
slices of whole control steps so that a stop or a cancelled tool call is answered within one slice. Camera reads
return the image file the episode server saved, or its PNG in base64 for `output: base64` and `array`.
"""

import base64
import http.client
import json
import secrets
import sys
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
WAIT_SLICE_S = 0.5  # device time per bridge call during a world wait (rounded to whole control steps)


class DriverError(RuntimeError):
    def __init__(self, message, code=None, details=None):
        super().__init__(message)
        self.code, self.details = code, details


@cache
def connection():
    return json.loads((HERE / "connection.json").read_text())


def request(op, args, deadline_s=600.0):
    """One roboenv/1 request to the bridge; the reply's result, or DriverError."""
    from urllib.parse import urlsplit

    conn = connection()
    url = urlsplit(conn["endpoint"])
    body = {
        "protocol": "roboenv/1",
        "session": conn["session"],
        "generation": conn["generation"],
        "request_id": "driver-" + secrets.token_hex(8),
        "deadline_s": deadline_s,
        "op": op,
        "args": args,
    }
    client = http.client.HTTPConnection(url.hostname, url.port, timeout=deadline_s + 60)
    try:
        client.request("POST", "/", json.dumps(body).encode() + b"\n", {"Content-Type": "application/json"})
        resp = client.getresponse()
        raw = resp.read()
    finally:
        client.close()
    if resp.status != 200:
        raise DriverError(f"the bridge answered HTTP {resp.status}", "transport_error")
    reply = json.loads(raw)
    if not reply.get("ok"):
        err = reply.get("error") or {}
        raise DriverError(str(err.get("message", "device call failed")), err.get("code"), err.get("details"))
    return reply["result"]


def call(action, args):
    result = request("devices.call", {"device": connection()["device"], "action": action, "args": args})
    data = dict(result["data"])
    if "simulation" in result:
        data["simulation"] = result["simulation"]  # the episode has ended: why, and the budget it used
    return data


@cache
def kinematics():
    """Kinex's joint model of this device's profile (numerical FK and IK)."""
    from kinex.joints import JointDevice
    from kinex.validation import settings

    return JointDevice(settings(HERE), HERE)


def wait(duration_s):
    from kinex.driver_protocol import cancellation
    from kinex.validation import number

    step = float(connection().get("step_s") or 0.05)
    piece = step * max(1, round(WAIT_SLICE_S / step))
    remaining, waited, time_s = float(number(duration_s, "duration_s")), 0.0, None
    while True:
        event = cancellation()
        if event is not None and event.is_set():
            raise InterruptedError("world wait interrupted")
        part = min(remaining, piece)
        data = call("wait", {"duration_s": part})
        waited += data["waited_s"]
        time_s = data["time_s"]
        remaining -= part
        if remaining <= step / 2 or data.get("terminal"):
            break
    # the episode ended during the wait: pass that on (terminal, and the simulation status with why), as `call` does
    return {"time_s": time_s, "waited_s": waited, **{k: data[k] for k in ("terminal", "simulation") if k in data}}


def camera_read(args):
    output = args.get("output", "file")
    if set(args) - {"output"} or output not in ("file", "base64", "array"):
        raise ValueError("camera read accepts only output: file, base64 or array")
    data = call("read", {})
    out = {"timestamp": data["timestamp"], "camera": data.get("camera")}
    if output == "file":
        return {**out, "file": data["file"]}
    # arrays cross the JSON boundary as an encoded PNG; Kinex's Python decodes them
    return {**out, "color": base64.b64encode(Path(data["file"]).read_bytes()).decode("ascii")}


def dispatch(action, args):
    try:
        kind = connection()["kind"]
        if kind == "world" and action == "wait":
            if set(args) != {"duration_s"}:
                raise ValueError("wait takes duration_s")
            return {"ok": True, **wait(args["duration_s"])}
        if kind == "camera" and action == "read":
            return {"ok": True, **camera_read(args)}
        if kind == "arm" and action == "fk":
            if set(args) - {"joints", "frame", "reference_frame"} or "joints" not in args:
                raise ValueError("fk takes joints and optional frame and reference_frame")
            return {"ok": True, **kinematics().fk(**args)}
        if kind == "arm" and action == "ik":
            if set(args) - {"pose", "seed", "frame", "reference_frame"} or "pose" not in args:
                raise ValueError("ik takes pose and optional seed, frame and reference_frame")
            joint = kinematics()
            seed = args.get("seed")
            if seed is None:
                seed = joint.project(call("read", {})["positions"])
            return {"ok": True, **joint.ik(args["pose"], seed, args.get("frame"), args.get("reference_frame"))}
        return {"ok": True, **call(action, args)}
    except DriverError as e:
        return {"ok": False, "error": str(e), "code": e.code, "details": e.details}
    except Exception as e:  # noqa: BLE001 - every failure goes back to Kinex as the driver's error
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main():
    from kinex.driver_protocol import run

    run(dispatch, lambda: None)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    main()
