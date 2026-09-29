#!/bin/bash
# Reference solution: the embodiment-agnostic go-to-landmark strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env go-to-landmark--google-robot--outdoor-field--s3
