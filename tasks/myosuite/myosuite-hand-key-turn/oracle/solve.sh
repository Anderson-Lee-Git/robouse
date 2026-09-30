#!/bin/bash
# Reference solution: runs MyoSuite's own NPG baseline policy for this env (oracle/policy.json) through `robo act`, reading `obs_vector` from `robo observe`. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend myosuite --env "$(cd "$(dirname "$0")" && pwd)/policy.json"
