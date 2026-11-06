# Writing the program

Your deliverable is `solution/solve.py`, defining `solve(robo)`. Robo Use scores the **last program you submit**
(`robo-dev submit`). It runs it once, on a fresh reset of the scene, with no model in the loop, as

```python
<your solve.py>

result = solve(robo)
```

and then ends the episode; the task's judge looks at the state the program leaves. The file in your workspace
is not read for scoring; only a submission is. A trial that ends with neither a submission nor a give-up
(`robo-dev give-up "REASON"`) scores 0.

## Developing

```
robo-dev look                       # a fresh reset: both camera views and the robot's state
robo-dev run [FILE]                 # run FILE (default solution/solve.py) on a fresh reset; not scored
        [--keyframes N]             #   keyframes after the first N motion calls (default 24), plus reset and end
        [--timeout S]               #   stop the program after S seconds (default 1800)
robo-dev submit [FILE]              # submit FILE (default solution/solve.py); you may resubmit, the last counts
robo-dev give-up "REASON"           # end the scored episode without running a program, with REASON; a later
                                    #   submission replaces it
robo-dev status                     # runs used and left (at most {{max_runs}}), submissions, minutes left
```

Each run is a fresh reset of the same scene the submission is scored on. It writes `dev-runs/NNNN/`:

- `summary.json`: whether the program finished or its error, steps used, tool calls;
- `stdout.txt`: what the program printed;
- `calls.jsonl`: one line per tool call, with its arguments, reply and steps;
- `keyframes.jsonl` and `frames/kNNN-<call>.png`: the task's camera views side by side, in the order `robo.info()`
  lists the cameras, after the reset, after motion calls and at the end, with the robot's state.

A development run tells you only what the program did and what the cameras saw. Whether the result satisfies the
task is for you to judge from the images. Runs take simulated time and real time (a few seconds to build the
scene, then the program), so print what you need and look at the frames.

## The program contract

The program is restricted Python, checked before it runs (a run or a submission that breaks it is refused):

- imports: `math` and `numpy` only (`import numpy as np` is fine); no `from ... import`;
- no `class`, `with`, `global`, `nonlocal`, `del`, `async`; no name or attribute that starts with `_`;
- builtins: `abs all any bool dict enumerate float int len list max min print range reversed round set sorted
  str sum tuple zip`, and the exceptions `Exception ValueError TypeError`; no `open`, files, processes or network;
- functions (`def`) and lambdas are fine; define helpers in the same file;
- `print` goes to `stdout.txt` in development; in the scored run it is recorded but read by no one.

A failed tool call raises an exception (catch it as `Exception`). The program does not end the episode: when
`solve` returns, Robo Use does. Every simulated step counts against the task's budget ({{max_steps}} steps);
when the budget is used up the episode ends and further motion calls fail.

## `robo`

| Call | |
|---|---|
| `robo.info()` | the action space, skills, cameras (with each one's 3x4 `projection` matrix) and the step budget |
| `robo.observe()` | the robot's own state (dict; see the task text for its fields); costs no step |
| `robo.image(camera)` | one camera's picture now, a height x width x 3 `uint8` numpy array; costs no step |
| `robo.act(action, repeat=1)` | one low-level action (a list of numbers, as the task text describes), applied `repeat` times |
| `robo.move_to(x, y, z, grip=None, max_steps=100, tol=0.01)` | the hand toward a point, where the task offers it |
| `robo.grip(value, steps=15)` | hold still and set the gripper |
| `robo.skill(name, *args)` | any skill `robo.info()` lists, e.g. `robo.skill("move_to_pose", x, y, z, roll, pitch, yaw)` |

Each skill is also a function of the same name (`move_to_pose(x, y, z, roll, pitch, yaw)`). Motion calls return
a dict with the robot's state and `steps_used`; skills also say whether they reached their target.
