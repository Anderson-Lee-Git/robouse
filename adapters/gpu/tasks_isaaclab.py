"""Isaac Lab tasks of the GPU track (task keys in src/robouse/backends/gpu_worker/isaaclab_sim.py)."""

IL_SOURCE = (
    "NVIDIA Isaac Lab 2.3.0 (isaac-sim/IsaacLab, BSD-3-Clause) on Isaac Sim 5.1 (NVIDIA Isaac Sim license): "
    "the Factory assembly environments (Narang et al., RSS 2022), PhysX GPU dynamics, RTX rendering"
)

IL_USAGE = """\
## Scene and frames

World frame: metres, z up. The fixed part (hole, gear base or bolt) is bolted to the table; the robot already holds the other part a few centimetres above it, as Factory starts every episode. `held_part_base` is the pose of the held part's base (the peg's bottom end, the gear's hub, the nut's bottom face); `fixed_part_position_estimate` is where the fixed part's top centre is measured to be.

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell; you cannot read or change the simulator, the scoring, or other files to succeed. The episode server checks Factory's own success condition on the final simulated state.

```
robo info                                   # action space, skills, cameras, step budget
robo observe                                # fingertip pose, held part pose, fixed part estimate and dimensions
robo observe --image [--camera C]           # also saves an RTX image (cameras: scene, close, side) and prints its path
robo act DX DY DZ RX RY RZ [--repeat N]     # one 1/15 s control step of Factory's task-space impedance controller
robo skill hold [N]                         # zero command for N steps (default 15)
robo done "short summary"                   # end the episode and ask for scoring
robo give-up "reason"                       # end the episode without claiming success
```

- `act` is Factory's action: DX, DY, DZ in [-1, 1] set a position target up to 2 cm from the current fingertip position; RX, RY, RZ in [-1, 1] rotate the target by up to 0.097 rad. Roll and pitch are held level (the gripper keeps pointing down), so only RZ turns the hand. The target is clamped to within 5 cm of the fixed part, and actions are smoothed (an exponential moving average), so the hand responds over several steps. The controller is compliant: pushing against a surface builds force rather than moving the part.
- Success is judged after you call `robo done`, with the robot holding still for 10 control steps. `robo give-up`, running out of steps or time, or stopping without `robo done` all score 0. Call `robo done` exactly once.
"""


def _t(**kw):
    kw.setdefault("source", IL_SOURCE)
    kw.setdefault("category", "contact-rich-assembly")
    return kw


ISAACLAB = [
    _t(
        id="il-factory-peg-insert",
        env="factory-peg-insert",
        title="Isaac Lab Factory: insert an 8 mm peg",
        summary="Insert the held 8 mm peg into the hole in the fixed socket, all the way down.",
        source_task="Isaac-Factory-PegInsert-Direct-v0",
        max_steps=300,
        hard="tight tolerance: 8.0 mm peg in an 8.1 mm hole (0.05 mm clearance per side); success needs the peg centred within 2.5 mm and seated to within 1 mm of the bottom (4 % of the 25 mm socket depth); compliant control with smoothed actions",
        oracle="scripted: align the peg's base over the hole from the privileged fixed-part pose, then descend with small lateral corrections",
        instruction="The robot holds an 8 mm peg a few centimetres above a socket with an 8.1 mm hole (25 mm deep). Insert the peg into the hole and push it all the way down. The task is solved when the peg's base is within 2.5 mm of the hole's axis and within 1 mm of the bottom of the hole.",
        tags=["tight-tolerance", "isaac-sim"],
    ),
    _t(
        id="il-factory-peg-insert-noisy",
        env="factory-peg-insert-noisy",
        title="Isaac Lab Factory: peg insertion with a noisy hole estimate",
        summary="Insert the held 8 mm peg into the socket's hole, all the way down, when the measured hole position is off by a few millimetres.",
        source_task="Isaac-Factory-PegInsert-Direct-v0 with 4 mm observation noise",
        max_steps=300,
        hard="noisy sensors: the reported hole position has a fixed error of about 4 mm (per seed), larger than the 0.05 mm clearance, so the agent must search (images, contact) instead of trusting the number",
        oracle="scripted with the true fixed-part pose (privileged): align, then descend",
        instruction="The robot holds an 8 mm peg a few centimetres above a socket with an 8.1 mm hole (25 mm deep). Insert the peg into the hole and push it all the way down. The task is solved when the peg's base is within 2.5 mm of the hole's axis and within 1 mm of the bottom of the hole.\n\nThe measured position of the socket (`fixed_part_position_estimate`) is off by several millimetres in x and y (a fixed calibration error, the same all episode). Use the cameras and what happens when the peg touches the socket to find the hole.",
        tags=["noisy-sensors", "tight-tolerance", "search"],
    ),
    _t(
        id="il-factory-gear-mesh",
        env="factory-gear-mesh",
        title="Isaac Lab Factory: mesh a gear onto its shaft",
        summary="Slide the held medium gear onto its shaft on the gear base so that it meshes with the two gears already there.",
        source_task="Isaac-Factory-GearMesh-Direct-v0",
        max_steps=400,
        hard="tight tolerance plus meshing: the gear's bore must go over its shaft and its teeth must mesh with the small and large gears, which needs yaw alignment found by feel; seated within 1 mm",
        oracle="scripted: align over the shaft from the privileged pose, then descend while wiggling the yaw so the teeth find the mesh",
        instruction="The robot holds a medium gear above a gear base that already carries a small and a large gear. Put the medium gear onto its own shaft (the middle one on the base) and push it down until it sits on the base, meshed with its neighbours. The task is solved when the gear's hub is within 2.5 mm of the shaft axis and within 1 mm of its seated height.\n\n`gear_peg_offset_in_base_frame_m` is the medium gear's shaft position in the gear base's frame (x along the base's yaw).",
        tags=["tight-tolerance", "isaac-sim"],
    ),
    _t(
        id="il-factory-nut-thread",
        env="factory-nut-thread",
        title="Isaac Lab Factory: thread an M16 nut onto a bolt",
        summary="Thread the held M16 nut onto the bolt by turning it clockwise while pressing down, at least 1.5 turns' worth of thread.",
        source_task="Isaac-Factory-NutThread-Direct-v0",
        max_steps=600,
        hard="contact-rich screwing: the nut must be centred on the bolt within 2.5 mm, then pressed and turned together (the thread pitch is 2 mm); long horizon of hundreds of small steps; wrong pressure cross-threads or stalls",
        oracle="scripted: align over the bolt from the privileged pose, then press down gently while turning clockwise at the maximum rate",
        instruction="The robot holds an M16 nut just above an M16 bolt (thread pitch 2 mm). Screw the nut onto the bolt: centre it, then turn it clockwise (RZ, which in this task only turns clockwise: RZ = +1 is the fastest turn, RZ = -1 no turn) while pressing down. The task is solved (Factory's condition) when the nut's bottom face is within 2.5 mm of the bolt's axis, has come down to within 0.75 mm (0.375 pitch) above a point 1.5 pitches below the top of the thread, and the hand's yaw has turned past zero (the hand starts at about +105 degrees and turns clockwise).",
        tags=["contact-rich", "long-horizon", "isaac-sim"],
    ),
    _t(
        id="il-factory-nut-thread-noisy",
        env="factory-nut-thread-noisy",
        title="Isaac Lab Factory: thread a nut with a noisy bolt estimate",
        summary="Thread the held M16 nut onto the bolt when the measured bolt position is off by a few millimetres.",
        source_task="Isaac-Factory-NutThread-Direct-v0 with 3 mm observation noise",
        max_steps=600,
        hard="noisy sensors plus contact-rich screwing: the reported bolt position has a fixed error of about 3 mm (per seed), more than the 2.5 mm centring tolerance, so the nut must be centred by feel or from images before it will thread; hundreds of small steps",
        oracle="scripted with the true bolt pose (privileged): align, then press down while turning clockwise",
        instruction="The robot holds an M16 nut just above an M16 bolt (thread pitch 2 mm). Screw the nut onto the bolt: centre it, then turn it clockwise (RZ, which in this task only turns clockwise: RZ = +1 is the fastest turn, RZ = -1 no turn) while pressing down. The task is solved (Factory's condition) when the nut's bottom face is within 2.5 mm of the bolt's axis, has come down to within 0.75 mm (0.375 pitch) above a point 1.5 pitches below the top of the thread, and the hand's yaw has turned past zero (the hand starts at about +105 degrees and turns clockwise).\n\nThe measured position of the bolt (`fixed_part_position_estimate`) is off by a few millimetres in x and y (a fixed calibration error, the same all episode). Use the cameras and what happens when the nut touches the bolt to find it.",
        tags=["noisy-sensors", "contact-rich", "long-horizon"],
    ),
]
