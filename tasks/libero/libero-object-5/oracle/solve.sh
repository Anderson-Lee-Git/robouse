#!/bin/bash
# Reference solution: replay LIBERO demonstration demo_0 of libero_object/pick_up_the_tomato_sauce_and_place_it_in_the_basket_demo.hdf5 (yifengzhu-hf/LIBERO-datasets) through the robo socket.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
