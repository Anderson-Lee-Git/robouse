# Driving suite (a car on MetaDrive roads)

The driving suite has 7 tasks in `tasks/driving/`: a passenger car on procedurally built roads with traffic, road works and junctions. It is the wheeled embodiment of Robo Use: the agent is the driver and makes the tactical decisions (speed for a bend, when to change lanes, when to wait for a gap), while skills do the low-level lane keeping.

- Backend: `src/robouse/backends/driving.py` (embodiment declaration, skills, judge, task scenes, reference solutions).
- Simulator worker: `src/robouse/backends/driving_worker.py` (runs in MetaDrive's own virtualenv; scene manager, observation, controllers under the skills, rendering).
- Generator: `python adapters/driving/generate.py` (needs the MetaDrive virtualenv: it starts each scene once to write the route facts into the instruction).

![Waiting at the stop line for oncoming traffic before an unprotected left turn](../img/suites/driving.webp)

## Simulator and licence

[MetaDrive](https://github.com/metadriverse/metadrive) 0.4.3 (Apache-2.0; Li et al., "MetaDrive: Composing Diverse Driving Scenarios for Generalizable Reinforcement Learning", TPAMI 2022). Roads are built from MetaDrive's procedural blocks (straight, curve, roundabout, intersection, on-ramp) from a fixed block string and seed per task. The ego car and all traffic are Bullet raycast vehicles (engine force, brakes, tyre friction, suspension). Traffic is MetaDrive's IDM policy (car following with MetaDrive's lane logic). No robot model or Menagerie asset is involved (`assets: []`).

## Setup

MetaDrive brings numpy 2, opencv, pygame, panda3d and gymnasium 1.x, which must not enter the Robo Use environment, so it runs in its own virtualenv as a subprocess of the episode server that speaks JSON lines (the DexJoCo pattern).

```
uv venv -p 3.11 ~/.cache/robouse/metadrive-venv
uv pip install -p ~/.cache/robouse/metadrive-venv/bin/python metadrive-simulator==0.4.3
```

- The backend looks for `~/.cache/robouse/metadrive-venv/bin/python`; override with `ROBOUSE_METADRIVE_PYTHON`. Set `ROBOUSE_METADRIVE_QUIET=0` to see the worker's stderr.
- The worker runs with its own folder as working directory, so a stray `profile.py` in the caller's directory cannot shadow the standard library.
- The first start after installation takes about 15 s (MetaDrive builds caches); later a scene starts in 2 to 4 s.
- Only the top-down renderer (pygame) is used. MetaDrive's 3D cameras (panda3d) cannot open an offscreen window headless on macOS ("Could not open window"), so there is no forward camera.

## Action and controllers

One step is one MetaDrive step: 0.1 s (5 Bullet substeps of 0.02 s).

| Action group | Components | Values |
|---|---|---|
| `vehicle.controls` (mode `vehicle_controls`) | [STEER, THROTTLE] | each in [-1, 1]: STEER x 40 deg front-wheel angle (+ = left); THROTTLE > 0 engine force, < 0 brake force, 0 coasts |

This is MetaDrive's own car action, with no controller underneath. Zero throttle coasts, so the group declares `hold = [0, -1]` (full brake): the 10-step settle after `robo done` stops the car. Full braking stops the car from 50 km/h in about 11 m. MetaDrive's default car gets no engine force above 80 km/h. A braked car at standstill jitters by up to about 1 km/h in Bullet, hence the 2 km/h "at rest" threshold.

## Skills

The skills are closed-loop generators on the Robo Use side that ask the worker for one action per step and yield it:

- `follow_route SPEED_KMH METERS`: keeps the current lane along the navigation route for METERS at a set speed. Steering is a Stanley lane-centre tracker at the front axle (heading error + cross-track term + road-curvature feed-forward) on the lane centre line of the route; speed is PI cruise control. It does not brake for vehicles or obstacles and does not slow for curves. It reports distance driven, speed, lane, remaining distance and the nearest vehicle or object ahead in the lane, and stops early if an event (collision, road departure) happens.
- `change_lane left|right [SPEED_KMH]`: the same tracker aimed at the adjacent lane until centred (lateral error below 0.3 m, heading error below 3 deg). It does not check traffic or line types.
- `stop [METERS]`: brakes to a standstill while lane keeping, with a constant deceleration over about METERS (0 = full brake). Reports the stopping distance and whether the car is in the destination zone.
- `wait SECONDS`: brakes held.

The controllers read only the public observation plus the lane centre lines of the route (like a navigation map); they never see traffic intentions. When a lane ends (the on-ramp's acceleration lane), `follow_route` steers into the nearest lane of the next road without looking, which is exactly the blind merge the agent has to avoid.

## Observation and cameras

`robo observe` reports `ego` (position, heading, speed, last action), `lane` (road, lane index from the left, lane count, lateral offset, station, road shape, left/right line types), `route` (travelled, remaining, route completion, next three roads with distance, lane count and shape such as "curve right, radius 17 m, turning 90 deg", destination, `in_destination_zone`), `vehicles` and `obstacles` within 60 m (position in the car's frame, distance, speed, relative heading, road and lane, and for objects on the route the distance along it, bumper gap and `in_my_lane`; `broken_down` for a stopped car), and `events`. Cameras: `topdown` (follows the car, map +y up, 5 px per metre, 96 m across at 480 px) and `route_map` (the whole route).

## Tasks

Every task has the same success rule: after `robo done` and the 10-step brake-on settle, the car is at rest (below 2 km/h) inside the destination zone (MetaDrive's `arrive_dest` region: from 5 m before the end of the route's final road to 5 m past it, any lane), and at no time did the monitor record a collision with a vehicle, object, building or pedestrian, contact with the sidewalk / road edge, or MetaDrive's out-of-road condition (off the lanes, or on a solid white or yellow line). The judge runs on the trusted side from the worker's state.

| Task | Map (blocks, seed) | Scene | Decisions | Budget |
|---|---|---|---|---|
| driving-winding-road | `CSCC`, 0; 2 lanes | no traffic; two long right-hand bends (radius 52 to 60 m, 115 and 125 deg), the second followed by a 25 m-radius left bend (S-bend); 572 m | speed per bend, precise stop | 1000 |
| driving-highway-overtake | `SSSSSSSS`, 1; 3 lanes | truck at 30 km/h ahead in the ego lane, slow cars in the middle and right lanes, cars at 70 km/h from behind in the left lane; 571 m | when to change lanes into a gap; following the truck runs out of budget | 500 |
| driving-broken-down-car | `SCS`, 2; 2 lanes | broken-down car blocks the right lane with a warning triangle 12 m behind it; three cars pass in the left lane at about 50 km/h | wait behind the triangle or change lanes into a gap | 800 |
| driving-cone-zone | `SCS`, 4; 3 lanes | cone taper, barrier and a 45 m cone row close the two right lanes on a right-hand curve; slower car (35 km/h) in the open lane | change lanes twice before the taper, keep distance | 900 |
| driving-roundabout | `SOS`, 0; 2 lanes | MetaDrive IDM traffic (density 0.25); route takes the third exit | speed and gaps in the roundabout | 900 |
| driving-intersection-left-turn | `SXS`, 0; 2 lanes | unsignalised four-way junction; a stream of six oncoming cars at 40 km/h, two more after a long gap (all spawned by a fixed timetable at the east end of the map) and one crossing car from the north | stop at the line, wait for a gap, turn | 900 |
| driving-ramp-merge | `SrS`, 0; ramp + 3 lanes | a short on-ramp and a 38 m acceleration lane; a platoon of six vehicles (one truck) at 50 km/h in the right lane, a faster car in the middle lane | hold back on the ramp, merge behind or into a gap before the lane ends | 700 |

Scripted scene elements (static objects, broken-down cars, timetabled IDM vehicles with a fixed cruise speed and no lane changes) are spawned by a small MetaDrive manager in the worker (`SceneManager`); scripted vehicles leave the scene when they drive off the end of the map, as in MetaDrive's own traffic manager.

## Validation

Real runner, 2026-09-28, MetaDrive 0.4.3 on the Mac's CPU:

| Harness | Result | Runs |
|---|---|---|
| oracle | 7/7 | `runs/emb-oracle-driving/` |
| noop | 0/7 | `runs/emb-noop-driving/` |

The reference solutions (`solution()` in `driving.py`) drive through the socket with the skills and the public observation only: speed limited by the bend radius (lateral acceleration 2.2 m/s²) and by the vehicle ahead (2 s gap), lane changes only when the target lane has no vehicle alongside, room ahead and a 3 s gap to faster vehicles behind, waiting at the stop line until no vehicle is closing in within 5 s, and holding back on the ramp until the platoon has passed. Oracle episodes take 10 to 20 s of wall time (3 in parallel on the loaded Mac) (worker start and map build 2 to 4 s; a step with the JSON round trip takes a few milliseconds; the 480 px top-down frame about 5 ms).

Decisions matter: a plain `follow_route` at one speed to the end of the route and a `stop` fails every traffic task at 40 km/h except the intersection and the ramp (which it gets through by timing luck), and at 70 km/h it fails the winding road (runs over the edge at the S-bend), highway, roundabout, intersection and ramp; at 45 km/h it slips through the intersection, at 30 km/h through the ramp. Scripted wrong attempts score 0: stopping 15 m short of the destination, rolling past its end (out of road), staying behind the truck (budget exhausted), and changing lanes only 8 m before the cone taper (hits a cone).

Determinism: MetaDrive is deterministic given the map seed and the action sequence. Two processes with the same actions gave identical positions of every vehicle (checked in both trigger and respawn traffic modes), and two runner episodes of the roundabout task (MetaDrive's own IDM traffic) produced byte-identical traces. Rendering does not change the simulation.

## Limitations

- Traffic is MetaDrive's IDM: it brakes for what is ahead in its lane but does not yield at junctions or roundabouts and does not react to a car cutting in beside it; PG maps have no traffic lights, so there are no red-light violations to check.
- Scripted traffic appears at fixed times at the map's edges (e.g. the east arm of the intersection is only 35 m long), so cars can enter the 60 m observation radius already moving.
- State is exact (no sensor noise, perfect detection within 60 m, no occlusion); there is no forward 3D camera on this Mac (headless panda3d fails).
- The world is paused between agent commands, so reaction time is not tested; only the decisions and their timing in simulated time are.
- Destination and lane geometry come from MetaDrive's map; a braked car at standstill jitters by up to about 1 km/h.
