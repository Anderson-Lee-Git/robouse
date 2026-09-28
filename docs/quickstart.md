# Quickstart

Install Robo Use and let Claude Code drive a simulated robot through one task.

## Install

Python 3.11 to 3.13:

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install 'robouse[sim]'
```

You also need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on your `PATH`, and one credential: an Anthropic API key, or a Claude subscription token from `claude setup-token`.

```sh
export ANTHROPIC_API_KEY=...
# or, with a Claude subscription:
export CLAUDE_CODE_OAUTH_TOKEN=...
```

## Pick a task

```console
$ robouse --version
robouse 0.1.1
$ robouse tasks | grep '^arc-g'
arc-gravity tabletop
arc-gravity-vision tabletop
```

`robouse tasks` lists all 341 bundled tasks, with their simulator backend. `arc-gravity` is a rule-inference task on a table: the agent sees example grids of blocks before and after, has to work out the rule (blocks fall toward the front, like gravity) and then move the real blocks with a gripper. It reads the task in `instruction.md` and acts only through the `robo` command.

## Run the agent

```console
$ robouse run --task arc-gravity --harness claude-code --model claude-sonnet-5 --out runs/quickstart
{
  "trial": "arc-gravity__claude-code__6268cb",
  "reward": 1.0,
  "outcome": "done",
  "steps": 739,
  "wall_s": 93.9,
  "exception": null
}
```

Claude Code worked for about a minute and a half: it read the task, observed the scene, moved the blocks with `robo move-to`, and called `robo done`. The episode server then checked where the blocks ended up and scored the trial 1. The run made 36 `robo` calls and cost about $0.64 in API usage.

## Look at the result

```console
$ cd runs/quickstart/arc-gravity__claude-code__6268cb
$ cat verifier/reward.txt
1
$ cat episode/result.json
{
  "task": "arc-gravity",
  "seed": 0,
  "success": true,
  "success_ever": true,
  "success_mode": "final",
  "outcome": "done",
  "steps_used": 739,
  "max_steps": 1400,
  "requests": 36,
  "agent_text": "Applied gravity rule: blocks fall within their column (increasing row) preserving relative order/stacking, ...",
  "wall_time_s": 84.02
}
```

- `artifacts/recording.mp4`: the video of the episode.
- `agent/trajectory.json`: what the agent said and ran, step by step. Here it started with `robo info`, `robo observe`, then `robo move-to -0.12 0.08 0.15 --grip -1`.
- `episode/trace.jsonl`: every `robo` request and the response.

What every file holds: [Episodes and robo](episodes.md#the-trial-folder). Results of many trials, with their videos, are on the [Runs](/runs/) page.

## Codex instead

With [Codex](https://github.com/openai/codex) on your `PATH`, and `OPENAI_API_KEY` set or a login from `codex login`:

```sh
robouse run --task arc-gravity --harness codex --model gpt-6-astra --out runs/quickstart
```

This command was checked against the code and `--help`, but not run for these docs.

## Next

- [Run an agent](run-an-agent.md): other tasks, harnesses and options.
- [Run a suite](run-a-suite.md): many tasks in parallel.
- [Write a task](write-a-task.md): your own scene and goal.
- [Supported](supported.md): the other suites and what they need.
