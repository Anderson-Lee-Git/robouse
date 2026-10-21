#!/bin/bash
# Reference solution: the scripted LIBERO solution (robouse.backends.libero.solver) through the robo socket, reading the
# scene from the reference solution's privileged observation; plan.json holds this task's options, if any.
set -euo pipefail
python -m robouse.oracle --backend libero_scripted --env "$(dirname "$0")/plan.json"
