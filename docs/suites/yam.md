# Dual YAM suite (Dream Labs' station scene) and the `dream` harness

9 tasks on Dream Labs' bimanual YAM station, the robot Dream Labs' Dream-1 models are trained for, in Dream's own MuJoCo scene, plus a harness that runs Dream-1 through DreamAPI. Added 2026-10-19, the day Dream Labs opened its API.

- Backend: `src/robouse/backends/yam/` (bridge `backend.py`, worker `worker.py`). Generator: `python adapters/yam/generate.py`. Harness: `src/robouse/harnesses/dream/` (builder `__init__.py`, client `client.py`).
- Scene: `dream_examples/yam_mujoco/yam_env.py` from the `dreamlabs` wheel 1.0.0 (PyPI, Apache-2.0), loaded unmodified from the installed wheel; nothing of it is copied into this repository. Two I2RT YAM arms (meshes MIT, I2RT Robotics) with linear grippers, the reference station's calibrated cameras (`top`, lowered 15 cm and tilted 5 degrees up by Dream for a closer view of the table; `left` and `right` on the wrists), an apple and a banana (YCB scans, CC BY 4.0), an orange, a water bottle, a bowl and a plate. Joint position servos, 20 Hz control (50 ms steps of 25 physics steps). Dream's scene needs MuJoCo 3.3.5 or later: on Robo Use's pinned 3.3.0 it fails to compile ("body mass is too small" for the massless arm bases), so it runs in its own virtualenv.

## Tasks

The three tasks of Dream's simulation example, each on Dream's layout (`seed: 0`, objects exactly where the scene puts them) and on two layouts with the three fruit moved by up to 3 cm and turned by up to 30 degrees (`layout-1`, `layout-2`; no two fruit overlap). The instruction a policy gets is Dream's own wording (`metadata.language_instruction`).

| Task | Instruction | Success, judged after `robo done` and a 10-step hold |
|---|---|---|
| `yam-apple-to-bowl[-layout-N]` | put apple into the bowl | the apple's centre within 6.5 cm of the bowl's axis and 0.5 to 11 cm above its base |
| `yam-orange-to-bowl[-layout-N]` | put orange into the bowl | the same for the orange |
| `yam-banana-to-plate[-layout-N]` | put banana on the plate | the banana touches the plate and its centre is within 7 cm of the plate's centre |

In every task the fruit must also be released (no fingertip of either arm touches it) and at rest (slower than 5 cm/s). Budget 1200 steps (60 s of simulated time; Dream's example runs 120 s by default).

- Action (14 numbers, Dream's YAM layout): right arm joints 1-6 (rad, absolute targets), right gripper opening (0 closed, 1 open), then the left arm's seven. Targets are clipped to the joint limits. Holding still repeats the last command (`hold_action`).
- Observation (`obs_mode: vision`): per arm the joints, the gripper opening, the tool point, its tilt from pointing down and the jaw's heading. Object positions are not given: agents find them in the cameras, like Dream-1. `robo info` gives the `top` camera's projection matrix (checked against the rendered image: the orange and the apple project within 3 px of their pixel centroids); the wrist cameras move with the arms, so they get none.
- Skills (closed loop, counted against the budget): `reach ARM X Y Z [YAW]` moves the tool point along a straight line through inverse-kinematics waypoints 2 cm apart, gripper pointing down, jaw along YAW; `set_gripper ARM OPENING [STEPS]`; `home ARM`. The inverse kinematics is damped least squares on MuJoCo's site Jacobian, in the worker.
- Reference solution: the nearer arm picks the fruit from above (the banana across its width) and puts it down 11 cm above the bowl's base or 6 cm above the plate's, with the public skills; object positions come from the privileged state the reference solution's token unlocks.

Validation (2026-10-19, macOS, MuJoCo 3.16.0, dreamlabs 1.0.0): reference solution 9/9 (231 to 258 steps), no-op 0/9.

## Setup

```sh
# the simulator (ROBOUSE_YAM_PYTHON)
uv venv -p 3.12 ~/.cache/robouse/yam-venv
uv pip install -p ~/.cache/robouse/yam-venv/bin/python mujoco==3.16.0 numpy pillow
uv pip install -p ~/.cache/robouse/yam-venv/bin/python --no-deps dreamlabs==1.0.0

# the dream harness's client (ROBOUSE_DREAM_PYTHON)
uv venv -p 3.12 ~/.cache/robouse/dream-venv
uv pip install -p ~/.cache/robouse/dream-venv/bin/python dreamlabs-client==1.0.0
```

`--no-deps` keeps `dreamlabs`' station dependencies (JAX 0.7.1, `numpy==2.2.6`, CAN and camera drivers) out; the scene needs only MuJoCo, numpy and Pillow. The key is `DREAM_API_KEY`, or Dream's credentials file `~/.dreamlabs/credentials` (four `NAME=value` lines; the platform's Setup API page prints it). The sandbox denies `~/.dreamlabs` to every agent, and the runner drops every `DREAM_*` variable from the agent's, the episode server's and the verifier's environments; the `dream` builder gives its own client the key and the service URLs.

## The `dream` harness

The client is Dream's own simulation loop (`dream_examples/yam_mujoco/dream_control.py`) with the episode server in place of the simulator, on Dream's client library (`dream.DreamClient`):

1. Hold still and take the three cameras' frames every 4 steps until each has 9 (32 steps).
2. Open the policy and hand the client the windows: `set_observation` with simulated-time timestamps, frames as 320x176 JPEG at quality 85 (`observe` with `inline`, added for this: the frames come in the reply, nothing is written to disk).
3. `get_action()` while the simulation waits, check the two 48-row chunks (shape, finite values, gripper openings within 0..1), clip them to the joint limits and execute up to `ROBOUSE_DREAM_ACTIONS` rows (default 48), handing the client every 4th step's frames.
4. Repeat until the budget is nearly spent, then `robo done`.

As in Dream's loop: `dreamlabs/dream-1-beta` reads hand poses, so it is sent the YAM station's keys (`state.arm_r.joint_pos`, `image_window.top`, `robot.arm: yam`, ...) from which the serve computes them; other models get their own keys (`state.right_arm`, `video.overhead`, ...) and switch when refused for missing poses. Config `{"timeout_ms": 45000, "strict": false, "action_hz": 20, "_record": false}`. `_record: false` matters: Dream's client otherwise uploads every observation it is given to Dream Labs in the background (the client's source shows it), and Dream's own MuJoCo example turns it off for simulated episodes. Session restarts are retried up to 3 times; retryable refusals (`rate_limited`, `pool_warming`) wait `retry_after_s`, at most 15 minutes in all. On any robot but a dual YAM with the three cameras the client gives up at 0 steps with the reason.

## Results (2026-10-19, one trial per task)

| Model | apple to bowl | orange to bowl | banana to plate | All |
|---|---|---|---|---|
| `dreamlabs/dream-1-beta` | 3/3 | 2/3 | 1/3 | 6/9 |
| `dreamlabs/dream-1-beta-flash` | 1/3 | 3/3 | 0/3 | 4/9 |

25 inferences per trial; a trial took 52 to 70 s of wall time. Round trips (225 per model): beta median 0.64 s (10th to 90th percentile 0.52 to 0.93 s, the model's own inference 455 ms), flash median 0.45 s (0.25 to 0.85 s, inference 219 ms). One trial per task is far too few to rank the two models: 6/9 against 4/9 is well inside the noise.

What the failures were (from the judge's record):
- flash, `yam-apple-to-bowl`: the apple was in the bowl, 1.3 cm from its axis, but a left fingertip still touched it at the end, so it was not released.
- flash, `yam-banana-to-plate` and `-layout-2`: the banana ended in the bowl, not on the plate.
- beta, `yam-banana-to-plate-layout-1`: the banana lay beside the plate, 7.7 cm from its centre, not touching it; `-layout-2`: the banana moved 4 cm toward the plate and one end touches its rim, but its centre is 14.5 cm from the plate's.

Parity with Dream's own loop on the same scene (`dream_control.py` run unmodified, 60 s of wall time, which at its real-time pacing with physics held during inference is about 42 s of simulated time): both models put the apple in the bowl on Dream's layout; beta did not touch the orange and moved the banana 4 cm without placing it. Dream's README: "Live apple/orange-to-bowl trials succeeded once each; banana-to-plate is inconsistent."

## Limits

- Rendered images, not camera images: Dream-1 is trained on real robots and human video, and this scene is Dream's own approximation of its station (Dream's CALIBRATION.md lists what differs: the table height, joint maxima, the tool length and the top camera's pose).
- The simulation waits while a request is out (as in Dream's loop), so latency costs nothing here; on a robot the arms would hold or keep moving through it (Dream's client paces that with `refill_due`).
- Small layout changes only, and the bowl, plate and bottle never move.
- Dream-1's other robots (MakerMods Metal and Makers arms, the beta "FaaS" robots, an arm of your own with an arm file) are reached through the client's inverse kinematics (`ik`, `robot: "other_embodiment"`); this harness does not use it yet, so no other Robo Use robot can run Dream-1.
