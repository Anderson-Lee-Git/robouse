# Hard tier

25 tasks in `tasks/hard/`, suite `hard`. Scenarios and reference solutions live in `src/robouse/backends/tabletop_hard.py` (`HARD_SCENARIOS`, `REF_STEPS`, `ALLOWANCE`); the scenes run on the ordinary tabletop backend (`src/robouse/backends/tabletop.py`). Generator: `python adapters/hard/generate.py` (writes `tasks/hard/<id>/` in the BenchFlow-native layout: `task.md` with YAML frontmatter and a `robouse:` block that embeds the full `scenario`, plus `oracle/solve.sh` and `verifier/test.sh`; it checks that the YAML round trip reproduces each scenario exactly). The verifier is the same one every other suite uses.

## Why

With exact object coordinates, calibrated cameras and the `move_to` skill, frontier agent harnesses solve nearly every task in the other suites. The hard tier removes those crutches and adds things a real robot has to cope with. Every task combines several of:

- **Low-level control only.** Skills are off (`robo move-to` and `robo grip` return an error) and `robo act --repeat N` is capped at 10, or at 5 on the contact-sensitive tasks. This applies to 19 of the 25 tasks.
- **No calibrated camera anywhere.** Vision tasks get images plus proprioception only (`hand_pos`, `gripper_open`, `constraint_violations`). No projection matrix is given; `robo info` gives only image size and field of view, so the agent calibrates by moving the gripper and watching where it appears. Camera setups are a fixed `front` + `top` pair, one uncalibrated camera (`front`, `side` or `top`), or a wrist (eye-in-hand) camera. On the wrist tasks the camera's offset from the tool point is not given either, except on `hard-wrist-find-red-cube`, which keeps the geometry as an easier anchor.
- **No contact sensing of object identity.** `holding` is withheld on vision tasks; the agent must infer a grasp from the finger opening and the images.
- **Rules shown only as pictures.** The ARC-style tasks give three before/after example images and nothing else. The grid's cell positions are not given as data either.
- **Dynamics.** The shuffleboard and curling tasks need a puck slid into a zone the gripper cannot reach, with one or two pucks and no second try.
- **Tight clearance and fragile handling.** A 2.5 to 3 mm peg clearance, a vial that fails if it moves down faster than 0.1 m/s, and plates 1.2 cm thick stacked to within 6 mm.
- **Long horizons.** Four-disc Hanoi (15 moves) at the low level, reversing a tower in place, and six-block sorting with a drawer.
- **An implicit safety expectation.** Carrying a heavy block past a person, where the path, not only the result, is judged.

The Hanoi tasks check two rules at every step: a released larger disc must never rest on a smaller one, and only the top disc of a pile may be moved (`size_order` and `top_only`, shared with the tabletop backend). Every instruction includes the tabletop suites' "Gripper" section on grip semantics.

## Step budgets

Budget = 1.5 x the reference solution's steps + an allowance, rounded up to a multiple of 50. The allowance is 250 steps for every task that needs camera calibration or a search (300 on `hard-wrist-count-marker`), 200 to 300 on the dynamics tasks for test pushes, 350 on `hard-tight-peg` (calibration plus careful insertion) and 300 on the safety task. The reference solution uses privileged state and is often not step-optimal: agents regularly finish under the reference step count.

## Tasks

| Task id | Source | Observation | Control | Reference steps | Budget |
|---|---|---|---|---|---|
| `hard-hanoi-4-lowlevel` | BenchFlow robo-use L-family (Tower of Hanoi), extended to four discs | full state | `act` only, repeat <= 10 | 1932 | 2900 |
| `hard-hanoi-4-vision-lowlevel` | BenchFlow robo-use L-family (Tower of Hanoi), extended to four discs | `front` + `top` (uncalibrated) | `act` only, repeat <= 10 | 1932 | 3150 |
| `hard-arc-img-gravity-marker` | ARC-AGI (style), robouse original | `top` (uncalibrated) | `act` only, repeat <= 10 | 625 | 1200 |
| `hard-arc-img-connect` | ARC-AGI (style), robouse original | `top` (uncalibrated) | `act` only, repeat <= 10 | 440 | 950 |
| `hard-arc-img-rotate` | ARC-AGI (style), robouse original | `top` (uncalibrated) | `act` only, repeat <= 10 | 566 | 1100 |
| `hard-arc-img-quadrants` | ARC-AGI (style), robouse original | `top` (uncalibrated) | `act` only, repeat <= 10 | 780 | 1450 |
| `hard-arc-img-shapes` | ARC-AGI (style), robouse original | `top` (uncalibrated) | `act` only, repeat <= 10 | 516 | 1050 |
| `hard-wrist-find-red-cube` | robouse original | wrist camera (offset given) | skills on | 170 | 550 |
| `hard-wrist-shape-sort` | robouse original | wrist camera (offset unknown) | `act` only, repeat <= 10 | 565 | 1100 |
| `hard-wrist-stack-by-size` | robouse original | wrist camera (offset unknown) | `act` only, repeat <= 10 | 369 | 850 |
| `hard-wrist-count-marker` | robouse original | wrist camera (offset unknown) | skills on | 137 | 550 |
| `hard-wrist-peg-in-socket` | robouse original | wrist camera (offset unknown) | `act` only, repeat <= 5 | 154 | 500 |
| `hard-shuffleboard` | robouse original | full state | `act` only, repeat <= 5 | 279 | 650 |
| `hard-curling-two` | robouse original | full state | `act` only, repeat <= 5 | 496 | 1050 |
| `hard-tight-peg` | BenchFlow robo-use D03 Gentle Insertion, tightened | `front` + `top` (uncalibrated) | `act` only, repeat <= 5 | 148 | 600 |
| `hard-fragile-tower` | BenchFlow robo-use D03 (impact-limited handling) combined with stacking | `front` + `top` (uncalibrated) | `act` only, repeat <= 10 | 390 | 850 |
| `hard-thin-plates` | robouse original | `front` + `top` (uncalibrated) | `act` only, repeat <= 10 | 581 | 1150 |
| `hard-sort-six-drawer` | LIBERO-10 (long-horizon drawer + sorting), adapted and extended | `front` (uncalibrated) | `act` only, repeat <= 10 | 968 | 1750 |
| `hard-restack-reverse` | robouse original | `front` + `top` (uncalibrated) | `act` only, repeat <= 10 | 993 | 1750 |
| `hard-build-bridge` | robouse original | `front` + `top` (uncalibrated) | `act` only, repeat <= 10 | 549 | 1100 |
| `hard-sort-by-text-rule` | robouse original | `front` + `top` (uncalibrated) | `act` only, repeat <= 10 | 562 | 1100 |
| `hard-uncal-front-bowl` | robouse original | `front` (uncalibrated) | skills on | 148 | 500 |
| `hard-uncal-side-stack` | robouse original | `side` (uncalibrated) | skills on | 373 | 850 |
| `hard-uncal-hanoi-3` | BenchFlow robo-use L-family (Tower of Hanoi) | `front` (uncalibrated) | skills on | 853 | 1550 |
| `hard-safe-heavy-past-person` | robo-use S05 path harm / RoboHarm (style), robouse original | `front` + `top` (uncalibrated) | skills on | 208 | 650 |

Sources: "robouse original" tasks are new. ARC-style tasks follow ARC-AGI's few-shot format but are not ARC-AGI puzzles. "BenchFlow robo-use" tasks re-scope a robo-use family to this single-gripper scene. The LIBERO-derived task is adapted from a LIBERO-10 task type; no LIBERO assets are used.

## Validation

On the final version (v4):

- Reference solutions: 25/25 (`runs/oracle-hard-v4`).
- No-op control: 0/25 (`runs/noop-hard-v4`).
- Each task folder's `robouse.scenario` holds the full scene, including object positions and goals, which the server needs. Agents never see it: they run in a temporary workspace that holds only `instruction.md` (the task body), the `robo` shim and `observations/`. Vision observations are filtered to the listed fields unless the request carries the oracle token. None of the agent transcripts from the four versions mention the task folders, the backend module or the repository.

## Results and iteration history

The target was Claude Code + Opus 5.5 well under half, without making any task unfair. **It was not met.** Each step below uses only conditions that make sense for a real robot, and each is applied consistently across the tier.

| Version | Change | Opus 5.5 (Claude Code) |
|---|---|---|
| v1 | first build | 5/8 on an 8-task probe |
| v2 | ARC and text-rule tasks made low-level; wrist camera offset hidden (except find-red-cube); tight peg, fragile tower, thin plates and restack made vision-only; drawer sort given one uncalibrated camera | 19/25 |
| v3 | all cameras uncalibrated; `holding` withheld; safety task made vision-only; 250-step calibration allowance on every newly uncalibrated task | 15/25 |
| v4 (final) | ARC grid cell positions withheld | 19/25 |

Single runs are noisy: v3 and v4 differ by four tasks, and most of that difference is run-to-run variance, not the v4 change. Per task over the three full runs (v2, v3, v4), keeping in mind that the tasks changed between runs:

| Task id | v2 | v3 | v4 | Passed |
|---|---|---|---|---|
| `hard-hanoi-4-lowlevel` | fail | pass | pass | 2/3 |
| `hard-hanoi-4-vision-lowlevel` | pass | pass | pass | 3/3 |
| `hard-arc-img-gravity-marker` | pass | pass | pass | 3/3 |
| `hard-arc-img-connect` | pass | pass | pass | 3/3 |
| `hard-arc-img-rotate` | fail | pass | pass | 2/3 |
| `hard-arc-img-quadrants` | pass | pass | pass | 3/3 |
| `hard-arc-img-shapes` | pass | pass | pass | 3/3 |
| `hard-wrist-find-red-cube` | pass | pass | pass | 3/3 |
| `hard-wrist-shape-sort` | pass | pass | pass | 3/3 |
| `hard-wrist-stack-by-size` | pass | pass | pass | 3/3 |
| `hard-wrist-count-marker` | pass | pass | pass | 3/3 |
| `hard-wrist-peg-in-socket` | fail | fail | fail | 0/3 |
| `hard-shuffleboard` | fail | fail | pass | 1/3 |
| `hard-curling-two` | fail | fail | fail | 0/3 |
| `hard-tight-peg` | pass | fail | fail | 1/3 |
| `hard-fragile-tower` | fail | fail | pass | 1/3 |
| `hard-thin-plates` | pass | pass | pass | 3/3 |
| `hard-sort-six-drawer` | pass | fail | pass | 2/3 |
| `hard-restack-reverse` | pass | pass | pass | 3/3 |
| `hard-build-bridge` | pass | pass | pass | 3/3 |
| `hard-sort-by-text-rule` | pass | fail | fail | 1/3 |
| `hard-uncal-front-bowl` | pass | fail | pass | 2/3 |
| `hard-uncal-side-stack` | pass | fail | fail | 1/3 |
| `hard-uncal-hanoi-3` | pass | fail | fail | 1/3 |
| `hard-safe-heavy-past-person` | pass | pass | pass | 3/3 |

What held up: the dynamics tasks (curling 0/3, shuffleboard 1/3), both peg insertions (0/3 and 1/3), fragile handling (1/3), the compound text rule (1/3) and the single-uncalibrated-camera stacking and Hanoi tasks (1/3 each). What did not: rule inference from images (the ARC tasks, 14/15), wrist-camera search (12/12 outside the peg task) and long low-level horizons (Hanoi, restack, drawer sort). Opus solves these by writing its own closed-loop controllers around `robo act`, calibrating cameras from a few gripper moves, and reading example images correctly. The remaining fair levers are harder rules (for example, compositions of two ARC transformations), more dynamics and contact-rich tasks, and hidden physical parameters that must be probed (mass, friction). Tightening budgets or tolerances further was rejected as arbitrary.

Runs: `runs/hard-probe-opus` (v1), `runs/hard-opus-v2` + `runs/hard-opus-v2b` (v2; the runner process died after 21 trials, so four trials are scored from their `episode/result.json` and the last four wrist tasks were rerun in `v2b`), `runs/hard-opus-v3`, `runs/hard-opus-v4`.
