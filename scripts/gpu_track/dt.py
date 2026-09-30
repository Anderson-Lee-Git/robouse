"""Daytona client for the GPU-track scripts. Needs DAYTONA_API_KEY (and optionally DAYTONA_API_URL/DAYTONA_TARGET) in the
environment, or a KEY=VALUE env file named by $DAYTONA_ENV_FILE. Never prints the key."""
import os

f = os.environ.get("DAYTONA_ENV_FILE")
if f and os.path.exists(f):
    for line in open(f):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.replace("export ", "").strip(), v.strip().strip('"').strip("'"))
from daytona import Daytona  # noqa: E402

d = Daytona()
LABEL = {"robouse": "gpu-track"}
