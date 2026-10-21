# Program API

Robo Use's version of ASPIRE's `docs/api-reference.md` for this trial: the contract programs run under, in practice runs (`cap-harness`) and in Stage 2 alike.

## The contract

- A program is Python source, run once from top to bottom.
- It may `import math` and `import numpy` (also `import numpy as np`), nothing else. ASPIRE allows `math` only; numpy is allowed here because this API passes arrays.
- It may not define a class or use `with`, `global`, `nonlocal`, `del`, `async`, `await`, `from ... import`, or a name or attribute that starts with `_`.
- Builtins: `Exception`, `ValueError`, `TypeError`, `abs`, `all`, `any`, `bool`, `dict`, `enumerate`, `float`, `int`, `len`, `list`, `max`, `min`, `print`, `range`, `reversed`, `round`, `set`, `sorted`, `str`, `sum`, `tuple`, `zip`. There is no `RuntimeError`, `getattr`, `hasattr`, `isinstance`, `type` or `open`.
- Set a top-level `result` (numbers, strings, lists, dictionaries): it is recorded in `source/program-result.json`.
- A tool that fails raises an exception with the tool's message; `except Exception` catches it.
- The program never ends the episode. After it returns (or raises), Robo Use ends the episode with `robo done` and judges the final state.

## Tools

Every function of the task's API, by its own name. Arrays and numbers go in as JSON; what a function returns comes back as numpy float arrays (a tuple when it returns several values; dictionaries stay dictionaries); what it prints is printed.

{{functions}}

The episode's other requests:

| Tool | What it does |
|---|---|
| `robo.info()` | the task, its action space, its API functions (`skills`) and the step budget, as a dictionary |
| `robo.observe(image=False, camera=None)` | the robot's state as numbers (`state`); with `image=True` also a picture from the task's camera (its file is copied into the run's `media/keyframes/`) |
| `robo.image(camera=None)` | one camera's picture now, as a numpy array (height x width x 3, uint8); on vision tasks `robo.info()["cameras"]` gives each camera's projection matrix |
| `robo.act(action, repeat=1)` | one low-level action, applied `repeat` times |
| `robo.move_to(x, y, z, grip=None, max_steps=100, tol=0.01)` | move the hand toward a point, where the task offers it |
| `robo.grip(value, steps=15)` | hold position and set the gripper (+1 close, -1 open), where the task offers it |
| `robo.skill(name, *args, **kwargs)` | any API function by name |

Every control step a tool takes counts against the task's step budget ({{max_steps}} steps).

## The task's API documentation

{{api_doc}}
