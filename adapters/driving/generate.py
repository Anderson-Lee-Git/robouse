"""Driving suite -> Robo Use tasks (suite "driving"): a passenger car on MetaDrive's procedural roads (MetaDrive 0.4.3,
Apache-2.0). Backend, scenes, skills, judge and reference solutions: src/robouse/backends/driving.py (the simulator runs
in its own virtualenv through src/robouse/backends/driving_worker.py; setup in docs/suites/driving.md). The generator
starts each scene once to read the route facts it writes into the instruction, so it needs that virtualenv too.

Usage: python adapters/driving/generate.py [--out tasks/driving]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.driving import CONTROL_DT, MAX_KMH, TASKS, DrivingBackend
from robouse.backends.embodied import write_embodied_task
from robouse.prompts import EMBODIED_USAGE

SCENE = ("You drive a passenger car (MetaDrive's default sedan: 4.5 m long, 1.85 m wide, Bullet vehicle dynamics, no engine force "
         f"above {MAX_KMH:.0f} km/h) on a road map built by the MetaDrive driving simulator. Map frame in metres: `x`, `y` on the ground, "
         "`heading_deg` 0 along +x and counter-clockwise positive; the top-down camera shows +y up. Traffic drives on the right. The two "
         "directions of a road are separated by a solid yellow centre line (drawn yellow in the top-down view), which you must never "
         "touch or cross. Lanes of your direction are numbered from the left: lane 0 is the one next to the yellow centre line. Roads are "
         "named by MetaDrive node pairs (e.g. `>>>->1S0_0_`). The navigation route is fixed: `robo observe` gives, under `route`, the "
         "distance travelled and remaining, the next roads (distance to their start, lane count and shape: straight, or a curve with its "
         "radius and turn angle) and the destination. Road users within 60 m are listed under `vehicles` and road objects (cones, "
         "warning triangles, barriers) under `obstacles`, with their position in your car's frame, their distance along your route and "
         "their lane. Other drivers follow MetaDrive's car-following model: they brake for what is ahead in their lane, but they do not "
         "yield to you at junctions and do not make room when you cut in. Simulated time advances only when you act; the scene is paused "
         "while you think.")

SUCCESS = ("you must bring the car to a stop inside the destination zone: from 5 m before the end of the route's final road to 5 m past "
           "it, in any lane of that road (`route.in_destination_zone`; `route.remaining_m` is the distance to the end of the final road, so "
           "stop with it between -5 and 5). After you call `robo done` the car brakes fully for 10 steps; then it must be at rest (below "
           "2 km/h) inside the zone, and at no time may it have collided with a vehicle or object, touched the road edge or sidewalk, left "
           "the road or touched a solid lane line (MetaDrive's out-of-road rule), or cut off another driver (a vehicle behind you in your "
           "lane closing in with less than a 1 s time gap, because you cut in front of it or braked hard in front of it){extra}. "
           "Violations are listed under `events` as they happen, and any event fails the task. Judged by the episode server from the "
           "simulated state")

YIELD = (", or entered the roundabout without giving way: while your car is on the entry road given in `route.give_way` (`road`), no "
         "other vehicle may be within 15 m of the conflict point `route.give_way.point` and approaching it, or less than "
         "`route.give_way.window_s` seconds away from it")

CONTROLS = ("**Controls.** `robo act STEER THROTTLE [--repeat N]` applies MetaDrive's own car action for N steps of 0.1 s: STEER in [-1, 1] "
            "sets the front-wheel angle (x 40 deg, positive = left); THROTTLE in [-1, 1] is engine force when positive and brake force when "
            "negative (full braking stops the car from 50 km/h in about 11 m); 0 coasts. During the 10-step settle after `robo done` the "
            "wheels are straightened and the brakes are fully on (STEER 0, THROTTLE -1). Skills (`robo info` lists their arguments): "
            "`follow_route SPEED_KMH METERS` keeps the current lane along the route at a set speed (lane-centred steering plus cruise "
            "control) for METERS; it does NOT brake for vehicles or obstacles and it does not slow for curves, but it reports the nearest "
            "vehicle or object ahead in the lane; if the lane ends (an acceleration lane) it keeps going straight off its end. "
            "`change_lane left|right [SPEED_KMH]` steers into the adjacent lane and centres in it; it does not check for traffic or solid "
            "lines. `stop [METERS]` brakes to a standstill while keeping the lane, spread over about METERS (0 = brake hard). `wait "
            "SECONDS` stays stopped with the brakes on.")

OBSERVATION = ("**Observation.** `robo observe` reports `ego` (`pos`, `heading_deg`, `speed_kmh`, last `steering` and `throttle`, size), "
               "`lane` (`road`, `index` (0 = leftmost), `count`, `lateral_offset_m` from the lane centre (+ = left), `width_m`, `station_m` "
               "along the road, `road_length_m`, `shape`, `left_line` / `right_line` types: broken lines may be crossed, solid ones may not), "
               "`route` (`travelled_m`, `remaining_m`, `total_m`, `route_completion`, `next_roads`, `destination`, `in_destination_zone`, "
               "and `give_way` where a give-way rule applies), `vehicles` (per vehicle: `id`, `kind`, `rel_ahead_m` / `rel_left_m` in your "
               "car's frame, `distance_m`, `speed_kmh`, `heading_rel_deg`, its `road` and `lane`, and for vehicles on your route "
               "`route_ahead_m` (negative = behind), `gap_m` (bumper to bumper) and `in_my_lane`; `broken_down` for a stopped car with hazard "
               "lights), `obstacles` (same position fields) and `events`. Cameras: `topdown` (default; follows the car, about 96 m across) "
               "and `route_map` (the whole route); `robo observe --image [--camera route_map]` saves one.")

TEXT = {
    "driving-winding-road": dict(
        title="Winding mountain road", difficulty="easy", category="lane keeping",
        goal=("Drive the two-lane mountain road to its end and stop at the destination. You start at rest in the right lane (lane 1). "
              "There is no other traffic, but the road has tight bends and an S-bend (see each road's `shape`): too fast and the car "
              "runs wide over the edge line."),
        tags=["lane-keeping", "curves"]),
    "driving-highway-overtake": dict(
        title="Overtake slow traffic on the highway", difficulty="medium", category="traffic",
        goal=("Drive the three-lane highway to the destination and stop there, within the step budget. You start at rest in the right lane "
              "(lane 2). A truck at about 30 km/h is ahead of you in your lane and other slow vehicles drive in the middle and right lanes "
              "further on; faster cars come from behind in the left lane. Staying behind the truck is too slow for the budget, so you have "
              "to pass safely: change lanes only into a gap, and do not cut in front of faster cars."),
        tags=["highway", "overtaking", "traffic"]),
    "driving-broken-down-car": dict(
        title="Pass a broken-down car", difficulty="medium", category="traffic",
        goal=("Drive the two-lane road to the destination and stop there. A car has broken down in your lane (the right lane, lane 1) "
              "about 90 m ahead, with a warning triangle 12 m behind it. Cars pass in the left lane at about 50 km/h. Get around the "
              "breakdown through the left lane without hitting the triangle or the car and without cutting off the passing traffic; "
              "stop and wait behind the triangle if the left lane is not clear."),
        tags=["obstacle", "lane-change", "traffic"]),
    "driving-cone-zone": dict(
        title="Construction zone on a curve", difficulty="medium", category="obstacles",
        goal=("Drive the three-lane road to the destination and stop there. You start in the right lane (lane 2). On the curve ahead a "
              "construction zone closes the two right lanes: a taper of traffic cones and a barrier, then a row of cones along the "
              "closed lanes. Move into the open lane (lane 0) in time, keep a safe distance to the slower car in that lane, and do not "
              "touch any cone."),
        tags=["construction", "cones", "lane-change"]),
    "driving-roundabout": dict(
        title="Roundabout", difficulty="medium", category="traffic",
        goal=("Drive through the two-lane roundabout to the destination and stop there. The route enters the roundabout, goes about three "
              "quarters of the way round and takes the third exit (see `route.next_roads`). A queue of cars circulates in the outer lane "
              "past your entry (entering from the north arm and leaving by the south exit); circulating traffic has the right of way, so "
              "stop before the entry and give way (the rule is in `route.give_way`)."),
        tags=["roundabout", "traffic"]),
    "driving-intersection-left-turn": dict(
        title="Unprotected left turn", difficulty="hard", category="traffic",
        goal=("At the four-way intersection ahead (no traffic lights), turn left onto the northbound road and stop at the destination. "
              "You start in the left lane (lane 0). A dense stream of oncoming cars comes from the east arm in both lanes and goes "
              "straight through at about 40 km/h; they have the right of way and do not stop for you. Stop before the junction, wait "
              "for a safe gap, then turn."),
        tags=["intersection", "left-turn", "yield", "traffic"]),
    "driving-ramp-merge": dict(
        title="Merge from an on-ramp", difficulty="hard", category="traffic",
        goal=("You start on an on-ramp. It joins the right side of a three-lane highway as a short acceleration lane (lane 3 of 4, "
              "about 38 m long, then it ends). A long platoon of vehicles drives in the highway's right lane (lane 2) at about 50 km/h. "
              "Merge into lane 2 through a safe gap (or behind the platoon; you may stop at the end of the ramp to wait) before the "
              "acceleration lane ends, then drive to the destination and stop there."),
        tags=["merge", "on-ramp", "traffic"]),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "driving"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for tid, t in TASKS.items():
        x = TEXT[tid]
        be = DrivingBackend({"env": tid})
        be.reset(0)
        st = be.observe()
        be.close()
        rt = st["route"]
        facts = (f"The route is {rt['total_m']:.0f} m long ({len(be.meta['route']['roads'])} roads); the destination is at "
                 f"({rt['destination']['pos'][0]:.1f}, {rt['destination']['pos'][1]:.1f}), at the end of road `{rt['destination']['road']}`. "
                 f"You start at ({st['ego']['pos'][0]:.1f}, {st['ego']['pos'][1]:.1f}), heading {st['ego']['heading_deg']:.0f} deg, in lane "
                 f"{st['lane']['index']} of {st['lane']['count']}.")
        steps = int(t["max_steps"])
        parts = [f"# {x['title']}", SCENE, "## Task\n\n" + x["goal"] + " " + facts,
                 f"**Success:** {SUCCESS.format(extra=YIELD if t.get('yield_rule') else '')}.", CONTROLS, OBSERVATION,
                 f"The step budget is {steps} steps ({steps * CONTROL_DT:.0f} s of driving).", EMBODIED_USAGE]
        write_embodied_task(out, task_id=tid, backend="driving", suite="driving", title=x["title"],
                            instruction="\n\n".join(parts) + "\n", robot="MetaDrive sedan", category=x["category"],
                            difficulty=x["difficulty"], tags=["driving", "wheeled", "metadrive"] + x["tags"],
                            max_steps=steps, camera=be.camera, cameras=be.decl.cameras,
                            oracle_note="scripted driving with the follow_route/change_lane/stop/wait skills and the public observation.",
                            extra_metadata={"source_benchmark": "robouse original (driving suite; MetaDrive 0.4.3)",
                                            "simulator": "MetaDrive 0.4.3 (Apache-2.0)"})
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
