"""Chancellor — governance-and-eval harness for long-running agents.

Doctrine:
  * Work is a graph, not a vibe.
  * Output is graded, not trusted.
  * Instruments fail closed.
  * Authority escalates; capability doesn't.
"""

from .api_client import CostMeter, MetaModelClient, NotConfiguredError
from .escalation import (
    ActionClass,
    AuditLog,
    AuditWriteError,
    EscalationRequest,
    Gatekeeper,
)
from .grader import Criterion, GradeResult, Rubric, grade
from .instruments import CheckResult, InstrumentPanel, default_panel
from .judge import Judge, JudgeError
from .orchestrator import CrewRunner, RunReport
from .supervise import (
    SupervisionState,
    Supervisor,
    SupervisorConfig,
    verify_at_checkpoint_boundary,
)
from .task_graph import (
    SCHEMA_VERSION,
    AttemptCapError,
    IllegalTransitionError,
    NodeStatus,
    TaskGraph,
    TaskNode,
)


def _declared_version() -> str:
    """The version is declared exactly once: pyproject.toml [project].

    Installed distributions read it back from their own metadata; an
    uninstalled source checkout reads the pyproject two levels above
    this file; a bare copied tree gets the sentinel, which says the
    version is unknown rather than repeating a stale literal.
    (Release-sync SPEC 2.2.)
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("chancellor")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    try:
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with pyproject.open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:
        return "0.0.0+unknown"


__version__ = _declared_version()


__all__ = [
    "TaskGraph",
    "TaskNode",
    "NodeStatus",
    "SCHEMA_VERSION",
    "AttemptCapError",
    "IllegalTransitionError",
    "Rubric",
    "Criterion",
    "GradeResult",
    "grade",
    "InstrumentPanel",
    "CheckResult",
    "default_panel",
    "Gatekeeper",
    "EscalationRequest",
    "ActionClass",
    "AuditLog",
    "AuditWriteError",
    "MetaModelClient",
    "NotConfiguredError",
    "CostMeter",
    "CrewRunner",
    "RunReport",
    "Judge",
    "JudgeError",
    "Supervisor",
    "SupervisorConfig",
    "SupervisionState",
    "verify_at_checkpoint_boundary",
]
