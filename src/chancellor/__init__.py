"""Chancellor — governance-and-eval harness for long-running agents.

Doctrine:
  * Work is a graph, not a vibe.
  * Output is graded, not trusted.
  * Instruments fail closed.
  * Authority escalates; capability doesn't.
"""

__version__ = "0.1.0"

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
from .task_graph import (
    SCHEMA_VERSION,
    AttemptCapError,
    IllegalTransitionError,
    NodeStatus,
    TaskGraph,
    TaskNode,
)

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
]
