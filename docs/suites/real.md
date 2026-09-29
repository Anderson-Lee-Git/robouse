# Real suite (real robot arms)

5 tasks on real arms, each runnable on the hardware-in-the-loop mock (default) or on live hardware with `--rig` ([Real robots](../real-robots.md)). Generator: `python adapters/real/generate.py`.

| Task | Robot | Verdict | Budget |
|---|---|---|---|
| `real-metal-reach` | Metal | fingertip within 2 cm of (0.30, -0.10, 0.08) m, from the measured joints | 300 |
| `real-metal-bead-to-bowl` | Metal | operator (mock: 6 staged checkpoints on the measured pose: above the bead open, at the bead, closed, lifted, over the bowl, released) | 900 |
| `real-so101-reach` | SO-101 | fingertip within 2 cm of (0.20, 0.05, 0.08) m | 300 |
| `real-so101-block-lift` | SO-101 | operator (mock: 4 staged checkpoints) | 600 |
| `real-piper-joint-pose` | Piper | every arm joint within 3 deg of the target | 300 |

| Run (mock) | Result | Folder |
|---|---|---|
| reference solutions (skill sequences through `robo`) | 5/5 | `runs/real-oracle` |
| no-op | 0/5 | `runs/real-noop` |
| VLA wires: XPolicyLab on `real-metal-reach`, GR00T on `real-so101-reach` (mock policy servers) | 2/2 | `runs/vla-dogfood` |

Kimi K3 probe (`task-lists/real-probe.txt`): see [the parity update](../supported.md#parity-update-2026-09-29).
