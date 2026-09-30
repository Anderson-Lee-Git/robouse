#!/bin/bash
# Reference solution: replay LIBERO demonstration demo_0 of libero_90/STUDY_SCENE2_pick_up_the_book_and_place_it_in_the_left_compartment_of_the_caddy_demo.hdf5 (yifengzhu-hf/LIBERO-datasets) through the robo socket.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
