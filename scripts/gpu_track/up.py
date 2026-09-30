"""Upload the GPU worker code to our sandbox, (re)start workers, and write the endpoints file.
  up.py BOX push                       upload backends/gpu_worker/*.py to /root/gw
  up.py BOX start SIM PORT [PYTHON]    (re)start one worker in a session
  up.py BOX links SIM=PORT ...         write runs/_gpu/remote.json (0600) with preview URLs
  up.py BOX sh 'cmd'                   run a shell command (prints output)
"""
import json, os, secrets, sys, time
from pathlib import Path
from dt import d
from box import ours
SRC = Path(__file__).resolve().parents[2] / "src" / "robouse" / "backends" / "gpu_worker"
REMOTE = Path(__file__).resolve().parents[2] / "runs" / "_gpu" / "remote.json"
SECRET = Path(__file__).resolve().parents[2] / "runs" / "_gpu" / "secret"
PY = {"maniskill": "/opt/sim/bin/python", "genesis": "/opt/sim/bin/python", "playground": "/opt/mjx/bin/python", "isaaclab": "/opt/isaac/bin/python"}

def box(name):
    for s in ours():
        if s.name == name or s.id == name: return s
    sys.exit(f"no sandbox {name}")

def secret():
    if not SECRET.exists():
        SECRET.write_text(secrets.token_hex(24)); SECRET.chmod(0o600)
    return SECRET.read_text().strip()

def sh(s, cmd, timeout=600):
    r = s.process.exec(cmd, timeout=timeout)
    return r.result

if __name__ == "__main__":
    s = box(sys.argv[1]); cmd = sys.argv[2]
    if cmd == "push":
        sh(s, "mkdir -p /root/gw")
        for f in sorted(SRC.glob("*.py")):
            s.fs.upload_file(f.read_bytes(), f"/root/gw/{f.name}")
        extra = SRC / "assets"
        if extra.is_dir():
            for f in extra.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(SRC); sh(s, f"mkdir -p /root/gw/{rel.parent}")
                    s.fs.upload_file(f.read_bytes(), f"/root/gw/{rel}")
        print("pushed", len(list(SRC.glob('*.py'))), "files")
    elif cmd == "start":
        from daytona import SessionExecuteRequest
        sim, port = sys.argv[3], sys.argv[4]
        py = sys.argv[5] if len(sys.argv) > 5 else PY[sim]
        sid = f"w-{sim}"
        sh(s, f"pkill -f 'server.py --sim {sim}' ; sleep 1; true")
        try: s.process.delete_session(sid)
        except Exception: pass
        s.process.create_session(sid)
        envs = f"ROBOUSE_GPU_SECRET={secret()} OMNI_KIT_ACCEPT_EULA=YES MUJOCO_GL=egl PYOPENGL_PLATFORM=egl PYTHONUNBUFFERED=1"
        s.process.execute_session_command(sid, SessionExecuteRequest(command=f"cd /root/gw && {envs} {py} server.py --sim {sim} --port {port} > /root/gw/{sim}.log 2>&1", run_async=True))
        time.sleep(3); print(sh(s, f"tail -3 /root/gw/{sim}.log"))
    elif cmd == "links":
        old = json.loads(REMOTE.read_text()) if REMOTE.exists() else {}
        workers, hdrs = old.get("workers", {}), old.get("worker_headers", {})
        for kv in sys.argv[3:]:
            sim, port = kv.split("=")
            l = s.get_preview_link(int(port)); workers[sim] = l.url; hdrs[sim] = {"x-daytona-preview-token": l.token}
        REMOTE.parent.mkdir(parents=True, exist_ok=True)
        REMOTE.write_text(json.dumps({"secret": secret(), "workers": workers, "worker_headers": hdrs}, indent=1))
        REMOTE.chmod(0o600); print("wrote endpoints for", sorted(workers))
    elif cmd == "sh":
        print(sh(s, sys.argv[3], timeout=int(sys.argv[4]) if len(sys.argv) > 4 else 600))
