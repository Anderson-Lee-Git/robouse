# Run a suite or dataset

`robouse run-many` runs one harness on many tasks from the package, on your machine. BenchFlow's `bench eval run -d` runs a published dataset in Docker.

## A suite

A suite is a subfolder of `robouse tasks --path`. This runs the first 4 Meta-World reference solutions, 4 at a time:

```console
$ robouse run-many --tasks "$(robouse tasks --path)/metaworld" --harness oracle --out runs/mw-oracle --concurrency 4 --limit 4
metaworld-basketball                     reward=1 outcome=success_reached steps=91 7.6s
metaworld-assembly                       reward=1 outcome=success_reached steps=93 7.7s
metaworld-bin-picking                    reward=1 outcome=success_reached steps=131 7.8s
metaworld-box-close                      reward=1 outcome=success_reached steps=105 7.9s
oracle/-: 4/4 solved
```

Without `--tasks`, `run-many` runs every task in the package. Each finished trial is appended to `runs/mw-oracle/run_log.jsonl`. After an interruption, run the same command with `--resume`: tasks that already have a finished trial are skipped.

A trial that ended in an infrastructure failure (the simulator or the harness failed, for example on an API error, or the run was interrupted) has an `EXC` note on its line and is not scored; `--retries N` reruns it up to N times, `--resume` reruns it, and `run-many` exits 1 if any trial ends that way.

## Pick tasks and repeats

```sh
robouse run-many --harness oracle --out runs/x \
  --include 'libero-*' --exclude '*-drawer*' --sample 20 --sample-seed 1 \
  --seeds 0-4 --split interpolation --dry-run
```

- `--include`, `--exclude`: globs on task ids (repeatable). `--task-list FILE`: one task id per line. `--tasks DIR`: any folder of task folders.
- `--sample N --sample-seed S`: a seeded random sample. `--limit N`: the first N.
- `--seeds 0-4`: one trial per seed, which gives pass@k in reports. `--epochs N`: repeat each task and seed N times.
- `--split nominal|interpolation|extrapolation`: seeded object placements for the tabletop pick-and-place tasks ([Metrics](metrics.md#splits)).
- `--dry-run`: print the trial plan and exit.

Compare jobs with `robouse report` ([Metrics](metrics.md#reports)).

## A dataset

A dataset is a named, versioned set of tasks on the [hub](/hub/), for example `farama-foundation/metaworld@0.1`. A registry file pins each version to one commit of the hub repository and a digest of every task. `bench` checks the digests, then runs each task in two Docker containers: the agent with only the `robo` client, and the simulator with no network, which also runs the verifier.

```console
$ bench eval run -d farama-foundation/metaworld@0.1 --registry https://robouse.ai/hub/registry.json --agent oracle --include metaworld-reach --include metaworld-drawer-open
✓ farama-foundation/metaworld@0.1: 50 tasks, digests verified (9e672aa1e7f0)
...
[PASS] metaworld-reach (reward=1.00, tools=0)
[PASS] metaworld-drawer-open (reward=1.00, tools=0)
Job complete: 2/2 (100.0%), mean_reward=1.00, errors=0, idle_timeouts=0, time=2.0min
```

- This needs Docker with Compose 2.24.4 or newer, and read access to the hub repository, `benchflow-ai/robohub`, which is private for now (for example after `gh auth login`).
- On a Mac with Colima, run `bench` from a folder under your home folder: Docker can only mount paths there.
- The first run of a dataset builds its simulator image, up to about 4 GB for LIBERO. Scenes render on the CPU inside the container, so some tasks are much slower than locally.
- `--agent oracle` runs the reference solutions. `benchflow/robouse-noop-control@0.1` is the no-op control for `benchflow/robouse-core@0.1`: with `--agent oracle`, every task must score 0.
