# Box Close

A Sawyer robot arm with a two-finger gripper stands at a table (adapted from Meta-World, `box-close-v3`).

**Goal:** Pick up the box lid and place it on top of the box.

In `robo observe`: `hand_pos` is the gripper position, `gripper_open` its opening (1 = open),
`obj1_pos`/`obj1_quat` and `obj2_pos` are the task objects (obj1 = lid handle; goal = box top), and `goal_pos` is the target.
The full 39-number observation vector is also given as `obs_vector`.

**Scoring:** as in Meta-World, the episode ends as solved the moment the goal is reached. If you run out of steps or call `robo done` first, it counts as a failure.

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other
way to move the robot, and you cannot read or change the simulator, the scoring, or other files to
succeed; the episode server judges the final physical state itself.

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
- Unless the task says otherwise, success is judged about 10 steps after you call `robo done`, with the
  robot holding still, so the goal must still be true when the robot stops.
- Work in small steps and re-observe after each motion. Call `robo done` exactly once when finished.
