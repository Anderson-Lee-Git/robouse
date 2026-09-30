#!/bin/bash
# Build the release-gate images: one Docker image per simulator runtime, from robohub's runtime Dockerfiles (the same
# pinned simulator environments the hub datasets run on), without the vendored Robo Use copy. The checkout under test is
# mounted at /src when the gate runs (tools/gate_run.sh), so one set of images serves every commit.
#
#   tools/gate_images.sh ROBOHUB_RUNTIMES_DIR [RUNTIME ...]      default: every CPU runtime
set -euo pipefail
RT_DIR=$(cd "$1" && pwd); shift
RUNTIMES=("$@")
[ ${#RUNTIMES[@]} -eq 0 ] && RUNTIMES=(base light menagerie robosuite libero dexjoco embodied driving dmcontrol myosuite humanoidbench maniskill robocasa)
for rt in "${RUNTIMES[@]}"; do
  ctx=$(mktemp -d)
  rsync -a --exclude robouse "$RT_DIR/$rt/" "$ctx/"
  # everything from the digest check on is about the vendored copy; the gate mounts the checkout instead
  sed '/^ARG ROBOHUB_RUNTIME_DIGEST/,$d' "$RT_DIR/$rt/Dockerfile" > "$ctx/Dockerfile"
  cat >> "$ctx/Dockerfile" <<'EOF'
RUN pip install --no-cache-dir pytest==9.1.1 pytest-cov==7.0.0 && rm -rf /root/.cache
ENV PYTHONPATH=/src/src
WORKDIR /src
EOF
  echo "== building robouse-gate-$rt"
  DOCKER_BUILDKIT=1 docker build -q -t "robouse-gate-$rt" "$ctx" > "/tmp/robouse-gate-$rt.build.log" 2>&1 || { tail -30 "/tmp/robouse-gate-$rt.build.log"; exit 1; }
  rm -rf "$ctx"
done
# composed tasks use the base robots (Panda, ALOHA) as well as the embodiment ones: add the checkout's to the embodied image
if [[ " ${RUNTIMES[*]} " == *" embodied "* ]]; then
  printf 'FROM robouse-gate-embodied\nCOPY . /opt/menagerie/\n' | docker build -q -t robouse-gate-embodied \
    -f - "$(cd "$(dirname "$0")/.." && pwd)/assets/menagerie" > /tmp/robouse-gate-embodied2.build.log 2>&1 \
    || { tail -30 /tmp/robouse-gate-embodied2.build.log; exit 1; }
fi
# the dev image: the base runtime plus the lint, type-check and packaging tools (tests, ruff, mypy, the wheel build)
if [[ " ${RUNTIMES[*]} " == *" base "* ]]; then
  printf 'FROM robouse-gate-base\nRUN pip install --no-cache-dir ruff==0.14.3 mypy==1.18.2 types-PyYAML build && rm -rf /root/.cache\n' \
    | docker build -q -t robouse-gate-dev - > /tmp/robouse-gate-dev.build.log 2>&1 || { tail -30 /tmp/robouse-gate-dev.build.log; exit 1; }
fi
