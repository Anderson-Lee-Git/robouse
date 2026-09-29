#!/bin/bash
# Reference solution: replay LIBERO demonstration demo_0 of libero_goal/open_the_top_drawer_and_put_the_bowl_inside_demo.hdf5 (yifengzhu-hf/LIBERO-datasets) through the robo socket.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
