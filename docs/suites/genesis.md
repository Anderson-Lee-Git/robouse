# Genesis suite (GPU track)

3 tasks in `tasks/gpu-genesis/` on [Genesis](https://github.com/Genesis-Embodied-AI/Genesis) 1.4.2 (Genesis-Embodied-AI, Apache-2.0): pouring a simulated liquid (SPH, about 2,000 particles) with a Franka Panda, on Genesis's CUDA backend. GPU required: the simulator runs in a remote worker ([GPU track](gpu-track.md)).

- Task module: `src/robouse/backends/gpu_worker/genesis_sim.py`. Task text: `adapters/gpu/tasks_genesis.py`.
- Success is measured on the liquid itself after `robo done` and a 10-step settle: the fraction of particles inside the target container and the fraction spilled (neither in the target nor in the glass).

## Tasks

| Task | What makes it hard | Success | Budget | Oracle steps |
|---|---|---|---|---|
| `gs-pour-water` | fluid: pour point, tilt angle and tilt rate decide where the stream lands; the liquid is only visible in images | >= 80 % in the bowl, <= 10 % spilled | 60 | 18 |
| `gs-pour-water-narrow` | fluid into an 8.5 cm opening 10 cm up, less than twice the glass mouth | >= 70 % in the vase, <= 15 % spilled | 60 | 18 |
| `gs-pour-water-vision` | the bowl pour with no object positions: glass and bowl from calibrated images and depth readings | >= 80 % in the bowl, <= 10 % spilled | 80 | 18 |

Glass and container positions are randomized per seed; both tasks use seed 0.

## Interface

- `robo skill move X Y Z [R P Y] [speed=S]`: straight-line tool-point move (inverse kinematics along the line), orientation interpolated.
- `robo skill gripper open|close`, `robo skill wait [N]`, and `robo act` (1 cm and 3 degrees per unit per 0.05 s step).
- Grasp model: closing the fingers around the glass (tool point inside its footprint) welds it to the hand until they open. Friction alone let the full glass slip out of the fingers.
- Cameras (Genesis rasterizer, 640x480, not ray-traced): `scene`, `front`, `top`. The camera-only task gives 3x4 projection matrices and a `robo skill depth CAMERA U V` reading (2 mm noise).

## Reference solutions

Scripted: top grasp near the rim, carry the glass beside the container with its rim over the container's near wall, tilt in four steps to 130 degrees with pauses, set it upright. SPH on the GPU is not bit-for-bit repeatable, so outcomes vary a little between runs; in development the narrow pour landed 92-98 % in the vase with 2-8 % spilled over three repeats.

## Not included

- Cloth folding (PBD cloth): the cloth slid across the floor as a whole when a corner was lifted, so a fold could not be made reliably; dropped.
- A "pour half" task: once the liquid starts to flow the whole glass empties within a few tenths of a second, and the scripted policy could not stop at half reliably; dropped.
