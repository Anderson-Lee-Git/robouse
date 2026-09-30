# MuJoCo Playground suite (GPU track)

5 tasks in `tasks/gpu-playground/` on [MuJoCo Playground](https://github.com/google-deepmind/mujoco_playground) 0.2.0 (Google DeepMind, Apache-2.0) with MuJoCo 3.14.0, MuJoCo Warp, JAX 0.7.2 and Brax 0.14.2. The robot is Playground's Unitree Go1 quadruped, walking with a joystick policy we trained on the GPU worker; the agent steers it with velocity commands. GPU required: the simulator and the policy run in a remote worker ([GPU track](gpu-track.md)).

- Task module: `src/robouse/backends/gpu_worker/playground_sim.py` (scene layouts, contact checks, reference planner). Training script: `src/robouse/backends/gpu_worker/train_playground.py`. Task text: `adapters/gpu/tasks_playground.py`.

## The walking policy

`Go1JoystickFlatTerrain`, trained with Brax PPO and Playground's own hyperparameters (`locomotion_params.brax_ppo_config`: 200 M environment steps, policy MLP 512-256-128) on one RTX PRO 6000: 46 minutes, final evaluation reward 29.3 (it reached 28 by 90 M steps). The policy runs at 50 Hz on the robot's proprioception and the command; physics is MuJoCo Warp (Playground's `warp` implementation). The trained parameters are not committed; `train_playground.py` reproduces them.

A G1 humanoid joystick policy was started too but reached only 10 M steps in 21 minutes while sharing the GPU (200 M would have taken hours), so it was stopped and the humanoid tasks were dropped.

## Tasks

| Task | What makes it hard | Budget | Oracle steps |
|---|---|---|---|
| `pg-go1-obstacle-field` | closed-loop navigation around five randomized boxes and a 2.4 m barrier across the direct line, with imperfect command tracking; any touch fails | 80 | 60 |
| `pg-go1-corridor-push` | a 0.9 m zig-zag corridor (13 cm to spare on each side) while Playground's velocity kicks (0.5-1.5 m/s, every 2-4 s) shove the robot | 100 | 58 |
| `pg-go1-moving-gates` | three blocks slide across the hall (1.8 m amplitude, 8-12 s periods, up to 1.4 m/s); crossings must be timed | 200 | 33 |
| `pg-go1-waypoint-tour` | six ordered waypoints around five pillars (long horizon) | 250 | 161 |
| `pg-go1-find-ball` | camera only: no map, no ball position; the red ball hides behind one of four interior walls | 100 | 24 |

Contacts are geometric: the robot's footprint (a 0.32 m circle around its base) must not overlap any obstacle box; the obstacles are drawn but do not push the robot. A fall (body tilted over, or the base below 45 % of its standing height) cannot be undone.

## Interface

- `robo act VX VY WZ` holds a body-frame velocity command for 0.5 s (limits 1.5 m/s, 0.8 m/s, 1.2 rad/s, Playground's command range).
- `robo skill walk VX VY WZ SECONDS` (up to 5 s, stops on a touch or a fall), `robo skill stand [SECONDS]`.
- Cameras (MuJoCo OpenGL renderer, EGL on the GPU; not photorealistic): `chase`, `overview`, `head`.

## Reference solutions

A* on a 0.1 m grid of the privileged map (obstacles inflated by the footprint plus 12 cm), then a heading controller (turn in place until within 0.5 rad, then walk). The moving-gates policy walks to 1.2 m before each lane, faces +x, waits until the block's known motion keeps it clear of the crossing window, and crosses at full speed.
