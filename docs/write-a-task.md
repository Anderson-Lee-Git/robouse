# Write a task

The quickest way to a new task is to compose it from components: pick an embodiment, a scene and a task template, and `robouse tasks init` writes and validates the task folder (see [Components](components.md)). Then write a reference solution of your own for it, or add a component (a task template, a scene or an embodiment). `robouse tasks init DIR` scaffolds a blank task folder instead, for a backend of your own.

## Compose a task

```console
$ robouse tasks init --embodiment franka-panda --scene tabletop --task put-in-container --out mytasks
wrote mytasks/put-in-container--franka-panda--tabletop--s0
oracle reward 1.0 (done, 159 steps); noop reward 0.0 (done)
accepted: oracle 1, noop 0
```

The markdown body of `task.md` is what the agent reads. For this seed it starts with the goal: "Put the yellow block in the grey tray. Leave the other objects where they are."

## Write the reference solution

`oracle/solve.sh` runs with `robo` on its `PATH`, like an agent, and may use only what an agent could: `robo info` for the robot's skills and action groups, `robo observe --json` for positions, and the skills. Replace it with this script, which works for any robot that grasps from above (the Franka Panda, and ALOHA 2, whose `move_to` picks the arm nearer the target and whose `grasp` and `release` use the arm that moved last). It names the object and the container, never a coordinate:

```sh
#!/bin/bash
# Reference solution for put-in-container on a top-grasp arm or bimanual rig: poses come from robo observe --json,
# motion from the declared skills (move_to, grasp, release).
set -euo pipefail
export OBJ=yellow_block CONTAINER=tray   # names from the task (robo observe lists them), not coordinates
python3 - <<'PY'
import json, os, subprocess

def robo(*args):  # one robo command; returns its result
    out = subprocess.run(["robo", *map(str, args), "--json"], check=True, capture_output=True, text=True).stdout
    r = json.loads(out)
    if not r.get("ok"):
        raise SystemExit(f"robo {' '.join(map(str, args))}: {r.get('error')}")
    return r["result"]

skills = {s["name"] for s in robo("info")["embodiment"]["skills"]}
assert {"move_to", "grasp", "release"} <= skills, f"needs move_to/grasp/release, has {sorted(skills)}"
st = robo("observe")["state"]
assert st["robot"]["grasp"].startswith("top-down"), "this solution grasps from above"
obj, cont_name = os.environ["OBJ"], os.environ["CONTAINER"]
cont = st["fixtures"][cont_name]  # center, rim height, inner size

o = st["objects"][obj]
x, y, z = o["pos"]
half = (o["size"].get("box_m") or [0, 0, o["size"].get("height_m", .05)])[2] / 2
bottom, top = z - half, z + half
robo("skill", "release")
robo("skill", "move_to", x, y, top + .07)
robo("skill", "move_to", x, y, bottom + min(half, .03))
robo("skill", "grasp")
robo("skill", "move_to", x, y, cont["rim_height_m"] + 2 * half + .06)
cx, cy, _ = cont["center"]
robo("skill", "move_to", cx, cy, cont["rim_height_m"] + 2 * half + .06)
robo("skill", "move_to", cx, cy, cont["rim_height_m"] + min(half, .03) + .01)
robo("skill", "release")
robo("skill", "move_to", cx, cy, cont["rim_height_m"] + 2 * half + .06)
robo("done", f"put the {obj} in the {cont_name}")
PY
```

Run it, and the no-op control:

```console
$ robouse run --task mytasks/put-in-container--franka-panda--tabletop--s0 --agent oracle --engine local --out runs/mine
  ...
  "reward": 1.0,
  "outcome": "done",
$ robouse run --task mytasks/put-in-container--franka-panda--tabletop--s0 --agent noop --engine local --out runs/mine
  ...
  "reward": 0.0,
```

The same script, copied into the task that `robouse tasks init --embodiment aloha-2 --scene tabletop --task put-in-container --out mytasks` writes, scores 1 there too. A robot that grasps from the front (PAL TIAGo, the Google Robot) needs a different approach: drive the base in front of the surface with `go_to`, then move the gripper in level along the robot's heading; `robo observe` reports the robot's `grasp` and `workspace` so a solution (or an agent) can tell which it has. The bundled reference solution, `src/robouse/backends/components_sim/strategies.py`, handles every embodiment that way.

Existing tasks on the tabletop, menagerie and RoboHarm suites also accept the arm shorthands `robo move-to X Y Z [--grip G]` and `robo grip G`; they map onto the arm's `move_to` and gripper skills.

## Write a component

Components live in the repository: the runtime code in `src/robouse/backends/components_sim/`, and one generated manifest per component in `components/`. After changing the code, rewrite the manifests and check the combinations you care about:

```sh
robouse components export
robouse components check franka-panda tabletop put-in-container
```

`tests/test_components.py` fails if a checked-in manifest differs from a fresh export.

**A task template** is a class in `templates.py` with:

- `variants`: the placements and capabilities it needs, for example `({"mounts": ["arm", "bimanual", "floor"], "caps": ["reach", "grasp"]},)`; the resolver matches embodiments against them;
- `capabilities` tags (`spatial-reasoning`, `topological-reasoning`, `contact-rich`, `long-horizon`, `perception`, ...) and a `difficulty`;
- `needs`: what the scene must stock (`containers`, `object_kinds_any`, `tags`, `surfaces`, `floor_slots`);
- `generate(ctx)`: lays out the objects and fixtures from the scene's regions (`ctx.regions()`, `ctx.spot(...)`) with the seeded `ctx.rng`, and returns the goal, the instruction (`task`), the success rule in words (`success`) and a step budget. Raise `Incompatible("why")` when the scene cannot host it;
- `check(b)`: the physical success predicate over the simulated state (`b.obj_pos`, `b.in_container`, `b.touches_surface`, `b.touch_robot`, ...), returning `(ok, details)`;
- `solve(r, inst)`: the reference solution through the socket, built from `strategies.Robo`'s helpers (`pick`, `place_in`, `place_on_point`, `travel_to`, `inspect`, ...), which read the robot's capabilities rather than assuming one.

Add the instance to `TEMPLATES` and its one-line summary to `TASKS` in `src/robouse/components/catalog.py`. `put-in-container` (`PutInContainer`) is the shortest template to copy.

**A scene** is a function in `scenes.py` returning a `Layout`: its scenario tag, floor area, work surfaces (height, size, the sides a floor robot can reach them from), obstacles, the placements it offers (`arm` and `bimanual` mounts with their work area, a `floor` start pose, an `airspace` pad), free floor areas, inspection-tag places, the object kinds and containers it stocks, and cameras. Register it in `SCENES` and describe it in `catalog.SCENES`.

**An embodiment** is a `Driver` in `robots.py`: it attaches the robot's model (MuJoCo Menagerie) to the scene at its placement, declares its action groups and skills (the embodied spec that `robo info` reports), runs its controllers every physics step, reports its state, and implements the shared skills it has (`move_to`, `grasp`, `release`, `home`, `go_to`, `turn`, `look_at`, `takeoff`, `fly_to`, `land`) as generators that yield one action per control step. Declare its `mount`, `caps`, `grasp_mode` and `max_grip`, register it in `DRIVERS`, and add its title, track, licence and summary to `catalog.EMBODIMENTS`.
