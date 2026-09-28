# Episodes and robo

One trial runs one episode. `robouse run` starts an episode server for the task, gives the agent a fresh workspace and waits for the agent to finish.

```
 agent harness                   episode server
 (Claude Code, Codex, ...)       (robouse serve)
┌─────────────────────────┐     ┌─────────────────────────┐
│ reads instruction.md    │     │ MuJoCo simulator        │
│ robo observe            │────►│ step and time budgets   │
│ robo act, robo move-to  │◄────│ video and trace         │
│ robo done               │     │ judges the final state  │
└─────────────────────────┘     └─────────────────────────┘
          JSON requests over a Unix socket
```

The agent gets a temporary workspace with `instruction.md` and an `observations/` folder for camera images, `robo` first on its `PATH`, and `ROBOUSE_SOCKET` pointing at the episode. There is no reset, teleport or state-setting request: the only way to change the scene is to move the robot.

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
| `verifier/reward.txt` | `1` or `0` |
| `artifacts/recording.mp4` | the episode video |
| `artifacts/observations/` | camera images from the episode's workspace |

Outcomes: `done` (the agent called `robo done`), `success_reached` (success mode `first`), `gave_up` (`robo give-up`, or the harness exited without `robo done`), `budget_exhausted`, `wall_time_exhausted`, `agent_timeout` (the harness hit its time limit) and `agent_exited` (the server was shut down mid-episode; the BenchFlow verifier does this).
