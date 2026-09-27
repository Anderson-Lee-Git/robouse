"""Export DexJoCo raw demonstrations (replay.zarr) to JSON: recorded absolute actions + the initial scene state.

Run with the DexJoCo virtualenv's Python (it has zarr):
  ~/.cache/robouse/dexjoco-venv/bin/python adapters/dexjoco/export_demos.py [RAW_DIR] [OUT_DIR]
RAW_DIR defaults to ~/.cache/robouse/dexjoco-demos/dexjoco_raw_datasets (downloaded from the Hugging Face dataset
DexJoCo/DexJoCo-Datasets-Raw, replay.zarr folders only); OUT_DIR to ~/.cache/robouse/dexjoco-demos/json.
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import zarr

raw = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / ".cache/robouse/dexjoco-demos/dexjoco_raw_datasets")
out = Path(sys.argv[2] if len(sys.argv) > 2 else Path.home() / ".cache/robouse/dexjoco-demos/json")
out.mkdir(parents=True, exist_ok=True)
for d in sorted(glob.glob(f"{raw}/*/*/replay.zarr")):
    task, demo = Path(d).parts[-3], Path(d).parts[-2]
    z = zarr.open(d, "r")
    rec = {"task": task, "demo": demo, "source": f"DexJoCo/DexJoCo-Datasets-Raw/dexjoco_raw_datasets/{task}/{demo}",
           "init_state": [float(x) for x in np.asarray(z["data"]["state"][0]).ravel()],
           "actions": [[round(float(x), 7) for x in row] for row in np.asarray(z["data"]["action"])]}
    (out / f"{task}__{demo}.json").write_text(json.dumps(rec))
    print(task, demo, len(rec["actions"]))
