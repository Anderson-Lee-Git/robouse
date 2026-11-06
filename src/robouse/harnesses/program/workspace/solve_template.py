import numpy as np  # noqa: F401 - available to the program


def solve(robo):
    """Called once, on a fresh reset of the scene; `robo` is described in PROGRAM.md."""
    state = robo.observe()
    print(state)
    return None
