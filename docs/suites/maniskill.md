# ManiSkill3 suite (GPU track)

10 tasks in `tasks/gpu-maniskill/` on [ManiSkill3](https://github.com/haosulab/ManiSkill) 3.0.1 (Hillbot and UC San Diego, Apache-2.0), with a Franka Panda. Physics is SAPIEN/PhysX; every image the agent or the video sees is rendered by SAPIEN's ray tracer on the GPU. GPU required: the simulator runs in a remote worker ([GPU track](gpu-track.md)).

- Task module: `src/robouse/backends/gpu_worker/maniskill_sim.py` (task table, skills, perturbations, reference policies). Task text: `adapters/gpu/tasks_maniskill.py`.
- Success is ManiSkill's own `evaluate()["success"]` on the final state, after `robo done` and a 10-step settle.

## Tasks

| Task | From | What makes it hard | Budget | Oracle steps |
|---|---|---|---|---|
| `ms-peg-insertion-side` | PegInsertionSide-v1 | 3 mm clearance per side; 6-DoF alignment from poses; the peg shifts in the hand when grasped | 40 | 17 |
| `ms-peg-insertion-side-1mm` | PegInsertionSide-v1, hole clearance 1 mm (upstream 3 mm) | 1 mm clearance: about 1 degree of misalignment jams the peg | 40 | 21 |
| `ms-peg-insertion-moving-box` | PegInsertionSide-v1 + perturbation | once the peg is held and lifted, the box slides 6-10 cm and turns 12-20 degrees; plans made from the first observation fail | 50 | 17 |
| `ms-peg-insertion-side-vision` | PegInsertionSide-v1, camera only | no object poses; locate peg and hole in images plus noisy depth readings | 60 | 17 |
| `ms-plug-charger` | PlugCharger-v1 | 0.5 mm clearance around two prongs; within 5 mm and 0.2 rad of fully inserted | 40 | 15 |
| `ms-plug-charger-vision` | PlugCharger-v1, camera only | 0.5 mm clearance from images and depth readings | 60 | 15 |
| `ms-stack-pyramid` | StackPyramid-v1 | two pick-and-place stages, 12+ primitive moves, static pyramid required | 40 | 16 |
| `ms-pull-cube-tool` | PullCubeTool-v1 | tool use: the cube is out of reach, the L-shaped hook must be placed behind it | 40 | 7 |
| `ms-lift-peg-upright` | LiftPegUpright-v1 | 90-degree reorientation with a loose grip that lets the peg pivot, then a stable placement | 40 | 7 |
| `ms-pick-moving-cube` | PickCube-v1 + conveyor | the cube slides 5 cm/s until grasped; skills take simulated time, so the agent must predict and track | 150 | 19 |

Every family randomizes object poses (and the peg's size) per seed; each task fixes one seed (the tasks' `seed`).

## Interface

- `robo act DX DY DZ DRX DRY DRZ GRIP`: one 0.05 s step of ManiSkill's `pd_ee_delta_pose` controller (0.1 m and 0.1 rad per unit, world-aligned axes; GRIP +1 open, -1 closed).
- `robo skill move X Y Z [R P Y | QW QX QY QZ] [speed=S]`: motion-planned move of the tool point with mplib (screw motion, then RRT-Connect), finished with an exact inverse-kinematics correction. The planner avoids the arm's own links, not the objects.
- `robo skill gripper open|close|VALUE`, `robo skill wait [N]`, and in camera-only tasks `robo skill depth CAMERA U V` (the world point at a pixel, with 2 mm noise).
- Cameras (640x480, ray-traced): `scene` (video), `front`, `top`, `wrist`. Camera-only tasks give calibrated 3x4 projection matrices in `robo info`.

## Reference solutions

ManiSkill's motion-planning solutions (`mani_skill/examples/motionplanning/panda/solutions`), ported to the `move` and `gripper` skills and made closed-loop: the insertion tasks re-measure the held part after grasping, correct the commanded pose by the part's remaining error until it is within 0.5 mm and 0.25 degrees of the pre-insertion pose, and insert in 2-4 mm increments across the entrance, re-centring each time. The moving-cube policy aligns yaw with a planned move, then tracks the cube with `act` steps (proportional control with the belt velocity as feed-forward).

Seeds: the tasks use seeds on which the reference policy succeeds. On other seeds the policies were not perfect in development: `peg-insertion-side-1mm` succeeded on 4 of 6 seeds (the peg jams at the entrance on the other two, where PhysX's contact offset takes up part of the 1 mm), `stack-pyramid` on 3 of 4.
