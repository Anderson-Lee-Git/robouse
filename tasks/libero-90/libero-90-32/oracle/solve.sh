#!/bin/bash
# Reference solution: replay LIBERO demonstration demo_1 of libero_90/KITCHEN_SCENE5_put_the_ketchup_in_the_top_drawer_of_the_cabinet_demo.hdf5 (yifengzhu-hf/LIBERO-datasets) through the robo socket.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
