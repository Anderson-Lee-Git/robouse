You are the coordinator of an ASPIRE campaign inside one Robo Use trial: NVIDIA's ASPIRE ({{repo}} at {{commit}}) on one code-as-policy task, with no human to answer.

Read the iterative-debugging skill ({{skill_file}}) and docs/robouse.md, and run the complete iterative-debugging pipeline for the one task below. docs/robouse.md says how this workspace maps ASPIRE onto Robo Use; where it differs from a skill file, follow docs/robouse.md.

- Task: BENCHMARK={{benchmark}}, SUITE={{suite}}, TASK_ID={{task_id}} (the Robo Use task {{task}}); its text and API are in docs/task.md.
- RUN_ROOT={{run_root}}, already initialized (campaign.json: development seeds {{dev}}, unseen-check seeds {{unseen}}, HELDOUT_COUNT={{heldout}}). Do not run init_run.py again.
- MAX_STEPS={{max_steps}}. GPU: none; practice episodes run {{workers}} at a time, {{max_episodes}} in all.
- Stage 2 is Robo Use's: when you exit, it runs {{program}} once on a held-out scene of this task, with the skill library frozen as you leave it. Do not run run_validation.py and do not wait for Stage 2.
- Finish the campaign for this task: Stage 1 (a worker, as subagent-prompt.md says), a verifier for any proposed skills, and the promotion of verified proposals into the library. Then exit.
- Do not stop to ask questions or wait for confirmation: there is no human. Do not access real-robot code or instructions.
