#!/bin/bash
# Reference solution: scripted pick/place plan through the robo socket (public observation only).
set -euo pipefail
python -m robouse.oracle --backend tabletop --env libero-block-in-drawer-and-close
