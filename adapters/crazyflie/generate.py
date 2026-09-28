"""Crazyflie suite -> Robo Use tasks (suite "crazyflie"): one or three Bitcraze Crazyflie 2 nano-quadrotors (MuJoCo
Menagerie, MIT) in an indoor flight arena. Backend, scene, controller, skills, judge and reference solutions:
src/robouse/backends/crazyflie.py.

Usage: python adapters/crazyflie/generate.py [--out tasks/crazyflie]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.crazyflie import GATES, PADS, SHELF, TASKS, WAYPOINTS, WINDOW, CrazyflieBackend
from robouse.backends.embodied import write_embodied_task
from robouse.prompts import EMBODIED_USAGE

SCENE = ("You fly {who} (MuJoCo Menagerie model; 27 g and 9 cm across each) in an indoor flight arena. World frame in metres: +x "
         "east, +y north, +z up, floor at z = 0. The arena is 8 m x 6 m (x from -4 to 4, y from -3 to 3) and 3 m high, closed by "
         "walls and a ceiling. A full-height partition wall at x = 1.5 separates the west hall from the east room; the only way "
         "through it is a 0.36 m x 0.36 m window centred at (1.5, 1.8, 1.0). The west hall has a `home` pad, a teal pad `A`, three "
         "square racing gates (orange frames, 0.5 m openings) and three swarm pads `S0`, `S1`, `S2`; the east room has a yellow pad "
         "`B` and a 0.9 m high shelf with a white landing platform (0.3 m square) on top. Pads are 0.3 m squares. Every position is "
         "listed under `arena` in `robo observe`. Touching anything other than the floor, a pad or the platform is a crash and fails "
         "the task{swarm_rule}.")

SINGLE_CONTROLS = ("**Controls.** `robo act VX VY VZ YAW_RATE` sets the velocity setpoint for the next step(s), each in [-1, 1]: VX, VY, VZ "
                   "along world x, y, z (x 1 m/s) and YAW_RATE (x 90 deg/s, counter-clockwise seen from above). One step is 50 ms; "
                   "`--repeat N` holds a setpoint for N steps. An onboard cascaded controller (velocity -> attitude -> thrust and body "
                   "moments) tracks the setpoint. An all-zero action holds the current position; resting on a surface with VZ <= 0 the "
                   "motors stay off, so take off with a positive VZ. Skills (`robo info` lists them with their arguments): `takeoff "
                   "[Z]`, `goto X Y Z [TOL]` (straight line, stops at the point; it does not avoid obstacles), `turn YAW_DEG`, `land` "
                   "(straight down onto whatever is below, then motors off) and `hover [SECONDS]`.")
SWARM_CONTROLS = ("**Controls.** `robo act VX0 VY0 VZ0 VX1 VY1 VZ1 VX2 VY2 VZ2` sets the velocity setpoints of drones cf0, cf1 and cf2 for "
                  "the next step(s), each in [-1, 1] (x 1 m/s along world x, y, z); headings stay fixed. One step is 50 ms; `--repeat "
                  "N` holds the setpoints for N steps. A drone whose three values are all zero holds its position; resting on a "
                  "surface with VZ <= 0 its motors stay off. Skills: `takeoff_all [Z]`, `goto ID X Y Z [TOL]` (one drone flies in a "
                  "straight line while the others hold position), `goto_all X0 Y0 Z0 X1 Y1 Z1 X2 Y2 Z2 [TOL]` (all at once, straight "
                  "lines, no collision avoidance), `land ID`, `land_all` and `hover [SECONDS]`.")
SINGLE_OBS = ("**Observation.** `robo observe` reports `drones` (one entry: `pos`, `vel`, `yaw_deg`, `roll_deg`, `pitch_deg`, `landed_on` "
              "(the pad or surface it rests on, else null) and `motors_on`), `arena`, `progress` where the task counts something, and "
              "`safety_events`. Cameras: `cf0/chase` (default, behind the drone), `cf0/fpv` (forward), `overview` (the west hall) and "
              "`east_room`.")
SWARM_OBS = ("**Observation.** `robo observe` reports `drones` (per drone: `id`, `pos`, `vel`, `yaw_deg`, `roll_deg`, `pitch_deg`, "
             "`landed_on`, `motors_on`), `arena` and `safety_events`. Cameras: `swarm` (default, the swarm pads from the south), "
             "`cf0/chase`, `cf1/chase`, `cf2/chase`, `overview` (the west hall) and `east_room`.")


def _usage(t: dict) -> str:
    if t.get("skills") is not False:
        return EMBODIED_USAGE
    lines = [l for l in EMBODIED_USAGE.split("\n") if not l.startswith(("robo skill", "- Skills are"))]
    return "\n".join(lines)


def _wp() -> str:
    return ", ".join(f"({x}, {y}, {z})" for x, y, z in WAYPOINTS)


def _gates() -> str:
    dirs = {(0, 1): "northward (+y)", (0, -1): "southward (-y)", (1, 0): "eastward (+x)", (-1, 0): "westward (-x)"}
    return "; ".join(f"{g['name']} centred at {g['c']}, passed {dirs[g['normal']]}" for g in GATES)


TEXT = {
    "crazyflie-waypoints": dict(
        title="Waypoint tour", difficulty="easy", category="navigation",
        goal=f"Take off from the `home` pad, fly through these four waypoints in this order: {_wp()}, then land on pad `A` at {PADS['A']}.",
        success=("each waypoint was reached in order (the drone's centre within 0.10 m of it), and the drone rests on pad `A` with no "
                 "crash; `progress.waypoints_reached` counts the waypoints reached so far")),
    "crazyflie-gates": dict(
        title="Gate course", difficulty="medium", category="navigation",
        goal=f"Take off from the `home` pad and fly through the three gates in order, each in its pass direction: {_gates()}. Then land on pad `A`.",
        success=("the drone's centre crossed each gate's plane inside its 0.5 m opening, in the pass direction and in the order G1, G2, "
                 "G3 (a gate crossed out of order fails the course), and the drone rests on pad `A`; touching a gate frame or post is a "
                 "crash; `progress.gates_passed_in_order` counts the gates passed")),
    "crazyflie-window": dict(
        title="Through the window", difficulty="medium", category="navigation",
        goal=f"Take off from the `home` pad in the west hall, fly through the window in the partition wall into the east room, and land on pad `B` at {PADS['B']}.",
        success="the drone rests on pad `B`, with no crash at any time"),
    "crazyflie-window-manual": dict(
        title="Through the window, no autopilot", difficulty="hard", category="low-level control",
        goal=(f"Take off from the `home` pad in the west hall, fly through the window in the partition wall into the east room, and "
              f"land on pad `B` at {PADS['B']}. In this task the skills are disabled: fly with `robo act` velocity setpoints only, "
              f"closing the loop yourself with `robo observe`."),
        success="the drone rests on pad `B`, with no crash at any time"),
    "crazyflie-shelf-landing": dict(
        title="Land on the shelf", difficulty="medium", category="navigation",
        goal=(f"Take off from the `home` pad, get into the east room (through the window), and land on the white platform on top of "
              f"the shelf at ({SHELF['c'][0]}, {SHELF['c'][1]}, {SHELF['h']})."),
        success="the drone rests on the platform (touching it, slower than 0.1 m/s), with no crash at any time"),
    "crazyflie-swarm-formation": dict(
        title="Triangle formation", difficulty="medium", category="multi-robot",
        goal=("Three drones rest on pads `S0`, `S1` and `S2`. Fly them into a horizontal equilateral triangle with 0.6 m sides whose "
              "centre is at (-1.9, -0.3), all three at height 1.2 m, and hold it."),
        success=("all three drones are within 0.05 m of 1.2 m height, the triangle's centroid is within 0.10 m of (-1.9, -0.3), every "
                 "side is 0.6 m +- 0.06 m, and every drone moves slower than 0.1 m/s; any crash, or two drones ever closer than 0.2 m, fails")),
    "crazyflie-swarm-swap": dict(
        title="Swap two drones", difficulty="hard", category="multi-robot",
        goal=("Three drones rest on pads: cf0 on `S0`, cf1 on `S1`, cf2 on `S2`. Swap cf0 and cf2: cf0 must end on `S2` and cf2 on "
              "`S0`, both landed; cf1 must end on `S1` (it may move in between)."),
        success=("cf0 rests on `S2`, cf1 on `S1` and cf2 on `S0`; any crash, or two drones ever closer than 0.2 m (centre to centre), "
                 "fails the task")),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "crazyflie"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for tid, t in TASKS.items():
        x = TEXT[tid]
        swarm = t["n"] > 1
        be = CrazyflieBackend({"env": tid})
        parts = [f"# {x['title']}",
                 SCENE.format(who="three Bitcraze Crazyflie 2 nano-quadrotors (cf0, cf1, cf2)" if swarm else "a Bitcraze Crazyflie 2 nano-quadrotor",
                              swarm_rule="; so does a collision between drones" if swarm else ""),
                 "## Task\n\n" + x["goal"],
                 f"**Success:** {x['success']}. Judged by the episode server from the simulated state after you call `robo done` and the drones have held still for 10 steps. A drone \"rests on\" a pad or the platform when it touches it, moves slower than 0.1 m/s and is tilted less than 20 degrees.",
                 SWARM_CONTROLS if swarm else (SINGLE_CONTROLS.split(" Skills (")[0] + " `robo skill` is disabled in this task."
                                               if t.get("skills") is False else SINGLE_CONTROLS),
                 SWARM_OBS if swarm else SINGLE_OBS,
                 f"The step budget is {t['max_steps']} steps ({t['max_steps'] * 0.05:.0f} s of flight).", _usage(t)]
        write_embodied_task(out, task_id=tid, backend="crazyflie", suite="crazyflie", title=x["title"], instruction="\n\n".join(parts) + "\n",
                            robot="Bitcraze Crazyflie 2", category=x["category"], difficulty=x["difficulty"],
                            tags=["aerial", "quadrotor", "crazyflie", "menagerie", "mujoco"] + (["swarm"] if swarm else []),
                            max_steps=t["max_steps"], camera=be.camera, cameras=be.decl.cameras,
                            oracle_note=("a proportional controller on the drone's predicted stopping point, through robo act only."
                                         if t.get("skills") is False else "scripted flight with the goto/land skills."),
                            extra_robouse={"skills": False} if t.get("skills") is False else None)
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
