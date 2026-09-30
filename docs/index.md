# Robo Use

Robo Use turns robot benchmarks into tasks that an agent harness, such as Claude Code or Codex, solves by driving a simulated robot from its shell. The agent acts only through the `robo` command. A trusted episode server runs the simulator, enforces the step budget, records a video and scores the final physical state.

```sh
pip install 'robouse[sim]'
robouse run --task arc-gravity --harness claude-code --model claude-sonnet-5 --out runs/quickstart
```

- **392 tasks** in 20 suites ship with the package, adapted from Meta-World, Gymnasium-Robotics, LIBERO, robosuite, DexJoCo, MetaDrive and MuJoCo Menagerie, plus Robo Use's own tabletop, vision, hard, safety and drone suites, and embodiment suites for quadrupeds, humanoids, mobile manipulators, dexterous hands, Crazyflie swarms and cars.
- **The policy is an agent harness.** Claude Code, Codex and mini-swe-agent are built in; any agent that can run shell commands can drive the robot.
- **Every task ships a reference solution** that scores 1, and doing nothing scores 0.
- **Every trial is a folder** with the video, the agent's trajectory and the reward, in BenchFlow's trial layout.

![One trial. The agent harness runs `robo` in its own workspace; each call is one JSON request over a Unix socket to the episode server, which owns the simulator, enforces the budgets, records the episode and judges success. The trial folder collects the agent's output, the episode record and the reward.](img/architecture.svg)

## Robo Use and BenchFlow

[BenchFlow](https://benchflow.ai) is an open environment framework: it runs AI agents against task environments and scores them through one contract, treating a benchmark as a frozen environment. Robo Use is built on its formats:

- tasks are BenchFlow-native `task.md` folders (schema 1.3), with Robo Use's settings in a `robouse:` block;
- each trial is written in BenchFlow's trial layout, with the agent's steps as an ATIF trajectory (`agent/trajectory.json`), so BenchFlow's tools can read it;
- tasks can be exported to run under BenchFlow's `bench eval run`, with the agent and the simulator in separate containers ([Run a suite](run-a-suite.md#run-under-benchflow); needs a checkout).

`robouse run` in the released package (0.1.1) is Robo Use's own local runner: it does not start BenchFlow. Running Robo Use tasks directly on BenchFlow's engine is coming in a later release.

## Start here

- [Quickstart](quickstart.md): install, and let Claude Code drive the robot through one task.
- [Supported](supported.md): which models, harnesses, simulators and outputs are tested.
- [Tasks and scoring](tasks.md), [Episodes and robo](episodes.md), [Harnesses](harnesses.md): how it works.
- [Results](/runs/): every trial of the v1 runs, with videos.
