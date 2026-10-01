# Overview

Robo Use turns robot benchmarks into tasks that an agent harness, such as Claude Code or Codex, solves by driving a simulated robot from its shell with the `robo` command. An episode server runs the simulator, enforces the step budget, records a video and scores the final physical state.

```sh
pip install 'robouse[sim,llm]'
export BASETEN_API_KEY=...
robouse run --task arc-gravity --harness claude-code --model baseten/moonshotai/Kimi-K3 --out runs/quickstart
```

![One trial: the harness sends `robo` requests over a Unix socket to the episode server, which owns the simulator; the trial folder collects the agent's output, the episode record and the reward.](img/architecture.svg)

Every task is a BenchFlow task folder (`task.md`) with a reference solution and a no-op control ([Suites](suites.md) lists their scores). Every trial is a folder in BenchFlow's trial layout: video, trajectory and reward. Published datasets of these tasks run with BenchFlow's `bench eval run -d`.

Tasks come from Meta-World, LIBERO, robosuite, Gymnasium-Robotics, dm_control, MyoSuite, HumanoidBench, ManiSkill3, RoboCasa, DexJoCo, MetaDrive, Robocurve's Inspect Robots and MuJoCo Menagerie robots, plus Robo Use's own suites. Results: [Runs](/runs/).
