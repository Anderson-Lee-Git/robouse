# CLIs

`robouse` runs tasks, trials and runs; `robo` is the agent's only way to act. The help below is the output of `robouse 0.2.0`.

```console
$ robouse --help
usage: robouse [-h] [--version] COMMAND ...

Robo Use: run robot tasks with an agent harness as the policy.
https://robouse.ai

options:
  -h, --help    show this help message and exit
  --version     show program's version number and exit

commands:
  COMMAND
    run         run one trial end to end
    run-many    run a set of trials
    tasks       list, create and check tasks
    components  list, show and check components
    fetch-assets
                download the MuJoCo Menagerie robot models (menagerie,
                roboharm, drone; --robot or --all for the embodiment suites
                and composed tasks)
    report      metrics with 95% confidence intervals over job folders,
                grouped by trial attributes
    summarize   distil a trial into learnings (markdown) for --prior-learnings
    doctor      what this machine can run: simulators, harnesses, credentials
                and the VLA server
```

## robo

```console
$ robo help
`robo`: the only way an agent touches the robot. Standard library only.

Finds the episode socket from $ROBOUSE_SOCKET (set by the runner; $ROBO_SOCKET on BenchFlow) and sends one JSON
request.

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
