# Navigation suite (object-goal navigation in homes)

40 tasks: drive a mobile base through a home to a named piece of furniture and stop next to it. The protocol follows Dimensional's "Can Jev Nav?" study of LLM agents as real-time navigation policies (research.dimensional.org/system-one-navigation; code in dimensionalOS/dimos, Apache-2.0): a robot-frame WorldState in spatial language, Dimensional's discrete drive command, and their metrics (SPL, SoftSPL, arrival, collisions, time to target, path smoothness, excess turning, cost per run).

- Backend: `src/robouse/backends/nav.py`. Generator: `python adapters/nav/generate.py --out tasks/nav`.
- Dimensional's own 327 tasks: `python adapters/nav/import_dimensional.py` converts their published task geometry into `tasks-local/dimensional-nav/` (gitignored). The geometry derives from HSSD scenes (CC-BY-NC-4.0) and the study's data has no licence of its own, so the converted tasks are not redistributed until Dimensional confirms the terms.

## Simulator

Geometry only (numpy, no assets): the home is a set of 2-D boxes (walls, furniture) and labelled objects. The robot is a 0.25 m radius holonomic base moved kinematically at 10 Hz, like an agent on a navigation mesh: a move into an obstacle slides along it or stops. Homes are generated from a seed: 4-6 rooms (living room, kitchen, bedrooms, bathroom, office) on a grid, interior walls with 0.9-1.2 m doorways on a spanning tree plus extra doors, and 2-4 labelled pieces of furniture per room against the walls, clear of the doorways. Geodesics come from a distance field on the occupancy grid (0.1 m cells, inflated by the robot radius).

## Observation and action

- `robo observe`: `goal` (label, `bearing` in ahead / ahead_left / left / behind_left / behind / behind_right / right / ahead_right, `bearing_deg`, `distance` touching < 0.5 m / near < 1.5 m / mid < 4 m / far, `distance_m`, `visible`, `arrived`), `objects` (furniture in line of sight within 6 m), `way_to_target` (`blocked`, `blocked_by`, `clear_m`, `open_sides`), `free_space` along the 8 bearings, `robot` (motion, last command, the last 8 s: moved, turned, target closer, pattern stuck / progressing, collisions). No world coordinates.
- `robo observe --image`: an egocentric top-down view of what the robot can see (ray-cast free space and visible objects; the target is red). The video records an overview of the whole home and the path.
- `robo act VX VY WZ` (m/s, m/s, deg/s; limits 0.5, 0.3, 46); skills `drive X Y YAW [SECONDS]` (Dimensional's discrete choices at 0.5 m/s and 0.8 rad/s), `turn DEG`, `forward METRES`.

## Success and metrics

Success: after `robo done`, the base is within 1.0 m of the target's footprint with line of sight to it (Dimensional's arrival rule). SPL = S * l / max(p, l); SoftSPL = max(0, 1 - d_final / l) * l / max(p, l), with l the geodesic from the spawn and d_final the geodesic left at the end; collisions count 0.5 s stalls of a linear command of at least 0.1 m/s at under 20 % of it; excess turning is radians turned per metre beyond the reference path's turning. Budget: 1200 steps (120 s).

## Tasks

10 homes x 4 targets (a label unique in its home), spawns 3-18 m of geodesic away; difficulty by detour ratio (geodesic / straight line): 23 easy (< 1.25), 12 medium (< 1.7), 5 hard.

## Validation

| Run | Result | Folder |
|---|---|---|
| reference solution (follows the distance field with `robo act`) | 40/40, SPL 0.987 [0.98, 0.993], path ratio 1.0 | `runs/nav-oracle3` |
| no-op | 0/40 | `runs/nav-noop` |
| Dimensional tasks, 20-task sample (seed 0) | 19 converted (1 unreachable in the 2-D footprints), reference 19/19 | `runs/dimnav-oracle5` |

Kimi K3 probe (`task-lists/nav-probe.txt`, `claude-code-glm`): see the table in [the parity update](../supported.md#parity-update-2026-09-29).
