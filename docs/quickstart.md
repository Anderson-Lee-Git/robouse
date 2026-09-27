# Quickstart

Install robo-use, list the tasks and run a reference solution. No model or API key is needed.

## Install

Python 3.11 to 3.13. Install the package with the `sim` extra (MuJoCo and video recording) and, for Meta-World tasks, the `metaworld` extra:

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install 'robouse[sim,metaworld]>=0.1' 'mujoco==3.3.0'
```

Keep both pins:

- `>=0.1`: without it, an extra that cannot be installed makes pip fall back to an empty 0.0.x placeholder instead of failing.
- `mujoco==3.3.0`: robouse 0.1.0 does not pin MuJoCo, and with newer releases some suites crash or their reference solutions fail. 3.3.0 is the version Meta-World requires and the one every suite was checked with.

Other extras are listed under [Supported](supported.md#simulators).

```console
$ robouse --version
robouse 0.1.0
```

## List tasks

```console
$ robouse tasks | head -3
arc-colour-to-pad tabletop
arc-count-marker tabletop
arc-fill-missing tabletop
$ robouse tasks | wc -l
327
```

Each line is a task id, its backend and its simulator env id. The task folders ship inside the package; `robouse tasks --path` prints where.

## Run a reference solution

Every task ships a reference solution, run by the `oracle` harness. It must score 1:

```console
$ robouse run --task metaworld-reach --harness oracle --out runs/try
{
  "trial": "metaworld-reach__oracle__ae2f3a",
  "reward": 1.0,
  "outcome": "success_reached",
  "steps": 51,
  "wall_s": 14.1,
  "exception": null
}
```

The `noop` harness ends the episode without moving the robot. It must score 0:

```console
$ robouse run --task metaworld-reach --harness noop --out runs/try
{
  "trial": "metaworld-reach__noop__3660b9",
  "reward": 0.0,
  "outcome": "done",
  "steps": 0,
  "wall_s": 7.2,
  "exception": null
}
```

## Look at the trial

```console
$ ls runs/try/metaworld-reach__oracle__ae2f3a
agent  artifacts  config.json  episode  result.json  verifier
$ cat runs/try/metaworld-reach__oracle__ae2f3a/verifier/reward.txt
1
```

The video of the episode is `artifacts/recording.mp4`.

What each file holds: [Episodes and robo](episodes.md#the-trial-folder).

## Next

- [Run an agent](run-an-agent.md): let Claude Code or Codex be the policy.
- [Run a suite](run-a-suite.md): many tasks in parallel.
- [Write a task](write-a-task.md): your own scene and goal.
