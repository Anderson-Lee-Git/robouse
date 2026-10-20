---
schema_version: '1.3'
task:
  name: robouse/yam-orange-to-bowl
  description: 'Dual YAM: put orange into the bowl (layout 0)'
metadata:
  source_benchmark: Dream Labs YAM MuJoCo example (dreamlabs 1.0.0, dream_examples/yam_mujoco, Apache-2.0)
  source_task: put orange into the bowl
  language_instruction: put orange into the bowl
  suite: yam
  category: pick-and-place
  difficulty: medium
  tags:
  - bimanual
  - yam
  - dream-labs
  - vision
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 60
robouse:
  id: yam-orange-to-bowl
  backend: yam
  env: yam-orange-to-bowl
  seed: 0
  goal:
    kind: in_bowl
    object: orange
  max_steps: 1200
  camera: top
  cameras:
  - top
  - left
  - right
  uncalibrated_cameras:
  - left
  - right
  obs_mode: vision
  visible_fields:
  - right_joint_pos
  - right_gripper_open
  - right_tcp_pos
  - right_tcp_down_deg
  - right_jaw_yaw_deg
  - left_joint_pos
  - left_gripper_open
  - left_tcp_pos
  - left_tcp_down_deg
  - left_jaw_yaw_deg
  frame_every: 2
  control_dt: 0.05
---

# Dual YAM: put orange into the bowl

Two I2RT YAM arms with parallel grippers stand side by side at one edge of a table, in the simulated station that Dream Labs' Dream-1 policy is trained for (Dream Labs' own MuJoCo scene). On the table are an apple, an orange, a banana, a water bottle, a white bowl and a white plate. The objects are where Dream's scene puts them.

## Task

Put orange into the bowl.

**Success:** after you call `robo done` and the robot holds still for 10 steps, the orange rests inside the bowl (its centre within 6.5 cm of the bowl's axis, below the rim height plus 5 cm), released (no fingertip touches it) and at rest. Any other ending scores 0.

**Frame.** Metres, +z up; the table top is at z = 0.76. The robots stand at y = 0.24 and reach toward -y. The left arm's base is at x = +0.305 and the right arm's at x = -0.305, left and right as the `top` camera sees them (+x is to the left in its image).

**Controls.** `robo act` takes 14 numbers: the right arm's six joint angles in radians (absolute targets, clipped to the joint limits that `robo info` lists), the right gripper's opening (0 closed, 1 open), then the same seven numbers for the left arm. One step is 50 ms; the joints move toward their targets under position control. Skills, all closed-loop and counted against the budget:
- `robo skill reach ARM X Y Z [YAW]` moves an arm's tool point (the point between the fingertips) along a straight line to (X, Y, Z) with the gripper pointing straight down. YAW (degrees, optional) is the heading the fingers close along, measured from +x toward +y. It reports the distance left; a target outside the arm's reach is not reached.
- `robo skill set_gripper ARM OPENING [STEPS]` opens or closes one gripper (0 closed, 1 open, about 9.5 cm wide) while the arm holds.
- `robo skill home ARM` moves one arm back to its home pose.

**Observation.** `robo observe` reports, per arm, the joint angles (`*_joint_pos`), the gripper opening (`*_gripper_open`), the tool point (`*_tcp_pos`), how far the gripper is tilted from pointing down (`*_tcp_down_deg`) and the heading the fingers close along (`*_jaw_yaw_deg`). It does not report where the objects are: find them in the camera images. `robo observe --image` saves all three cameras: `top` (over the robots, looking across the table; `robo info` gives its 3x4 projection matrix, which maps a world point to its pixel), and `left` and `right` on the wrists (they move with the arms, so no matrix is given).

The step budget is 1200 steps (60 s of simulated time).

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the scoring, or other files to succeed; the episode server judges the final physical state itself.

```
robo info                          # the robot, its sensors, action groups, skills and step budget
robo observe                       # robot and scene state as numbers
robo observe --image [--camera C]  # also saves a camera image and prints its path (open it to look)
robo act V1 V2 ... [--repeat N]    # one low-level action (the action groups under Controls), applied N times (N <= 50)
robo skill NAME ARG ...            # run a skill listed by `robo info`; it runs until it finishes and reports the result
robo done "short summary"          # end the episode and ask for scoring
robo give-up "reason"              # end the episode without claiming success
```

- Positions are in metres in the world frame (+z up); angles are in degrees unless a field says otherwise.
- The episode has a fixed step budget (see `robo info`); every simulated control step counts, including the steps a skill runs.
- Skills are ordinary controllers: they can fail, stop early or be blocked by the scene. Read what they report and re-observe.
- Success is judged about 10 steps after you call `robo done`, with the robot holding still (each action group's hold value: zero for velocity and delta commands, full brake for a car), so the goal must still be true when the robot stops.
- Call `robo done` exactly once when finished.
