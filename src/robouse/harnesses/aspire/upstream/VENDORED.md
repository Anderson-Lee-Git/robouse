# Vendored ASPIRE files

Source: https://github.com/NVlabs/ASPIRE at commit fa00f0ef2bc1d91d594b9aa502c22133c9f538f7 ("ASPIRE v1.0 release", 2026-10-15), Apache License 2.0 (LICENSE, copyright 2026 NVIDIA CORPORATION & AFFILIATES; ASPIRE's NOTICE beside it). Robo Use copies the two simulation skills its `aspire` harnesses run, unchanged, and lays them out in each trial's workspace at their upstream paths (`claude/` as `.claude/`, `codex/` as `.codex/`); the folders here have no leading dot so that packaging tools and coding agents working on this repository do not treat them as live configuration.

| Here | Upstream | Changes |
|---|---|---|
| claude/skills/iterative-debugging/{SKILL.md, main-agent-prompt.md, subagent-prompt.md, verifier-prompt.md, clean-task-slate.md} | .claude/skills/iterative-debugging/ | none |
| claude/skills/iterative-debugging/skills/ | the skill library | none; it seeds a new library (../library.py) |
| claude/skills/iterative-debugging/scripts/ | campaign scripts | none |
| claude/skills/evosearch/ | .claude/skills/evosearch/ | none |
| codex/skills/{iterative-debugging, evosearch}/ | .codex/skills/ | none |

Not copied:

- `.claude/skills/iterative-debugging/robosuite/`: worked solutions (`*_fix_code.py`) and their held-out pass rates for CaP-X's robosuite tasks, the same tasks the `capx` suite holds. ASPIRE's own rules keep solutions away from the agents being measured (its verifier may not open `examples/`).
- `.claude/skills/iterative-debugging/behavior/`: the BEHAVIOR-1K protocol (Isaac Sim on a GPU).
- Everything else: cap-harness (`src/cap_harness`), its docs, `examples/`, the real-robot parts (`AGENTS.md`, `docs/system2*.md`, `docs/yam-real.md`, `.agents/`, anything under `yam_real`), media and the third-party submodules. ASPIRE's licensing index (`LICENSES/README.md` and `THIRD_PARTY_LICENSES.md`, at the v0.1 tag; v1.0 has none) lists no third-party material in the skill folders; its NOTICE says third-party components are the submodules under `third_party/`.

Robo Use's own files take the place of what is not copied, in each trial's workspace: `docs/robouse.md` (how ASPIRE maps onto the trial), `docs/api-reference.md` and `docs/run-artifacts.md` (the program contract and run layout), `cap-harness` (practice episodes) and `src/cap_harness/runtime.py` (the program check ASPIRE's lint imports). See ../workspace/.

SHA-256 of each file as copied (tests/test_aspire.py checks them):

```text
4f321b887d0350e672e06c8a8bc85cff17ee2d1f3c360617079041ceee324c81  LICENSE
720ea9aa05340560f996e73d9890e7e312d1e078ee363960a936ecd72864a809  NOTICE
7f7f4b86a35c46566d5dd8484e0532718304960153e2463411c6e96f2bf2202d  claude/skills/evosearch/SKILL.md
758c28ef40a33af0c40a37a7299692c168cf3dd854fab38a36917975d224a4ee  claude/skills/evosearch/clean-task-slate.md
77976a004c792472b76ecfaa10bb8e7fc427f65431cc7bc4e5b411f9ab1f3ca9  claude/skills/evosearch/main-agent-prompt.md
6e2d540f18e26478d8fde7ecab96ace89a15f2ae4eeadb3989425ecb1d8c93b2  claude/skills/evosearch/scripts/analyze_evosearch_traces.py
62c99f8a8b5e75091f42935cf8950da4c523d73cd51bd6b00814225b20127181  claude/skills/evosearch/scripts/evosearch_eval.py
9a39ad36fde444968a0796bfae802d39d4d8acf7874ef6ee03e7b2240f3408eb  claude/skills/evosearch/skills/README.md
fc0adca88aaa4e67933b39c341f4dce8c58597820361df6efbabea62a6e66ef0  claude/skills/evosearch/skills/evosearch-iteration.md
4b05d2bc1c00f1e12da888d47c69629e8ec4b2a77fae457b8a71b294227fdeda  claude/skills/evosearch/subagent-prompt.md
645502be26898cb729a01683c4c4cc86e9ad08807ea4f6f1861daf2e324d560c  claude/skills/iterative-debugging/SKILL.md
7f21455e0971f4091aebc2d1767112d5d45b3b7663ff22f27da0e72b787eca37  claude/skills/iterative-debugging/clean-task-slate.md
8db2bb2e564be5961230a367332b8ffb6989ed0ca797c453c332ac3bef69de5c  claude/skills/iterative-debugging/main-agent-prompt.md
208018d22aaa7a5eb46799fbafe64618e08253ebe1b8977d86cbb182de37cd6a  claude/skills/iterative-debugging/scripts/audit_seeding.py
45cb3613f19e6be17a7acc21f7b8832565f0e6300f58daea52bed3542848e115  claude/skills/iterative-debugging/scripts/campaign.py
f9859475b06411b180565ab436d306e7e9e97924bcfce1bd1d9a9eed9e9483b4  claude/skills/iterative-debugging/scripts/dispatch.py
3edb26a9248e578f4f852694fc1ac8af5e45cd642ed7f34c7cc95414dcee3722  claude/skills/iterative-debugging/scripts/gen_progress.py
ce5f13474f97fc0be295ef358ae5d8faacaf042b116607cb22d6c267b987c99a  claude/skills/iterative-debugging/scripts/init_run.py
247e3311cb07e5dca5c7a594bb7258e223ce1e93ba606e4b6ddd66f4e4cf5b0f  claude/skills/iterative-debugging/scripts/lint_skills.py
bd07e66cf44be9813bc26c54d81a42ca629e4d5b2682233209ea491f4b5ef598  claude/skills/iterative-debugging/scripts/run_validation.py
e1bbb3dd72048298a1e719e460f4f7ba3e954642dad6a22228499f6bfd4230ef  claude/skills/iterative-debugging/scripts/scene_snapshot.py
6dd611a61405547826793de31d73933dc169ff0163e3072090c963d750a3936a  claude/skills/iterative-debugging/scripts/trace_stats.py
a2729d8ae9b0609af20d6a567d7df865432103f9a2a8e5a05b8ea06e0542e784  claude/skills/iterative-debugging/scripts/watchdog.py
a3188000bad237de00757053c4acad1da80197be0c7e06b99aa8141b3bd2c7b8  claude/skills/iterative-debugging/skills/README.md
2ca0fee3df9117ddf764805a388d10a70c8f190263a5c438b1a46ecc58551284  claude/skills/iterative-debugging/skills/grasp.md
88d2b8eb60dc0d43fd891110a92b3327e524e5392ac17ad675c85e2143861d75  claude/skills/iterative-debugging/skills/localize.md
e7733e886aa54f3f94678abbad584944cebdb8257e4ae00776de2a69c9e8e1bc  claude/skills/iterative-debugging/skills/manipulation.md
a60e33eb881bb7e38d821e66835acf8e92106f83493b47ef9d9380462f6bd632  claude/skills/iterative-debugging/skills/task-exploration.md
6390321c603d31748a771caee1d04fa3082b44ae89acf7054f72e4444a18fdbe  claude/skills/iterative-debugging/skills/transport.md
ca78d55c8910d116f6ca0a02bc064c27d875a10e4981cba8fde96318581ac1db  claude/skills/iterative-debugging/subagent-prompt.md
f3362a4df3a41c8bed40b2f54e1faf08b3cf0aa80635194cb4560aad715ced9a  claude/skills/iterative-debugging/verifier-prompt.md
44e62d00b873fd48285dfb082f2b412684cd90a992ac267504ac2062c627afc7  codex/skills/evosearch/SKILL.md
3f4f4a7cc8089755385656ccc82b3caddd6c2698c6e8a5a33860a1191df213d8  codex/skills/evosearch/agents/openai.yaml
a971d4f45f684c7089afaf4997497831b40e2f1cc751b1953e9295114fa35e5d  codex/skills/iterative-debugging/SKILL.md
47c9afad9122407deb8263b7ed8c66ea9a4fd16e6e44cf2af55ea96959f3766c  codex/skills/iterative-debugging/agents/openai.yaml
```
