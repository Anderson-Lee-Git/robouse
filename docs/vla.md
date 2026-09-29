# VLA policies (`vla` harness)

`--harness vla --model PRESET` drives an episode with a vision-language-action policy served elsewhere (usually on a GPU). The client (`src/robouse/vla/client.py`, standard library + numpy) is copied into the trial workspace and reaches the robot only through `robo`, like every harness; it speaks each policy server's own wire protocol, so the servers run unmodified.

```bash
export ROBOUSE_VLA_URL=ws://gpu-box:8000          # the policy server
robouse run --task libero-10-0 --harness vla --model openpi/pi05_libero --out runs/pi05
robouse run --task real-so101-reach --harness vla --model gr00t/so101 --out runs/gr00t   # ROBOUSE_VLA_URL=tcp://gpu-box:5555
```

## Wire protocols

| Wire | Servers | Transport and messages |
|---|---|---|
| `openpi` | openpi `serve_policy.py` (pi0, pi0-FAST, pi0.5) | websocket; msgpack with openpi's numpy convention; server metadata first, then one observation dict per request, reply `{"actions": [H, D]}` |
| `xpolicylab` | XPolicyLab policy servers (pi0/pi0.5, GR00T, OpenVLA-OFT, RDT-1B, SmolVLA, ACT, Diffusion Policy, ...) | websocket; msgpack + msgpack-numpy envelope (`hello`, `reset`, `infer`, `trial_end`), Observation Data Format v1.0, reply a list of per-step action dicts |
| `openvla` | OpenVLA `vla-scripts/deploy.py` | HTTP POST `/act`, json-numpy `{"image", "instruction", "unnorm_key"}`, reply one action |
| `gr00t` | Isaac GR00T N1.6/N1.7 `run_gr00t_server.py` | ZeroMQ REQ/REP, msgpack + msgpack-numpy, `{"endpoint": "get_action", "data": {"observation": ...}}`, reply `[{key: [B, H, D]}, info]` |
| `http-json` | Robo Use's MolmoAct2 server and `src/robouse/vla/lerobot_server.py` (any LeRobot policy: SmolVLA, pi0, pi0.5, ACT, diffusion, MolmoAct2; LIBERO pipeline or joint-state robots) | HTTP JSON: `/reset`, `/act` with base64 PNG images and state, reply `{"actions": [[...]]}` |

## Presets

`src/robouse/vla/presets.json` fixes, per policy, the wire, the observation template (dotted keys filled from a camera, state fields, the instruction or a constant, with resizing, padding and flips), the action mapping onto the task's action vector (selection, sign, scale, gripper conventions such as OpenVLA's, relative-to-state) and the chunk controller. Shipped: `openpi/pi05_libero`, `openpi/pi0_libero`, `openvla/openvla-7b-libero`, `molmoact2/libero`, `lerobot/smolvla_libero`, `lerobot/pi05_libero`, `gr00t/so101`, `xpolicylab/metal-joint`, `xpolicylab/so101-joint`, and `*/generic` presets to fill in. Override any field with `ROBOUSE_VLA_POLICY_CONFIG=overrides.json`.

## Chunk execution and checks

- Controllers: open loop (`replan: K` executes the first K actions of each chunk), ACT/ALOHA temporal ensembling (`mode: ensemble`, weights exp(-m * age)), exponential smoothing (`smooth: alpha`).
- Compatibility check before anything moves: the preset's backends, the policy's action dimension against the task's (unless mapped), and the policy's control mode against the embodiment's action groups. A mismatch ends the episode with `give_up` and the reason, at 0 steps.
- A VLA never says done: the client claims `done` when the budget is about to run out or, with `stop.still_steps`, when the commanded action has settled.
- Every inference is one JSON line in `agent/stdout.jsonl` (chunk shape, executed actions, round-trip and server timing), converted to the trial's ATIF trajectory.

## What was tested

- `scripts/vla_dogfood.sh`: mock policy servers built on the upstream libraries (msgpack, msgpack-numpy, websockets, pyzmq, json-numpy; `tests/vla_mock_servers.py`) on every wire, end to end through the sandboxed harness: openpi, OpenVLA and http-json replay a LIBERO demonstration through the wire and solve `libero-10-0`; XPolicyLab solves `real-metal-reach` and GR00T solves `real-so101-reach` on the hardware-in-the-loop mock. 5/5. The observations the servers received had the expected keys, shapes and dtypes (e.g. openpi `observation/image uint8[224, 224, 3]`, GR00T `video.front uint8[1, 1, 224, 224, 3]`).
- An incompatible pairing (`gr00t/so101` on the 7-joint Metal arm) is rejected at 0 steps.
- `tests/test_vla.py`: codecs, PNG round trip, resizing, gripper mapping, controllers, compatibility check, presets.
- Not tested: real model weights (they need a GPU server; LeRobot's SmolVLA could run on CPU with `lerobot_server.py` but was not run for these docs).
