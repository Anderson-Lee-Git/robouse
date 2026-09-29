# Suites

The package bundles 599 tasks in 28 suites; each is a subfolder of `robouse tasks --path`. The last two columns are the results of running every reference solution and the no-op control, with MuJoCo 3.3.0.

```gallery
img/suites/metaworld.webp | `metaworld`
img/suites/gymrobotics.webp | `gymrobotics`
img/suites/libero.webp | `libero`
img/suites/robosuite.webp | `robosuite`
img/suites/libero-style.webp | `libero-style`
img/suites/arc-style.webp | `arc-style`
img/suites/robo-use-families.webp | `robo-use-families`
img/suites/safety.webp | `safety`
img/suites/vision.webp | `vision` (top camera, as the agent sees it)
img/suites/hard.webp | `hard`
img/suites/menagerie.webp | `menagerie`
img/suites/roboharm.webp | `roboharm`
img/suites/drone.webp | `drone`
img/suites/dexjoco.webp | `dexjoco`
img/suites/quadruped.webp | `quadruped`
img/suites/humanoid.webp | `humanoid`
img/suites/mobile-manip.webp | `mobile-manip`
img/suites/dexhand.webp | `dexhand`
img/suites/crazyflie.webp | `crazyflie`
img/suites/driving.webp | `driving`
img/suites/libero-90.webp | `libero-90`
img/suites/kitchen.webp | `kitchen`
img/suites/adroit.webp | `adroit`
img/suites/dmcontrol.webp | `dmcontrol`
img/suites/myosuite.webp | `myosuite`
img/suites/humanoidbench.webp | `humanoidbench`
img/suites/maniskill.webp | `maniskill`
img/suites/robocasa.webp | `robocasa`
```

Stills from the recordings of one reference solution per suite; for `vision`, a camera image the agent receives.

| Suite | From | Tasks | Needs | Oracle | No-op |
|---|---|---|---|---|---|
| `metaworld` | Meta-World MT50 | 50 | `[metaworld]` | 50/50 | 0/50 |
| `gymrobotics` | Gymnasium-Robotics: Fetch, PointMaze | 12 | `[gymrobotics]` | 12/12 | 0/12 |
| `libero` | LIBERO: Spatial, Object, Goal, Long (10 each) | 40 | [see below](#libero) | 40/40 | 0/40 |
| `libero-90` | LIBERO-90 | 90 | [see below](#libero) | 90/90 | 0/90 |
| `robosuite` | robosuite 1.5, five arm models | 21 | `[robosuite]` | 21/21 | 0/21 |
| `libero-style` | LIBERO-like, Robo Use tabletop | 12 | `[sim]` | 12/12 | 0/12 |
| `arc-style` | ARC-style rules on a table | 11 | `[sim]` | 11/11 | 0/11 |
| `robo-use-families` | Robo Use task families | 8 | `[sim]` | 8/8 | 0/8 |
| `safety` | harmful requests, benign twins | 8 | `[sim]` | 8/8 | 0/8 |
| `vision` | camera images, no coordinates | 55 | `[sim,metaworld]` | 55/55 | 0/55 |
| `hard` | low-level control, uncalibrated cameras | 25 | `[sim]` | 25/25 | 0/25 |
| `menagerie` | dual Franka Panda, ALOHA 2 | 15 | `[sim]`, assets | 15/15 | 0/15 |
| `roboharm` | 10 harm scenarios, 4 configurations | 80 | `[sim]`, assets | 80/80 | 0/80 |
| `drone` | Skydio X2 over a small town | 10 | `[sim]`, assets | 10/10 | 0/10 |
| `dexjoco` | DexJoCo: Allegro hand tool use | 14 | `[dexjoco]` + DexJoCo, [see below](#dexjoco) | 14/14 | 0/14 |
| `quadruped` | Unitree Go2, Go1, Spot (with arm), ANYmal C | 11 | `[sim]`, assets | 11/11 | 0/11 |
| `humanoid` | Unitree G1, H1, Apptronik Apollo, Booster T1 (on stands) | 9 | `[sim]`, assets | 9/9 | 0/9 |
| `mobile-manip` | Stretch 3, TIAGo, Google Robot in an apartment | 10 | `[sim]`, assets | 10/10 | 0/10 |
| `dexhand` | Shadow Hand, LEAP hand | 7 | `[sim]`, assets | 7/7 | 0/7 |
| `crazyflie` | Crazyflie 2, single and swarm of three | 7 | `[sim]`, assets | 7/7 | 0/7 |
| `driving` | MetaDrive car in traffic | 7 | MetaDrive, [see below](#driving) | 7/7 | 0/7 |
| `kitchen` | Gymnasium-Robotics Franka Kitchen | 10 | `[gymrobotics]` | 10/10 | 0/10 |
| `adroit` | Gymnasium-Robotics Adroit hand (D4RL human-demo starts) | 12 | `[gymrobotics]` | 12/12 | 0/12 |
| `dmcontrol` | DeepMind dm_control: Control Suite, Kinova Jaco arm | 17 | dm_control virtualenv, `docs/suites/dmcontrol.md` | 17/17 | 0/17 |
| `myosuite` | MyoSuite: muscle-driven elbow, finger and hand | 15 | MyoSuite virtualenv, `docs/suites/myosuite.md` | 15/15 | 0/15 |
| `humanoidbench` | HumanoidBench: Unitree H1 with two Shadow hands | 7 | HumanoidBench virtualenv, `docs/suites/humanoidbench.md` | 7/7 | 0/7 |
| `maniskill` | ManiSkill3 tabletop, Franka Panda (CPU physics) | 12 | ManiSkill virtualenv, `docs/suites/maniskill.md` | 12/12 | 0/12 |
| `robocasa` | RoboCasa kitchens, Franka Panda on a parked mobile base | 24 | RoboCasa virtualenv, `docs/suites/robocasa.md` | 24/24 | 0/24 |

"Assets" means `robouse fetch-assets`, which downloads the MuJoCo Menagerie robot models once (`--robot NAME` for one robot; the embodiment suites need about 350 MB).

Solve rates of agents on these suites are on the [Results](/runs/) page.

## LIBERO

LIBERO needs a virtual environment of its own, because it pins robosuite 1.4 and MuJoCo below 3.9. This recipe was run as written, with Python 3.12 on macOS:

```sh
python3.12 -m venv .venv-libero && source .venv-libero/bin/activate
pip install 'robouse[sim]>=0.1' 'mujoco==3.3.0'
pip install --no-deps hf-libero==0.1.4 robosuite==1.4.0 bddl==1.0.1
pip install numba scipy opencv-python-headless termcolor easydict huggingface_hub h5py fsspec tqdm matplotlib future cloudpickle gymnasium
pip install torch --index-url https://download.pytorch.org/whl/cpu
robouse run --task libero-object-0 --harness oracle --out runs/try
```

The first episode downloads LIBERO's scene assets (about 400 MB) into `~/.cache/libero/assets`. In a new environment the first start can take more than two minutes while Python compiles the new packages, and `robouse run` may stop with `TimeoutError: episode server did not start`; run it again.

## DexJoCo

DexJoCo pins its own Python and MuJoCo, so it runs in a separate virtual environment that the episode server starts as a subprocess. Run once (about 300 MB):

```sh
pip install 'robouse[dexjoco]>=0.1.1'
git clone --depth 1 https://github.com/brave-eai/dexjoco.git ~/.cache/robouse/dexjoco
uv venv -p 3.11 ~/.cache/robouse/dexjoco-venv
VIRTUAL_ENV=~/.cache/robouse/dexjoco-venv uv pip install -e ~/.cache/robouse/dexjoco/dexjoco "numcodecs<0.16"
robouse run --task dexjoco-photograph --harness oracle --out runs/try
```

The episode server looks for DexJoCo's Python at `~/.cache/robouse/dexjoco-venv/bin/python`; set `ROBOUSE_DEXJOCO_PYTHON` to use another.

## Embodiment suites

`quadruped`, `humanoid`, `mobile-manip`, `dexhand`, `crazyflie` and `driving` are robots other than a single arm. Each backend declares its embodiment in one place (sensors, action groups such as `base.twist` or `hand.joints`, typed skills, budget; `src/robouse/backends/embodied.py`), and `robo info` reports it in the format of BenchFlow's embodiment spec. Their instructions use `robo act` with the task's action groups and `robo skill NAME ARG ...`; the skills are closed-loop controllers whose every simulator step counts against the budget. Design notes per suite are in the repository under `docs/suites/` (`quadruped.md`, `humanoid.md`, `mobile-manip.md`, `dexhand.md`, `crazyflie.md`, `driving.md`).

Robot model licences (MuJoCo Menagerie commit `8161bba2`, hashes in `assets/menagerie/embodiments.json`; the meshes are not stored in git):

| Robot | Menagerie folder | Licence | Suite |
|---|---|---|---|
| Unitree Go2 | `unitree_go2` | BSD-3-Clause | quadruped |
| Unitree Go1 | `unitree_go1` | BSD-3-Clause | quadruped |
| Boston Dynamics Spot | `boston_dynamics_spot` | BSD-3-Clause | quadruped |
| ANYbotics ANYmal C | `anybotics_anymal_c` | BSD-3-Clause | quadruped |
| Unitree G1 | `unitree_g1` | BSD-3-Clause | humanoid |
| Unitree H1 | `unitree_h1` | BSD-3-Clause | humanoid |
| Apptronik Apollo | `apptronik_apollo` | Apache-2.0 | humanoid |
| Booster T1 | `booster_t1` | Apache-2.0 | humanoid |
| Hello Robot Stretch 3 | `hello_robot_stretch_3` | Apache-2.0 | mobile-manip |
| PAL TIAGo | `pal_tiago` | Apache-2.0 | mobile-manip |
| Google Robot | `google_robot` | Apache-2.0 | mobile-manip |
| Shadow Hand E3M5 | `shadow_hand` | Apache-2.0 | dexhand |
| LEAP Hand | `leap_hand` | MIT | dexhand |
| Bitcraze Crazyflie 2 | `bitcraze_crazyflie_2` | MIT | crazyflie |

The driving suite uses MetaDrive 0.4.3 (Apache-2.0), not Menagerie.

## Driving

MetaDrive has dependencies of its own (panda3d, opencv, pygame), so it runs in a separate virtual environment that the episode server starts as a subprocess:

```sh
uv venv -p 3.11 ~/.cache/robouse/metadrive-venv
uv pip install -p ~/.cache/robouse/metadrive-venv/bin/python metadrive-simulator==0.4.3
robouse run --task driving-winding-road --harness oracle --out runs/try
```

Set `ROBOUSE_METADRIVE_PYTHON` to use another interpreter.

## Suites with their own simulator environment

`dmcontrol`, `myosuite`, `humanoidbench`, `maniskill` and `robocasa` pin simulator versions that conflict with the main environment, so each runs in a virtual environment of its own that the episode server starts as a subprocess (the DexJoCo pattern). The setup for each is in the repository under `docs/suites/<suite>.md`. Every suite also runs without local setup from the [hub](https://robouse.ai/hub/), where each simulator image is built from pinned sources.

## Not in the package

BEHAVIOR-1K needs an NVIDIA RTX GPU for its simulator worker, so it runs only from a checkout of the Robo Use repository.
