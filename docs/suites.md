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
<!-- /suites-table -->

`robouse fetch-assets` downloads the MuJoCo Menagerie robot models once, each checked by SHA-256. Solve rates of models on these suites: [leaderboard](/hub/leaderboard/).

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

`humanoidbench`, `maniskill` and `robocasa` need setup files from the Robo Use repository, which is private for now. Run them from the hub instead, with `bench eval run -d` ([Run a suite or dataset](run-a-suite.md#a-dataset)).

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
