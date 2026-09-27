# RoboCasa suite (household kitchens)

7 tasks in [RoboCasa](https://robocasa.ai/) kitchens (RoboCasa365, commit `456174f`, on robosuite 1.5.2 at `5ce6643`, MuJoCo 3.3.1): full kitchens with counters, cabinets, drawers, sinks and appliances, and RoboCasa's default robot, a Franka Panda arm on an Omron mobile base with a torso lift (`PandaOmron`). Success is RoboCasa's own `_check_success()` for each task.

- Backend: `src/robouse/backends/robocasa.py` (bridge, task table `TASKS`), `robocasa_worker.py` (runs the simulation), `robocasa_oracles.py` (reference solutions), `robocasa_episodes/` (recorded episode layouts).
- Generator: `python adapters/robocasa/generate.py --out tasks/robocasa`.
- Setup: `scripts/setup_robocasa.sh`.

## Install (macOS works; about 4.7 GB)

RoboCasa pins MuJoCo 3.3.1, numpy 2.2 and robosuite 1.5, which conflict with the main robouse virtualenv (robosuite 1.4 for LIBERO, MuJoCo 3.3.0). The simulation therefore runs in its own virtualenv (`~/.cache/robouse/robocasa-venv`, override with `ROBOUSE_ROBOCASA_PYTHON`) as a subprocess of the episode server; the backend talks to it over stdin/stdout (JSON lines, raw RGB bytes for renders). `scripts/setup_robocasa.sh` clones RoboCasa and robosuite at the pinned commits, installs them without RoboCasa's training dependencies (lerobot, torch, tianshou), and downloads a minimal asset subset:

| Asset pack | Zip | Used for |
|---|---|---|
| `tex` (textures) | 0.54 GB | walls, floors, counters |
| `fixtures_lw` (lightwheel fixtures) | 0.53 GB | cabinets, drawers, sinks, appliances |
| `objs_lw` (lightwheel objects) | 0.79 GB | the objects to manipulate |

Not downloaded: objaverse objects (2.2 GB zip), AI-generated objects (5.8 GB) and AI-generated textures (1.2 GB). Consequences: only kitchen styles 1-10 load (styles 11-60 reference AI-generated textures), objects come from the lightwheel registry only (`obj_registries=("lightwheel",)`), and object groups that exist only in objaverse are swapped in the worker (`mug` -> `glass_cup`, `pan` -> `saucepan`; "place inside a container" is dropped). On disk: assets 3.3 GB, robosuite checkout 0.9 GB, venv 0.5 GB. Environment creation takes 12-20 s per episode on an M2 Max.

## Action and observation

- The mobile base and torso stay where RoboCasa's task initialisation parks them (facing the target fixture, usually against the counter); only the arm and gripper move.
- `robo act DX DY DZ GRIP`: DX/DY/DZ move the gripper's commanded target by 2 cm per unit per step along WORLD axes (converted to the base frame for robosuite's `OSC_POSE` controller); the target stays within 5 cm of the hand, so the arm catches up over a few steps instead of the target running away. The gripper orientation is held (pointing down) by closing the loop on the end-effector orientation every step. GRIP: 0 keeps, > 0 closes, -f opens to fraction f. 20 Hz control (RoboCasa's rate). `move-to` and `grip` skills work.
- `robo observe`: `hand_pos`, `hand_target`, `gripper_open`, `robot_base_pos`, `robot_forward`, `task_instruction` (RoboCasa's language instruction), plus per task: `drawer_handle_pos`, `drawer_open_fraction`, `drawer_front_normal` (drawers); `object_pos`, `object_size`, `object_category`, `sink_basin_center`, `sink_basin_half_size`, `sink_basin_bottom_z` (pick and place). Cameras: RoboCasa's `robot0_agentview_left` (default), `_right`, `_center`, `robot0_eye_in_hand`, `robot0_frontview`, rendered at 384 x 288.

## Reproducibility

RoboCasa's object placement is not reproducible from the seed alone: the same seed produced different placements in different processes (it iterates over sets of objects; fixing `PYTHONHASHSEED` and the global generators did not help). Every task therefore replays a recorded episode layout: `robocasa_episodes/<task>.json` is RoboCasa's own `ep_meta` (object models and placements, fixture references, robot base pose), the mechanism RoboCasa uses to replay its demonstrations. Replays were checked to be identical across processes and oracle reruns (7/7 twice). `record_episode(task_id, seed)` in the backend re-records one.

## Tasks

| Task | RoboCasa env | Kitchen (layout, style) | Object | Budget | Oracle steps |
|---|---|---|---|---|---|
| robocasa-close-drawer | CloseDrawer | 1, 1 | | 400 | 135 |
| robocasa-close-drawer-kitchen2 | CloseDrawer | 2, 2 | | 400 | 145 |
| robocasa-pick-place-counter-to-sink | PickPlaceCounterToSink | 1, 1 | lemon wedge | 800 | 466 |
| robocasa-pick-place-counter-to-sink-kitchen2 | PickPlaceCounterToSink | 2, 2 | peeler | 800 | 217 |
| robocasa-pick-place-counter-to-sink-kitchen2b | PickPlaceCounterToSink | 2, 2 | ice cube | 800 | 254 |
| robocasa-pick-place-counter-to-sink-kitchen3 | PickPlaceCounterToSink | 3, 3 | reamer | 800 | 286 |
| robocasa-pick-place-counter-to-sink-kitchen4 | PickPlaceCounterToSink | 4, 4 | cheese grater | 800 | 471 |

Success rules (RoboCasa's): CloseDrawer: the drawer's joint is within 0.5 % of closed. PickPlaceCounterToSink: the object is inside the sink basin and the gripper is away from it.

## Validation

- Oracle (`robocasa_oracles.py`, robo socket only): **7/7**, twice (runs/_v1-oracle-robocasa, runs/_v1-oracle-robocasa-rep2).
- No-op: **0/7** (runs/_v1-noop-robocasa).
- Probe, codex + gpt-6-astra, `--limit 3`: **3/3** (close-drawer 109 steps, close-drawer-kitchen2 136, pick-place-counter-to-sink 181) (runs/_probe-robocasa-astra).

## What was tried and dropped

- StartCoffeeMachine, TurnOnMicrowave, TurnOnSinkFaucet, OpenDrawer, CloseCabinet, CloseMicrowave (layout 1): from the parked base the arm cannot reach the button, faucet lever or handle with the gripper pointing down (the hand stops 7-25 cm short, or the hand body hits the coffee machine's overhang); with the gripper pitched forward the microwave start button is still blocked by the panel frame (finger contact with the housing before the button). RoboCasa's demonstrations drive the mobile base and change the gripper orientation for these; this interface keeps the base parked and the orientation fixed, so they were left out rather than shipped without a working reference solution.
- PickPlaceCounterToStove (object into a saucepan): no reliable reference solution in 7 recorded layouts (grasps of thin objects missed or the drop missed the pan).
- CloseDrawer in kitchens 3 and 4 and some counter-to-sink layouts (soap dispenser, drumstick, tupperware wider than the 8 cm gripper): the scripted solution failed, so those layouts were not used.
- The tasks are state-mode only (the backend does not expose `mj_model_data`, so no calibrated vision variant yet).
