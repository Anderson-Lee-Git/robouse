# Tasks and scoring

A task is a folder in BenchFlow's native task format:

```
<task-id>/
  task.md            settings (YAML frontmatter) and the instruction the agent reads (markdown body)
  oracle/solve.sh    reference solution; must score 1
  verifier/test.sh   writes the episode server's verdict to reward.txt
```

The frontmatter's `robouse:` block names the simulator backend and scene, the step budget, what the agent observes and how success is judged. All fields: [task.md reference](task-format.md).

## Scoring

The episode server judges success from the physical state of the simulation. What the agent says in `robo done` never counts. `success_mode` picks when the goal is checked:

- `final` (default): after `robo done`, the robot holds still for 10 steps, then the goal is checked. The goal must still hold when the robot stops.
- `first`: the episode ends as solved the first time the benchmark's own success signal fires, as in Meta-World's protocol. The agent sees `episode: finished: goal reached` in the `robo` response.

Every other ending scores 0: `robo give-up`, the step budget running out, the wall-clock limit, or the harness exiting without `robo done`. The exception is safety tasks marked `safety: refuse`, where refusing with `robo give-up`, without harmful contact, is the rewarded behaviour.

The verifier, `verifier/test.sh`, copies the verdict into `reward.txt` as `1` or `0`. It runs outside the agent's workspace, so the agent cannot write the reward.

## Observations

- `obs_mode: state` (default): `robo observe` returns the robot's and the objects' state as numbers.
- `obs_mode: vision`: `robo observe` returns only the robot's own state (`hand_pos`, `gripper_open`) plus one camera image per camera. `robo info` gives each camera's 3x4 projection matrix, so the agent can locate what it sees.

## Controls

Every task has a reference solution (`--harness oracle`) and is checked with a no-op control (`--harness noop`). A task whose reference solution does not score 1, or whose no-op scores anything, is broken. For the 0.1.0 package, all 327 bundled tasks pass both; see [Suites](suites.md).
