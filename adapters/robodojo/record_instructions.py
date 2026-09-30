"""Record RoboDojo's instruction for each task's layout from episode traces (the first `robo observe` of a trial).

Usage: python adapters/robodojo/record_instructions.py RUNS_DIR [RUNS_DIR ...]   -> adapters/robodojo/instructions.json
RoboDojo builds the instruction per layout (`gen_instruction`, e.g. the object named in general_pickup or the colour
order in stack_blocks_by_language); the worker reports it in `robo observe` as `instruction`."""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
out = json.loads((HERE / "instructions.json").read_text()) if (HERE / "instructions.json").exists() else {}
for root in sys.argv[1:]:
    for trace in sorted(glob.glob(f"{root}/robodojo-*/episode/trace.jsonl")):
        cfg = (
            json.loads((Path(trace).parents[1] / "config.json").read_text())
            if (Path(trace).parents[1] / "config.json").exists()
            else {}
        )
        for line in open(trace):
            r = (json.loads(line).get("resp") or {}).get("result") or {}
            st = r.get("state") if isinstance(r, dict) else None
            if st and st.get("instruction"):
                task = Path(trace).parents[1].name.split("__")[0]
                name = (
                    task.removeprefix("robodojo-")
                    .replace("-", "_")
                    .replace("push_t", "push_T")
                    .replace("swap_t", "swap_T")
                )
                out[name] = {"layout": st.get("layout"), "instruction": st["instruction"]}
                break
(HERE / "instructions.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
print(f"{len(out)} instructions")
