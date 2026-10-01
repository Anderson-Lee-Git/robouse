#!/bin/bash
# Reference solution: RLE-Bench's own HiddenCOM solver (tasks/task03/_template/hidden_com_solution/oracle.py): lift the box
# by its handle and read the ballast quadrant from the top camera's RGB image. Public observations only.
set -euo pipefail
python -m robouse.oracle --backend rlebench --env rle-hidden-com-box-1
