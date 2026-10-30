"""Chancellor — governance-and-eval harness for long-running agents.

Doctrine:
  * Work is a graph, not a vibe.
  * Output is graded, not trusted.
  * Instruments fail closed.
  * Authority escalates; capability doesn't.
"""

__version__ = "0.1.0"

from .task_graph import (TaskGraph, TaskNode, NodeStatus, SCHEMA_VERSION,
                         AttemptCapError, IllegalTransitionError)
from .grader import Rubric, Criterion, GradeResult, grade
from .instruments import InstrumentPanel, CheckResult, default_panel
from .escalation import (Gatekeeper, EscalationRequest, ActionClass,
                         AuditLog, AuditWriteError)
from .api_client import MetaModelClient, NotConfiguredError, CostMeter
from .orchestrator import CrewRunner, RunReport
from .judge import Judge, JudgeError

__all__ = [
    "TaskGraph", "TaskNode", "NodeStatus", "SCHEMA_VERSION",
    "AttemptCapError", "IllegalTransitionError",
    "Rubric", "Criterion", "GradeResult", "grade",
    "InstrumentPanel", "CheckResult", "default_panel",
    "Gatekeeper", "EscalationRequest", "ActionClass",
    "AuditLog", "AuditWriteError",
    "MetaModelClient", "NotConfiguredError", "CostMeter",
    "CrewRunner", "RunReport",
    "Judge", "JudgeError",
]
