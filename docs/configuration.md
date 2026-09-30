# Configuration

Robo Use reads its settings from environment variables; the ones you set are listed here, generated from `robouse.config`. Paths default to `~/.cache/robouse` (the cache) and `~/.config/robouse` (private settings such as remote worker endpoints, which the local runner's sandbox keeps from agents).

| Variable | Meaning |
|---|---|
| `ROBOUSE_CACHE_DIR` | cache for simulator virtualenvs, downloaded assets and harness homes (default ~/.cache/robouse) |
| `ROBOUSE_CONFIG_DIR` | private settings such as remote worker endpoints (default ~/.config/robouse); agents never see it |
| `ROBOUSE_MENAGERIE_ASSETS` | MuJoCo Menagerie robot models (default: the checkout's assets/menagerie, else <cache>/menagerie) |
| `ROBOUSE_PRICING` | JSON price table for trial cost (default: the packaged pricing.json) |
| `ROBOUSE_RECORD_SIZE` | episode video size WIDTHxHEIGHT (default: the backend's native size) |
| `ROBOUSE_SANDBOX` | 0 disables the macOS Seatbelt sandbox around agent processes (default 1) |
| `ROBOUSE_SANDBOX_DENY` | extra colon-separated paths agents may neither read nor write |
| `ROBOUSE_DEXJOCO_PYTHON` | Python of the DexJoCo virtualenv (default <cache>/dexjoco-venv/bin/python) |
| `ROBOUSE_DMCONTROL_PYTHON` | Python of the dm_control virtualenv (default <cache>/dmcontrol-venv/bin/python) |
| `ROBOUSE_HUMANOIDBENCH_PYTHON` | Python of the HumanoidBench virtualenv (default <cache>/humanoidbench-venv/bin/python) |
| `ROBOUSE_MANISKILL_PYTHON` | Python of the ManiSkill virtualenv (default <cache>/maniskill-venv/bin/python) |
| `ROBOUSE_METADRIVE_PYTHON` | Python of the MetaDrive virtualenv (default <cache>/metadrive-venv/bin/python) |
| `ROBOUSE_MYOSUITE_PYTHON` | Python of the MyoSuite virtualenv (default <cache>/myosuite-venv/bin/python) |
| `ROBOUSE_ROBOCASA_PYTHON` | Python of the RoboCasa virtualenv (default <cache>/robocasa-venv/bin/python) |
| `ROBOUSE_VLA_URL` | policy server for the `vla` harness |
| `ROBOUSE_VLA_TOKEN` | bearer token for the policy server |
| `ROBOUSE_VLA_POLICY_CONFIG` | JSON file with overrides for the `vla` preset |
| `ROBOUSE_MOLMOACT2_URL` | MolmoAct2 policy server for the `molmoact2` harness |
| `ROBOUSE_MOLMOACT2_TOKEN` | bearer token for the MolmoAct2 server |
| `ROBOUSE_GRADER_URL` | OpenAI-compatible endpoint for `robouse grade` (default: Baseten) |
| `ROBOUSE_GRADER_API_KEY` | API key for `robouse grade` (default: BASETEN_API_KEY) |
| `ROBOUSE_OPERATOR_DIR` | operator channel and e-stop latch for real robots (default ~/.config/robouse-operator) |
