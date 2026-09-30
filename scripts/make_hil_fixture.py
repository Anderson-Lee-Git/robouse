"""Build a hardware-in-the-loop fixture (assets/hil/<name>/) from a session recorded on the real bench.

  # Metal arm session (recorder.py layout: log.jsonl, video_index.jsonl, <camera>.mp4)
  python scripts/make_hil_fixture.py metal ~/benchflow/robot/recordings/2026-09-05-metal-arm-bowl/sessions/20260905-121853-bowl-pick \
      --name metal-bowl-121853
  # SO-101 snapshots (so101_sort_control.py layout: <side>_state.json + <stamp>_<camera>.jpg stills)
  python scripts/make_hil_fixture.py so101 ~/benchflow/robot/sessions/so101-sort --side left --name so101-sort-left
  # synthetic fixture (no recording: start pose only, default tracking), e.g. for the Piper driver
  python scripts/make_hil_fixture.py piper --synthetic --name piper-synthetic

Keyframes are chosen by farthest-point sampling in joint space among the logged steps; each keeps the video frame of
every camera nearest in time, downscaled to --width and saved as JPEG. See src/robouse/real/replay.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from robouse.real.replay import HIL_DIR, fit_tracking  # noqa: E402
from robouse.real.robots import profile  # noqa: E402


def _save(img: np.ndarray, path: Path, width: int) -> None:
    from PIL import Image

    im = Image.fromarray(img)
    h = int(round(im.height * width / im.width))
    im.resize((width, h), Image.BILINEAR).save(path, quality=80)


def from_recorder_session(sess: Path, out: Path, n_key: int, width: int) -> dict:
    import imageio.v2 as imageio

    steps = [json.loads(l) for l in (sess / "log.jsonl").read_text().splitlines() if l.strip()]
    cmd = np.asarray([s["cmd"] for s in steps], dtype=float)
    pos = np.asarray([s["pos"] for s in steps], dtype=float)
    gain, bias = fit_tracking(cmd, pos)
    vidx = [json.loads(l) for l in (sess / "video_index.jsonl").read_text().splitlines() if l.strip()]
    cams = sorted({v["cam"] for v in vidx if (sess / f"{v['cam']}.mp4").exists()})
    # farthest-point sampling over measured poses
    w = np.ones(pos.shape[1])
    w[-1] = 0.2
    chosen = [0]
    d = (((pos - pos[0]) * w) ** 2).sum(axis=1)
    while len(chosen) < min(n_key, len(pos)):
        i = int(np.argmax(d))
        if d[i] < 1.0:
            break
        chosen.append(i)
        d = np.minimum(d, (((pos - pos[i]) * w) ** 2).sum(axis=1))
    (out / "keyframes").mkdir(parents=True, exist_ok=True)
    readers = {c: imageio.get_reader(sess / f"{c}.mp4") for c in cams}
    by_cam = {c: [(v["frame"], v["t"]) for v in vidx if v["cam"] == c] for c in cams}
    keyframes = []
    for n, i in enumerate(sorted(chosen)):
        t = steps[i]["t"]
        files = {}
        for c in cams:
            fr, _ = min(by_cam[c], key=lambda ft: abs(ft[1] - t))
            try:
                img = readers[c].get_data(max(0, fr - 1))
            except (IndexError, RuntimeError):
                continue
            name = f"{n:03d}_{c}.jpg"
            _save(img, out / "keyframes" / name, width)
            files[c] = name
        keyframes.append({"q": pos[i].round(3).tolist(), "t": t, "step": i, "files": files})
    compact = [{k: s[k] for k in ("t", "cmd", "pos", "link6", "joint_torque_nm", "temp_mos_c", "temp_rotor_c") if k in s} for s in steps]
    return {"steps": compact, "model": {"gain": gain.round(4).tolist(), "bias": bias.round(4).tolist()},
            "start": pos[0].round(3).tolist(), "keyframes": keyframes, "cameras": cams, "bus": "damiao"}


def from_snapshots(sess: Path, out: Path, side: str, prof, width: int) -> dict:
    from PIL import Image

    q, temps = [], []
    for j in prof.joints:  # single arm: joint names as recorded; bimanual: left_<joint> / right_<joint> from each side's file
        s, name = (j.split("_", 1) if side == "both" else (side, j))
        st = json.loads((sess / f"{s}_state.json").read_text())
        q.append(float(st["Present_Position"][name]))
        temps.append(float(st.get("Present_Temperature", {}).get(name, 30)))
    import re

    stamps = sorted({m.group(1) for p in sess.glob("*.jpg") if (m := re.match(r"(\d{8}-\d{6})_", p.name))})
    last = stamps[-1]  # the stills taken last in the session (closest to the recorded joint state)
    (out / "keyframes").mkdir(parents=True, exist_ok=True)
    files = {}
    for p in sorted(sess.glob(f"{last}_*.jpg")):
        cam = p.stem[len(last) + 1:]
        _save(np.asarray(Image.open(p).convert("RGB")), out / "keyframes" / f"000_{cam}.jpg", width)
        files[cam] = f"000_{cam}.jpg"
    n = len(prof.joints)
    return {"steps": [{"t": 0.0, "cmd": q, "pos": q, "temp_c": temps}], "model": {"gain": [0.6] * n, "bias": [0.0] * n},
            "start": q, "keyframes": [{"q": q, "t": 0.0, "step": 0, "files": files}], "cameras": sorted(files), "bus": "feetech",
            "note": "snapshot replay: one recorded pose and its stills; tracking model is the default (no control log recorded)"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("robot")
    ap.add_argument("session", nargs="?")
    ap.add_argument("--name", required=True)
    ap.add_argument("--side", default="left")
    ap.add_argument("--keyframes", type=int, default=40)
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--session-envelope", default="", help='JSON guard overrides the session ran with, e.g. {"joint_speed_deg_s": 15, "windup_deg": 3}')
    a = ap.parse_args()
    prof = profile(a.robot)
    out = HIL_DIR / a.name
    out.mkdir(parents=True, exist_ok=True)
    if a.synthetic:
        n = len(prof.joints)
        body = {"steps": [], "model": {"gain": [0.5] * n, "bias": [0.0] * n}, "start": list(prof.park), "keyframes": [],
                "cameras": [], "bus": "none", "note": "synthetic: no recording; start at the park pose, default tracking"}
        src = "synthetic"
    elif (Path(a.session) / "log.jsonl").exists():
        body = from_recorder_session(Path(a.session), out, a.keyframes, a.width)
        src = str(Path(a.session).resolve()).replace(str(Path.home()), "~")
    else:
        body = from_snapshots(Path(a.session), out, a.side, prof, a.width)
        src = str(Path(a.session).resolve()).replace(str(Path.home()), "~") + f" ({a.side} arm)"
    fx = {"name": a.name, "robot": prof.name, "source": src, **body}
    if a.session_envelope:  # the guard settings the session ran with (hil-check replays with the same ones)
        fx["session_envelope"] = json.loads(a.session_envelope)
    (out / "fixture.json").write_text(json.dumps(fx, separators=(",", ":")) + "\n")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"{out}: {len(body['steps'])} steps, {len(body['keyframes'])} keyframes, cameras {body['cameras']}, "
          f"gain {body['model']['gain']}, bias {body['model']['bias']}, {size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
