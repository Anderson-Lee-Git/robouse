# robouse

**Robo Use: agent as a policy for embodied agents.** Robo Use turns robot benchmarks into tasks that an agent harness, such as Claude Code or Codex, solves by driving a simulated robot from its shell, one `robo` command at a time. A trusted episode server runs the simulator, enforces the step budget, records a video and scores the final physical state.

```sh
pip install 'robouse[sim]'
robouse run --task arc-gravity --harness claude-code-glm --model moonshotai/Kimi-K3 --out runs/quickstart
```

Python 3.11 to 3.13. Extras add simulators: `metaworld`, `gymrobotics`, `robosuite`, `dexjoco`, `all`.

Docs: [robouse.ai/docs](https://robouse.ai/docs/). Results: [robouse.ai/runs](https://robouse.ai/runs/).

## Working on Robo Use

An editable install uses the checkout's `tasks/` and `assets/`:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[metaworld,gymrobotics]"
```

The public docs are built from `docs/` by `tools/docs/build_docs.py`, which publishes the pages in its `PAGES`; the other files in `docs/` are maintainers' notes. `tools/docs/cli_reference.py` and `tools/docs/suites_reference.py` regenerate the CLI page and the suites table from an installed release.
