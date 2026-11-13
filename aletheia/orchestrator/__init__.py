"""Orchestration patterns. Both implement `run_pattern(ctx) -> FinalAnswer`."""
from .supervisor import run_supervisor  # noqa: F401
from .blackboard import run_blackboard  # noqa: F401

PATTERNS = {"supervisor": run_supervisor, "blackboard": run_blackboard}
