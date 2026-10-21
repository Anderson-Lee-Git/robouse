---
schema_version: '1.3'
task:
  name: robouse/one-demo-lid-pot
  description: Take the lid off, after one demonstration
metadata:
  source_benchmark: robouse original, after DemoMimic (Sharma et al., arXiv 2609.01938)
  source_task: lift-lid
  source_suite: one-demo
  suite: one-demo
  category: in-context-imitation
  difficulty: medium
  tags:
  - one-demo
  - in-context
  - imitation
  - lift-lid
  demonstration: a square tin 6 cm tall, its pad to the front left
  differs: a round pot with a round lid; the pad lies the other way
agent:
  timeout_sec: 1200
verifier:
  timeout_sec: 120
robouse:
  id: one-demo-lid-pot
  backend: tabletop
  seed: 0
  max_steps: 800
  camera: front
  skills: true
  success_mode: final
  scenario:
    id: one-demo-lid-pot
    title: Take the lid off
    family: lift-lid
    objects:
    - name: lid
      kind: lid
      color: orange
      pos:
      - -0.1
      - 0.08
      z: 0.079
      plug: 0.012
      shape: round
      size:
      - 0.0798
      plug_inset: 0.0188
    fixtures:
    - name: container
      kind: bowl
      pos:
      - -0.1
      - 0.08
      radius: 0.065
      height: 0.07
      color: white
    - name: rest
      kind: pad
      pos:
      - 0.15
      - -0.1
      size:
      - 0.05
      - 0.05
      color: grey
    goals:
    - type: on_pad
      obj: lid
      pad: rest
      max_tilt: 15
    max_steps: 800
    demo:
      objects:
      - name: lid
        kind: lid
        color: red
        pos:
        - 0.1
        - 0.06
        z: 0.069
        plug: 0.012
        shape: box
        size:
        - 0.06
        - 0.06
        plug_inset: 0.014
      fixtures:
      - name: container
        kind: tray
        pos:
        - 0.1
        - 0.06
        size:
        - 0.05
        - 0.05
        height: 0.06
        color: blue
      - name: rest
        kind: pad
        pos:
        - -0.14
        - -0.08
        size:
        - 0.05
        - 0.05
        color: grey
      view_azimuth: 90.0
      steps: 204
      commands:
      - op: observe
      - op: move_to
        pos:
        - 0.1
        - 0.06
        - 0.1489
        grip: -0.3
        max_steps: 150
        tol: 0.006
      - op: move_to
        pos:
        - 0.1
        - 0.06
        - 0.0789
        grip: -0.3
        max_steps: 150
        tol: 0.003
      - op: grip
        value: 1.0
        steps: 15
      - op: move_to
        pos:
        - 0.1
        - 0.06
        - 0.1209
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: observe
      - op: move_to
        pos:
        - -0.1401
        - -0.08
        - 0.1169
        grip: 1.0
        max_steps: 150
        tol: 0.004
      - op: move_to
        pos:
        - -0.1401
        - -0.08
        - 0.0377
        grip: 1.0
        max_steps: 150
        tol: 0.003
      - op: grip
        value: -0.3
        steps: 12
      - op: observe
      - op: move_to
        pos:
        - -0.14
        - -0.08
        - 0.1204
        grip: -0.3
        max_steps: 150
        tol: 0.01
      - op: done
        text: lid on the pad
      frames:
      - label: above the knob, fingers part open
        step: 33
        after: 2
        qpos:
        - 0.1
        - 0.06
        - 0.068945
        - 1.0
        - 0.0
        - 0.0
        - 0.0
        - 0.097432
        - 0.064033
        - 0.1515
        - 1.0
        - 0.000186
        - 0.000133
        - 0.0
        - 0.03249
        - 0.032551
      - label: knob pinched between the fingers
        step: 77
        after: 4
        qpos:
        - 0.1
        - 0.060001
        - 0.068948
        - 1.0
        - -8.0e-06
        - 0.0
        - 0.0
        - 0.099909
        - 0.06014
        - 0.081647
        - 1.0
        - -1.8e-05
        - 0.0
        - 1.0e-06
        - 0.009506
        - 0.00968
      - label: lid lifted straight up, plug clear of the rim
        step: 98
        after: 5
        qpos:
        - 0.100081
        - 0.059965
        - 0.10422
        - 1.0
        - 1.0e-06
        - 3.0e-06
        - -1.4e-05
        - 0.099991
        - 0.060014
        - 0.11697
        - 1.0
        - 1.0e-06
        - 2.0e-06
        - 0.0
        - 0.009596
        - 0.009599
      - label: carried over the pad
        step: 142
        after: 7
        qpos:
        - -0.132922
        - -0.078858
        - 0.103208
        - 0.997718
        - -0.000273
        - -0.067352
        - 0.004769
        - -0.136496
        - -0.078834
        - 0.116896
        - 1.0
        - 5.4e-05
        - -7.6e-05
        - -1.0e-06
        - 0.00968
        - 0.009724
      - label: set down on the pad and let go
        step: 184
        after: 9
        qpos:
        - -0.132948
        - -0.079968
        - 0.020618
        - 0.999987
        - -2.1e-05
        - 0.001978
        - 0.004667
        - -0.139987
        - -0.079963
        - 0.040402
        - 1.0
        - 0.0
        - 0.0
        - 0.0
        - 0.03052
        - 0.030522
---

# Take the lid off

A two-finger parallel gripper hangs over a table (a floating gripper, no arm; it cannot rotate). x points to the right as seen from the front of the table, y away from the front (toward the back of the table), z up; the table top is at z = 0 and spans x from -0.35 to 0.35 and y from -0.30 to 0.30. The gripper's tool point can reach x in [-0.34, 0.34], y in [-0.27, 0.28], z in [0.012, 0.35]. The fingers close along the y axis; the fully open gap is 10 cm.

**Goal:** A container with a lid on it stands on the table. Take the lid off and put it down on the grey pad.

**Success:** the lid's centre is over the grey pad (`fixtures.rest`), the lid rests on the table there, tilted less than 15 degrees, and the gripper has let go of it, judged by the episode server about 10 steps after you call `robo done`, with the gripper holding still.

## One demonstration

The same skill was demonstrated on another container in this same scene, with only that container on the table: a reference controller did it through `robo`, and the episode server scored it 1. Your container is a different one, in another place. Work out from the demonstration how the skill is done, and do it on your container.

At the start of your episode, 5 pictures of the demonstration are placed in your working directory, `observations/demo_1.png` to `observations/demo_5.png`. Each shows one moment of it from two cameras: from the front and above (left), and from straight above (right; the back of the table is at the top, and the gripper is drawn see-through so that it does not hide what it holds).

1. `demo_1.png`, after command 2 (step 33): above the knob, fingers part open.
2. `demo_2.png`, after command 4 (step 77): knob pinched between the fingers.
3. `demo_3.png`, after command 5 (step 98): lid lifted straight up, plug clear of the rim.
4. `demo_4.png`, after command 7 (step 142): carried over the pad.
5. `demo_5.png`, after command 9 (step 184): set down on the pad and let go.

These are the demonstration's `robo` commands and what `robo` printed for each. From command 2 on, a reply's `state` is shortened to the gripper and the parts of the container that move.

```console
$ robo observe  # command 1
state:
  hand_pos: [0.0, 0.2, 0.25]
  gripper_open: 1.0
  holding: []
  objects: {'lid': {'kind': 'lid', 'color': 'red', 'pos': [0.1, 0.06, 0.0689], 'shape': 'box', 'size': [0.12, 0.12, 0.042], 'yaw_deg': 0.0, 'knob_pos': [0.1, 0.06, 0.0789], 'knob_diameter': 0.02, 'plug_depth': 0.012, 'half_height': 0.021, 'tilt_deg': 0.0}}
  fixtures: {'container': {'kind': 'tray', 'color': 'blue', 'pos': [0.1, 0.06, 0.0], 'floor_z': 0.006, 'rim_z': 0.06, 'inner_size': [0.1, 0.1]}, 'rest': {'kind': 'pad', 'color': 'grey', 'pos': [-0.14, -0.08, 0.0], 'size': [0.1, 0.1]}}
steps_used: 0
max_steps: 800
$ robo move-to 0.1 0.06 0.1489 --grip -0.3 --max-steps 150 --tol 0.006  # command 2
reached: True
distance: 0.0055
executed_steps: 33
state:
  hand_pos: [0.0974, 0.0641, 0.1515]
  gripper_open: 0.65
  holding: []
  objects: {'lid': {'pos': [0.1, 0.06, 0.0689], 'knob_pos': [0.1, 0.06, 0.0789], 'tilt_deg': 0.0}}
steps_used: 33
# frame 1: observations/demo_1.png
$ robo move-to 0.1 0.06 0.0789 --grip -0.3 --max-steps 150 --tol 0.003  # command 3
reached: True
distance: 0.003
executed_steps: 29
state:
  hand_pos: [0.0999, 0.0602, 0.0819]
  gripper_open: 0.65
  holding: []
  objects: {'lid': {'pos': [0.1, 0.06, 0.0689], 'knob_pos': [0.1, 0.06, 0.0789], 'tilt_deg': 0.0}}
steps_used: 62
$ robo grip 1  # command 4
executed_steps: 15
state:
  hand_pos: [0.0999, 0.0601, 0.0816]
  gripper_open: 0.192
  holding: ['lid']
  objects: {'lid': {'pos': [0.1, 0.06, 0.0689], 'knob_pos': [0.1, 0.06, 0.0789], 'tilt_deg': 0.0}}
steps_used: 77
# frame 2: observations/demo_2.png
$ robo move-to 0.1 0.06 0.1209 --grip 1 --max-steps 150 --tol 0.004  # command 5
reached: True
distance: 0.004
executed_steps: 21
state:
  hand_pos: [0.1, 0.06, 0.1169]
  gripper_open: 0.192
  holding: ['lid']
  objects: {'lid': {'pos': [0.1001, 0.06, 0.1042], 'knob_pos': [0.1001, 0.06, 0.1142], 'tilt_deg': 0.0}}
steps_used: 98
# frame 3: observations/demo_3.png
$ robo observe  # command 6
state:
  hand_pos: [0.1, 0.06, 0.1169]
  gripper_open: 0.192
  holding: ['lid']
  objects: {'lid': {'pos': [0.1001, 0.06, 0.1042], 'knob_pos': [0.1001, 0.06, 0.1142], 'tilt_deg': 0.0}}
steps_used: 98
max_steps: 800
$ robo move-to -0.1401 -0.08 0.1169 --grip 1 --max-steps 150 --tol 0.004  # command 7
reached: True
distance: 0.0038
executed_steps: 44
state:
  hand_pos: [-0.1365, -0.0788, 0.1169]
  gripper_open: 0.194
  holding: ['lid']
  objects: {'lid': {'pos': [-0.1329, -0.0788, 0.1032], 'knob_pos': [-0.1342, -0.0788, 0.1131], 'tilt_deg': 7.7}}
steps_used: 142
# frame 4: observations/demo_4.png
$ robo move-to -0.1401 -0.08 0.0377 --grip 1 --max-steps 150 --tol 0.003  # command 8
reached: True
distance: 0.0029
executed_steps: 30
state:
  hand_pos: [-0.14, -0.08, 0.0406]
  gripper_open: 0.194
  holding: ['lid']
  objects: {'lid': {'pos': [-0.1364, -0.08, 0.0268], 'knob_pos': [-0.1377, -0.08, 0.0367], 'tilt_deg': 7.6}}
steps_used: 172
$ robo grip -0.3 --steps 12  # command 9
executed_steps: 12
state:
  hand_pos: [-0.14, -0.08, 0.0404]
  gripper_open: 0.61
  holding: []
  objects: {'lid': {'pos': [-0.1329, -0.08, 0.0206], 'knob_pos': [-0.1329, -0.08, 0.0306], 'tilt_deg': 0.2}}
steps_used: 184
# frame 5: observations/demo_5.png
$ robo observe  # command 10
state:
  hand_pos: [-0.14, -0.08, 0.0404]
  gripper_open: 0.61
  holding: []
  objects: {'lid': {'pos': [-0.1329, -0.08, 0.0206], 'knob_pos': [-0.1329, -0.08, 0.0306], 'tilt_deg': 0.2}}
steps_used: 184
max_steps: 800
$ robo move-to -0.14 -0.08 0.1204 --grip -0.3 --max-steps 150  # command 11
reached: True
distance: 0.009
executed_steps: 20
state:
  hand_pos: [-0.14, -0.08, 0.1114]
  gripper_open: 0.649
  holding: []
  objects: {'lid': {'pos': [-0.133, -0.08, 0.0208], 'knob_pos': [-0.133, -0.08, 0.0308], 'tilt_deg': 0.0}}
steps_used: 204
$ robo done "lid on the pad"  # command 12
outcome: done
episode: finished
# the episode server judged the final state: success, reward 1
```

## What `robo observe` shows

- `hand_pos`: the gripper's tool point (between the fingertips), metres. `gripper_open`: 0 = closed, 1 = fully open (10 cm gap). `holding`: names of objects currently touching the fingers.
- `objects.lid`: `shape` (`box` or `round`), `pos` (its centre), `size` (outer x, y and the height from the bottom of its plug to the top of its knob), `knob_pos` (the centre of the knob on top, where it is now), `knob_diameter`, `plug_depth` (how far the plug under the lid reaches down into the container), `half_height`, `tilt_deg`. `fixtures.container` is the container (a tray or an octagonal bowl, with `rim_z`), and `fixtures.rest` is the grey pad.

## Gripper

The grip value is a finger position target, not a hold command: +1 = fully closed, -1 = fully open (10 cm gap), and values in between give a partial opening (finger gap = 10 cm * (1 - G) / 2, so 0 = half open, a 5 cm gap). There is no separate "hold" value: to keep holding an object, keep sending +1 (the fingers then squeeze it). `robo move-to X Y Z --grip G` applies G on every step of the move, starting with the first, so `--grip 1` closes the fingers at the start of the move (they take about 15 steps to close fully); without `--grip`, the last grip value is kept. `robo grip G --steps N` holds the hand still for N steps while applying G. The same values apply to the GRIP argument of `robo act`.

`robo move-to` also takes `--max-steps N` (it moves for at most N steps, up to 150; default 100) and `--tol T` (it stops once the tool point is within T metres of the target; default 0.01), as the demonstration's commands do.

## Task rules

- Step budget: 800 simulated steps (one step = 20 ms); the demonstration used 204. Wall-clock limit: 20 minutes.
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
