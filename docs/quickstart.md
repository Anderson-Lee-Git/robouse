# Quickstart

Install Robo Use and let an agent drive a simulated robot through one task.

## Install

Python 3.11 to 3.13:

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install 'robouse[sim]'
```

This example runs Claude Code with Kimi K3, served by Baseten. You need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on your `PATH` and a Baseten API key:

```sh
export BASETEN_API_KEY=...
```

To use Claude models instead, run `--harness claude-code --model claude-sonnet-5` with `ANTHROPIC_API_KEY` set. Other harnesses: [Concepts](concepts.md#harnesses).

## Pick a task

```console
$ robouse tasks | grep '^arc-g'
arc-gravity tabletop
arc-gravity-vision tabletop
```

`robouse tasks` lists every task in the package with its simulator backend. In `arc-gravity` the agent sees example grids of blocks before and after, works out the rule (blocks fall toward the front, like gravity), and then moves the real blocks with a gripper.

## Run the agent

```console
$ robouse run --task arc-gravity --harness claude-code-glm --model moonshotai/Kimi-K3 --out runs/quickstart
{
  "trial": "arc-gravity__claude-code-glm__1a6f32",
  "reward": 1.0,
  "outcome": "done",
  "steps": 500,
  "wall_s": 77.6,
  "exception": null
}
```

The agent read the instruction, observed the scene, moved the blocks with `robo move-to` and called `robo done`. The episode server then checked where the blocks were and scored the trial 1. The trial made 26 `robo` calls and cost about $2.16 at Baseten's list price.

## Look at the result

```console
$ cd runs/quickstart/arc-gravity__claude-code-glm__1a6f32
$ cat verifier/reward.txt
1
$ cat episode/result.json
{
  "task": "arc-gravity",
  "seed": 0,
  "success": true,
  "success_mode": "final",
  "outcome": "done",
  "steps_used": 500,
  "max_steps": 1400,
  "requests": 26,
  "agent_text": "Applied gravity rule: each block falls to the front of its column, stacking from row 2 up. ...",
  ...
}
```

- `artifacts/recording.mp4`: the video.
- `agent/trajectory.json`: what the agent said and ran. This one started with `robo info`, `robo observe`, then `robo move-to -0.12 0.08 0.08`.
- `episode/trace.jsonl`: every `robo` request and its response.

Every file in the folder: [Concepts](concepts.md#the-trial-folder).
