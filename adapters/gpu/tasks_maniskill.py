"""ManiSkill3 tasks of the GPU track (task keys in src/robouse/backends/gpu_worker/maniskill_sim.py)."""

MS_SOURCE = "ManiSkill3 3.0.1 (Hillbot / UC San Diego, haosulab/ManiSkill, Apache-2.0); SAPIEN ray-traced rendering"

MS_USAGE = """\
## Scene and frames

World frame: x points away from the robot across the table, y to the robot's left, z up; the table top is z = 0 and the robot base sits at (-0.615, 0, 0). Positions are in metres. Poses in `robo observe` give `pos`, `quat_wxyz` (a unit quaternion w, x, y, z) and `rpy_deg` (roll, pitch, yaw in degrees: R = Rz(yaw) Ry(pitch) Rx(roll)).

The gripper's tool point (TCP) sits between the fingertips. In the TCP frame, +z points out between the fingers (the approach direction) and +y is the axis along which the fingers close. Pointing straight down with the fingers closing along world y is roll 180, pitch 0, yaw 0 (quaternion 0 1 0 0); turning that about the vertical is a change of yaw.

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell; you cannot read or change the simulator, the scoring, or other files to succeed. The episode server checks the task's physical success condition on the final simulated state itself.

```
robo info                                      # action space, skills, cameras, step budget
robo observe                                   # TCP pose, joint angles, gripper, and the task's object state
robo observe --image [--camera C]              # also saves a ray-traced image (cameras: scene, front, top, wrist) and prints its path
robo skill move X Y Z                          # motion-planned move of the TCP to (X, Y, Z), keeping its orientation
robo skill move X Y Z ROLL PITCH YAW           # ... to a full pose, orientation in degrees
robo skill move X Y Z QW QX QY QZ              # ... orientation as a quaternion
robo skill move ... speed=0.3                  # any move, slowed down (speed 0.05-1, default 1)
robo skill gripper open|close                  # open or close the fingers
robo skill gripper -0.6                        # finger target in [-1, 1] (-1 closed, +1 open); a loose grip lets a held object pivot
robo skill wait [N]                            # hold still for N control steps (default 10)
robo act DX DY DZ DRX DRY DRZ GRIP [--repeat N]   # low-level: one 0.05 s control step (see below)
robo done "short summary"                      # end the episode and ask for scoring
robo give-up "reason"                          # end the episode without claiming success
```

- `move` plans a path for the arm itself (straight-line screw motion first, then a sampling planner) but does not avoid the objects on the table: moving through them pushes them. It reports the TCP position it reached and the remaining position and orientation error. Contact (a held object touching something) can stop the arm short of the target.
- `act` is ManiSkill's end-effector delta-pose controller: DX, DY, DZ move the TCP by up to 0.1 m per step (value x 0.1 m), DRX, DRY, DRZ rotate it by up to 0.1 rad per step about world-aligned axes, and GRIP is the absolute finger target (+1 open, -1 closed). Values are clipped to [-1, 1].
- Success is judged after you call `robo done`, with the robot holding still for 10 control steps: the condition must hold at that moment. `robo give-up`, running out of steps or time, or stopping without `robo done` all score 0. Call `robo done` exactly once.
"""

MS_VISION_NOTE = """\
This is a camera-only task: `robo observe` returns only the robot's own state (TCP pose, joint angles, gripper). Every observation saves images from the cameras listed in `robo info` (calibrated: each has a 3x4 projection matrix P with [u*w, v*w, w] = P [x, y, z, 1] in image pixels, u to the right, v down). The cameras are RGB-D: `robo skill depth CAMERA U V` returns the world point seen at pixel (U, V) of that camera (with about 2 mm of sensor noise); it costs one step like every skill.
"""


def _t(**kw):
    kw.setdefault("source", MS_SOURCE)
    kw.setdefault("oracle_kind", "motion-planning")
    return kw


PEG = (
    "Pick up the peg lying on the table and insert it into the hole in the side of the box. The peg is a square bar: its head half is orange, its tail half white. Insert the orange head first: the task is solved when the peg's head end is inside the hole and at least half-way through the box's depth (the head end within 15 mm of the box centre along the hole or past it), and inside the hole's cross-section.\n\n"
    "`robo observe` gives `peg_pose` (the peg's centre; its +x axis points from the tail to the head), `peg_half_size` (half length, half width, half height in metres), `box_hole_pose` (the centre of the hole at the middle of the box; its +x axis is the insertion direction, so the peg enters from the hole frame's -x side) and `box_hole_radius` (the half width of the square hole)."
)

MANISKILL = [
    _t(
        id="ms-peg-insertion-side",
        env="peg-insertion-side",
        title="ManiSkill: peg insertion into a side hole (3 mm clearance)",
        summary="Pick up the peg and insert its orange head into the hole in the side of the box, at least half-way.",
        source_task="PegInsertionSide-v1",
        category="contact-rich-insertion",
        max_steps=40,
        hard="tight tolerance: 3 mm clearance per side around a 3-5 cm peg; a 6-DoF alignment computed from poses (quaternions), and the peg's pose in the hand shifts when the fingers close; peg size and poses randomized per seed",
        oracle="ManiSkill's motion-planning solution for PegInsertionSide, ported to the move/gripper skills (grasp, re-measure the peg in the hand, align in front of the hole, refine 3 times, insert)",
        instruction=PEG + "\n\nThe hole leaves 3 mm of clearance on each side of the peg.",
        tags=["tight-tolerance", "6dof"],
    ),
    _t(
        id="ms-peg-insertion-side-1mm",
        env="peg-insertion-side-1mm",
        title="ManiSkill: peg insertion with 1 mm clearance",
        summary="Pick up the peg and insert its orange head into the hole in the side of the box, at least half-way; the hole leaves only 1 mm of clearance on each side.",
        source_task="PegInsertionSide-v1 with a 1 mm hole clearance (upstream: 3 mm)",
        category="contact-rich-insertion",
        max_steps=40,
        hard="tighter tolerance than upstream: 1 mm clearance per side; a misalignment of about 1 degree jams the 17-25 cm peg",
        oracle="the ported motion-planning solution (re-measure the peg in the hand, refine the alignment 3 times, insert)",
        instruction=PEG + "\n\nThe hole leaves only 1 mm of clearance on each side of the peg.",
        tags=["tight-tolerance", "6dof"],
    ),
    _t(
        id="ms-peg-insertion-moving-box",
        env="peg-insertion-moving-box",
        title="ManiSkill: peg insertion when the box moves",
        summary="Pick up the peg and insert its orange head into the hole in the side of the box. The box gets bumped to a new pose while you work.",
        source_task="PegInsertionSide-v1 with a mid-episode perturbation",
        category="contact-rich-insertion",
        max_steps=50,
        hard="perturbation mid-episode: once the peg has been held for 10 control steps the box slides 6-10 cm and turns 12-20 degrees, so a plan made from the first observation fails; the agent has to notice and re-plan",
        oracle="the ported motion-planning solution, closed-loop: every alignment move is recomputed from the current box pose",
        instruction=PEG
        + "\n\nThe hole leaves 3 mm of clearance on each side. Somewhere during the task the box will be bumped and move to a new pose on the table; the task is judged against wherever the box is at the end.",
        tags=["perturbation", "tight-tolerance"],
    ),
    _t(
        id="ms-peg-insertion-side-vision",
        env="peg-insertion-side-vision",
        title="ManiSkill: peg insertion from cameras only",
        summary="Pick up the peg and insert its orange head into the hole in the side of the box, using only camera images and depth readings to find them.",
        source_task="PegInsertionSide-v1, camera-only observations",
        category="contact-rich-insertion",
        max_steps=60,
        seed=2,
        obs_mode="vision",
        visible_fields=["tcp", "qpos", "gripper"],
        cameras=["front", "top", "wrist"],
        hard="partial observability: no object poses at all; the peg and the hole must be located in ray-traced RGB images and with noisy depth readings, then inserted with 3 mm clearance",
        oracle="the ported motion-planning solution (reads the privileged state with the oracle token)",
        instruction=PEG.split("\n\n")[0]
        + "\n\nThe hole leaves 3 mm of clearance on each side of the peg. The peg is 17-25 cm long and 3-5 cm thick; the box is as deep as the peg is long.\n\n"
        + MS_VISION_NOTE,
        tags=["camera-only", "tight-tolerance"],
    ),
    _t(
        id="ms-plug-charger",
        env="plug-charger",
        title="ManiSkill: plug a charger into its socket",
        summary="Pick up the charger and plug its two prongs fully into the wall receptacle.",
        source_task="PlugCharger-v1",
        category="contact-rich-insertion",
        max_steps=40,
        hard="very tight tolerance: 0.5 mm clearance around each prong; success needs the charger within 5 mm and 0.2 rad of the fully inserted pose; poses randomized per seed",
        oracle="ManiSkill's motion-planning solution for PlugCharger ported to the skills (angled grasp, align 5 cm in front of the socket, refine, insert)",
        instruction="Pick up the charger (a small block with two metal prongs) and plug it into the receptacle on the wall: both prongs must go into the receptacle's two holes. The holes leave 0.5 mm of clearance around each prong. The task is solved when the charger is within 5 mm and 0.2 rad of the fully inserted pose.\n\n`robo observe` gives `charger_pose` (the charger's frame: +x points along the prongs, the prongs stick out at +x), `receptacle_pose` and `goal_pose` (where `charger_pose` must end up when fully plugged in).",
        tags=["tight-tolerance"],
    ),
    _t(
        id="ms-plug-charger-vision",
        env="plug-charger-vision",
        title="ManiSkill: plug a charger in, cameras only",
        summary="Pick up the charger and plug its two prongs fully into the wall receptacle, using only camera images and depth readings.",
        source_task="PlugCharger-v1, camera-only observations",
        category="contact-rich-insertion",
        max_steps=60,
        seed=1,
        obs_mode="vision",
        visible_fields=["tcp", "qpos", "gripper"],
        cameras=["front", "top", "wrist"],
        hard="partial observability plus 0.5 mm prong clearance: charger and socket poses must be estimated from images and depth readings",
        oracle="the ported motion-planning solution (privileged state via the oracle token)",
        instruction="Pick up the charger (a small block with two metal prongs) and plug it into the receptacle on the wall: both prongs must go into the receptacle's two holes, which leave 0.5 mm of clearance around each prong. The task is solved when the charger is within 5 mm and 0.2 rad of the fully inserted pose.\n\n"
        + MS_VISION_NOTE,
        tags=["camera-only", "tight-tolerance"],
    ),
    _t(
        id="ms-stack-pyramid",
        env="stack-pyramid",
        title="ManiSkill: stack three cubes into a pyramid",
        summary="Place the red cube next to the green cube, then stack the blue cube on top of both.",
        source_task="StackPyramid-v1",
        category="multi-stage-stacking",
        max_steps=40,
        hard="multi-stage (two pick-and-place stages, 12+ primitive moves); 4 cm cubes must end touching side by side with the top cube resting on both, the whole pyramid static",
        oracle="ManiSkill's motion-planning solution for StackPyramid ported to the skills",
        instruction="Build a pyramid from the three 4 cm cubes: put the red cube (cubeA) directly beside the green cube (cubeB) so that the two touch, then set the blue cube (cubeC) on top of both, resting on the two of them. The task is solved when A and B are side by side on the table, C rests on both, and nothing is moving.\n\n`robo observe` gives the pose of each cube.",
        tags=["long-horizon"],
    ),
    _t(
        id="ms-pull-cube-tool",
        env="pull-cube-tool",
        title="ManiSkill: pull a cube closer with an L-shaped tool",
        summary="Use the L-shaped tool to pull the cube, which is out of the robot's reach, back towards the robot.",
        source_task="PullCubeTool-v1",
        category="tool-use",
        max_steps=40,
        hard="tool use: the cube is out of reach, so the agent must grasp the tool, place its hook behind the cube and pull; poses randomized per seed",
        oracle="ManiSkill's motion-planning solution for PullCubeTool ported to the skills",
        instruction="The red cube is out of the arm's reach. Use the L-shaped tool on the table: grasp its handle, place its hook behind the cube (on the far side from the robot), and pull the cube towards the robot base. The task is solved when the cube's centre is within 0.6 m (measured horizontally) of the robot base at (-0.615, 0).\n\n`robo observe` gives the poses of the tool and the cube.",
        tags=["tool-use"],
    ),
    _t(
        id="ms-lift-peg-upright",
        env="lift-peg-upright",
        title="ManiSkill: stand a lying peg upright",
        summary="Pick up the peg lying on its side and stand it upright on the table.",
        source_task="LiftPegUpright-v1",
        category="reorientation",
        max_steps=40,
        hard="in-hand reorientation by 90 degrees and a stable placement on a small end face",
        oracle="ManiSkill's motion-planning solution for LiftPegUpright ported to the skills",
        instruction="A peg lies on its side on the table. Stand it upright on one of its end faces, so that its long axis is vertical, resting on the table. The task is solved when the peg's long axis is within about 5 degrees (0.08 rad) of vertical and its centre is within 5 mm of half its length above the table.\n\n`robo observe` gives `obj_pose`, the peg's pose (its +x axis is the long axis; the peg is 24 cm long).",
        tags=["reorientation"],
    ),
    _t(
        id="ms-pick-moving-cube",
        env="pick-moving-cube",
        title="ManiSkill: pick a cube off a moving belt",
        summary="Grasp the cube while it slides across the table and hold it at the goal point.",
        source_task="PickCube-v1 with the cube sliding at 5 cm/s (conveyor)",
        category="dynamic",
        max_steps=150,
        hard="dynamic object: the cube slides 2.5 mm every control step (5 cm/s) until grasped and is carried off the belt, out of reach, about 10 s of simulated time after the start; every skill and step advances time, so the agent must predict where the cube will be and track it; cube yaw and direction randomized per seed",
        oracle="yaw-aligned approach with the move skill, then a visual-servo loop of end-effector delta steps (proportional control with velocity feed-forward), grasp, and a planned carry to the goal",
        instruction="A 4 cm red cube slides across the table at a constant 5 cm/s, as if on a conveyor belt: it moves 2.5 mm every control step (0.05 s of simulated time), in a straight line along the y axis, until it is grasped or lifted. When it passes y = 0.3 m (or -0.3 m) it is carried off the end of the belt, out of reach, and the task can no longer be solved. Simulated time only passes when the robot acts: each `robo act` step is 0.05 s, and a `robo skill` takes as long as its motion does (a `move` typically 0.5-2 s). Grasp the cube and bring it to the goal point, holding it there with the arm still. The task is solved when the cube's centre is within 2.5 cm of the goal point and the robot is static.\n\n`robo observe` gives `obj_pose` (the cube), `goal_pos` (the goal point, in the air above the table), `is_grasped`, and the TCP pose.",
        tags=["dynamic"],
    ),
    _t(
        id="ms-stack-pyramid-vision",
        env="stack-pyramid-vision",
        title="ManiSkill: stack a pyramid from cameras only",
        summary="Place the red cube next to the green cube, then stack the blue cube on top of both, finding the cubes only in camera images.",
        source_task="StackPyramid-v1, camera-only observations",
        category="multi-stage-stacking",
        max_steps=60,
        obs_mode="vision",
        visible_fields=["tcp", "qpos", "gripper"],
        cameras=["front", "top", "wrist"],
        hard="partial observability plus a multi-stage stack: cube positions and yaws must be estimated from ray-traced images and noisy depth readings, to within the 4 cm cubes' tolerance",
        oracle="the ported motion-planning solution (privileged state via the oracle token)",
        instruction="Build a pyramid from the three 4 cm cubes: put the red cube directly beside the green cube so that the two touch, then set the blue cube on top of both, resting on the two of them. The task is solved when red and green are side by side on the table, blue rests on both, and nothing is moving.\n\n"
        + MS_VISION_NOTE,
        tags=["camera-only", "long-horizon"],
    ),
    _t(
        id="ms-pick-moving-cube-vision",
        env="pick-moving-cube-vision",
        title="ManiSkill: pick a moving cube, cameras only",
        summary="Grasp the red cube while it slides across the table and hold it at the goal point, tracking it only in camera images.",
        source_task="PickCube-v1 with a conveyor, camera-only observations",
        category="dynamic",
        max_steps=150,
        obs_mode="vision",
        visible_fields=["tcp", "qpos", "gripper", "goal_pos"],
        cameras=["front", "top"],
        hard="dynamic object under partial observability: the cube moves 2.5 mm per control step and is only visible in images (plus depth readings, each of which costs a step), so position and velocity must be estimated from successive frames",
        oracle="the visual-servo policy on the privileged state (oracle token)",
        instruction="A 4 cm red cube slides across the table at a constant 5 cm/s, as if on a conveyor belt: it moves 2.5 mm every control step (0.05 s of simulated time), in a straight line along the y axis, until it is grasped or lifted. When it passes y = 0.3 m (or -0.3 m) it is carried off the end of the belt, out of reach, and the task can no longer be solved. Simulated time only passes when the robot acts: each `robo act` step is 0.05 s, and a `robo skill` takes as long as its motion does. Grasp the cube and bring it to the goal point (`goal_pos` in `robo observe`, in the air above the table), holding it there with the arm still. The task is solved when the cube's centre is within 2.5 cm of the goal point and the robot is static.\n\n"
        + MS_VISION_NOTE,
        tags=["camera-only", "dynamic"],
    ),
]
