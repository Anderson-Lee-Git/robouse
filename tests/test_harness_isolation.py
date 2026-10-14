"""What a model harness offers its model and what its sandbox lets the agent reach (deep audit, 2026-10-14)."""

from __future__ import annotations

from robouse import harnesses
from robouse.harnesses import interface as iface


def _flags(cmd: list[str]) -> list[str]:
    """The `-c` overrides of a Codex command."""
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == "-c"]


def test_codex_turns_web_search_off(tmp_path) -> None:
    """Codex offers its model a web_search tool by default (0.155 and later); every Codex launch turns it off, on its
    own vendor and through the gateway (extra provider flags), and the MCP interface keeps it."""
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    native = harnesses._codex_cmd("TASK", "gpt-6-astra", ws)
    via_gateway = harnesses._codex_cmd("TASK", "m", ws, ["-c", 'model_provider="robouse"'])
    for cmd in (native, via_gateway):
        assert 'web_search="disabled"' in _flags(cmd)
        assert cmd.index('web_search="disabled"') < cmd.index("-m")
    launch = harnesses.Launch(list(native), {"PATH": f"{ws / '.robouse' / 'bin'}:/usr/bin"})
    iface.apply("codex", launch, "mcp", ws, "/tmp/x.sock")
    flags = _flags(launch.cmd)
    assert 'web_search="disabled"' in flags and any(f.startswith("mcp_servers.robo") for f in flags)


def test_codex_web_search_setting_is_valid_toml() -> None:
    """Codex parses each `-c` value as TOML: an unquoted value would be a different setting or an error."""
    import tomllib

    assert tomllib.loads(harnesses.CODEX_WEB_SEARCH) == {"web_search": "disabled"}
