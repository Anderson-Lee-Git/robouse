# RLE-Bench suite (tabletop reasoning)

6 tasks from [RLE-Bench](https://github.com/RLE-Bench/RLE-Bench) (Harvard and Georgia Tech, MIT), family 03 "tabletop reasoning", one of its interactive-control families, at commit `34a73aa`: build the tallest tower from mixed pieces, stack blocks as far past the table edge as they go, find the heavy cube of nine with a two-pan balance, and find the hidden ballast in each of three sealed boxes. The scenes are RLE-Bench's own code, vendored in `src/robouse/backends/rlebench/rlebench_upstream/`, with RLE-Bench's seeds, action space, public observations, step budgets and scoring.

- Backend: `src/robouse/backends/rlebench/` (`backend.py` bridge and task table, `worker.py` simulation, `oracles.py` reference solutions).
- Generator: `python adapters/rlebench/generate.py --out tasks/rle-bench`.
- Hub: dataset `rle-bench/rle-bench`, simulator runtime `rlebench`.

## What is the same as RLE-Bench

- Robot and controls: for the tower, cantilever and balance, a PandaOmron (a Franka Panda on a mobile base with a torso lift) with RLE-Bench's 12-number action (arm pose deltas in the robot base frame, absolute gripper, base velocity, torso, mode); `robo skill move` is RLE-Bench's `move()` and `robo skill reset` its `reset()`. For HiddenCOM, a fixed Panda with 7-number actions and `robo skill submit A|B|C|D`.
- Observation: RLE-Bench's public proprioception and 512 x 512 RGB images from its cameras, camera intrinsics only; BalanceCoins adds the cube and pan positions. Hidden conditions (which cube is heavy, the ballast's quadrant and masses, every mass) stay in the simulator worker.
- Budgets: 50,000 control steps and 9 hours for the tabletop tasks; 12,000 steps per box for HiddenCOM.
- Scoring: RLE-Bench's quality function for each task, computed from the final scene.

## What is adapted

- Robo Use rewards 1 or 0, and RLE-Bench has no pass mark (it reports the quality as the score). The pass mark is ours: a tabletop trial passes when RLE-Bench's quality is at least 0.5: a tower at least half the analytic optimum height, a cantilever overhang at least half the harmonic-stack optimum (more than one block alone reaches), or the heavy cube alone on the mat found with at most four weighings. `result.json` records the quality under `judge_detail`.
- HiddenCOM is one task per box (RLE-Bench runs its three boxes in one attempt and scores the fraction correct, so the mean over the three tasks is RLE-Bench's score). Each box gets 20 minutes (RLE-Bench: one hour for all three), and the episode ends when the step budget is used up, so the agent must submit before then.
- As in RLE-Bench, a tabletop scene is scored however the episode ends; `robo give-up` scores 0.
- Rendering is on the CPU (OSMesa, with numba's JIT off, RLE-Bench's supported fallback); RLE-Bench renders with EGL on an NVIDIA GPU.
- Reference solutions: HiddenCOM uses RLE-Bench's own RGB-based solver. RLE-Bench's reference solutions for the tabletop tasks replay recorded trajectories open-loop; on this build they diverge (the first grasp closes about 2 cm above the block), so the tabletop reference solutions are closed-loop controllers that read the object poses (given only to the reference solution, never masses): a four-piece tower, a two-block cantilever, and a balance search with two weighings (3 against 3, then 1 against 1).

## Not included

- Family 03's two-arm 2x2 cube (RLE-Bench has no reference solution for it, and its renderer needs EGL).
- Family 01 (RoboCasa kitchen speed-run: a development phase with a 50,000-interaction budget, then five evaluation trials) and family 02 (one agent builds a harness that five fresh agents use on a held-out task): see the RLE-Bench dataset card on the hub.

## Licence

RLE-Bench code and tasks: MIT (Copyright (c) 2026 RLE-Bench contributors). robosuite: MIT. The adaptation is BenchFlow's; the RLE-Bench authors did not publish or review it.
