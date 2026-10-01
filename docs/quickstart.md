# Quickstart

Install Robo Use and let an agent drive a simulated robot through one task.

## Install

Python 3.11 to 3.13:

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install 'robouse[sim]'
```

On Linux without a display, MuJoCo renders offscreen with OSMesa or EGL, and Robo Use picks whichever works (`MUJOCO_GL`, if set, overrides the choice). `robouse doctor` says whether it can render:

```console
$ robouse doctor
Offscreen rendering
  ok MuJoCo renders offscreen (MUJOCO_GL=osmesa, chosen because it was unset)
...
```

If it says MuJoCo cannot render offscreen, install OSMesa (or EGL, `libegl1 libgl1`) and run `robouse doctor` again:

```sh
sudo apt-get update && sudo apt-get install -y libosmesa6
```

The agent here is Claude Code with its default model, `claude-sonnet-5`. You need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on your `PATH` and a token from `claude setup-token` (with a Claude subscription) or an Anthropic API key in `ANTHROPIC_API_KEY`:

```sh
export CLAUDE_CODE_OAUTH_TOKEN=...
```

Another model or provider: [Run agents and VLAs](run-agents.md#model-harnesses).

## Pick a task

```console
$ robouse tasks | grep '^arc-g'
arc-gravity tabletop
arc-gravity-vision tabletop
```

In `arc-gravity` the agent sees example grids of blocks before and after, works out the rule (blocks fall toward the front, like gravity), and then moves the real blocks with a gripper.

## Run the agent

```console
$ robouse run --task arc-gravity --harness claude-code --out runs/quickstart
{
  "trial": "arc-gravity__claude-code__d10e94",
  "reward": 1.0,
  "outcome": "done",
  "steps": 731,
  "wall_s": 98.9,
  "exception": null
}
```

The agent observed the scene, moved the blocks with `robo move-to` and called `robo done`; the episode server then checked where the blocks were. The trial made 35 `robo` calls.

## Look at the result

The trial's folder is `runs/quickstart/` plus the `trial` name the run printed:

```console
$ cd runs/quickstart/arc-gravity__claude-code__*/
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
  "steps_used": 731,
  "max_steps": 1400,
  "requests": 35,
  "agent_text": "Applied gravity rule: blocks fall to the bottom ...",
  ...
}
```

- `artifacts/recording.mp4`: the video.
- `agent/trajectory.json`: what the agent said and ran. This one started with `robo info`, `robo observe`, then `robo move-to 0.04 0.0 0.15 --grip -1`.
- `episode/trace.jsonl`: every `robo` request and its response.

Every file in the folder: [Concepts](concepts.md#the-trial-folder).
