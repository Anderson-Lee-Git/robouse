#!/bin/bash
# Reference solution: upstream's scripted policy (step toward the cube).
set -euo pipefail
python -m robouse.oracle --backend cubepick
