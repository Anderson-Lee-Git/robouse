# Suites

The 0.1.0 package bundles 327 tasks in 13 suites; each is a subfolder of `robouse tasks --path`. The last two columns are the results of running every reference solution and the no-op control from the 0.1.0 package, with MuJoCo 3.3.0.

| Suite | From | Tasks | Needs | Oracle | No-op |
|---|---|---|---|---|---|
| `metaworld` | Meta-World MT50 | 50 | `[metaworld]` | 50/50 | 0/50 |
| `gymrobotics` | Gymnasium-Robotics: Fetch, PointMaze | 12 | `[gymrobotics]` | 12/12 | 0/12 |
| `libero` | LIBERO, 5 tasks per suite | 20 | [see below](#libero) | 20/20 | 0/20 |
| `robosuite` | robosuite 1.5, five arm models | 21 | `[robosuite]` | 21/21 | 0/21 |
| `libero-style` | LIBERO-like, robo-use tabletop | 12 | `[sim]` | 12/12 | 0/12 |
| `arc-style` | ARC-style rules on a table | 11 | `[sim]` | 11/11 | 0/11 |
| `robo-use-families` | robo-use task families | 8 | `[sim]` | 8/8 | 0/8 |
| `safety` | harmful requests, benign twins | 8 | `[sim]` | 8/8 | 0/8 |
| `vision` | camera images, no coordinates | 55 | `[sim,metaworld]` | 55/55 | 0/55 |
| `hard` | low-level control, uncalibrated cameras | 25 | `[sim]` | 25/25 | 0/25 |
| `menagerie` | dual Franka Panda, ALOHA 2 | 15 | `[sim]`, assets | 15/15 | 0/15 |
| `roboharm` | 10 harm scenarios, 4 configurations | 80 | `[sim]`, assets | 80/80 | 0/80 |
| `drone` | Skydio X2 over a small town | 10 | `[sim]`, assets | 10/10 | 0/10 |

"Assets" means `robouse fetch-assets`, which downloads the MuJoCo Menagerie robot models once. Install each extra with MuJoCo pinned, for example `pip install 'robouse[robosuite]>=0.1' 'mujoco==3.3.0'`: with MuJoCo 3.14, many robosuite, menagerie, gymrobotics and drone episodes crash.

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

## Not in 0.1.0

DexJoCo (14 dexterous tool-use tasks with an Allegro hand) and RoboCasa (7 kitchen tasks) were added after the 0.1.0 release. They need a checkout of the robo-use repository, which is private for now, and simulators installed in environments of their own.
