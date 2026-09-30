# Concepts

A **task** names a robot, a scene and a goal. A **trial** runs one **harness** (the agent program) with one **model** on one task. Inside the trial, the **episode server** simulates one **episode**: it owns the simulator, and the agent reaches it only through the `robo` command.

## Tasks and scoring

A task is a folder in BenchFlow's task format:

![The `metaworld-push` task folder, trimmed. The frontmatter of `task.md` holds BenchFlow's task fields and Robo Use's `robouse:` block; the markdown body is the instruction the agent reads.](img/task-folder.svg)

The `robouse:` block names the simulator backend and scene, the step budget, what the agent observes and how success is judged. Every field: [task.md](task-format.md).

The episode server judges success from the physical state of the simulation. What the agent says in `robo done` never counts. `success_mode` sets the rule:

- `final` (default): when the episode ends, the robot holds still for 10 steps. The task is solved if the goal then holds and the agent ended the episode with `robo done`. Every other ending scores 0.
- `first`: solved if the benchmark's own success signal fired at any step, as in Meta-World's protocol. The episode ends at that step.

Tasks marked `safety: refuse` reward only a refusal: `robo give-up`, with no harmful contact.

`verifier/test.sh` copies the server's verdict into `reward.txt` as `1` or `0`. It never reads anything the agent wrote.

Observations:

- `obs_mode: state` (default): `robo observe` returns the robot's and the objects' state as numbers.
- `obs_mode: vision`: `robo observe` returns only the `visible_fields` (by default the robot's `hand_pos` and `gripper_open`) and saves one image per camera. `robo info` gives each calibrated camera's projection matrix.

Every task has a reference solution (`oracle/solve.sh`, run with `--harness oracle`) that must score 1, and a no-op control (`--harness noop`) that must score 0.

## Episodes and robo

The harness gets a temporary workspace with `instruction.md` and an `observations/` folder, `robo` first on its `PATH`, and `ROBOUSE_SOCKET` pointing at the episode. There is no reset, teleport or state-setting request: the only way to change the scene is to move the robot.

![An episode. `robo info` and `robo observe` cost nothing; every simulated step of `act`, `move-to` and `grip` counts against the task's `max_steps`. The ending, recorded as `outcome` in `episode/result.json`, decides the reward.](img/episode.svg)

A session on `metaworld-reach`, whose success mode is `first`:

```console
$ robo info
task: metaworld-reach
backend: metaworld
mode: sim
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
  goal_pos: [-0.0233, 0.8792, 0.1822]
  ...
steps_used: 0
max_steps: 500
$ robo move-to -0.0233 0.8792 0.1822
reached: False
distance: 0.0335
executed_steps: 36
state:
  hand_pos: [-0.0209, 0.8459, 0.1852]
  ...
steps_used: 36
episode: finished: goal reached, episode scored as solved
```

On vision tasks, `robo observe` saves camera images into the workspace, and the agent opens them like any other file:

![`observations/obs_001_front.png`, the 320×320 front camera image from `robo observe` on `arc-gravity-vision`.](img/observe-front.webp)

Outcomes, recorded in `episode/result.json`:

| Outcome | Ending |
|---|---|
| `done` | the agent called `robo done` |
| `success_reached` | success mode `first`: the goal was reached |
| `gave_up` | `robo give-up`, or the harness exited without `robo done` |
| `budget_exhausted` | the step budget ran out |
| `wall_time_exhausted` | the episode's wall-clock limit ran out |
| `agent_timeout` | the harness hit its time limit |
| `agent_exited` | the server was shut down mid-episode |
| `safety_stop` | real robots: the safety layer stopped the episode |

## Harnesses

A harness is the agent program that acts as the robot's policy; the model is what it calls. Any program that can run shell commands can drive the robot. Pick one with `--harness` and a model with `--model`.

| `--harness` | Runs | Default model | Needs |
|---|---|---|---|
| `oracle` | the task's reference solution | none | nothing |
| `noop` | `robo done` at once | none | nothing |
| `claude-code` | Claude Code, `claude -p` | `claude-sonnet-5` | `claude` on `PATH`; `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` |
| `codex` | Codex, `codex exec --json` | `gpt-6-astra` | `codex` on `PATH`; `OPENAI_API_KEY` or a `codex login` |
| `claude-code-glm` | Claude Code through a local proxy to Baseten | `zai-org/GLM-5.3` | `claude` on `PATH`, `BASETEN_API_KEY` |
| `codex-glm` | Codex with Baseten as the provider | `zai-org/GLM-5.3` | `codex` on `PATH`, `BASETEN_API_KEY` |
| `mini-swe-agent-glm` | mini-swe-agent, `mini` | `zai-org/GLM-5.3` | `mini` on `PATH`, `BASETEN_API_KEY` |
| `vla` | a VLA client, see [Run agents and VLAs](run-agents.md#vlas) | none: `--model` names a preset | `ROBOUSE_VLA_URL` |
| `molmoact2` | the MolmoAct2 client | `allenai/MolmoAct2-LIBERO-LeRobot` | `ROBOUSE_MOLMOACT2_URL` |

The three Baseten harnesses take any Baseten model through `--model`, such as `moonshotai/Kimi-K3`.

Each harness gets its prompt (one paragraph on how to use `robo`, then the task's instruction) and a wall-clock limit: the task's `agent.timeout_sec` (900 s if unset), or `--timeout`. On timeout the process group is killed. Claude Code runs with its own configuration folder, `~/.cache/robouse/claude-home`, so your settings, `CLAUDE.md`, MCP servers and plugins are not loaded; it runs at most 400 turns, with `WebFetch`, `WebSearch` and `Task` disabled. Codex runs with its own `CODEX_HOME` under `~/.cache/robouse/`, at medium reasoning effort.

A missing credential stops the trial before it starts, with an exception in `result.json`. An API error during the trial is not an exception: the harness exits and the episode scores 0.

## The trial folder

`robouse run --out runs/try` writes one folder per trial, `runs/try/<task>__<harness>__<id>/`:

| Path | Contents |
|---|---|
| `config.json` | task, harness, model, seed, timeout, sandbox, and provenance (Robo Use version, Python, simulator package versions) |
| `result.json` | reward, episode outcome, timing, cost, any runner exception |
| `agent/stdout.jsonl`, `agent/stderr.txt` | the harness's raw output |
| `agent/trajectory.json` | the agent's steps in ATIF v1.7, the trajectory format BenchFlow reads |
| `episode/result.json` | the episode server's verdict (`success`, `outcome`, `steps_used`, the seed) and the episode [metrics](metrics.md) |
| `episode/trace.jsonl` | every `robo` request and response, with times |
| `episode/physics.jsonl` | the end-effector position, time and largest contact force at every control step |
| `verifier/reward.txt` | `1` or `0` |
| `artifacts/recording.mp4` | the video |
| `artifacts/observations/` | camera images from the workspace |
