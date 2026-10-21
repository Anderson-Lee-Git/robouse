# Run agents and VLAs

`robouse run` runs one harness on one task and writes one trial folder. Harnesses and what each needs: [Concepts](concepts.md#harnesses).

## Model harnesses

A provider-prefixed model goes through the trial's model gateway, which needs Python 3.12 or newer and the `llm` extra. `mini-swe-agent` and `dimcode` default to `glm/glm-5.3`: GLM-5.3 on the Z.ai Coding Plan, through BenchFlow's `glm` provider. It needs the plan's API key and endpoint (the one below is for a plan bought on bigmodel.cn) and, because the plan has no per-token price, the spend cap turned off, or a price for `glm-5.3` in `ROBOUSE_PRICING` ([Configuration](configuration.md)). mini-swe-agent is a separate package, installed here with Robo Use:

```sh
pip install 'robouse[sim,llm]' mini-swe-agent
export GLM_API_KEY=...
export GLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4
export ROBOUSE_SPEND_CAP_USD=0
robouse run --task arc-gravity --harness mini-swe-agent --model glm/glm-5.3 --out runs/try
```

Claude Code takes the same model with `--harness claude-code --model glm/glm-5.3`. Codex cannot use it: it needs a provider with a Responses API, which the plan does not have. The gateway sends GLM-5.3 no images (BenchFlow's registry does not list its inputs, and the plan's endpoint refuses image parts); the camera images are still files in the agent's workspace. If a setting is missing, `robouse run` names it and starts no trial. mini-swe-agent, Claude Code and dimcode have run whole trials on `glm/glm-5.3` only against a local stand-in for the plan's endpoint; with GLM-5.3 itself they were checked only up to the plan's usage-limit error, so no trial on the plan has reached a result yet ([Supported](supported.md)).

A non-null `exception` in the printed summary means the trial did not run to a result (a missing credential, a harness that is not installed, a harness that stopped on an API error before ending the episode, every request to the model failing, as when the plan is at its usage limit, or Ctrl-C); that trial is not scored, and `robouse run` exits 1. Tasks on other simulators need their extra, for example `pip install 'robouse[metaworld]'` for `metaworld-*` ([Suites](suites.md)).

Options:

- `--timeout 600`: the agent's wall-clock limit in seconds, instead of the task's.
- `--seed 3`: another object and goal layout, where the backend supports it.
- `--extra-instruction TEXT`: text appended to the instruction.
- `--prior-learnings FILE`: markdown appended to the instruction, for example from `robouse summarize TRIAL`.

## Show-Harness

`show-harness` runs NUS Show Lab's [Show-Harness](https://showlab.github.io/Show-Harness/): the model looks at the task's camera images and picks one parameter-free action unit per call (a move in one of six directions, `GRASP`, `RELEASE` or `DONE`), and an interpreter turns each unit into closed-loop hand motion, every control step counting against the step budget. `--model` is required, since the policy is the model's reading of the images: a provider-prefixed model runs Show-Harness's zero-shot loop through the model gateway if BenchFlow's provider registry lists it as reading images (`robouse run` refuses any other before the trial starts, `glm/glm-5.3` included, since the gateway would remove every camera image); a model you serve at `ROBOUSE_SHOW_HARNESS_URL`, such as one of its fine-tuned adapters on vLLM, runs the fine-tuned loop. No provider-prefixed model has been tested with it in Robo Use 0.4.1. It runs only tasks on the `tabletop`, `libero` and `cubepick` backends, and stops before moving any other robot. It sees the images, the hand's height and the gripper's width, not object coordinates, and it does not turn the hand. It has no unit for refusing, so it cannot pass the four `safety: refuse` tasks on these robots. On LIBERO a unit takes 8 to 12 control steps, so the step budgets there (280 to 520 steps) are tight for it.

## Isolation

Model harnesses run in a sandbox that hides the trial's run folder, the task folder with its reference solution, the installed package and other trials' workspaces from the agent. Its environment carries no model provider key and no other variable whose name marks a credential (a token, key, secret, password or login, such as `GITHUB_TOKEN`, `HF_TOKEN`, `AWS_SECRET_ACCESS_KEY` or `SSH_AUTH_SOCK`); a harness adds back only what its program needs, such as its own vendor's login. Nor can it read or write credential and task-copy locations in your home folder: other programs' logins (such as `~/.ssh`, `~/.aws`, `~/.config/gcloud`, `~/.config/gh`, `~/.netrc` and `~/.docker`), your own Claude Code, Codex and mini-swe-agent settings (`~/.claude`, `~/.claude.json`, `~/.codex`, mini-swe-agent's global `.env`), BenchFlow's settings and task cache (`~/.config/benchflow`, `~/.cache/benchflow`), package caches that hold copies of the tasks with their reference solutions (`~/.cache/uv`, pip's cache), and Robo Use's own cache (`~/.cache/robouse`: simulator environments and other trials' harness folders). The full list is `HOME_DENIED` in [`src/robouse/runner/sandbox.py`](../src/robouse/runner/sandbox.py). The agent keeps its own harness folder, and Codex's own install in `~/.codex/packages` stays readable so Codex can run. When Robo Use runs from a source checkout, the checkout's `tasks/`, `runs/` and `adapters/` folders are out of reach too, and so, on LIBERO tasks, are the scene files and saved start states of hf-libero in Robo Use's environment and where LIBERO's config points. The agent can read but not change the Python that Robo Use runs on (the episode server and the verifier run on it), and it cannot connect to the Docker, Podman or LXD socket, to your SSH agent or to other trials' episode sockets. On macOS it cannot start `open`, `osascript`, `shortcuts` or `security`, which act outside the sandbox (`security` reads the login keychain, where Claude Code and the GitHub CLI keep their logins). The reference solution and the no-op control run without the sandbox.

The sandbox is a deny list, not a container. It keeps an agent from stumbling on the answer, not one that looks for it:

- The agent runs as your user and can read the rest of the machine: folders outside the lists above, such as other checkouts or copies of the tasks you keep elsewhere. Add such paths to `ROBOUSE_SANDBOX_DENY`. On Linux it can also write wherever your user can, outside the denied folders.
- The network is open, and public copies of the tasks, including reference solutions and verifiers, are on the internet. On Linux, services listening on localhost are reachable too.
- Environment variables whose names do not mark a credential reach the agent, so a secret kept under another name reaches it too.
- Episode sockets have no per-trial authentication: the sandbox refuses the agent's connections to other trials' sockets, but any process of your user outside the sandbox can connect to them.

Run agents you do not trust in a disposable VM or container with no credentials of yours, and check the trial logs before you publish a score.

- **macOS**: the system's Seatbelt sandbox (`sandbox-exec`); nothing to install.
- **Linux**: bubblewrap. Install it first, for example `sudo apt-get install bubblewrap`. Ubuntu 24.04 blocks the user namespaces bubblewrap needs unless an AppArmor profile allows them; if `robouse run` stops with "no sandbox for the agent on this machine", add the profile and load it:

```sh
sudo tee /etc/apparmor.d/bwrap >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

`ROBOUSE_SANDBOX_DENY` adds paths the agent may not read or write, separated by colons, such as credential files. `ROBOUSE_SANDBOX=0` runs the agent without a sandbox; use it only on a machine you trust, since the agent can then read the reference solution.

## VLAs

The `vla` harness drives the robot with a vision-language-action model served elsewhere, usually on a GPU. Its client sends the camera images, the robot state and the instruction to the policy server, and applies the action chunk it gets back through `robo`, like any harness. `--model` names a preset, and `ROBOUSE_VLA_URL` points at the server:

```sh
export ROBOUSE_VLA_URL=ws://gpu-box:8000
robouse run --task libero-10-0 --harness vla --model openpi/pi05_libero --out runs/pi05
```

| Preset | Server |
|---|---|
| `openpi/pi05_libero`, `openpi/pi0_libero` | openpi `serve_policy.py` |
| `lerobot/groot_n1.7_libero`, `lerobot/evo1_libero`, `lerobot/vla_jepa_libero`, `lerobot/smolvla_libero`, `lerobot/pi05_libero` | `robouse/harnesses/vla/lerobot_server.py` (any LeRobot policy) |
| `openvla/openvla-7b-libero` | OpenVLA `vla-scripts/deploy.py` |
| `molmoact2/libero` | Robo Use's MolmoAct2 server |
| `gr00t/so101` | Isaac GR00T `run_gr00t_server.py` |
| `xpolicylab/metal-joint`, `xpolicylab/so101-joint` | XPolicyLab policy servers |
| `openpi/generic`, `gr00t/generic`, `xpolicylab/generic`, `http-json/generic` | templates to fill in |

A preset fixes the wire protocol, how the policy's observation is built from the task's cameras and state, how its actions map onto the task's action vector, and how action chunks are executed. Override any field with a JSON file in `ROBOUSE_VLA_POLICY_CONFIG`. Before the first action the client checks that the preset fits the task (backend, action dimension, control mode); a mismatch ends the episode at 0 steps. A VLA does not decide when it is finished: the client calls `robo done` when the step budget is nearly spent, or, if the preset sets `stop.still_steps`, once the commanded action stops changing.

## Dream-1

The `dream` harness drives the robot with Dream Labs' Dream-1, a world-action model behind Dream Labs' DreamAPI. Its client is Dream's own client library running Dream's own simulation loop: it sends the three cameras' last nine frames (0.2 s apart in simulated time, 320x176 JPEG), the joint angles and the task's instruction, and executes the 48-step joint chunk it gets back through `robo`, then asks again. The simulation waits while a request is out. Dream-1's public models drive Dream's bimanual YAM, so the harness runs the `yam` suite ([Suites](suites.md)); on any other robot it stops at 0 steps and says why.

```sh
uv venv -p 3.12 ~/.cache/robouse/dream-venv
uv pip install -p ~/.cache/robouse/dream-venv/bin/python dreamlabs-client==1.0.0
export DREAM_API_KEY=dl_live_...   # or ~/.dreamlabs/credentials, as the platform's Setup API page prints it
robouse run --task yam-apple-to-bowl --harness dream --out runs/dream
```

`robouse doctor` says whether the client and the key are in place (`ok dream`). On a clean install of robouse 0.5.0 (macOS, Apple silicon, 2026-10-20), with the `yam` suite's virtualenv set up as in [Suites](suites.md), the last command printed:

```console
$ robouse run --task yam-apple-to-bowl --harness dream --out runs/dream
{
  "trial": "yam-apple-to-bowl__dream__08978f",
  "reward": 1.0,
  "outcome": "done",
  "steps": 1199,
  "wall_s": 54.9,
  "exception": null
}
```

`--model` is `dreamlabs/dream-1-beta` (the default) or `dreamlabs/dream-1-beta-flash`, or any checkpoint your account may run, such as a fine-tune. `ROBOUSE_DREAM_PYTHON` names another Python that has the client, and `ROBOUSE_DREAM_ACTIONS` how many rows of each chunk run before the next request (default all 48). The key goes to the client's environment only; the sandbox keeps `~/.dreamlabs` from every agent. Episodes are not recorded to your Dream Labs account: the client uploads every observation it is given unless told not to, and the harness tells it not to, as Dream's own simulation example does. DreamAPI bills by the hour of use; a trial on the `yam` suite takes about a minute. On 2026-10-19, with one trial per task, `dreamlabs/dream-1-beta` solved 6 of the 9 `yam` tasks and `dreamlabs/dream-1-beta-flash` 4.
