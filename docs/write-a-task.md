# Write a task

Make a task by copying one from the package, changing its goal and writing its reference solution. This example turns "put the red block in the bowl" into "put the blue block in the bowl". Tabletop tasks describe their whole scene in `task.md`, so no code is needed.

## Copy a task

```sh
mkdir -p mytasks
cp -r "$(robouse tasks --path)/libero-style/libero-red-block-in-bowl" mytasks/blue-block-in-bowl
```

## Change the goal

In `mytasks/blue-block-in-bowl/task.md`, change the ids, the goal and the instruction:

```yaml
task:
  name: my/blue-block-in-bowl
  description: Put the blue block in the bowl
...
robouse:
  id: blue-block-in-bowl
  ...
  scenario:
    id: blue-block-in-bowl
    title: Put the blue block in the bowl
    goal: Pick up the blue block and place it in the white bowl.
    ...
    goals:
    - type: in
      obj: blue_block
      container: bowl
```

Replace "red block" with "blue block" in the markdown body too: the body is what the agent reads. The objects are listed under `scenario.objects`: the blue block is at x = 0.10, y = -0.12 and the bowl at x = 0.12, y = 0.10.

## Check the old solution fails

The copied reference solution still moves the red block, so it must now score 0:

```console
$ robouse run --task mytasks/blue-block-in-bowl --harness oracle --out runs/mine
{
  "trial": "blue-block-in-bowl__oracle__4528f5",
  "reward": 0.0,
  "outcome": "done",
  ...
```

## Write the reference solution

`oracle/solve.sh` runs with `robo` on its `PATH`, like an agent. Replace it with:

```sh
#!/bin/bash
# Reference solution: pick the blue block and drop it in the bowl, using only robo.
set -euo pipefail
robo move-to 0.10 -0.12 0.10 --grip -1   # above the blue block, fingers open
robo move-to 0.10 -0.12 0.02             # down around it
robo grip 1 --steps 20                   # close
robo move-to 0.10 -0.12 0.15 --grip 1    # lift
robo move-to 0.12 0.10 0.15 --grip 1     # over the bowl
robo move-to 0.12 0.10 0.06 --grip 1     # lower
robo grip -1 --steps 15                  # release
robo move-to 0.12 0.10 0.15              # back off
robo done "blue block in the bowl"
```

## Check both controls

```console
$ robouse run --task mytasks/blue-block-in-bowl --harness oracle --out runs/mine
{
  "trial": "blue-block-in-bowl__oracle__41cb4c",
  "reward": 1.0,
  "outcome": "done",
  "steps": 198,
  ...
$ robouse run --task mytasks/blue-block-in-bowl --harness noop --out runs/mine
{
  "trial": "blue-block-in-bowl__noop__aa263f",
  "reward": 0.0,
  "outcome": "done",
  ...
```

The reference solution scores 1 and the no-op control scores 0, so the task is ready. Run an agent on it with `--task mytasks/blue-block-in-bowl`, or on a folder of tasks with `robouse run-many --tasks mytasks`.

## Other goals

Tabletop goal types: `in`, `on_pad`, `on_plate`, `on_top`, `on_top_level`, `stack`, `drawer`, `unmoved`, `upright`, `in_socket`, `grid`, `in_zone` and `handle_toward`. Constraints, listed under `scenario.constraints`, fail the task when broken: `no_contact`, `max_disp`, `max_down_speed`, `size_order`, `top_only`, `no_attempt` and `no_overfly`. Find a task that uses the one you need and copy it:

```sh
grep -rl "type: stack" "$(robouse tasks --path)"
```

Tasks on the other backends (Meta-World, LIBERO, robosuite, ...) load a scene from their benchmark by env id, so a new task there can only use a scene the benchmark already has.
