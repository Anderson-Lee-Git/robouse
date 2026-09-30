"""Reference solutions for the RLE-Bench tasks. They drive the robot only through the robo socket, like an agent.

- Tabletop tasks (TowerMaxHeight, CantileverOverhang, BalanceCoins): RLE-Bench's own reference solution, a replay of its
  recorded control trajectory (tasks/task03/_template/solution/actions/<Task>.npz, MIT, copied into the task's oracle/
  folder) through the public step interface, then `robo done`.
- HiddenCOM: RLE-Bench's own reference solution (tasks/task03/_template/hidden_com_solution/oracle.py): grasp the handle,
  lift the box, find the box in the top camera's RGB image and read the ballast quadrant from how the box hangs relative
  to the gripper. It uses only public observations (no oracle token).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

from robouse.agent_cli import _send


class Finished(Exception):
    pass


def _call(req: dict) -> dict:
    r = _send(req)
    if not r.get("ok"):
        raise Finished(r.get("error"))
    return r["result"]


def replay(path: str) -> None:
    with np.load(path, allow_pickle=False) as data:
        actions = np.asarray(data["actions"], dtype=float)
    try:
        for a in actions:
            res = _call({"op": "act", "action": [float(x) for x in a], "repeat": 1})
            if "episode" in res:
                return
    except Finished:
        return
    _send({"op": "done", "text": "reference trajectory replayed"})


# ---- HiddenCOM ------------------------------------------------------------------------------------------------------


def _read_png(path: str) -> np.ndarray:
    """An 8-bit RGB or RGBA PNG (as the episode server writes them) as an HxWx3 array; standard library + numpy only."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos : pos + 8])
        chunk = data[pos + 8 : pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, color = struct.unpack(">IIBB", chunk[:10])
            if depth != 8 or color not in (2, 6) or chunk[12] != 0:
                raise ValueError("only 8-bit, non-interlaced RGB/RGBA PNGs are supported")
            ch = 3 if color == 2 else 4
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
        pos += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(h, 1 + w * ch)
    out = np.zeros((h, w * ch), dtype=np.int32)
    for y in range(h):
        f, line = raw[y, 0], raw[y, 1:].astype(np.int32)
        prev = out[y - 1] if y else np.zeros(w * ch, dtype=np.int32)
        if f == 0:
            cur = line
        elif f == 1:
            cur = line.copy()
            for x in range(ch, w * ch):
                cur[x] = (cur[x] + cur[x - ch]) & 255
        elif f == 2:
            cur = (line + prev) & 255
        elif f == 3:
            cur = line.copy()
            for x in range(w * ch):
                left = cur[x - ch] if x >= ch else 0
                cur[x] = (cur[x] + ((left + prev[x]) >> 1)) & 255
        elif f == 4:
            cur = line.copy()
            for x in range(w * ch):
                a = cur[x - ch] if x >= ch else 0
                b, c = prev[x], (prev[x - ch] if x >= ch else 0)
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                cur[x] = (cur[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        else:
            raise ValueError(f"unknown PNG filter {f}")
        out[y] = cur
    return out.reshape(h, w, ch)[:, :, :3].astype(np.uint8)


def hidden_com() -> None:
    q = [2**-0.5, 2**-0.5, 0, 0]  # the gripper pointing down, fingers across the handle (RLE-Bench's oracle)
    try:
        for position, gripper, steps in (
            ([0, 0, 1.05], -1, 60),
            ([0, 0, 0.86], -1, 60),
            ([0, 0, 0.86], 1, 40),
            ([0, 0, 1.06], 1, 80),
        ):
            _call({"op": "skill", "name": "move", "args": [*position, *q, gripper, steps]})
        obs = _call({"op": "observe", "image": True, "camera": "top"})
    except Finished:
        return
    paths = obs["image_path"] if isinstance(obs["image_path"], list) else [obs["image_path"]]
    top = next((p for p in paths if p.endswith("_top.png")), paths[0])
    rgb = _read_png(top).astype(float)
    yellow = (
        (rgb[:, :, 0] > 150)
        & (rgb[:, :, 1] > 100)
        & (rgb[:, :, 0] - rgb[:, :, 2] > 60)
        & (rgb[:, :, 1] - rgb[:, :, 2] > 50)
    )
    rows, cols = np.where(yellow)
    if len(rows) < 200:
        _send({"op": "give_up", "text": "box is not visible"})
        return
    eef = obs["state"]["eef_pos"]
    # The known handle-to-lid separation sets the approximate projection plane.
    lid_z = eef[2] - 0.056
    scale = rgb.shape[0] / (2 * np.tan(np.deg2rad(43 / 2)) * (1.71 - lid_z))
    u, v = (cols.min() + cols.max()) / 2, (rows.min() + rows.max()) / 2
    cx, cy = (rgb.shape[1] - 1) / 2, (rgb.shape[0] - 1) / 2
    center = np.array([(u - cx) / scale + 0.03, -(v - cy) / scale])
    delta = center - np.array(eef[:2])
    if np.min(np.abs(delta)) < 0.001:
        _send({"op": "give_up", "text": "lift deflection is inconclusive"})
        return
    answer = ("A" if delta[0] > 0 else "B") if delta[1] < 0 else ("C" if delta[0] > 0 else "D")
    _call({"op": "skill", "name": "submit", "args": [answer]})
    _send({"op": "done", "text": f"submitted {answer}"})


def run(env: str) -> None:
    if env.endswith(".npz"):
        replay(env)
    elif env.startswith("rle-hidden-com"):
        hidden_com()
    else:
        raise SystemExit(f"no RLE-Bench reference solution for {env!r}")
