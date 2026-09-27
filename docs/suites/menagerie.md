# Menagerie suite (robo-use scenes: dual Franka Panda and ALOHA 2)

15 tasks on the robo-use workspace's desk scenes: two real robot arms from [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie), either two Franka Emika Panda arms or an ALOHA 2 pair of ViperX 300 arms, mounted side by side at the back edge of a desk and reaching forward. The scenes, physics settings, success thresholds and reference controllers come from the robo-use workspace (benchflow-ai/robo-use-workspace: `src/robo_use/*_scene.py`, `oracle.py`, `patterns.py`) and from the four finished dual-arm tasks of the robotics-tasks-20260917 batch that was built on it (precise landing, clutter retrieval, gentle insertion, two bowls to board). Here they are driven live through `robo`, one 50 ms control step at a time, instead of by a submitted policy file.

- Backend: `src/robouse/backends/menagerie.py` (task table `TASKS`, action interface, observation) and `src/robouse/backends/menagerie_sim/` (scenes, IK, success checks in `families.py`, reference solutions in `oracles.py`).
- Generator: `python adapters/menagerie/generate.py --out tasks/menagerie`.
- Assets: `assets/menagerie/` (41 MB): the Menagerie `franka_emika_panda` (Apache-2.0) and `aloha` (BSD-3-Clause, Trossen Robotics) models at commit `8161bba264d7fa7c99ca301e91e7fb44737676ad`, with each model's LICENSE and README. Only the files `panda.xml` and `aloha.xml` reference are included; `provenance.json` lists every file with its upstream URL and SHA-256. Override the location with `ROBOUSE_MENAGERIE_ASSETS`.

## Scene and physics

World frame in metres: +x right, +y toward the robot bases (the back of the desk), +z up, desk top at z = 0. Bases at x = -0.35 ("left") and x = +0.35 ("right"), y = 0.30, both facing -y. Two bowls (28 cm across, 3 cm segmented rim) at x = +-0.36, y = -0.12; the task fixtures (chessboard, tray, socket, pattern grid, kit tray, bin, column) in between. Every task object is a free rigid body that moves only through contact and friction; nothing is welded, attached or teleported. Physics runs at 2 ms, control at 50 ms, joint targets are slew-limited at 1.2 rad/s and the arm joints get ideal gravity compensation, all as in robo-use `control.py`. The Panda grip is Menagerie's (v1 "pinned" contact revision in robo-use terms: about 0.6 N per finger), so fast swings and high grasps do drop things.

Cameras: `workspace` (a front view from above the desk edge; default for videos), `top` (straight down over the working area), `overhead` and `overview` (robo-use's own cameras), plus `inspect` (looking up from the inspection station) in the fragile-kit task. `workspace` and `top` are robouse additions.

## Action and observation

The agent drives a Cartesian target for each arm it controls; IK (robo-use's damped least-squares solver, warm-started and bounded so an unreachable target makes the arm stop at the closest pose instead of failing) turns it into joint targets every step. The gripper always points straight down.

- One step moves an arm's commanded target by DX, DY, DZ x 2 cm (each in [-1, 1]) along world axes. The target is clamped to the reachable desk volume and to within 5 cm of the measured gripper point, so a blocked arm does not wind up.
- DYAW (only on tasks with yaw): turns the gripper about the vertical by 10 degrees per unit, limit +-100 degrees; at yaw 0 the fingers close along world y.
- GRIP: 0 keeps the fingers as they are, any positive value closes them, a negative value -f opens them to fraction f (-1 fully open, -0.4 = 40 % open). 0 = keep is what makes the server's settle hold (all zeros) safe for every layout.
- Layouts (task field `arms`): single arm `[DX, DY, DZ, GRIP]` (`move-to`/`grip` drive that arm); `switch` `[ARM, DX, DY, DZ, GRIP]` where ARM -1/+1 selects the left/right arm and the other holds (skills drive the selected arm); `both` `[L_DX, L_DY, L_DZ, L_GRIP, R_DX, R_DY, R_DZ, R_GRIP]`, both arms on one clock, no skills. DYAW is inserted before GRIP on yaw tasks.
- `robo observe`: per arm `hand_pos` (measured point between the fingertips), `hand_target`, `gripper_open`, `hand_yaw_deg` (yaw tasks) and `touching` (task objects in contact with that arm); per object `<name>_pos` (centre of its base), `<name>_tilt_deg`, `<name>_yaw_deg`; the task's goal fields; `robot` and `time_s`. In `switch`/`both` tasks the arm fields carry `left_`/`right_` prefixes.
- Vision tasks use the session's `obs_mode: vision`: the listed `visible_fields` plus one image per camera and calibrated projection matrices (`mj_model_data` is implemented). The two `-vision` tasks hide all object poses; the fragile kit hides only the vials' labels.

## Tasks

Success is judged by the trusted server after `robo done` and a 10-step hold (`success_mode: final`). "Released" = no robot contact with the object; "at rest" = slower than 1 cm/s and 0.1 rad/s. Protected-object limits are checked at every control step of the episode, not just at the end.

| Task | Robot | Family / provenance | Arms | Budget | Oracle steps | Success rule |
|---|---|---|---|---|---|---|
| menagerie-panda-precise-landing | Panda | D01; robotics-tasks `dual-panda-precise-landing` | left | 600 | 201 | block centre within 12 mm of the gold square's centre, resting on the board, tilt <= 10 deg, released, at rest |
| menagerie-aloha-pawn-landing | ALOHA 2 | D01 Precise Landing (robo-use pawn) | right | 600 | 280 | as above, for a chess pawn |
| menagerie-aloha-pawn-landing-vision | ALOHA 2 | D01, vision-only variant | left | 600 | 280 | as above; pawn position only in images |
| menagerie-panda-clutter-retrieval | Panda | D02; robotics-tasks `panda-clutter-retrieval` | left | 800 | 228 | target within 15 mm of tray centre, resting on the tray floor, tilt <= 12 deg, released, at rest; no violet neighbour ever moved > 8 mm or tilted > 15 deg |
| menagerie-aloha-clutter-retrieval | ALOHA 2 | D02 Clutter Retrieval | right | 800 | 310 | as above |
| menagerie-panda-clutter-retrieval-vision | Panda | D02, vision-only variant | left | 800 | 229 | as above; object positions only in images |
| menagerie-aloha-gentle-insertion | ALOHA 2 | D03; robotics-tasks `aloha2-gentle-insertion` | left | 1200 | 491 | peg base inside the 23 mm aperture and >= 80 % inserted, tilt <= 8 deg, released, at rest; peg-socket contact force never above 6 N |
| menagerie-panda-keyed-insertion | Panda | D03 Gentle Insertion (keyed 18 x 12 mm shaft, 21 x 15 mm socket), peg starts turned 35-60 deg | right, yaw | 1500 | 662 | whole shaft footprint inside the aperture, base within 2 mm of the socket floor, tilt <= 3 deg, released, at rest; contact force never above 10 N |
| menagerie-panda-pattern-apprentice | Panda | D04 Pattern Apprentice, development split (seed 5: reflection) | switch | 2000 | 718 | each token within 10 mm of the centre of the cell the rule maps its label to, upright, released, at rest; violet distractors never moved > 5 mm / tilted > 10 deg |
| menagerie-aloha-pattern-heldout | ALOHA 2 | D04, held-out compositional split (seed 5: reflect + half turn + shift, two examples) | switch | 2000 | 961 | as above |
| menagerie-panda-two-bowls-to-board | Panda | L01 (reduced); robotics-tasks `dual-panda-two-bowls-to-board` | both | 3000 | 984 | all 8 pieces within 12 mm of their own squares, resting, tilt <= 10 deg, released, at rest |
| menagerie-aloha-opening-four | ALOHA 2 | L01 Opening Night (reduced to 4 pieces) | both | 2000 | 702 | all 4 pieces placed as above, and each arm last held at least one placed piece |
| menagerie-panda-fragile-kit | Panda | L03 Fragile Kit (hidden underside labels) | switch | 2500 | 910 | every vial upright in the compartment of its hidden label colour (within 10 mm, resting, released, at rest); every vial was held over the inspection camera (within 3 cm, 4-25 cm up, tilt < 20 deg); ampoules never moved > 5 mm / tilted > 10 deg |
| menagerie-panda-route-around | Panda | S05 path constraint | left | 1000 | 503 | payload within 15 mm of the delivery pad centre, resting, upright, released, at rest; nothing but the desk ever touched the 60 cm protected column (sampled every 10 ms) |
| menagerie-panda-fragile-disposal | Panda | S04 fragile handling versus disposal | left | 1000 | 376 | vial upright on the gold square (10 mm), released, at rest; blank inside the bin; vial never fell faster than 0.25 m/s while unsupported (sampled every 10 ms); vial never entered the bin |

Adaptations from the sources: the robotics-tasks scenes run at their nominal physical condition (no hidden mass/friction/base-offset randomisation, which served held-out policy evaluation there), and their continuous 0-1 quality scores become the binary success predicates their verifiers already used for "completion". robo-use's own verifiers are deliberately unscored; the predicates above follow its public acceptance numbers where the Cartesian interface can meet them (for example the keyed-insertion tilt limit is 3 degrees instead of 2, and protected objects may shift 5-8 mm instead of 2 mm). The fragile-kit inspection uses an upward camera at a station instead of flipping a vial, because the gripper always points down. The pattern tasks use robo-use's finite rule grammar and instance generator unchanged (`scenes/ru_patterns.py`); the reference solution solves the rule by enumerating the grammar over the public examples.

## Validation

- Reference solutions (`menagerie_sim/oracles.py`, driving only the robo socket; step counts above): `robouse run-many --tasks tasks/menagerie --harness oracle`: **15/15** (runs/_v1-oracle-menagerie). The keyed-insertion solution regrasps: it picks the peg by the flat shaft faces (a twist of the round handle slips), squares it, sets it down, re-picks it by the handle and inserts at 1.2 cm/s.
- No-op control (`--harness noop`): **0/15** (runs/_v1-noop-menagerie).
- Difficulty probe 1, claude-code + claude-opus-5-5 (run before the owner paused Opus trials), `--limit 6` (the first six tasks alphabetically: both ALOHA clutter/insertion/opening-four/pattern-heldout/pawn-landing and Panda clutter retrieval): **6/6**, 125-423 steps, 35-132 s each (runs/_probe-menagerie-opus). The model wrote its own small P-controller around `robo act` and used `touching` and the measured offsets; it solved the bimanual opening-four task by moving both arms in the same steps.
- Difficulty probe 2, codex + gpt-6-astra, `--limit 6` (the first six tasks alphabetically after the vision variants were added, so it includes `menagerie-aloha-pawn-landing-vision`): **6/6** (runs/_probe-menagerie-astra).

## Probe results

| Task | Opus 5.5 (claude-code) | GPT-6 Astra (codex) | Oracle steps |
|---|---|---|---|
| menagerie-aloha-clutter-retrieval | solved, 199 steps, 64 s | solved, 298 steps, 69 s | 310 |
| menagerie-aloha-gentle-insertion | solved, 217 steps, 43 s | solved, 328 steps, 57 s | 491 |
| menagerie-aloha-opening-four | solved, 365 steps, 132 s | solved, 388 steps, 92 s | 702 |
| menagerie-aloha-pattern-heldout | solved, 423 steps, 83 s | solved, 405 steps, 75 s | 961 |
| menagerie-aloha-pawn-landing | solved, 125 steps, 35 s | solved, 189 steps, 51 s | 280 |
| menagerie-aloha-pawn-landing-vision | not run | solved, 202 steps, 85 s | 280 |
| menagerie-panda-clutter-retrieval | solved, 128 steps, 38 s | not run | 228 |

Both agents solved every probed task, faster than the reference solutions. The probes cover the ALOHA tasks and the easiest Panda task; the keyed insertion, fragile kit, two-bowls, route-around and fragile-disposal tasks have not been probed yet.

## Limitations

- Dropped: L02 Set and Clear (ALOHA). The plate, fork and spoon placements worked, but the port could not make the utensil placements and the cup grasp reliable with a vertical gripper (forks flipped or were pushed off their slots), so the task is not included. L04 Assembly Workcell (press tool, keyed post, cap) and S01-S03/S06 were not ported.
- The gripper orientation is fixed (straight down, plus yaw where enabled), so robo-use's full-orientation corrections are not available; tasks were chosen and toleranced accordingly.
- The contact-force limits are simulator proxies sampled every 10 ms, not hardware ratings (as robo-use states for its own numbers).
- The scenes are rendered and judged in the robouse process; `benchflow/export.py` copies `src/robouse` but not `assets/menagerie`, so containerised export needs the assets directory added (or `ROBOUSE_MENAGERIE_ASSETS`).
- The probes show these tasks, including a vision-only one, are within reach of frontier coding agents that write their own controllers (12/12 probed trials solved). The unprobed long-horizon (two bowls, fragile kit), regrasp (keyed insertion) and constraint tasks are the candidates to discriminate; harder variants (vision-only for the long tasks, tighter budgets, `max_repeat` limits) are the obvious next step.
