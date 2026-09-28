# Datasets

A dataset is a named, versioned set of Robo Use tasks that BenchFlow's `bench` runs by name, for example `robouse-core@0.1`. The tasks are exported as native BenchFlow task packages into a hub repository, and a registry file pins each version to one commit of that repository together with a content digest of every task. A version never changes: a new export gets a new version.

The hub is [robouse.ai/hub](/hub/). It lists every dataset with its task count, robots and simulators, and the command to run it.

## Run a dataset

```console
$ gh api repos/benchflow-ai/robohub/contents/registry.json -H 'Accept: application/vnd.github.raw' > registry.json
$ bench eval run -d robouse-core@0.1 --registry registry.json --agent oracle --concurrency 4
✓ robouse-core@0.1: 100 tasks, digests verified (9e672aa1e7f0)
...
[PASS] arc-gravity (reward=1.00, tools=0)
[PASS] metaworld-reach (reward=1.00, tools=0)
...
Job complete: 100/100 (100.0%), mean_reward=1.00, errors=0, idle_timeouts=0, time=97.8min
✓ Score: 100/100 (100.0%), mean reward 1.00, errors=0
```

`bench` reads the registry, clones the hub repository at the pinned commit, recomputes every task's digest and stops if one does not match. Then each task runs in two Docker containers: the agent with only the `robo` client, and the simulator with no network, which also runs the verifier. The reward is 1 if the episode server judged the task solved, else 0.

- `--include TASK` (repeatable) runs a subset.
- `--agent oracle` runs each task's reference solution. Any BenchFlow agent can take its place, with `--model`.
- `--registry` takes a URL or a file. The registry is in the hub repository and mirrored at `https://robouse.ai/hub/registry.json`, which `bench` can read without a token (the no-op run below used it). The hub repository, `benchflow-ai/robohub`, is private for now, so the machine running `bench` needs read access to it (for example after `gh auth login`).
- Run `bench` from a folder under your home folder: on a Mac with Colima, Docker can only mount paths there.

`robouse-noop-control@0.1` is a negative control: the same tasks as `robouse-core`, but each reference solution only looks at the robot and exits. Run with `--agent oracle`, every task must score 0.

## What was checked

With the released `bench` 0.7.4 and Docker in Colima (6 CPUs, 12 GiB) on an M2 Max, on 2026-09-28:

| Run | Result |
|---|---|
| `robouse-core@0.1`, reference solutions, all 100 tasks (the run above) | 100/100, 97.8 min at 4 at a time |
| `robouse-noop-control@0.1`, 10 tasks across all five simulator images, registry from the robouse.ai URL | 0/10; every episode was closed by the verifier with 0 steps |

A model-driven run was not possible with `bench` 0.7.4: its pinned Codex adapter does not accept `gpt-6-astra`.

The simulator images are built from the hub repository the first time a dataset needs them (the largest, for LIBERO, is about 4 GB), so the first run takes longer. Scenes render on the CPU inside the container, so some tasks are much slower than a local `robouse run`: a DexJoCo reference solution took about 8 minutes.
