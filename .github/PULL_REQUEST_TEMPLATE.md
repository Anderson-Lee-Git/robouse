## What and why

<!-- What this changes and why. Link the issue it closes, if any. -->

## Kind

- [ ] Bug fix
- [ ] Task or suite (new or changed)
- [ ] Harness, runner or episode server
- [ ] Sandbox or scoring
- [ ] Documentation only

## Checks

- [ ] `uvx ruff@0.14.3 check .` and `uvx ruff@0.14.3 format --check .`
- [ ] `.venv/bin/pytest -q`
- [ ] For task changes: `robouse tasks check` on every changed task (reference solution 1, no-op control 0)
- [ ] Public docs updated, and every command added to them run as written
- [ ] No credentials, `.env` files, run folders or large binaries committed

## Sandbox and scoring

<!-- If this touches the sandbox, the episode server, a judge or a harness launcher: what can an agent do or see now that it could not before, or the reverse? Update SECURITY.md if the sandbox's limits change. Otherwise write "none". -->
