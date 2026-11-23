# Configuration

Robo Use reads its settings from environment variables; the ones you set are listed here, generated from `robouse.config`. Paths default to `~/.cache/robouse` (the cache) and `~/.config/robouse` (private settings such as remote worker endpoints, which the local runner's sandbox keeps from agents).

| Variable | Meaning |
|---|---|
| `ROBOUSE_CACHE_DIR` | cache for simulator virtualenvs, downloaded assets and harness homes (default ~/.cache/robouse) |
| `ROBOUSE_CONFIG_DIR` | private settings such as remote worker endpoints (default ~/.config/robouse); agents never see it |
| `ROBOUSE_MENAGERIE_ASSETS` | MuJoCo Menagerie robot models (default: the checkout's assets/menagerie, else <cache>/menagerie); agents never see it |
| `ROBOUSE_CHEMLAB_ASSETS` | ChemLab-Assets instrument files for the chemlab suite, from `robouse fetch-assets --chemlab` (default <cache>/chemlab); agents never see it |
| `ROBOUSE_EMBODIED_PLAYGROUND_SOURCE` | Embodied Playground's MuJoCo package for the embodied-playground suite, from `robouse fetch-assets --embodied-playground` (default <cache>/embodied-playground); agents never see it |
| `ROBOUSE_PRICING` | JSON price table for trial cost and the spend cap, used instead of the packaged pricing.json (not added to it) |
| `ROBOUSE_RECORD_SIZE` | episode video size WIDTHxHEIGHT (default: the backend's native size) |
| `ROBOUSE_AGENT_IMAGES` | 0: the model gets no image input in this run, whatever it takes (its gateway replaces every image part; recorded as image_input: false). Default: from the model registry |
| `ROBOUSE_SPEND_CAP_USD` | the model spend at which the model gateway stops a trial, in USD (default 5; 0: no cap; recorded as a budget stop). A model without a price, such as glm/glm-5.3, runs with 0 or with its price in ROBOUSE_PRICING |
| `ROBOUSE_SANDBOX` | 0 disables the sandbox around agent processes (macOS Seatbelt, Linux bubblewrap; default 1) |
| `ROBOUSE_SANDBOX_DENY` | extra colon-separated paths agents may neither read nor write |
| `ROBOUSE_SANDBOX_ALLOW` | colon-separated paths inside a denied folder that agents may read (not write), such as an interpreter or a runtime library inside a denied checkout |
| `ROBOUSE_DEXJOCO_PYTHON` | Python of the DexJoCo virtualenv (default <cache>/dexjoco-venv/bin/python) |
| `ROBOUSE_DMCONTROL_PYTHON` | Python of the dm_control virtualenv (default <cache>/dmcontrol-venv/bin/python) |
| `ROBOUSE_HUMANOIDBENCH_PYTHON` | Python of the HumanoidBench virtualenv (default <cache>/humanoidbench-venv/bin/python) |
| `ROBOUSE_MANISKILL_PYTHON` | Python of the ManiSkill virtualenv (default <cache>/maniskill-venv/bin/python) |
| `ROBOUSE_METADRIVE_PYTHON` | Python of the MetaDrive virtualenv (default <cache>/metadrive-venv/bin/python) |
| `ROBOUSE_MYOSUITE_PYTHON` | Python of the MyoSuite virtualenv (default <cache>/myosuite-venv/bin/python) |
| `ROBOUSE_ROBOCASA_PYTHON` | Python of the RoboCasa virtualenv (default <cache>/robocasa-venv/bin/python) |
| `ROBOUSE_ROBOCASA_OBJECT_ROOT` | Directory of authored RoboCasa object bundles (needed for custom/... objects) |
| `ROBOUSE_ROBOCASA_PLUGINS` | comma-separated importable modules that register scene-specific RoboCasa scenario predicates and liquid container kinds (each has register(scenario); robocasa_scenario backend and worker) |
| `ROBOUSE_LIQUID_WORK_ROOT` | host-side scratch folder for the SPH liquid's solver files (robocasa_scenario scenes with a liquid; default: a temporary folder) |
| `ROBOUSE_RLEBENCH_PYTHON` | Python of the RLE-Bench virtualenv (default <cache>/rlebench-venv/bin/python) |
| `ROBOUSE_CAPX_PYTHON` | Python of the CaP-X virtualenv (default <cache>/capx-venv/bin/python) |
| `ROBOUSE_CAPX_LIBERO_PYTHON` | Python of the CaP-X LIBERO virtualenv (default <cache>/capx-libero-venv/bin/python) |
| `ROBOUSE_YAM_PYTHON` | Python of the dual-YAM virtualenv (MuJoCo 3.3.5+ and Dream Labs' scene; default <cache>/yam-venv/bin/python) |
| `ROBOUSE_EMBODIED_PLAYGROUND_PYTHON` | Python of the Embodied Playground virtualenv (Python 3.11, MuJoCo 3.3.7; default <cache>/embodied-playground-venv/bin/python) |
| `ROBOUSE_VLA_URL` | policy server for the `vla` harness |
| `ROBOUSE_VLA_TOKEN` | bearer token for the policy server |
| `ROBOUSE_VLA_POLICY_CONFIG` | JSON file with overrides for the `vla` preset |
| `ROBOUSE_DREAM_PYTHON` | interpreter that runs the `dream` client, with Dream's client library installed (default <cache>/dream-venv/bin/python) |
| `ROBOUSE_DREAM_ACTIONS` | rows of each Dream-1 action chunk the `dream` client executes before asking again (1-48, default 48) |
| `ROBOUSE_MOLMOACT2_URL` | MolmoAct2 policy server for the `molmoact2` harness |
| `ROBOUSE_MOLMOACT2_TOKEN` | bearer token for the MolmoAct2 server |
| `ROBOUSE_DIMCODE` | the dimcode executable for the `dimcode` harness (default: `dimcode` on PATH) |
| `ROBOUSE_DIMCODE_NODE` | Node 24 or 26 that runs dimcode (default: `node` on PATH) |
| `ROBOUSE_KINEX` | the Kinex launcher for the `kinex` harness (default: `kinex` on PATH), or bin/kinex.mjs of an npm install |
| `ROBOUSE_KINEX_NODE` | Node 22.19 or newer that runs a bin/kinex.mjs launcher (default: `node` on PATH) |
| `ROBOUSE_KINEX_VENV` | the Python environment Kinex's tools and drivers run in, with Kinex's runtime packages (default <cache>/kinex-venv, which agents can read but not change) |
| `ROBOUSE_SHOW_HARNESS_URL` | OpenAI-compatible server (base URL ending in /v1) of a self-hosted model for the `show-harness` harness, e.g. vLLM serving a Show-Harness adapter |
| `ROBOUSE_SHOW_HARNESS_TOKEN` | token for that server: a bearer token, or sent under the overrides' `token_header` |
| `ROBOUSE_SHOW_HARNESS_CONFIG` | JSON file of `show-harness` overrides (mode zs or ft, step sizes, plugins) |
| `ROBOUSE_ASPIRE_LIBRARY` | a folder that keeps the `aspire` harnesses' ASPIRE skill library, and each task's selected program, across trials (created on first use; default: each trial starts from ASPIRE's own library and keeps what it promotes in its trial folder only) |
| `ROBOUSE_ASPIRE_WORKFLOW` | the ASPIRE workflow the `aspire` harnesses run: iterative-debugging (default) or evosearch |
| `ROBOUSE_ASPIRE_DEV_SEEDS` | the `aspire` harnesses' development seeds, e.g. 101-105 (default: ASPIRE's band for the task's benchmark, 101-125 on capx) |
| `ROBOUSE_ASPIRE_UNSEEN_SEEDS` | the `aspire` harnesses' unseen-check seeds, each run once, e.g. 126-127 (default: ASPIRE's band, 126-130 on capx) |
| `ROBOUSE_ASPIRE_PRACTICE_EPISODES` | practice episodes one `aspire` trial may run (default 300, 650 with evosearch) |
| `ROBOUSE_ASPIRE_PRACTICE_WORKERS` | practice episodes an `aspire` trial runs at once (default 4) |
| `ROBOUSE_ASPIRE_REUSE` | whether an `aspire` trial whose library already holds a selected program for the task evaluates it instead of running Stage 1, as ASPIRE evaluates one frozen program on every held-out seed: 1 (default) when the same harness and model selected it, any whichever selected it, 0 never |


## Robot prompt framing

`run` and `run-many` accept `--robot-framing {simulated,real}`. The default,
`simulated`, preserves existing prompts byte for byte. `real` changes
"You are controlling a simulated robot." to "You are controlling a real robot."
(including MCP/both prefixes), or "a program that controls a simulated robot."
to "a program that controls a real robot." in the program preamble. In `PROGRAM.md`,
it also changes "Runs take simulated time and real time" to "Runs take robot time
and real time", and "Every simulated step counts" to "Every step counts"; each
expected phrase must be present. Development
still uses "a fresh reset of the scene". This option changes prompt framing,
not the simulator or hardware backend.

Supported harnesses are `claude-code`, `codex`, `program`, `program-codex` and
plugins whose `base_of()` is one of those. Others refuse `real`, as does the
BenchFlow engine. A missing expected phrase raises rather than silently using an
unchanged prompt. `config.json` and `job.json` record `robot_framing`; resume
refuses another framing (older configs without the field mean `simulated`).
ATIF preserves the framed prompt. The private runner-to-builder variable
`_ROBOUSE_ROBOT_FRAMING` never reaches the agent environment.

## Agent turn cap

`run` and `run-many` accept `--max-turns N` (else a task's `agent.max_turns`). It is
the same count for every coding agent: model requests whose answer asked for tools.
`config.json` records `max_turns`, and its `harness_config` records `max_turns_method`
and `max_turns_enforced`. `result.json` records `turn_cap`, which includes whether
the agent `reached` the cap.

- **Claude Code** (`claude-code`, and the inner agent of `program` and `aspire`) gets
  `--max-turns N` (`max_turns_method: "claude-code --max-turns"`). Claude Code counts
  its agent loop's iterations. Each one is a model request whose answer asked for
  tools, followed by those tools' run. A retried request counts as the same
  iteration. After the tools of answer N have run, it does not send request N+1.
  Instead it ends with a result event `{"subtype": "error_max_turns", "is_error": true}`.
- **Codex** (`codex`, and the inner agent of `program-codex` and `aspire-codex`) has
  no turn option, so the runner applies the same count
  (`max_turns_method: "codex-hooks"`, codex-cli 0.167.0 and later). The runner writes
  `hooks.json` into the trial's own `CODEX_HOME` and passes
  `--dangerously-bypass-hook-trust`, because Robo Use wrote these hooks. The hooks
  report each model request to a server in the runner process.
  - A PostModelRequest hook reports each attempt's `status`. Only `completed`
    attempts count, so retries do not.
  - A PreModelRequest hook asks before every attempt. Once N requests have completed,
    it gets no answer and blocks, so request N+1 is never sent. The runner then stops
    Codex. Under a driver, the runner stops only Codex's own process group, and the
    driver goes on as it does after Claude Code's cap.

  The count is kept in the runner, where the agent cannot reach it. The hooks print
  nothing, and `hooks.json` is read-only in the sandbox.
- **Fallback** (`max_turns_method: "json-stream"`, `max_turns_enforced: false`): the
  runner uses this when the Codex is older than 0.167.0, when a shared account-pool
  home is in use (`ROBOUSE_CODEX_AUTH_DIR`), or when the home's path is too long for
  a Unix socket. The runner counts model answers in the `codex exec --json` stream
  and stops Codex once answer N+1 begins. This count is approximate. By that point
  request N+1 has already been sent, and one answer whose tool calls run one after
  another may count more than once. The same count backs up the hooks: if the stream
  shows more than N answers and no hook ever reported, the runner stops Codex and
  records `reached_by: "json-stream (hooks never fired)"`.

A trial that reaches the cap ends the same way for both agents. The runner closes the
episode with "agent exited without robo done" (`gave_up`) and records no harness
error. For example, Claude Code's `error_max_turns` result and Codex being stopped are
not infrastructure failures. Other harnesses refuse a turn cap.
