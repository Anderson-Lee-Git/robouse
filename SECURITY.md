# Security policy

## Reporting a vulnerability

Please do not report security vulnerabilities in public issues, pull requests or Discord.

Report them privately through GitHub's private vulnerability reporting: the **Report a vulnerability** button on the repository's [Security](https://github.com/benchflow-ai/robouse/security) tab. If you cannot use GitHub, email xiangyi@benchflow.ai with "robouse security" in the subject.

Include what you can of the following: the Robo Use version (`robouse --version`), the operating system, the command you ran, what an agent or another process could do that it should not, and the smallest steps that show it. Do not include real credentials; if a report needs one, say where it appeared and how long it was.

We aim to acknowledge a report within 5 working days and to agree on a disclosure date with you, normally no later than 90 days after the report. We credit reporters in the release notes unless they ask us not to.

## Supported versions

Only the latest release on [PyPI](https://pypi.org/project/robouse/) gets security fixes. Robo Use is alpha software; upgrade to the latest version before reporting.

## What to report where

| Problem | Where |
|---|---|
| A credential, token or private file reaches an agent, a model provider, a trial folder, a published page, this repository or a release | Privately, as above |
| An agent can affect something outside its own trial: another trial's episode, the host, a remote simulator worker | Privately, as above |
| A task can be scored without doing it: a judge bug, hidden state printed to the agent, a reference solution reachable by the agent | A public issue with the **Task or scoring integrity** template, unless it also exposes a credential |
| A bug in an upstream simulator, a harness (Claude Code, Codex, mini-swe-agent), a model provider or BenchFlow | The upstream project |

## The agent sandbox and its limits

`robouse run` (the local runner) starts every model harness, and the `vla` and `molmoact2` clients, under the operating system's sandbox: Seatbelt (`sandbox-exec`) on macOS and bubblewrap on Linux. The reference solution (`--harness oracle`) and the no-op control run without it. Read this section before you run an agent you do not trust or publish scores.

### What it does

- It denies reads and writes to the trial's run folder, the trial's task folder, any `robouse` source or install (a `robouse` package folder) and, when Robo Use runs from a source checkout, that checkout's `tasks/`, `runs/` and `adapters/` folders.
- It denies `~/.config/robouse`, `~/.config/robouse-operator`, the optional credential pools (`ROBOUSE_CLAUDE_TOKEN_FILE`, `ROBOUSE_CODEX_AUTH_DIR`) and every path in `ROBOUSE_SANDBOX_DENY`.
- It denies credential and task-copy locations in your home folder (`HOME_DENIED` in [`src/robouse/runner/sandbox.py`](src/robouse/runner/sandbox.py)): other programs' logins (such as `~/.ssh`, `~/.aws`, `~/.config/gcloud`, `~/.config/gh`, `~/.netrc` and `~/.docker`), your own Claude Code, Codex and mini-swe-agent settings, BenchFlow's settings and task cache, package caches that hold copies of the tasks (`~/.cache/uv`, pip's cache) and Robo Use's own cache, except the agent's own per-trial harness folder. A denied file is hidden as well as a denied folder.
- Each trial's Claude Code and Codex get a config folder of their own, which is removed when the trial ends.
- The agent can read but not change the Python that Robo Use runs on, because the episode server and the verifier run on it.
- It keeps other trials' workspaces and episode sockets from the agent, and refuses connections to the Docker, Podman and LXD sockets and to your SSH agent.
- On Linux the agent gets its own process namespace, so it cannot see other processes, and its own `/tmp`.
- On macOS it refuses TCP connections to localhost, except to the trial's own model gateway, and the agent cannot start `open`, `osascript`, `shortcuts` or `security` or send Apple events, which act outside the sandbox.
- The runner removes model-provider credentials (`ANTHROPIC_*`, `OPENAI_*`, `CLAUDE_CODE_OAUTH*`, `GLM_*`, `ZAI_*` and the key variables of every known provider) and every variable whose name marks a credential (a token, key, secret, password or login, such as `GITHUB_TOKEN`, `HF_TOKEN`, `AWS_SECRET_ACCESS_KEY` or `SSH_AUTH_SOCK`) from the agent's environment. Each harness gets back only its own login, or a per-trial key for the trial's model gateway. The episode server and the verifier get no model-provider key either.
- The episode server receives the reference solution's token and the key that signs the verdict on its standard input, never in an environment variable or a command line.
- Claude Code is offered only the Bash, Read, Write, Edit, Glob and Grep tools, plus the `robo` MCP tools when it uses them; Codex runs with its web search turned off.

### What it does not do

- **It is a deny list, not an allow list.** The macOS profile allows everything by default and denies the paths above. On Linux, bubblewrap binds the whole host file system read-write and hides only the listed paths. Everything else in your home folder and on the machine is readable, and mostly writable, by the agent.
- **Other copies of tasks are readable.** Copies outside the denied places, such as another checkout, a downloaded wheel, an exported dataset or a robohub clone, hold reference solutions and verifiers. Add such copies to `ROBOUSE_SANDBOX_DENY`, or remove them.
- **The network is open.** The agent can reach the internet through its shell even without web tools. Public copies of the tasks, including reference solutions and verifiers, are downloadable (the [robohub](https://github.com/benchflow-ai/robohub) repository, the package on PyPI, the upstream benchmarks' sources).
- **On Linux, services on this machine are reachable.** There is no network namespace, so the agent can connect to anything listening on localhost.
- **The agent runs as your user** (as root, if you run `robouse` as root). A secret in a variable whose name does not mark a credential reaches the agent, and so does a credential file outside the denied locations unless you list it in `ROBOUSE_SANDBOX_DENY`.
- **Episodes are not authenticated.** The sandbox refuses the agent's connections to other trials' episode sockets, but any process of your user outside the sandbox can connect to a running episode's socket and send it requests. On macOS, processes of the same user can also read each other's command lines and environments.
- **Remote simulator workers trust whoever holds their secret.** Robo Use reads a worker endpoints file only from `~/.config/robouse/remote/<name>.json`, which the sandbox denies, or from the file `ROBOUSE_<NAME>_REMOTE` names; keep that file out of every folder an agent can read.
- `ROBOUSE_SANDBOX=0` turns the sandbox off completely.

In short: the sandbox stops an agent from stumbling on the answer, not one that looks for it. For agents you do not trust, use a disposable VM or container with no credentials of yours and no network access except to the model API, or run published datasets with BenchFlow (`bench eval run`), which puts the agent and the simulator in separate containers.

### What we saw in our own runs

Two audits of the leaderboard runs on [robouse.ai/runs](https://robouse.ai/runs/) (September 27 to October 13, 2026) checked every counted solve. Agents in those runs read reference solutions from task copies left in a shared `/tmp`, downloaded upstream benchmark source from GitHub, printed their inherited environment, and connected to other trials' episode sockets. The trials that gained from this were removed from the leaderboard or re-run. The runner has been tightened since then, but the limits above remain, so a score from `robouse run` rests on the trial logs as well as on the sandbox.
