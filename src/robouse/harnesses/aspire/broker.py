"""The practice broker of an aspire trial: practice episodes on other seeds of the task, never the scored one.

ASPIRE debugs a program on development seeds, checks it once on unseen-check seeds and evaluates the frozen program on
held-out seeds. In a Robo Use trial the held-out evaluation is the scored episode, and the broker provides the rest:
it runs in the runner's process (outside the agent's sandbox) and serves `cap-harness` in the agent's workspace over
HTTP on 127.0.0.1, behind a per-trial token. Each practice episode is the task's own episode server (`robouse serve`,
unchanged) on a practice seed, recorded under the trial folder's `aspire/practice/`, out of the agent's reach; the
agent gets its records through the broker.

The broker refuses a seed that is not one of the trial's practice seeds, any seed whose scene is protected (the scored
episode's, by the task backend's own seed rule), a second run of an unseen-check seed (ASPIRE measures those once),
anything past the practice budget, and everything after the trial is frozen. Requests are forwarded without the
reference solution's token and without `runner` marks; ending an episode goes through `finish`, which returns the
episode server's signed verdict.

Freezing ends practice, and only the harness's driver can ask for it (a key it alone holds; the agent holds the
broker's token): running practice episodes are stopped, and the skill library and the selected program are copied out
of the workspace into the trial folder, so what the trial records, and what a persistent library receives, is the
state at the end of practice. The copy reads regular files only, each folder and file opened relative to its parent
without following a link, from the workspace folder as it was opened before the agent started (WorkspaceReader).

Practice episode sockets are named like every episode socket (robouse-<hex>.sock in /tmp), which the macOS sandbox
refuses to every trial's agent but its own scored one, and which bubblewrap's private /tmp hides.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ...core.protocol import token_matches, verify_result
from ...lib.text import clip

AGENT_OPS = ("info", "status", "observe", "act", "move_to", "grip", "skill")  # what a program may send
MAX_FILE_BYTES = 512 * 1024  # a library file or a program copied out of the workspace
MAX_COPY_BYTES = 20 * 1024 * 1024  # all files copied out of one folder
READY_TIMEOUT_S = 600


def _send(path: str, req: dict, timeout: float = 3600) -> dict:
    """One request to an episode server's socket (no token: practice episodes get no privileged state)."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode() or '{"ok": false, "error": "empty response"}')
    except (FileNotFoundError, ConnectionRefusedError):
        return {"ok": False, "error": "the practice episode's server is not running (the episode may have ended)"}
    except TimeoutError:
        return {"ok": False, "error": "no answer from the practice episode's server"}
    finally:
        s.close()


def inside(path: Path, root: Path) -> bool:
    """`path`, resolved, is `root` or inside it."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK  # O_NONBLOCK: a FIFO planted in place of a file never blocks


def _read_at(dir_fd: int, name: str, limit: int) -> bytes | None:
    """A regular file `name` in the folder `dir_fd`, if it is one (checked on the open descriptor) and at most `limit`
    bytes; never through a link."""
    try:
        fd = os.open(name, FILE_FLAGS, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        chunks, size = [], 0
        while chunk := os.read(fd, 1 << 16):
            size += len(chunk)
            if size > limit:  # it grew after fstat
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


class WorkspaceReader:
    """Reads regular files out of the agent's workspace without following a link on the way. The workspace folder is
    opened once, when the reader is made (before the agent starts); every folder below it and every file is opened
    relative to its parent with O_NOFOLLOW and checked on the open descriptor (fstat). A path swapped for a link at
    any moment is not followed: the read fails instead of reaching outside."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.fd: int | None = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _parts(self, p: Path) -> tuple[str, ...] | None:
        try:
            parts = Path(p).relative_to(self.root).parts  # by name: nothing is resolved through the file system
        except ValueError:
            return None
        return None if any(x in ("", ".", "..") for x in parts) else parts

    def _open_dir(self, parts: tuple[str, ...]) -> int | None:
        if self.fd is None:
            return None
        fd = os.dup(self.fd)
        for part in parts:
            try:
                sub = os.open(part, DIR_FLAGS, dir_fd=fd)
            except OSError:
                os.close(fd)
                return None
            os.close(fd)
            fd = sub
        return fd

    def read(self, p: Path, limit: int = MAX_FILE_BYTES) -> bytes | None:
        """The bytes of the regular file at `p` inside the workspace, else None."""
        parts = self._parts(p)
        if not parts:
            return None
        fd = self._open_dir(parts[:-1])
        if fd is None:
            return None
        try:
            return _read_at(fd, parts[-1], limit)
        finally:
            os.close(fd)

    def readlink(self, p: Path) -> str | None:
        """The target of the link at `p` inside the workspace, as text (the link is read, not followed), else None."""
        parts = self._parts(p)
        if not parts:
            return None
        fd = self._open_dir(parts[:-1])
        if fd is None:
            return None
        try:
            return os.readlink(parts[-1], dir_fd=fd)
        except OSError:
            return None
        finally:
            os.close(fd)

    def read_text(self, p: Path) -> str | None:
        data = self.read(p)
        try:
            return data.decode() if data is not None else None
        except UnicodeDecodeError:
            return None

    def copy(self, src: Path, dest: Path, suffixes: tuple[str, ...]) -> list[str]:
        """Copy the regular files under `src` with these suffixes into `dest`, keeping relative paths, skipping
        folders whose name starts with a dot; each at most MAX_FILE_BYTES and MAX_COPY_BYTES in all. Returns the
        relative paths copied."""
        parts = self._parts(src)
        fd = self._open_dir(parts) if parts is not None else None
        copied: list[str] = []
        if fd is None:
            return copied
        try:
            self._walk(fd, Path(), dest, suffixes, copied, [0])
        finally:
            os.close(fd)
        return copied

    def _walk(self, fd: int, rel: Path, dest: Path, suffixes: tuple[str, ...], copied: list[str], total: list[int]):
        with os.scandir(fd) as it:
            entries = sorted(it, key=lambda e: e.name)
        for e in entries:
            if e.is_symlink():
                continue
            if e.is_dir(follow_symlinks=False):
                if e.name.startswith("."):
                    continue
                try:
                    sub = os.open(e.name, DIR_FLAGS, dir_fd=fd)
                except OSError:
                    continue
                try:
                    self._walk(sub, rel / e.name, dest, suffixes, copied, total)
                finally:
                    os.close(sub)
            elif e.name.endswith(suffixes):
                data = _read_at(fd, e.name, min(MAX_FILE_BYTES, MAX_COPY_BYTES - total[0]))
                if data is None:
                    continue
                out = dest / rel / e.name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
                total[0] += len(data)
                copied.append(str(rel / e.name))


def copy_regular_files(src: Path, dest: Path, root: Path, suffixes: tuple[str, ...]) -> list[str]:
    """WorkspaceReader(root).copy(...), for a one-off copy (the root folder opened now)."""
    try:
        reader = WorkspaceReader(root)
    except OSError:
        return []
    try:
        return reader.copy(src, dest, suffixes)
    finally:
        reader.close()


def read_regular_file(p: Path, root: Path) -> str | None:
    """WorkspaceReader(root).read_text(p), for a one-off read (the root folder opened now)."""
    try:
        reader = WorkspaceReader(root)
    except OSError:
        return None
    try:
        return reader.read_text(p)
    finally:
        reader.close()


class Episode:
    """One practice episode: a `robouse serve` process on a practice seed."""

    def __init__(self, eid: str, seed: int, scene: Any, run_dir: Path, sock: str, proc: subprocess.Popen, key: str):
        self.id, self.seed, self.scene, self.run_dir, self.sock, self.proc, self.key = (
            eid,
            seed,
            scene,
            run_dir,
            sock,
            proc,
            key,
        )
        self.started = time.time()
        self.verdict: dict | None = None
        self.ended = False
        self.lock = threading.Lock()


class PracticeBroker:
    """See the module docstring. `scene(seed)` is the task backend's seed rule; `protected` the scenes no practice
    episode may show; `snapshot()` (called once, at freeze) copies the library and the selected program out."""

    def __init__(
        self,
        task_path: Path,
        record_dir: Path,
        dev: list[int],
        unseen: list[int],
        scene: Callable[[int], Any],
        protected: set,
        max_episodes: int,
        workers: int,
        episode_wall_s: float,
        split: str | None = None,
        snapshot: Callable[[], dict] | None = None,
    ):
        self.task_path = Path(task_path)
        self.record_dir = Path(record_dir)
        self.dev, self.unseen = list(dev), list(unseen)
        self.scene = scene
        self.protected = set(protected)
        self.max_episodes = int(max_episodes)
        self.workers = max(1, int(workers))
        self.episode_wall_s = float(episode_wall_s)
        self.split = split
        self.snapshot = snapshot
        self.token = secrets.token_urlsafe(18)  # the agent's: cap-harness calls the broker with it
        self.freeze_key = secrets.token_urlsafe(24)  # the driver's alone: only it may end practice
        self.episodes: dict[str, Episode] = {}
        self.procs: dict[str, subprocess.Popen] = {}  # every episode server started, from its first moment
        self.order: list[str] = []
        self.unseen_used: set[int] = set()
        self.refused: list[dict] = []
        self.slots = threading.BoundedSemaphore(self.workers)
        self.lock = threading.Lock()
        self.frozen: dict | None = None
        self.frozen_by: str | None = None
        self.server: ThreadingHTTPServer | None = None
        self.url = ""

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    def start(self) -> str:
        broker = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                broker._handle(self, "GET")

            def do_POST(self) -> None:
                broker._handle(self, "POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, name="aspire-broker", daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/{self.token}"
        return self.url

    def stop(self) -> None:
        """Freeze (if the driver did not), stop every practice episode and the HTTP server. The runner exits after
        this, and its daemon threads with it, so an episode server still starting (a request that came in as practice
        froze) is stopped here rather than left to its thread."""
        if self.frozen is None:
            self.freeze("runner")
        with self.lock:
            procs = list(self.procs.values())
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    # ---- policy ----------------------------------------------------------------------------------------------------
    def refusal(self, seed: Any) -> str | None:
        """Why a practice episode on `seed` may not start, or None. Called with the lock held."""
        if self.frozen is not None:
            return "practice is over: the trial is frozen for Stage 2"
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            return f"a seed is a non-negative integer, not {seed!r}"
        if seed not in self.dev and seed not in self.unseen:
            return (
                f"seed {seed} is not a practice seed of this trial (development seeds {fmt(self.dev)}, unseen-check "
                f"seeds {fmt(self.unseen)}); held-out evaluation is the scored episode, which Robo Use runs after you "
                "exit"
            )
        if self.scene(seed) in self.protected:
            return f"seed {seed} shows a protected scene (the scored episode's), so it cannot be practised on"
        if seed in self.unseen and seed in self.unseen_used:
            return f"unseen-check seed {seed} has run once already; ASPIRE measures each unseen-check seed once"
        if len(self.order) >= self.max_episodes:
            return f"the practice budget is used: {self.max_episodes} practice episodes in this trial"
        return None

    # ---- episodes --------------------------------------------------------------------------------------------------
    def start_episode(self, seed: Any, label: str = "") -> tuple[int, dict]:
        with self.lock:
            if why := self.refusal(seed):
                self.refused.append({"seed": seed, "why": why})
                return 409, {"error": why}
            eid = f"e{len(self.order) + 1:04d}"
            self.order.append(eid)  # counts against the budget from now, even if it never starts
            if seed in self.unseen:
                self.unseen_used.add(seed)
        if not self.slots.acquire(timeout=7200):
            return 503, {"error": "no practice slot came free within two hours"}
        try:
            ep = self._spawn(eid, int(seed), label)
        except Exception as e:  # noqa: BLE001 - reported to the agent and recorded
            self.slots.release()
            if self.frozen is not None:
                return 409, {"error": "practice is over: the trial is frozen for Stage 2"}
            return 500, {"error": clip(f"the practice episode did not start: {type(e).__name__}: {e}", 1000)}
        with self.lock:
            self.episodes[eid] = ep
            frozen = self.frozen is not None
        if frozen:  # frozen while it started
            with ep.lock:
                self._end(ep, kill=True)
            return 409, {"error": "practice is over: the trial is frozen for Stage 2"}
        threading.Thread(target=self._reap, args=(ep,), name=f"aspire-reap-{eid}", daemon=True).start()
        info = _send(ep.sock, {"op": "info"}, timeout=120)
        return 200, {"id": eid, "seed": seed, "scene": _jsonable(ep.scene), "info": info.get("result") or {}}

    def _spawn(self, eid: str, seed: int, label: str) -> Episode:
        run_dir = self.record_dir / "practice" / f"{eid}-seed{seed:04d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "label.txt").write_text(label[:200])
        # named like every episode socket, which the sandbox refuses to agents; the agent never connects to it
        sock = f"/tmp/robouse-{uuid.uuid4().hex[:12]}.sock"
        ready = run_dir / "ready"
        cmd = [sys.executable, "-m", "robouse.cli", "serve", "--task", str(self.task_path), "--run-dir", str(run_dir)]
        cmd += ["--socket", sock, "--ready-file", str(ready), "--max-wall-s", str(self.episode_wall_s)]
        cmd += ["--seed", str(seed), "--secrets-stdin"] + (["--split", self.split] if self.split else [])
        from ...runner.trial import without_provider_keys

        env = {k: v for k, v in without_provider_keys(os.environ).items() if k != "ROBOUSE_ORACLE_TOKEN"}
        key = secrets.token_hex(32)
        with open(run_dir / "server.log", "w") as log:
            proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
        with self.lock:
            self.procs[eid] = proc  # stop() finds it from here on, even if this thread never returns
        try:
            assert proc.stdin is not None
            # a token nobody holds: no request to a practice episode is privileged
            proc.stdin.write(json.dumps({"oracle_token": secrets.token_hex(16), "result_key": key}).encode() + b"\n")
            proc.stdin.close()
            deadline = time.time() + READY_TIMEOUT_S
            while not ready.exists():
                if self.frozen is not None:
                    raise RuntimeError("practice froze while the episode started")
                if proc.poll() is not None:
                    log_lines = (run_dir / "server.log").read_text(errors="replace").splitlines()
                    lines = [ln for ln in log_lines if ln.strip()]
                    raise RuntimeError(f"episode server exited ({proc.returncode}): {lines[-1] if lines else ''}")
                if time.time() > deadline:
                    raise TimeoutError("the practice episode's server did not start")
                time.sleep(0.2)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        return Episode(eid, seed, self.scene(seed), run_dir, sock, proc, key)

    def _reap(self, ep: Episode) -> None:
        """A practice server that ends on its own (its wall-clock budget, a crash) frees its slot."""
        ep.proc.wait()
        with ep.lock:
            self._end(ep, kill=True)

    def request(self, eid: str, req: Any) -> tuple[int, dict]:
        ep = self.episodes.get(eid)
        if ep is None:
            return 404, {"error": f"no practice episode {eid!r}"}
        if not isinstance(req, dict) or req.get("op") not in AGENT_OPS:
            return 400, {"error": f"a practice request is one of {', '.join(AGENT_OPS)}; finish ends the episode"}
        req = {k: v for k, v in req.items() if k not in ("token", "runner")}
        with ep.lock:
            if ep.ended:
                return 200, {"ok": False, "error": "the practice episode has ended"}
            reply = _send(ep.sock, req)
        res = reply.get("result")
        if isinstance(res, dict) and "image_path" in res:  # paths inside the trial folder: name them by file
            res["image_path"] = _relative(res["image_path"], ep.run_dir)
        return 200, reply

    def finish(self, eid: str, op: str, text: str) -> tuple[int, dict]:
        ep = self.episodes.get(eid)
        if ep is None:
            return 404, {"error": f"no practice episode {eid!r}"}
        if op not in ("done", "give_up"):
            return 400, {"error": "finish takes op done or give_up"}
        with ep.lock:
            if not ep.ended:
                _send(ep.sock, {"op": op, "text": str(text)[:500]}, timeout=900)
                self._end(ep)
        return 200, {"verdict": ep.verdict or {}, "files": self.files(ep)}

    def _end(self, ep: Episode, kill: bool = False) -> None:
        """Stop the episode's server and keep its checked verdict. Called once per episode, with its lock held (or
        while freezing)."""
        if ep.ended:
            return
        ep.ended = True
        if not kill:
            _send(ep.sock, {"op": "shutdown"}, timeout=60)
        try:
            ep.proc.wait(timeout=5 if kill else 120)
        except subprocess.TimeoutExpired:
            ep.proc.kill()
            ep.proc.wait()
        try:
            verdict = json.loads((ep.run_dir / "result.json").read_text())
        except (OSError, ValueError):
            verdict = {}
        if verdict and not verify_result(verdict, ep.key):
            verdict = {"outcome": "unverified", "success": False}
        verdict.pop("signature", None)
        ep.verdict = verdict
        self.slots.release()

    def files(self, ep: Episode) -> list[str]:
        return sorted(
            str(p.relative_to(ep.run_dir))
            for p in ep.run_dir.rglob("*")
            if p.is_file() and p.name not in ("ready", "server.log")
        )

    def file(self, eid: str, rel: str) -> tuple[int, bytes | dict]:
        ep = self.episodes.get(eid)
        if ep is None:
            return 404, {"error": f"no practice episode {eid!r}"}
        p = ep.run_dir / rel
        if ".." in Path(rel).parts or not inside(p, ep.run_dir) or not p.is_file() or p.name in ("ready",):
            return 404, {"error": f"no file {rel!r} in practice episode {eid}"}
        return 200, p.read_bytes()

    # ---- freeze ----------------------------------------------------------------------------------------------------
    def freeze(self, by: str) -> dict:
        """End practice once: stop the running episodes, copy the library and the selected program out of the
        workspace (`snapshot`) and keep the result, which every later call returns."""
        with self.lock:
            if self.frozen is not None:
                return self.frozen
            self.frozen = {}  # refuse new episodes from here
            self.frozen_by = by
            running = [e for e in self.episodes.values() if not e.ended]
        for ep in running:
            with ep.lock:
                if not ep.ended:
                    _send(ep.sock, {"op": "give_up", "text": "practice ended (the trial froze)"}, timeout=60)
                    self._end(ep)
        out = self.snapshot() if self.snapshot is not None else {}
        with self.lock:
            self.frozen = out
        return out

    # ---- record ----------------------------------------------------------------------------------------------------
    def record(self) -> dict:
        eps = [self.episodes[e] for e in self.order if e in self.episodes]
        rows = []
        for ep in eps:
            v = ep.verdict or {}
            rows.append(
                {
                    "id": ep.id,
                    "seed": ep.seed,
                    "scene": _jsonable(ep.scene),
                    "outcome": v.get("outcome"),
                    "success": v.get("success"),
                    "steps_used": v.get("steps_used"),
                    "wall_time_s": v.get("wall_time_s"),
                }
            )
        return {
            "episodes": len(self.order),
            "max_episodes": self.max_episodes,
            "workers": self.workers,
            "dev_seeds": self.dev,
            "unseen_seeds": self.unseen,
            "unseen_used": sorted(self.unseen_used),
            "successes": sum(1 for r in rows if r["success"]),
            "seeds_run": sorted({r["seed"] for r in rows}),
            "scenes_run": sorted({json.dumps(r["scene"]) for r in rows}),
            "refused": self.refused[-50:],
            "frozen_by": self.frozen_by,
            "runs": rows,
        }

    # ---- HTTP ------------------------------------------------------------------------------------------------------
    def _handle(self, h: BaseHTTPRequestHandler, method: str) -> None:
        parts = [p for p in h.path.split("?")[0].split("/") if p]
        if not parts or not secrets.compare_digest(parts[0], self.token):
            return _reply(h, 403, {"error": "unknown practice broker path"})
        parts = parts[1:]
        body: Any = {}
        if method == "POST":
            n = int(h.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                return _reply(h, 413, {"error": "request too large"})
            try:
                body = json.loads(h.rfile.read(n).decode() or "{}")
            except ValueError:
                return _reply(h, 400, {"error": "the body is not JSON"})
        try:
            if method == "GET" and parts == ["status"]:
                return _reply(h, 200, {**self.record(), "frozen": self.frozen is not None})
            if method == "POST" and parts == ["episodes"]:
                return _reply(h, *self.start_episode(body.get("seed"), str(body.get("label") or "")))
            if method == "POST" and parts == ["freeze"]:
                if not token_matches(body.get("key"), self.freeze_key):
                    return _reply(h, 403, {"error": "only the harness's driver ends practice"})
                return _reply(h, 200, self.freeze(str(body.get("by") or "driver")))
            if len(parts) == 2 and parts[0] == "episodes" and method == "POST":
                return _reply(h, *self.request(parts[1], body.get("req")))
            if len(parts) == 3 and parts[0] == "episodes" and parts[2] == "finish" and method == "POST":
                return _reply(h, *self.finish(parts[1], str(body.get("op") or "done"), str(body.get("text") or "")))
            if len(parts) >= 4 and parts[0] == "episodes" and parts[2] == "files" and method == "GET":
                status, data = self.file(parts[1], "/".join(parts[3:]))
                return _reply(h, status, data)
        except Exception as e:  # noqa: BLE001 - the agent gets the error; the trial goes on
            return _reply(h, 500, {"error": clip(f"{type(e).__name__}: {e}", 1000)})
        return _reply(h, 404, {"error": f"unknown practice broker request {method} /{'/'.join(parts)}"})


def _reply(h: BaseHTTPRequestHandler, status: int, data: dict | bytes) -> None:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    try:
        h.send_response(status)
        h.send_header("Content-Type", "application/octet-stream" if isinstance(data, bytes) else "application/json")
        h.send_header("Content-Length", str(len(raw)))
        h.end_headers()
        h.wfile.write(raw)
    except OSError:  # the client went away
        pass


def _relative(path: Any, root: Path) -> Any:
    if isinstance(path, list):
        return [_relative(p, root) for p in path]
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except (TypeError, ValueError, OSError):
        return path


def _jsonable(v: Any) -> Any:
    return list(v) if isinstance(v, tuple) else v


def fmt(seeds: list[int]) -> str:
    """101-125, or 2,5,9: as ASPIRE's campaign.format_seed_range writes a band."""
    if not seeds:
        return "none"
    s = sorted(seeds)
    return f"{s[0]}-{s[-1]}" if s == list(range(s[0], s[-1] + 1)) and len(s) > 1 else ",".join(map(str, s))
