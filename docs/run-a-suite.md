# Run a suite

`robouse run-many` runs one harness on a set of tasks, several at a time. Like `robouse run`, it runs the trials on your machine by default (`--engine local`); `--engine benchflow` runs them as one BenchFlow job in Docker.

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

The suite folders are the subfolders of `robouse tasks --path`; [Suites](suites.md) says what each needs. Without `--tasks`, `run-many` runs all bundled tasks.

## Pick tasks

```sh
robouse run-many --filter drawer --harness oracle --out runs/drawer        # ids containing "drawer"
robouse run-many --task-list picks.txt --harness noop --out runs/picks     # one task id per line
robouse run-many --tasks mytasks --harness oracle --out runs/mine          # any folder of task folders
```

## Stop and resume

With `--engine local`, each finished trial is appended to `<out>/run_log.jsonl`. After an interruption, run the same command with `--resume`: tasks that already have a finished trial in `--out` are skipped, and the rest run.

## With an agent

```sh
robouse run-many --tasks "$(robouse tasks --path)/metaworld" --harness codex --model gpt-6-astra --out runs/mw-codex --concurrency 4
```

Each trial is one agent session, so cost and rate limits grow with `--concurrency`. A trial that failed for an infrastructure reason has an `EXC` note on its line and `exception_info` in its `result.json`; with `--engine local`, rerunning with `--resume` retries it.

## Run under BenchFlow

With `--engine benchflow`, `robouse run` and `run-many` run on BenchFlow (install `robouse[benchflow]`; Python 3.12). BenchFlow loads the task folders as they are and runs each trial in two Docker containers: the agent with only the `robo` client, and the simulator with no network. They share only the episode socket, and the verifier runs in the simulator container. The job is written to `OUT/<job>/`, one `<task>__<id>/` folder per trial. `bench eval run` runs the same task folders directly:

```sh
bench eval run --tasks-dir "$(robouse tasks --path)/metaworld" --agent oracle --sandbox docker
```

This needs Docker with Compose 2.24.4 or newer. `robouse export --tasks DIR --out DIR` writes the same tasks as BenchFlow packages, for a machine without Robo Use installed.
