# Run a suite or dataset

`robouse run-many` runs one harness on many tasks from the package, on your machine. BenchFlow's `bench eval run -d` runs a published dataset in Docker.

## A suite

A suite is a subfolder of `robouse tasks --path`. Meta-World needs its extra, `pip install 'robouse[metaworld]'` (the [Suites](suites.md) table lists the extra for each suite). This runs the first 4 Meta-World reference solutions, 4 at a time:

```console
$ robouse run-many --tasks "$(robouse tasks --path)/metaworld" --harness oracle --out runs/mw-oracle --concurrency 4 --limit 4
metaworld-assembly                       reward=1 outcome=success_reached steps=93 16.0s
metaworld-basketball                     reward=1 outcome=success_reached steps=91 16.0s
metaworld-box-close                      reward=1 outcome=success_reached steps=105 16.8s
metaworld-bin-picking                    reward=1 outcome=success_reached steps=131 17.0s
oracle/-: 4/4 solved
```

Without `--tasks`, `run-many` runs every task in the package. Each finished trial is appended to `runs/mw-oracle/run_log.jsonl`. After an interruption, run the same command with `--resume`: tasks that already have a finished trial are skipped. A run folder holds one harness and model: if it has trials of another, `--resume` names them and stops before any trial.

A trial that ended in an infrastructure failure (the simulator or the harness failed, for example on an API error, or the run was interrupted) has an `EXC` note on its line and is not scored; `--retries N` reruns it up to N times, `--resume` reruns it, and `run-many` exits 1 if any trial ends that way.

## Pick tasks and repeats

```sh
robouse run-many \
  --harness oracle \
  --out runs/x \
  --include 'libero-*' \
  --exclude '*-drawer*' \
  --sample 20 \
  --sample-seed 1 \
  --seeds 0-4 \
  --split interpolation \
  --dry-run
```

- `--include`, `--exclude`: globs on task ids (repeatable). `--task-list FILE`: one task id per line. `--tasks DIR`: any folder of task folders.
- `--sample N --sample-seed S`: a seeded random sample. `--limit N`: the first N.
- `--seeds 0-4`: one trial per seed, which gives pass@k in reports. `--epochs N`: repeat each task and seed N times.
- `--split nominal|interpolation|extrapolation`: seeded object placements for the tabletop pick-and-place tasks ([Metrics](metrics.md#splits)).
- `--dry-run`: print the trial plan and exit.

Compare runs with `robouse report` ([Metrics](metrics.md#reports)).

## A dataset

A dataset is a named, versioned set of tasks on the [hub](https://robouse.ai/hub/), for example `farama-foundation/metaworld@0.3`. A registry file pins each version to one commit of the hub repository, [github.com/benchflow-ai/robohub](https://github.com/benchflow-ai/robohub), and a digest of every task. `bench` checks the digests, then runs each task in two Docker containers: the agent with only the `robo` client, and the simulator with no network, which also runs the verifier. `bench` is BenchFlow's command; `pip install 'robouse[benchflow]'` installs it (Python 3.12 or newer).

```console
$ ROBOUSE_ORACLE_TOKEN=$(openssl rand -hex 16) \
    bench eval run \
      -d farama-foundation/metaworld@0.3 \
      --registry https://robouse.ai/hub/registry.json \
      --agent oracle \
      --include metaworld-reach \
      --include metaworld-drawer-open
✓ farama-foundation/metaworld@0.3: 50 tasks, digests verified (8fcb01516305)
...
[PASS] metaworld-reach (reward=1.00, tools=0)
[PASS] metaworld-drawer-open (reward=1.00, tools=0)
Job complete: 2/2 (100.0%), mean_reward=1.00, errors=0, idle_timeouts=0, time=1.8min
✓ Score: 2/2 (100.0%), mean reward 1.00, errors=0
```

- `--agent oracle` runs the reference solutions. `ROBOUSE_ORACLE_TOKEN` is needed only for these runs: a reference solution that reads the true state gets the token, an agent never does.
- `benchflow/robouse-noop-control` is the no-op control for `benchflow/robouse-core`: the same scenes, each reference solution only looks at the robot and exits, so with `--agent oracle` every task must score 0.
- This needs Docker with Compose 2.24.4 or newer. On a Mac with Colima, run `bench` from a folder under your home folder: Docker can only mount paths there.
- The first run of a dataset builds its simulator image, up to about 4 GB for LIBERO. Scenes render on the CPU inside the container, so some tasks are much slower than locally.
