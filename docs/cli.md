# CLIs

`robouse` runs tasks, trials and runs; `robo` is the agent's only way to act. The help below is the output of `robouse 0.2.0`.

```console
$ robouse --help
usage: robouse [-h] [--version]
               {serve,run,run-many,export,tasks,components,fetch-assets,report,grade,summarize,doctor,estop,operator,hil-check,robots}
               ...

Robo Use: run robot tasks with an agent harness as the policy.
https://robouse.ai

positional arguments:
  {serve,run,run-many,export,tasks,components,fetch-assets,report,grade,summarize,doctor,estop,operator,hil-check,robots}
    serve               run one trusted episode server (used by `run`)
    run                 run one trial end to end
    run-many            run a set of trials
    export              write tasks as native BenchFlow task packages (needs
                        robouse[benchflow])
    tasks               list, compose, scaffold and check tasks
    components          list, show and check components
    fetch-assets        download the MuJoCo Menagerie robot models (menagerie,
                        roboharm, drone; --robot or --all for the embodiment
                        suites and composed tasks)
    report              metrics with 95% confidence intervals over job
                        folders, grouped by trial attributes
    grade               a vision-language model's second opinion on finished
                        trials, from their video frames (writes
                        <trial>/grader/vlm.json)
    summarize           distil a trial into learnings (markdown) for --prior-
                        learnings
    doctor              what this machine can run: backends, harnesses,
                        credentials, VLA, real-robot SDKs, plugins
    estop               latch the real-robot e-stop (every real episode stops
                        at its next command); --clear releases it
    operator            answer a pending operator gate or verdict, or send the
                        policy a remark
    hil-check           replay recorded real sessions strictly through the
                        safety guard and fit the tracking model
    robots              list real-robot profiles, drivers and hardware-in-the-
                        loop fixtures

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
  --record-size WxH     render the episode video at this size, e.g. 1280x720;
                        agent images are unchanged (default: the backend's
                        native size, or $ROBOUSE_RECORD_SIZE)
  --ready-file READY_FILE
                        file created once the server is listening
  --split SPLIT         placement split: nominal, interpolation or
                        extrapolation (tasks with seeded placements)
```

Runs one episode server until the episode ends, then prints the verdict as JSON. `robouse run` starts it for you; to drive a robot by hand, start it and set `ROBOUSE_SOCKET` to the socket path.

## robouse run

```console
$ robouse run --help
usage: robouse run [-h] --task TASK --out OUT [--seeds SEEDS] --harness
                   HARNESS [--model MODEL] [--timeout TIMEOUT]
                   [--record-size WxH] [--seed SEED] [--rig RIG]
                   [--split SPLIT] [--extra-instruction EXTRA_INSTRUCTION]
                   [--prior-learnings PRIOR_LEARNINGS]
                   [--engine {local,benchflow}] [--sandbox SANDBOX]
                   [--reasoning-effort REASONING_EFFORT] [--job-name JOB_NAME]

options:
  -h, --help            show this help message and exit
  --task TASK           task folder or bundled task id
  --out OUT             job folder; the trial is written to
                        OUT/<task>__<harness>__<id>/
  --seeds SEEDS         (--engine benchflow) one trial per seed, e.g. 0-4 or
                        0,3,7
  --harness HARNESS, --agent HARNESS
                        harness: oracle, noop, claude-code, codex, claude-
                        code-glm, codex-glm, mini-swe-agent-glm, molmoact2 or
                        vla (https://robouse.ai/docs/concepts/#harnesses);
                        with --engine benchflow, a BenchFlow agent (`bench
                        agent list`)
  --model MODEL         model for the harness (default: the harness's)
  --timeout TIMEOUT     agent wall-clock limit in seconds (default: the task's
                        agent.timeout_sec)
  --record-size WxH     render the episode video at this size, e.g. 1280x720;
                        agent images are unchanged (default: the backend's
                        native size, or $ROBOUSE_RECORD_SIZE)
  --seed SEED           override the task's seed
  --rig RIG             real-robot rig file (YAML, keyed by robot): real tasks
                        run on live hardware instead of the mock
  --split SPLIT         placement split: nominal, interpolation or
                        extrapolation (tasks with seeded placements)
  --extra-instruction EXTRA_INSTRUCTION
                        text appended to the task instruction (recorded in
                        config.json)
  --prior-learnings PRIOR_LEARNINGS
                        markdown notes (e.g. from `robouse summarize`)
                        appended to the instruction
  --engine {local,benchflow}
                        local (default): processes on this machine, macOS
                        Seatbelt sandbox, no Docker; benchflow: one BenchFlow
                        job in Docker (needs robouse[benchflow])
  --sandbox SANDBOX     (--engine benchflow) BenchFlow sandbox (default
                        docker)
  --reasoning-effort REASONING_EFFORT
                        (--engine benchflow) agent reasoning effort, for
                        agents that have one
  --job-name JOB_NAME   (--engine benchflow) BenchFlow job name (default: a
                        timestamp)
```

Prints a JSON summary: `trial`, `reward`, `outcome`, `steps`, `wall_s`, `exception`. A non-null `exception` means the trial could not start; it is not scored.

## robouse run-many

```console
$ robouse run-many --help
usage: robouse run-many [-h] [--tasks TASKS] --out OUT [--filter FILTER]
                        [--task-list TASK_LIST] [--include INCLUDE]
                        [--exclude EXCLUDE] [--mode {sim,real}]
                        [--sample SAMPLE] [--sample-seed SAMPLE_SEED]
                        [--limit LIMIT] [--seeds SEEDS] [--epochs EPOCHS]
                        [--concurrency CONCURRENCY] [--retries RETRIES]
                        [--resume] [--dry-run] --harness HARNESS
                        [--model MODEL] [--timeout TIMEOUT]
                        [--record-size WxH] [--seed SEED] [--rig RIG]
                        [--split SPLIT]
                        [--extra-instruction EXTRA_INSTRUCTION]
                        [--prior-learnings PRIOR_LEARNINGS]
                        [--engine {local,benchflow}] [--sandbox SANDBOX]
                        [--reasoning-effort REASONING_EFFORT]
                        [--job-name JOB_NAME]

options:
  -h, --help            show this help message and exit
  --tasks TASKS         task root (default: the bundled tasks)
  --out OUT             job folder; one trial folder per task
  --filter FILTER       only task ids containing this substring
  --task-list TASK_LIST
                        file with one task id per line (a subset of --tasks)
  --include INCLUDE     only task ids matching this glob (repeatable), e.g.
                        'libero-10-*'
  --exclude EXCLUDE     skip task ids matching this glob (repeatable)
  --mode {sim,real}     only simulated or only real-robot tasks
  --sample SAMPLE       run a seeded random sample of N tasks
  --sample-seed SAMPLE_SEED
                        seed for --sample (default 0)
  --limit LIMIT         run at most this many tasks (default 0: all)
  --seeds SEEDS         episode seeds per task, e.g. 0-4 or 0,3,7: one trial
                        per task and seed, for pass@k (default: the task's own
                        seed)
  --epochs EPOCHS       repeat each task and seed N times (default 1)
  --concurrency CONCURRENCY
                        trials run in parallel (default 1)
  --retries RETRIES     rerun a trial up to N times after an infrastructure
                        failure, with backoff; the failed trial is kept in
                        OUT/_infra_failed (default 0)
  --resume              skip tasks that have a finished trial in --out that
                        did not fail on infrastructure
  --dry-run             print the resolved trial plan and exit
  --harness HARNESS, --agent HARNESS
                        harness: oracle, noop, claude-code, codex, claude-
                        code-glm, codex-glm, mini-swe-agent-glm, molmoact2 or
                        vla (https://robouse.ai/docs/concepts/#harnesses);
                        with --engine benchflow, a BenchFlow agent (`bench
                        agent list`)
  --model MODEL         model for the harness (default: the harness's)
  --timeout TIMEOUT     agent wall-clock limit in seconds (default: each
                        task's)
  --record-size WxH     render the episode video at this size, e.g. 1280x720;
                        agent images are unchanged (default: the backend's
                        native size, or $ROBOUSE_RECORD_SIZE)
  --seed SEED           override every task's seed
  --rig RIG             real-robot rig file (YAML, keyed by robot): real tasks
                        run on live hardware instead of the mock, one at a
                        time
  --split SPLIT         placement split: nominal, interpolation or
                        extrapolation (tasks with seeded placements)
  --extra-instruction EXTRA_INSTRUCTION
                        text appended to the task instruction (recorded in
                        config.json)
  --prior-learnings PRIOR_LEARNINGS
                        markdown notes (e.g. from `robouse summarize`)
                        appended to the instruction
  --engine {local,benchflow}
                        local (default): processes on this machine, macOS
                        Seatbelt sandbox, no Docker; benchflow: one BenchFlow
                        job in Docker (needs robouse[benchflow])
  --sandbox SANDBOX     (--engine benchflow) BenchFlow sandbox (default
                        docker)
  --reasoning-effort REASONING_EFFORT
                        (--engine benchflow) agent reasoning effort, for
                        agents that have one
  --job-name JOB_NAME   (--engine benchflow) BenchFlow job name (default: a
                        timestamp)
```

Prints one line per finished trial, appends it to `OUT/run_log.jsonl`, and ends with the number solved. Examples: [Run a suite or dataset](run-a-suite.md).

## robouse export

```console
$ robouse export --help
usage: robouse export [-h] --tasks TASKS [TASKS ...] --out OUT
                      [--filter FILTER] [--noop]

options:
  -h, --help            show this help message and exit
  --tasks TASKS [TASKS ...]
                        task folders, suite folders or a task root
  --out OUT             bundle folder: <out>/tasks/<id>/ and
                        <out>/runtime-<hash>/
  --filter FILTER       comma-separated substrings; keep tasks whose id
                        contains one
  --noop                no-op reference solution (negative control: must score
                        0)
```

## robouse tasks

```console
$ robouse tasks --help
usage: robouse tasks [-h] {list,init,check} ...

list, compose, scaffold and check tasks

positional arguments:
  {list,init,check}
    list             list tasks (default: the bundled tasks)
    init             compose a task from components, regenerate one, or
                     scaffold a blank task
    check            validate a task: schema, `bench tasks check`, reference
                     solution 1, no-op control 0

options:
  -h, --help         show this help message and exit
```

```console
$ robouse tasks list --help
usage: robouse tasks list [-h] [--path] [ROOT]

positional arguments:
  ROOT        task root (default: the bundled tasks)

options:
  -h, --help  show this help message and exit
  --path      print the bundled task directory and exit
```

```console
$ robouse tasks init --help
usage: robouse tasks init [-h] [--embodiment ID] [--scene ID] [--task ID]
                          [--obs MODE] [--budget BUDGET] [--perturb KIND]
                          [--safety LEVEL] [--roles ROLES] [--seed N]
                          [--out DIR] [--grid] [--from DIR] [--upgrade]
                          [--no-validate] [--keep-trials DIR]
                          [DIR]

compose a task from components and validate it (--embodiment, --scene,
--task), regenerate a composed task from its recorded instance (--from), or
scaffold a blank task (DIR)

positional arguments:
  DIR                   blank task folder to create (scaffold mode)

options:
  -h, --help            show this help message and exit
  --embodiment ID       embodiment component id (robouse components list)
  --scene ID            scene component id
  --task ID             task component id
  --obs MODE            observation mode: state (default), vision or noisy
  --budget BUDGET       step budget: normal (default), loose or tight
  --perturb KIND        perturbation: none (default), push, dynamics or
                        clutter
  --safety LEVEL        safety overlay: none (default), direct, indirect or
                        privacy
  --roles ROLES         roles: single (default) or planner-operator
  --seed N              instance seed (default 0)
  --out DIR             folder to write the composed task folder(s) into
  --grid                comma-separated values in any flag: compose every
                        compatible combination
  --from DIR            regenerate the composed task in this folder from its
                        recorded instance
  --upgrade             with --from: use the installed component versions if
                        they differ
  --no-validate         write without running the reference solution and the
                        no-op control
  --keep-trials DIR, --keep-runs DIR
                        keep the validation trials in this folder
```

```console
$ robouse tasks check --help
usage: robouse tasks check [-h] [--level LEVEL] [--no-run] [--keep-trials DIR]
                           DIR

positional arguments:
  DIR                   task folder

options:
  -h, --help            show this help message and exit
  --level LEVEL         `bench tasks check` level (default structural)
  --no-run              skip the reference solution and no-op control trials
  --keep-trials DIR, --keep-runs DIR
                        keep the trials in this folder
```

`robouse tasks` alone lists the tasks: id, backend and simulator env id. `tasks init` composes a task from components and keeps it only if the reference solution scores 1 and the no-op control 0; with only `DIR` it scaffolds a blank task folder. `tasks check` re-runs those checks on any task folder ([Write or compose a task](write-a-task.md)).

## robouse components

```console
$ robouse components --help
usage: robouse components [-h] {list,show,check} ...

the embodiments, scenes, task templates and modifiers composed tasks are built
from

positional arguments:
  {list,show,check}
    list             list components
    show             print one component's manifest
    check            whether an embodiment, a scene and a task template fit
                     together, and why not

options:
  -h, --help         show this help message and exit
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
usage: robouse components show [-h] [--compatible] ID

positional arguments:
  ID            component id

options:
  -h, --help    show this help message and exit
  --compatible  also list the combinations it composes into
```

```console
$ robouse components check --help
usage: robouse components check [-h] [--obs MODE] [--budget BUDGET]
                                [--perturb KIND] [--safety LEVEL]
                                [--roles ROLES] [--seed N] [--json]
                                EMBODIMENT SCENE TASK

positional arguments:
  EMBODIMENT       embodiment component id
  SCENE            scene component id
  TASK             task component id

options:
  -h, --help       show this help message and exit
  --obs MODE       observation mode: state (default), vision or noisy
  --budget BUDGET  step budget: normal (default), loose or tight
  --perturb KIND   perturbation: none (default), push, dynamics or clutter
  --safety LEVEL   safety overlay: none (default), direct, indirect or privacy
  --roles ROLES    roles: single (default) or planner-operator
  --seed N         instance seed to lay out (default 0)
  --json           print the report as JSON
```

## robouse fetch-assets

```console
$ robouse fetch-assets --help
usage: robouse fetch-assets [-h] [--dest DEST] [--robot ROBOT] [--all]

options:
  -h, --help     show this help message and exit
  --dest DEST    target folder (default: <cache>/menagerie, or
                 $ROBOUSE_MENAGERIE_ASSETS)
  --robot ROBOT  only this Menagerie robot folder (repeatable), e.g.
                 unitree_go2
  --all          every robot the bundled suites use (about 2 GB)
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
                        robot metrics and cost)
  --json JSON           write the full report as JSON
  --cost-quality COST_QUALITY
                        write cost-versus-success points (JSON) for groups
                        with a known cost
  --svg SVG             write a cost-versus-success scatter (SVG)
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
  --model MODEL    vision-language model, OpenAI-compatible (default: Kimi K3
                   on Baseten)
  --rubric RUBRIC  extra rubric text appended to the task's success rule
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

## robouse doctor

```console
$ robouse doctor --help
usage: robouse doctor [-h]

options:
  -h, --help  show this help message and exit
```

## robouse estop

```console
$ robouse estop --help
usage: robouse estop [-h] [--clear] [reason]

positional arguments:
  reason      why (default: operator e-stop)

options:
  -h, --help  show this help message and exit
  --clear     release the e-stop
```

## robouse operator

```console
$ robouse operator --help
usage: robouse operator [-h] [--note NOTE] {status,answer,say} [value]

positional arguments:
  {status,answer,say}  status, answer or say
  value                answer: yes, no, partial or skip; say: the remark

options:
  -h, --help           show this help message and exit
  --note NOTE          a note recorded with the answer
```

## robouse hil-check

```console
$ robouse hil-check --help
usage: robouse hil-check [-h] [fixtures ...]

positional arguments:
  fixtures    hardware-in-the-loop fixture names (default: all)

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
