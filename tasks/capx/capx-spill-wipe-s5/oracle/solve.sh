#!/bin/bash
# Reference solution: CaP-X's own reference code for this task (ORACLE_CODE, or PRIVILEGED_ORACLE_CODE, of capx/envs/tasks/franka/franka_spill_wipe.py at CaP-X
# 53e9966, MIT; copied as oracle_code.py), run against the API through capx_api like an agent's code, then `robo done`.
# Changed from CaP-X's code: it wipes at z = -0.10 instead of 0.0 (at 0.0 the sponge stays above the table).
set -euo pipefail
python -m robouse.oracle --backend capx --env "$(dirname "$0")/oracle_code.py"
