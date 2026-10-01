#!/bin/bash
# Reference solution: a closed-loop controller that reads the objects' poses (given only to the reference solution; never
# masses or which cube is heavy) and drives the robot with RLE-Bench's move skill and base actions. RLE-Bench's own
# recorded trajectory for this task does not reproduce when replayed open-loop on this build, so it is not used.
set -euo pipefail
python -m robouse.oracle --backend rlebench --env rle-balance-coins
