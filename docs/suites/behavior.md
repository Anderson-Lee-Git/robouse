# BEHAVIOR suite

5 long-horizon household activities from [BEHAVIOR-1K](https://behavior.stanford.edu/) (Stanford Vision and Learning Lab), taken from the 2026 BEHAVIOR Challenge task list. Each runs in its challenge house with the challenge's task instance 0 and the Galaxea R1Pro wheeled two-arm robot, in OmniGibson 3.9.3 on NVIDIA Isaac Sim 5.1. The agent is the robot's high-level policy: it drives BEHAVIOR's symbolic action primitives (navigate, grasp, place, open, close, toggle) through `robo skill`. Success is BEHAVIOR's own BDDL goal check.

- Backend: `src/robouse/backends/behavior.py`, a thin HTTP client that runs on the robouse host.
- Simulator worker: `src/robouse/backends/behavior_worker.py`, which runs on a GPU machine inside the BEHAVIOR-1K conda environment.
- Generator: `python adapters/behavior/generate.py --out tasks/behavior --bddl <BEHAVIOR-1K>/bddl3/bddl/activity_definitions`. The `--bddl` path is optional; with it, the formal goal is added to each instruction.

Isaac Sim needs an NVIDIA RTX GPU, one with RT cores (for example an RTX PRO 6000 Blackwell, L40S or RTX 5070). Data-center cards without RT cores, such as the H100, cannot render. The simulator therefore runs remotely. The episode server, step budget, trace, video, verifier and harnesses all run on the robouse host, as for every other suite. Only the backend's `reset` / `observe` / `skill` / `render` / `success` calls cross the network.

## Tasks

| Task id | BEHAVIOR activity | Scene | Instruction (the challenge's) | Oracle skills | Budget |
|---|---|---|---|---|---|
| behavior-turning-on-radio | turning_on_radio | house_double_floor_lower | Turn on the radio receiver that's on the table in the living room. | 2 | 20 |
| behavior-picking-up-trash | picking_up_trash | house_double_floor_lower | Put the three cans of soda from the living room inside the trash can in the kitchen. | 12 | 40 |
| behavior-rearranging-kitchen-furniture | rearranging_kitchen_furniture | house_double_floor_lower | Move the toaster, food processor, and French press from the kitchen countertop into the same kitchen cabinet, and make sure that cabinet is closed at the end. | 15 | 45 |
| behavior-bringing-water | bringing_water | house_single_floor | Retrieve the two bottles from the refrigerator in the kitchen, bring them to the living room, and place both on the coffee table. Make sure the refrigerator is closed at the end. | 11 | 40 |
| behavior-putting-dishes-away-after-cleaning | putting_dishes_away_after_cleaning | house_single_floor | In the kitchen, gather all eight plates from the two countertops, place them all inside a single cabinet (either one), and make sure all cabinets are closed when you are done. | 35 | 90 |

Why these five: the goals of all five only need predicates that the primitive set can reach (`toggled_on`, `inside`, `ontop`, `open`). They span 1 to 8 objects and one or two rooms, and the three multi-object tasks carry a closing condition ("the cabinet/refrigerator must be closed") that an agent can forget. Challenge tasks that need cooking, cutting, washing, spraying, wiping, `nextto` or `touching` goals were left out: those either need continuous control, or they need primitives that the symbolic set implements only by teleporting particles.

Loaded rooms: the challenge's room list for each scene (`B100_task_misc.csv`). house_double_floor_lower loads corridor_0, garden_0, kitchen_0 and living_room_0. house_single_floor loads corridor_0, dining_room_0, entryway_0, garden_0, kitchen_0, living_room_0 and living_room_1.

## Action and observation interface

```
robo skill navigate_to OBJ     # drive the base to a free spot next to OBJ, facing it (a held object comes along)
robo skill grasp OBJ           # pick up OBJ
robo skill place_on_top OBJ    # put the held object on top of OBJ
robo skill place_inside OBJ    # put the held object inside OBJ
robo skill open OBJ / close OBJ / toggle_on OBJ / toggle_off OBJ
robo skill release             # drop the held object
robo act 0 [--repeat N]        # no low-level control: holds the robot still for N simulator steps
robo observe [--image [--camera head]]
```

`robo skill NAME ARGS...` is a generic operation added to robouse for this suite (see "Changes to robouse core" below). OBJ is a BDDL instance name exactly as BEHAVIOR's task definition names it, for example `can__of__soda.n.01_2` or `cabinet.n.01_1`. Only the task's own objects (its BDDL object scope) can be named. For wildcard categories such as `cabinet.n.01_*`, the scope includes every cabinet in the loaded rooms.

How the skills work:

- `open`, `close`, `toggle_on` and `toggle_off` are OmniGibson's `SymbolicSemanticActionPrimitives`. They set the post-condition state directly (the joint is set to open, the toggle state to on), and physics then settles. The arm does not move.
- `navigate_to` is our own implementation, because OmniGibson's version needs cuRobo motion planning. It picks the closest free base position next to the object's bounding box, using the scene's traversability map with a 0.38 m clearance and the object's room. It then teleports the base there, facing the object.
- `grasp` is a kinematic carry. The object's gravity is switched off, and it rides 0.45 m in front of the base at 1.1 m height until it is placed or released. We first used OmniGibson's sticky grasp joint (the symbolic `GRASP`), but it kept dropping objects when the base teleported; in the reference solutions, 3 of 4 multi-object tasks failed that way.
- `place_on_top` / `place_inside` release the object, then put it in the relation with BEHAVIOR's own kinematic samplers (`object_states.OnTop` / `Inside` `set_value`). Physics then settles, and the relation is checked again. The symbolic primitive's sampler, which runs while the object is still attached to the hand, could not find a spot inside an open trash can.

The worker adds the constraints that the symbolic set leaves out, so the agent still has to plan the activity:

- Reach: grasp, place, open, close and toggle fail unless the robot base is within 1.25 m (horizontally) of the target's bounding box, so the agent must navigate first.
- Grasp fails if the hand is full, the object is fixed or larger than 1 m, or the object is inside a closed container from the scope.
- Open, close and toggle need an empty hand.
- `place_inside` fails on a closed openable container.
- A failed skill returns `ok: False` with the reason, and still costs one step.

One skill counts as one step of the task's budget. `robo act` steps count too.

What `robo observe` returns:

- robot: base `xy`, `yaw_deg`, the room it is in, and `holding`.
- For every scope object:
  - `category`, `room`, and its bounding-box `position`;
  - `distance_m` from the base, and `in_reach`;
  - `open` / `toggled_on` where the object has that state;
  - `relations`: `inside X` / `on_top_of X` against the other scope objects, for movable objects.

These are all things a robot looking at the scene could perceive. BDDL goal satisfaction itself is never shown.

Cameras:

- `follow` (the default and the video camera) is a third-person camera 2.6 m behind and 2.0 m above the robot.
- `head` is the robot's head camera.

Both are 640x480. Rendering happens only when an image is requested; see "Setup" below.

Scoring: `success_mode: final`. After `robo done`, the server holds the robot still for 10 steps. The worker then evaluates BEHAVIOR's `PredicateGoal` termination condition, which is the task's compiled BDDL goal, on the simulated state. `robo give-up`, the budget running out or the agent exiting all score 0.

## Setup

1. GPU machine. We used a Daytona sandbox created with the `daytona` Python SDK: image `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`, `Resources(cpu=16, memory=64, disk=200, gpu=1, gpu_type=[RTX_PRO_6000])`, `ephemeral=True`, `auto_stop_interval=30`, `ttl_minutes=170`. Daytona allocated an RTX PRO 6000 Blackwell Server Edition (96 GB, driver 580). The NVIDIA Vulkan ICD is already mounted, and Isaac Sim ran headless with no extra configuration.
2. Install, about 6 minutes in total. The dataset download runs in parallel with the environment install:

   ```
   git clone --depth 1 -b v3.9.3 https://github.com/StanfordVL/BEHAVIOR-1K.git && cd BEHAVIOR-1K
   ./setup.sh --new-env --omnigibson --bddl --accept-conda-tos --accept-nvidia-eula --accept-dataset-tos   # conda env "behavior": Python 3.11, torch 2.7 cu128, isaacsim 5.1 wheels
   conda activate behavior && pip install warp-lang==1.12.0    # OmniGibson imports warp, but only its [primitives] extra (with cuRobo) installs it
   # datasets from HF behavior-1k/zipped-datasets, unzipped into BEHAVIOR-1K/datasets/<name>:
   #   behavior-1k-assets-3.9.0.zip (31.5 GB), omnigibson-robot-assets-3.8.2.zip (0.6 GB), 2026-challenge-task-instances.zip (0.1 GB)
   python -c "from omnigibson.utils.asset_utils import download_key; download_key()"   # dataset decryption key (accepting the BEHAVIOR data license)
   ```

   We downloaded the zips with `hf_hub_download` (hf_xet) instead of `setup.sh --dataset`, so that the 31 GB download overlapped with the install. Disk use is about 37 GB of datasets plus about 25 GB for the conda environment.
3. Workers. Start one worker per activity, each on its own port, with a shared secret:

   ```
   OMNI_KIT_ACCEPT_EULA=YES OMNIGIBSON_HEADLESS=1 ROBOUSE_BEHAVIOR_SECRET=<secret> \
     python behavior_worker.py --activity picking_up_trash --scene house_double_floor_lower --port 8766 \
       --rooms corridor_0,garden_0,kitchen_0,living_room_0
   ```

   Each worker loads its scene once:
   - about 6.5 min alone;
   - 22-26 min when all five load at the same time, since loading is CPU-bound;
   - 11-15 GB of host RAM and about 11 GB of VRAM each (all five together: 55-76 GB VRAM).

   `reset` restores the task's initial state in about 17 s.
4. Endpoints. Write `runs/_behavior/remote.json` (or point `$ROBOUSE_BEHAVIOR_REMOTE` at another file):

   ```json
   {"secret": "<secret>", "headers": {"x-daytona-preview-token": "<token>"}, "workers": {"picking_up_trash": "https://8766-<sandbox>.<proxy>", "...": "..."}}
   ```

   We used Daytona preview URLs (`sandbox.get_preview_link(port)`). The file lives under `~/benchflow`, which the macOS sandbox profile denies to model harnesses, so agents cannot reach the worker directly. The worker also rejects requests that lack the secret.
5. Run as usual. The tasks set `ready_timeout_s: 900` because the first `reset` can queue behind another trial on the same GPU:

   ```
   robouse run-many --tasks tasks/behavior --harness codex --model gpt-6-astra --out runs/final-behavior-astra --concurrency 5
   ```

   Run at most one trial per activity at a time: each worker holds one simulator.

Performance notes. These fixes are in the worker:
- Disable Isaac Sim's render-on-step (`og.sim._render_on_step = False`) and render only when an image is requested. With five Isaac Sim instances rendering every physics step on one GPU, one skill took several minutes.
- Step the robot and simulator directly instead of through `env.step`, which also computes observations, rewards and a BDDL goal check on every step.
- Limit torch to 8 threads per worker (`ROBOUSE_BEHAVIOR_TORCH_THREADS`). With torch's default of one thread per core, five busy workers on 60 cores oversubscribed the CPUs so badly that single skills timed out.
- Shorten OmniGibson's settle loop (50 fixed steps plus up to `MAX_STEPS_FOR_SETTLING`) to 8-30 steps. One simulator step in a full house costs about 0.3 s, and the stock settle made a single grasp take close to a minute.

With these, a skill takes about 1-3 s, with five workers busy at once.

A development-only `debug_exec` method in the worker (enabled with `ROBOUSE_BEHAVIOR_DEBUG=1`, which is the default in our launch script) executes Python in the worker process. It is protected by the shared secret, and model harnesses never see the secret. Our runs had it enabled: we used it to apply the performance fixes above to the already-loaded workers without reloading the scenes. Disable it for a public deployment.

## Results

All runs were on 2026-09-27, one trial per task, with the five workers on one RTX PRO 6000. The job folders are under `runs/`, which is not committed.

| Job | Harness / model | Solved | Skill steps used (radio, trash, kitchen, water, dishes) |
|---|---|---|---|
| `runs/_v1-oracle-behavior` | reference plans | 5/5 | 2, 12, 15, 11, 35 |
| `runs/_v1-noop-behavior` | noop (immediate `robo done`) | 0/5 | 0 each |
| `runs/final-behavior-cc-glm` | claude-code-glm / GLM-5.3 | 5/5 | 2, 13, 12, 11, 22 |
| `runs/final-behavior-codex-glm` | codex-glm / GLM-5.3 | 5/5 | 2, 12, 15, 11, 26 |
| `runs/final-behavior-mini-glm` | mini-swe-agent-glm / GLM-5.3 | 5/5 (one rerun, below) | 2, 13, 15, 11, 35 |
| (not kept as a final job) | codex / gpt-6-astra | not run: every trial failed at startup with `401 Unauthorized` | - |

- Trials took 24-105 s of wall time each. With the performance fixes, a skill takes about 1-3 s once the worker is warm, and a `reset` about 13-18 s.
- All 15 model trials pass `scripts/audit.py` with no flags. The audit script now counts `skill` requests as robot motion.
- The suite is saturated for LLM agents with state observations. All three GLM-5.3 harnesses solved all five tasks, including the 8-plate task, well inside the budgets. Claude Code + GLM used 22 skills on the dishes task, 13 fewer than the reference plan: from one spot next to the cabinet, most plates were within the 1.25 m reach. The suite checks the plumbing (GPU simulator, remote worker, primitive interface, BDDL scoring), not model capability. Harder variants would need image-only observations (`obs_mode: vision`), the challenge's other task instances, a tighter reach, or no named relations in `robo observe`.
- codex + gpt-6-astra: the Codex credential on this machine failed. `~/.codex/auth.json` holds the placeholder API key `x` (`auth_mode: api`), and `OPENAI_API_KEY` is unset, so every request returned 401. The 5 infra-failed trials are kept in `runs/_behavior/failed/astra-codex-401/`. Claude Code + Claude Opus 5.5 was not run, on the owner's instruction.
- mini-swe-agent-glm, first `picking_up_trash` trial: the agent chained several `robo` calls in one shell command. The command hit mini-swe-agent's 30 s tool timeout, which killed the `robo` client while the server was replying. The episode server then crashed on the broken pipe (`conn.sendall` in `session.serve`), and the episode ended as `agent_exited`. That was a robouse bug, now fixed (see "Changes to robouse core"), so the trial was rerun (solved, 13 skills). The failed trial is kept in `runs/final-behavior-mini-glm/_infra_failed/`.
- Audit finding, same failed trial: after the crash, the agent read other trials' results and its own episode's `server.log`, `frames.jsonl` and `config.json` over HTTP from the local runs viewer on `localhost:8768` (`/api/jobs/.../files/...`). It also listed the installed robouse package under `/private/tmp/qs/.venv`, another agent's quickstart environment. The macOS sandbox profile blocks file access to `~/benchflow` but not localhost network access or other copies of the package. The agent did not change anything, and it scored 0 on that trial. The viewer should not be reachable from agent processes while trials run (or the sandbox profile should deny localhost ports other than the model proxies).

## GPU time and cost

Two Daytona RTX PRO 6000 sandboxes, about 4.9 GPU-hours in total:

- The first (08:51 UTC) got BEHAVIOR-1K up: install, datasets, the first scene load, and a navigate + toggle_on test that satisfied the BDDL goal of `turning_on_radio`. Our session was then interrupted for about 8 hours. The sandbox sat idle until Daytona's time limit (`ttl_minutes=180`) deleted it, at about 11:51 UTC. So about 3 of the 4.9 hours were this sandbox, mostly idle.
- The second (17:32:47-19:28:03 UTC, 1 h 55 min):
  - bootstrap, 6 min;
  - parallel loading of the five scenes, 26 min;
  - debugging the primitives (carry, placement, speed), about 45 min;
  - reference solution, no-op control and three GLM harness jobs, about 20 min.

  Deleted right after the runs; listing confirmed that no robouse sandbox remained.

The Daytona price for this GPU type was not checked. For a rerun, budget about 35 min of setup (install plus scene loads) and 1-2 min per trial.

## Limitations

- Symbolic, not physical. Grasps, placements, opening and toggling set the post-condition state directly, and navigation teleports the base. The suite tests long-horizon task planning, object bookkeeping, and handling of preconditions and failures in a realistic house. It does not test motion control. The BEHAVIOR Challenge itself scores low-level policies (joint-space control of the R1Pro from cameras), and our numbers are not comparable to challenge scores.
- Positions and relations are given as numbers. An agent can solve the tasks from `robo observe` without looking at images; the cameras are there for inspection and for the video.
- There is one task instance per activity: the challenge's instance 0 (the cached `*_0_0_template` scene), so every trial of a task starts from the same state. The challenge's other instances (`2026-challenge-task-instances`) could be loaded as seeds by applying their `tro_state` files.
- The simulator runs remotely. A trial fails as an infrastructure error if the worker or the network drops. Each worker handles one trial at a time.
- MolmoAct2 was not run. Its checkpoints are trained for the LIBERO, DROID, SO-100/101 and YAM embodiments, not the R1Pro. There is no BEHAVIOR checkpoint to run zero-shot, and the symbolic interface is not an action space a VLA policy uses.
- Low-level control (the R1Pro's 23-dimensional joint and base action) is not exposed. `robo act` only waits.

## Changes to robouse core

These are backward-compatible additions, and no existing behaviour changes:

- `session.py`: a new `skill` request (`{"op": "skill", "name": ..., "args": [...]}`). It calls an optional backend hook `run_skill(name, args)`, counts one step, records the frames from an optional `pop_frames()` hook into the episode video, and then records one frame. Backends without `run_skill` answer with an error. `skill` joins `act` / `move_to` / `grip` in getting the "episode finished" note.
- `agent_cli.py`: `robo skill NAME [ARG ...]`.
- `oracle.py`: `behavior` added to the backends whose module provides `oracle_main`.
- `backends/__init__.py`: registers `backend: behavior`.
- `runner.py`: the episode-server start timeout (120 s) can be raised per task with `ready_timeout_s` in the `robouse:` block.
- `session.py`: `serve()` ignores a failed reply (`OSError` on `conn.sendall`) when the client has gone away, instead of crashing the episode. This was a bug for every suite. It surfaced here because a harness's tool timeout killed a `robo` call mid-reply.
- `scripts/audit.py`: `skill` counts as a motion request (otherwise every BEHAVIOR trial was flagged "success without motion").
