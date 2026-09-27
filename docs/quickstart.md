# Quickstart

Install robo-use and let Claude Code drive a simulated robot through one task.

## Install

Python 3.11 to 3.13:

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install 'robouse[sim]'
```

You also need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on your `PATH`, and one credential: an Anthropic API key, or a Claude subscription token from `claude setup-token`.

```sh
export ANTHROPIC_API_KEY=...          # or: export CLAUDE_CODE_OAUTH_TOKEN=...
```

## Pick a task

```console
$ robouse tasks | head -4
arc-colour-to-pad tabletop
arc-count-marker tabletop
arc-fill-missing tabletop
arc-gravity tabletop
```

`arc-gravity` is a rule-inference task on a table: the agent sees example grids of blocks before and after, has to work out the rule (blocks fall toward the front, like gravity) and then move the real blocks with a gripper. It reads the task in `instruction.md` and acts only through the `robo` command.

## Run the agent

```console
$ robouse run --task arc-gravity --harness claude-code --model claude-sonnet-5 --out runs/quickstart
{
  "trial": "arc-gravity__claude-code__1272c0",
  "reward": 1.0,
  "outcome": "done",
  "steps": 747,
  "wall_s": 108.2,
  "exception": null
}
```

Claude Code worked for about two minutes: it read the task, observed the scene, moved the blocks with `robo move-to` and `robo grip`, and called `robo done`. The episode server then checked the final state of the blocks and scored it 1. This trial made 35 `robo` calls and cost about $0.60.

## Look at the result

The trial folder is `runs/quickstart/arc-gravity__claude-code__1272c0/`:

```console
$ cat verifier/reward.txt
1
$ head -c 400 episode/result.json
{
  "task": "arc-gravity",
  "seed": 0,
  "success": true,
  "success_ever": true,
  "success_mode": "final",
  "outcome": "done",
  "steps_used": 747,
  "max_steps": 1400,
  "requests": 35,
  "agent_text": "Applied gravity rule per-column: blocks fall to the front row, keeping relative order. ...",
```

- `artifacts/recording.mp4`: the video of the episode.
- `agent/trajectory.json`: what the agent thought and ran, step by step. Its first commands were `robo info`, `robo observe`, then `robo move-to -0.04 0.0 0.15 --grip -1`.
- `episode/trace.jsonl`: every `robo` request and the response.

What every file holds: [Episodes and robo](episodes.md#the-trial-folder).

## Codex instead

With [Codex](https://github.com/openai/codex) on your `PATH`, and `OPENAI_API_KEY` set or a login from `codex login`:

```sh
robouse run --task arc-gravity --harness codex --model gpt-6-astra --out runs/quickstart
```

## Next

- [Run an agent](run-an-agent.md): other tasks, harnesses and options.
- [Run a suite](run-a-suite.md): many tasks in parallel.
- [Write a task](write-a-task.md): your own scene and goal.
- [Supported](supported.md): the other suites and what they need.
