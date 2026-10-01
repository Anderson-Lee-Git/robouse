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

## Licence

CaP-X: MIT (Copyright (c) 2026 Max Fu). CaP-X's robosuite fork: MIT. PyRoKi: MIT. The adaptation is BenchFlow's; the CaP-X authors did not publish or review it.
