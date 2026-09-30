"""The settings layer: every ROBOUSE_* variable is declared, and paths resolve in the documented order."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from robouse import _maintainer, config

SRC = Path(__file__).resolve().parents[1] / "src" / "robouse"


def test_every_variable_the_source_reads_is_declared() -> None:
    used = set()
    for p in SRC.rglob("*.py"):
        used |= set(re.findall(r"\bROBOUSE_[A-Z0-9_]+[A-Z0-9]\b", p.read_text()))
    assert used - set(config.ENV) == set(), "declare these in robouse.config.ENV"


def test_undeclared_names_are_refused(monkeypatch) -> None:
    with pytest.raises(KeyError, match="not declared"):
        config.env("ROBOUSE_NO_SUCH_THING")
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    assert config.flag("ROBOUSE_SANDBOX", default=True) is False
    monkeypatch.setenv("ROBOUSE_SANDBOX", "yes")
    assert config.flag("ROBOUSE_SANDBOX") is True


def test_cache_python_and_remote_endpoints(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ROBOUSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("ROBOUSE_DMCONTROL_PYTHON", raising=False)
    assert config.sim_python("dmcontrol") == tmp_path / "cache" / "dmcontrol-venv" / "bin" / "python"
    monkeypatch.setenv("ROBOUSE_DMCONTROL_PYTHON", "/opt/x/python")
    assert config.sim_python("dmcontrol") == Path("/opt/x/python")
    monkeypatch.setattr(_maintainer, "remote_endpoint_files", lambda name: [])
    monkeypatch.delenv("ROBOUSE_GPU_REMOTE", raising=False)
    assert config.remote_endpoints("gpu") is None
    f = tmp_path / "cfg" / "remote" / "gpu.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"secret": "s"}))
    assert config.remote_endpoints("gpu") == f
    other = tmp_path / "other.json"
    other.write_text("{}")
    monkeypatch.setenv("ROBOUSE_GPU_REMOTE", str(other))
    assert config.remote_endpoints("gpu") == other


def test_sandbox_denies_private_folders(tmp_path, monkeypatch) -> None:
    from robouse.runner.sandbox import sandbox_profile

    (tmp_path / "cfg").mkdir()
    monkeypatch.setenv("ROBOUSE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ROBOUSE_SANDBOX_DENY", "/secret/a:/secret/b")
    monkeypatch.setattr(_maintainer, "private_dirs", lambda: [])
    prof = sandbox_profile(tmp_path / "ws")
    assert str((tmp_path / "cfg").resolve()) in prof
    assert '"/secret/a"' in prof and '"/secret/b"' in prof
    assert "/src/robouse(/|$)" in prof and 'deny network-outbound (remote ip "localhost:*")' in prof
