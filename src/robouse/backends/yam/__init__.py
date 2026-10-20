"""Dual YAM: Dream Labs' bimanual YAM station in simulation (Dream's own MuJoCo scene, in its own virtualenv)."""

from .backend import YamBackend, oracle_main

__all__ = ["YamBackend", "oracle_main"]
