"""`dream` harness: Dream Labs' Dream-1 drives a Robo Use episode through DreamAPI, with Dream's own client library.

The runner copies this file into the trial workspace and runs it with ROBOUSE_DREAM_PYTHON, a Python that has Dream's
client (`pip install dreamlabs-client`), inside the agent sandbox; it reaches the robot only through the `robo` socket,
like every harness. The loop is Dream Labs' own simulation loop (`dream_examples/yam_mujoco/dream_control.py` in the
dreamlabs 1.0.0 wheel), with the episode server in place of the simulator:

  1. Fill the camera windows: hold still and take the three cameras' frames every 4 steps (0.2 s of simulated time)
     until each has 9.
  2. Open the policy and hand the client the windows (`set_observation`, timestamps in simulated time).
  3. `get_action()` while the simulation waits (the episode server only steps when asked). Check the two 48-row joint
     chunks and execute up to `actions` rows of them with `act`, handing the client every 4th step's frames.
  4. Repeat until the step budget is about to run out, then `robo done`: a policy never says it is done, and the
     episode server judges the physical state it left.

Frames come inline from the episode server (`observe` with `inline`): 320x176 JPEG at quality 85, what Dream's models
read. A model that reads hand poses (dreamlabs/dream-1-beta) gets the YAM station's keys, from which the serve computes
the poses, as Dream's loop does; other models get their own keys and switch when refused for missing poses. Episodes
are not recorded to the Dream Labs account (`_record: False`, as in Dream's simulation example; the client otherwise
uploads every observation it is given).

Environment: ROBOUSE_SOCKET, DREAM_API_KEY and the service URLs (from the runner), ROBOUSE_DREAM_CONFIG ({"model",
"actions"}), ROBOUSE_TASK_LANGUAGE (the instruction the policy gets). One JSON line per inference on stdout
(agent/stdout.jsonl).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import warnings
from collections import deque

import numpy as np

FRAMES, FRAME_EVERY = 9, 4  # frames per camera window, and control steps between two of them (0.2 s at 20 Hz)
INLINE = {"format": "jpeg", "width": 320, "height": 176, "quality": 85}
VIDEO_ROLES = {"top": "overhead", "left": "wrist_l", "right": "wrist_r"}  # Robo Use camera -> Dream's camera role
YAM_GROUPS = {"right_arm.joints": 6, "right_gripper": 1, "left_arm.joints": 6, "left_gripper": 1}
YAM_PARTS = {"right_arm": [0, 6], "right_gripper": [6, 7], "left_arm": [7, 13], "left_gripper": [13, 14]}
YAM_EMBODIMENT = {
    "state": YAM_PARTS,
    "action": YAM_PARTS,
    "video": {role: f"observation.images.{role}" for role in VIDEO_ROLES.values()},
}
# Models known to read each hand's pose; they are sent the YAM station's keys, from which the serve computes the poses
# (the model's own keys cannot carry them yet; Dream's dream_control.py explains why).
POSE_MODELS = {"dreamlabs/dream-1-beta"}
STATION_SLOTS = {"right": "arm_r", "left": "arm_l"}
STATION_ROBOT = {
    "robot.arm": "yam",
    "robot.exec_head": "joint",
    "robot.max_joint_vel_rad_s": 0.0,
    "robot.gripper_open": 1.0,
}
MAX_RETRY_WAIT_S = 900  # a model that is warming up, or rate limiting, is retried for at most this long in all


def robo(req: dict) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(300)
    try:
        s.connect(os.environ["ROBOUSE_SOCKET"])
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(1 << 20)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode() or '{"ok": false, "error": "empty response"}')
    except (FileNotFoundError, ConnectionRefusedError):
        return {"ok": False, "error": "episode server is not running"}
    finally:
        s.close()


def emit(**kw) -> None:
    print(json.dumps(kw, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)), flush=True)


def check_embodiment(info: dict) -> str | None:
    """Why Dream-1 cannot drive this task's robot, or None: its models drive Dream's bimanual YAM."""
    emb = info.get("embodiment") or {}
    groups = {g.get("name"): len(g.get("components") or []) for g in emb.get("action_groups") or []}
    cams = {c.get("name") for c in (emb.get("sensors") or {}).get("cameras") or []}
    if groups != YAM_GROUPS or len(info["action"]["names"]) != 14:
        return (
            f"Dream-1 drives Dream's bimanual YAM (two 6-joint arms with grippers, joint targets); this task's robot is "
            f"{emb.get('name') or info.get('backend')!r} with action groups {sorted(groups)}"
        )
    if missing := [c for c in VIDEO_ROLES if c not in cams]:
        return f"Dream-1 reads an overhead and two wrist cameras; this task has no {missing}"
    return None


def observation(state: dict, language: str, station: bool) -> dict:
    """The state keys and the prompt of one tick, in the model's own keys or in the YAM station's."""
    obs: dict = {"prompt": language}
    for side in ("left", "right"):
        joints = [float(x) for x in state[f"{side}_joint_pos"]]
        grip = [float(state[f"{side}_gripper_open"])]
        if station:
            obs[f"state.{STATION_SLOTS[side]}.joint_pos"] = joints
            obs[f"state.{STATION_SLOTS[side]}.gripper_pos"] = grip
        else:
            obs[f"state.{side}_arm"] = joints
            obs[f"state.{side}_gripper"] = grip
    if station:
        obs.update(STATION_ROBOT)
    return obs


def frame_key(camera: str, station: bool) -> str:
    return f"image_window.{camera}" if station else f"video.{VIDEO_ROLES[camera]}"


def policy_config(model: str, station: bool) -> dict:
    """Dream's simulation loop's session config: no strict-mode embodiment for the station keys (it names none of
    them); the chunks are checked here (`rows`)."""
    cfg = {"checkpoint": model, "timeout_ms": 45000, "strict": False, "action_hz": 20, "_record": False}
    if not station:
        cfg["embodiment"] = YAM_EMBODIMENT
    return cfg


def needs_poses(error: Exception) -> bool:
    """A refusal that names a missing `_eef_` key: the model reads hand poses."""
    return getattr(error, "reason", None) in ("malformed", "error") and "_eef_" in str(error)


def rows(reply: dict, low: np.ndarray, high: np.ndarray, limit: int) -> tuple[np.ndarray, int]:
    """The reply's joint chunks as Robo Use actions ([right 7, left 7] per row), at most `limit` rows, clipped to the
    joint limits; a malformed chunk (wrong shape, non-finite, a gripper outside 0..1) raises, and nothing runs."""
    right, left = (np.asarray(reply[k], dtype=np.float64) for k in ("q_r_chunk", "q_l_chunk"))
    if right.ndim != 2 or right.shape != left.shape or right.shape[1] != 7 or not 1 <= len(right) <= 48:
        raise ValueError(f"Dream returned chunks of shape {right.shape} and {left.shape}, not matching 1-48 x 7")
    both = np.concatenate([right, left], axis=1)[:limit]
    if not np.isfinite(both).all():
        raise ValueError("Dream returned non-finite joint targets")
    grips = both[:, [6, 13]]
    if (grips < -0.05).any() or (grips > 1.05).any():
        raise ValueError(f"Dream returned gripper openings outside 0..1 ({grips.min():.3f} to {grips.max():.3f})")
    clipped = np.clip(both, low, high)
    return clipped, int(np.count_nonzero(np.abs(clipped - both) > 1e-9))


def main() -> int:
    cfg = json.loads(os.environ.get("ROBOUSE_DREAM_CONFIG") or "{}")
    model = str(cfg.get("model") or "dreamlabs/dream-1-beta")
    per_chunk = max(1, min(48, int(cfg.get("actions", 48))))
    language = os.environ.get("ROBOUSE_TASK_LANGUAGE", "").strip()
    info = robo({"op": "info"})
    if not info.get("ok"):
        emit(type="error", error=info.get("error"))
        return 1
    info = info["result"]
    max_steps = int(info["max_steps"])
    emit(
        type="start",
        task=info.get("task"),
        backend=info.get("backend"),
        model=model,
        language=language,
        max_steps=max_steps,
        actions_per_chunk=per_chunk,
    )
    if why := check_embodiment(info):
        emit(type="incompatible", reason=why)
        robo({"op": "give_up", "text": f"dream: incompatible embodiment: {why}"})
        return 2
    if not language:
        emit(type="error", error="no language instruction (ROBOUSE_TASK_LANGUAGE)")
        robo({"op": "give_up", "text": "dream: no language instruction"})
        return 1
    try:
        import dream
    except ImportError:
        why = "Dream's client is not installed for this Python (pip install dreamlabs-client; ROBOUSE_DREAM_PYTHON)"
        emit(type="error", error=why)
        robo({"op": "give_up", "text": f"dream: {why}"})
        return 1
    # the client's slow-network warning repeats the timing logged here for every inference
    warnings.filterwarnings("ignore", category=dream.DreamSlowNetworkWarning)
    low, high = (np.asarray(info["action"][k], dtype=np.float64) for k in ("low", "high"))
    request = {"op": "observe", "inline": {**INLINE, "cameras": list(VIDEO_ROLES)}}

    windows: deque = deque(maxlen=FRAMES)  # (steps, state, {camera: jpeg}), oldest first

    def tick() -> int | None:
        r = robo(request)
        if not r.get("ok"):
            emit(type="end", reason=r.get("error"))
            return None
        res = r["result"]
        windows.append((int(res["steps_used"]), res["state"], res["images"]))
        return int(res["steps_used"])

    def feed(policy, station: bool, every: bool = False) -> None:
        """Hand the client the newest tick, or (`every`) the whole window, oldest first, as Dream's loop does."""
        for i, (steps_at, state, images) in enumerate(windows if every else [windows[-1]]):
            frames = {frame_key(c, station): images[c] for c in VIDEO_ROLES}
            policy.set_observation(frames, observation(state, language, station), timestamp=steps_at * 0.05 + i * 1e-6)

    # 1. the windows: hold still (the measured joints as targets) until every camera has FRAMES frames
    steps = tick()
    if steps is None:
        return 0
    while len(windows) < FRAMES:
        st = windows[-1][1]
        hold = [*st["right_joint_pos"], st["right_gripper_open"], *st["left_joint_pos"], st["left_gripper_open"]]
        r = robo({"op": "act", "action": [float(x) for x in hold], "repeat": FRAME_EVERY})
        if not r.get("ok") or "episode" in r["result"]:
            emit(type="end", reason=r.get("error") or r["result"]["episode"])
            return 0
        if (steps := tick()) is None:
            return 0

    # 2. the policy
    station = model in POSE_MODELS
    client = dream.DreamClient()
    client.policy(policy_config(model, station))
    feed(client, station, every=True)
    n_inf, restarts, waited = 0, 0, 0.0
    try:
        while steps < max_steps - 1:
            t0 = time.time()
            try:
                reply = client.get_action()
            except dream.DreamSessionExpired:  # the serve restarted the episode; the client holds the new session
                restarts += 1
                emit(type="session_restarted", count=restarts)
                if restarts > 3:
                    raise
                continue
            except dream.DreamServerError as e:
                if needs_poses(e) and not station:
                    emit(type="switch", reason="the model reads hand poses; sending the YAM station keys")
                    station = True
                    client.policy(policy_config(model, station))
                    feed(client, station, every=True)
                    continue
                wait = float(getattr(e, "retry_after_s", None) or 0)
                if getattr(e, "retryable", False) and waited + wait <= MAX_RETRY_WAIT_S:
                    emit(type="retry", code=getattr(e, "code", None), reason=getattr(e, "reason", None), wait_s=wait)
                    time.sleep(max(wait, 0.5))
                    waited += max(wait, 0.5)
                    continue
                raise
            restarts = 0
            n_inf += 1
            acts, n_clipped = rows(reply, low, high, per_chunk)
            emit(
                type="chunk",
                inference=n_inf,
                steps_used=steps,
                rows=len(acts),
                clipped_values=n_clipped,
                roundtrip_s=round(time.time() - t0, 3),
                timing=client.last_timing,
                session=client.session_id,
                actions=[[round(float(x), 4) for x in a] for a in acts],
            )
            # 3. execute the rows; every FRAME_EVERY steps the client gets the newest frames
            for a in acts:
                if steps >= max_steps - 1:
                    break
                r = robo({"op": "act", "action": [float(x) for x in a], "repeat": 1})
                if not r.get("ok"):
                    emit(type="end", reason=r.get("error"))
                    return 0
                if "episode" in r["result"]:
                    emit(type="end", reason=r["result"]["episode"], steps_used=r["result"].get("steps_used"))
                    return 0
                steps = int(r["result"]["steps_used"])
                if steps % FRAME_EVERY == 0:
                    if tick() is None:
                        return 0
                    feed(client, station)
        # 4. a policy never says it is done: the episode is judged on the state it left at the end of the budget
        robo({"op": "done", "text": f"dream: step budget reached after {n_inf} inferences"})
        emit(type="end", reason="done", steps_used=steps, inferences=n_inf)
    except Exception as e:  # noqa: BLE001 - recorded in the trial; the runner closes the episode
        emit(type="error", error=f"{type(e).__name__}: {e}"[:2000])
        robo({"op": "give_up", "text": f"dream: {type(e).__name__}: {e}"[:1000]})
        return 1
    finally:
        try:
            client.close()  # ends the session on the model's side
        except Exception:  # noqa: BLE001 - a session that was not released ends on its own once idle
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
