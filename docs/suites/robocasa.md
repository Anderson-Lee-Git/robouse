# RoboCasa suite (household kitchens)

24 tasks in [RoboCasa](https://robocasa.ai/) kitchens (RoboCasa365, code [robocasa/robocasa](https://github.com/robocasa/robocasa) at commit `456174f`, on robosuite 1.5.2 at `5ce6643`, MuJoCo 3.3.1): full kitchens with counters, cabinets, drawers, sinks and appliances, and RoboCasa's default robot, a Franka Panda arm on an Omron mobile base with a torso lift (`PandaOmron`). The tasks are eight of RoboCasa's atomic tasks (CloseDrawer, PickPlaceCounterToSink, PickPlaceCounterToCabinet, TurnOnToaster, CloseElectricKettleLid, TurnOffSinkFaucet, TurnOnStove, TurnOffStove) in all ten of RoboCasa's kitchen layouts. Success is RoboCasa's own `_check_success()` for each task.

- Backend: `src/robouse/backends/robocasa.py` (bridge, task table `TASKS`), `robocasa_worker.py` (runs the simulation), `robocasa_oracles.py` (reference solutions), `robocasa_episodes/` (recorded episode layouts).
- Generator: `python adapters/robocasa/generate.py --out tasks/robocasa`.
- Setup: `tools/setup/setup_robocasa.sh`. Asset manifest: `assets/robocasa/provenance.json`.
- Hub: dataset `robocasa/robocasa` version 0.1, simulator runtime `robocasa` (below).

## Licence

- RoboCasa code: MIT ([LICENSE](https://github.com/robocasa/robocasa/blob/456174f62b89b8fca99eaaf33949c29fec9cfc2a/LICENSE), "Copyright (c) 2026 the RoboCasa Team", with a note that it includes parts of MuJoCo under Apache 2.0). robosuite: MIT.
- Assets: CC BY 4.0. RoboCasa's README states "Assets and Datasets: CC BY 4.0", and both Hugging Face datasets the assets come from are tagged `cc-by-4.0`: [robocasa/robocasa-assets](https://huggingface.co/datasets/robocasa/robocasa-assets) (textures) and [nvidia/PhysicalAI-Robotics-Manipulation-Objects-Kitchen-MJCF](https://huggingface.co/datasets/nvidia/PhysicalAI-Robotics-Manipulation-Objects-Kitchen-MJCF) (the lightwheel fixtures and objects; RoboCasa's asset folders carry a README pointing to this dataset). CC BY 4.0 allows redistribution with attribution; Robo Use still does not copy the assets into its repository or the hub: they are downloaded while the simulator image is built, from the official datasets at pinned revisions.
- The task adaptation (interface, observation fields, reference solutions, recorded layouts) is BenchFlow's; the RoboCasa authors did not publish or review it.

## Install (macOS works; about 4.7 GB)

RoboCasa pins MuJoCo 3.3.1, numpy 2.2 and robosuite 1.5, which conflict with the main robouse virtualenv (robosuite 1.4 for LIBERO, MuJoCo 3.3.0). The simulation therefore runs in its own virtualenv (`~/.cache/robouse/robocasa-venv`, override with `ROBOUSE_ROBOCASA_PYTHON`) as a subprocess of the episode server; the backend talks to it over stdin/stdout (JSON lines, raw RGB bytes for renders). `tools/setup/setup_robocasa.sh` clones RoboCasa and robosuite at the pinned commits, installs them with pinned dependency versions but without RoboCasa's training dependencies (lerobot, torch, tianshou), and downloads a minimal asset subset:

| Asset pack | Source (pinned revision) | Zips | Used for |
|---|---|---|---|
| `tex` (textures) | `robocasa/robocasa-assets` `1b92c3d`, `textures.zip` | 1, 0.54 GB | walls, floors, counters |
| `fixtures_lw` (lightwheel fixtures) | `nvidia/PhysicalAI-Robotics-Manipulation-Objects-Kitchen-MJCF` `420a04a`, `fixtures_lightwheel/*.zip` | 17, 0.53 GB | cabinets, drawers, sinks, appliances |
| `objs_lw` (lightwheel objects) | the same dataset, `objects_lightwheel/*.zip` | 69, 0.79 GB | the objects to manipulate |

Every zip's URL, size and SHA-256 (Hugging Face's LFS object id) is listed in `assets/robocasa/provenance.json`, and the setup script and the hub image check each one. RoboCasa's own downloader (`python -m robocasa.scripts.download_kitchen_assets --type tex fixtures_lw objs_lw`) fetches the same content from Box share links (`utexas.box.com`), which can change without notice; on 2026-09-29 the extracted Hugging Face zips were compared file by file with a Box-installed tree and were identical (the only extra files in the Box tree are the fixture XMLs tracked in RoboCasa's git repository).

Not downloaded: objaverse objects (2.2 GB zip), AI-generated objects (5.8 GB) and AI-generated textures (1.2 GB). Consequences: only kitchen styles 1-10 load (styles 11-60 reference AI-generated textures), objects come from the lightwheel registry only (`obj_registries=("lightwheel",)`), and object groups that exist only in objaverse are swapped in the worker (`mug` -> `glass_cup`, `pan` -> `saucepan`; "place inside a container" is dropped). On disk: assets 3.3 GB, robosuite checkout 0.9 GB, venv 0.5 GB. Creating a kitchen takes 5-20 s per episode on an M2 Max.

## Action and observation

- The mobile base and torso stay where RoboCasa's task initialisation parks them (facing the target fixture, usually against the counter); only the arm and gripper move.
- `robo act DX DY DZ GRIP`: DX/DY/DZ move the gripper's commanded target by 2 cm per unit per step along WORLD axes (converted to the base frame for robosuite's `OSC_POSE` controller); the target stays within 5 cm of the hand, so the arm catches up over a few steps instead of the target running away. The gripper orientation is held (pointing down) by closing the loop on the end-effector orientation every step. GRIP: 0 keeps, > 0 closes, -f opens to fraction f. 20 Hz control (RoboCasa's rate). `move-to` and `grip` skills work.
- `robo observe`: `hand_pos`, `hand_target`, `gripper_open`, `robot_base_pos`, `robot_forward`, `task_instruction` (RoboCasa's language instruction), plus per task family:
  - drawers: `drawer_handle_pos`, `drawer_open_fraction` (RoboCasa's own drawer measure), `drawer_front_normal`;
  - pick and place: `object_pos`, `object_size`, `object_category`, and `sink_basin_center`, `sink_basin_half_size`, `sink_basin_bottom_z` (sink) or `cabinet_interior_center`, `cabinet_interior_half_size`, `cabinet_interior_bottom_z`, `cabinet_interior_top_z`, `cabinet_front_normal` (cabinet, lowest shelf);
  - toaster: `toaster_lever_pos`, `toaster_lever_size`, `toaster_lever_pressed`, `toaster_on` (the slot pair holding the bread);
  - kettle: `kettle_pos`, `kettle_lid_pos`, `kettle_lid_size`, `kettle_lid_hinge_pos`, `kettle_lid_hinge_axis`, `kettle_lid_open`, `kettle_switch_pos`, `kettle_switch_size`, `kettle_on`;
  - faucet: `faucet_handle_pos`, `faucet_handle_size`, `faucet_handle_hinge_pos`, `faucet_handle_hinge_axis`, `faucet_handle_angle`, `water_on`;
  - stove: `stove_knob_pos`, `stove_knob_axis`, `stove_knob_ridge_dir`, `stove_knob_ridge_half_length`, `stove_knob_top_z`, `stove_knob_angle`, `burner_on` (the knob of the burner named in the instruction).
- Positions of handles, levers and lids are the centres (and sizes) of the collision geometry of the moving part, read from MuJoCo every observation. Cameras: RoboCasa's `robot0_agentview_left` (default), `_right`, `_center`, `robot0_eye_in_hand`, `robot0_frontview`, rendered at 384 x 288.

## Reproducibility

RoboCasa's object placement is not reproducible from the seed alone: the same seed produced different placements in different processes (it iterates over sets of objects; fixing `PYTHONHASHSEED` and the global generators did not help). Every task therefore replays a recorded episode layout: `robocasa_episodes/<task>.json` is RoboCasa's own `ep_meta` (object models and placements, fixture references, robot base pose, task references such as the burner), the mechanism RoboCasa uses to replay its demonstrations. Object model paths in these files are relative to RoboCasa's asset root (`objects/lightwheel/<category>/<model>/model.xml`); the worker resolves them against the installed `robocasa.models.assets_root`, so the files are machine-independent and ship with the hub runtime. Converting the original seven files from absolute paths left their replays unchanged: the initial simulator state (qpos and qvel) hashed identically before and after, and the counter-to-sink reference solutions took exactly the same number of steps as before. Replays are identical across processes: two oracle runs of the 25 tasks of the first build (24 of which ship) took the same number of steps on every task. `record_episode(task_id, seed)` in the backend records one (object paths already relative).

How the layouts were chosen: for each candidate task and kitchen, a seed's scene was recorded, replayed in a fresh environment, and kept if the reference solution solved it within 75 % of the step budget; the next seed was tried otherwise. So every shipped layout is solvable through the public interface, but the reference solutions do not solve every RoboCasa layout (see below).

## Tasks

| Task | RoboCasa env | Kitchen (layout = style) | Object / target | Budget | Oracle steps |
|---|---|---|---|---|---|
| robocasa-close-drawer-kitchen2 | CloseDrawer | 2 | right drawer | 400 | 293 |
| robocasa-close-drawer-kitchen7 | CloseDrawer | 7 | right drawer | 400 | 149 |
| robocasa-close-drawer-kitchen10 | CloseDrawer | 10 | right drawer | 400 | 265 |
| robocasa-pick-place-counter-to-sink | PickPlaceCounterToSink | 1 | lemon wedge | 800 | 466 |
| robocasa-pick-place-counter-to-sink-kitchen2 | PickPlaceCounterToSink | 2 | peeler | 800 | 217 |
| robocasa-pick-place-counter-to-sink-kitchen2b | PickPlaceCounterToSink | 2 | ice cube | 800 | 254 |
| robocasa-pick-place-counter-to-sink-kitchen3 | PickPlaceCounterToSink | 3 | reamer | 800 | 286 |
| robocasa-pick-place-counter-to-sink-kitchen4 | PickPlaceCounterToSink | 4 | cheese grater | 800 | 471 |
| robocasa-pick-place-counter-to-sink-kitchen5 | PickPlaceCounterToSink | 5 | straw | 800 | 375 |
| robocasa-pick-place-counter-to-sink-kitchen6 | PickPlaceCounterToSink | 6 | juice | 800 | 390 |
| robocasa-pick-place-counter-to-cabinet-kitchen3 | PickPlaceCounterToCabinet | 3 | marshmallow | 800 | 518 |
| robocasa-pick-place-counter-to-cabinet-kitchen8 | PickPlaceCounterToCabinet | 8 | whisk | 800 | 533 |
| robocasa-pick-place-counter-to-cabinet-kitchen9 | PickPlaceCounterToCabinet | 9 | sugar cube | 800 | 382 |
| robocasa-turn-on-toaster-kitchen7 | TurnOnToaster | 7 | toaster lever | 300 | 76 |
| robocasa-turn-on-toaster-kitchen8 | TurnOnToaster | 8 | toaster lever | 300 | 79 |
| robocasa-close-kettle-lid-kitchen1 | CloseElectricKettleLid | 1 | kettle lid | 400 | 153 |
| robocasa-close-kettle-lid-kitchen6 | CloseElectricKettleLid | 6 | kettle lid | 400 | 147 |
| robocasa-close-kettle-lid-kitchen10 | CloseElectricKettleLid | 10 | kettle lid | 400 | 163 |
| robocasa-turn-off-faucet-kitchen2 | TurnOffSinkFaucet | 2 | faucet handle | 400 | 277 |
| robocasa-turn-off-faucet-kitchen9 | TurnOffSinkFaucet | 9 | faucet handle | 400 | 300 |
| robocasa-turn-on-stove-kitchen2 | TurnOnStove | 2 | front right burner | 500 | 369 |
| robocasa-turn-on-stove-kitchen7 | TurnOnStove | 7 | rear left burner | 500 | 277 |
| robocasa-turn-off-stove-kitchen2 | TurnOffStove | 2 | front center burner | 500 | 203 |
| robocasa-turn-off-stove-kitchen9 | TurnOffStove | 9 | front right burner | 500 | 161 |

Success rules (RoboCasa's):

- CloseDrawer: the drawer is at most 5 % open by RoboCasa's measure (slide travel over 55 % of the drawer's depth, the most RoboCasa opens a drawer). The earlier version of this doc said 0.5 %; that was the generic fixture threshold, not what the drawer task checks.
- PickPlaceCounterToSink: the object is inside the sink basin and the gripper is at least 25 cm from it.
- PickPlaceCounterToCabinet: all eight corners of the object's bounding box are inside one of the cabinet's shelf compartments (5 cm tolerance) and the gripper is at least 25 cm from the object.
- TurnOnToaster: the slot holding the bread is on. Pushing the lever to 90 % of its travel latches it; the toaster then holds the lever down itself for 500 steps and pops it up.
- CloseElectricKettleLid: the lid is at most 1 % of its travel from closed. While more than 90 % open the lid springs back to fully open.
- TurnOffSinkFaucet: the water is off (handle angle at most 0.40 rad; the handle's range is 0 to 0.5 rad).
- TurnOnStove / TurnOffStove: the named burner is on (off) when its knob angle is (not) between 0.35 and 2 pi - 0.35 rad.

Reference solutions (`robocasa_oracles.py`, robo socket only, closed gripper used as a finger): push the drawer front along its axis, then lift clear before retreating; grasp from above and carry (into the cabinet: back off, lift above the shelf, slide in through the open front, set down, withdraw); press the toaster lever down; sweep along the arc of the kettle lid's edge about its hinge and press it shut; push the faucet handle's tip about its hinge; push the end of the knob's ridge sideways in short re-aimed pushes.

## Validation

- Oracle (`robocasa_oracles.py`, robo socket only): **24/24** (`runs/robocasa-oracle-final`); the same 24 also passed in two earlier full runs with identical step counts (`runs/robocasa-oracle`, `runs/robocasa-oracle-rep2`, which also contain the dropped kitchen-1 drawer task).
- No-op: **0/24** (`runs/robocasa-noop-final`; earlier 0/25 in `runs/robocasa-noop`).
- Earlier probe of the first 7 tasks, Codex + gpt-6-astra, `--limit 3`: **3/3** (close-drawer 109 steps, close-drawer-kitchen2 136, pick-place-counter-to-sink 181) (`runs/_probe-robocasa-astra`, before this revision: drawer measure and oracles have changed since).

Model probe, Claude Code harness + Kimi K3 on Baseten (`--harness claude-code-glm --model moonshotai/Kimi-K3`), 3 tasks (`runs/robocasa-probe-kimi`, list `task-lists/robocasa-probe.txt`): **3/3**.

| Task | Result | Steps | Wall time | What happened |
|---|---|---|---|---|
| robocasa-close-drawer-kitchen7 | solved | 100 | 251 s | Looked through four cameras, moved the closed gripper in front of the handle with `move-to`, pushed along +y in `act` bursts while watching `drawer_open_fraction` (0.86 to 0.007), backed off and checked it stayed shut |
| robocasa-turn-on-toaster-kitchen7 | solved | 44 | 48 s | `move-to` above the lever tab; the open fingers slid past the 1.8 cm tab, so it closed the gripper on the tab and pushed down until `toaster_on` |
| robocasa-close-kettle-lid-kitchen1 | solved | 104 | 101 s | Put the closed gripper behind the open lid's top edge and pushed toward the kettle's mouth and down; once past the spring point the lid fell shut under gravity while the robot held still |

The trajectories showed no instruction problems: the agents used the task fields as described (handle and lever positions, open fractions, `toaster_on`). The kettle lid closes by itself under gravity once pushed well past the spring point, which the instruction does not say; it only makes that task easier.

## Hub runtime (`robocasa`)

Template `templates/runtimes/robocasa/` in the robohub: `python:3.12-slim-bookworm` with the episode server's pinned requirements (MuJoCo 3.3.0), plus a separate Python 3.12 venv `/opt/robocasa-venv` (`requirements-robocasa.txt`, the frozen versions of the local RoboCasa venv, installed with `--no-deps`; MuJoCo 3.3.1, numpy 2.2.5), RoboCasa at `456174f` and robosuite at `5ce6643` fetched from GitHub by commit, and the asset subset downloaded by `fetch_assets.py` from the manifest (87 zips, every SHA-256 checked) and extracted into RoboCasa's asset folders. The build ends by creating one kitchen as a smoke test. `ROBOUSE_ROBOCASA_PYTHON=/opt/robocasa-venv/bin/python`; `sim_memory: 4G`. The exporter must ship `robocasa_episodes/` (it was in `PKG_IGNORE` before; removed).

- Image size (linux/arm64): **8.25 GB** on disk (2.55 GB compressed content): assets 3.5 GB, RoboCasa venv + robosuite 1.3 GB, episode server 0.4 GB, Debian + OSMesa 0.3 GB. Build about 20 minutes on Colima (6 CPUs), most of it the asset download and layer export.
- `bench eval run --tasks-dir .../datasets/robouse-robocasa --agent oracle --concurrency 2` (bench 0.7.4, first export with 25 tasks): **24/25**. The failure was `robocasa-close-drawer` (kitchen 1): after the push its drawer springs back to 5.2 % open in the Linux image (4.9 % on macOS, limit 5 %), so that task was dropped; every other task passed with the same step counts as on macOS (one differed by 1 step).
- No-op in Docker: not run to completion (the run was killed during an interruption, and the disk was too full to rebuild the 8 GB image; the local no-op is 0/24).

## What was tried and dropped

Found by surveying 24 RoboCasa atomic tasks in all ten layouts (scene creation, where the robot is parked, and where the parts to manipulate are) and trying a scripted solution for the promising ones:

- TurnOnSinkFaucet: 0/10 layouts. The handle rests against its lower limit and has to be lifted from below; pushing its tip with the pointing-down fingers did not raise it past 0.40 rad. (TurnOffSinkFaucet, pushing the raised handle back down, works.)
- TurnOnElectricKettle: 0/10 layouts. The switch is a small tab at the foot of the kettle under its handle; with the gripper pointing down and a fixed yaw, the hand body (about 20 cm wide along the finger axis) hits the kettle handle before the fingertips reach the tab. A task-specific gripper yaw would probably fix this; it was not added (see below).
- PickPlaceSinkToCounter, PickPlaceStoveToCounter, PickPlaceCounterToMicrowave, and CloseOven in 6 of 10 layouts: RoboCasa cannot create the scene with the lightwheel object registry alone (`ValueError: a cannot be empty` while sampling an object category; SinkToCounter, for example, needs a plate or bowl as the receptacle, which exists only in the objaverse or AI-generated packs, not in the asset subset).
- CloseDrawer in kitchens 3, 4 and 5: the push stalled with the drawer 2-30 % open (kitchen 3: 0 of 10 seeds closed within the budget; kitchens 4 and 5: 0 of 3), and in kitchen 5 the drawer is 0.72 m to the side of the parked base. CloseDrawer in kitchens 1 and 9 were left out because their drawers spring back to 3-8 % open after the push (too close to the 5 % limit; kitchen 1 failed in the Linux image).
- PickPlaceCounterToCabinet in kitchens 1, 2, 4-7 and 10: the scripted solution failed or needed more than 75 % of the budget in the seeds tried (2 to 5 per kitchen). Most failures had tall or wide objects (spray bottle, juice carton, syrup bottle, pot), which leave little room between the shelf and the shelf above for the object with the hand on top of it; layouts with a small object were kept.
- TurnOnStove/TurnOffStove: only the stovetops of layouts 2, 4, 7 and 9 were tried (their knobs sit on the counter surface with a vertical axis); the other layouts have ranges whose knobs are on a back panel or on the front below the cooktop, which were not attempted with a pointing-down finger. Pushing the ridge turns the knob only 0.3-0.6 rad per push, and turning an "on" knob (0.5-3.7 rad) back below 0.35 rad took too many pushes in most seeds; the shipped layouts are ones where the scripted pushes succeed with margin (final angles 0.66 and 0.64 rad for on, 0.0 for off).
- From the first version, still not attempted with this interface: StartCoffeeMachine, TurnOnMicrowave, OpenDrawer, CloseCabinet, CloseMicrowave (layout 1: the arm could not reach the button, handle or door edge with the gripper pointing down; RoboCasa's demonstrations drive the mobile base and change the gripper orientation for these), PickPlaceCounterToStove (no reliable reference solution in 7 recorded layouts).
- Letting the base move or the gripper turn: the worker already supports a per-task gripper orientation (`tool="forward"`, fingers pointing along the robot's forward direction) and RoboCasa's composite controller has base and torso channels. Adding a base or yaw channel to the action would likely unlock the kettle switch (yaw), OpenDrawer and the microwave and coffee-machine buttons (forward orientation plus a base step toward the fixture). It was not done in this revision so that all 25 tasks keep one action space (`DX DY DZ GRIP`) and one instruction; it is the obvious next step for a larger RoboCasa set.
- The tasks are state-mode only (the backend does not expose `mj_model_data`, so no calibrated vision variant yet).

## On the hub

The hub dataset `robocasa/robocasa@0.1` has 23 of these tasks. It leaves out `robocasa-close-kettle-lid-kitchen6`: its reference solution passes on macOS and in Colima on an M2 Max, but on a c4a (Arm Neoverse V2) linux/arm64 cloud VM the lid did not close within the 400-step budget, in two separate runs.
