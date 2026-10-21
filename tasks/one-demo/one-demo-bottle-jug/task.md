---
schema_version: '1.3'
task:
  name: robouse/one-demo-bottle-jug
  description: Stand the bottle up, after one demonstration
metadata:
  source_benchmark: robouse original, after DemoMimic (Sharma et al., arXiv 2609.01938)
  source_task: upright-bottle
  source_suite: one-demo
  suite: one-demo
  category: in-context-imitation
  difficulty: medium
  tags:
  - one-demo
  - in-context
  - imitation
  - upright-bottle
  demonstration: a 6 cm wide bottle with an 11 cm body, cap toward +x
  differs: a short, wide jug lying the other way round
agent:
  timeout_sec: 1200
verifier:
  timeout_sec: 120
robouse:
  id: one-demo-bottle-jug
  backend: tabletop
  seed: 0
  max_steps: 900
  camera: front
  skills: true
  success_mode: final
  scenario:
    id: one-demo-bottle-jug
    title: Stand the bottle up
    family: upright-bottle
    objects:
    - name: bottle
      kind: bottle
      pos:
      - 0.1
      - 0.12
      body:
      - 0.045
      - 0.09
      neck:
      - 0.008
      - 0.03
      lying: -x
      mass: 0.8
      color: orange
      cap_color: white
    fixtures: []
    goals:
    - type: standing
      obj: bottle
      max_tilt: 10
    max_steps: 900
    demo:
      objects:
      - name: bottle
        kind: bottle
        pos:
        - 0.0
        - 0.05
        body:
        - 0.03
        - 0.11
        neck:
        - 0.008
        - 0.035
        lying: +x
        mass: 0.8
        color: green
        cap_color: white
      fixtures: []
      view_azimuth: 90.0
      steps: 278
      commands:
      - op: observe
      - op: move_to
        pos:
        - 0.0665
        - 0.05
        - 0.0998
        grip: -0.3
        max_steps: 150
        tol: 0.006
      - op: move_to
        pos:
        - 0.0665
        - 0.05
        - 0.0298
        grip: -0.3
        max_steps: 150
        tol: 0.003
      - op: grip
        value: 1.0
        steps: 15
      - op: move_to
        pos:
        - 0.0591
        - 0.05
        - 0.0545
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - 0.0476
        - 0.05
        - 0.0776
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - 0.0322
        - 0.05
        - 0.0983
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - 0.0134
        - 0.05
        - 0.116
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - -0.0081
        - 0.05
        - 0.1302
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - -0.0318
        - 0.05
        - 0.1405
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - -0.0569
        - 0.05
        - 0.1464
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - -0.0827
        - 0.05
        - 0.148
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - -0.1083
        - 0.05
        - 0.145
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: grip
        value: -0.3
        steps: 12
      - op: observe
      - op: move_to
        pos:
        - -0.1049
        - 0.05
        - 0.2153
        grip: -0.3
        max_steps: 150
        tol: 0.01
      - op: done
        text: bottle standing
      frames:
      - label: above the cap, fingers part open
        step: 34
        after: 2
        qpos:
        - 2.5e-05
        - 0.049932
        - 0.029817
        - 0.706822
        - 0.000807
        - 0.707391
        - 0.000807
        - 0.064975
        - 0.054033
        - 0.103835
        - 1.0
        - 0.000177
        - 7.5e-05
        - 0.0
        - 0.032486
        - 0.032547
      - label: cap pinched between the fingers
        step: 79
        after: 4
        qpos:
        - 4.6e-05
        - 0.049884
        - 0.02984
        - 0.70656
        - 0.001399
        - 0.707651
        - 0.001448
        - 0.066454
        - 0.050123
        - 0.032299
        - 1.0
        - -0.000148
        - -5.0e-06
        - 4.0e-06
        - 0.010909
        - 0.011354
      - label: cap swung up along the circle about the base's edge
        step: 153
        after: 8
        qpos:
        - -0.034278
        - 0.049954
        - 0.070836
        - 0.893584
        - 0.000456
        - 0.448892
        - 0.001792
        - 0.01595
        - 0.05
        - 0.113375
        - 1.0
        - 3.0e-06
        - 0.000139
        - -1.0e-06
        - 0.011119
        - 0.011107
      - label: bottle upright
        step: 248
        after: 13
        qpos:
        - -0.104072
        - 0.049932
        - 0.080176
        - 0.999459
        - -0.00024
        - 0.032836
        - 0.001933
        - -0.104675
        - 0.05
        - 0.145258
        - 1.0
        - 0.0
        - -4.9e-05
        - -3.0e-06
        - 0.011087
        - 0.011138
      - label: 'released: the bottle stands on its base'
        step: 278
        after: 16
        qpos:
        - -0.109301
        - 0.049885
        - 0.078411
        - 0.999998
        - 4.0e-06
        - -9.0e-06
        - 0.001967
        - -0.104895
        - 0.05
        - 0.20549
        - 1.0
        - 0.0
        - 0.0
        - 0.0
        - 0.032453
        - 0.032454
---

# Stand the bottle up

A two-finger parallel gripper hangs over a table (a floating gripper, no arm; it cannot rotate). x points to the right as seen from the front of the table, y away from the front (toward the back of the table), z up; the table top is at z = 0 and spans x from -0.35 to 0.35 and y from -0.30 to 0.30. The gripper's tool point can reach x in [-0.34, 0.34], y in [-0.27, 0.28], z in [0.012, 0.35]. The fingers close along the y axis; the fully open gap is 10 cm.

**Goal:** A full bottle (0.8 kg) lies on its side on the table. Stand it up on its base.

**Success:** the bottle stands on its base on the table, tilted less than 10 degrees from upright, at rest, and the gripper has let go of it, judged by the episode server about 10 steps after you call `robo done`, with the gripper holding still.

## One demonstration

The same skill was demonstrated on another bottle in this same scene, with only that bottle on the table: a reference controller did it through `robo`, and the episode server scored it 1. Your bottle is a different one, in another place. Work out from the demonstration how the skill is done, and do it on your bottle.

At the start of your episode, 5 pictures of the demonstration are placed in your working directory, `observations/demo_1.png` to `observations/demo_5.png`. Each shows one moment of it from two cameras: from the front and above (left), and from straight above (right; the back of the table is at the top, and the gripper is drawn see-through so that it does not hide what it holds).

1. `demo_1.png`, after command 2 (step 34): above the cap, fingers part open.
2. `demo_2.png`, after command 4 (step 79): cap pinched between the fingers.
3. `demo_3.png`, after command 8 (step 153): cap swung up along the circle about the base's edge.
4. `demo_4.png`, after command 13 (step 248): bottle upright.
5. `demo_5.png`, after command 16 (step 278): released: the bottle stands on its base.

These are the demonstration's `robo` commands and what `robo` printed for each. From command 2 on, a reply's `state` is shortened to the gripper and the parts of the bottle that move.

```console
$ robo observe  # command 1
state:
  hand_pos: [0.0, 0.2, 0.25]
  gripper_open: 1.0
  holding: []
  objects: {'bottle': {'kind': 'bottle', 'color': 'green', 'pos': [0.0, 0.05, 0.0298], 'size': [0.06, 0.06, 0.157], 'axis': [1.0, 0.0, -0.0003], 'base_pos': [-0.0785, 0.05, 0.0298], 'cap_pos': [0.0665, 0.05, 0.0298], 'body_diameter': 0.06, 'neck_diameter': 0.016, 'cap_diameter': 0.024, 'half_height': 0.03, 'tilt_deg': 90.0}}
  fixtures: {}
steps_used: 0
max_steps: 900
$ robo move-to 0.0665 0.05 0.0998 --grip -0.3 --max-steps 150 --tol 0.006  # command 2
reached: True
distance: 0.006
executed_steps: 34
state:
  hand_pos: [0.065, 0.0541, 0.1039]
  gripper_open: 0.65
  holding: []
  objects: {'bottle': {'cap_pos': [0.0665, 0.0499, 0.0298], 'base_pos': [-0.0785, 0.0499, 0.0299], 'tilt_deg': 90.0}}
steps_used: 34
# frame 1: observations/demo_1.png
$ robo move-to 0.0665 0.05 0.0298 --grip -0.3 --max-steps 150 --tol 0.003  # command 3
reached: True
distance: 0.0027
executed_steps: 30
state:
  hand_pos: [0.0664, 0.0501, 0.0325]
  gripper_open: 0.65
  holding: []
  objects: {'bottle': {'cap_pos': [0.0665, 0.0498, 0.0297], 'base_pos': [-0.0785, 0.0498, 0.0299], 'tilt_deg': 90.1}}
steps_used: 64
$ robo grip 1  # command 4
executed_steps: 15
state:
  hand_pos: [0.0665, 0.0501, 0.0323]
  gripper_open: 0.223
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [0.0665, 0.0499, 0.0297], 'base_pos': [-0.0785, 0.0499, 0.03], 'tilt_deg': 90.1}}
steps_used: 79
# frame 2: observations/demo_2.png
$ robo move-to 0.0591 0.05 0.0545 --grip 1 --max-steps 150 --tol 0.004  # command 5
reached: True
distance: 0.0037
executed_steps: 17
state:
  hand_pos: [0.0602, 0.05, 0.0509]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [0.0609, 0.05, 0.0481], 'base_pos': [-0.0829, 0.0499, 0.0295], 'tilt_deg': 82.6}}
steps_used: 96
$ robo move-to 0.0476 0.05 0.0776 --grip 1 --max-steps 150 --tol 0.004  # command 6
reached: True
distance: 0.0037
executed_steps: 19
state:
  hand_pos: [0.0491, 0.05, 0.0742]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [0.0504, 0.05, 0.0711], 'base_pos': [-0.0882, 0.0499, 0.0285], 'tilt_deg': 72.9}}
steps_used: 115
$ robo move-to 0.0322 0.05 0.0983 --grip 1 --max-steps 150 --tol 0.004  # command 7
reached: True
distance: 0.0037
executed_steps: 19
state:
  hand_pos: [0.0343, 0.05, 0.0952]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [0.0365, 0.05, 0.0921], 'base_pos': [-0.0929, 0.0499, 0.0267], 'tilt_deg': 63.2}}
steps_used: 134
$ robo move-to 0.0134 0.05 0.116 --grip 1 --max-steps 150 --tol 0.004  # command 8
reached: True
distance: 0.0037
executed_steps: 19
state:
  hand_pos: [0.016, 0.05, 0.1134]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [0.0191, 0.05, 0.1105], 'base_pos': [-0.0972, 0.0499, 0.024], 'tilt_deg': 53.4}}
steps_used: 153
# frame 3: observations/demo_3.png
$ robo move-to -0.0081 0.05 0.1302 --grip 1 --max-steps 150 --tol 0.004  # command 9
reached: True
distance: 0.0037
executed_steps: 19
state:
  hand_pos: [-0.0051, 0.05, 0.128]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [-0.0012, 0.05, 0.1257], 'base_pos': [-0.1011, 0.0499, 0.0206], 'tilt_deg': 43.5}}
steps_used: 172
$ robo move-to -0.0318 0.05 0.1405 --grip 1 --max-steps 150 --tol 0.004  # command 10
reached: True
distance: 0.0037
executed_steps: 19
state:
  hand_pos: [-0.0285, 0.05, 0.1389]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [-0.024, 0.05, 0.1372], 'base_pos': [-0.1043, 0.0499, 0.0165], 'tilt_deg': 33.6}}
steps_used: 191
$ robo move-to -0.0569 0.05 0.1464 --grip 1 --max-steps 150 --tol 0.004  # command 11
reached: True
distance: 0.0037
executed_steps: 19
state:
  hand_pos: [-0.0534, 0.05, 0.1454]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [-0.0484, 0.05, 0.1447], 'base_pos': [-0.1068, 0.0499, 0.0119], 'tilt_deg': 23.7}}
steps_used: 210
$ robo move-to -0.0827 0.05 0.148 --grip 1 --max-steps 150 --tol 0.004  # command 12
reached: True
distance: 0.0037
executed_steps: 19
state:
  hand_pos: [-0.079, 0.05, 0.1476]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [-0.074, 0.05, 0.1479], 'base_pos': [-0.1085, 0.0499, 0.007], 'tilt_deg': 13.8}}
steps_used: 229
$ robo move-to -0.1083 0.05 0.145 --grip 1 --max-steps 150 --tol 0.004  # command 13
reached: True
distance: 0.0037
executed_steps: 19
state:
  hand_pos: [-0.1046, 0.05, 0.1453]
  gripper_open: 0.222
  holding: ['bottle']
  objects: {'bottle': {'cap_pos': [-0.0997, 0.05, 0.1465], 'base_pos': [-0.1092, 0.0499, 0.0019], 'tilt_deg': 3.8}}
steps_used: 248
# frame 4: observations/demo_4.png
$ robo grip -0.3 --steps 12  # command 14
executed_steps: 12
state:
  hand_pos: [-0.1049, 0.05, 0.1453]
  gripper_open: 0.613
  holding: []
  objects: {'bottle': {'cap_pos': [-0.1095, 0.0499, 0.1447], 'base_pos': [-0.1093, 0.0499, -0.0003], 'tilt_deg': 0.1}}
steps_used: 260
$ robo observe  # command 15
state:
  hand_pos: [-0.1049, 0.05, 0.1453]
  gripper_open: 0.613
  holding: []
  objects: {'bottle': {'cap_pos': [-0.1095, 0.0499, 0.1447], 'base_pos': [-0.1093, 0.0499, -0.0003], 'tilt_deg': 0.1}}
steps_used: 260
max_steps: 900
$ robo move-to -0.1049 0.05 0.2153 --grip -0.3 --max-steps 150  # command 16
reached: True
distance: 0.0099
executed_steps: 18
state:
  hand_pos: [-0.1049, 0.05, 0.2054]
  gripper_open: 0.649
  holding: []
  objects: {'bottle': {'cap_pos': [-0.1093, 0.0499, 0.1449], 'base_pos': [-0.1093, 0.0499, -0.0001], 'tilt_deg': 0.0}}
steps_used: 278
# frame 5: observations/demo_5.png
$ robo done "bottle standing"  # command 17
outcome: done
episode: finished
# the episode server judged the final state: success, reward 1
```

## What `robo observe` shows

- `hand_pos`: the gripper's tool point (between the fingertips), metres. `gripper_open`: 0 = closed, 1 = fully open (10 cm gap). `holding`: names of objects currently touching the fingers.
- `objects.bottle`: `pos` (its centre), `size` (body diameter, body diameter, and the length from the base to the top of the cap), `axis` (unit vector from the base toward the cap), `base_pos` (the centre of the base), `cap_pos` (the centre of the ball cap), `body_diameter`, `neck_diameter`, `cap_diameter`, `half_height`, `tilt_deg` (90 lying, 0 upright). Nearly all of its mass is in the body.

## Gripper

The grip value is a finger position target, not a hold command: +1 = fully closed, -1 = fully open (10 cm gap), and values in between give a partial opening (finger gap = 10 cm * (1 - G) / 2, so 0 = half open, a 5 cm gap). There is no separate "hold" value: to keep holding an object, keep sending +1 (the fingers then squeeze it). `robo move-to X Y Z --grip G` applies G on every step of the move, starting with the first, so `--grip 1` closes the fingers at the start of the move (they take about 15 steps to close fully); without `--grip`, the last grip value is kept. `robo grip G --steps N` holds the hand still for N steps while applying G. The same values apply to the GRIP argument of `robo act`.

`robo move-to` also takes `--max-steps N` (it moves for at most N steps, up to 150; default 100) and `--tol T` (it stops once the tool point is within T metres of the target; default 0.01), as the demonstration's commands do.

## Task rules

- Step budget: 900 simulated steps (one step = 20 ms); the demonstration used 278. Wall-clock limit: 20 minutes.
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
