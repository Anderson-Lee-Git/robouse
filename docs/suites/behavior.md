# BEHAVIOR suite

43 tasks built from 30 activities of the 2026 [BEHAVIOR Challenge](https://behavior.stanford.edu/) (BEHAVIOR-1K, Stanford Vision and Learning Lab). Each runs in the challenge's scene, with the challenge's rooms and task instance, on the Galaxea R1Pro wheeled two-arm robot, in OmniGibson 3.9.3 on NVIDIA Isaac Sim 5.1. The agent is the robot's high-level policy: it calls symbolic skills (navigate, grasp, place, open, close, toggle) through `robo skill`. Success is BEHAVIOR's own BDDL goal check.

- Backend: `src/robouse/backends/behavior.py`, a thin HTTP client on the Robo Use host. It also declares the robot as a BenchFlow embodiment spec (`r1pro_embodiment`: kind `skill_only`, one `base.wait` action group, 9 backend skills, cameras `follow` and `head`).
- Simulator worker: `src/robouse/backends/behavior_worker.py`, one process per task instance on a GPU machine, inside the BEHAVIOR-1K conda environment.
- Generator: `python adapters/behavior/generate.py --out tasks/behavior --bddl <BEHAVIOR-1K>/bddl3/bddl/activity_definitions`. Reference plans and instructions are in `adapters/behavior/plans.py`; the challenge's scene, rooms and instruction for all 100 activities are in `adapters/behavior/challenge_tasks.json`. `--bddl` adds each task's formal goal to its instruction.

## Tasks

Variants of one activity:

- `behavior-<activity>`: challenge task instance 0, full state in `robo observe`.
- `behavior-<activity>-instance-<k>`: challenge training instance k (other object placements and robot start pose), full state.
- `behavior-<activity>-vision`: instance 0, vision only (see below).

| Task id | Challenge # | Scene | Oracle skills | Budget | Also as |
|---|---|---|---|---|---|
| behavior-turning-on-radio | 0 | house_double_floor_lower | 2 | 20 | - |
| behavior-picking-up-trash | 1 | house_double_floor_lower | 12 | 40 | instance 1, vision |
| behavior-cleaning-up-plates-and-food | 3 | house_double_floor_lower | 20 | 55 | - |
| behavior-picking-up-toys | 7 | house_single_floor | 24 | 65 | - |
| behavior-rearranging-kitchen-furniture | 8 | house_double_floor_lower | 15 | 45 | vision |
| behavior-putting-dishes-away-after-cleaning | 11 | house_single_floor | 35 | 85 | vision |
| behavior-loading-the-car | 13 | house_double_floor_lower | 15 | 45 | - |
| behavior-carrying-in-groceries | 14 | house_double_floor_lower | 14 | 45 | - |
| behavior-bringing-in-wood | 15 | house_double_floor_lower | 12 | 40 | - |
| behavior-moving-boxes-to-storage | 16 | house_double_floor_lower | 8 | 35 | - |
| behavior-bringing-water | 17 | house_single_floor | 12 | 40 | instance 1, instance 2, vision |
| behavior-collecting-childrens-toys | 21 | house_single_floor | 28 | 75 | - |
| behavior-storing-food | 24 | house_single_floor | 34 | 85 | - |
| behavior-freeze-fruit | 50 | house_single_floor | 38 | 95 | vision |
| behavior-tidying-living-room | 53 | house_double_floor_upper | 16 | 50 | - |
| behavior-putting-away-toys | 54 | house_single_floor | 32 | 80 | - |
| behavior-re-shelving-library-books | 55 | house_double_floor_upper | 12 | 40 | - |
| behavior-organizing-art-supplies | 59 | house_double_floor_upper | 20 | 55 | - |
| behavior-turning-out-all-lights-before-sleep | 66 | house_single_floor | 10 | 35 | instance 1, vision |
| behavior-carrying-out-garden-furniture | 74 | house_single_floor | 8 | 35 | - |
| behavior-dispose-of-glass | 76 | hotel_suite_large | 16 | 50 | - |
| behavior-clean-up-broken-glass | 80 | restaurant_diner | 12 | 40 | - |
| behavior-store-honey | 83 | Rs_int | 6 | 30 | - |
| behavior-tidying-bathroom | 84 | hotel_suite_large | 16 | 50 | vision |
| behavior-putting-dirty-dishes-in-sink | 85 | restaurant_diner | 16 | 50 | - |
| behavior-collecting-aluminum-cans | 87 | hotel_suite_large | 24 | 65 | - |
| behavior-rearrange-your-room | 88 | hotel_suite_large | 12 | 40 | - |
| behavior-installing-a-fax-machine | 89 | office_cubicles_right | 5 | 25 | - |
| behavior-store-produce | 91 | restaurant_diner | 18 | 55 | instance 1, vision |
| behavior-sorting-books-on-shelf | 99 | house_double_floor_upper | 9 | 35 | - |

That is 30 instance-0 tasks, 5 extra instances (`picking_up_trash` 1, `bringing_water` 1 and 2, `store_produce` 1, `turning_out_all_lights_before_sleep` 1) and 8 vision-only variants.

The "Challenge #" is the activity's index in the challenge's task list. Instructions state what the BDDL goal checks. For activities 50-99 the challenge's own instruction often differs from its goal (for example `tidying_living_room` asks for "books and papers into the bookcase", but the goal puts the newspaper on the coffee table and the notebook on the desk); there the instruction follows the goal, and the challenge's text is kept in `metadata.challenge_instruction`. Budgets are twice the reference plan plus 15 skills, rounded up to a multiple of 5 (at least 20).

### Which activities, and why the others were left out

Of the 100 challenge activities, 50 have goals built only from `inside`, `ontop`, `open` and `toggled_on`, the relations the skills can reach. The other 50 need cooking, freezing, slicing, cleaning (`covered`), attaching, `nextto`, `under` or `touching`, which the symbolic skills cannot produce. Every one of the 50 got a reference plan; 20 were dropped because the plan could not be made to pass BEHAVIOR's goal check:

| Challenge # | Activity | Why it was dropped |
|---|---|---|
| 4 | can_meat | the two hinged jars do not fit back inside the cabinet (Inside sampler), and the bratwursts on the chopping board are out of reach from every free spot next to the counter |
| 12 | preparing_lunch_box | the bottle of tea does not fit inside the packing box (Inside sampler, 4 draws), in either order of packing |
| 19 | outfit_a_basic_toolbox | the toolbox lid falls shut again after `open` (place_inside then reports it closed), and the drill finds no spot inside the toolbox |
| 20 | sorting_vegetables | the mixing bowls cannot hold the vegetables: with two bok choy in a bowl, placing the third found no spot and the sampler ran past the robo client's 120 s timeout |
| 23 | boxing_books_up_for_storage | the six books do not reliably fit into the box: in 3 of 4 reference runs one book found no spot inside it |
| 25 | clearing_food_from_table_into_fridge | place_inside finds no spot for the half chicken inside either tupperware container (BEHAVIOR's Inside sampler, 4 draws), so the goal cannot be reached |
| 26 | assembling_gift_baskets | every skill succeeds, but the placed items do not stay inside the small wicker baskets on the floor: after settling none of the 16 items counts as inside |
| 29 | clean_up_your_desk | the child's room is too cramped for the base: navigate_to finds no free spot (0.38 m clearance) within reach of the desk, the bookcase or the items on them |
| 52 | sorting_bottles_cans_and_paper | the newspaper and the magazine do not fit inside a bucket (Inside sampler) |
| 56 | make_rose_centerpieces | the roses do not fit inside the vase: the second rose found no spot (Inside sampler) |
| 61 | bringing_paper_to_recycling | the newspaper finds no spot inside the recycling bin (Inside sampler) |
| 67 | boxing_food_after_dinner | the second plate finds no spot on the kitchen sink (OnTop sampler) |
| 68 | cleaning_up_branches_and_twigs | the branches find no spot inside the recycling bin (Inside sampler; 4 of 4 branches failed with the bin open) |
| 73 | organizing_school_stuff | the folder finds no spot inside the tote bag (Inside sampler) |
| 75 | put_together_a_basic_pruning_kit | the shears find no spot inside the toolbox (Inside sampler) |
| 81 | packing_meal_for_delivery | the three paper sacks do not fit on top of the storage container: the second found no spot (OnTop sampler) |
| 82 | store_batteries | the battery on the kitchen countertop is out of reach: navigate_to finds no free spot next to it |
| 86 | make_gift_bags_for_baby_showers | the wafers find no spot inside the paper sacks (Inside sampler) |
| 90 | composting_waste | the half banana finds no spot inside the kitchen trash can (Inside sampler; 2 of 2 runs) |
| 94 | dispose_of_batteries | every skill succeeds, but after settling the goal (batteries inside the trash can, the can on the copy-room floor) does not hold |

Most drops are BEHAVIOR's placement sampler (`object_states.Inside` / `OnTop` `set_value`) finding no collision-free pose for a large or flat object in a small container. A continuous placement controller could solve some of them; this suite does not have one.

## Action and observation interface

```
robo skill navigate_to OBJ     # drive the base to a free spot next to OBJ, facing it (a held object comes along)
robo skill grasp OBJ           # pick up OBJ; task objects resting in or on it come along
robo skill place_on_top OBJ    # put the held object on top of OBJ
robo skill place_inside OBJ    # put the held object inside OBJ
robo skill open OBJ / close OBJ / toggle_on OBJ / toggle_off OBJ
robo skill release             # drop the held object
robo act 0 [--repeat N]        # no low-level control: holds the robot still for N simulator steps
robo observe [--image [--camera head]]
```

OBJ is a BDDL instance name from the task's object scope, for example `can__of__soda.n.01_2`. Wildcard scope entries (`cabinet.n.01_*`) expand to every matching object in the loaded rooms.

How the skills work:

- `open`, `close`, `toggle_on`, `toggle_off`: OmniGibson's `SymbolicSemanticActionPrimitives`, which set the post-condition directly; the arm does not move.
- `navigate_to`: teleports the base to the closest free spot next to the object's bounding box (traversability map, 0.38 m clearance, same room as the object; stand-offs 0.35-1.1 m). For a floor or lawn it picks the nearest free spot on it.
- `grasp`: a kinematic carry. The object loses gravity and rides 0.45 m in front of the base at 1.1 m height. Task objects inside or on top of it ride along at their relative pose (a pizza on its plate, a camera in a container).
- `place_on_top` / `place_inside`: BEHAVIOR's kinematic samplers put the object in the relation, carried contents are put back at their relative pose, physics settles, and the relation is checked again. Up to 4 sampler draws within 60 s. On a floor, the object is first set down just in front of the robot; on top of a movable object, it is first centred on it.

Constraints the worker adds, so the agent still has to plan: manipulation needs the base within 1.25 m (horizontally) of the target; the hand holds one object; grasp fails on fixed objects, objects longer than 2.5 m, or objects inside a closed container; open, close and toggle need an empty hand; `place_inside` fails on a closed container. A failed skill returns `ok: False` with the reason and costs one step, like any skill.

`robo observe` (state tasks) returns the robot (`xy`, `yaw_deg`, room, `holding`), `object_names`, and per task object its category, room, position, `distance_m`, `in_reach`, `open` / `toggled_on`, and `inside` / `on_top_of` relations. BDDL goal satisfaction is never shown. Cameras: `follow` (2.6 m behind and 2.0 m above the robot, also the video camera) and `head` (the robot's head camera), both 640x480.

Vision tasks set `obs_mode: vision` with `visible_fields: [robot, object_names]`: `robo observe` gives only the robot's own state and the object names (what skills take), plus one picture per camera. Where things are, whether they are open or on, and what rests on what must be read from the images; skill failures still say why. The reference solution sees the full state (oracle token), but its plan does not use it.

Scoring: `success_mode: final`. After `robo done` the server holds still for 10 steps, then the worker evaluates the task's compiled BDDL goal (`PredicateGoal`). Give-up, budget exhaustion and agent exit score 0.

## Source and licences

- BEHAVIOR-1K code, including OmniGibson and BDDL: MIT (copyright 2023 Stanford Vision and Learning Group). The task instructions in `adapters/behavior/challenge_tasks.json` and `tasks/behavior/` come from BEHAVIOR-1K's `docs/challenge/task_data.json` and the goals from its BDDL activity definitions; NOTICE credits them.
- The BEHAVIOR Data Bundle (scenes, objects and their textures, which the worker downloads on the GPU machine) is for non-commercial academic research only, and may not be redistributed in whole or in part. Robo Use redistributes none of it: the task folders hold instructions, scene and activity names and instance numbers, and they are not in the package or the source distribution.
- NVIDIA Isaac Sim, which OmniGibson runs on: NVIDIA's EULA.
- So this suite cannot be run for commercial purposes. Screenshots and videos of its scenes show Data Bundle artwork, which the no-redistribution term covers; ask Stanford SVL before publishing any.

## Setup

1. GPU machine. Isaac Sim needs an NVIDIA RTX GPU with RT cores and, as of this writing, host driver 580. We used Daytona sandboxes through the `daytona` Python SDK: image `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`, `Resources(cpu=16, memory=128, disk=250, gpu=1, gpu_type=[RTX_5090])`, `ephemeral=True`, `auto_stop_interval=20`, `ttl_minutes=170`. Daytona's RTX PRO 6000 hosts now run driver 595, where Isaac Sim 5.1 crashes at start-up (a segfault in `librtx.scenedb.plugin.so`, also with a bare `SimulationApp`); the RTX 5090 hosts ran driver 580 and worked. H100s have no RT cores.
2. Install, about 10 minutes, with the dataset download in parallel:

   ```
   git clone --depth 1 -b v3.9.3-post1 https://github.com/StanfordVL/BEHAVIOR-1K.git && cd BEHAVIOR-1K
   ./setup.sh --new-env --omnigibson --bddl --accept-conda-tos --accept-nvidia-eula --accept-dataset-tos
   conda activate behavior && pip install warp-lang==1.12.0
   # from HF behavior-1k/zipped-datasets, unzipped into BEHAVIOR-1K/datasets/<name>:
   #   behavior-1k-assets-3.9.0.zip, omnigibson-robot-assets-3.8.2.zip, 2026-challenge-task-instances.zip
   python -c "from omnigibson.utils.asset_utils import download_key; download_key()"
   ```

   The `v3.9.3` tag used for the first version of this suite no longer exists upstream; `v3.9.3-post1` is OmniGibson 3.9.3.
3. Workers. One per task instance, each on its own port, with a shared secret:

   ```
   OMNI_KIT_ACCEPT_EULA=YES OMNIGIBSON_HEADLESS=1 ROBOUSE_BEHAVIOR_SECRET=<secret> \
     python behavior_worker.py --activity picking_up_trash --scene house_double_floor_lower --instance 0 --port 8800 \
       --rooms corridor_0,garden_0,kitchen_0,living_room_0
   ```

   Scene, rooms and instance are in each task's `robouse:` block. For an instance k > 0 the worker loads the cached instance-0 scene and applies the challenge's `*_0_k_template-tro_state.json` (object states and robot start pose) as the challenge evaluator does, then makes that the state `reset` restores. A load takes 2.5-8 minutes and about 7 GB of VRAM; three workers at a time fit on a 32 GB RTX 5090 (four ran out of GPU memory during a load). `reset` takes about 5-20 s.
4. Endpoints. Write `~/.config/robouse/remote/behavior.json` (or point `$ROBOUSE_BEHAVIOR_REMOTE` at a file in another folder the sandbox denies):

   ```json
   {"secret": "<secret>", "workers": {"picking_up_trash": {"url": "https://8800-<sandbox>.<proxy>", "headers": {"x-daytona-preview-token": "<token>"}},
                                      "picking_up_trash@1": {"url": "...", "headers": {}}}}
   ```

   The key is the activity for instance 0 and `<activity>@<k>` otherwise. We used Daytona preview URLs (`sandbox.get_preview_link(port)`). The sandbox denies `~/.config/robouse` to model harnesses (a file in the checkout would be readable), and the worker rejects requests without the secret. Delete the file after the runs.
5. Run from the checkout, at most one trial per worker at a time:

   ```
   robouse run-many --tasks tasks/behavior --task-list <ids> --harness oracle --out runs/behavior-oracle
   ```

This is the only run path we tested. `bench eval run -d stanfordvl/behavior-1k` is not: BenchFlow's sandboxes cannot attach a GPU (its Daytona provider passes no GPU resources, and tasks that request one are rejected), so the simulator cannot run inside a bench sandbox, and the exported packages would need the worker endpoints file from the host.

A development-only `debug_exec` method (enabled with `ROBOUSE_BEHAVIOR_DEBUG=1`) runs Python in the worker process, behind the shared secret. We used it to patch skills into loaded workers without reloading scenes. Disable it for anything shared.

## Results

All runs on 2026-09-29, one trial per task, workers on Daytona RTX 5090s. Job folders are under `runs/` (not committed).

| Job | Harness / model | Solved |
|---|---|---|
| `runs/behavior-oracle` | reference plans | 43/43 |
| `runs/behavior-noop` | noop (immediate `robo done`) | 0/43 |
| `runs/behavior-kimi` | claude-code-glm / Kimi K3 (Baseten), probe | 8/8 (8 tasks probed) |

| Probed task | Kimi K3 skills | Reference skills | Wall time |
|---|---|---|---|
| behavior-picking-up-trash | 12 | 12 | 84 s |
| behavior-picking-up-trash-vision | 12 | 12 | 139 s |
| behavior-freeze-fruit | 39 | 38 | 216 s |
| behavior-freeze-fruit-vision | 38 | 38 | 476 s |
| behavior-store-produce | 17 | 18 | 69 s |
| behavior-store-produce-vision | 20 | 18 | 272 s |
| behavior-tidying-bathroom-vision | 16 | 16 | 137 s |
| behavior-turning-out-all-lights-before-sleep-vision | 10 | 10 | 104 s |

- The oracle row counts each task's final trial. The worker was fixed during the day (placement on floors, stacking on movable objects, the room of a moved object, placement retries after a failed draw); workers loaded before a fix ran the earlier revision. `moving_boxes_to_storage`, `tidying_living_room`, `bringing_in_wood` and `cleaning_up_plates_and_food` were rerun on the final revision; superseded trials are kept in `runs/behavior-*/_superseded/`. `cleaning_up_plates_and_food` failed 1 of 2 direct runs before placement retries existed (the first plate found no spot in the refrigerator).
- Kimi K3 solved every probe, including all vision-only ones, usually with the reference plan's skill count. The probed tasks are not hard for a strong model even without state: the object names say what to move, and a skill's failure message says why it failed. Vision-only mostly costs the model more observations and wall time.
- Not run: Codex and Claude harnesses (quota), Claude Opus (paused at the time).

## GPU time

4.7 GPU-hours on Daytona, 07:40-10:31 UTC:

- RTX PRO 6000 (07:40-08:00): bootstrapped, then Isaac Sim crashed at start-up on driver 595; deleted. A second RTX PRO 6000 (driver 595 too) and one RTX 5090 and one RTX 4090 probe were created and deleted within a minute each to read their drivers.
- Two RTX 5090 boxes (driver 580), 08:00-10:14 and 08:22-10:31: bootstrap (10 min each), then 3 workers each, loading the task instances in turn while `robouse run-many` ran the reference solution, the no-op and the Kimi probes on each loaded worker, and failing plans were debugged on the loaded worker. Each box was deleted when its queue was done; listing confirmed no `robouse=behavior` sandbox remained.

For a rerun, budget about 10 minutes of setup per box and 3-8 minutes per worker load; a trial takes 0.5-8 minutes.

## Limitations

- Symbolic, not physical: skills set post-conditions, navigation teleports, grasps are kinematic. The suite tests task planning, object bookkeeping and handling failures in a realistic house, not motion control. Numbers are not comparable to BEHAVIOR Challenge scores, which grade low-level policies.
- Placement is sampled. A reference plan passing once does not mean every placement succeeds every time; a skill that fails reports it, and the agent can retry.
- Each worker serves one trial at a time, and a trial fails as an infrastructure error if the worker or network drops.
- Low-level control (the R1Pro's joint and base actions) is not exposed.
