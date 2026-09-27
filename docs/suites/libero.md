# LIBERO suite

20 tasks adapted from [LIBERO](https://libero-project.github.io/) (Liu et al. 2023): 5 from each of the four standard suites, a Franka Panda in LIBERO's MuJoCo / robosuite scenes. Backend: `src/robouse/backends/libero.py`. Generator: `python adapters/libero/generate.py --out tasks/libero`.

The suite exists so that learned VLA policies and LLM agent harnesses can be compared on the same robouse tasks: the same scene, initial state, step budget, success check, episode server and video pipeline. MolmoAct2 runs on it through the `molmoact2` harness ([molmoact2.md](../molmoact2.md)); every LLM harness in [harnesses.md](../harnesses.md) runs on it through `robo`.

## Install

The backend uses `hf-libero` (the LIBERO package LeRobot's LIBERO evaluation uses) with `robosuite==1.4.0`. It runs on macOS (Apple M2 Max, `MUJOCO_GL=cgl`) and on Linux (`MUJOCO_GL=egl`).

```
uv pip install --python .venv/bin/python --no-deps hf-libero==0.1.4 robosuite==1.4.0 bddl==1.0.1
uv pip install --python .venv/bin/python numba scipy opencv-python-headless termcolor easydict pyyaml huggingface_hub h5py fsspec tqdm matplotlib future
uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu   # LIBERO loads its init-state files with torch
```

- `--no-deps` matters: `hf-libero` pins `robomimic`, `wandb`, `transformers` and `egl-probe` (which needs CMake), none of which the backend uses.
- LIBERO asks an interactive question the first time it is imported. The backend avoids it by writing `~/.libero/config.yaml` (or `$LIBERO_CONFIG_PATH/config.yaml`) itself if it is missing.
- The first episode downloads LIBERO's scene assets from the HF Hub into `~/.cache/libero/assets` (407 MB). The packages above add about 1 GB to the virtualenv, most of it torch.
- Tested with MuJoCo 3.3.0, numpy 2.5.3 and Python 3.12. `hf-libero` needs `mujoco<3.9`. A robosuite 1.5 install in the same environment would break this backend.

## Tasks

LIBERO task indices 0, 2, 4, 6 and 8 of each suite, in LIBERO's standard task order.

| Task id | LIBERO suite | Instruction | Demo | Oracle steps | Budget |
|---|---|---|---|---|---|
| libero-spatial-0 | libero_spatial | pick up the black bowl between the plate and the ramekin and place it on the plate | demo_0 | 80 | 280 |
| libero-spatial-2 | libero_spatial | pick up the black bowl from table center and place it on the plate | demo_0 | 92 | 280 |
| libero-spatial-4 | libero_spatial | pick up the black bowl in the top drawer of the wooden cabinet and place it on the plate | demo_0 | 115 | 280 |
| libero-spatial-6 | libero_spatial | pick up the black bowl next to the cookie box and place it on the plate | demo_1 | 125 | 280 |
| libero-spatial-8 | libero_spatial | pick up the black bowl next to the plate and place it on the plate | demo_0 | 101 | 280 |
| libero-object-0 | libero_object | pick up the alphabet soup and place it in the basket | demo_0 | 121 | 280 |
| libero-object-2 | libero_object | pick up the salad dressing and place it in the basket | demo_1 | 113 | 280 |
| libero-object-4 | libero_object | pick up the ketchup and place it in the basket | demo_1 | 145 | 280 |
| libero-object-6 | libero_object | pick up the butter and place it in the basket | demo_0 | 158 | 280 |
| libero-object-8 | libero_object | pick up the chocolate pudding and place it in the basket | demo_0 | 158 | 280 |
| libero-goal-0 | libero_goal | open the middle drawer of the cabinet | demo_0 | 127 | 300 |
| libero-goal-2 | libero_goal | put the wine bottle on top of the cabinet | demo_0 | 82 | 300 |
| libero-goal-4 | libero_goal | put the bowl on top of the cabinet | demo_0 | 81 | 300 |
| libero-goal-6 | libero_goal | put the cream cheese in the bowl | demo_0 | 76 | 300 |
| libero-goal-8 | libero_goal | put the bowl on the plate | demo_0 | 69 | 300 |
| libero-10-0 | libero_10 | put both the alphabet soup and the tomato sauce in the basket | demo_1 | 293 | 520 |
| libero-10-2 | libero_10 | turn on the stove and put the moka pot on it | demo_0 | 260 | 520 |
| libero-10-4 | libero_10 | put the white mug on the left plate and put the yellow and white mug on the right plate | demo_0 | 226 | 520 |
| libero-10-6 | libero_10 | put the white mug on the plate and put the chocolate pudding to the right of the plate | demo_0 | 193 | 520 |
| libero-10-8 | libero_10 | put both moka pots on the stove | demo_0 | 448 | 520 |

- Budgets are LeRobot's per-suite LIBERO evaluation budgets (`TASK_SUITE_MAX_STEPS`: 280, 280, 300, 520).
- `success_mode: first`, LIBERO's protocol: the episode ends as solved the first time LIBERO's `check_success()` (the task's BDDL goal predicates) is true.
- Agent wall-clock limit: 1200 s (1800 s for libero_10).
- Difficulty label: spatial and object easy, goal medium, libero_10 hard.

## Initial state and reference solution

LIBERO has no scripted experts, so each task's reference solution replays one human demonstration from LIBERO's own dataset (HF `yifengzhu-hf/LIBERO-datasets`, one hdf5 file per task). The adapter range-reads only `data/demo_k/states` and `data/demo_k/actions` from the 1 GB+ hdf5 file over the HF Hub (about 2.5 s per demo). It does not download the file.

- The task's initial state (`robouse.init_state` in `task.md`, a flat MuJoCo state vector) is the demonstration's first state. After loading it, the robot holds still for 50 steps (`settle_steps`, as in LeRobot's MolmoAct2 evaluation) so objects come to rest. These steps are not counted.
- `oracle/demo_actions.json` holds the demonstration's actions. `oracle/solve.sh` replays them open-loop through the `robo` socket (`python -m robouse.oracle --backend libero`).
- The adapter replays each candidate in-process first and keeps the first demonstration (demo_0, demo_1, ...) whose replay reaches the success check. Four tasks needed demo_1 (the "Demo" column above).

Validation through the real runner: oracle 20/20 (`runs/oracle-libero`), no-op 0/20 (`runs/noop-libero`).

Caveat: these initial states come from LIBERO's training demonstrations, not from LIBERO's 50 fixed evaluation init states per task. Policies trained on LIBERO demonstrations, including MolmoAct2-LIBERO (trained on LeRobot's re-rendered copy of the same demonstrations), have therefore seen these exact starting layouts in training. For the LIBERO evaluation states, drop `init_state` from a task: the backend then loads LIBERO's benchmark init state number `seed`. There is no reference solution for those states.

## Action and observation

Action: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. This is LIBERO's own 7-D delta end-effector command for robosuite's OSC_POSE controller at 20 Hz.

- 1.0 on DX/DY/DZ asks for 5 cm per step. The arm lags behind the request, and holding an axis at 1.0 moves the hand about 1 cm per step (measured: 4.4-5.9 cm over 5 steps).
- DROLL/DPITCH/DYAW: 1.0 asks for 0.5 rad.
- GRIPPER: -1 opens, +1 closes.
- The `move_to`/`grip` skills work. They send `[dx, dy, dz, grip]`, which the backend pads with zero rotation.

World frame, in metres: +x forward, away from the robot base; +y to the robot's left; +z up. The table surface is at about z = 0.90.

| Field | Meaning |
|---|---|
| hand_pos | end-effector position (`robot0_eef_pos`) |
| eef_quat, eef_axis_angle | end-effector orientation, quaternion (x, y, z, w) and axis-angle |
| gripper_qpos | the two finger joint positions |
| gripper_open | finger gap in metres (about 0.08 fully open) |
| objects | `{name: {pos, quat}}` for every object in LIBERO's observation (e.g. `akita_black_bowl_1`, `plate_1`) |

Cameras: `agentview` (front, the default and the video camera) and `robot0_eye_in_hand` (wrist). Both are 256x256 and saved upright. robosuite renders them upside down, and the backend flips them. `mj_model_data` is provided, so a vision-mode variant (`obs_mode: vision`) would get projection matrices. The shipped tasks use `obs_mode: state`.

Speed on the Mac: about 40 ms per simulated step, including rendering both cameras. Creating an environment takes about 5 s after the first run.

## Results so far

| Harness | Model | Solved | Job |
|---|---|---|---|
| oracle | demonstration replay | 20/20 | `runs/oracle-libero` |
| noop | none | 0/20 | `runs/noop-libero` |
| molmoact2 | allenai/MolmoAct2-LIBERO-LeRobot | see [molmoact2.md](../molmoact2.md) | `runs/final-libero-molmoact2` |
| claude-code | claude-opus-5-5 | 1/1 smoke trial (libero-goal-8, 279 of 300 steps) | `runs/smoke-libero-claude` |
