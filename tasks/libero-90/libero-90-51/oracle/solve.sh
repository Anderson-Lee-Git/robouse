#!/bin/bash
# Reference solution: follow the end-effector path of LIBERO demonstration demo_0 of libero_90/LIVING_ROOM_SCENE2_pick_up_the_butter_and_put_it_in_the_basket_demo.hdf5 (yifengzhu-hf/LIBERO-datasets) through the
# robo socket. Its recorded actions do not replay in the released scene (the robot sits about 14 cm further forward
# than when it was recorded), so the adapter tracked the recorded hand positions closed-loop and saved those actions.
# The task's init_state is that demonstration's first MuJoCo state.
set -euo pipefail
python -m robouse.oracle --backend libero --env "$(dirname "$0")/demo_actions.json"
