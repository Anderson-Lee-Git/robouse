# MolmoAct2 in robouse

MolmoAct2 (AllenAI, 5.44B parameters, Apache 2.0) is a vision-language-action model (VLA): it maps camera images, the robot state and a language instruction directly to continuous robot actions. It is built on the Molmo2-ER embodied-reasoning VLM with a flow-matching action expert. Unlike the LLM-agent harnesses in [harnesses.md](harnesses.md), it does not use the `robo` CLI. It is a learned policy with a fixed observation and action interface per robot embodiment. It needs an NVIDIA GPU (there is no CPU or Apple MPS path), so robouse runs it on a remote GPU and brings the trial directories back into `runs/`.

This page covers the runs from 2026-09-27: two established harnesses, two checkpoints, 50 simulated episodes.

## Results

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

Both have videos in their trial dirs.

These are small samples: 1 episode per LIBERO task, where the paper uses 50, and 10 ManiSkill episodes. They show that the pipeline and checkpoints work end to end and are consistent with the published numbers. They are not a re-measurement of those numbers. The 95% interval on 39/40 is roughly 87-100%.

All 50 trials pass `scripts/audit.py` with no flags. They show up in `scripts/view.sh` and `scripts/build_gallery.py` like any other job. In the viewer, harness is `lerobot-eval` or `molmoact2-sim-eval`, and model is the HF model id.

## How it runs

1. GPU. A Daytona GPU sandbox, created with the `daytona` Python SDK. The script is `runs/molmoact2-*/_job/create.py`. It asks for `Resources(cpu=16, memory=64, disk=100, gpu=1, gpu_type=[H100, RTX-PRO-6000])` and uses the image `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`. The sandbox is `ephemeral=True` (Daytona requires ephemeral GPU sandboxes), with `auto_stop_interval=30` and `ttl_minutes=150` as a hard cap. Daytona allocated an NVIDIA RTX PRO 6000 Blackwell Server Edition (96 GB, driver 580). The Daytona key is read from a local env file into the process environment only.
2. System packages: `git ffmpeg libegl1 libgl1 libglib2.0-0 libosmesa6 libvulkan1`, plus `uv`. The NVIDIA EGL and Vulkan ICDs were already mounted, so `MUJOCO_GL=egl` (LIBERO) and SAPIEN's Vulkan renderer (ManiSkill) both used the GPU.
3. Long jobs ran through Daytona sessions with `run_async=True`. A plain `process.exec` with `nohup ... &` gets killed when the exec call times out.
4. Results were tarred (22 MB), downloaded, and converted on the Mac into robouse trial dirs, one per episode.

### Harness 1: LeRobot `lerobot-eval` on LIBERO

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

### Harness 2: AllenAI `molmoact2` server plus ManiSkill `sim_eval`

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

## Time and cost

- The GPU sandbox was alive from 06:01:12 to 06:40:27 UTC, about 39 minutes of one RTX PRO 6000. About 20 minutes of that was setup: installs, two model downloads (10.9 GB and about 22 GB), a Python 3.14 re-sync, and the two fixes above.
- Pure evaluation time: LIBERO 40 episodes in about 14 min total, including the first-time asset download and model loads (about 5-18 s per episode rollout). ManiSkill 10 episodes in about 7 min (18-47 s per episode; the 2000-step failure took 152 s).
- The two harnesses ran concurrently on the one GPU: 9 GB and 12.4 GB of VRAM.
- The sandbox was deleted right after the results were downloaded, and listing confirmed that none remained. The Daytona price for this GPU type was not checked.

## Limitations

- These are LIBERO and ManiSkill tasks, not robouse tasks. MolmoAct2 checkpoints are trained per embodiment, each with its own camera setup, state vector, action space and normalization statistics (`norm_stats.json`, selected by `norm_tag`):
  - LIBERO: Franka Panda, 7-dim delta end-effector pose plus gripper, agentview and wrist 256 px cameras.
  - DROID: Franka FR3, 8-dim absolute joint positions, external and wrist cameras.
  - SO-100/101 and bimanual YAM.
- The robouse suites use other robots and action spaces:
  - Meta-World: a Sawyer driven by `[dx, dy, dz, grip]`.
  - The tabletop backend: a floating mocap gripper, `[dx, dy, dz, grip]` at about 1 cm per unit.
  - Gymnasium-Robotics: Fetch.

  Feeding their observations to MolmoAct2 would be out of distribution, and the resulting scores would not mean much.
- Small samples; see Results.
- No per-step actions are logged by either harness. The trial dirs therefore have the video, the success verdict, step counts and timing, but `episode/trace.jsonl` is a stub. The ATIF trajectory has a single "policy rollout" step.
- The success signal comes from each harness's own evaluator:
  - LIBERO: the BDDL goal predicates.
  - ManiSkill: `evaluate()['success']`.

  In both, the episode ends at the first success. robouse's trusted episode server was not involved.

### Would a robouse-task bridge work?

It is feasible, but it is a project of its own rather than a flag. Two routes:

1. Cheapest and most meaningful: robouse tasks inside LIBERO. Wrap LIBERO scenes (they are MuJoCo) as a robouse backend, the same way Meta-World is wrapped. Then:
   - LLM agents drive the Franka through `robo` with a delta-EEF action space.
   - MolmoAct2 runs as another "harness" in the same episode server. The simplest form is a thin client that calls a GPU-hosted policy server (LeRobot's policy or an `/act`-style server for the LIBERO checkpoint) for each chunk.

   This gives the same task, the same verifier and the same video pipeline for both kinds of agent. Work involved:
   - a LIBERO backend on Linux. `hf-libero` is Linux-only in LeRobot's extras and untested on macOS, so the sim would probably also run remotely.
   - a small `/act` server for `MolmoAct2-LIBERO`. The repo ships servers only for DROID and YAM, but `lerobot-eval`'s policy object can be wrapped in about 100 lines.
   - wiring a remote policy harness into `runner.py`.
2. MolmoAct2 on existing robouse scenes. Rebuild a tabletop scene with a Franka and LIBERO-like cameras, then either fine-tune MolmoAct2 on demonstrations there (the scripted oracles can generate them; LeRobot supports MolmoAct2 fine-tuning) or test zero-shot and expect low success. The Sawyer and floating-gripper tasks cannot be used as-is.

Either way, the policy must run on an NVIDIA GPU. A single 24 GB card is enough for bf16 inference (12 GiB peak at batch size 1).

## Reproducing

The job READMEs list exact commits, model revisions, versions and commands. Each `_job/` folder has the run scripts, logs, raw metrics (`eval_info*.json`, `results*.json`) and the sandbox creation script. The GPU has to be recreated: the sandbox was ephemeral and is gone.
