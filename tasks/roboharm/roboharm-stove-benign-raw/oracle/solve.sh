#!/bin/bash
# Reference solution: scripted pick/place through the robo socket (roboharm.oracle_main).
set -euo pipefail
python -m robouse.oracle --backend roboharm --env stove
