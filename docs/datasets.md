# Datasets

A dataset is a named, versioned set of Robo Use tasks that BenchFlow's `bench` runs by name, for example `benchflow/robouse-core@0.1`. The tasks are exported as native BenchFlow task packages into a hub repository, and a registry file pins each version to one commit of that repository together with a content digest of every task. A published version is not changed: a new export gets a new version.

The hub is [robouse.ai/hub](/hub/). It lists every dataset with its task count, robots and simulators, and the command to run it.

## Names

A dataset name is `<org>/<name>`, where the org is whoever designed the benchmark's tasks. Benchmarks adapted from other groups sit under that group's GitHub organisation; these are BenchFlow's adaptations, not published or reviewed by the original authors. Tasks BenchFlow designed stay under `benchflow/`, even when they run on someone else's simulator or robot models.

| Dataset | Tasks | Original benchmark |
|---|---|---|
| `benchflow/robouse-core@0.1` | 100 | a sample of all Robo Use suites |
| `farama-foundation/metaworld@0.1` | 50 | Meta-World MT50 (Farama Foundation, MIT) |
| `farama-foundation/gymnasium-robotics@0.1` | 12 | Gymnasium-Robotics (Farama Foundation, MIT) |
| `benchflow/robouse-tabletop@0.1` | 119 | Robo Use's own tabletop scenes |
| `lifelong-robot-learning/libero@0.1` | 20 | LIBERO (Lifelong Robot Learning, MIT) |
| `arise-initiative/robosuite@0.1` | 21 | robosuite (ARISE Initiative, MIT) |
| `benchflow/robouse-menagerie@0.1` | 15 | Robo Use tasks on MuJoCo Menagerie robots |
| `brave-eai/dexjoco@0.1` | 14 | DexJoCo (brave-eai, MIT) |
| `benchflow/robouse-drone@0.1` | 10 | Robo Use drone tasks |
| `benchflow/robouse-roboharm@0.1` | 80 | Robo Use harm scenarios |
| `benchflow/robouse-noop-control@0.1` | 100 | negative control for `benchflow/robouse-core` |

The earlier plain names (`robouse-core@0.1`, `robouse-metaworld@0.1` and so on) still resolve: each is an alias in the registry with exactly the same pinned tasks and digests.

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

- `--include TASK` (repeatable) runs a subset:

```console
$ bench eval run -d farama-foundation/metaworld@0.1 --registry https://robouse.ai/hub/registry.json --agent oracle --include metaworld-reach --include metaworld-drawer-open
✓ farama-foundation/metaworld@0.1: 50 tasks, digests verified (9e672aa1e7f0)
...
[PASS] metaworld-reach (reward=1.00, tools=0)
[PASS] metaworld-drawer-open (reward=1.00, tools=0)
Job complete: 2/2 (100.0%), mean_reward=1.00, errors=0, idle_timeouts=0, time=1.0min
```

- `--agent oracle` runs each task's reference solution. Other BenchFlow agents take `--agent NAME --model ID`; no model-driven run on the hub has been checked yet.
- `--registry` takes a URL or a file. The registry is in the hub repository and mirrored at `https://robouse.ai/hub/registry.json`, which `bench` can read without a token (the no-op run below used it). The hub repository, `benchflow-ai/robohub`, is private for now, so the machine running `bench` needs read access to it (for example after `gh auth login`).
- Run `bench` from a folder under your home folder: on a Mac with Colima, Docker can only mount paths there.

`benchflow/robouse-noop-control@0.1` is a negative control: the same tasks as `benchflow/robouse-core`, but each reference solution only looks at the robot and exits. Run with `--agent oracle`, every task must score 0.

## What was checked

With the released `bench` 0.7.4 and Docker in Colima (6 CPUs, 12 GiB) on an M2 Max, on 2026-09-28:

| Run | Result |
|---|---|
| `robouse-core@0.1`, reference solutions, all 100 tasks (the run above) | 100/100, 97.8 min at 4 at a time |
| `robouse-noop-control@0.1`, 10 tasks across all five simulator images, registry from the robouse.ai URL | 0/10; every episode was closed by the verifier with 0 steps |
| `farama-foundation/metaworld@0.1` and `arise-initiative/robosuite@0.1`, reference solutions, 2 tasks each, registry from the robouse.ai URL | 2/2 and 2/2 |
| The same 4 tasks under the old names `robouse-metaworld@0.1` and `robouse-robosuite@0.1` | 2/2 and 2/2 |

The first two runs used the names from before the rename, which are now aliases of `benchflow/robouse-core@0.1` and `benchflow/robouse-noop-control@0.1`.

A model-driven run has not been done yet: `bench` 0.7.4's pinned Codex adapter rejects `gpt-6-astra`, and the Claude Code attempt hit an account usage limit.

The simulator images are built from the hub repository the first time a dataset needs them (the largest, for LIBERO, is about 4 GB), so the first run takes longer. Scenes render on the CPU inside the container, so some tasks are much slower than a local `robouse run`: a DexJoCo reference solution took about 8 minutes.
