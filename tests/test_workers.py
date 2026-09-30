"""The simulator-worker framework: StdioWorker against a worker script, HttpWorker against serve_http."""
from __future__ import annotations

import socket
import sys
import textwrap
import threading
from pathlib import Path

import numpy as np
import pytest

from robouse.workers.client import HttpWorker, StdioWorker, WorkerError
from robouse.workers.wire import serve_http

WORKER = textwrap.dedent('''
    import numpy as np
    print("noise on stdout must not break the protocol")

    class Worker:
        def __init__(self):
            self.n = 0

        def echo(self, value):
            self.n += 1
            return {"value": value, "n": self.n, "np": np.float32(1.5)}

        def image(self, width, height):
            return np.full((height, width, 3), 7, dtype=np.uint8)

        def big(self):
            return np.arange(3_000_000, dtype=np.uint8)

        def boom(self):
            raise ValueError("bad thing")

        def _private(self):
            return 1
''')


@pytest.fixture()
def worker(tmp_path: Path):
    script = tmp_path / "fake_worker.py"
    script.write_text(WORKER)
    w = StdioWorker("fake", Path(sys.executable), script, timeout=30)
    yield w
    w.close()


def test_stdio_calls_arrays_and_errors(worker: StdioWorker) -> None:
    assert worker.call("echo", value=[1, 2]) == {"value": [1, 2], "n": 1, "np": 1.5}
    img = worker.call("image", width=4, height=3)
    assert img.shape == (3, 4, 3) and img.dtype == np.uint8 and int(img[0, 0, 0]) == 7
    assert worker.call("big").shape == (3_000_000,)  # larger than one pipe read
    with pytest.raises(WorkerError, match="ValueError: bad thing"):
        worker.call("boom")
    with pytest.raises(WorkerError, match="unknown command"):
        worker.call("_private")
    assert worker.call("echo", value=None)["n"] == 2  # the worker keeps serving after errors
    worker.close()
    assert not worker.alive
    with pytest.raises(WorkerError, match="exited"):
        worker.call("echo", value=1)


def test_stdio_missing_virtualenv(tmp_path: Path) -> None:
    with pytest.raises(WorkerError, match="virtualenv not found"):
        StdioWorker("fake", tmp_path / "nope" / "python", tmp_path / "w.py", setup="docs/x.md")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_worker_roundtrip_and_secret() -> None:
    port = _free_port()
    seen = []

    def handle(req: dict):
        seen.append(req)
        if req["method"] == "fail":
            raise RuntimeError("nope")
        return {"got": req["args"], "session": req.get("session")}

    threading.Thread(target=serve_http, args=(handle, port, "s3cret"), kwargs={"host": "127.0.0.1"},
                     daemon=True).start()
    w = HttpWorker(f"http://127.0.0.1:{port}", "s3cret", timeout=10, retry=frozenset({"observe"}))
    for _ in range(50):
        try:
            assert w.call("observe", x=1) == {"got": {"x": 1}, "session": None}
            break
        except WorkerError:
            import time

            time.sleep(0.1)
    w.session = "abc"
    assert w.call("step", a=[1])["session"] == "abc"
    with pytest.raises(WorkerError, match="RuntimeError: nope"):
        w.call("fail")
    bad = HttpWorker(f"http://127.0.0.1:{port}", "wrong", timeout=10)
    with pytest.raises(WorkerError, match="HTTP 403"):
        bad.call("observe")
    w.close()


def test_http_server_needs_a_secret() -> None:
    with pytest.raises(SystemExit, match="secret"):
        serve_http(lambda r: r, _free_port(), "")
