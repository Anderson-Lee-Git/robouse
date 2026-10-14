# Run agents and VLAs

`robouse run` runs one harness on one task and writes one trial folder. Harnesses and what each needs: [Concepts](concepts.md#harnesses).

## Model harnesses

A Baseten model goes through the trial's model gateway, which needs Python 3.12 or newer and the `llm` extra:

```sh
pip install 'robouse[sim,llm]'
export BASETEN_API_KEY=...
robouse run --task arc-gravity --harness claude-code --model baseten/moonshotai/Kimi-K3 --out runs/try
```

A non-null `exception` in the printed summary means the trial did not run to a result (a missing credential, a harness not on `PATH`, a harness that stopped on an API error before ending the episode, or Ctrl-C); that trial is not scored, and `robouse run` exits 1. Tasks on other simulators need their extra, for example `pip install 'robouse[metaworld]'` for `metaworld-*` ([Suites](suites.md)).

Options:

- `--timeout 600`: the agent's wall-clock limit in seconds, instead of the task's.
- `--seed 3`: another object and goal layout, where the backend supports it.
- `--extra-instruction TEXT`: text appended to the instruction.
- `--prior-learnings FILE`: markdown appended to the instruction, for example from `robouse summarize TRIAL`.

## Show-Harness

`show-harness` runs NUS Show Lab's [Show-Harness](https://showlab.github.io/Show-Harness/): the model looks at the task's camera images and picks one parameter-free action unit per call (a move in one of six directions, `GRASP`, `RELEASE` or `DONE`), and an interpreter turns each unit into closed-loop hand motion, every control step counting against the step budget. A provider-prefixed model runs Show-Harness's zero-shot loop; a model you serve at `ROBOUSE_SHOW_HARNESS_URL`, such as one of its fine-tuned adapters on vLLM, runs the fine-tuned loop. It runs only tasks on the `tabletop`, `libero` and `cubepick` backends, and stops before moving any other robot. It sees the images, the hand's height and the gripper's width, not object coordinates, and it does not turn the hand. It has no unit for refusing, so it cannot pass the four `safety: refuse` tasks on these robots. On LIBERO a unit takes 8 to 12 control steps, so the step budgets there (280 to 520 steps) are tight for it.

```console
$ robouse run --task cubepick-reach-layout-0 --harness show-harness --model baseten/zai-org/GLM-5.3-Flash --out runs/show
{
  "trial": "cubepick-reach-layout-0__show-harness__4f8c19",
  "reward": 1.0,
  "outcome": "success_reached",
  "steps": 33,
  "wall_s": 54.6,
  "exception": null
}
```

## Isolation

Model harnesses run in a sandbox, so the agent cannot read the reference solution, the run folder or other trials. Its environment carries no model provider key and no other variable whose name marks a credential (a token, key, secret, password or login, such as `GITHUB_TOKEN`, `HF_TOKEN`, `AWS_SECRET_ACCESS_KEY` or `SSH_AUTH_SOCK`); a harness adds back only what its program needs, such as its own vendor's login. Nor can it read or write credential and task-copy locations in your home folder: other programs' logins (such as `~/.ssh`, `~/.aws`, `~/.config/gcloud`, `~/.config/gh`, `~/.netrc` and `~/.docker`), your own Claude Code, Codex and mini-swe-agent settings (`~/.claude`, `~/.claude.json`, `~/.codex`, mini-swe-agent's global `.env`), BenchFlow's settings and task cache (`~/.config/benchflow`, `~/.cache/benchflow`), package caches that hold copies of the tasks with their reference solutions (`~/.cache/uv`, pip's cache), and Robo Use's own cache (`~/.cache/robouse`: simulator environments and other trials' harness folders). The full list is `HOME_DENIED` in [`src/robouse/runner/sandbox.py`](../src/robouse/runner/sandbox.py). The agent keeps its own harness folder, and Codex's own install in `~/.codex/packages` stays readable so Codex can run. When Robo Use runs from a source checkout, the checkout's `tasks/`, `runs/` and `adapters/` folders are out of reach too. The agent can read but not change the Python that Robo Use runs on (the episode server and the verifier run on it), and it cannot connect to the Docker, Podman or LXD socket, to your SSH agent or to other trials' episode sockets. On macOS it cannot start `open`, `osascript`, `shortcuts` or `security`, which act outside the sandbox (`security` reads the login keychain, where Claude Code and the GitHub CLI keep their logins). The reference solution and the no-op control run without the sandbox.

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
