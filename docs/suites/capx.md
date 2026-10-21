# CaP-X suite (code as policy)

Tasks from [CaP-X](https://github.com/capgym/cap-x) (NVIDIA, UC Berkeley, Stanford and CMU; MIT; arXiv 2603.22435) at commit `53e9966`, in two suites. The agent controls the robot by writing Python code that calls CaP-X's API for the task.

- `capx` (35 tasks): CaP-Bench's seven RoboSuite tasks (lift a cube, stack two cubes, restack them, wipe a spill, put a nut on a peg, lift a pot with two arms, hand a hammer from one arm to the other), each in five fixed layouts (seeds 1-5; the two-arm lift uses seeds 1, 3, 5, 7 and 8, because CaP-X's reference code does not lift the pot in the layouts of seeds 2, 4 and 6).
- `capx-libero` (8 tasks): LIBERO-PRO's `libero_object_swap` tasks (pick an item and put it in the basket, with the items' positions swapped), with LIBERO's first initial state (CaP-X's trial 1) and CaP-X's privileged LIBERO API. CaP-X's LIBERO reference code (written for the milk, task 7) solves 8 of the 10 with the item's name swapped in; the ketchup (task 4) and the chocolate pudding (task 8) are left out, as is `libero_spatial_swap` (the code grasps the bowls at their centre, which fails, and CaP-X has no reference code for it).

- Backend: `src/robouse/backends/capx/` (`backend.py` bridge, `worker.py` simulation, `capx_api.py` the Python module agents use, `oracles.py` reference solutions, `capx_upstream/` the vendored CaP-X code).
- Generator: `python adapters/capx/generate.py --capx PATH/TO/cap-x --out tasks/capx` (API documentation from `adapters/capx/api_docs.py`).
- Hub: dataset `capgym/cap-x`, simulator runtimes `capx` (RoboSuite) and `capx-libero` (LIBERO-PRO on CaP-X's robosuite 1.4 fork).

## What is the same as CaP-X

- The environments are CaP-X's own low-level RoboSuite environments on CaP-X's robosuite fork (1.5.1, commit `97292732`) with MuJoCo 3.5.0, and the API is CaP-X's privileged API for each task (object poses from the simulator), running unchanged: `get_object_pose`, `sample_grasp_pose`, `goto_pose` (PyRoKi inverse kinematics, then CaP-X's joint-position controller), `open_gripper`, `close_gripper`, and the task-specific functions (nut assembly's `goto_home_joint_position`, the two-arm functions).
- The task text is CaP-X's prompt for the task and the API documentation is CaP-X's, as it writes them into its own prompt.
- The step budget is CaP-X's horizon for the task, counted in robosuite control steps; success is CaP-X's `task_completed()`.
- PyRoKi runs on the CPU, as in CaP-X's `--profile minimal` for privileged evaluations.

## What is adapted

- Each API function is a robot skill (`robo skill NAME ARG ...`), and the instruction gives the agent `capx_api.py`, which turns the skills back into Python functions with CaP-X's names and signatures. Every robosuite step an API call takes is one step of the episode, recorded and budgeted by the episode server.
- Tier: CaP-Bench's S1 tier gives this API in a single turn, one program run once. A coding agent in a shell cannot be held to one program, so here it may run code several times and read each call's output, and it can look at the scene camera. That is multi-turn interaction on the S1 API, which is not one of CaP-Bench's eight tiers; results are not comparable to CaP-Bench's S1 numbers.
- There is no low-level control (`robo act 0` only holds still), as CaP-X's agent has only the API.
- Each task is one fixed layout (robosuite's placement sampler seeded with the task's seed); CaP-X samples a new layout for every trial.
- Success is judged after `robo done` and 10 still steps; CaP-X judges when the code finishes.
- Reference solutions are CaP-X's own reference code for each task, run through `capx_api.py`. For the spill, CaP-X's code wipes at z = 0 (its prompt says the table is at z = 0), which keeps the sponge about 8 cm above the table in CaP-X's environment; the reference wipes at z = -0.10 instead. The prompt is kept as CaP-X wrote it.

## Not included

- The perception tiers (S2-S4 and M1-M4): they need SAM3, Molmo 2, OWL-ViT, SAM2 and Contact-GraspNet model servers on a GPU, and SAM3's weights are gated. No perception is replaced with simulator state.
- BEHAVIOR tasks (Isaac Sim on a GPU), the LIBERO-PRO tasks named above, and LIBERO-PRO suites whose task files are not in CaP-X's pinned LIBERO-PRO.
- CaP-X's LIBERO API function `goto_pose_interactive_cartesian`, which takes a Python function as its target and so cannot pass through `robo`.

## Run it without the image

The suites' simulator environment is robohub's `runtimes/capx` image (`runtimes/capx-libero` for LIBERO-PRO). To run the `capx` suite from a checkout instead, build the same CaP-X virtualenv the image builds (Linux, Python 3.12, uv; the pins are the image's `requirements-capx.txt`) and point Robo Use at it:

```sh
W=~/capx && mkdir -p $W && git init -q $W/robosuite-capx
git -C $W/robosuite-capx fetch -q --depth 1 https://github.com/uynitsuj/robosuite.git 97292732ed909ac3ae116579fb768607034a4dbd
git -C $W/robosuite-capx checkout -q FETCH_HEAD
uv venv -p 3.12 $W/capx-venv
uv pip install -p $W/capx-venv/bin/python --no-deps -r requirements-capx.txt
uv pip install -p $W/capx-venv/bin/python --no-deps "pyroki @ git+https://github.com/chungmin99/pyroki.git@95afccc22658c461ab1042a048ae4e9c24bc2a47"
uv pip install -p $W/capx-venv/bin/python --no-deps -e $W/robosuite-capx
export ROBOUSE_CAPX_PYTHON=$W/capx-venv/bin/python ROBOT_DESCRIPTIONS_CACHE=$W/robot_descriptions
export JAX_PLATFORMS=cpu JAX_COMPILATION_CACHE_DIR=$W/jax-cache NUMBA_DISABLE_JIT=1
robouse run --task tasks/capx/capx-cube-stack-s1 --harness oracle --out runs/capx
```

The first episode downloads the `panda_description` robot model that PyRoKi loads and compiles its inverse kinematics into the JAX cache. Built this way on Linux x86_64 (2026-10-20), the reference solution solved `capx-cube-stack-s1` in 217 steps and about 40 seconds.

## ASPIRE

The `aspire` and `aspire-codex` harnesses ([Run agents and VLAs](../run-agents.md#aspire)) run NVIDIA's ASPIRE workflow on these suites. ASPIRE's own campaigns use cap-harness's perception API on a GPU; here its programs use the API above, and its practice episodes run on other seeds of the task: development seeds 101 to 125 and unseen-check seeds 126 to 130 on `capx` (ASPIRE's Robosuite bands), and on `capx-libero` saved initial states 35 to 49 and 20 to 34 (seeds 36 to 50 and 21 to 35), since seed n restores state (n - 1) % 50 and ASPIRE's LIBERO bands (51 to 80) would replay the scored state 0. The five tasks of one CaP-X task (`capx-cube-stack-s1` to `-s5`) are five held-out scenes of one ASPIRE task: with a persistent library, the first trial selects a program and the others evaluate it.

## Licence

CaP-X: MIT (Copyright (c) 2026 Max Fu). CaP-X's robosuite fork: MIT. PyRoKi: MIT. The adaptation is BenchFlow's; the CaP-X authors did not publish or review it.
