# GPU track

Suites whose simulators need an NVIDIA GPU: [ManiSkill3](maniskill.md), [Genesis](genesis.md), [MuJoCo Playground](playground.md) and [Isaac Lab](isaaclab.md). They were built to be harder than the MuJoCo suites that run on a laptop: tight insertion tolerances, liquids, moving objects and obstacles, perturbations mid-episode, camera-only observation, and learned walking gaits the agent has to steer.

GPU required. Every task in this track needs a remote NVIDIA RTX GPU worker; none of them runs on a laptop alone.

## How it runs

```
 Robo Use host (laptop)                                      GPU machine (NVIDIA RTX)
 ┌───────────────────────────────────────────┐               ┌─────────────────────────────────────────┐
 │ harness (Claude Code, Codex, ...)          │               │ gpu_worker/server.py  --sim maniskill   │
 │   └─ robo  ──Unix socket──► robouse serve  │   HTTPS +     │   one child process per episode         │
 │                              │ budgets,    │ shared secret │   (ManiSkill3 / Genesis / Playground /  │
 │                              │ video,      │──────────────►│    Isaac Lab task module)               │
 │                              │ judge       │               │                                         │
 │                              └ backend gpu │               └─────────────────────────────────────────┘
 └───────────────────────────────────────────┘
```

- The trusted episode server (`robouse serve`) runs on the Robo Use host as for every suite: step and wall budgets, the trace, the video, and the verdict. Its backend (`src/robouse/backends/gpu.py`) is a thin HTTPS client.
- The simulator runs in a worker on the GPU machine (`src/robouse/backends/gpu_worker/server.py`), one worker per simulator family, each on its own port. Every episode gets its own child process, because each GPU engine (PhysX GPU, Genesis, JAX, Isaac Sim) holds process-wide state.
- The worker's address and the shared secret are read from `runs/_gpu/remote.json` (or the file named by `$ROBOUSE_GPU_REMOTE`). The file lives under `~/benchflow`, which the macOS sandbox profile denies to model harnesses, and the worker rejects requests without the secret. Delete the file when the runs are over.
- Reference solutions are the tasks' own scripted or planner-based policies. They run next to the simulator on the privileged state; the oracle's observations (oracle token only) carry the policy's next action, and `robouse.oracle --backend gpu` sends it through the socket like an agent's `robo act` or `robo skill`.
- Each task declares its robot in BenchFlow's embodied spec (`embodiment` in `robo info`): action groups, cameras, proprioception, skills and budgets.

## Setup

1. GPU machine: a Daytona sandbox (RTX PRO 6000 Blackwell, 96 GB) created from the snapshot `robouse-gpu-sims-v4`: Ubuntu 22.04 with `/opt/sim` (Python 3.11, PyTorch 2.11 cu128, mani_skill 3.0.1, mplib 0.1.1, genesis-world 1.4.2, numpy 1.26.4) and `/opt/mjx` (Python 3.12, JAX 0.7.2 with CUDA 12, mujoco 3.14.0, playground 0.2.0, brax 0.14.2, Menagerie pre-cloned). Isaac Lab goes into `/opt/isaac` at start-up (Python 3.11, torch 2.7.0 cu128, `isaacsim[all]==5.1.0`, Isaac Lab v2.3.2 with `isaaclab.sh --install none`, then `pip install -e source/isaaclab` after `flatdict==4.0.1` with `--no-build-isolation`, and `packaging==23.0 click==8.1.7 psutil==5.9.8`; about 10 minutes). The snapshot recipes are `scripts/gpu_track/snapshot_sims.py` and `snapshot_isaaclab.py` (Daytona SDK, `Image.base("ubuntu:22.04").run_commands(...)`); Daytona snapshots are limited to 20 GB, so Isaac Sim does not fit in the same image, and on driver 595 the Isaac snapshot is not usable with RTX anyway. `scripts/gpu_track/box.py` creates and deletes the labelled sandboxes and keeps the GPU-hours ledger, `up.py` uploads the worker code, starts workers and writes the endpoints file, `boot.sh` applies the fixes below.
   On a fresh sandbox, link the NVIDIA libraries that are mounted without their `.so.0` names (`libGLX_nvidia`, `libEGL_nvidia`, `libnvidia-glcore`, ...) and copy `/etc/vulkan/icd.d/nvidia_icd.json` to `/usr/share/vulkan/icd.d/` (SAPIEN looks there); without this SAPIEN reports an incompatible driver.
2. Upload `src/robouse/backends/gpu_worker/*.py` to the machine and start one worker per simulator with a shared secret:

   ```
   ROBOUSE_GPU_SECRET=<secret> /opt/sim/bin/python server.py --sim maniskill --port 8800
   ROBOUSE_GPU_SECRET=<secret> /opt/sim/bin/python server.py --sim genesis --port 8801
   ROBOUSE_GPU_SECRET=<secret> MUJOCO_GL=egl /opt/mjx/bin/python server.py --sim playground --port 8802
   ROBOUSE_GPU_SECRET=<secret> OMNI_KIT_ACCEPT_EULA=YES /opt/isaac/bin/python server.py --sim isaaclab --port 8803
   ```

3. Write the endpoints file (mode 0600):

   ```json
   {"secret": "<secret>", "workers": {"maniskill": "https://8800-<sandbox>.<proxy>", "genesis": "..."},
    "worker_headers": {"maniskill": {"x-daytona-preview-token": "<token>"}, "genesis": {"...": "..."}}}
   ```

4. Run as usual, from a Robo Use checkout on this branch:

   ```
   robouse run-many --tasks tasks/gpu-maniskill --harness oracle --out runs/gpu-oracle-maniskill --concurrency 5
   robouse run-many --tasks tasks/gpu-maniskill --harness claude-code-glm --model moonshotai/Kimi-K3 --out runs/gpu-kimi-maniskill --concurrency 4
   ```

Train the Go1 walking policy once before the Playground tasks (46 minutes on one RTX PRO 6000):

```
MUJOCO_GL=egl /opt/mjx/bin/python train_playground.py Go1JoystickFlatTerrain /root/policies/go1_flat
```

The task folders are generated by `python adapters/gpu/generate.py --out tasks` (with `adapters/gpu` and `src` on `PYTHONPATH`).

## Suites

| Suite | Simulator (licence) | Tasks | Oracle | No-op | Kimi K3 probe |
|---|---|---|---|---|---|
| [ManiSkill3](maniskill.md) | ManiSkill3 3.0.1 (Apache-2.0), SAPIEN ray tracing | 12 | 12/12 | 0/12 | 4/7 |
| [Genesis](genesis.md) | Genesis 1.4.2 (Apache-2.0), SPH liquid | 3 | 3/3 | 0/3 | 0/1 |
| [MuJoCo Playground](playground.md) | MuJoCo Playground 0.2.0 (Apache-2.0), MuJoCo Warp, our trained Go1 policy | 5 | 5/5 | 0/5 | 2/3 |
| [Isaac Lab](isaaclab.md) | Isaac Lab 2.3 (BSD-3-Clause) on Isaac Sim 5.1 (NVIDIA Isaac Sim additional software license) | 5 | 5/5 | 0/5 | 0/2 |
| total | | 25 | 25/25 | 0/25 | 6/13 |

Oracle and no-op: one run per task through `robouse run-many` against the remote workers (job folders `runs/gpu-oracle-*`, `runs/gpu-noop-*`, not committed). A still per task is in `docs/img/suites/gpu/<task>.jpg` (the default camera after reset).

### Probe with Kimi K3

One trial per probed task with `claude-code-glm --model moonshotai/Kimi-K3` (Claude Code against Kimi K3 on Baseten), agent limit 40 minutes, 2026-09-29. Other harnesses were not run (the Codex and Claude pools were at their limits).

| Task | Solved | Steps | How it ended |
|---|---|---|---|
| ms-peg-insertion-side | 0 | 40 | budget spent; never got the peg into the 3 mm clearance |
| ms-plug-charger | 0 | 39 | aligned the prongs to within 0.1 mm, but every insertion wedged; it gave up the attempt with `robo done` |
| ms-peg-insertion-moving-box | 0 | 6 | ran out of wall-clock time (most of it spent reasoning) |
| ms-stack-pyramid | 1 | 39 | |
| ms-pick-moving-cube | 1 | 15 | tracked the cube with `act` steps and grasped it on the belt |
| ms-lift-peg-upright | 1 | 38 | |
| ms-pull-cube-tool | 1 | 7 | |
| gs-pour-water | 0 | 9 | ran out of wall-clock time: each Genesis move takes 20-60 s on a shared GPU, and the agent reasoned at length between moves |
| pg-go1-obstacle-field | 1 | 9 | long `walk` commands around the boxes |
| pg-go1-moving-gates | 1 | 11 | waited, then walked through |
| pg-go1-find-ball | 0 | 97 | did not find the ball from the images |
| il-factory-peg-insert | 0 | 300 | budget spent without seating the peg |
| il-factory-nut-thread | 0 | 180 | ran out of wall-clock time |

6 of 13 (46 %). For comparison, the same model and harness solved every probed task of the humanoid, quadruped, driving, dexterous-hand, mobile-manipulation and Crazyflie suites (13 of 13) and every probed BEHAVIOR task. Caveats: one trial per task; three of the failures are wall-clock endings in which a slow simulator step (Genesis, ManiSkill with 5 concurrent sessions) shared the blame with long model reasoning; the ManiSkill stack-pyramid probe ran with task text that had the cube colours wrong (fixed since); the moving-cube probe that counts is the one after the fix that carries the cube off the belt end (an earlier version let the cube stop at the end of the belt, and the agent waited for it). The Playground tasks are the least discriminating: with state observations and the `walk` skill Kimi K3 solved two of three in about ten commands.

## GPU hours

Daytona sandboxes labelled `robouse=gpu-track`, one GPU each, counted from creation to deletion. Total 9.5 GPU hours (cap 20):

| Sandbox | Hours | Use |
|---|---|---|
| gt-a | 6.00 | development of all four modules, first Go1 training; about 3 hours of it idle during a pause, when a keep-alive loop kept the box up until its 6-hour limit removed it (the trained policy was lost with it) |
| gt-b, gt-c, gt-a3 (x3) | 0.20 | created and deleted within minutes: driver 595, on which Isaac Sim 5.1's renderer crashes |
| gt-a2 | 1.18 | second Go1 training and Isaac Lab install; auto-stopped during a stall before the policy was copied off |
| gt-a4 | 2.12 | final Go1 training (policy copied off), Isaac Lab without RTX, all oracle, no-op and probe runs |

Snapshot builds (ManiSkill3 + Genesis + Playground, Isaac Lab) ran on Daytona's builders, not on GPU sandboxes. No sandbox of this track remains.
