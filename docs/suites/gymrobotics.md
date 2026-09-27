# Gymnasium-Robotics suite

12 tasks adapted from Farama's [Gymnasium-Robotics](https://robotics.farama.org/) (gymnasium-robotics 1.4.2, gymnasium 1.3.0, MuJoCo 3.3.0): 6 Fetch manipulation tasks and 6 PointMaze navigation tasks. Backend: `src/robouse/backends/gymrobotics.py`. Generator: `python adapters/gymrobotics/generate.py --out tasks/gymrobotics`. The task list (id -> env id, seed) lives in `TASKS` in the backend module.

## Tasks

| Task id | Source env | Seed | Category | Difficulty | Step budget | Skills | Success mode |
|---|---|---|---|---|---|---|---|
| gymrobotics-fetch-reach-s0 | FetchReach-v4 | 0 | manipulation | easy | 300 | move_to, grip | final |
| gymrobotics-fetch-reach-s1 | FetchReach-v4 | 1 | manipulation | easy | 300 | move_to, grip | final |
| gymrobotics-fetch-push-s0 | FetchPush-v4 | 0 | manipulation | medium | 300 | move_to, grip | final |
| gymrobotics-fetch-push-s1 | FetchPush-v4 | 1 | manipulation | medium | 300 | move_to, grip | final |
| gymrobotics-fetch-pick-place-s0 | FetchPickAndPlace-v4 | 0 | manipulation | medium | 300 | move_to, grip | final |
| gymrobotics-fetch-pick-place-s1 | FetchPickAndPlace-v4 | 1 | manipulation | medium | 300 | move_to, grip | final |
| gymrobotics-pointmaze-umaze-s3 | PointMaze_UMaze-v3 | 3 | navigation | easy | 600 | none | first |
| gymrobotics-pointmaze-umaze-s11 | PointMaze_UMaze-v3 | 11 | navigation | easy | 600 | none | first |
| gymrobotics-pointmaze-medium-s3 | PointMaze_Medium-v3 | 3 | navigation | medium | 1000 | none | first |
| gymrobotics-pointmaze-medium-s5 | PointMaze_Medium-v3 | 5 | navigation | medium | 1000 | none | first |
| gymrobotics-pointmaze-large-s1 | PointMaze_Large-v3 | 1 | navigation | hard | 1500 | none | first |
| gymrobotics-pointmaze-large-s2 | PointMaze_Large-v3 | 2 | navigation | hard | 1500 | none | first |

The seed is passed to the env's `reset(seed=...)`, which samples the object position and goal (Fetch) or the start and goal cells (PointMaze), so the two seeds of an env give different layouts. Seed 1 of FetchPickAndPlace puts the goal 37 cm above the table; seed 0 puts it on the table. Maze seeds were chosen for long routes: the shortest start-to-goal path is 5 and 6 cells (UMaze), 9 and 9 (Medium), 13 and 16 (Large).

FetchSlide-v4 is not included. The backend loads it, but no scripted controller driving the arm through the public `robo` interface solved it reliably (several attempts, each failing on most of the 8 layouts tried): the puck keeps gliding at about 3 cm/s on the low-friction table, strikes from the blocked fingers deflect it by 5 to 20 degrees, and most goals lie beyond the arm's reach (x > 1.38 m), so a missed strike cannot be corrected. A task without a working reference solution cannot be validated, so it was left out.

## Fetch: action and observation

Action `robo act DX DY DZ GRIP`, each in [-1, 1]. DX/DY/DZ move the gripper's position target by up to 5 cm per step (Fetch's native scaling; one step is 40 ms of simulation). GRIP +1 closes the fingers and -1 opens them. The grip sign is flipped relative to native Fetch (where +1 opens) so that it matches the shared `robo grip` skill and Meta-World. In FetchReach the fingers are locked and GRIP does nothing. The gripper orientation is fixed (pointing down).

Observation fields (named to match Meta-World so the shared `move_to`/`grip` skills work):

| Field | Meaning |
|---|---|
| hand_pos, hand_vel | gripper position (m) and velocity (m/s) |
| gripper_open | finger opening, 0 = closed, 1 = fully open |
| gripper_width | finger gap in metres |
| obj1_pos, obj1_vel, obj1_rot | block position, world velocity, Euler angles (not in Reach) |
| goal_pos | Fetch's `desired_goal`, drawn as a red sphere |

All of these come from Fetch's own observation vector; `obj1_vel` is converted from Fetch's gripper-relative, per-step form to world m/s.

Success is Fetch's own `_is_success`: the block (the gripper for Reach) within 5 cm of the goal. Success mode is `final`: the session judges the state after `robo done` and a 10-step hold. This matches Fetch's usual evaluation (success at the end of the episode) and means a block that is pushed through the goal, or dropped, does not count.

## PointMaze: action and observation

Action `robo act FX FY`, each in [-1, 1]: a force on the ball along world x and y (one step is 10 ms; the ball's speed is capped at 5 m/s). The ball keeps its momentum. Skills are disabled (`skills: false`): the session's `move_to` assumes a 3-D hand position, and a straight-line mover would run into walls, so the agent drives the ball with `robo act ... --repeat N`.

Observation fields:

| Field | Meaning |
|---|---|
| agent_pos, agent_vel | ball position (m) and velocity (m/s) |
| goal_pos | goal position (red in images; the ball is green) |
| maze_rows | maze layout, one string per row from the top (+y) row down; `#` wall, `.` free |
| cell_size | cell width in metres (1.0) |
| cell_center | formula for the world (x, y) of the centre of cell (row, col) |
| agent_cell, goal_cell | the [row, col] cell of the ball and of the goal |

The maze layout is public in the original benchmark (it is the environment's fixed map), and `agent_cell`/`goal_cell` are derived from public positions, so none of this leaks hidden state.

Success is PointMaze's own rule: the ball within 0.45 m of the goal. The env is created with `continuing_task=False` (no new goal after reaching one) and the task uses success mode `first`: the episode ends as solved the first time the ball reaches the goal, which is PointMaze's episodic protocol (it terminates on reaching the goal, as in D4RL/Minari). Requiring the ball to stop on the goal would add a braking problem the original task does not have.

## Camera

320x320 offscreen renders with `mujoco.Renderer` on the env's model/data (no gymnasium GL setup; images come out upright). Fetch uses a free camera looking at the table from the front-left, high enough to keep goals in the air in view; the 2 m green crosshair drawn on Fetch's mocap body is hidden (visual only). If a task's `camera` names a model camera (e.g. `external_camera_0`), that camera is used instead. PointMaze uses a top-down camera with +x right and +y up, sized to the whole maze.

## Reference solutions

`oracle_main(task_id)` in the backend module drives the robot only through the episode socket (`robouse.agent_cli._send`, ops `observe`/`act`/`move_to`/`grip`/`done`) and reads only public observation fields.

- Reach: `move_to` the goal, then `done`.
- Push: close the fingers, stand 6 cm behind the block on the block-to-goal line, push along the line with `act` while checking the block, and re-approach from behind if the hand drifts off the line; `done` once the block is within 1.5 cm of the goal.
- Pick and place: open, move above the block, descend, close, lift, move so the held block is on the goal (correcting for the block's offset in the grip), `done`.
- PointMaze: BFS over `maze_rows` from `agent_cell` to `goal_cell`, then a PD controller (`act` with 5-step repeats) through the cell centres and finally to `goal_pos`.

## Validation

Run through the real runner on 2026-09-27:

| Harness | Command | Result |
|---|---|---|
| oracle | `.venv/bin/robouse run-many --tasks tasks/gymrobotics --harness oracle --out runs/oracle-gymrobotics --concurrency 4` | 12/12 solved (reward 1 on every task) |
| noop | `.venv/bin/robouse run-many --tasks tasks/gymrobotics --harness noop --out runs/noop-gymrobotics --concurrency 4` | 0/12 solved |

Oracle steps used: Reach 100 and 8; Push 65 and 37; Pick and place 46 and 47; UMaze 189 and 233; Medium 346 and 351; Large 517 and 628. Each episode took 7 to 8 s of wall time. Recorded videos were checked visually: the Fetch view shows the arm, block and goal sphere; the maze view shows the full maze with the ball and goal.

## Limitations

- FetchSlide is excluded (see above).
- FetchReach is easy: both goals are 16 to 17 cm from the starting gripper position.
- Some FetchReach goals are slightly below the table top, where the gripper cannot go; they are still reachable within the 5 cm success radius (seed 0's goal is at z = 0.397 m; the gripper bottoms out at z = 0.419 m, 2.2 cm away, which counts as success).
- The Fetch step budget (300) is 6x the original 50-step episode, and the maze budgets (600/1000/1500) are 2x the originals (300/600/800), to leave room for an agent that works through a CLI in small steps.
- PointMaze has no skills; an agent must plan a route over the grid and control a ball with momentum through `robo act`.
- `gymnasium-robotics` (1.4.2) must be installed in the environment that runs `robouse serve`.
