# robouse simulator: the trusted simulator + episode server + verifier image of a robouse task on BenchFlow.
#
# Build context: the simulator runtime written by robouse.engine.format (this file, requirements.txt,
# sim-entry.sh and a copy of the robouse package under robouse/src/robouse). The agent container never uses it.
FROM python:3.12-slim-bookworm

# Headless rendering: MuJoCo renders through OSMesa (CPU); no X server or GPU needed.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libosmesa6 \
 && rm -rf /var/lib/apt/lists/*

ENV MUJOCO_GL=osmesa PYOPENGL_PLATFORM=osmesa \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /tmp/requirements-sim.txt
RUN pip install --no-cache-dir -r /tmp/requirements-sim.txt && rm -rf /root/.cache

# robouse itself is pure Python; run it from source.
COPY robouse/ /opt/robouse/
ENV PYTHONPATH=/opt/robouse/src
COPY sim-entry.sh /usr/local/bin/robouse-sim-entry
RUN chmod 755 /usr/local/bin/robouse-sim-entry \
 && mkdir -p /rpc /episode /task /logs/verifier \
 && python -c "import robouse.session, robouse.backends.metaworld_backend"

WORKDIR /episode
CMD ["robouse-sim-entry"]
