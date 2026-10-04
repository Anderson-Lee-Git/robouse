# robouse

**Robo Use: agent as a policy for embodied agents.** Robo Use turns robot benchmarks into tasks that an agent harness, such as Claude Code or Codex, solves by driving a simulated robot from its shell, one `robo` command at a time. A trusted episode server runs the simulator, enforces the step budget, records a video and scores the final physical state.

```sh
pip install 'robouse[sim]'
```

The package contains 692 tasks in 31 suites, from rule puzzles on a table to Meta-World, LIBERO, RoboCasa, quadrupeds, humanoids and drones, and harnesses for Claude Code, Codex, mini-swe-agent, dimcode, Show-Harness and served VLA policies. It needs Python 3.11 to 3.13.

- First run: [robouse.ai/docs/quickstart](https://robouse.ai/docs/quickstart/)
- Documentation: [robouse.ai/docs](https://robouse.ai/docs/)
- Datasets, tasks and results: [robouse.ai/hub](https://robouse.ai/hub/)
