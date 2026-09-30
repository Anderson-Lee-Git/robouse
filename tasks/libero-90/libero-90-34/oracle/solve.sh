#!/bin/bash
# Reference solution: replay LIBERO demonstration demo_0 of libero_90/KITCHEN_SCENE6_put_the_yellow_and_white_mug_to_the_front_of_the_white_mug_demo.hdf5 (yifengzhu-hf/LIBERO-datasets) through the robo socket.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
