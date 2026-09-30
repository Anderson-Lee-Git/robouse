"""Build the Daytona snapshot for the GPU track's ManiSkill3 / Genesis / MuJoCo Playground worker (no GPU needed to build)."""

import sys
import time

from daytona import CreateSnapshotParams, GpuType, Image, Resources
from dt import d

name = sys.argv[1] if len(sys.argv) > 1 else "robouse-gpu-sims-v4"
img = (
    Image.base("ubuntu:22.04")
    .env(
        {
            "DEBIAN_FRONTEND": "noninteractive",
            "UV_LINK_MODE": "hardlink",
            "PATH": "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "NVIDIA_DRIVER_CAPABILITIES": "all",
            "MUJOCO_GL": "egl",
            "PYOPENGL_PLATFORM": "egl",
        }
    )
    .run_commands(
        "apt-get update -qq && apt-get install -y -qq git wget curl ffmpeg libegl1 libgl1 libglib2.0-0 libvulkan1 vulkan-tools libxt6 libglu1-mesa libsm6 libxrender1 libxi6 libxrandr2 libxkbcommon0 libx11-6 build-essential unzip ca-certificates >/dev/null && rm -rf /var/lib/apt/lists/*",
        "curl -LsSf https://astral.sh/uv/install.sh | sh",
        # ManiSkill3 + Genesis share one torch venv
        "uv venv -q --python 3.11 /opt/sim && uv pip install -q --python /opt/sim/bin/python torch torchvision --index-url https://download.pytorch.org/whl/cu128",
        "uv pip install -q --python /opt/sim/bin/python mani_skill==3.0.1 mplib genesis-world pillow imageio imageio-ffmpeg trimesh 'numpy==1.26.4' 'mplib==0.1.1' && /opt/sim/bin/pip --version || true",
        # MuJoCo Playground (JAX / MJX)
        "uv venv -q --python 3.12 /opt/mjx && uv pip install -q --python /opt/mjx/bin/python 'jax[cuda12]==0.7.2' mujoco mujoco-mjx playground brax flax orbax-checkpoint mediapy pillow imageio imageio-ffmpeg",
        "/opt/mjx/bin/python -c 'from mujoco_playground._src import mjx_env; mjx_env.ensure_menagerie_exists()' || true",
        "uv cache clean",
    )
)
t = time.time()
s = d.snapshot.create(
    CreateSnapshotParams(
        name=name, image=img, resources=Resources(cpu=16, memory=64, disk=150, gpu=1, gpu_type=[GpuType.RTX_PRO_6000])
    ),
    on_logs=lambda l: print(l.rstrip()[:300], flush=True),
    timeout=0,
)
print("SNAPSHOT", s.name, s.state, round(time.time() - t), "s")
