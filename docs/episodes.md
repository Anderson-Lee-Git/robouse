# Episodes and robo

One trial runs one episode. `robouse run` starts an episode server for the task, gives the agent a fresh workspace and waits for the agent to finish.

The agent gets a temporary workspace with `instruction.md` and an `observations/` folder for camera images, `robo` first on its `PATH`, and `ROBOUSE_SOCKET` pointing at the episode. There is no reset, teleport or state-setting request: the only way to change the scene is to move the robot.

![An episode. `robo info` and `robo observe` cost nothing; every simulated step of `act`, `move-to` and `grip` counts against the task's `max_steps`. The ending, recorded as `outcome` in `episode/result.json`, decides the reward. Not shown: the wall-clock limit (`wall_time_exhausted`, 0) and a harness that exits without `robo done` (`gave_up`, 0).](img/episode.svg)

On vision tasks, `robo observe` also saves camera images into the workspace, and the agent opens them like any other file. This is the first image from `arc-gravity-vision`:

![`observations/obs_001_front.png`, the 320×320 front camera image the agent gets from `robo observe` on `arc-gravity-vision`. The agent must infer the rule from example grids and move the blocks it sees.](img/observe-front.webp)

## A session

This is a real session on `metaworld-reach`, whose success mode is `first`:

```console
$ robo info
task: metaworld-reach
backend: metaworld
action: ['dx', 'dy', 'dz', 'grip'] low=[-1, -1, -1, -1] high=[1, 1, 1, 1]
  dx/dy/dz: end-effector velocity, about 1 cm per unit per step; grip: +1 close, -1 open
skills: ['move_to', 'grip']
steps_used: 0
max_steps: 500
observation_mode: state
$ robo observe
state:
  hand_pos: [0.0042, 0.6005, 0.1946]
  gripper_open: 1.0
  obj1_pos: [-0.0125, 0.6892, 0.0196]
  obj1_quat: [0.0003, -0.0003, 0.0, 1.0]
  obj2_pos: [0.0, 0.0, 0.0]
  goal_pos: [-0.0233, 0.8792, 0.1822]
steps_used: 0
max_steps: 500
$ robo act 0 1 0 -1 --repeat 5
executed_steps: 5
state:
  hand_pos: [0.0004, 0.6205, 0.1949]
  ...
steps_used: 5
$ robo move-to -0.0233 0.8792 0.1822
reached: False
distance: 0.0336
executed_steps: 31
state:
  hand_pos: [-0.0208, 0.8459, 0.1852]
  ...
steps_used: 36
episode: finished: goal reached, episode scored as solved
```

Every simulated step counts against `max_steps`, including the steps a skill such as `move-to` takes. All commands: [robo reference](robo-cli.md).

## The trial folder

`robouse run --out runs/try` writes one folder per trial, `runs/try/<task>__<harness>__<id>/`:

| Path | Contents |
|---|---|
| `config.json` | task, harness, `--model` and `--seed` as given, timeout, whether the sandbox was on |
| `result.json` | reward, episode outcome, model, timing, any runner exception |
| `agent/stdout.jsonl`, `agent/stderr.txt` | the harness's raw output |
| `agent/trajectory.json` | the agent's steps in ATIF v1.7, the trajectory format BenchFlow reads |
| `episode/result.json` | the episode server's verdict: `success`, `outcome`, `steps_used`, the seed used |
| `episode/trace.jsonl` | every `robo` request and response, with times |
| `episode/episode.json` | header: task, seed, the robot's embodiment, observation mode, the initial state and its hash |
| `episode/steps.jsonl` | one line per simulator step: action by group, reward, success, the state after the step, the video frame (the training trace) |
| `episode/frames.jsonl`, `episode/video_index.json` | per video frame: wall time and the steps completed when it was rendered |
| `verifier/reward.txt` | `1` or `0` |
| `artifacts/recording.mp4` | the episode video |
| `artifacts/observations/` | camera images from the episode's workspace |

Outcomes: `done` (the agent called `robo done`), `success_reached` (success mode `first`), `gave_up` (`robo give-up`, or the harness exited without `robo done`), `budget_exhausted`, `wall_time_exhausted`, `agent_timeout` (the harness hit its time limit) and `agent_exited` (the server was shut down mid-episode; the BenchFlow verifier does this).
