#!/bin/bash
# Reference solution: pick the fruit with the nearer arm and place it, with the public skills (object positions from the reference solution's privileged state).
set -euo pipefail
python -m robouse.oracle --backend yam
