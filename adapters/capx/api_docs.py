"""Write adapters/capx/api_docs.json: each CaP-X task's privileged API documentation exactly as CaP-X writes it into the
prompt (ApiBase.combined_doc of the API instance). Run with the CaP-X worker's Python (the capx runtime):

    $ROBOUSE_CAPX_PYTHON adapters/capx/api_docs.py
"""

import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
W = runpy.run_path(str(ROOT / "src/robouse/backends/capx/worker.py"))
out = {}
for task in W["TASKS"]:
    w = W["Worker"]()
    w.make(task, 1)
    d = w.docs()
    out[task] = {"functions": d["functions"], "combined_doc": d["combined_doc"]}
    w.close()
    print(task, d["functions"], file=sys.stderr)
(ROOT / "adapters/capx/api_docs.json").write_text(json.dumps(out, indent=1) + "\n")
