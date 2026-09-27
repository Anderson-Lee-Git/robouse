# Run a suite

`robouse run-many` runs one harness on a set of tasks, several at a time. It is robo-use's own local runner, the same one as `robouse run`.

## A suite

A suite is a subfolder of the bundled tasks. This runs the first 4 Meta-World reference solutions, 4 at a time:

```console
$ robouse run-many --tasks "$(robouse tasks --path)/metaworld" --harness oracle --out runs/mw-oracle --concurrency 4 --limit 4
metaworld-bin-picking                    reward=1 outcome=success_reached steps=131 9.0s
metaworld-assembly                       reward=1 outcome=success_reached steps=93 9.1s
metaworld-basketball                     reward=1 outcome=success_reached steps=91 9.1s
metaworld-box-close                      reward=1 outcome=success_reached steps=105 9.2s
oracle/-: 4/4 solved
```

Suite folders: `robouse tasks --path` lists them, and [Suites](suites.md) says what each needs. Without `--tasks`, `run-many` runs all bundled tasks.

## Pick tasks

```sh
robouse run-many --filter drawer --harness oracle --out runs/drawer        # ids containing "drawer"
robouse run-many --task-list picks.txt --harness noop --out runs/picks     # one task id per line
robouse run-many --tasks mytasks --harness oracle --out runs/mine          # any folder of task folders
```

## Stop and resume

Each finished trial is appended to `<out>/run_log.jsonl`. After an interruption, run the same command with `--resume`: tasks that already have a finished trial in `--out` are skipped, and the rest run.

## With an agent

```sh
robouse run-many --tasks "$(robouse tasks --path)/metaworld" --harness codex --model gpt-6-astra --out runs/mw-codex --concurrency 4
```

Each trial is one agent session, so cost and rate limits grow with `--concurrency`. A trial that failed for an infrastructure reason has an `EXC` note on its line and `exception_info` in its `result.json`; rerunning with `--resume` retries it.

## Run under BenchFlow

`robouse run` and `run-many` do not use BenchFlow. They write BenchFlow's trial layout and ATIF trajectories, and the tasks are BenchFlow-native `task.md` folders, but the runner, the episode server and the agent all run on your machine.

To run tasks under BenchFlow's `bench eval run` instead, export them with `benchflow/export.py`. Each exported task runs in two Docker containers: the agent with only the `robo` client, and the simulator with no network. They share only the episode socket, and the verifier runs in the simulator container. The exporter is in the robo-use repository, not in the PyPI package, so this needs a checkout:

```console
$ python benchflow/export.py --tasks tasks/metaworld --filter reach,push --out dist/robouse
...
7 task(s) -> /path/to/robouse/dist/robouse
$ cd dist/robouse && bench tasks check tasks/metaworld-reach
✓ metaworld-reach — valid (structural)
$ bench eval run --config robouse-oracle.yaml
```

The export and the structural check were run for these docs. `bench eval run` needs Docker with Compose 2.24.4 or newer and was not re-run for these docs.
