# LIBERO-PRO suite

LIBERO-PRO's perturbed LIBERO tasks on a Franka Panda in LIBERO's MuJoCo / robosuite scenes: `tasks/libero-pro/` (suite `libero-pro`, 73 tasks, backend `libero`). They are the 80 (suite, task) pairs NVIDIA's ASPIRE reports its LIBERO-Pro results on, less the seven listed under [Left out](#left-out): the ten tasks of each of LIBERO-PRO's `swap` suites (LIBERO's objects start in each other's places) and `task` suites (LIBERO's scene with a new goal) for LIBERO-Goal, -Object, -Spatial and -Long (`libero_10`). Ids are `libero-pro-<family>-<swap|task>-<k>`, where `k` is the task's index in the LIBERO-PRO suite (LIBERO's own task order), so `libero-pro-goal-task-8` is ASPIRE's `libero_goal_task:8` (`metadata.aspire_task_ref`).

- Generator: `python adapters/libero-pro/generate.py --root tasks`, in the LIBERO virtualenv ([LIBERO setup](../suites.md#libero)). It downloads LIBERO-PRO's BDDL and init files for the 80 pairs from the pinned commit (or reads a checkout, `--source`), runs the reference solution on each task in-process and writes the tasks it solves; `--only libero_goal_task:8,...` regenerates some.
- Backend: the LIBERO backend (`src/robouse/backends/libero/backend.py`), which takes a task's own BDDL file and init file ([LIBERO](libero.md#initial-state-and-reference-solution)). Reference solution: `src/robouse/backends/libero/solver.py`.

## Source and licence

- LIBERO-PRO: Xueyang Zhou, Yangming Xu, Guiyao Tie, Yongchao Chen, Guowen Zhang, Duanfeng Chu, Pan Zhou and Lichao Sun, "LIBERO-PRO: Towards Robust and Fair Evaluation of Vision-Language-Action Models Beyond Memorization", [arXiv 2510.03827](https://arxiv.org/abs/2510.03827). Code: [Zxy-MLlab/LIBERO-PRO](https://github.com/Zxy-MLlab/LIBERO-PRO); project page: [zxy-mllab.github.io/LIBERO-PRO-Webpage](https://zxy-mllab.github.io/LIBERO-PRO-Webpage/). It builds on LIBERO (Liu et al. 2023).
- The files come from the fork ASPIRE pins as its `third_party/LIBERO-PRO` submodule, [uynitsuj/LIBERO-PRO](https://github.com/uynitsuj/LIBERO-PRO) at `47aaa8038930bcdc84ab9ea2867e2ffc8039ab4a` (ASPIRE's `configs/dependency-lock.json`): LIBERO-PRO's master up to 2026-01-09 plus four commits that change import paths and add init helpers. MIT licence, "Copyright (c) 2023 Lifelong Robot Learning" (LIBERO's licence file, which LIBERO-PRO keeps): [licenses/LIBERO-PRO-MIT.txt](../../licenses/LIBERO-PRO-MIT.txt), and an entry in NOTICE.
- Each `task.md` carries LIBERO-PRO's BDDL file for the task verbatim (`robouse.bddl`, `libero/libero/bddl_files/<suite>/<task>.bddl`) and the first state of its init file (`robouse.init_state`). The other states are downloaded at run time from the pinned commit (`robouse.init_states.url`) and checked against their SHA-256; the task folders do not carry them.
- LIBERO-PRO also publishes the BDDL and init files as the Hugging Face dataset [zhouxueyang/LIBERO-Pro](https://huggingface.co/datasets/zhouxueyang/LIBERO-Pro) (CC BY 4.0 for the dataset); this suite takes them from the git repository, under its MIT licence, at the commit ASPIRE uses.
- ASPIRE: [NVlabs/ASPIRE](https://github.com/NVlabs/ASPIRE) (Apache 2.0), "ASPIRE: Agentic /Skills Discovery for Robotics", [arXiv 2607.00272](https://arxiv.org/abs/2607.00272). The 80 pairs are its `REQUIRED_SUITE_NAMES` (`src/cap_harness/libero/registry.py`); nothing of ASPIRE is copied here.

## The tasks

- Scene: LIBERO-PRO's BDDL file, which LIBERO's own environment classes build (hf-libero 0.1.4, the package the `libero` suite runs). LIBERO-PRO's `swap` and `task` files use only LIBERO's objects and problem classes: of the LIBERO source files LIBERO-PRO changes, the ones these scenes use differ from LIBERO's only in import paths, and every scene asset the 80 tasks load is byte-identical to the copy hf-libero downloads (585 files, compared by git blob hash).
- Start: the seed picks a state of LIBERO-PRO's init file for the task (50 states each), as ASPIRE's `--init-mode saved` does: seed n starts from state (n - 1) mod 50. The task's own seed is 1 (state 0, the copy in `task.md`); `robouse run-many --seeds 1-50` runs all 50. The robot then holds still for 10 steps, as in ASPIRE and LIBERO-PRO's evaluation, before the agent's first step.
- Instruction: the BDDL file's `(:language ...)` as written, which ASPIRE gives its agents (`get_task_context().language`); `metadata.language_instruction` holds it for VLA clients. LIBERO's task list derives an instruction from the file name instead, which in the `task` suites is the old goal; neither the prompt nor `robo info` names the file.
- Success: LIBERO's own check of the BDDL goal predicates (`check_success()`), evaluated by the episode server; the episode ends as solved the first time it holds (`success_mode: first`), LIBERO-PRO's protocol.
- Budget: 1000 steps at 20 Hz (50 s of simulated time), ASPIRE's episode length for LIBERO-Pro. Agent wall-clock limit 1800 s (2400 s for LIBERO-Long).
- Observation (`obs_mode: vision`): the robot's own state (`hand_pos`, `eef_quat`, `eef_axis_angle`, `gripper_qpos`, `gripper_open`) and two 256x256 cameras, `agentview` and `robot0_eye_in_hand`, saved on every `robo observe`. Object poses are not given, as ASPIRE's agents do not get them. `robo info` gives each camera's 3x4 projection matrix, checked against a segmentation render (see [Checks](#checks)).
- Action: LIBERO's 7-D delta end-effector command for robosuite's OSC_POSE controller, and the `move_to` / `grip` skills, as in the `libero` suite ([LIBERO](libero.md#action-and-observation)).

## Relation to ASPIRE's evaluation

The same: the (suite, task) pairs (73 of ASPIRE's 80); LIBERO-PRO's files at the commit ASPIRE pins; LIBERO's success check of the BDDL goal; 20 Hz control; 1000-step episodes; the saved-state start with ASPIRE's seed numbering; 10 settle steps; the instruction from the BDDL file.

Different, and why:

- robosuite: ASPIRE pins [Max-Fu/robosuite](https://github.com/Max-Fu/robosuite) at `a498b087`, which is robosuite 1.4.0 (ARISE-Initiative `fbee584`, 2022-11-29) plus one commit, "make offscreen rendering possible": the EGL context, the choice of MuJoCo's GL backend moved into the render context, and room for 10000 geoms in a rendered scene. It changes nothing in the physics or the controllers, so this suite runs robosuite 1.4.0 from PyPI, the `libero` suite's install. MuJoCo is 3.3.0 in both.
- Controller: ASPIRE drives the arm with absolute joint targets (robosuite's JOINT_POSITION controller); these tasks keep LIBERO's OSC_POSE end-effector deltas, the action LIBERO's VLAs and the `libero` suite use. An ASPIRE harness has to turn its joint-space plans into end-effector motions.
- When success counts: LIBERO-PRO ends an episode at the first success; ASPIRE checks once, when the agent's program ends. A goal that holds for a moment and is then undone counts here, not in ASPIRE.
- Init mode: `saved` is ASPIRE's default for `cap-harness run`. ASPIRE's own iterative-debugging evaluation, behind its 99% figure, runs `--init-mode seeded` on held-out seeds 1 to 50: LIBERO's placement sampler draws the layout from the BDDL regions with the seed. The backend has that mode too (`init_mode: seeded` in a task's `robouse:` block). The shipped tasks use `saved`: the saved states are LIBERO-PRO's own fixed starts (50 per task, in the init files it ships for evaluation), the same bytes on every machine (checked by SHA-256), and the start the reference solution is checked from. In `seeded` mode the layout comes from LIBERO's sampler and the seed, and no reference solution has been checked on those layouts.
- Cameras: ASPIRE's agents get RGB-D images (800x512 by default) with intrinsics and the camera pose, and joint positions; here they get 256x256 RGB images with projection matrices, and no depth.

## Reference solutions

LIBERO-PRO moves LIBERO's objects and changes its goals, so LIBERO's recorded demonstrations, which the `libero` suite replays, do not fit these scenes. Each task's reference solution is instead a scripted controller (`python -m robouse.oracle --backend libero_scripted`), which drives the arm through the `robo` socket with LIBERO's action, as an agent does, and reads the scene from the reference solution's privileged observation (the oracle token): the goal predicates, the pose and bounding box of every object, fixture, region and joint, and the arm's joint angles. It works out a plan from the goal predicates:

- `On` and `In`: a top-down grasp across the narrow side of a box, can or bottle, on the rim of a bowl, plate or mug, or where LIBERO's models need it (the moka pot's body, the frying pan's handle), picked so the hand clears its neighbours, tilted away from the robot's base when the object is close to it; then carry the object clear of everything on the way and lower it onto or into the target until it touches down, at a spot of the target region where neither it nor the hand hits anything, turning the wrist only as far as its last joint allows.
- `Open` of a drawer: grasp the handle with the hand turned towards the cabinet (tilted down for a low handle) and pull; objects standing in the way are moved aside first. `Close` of a drawer: move aside what stands in front of it, then push its front with the closed hand.
- `Turnon` and `Turnoff` of the stove: grasp the knob's fin and turn the wrist, as LIBERO's human operators did.

A task's `oracle/plan.json` can hold options for the solution where its defaults do not do (`OPTIONS` in the generator); none of the 73 tasks needs any. The solution is checked on each task's own seed (saved state 0); it is not a demonstration for the other 49 states.

## Left out

Seven of ASPIRE's 80 pairs have no task here: the scripted reference solution does not reach their goal, so the task could not be shown to be solvable as set up (`LEFT_OUT` in the generator). An agent may well solve them; a later solution (or a recorded demonstration) can bring them in.

| ASPIRE pair | Instruction | Goal | Why the reference solution fails |
|---|---|---|---|
| `libero_goal_task:0` | open the bottom drawer of the cabinet | `Open wooden_cabinet_1_bottom_region` | the bottom drawer's handle is 5 cm above the table, under the middle drawer's handle: the solution's grasps of it (level, tilted down, and 16 variants of a hook from above) hit the table or the upper handle or miss the bar, and the drawer does not open |
| `libero_10_swap:3` | put the black bowl in the bottom drawer of the cabinet and close it | `In akita_black_bowl_1 white_cabinet_1_bottom_region`, `Close white_cabinet_1_bottom_region` | the bowl goes into the open bottom drawer, but pushing the drawer shut stalls before it closes, with the bowl in it |
| `libero_10_task:3` | put the bottle in the bottom drawer of the cabinet and close it | `In wine_bottle_1 white_cabinet_1_bottom_region`, `Close white_cabinet_1_bottom_region` | the wine bottle is 16 cm tall and the bottom drawer about 7 cm deep under the middle one: standing in the open drawer, the bottle keeps it from closing; it fits only lying down, which top-down grasps cannot do |
| `libero_10_swap:6` | put the white mug on the plate and put the chocolate pudding to the right of the plate | `On porcelain_mug_1 plate_1`, `On chocolate_pudding_1 living_room_table_plate_right_region` | the pudding starts 0.30 m from the robot's base, right under the arm: the hand cannot get above it pointing down or tilted away from the base (its moves stop 0.1 to 0.2 m short) |
| `libero_10_swap:8` | put both moka pots on the stove | `On moka_pot_1 flat_stove_1_cook_region`, `On moka_pot_2 flat_stove_1_cook_region`, `Turnon flat_stove_1` | the stove's cook region is 0.84 m from the robot's base: after the first pot is put down there the arm is stretched to its elbow limit, and robosuite's controller does not bring it back for the second |
| `libero_10_swap:9` | put the yellow and white mug in the microwave and close it | `In white_yellow_mug_1 microwave_1_heating_region`, `Close microwave_1` | the microwave opens sideways under its top, so a mug held from above cannot go in (the hand hits the top); LIBERO's operators held the mug by its handle with a tilted hand, which the solution does not do |
| `libero_10_task:9` | put the white mug in the microwave and close it | `In porcelain_mug_1 microwave_1_heating_region`, `Close microwave_1` | as `libero_10_swap:9` |

## Checks

Run on a Linux x86_64 machine with 32 cores (Ubuntu 24.04; MuJoCo 3.3.0 rendering with OSMesa; hf-libero 0.1.4, robosuite 1.4.0) on 2026-10-20, with this suite's code:

- `robouse tasks check tasks/libero-pro/<id>` on each of the 73 tasks (the episode server with both cameras, the reference solution through the `robo` socket, then the no-op): all 73 valid. The reference solution scores 1 (`success_reached`) in 66 to 366 steps (median 138), and the no-op scores 0.
- The generator's in-process run of the reference solution (`generate.py --only <pair>`, one pair per process) reaches the goal on the 73 tasks here, in the same number of steps as through the episode server, and not on the seven left out.
- Another seed: `robouse run --task libero-pro-object-swap-0 --harness oracle --seed 2` downloaded the task's init file (4 kB, SHA-256 as in `task.md`) and started from saved state 1 (`"placement": {"init_mode": "saved", "init_state": 1}` in result.json). The reference solution scored 1 there too, in 122 steps.
- `robo info`'s projection matrices, against a segmentation render of the same camera at 256x256 in a kitchen scene (`libero-pro-goal-swap-8`) and a living-room scene (`libero-pro-10-task-4`). In `agentview`, the centre of each object's bounding box projects within 7 px of the centroid of the object's pixels for the objects wholly in view (median 4.5 px). The centroid of the visible pixels is not the box centre, so this overstates the error. In the wrist camera, which is closer to the objects, the figure is 17 px.

## Tasks

The goal is the BDDL file's `(:goal ...)`; the last column is the number of steps the reference solution takes from the task's own start (seed 1).

| Task id | ASPIRE pair | Instruction | Goal | Reference solution |
|---|---|---|---|---|
| `libero-pro-goal-swap-0` | `libero_goal_swap:0` | Open the middle layer of the drawer | `Open wooden_cabinet_1_middle_region` | 225 steps |
| `libero-pro-goal-swap-1` | `libero_goal_swap:1` | Put the bowl on the stove | `On akita_black_bowl_1 flat_stove_1_cook_region` | 167 steps |
| `libero-pro-goal-swap-2` | `libero_goal_swap:2` | Put the wine bottle on the top of the drawer | `On wine_bottle_1 wooden_cabinet_1_top_side` | 131 steps |
| `libero-pro-goal-swap-3` | `libero_goal_swap:3` | Open the top layer of the drawer and put the bowl inside | `In akita_black_bowl_1 wooden_cabinet_1_top_region` | 233 steps |
| `libero-pro-goal-swap-4` | `libero_goal_swap:4` | Put the bowl on the top of the drawer | `On akita_black_bowl_1 wooden_cabinet_1_top_side` | 145 steps |
| `libero-pro-goal-swap-5` | `libero_goal_swap:5` | Push the plate to the front of the stove | `On plate_1 main_table_stove_front_region` | 198 steps |
| `libero-pro-goal-swap-6` | `libero_goal_swap:6` | Put the cream cheese on the bowl | `On cream_cheese_1 akita_black_bowl_1` | 149 steps |
| `libero-pro-goal-swap-7` | `libero_goal_swap:7` | Turn on the stove | `Turnon flat_stove_1` | 66 steps |
| `libero-pro-goal-swap-8` | `libero_goal_swap:8` | Put the bowl on the plate | `On akita_black_bowl_1 plate_1` | 181 steps |
| `libero-pro-goal-swap-9` | `libero_goal_swap:9` | Put the wine bottle on the rack | `On wine_bottle_1 wine_rack_1_top_region` | 151 steps |
| `libero-pro-goal-task-1` | `libero_goal_task:1` | Put the plate on the stove | `On plate_1 flat_stove_1_cook_region` | 125 steps |
| `libero-pro-goal-task-2` | `libero_goal_task:2` | put the wine bottle in the bowl | `On wine_bottle_1 akita_black_bowl_1` | 102 steps |
| `libero-pro-goal-task-3` | `libero_goal_task:3` | Open the top layer of the drawer and put the cream cheese inside | `In cream_cheese_1 wooden_cabinet_1_top_region` | 240 steps |
| `libero-pro-goal-task-4` | `libero_goal_task:4` | Put the plate on the top of the drawer | `On plate_1 wooden_cabinet_1_top_side` | 127 steps |
| `libero-pro-goal-task-5` | `libero_goal_task:5` | Push the cream cheese to the front of the stove | `On cream_cheese_1 main_table_stove_front_region` | 85 steps |
| `libero-pro-goal-task-6` | `libero_goal_task:6` | put the wine bottle in the bowl | `On wine_bottle_1 akita_black_bowl_1` | 102 steps |
| `libero-pro-goal-task-7` | `libero_goal_task:7` | Turn off the stove | `Turnoff flat_stove_1` | 67 steps |
| `libero-pro-goal-task-8` | `libero_goal_task:8` | Put the wine bottle on the plate | `On wine_bottle_1 plate_1` | 121 steps |
| `libero-pro-goal-task-9` | `libero_goal_task:9` | Put the cream cheese on the rack | `On cream_cheese_1 wine_rack_1_top_region` | 148 steps |
| `libero-pro-object-swap-0` | `libero_object_swap:0` | Pick the alphabet soup and place it in the basket | `In alphabet_soup_1 basket_1_contain_region` | 123 steps |
| `libero-pro-object-swap-1` | `libero_object_swap:1` | Pick the cream cheese and place it in the basket | `In cream_cheese_1 basket_1_contain_region` | 128 steps |
| `libero-pro-object-swap-2` | `libero_object_swap:2` | Pick the salad dressing and place it in the basket | `In salad_dressing_1 basket_1_contain_region` | 117 steps |
| `libero-pro-object-swap-3` | `libero_object_swap:3` | Pick the bbq sauce and place it in the basket | `In bbq_sauce_1 basket_1_contain_region` | 133 steps |
| `libero-pro-object-swap-4` | `libero_object_swap:4` | Pick the ketchup and place it in the basket | `In ketchup_1 basket_1_contain_region` | 131 steps |
| `libero-pro-object-swap-5` | `libero_object_swap:5` | Pick the tomato sauce and place it in the basket | `In tomato_sauce_1 basket_1_contain_region` | 137 steps |
| `libero-pro-object-swap-6` | `libero_object_swap:6` | Pick the butter and place it in the basket | `In butter_1 basket_1_contain_region` | 114 steps |
| `libero-pro-object-swap-7` | `libero_object_swap:7` | Pick the milk and place it in the basket | `In milk_1 basket_1_contain_region` | 124 steps |
| `libero-pro-object-swap-8` | `libero_object_swap:8` | Pick the chocolate pudding and place it in the basket | `In chocolate_pudding_1 basket_1_contain_region` | 138 steps |
| `libero-pro-object-swap-9` | `libero_object_swap:9` | Pick the orange juice and place it in the basket | `In orange_juice_1 basket_1_contain_region` | 101 steps |
| `libero-pro-object-task-0` | `libero_object_task:0` | Pick the cream cheese and place it in the basket | `In cream_cheese_1 basket_1_contain_region` | 92 steps |
| `libero-pro-object-task-1` | `libero_object_task:1` | Pick the alphabet soup and place it in the basket | `In alphabet_soup_1 basket_1_contain_region` | 142 steps |
| `libero-pro-object-task-2` | `libero_object_task:2` | Pick the tomato sauce and place it in the basket | `In tomato_sauce_1 basket_1_contain_region` | 123 steps |
| `libero-pro-object-task-3` | `libero_object_task:3` | Pick the ketchup and place it in the basket | `In ketchup_1 basket_1_contain_region` | 100 steps |
| `libero-pro-object-task-4` | `libero_object_task:4` | Pick the milk and place it in the basket | `In milk_1 basket_1_contain_region` | 112 steps |
| `libero-pro-object-task-5` | `libero_object_task:5` | Pick the bbq sauce and place it in the basket | `In bbq_sauce_1 basket_1_contain_region` | 116 steps |
| `libero-pro-object-task-6` | `libero_object_task:6` | Pick the orange juice and place it in the basket | `In orange_juice_1 basket_1_contain_region` | 100 steps |
| `libero-pro-object-task-7` | `libero_object_task:7` | Pick the butter and place it in the basket | `In butter_1 basket_1_contain_region` | 133 steps |
| `libero-pro-object-task-8` | `libero_object_task:8` | Pick the salad dressing and place it in the basket | `In salad_dressing_1 basket_1_contain_region` | 130 steps |
| `libero-pro-object-task-9` | `libero_object_task:9` | Pick the chocolate pudding and place it in the basket | `In chocolate_pudding_1 basket_1_contain_region` | 95 steps |
| `libero-pro-spatial-swap-0` | `libero_spatial_swap:0` | Pick the akita black bowl between the plate and the ramekin and place it on the plate | `On akita_black_bowl_1 plate_1` | 107 steps |
| `libero-pro-spatial-swap-1` | `libero_spatial_swap:1` | Pick the akita black bowl next to the ramekin and place it on the plate | `On akita_black_bowl_1 plate_1` | 139 steps |
| `libero-pro-spatial-swap-2` | `libero_spatial_swap:2` | Pick the akita black bowl from table center and place it on the plate | `On akita_black_bowl_1 plate_1` | 106 steps |
| `libero-pro-spatial-swap-3` | `libero_spatial_swap:3` | Pick the akita black bowl on the cookies box and place it on the plate | `On akita_black_bowl_1 plate_1` | 182 steps |
| `libero-pro-spatial-swap-4` | `libero_spatial_swap:4` | Pick the akita black bowl in the top layer of the wooden cabinet and place it on the plate | `On akita_black_bowl_1 plate_1` | 169 steps |
| `libero-pro-spatial-swap-5` | `libero_spatial_swap:5` | Pick the akita black bowl on the ramekin and place it on the plate | `On akita_black_bowl_1 plate_1` | 130 steps |
| `libero-pro-spatial-swap-6` | `libero_spatial_swap:6` | Pick the akita black bowl next to the cookies box and place it on the plate | `On akita_black_bowl_1 plate_1` | 204 steps |
| `libero-pro-spatial-swap-7` | `libero_spatial_swap:7` | Pick the akita black bowl on the stove and place it on the plate | `On akita_black_bowl_1 plate_1` | 135 steps |
| `libero-pro-spatial-swap-8` | `libero_spatial_swap:8` | Pick the akita black bowl next to the plate and place it on the plate | `On akita_black_bowl_1 plate_1` | 122 steps |
| `libero-pro-spatial-swap-9` | `libero_spatial_swap:9` | Pick the akita black bowl on the wooden cabinet and place it on the plate | `On akita_black_bowl_1 plate_1` | 214 steps |
| `libero-pro-spatial-task-0` | `libero_spatial_task:0` | Pick the akita black bowl not between the plate and the ramekin and place it on the plate | `On akita_black_bowl_2 plate_1` | 124 steps |
| `libero-pro-spatial-task-1` | `libero_spatial_task:1` | Pick the akita black bowl next to the cookie box and place it on the plate | `On akita_black_bowl_2 plate_1` | 173 steps |
| `libero-pro-spatial-task-2` | `libero_spatial_task:2` | Pick the akita black bowl next to the plate and place it on the plate | `On akita_black_bowl_2 plate_1` | 106 steps |
| `libero-pro-spatial-task-3` | `libero_spatial_task:3` | Pick the akita black bowl on the top of the cabinet and place it on the plate | `On akita_black_bowl_2 plate_1` | 218 steps |
| `libero-pro-spatial-task-4` | `libero_spatial_task:4` | Pick the akita black bowl on the top of the wooden cabinet and place it on the plate | `On akita_black_bowl_2 plate_1` | 205 steps |
| `libero-pro-spatial-task-5` | `libero_spatial_task:5` | Pick the akita black bowl on the cookie box and place it on the plate | `On akita_black_bowl_2 plate_1` | 109 steps |
| `libero-pro-spatial-task-6` | `libero_spatial_task:6` | Pick the akita black bowl on the stove and place it on the plate | `On akita_black_bowl_2 plate_1` | 147 steps |
| `libero-pro-spatial-task-7` | `libero_spatial_task:7` | Pick the akita black bowl on the top of the cabinet and place it on the plate | `On akita_black_bowl_2 plate_1` | 206 steps |
| `libero-pro-spatial-task-8` | `libero_spatial_task:8` | Pick the akita black bowl next to the ramekin and place it on the plate | `On akita_black_bowl_2 plate_1` | 119 steps |
| `libero-pro-spatial-task-9` | `libero_spatial_task:9` | Pick the akita black bowl on the stove and place it on the plate | `On akita_black_bowl_2 plate_1` | 145 steps |
| `libero-pro-10-swap-0` | `libero_10_swap:0` | put both the alphabet soup and the tomato sauce in the basket | `In alphabet_soup_1 basket_1_contain_region`, `In tomato_sauce_1 basket_1_contain_region` | 366 steps |
| `libero-pro-10-swap-1` | `libero_10_swap:1` | put both the cream cheese box and the butter in the basket | `In cream_cheese_1 basket_1_contain_region`, `In butter_1 basket_1_contain_region` | 256 steps |
| `libero-pro-10-swap-2` | `libero_10_swap:2` | turn on the stove and put the moka pot on it | `Turnon flat_stove_1`, `On moka_pot_1 flat_stove_1_cook_region` | 262 steps |
| `libero-pro-10-swap-4` | `libero_10_swap:4` | put the white mug on the left plate and put the yellow and white mug on the right plate | `On porcelain_mug_1 plate_1`, `On white_yellow_mug_1 plate_2` | 331 steps |
| `libero-pro-10-swap-5` | `libero_10_swap:5` | pick up the book and place it in the back compartment of the caddy | `In black_book_1 desk_caddy_1_back_contain_region` | 171 steps |
| `libero-pro-10-swap-7` | `libero_10_swap:7` | put both the alphabet soup and the cream cheese box in the basket | `In alphabet_soup_1 basket_1_contain_region`, `In cream_cheese_1 basket_1_contain_region` | 333 steps |
| `libero-pro-10-task-0` | `libero_10_task:0` | put both the cream cheese and the tomato sauce in the basket | `In cream_cheese_1 basket_1_contain_region`, `In tomato_sauce_1 basket_1_contain_region` | 294 steps |
| `libero-pro-10-task-1` | `libero_10_task:1` | put both the alphabet soup and the butter in the basket | `In alphabet_soup_1 basket_1_contain_region`, `In butter_1 basket_1_contain_region` | 277 steps |
| `libero-pro-10-task-2` | `libero_10_task:2` | turn on the stove and put the pan on it | `Turnon flat_stove_1`, `On chefmate_8_frypan_1 flat_stove_1_cook_region` | 269 steps |
| `libero-pro-10-task-4` | `libero_10_task:4` | put the yellow and white mug on the left plate and put the white mug on the right plate | `On white_yellow_mug_1 plate_1`, `On porcelain_mug_1 plate_2` | 326 steps |
| `libero-pro-10-task-5` | `libero_10_task:5` | pick up the cup and place it in the back compartment of the caddy | `In white_yellow_mug_1 desk_caddy_1_back_contain_region` | 143 steps |
| `libero-pro-10-task-6` | `libero_10_task:6` | put the red mug on the plate and put the chocolate pudding to the right of the plate | `On red_coffee_mug_1 plate_1`, `On chocolate_pudding_1 living_room_table_plate_right_region` | 306 steps |
| `libero-pro-10-task-7` | `libero_10_task:7` | put both the ketchup and the cream cheese box in the basket | `In ketchup_1 basket_1_contain_region`, `In cream_cheese_1 basket_1_contain_region` | 340 steps |
| `libero-pro-10-task-8` | `libero_10_task:8` | put the left moka pot on the stove | `On moka_pot_1 flat_stove_1_cook_region`, `Turnon flat_stove_1` | 156 steps |

## Quirks of LIBERO-PRO's tasks

- `libero-pro-goal-task-7` ("Turn off the stove"): the stove starts with its knob at 0, which LIBERO's `TurnOff` check does not count as off (it wants the knob below 0), so the knob has to be turned a little clockwise, against its stop.
- `libero-pro-goal-task-2` and `libero-pro-goal-task-6` have the same goal and instruction ("put the wine bottle in the bowl", `On wine_bottle_1 akita_black_bowl_1`) in the same scene, from different LIBERO-PRO files and init files.
- `libero-pro-10-task-8` says "put the left moka pot on the stove"; its goal also has `Turnon flat_stove_1`, and the stove starts on.
- The `task` suites' instructions are LIBERO-PRO's own and sometimes describe the object loosely ("the akita black bowl on the stove", "the bottle"); the goal predicates decide.
