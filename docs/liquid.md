# RoboCasa liquid physics reference

Researcher-only; never expose to evaluated policies.

Generic solver, API and implementation reference. Modules live in
`src/robouse/backends/robocasa/physics/liquid/` and load through
`robouse.backends.robocasa.physics.load_liquid()` as `robouse_robocasa_liquid`.
The backend must not import a benchmark task package. Container kinds are registered
by host plugins; an unknown kind is an error. Benchmark-specific version selection,
asset profiles, predicates and adoption decisions belong to the consuming suite.

## Coupling and rendering

- A DFSPH liquid (SPlisHSPlasH via `pysplishsplash`) runs beside MuJoCo, in MuJoCo's world frame.
- **One-way coupling.** After every MuJoCo step, the fluid advances to the same time.
  - The boundaries are the explicitly selected MuJoCo geometry: moving container meshes and configured static supports/walls.
  - Within one MuJoCo step, the boundaries move along a straight line, and rotate along the shortest arc, from the pose before the step to the pose after it.
  - The liquid exerts no force on MuJoCo and has no mass in it. A full bottle weighs what its MuJoCo model says. Nothing can knock the liquid's container over through the liquid.
- **Rendering.** Before a frame is drawn, the particles are turned into a surface mesh (splashsurf). The mesh is written into a preallocated, visual-only mesh geom of the model and uploaded to the render context.
  - Lights, shadows, anti-aliasing, resolution, cameras and the render call stay exactly as they were.
  - The surface is reconstructed once per fluid state and shared by both views.
- **Queries** (researcher side) report:
  - volume per container
  - volume on the counter and its puddle (area, largest patch, thickness)
  - volume through the counter (a leak) and non-finite particles
  - volume elsewhere (in flight or off the counter)
- **Reset.** `LiquidCoupling.reset()` puts the liquid back to its exact initial state. Restore the MuJoCo state first.

## Install (login node; compute nodes have no internet)

```
uv pip install --python .cache/robocasa/robocasa-venv/bin/python pysplishsplash==2.19.0 pysplashsurf==0.14.1.0
```

- This goes into RoboCasa's interpreter only. `pyproject.toml` and `uv.lock` are unchanged.
- `pysplishsplash` is CPU-only (OpenMP) and its `Real` is float32.
- Importing it crashes the process (SIGSEGV in the GL dispatcher) unless the system `libGLdispatch.so.0` is loaded globally first. `solver.sph()` does that, so always import through it.

## API

The following generic modules are in `robouse/backends/robocasa/physics/liquid/`.

| module | what |
|---|---|
| `solver.py` (robouse) | `FluidParams` (material and solver settings), `Boundary`, `SPHFluid`: `advance(t, pose_at)`, `settle()`, `reset()`, `positions()`, `velocities()`, `initial_state()` |
| `coupling.py` (robouse) | `LiquidCoupling(sim, fluid, bodies, renderer).install()`. It wraps `sim.step`/`step2` (pre-step hooks, then step, then fluid sync) and `sim.render` (surface refresh). Also `reset()` and `timing` |
| `surface.py` (robouse) | `add_to_robosuite_model()` adds the liquid mesh geom at build time; `SurfaceRenderer` reconstructs the surface and uploads it |
| `queries.py` (robouse) | `Container` (inside profile), `Surface` (counter top), `partition()` (a label per particle), `volumes_ml()`, `puddle()` |
| `scene.py` (robouse) | Opt-in glue for robouse's worker: `enable_surface(S)` before the build, `attach(env, cfg, workdir)` after `make_scenario`. Returns a `LiquidScene` with `volumes_ml()`, `puddle()` and `report()` |
| `contact.py` (robouse) | `MeshContact` (exact mesh distances), `Absorber`, `PuddleSleep`, `ContainerSleep` |
| `meshes.py` (robouse) | Surfaces of revolution, boxes, MuJoCo body meshes, lattices and `puddle_fill` |

Example host integration (supply a configured worker and registered containers):

```python
from robouse.backends.robocasa.physics import load_liquid
scene = load_liquid("scene")
# S and W are the host scenario and worker modules.
scene.enable_surface(S)                      # before any scenario class is made
w = W.Worker(); w.make_scenario(spec, seed, "eef")
ls = scene.attach(w.env, {"source": "bottle", "fill_ml": 250,
                          "containers": {"bottle": "liquid_juice_bottle", "glass": "liquid_tumbler"},
                          "surface": {"fixture": "counter", "half_extent_m": 0.2,
                                      "centre_between": ["bottle", "glass"]}},
                  workdir, threads=4)

ls.volumes_ml()   # {"bottle": ml, "glass": ml, "surface": ml, "elsewhere": ml, "below": ml, "nonfinite": ml}
ls.puddle()       # {"area_m2", "largest_patch_m2", "thickness_m", "bbox_xy", "centroid_xy", "particles"}
```

## Boundary and reset requirements

Register every container kind with a closed walled boundary mesh and an inside
profile, versioned with the container asset. MuJoCo collision may use primitives.
`attach` generates the fill and performs configured damped settling (default 0.3 s).
To skip settling, supply `x0` from `fluid.initial_state()`; ship the settled state
with immutable task assets. Only explicitly supplied boundaries collide with fluid.
Fingers are not automatically boundaries. A square counter patch is limited by
`half_extent_m`; fluid leaving it is labeled `elsewhere`. Cost grows with nearby
boundary particles.

## Material and solver settings (`FluidParams` defaults)

| setting | value | why |
|---|---|---|
| particle radius | 1.25 mm (2.5 mm spacing; 250 ml = 16 000 particles) | reference default |
| method | DFSPH, density error 0.05 %, divergence error 0.1 % | |
| viscosity | Weiler 2018, 1e-4 m^2/s; wall friction 1e-3 | at 1e-5 the viscosity solver does nothing, and a spill races off the counter as a monolayer at > 1 m/s. This is an effective value for this resolution without surface tension, not juice's real viscosity |
| surface tension, adhesion | **off by default** | Select each instantiated model's own parameter IDs; IDs remain -1 until instantiation. Read coefficients back from `fluid.material`. |
| time step | ours: CFL 0.5, 0.05–2 ms, landing exactly on every MuJoCo step (2 ms) | SPlisHSPlasH's own CFL control is off; its clock is float32, ours float64 |
| z-sort | off | with it on, a reset does not reproduce the run bit for bit |
| boundaries | Akinci samples of the visual meshes; counter = a 2-layer sample grid on its top face only | far fewer samples than the whole counter box |

## Versioned extensions

### Container-free puddles, shelves and walls

`meshes.puddle_fill(polygon, volume_ml, z, spacing)` returns a deterministic
lattice above a simple, possibly concave XY footprint. Requested volume is
rounded to the nearest particle; a partial top layer is distributed over the
footprint. It raises for an undersized footprint or invalid inputs.

```python
cfg = {
    "version": "0.2.0",
    "containers": {},
    "puddle": {"polygon_xy": [[0, 0], [.1, 0], [.1, .08], [0, .08]],
               "volume_ml": 12},
    "surface": {"fixture": "shelf", "geom": "shelf_floor_collision",
                "centre_xy": [.05, .04], "half_extent_m": .15},
    "boundaries": {
        "back_wall": {"body": "shelf_root", "groups": [0],
                      "name_contains": "back", "animated": False},
        "bag": {"object": "bag", "groups": [0]},
    },
    "settle_s": 0,
    "sleep": {"initially_frozen": True},
    "threads": 4,
}
```

Names in this example are placeholders for actual compiled model names. An
explicit horizontal box `surface.geom` bypasses the old `<fixture>_top*`
lookup, so an open-shelf floor is usable. Static wall boundaries use their
actual geometry; the support query respects the union of real rectangles,
including gaps. The square sampling patch must cover the relevant support.

`boundaries` accepts general objects or explicit MuJoCo body names. `groups`
and `name_contains` select the geometry; `meshes_only` excludes primitives.
Use collision geometry for solid contact proxies or carefully selected visual
meshes for hollow walls. Invisible `reg_*` volumes must never become boundaries.
Articulated children require separate body entries. Optional finger boundaries
can use their individual body names, but no automatic finger setup is supplied.

### Wetting, absorption and accounting

`LiquidScene.wetting_ml("bag")` measures **free** liquid within two particle
spacings of that boundary's mesh. Pass `distance_m` to change the query band.
The KD-tree broad phase is conservative; the final distances are exact
point-to-triangle distances. An empty container cavity is not its bounding box.
This reports nearby resolved liquid, not a molecular wetting film.

```python
cfg["boundaries"]["sponge"] = {"object": "sponge", "groups": [0]}
cfg["absorbers"] = {"sponge": {"capacity_ml": 100, "contact_m": .0025}}
```

The default contact band is one particle spacing. Only contacting particles are taken up. Capacity is rounded down to whole
particles and never exceeded. The reservoir is irreversible within an episode;
there is no squeezing, evaporation, saturation-dependent permeability or
capillary transport. Capacity is a host asset/scene parameter, not a calibrated uptake rate. [Cellulose sponge measurements](https://doi.org/10.1533/9781845698546.305)
report 10–15 g/g uptake for particular 0.08–0.12 g/cm³ samples; that is context,
not a measurement of an arbitrary host asset or its instantaneous uptake rate.

Absorbed particles retain their IDs and volume in an `absorbed:<tool>` ledger.
The native solver marks them `AnimatedByEmitter` and isolates them in a sparse
reservoir outside the scene. This is the numerical representation of liquid
inside an unresolved absorbent, not deletion or a visible teleport. Spatial
queries override reservoir labels; the renderer uses `free_mask`; reset clears
the ledger. `z_sort=True` is incompatible with absorption and raises.
Conservation is free liquid + every absorbed reservoir, with non-finite and
below-support particles still treated as errors. `state()` includes the ledger.

### Explicit sleep and clear-water rendering

`PuddleSleep` is an **opt-in approximation** for an initially supported puddle.
It advances the clock while freezing its authored positions. A moving boundary
within two spacings wakes it permanently. Distant motion does not wake it, and
flow is never silently re-frozen. This mode is not evidence of natural static
wetting equilibrium. Container sources cannot use it.

Use `surface.WATER_RGBA` (`[.75, .88, 1, .28]`) for alpha-blended clear water;
existing specular/shininess settings remain in the native policy renderer.
There is no refraction or caustics. Pass this RGBA to `enable_surface` or the
worker's `liquid.rgba`. Visual acceptance still requires the actual policy views.


## Native backend loading

Load an optional `native_backend` declaration containing `id`, asset-relative
`file`, `sha256` and `python_abi`. Resolve under `ROBOUSE_ROBOCASA_OBJECT_ROOT`;
validate containment, SHA256 and ABI before loading. A missing/mismatched backend
raises; never silently fall back. Use a fresh process for a different native
implementation because bindings and native singletons cannot safely mix.
`LiquidScene.report()` records the selected contract/backend; references also
record parameters, threads and OpenMP waiting settings. Dependency binaries,
licenses and platform-specific build provenance belong with versioned backend assets.

## Container sleep

`ContainerSleep` selects `sleep={"containers": true}` for an entire initial fill
contained in still containers. Owning-container translation or rotation wakes it,
even when walls are far from fluid; nearby moving boundaries also wake it.
Wake is permanent until reset. Do not freeze part of an active flow or
re-freeze a poured spill automatically.

## Validity contracts 0.4.x

`ValidatedSPHFluid` uses continuous particle trajectories against radius-expanded oriented boxes, including finite slab sides, actual gaps, walls and the floor. Contacts retain the particle and its volume, preserve tangential velocity and remove only inward normal velocity. This is an authored zero-restitution, free-slip contact approximation; corner expansion is conservative. It supplements the configured native Akinci pressure/viscosity boundaries. It adds neither liquid reaction loads nor GPU solving.

The externally selected timestep bounds relative motion using the largest free-particle speed plus the largest animated boundary translation/angular-radius speed, with gravity acquired over `dt_max`; the existing capillary bound also applies. A required step below `dt_min` is an error, rather than an upward clamp. Synchronization remainders may be shorter than `dt_min`. A completed native step moving any free particle more than one spacing is rejected before another neighborhood search. Free velocities are not magnitude-clipped.

Nonfinite or inconsistent states, particles embedded in selected solid material, particles below the actual floor or outside its modeled footprint, and unresolved contacts raise `LiquidValidityError`. The error is latched, including queries and sleeping calls, until an explicit reset. Rejected arrays and the free-particle mask are saved to the host-only work directory as `invalid-state.npz`. No particle is deleted or culled. Small geometric tolerances are numerical allowances: 2 micrometres for solid-interior tests, 1 micrometre outward contact offset, and one particle radius beyond the floor footprint.

Physical validity and grading regions are separate. A particle can enter laterally underneath a finite counter slab without crossing solid material. After physical validity succeeds, contract 0.4.0 accounts such a particle as `elsewhere`.  Invalid evidence never becomes a successful or safe outcome.


Contract 0.4.1 selects `ResolvedSPHFluid` / `ResolvedLiquidScene` in `validity_v2.py`.
Before projection, raw native speed must satisfy `speed * dt_min <= cfl * spacing`.
Resolve swept contact, then require accepted displacement at most one spacing.
Unresolved free-flight/lateral excess raises; no magnitude clipping or culling is permitted.
Save the first longer raw prediction that resolves validly to `resolved-prediction-first.npz`,
including old/predicted arrays, free mask and resolved free arrays. Reports include
prediction count and maximum predicted displacement as host diagnostics.

Contract 0.4.2 (`validity_v3.py`) includes the preceding raw native maximum speed
as another CFL bound after projection. Contract 0.4.3 (`validity_v4.py`) selects
`SubstepContactSPHFluid` / `SubstepContactLiquidScene`. After each valid accepted
native step, apply the existing mesh-distance/finite-capacity absorption rule at
the interpolated accepted-time pose, retaining rigid-sync uptake as well. Ownership
prevents duplicate uptake; accounted reservoirs preserve particle IDs and volume.
Invalid predictions raise before uptake. Contact distances, capacities, material,
velocity bounds and accepted-displacement limits remain unchanged. Earlier contracts
keep their classes and cadence. Benchmark adoption is the consuming suite's decision.

## Host compute validation

`compute.requirement(spec)` validates the optional host requirement without
importing solvers or inspecting hardware. `validate_runtime(spec)` checks requested
threads, allocation affinity, OSMesa and CUDA before simulator construction.
`validate_solver(compute, fluid)` checks actual backend, threads and GPU device
after attachment. `native_thread_count()` reads the selected loaded libgomp
without changing it; failure to identify that runtime is an error. The consuming
suite documents its versioned compute declaration and adoption gates.

## GPU contract 0.5.0

Explicit contract 0.5.0 selects `gpu/validity_gpu.py`, without a process-wide patch.
It combines Warp DFSPH kernels with the 0.4.3 finite-domain, continuous-contact,
validity, raw-speed CFL and accepted-substep uptake implementation. Domain/contact
work remains on the host; projected host state is uploaded before the next device
integration and settling damps the resolved host velocities. Earlier contract
classes and cadence remain unchanged. `gpu.patch.install()` is the historical
prototype, not a supported per-scene selector.

The exact backend ID is `warp-dfsph-0.5.0-candidate`. CUDA and Warp **1.19.0** are
required; a mismatched version or unavailable CUDA is an error. The host selects
`LIQUID_GPU_DEVICE` (default `cuda:0`) and must obtain a CUDA device, never a CPU
Warp fallback. Host rigid simulation and rendering remain CPU/OSMesa. Install
Warp into a dedicated GPU simulator environment; dependency installation happens
on the networked login host before scheduling a compute worker.

The selected GPU contract requires an explicit host compute declaration before
simulator construction; runtime and constructed-solver checks are provided by the
[compute validation API](#host-compute-validation). The consuming suite owns the
JSON declaration, scheduler/allocation workflow, frozen thread count and adoption
status. Declarations and private diagnostics stay host-only, outside observations.

## Flex patch contract 0.6.0

Contract 0.6.0 is the 0.5.0 GPU solver, validity, domain and uptake implementation unchanged, plus one boundary
kind for a deformable MuJoCo `dim=2` flex cloth (`physics/liquid/flex_patches.py`). The one-way coupling moves
rigid meshes; a flex has no rigid body, so its boundary is a grid of piecewise-rigid thin boxes ("patches"). A
boundary entry `{"object": NAME, "flex_patches": {"grid": [NX, NY], "cells": [CX, CY]}}` names the object owning
exactly one flex (all its vertex bodies in the object's subtree), its flexcomp point grid (x-major vertex order,
verified at attach) and the flex cells per patch (which must divide the grid's cells evenly). Each patch is a box
of the block's rest extent plus the flex radius, half height the radius, named `NAME#pIIJJ`. Before every fluid
query the patch takes the least-squares rigid pose (Kabsch) of its vertices relative to their layout at attach,
supplied through `LiquidCoupling(pose_sources=...)` on the same data as body poses, so the accepted-substep
interpolation and continuous contact are as for bodies. Bending and stretching inside a patch are not represented;
at seams a bent cloth leaves gaps or overlaps of order patch size times half the bend angle. The fluid still exerts
no force on MuJoCo.

An absorber named like a patch boundary is a `PatchAbsorber`: one reservoir with the declared capacity for the
whole cloth (never divided per patch); a free particle within `contact_m` of any patch is absorbed, lowest particle
ids first. Its report adds `patches` and `by_patch_ml`, the split of absorbed volume by the first touching patch in
fixed order, which is attribution only. `LiquidScene.wetting_ml(NAME)` unions the patches and the scene report
lists `flex_patches` counts. Flex patch boundaries are refused under any other contract; contract 0.6.0 requires
the same explicit GPU `compute` declaration and backend ID as 0.5.0 (`compute.GPU_CONTRACTS`).

Related flex support outside the liquid package: `scenario.object_flexes`, object `friction` and opt-in `condim`
(1, 3, 4 or 6) applied to an object's flexes as well as its geoms, `scenario.contact_bodies` (a flex contact side
has geom -1 and resolves to its vertex's, or element's first vertex's, body), flex-aware `supported_v1`,
`released_v1`, `contents_contact` and `impact_speed`, refusal of flex objects by `contact`, `on_fixture`,
`impact_speed` and `moving_contact` watches (geom-name checks cannot see a flex, so a negative would be missing
evidence), and state-trace contacts, labels and boxes for flexes.

## Continuous flex patches and gated time step, contract 0.7.0

Contract 0.7.0 is the 0.6.0 condition (same Warp DFSPH solver and backend ID, domain, uptake, absorbers and
validity checks) with two changes to how moving boundaries reach the solver. Both fix a measured non-physical
failure: under 0.6.0, scene 8005 v6's violating route failed with "relative boundary/particle speed requires a time
step below dt_min" while every liquid particle moved below 0.07 m/s; the limiting "wall speed" came from single
towel patches with fitted angular velocities of 893 and 1385 rad/s (a patch is about 7 cm across).

**Continuous patch rotation** (`FlexPatches(..., continuous=True)`). The 0.6.0 Kabsch fit of a planar rest layout
leaves the third axis to the determinant correction, so a crumpled or folded patch can change its best proper
rotation abruptly. 0.7.0 augments rest and current vertices by plus and minus the patch half-diagonal along their
oriented normals (rest: at attach; now: the area-weighted normal of the patch's flex triangles), which makes the
fit well posed, and rejects a fit whose orthogonal optimum is a reflection (det < 0) instead of forcing it proper.
A patch is degenerate when its fit is a reflection, its in-plane second/first singular value ratio is below 0.25
(folded or collinear vertices), or its oriented area is below 0.25 of its rest area. A degenerate patch keeps its
previous accepted rotation (its centroid still follows its vertices), and every such fit is logged with time,
patch, reason and ratios; the first regular fit after a hold logs the rotation angle accumulated while held. The
coupling's angular velocity is unchanged in form: the principal (smallest-angle) rotation increment between
consecutive MuJoCo-step fits divided by the step. No angular-velocity cap is applied. The scene report adds
`flex_patch_fits` (held fits, releases, largest release angle) per flex boundary.

**Time step gated to boundaries that can reach the liquid** (`gpu.validity_gpu.GatedWarpFluid`). 0.5.0 and 0.6.0
bound every substep by the fastest animated boundary anywhere in the scene. The bound exists to keep each
particle-boundary interaction resolved, and a particle interacts with a boundary only inside the kernel support
h = 4 r of its boundary samples, which lie inside the sphere of radius r_b (the boundary mesh's largest vertex
distance from its body origin) about the boundary's pose. Over one step of at most dt_max, a boundary's points move
at most s_b dt_max (s_b = |v| + r_b |w|, the bound 0.5.0 uses) and a free particle at most (u + |g| dt_max) dt_max,
with u the larger of the current and previously predicted particle speed. A boundary whose sphere is farther than
h + (u + |g| dt_max + s_b) dt_max from every free particle therefore cannot enter any particle's kernel support
during any step the rule can choose, exerts no force in that step, and is excluded from the wall speed (a CFL
argument: the excluded speed cannot affect resolution). Every other boundary enters exactly as before; with no free
particle the wall speed is zero. The particle-speed term, gravity term, CFL number, dt_min and all validity checks
are unchanged. The validity report adds `wall_speed_gating`: `substeps_changed` counts substeps in which an
excluded boundary was faster than every included one (the exclusion lowered the wall-speed term; the step itself
changed only where that term was binding), and the fastest excluded boundary and its speed.

0.7.0 requires the same explicit GPU `compute` declaration and backend ID as 0.5.0 and 0.6.0. Scenes declaring
0.5.0 or 0.6.0 are unchanged (`ValidatedWarpFluid.wall_speed` keeps the ungated maximum; `FlexPatches` keeps the
0.6.0 fit unless `continuous`).

## Flex patch rotation-rate limit, contract 0.7.1

Contract 0.7.1 is 0.7.0 with one declared knob per flex patch boundary,
`"flex_patches": {"grid": [...], "cells": [...], "max_angular_speed_rad_s": w_max}` (required under 0.7.1, refused
under 0.6.0 and 0.7.0). Measured need: under 0.7.0, scene 8005 v6's violating route still failed at dt_min. The
cause was a hold release: a patch held through a fold re-acquires its fitted rotation in one MuJoCo step (releases
up to 3.09 rad; one of 1.95 rad, 977 rad/s, on a patch 18 mm from free liquid). 0.7.1 limits each patch's output
rotation to turn at most w_max times the MuJoCo time elapsed since its last output at an earlier time, along the
shortest arc (repeated queries at one time return one pose). The fit and the hold logic are unchanged, so the output
catches up with the fitted rotation at w_max. A patch's contribution to the wall speed is then at most
|v| + r_b w_max. Choice of w_max: regular (non-released) patch fits of the 8005 towel turn at about 1-2 rad/s, so
50 rad/s never limits ordinary cloth motion, bounds a 3.5 cm patch's rim speed by 1.75 m/s, and lets a 3 rad release
catch up in 60 ms. `flex_patch_fits` adds `max_angular_speed_rad_s`, `cap_events` (limited outputs) and
`cap_max_deficit_rad` (largest angle still to catch up). Everything else, including the GPU solver, backend ID and
time-step gating, is 0.7.0.

## Material selection and surface capacity

Surface-tension model parameter IDs remain -1 until that model is instantiated.
`SPHFluid._set_material` uses the selected model's own IDs and records coefficient
readback in `fluid.material`. Numerical coefficient agreement with water does not
establish resolution-independent surface tension or calibrated wetting.
Experimental `FluidParams` fields include `cfl_method` (0/1/2), `capillary_safety`,
`boundary_method` (0/1/2) and `map_resolution`. Native map updates must use the
matching density/volume methods, not Akinci's `updateBoundaryParticles` class cast.
Support meshes preserve clipped slab unions and gaps; unsupported rotated support
slabs raise rather than creating fictitious support.

Set `strict_surface=True` to refuse a surface exceeding the preallocated mesh
capacity. Earlier configurations retain logged truncation unless explicitly
selected. Attachment forwards the derived MuJoCo geom pose before the first frame;
changing only `model.geom_pos` otherwise leaves the surface invisible until a step.
This cannot change pixels already recorded by a host.
