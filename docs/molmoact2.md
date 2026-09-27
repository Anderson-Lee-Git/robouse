# MolmoAct2 in robo-use

MolmoAct2 (AllenAI, 5.44B parameters, Apache 2.0) is a vision-language-action model (VLA): it maps camera images, the robot state and a language instruction directly to continuous robot actions. It is built on the Molmo2-ER embodied-reasoning VLM with a flow-matching action expert. It is a learned policy with a fixed observation and action interface per robot embodiment, and it needs an NVIDIA GPU (there is no CPU or Apple MPS path).

Since 2026-09-27 MolmoAct2 is a robo-use harness like the LLM agents: `--harness molmoact2` drives a normal robo-use episode through the same `robo` socket, on the same tasks, with the same episode server, verifier, budgets and video pipeline. Only the policy runs remotely, on a GPU. The main target is the [LIBERO suite](suites/libero.md) (`tasks/libero`), where MolmoAct2 and every LLM harness can be compared on identical tasks. The earlier runs through LeRobot's and AllenAI's own evaluators are described further down.

## The `molmoact2` harness

| Job | Tasks | Checkpoint | Solved |
| --- | --- | --- | --- |
| `runs/final-libero-molmoact2` | robo-use LIBERO suite, all 20 tasks, 1 episode each | `allenai/MolmoAct2-LIBERO-LeRobot` (bf16) | 20/20 |
| `runs/final-other-molmoact2` | zero-shot: 5 tabletop `libero-style` tasks and 5 Meta-World tasks | same | 0/10 |

LIBERO, per suite (steps used; the demonstration replay used by the reference solution in brackets):

| Suite | Solved | Steps used |
| --- | --- | --- |
| libero_spatial (budget 280) | 5/5 | 77 [80], 93 [92], 121 [115], 112 [125], 92 [101] |
| libero_object (280) | 5/5 | 128 [121], 115 [113], 142 [145], 163 [158], 143 [158] |
| libero_goal (300) | 5/5 | 144 [127], 78 [82], 81 [81], 83 [76], 70 [69] |
| libero_10 (520) | 5/5 | 253 [293], 269 [260], 219 [226], 204 [193], 352 [448] |

Read these numbers with two caveats:
- The initial states are the first states of LIBERO training demonstrations (the ones the reference solution replays; see [suites/libero.md](suites/libero.md)). MolmoAct2-LIBERO was trained on these demonstrations, so it has seen these exact starting layouts. 20/20 fits its published 98.25% on LIBERO's held-out evaluation states, but it is not a held-out measurement.
- These are single episodes. The 95% interval on 20/20 is roughly 83-100%.

Controls on the same 20 tasks: reference solution 20/20 (`runs/oracle-libero`), no-op 0/20 (`runs/noop-libero`). All 50 trials in these three jobs pass `scripts/audit.py` with no flags. LLM agents run on the same tasks on the Mac. A smoke trial of `claude-code` + `claude-opus-5-5` solved `libero-goal-8` in 279 of 300 steps (`runs/smoke-libero-claude`).

Zero-shot, all 10 ran out their step budget. The policy moves the gripper (largest commanded |dx|, |dy|, |dz| per trial 0.5-0.8) but completes nothing. This was expected. Those scenes are a different robot (a Sawyer, or a floating gripper), with a different camera and no wrist camera, and every observation is out of distribution for a checkpoint trained only on LIBERO's Franka.

### How it runs

```
Mac (robo-use runner, episode server, simulator)           GPU (Daytona sandbox)
  runner -> sandboxed client (molmoact2/client.py)   --HTTPS-->  molmoact2/server.py in a LeRobot checkout
            robo observe (2 PNGs + state), robo act x10    <--   10-action chunk from MolmoAct2
```

- `src/robouse/molmoact2/client.py` is the harness process. It is standard library only. The runner copies it into the trial workspace and runs it with `python3` under the same macOS Seatbelt sandbox as the LLM harnesses, so it has no access to the simulator or the repo. Each cycle:
  1. `observe` with `camera=agentview` and `camera=robot0_eye_in_hand` (the episode server saves the PNGs).
  2. POST both PNGs, the robot state and the task's language instruction to the server.
  3. Apply the returned chunk with one `act` per action, stopping as soon as the episode ends.
- The instruction given to the policy is `metadata.language_instruction` (LIBERO's own sentence, e.g. "put the bowl on the plate"), falling back to the task description. The policy does not see the robo-use instruction text.
- One JSON line per chunk goes to `agent/stdout.jsonl`: the state sent, the 10 actions returned, and the server and round-trip latency. Per-step actions are also in `episode/trace.jsonl`, and the ATIF trajectory is built from that trace, as for the reference solution.
- `src/robouse/molmoact2/server.py` loads the policy exactly as `lerobot-eval` does: same LeRobot config parser and command-line flags, `make_policy`, the checkpoint's pre/post processors, and LeRobot's LIBERO env processor. Per request it:
  1. flips each upright PNG back to robosuite's raw (upside-down) orientation.
  2. rebuilds the observation dict LeRobot's `LiberoEnv` returns.
  3. runs `LiberoProcessorStep`: a 180-degree image rotation, and state = eef position + axis-angle + 2 finger joints.
  4. normalizes, calls `select_action` 10 times (`n_action_steps=10`; one chunk prediction, then 9 queue pops), and un-normalizes.

  Episodes can run concurrently. Each keeps its own action queue and per-episode flow-matching generator (`per_episode_seed=true`, `eval_seed=1000`), swapped in under a lock.
- Differences from the earlier `lerobot-eval` run:
  - Images are 256x256 (the checkpoint's `input_features` and training resolution). `lerobot-eval`'s LIBERO env renders 360x360 by default, and both are resized by the policy processor.
  - Initial states come from demonstrations, not LIBERO's evaluation init states.
  - The 50 no-op settle steps are the same.

Commands (the scripts are in `runs/final-libero-molmoact2/_job/`):

```
# GPU sandbox (daytona SDK; key from the owner's env file, never printed): create.py -> H100 80 GB
# in the sandbox: setup.sh
git clone https://github.com/huggingface/lerobot && cd lerobot && git checkout e595b790
uv sync --locked --python 3.12 --extra molmoact2        # no libero extra: the server needs no simulator, and egl-probe needs CMake
hf download allenai/MolmoAct2-LIBERO-LeRobot --local-dir /root/ckpt/MolmoAct2-LIBERO-LeRobot   # plus the config shim below
# serve.sh
python /root/server.py --port 8000 -- --policy.path=/root/ckpt/MolmoAct2-LIBERO-LeRobot --policy.inference_action_mode=continuous \
  --policy.dtype=bfloat16 --policy.enable_inference_cuda_graph=true --policy.device=cuda --policy.per_episode_seed=true \
  --policy.eval_seed=1000 --env.type=libero --env.task=libero_spatial \
  --env.camera_name_mapping='{"agentview_image":"image","robot0_eye_in_hand_image":"wrist_image"}' --seed=1000

# on the Mac: the sandbox's preview URL for port 8000 and its preview token (sandbox.get_preview_link(8000))
export ROBOUSE_MOLMOACT2_URL=https://8000-<sandbox>.<daytona proxy> ROBOUSE_MOLMOACT2_TOKEN=<preview token>
MUJOCO_GL=cgl .venv/bin/python -m robouse.cli run-many --tasks tasks/libero --harness molmoact2 \
  --model allenai/MolmoAct2-LIBERO-LeRobot --out runs/final-libero-molmoact2 --concurrency 3
MUJOCO_GL=cgl .venv/bin/python -m robouse.cli run-many --tasks tasks --task-list task-lists/molmoact2-zero-shot.txt \
  --harness molmoact2 --model allenai/MolmoAct2-LIBERO-LeRobot --out runs/final-other-molmoact2 --concurrency 3
```

The config shim is the same as before: drop `enable_lora_vlm`, `enable_lora_action_expert`, `train_action_expert_only` and `model_dtype` from the checkpoint's `config.json`, and set `dtype=bfloat16` and `train_mode_vlm=fft`. The weights are unchanged. The preview token is passed to the client in its environment and is not written to trial directories. Any server reachable over HTTP works, including a local GPU at `http://127.0.0.1:8000`.

### Zero-shot mapping (other suites)

Tasks, listed in `task-lists/molmoact2-zero-shot.txt`:
- tabletop: `libero-red-block-in-bowl`, `libero-cube-on-plate`, `libero-open-drawer`, `libero-close-drawer`, `libero-push-block-to-pad`
- Meta-World: `metaworld-reach`, `-push`, `-pick-place`, `-drawer-open`, `-button-press-topdown`

The mapping, in `client.py`, is as honest as the interfaces allow:
- Images: the task's single scene camera (`front` or `corner`) fills both the external and the wrist slot. These tasks have no wrist camera, and the task files were not changed.
- Frames: LIBERO's +x (forward from the robot) is robo-use +y (away from the front camera or robot), and LIBERO's +y (robot's left) is robo-use -x.
- Actions: LIBERO (dx, dy, dz) maps to robo-use (-dy, dx, dz). The scale is 1:1, since both move about 1 cm per step at 1.0. The rotation deltas are dropped. The gripper passes through (both use -1 open, +1 close).
- State:
  - The hand position is rotated into LIBERO's frame and re-centred so the episode's first position maps to LIBERO's usual start pose (-0.21, 0, 1.17).
  - The orientation is a fixed gripper-down quaternion.
  - The fingers are set from `gripper_open` (0.04 m per finger when fully open).
- Language: the task description (e.g. "Put the red block in the bowl").

### Time and cost

- One Daytona GPU sandbox (NVIDIA H100 80 GB HBM3, `ephemeral`, `auto_stop_interval=30`, `ttl_minutes=180`) was alive from 08:06:43 to 09:06:13 UTC, about 60 minutes. About 24 minutes of that was setup:
  - apt, uv, `uv sync` and the 11 GB checkpoint download: 08:07-08:19 UTC, including one failed first attempt with the libero extra.
  - server start: 08:20-08:30 UTC. This covers extra model files fetched from the HF Hub, the weight load and warm-up.
- The run was interrupted once by a session restart (the lead's), which cut off one zero-shot trial. It was moved to `runs/final-other-molmoact2/_infra_failed/` and rerun.
- The sandbox was deleted after the runs. Listing confirmed it was gone.
- VRAM: 12-16 GB.
- One chunk takes about 1.5-2 s on the server with a single episode (5.44B parameters, 8 flow steps, 10 `select_action` calls plus processors). With 3 concurrent episodes, the median server time per chunk was 1.5-7 s (it includes waiting for the lock). The preview-URL round trip added about 0.5-0.7 s.
- Wall time per LIBERO trial: 38-207 s on the Mac, where simulation takes about 40 ms per step. The 20 LIBERO trials took about 10 minutes at concurrency 3, and the 10 zero-shot trials about 17 minutes.

### Limits

- The policy needs a reachable GPU server for the whole run. The client retries a failed HTTP call 4 times, then stops, and the episode is closed as given up.
- There is one checkpoint per embodiment. Only the LIBERO checkpoint matches a robo-use suite. The DROID checkpoint (joint-position actions) is not wired up.
- The zero-shot numbers measure transfer to a different robot and camera, not MolmoAct2's ability on those tasks.

## Earlier runs through the original evaluators

The two jobs below ran on the same day, before the harness existed. They used two established harnesses and two checkpoints, 50 simulated episodes in all. Their trial directories were converted from the evaluators' own outputs. The robo-use episode server was not involved.

### Results

The job folders linked below are under `runs/`, which is not committed to git; the links work only in a local checkout that has the runs.

| Job | Harness | Checkpoint | Simulator and tasks | Episodes | Solved |
| --- | --- | --- | --- | --- | --- |
| [`runs/molmoact2-lerobot-eval`](../runs/molmoact2-lerobot-eval/README.md) | LeRobot `lerobot-eval` | `allenai/MolmoAct2-LIBERO-LeRobot` (bf16) | LIBERO (robosuite 1.4 / MuJoCo), Franka Panda, 1 episode per task, all 40 tasks of the 4 suites | 40 | 39 (97.5%) |
| [`runs/molmoact2-sim-eval`](../runs/molmoact2-sim-eval/README.md) | AllenAI `molmoact2` repo: FastAPI `/act` server plus `sim_eval` ManiSkill client | `allenai/MolmoAct2-DROID` (served in bf16) | ManiSkill3 `DroidPutEverythingInBox-v1`, Franka FR3 with Robotiq gripper, zero-shot | 10 | 9 (90%) |

Per suite (LeRobot job):

| LIBERO suite | Solved | Mean env steps | Paper (LeRobot port, 50 eps per task) |
| --- | --- | --- | --- |
| libero_spatial | 10/10 | 101 | 98.4% |
| libero_object | 10/10 | 136 | 100.0% |
| libero_goal | 9/10 | 139 | 98.0% |
| libero_10 | 10/10 | 235 | 96.6% |

The failures:
- `libero-goal-2` ("put the wine bottle on top of the cabinet") ran out its 300-step budget.
- `maniskill-droid-put-everything-in-box-s1046` ran out its 2000-step budget.

Both have videos in their trial directories.

These are small samples: 1 episode per LIBERO task, where the paper uses 50, and 10 ManiSkill episodes. They show that the pipeline and checkpoints work end to end and are consistent with the published numbers. They are not a re-measurement of those numbers. The 95% interval on 39/40 is roughly 87-100%.

All 50 trials pass `scripts/audit.py` with no flags. They show up in `scripts/view.sh` and `scripts/build_gallery.py` like any other job. In the viewer, harness is `lerobot-eval` or `molmoact2-sim-eval`, and model is the HF model id.

### How it ran

1. GPU. A Daytona GPU sandbox, created with the `daytona` Python SDK. The script is `runs/molmoact2-*/_job/create.py`. It asks for `Resources(cpu=16, memory=64, disk=100, gpu=1, gpu_type=[H100, RTX-PRO-6000])` and uses the image `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`. The sandbox is `ephemeral=True` (Daytona requires ephemeral GPU sandboxes), with `auto_stop_interval=30` and `ttl_minutes=150` as a hard cap. Daytona allocated an NVIDIA RTX PRO 6000 Blackwell Server Edition (96 GB, driver 580). The Daytona key is read from a local env file into the process environment only.
2. System packages: `git ffmpeg libegl1 libgl1 libglib2.0-0 libosmesa6 libvulkan1`, plus `uv`. The NVIDIA EGL and Vulkan ICDs were already mounted, so `MUJOCO_GL=egl` (LIBERO) and SAPIEN's Vulkan renderer (ManiSkill) both used the GPU.
3. Long jobs ran through Daytona sessions with `run_async=True`. A plain `process.exec` with `nohup ... &` gets killed when the exec call times out.
4. Results were tarred (22 MB), downloaded, and converted on the Mac into BenchFlow trial directories, one per episode.

#### Harness 1: LeRobot `lerobot-eval` on LIBERO

```
git clone https://github.com/huggingface/lerobot && cd lerobot      # main @ e595b790
uv sync --locked --python 3.12 --extra molmoact2 --extra libero     # Python 3.14 breaks draccus
echo N | .venv/bin/python -c "from libero.libero import benchmark"   # answer LIBERO's first-run prompt, else lerobot-eval blocks on stdin
export MUJOCO_GL=egl PYOPENGL_PLATFORM=egl OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
lerobot-eval --policy.path=<patched copy of allenai/MolmoAct2-LIBERO-LeRobot> \
  --policy.inference_action_mode=continuous --policy.dtype=bfloat16 --policy.enable_inference_cuda_graph=true \
  --policy.device=cuda --policy.per_episode_seed=true --policy.eval_seed=1000 \
  --env.type=libero --env.task=libero_spatial,libero_object \
  --env.camera_name_mapping='{"agentview_image":"image","robot0_eye_in_hand_image":"wrist_image"}' \
  --eval.batch_size=1 --eval.n_episodes=1 --seed=1000
# second run: --env.task=libero_goal,libero_10
```

Two fixes were needed against current LeRobot main. Both are recorded in the job README:
- Config shim. The published checkpoint's `config.json` still has `enable_lora_vlm`, `enable_lora_action_expert`, `train_action_expert_only` and `model_dtype`, which current main rejects. The fix drops them and sets `dtype=bfloat16`, `train_mode_vlm=fft`. The weights are unchanged.
- `num_steps_wait` changed from 10 to 50 in `envs/libero.py`. The docs say all reported numbers use 50, but main has no flag for it.

#### Harness 2: AllenAI `molmoact2` server plus ManiSkill `sim_eval`

```
git clone https://github.com/allenai/molmoact2 && cd molmoact2 && uv sync        # @ 66b87e64
uv run hf download allenai/MolmoAct2-DROID
uv run python sim_eval/scripts/download_assets.py
.venv/bin/python -m mani_skill.utils.download_asset ycb -y                       # not in the README; required
uv run python examples/droid/host_server_droid.py --host 127.0.0.1 --port 8000 --dtype bfloat16 --cuda-graph
uv run python -m sim_eval.run_eval --policy-type remote-droid --remote-url http://127.0.0.1:8000/act \
  -e DroidPutEverythingInBox-v1 -n 3                  # seeds 42-44; second run: -n 7 --seed 1042
```

This is AllenAI's own evaluation path. The policy runs behind an HTTP `/act` endpoint (json_numpy: external and wrist RGB, 8-dim joint state, instruction in; joint-position action chunk out), and a separate simulator client drives the episode. It uses a different checkpoint (DROID, absolute joint pose) and a different simulator from harness 1.

### Time and cost (earlier runs)

- The GPU sandbox was alive from 06:01:12 to 06:40:27 UTC, about 39 minutes of one RTX PRO 6000. About 20 minutes of that was setup: installs, two model downloads (10.9 GB and about 22 GB), a Python 3.14 re-sync, and the two fixes above.
- Pure evaluation time: LIBERO 40 episodes in about 14 min total, including the first-time asset download and model loads (about 5-18 s per episode rollout). ManiSkill 10 episodes in about 7 min (18-47 s per episode; the 2000-step failure took 152 s).
- The two harnesses ran concurrently on the one GPU: 9 GB and 12.4 GB of VRAM.
- The sandbox was deleted right after the results were downloaded, and listing confirmed that none remained. The Daytona price for this GPU type was not checked.

### Limitations (earlier runs)

- These are LIBERO and ManiSkill tasks run by their own evaluators, not robo-use tasks. MolmoAct2 checkpoints are trained per embodiment, each with its own camera setup, state vector, action space and normalization statistics (`norm_stats.json`, selected by `norm_tag`):
  - LIBERO: Franka Panda, 7-dim delta end-effector pose plus gripper, agentview and wrist 256 px cameras.
  - DROID: Franka FR3, 8-dim absolute joint positions, external and wrist cameras.
  - SO-100/101 and bimanual YAM.
- The robo-use suites use other robots and action spaces:
  - Meta-World: a Sawyer driven by `[dx, dy, dz, grip]`.
  - The tabletop backend: a floating mocap gripper, `[dx, dy, dz, grip]` at about 1 cm per unit.
  - Gymnasium-Robotics: Fetch.

  Feeding their observations to MolmoAct2 would be out of distribution, and the resulting scores would not mean much.
- Small samples; see Results.
- No per-step actions are logged by either harness. The trial directories therefore have the video, the success verdict, step counts and timing, but `episode/trace.jsonl` is a stub. The ATIF trajectory has a single "policy rollout" step.
- The success signal comes from each harness's own evaluator:
  - LIBERO: the BDDL goal predicates.
  - ManiSkill: `evaluate()['success']`.

  In both, the episode ends at the first success. The robo-use episode server was not involved.

### The bridge

These notes originally proposed wrapping LIBERO as a robo-use backend and adding a thin policy-server client as a harness. That is what the `molmoact2` harness above now does. LIBERO runs on macOS after all (`hf-libero --no-deps`, `MUJOCO_GL=cgl`), so only the policy needs the GPU.

## Reproducing

For the `molmoact2` harness, see the commands above and `runs/final-*-molmoact2/_job/`. For the earlier runs, the job READMEs list exact commits, model revisions, versions and commands. Each `_job/` folder has the run scripts, logs, raw metrics (`eval_info*.json`, `results*.json`) and the sandbox creation script. The GPU has to be recreated: the sandbox was ephemeral and is gone.
