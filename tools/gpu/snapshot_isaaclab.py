"""Daytona snapshot for the GPU track's Isaac Lab worker (Isaac Sim 5.1 pip wheels + Isaac Lab v2.3.0)."""
import sys, time
from dt import d
from daytona import CreateSnapshotParams, Image, Resources, GpuType
name = sys.argv[1] if len(sys.argv) > 1 else "robouse-gpu-isaaclab-v3"
img = (Image.base("ubuntu:22.04")
       .env({"DEBIAN_FRONTEND": "noninteractive", "PATH": "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
             "NVIDIA_DRIVER_CAPABILITIES": "all", "OMNI_KIT_ACCEPT_EULA": "YES", "ACCEPT_EULA": "Y", "TERM": "xterm"})
       .run_commands(
           "apt-get update -qq && apt-get install -y -qq git wget curl ffmpeg libegl1 libgl1 libglib2.0-0 libvulkan1 vulkan-tools libxt6 libglu1-mesa libsm6 libxrender1 libxi6 libxrandr2 libxkbcommon0 libx11-6 build-essential cmake unzip ca-certificates >/dev/null && rm -rf /var/lib/apt/lists/*",
           "curl -LsSf https://astral.sh/uv/install.sh | sh",
           "uv venv -q --seed --python 3.11 /opt/isaac",
           "uv pip install -q --python /opt/isaac/bin/python torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128",
           "uv pip install -q --python /opt/isaac/bin/python 'isaacsim[all]==5.1.0' --extra-index-url https://pypi.nvidia.com",
           "git clone -q --depth 1 -b v2.3.0 https://github.com/isaac-sim/IsaacLab.git /opt/IsaacLab",
           "bash -lc 'source /opt/isaac/bin/activate && cd /opt/IsaacLab && ./isaaclab.sh --install none > /tmp/il_install.log 2>&1; tail -5 /tmp/il_install.log'",
           "cd /opt/IsaacLab && /opt/isaac/bin/pip install -q 'setuptools<70' wheel && /opt/isaac/bin/pip install -q --no-build-isolation flatdict==4.0.1 && /opt/isaac/bin/pip install -q -e source/isaaclab",
           "/opt/isaac/bin/pip install -q packaging==23.0 click==8.1.7 psutil==5.9.8 pillow imageio imageio-ffmpeg",
           "uv cache clean; rm -rf /root/.cache/pip",
       ))
t = time.time()
s = d.snapshot.create(CreateSnapshotParams(name=name, image=img, resources=Resources(cpu=16, memory=64, disk=150, gpu=1, gpu_type=[GpuType.RTX_PRO_6000])),
                      on_logs=lambda l: print(l.rstrip()[:300], flush=True), timeout=0)
print("SNAPSHOT", s.name, s.state, round(time.time() - t), "s")
