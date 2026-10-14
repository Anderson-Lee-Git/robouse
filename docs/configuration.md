# Configuration

Robo Use reads its settings from environment variables; the ones you set are listed here, generated from `robouse.config`. Paths default to `~/.cache/robouse` (the cache) and `~/.config/robouse` (private settings such as remote worker endpoints, which the local runner's sandbox keeps from agents).

| Variable | Meaning |
|---|---|
| `ROBOUSE_CACHE_DIR` | cache for simulator virtualenvs, downloaded assets and harness homes (default ~/.cache/robouse) |
| `ROBOUSE_CONFIG_DIR` | private settings such as remote worker endpoints (default ~/.config/robouse); agents never see it |
| `ROBOUSE_MENAGERIE_ASSETS` | MuJoCo Menagerie robot models (default: the checkout's assets/menagerie, else <cache>/menagerie) |
| `ROBOUSE_PRICING` | JSON price table for trial cost (default: the packaged pricing.json) |
| `ROBOUSE_RECORD_SIZE` | episode video size WIDTHxHEIGHT (default: the backend's native size) |
| `ROBOUSE_AGENT_IMAGES` | 0: the model gets no image input in this run, whatever it takes (its gateway replaces every image part; recorded as image_input: false). Default: from the model registry |
| `ROBOUSE_SPEND_CAP_USD` | the model spend at which the model gateway stops a trial, in USD (default 5; 0: no cap, needed for a model without a price, such as glm/glm-5.3; recorded as a budget stop) |
| `ROBOUSE_SANDBOX` | 0 disables the macOS Seatbelt sandbox around agent processes (default 1) |
| `ROBOUSE_SANDBOX_DENY` | extra colon-separated paths agents may neither read nor write |
| `ROBOUSE_DEXJOCO_PYTHON` | Python of the DexJoCo virtualenv (default <cache>/dexjoco-venv/bin/python) |
| `ROBOUSE_DMCONTROL_PYTHON` | Python of the dm_control virtualenv (default <cache>/dmcontrol-venv/bin/python) |
| `ROBOUSE_HUMANOIDBENCH_PYTHON` | Python of the HumanoidBench virtualenv (default <cache>/humanoidbench-venv/bin/python) |
| `ROBOUSE_MANISKILL_PYTHON` | Python of the ManiSkill virtualenv (default <cache>/maniskill-venv/bin/python) |
| `ROBOUSE_METADRIVE_PYTHON` | Python of the MetaDrive virtualenv (default <cache>/metadrive-venv/bin/python) |
| `ROBOUSE_MYOSUITE_PYTHON` | Python of the MyoSuite virtualenv (default <cache>/myosuite-venv/bin/python) |
| `ROBOUSE_ROBOCASA_PYTHON` | Python of the RoboCasa virtualenv (default <cache>/robocasa-venv/bin/python) |
| `ROBOUSE_RLEBENCH_PYTHON` | Python of the RLE-Bench virtualenv (default <cache>/rlebench-venv/bin/python) |
| `ROBOUSE_CAPX_PYTHON` | Python of the CaP-X virtualenv (default <cache>/capx-venv/bin/python) |
| `ROBOUSE_CAPX_LIBERO_PYTHON` | Python of the CaP-X LIBERO virtualenv (default <cache>/capx-libero-venv/bin/python) |
| `ROBOUSE_VLA_URL` | policy server for the `vla` harness |
| `ROBOUSE_VLA_TOKEN` | bearer token for the policy server |
| `ROBOUSE_VLA_POLICY_CONFIG` | JSON file with overrides for the `vla` preset |
| `ROBOUSE_MOLMOACT2_URL` | MolmoAct2 policy server for the `molmoact2` harness |
| `ROBOUSE_MOLMOACT2_TOKEN` | bearer token for the MolmoAct2 server |
| `ROBOUSE_DIMCODE` | the dimcode executable for the `dimcode` harness (default: `dimcode` on PATH) |
| `ROBOUSE_DIMCODE_NODE` | Node 24 or 26 that runs dimcode (default: `node` on PATH) |
| `ROBOUSE_SHOW_HARNESS_URL` | OpenAI-compatible server (base URL ending in /v1) of a self-hosted model for the `show-harness` harness, e.g. vLLM serving a Show-Harness adapter |
| `ROBOUSE_SHOW_HARNESS_TOKEN` | token for that server: a bearer token, or sent under the overrides' `token_header` |
| `ROBOUSE_SHOW_HARNESS_CONFIG` | JSON file of `show-harness` overrides (mode zs or ft, step sizes, plugins) |
