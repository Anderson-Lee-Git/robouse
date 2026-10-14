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

- It denies reads and writes to the trial's run folder, the trial's task folder, the installed `robouse` package, `~/.config/robouse`, `~/.config/robouse-operator`, the optional credential pools (`ROBOUSE_CLAUDE_TOKEN_FILE`, `ROBOUSE_CODEX_AUTH_DIR`) and every path in `ROBOUSE_SANDBOX_DENY`. On macOS it also denies reading any `src/robouse` or `site-packages/robouse` folder.
- It keeps other trials' workspaces from the agent: on macOS by path, on Linux by giving each trial its own `/tmp`.
- On Linux the agent gets its own process namespace, so it cannot see other processes.
- On macOS it refuses TCP connections to localhost, except to the trial's own model gateway.
- The runner removes model-provider credentials (`ANTHROPIC_*`, `OPENAI_*`, `CLAUDE_CODE_OAUTH*` and the key variables of every known provider) from the agent's environment. Each harness gets back only its own login, or a per-trial key for the trial's model gateway.
- The episode server receives the reference solution's token and the key that signs the verdict on its standard input, never in an environment variable or a command line.
- Claude Code runs with WebFetch, WebSearch and Task disabled.

### What it does not do

- **It is a deny list, not an allow list.** The macOS profile allows everything by default and denies the paths above. On Linux, bubblewrap binds the whole host file system read-write and hides only the listed folders. Everything else in your home folder and on the machine is readable, and mostly writable, by the agent.
- **Other copies of tasks are readable.** Only the trial's own task folder and the installed package are hidden. The other task folders of a checkout, a robouse wheel or its unpacked copy in a package cache (`~/.cache/uv`, `~/.cache/pip`), an exported dataset and BenchFlow's task cache all hold reference solutions and verifiers, and a vision task's state twin describes the same scene with its object positions. Add such copies to `ROBOUSE_SANDBOX_DENY`, or remove them.
- **The network is open.** The agent can reach the internet. Public copies of the tasks, including reference solutions and verifiers, are downloadable (the [robohub](https://github.com/benchflow-ai/robohub) repository, the package on PyPI, the upstream benchmarks' sources). Codex's built-in web search is not turned off, and Claude Code tools other than the three above stay available.
- **On Linux, services on this machine are reachable.** There is no network namespace, so the agent can connect to anything listening on localhost.
- **The agent runs as your user** (as root, if you run `robouse` as root), with your other environment variables. Other tokens in your shell, such as `GITHUB_TOKEN` or cloud credentials, reach the agent, and so do credential files in your home folder unless you list them in `ROBOUSE_SANDBOX_DENY`.
- **On macOS, `/tmp` is shared and episodes are not authenticated.** Each episode's socket is in `/tmp`, and any process of your user can connect to any running episode's socket and send it requests. Processes of the same user can also read each other's command lines and environments. `open` hands files and URLs to LaunchServices, which runs them outside the sandbox.
- **On Linux, only folders are hidden.** A single file listed in `ROBOUSE_SANDBOX_DENY`, or a token file in `ROBOUSE_CLAUDE_TOKEN_FILE`, stays readable; list the folder that holds it instead.
- **Remote simulator workers trust whoever holds their secret.** Robo Use reads a worker endpoints file only from `~/.config/robouse/remote/<name>.json`, which the sandbox denies, or from the file `ROBOUSE_<NAME>_REMOTE` names; keep that file out of every folder an agent can read.
- `ROBOUSE_SANDBOX=0` turns the sandbox off completely.

In short: the sandbox stops an agent from stumbling on the answer, not one that looks for it. For agents you do not trust, use a disposable VM or container with no credentials of yours and no network access except to the model API, or run published datasets with BenchFlow (`bench eval run`), which puts the agent and the simulator in separate containers.

### What we saw in our own runs

Two audits of the leaderboard runs on [robouse.ai/runs](https://robouse.ai/runs/) (September 27 to October 13, 2026) checked every counted solve. Agents in those runs read reference solutions from task copies left in a shared `/tmp`, downloaded upstream benchmark source from GitHub, printed their inherited environment, and connected to other trials' episode sockets. The trials that gained from this were removed from the leaderboard or re-run. The runner has been tightened since then, but the limits above remain, so a score from `robouse run` rests on the trial logs as well as on the sandbox.
