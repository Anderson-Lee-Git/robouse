# DexJoCo suite

14 dexterous tool-use tasks adapted from [DexJoCo](https://dexjoco.github.io) ([arXiv 2605.16257](https://arxiv.org/abs/2605.16257), v2 2026-09-22; code [brave-eai/dexjoco](https://github.com/brave-eai/dexjoco), MIT). A Franka Panda arm (or two) carries a four-fingered, 16-joint Allegro hand instead of a gripper, and the tasks are functional: water a plant with a trigger sprayer, hammer a nail, click a mouse, fill and lift a bucket, squeeze kitchen tongs, fold a pair of glasses into a box, and bimanual microwave cooking, photographing, iPad passcode entry and peg-in-hole assembly. Why this suite was picked over other 2026 releases: [../research/recent-2026.md](../research/recent-2026.md).

Backend: `src/robouse/backends/dexjoco.py` (bridge) and `src/robouse/backends/dexjoco_worker.py` (runs in DexJoCo's own virtualenv). Generator: `adapters/dexjoco/generate.py`. Runs on the Mac (MuJoCo on CPU, no GPU).

## Setup

DexJoCo pins Python 3.11, MuJoCo 3.4.0 and numpy 1.26, which conflict with the main robouse environment, so it gets its own virtualenv and runs as a subprocess of the episode server (the same pattern as the RoboCasa backend).

```
git clone --depth 1 https://github.com/brave-eai/dexjoco.git ~/.cache/robouse/dexjoco          # 305 MB (MuJoCo scenes and meshes)
uv venv -p 3.11 ~/.cache/robouse/dexjoco-venv
VIRTUAL_ENV=~/.cache/robouse/dexjoco-venv uv pip install -e ~/.cache/robouse/dexjoco/dexjoco "numcodecs<0.16"
```

- `numcodecs<0.16`: newer numcodecs removed a function that `zarr<3` (pinned by DexJoCo) imports.
- The backend looks for the interpreter at `~/.cache/robouse/dexjoco-venv/bin/python`; override with `ROBOUSE_DEXJOCO_PYTHON`. Set `ROBOUSE_DEXJOCO_QUIET=0` to see the worker's stderr.
- The worker forces single-threaded BLAS (`OPENBLAS_NUM_THREADS=1`). DexJoCo's controller inverts small matrices on every physics substep, and with threaded BLAS on macOS a control step took 460 ms instead of 6.5 ms. With it, a step takes 3 ms (water plant) to about 50 ms (bimanual scenes, mostly mesh contacts).

Demonstrations (only needed to regenerate the tasks; each task folder carries its own `oracle/demo.json`): download the `replay.zarr` folders of the first four demonstrations per task from the Hugging Face dataset [DexJoCo/DexJoCo-Datasets-Raw](https://huggingface.co/datasets/DexJoCo/DexJoCo-Datasets-Raw) (`allow_patterns=["dexjoco_raw_datasets/<task>/<demo>/replay.zarr/**"]`, 25 MB for 44 demonstrations) into `~/.cache/robouse/dexjoco-demos`, then

```
~/.cache/robouse/dexjoco-venv/bin/python adapters/dexjoco/export_demos.py      # -> ~/.cache/robouse/dexjoco-demos/json
.venv/bin/python adapters/dexjoco/generate.py                                  # -> tasks/dexjoco
```

## How the tasks are built

Each robouse task is one DexJoCo task started from the initial scene of one recorded human teleoperation demonstration: DexJoCo's own state restorers put the objects and the table height where they were in that recording (the scene is stored in `robouse.init_state` in `task.md`). The reference solution (`oracle/solve.sh`) replays that recording through the `robo` socket: at every step it reads the commanded hand pose and finger targets from `robo observe` and sends the `robo act` delta that moves them onto the recorded absolute targets. So the reference solution uses only the public interface, like an agent.

DexJoCo's replay is not bit-for-bit reproducible across machines. On this Mac 34 of 40 demonstrations (Tower of Hanoi excluded) replayed to success through the socket; the tasks use only demonstrations that do. Tower of Hanoi is left out because none of its four demonstrations replayed to success (its disk placement at reset is re-randomised and not fully restored).

## Action, observation, scoring

- **Action** per arm, 22 numbers: `DX DY DZ` move the commanded hand position 2 cm per unit along world axes (limit +-8), `RX RY RZ` rotate the commanded orientation 0.2 rad per unit about world axes (limit +-3), `F0..F15` move the 16 commanded finger joint angles 0.3 rad per unit (limit +-6). Bimanual tasks take 44 (right arm, then left). DexJoCo's operational-space controller tracks the commanded pose and the finger servos track the joint targets. One step is 20 ms. The large limits exist so the recorded demonstrations fit into the delta interface; agents usually use small values with `--repeat`.
- **Skills**: `robo move-to X Y Z` moves the active hand's flange point with orientation and fingers unchanged; `robo grip G` sets a generic power grasp (G > 0 closes to fraction G, G < 0 opens). The preset suits few of these objects, so the tasks are really about finger-level control.
- **Observation**: flange pose, commanded pose, measured and commanded finger joints (per arm), object poses (position, quaternion, tilt, yaw), and task quantities (trigger angle, nail depth, mouse button travel, pinch count, temple hinge angles, microwave door angle, iPad button positions and digits entered). Images from the front/back camera, overhead, side and wrist cameras with `robo observe --image --camera C`.
- **Success** (`success_mode: first`): DexJoCo's own success signal, which ends the episode as solved the first time it fires. Most tasks require the goal to hold for 10 to 50 consecutive steps. Two tasks have a failure event that makes success impossible afterwards (`task_failed` appears in `robo observe`): spraying while the nozzle is away from the plant (DexJoCo ends its episode there), and pressing a wrong iPad digit.

## Tasks

| Task id | DexJoCo task | Demonstration (suffix) | Demo steps | Budget |
|---|---|---|---|---|
| dexjoco-water-plant | water_plant | 2026-02-05_19-50-27 | 309 | 2500 |
| dexjoco-water-plant-b | water_plant | 2026-02-05_21-14-32 | 232 | 2500 |
| dexjoco-hammer-nail | hammer_nail | 2026-02-05_19-18-55 | 202 | 2500 |
| dexjoco-hammer-nail-b | hammer_nail | 2026-02-05_19-19-09 | 237 | 2500 |
| dexjoco-click-mouse | click_mouse | 2026-03-10_20-07-29 | 559 | 2500 |
| dexjoco-click-mouse-b | click_mouse | 2026-03-12_12-49-21 | 387 | 2500 |
| dexjoco-pick-bucket | pick_bucket | 2026-03-11_20-12-38 | 380 | 2500 |
| dexjoco-pick-bucket-b | pick_bucket | 2026-03-11_21-13-52 | 428 | 2500 |
| dexjoco-pinch-tongs | pinch_tongs | 2026-03-12_16-30-04 | 375 | 2500 |
| dexjoco-fold-glasses | fold_glasses | 2026-03-16_09-48-20 | 422 | 2500 |
| dexjoco-microwave-cook | bimanual_microwave_cook | 2026-02-09_17-09-31 | 693 | 3000 |
| dexjoco-photograph | bimanual_photograph | 2026-03-16_14-31-13 | 260 | 3000 |
| dexjoco-unlock-ipad | bimanual_unlock_ipad | 2026-03-22_14-10-52 | 336 | 3000 |
| dexjoco-assembly | bimanual_assembly | 2026-03-19_17-36-54 | 587 | 3000 |

## Validation

Through the real runner (`robouse run-many`, macOS, M2 Max):

- Reference solutions: **14/14** (`runs/dexjoco-oracle`), 202 to 693 steps, 13 to 57 s of wall time per episode.
- No-op control: **0/14** (`runs/dexjoco-noop`).

PROBE_PLACEHOLDER

## Known limitations

- Reference solutions are replayed human demonstrations, so they prove each scene is solvable through `robo` but are not closed-loop controllers; a change in MuJoCo version or platform can break a replay (rerun `--harness oracle` after any upgrade).
- Object poses are given as numbers (state tier). A vision-only variant would need calibrated projection matrices, which the bridge does not yet forward (`mj_model_data` is not available across the process boundary).
- The left hand's finger order follows DexJoCo's actuator order (ring, middle, index, thumb), which the instruction states.
