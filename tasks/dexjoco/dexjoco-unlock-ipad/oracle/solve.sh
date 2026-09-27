#!/bin/bash
# Reference solution: replays one recorded DexJoCo human demonstration (oracle/demo.json, absolute hand-pose and finger
# targets) through the robo socket, converted to the task's delta actions (src/robouse/backends/dexjoco.py, oracle_main).
set -euo pipefail
python -m robouse.oracle --backend dexjoco --env "$(cd "$(dirname "$0")" && pwd)/demo.json"
