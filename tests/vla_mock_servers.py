"""Mock VLA policy servers speaking each supported wire protocol with the upstream libraries (msgpack, msgpack-numpy,
websockets, pyzmq, json-numpy), so the stdlib `vla` client is checked for interoperability, not against itself.

Runs in its own small virtualenv (the shared robouse venv stays untouched):
  uv venv -p 3.12 ~/.cache/robouse/vla-test-venv
  uv pip install --python ~/.cache/robouse/vla-test-venv/bin/python numpy msgpack msgpack-numpy websockets pyzmq json-numpy
  ~/.cache/robouse/vla-test-venv/bin/python tests/vla_mock_servers.py --wire openpi --port 8765 --policy replay:DEMO.json

Policies (stand-ins for a model; no GPU):
  replay:FILE        return the next actions of a recorded LIBERO demonstration ({"actions": [[7 floats], ...]})
  track:J1,J2,...    absolute joint targets moving from the observed joints toward the given pose at <= 3 units/step
Every observation received is summarised (keys, array shapes and dtypes, the prompt) into --log (JSON lines).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import time

import msgpack
import numpy as np


class Policy:
    def __init__(self, spec: str, chunk: int, advance: int = 0):
        kind, _, arg = spec.partition(":")
        self.kind, self.chunk, self.advance = kind, chunk, advance
        if kind == "replay":
            self.actions = np.asarray(json.load(open(arg))["actions"], dtype=np.float64)
            self.i = 0
        else:
            self.target = np.asarray([float(x) for x in arg.split(",")], dtype=np.float64)

    def reset(self):
        if self.kind == "replay":
            self.i = 0

    def act(self, joints=None, n=None) -> np.ndarray:
        n = n or self.chunk
        if self.kind == "replay":
            out = self.actions[self.i:self.i + n]
            self.i += min(len(out), self.advance or n)  # a client that replans after k actions only executed k of them
            if len(out) < n:  # past the end of the demonstration: hold still with the last gripper command
                hold = np.zeros((n - len(out), 7))
                hold[:, 6] = self.actions[-1, 6]
                out = np.concatenate([out, hold]) if len(out) else hold
            return out
        q = np.asarray(joints, dtype=np.float64).ravel()[: len(self.target)]
        rows = []
        for _ in range(n):
            q = q + np.clip(self.target - q, -3.0, 3.0)
            rows.append(q.copy())
        return np.asarray(rows)


def summarise(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            k = k.decode() if isinstance(k, bytes) else k
            out.update(summarise(v, f"{prefix}{k}."))
    elif isinstance(obj, np.ndarray):
        out[prefix[:-1]] = f"{obj.dtype}{list(obj.shape)}"
    elif isinstance(obj, (list, tuple)) and obj and isinstance(obj[0], (list, str)):
        out[prefix[:-1]] = json.dumps(obj)[:120]
    else:
        out[prefix[:-1]] = (obj if isinstance(obj, (int, float, str, bool)) or obj is None else type(obj).__name__)
        if isinstance(obj, str) and len(obj) > 120:
            out[prefix[:-1]] = f"str[{len(obj)}]"
    return out


def log_obs(path, wire, obs):
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"wire": wire, "t": time.time(), "obs": summarise(obs)}) + "\n")


# ---- openpi (websocket + openpi's msgpack numpy convention, as in openpi_client/msgpack_numpy.py) -----------------------
def _openpi_pack(obj):
    if isinstance(obj, np.ndarray):
        return {b"__ndarray__": True, b"data": obj.tobytes(), b"dtype": obj.dtype.str, b"shape": obj.shape}
    if isinstance(obj, np.generic):
        return {b"__npgeneric__": True, b"data": obj.item(), b"dtype": obj.dtype.str}
    return obj


def _openpi_unpack(obj):
    if b"__ndarray__" in obj:
        return np.ndarray(buffer=obj[b"data"], dtype=np.dtype(obj[b"dtype"]), shape=obj[b"shape"])
    if b"__npgeneric__" in obj:
        return np.dtype(obj[b"dtype"]).type(obj[b"data"])
    return obj


def serve_openpi(port, pol, log):
    from websockets.sync.server import serve

    packer = msgpack.Packer(default=_openpi_pack)

    def handler(ws):
        ws.send(packer.pack({"mock": True, "wire": "openpi"}))
        pol.reset()
        while True:
            try:
                obs = msgpack.unpackb(ws.recv(), object_hook=_openpi_unpack)
            except Exception:
                return
            log_obs(log, "openpi", obs)
            ws.send(packer.pack({"actions": pol.act(), "server_timing": {"infer_ms": 1.0}}))

    with serve(handler, "127.0.0.1", port, compression=None, max_size=None) as srv:
        srv.serve_forever()


# ---- XPolicyLab (websocket + msgpack-numpy envelope) -------------------------------------------------------------------
def serve_xpolicylab(port, pol, log):
    import msgpack_numpy as mnp
    from websockets.sync.server import serve

    pairs = {"hello": "hello_ack", "reset": "reset_result", "infer": "infer_result", "trial_end": "trial_end_ack",
             "heartbeat": "heartbeat_ack"}

    def handler(ws):
        while True:
            try:
                f = msgpack.unpackb(ws.recv(), object_hook=mnp.decode, raw=False)
            except Exception:
                return
            mt = f["message_type"]
            if mt == "close":
                return
            payload = {}
            if mt == "reset":
                pol.reset()
            if mt == "infer":
                obs = f["payload"]["observation"]
                log_obs(log, "xpolicylab", obs)
                st = obs.get("state", {})
                q = np.concatenate([np.asarray(st["arm_joint_state"]).ravel(), np.asarray(st["ee_joint_state"]).ravel()])
                chunk = pol.act(q)
                n_arm = len(np.asarray(st["arm_joint_state"]).ravel())
                payload = {"actions": [{"arm_joint_state": a[:n_arm], "ee_joint_state": a[n_arm:]} for a in chunk], "latency_ms": 1.0}
            reply = {**{k: f.get(k) for k in ("message_id", "evaluation_id", "action_case_id", "trial_id", "repeat_index", "step")},
                     "message_type": pairs.get(mt, "error"), "sent_at": "now", "payload": payload}
            ws.send(msgpack.packb(reply, default=mnp.encode, use_bin_type=True))

    with serve(handler, "127.0.0.1", port, compression=None, max_size=None) as srv:
        srv.serve_forever()


# ---- OpenVLA deploy.py (HTTP + json-numpy) ----------------------------------------------------------------------------
def serve_openvla(port, pol, log):
    import json_numpy

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json_numpy.loads(self.rfile.read(int(self.headers["Content-Length"])))
            log_obs(log, "openvla", payload)
            assert isinstance(payload["image"], np.ndarray) and payload["image"].dtype == np.uint8
            a = pol.act(n=1)[0].copy()
            a[6] = (1.0 - a[6]) / 2.0  # LIBERO -1 open / +1 close -> OpenVLA's [0, 1] with 1 = open
            body = json_numpy.dumps(a).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


# ---- GR00T (ZeroMQ REP + msgpack-numpy) --------------------------------------------------------------------------------
def serve_gr00t(port, pol, log):
    import msgpack_numpy as mnp
    import zmq

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(f"tcp://127.0.0.1:{port}")
    while True:
        req = msgpack.unpackb(sock.recv(), object_hook=mnp.decode, raw=False)
        ep = req.get("endpoint", "get_action")
        if ep == "ping":
            out = {"status": "ok", "message": "Server is running"}
        elif ep == "reset":
            pol.reset()
            out = {}
        elif ep == "get_action":
            obs = req["data"]["observation"]
            log_obs(log, "gr00t", obs)
            st = obs["state"]
            q = np.concatenate([np.asarray(st["single_arm"])[0, -1], np.asarray(st["gripper"])[0, -1]])
            chunk = pol.act(q)
            out = [{"action.single_arm": chunk[None, :, :5].astype(np.float32), "action.gripper": chunk[None, :, 5:6].astype(np.float32)}, {}]
        else:
            out = {"error": f"Unknown endpoint: {ep}"}
        sock.send(msgpack.packb(out, default=mnp.encode))


# ---- HTTP JSON (Robo Use's LeRobot / MolmoAct2 server) -------------------------------------------------------------------
def serve_http_json(port, pol, log):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.startswith("/reset"):
                pol.reset()
                out = {"ok": True}
            else:
                log_obs(log, "http-json", req)
                out = {"actions": pol.act().tolist(), "latency_s": 0.001}
            body = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


SERVERS = {"openpi": serve_openpi, "xpolicylab": serve_xpolicylab, "openvla": serve_openvla, "gr00t": serve_gr00t,
           "http-json": serve_http_json}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--wire", required=True, choices=sorted(SERVERS))
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--chunk", type=int, default=10)
    ap.add_argument("--advance", type=int, default=0, help="replay: actions consumed per request (the client's replan interval)")
    ap.add_argument("--log", default="")
    a = ap.parse_args()
    SERVERS[a.wire](a.port, Policy(a.policy, a.chunk, a.advance), a.log)
