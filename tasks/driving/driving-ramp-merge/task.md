---
schema_version: '1.3'
task:
  name: robouse/driving-ramp-merge
  description: Merge from an on-ramp
metadata:
  source_benchmark: robouse original (driving suite; MetaDrive 0.4.3)
  source_task: driving-ramp-merge
  suite: driving
  category: traffic
  difficulty: hard
  tags:
  - driving
  - wheeled
  - metadrive
  - merge
  - on-ramp
  - traffic
  simulator: MetaDrive 0.4.3 (Apache-2.0)
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: driving-ramp-merge
  backend: driving
  env: driving-ramp-merge
  seed: 0
  max_steps: 700
  camera: topdown
  cameras:
  - topdown
  - route_map
  skills: true
  success_mode: final
---

# Merge from an on-ramp

You drive a passenger car (MetaDrive's default sedan: 4.5 m long, 1.85 m wide, Bullet vehicle dynamics, no engine force above 80 km/h) on a road map built by the MetaDrive driving simulator. Map frame in metres: `x`, `y` on the ground, `heading_deg` 0 along +x and counter-clockwise positive; the top-down camera shows +y up. Traffic drives on the right. Lanes of your direction are numbered from the left: lane 0 is next to the yellow centre line, which you must never cross. Roads are named by MetaDrive node pairs (e.g. `>>>->1S0_0_`). The navigation route is fixed: `robo observe` gives, under `route`, the distance travelled and remaining, the next roads (distance to their start, lane count and shape: straight, or a curve with its radius and turn angle) and the destination. Road users within 60 m are listed under `vehicles` and road objects (cones, warning triangles, barriers) under `obstacles`, with their position in your car's frame, their distance along your route and their lane. Simulated time advances only when you act; the scene is paused while you think.

## Task

You start on an on-ramp. It joins the right side of a three-lane highway as a short acceleration lane (lane 3 of 4, about 38 m long, then it ends). A platoon of cars drives in the highway's right lane (lane 2) at about 50 km/h. Merge into lane 2 through a safe gap before the acceleration lane ends, then drive to the destination and stop there. The route is 220 m long (7 roads); the destination is at (350.6, 3.5), at the end of road `2r0_2_->3S0_0_`. You start at (133.3, -8.2), heading 0 deg, in lane 0 of 1.

**Success:** after you call `robo done` and the car has braked for 10 steps, it is at rest (below 2 km/h) inside the destination zone (from 5 m before the end of the route's final road to 5 m past it, any lane; `route.in_destination_zone`), and at no time did it collide with a vehicle or object, touch the road edge or sidewalk, leave the road, or cross a solid lane line (MetaDrive's out-of-road rule). Collisions and road departures are listed under `events` as they happen, and any event fails the task. Judged by the episode server from the simulated state.

**Controls.** `robo act STEER THROTTLE [--repeat N]` applies MetaDrive's own car action for N steps of 0.1 s: STEER in [-1, 1] sets the front-wheel angle (x 40 deg, positive = left); THROTTLE in [-1, 1] is engine force when positive and brake force when negative (full braking stops the car from 50 km/h in about 11 m); 0 coasts. After `robo done` the car brakes fully. Skills (`robo info` lists their arguments): `follow_route SPEED_KMH METERS` keeps the current lane along the route at a set speed (lane-centred steering plus cruise control) for METERS; it does NOT brake for vehicles or obstacles and it does not slow for curves, but it reports the nearest vehicle or object ahead in the lane. `change_lane left|right [SPEED_KMH]` steers into the adjacent lane and centres in it; it does not check for traffic or solid lines. `stop [METERS]` brakes to a standstill while keeping the lane, spread over about METERS (0 = brake hard). `wait SECONDS` stays stopped with the brakes on. A vehicle that rear-ends you, or one you cut in front of, still counts as a collision.

**Observation.** `robo observe` reports `ego` (`pos`, `heading_deg`, `speed_kmh`, last `steering` and `throttle`, size), `lane` (`road`, `index` (0 = leftmost), `count`, `lateral_offset_m` from the lane centre (+ = left), `width_m`, `station_m` along the road, `road_length_m`, `shape`, `left_line` / `right_line` types: broken lines may be crossed, solid ones may not), `route` (`travelled_m`, `remaining_m`, `total_m`, `route_completion`, `next_roads`, `destination`, `in_destination_zone`), `vehicles` (per vehicle: `id`, `kind`, `rel_ahead_m` / `rel_left_m` in your car's frame, `distance_m`, `speed_kmh`, `heading_rel_deg`, its `road` and `lane`, and for vehicles on your route `route_ahead_m` (negative = behind), `gap_m` (bumper to bumper) and `in_my_lane`; `broken_down` for a stopped car with hazard lights), `obstacles` (same position fields) and `events`. Cameras: `topdown` (default; follows the car, about 96 m across) and `route_map` (the whole route); `robo observe --image [--camera route_map]` saves one.

The step budget is 700 steps (70 s of driving).

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the scoring, or other files to succeed; the episode server judges the final physical state itself.

```
robo info                          # the robot, its sensors, action groups, skills and step budget
robo observe                       # robot and scene state as numbers
robo observe --image [--camera C]  # also saves a camera image and prints its path (open it to look)
robo act V1 V2 ... [--repeat N]    # one low-level action (the action groups under Controls), applied N times (N <= 50)
robo skill NAME ARG ...            # run a skill listed by `robo info`; it runs until it finishes and reports the result
robo done "short summary"          # end the episode and ask for scoring
robo give-up "reason"              # end the episode without claiming success
```

- Positions are in metres in the world frame (+z up); angles are in degrees unless a field says otherwise.
- The episode has a fixed step budget (see `robo info`); every simulated control step counts, including the steps a skill runs.
- Skills are ordinary controllers: they can fail, stop early or be blocked by the scene. Read what they report and re-observe.
- Success is judged about 10 steps after you call `robo done`, with the robot holding still (zero action), so the goal must still be true when the robot stops.
- Call `robo done` exactly once when finished.

