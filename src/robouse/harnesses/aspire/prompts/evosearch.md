You are running ASPIRE's Evolutionary Search inside one Robo Use trial: NVIDIA's ASPIRE ({{repo}} at {{commit}}) on one code-as-policy task, with no human to answer.

Read the evosearch skill ({{skill_file}}) and docs/robouse.md, and run the complete Evolutionary Search pipeline for the one task below, as its coordinator. docs/robouse.md says how this workspace maps ASPIRE onto Robo Use; where it differs from a skill file, follow docs/robouse.md.

- Task: BENCHMARK={{benchmark}}, SUITE={{suite}}, TASK_ID={{task_id}} (the Robo Use task {{task}}); its text and API are in docs/task.md.
- EVOSEARCH_DIR=outputs/evosearch, EVALDIR=outputs/evosearch_eval; TASK_DIR={{evo_task_dir}}.
- BASELINE_RATE: {{baseline}}
- Trial seeds for the iterations: the development seeds {{dev}}. MAX_STEPS={{max_steps}}. GPU: none; practice episodes run {{workers}} at a time, {{max_episodes}} in all.
- Stage 2 is Robo Use's: when you exit, it runs {{program}} once on a held-out scene of this task, with the skill library frozen as you leave it. Skip step 7b (Stage 2) and do not run run_validation.py.
- Do not stop to ask questions or wait for confirmation: there is no human. Do not access real-robot code or instructions.
