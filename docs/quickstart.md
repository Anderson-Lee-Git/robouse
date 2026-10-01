# Quickstart

Install Robo Use and let an agent drive a simulated robot through one task.

## Install

Python 3.12 or 3.13 (the model gateway this example uses needs 3.12 or newer):

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install 'robouse[sim,llm]'
```

On Linux without a display, MuJoCo needs an offscreen renderer. Install OSMesa; Robo Use selects it when `MUJOCO_GL` is unset:

```sh
sudo apt-get update && sudo apt-get install -y libosmesa6
```

Without one, a trial stops with a message that says what to install.

This example runs Claude Code with Kimi K3, served by Baseten. You need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on your `PATH` and a Baseten API key:

```sh
export BASETEN_API_KEY=...
```

Other harnesses and models: [Concepts](concepts.md#harnesses).

## Pick a task

```console
$ robouse tasks | grep '^arc-g'
arc-gravity tabletop
arc-gravity-vision tabletop
```

In `arc-gravity` the agent sees example grids of blocks before and after, works out the rule (blocks fall toward the front, like gravity), and then moves the real blocks with a gripper.

## Run the agent

```console
$ robouse run --task arc-gravity --harness claude-code --model baseten/moonshotai/Kimi-K3 --out runs/quickstart
{
  "trial": "arc-gravity__claude-code__88bacc",
  "reward": 1.0,
  "outcome": "done",
  "steps": 600,
  "wall_s": 60.9,
  "exception": null
}
```

The agent observed the scene, moved the blocks with `robo move-to` and called `robo done`; the episode server then checked where the blocks were. The trial made 31 `robo` calls and cost about $1.27 at Baseten's list price, through the trial's model gateway.

## Look at the result

```console
$ cd runs/quickstart/arc-gravity__claude-code__88bacc
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
  "steps_used": 600,
  "max_steps": 1400,
  "requests": 31,
  "agent_text": "Applied gravity rule: every block fell to the lowest free cell in its column (blue [2,0], green [2,2], red [1,2] stacked above green, yellow [2,3])",
  ...
}
```

- `artifacts/recording.mp4`: the video.
- `agent/trajectory.json`: what the agent said and ran. This one started with `robo info`, `robo observe`, then `robo move-to -0.12 0.08 0.12 --grip -1`.
- `episode/trace.jsonl`: every `robo` request and its response.

Every file in the folder: [Concepts](concepts.md#the-trial-folder).
