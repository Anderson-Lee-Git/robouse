"""MuJoCo Playground tasks of the GPU track (task keys in src/robouse/backends/gpu_worker/playground_sim.py)."""

PG_SOURCE = ("MuJoCo Playground 0.2.0 (Google DeepMind, google-deepmind/mujoco_playground, Apache-2.0): Unitree robot models "
             "and joystick environments; walking policies trained for this track with Brax PPO on the GPU worker; MuJoCo Warp physics")

PG_USAGE = """\
## Scene and frames

World frame: x and y on the floor, z up, metres. The robot starts at the origin facing +x (yaw 0). `yaw_deg` is the heading measured counter-clockwise from +x.

## How to control the robot

You are the robot's high-level policy. The robot already knows how to walk: a learned locomotion policy (trained with reinforcement learning in MuJoCo Playground) turns your velocity command into leg motion 50 times a second. You act only through the `robo` command in your shell; you cannot read or change the simulator, the scoring, or other files to succeed.

```
robo info                              # command limits, skills, cameras, step budget
robo observe                           # base pose and velocity, fallen flag, contacts, and the task's map
robo observe --image [--camera C]      # also saves an image (cameras: chase, overview, head) and prints its path
robo act VX VY WZ                      # hold a body-frame velocity command for 0.5 s: VX forward m/s, VY left m/s, WZ turn rate rad/s (counter-clockwise)
robo act VX VY WZ --repeat N           # the same command for N x 0.5 s (N steps of the budget)
robo skill walk VX VY WZ SECONDS       # hold a command for up to 5 s; stops early if the robot touches something or falls (one step)
robo skill stand [SECONDS]             # stand still (zero command), default 1 s
robo done "short summary"              # end the episode and ask for scoring
robo give-up "reason"                  # end the episode without claiming success
```

- The robot does not track commands perfectly: it accelerates over a few tenths of a second, drifts sideways, and turns a little while walking straight. Re-observe and correct.
- Obstacles and walls are boxes given by their centre and half sizes in x and y. Collision is checked on the robot's footprint, a circle of `robot_radius_m` around its base: any overlap with an obstacle counts as a touch, and any touch fails the task (it is counted in `obstacle_contacts`; the episode goes on). If the robot falls (`fallen: true`) it cannot get up again.
- Success is judged after you call `robo done`: the condition must hold at that moment. `robo give-up`, running out of steps or time, or stopping without `robo done` all score 0. Call `robo done` exactly once.
"""

GO1 = "a Unitree Go1 quadruped (about 0.6 m long; footprint radius 0.32 m)"
G1 = "a Unitree G1 humanoid (1.3 m tall; footprint radius 0.28 m)"


def _t(**kw):
    kw.setdefault("source", PG_SOURCE)
    kw.setdefault("oracle_kind", "planner")
    kw.setdefault("category", "locomotion-navigation")
    return kw


PLAYGROUND = [
    _t(id="pg-go1-obstacle-field", env="go1-obstacle-field", title="Playground: Go1 through an obstacle field",
       summary="Walk the Go1 to the green goal disc 6 m away through a field of boxes without touching any of them.",
       max_steps=80, source_task="Go1JoystickFlatTerrain policy; scene built for this track",
       hard="closed-loop navigation through 11 randomized boxes (including a barrier across the direct line) with imperfect velocity tracking by a learned gait; any touch fails; layout randomized per seed",
       oracle="A* on a 0.1 m grid of the privileged map (obstacles inflated by the footprint plus 12 cm), then a heading controller that turns in place and walks each waypoint",
       instruction=f"You control {GO1}. Walk it to the goal: stop with its base inside the green disc (within 0.4 m of `goal`) without touching any obstacle and without falling.\n\n`robo observe` lists every obstacle (a box, centre and half sizes) and the goal position.",
       tags=["quadruped", "learned-policy", "navigation"]),
    _t(id="pg-go1-corridor-push", env="go1-corridor-push", title="Playground: Go1 down a zig-zag corridor while being shoved",
       summary="Walk the Go1 along a 0.9 m wide zig-zag corridor to its end while random shoves push it sideways, without touching the walls.",
       max_steps=100, source_task="Go1JoystickFlatTerrain policy with Playground's velocity-kick perturbation enabled",
       hard="perturbations mid-episode: every 2-4 s a shove of 0.5-1.5 m/s knocks the robot off course in a random direction; the corridor leaves 13 cm on each side of the footprint, so the agent must keep re-centring; three legs with two 90-degree turns",
       oracle="A* through the corridor on the privileged map and a heading controller at reduced speed, re-planned from the robot's current position after every command",
       instruction=f"You control {GO1}. Walk it through the corridor to the goal at its far end (within 0.4 m of `goal`) without touching the walls and without falling. The corridor is 0.9 m wide and has two 90-degree turns. Every few seconds a random shove pushes the robot (the policy keeps it on its feet, but it gets knocked off course).\n\n`robo observe` lists the wall segments (boxes) and the goal.",
       tags=["quadruped", "perturbation", "narrow"]),
    _t(id="pg-go1-moving-gates", env="go1-moving-gates", title="Playground: Go1 across three moving barriers",
       summary="Walk the Go1 7 m down a hall crossed by three blocks that slide back and forth, without being touched by any of them.",
       max_steps=100, source_task="Go1JoystickFlatTerrain policy; moving blocks added for this track",
       hard="dynamic obstacles: three 0.7 x 1.0 m blocks slide across the path sinusoidally (1.6 m amplitude, 5-8 s periods, random phases); the agent must time each crossing from the reported positions (simulated time only passes when the robot acts)",
       oracle="walk to 1.1 m before each lane, wait until the block's known motion keeps it clear of the path for 3 s, cross; then walk to the goal",
       instruction=f"You control {GO1}. Walk it from the start to the goal at the far end of the hall (within 0.4 m of `goal`). Three orange blocks slide back and forth across the hall along y (each moves along a fixed line x = `x`, 1.6 m to either side of the centre line, repeating every few seconds). The robot must not touch a block or the side walls, and must not fall.\n\nTime only passes in the simulation while the robot acts (0.5 s per `robo act` step). `robo observe` gives each block's lane (`x`), size and current `y_now`, the walls and the goal; watch a block over a few steps to learn its motion.",
       tags=["quadruped", "dynamic"]),
    _t(id="pg-go1-waypoint-tour", env="go1-waypoint-tour", title="Playground: Go1 six-waypoint tour",
       summary="Walk the Go1 through six waypoints in the given order, ending on the last one, without touching the five pillars.",
       max_steps=120, source_task="Go1JoystickFlatTerrain policy; scene built for this track",
       hard="long horizon: six ordered subgoals (each must be entered within 0.35 m, in order) around five pillars, with imperfect tracking by the learned gait; one touch or one skipped waypoint fails",
       oracle="for each waypoint in order: A* on the privileged map and the heading controller",
       instruction=f"You control {GO1}. Visit the six waypoints (blue discs) in the order listed in `waypoints`: the robot's base must come within 0.35 m of each waypoint, in order, and the episode must end with the robot standing at the last one. Do not touch the pillars and do not fall. `next_waypoint` in `robo observe` counts the waypoints reached so far (a waypoint only counts when all earlier ones have been reached).",
       tags=["quadruped", "long-horizon"]),
    _t(id="pg-go1-find-ball", env="go1-find-ball", title="Playground: Go1 finds the red ball (camera only)",
       summary="Find the red ball hidden somewhere in a walled room using the robot's cameras, and stop next to it.",
       max_steps=100, source_task="Go1JoystickFlatTerrain policy; scene built for this track",
       obs_mode="state", hard="partial observability: no map and no ball position; the ball sits behind one of four interior walls, so the agent must explore with the head camera, avoid walls it can only see, and stop within 0.6 m of the ball",
       oracle="A* to the ball on the privileged map (oracle token) and the heading controller",
       instruction=f"You control {GO1} in an 8 x 8 m room (walls at x = +-4 and y = +-4) with four low interior walls. A red ball (30 cm across) lies somewhere in the room, hidden behind one of the interior walls. Find it and stop with the robot's base within 0.6 m of the ball's centre, without touching any wall and without falling.\n\n`robo observe` gives only the robot's own state: no map and no ball position. Use the cameras: `head` looks forward from the robot, `chase` follows it from behind, `overview` looks down on the room at a steep angle (`robo observe --image --camera overview`).",
       tags=["quadruped", "camera-only", "exploration"]),
]
