"""User-facing text names only the model route tested with Robo Use (GLM-5.3 on the Z.ai Coding Plan, `glm/glm-5.3`
through BenchFlow's glm provider), and `robouse doctor` checks that provider's settings where the model gateway reads
them: environment variables, not a key file."""

from __future__ import annotations

import pytest

from robouse.cli import main
from robouse.harnesses import models

EXAMPLE = "glm/glm-5.3"
UNTESTED = ("openrouter", "together", "fireworks", "groq", "deepinfra", "baseten")


@pytest.mark.parametrize("cmd", ["run", "run-many"])
def test_harness_help_gives_the_zai_example_only(cmd, capsys) -> None:
    with pytest.raises(SystemExit):
        main([cmd, "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert EXAMPLE in out and not any(p in out.lower() for p in UNTESTED)


def test_missing_prefix_error_gives_the_zai_example_only() -> None:
    with pytest.raises(ValueError) as e:
        models.resolve("mini-swe-agent", "GLM-5.3")  # a bare id, for a harness with no vendor of its own
    msg = str(e.value)
    assert EXAMPLE in msg and not any(p in msg.lower() for p in UNTESTED)


def _doctor(monkeypatch, capsys) -> str:
    from robouse.core import gl

    monkeypatch.setattr(gl, "auto_select", lambda: None)
    monkeypatch.setattr(gl, "probe", lambda p=None, python=None: None)
    assert main(["doctor"]) == 0
    return capsys.readouterr().out


def test_doctor_checks_the_settings_where_the_gateway_reads_them(monkeypatch, capsys) -> None:
    pytest.importorskip("benchflow")  # the provider registry
    from robouse.cli.doctor import gateway_env_vars

    names = gateway_env_vars("glm")
    assert names == ["GLM_API_KEY", "GLM_BASE_URL"]  # BenchFlow's glm entry: the key, and a base URL with no default
    line = "GLM_API_KEY and GLM_BASE_URL in the environment (what the model gateway reads for glm/ models"
    for var in names:
        monkeypatch.delenv(var, raising=False)
    out = _doctor(monkeypatch, capsys)
    assert f"-- {line}" in out and "default glm/glm-5.3; no key file is read" in out
    monkeypatch.setenv("GLM_API_KEY", "not-a-real-key")
    assert f"-- {line}" in _doctor(monkeypatch, capsys)  # both are needed
    monkeypatch.setenv("GLM_BASE_URL", "http://127.0.0.1:9/v1")
    out = _doctor(monkeypatch, capsys)
    assert f"ok {line}" in out and "baseten" not in out.lower()


def test_doctor_without_the_registry_says_what_to_install(monkeypatch, capsys) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "benchflow.agents.providers", None)  # importing it raises ImportError
    out = _doctor(monkeypatch, capsys)
    assert "-- the model gateway's provider registry (pip install 'robouse[llm]'; for glm/glm-5.3" in out


@pytest.mark.parametrize("version,needs", [((3, 11), "Python 3.12 or newer"), ((3, 12), "pip install 'robouse[llm]'")])
def test_without_benchflow_the_message_says_what_helps(version, needs, monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "benchflow.agents.providers", None)  # importing it raises ImportError
    monkeypatch.setattr(models, "_python", lambda: version)
    with pytest.raises(RuntimeError) as e:
        models.provider_registry()
    assert needs in str(e.value)
    # the default model's prefix is known only to BenchFlow's registry: the message says what to install, not that
    # the id lacks a prefix
    with pytest.raises(RuntimeError) as e:
        models.resolve("mini-swe-agent", "glm/glm-5.3")
    assert needs in str(e.value) and "provider prefix" not in str(e.value)
