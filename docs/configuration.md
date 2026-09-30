# Configuration

Robo Use reads its settings from environment variables; every one is listed here, generated from `robouse.config`. Paths default to `~/.cache/robouse` (the cache) and `~/.config/robouse` (private settings such as remote worker endpoints, which the local runner's sandbox keeps from agents).

| Variable | Meaning |
|---|---|
| `ROBOUSE_CACHE_DIR` | cache for simulator virtualenvs, downloaded assets and harness homes (default ~/.cache/robouse) |
| `ROBOUSE_CONFIG_DIR` | private settings such as remote worker endpoints (default ~/.config/robouse); agents never see it |
| `ROBOUSE_MENAGERIE_ASSETS` | MuJoCo Menagerie robot models (default: the checkout's assets/menagerie, else <cache>/menagerie) |
| `ROBOUSE_ROBOHARM_TEX` | generated texture cache for the roboharm scenes (default <cache>/roboharm_tex) |
| `ROBOUSE_PRICING` | JSON price table for trial cost (default: the packaged pricing.json) |
| `ROBOUSE_SOCKET` | episode server socket the `robo` client talks to (set by the runner) |
| `ROBOUSE_ORACLE_TOKEN` | per-episode token that unlocks privileged state for the reference solution (set by the runner) |
| `ROBOUSE_RECORD_SIZE` | episode video size WIDTHxHEIGHT (default: the backend's native size) |
| `ROBOUSE_EPISODE_DIR` | episode folder a task verifier reads (set by the runner) |
| `ROBOUSE_VERIFIER_DIR` | folder a task verifier writes reward.txt to (set by the runner) |
| `ROBOUSE_TEXT_ONLY` | 1: `robo observe --image` prints the path without attaching the image (set for harnesses whose API rejects images) |
| `ROBOUSE_SANDBOX` | 0 disables the macOS Seatbelt sandbox around agent processes (default 1) |
| `ROBOUSE_SANDBOX_DENY` | extra colon-separated paths agents may neither read nor write |
| `ROBOUSE_DEXJOCO_PYTHON` | Python of the DexJoCo virtualenv (default <cache>/dexjoco-venv/bin/python) |
| `ROBOUSE_DMCONTROL_PYTHON` | Python of the dm_control virtualenv (default <cache>/dmcontrol-venv/bin/python) |
| `ROBOUSE_HUMANOIDBENCH_PYTHON` | Python of the HumanoidBench virtualenv (default <cache>/humanoidbench-venv/bin/python) |
| `ROBOUSE_MANISKILL_PYTHON` | Python of the ManiSkill virtualenv (default <cache>/maniskill-venv/bin/python) |
| `ROBOUSE_METADRIVE_PYTHON` | Python of the MetaDrive virtualenv (default <cache>/metadrive-venv/bin/python) |
| `ROBOUSE_MYOSUITE_PYTHON` | Python of the MyoSuite virtualenv (default <cache>/myosuite-venv/bin/python) |
| `ROBOUSE_ROBOCASA_PYTHON` | Python of the RoboCasa virtualenv (default <cache>/robocasa-venv/bin/python) |
| `ROBOUSE_DEXJOCO_QUIET` | 0 shows the dexjoco worker's stderr (default 1) |
| `ROBOUSE_DMCONTROL_QUIET` | 0 shows the dmcontrol worker's stderr (default 1) |
| `ROBOUSE_HUMANOIDBENCH_QUIET` | 0 shows the humanoidbench worker's stderr (default 1) |
| `ROBOUSE_MANISKILL_QUIET` | 0 shows the maniskill worker's stderr (default 1) |
| `ROBOUSE_METADRIVE_QUIET` | 0 shows the metadrive worker's stderr (default 1) |
| `ROBOUSE_MYOSUITE_QUIET` | 0 shows the myosuite worker's stderr (default 1) |
| `ROBOUSE_ROBOCASA_QUIET` | 0 shows the robocasa worker's stderr (default 1) |
| `ROBOUSE_MANISKILL_DEBUG` | 1: the ManiSkill worker logs each request |
| `ROBOUSE_HUMANOIDBENCH_POLICY` | HumanoidBench low-level walking policy (default <cache>/humanoidbench/h1_motion.pt) |
| `ROBOUSE_ROBOSUITE_PATH` | isolated robosuite 1.5 install for the robosuite suite (default <venv>/robosuite-1.5) |
| `ROBOUSE_BEHAVIOR_REMOTE` | BEHAVIOR worker endpoints file (default <config>/remote/behavior.json) |
| `ROBOUSE_GPU_REMOTE` | GPU-track worker endpoints file (default <config>/remote/gpu.json) |
| `ROBOUSE_ROBODOJO_REMOTE` | RoboDojo worker endpoints file (default <config>/remote/robodojo.json) |
| `ROBOUSE_BEHAVIOR_SECRET` | shared secret the BEHAVIOR worker requires (worker side; the client reads it from the endpoints file) |
| `ROBOUSE_GPU_SECRET` | shared secret the GPU-track worker requires (worker side) |
| `ROBOUSE_ROBODOJO_SECRET` | shared secret the RoboDojo worker requires (worker side) |
| `ROBOUSE_BEHAVIOR_DEBUG` | 1: the BEHAVIOR worker logs each request |
| `ROBOUSE_BEHAVIOR_PLAN` | BEHAVIOR worker: motion-planning mode for skills |
| `ROBOUSE_BEHAVIOR_TORCH_THREADS` | BEHAVIOR worker: torch CPU threads |
| `ROBOUSE_BEHAVIOR_MAX_GRASP_M` | BEHAVIOR worker: largest object size the grasp skill accepts, in metres |
| `ROBOUSE_ROBODOJO_DEBUG` | 1: the RoboDojo worker logs each request |
| `ROBOUSE_ROBODOJO_KIT_THREADS` | RoboDojo worker: Omniverse Kit worker threads |
| `ROBOUSE_ROBODOJO_TASK` | RoboDojo worker: task to preload at start |
| `ROBOUSE_ROBODOJO_SKILL_WALL_S` | RoboDojo worker: wall-clock limit per skill call, in seconds |
| `ROBOUSE_GPU_MAX_SESSIONS` | GPU-track worker: concurrent sessions |
| `ROBOUSE_GPU_IDLE_S` | GPU-track worker: idle seconds before a session is closed |
| `ROBOUSE_MS_SIM` | GPU-track worker: ManiSkill simulation backend |
| `ROBOUSE_PG_POLICIES` | GPU-track worker: folder of trained MuJoCo Playground policies |
| `ROBOUSE_IL_RTX` | GPU-track worker: 1 renders Isaac Lab with RTX |
| `ROBOUSE_VLA_URL` | policy server for the `vla` harness |
| `ROBOUSE_VLA_TOKEN` | bearer token for the policy server |
| `ROBOUSE_VLA_POLICY_CONFIG` | JSON file with overrides for the `vla` preset |
| `ROBOUSE_VLA_PYTHON` | interpreter that runs the `vla` client (default python3) |
| `ROBOUSE_VLA_CONFIG` | resolved `vla` preset, passed to the client (set by the runner) |
| `ROBOUSE_MOLMOACT2_URL` | MolmoAct2 policy server for the `molmoact2` harness |
| `ROBOUSE_MOLMOACT2_TOKEN` | bearer token for the MolmoAct2 server |
| `ROBOUSE_TASK_LANGUAGE` | the language instruction a VLA client sends (set by the runner) |
| `ROBOUSE_GRADER_URL` | OpenAI-compatible endpoint for `robouse grade` (default: Baseten) |
| `ROBOUSE_GRADER_API_KEY` | API key for `robouse grade` (default: BASETEN_API_KEY) |
| `ROBOUSE_RIG` | real-robot rig file; real tasks run on live hardware instead of the hardware-in-the-loop mock |
| `ROBOUSE_OPERATOR_DIR` | operator channel and e-stop latch for real robots (default ~/.config/robouse-operator) |
| `ROBOUSE_OPERATOR` | operator channel: tty, file or script (default: tty when attended) |
| `ROBOUSE_OPERATOR_SCRIPT` | scripted operator answers (hardware-in-the-loop tests only) |
| `ROBOUSE_ESTOP_FILE` | e-stop latch file (default <operator dir>/ESTOP) |
| `ROBOUSE_REAL_UNATTENDED` | 1: run real tasks without an operator (mock only) |
| `ROBOUSE_REAL_ORACLE` | reference-solution mode for real tasks (hardware-in-the-loop tests) |
| `ROBOUSE_HIL_DIR` | hardware-in-the-loop fixtures (default: the packaged fixtures) |
