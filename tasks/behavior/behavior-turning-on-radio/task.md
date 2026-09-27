---
schema_version: '1.3'
task:
  name: robouse/behavior-turning-on-radio
  description: Turn on the radio receiver that's on the table in the living room.
metadata:
  source_benchmark: BEHAVIOR-1K (Li et al. 2022/2024), 2026 BEHAVIOR Challenge task list; OmniGibson 3.9.3 on Isaac Sim 5.1
  source_task: turning_on_radio
  suite: behavior
  behavior_scene: house_double_floor_lower
  behavior_instance: 0
  category: household-long-horizon
  difficulty: easy
  language_instruction: Turn on the radio receiver that's on the table in the living room.
  tags:
  - behavior-1k
  - omnigibson
  - isaac-sim
  - r1pro
  - mobile-manipulation
  - symbolic-primitives
  - remote-gpu
  reference_solution: scripted primitive plan, 2 skills (oracle/plan.json)
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: behavior-turning-on-radio
  backend: behavior
  env: turning_on_radio
  scene: house_double_floor_lower
  rooms:
  - corridor_0
  - garden_0
  - kitchen_0
  - living_room_0
  instance: 0
  seed: 0
  max_steps: 20
  camera: follow
  cameras:
  - follow
  - head
  skills: true
  success_mode: final
  obs_mode: state
  frame_every: 1
  linger_s: 5
  ready_timeout_s: 900
  rpc_timeout_s: 600
---

# BEHAVIOR: turning on radio

Turn on the radio receiver that's on the table in the living room.

This is the BEHAVIOR-1K activity `turning_on_radio` in the `house_double_floor_lower` house (rooms loaded: corridor_0, garden_0, kitchen_0, living_room_0). The robot starts where the BEHAVIOR Challenge places it. The step budget is 20 skill calls.

BEHAVIOR's formal goal (BDDL; `?x` are variables, `_1`, `_2` number objects of one category) is:

```
(:goal 
        (and 
            (toggled_on ?radio_receiver.n.01_1)
        )
    )
```

## How to control the robot

You are the robot's high-level policy. You act only through the `robo` command in your shell; you cannot read or change the simulator, the scoring, or other files to succeed. The episode server checks BEHAVIOR's goal conditions on the final simulated state itself.

```
robo info                          # skills, step budget
robo observe                       # robot pose, held object, and every task-relevant object (name, category, room, position, distance, open/on state, inside/on-top relations)
robo observe --image               # also saves a third-person camera image and prints its path (open it to look)
robo observe --image --camera head # the robot's own head camera instead
robo skill navigate_to OBJ         # drive next to OBJ (a held object comes along)
robo skill grasp OBJ               # pick up OBJ (hand must be empty, OBJ within reach)
robo skill place_on_top OBJ        # put the held object on top of OBJ
robo skill place_inside OBJ        # put the held object inside OBJ (open OBJ first if it has a door or lid)
robo skill open OBJ                # open OBJ (hand must be empty)
robo skill close OBJ               # close OBJ (hand must be empty)
robo skill toggle_on OBJ           # switch OBJ on (hand must be empty)
robo skill toggle_off OBJ          # switch OBJ off (hand must be empty)
robo skill release                 # drop the held object where the hand is
robo done "short summary"          # end the episode and ask for scoring
robo give-up "reason"              # end the episode without claiming success
```

- OBJ is an object name exactly as `robo observe` lists it (BEHAVIOR's BDDL instance names, e.g. `bottle.n.01_1`). Identical objects are numbered `_1`, `_2`, ...
- The robot is an R1Pro wheeled mobile manipulator that carries one object at a time. Manipulation skills only work on objects within reach (`in_reach` in `robo observe`, about 1.25 m); use `navigate_to` first. Objects inside a closed container must be taken out after opening it.
- A skill can fail (the response says why, with `ok: False`); a failed skill still costs one step. Every skill call counts against the step budget (`robo info`).
- Success is judged after you call `robo done`, with the robot holding still: every goal condition must hold at that moment. Call `robo done` exactly once when finished.
