#!/bin/bash
# Reference solution: scripted controller that uses only the robo socket and public observations.
set -euo pipefail
python -m robouse.oracle --backend gymrobotics --env gymrobotics-fetch-reach-s0
