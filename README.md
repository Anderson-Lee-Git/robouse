# robouse

**robo-use: agent as a policy for embodied agents.** robo-use turns robot benchmarks into tasks that an agent harness, such as Claude Code or Codex, solves by driving a simulated robot from its shell, one `robo` command at a time. A trusted episode server runs the simulator, enforces the step budget, records a video and scores the final physical state.

```sh
pip install 'robouse[sim]>=0.1' 'mujoco==3.3.0'
robouse run --task arc-gravity --harness oracle --out runs/try
```

Keep the `>=0.1`: older 0.0.x versions on PyPI are empty placeholders, and pip falls back to them when an extra cannot be installed. Pin MuJoCo 3.3.0: robouse 0.1.0 does not, and newer MuJoCo releases break several suites.

Docs: [robouse.ai/docs](https://robouse.ai/docs/). Results and videos: [robouse.ai/runs](https://robouse.ai/runs/).

## Working on robo-use

Install a checkout in editable mode; it then uses the checkout's `tasks/` and `assets/`:

```sh
git clone https://github.com/benchflow-ai/robouse.git && cd robouse
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[metaworld,gymrobotics]"
```

The public docs are built from `docs/` by `scripts/build_docs.py`; the pages it publishes are listed in its `PAGES`. `docs/dogfood.md` records the commands run to check them. The other files in `docs/` are internal notes.
