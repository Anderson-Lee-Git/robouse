"""User-facing text names only the provider tested with Robo Use (Baseten), and `robouse doctor` checks the provider
key where the model gateway reads it: the environment variable, not a key file."""

from __future__ import annotations

import pytest

from robouse.cli import main
from robouse.harnesses import models

EXAMPLE = "baseten/zai-org/GLM-5.3"
UNTESTED = ("openrouter", "together", "fireworks", "groq", "deepinfra")


@pytest.mark.parametrize("cmd", ["run", "run-many"])
def test_harness_help_gives_the_baseten_example_only(cmd, capsys) -> None:
    with pytest.raises(SystemExit):
        main([cmd, "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert EXAMPLE in out and not any(p in out.lower() for p in UNTESTED)


def test_missing_prefix_error_gives_the_baseten_example_only() -> None:
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


def test_doctor_checks_the_key_where_the_gateway_reads_it(monkeypatch, capsys) -> None:
    from robouse import _maintainer
    from robouse.cli.doctor import gateway_key_var

    var = gateway_key_var("baseten")
    assert var == models.PENDING_PROVIDERS["baseten"]["auth_env"] == "BASETEN_API_KEY"
    # a maintainer key file does not count: the gateway passes only the environment to the provider proxy
    monkeypatch.setattr(_maintainer, "baseten_key", lambda: "from-a-key-file")
    monkeypatch.delenv(var, raising=False)
    out = _doctor(monkeypatch, capsys)
    assert f"-- {var} in the environment (what the model gateway reads" in out
    monkeypatch.setenv(var, "not-a-real-key")
    out = _doctor(monkeypatch, capsys)
    assert f"ok {var} in the environment (what the model gateway reads" in out


@pytest.mark.parametrize("version,needs", [((3, 11), "Python 3.12 or newer"), ((3, 12), "pip install 'robouse[llm]'")])
def test_without_benchflow_the_message_says_what_helps(version, needs, monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "benchflow.agents.providers", None)  # importing it raises ImportError
    monkeypatch.setattr(models, "_python", lambda: version)
    with pytest.raises(RuntimeError) as e:
        models.provider_registry()
    assert needs in str(e.value)
