#!/bin/bash
# Set up the isolated RoboCasa environment used by the `robocasa` backend (about 4.7 GB in ~/.cache/robouse).
# RoboCasa pins MuJoCo 3.3.1 / numpy 2.2 / robosuite 1.5, which conflict with the main robouse venv, so it gets its own.
set -euo pipefail
D="${ROBOUSE_ROBOCASA_HOME:-$HOME/.cache/robouse}"
mkdir -p "$D" && cd "$D"
[ -d robocasa-src ] || { git clone https://github.com/robocasa/robocasa.git robocasa-src && git -C robocasa-src checkout 456174f62b89b8fca99eaaf33949c29fec9cfc2a; }
[ -d robosuite-src ] || { git clone https://github.com/ARISE-Initiative/robosuite robosuite-src && git -C robosuite-src checkout 5ce6643f3092639d08f7b0f90ed1c6a84f50552c; }
uv venv robocasa-venv --python 3.12
PY=robocasa-venv/bin/python
uv pip install --python $PY "numpy==2.2.5" "mujoco==3.3.1" scipy numba pillow opencv-python-headless pyyaml tqdm termcolor imageio imageio-ffmpeg h5py lxml gymnasium
uv pip install --python $PY --no-deps -e robosuite-src
uv pip install --python $PY --no-deps -e robocasa-src   # not lerobot/torch/tianshou: only needed for RoboCasa's policy training code
$PY robocasa-src/robocasa/scripts/setup_macros.py
# minimal asset subset: textures (0.54 GB zip), lightwheel fixtures (0.53 GB) and lightwheel objects (0.79 GB)
echo y | $PY -m robocasa.scripts.download_kitchen_assets --type tex fixtures_lw objs_lw
$PY -c "import robosuite, robocasa; print('robocasa ready, robosuite', robosuite.__version__)"
