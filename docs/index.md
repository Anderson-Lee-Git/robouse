# robo-use

robo-use turns robot benchmarks into tasks that an agent harness, such as Claude Code or Codex, solves by driving a simulated robot from its shell. The agent acts only through the `robo` command. A trusted episode server runs the simulator, enforces the step budget, records a video and scores the final physical state.

```sh
pip install 'robouse[sim]'
robouse run --task arc-gravity --harness claude-code --model claude-sonnet-5 --out runs/quickstart
```

- **341 tasks** in 14 suites ship with the package, adapted from Meta-World, Gymnasium-Robotics, LIBERO, robosuite, DexJoCo and MuJoCo Menagerie, plus robo-use's own tabletop, vision, hard, safety and drone suites.
- **The policy is an agent harness.** Claude Code, Codex and mini-swe-agent are built in; any agent that can run shell commands can drive the robot.
- **Every task ships a reference solution** that scores 1, and doing nothing scores 0.
- **Every trial is a folder** with the video, the agent's trajectory and the reward, in BenchFlow's trial layout.

## Start here

- [Quickstart](quickstart.md): install, and let Claude Code drive the robot through one task.
- [Supported](supported.md): which models, harnesses, simulators and outputs are tested.
- [Tasks and scoring](tasks.md), [Episodes and robo](episodes.md), [Harnesses](harnesses.md): how it works.
- [Results](/runs/): every trial of the v1 runs, with videos.
