#!/bin/bash
# Reference solution: CaP-X's privileged LIBERO reference code (env_configs/human_oracle_code/libero/
# franka_libero_object_swap_7_privileged_oracle.yaml at CaP-X 53e9966, MIT) with this task's object (cream_cheese) and target
# (basket) in place of the milk and the basket; copied as oracle_code.py and run through capx_api, then `robo done`.
set -euo pipefail
python -m robouse.oracle --backend capx_libero --env "$(dirname "$0")/oracle_code.py"
