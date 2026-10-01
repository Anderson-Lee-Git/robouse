#!/bin/bash
# Reference solution: CaP-X's own reference code for this task (ORACLE_CODE, or PRIVILEGED_ORACLE_CODE, of capx/envs/tasks/franka/franka_lift.py at CaP-X
# 53e9966, MIT; copied as oracle_code.py), run against the API through capx_api like an agent's code, then `robo done`.
set -euo pipefail
python -m robouse.oracle --backend capx --env "$(dirname "$0")/oracle_code.py"
