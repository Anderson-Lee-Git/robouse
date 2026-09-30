# CLIs

`robouse` runs tasks, trials and runs; `robo` is the agent's only way to act. The help below is the output of `robouse 0.1.1`.

```console
$ robouse --help
usage: robouse [-h] [--version]
               {serve,run,run-many,estop,operator,hil-check,robots,report,grade,doctor,summarize,tasks,fetch-assets,export,remix,components}
               ...

Robo Use: agent as a policy for embodied agents. Runs robot tasks with an
agent harness as the policy. https://robouse.ai

positional arguments:
  {serve,run,run-many,estop,operator,hil-check,robots,report,grade,doctor,summarize,tasks,fetch-assets,export,remix,components}
    serve               run one trusted episode server (used by `run`)
    run                 run one trial end to end
    run-many            run a set of trials
    estop               latch the real-robot e-stop (every real episode stops
                        at its next command); --clear releases it
    operator            answer a pending operator gate or verdict, or send the
                        policy a remark
    hil-check           strict replay of recorded real sessions through the
                        safety guard + tracking-model fit
    robots              list real-robot profiles, drivers and hardware-in-the-
                        loop fixtures
    report              metrics with 95% confidence intervals over job
                        folders, grouped by trial attributes
    grade               VLM second opinion on finished trials from their video
                        frames (writes <trial>/grader/vlm.json)
    doctor              what this machine can run: backends, harnesses,
                        credentials, VLA, real-robot SDKs, plugins
    summarize           distil a trial into learnings (markdown) for --prior-
                        learnings
    tasks               list tasks (default: the bundled tasks)
    fetch-assets        download the MuJoCo Menagerie robot models (menagerie,
                        RoboHarm, drone and embodiment suites)
    export              write robouse tasks as native BenchFlow task packages
                        (a movable bundle)
    remix               compose a task from an embodiment, a scene and a task
                        component (+ modifiers)
    components          list or show components (embodiments, scenes, tasks,
                        modifiers)

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```

## robouse serve

```console
$ robouse serve --help
usage: robouse serve [-h] --task TASK --run-dir RUN_DIR --socket SOCKET
                     [--workspace WORKSPACE] [--seed SEED]
                     [--max-wall-s MAX_WALL_S] [--record-size WxH]
                     [--ready-file READY_FILE] [--split SPLIT]

options:
  -h, --help            show this help message and exit
  --task TASK           task folder or bundled task id
  --run-dir RUN_DIR     where the episode record is written
  --socket SOCKET       Unix socket path to listen on
  --workspace WORKSPACE
                        agent workspace (camera images are saved in its
                        observations/)
  --seed SEED           override the task's seed
  --max-wall-s MAX_WALL_S
                        wall-clock budget in seconds (default 1800)
  --record-size WxH     render the episode video at this size, e.g. 1280x720
                        (agent images unchanged; default: native size; also
                        $ROBOUSE_RECORD_SIZE)
  --ready-file READY_FILE
                        file created once the server is listening
  --split SPLIT         placement split for backends with seeded placements:
                        nominal, interpolation or extrapolation
```

Runs one episode server until the episode ends, then prints the verdict as JSON. `robouse run` starts it for you; to drive a robot by hand, start it and set `ROBOUSE_SOCKET` to the socket path.

## robouse run

```console
$ robouse run --help
usage: robouse run [-h] --task TASK --harness HARNESS [--model MODEL] --out
                   OUT [--timeout TIMEOUT] [--record-size WxH] [--seed SEED]
                   [--rig RIG] [--split SPLIT]
                   [--extra-instruction EXTRA_INSTRUCTION]
                   [--prior-learnings PRIOR_LEARNINGS] [--seeds SEEDS]
                   [--engine {local,benchflow}] [--sandbox SANDBOX]
                   [--reasoning-effort REASONING_EFFORT] [--job-name JOB_NAME]

options:
  -h, --help            show this help message and exit
  --task TASK           task folder or bundled task id
  --harness HARNESS, --agent HARNESS
                        oracle, noop, claude-code, codex, claude-code-glm,
                        codex-glm, mini-swe-agent-glm, molmoact2 or vla (see
                        https://robouse.ai/docs/harnesses/); with --engine
                        benchflow, a BenchFlow agent (see `bench agent list`)
  --model MODEL         model for the harness (default: the harness's default)
  --out OUT             job folder; the trial is written to
                        OUT/<task>__<harness>__<id>/
  --timeout TIMEOUT     agent wall-clock limit in seconds (default: the task's
                        agent.timeout_sec)
  --record-size WxH     render the episode video at this size, e.g. 1280x720
                        (agent images unchanged; default: native size; also
                        $ROBOUSE_RECORD_SIZE)
  --seed SEED           override the task's seed
  --rig RIG             real-robot rig file (YAML, keyed by robot): runs real
                        tasks on live hardware instead of the mock
  --split SPLIT         placement split: nominal, interpolation or
                        extrapolation (tabletop pick-and-place tasks)
  --extra-instruction EXTRA_INSTRUCTION
                        text appended to the task instruction (recorded in
                        config.json)
  --prior-learnings PRIOR_LEARNINGS
                        markdown notes (e.g. from `robouse summarize`)
                        appended to the instruction
  --seeds SEEDS         (--engine benchflow) one trial per seed, e.g. 0-4 or
                        0,3,7
  --engine {local,benchflow}
                        local (default): host processes, macOS Seatbelt
                        sandbox, no Docker; benchflow: one BenchFlow job in
                        Docker (needs robouse[benchflow])
  --sandbox SANDBOX     (--engine benchflow) BenchFlow sandbox (default
                        docker)
  --reasoning-effort REASONING_EFFORT
                        (--engine benchflow) agent reasoning effort, for
                        agents that expose one
  --job-name JOB_NAME   (--engine benchflow) BenchFlow job name (default: a
                        timestamp)
```

Prints a JSON summary: `trial`, `reward`, `outcome`, `steps`, `wall_s`, `exception`. A non-null `exception` means the trial could not start; it is not scored.

## robouse run-many

```console
$ robouse run-many --help
usage: robouse run-many [-h] [--tasks TASKS] --harness HARNESS [--model MODEL]
                        --out OUT [--filter FILTER] [--limit LIMIT]
                        [--concurrency CONCURRENCY] [--timeout TIMEOUT]
                        [--task-list TASK_LIST] [--record-size WxH] [--resume]
                        [--rig RIG] [--include INCLUDE] [--exclude EXCLUDE]
                        [--sample SAMPLE] [--sample-seed SAMPLE_SEED]
                        [--seeds SEEDS] [--epochs EPOCHS] [--retries RETRIES]
                        [--split SPLIT] [--mode {sim,real}]
                        [--extra-instruction EXTRA_INSTRUCTION]
                        [--prior-learnings PRIOR_LEARNINGS] [--dry-run]
                        [--seed SEED] [--engine {local,benchflow}]
                        [--sandbox SANDBOX]
                        [--reasoning-effort REASONING_EFFORT]
                        [--job-name JOB_NAME]

options:
  -h, --help            show this help message and exit
  --tasks TASKS         task root (default: the bundled tasks)
  --harness HARNESS, --agent HARNESS
                        oracle, noop, claude-code, codex, claude-code-glm,
                        codex-glm, mini-swe-agent-glm, molmoact2 or vla (see
                        https://robouse.ai/docs/harnesses/); with --engine
                        benchflow, a BenchFlow agent (see `bench agent list`)
  --model MODEL         model for the harness (default: the harness's default)
  --out OUT             job folder; one trial folder per task
  --filter FILTER       only task ids containing this substring
  --limit LIMIT         run at most this many tasks (0: all)
  --concurrency CONCURRENCY
                        trials run in parallel (default 1)
  --timeout TIMEOUT     agent wall-clock limit per trial in seconds (default:
                        each task's)
  --task-list TASK_LIST
                        file with one task id per line (subset of --tasks)
  --record-size WxH     render the episode video at this size, e.g. 1280x720
                        (agent images unchanged; default: native size; also
                        $ROBOUSE_RECORD_SIZE)
  --resume              skip tasks that already have a finished, non-infra-
                        failed trial in --out
  --rig RIG             real-robot rig file (YAML, keyed by robot): real tasks
                        run on live hardware, one at a time
  --include INCLUDE     only task ids matching this glob (repeatable), e.g.
                        'libero-10-*'
  --exclude EXCLUDE     skip task ids matching this glob (repeatable)
  --sample SAMPLE       run a seeded random sample of N tasks
  --sample-seed SAMPLE_SEED
                        seed for --sample (default 0)
  --seeds SEEDS         episode seeds per task, e.g. 0-4 or 0,3,7 (default:
                        the task's own seed); gives pass@k
  --epochs EPOCHS       repeat each (task, seed) N times (real robots:
                        repeated trials)
  --retries RETRIES     rerun a trial up to N times after an infrastructure
                        failure (exponential backoff; the failed trial is kept
                        in OUT/_infra_failed)
  --split SPLIT         placement split: nominal, interpolation or
                        extrapolation (identical placements per seed)
  --mode {sim,real}     only simulated or only real-robot tasks
  --extra-instruction EXTRA_INSTRUCTION
                        text appended to every task instruction
  --prior-learnings PRIOR_LEARNINGS
                        markdown notes appended to every instruction (retry
                        with learning)
  --dry-run             print the resolved trial plan and exit
  --seed SEED           override every task's seed
  --engine {local,benchflow}
                        local (default): host processes, macOS Seatbelt
                        sandbox, no Docker; benchflow: one BenchFlow job in
                        Docker (needs robouse[benchflow])
  --sandbox SANDBOX     (--engine benchflow) BenchFlow sandbox (default
                        docker)
  --reasoning-effort REASONING_EFFORT
                        (--engine benchflow) agent reasoning effort, for
                        agents that expose one
  --job-name JOB_NAME   (--engine benchflow) BenchFlow job name (default: a
                        timestamp)
```

Prints one line per finished trial, appends it to `OUT/run_log.jsonl`, and ends with the number solved. Examples: [Run a suite or dataset](run-a-suite.md).

## robouse estop

```console
$ robouse estop --help
usage: robouse estop [-h] [--clear] [reason]

positional arguments:
  reason

options:
  -h, --help  show this help message and exit
  --clear
```

## robouse operator

```console
$ robouse operator --help
usage: robouse operator [-h] [--note NOTE] {status,answer,say} [value]

positional arguments:
  {status,answer,say}
  value

options:
  -h, --help           show this help message and exit
  --note NOTE
```

## robouse hil-check

```console
$ robouse hil-check --help
usage: robouse hil-check [-h] [fixtures ...]

positional arguments:
  fixtures    fixture names under assets/hil (default: all)

options:
  -h, --help  show this help message and exit
```

## robouse robots

```console
$ robouse robots --help
usage: robouse robots [-h]

options:
  -h, --help  show this help message and exit
```

## robouse report

```console
$ robouse report --help
usage: robouse report [-h] [--by BY] [--metrics METRICS] [--json JSON]
                      [--cost-quality COST_QUALITY] [--svg SVG]
                      jobs [jobs ...]

positional arguments:
  jobs                  job folders (run-many --out)

options:
  -h, --help            show this help message and exit
  --by BY               group keys, comma-separated (repeatable): harness,
                        model, suite, category, difficulty, task, split, seed,
                        mode, job, regime, released (default harness,model)
  --metrics METRICS     metrics to show, comma-separated (default: the nine
                        robot metrics + cost)
  --json JSON           write the full report as JSON
  --cost-quality COST_QUALITY
                        write cost-vs-success points (JSON) for groups with a
                        known cost
  --svg SVG             write a cost-vs-success scatter (SVG)
```

## robouse grade

```console
$ robouse grade --help
usage: robouse grade [-h] [--model MODEL] [--rubric RUBRIC]
                     trials [trials ...]

positional arguments:
  trials           trial folders or job folders

options:
  -h, --help       show this help message and exit
  --model MODEL    vision-language model (OpenAI-compatible; default Kimi K3
                   on Baseten)
  --rubric RUBRIC  extra rubric text appended to the task's success rule
```

## robouse doctor

```console
$ robouse doctor --help
usage: robouse doctor [-h]

options:
  -h, --help  show this help message and exit
```

## robouse summarize

```console
$ robouse summarize --help
usage: robouse summarize [-h] [-o OUT] trial

positional arguments:
  trial              trial folder (OUT/<task>__<harness>__<id>)

options:
  -h, --help         show this help message and exit
  -o OUT, --out OUT  output file (default: <trial>/learnings.md; - for stdout)
```

## robouse tasks

```console
$ robouse tasks --help
usage: robouse tasks [-h] [--path] [root]

positional arguments:
  root        task root (default: the bundled tasks)

options:
  -h, --help  show this help message and exit
  --path      print the bundled task directory and exit
```

## robouse fetch-assets

```console
$ robouse fetch-assets --help
usage: robouse fetch-assets [-h] [--dest DEST] [--robot ROBOT]

options:
  -h, --help     show this help message and exit
  --dest DEST    target directory (default: ~/.cache/robouse/menagerie or
                 $ROBOUSE_MENAGERIE_ASSETS)
  --robot ROBOT  only this Menagerie robot folder (repeatable), e.g.
                 unitree_go2
```

## robouse export

```console
$ robouse export --help
usage: robouse export [-h] --tasks TASKS [TASKS ...] --out OUT
                      [--filter FILTER] [--noop]

options:
  -h, --help            show this help message and exit
  --tasks TASKS [TASKS ...]
                        task folders, suite folders or a task root
  --out OUT             bundle directory: <out>/tasks/<id>/ and
                        <out>/runtime-<hash>/
  --filter FILTER       comma-separated substrings; keep tasks whose id
                        matches one
  --noop                noop oracle (negative control: must score 0)
```

## robouse remix

```console
$ robouse remix --help
usage: robouse remix [-h] --embodiment EMBODIMENT --scene SCENE --task TASK
                     [--obs OBS] [--budget BUDGET]
                     [--perturbation PERTURBATION] [--safety SAFETY]
                     [--roles ROLES] [--seed SEED] [--out OUT] [--check]
                     [--json] [--no-validate] [--keep-runs KEEP_RUNS]

options:
  -h, --help            show this help message and exit
  --embodiment EMBODIMENT
                        embodiment component id (robouse components list)
  --scene SCENE         scene component id
  --task TASK           task component id
  --obs OBS             observation mode: state (default), vision or noisy
  --budget BUDGET       budget: normal (default), loose or tight
  --perturbation PERTURBATION
                        none (default), push, dynamics or clutter
  --safety SAFETY       safety overlay: none (default), direct, indirect or
                        privacy
  --roles ROLES         single (default) or planner-operator
  --seed SEED           instance seed (default 0)
  --out OUT             folder to write the task folder into (not needed with
                        --check)
  --check               only report whether the components fit together, and
                        why not
  --json                with --check: print the report as JSON
  --no-validate         skip the oracle (must score 1) and no-op (must score
                        0) runs
  --keep-runs KEEP_RUNS
                        keep the validation trials in this folder
```

## robouse components

```console
$ robouse components --help
usage: robouse components [-h] {list,show,export,matrix} ...

positional arguments:
  {list,show,export,matrix}
    list                list components
    show                print one component's manifest
    export              (maintainers) rewrite components/ from the runtime
                        declarations
    matrix              the compatibility matrix of every embodiment x scene x
                        task, as JSON

options:
  -h, --help            show this help message and exit
```

```console
$ robouse components list --help
usage: robouse components list [-h] [--all]
                               [{embodiments,scenes,tasks,modifiers}]

positional arguments:
  {embodiments,scenes,tasks,modifiers}
                        only this kind

options:
  -h, --help            show this help message and exit
  --all                 also list fixed components (the existing suites'
                        robots and scenes)
```

```console
$ robouse components show --help
usage: robouse components show [-h] [--compatible] id

positional arguments:
  id            component id

options:
  -h, --help    show this help message and exit
  --compatible  also list what it can be remixed with
```

```console
$ robouse components matrix --help
usage: robouse components matrix [-h] [--out OUT]

options:
  -h, --help  show this help message and exit
  --out OUT   write it here (default: stdout)
```

## robo

```console
$ robo help
`robo`: the only way an agent touches the robot. Standard library only.

Finds the episode socket from $ROBOUSE_SOCKET (set by the runner) and sends one JSON request.

  robo info                          action space, skills, step budget
  robo observe [--image] [--camera C] robot and object state; --image also saves a camera PNG and prints its path
  robo act A1 A2 ... [--repeat N]    apply one low-level action N times (N <= 50)
  robo move-to X Y Z [--grip G]      move the hand toward a point (skill; may be disabled per task)
  robo grip G [--steps N]            hold position and set the gripper (+1 close, -1 open)
  robo skill NAME [ARG ...]          run a named high-level skill listed by `robo info` (only some tasks have them)
  robo done ["message"]              end the episode and ask for scoring
  robo give-up ["message"]           end the episode without claiming success
Add --json to any command for raw JSON output.
```

Each call sends one JSON object to the episode server at `$ROBOUSE_SOCKET` and prints the response, for example `{"op": "act", "action": [0, 0, -1, 1], "repeat": 5}` and `{"ok": true, "result": {...}}`. Operations: `info`, `status`, `observe`, `act`, `move_to`, `grip`, `skill`, `done`, `give_up`. `robo info` also describes the robot's embodiment: its action groups, skills, cameras and budgets. Skills run on the server, and each simulated step they take counts against the budget. Without an episode, `robo` prints an error and exits 1.
