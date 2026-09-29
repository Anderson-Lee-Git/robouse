# Isaac Lab suite (GPU track)

5 tasks in `tasks/gpu-isaaclab/` on [NVIDIA Isaac Lab](https://github.com/isaac-sim/IsaacLab) 2.3.0 (BSD-3-Clause) running on Isaac Sim 5.1 (pip wheels, NVIDIA Isaac Sim additional software license). They are Isaac Lab's Factory assembly environments (Narang et al., "Factory: Fast Contact for Robotic Assembly", RSS 2022): sub-millimetre peg insertion, gear meshing and nut threading with a Franka Panda under Factory's task-space impedance controller and PhysX GPU dynamics. GPU required: the simulator runs in a remote worker ([GPU track](gpu-track.md)).

- Task module: `src/robouse/backends/gpu_worker/isaaclab_sim.py`. Task text: `adapters/gpu/tasks_isaaclab.py`.
- Success is Factory's own check (`_get_curr_successes` with each task's thresholds) after `robo done` and a 10-step settle.
- The environment's episode length is raised to 10 hours so Isaac Lab never auto-resets it; the episode server's budget ends the episode instead.

## Interface

- `robo act DX DY DZ RX RY RZ`: Factory's action, one 1/15 s step (position target offset x 2 cm, rotation x 0.097 rad, roll and pitch held level, target clamped to 5 cm around the fixed part, exponential smoothing). In nut threading RZ only turns clockwise.
- `robo skill hold [N]`.
- `robo observe`: fingertip pose, the held part's base pose, the fixed part's position estimate (exact, except in the noisy task), its dimensions, and for the gear the shaft offset.
- Cameras (640x480): `scene`, `close`, `side`. See the next section for how they are rendered.

## Tasks

| Task | From | What makes it hard | Budget | Oracle steps |
|---|---|---|---|---|
| `il-factory-peg-insert` | Isaac-Factory-PegInsert-Direct-v0 | 8.0 mm peg, 8.1 mm hole; centred within 2.5 mm and seated within 1 mm; compliant, smoothed control | 300 | 98 |
| `il-factory-peg-insert-noisy` | the same, hole estimate off by ~4 mm | noisy sensor: the reported hole position is wrong by more than the clearance | 300 | 98 |
| `il-factory-gear-mesh` | Isaac-Factory-GearMesh-Direct-v0 | bore over the shaft and teeth meshed with two gears, seated within 1 mm | 400 | 75 |
| `il-factory-nut-thread` | Isaac-Factory-NutThread-Direct-v0 | centre within 2.5 mm, then press and turn clockwise through the 2 mm-pitch thread | 600 | 263 |
| `il-factory-nut-thread-noisy` | the same, bolt estimate off by ~3 mm | noisy sensor plus screwing | 600 | 263 |

Factory randomizes the fixed part's position (5 cm) and yaw, the hand's start pose and the part's pose in the hand on every reset; each task uses seed 0 (`torch.manual_seed` before the reset).

## Reference solutions

Scripted on the privileged (true) fixed-part pose: servo the held part's base to 12 mm above its target, then descend with lateral corrections. Gear meshing wiggles the yaw (0.5 x sin) while descending so the teeth find the mesh; nut threading presses down gently while turning clockwise at the maximum rate.

## Images and the GPU driver

Isaac Sim 5.1's RTX renderer crashed at start-up (in its scene database plugin, `librtx.scenedb`) on the Daytona hosts, which now run NVIDIA driver 595.71 or 595.91; it ran on a host with driver 580.126 early in this work (the Factory peg insertion reference solution passed there with RTX images). Isaac Sim starts fine on 595 without its renderer, so the worker runs Isaac Lab headless without cameras: physics is unchanged (PhysX on the GPU), and the images the agent and the video see come from a small MuJoCo (OpenGL, EGL) scene of the parts' shapes (boxes and cylinders sized from Factory's asset configuration, a schematic hand at the fingertip pose), whose poses are copied from Isaac Lab every frame. They are schematic, not photorealistic. On a host with a 580-series driver, `ROBOUSE_IL_RTX=1` switches the worker to Isaac Sim's own RTX viewport.
