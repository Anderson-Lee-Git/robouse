# Run agents and VLAs

`robouse run` runs one harness on one task and writes one trial folder. Harnesses and what each needs: [Concepts](concepts.md#harnesses).

## Model harnesses

```sh
export BASETEN_API_KEY=...
robouse run --task arc-gravity --harness claude-code-glm --model moonshotai/Kimi-K3 --out runs/try
```

A non-null `exception` in the printed summary means the trial could not start (a missing credential, a harness not on `PATH`); that trial is not scored. Tasks on other simulators need their extra, for example `pip install 'robouse[metaworld]'` for `metaworld-*` ([Suites](suites.md)).

Options:

- `--timeout 600`: the agent's wall-clock limit in seconds, instead of the task's.
- `--seed 3`: another object and goal layout, where the backend supports it.
- `--extra-instruction TEXT`: text appended to the instruction.
- `--prior-learnings FILE`: markdown appended to the instruction, for example from `robouse summarize TRIAL`.

## Isolation

On macOS, model harnesses run under `sandbox-exec`. The profile denies reading the Robo Use package (it holds the reference solutions), other trials' workspaces and connections to other servers on the machine. It also denies the paths in `ROBOUSE_SANDBOX_DENY`: list your `--out` folder (the episode record is written there) and any credential files.

```sh
export ROBOUSE_SANDBOX_DENY="$PWD/runs:$HOME/.aws"
```

Paths are separated by colons. `ROBOUSE_SANDBOX=0` turns the sandbox off; It is a file fence, not a full security boundary. Linux has no sandbox; for container isolation, run published datasets with `bench eval run -d` ([Run a suite or dataset](run-a-suite.md#a-dataset)).

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
