"""FR3 + Robotiq 2F-85 in a compiled household scene package (MuJoCo 4, in process)."""


def __getattr__(name: str):
    # lazy, so `python -m robouse.backends.household.assets fetch` runs without importing MuJoCo
    if name == "HouseholdBackend":
        from .backend import HouseholdBackend

        return HouseholdBackend
    raise AttributeError(name)


__all__ = ["HouseholdBackend"]
