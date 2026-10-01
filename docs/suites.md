# Suites

A suite is a folder of tasks in the package: a subfolder of `robouse tasks --path`. Run one with `robouse run-many --tasks "$(robouse tasks --path)/SUITE"`.

```gallery
img/suites/metaworld.webp | `metaworld`
img/suites/gymrobotics.webp | `gymrobotics`
img/suites/libero.webp | `libero`
img/suites/robosuite.webp | `robosuite`
img/suites/libero-style.webp | `libero-style`
img/suites/arc-style.webp | `arc-style`
img/suites/robo-use-families.webp | `robo-use-families`
img/suites/safety.webp | `safety`
img/suites/vision.webp | `vision` (a camera image the agent gets)
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

<!-- suites-table -->
robouse 0.3.0 bundles 692 tasks in 31 suites. "Needs" is what a suite needs beyond `pip install 'robouse[sim]'`. The last two columns count the tasks that scored 1 with the reference solution and with the no-op control.

| Suite | What | Tasks | Needs | Reference solution | No-op control |
|---|---|---|---|---|---|
| `adroit` | Adroit hand | 12 | `[gymrobotics]` | 12/12 | 0/12 |
| `arc-style` | ARC-style rules on a table | 11 | - | 11/11 | 0/11 |
| `composed` | composed from components | 48 | `robouse fetch-assets --all` | 48/48 | 0/48 |
| `crazyflie` | Crazyflie 2, one or three | 7 | `robouse fetch-assets --all` | 7/7 | 0/7 |
| `cubepick` | cube pick-and-reach | 5 | - | 5/5 | 0/5 |
| `dexhand` | Shadow Hand, LEAP Hand | 7 | `robouse fetch-assets --all` | 7/7 | 0/7 |
| `dexjoco` | DexJoCo: Allegro hand tool use | 14 | own virtualenv (below) | 14/14 | 0/14 |
| `dmcontrol` | dm_control: Control Suite, Jaco arm | 17 | own virtualenv (below) | 17/17 | 0/17 |
| `driving` | MetaDrive car in traffic | 7 | own virtualenv (below) | 7/7 | 0/7 |
| `drone` | Skydio X2 over a town | 10 | `robouse fetch-assets` | 10/10 | 0/10 |
| `gymrobotics` | Gymnasium-Robotics: Fetch, PointMaze | 12 | `[gymrobotics]` | 12/12 | 0/12 |
| `hard` | low-level control, uncalibrated cameras | 25 | - | 25/25 | 0/25 |
| `humanoid` | Unitree G1 and H1, Apollo, Booster T1 | 9 | `robouse fetch-assets --all` | 9/9 | 0/9 |
| `humanoidbench` | HumanoidBench: H1 with two hands | 7 | [the hub](run-a-suite.md#a-dataset) only | 7/7 | 0/7 |
| `kitchen` | Franka Kitchen | 10 | `[gymrobotics]` | 10/10 | 0/10 |
| `libero` | LIBERO: Spatial, Object, Goal, Long | 40 | [LIBERO setup](#libero) | 40/40 | 0/40 |
| `libero-90` | LIBERO-90 | 90 | [LIBERO setup](#libero) | 90/90 | 0/90 |
| `libero-style` | LIBERO-like tabletop scenes | 12 | - | 12/12 | 0/12 |
| `maniskill` | ManiSkill3 on the CPU | 12 | [the hub](run-a-suite.md#a-dataset) only | 12/12 | 0/12 |
| `menagerie` | dual Franka Panda, ALOHA 2 | 15 | `robouse fetch-assets` | 15/15 | 0/15 |
| `metaworld` | Meta-World MT50 | 50 | `[metaworld]` | 50/50 | 0/50 |
| `mobile-manip` | Stretch 3, TIAGo, Google Robot | 10 | `robouse fetch-assets --all` | 10/10 | 0/10 |
| `myosuite` | MyoSuite: muscle-driven arm and hand | 15 | own virtualenv (below) | 15/15 | 0/15 |
| `nav` | object-goal navigation in homes | 40 | - | 40/40 | 0/40 |
| `quadruped` | Unitree Go2 and Go1, Spot, ANYmal C | 11 | `robouse fetch-assets --all` | 11/11 | 0/11 |
| `robo-use-families` | Robo Use task families | 8 | - | 8/8 | 0/8 |
| `robocasa` | RoboCasa kitchens | 24 | [the hub](run-a-suite.md#a-dataset) only | 24/24 | 0/24 |
| `roboharm` | 10 harm scenarios, 4 configurations | 80 | `robouse fetch-assets` | 80/80 | 0/80 |
| `robosuite` | robosuite 1.5, five arms | 21 | `[robosuite]` | 21/21 | 0/21 |
| `safety` | harmful requests and benign twins | 8 | - | 8/8 | 0/8 |
| `vision` | camera images, no coordinates | 55 | `[metaworld]` | 55/55 | 0/55 |
<!-- /suites-table -->

`robouse fetch-assets` downloads the MuJoCo Menagerie robot models for `menagerie`, `roboharm` and `drone`; `robouse fetch-assets --all` adds every robot the other suites and composed tasks use (about 390 MB). Each file is checked by SHA-256. Results of models on these suites: [Runs](/runs/).

## LIBERO

LIBERO pins robosuite 1.4, so it needs a virtual environment of its own:

```sh
python3.12 -m venv .venv-libero && source .venv-libero/bin/activate
pip install 'robouse[sim]' 'mujoco==3.3.0'
pip install --no-deps hf-libero==0.1.4 robosuite==1.4.0 bddl==1.0.1
pip install numba scipy opencv-python-headless termcolor easydict huggingface_hub h5py fsspec tqdm matplotlib future cloudpickle gymnasium
pip install torch --index-url https://download.pytorch.org/whl/cpu
robouse run --task libero-object-0 --harness oracle --out runs/try
```

The first episode downloads LIBERO's scene assets (about 400 MB) into `~/.cache/libero/assets`. In a new environment the first start can take more than two minutes, and `robouse run` may stop with `TimeoutError: episode server did not start`; run it again.

## Suites with their own virtualenv

These simulators pin versions that conflict with the main environment. The episode server runs each in a virtualenv of its own, started as a subprocess; set the environment variable to use another interpreter.

```sh
# dexjoco (ROBOUSE_DEXJOCO_PYTHON); also pip install 'robouse[dexjoco]'
git clone --depth 1 https://github.com/brave-eai/dexjoco.git ~/.cache/robouse/dexjoco
uv venv -p 3.11 ~/.cache/robouse/dexjoco-venv
VIRTUAL_ENV=~/.cache/robouse/dexjoco-venv uv pip install -e ~/.cache/robouse/dexjoco/dexjoco "numcodecs<0.16"

# driving (ROBOUSE_METADRIVE_PYTHON)
uv venv -p 3.11 ~/.cache/robouse/metadrive-venv
uv pip install -p ~/.cache/robouse/metadrive-venv/bin/python metadrive-simulator==0.4.3

# dmcontrol (ROBOUSE_DMCONTROL_PYTHON)
uv venv -p 3.12 ~/.cache/robouse/dmcontrol-venv
uv pip install -p ~/.cache/robouse/dmcontrol-venv/bin/python dm-control==1.0.47

# myosuite (ROBOUSE_MYOSUITE_PYTHON)
uv venv -p 3.11 ~/.cache/robouse/myosuite-venv
uv pip install -p ~/.cache/robouse/myosuite-venv/bin/python myosuite==2.12.2 scipy==1.16.2
```

`humanoidbench`, `maniskill` and `robocasa` run from the hub, with `bench eval run -d`.

## Robot models

The Menagerie-based suites use MuJoCo Menagerie commit `8161bba2`; the models are downloaded, not bundled.

| Robot | Licence | Suite |
|---|---|---|
| Unitree Go2, Go1, G1, H1 | BSD-3-Clause | quadruped, humanoid |
| Boston Dynamics Spot, ANYbotics ANYmal C | BSD-3-Clause | quadruped |
| Apptronik Apollo, Booster T1 | Apache-2.0 | humanoid |
| Hello Robot Stretch 3, PAL TIAGo, Google Robot | Apache-2.0 | mobile-manip |
| Shadow Hand E3M5 | Apache-2.0 | dexhand |
| LEAP Hand, Bitcraze Crazyflie 2 | MIT | dexhand, crazyflie |

The driving suite uses MetaDrive 0.4.3 (Apache-2.0).

## Not in the package

These suites run their simulators in environments built from the upstream projects' own pinned stacks (RLE-Bench's robosuite and RoboCasa commits; CaP-X's robosuite forks, LIBERO-PRO and PyRoKi), so they are not in the package: they run in those simulator images.

<!-- hub-only-table -->
| Suite | What | Tasks | Reference solution | No-op control |
|---|---|---|---|---|
| `rle-bench` | RLE-Bench family 03, tabletop reasoning: tower, cantilever, balance, hidden centre of mass | 6 | 6/6 | 0/6 |
| `capx` | CaP-X's robosuite tasks, code as policy with CaP-X's privileged API (simulator object poses, no perception) | 35 | 35/35 | 0/35 |
| `capx-libero` | CaP-X on LIBERO-PRO's object-swap tasks, code as policy with CaP-X's privileged LIBERO API | 8 | 8/8 | 0/8 |
<!-- /hub-only-table -->
