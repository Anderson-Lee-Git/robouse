#!/bin/bash
# Dogfood the `vla` harness on every wire protocol against mock policy servers built on the upstream libraries
# (tests/vla_mock_servers.py; no GPU). LIBERO tasks replay the task's demonstration through the wire; real-arm tasks
# (hardware-in-the-loop mock) track the goal pose found by inverse kinematics. Usage: scripts/vla_dogfood.sh [OUT]
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-runs/vla-dogfood}
V=${VLA_TEST_PYTHON:-$HOME/.cache/robouse/vla-test-venv/bin/python}
P=${ROBOUSE_PYTHON:-$HOME/benchflow/robouse/.venv/bin/python}
LIB=tasks/libero/libero-10-0
DEMO=$LIB/oracle/demo_actions.json
ik() { PYTHONPATH=src $P -c "
from robouse.real.robots import profile; import numpy as np
p=profile('$1'); c=p.chain(); q,e=c.solve($2, np.array(p.home,float), p.low, p.high, seeds=p.ik_seeds)
q=list(q); q[p.gripper]=p.gripper_closed; print(','.join(f'{x:.2f}' for x in q))"; }
METAL_Q=$(ik metal "[0.30,-0.10,0.08]")
SO_Q=$(ik so101 "[0.20,0.05,0.08]")
run() {  # wire port policy chunk advance task preset
  local log=/tmp/vla-$1.log; rm -f $log
  $V tests/vla_mock_servers.py --wire $1 --port $2 --policy "$3" --chunk $4 --advance $5 --log $log & local pid=$!
  sleep 1.5
  local url=$([ $1 = openpi ] || [ $1 = xpolicylab ] && echo ws://127.0.0.1:$2 || ([ $1 = gr00t ] && echo tcp://127.0.0.1:$2 || echo http://127.0.0.1:$2))
  ROBOUSE_VLA_URL=$url PYTHONPATH=src $P -m robouse.cli run --task $6 --harness vla --model $7 --out $OUT > /tmp/vla-$1.run 2>&1
  kill $pid 2>/dev/null
  printf "%-11s %-26s %-24s reward=%s outcome=%s inferences=%s\n" $1 $7 $(basename $6) \
    "$(grep -o '"reward": [0-9.]*' /tmp/vla-$1.run | head -1 | cut -d' ' -f2)" "$(grep -o '"outcome": "[a-z_]*"' /tmp/vla-$1.run | head -1 | cut -d'"' -f4)" "$(wc -l < $log | tr -d ' ')"
  head -1 $log | cut -c1-400
}
run openpi     18765 replay:$DEMO 10 5 $LIB openpi/pi05_libero
run openvla    18766 replay:$DEMO 1 1 $LIB openvla/openvla-7b-libero
run http-json  18767 replay:$DEMO 10 10 $LIB molmoact2/libero
run xpolicylab 18768 track:$METAL_Q 8 8 tasks/real/real-metal-reach xpolicylab/metal-joint
run gr00t      18769 track:$SO_Q 16 8 tasks/real/real-so101-reach gr00t/so101
