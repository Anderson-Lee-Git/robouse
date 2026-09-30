#!/bin/bash
# Run the release gate (tools/gate.py) for every CPU suite inside the image of its simulator runtime (tools/gate_images.sh).
#
#   tools/gate_run.sh OUT [PER_SUITE] [SUITE ...]      default: 3 tasks per suite, every CPU suite
# Writes OUT/<runtime>/<suite>/{oracle,noop}/ trial folders and OUT/<runtime>/summary.json; prints one line per suite.
# GATE_REPO=DIR runs the gate on another checkout (e.g. an older commit, for a before/after comparison).
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "${GATE_REPO:-$HERE/..}" && pwd)
OUT=$(mkdir -p "$1" && cd "$1" && pwd); shift
PER=${1:-3}; [ $# -gt 0 ] && shift
declare -A RT=(
  [metaworld]=base [gymrobotics]=base [arc-style]=base [hard]=base [libero-style]=base [robo-use-families]=base
  [safety]=base [vision]=base [kitchen]=base [adroit]=base [real]=base [stationerybench]=base
  [nav]=light [cubepick]=light
  [menagerie]=menagerie [roboharm]=menagerie [drone]=menagerie
  [robosuite]=robosuite [libero]=libero [libero-90]=libero [dexjoco]=dexjoco
  [quadruped]=embodied [humanoid]=embodied [mobile-manip]=embodied [dexhand]=embodied [crazyflie]=embodied
  [composed]=embodied [remix]=embodied
  [driving]=driving [dmcontrol]=dmcontrol [myosuite]=myosuite [humanoidbench]=humanoidbench [maniskill]=maniskill
  [robocasa]=robocasa
)
SUITES=("$@"); [ ${#SUITES[@]} -eq 0 ] && SUITES=("${!RT[@]}")
declare -A BY
for s in "${SUITES[@]}"; do BY[${RT[$s]}]+="${BY[${RT[$s]}]:+,}$s"; done
status=0
for rt in "${!BY[@]}"; do
  # the per-backend smoke tests, in the runtime that has the simulator
  docker run --rm -e HOME=/tmp -v "$REPO":/src:ro "robouse-gate-$rt" python -m pytest -q -p no:cacheprovider \
    tests/test_backends_smoke.py 2>&1 | tail -1 | sed "s/^/$rt smoke: /" || status=1
  docker run --rm -e HOME=/tmp -v "$REPO":/src:ro -v "$HERE/gate.py":/gate.py:ro -v "$OUT":/out "robouse-gate-$rt" \
    python /gate.py --repo /src --out "/out/$rt" --per-suite "$PER" --concurrency 4 --suites "${BY[$rt]}" || status=1
done
exit $status
