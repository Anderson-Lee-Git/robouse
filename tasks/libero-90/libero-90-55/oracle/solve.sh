#!/bin/bash
# Reference solution: replay LIBERO demonstration demo_0 of libero_90/LIVING_ROOM_SCENE3_pick_up_the_alphabet_soup_and_put_it_in_the_tray_demo.hdf5 (yifengzhu-hf/LIBERO-datasets) through the robo socket.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
