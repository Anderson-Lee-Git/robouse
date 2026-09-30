#!/bin/bash
# Reference solution: follow the geodesic distance field to the target with `robo act`, then `robo done`.
set -euo pipefail
python -m robouse.oracle --backend nav --env "$(dirname "$0")/nav_spec.json"
