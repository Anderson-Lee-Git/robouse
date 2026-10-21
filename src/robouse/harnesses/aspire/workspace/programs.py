"""The program contract of the `aspire` harnesses: how a generated program is checked and run, in practice runs
(`cap-harness run` in the agent's workspace) and in the scored run (Stage 2, run by the driver) alike.

ASPIRE (NVlabs/ASPIRE, Apache-2.0) runs every generated program under cap-harness's restricted executor: the source is
parsed and refused if it imports anything but `math`, defines a class, uses `with`, `global`, `nonlocal`, `del` or a
name or attribute that starts with `_`; it runs with a short list of builtins and the public tools as globals; and its
top-level `result` is recorded. Robo Use keeps those rules and changes two things. Programs may also import `numpy`,
because the CaP-X API speaks numpy arrays, as CaP-X's own reference code does. And the tools are the task's own API
instead of cap-harness's: every skill `robo info` lists is a function of the same name (CaP-X's API on the CaP-X
suites), and the `robo` object holds the episode's other requests. A program never ends the episode; the caller does.

Standard library only (numpy when it is installed): this file is copied into the agent's workspace as
`.robouse/bin/aspire_programs.py`, where the robouse package is out of reach.
"""

from __future__ import annotations

import ast
import base64
import contextlib
import importlib
import io
import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

try:  # the CaP-X API returns arrays; without numpy they come back as tuples
    import numpy as _np
except ImportError:  # pragma: no cover - numpy is a dependency of robouse
    _np = None  # type: ignore[assignment]
try:  # camera images; imported here, not when a program first asks for one (Stage 2 imports nothing later)
    from PIL import Image as _PILImage
except ImportError:  # pragma: no cover - Pillow is a dependency of robouse
    _PILImage = None  # type: ignore[assignment]

ALLOWED_IMPORTS = frozenset({"math", "numpy"})
"""Modules a program may import: ASPIRE allows `math`; Robo Use adds `numpy` (also `import numpy as np`)."""

# ASPIRE's builtins, exactly (cap_harness.runtime._SAFE_BUILTINS without __import__); campaign.py's PROGRAM_BUILTINS
# and PROGRAM_EXCEPTIONS list the same names, so the library's snippets are checked against what programs get here
BUILTIN_NAMES = (
    "Exception",
    "ValueError",
    "TypeError",
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "float",
    "int",
    "len",
    "list",
    "max",
    "min",
    "print",
    "range",
    "reversed",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
)
CONTINUE = "capx_continue"  # the CaP-X backend's skill that goes on with a long API call
STEPPING_TIMEOUT_S = 3600  # a request that steps the simulator waits as long as the episode may run (as `robo` does)
STDOUT_LIMIT = 200_000


class ProgramRejected(ValueError):
    """The source breaks the contract; it never ran."""


class ToolError(Exception):
    """A tool call failed (the episode server's error, or the API's own exception). Programs catch it as Exception."""


class ProgramValidator(ast.NodeVisitor):
    """ASPIRE's checks on a program's syntax tree (cap_harness.runtime._ProgramValidator), with numpy allowed."""

    forbidden_nodes = (
        ast.AsyncFunctionDef,
        ast.Await,
        ast.ClassDef,
        ast.Delete,
        ast.Global,
        ast.ImportFrom,
        ast.Nonlocal,
        ast.With,
    )

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, self.forbidden_nodes):
            raise ValueError(f"{type(node).__name__} is not allowed in generated programs")
        super().generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            aliased_numpy = alias.name == "numpy" and alias.asname in (None, "np")
            if alias.name not in ALLOWED_IMPORTS or (alias.asname is not None and not aliased_numpy):
                raise ValueError(
                    f"Import of {alias.name!r} is not allowed; only math and numpy (also as np) may be imported"
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise ValueError("private and dunder attribute access is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("_"):
            raise ValueError("private and dunder names are not allowed")
        self.generic_visit(node)


def validate(source: str) -> ast.Module:
    """The parsed program; raises ProgramRejected when it is empty, does not parse or breaks the contract."""
    if not isinstance(source, str) or not source.strip():
        raise ProgramRejected("program rejected: the program is empty")
    try:
        tree = ast.parse(source, mode="exec")
        ProgramValidator().visit(tree)
    except (SyntaxError, ValueError) as e:
        raise ProgramRejected(f"program rejected: {e}") from e
    return tree


def _restricted_import(name: str, globals=None, locals=None, fromlist=(), level=0):
    """A program's own imports are checked before it runs (`math` and `numpy` only). This hook also serves the
    imports numpy's compiled code makes on first use (`numpy._core._methods` for `.mean()`): CPython looks those up in
    the builtins of the Python frame that called it, which is the program's."""
    top = name.partition(".")[0]
    if level != 0 or top not in ALLOWED_IMPORTS:
        raise ImportError(f"import of {name!r} is not allowed in generated programs")
    module = importlib.import_module(name)
    return module if fromlist else importlib.import_module(top)


def safe_builtins() -> dict[str, Any]:
    """A program's builtins. A dict: CPython's import from compiled code finds `__import__` only in a dict."""
    import builtins

    return {"__import__": _restricted_import, **{n: getattr(builtins, n) for n in BUILTIN_NAMES}}


# ---- transports: one JSON request in, one JSON reply out ------------------------------------------------------------
Send = Callable[[dict], dict]


def unix_transport(path: str) -> Send:
    """Requests to an episode server's Unix socket (the scored episode), as `robo` sends them."""

    def send(req: dict) -> dict:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(STEPPING_TIMEOUT_S if req.get("op") not in ("info", "status", "observe") else 120)
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
            return {"ok": False, "error": "episode server is not running (episode may have finished)"}
        except TimeoutError:
            return {"ok": False, "error": "no answer from the episode server"}
        finally:
            s.close()

    return send


def http_json(url: str, body: dict | None = None, timeout: float = STEPPING_TIMEOUT_S) -> tuple[int, dict]:
    """(status, JSON reply) of a request to the practice broker; a GET without a body."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"error": f"the practice broker did not answer: {e}"}


def practice_transport(base_url: str, episode: str) -> Send:
    """Requests to one practice episode, through the trial's practice broker."""

    def send(req: dict) -> dict:
        status, reply = http_json(f"{base_url}/episodes/{episode}", {"req": req})
        if status == 200 and isinstance(reply, dict) and "ok" in reply:
            return reply
        return {"ok": False, "error": str(reply.get("error") or f"practice broker answered HTTP {status}")}

    return send


# ---- the API a program sees -----------------------------------------------------------------------------------------
def encode(v: Any) -> str:
    """One skill argument as JSON, as capx_api sends it (arrays as lists)."""
    if hasattr(v, "tolist"):
        v = v.tolist()
    return json.dumps(v)


def decode(v: Any) -> Any:
    """A returned value as capx_api gives it: lists of numbers become float arrays (tuples without numpy), other lists
    tuples, dictionaries stay dictionaries."""
    if isinstance(v, dict):
        return {k: decode(x) for k, x in v.items()}
    if isinstance(v, list):
        if v and all(isinstance(x, int | float) and not isinstance(x, bool) for x in v):
            return _np.asarray(v, dtype=_np.float64) if _np is not None else tuple(float(x) for x in v)
        return tuple(decode(x) for x in v)
    return v


def public_value(v: Any, depth: int = 0) -> Any:
    """A JSON value for the record: arrays and tuples become lists, numpy scalars numbers, anything else its repr."""
    if depth > 8:
        return "..."
    if isinstance(v, dict):
        return {str(k): public_value(x, depth + 1) for k, x in list(v.items())[:200]}
    if isinstance(v, list | tuple | set):
        return [public_value(x, depth + 1) for x in list(v)[:1000]]
    if hasattr(v, "tolist"):
        return public_value(v.tolist(), depth + 1)
    if isinstance(v, bool | int | float | str) or v is None:
        return v
    return repr(v)[:500]


class Api:
    """The tools of one episode: the task's skills as functions and the `robo` object, over `send`.

    `on_call(span)` gets one record per tool call (name, arguments, ok, error, duration, steps); `after_motion(label)`
    is called after each call that stepped the simulator (practice runs save a keyframe there)."""

    def __init__(
        self,
        send: Send,
        info: dict,
        on_call: Callable[[dict], None] | None = None,
        after_motion: Callable[[str], None] | None = None,
    ):
        self.send = send
        self.info = info
        self.on_call = on_call
        self.after_motion = after_motion
        self.steps_used = int(info.get("steps_used") or 0)
        self.max_steps = int(info.get("max_steps") or 0)
        self.finished: str | None = None  # the episode's ending, once a reply says it finished
        self.calls = 0
        skills = [s for s in info.get("skills") or [] if isinstance(s, str)]
        self.has_continue = CONTINUE in skills
        self.skills = [s for s in skills if s != CONTINUE and s.isidentifier() and not s.startswith("_")]

    # every request a program makes goes through here
    def request(self, name: str, req: dict, args: tuple = (), kwargs: dict | None = None) -> Any:
        t0 = time.time()
        before = self.steps_used
        span: dict[str, Any] = {
            "name": name,
            "args": public_value(list(args)),
            "kwargs": public_value(kwargs or {}),
        }
        try:
            reply = self.send(req)
            if not reply.get("ok"):
                raise ToolError(f"{name}: {reply.get('error')}")
            result = reply.get("result")
            out = self._follow(name, result if isinstance(result, dict) else {"value": result})
            if out.get("stdout"):  # what the API printed, as capx_api prints it
                print(out["stdout"], end="" if str(out["stdout"]).endswith("\n") else "\n")
            if out.get("error"):
                raise ToolError(f"{name}: {out['error']}")
            if out.get("stopped"):
                raise ToolError(f"{name}: stopped ({out['stopped']})")
            span.update(ok=True, output=public_value(_summary(out)))
            return out
        except ToolError as e:
            span.update(ok=False, error=str(e))
            raise
        finally:
            self.calls += 1
            span.update(
                duration_s=round(time.time() - t0, 3), steps_used=self.steps_used, steps=self.steps_used - before
            )
            if self.on_call is not None:
                self.on_call(span)
            if self.after_motion is not None and self.steps_used > before and self.finished is None:
                self.after_motion(name)

    def _follow(self, name: str, res: dict) -> dict:
        """Track the episode's step count and ending; go on with a CaP-X call that returned running."""
        while True:
            if isinstance(res.get("steps_used"), int):
                self.steps_used = res["steps_used"]
            ep = res.get("episode")
            if isinstance(ep, str) and ep.startswith("finished"):
                self.finished = ep
            if not (res.get("running") and self.has_continue and self.finished is None):
                return res
            reply = self.send({"op": "skill", "name": CONTINUE, "args": []})
            if not reply.get("ok"):
                raise ToolError(f"{name}: {reply.get('error')}")
            nxt = reply.get("result")
            res = nxt if isinstance(nxt, dict) else {}

    def skill_function(self, name: str) -> Callable[..., Any]:
        """A task skill as a function with the API's name: arguments as JSON (`key=VALUE` for keywords), its return
        value decoded as capx_api does, its printed output printed, its failure raised."""

        def call(*args: Any, **kwargs: Any) -> Any:
            argv = [encode(a) for a in args] + [f"{k}={encode(v)}" for k, v in kwargs.items()]
            res = self.request(name, {"op": "skill", "name": name, "args": argv}, args, kwargs)
            if "return" in res:
                return decode(res.get("return"))
            return decode({k: v for k, v in res.items() if k not in ("state", "steps_used", "max_steps", "skill")})

        call.__name__ = name
        call.__doc__ = f"The task's API function {name} (robo skill {name})."
        return call

    def namespace(self) -> dict[str, Any]:
        """The program's globals besides the builtins: every skill by name, and `robo`."""
        ns: dict[str, Any] = {n: self.skill_function(n) for n in self.skills}
        ns["robo"] = Robo(self)
        return ns


class Robo:
    """The episode's requests besides its skills, as `robo.NAME(...)` in a program. Ending the episode is not among
    them: the caller does that after the program."""

    __slots__ = ("_api",)

    def __init__(self, api: Api):
        self._api = api

    def info(self) -> dict:
        """The task, action space, skills and step budget (`robo info`)."""
        return decode(self._api.request("info", {"op": "info"}))

    def observe(self, image: bool = False, camera: str | None = None) -> dict:
        """The robot's state as numbers (`robo observe`); with image=True also a camera image, saved by the episode."""
        return decode(self._api.request("observe", {"op": "observe", "image": bool(image), "camera": camera}))

    def image(self, camera: str | None = None) -> Any:
        """One camera's picture now, as an array of height x width x 3 bytes (the task's first camera by default);
        `robo.info()` gives each camera's calibration on vision tasks. Costs no step."""
        spec: dict[str, Any] = {"format": "png"}
        if camera:
            spec["cameras"] = [camera]
        res = self._api.request("image", {"op": "observe", "inline": spec}, (camera,) if camera else ())
        frames = res.get("images") or {}
        if not frames:
            raise ToolError("image: the episode returned no picture")
        if _PILImage is None:
            raise ToolError("image: Pillow is not installed in this Python")
        png = base64.b64decode(next(iter(frames.values())))
        img = _PILImage.open(io.BytesIO(png)).convert("RGB")
        return _np.asarray(img, dtype=_np.uint8) if _np is not None else img.tobytes()

    def act(self, action: Any, repeat: int = 1) -> dict:
        """One low-level action, applied `repeat` times (`robo act`)."""
        vals = [float(x) for x in (action.tolist() if hasattr(action, "tolist") else action)]
        return decode(self._api.request("act", {"op": "act", "action": vals, "repeat": int(repeat)}, (vals,)))

    def move_to(
        self, x: float, y: float, z: float, grip: float | None = None, max_steps: int = 100, tol: float = 0.01
    ) -> dict:
        """Move the hand toward a point (`robo move-to`), where the task offers it."""
        req = {"op": "move_to", "pos": [float(x), float(y), float(z)], "grip": grip, "max_steps": int(max_steps)}
        return decode(self._api.request("move_to", {**req, "tol": float(tol)}, (x, y, z)))

    def grip(self, value: float, steps: int = 15) -> dict:
        """Hold position and set the gripper (`robo grip`; +1 close, -1 open), where the task offers it."""
        return decode(self._api.request("grip", {"op": "grip", "value": float(value), "steps": int(steps)}, (value,)))

    def skill(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """A skill by name, as its function does."""
        return self._api.skill_function(str(name))(*args, **kwargs)


def _summary(res: dict) -> dict:
    """What a span records of a reply: without the robot state, the API's printed output and encoded pictures."""
    return {k: v for k, v in res.items() if k not in ("state", "stdout", "images")}


class Execution:
    """The outcome of running one program: ok, its `result`, its printed output and the error that stopped it."""

    def __init__(self, ok: bool, result: Any, stdout: str, error: dict | None):
        self.ok, self.result, self.stdout, self.error = ok, result, stdout, error

    def as_dict(self) -> dict:
        return {"ok": self.ok, "result": self.result, "error": self.error}


def execute(source: str, api: Api) -> Execution:
    """Check and run one program against `api`. Never raises for the program's own failures."""
    try:
        tree = validate(source)
    except ProgramRejected as e:
        return Execution(False, None, "", {"type": "ProgramRejected", "message": str(e)})
    env: dict[str, Any] = {"__builtins__": safe_builtins(), **api.namespace()}
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(tree, "<generated-program>", "exec"), env, env)
        return Execution(True, public_value(env.get("result")), out.getvalue()[-STDOUT_LIMIT:], None)
    except Exception as e:
        err = {"type": type(e).__name__, "message": f"program execution failed: {type(e).__name__}: {e}"[:2000]}
        return Execution(False, None, out.getvalue()[-STDOUT_LIMIT:], err)
