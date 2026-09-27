# Run an agent

Let Claude Code or Codex be the robot's policy on one task.

The commands on this page call paid model APIs. The Claude Code command was run for these docs (the [Quickstart](quickstart.md) shows the trial); the Codex command was checked against `robouse run --help` and the harness code, and the same harness produced the [v1 runs](/runs/).

## Claude Code

Install Claude Code so that `claude` is on your `PATH`. Set an Anthropic API key, or a subscription token from `claude setup-token`:

```sh
export ANTHROPIC_API_KEY=...
# or, with a Claude subscription:
export CLAUDE_CODE_OAUTH_TOKEN=...
robouse run --task metaworld-push --harness claude-code --model claude-sonnet-5 --out runs/try
```

`metaworld-push` needs the Meta-World extra: `pip install 'robouse[metaworld]>=0.1.1'`.

## Codex

Install Codex so that `codex` is on your `PATH`. Set `OPENAI_API_KEY`, or log in once with `codex login`:

```sh
robouse run --task metaworld-push --harness codex --model gpt-6-astra --out runs/try
```

## What you get

The command prints the same summary as the reference solution in the [Quickstart](quickstart.md), and writes the trial folder. To see what the agent did:

- `agent/trajectory.json`: its messages, reasoning and commands, step by step.
- `episode/trace.jsonl`: every `robo` request it made and the response.
- `artifacts/recording.mp4`: the video.

A trial that could not start (a missing credential, a harness not on `PATH`, an episode server that did not start) has `"exception"` set in the summary and in `result.json`; it is not a score. Errors inside the harness, such as a failed API call, end the episode and score 0.

## Options

- `--timeout 600`: the agent's wall-clock limit in seconds, instead of the task's own.
- `--seed 3`: another object and goal layout, where the task's backend supports it.
- Other harnesses and what they need: [Harnesses](harnesses.md).
