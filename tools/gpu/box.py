"""GPU-track sandbox lifecycle with a GPU-hours ledger. Usage:
  box.py create NAME SNAPSHOT     create a labelled GPU sandbox (auto-stop after 20 idle minutes, deleted when stopped, 6-hour cap)
  box.py delete ID|NAME           delete it and close its ledger entry
  box.py list                     our sandboxes (label robouse=gpu-track)
  box.py ledger                   GPU-hours so far
"""
import json, os, sys, time
from pathlib import Path
from dt import d, LABEL
LEDGER = Path(__file__).resolve().parents[2] / "runs" / "_gpu" / "ledger.jsonl"

def ours():
    from daytona import ListSandboxesQuery
    r = d.list(ListSandboxesQuery(labels=LABEL))
    return [s for s in getattr(r, "items", r) if (s.labels or {}).get("robouse") == "gpu-track"]

def log(ev):
    ev["t"] = time.time(); ev["utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(LEDGER, "a") as f: f.write(json.dumps(ev) + "\n")

def ledger():
    open_, total, rows = {}, 0.0, []
    for line in LEDGER.read_text().splitlines() if LEDGER.exists() else []:
        e = json.loads(line)
        if e["ev"] == "create": open_[e["id"]] = e
        elif e["ev"] == "delete" and e["id"] in open_:
            c = open_.pop(e["id"]); h = (e["t"] - c["t"]) / 3600 * c.get("gpus", 1); total += h
            rows.append((c["name"], c["utc"], e["utc"], round(h, 3)))
    for c in open_.values():
        h = (time.time() - c["t"]) / 3600 * c.get("gpus", 1); total += h
        rows.append((c["name"], c["utc"], "RUNNING", round(h, 3)))
    return rows, total

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "create":
        from daytona import CreateSandboxFromSnapshotParams
        name, snap = sys.argv[2], sys.argv[3]
        if len(ours()) >= 2: sys.exit("already 2 gpu-track sandboxes; delete one first")
        t = time.time()
        s = d.create(CreateSandboxFromSnapshotParams(name=name, snapshot=snap, labels={**LABEL, "owner": "robouse-gpu-track-agent"},
                     auto_stop_interval=20, auto_delete_interval=0, ephemeral=True, ttl_minutes=360), timeout=1800)
        log({"ev": "create", "id": s.id, "name": name, "snapshot": snap, "gpus": 1})
        print("ID", s.id, "in", round(time.time() - t), "s")
        print(s.process.exec("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv; nproc; free -g | head -2; df -h / | tail -1", timeout=60).result)
    elif cmd == "delete":
        key = sys.argv[2]
        for s in ours():
            if s.id == key or s.name == key:
                d.delete(s); log({"ev": "delete", "id": s.id, "name": s.name}); print("deleted", s.id)
    elif cmd == "list":
        for s in ours(): print(s.id, s.name, s.state, s.labels)
    elif cmd == "ledger":
        rows, total = ledger()
        for r in rows: print(*r)
        print("TOTAL GPU-hours", round(total, 3))
