# runtime fixes on a fresh GPU sandbox: the NVIDIA GLX/Vulkan libraries are mounted without their .so.0 names
cd /usr/lib/x86_64-linux-gnu && for f in libGLX_nvidia libEGL_nvidia libnvidia-glcore libnvidia-glsi libnvidia-tls libnvidia-gpucomp libnvidia-rtcore; do v=$(ls $f.so.[0-9][0-9][0-9].* 2>/dev/null | head -1); [ -n "$v" ] && ln -sf $v $f.so.0; done; ldconfig
mkdir -p /usr/share/vulkan/icd.d && cp -n /etc/vulkan/icd.d/nvidia_icd.json /usr/share/vulkan/icd.d/ 2>/dev/null  # SAPIEN looks here
mkdir -p /root/out /root/policies
nvidia-smi --query-gpu=driver_version --format=csv,noheader
