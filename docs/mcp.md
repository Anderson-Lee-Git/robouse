# MCP

`robo mcp` serves the `robo` operations as tools of an MCP server named `robo`, so an agent that speaks the Model Context Protocol can drive the robot without a shell. It runs on the agent's side, as one more client of the episode server: each tool call sends exactly the request the matching `robo` command sends, over the same socket, with no extra authority. The episode server still keeps the step and wall-clock budgets, records the episode and decides success.

## Tools

| Tool | Arguments | Same as |
|---|---|---|
| `info` | none | `robo info` |
| `observe` | `image` (boolean), `camera` (string) | `robo observe [--image] [--camera C]` |
| `act` | `action` (numbers, one per action dimension), `repeat` (integer, default 1) | `robo act A1 A2 ... [--repeat N]` |
| `move_to` | `x`, `y`, `z`, `grip`, `max_steps` (default 100), `tol` (default 0.01) | `robo move-to X Y Z [--grip G]` |
| `grip` | `value`, `steps` (default 15) | `robo grip G [--steps N]` |
| `skill` | `name`, `args` (strings) | `robo skill NAME [ARG ...]` |
| `done` | `message` | `robo done [message]` |
| `give_up` | `message` | `robo give-up [message]` |

A result's text is exactly what the `robo` command prints. When the reply names camera images (`image_path`), the PNGs are attached as MCP image content as well, so an image reaches the agent through MCP exactly when the CLI would have printed a path. In a trial without image input (see [Harnesses](harnesses.md#image-input)), the model gateway replaces those image parts as it replaces any other. Arguments that do not match a tool's schema are rejected before anything is sent. The raw reply is in the result's `_meta["robouse/reply"]`. The runner's own operations (`status`, `shutdown`) have no tool.

## Transports

- stdio: `robo mcp`. The server finds the episode from `$ROBOUSE_SOCKET` (or `$ROBO_SOCKET`, or `.robouse/socket` in the working directory).
- Streamable HTTP: `robo mcp --http 127.0.0.1:PORT --path /PATH`. Every POST is answered with JSON; there is no server-sent event stream and no session id. It listens on the given address only, answers only at the given path, and refuses requests whose `Origin` is not local. `--run CMD ...` serves while `CMD` runs and then exits with its return code.

Any MCP client can use it. For example, a Claude Code or Claude Desktop entry:

```json
{"mcpServers": {"robo": {"command": "robo", "args": ["mcp"], "env": {"ROBOUSE_SOCKET": "/tmp/robouse-XXXX.sock"}}}}
```

## Choosing the interface

`--interface` on `robouse run` and `robouse run-many` picks what the agent gets:

| Value | The agent gets |
|---|---|
| `cli` | `robo` on its `PATH` (the default) |
| `mcp` | the `robo` MCP server only; `robo` is not on its `PATH` and the prompt names the tools |
| `both` | both; they drive the same episode |

Without `--interface`, a task's `robouse.interface` field decides, else `cli`. The choice is recorded as `interface` in the trial's `config.json` and in `result.json` under `agent_info`. Every request made through MCP carries `"via": "mcp"` in `episode/trace.jsonl`.

Leaving `robo` off the `PATH` states what the agent is offered; it is not a security boundary. Authority is the episode socket, which both interfaces share.

| Harness | MCP wiring |
|---|---|
| `claude-code` | a per-trial `--mcp-config` with `--strict-mcp-config` (no other MCP servers) |
| `codex` | `-c mcp_servers.robo.*` on the command line |
| `dimcode` | the HTTP transport at a random path, listed as dimcode's only MCP endpoint |
| `oracle`, `noop` | every request goes through a `robo mcp` server |
| others | no MCP client: `cli` only |

The trajectory converter treats a call of a `robo` MCP tool as the equivalent `robo` command, so trajectories and video indexes line up as they do for the CLI.

```sh
robouse run --task tasks/cubepick/cubepick-reach-layout-0 \
  --harness claude-code \
  --model baseten/zai-org/GLM-5.3 \
  --interface mcp \
  --out runs/mcp
```
