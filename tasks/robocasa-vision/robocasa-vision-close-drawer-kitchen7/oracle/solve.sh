#!/bin/bash
# Reference solution: scripted controller that uses only the robo socket (robocasa_oracles.py).
set -euo pipefail
python -m robouse.oracle --backend robocasa --env robocasa-close-drawer-kitchen7
