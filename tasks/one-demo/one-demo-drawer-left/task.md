---
schema_version: '1.3'
task:
  name: robouse/one-demo-drawer-left
  description: Open the drawer, after one demonstration
metadata:
  source_benchmark: robouse original, after DemoMimic (Sharma et al., arXiv 2609.01938)
  source_task: open-drawer
  source_suite: one-demo
  suite: one-demo
  category: in-context-imitation
  difficulty: medium
  tags:
  - one-demo
  - in-context
  - imitation
  - open-drawer
  demonstration: a cabinet facing the front with 10 cm of travel
  differs: 'faces left: the drawer comes out toward -x'
agent:
  timeout_sec: 1200
verifier:
  timeout_sec: 120
robouse:
  id: one-demo-drawer-left
  backend: tabletop
  seed: 0
  max_steps: 600
  camera: front
  skills: true
  success_mode: final
  scenario:
    id: one-demo-drawer-left
    title: Open the drawer
    family: open-drawer
    objects: []
    fixtures:
    - name: cabinet
      kind: cabinet
      pos:
      - -0.06
      - 0.1
      size:
      - 0.16
      - 0.16
      - 0.1
      facing: left
      travel: 0.1
      color: teal
    goals:
    - type: drawer
      drawer: cabinet
      min_open: 0.075
      released: true
    max_steps: 600
    demo:
      objects: []
      fixtures:
      - name: cabinet
        kind: cabinet
        pos:
        - 0.1
        - 0.12
        size:
        - 0.18
        - 0.16
        - 0.1
        facing: front
        travel: 0.1
        color: darkgrey
      view_azimuth: 40.0
      steps: 116
      commands:
      - op: observe
      - op: move_to
        pos:
        - 0.1
        - 0.0225
        - 0.14
        grip: 1.0
        max_steps: 150
        tol: 0.006
      - op: move_to
        pos:
        - 0.1
        - 0.0225
        - 0.06
        grip: 1.0
        max_steps: 150
        tol: 0.003
      - op: move_to
        pos:
        - 0.1
        - -0.0875
        - 0.06
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - 0.1
        - -0.0875
        - 0.14
        grip: 1.0
        max_steps: 150
        tol: 0.01
      - op: done
        text: drawer open
      frames:
      - label: closed fingers above the gap behind the handle
        step: 35
        after: 2
        qpos:
        - 0.0
        - 0.097953
        - 0.027415
        - 0.142288
        - 1.0
        - 0.000217
        - 0.000101
        - 0.0
        - 2.0e-06
        - 7.6e-05
      - label: fingers down in the gap
        step: 65
        after: 3
        qpos:
        - 0.0
        - 0.099931
        - 0.022666
        - 0.062966
        - 1.0
        - 9.0e-06
        - 4.0e-06
        - 0.0
        - 0.0
        - 1.0e-06
      - label: drawer pulled out to its stop
        step: 96
        after: 4
        qpos:
        - 0.100241
        - 0.099998
        - -0.083858
        - 0.060095
        - 1.0
        - 7.9e-05
        - 0.0
        - -5.0e-06
        - -4.0e-06
        - -0.00049
      - label: fingers lifted out of the handle
        step: 116
        after: 5
        qpos:
        - 0.100004
        - 0.1
        - -0.087131
        - 0.131075
        - 1.0
        - 1.1e-05
        - 0.0
        - 0.0
        - 0.0
        - 2.0e-06
---

# Open the drawer

A two-finger parallel gripper hangs over a table (a floating gripper, no arm; it cannot rotate). x points to the right as seen from the front of the table, y away from the front (toward the back of the table), z up; the table top is at z = 0 and spans x from -0.35 to 0.35 and y from -0.30 to 0.30. The gripper's tool point can reach x in [-0.34, 0.34], y in [-0.27, 0.28], z in [0.012, 0.35]. The fingers close along the y axis; the fully open gap is 10 cm.

**Goal:** A cabinet with one drawer stands on the table. Pull the drawer open.

**Success:** the drawer is pulled out at least 75% of its travel (`max_opening`) and the gripper is not touching it, judged by the episode server about 10 steps after you call `robo done`, with the gripper holding still.

## One demonstration

The same skill was demonstrated on another cabinet in this same scene, with only that cabinet on the table: a reference controller did it through `robo`, and the episode server scored it 1. Your cabinet is a different one, in another place. Work out from the demonstration how the skill is done, and do it on your cabinet.

At the start of your episode, 4 pictures of the demonstration are placed in your working directory, `observations/demo_1.png` to `observations/demo_4.png`. Each shows one moment of it from two cameras: from the front left and above (left), and from straight above (right; the back of the table is at the top, and the gripper is drawn see-through so that it does not hide what it holds).

1. `demo_1.png`, after command 2 (step 35): closed fingers above the gap behind the handle.
2. `demo_2.png`, after command 3 (step 65): fingers down in the gap.
3. `demo_3.png`, after command 4 (step 96): drawer pulled out to its stop.
4. `demo_4.png`, after command 5 (step 116): fingers lifted out of the handle.

These are the demonstration's `robo` commands and what `robo` printed for each. From command 2 on, a reply's `state` is shortened to the gripper and the parts of the cabinet that move.

```console
$ robo observe  # command 1
state:
  hand_pos: [0.0, 0.2, 0.25]
  gripper_open: 1.0
  holding: []
  objects: {}
  fixtures: {'cabinet': {'kind': 'cabinet', 'color': 'darkgrey', 'pos': [0.1, 0.12, 0.0], 'size': [0.18, 0.16, 0.1], 'facing': 'front', 'pull_direction': [0.0, -1.0, 0.0], 'opening': 0.0, 'max_opening': 0.1, 'handle_pos': [0.1, -0.0, 0.06], 'handle_length': 0.08, 'handle_gap': 0.035, 'gripper_touching': False}}
steps_used: 0
max_steps: 600
$ robo move-to 0.1 0.0225 0.14 --grip 1 --max-steps 150 --tol 0.006  # command 2
reached: True
distance: 0.0058
executed_steps: 35
state:
  hand_pos: [0.0979, 0.0275, 0.1423]
  gripper_open: 0.001
  holding: []
  fixtures: {'cabinet': {'opening': 0.0, 'handle_pos': [0.1, -0.0, 0.06], 'gripper_touching': False}}
steps_used: 35
# frame 1: observations/demo_1.png
$ robo move-to 0.1 0.0225 0.06 --grip 1 --max-steps 150 --tol 0.003  # command 3
reached: True
distance: 0.003
executed_steps: 30
state:
  hand_pos: [0.0999, 0.0227, 0.063]
  gripper_open: 0.0
  holding: []
  fixtures: {'cabinet': {'opening': 0.0, 'handle_pos': [0.1, -0.0, 0.06], 'gripper_touching': False}}
steps_used: 65
# frame 2: observations/demo_2.png
$ robo move-to 0.1 -0.0875 0.06 --grip 1 --max-steps 150 --tol 0.004  # command 4
reached: True
distance: 0.0037
executed_steps: 31
state:
  hand_pos: [0.1, -0.0838, 0.0601]
  gripper_open: -0.005
  holding: []
  fixtures: {'cabinet': {'opening': 0.1002, 'handle_pos': [0.1, -0.1002, 0.06], 'gripper_touching': True}}
steps_used: 96
# frame 3: observations/demo_3.png
$ robo move-to 0.1 -0.0875 0.14 --grip 1 --max-steps 150  # command 5
reached: True
distance: 0.009
executed_steps: 20
state:
  hand_pos: [0.1, -0.0871, 0.131]
  gripper_open: 0.0
  holding: []
  fixtures: {'cabinet': {'opening': 0.1, 'handle_pos': [0.1, -0.1, 0.06], 'gripper_touching': False}}
steps_used: 116
# frame 4: observations/demo_4.png
$ robo done "drawer open"  # command 6
outcome: done
episode: finished
# the episode server judged the final state: success, reward 1
```

## What `robo observe` shows

- `hand_pos`: the gripper's tool point (between the fingertips), metres. `gripper_open`: 0 = closed, 1 = fully open (10 cm gap). `holding`: names of objects currently touching the fingers.
- `fixtures.cabinet`: `pos` (its centre), `size` (width across its face, depth, height), `facing` (`front`, `left` or `right`: the side the drawer comes out of), `pull_direction` (unit vector the drawer slides out along), `opening` (metres pulled out, 0 = shut), `max_opening` (its travel), `handle_pos` (the centre of the handle bar, where it is now), `handle_length`, `handle_gap` (the clear gap between the bar and the drawer's face) and `gripper_touching` (whether the gripper touches the drawer or its handle now).

## Gripper

The grip value is a finger position target, not a hold command: +1 = fully closed, -1 = fully open (10 cm gap), and values in between give a partial opening (finger gap = 10 cm * (1 - G) / 2, so 0 = half open, a 5 cm gap). There is no separate "hold" value: to keep holding an object, keep sending +1 (the fingers then squeeze it). `robo move-to X Y Z --grip G` applies G on every step of the move, starting with the first, so `--grip 1` closes the fingers at the start of the move (they take about 15 steps to close fully); without `--grip`, the last grip value is kept. `robo grip G --steps N` holds the hand still for N steps while applying G. The same values apply to the GRIP argument of `robo act`.

`robo move-to` also takes `--max-steps N` (it moves for at most N steps, up to 150; default 100) and `--tol T` (it stops once the tool point is within T metres of the target; default 0.01), as the demonstration's commands do.

## Task rules

- Step budget: 600 simulated steps (one step = 20 ms); the demonstration used 116. Wall-clock limit: 20 minutes.
- `robo done` ends the episode; call it once, when you are finished.

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the scoring, or other files to succeed; the episode server judges the final physical state itself.

```
robo info                         # action space, available skills, step budget
robo observe                      # robot and object state as numbers
robo observe --image              # also saves a camera image and prints its path (open it to look)
robo act DX DY DZ GRIP [--repeat N]   # low-level action, applied N times (N <= 50)
robo move-to X Y Z [--grip G]     # skill: move the gripper toward a point (if enabled for this task)
robo grip G [--steps N]           # skill: hold position and set the gripper (+1 close, -1 open)
robo done "short summary"         # end the episode and ask for scoring
robo give-up "reason"             # end the episode without claiming success
```

- Positions are in metres in the world frame (x, y on the table plane, z up).
- The episode has a fixed step budget (see `robo info`); every simulated step counts, including skills.
- Unless the task says otherwise, success is judged about 10 steps after you call `robo done`, with the robot holding still, so the goal must still be true when the robot stops.
- Work in small steps and re-observe after each motion. Call `robo done` exactly once when finished.
