#!/bin/bash
# Reference solution: replays the recorded DAPG human demonstration (oracle/demo.json, the upstream normalised absolute targets)
# through the robo socket as target changes (src/robouse/backends/adroit.py, oracle_main).
set -euo pipefail
python -m robouse.oracle --backend adroit --env "$(cd "$(dirname "$0")" && pwd)/demo.json"
