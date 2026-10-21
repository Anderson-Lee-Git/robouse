---
schema_version: '1.3'
task:
  name: robouse/one-demo-box-wide
  description: Open the box, after one demonstration
metadata:
  source_benchmark: robouse original, after DemoMimic (Sharma et al., arXiv 2609.01938)
  source_task: open-box
  source_suite: one-demo
  suite: one-demo
  category: in-context-imitation
  difficulty: medium
  tags:
  - one-demo
  - in-context
  - imitation
  - open-box
  demonstration: a 14 x 10 x 6 cm box hinged on the left
  differs: 'a wide flat case with the hinge on the right: a lid 8 cm longer, swinging the other way'
agent:
  timeout_sec: 1200
verifier:
  timeout_sec: 120
robouse:
  id: one-demo-box-wide
  backend: tabletop
  seed: 0
  max_steps: 900
  camera: front
  skills: true
  success_mode: final
  scenario:
    id: one-demo-box-wide
    title: Open the box
    family: open-box
    objects: []
    fixtures:
    - name: box
      kind: hinged_box
      pos:
      - 0.02
      - -0.06
      size:
      - 0.22
      - 0.12
      - 0.045
      hinge: right
      color: grey
      lid_color: red
    goals:
    - type: lid_open
      box: box
      min_deg: 100
    max_steps: 900
    demo:
      objects: []
      fixtures:
      - name: box
        kind: hinged_box
        pos:
        - 0.08
        - 0.04
        size:
        - 0.14
        - 0.1
        - 0.06
        hinge: left
        color: tan
        lid_color: brown
      view_azimuth: 90.0
      steps: 268
      commands:
      - op: observe
      - op: move_to
        pos:
        - 0.125
        - 0.04
        - 0.152
        grip: -0.3
        max_steps: 150
        tol: 0.006
      - op: move_to
        pos:
        - 0.125
        - 0.04
        - 0.082
        grip: -0.3
        max_steps: 150
        tol: 0.003
      - op: grip
        value: 1.0
        steps: 15
      - op: move_to
        pos:
        - 0.1144
        - 0.04
        - 0.1109
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - 0.0966
        - 0.04
        - 0.136
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - 0.0729
        - 0.04
        - 0.1557
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - 0.045
        - 0.04
        - 0.1686
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - 0.0147
        - 0.04
        - 0.1738
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - -0.016
        - 0.04
        - 0.171
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - -0.0449
        - 0.04
        - 0.1604
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: grip
        value: -0.3
        steps: 12
      - op: observe
      - op: move_to
        pos:
        - -0.0915
        - 0.04
        - 0.1616
        grip: -0.3
        max_steps: 150
        tol: 0.006
      - op: move_to
        pos:
        - -0.0915
        - 0.04
        - 0.2416
        grip: -0.3
        max_steps: 150
        tol: 0.01
      - op: done
        text: lid open
      frames:
      - label: above the knob, fingers part open
        step: 34
        after: 2
        qpos:
        - -0.000174
        - 0.12197
        - 0.044515
        - 0.154247
        - 1.0
        - 0.000196
        - 0.000148
        - 0.0
        - 0.032483
        - 0.032551
      - label: knob pinched between the fingers
        step: 78
        after: 4
        qpos:
        - -0.000174
        - 0.124893
        - 0.040157
        - 0.084736
        - 1.0
        - -8.0e-06
        - 0.0
        - 0.0
        - 0.010925
        - 0.011219
      - label: lid swung up along the circle about the hinge
        step: 156
        after: 8
        qpos:
        - 0.979112
        - 0.04838
        - 0.04
        - 0.166808
        - 1.0
        - 0.0
        - 0.000467
        - 0.0
        - 0.011053
        - 0.011053
      - label: lid past upright
        step: 216
        after: 11
        qpos:
        - 1.754051
        - -0.04124
        - 0.04
        - 0.161519
        - 1.0
        - 0.0
        - 0.000537
        - 0.0
        - 0.011053
        - 0.011053
      - label: 'released: the lid rests open on its stop'
        step: 268
        after: 15
        qpos:
        - 1.919927
        - -0.090919
        - 0.04
        - 0.232661
        - 1.0
        - 0.0
        - -2.0e-05
        - 0.0
        - 0.032499
        - 0.032499
---

# Open the box

A two-finger parallel gripper hangs over a table (a floating gripper, no arm; it cannot rotate). x points to the right as seen from the front of the table, y away from the front (toward the back of the table), z up; the table top is at z = 0 and spans x from -0.35 to 0.35 and y from -0.30 to 0.30. The gripper's tool point can reach x in [-0.34, 0.34], y in [-0.27, 0.28], z in [0.012, 0.35]. The fingers close along the y axis; the fully open gap is 10 cm.

**Goal:** A box with a hinged lid stands on the table. Open it: swing the lid open on its hinge so that it stays open by itself.

**Success:** the lid is open at least 100 degrees (`lid_angle_deg`; it stops at 110) and the gripper is not touching it, judged by the episode server about 10 steps after you call `robo done`, with the gripper holding still.

## One demonstration

The same skill was demonstrated on another box in this same scene, with only that box on the table: a reference controller did it through `robo`, and the episode server scored it 1. Your box is a different one, in another place. Work out from the demonstration how the skill is done, and do it on your box.

At the start of your episode, 5 pictures of the demonstration are placed in your working directory, `observations/demo_1.png` to `observations/demo_5.png`. Each shows one moment of it from two cameras: from the front and above (left), and from straight above (right; the back of the table is at the top, and the gripper is drawn see-through so that it does not hide what it holds).

1. `demo_1.png`, after command 2 (step 34): above the knob, fingers part open.
2. `demo_2.png`, after command 4 (step 78): knob pinched between the fingers.
3. `demo_3.png`, after command 8 (step 156): lid swung up along the circle about the hinge.
4. `demo_4.png`, after command 11 (step 216): lid past upright.
5. `demo_5.png`, after command 15 (step 268): released: the lid rests open on its stop.

These are the demonstration's `robo` commands and what `robo` printed for each. From command 2 on, a reply's `state` is shortened to the gripper and the parts of the box that move.

```console
$ robo observe  # command 1
state:
  hand_pos: [0.0, 0.2, 0.25]
  gripper_open: 1.0
  holding: []
  objects: {}
  fixtures: {'box': {'kind': 'hinged_box', 'color': 'tan', 'pos': [0.08, 0.04, 0.0], 'size': [0.14, 0.1, 0.06], 'hinge_side': 'left', 'hinge_pos': [0.01, 0.04, 0.056], 'lid_angle_deg': 0.0, 'max_angle_deg': 110.0, 'knob_pos': [0.125, 0.04, 0.082], 'knob_diameter': 0.024, 'gripper_touching': False}}
steps_used: 0
max_steps: 900
$ robo move-to 0.125 0.04 0.152 --grip -0.3 --max-steps 150 --tol 0.006  # command 2
reached: True
distance: 0.0059
executed_steps: 34
state:
  hand_pos: [0.1219, 0.0446, 0.1543]
  gripper_open: 0.65
  holding: []
  fixtures: {'box': {'lid_angle_deg': 0.0, 'knob_pos': [0.125, 0.04, 0.082], 'gripper_touching': False}}
steps_used: 34
# frame 1: observations/demo_1.png
$ robo move-to 0.125 0.04 0.082 --grip -0.3 --max-steps 150 --tol 0.003  # command 3
reached: True
distance: 0.0029
executed_steps: 29
state:
  hand_pos: [0.1249, 0.0402, 0.0849]
  gripper_open: 0.65
  holding: []
  fixtures: {'box': {'lid_angle_deg': 0.0, 'knob_pos': [0.125, 0.04, 0.082], 'gripper_touching': False}}
steps_used: 63
$ robo grip 1  # command 4
executed_steps: 15
state:
  hand_pos: [0.1249, 0.0402, 0.0847]
  gripper_open: 0.221
  holding: []
  fixtures: {'box': {'lid_angle_deg': 0.0, 'knob_pos': [0.125, 0.04, 0.082], 'gripper_touching': True}}
steps_used: 78
# frame 2: observations/demo_2.png
$ robo move-to 0.1144 0.04 0.1109 --grip 1 --max-steps 150 --tol 0.004  # command 5
reached: True
distance: 0.004
executed_steps: 18
state:
  hand_pos: [0.1158, 0.04, 0.1072]
  gripper_open: 0.221
  holding: []
  fixtures: {'box': {'lid_angle_deg': 11.7, 'knob_pos': [0.1174, 0.04, 0.1047], 'gripper_touching': True}}
steps_used: 96
$ robo move-to 0.0966 0.04 0.136 --grip 1 --max-steps 150 --tol 0.004  # command 6
reached: True
distance: 0.0039
executed_steps: 20
state:
  hand_pos: [0.0987, 0.04, 0.1327]
  gripper_open: 0.221
  holding: []
  fixtures: {'box': {'lid_angle_deg': 26.5, 'knob_pos': [0.1013, 0.04, 0.1306], 'gripper_touching': True}}
steps_used: 116
$ robo move-to 0.0729 0.04 0.1557 --grip 1 --max-steps 150 --tol 0.004  # command 7
reached: True
distance: 0.0039
executed_steps: 20
state:
  hand_pos: [0.0757, 0.04, 0.1531]
  gripper_open: 0.221
  holding: []
  fixtures: {'box': {'lid_angle_deg': 41.3, 'knob_pos': [0.0792, 0.04, 0.1514], 'gripper_touching': True}}
steps_used: 136
$ robo move-to 0.045 0.04 0.1686 --grip 1 --max-steps 150 --tol 0.004  # command 8
reached: True
distance: 0.0039
executed_steps: 20
state:
  hand_pos: [0.0484, 0.04, 0.1668]
  gripper_open: 0.221
  holding: []
  fixtures: {'box': {'lid_angle_deg': 56.1, 'knob_pos': [0.0526, 0.04, 0.1659], 'gripper_touching': True}}
steps_used: 156
# frame 3: observations/demo_3.png
$ robo move-to 0.0147 0.04 0.1738 --grip 1 --max-steps 150 --tol 0.004  # command 9
reached: True
distance: 0.0039
executed_steps: 20
state:
  hand_pos: [0.0185, 0.04, 0.1729]
  gripper_open: 0.221
  holding: []
  fixtures: {'box': {'lid_angle_deg': 70.9, 'knob_pos': [0.0231, 0.04, 0.1732], 'gripper_touching': True}}
steps_used: 176
$ robo move-to -0.016 0.04 0.171 --grip 1 --max-steps 150 --tol 0.004  # command 10
reached: True
distance: 0.0039
executed_steps: 20
state:
  hand_pos: [-0.0121, 0.04, 0.1711]
  gripper_open: 0.221
  holding: []
  fixtures: {'box': {'lid_angle_deg': 85.7, 'knob_pos': [-0.0073, 0.04, 0.1726], 'gripper_touching': True}}
steps_used: 196
$ robo move-to -0.0449 0.04 0.1604 --grip 1 --max-steps 150 --tol 0.004  # command 11
reached: True
distance: 0.0039
executed_steps: 20
state:
  hand_pos: [-0.0412, 0.04, 0.1615]
  gripper_open: 0.221
  holding: []
  fixtures: {'box': {'lid_angle_deg': 100.5, 'knob_pos': [-0.0365, 0.04, 0.1643], 'gripper_touching': True}}
steps_used: 216
# frame 4: observations/demo_4.png
$ robo grip -0.3 --steps 12  # command 12
executed_steps: 12
state:
  hand_pos: [-0.0415, 0.04, 0.1616]
  gripper_open: 0.61
  holding: []
  fixtures: {'box': {'lid_angle_deg': 104.5, 'knob_pos': [-0.0439, 0.04, 0.1609], 'gripper_touching': False}}
steps_used: 228
$ robo observe  # command 13
state:
  hand_pos: [-0.0415, 0.04, 0.1616]
  gripper_open: 0.61
  holding: []
  fixtures: {'box': {'lid_angle_deg': 104.5, 'knob_pos': [-0.0439, 0.04, 0.1609], 'gripper_touching': False}}
steps_used: 228
max_steps: 900
$ robo move-to -0.0915 0.04 0.1616 --grip -0.3 --max-steps 150 --tol 0.006  # command 14
reached: True
distance: 0.0056
executed_steps: 20
state:
  hand_pos: [-0.0859, 0.04, 0.1616]
  gripper_open: 0.649
  holding: []
  fixtures: {'box': {'lid_angle_deg': 110.0, 'knob_pos': [-0.0538, 0.04, 0.1552], 'gripper_touching': False}}
steps_used: 248
$ robo move-to -0.0915 0.04 0.2416 --grip -0.3 --max-steps 150  # command 15
reached: True
distance: 0.009
executed_steps: 20
state:
  hand_pos: [-0.0909, 0.04, 0.2326]
  gripper_open: 0.65
  holding: []
  fixtures: {'box': {'lid_angle_deg': 110.0, 'knob_pos': [-0.0538, 0.04, 0.1552], 'gripper_touching': False}}
steps_used: 268
# frame 5: observations/demo_5.png
$ robo done "lid open"  # command 16
outcome: done
episode: finished
# the episode server judged the final state: success, reward 1
```

## What `robo observe` shows

- `hand_pos`: the gripper's tool point (between the fingertips), metres. `gripper_open`: 0 = closed, 1 = fully open (10 cm gap). `holding`: names of objects currently touching the fingers.
- `fixtures.box`: `pos` (the centre of its base), `size` (outer x, y and height, closed lid included), `hinge_side` (`left`: the hinge runs along the box's top edge at smaller x, so the lid swings up and over to the left; `right`: the opposite), `hinge_pos` (the middle of the hinge line, which runs along y), `lid_angle_deg` (0 = shut), `max_angle_deg`, `knob_pos` (the centre of the ball knob on the lid, where it is now), `knob_diameter` and `gripper_touching` (whether the gripper touches the lid or its knob now; `holding` lists free objects only).

## Gripper

The grip value is a finger position target, not a hold command: +1 = fully closed, -1 = fully open (10 cm gap), and values in between give a partial opening (finger gap = 10 cm * (1 - G) / 2, so 0 = half open, a 5 cm gap). There is no separate "hold" value: to keep holding an object, keep sending +1 (the fingers then squeeze it). `robo move-to X Y Z --grip G` applies G on every step of the move, starting with the first, so `--grip 1` closes the fingers at the start of the move (they take about 15 steps to close fully); without `--grip`, the last grip value is kept. `robo grip G --steps N` holds the hand still for N steps while applying G. The same values apply to the GRIP argument of `robo act`.

`robo move-to` also takes `--max-steps N` (it moves for at most N steps, up to 150; default 100) and `--tol T` (it stops once the tool point is within T metres of the target; default 0.01), as the demonstration's commands do.

## Task rules

- Step budget: 900 simulated steps (one step = 20 ms); the demonstration used 268. Wall-clock limit: 20 minutes.
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
