#!/bin/bash
# Set up the isolated RoboCasa environment used by the `robocasa` backend (about 4.7 GB in ~/.cache/robouse).
# RoboCasa pins MuJoCo 3.3.1 / numpy 2.2 / robosuite 1.5, which conflict with the main robouse venv, so it gets its own.
# The asset subset (textures, lightwheel fixtures and objects) comes from pinned Hugging Face revisions listed in
# assets/robocasa/provenance.json; every zip is checked against its SHA-256 (the same files RoboCasa's own
# download_kitchen_assets.py fetches as tex, fixtures_lw and objs_lw).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
D="${ROBOUSE_ROBOCASA_HOME:-$HOME/.cache/robouse}"
mkdir -p "$D" && cd "$D"
[ -d robocasa-src ] || { git clone https://github.com/robocasa/robocasa.git robocasa-src && git -C robocasa-src checkout 456174f62b89b8fca99eaaf33949c29fec9cfc2a; }
[ -d robosuite-src ] || { git clone https://github.com/ARISE-Initiative/robosuite robosuite-src && git -C robosuite-src checkout 5ce6643f3092639d08f7b0f90ed1c6a84f50552c; }
uv venv robocasa-venv --python 3.12
PY=robocasa-venv/bin/python
uv pip install --python $PY "numpy==2.2.5" "mujoco==3.3.1" "scipy==1.18.1" "numba==0.67.0" "pillow==12.3.0" \
    "opencv-python-headless==5.0.0.93" "pyyaml==6.0.3" "tqdm==4.70.1" "termcolor==3.3.0" "imageio==2.37.4" \
    "imageio-ffmpeg==0.6.0" "h5py==3.16.0" "lxml==6.1.3" "gymnasium==1.3.0"
uv pip install --python $PY --no-deps -e robosuite-src
uv pip install --python $PY --no-deps -e robocasa-src   # not lerobot/torch/tianshou: only needed for RoboCasa's policy training code
$PY robocasa-src/robocasa/scripts/setup_macros.py
# minimal asset subset (about 1.9 GB of zips, 3.3 GB extracted): textures, lightwheel fixtures, lightwheel objects
$PY - "$REPO/assets/robocasa/provenance.json" robocasa-src/robocasa/models/assets <<'EOF'
import hashlib, json, sys, tempfile, urllib.request, zipfile
from pathlib import Path
manifest, root = json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2])
for f in manifest["files"]:
    with tempfile.TemporaryFile() as tmp:
        h = hashlib.sha256()
        with urllib.request.urlopen(f["url"], timeout=300) as r:
            while chunk := r.read(1 << 20):
                h.update(chunk)
                tmp.write(chunk)
        if h.hexdigest() != f["sha256"]:
            sys.exit(f"sha256 mismatch for {f['url']}")
        tmp.seek(0)
        zipfile.ZipFile(tmp).extractall(root / f["extract_to"])
    print("ok", f["path"], flush=True)
EOF
$PY -c "import robosuite, robocasa; print('robocasa ready, robosuite', robosuite.__version__)"
