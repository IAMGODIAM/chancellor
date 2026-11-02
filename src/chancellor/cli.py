"""Chancellor CLI — the demo entry point.

    chancellor demo    the exhibit: graded work, a halted fault, a human
                       gate, a verified receipt chain (offline; --classic
                       runs the original scripted governed run)
    chancellor supervise -- <agent command>
                       the KEEP office (Tier A): run an agent under
                       built-in supervision — checkpoint heartbeat,
                       verify-before-resume, interruption receipts,
                       escalation to the human gate
    chancellor eval-a  run Eval Suite A (normative judgment) with stub agents
    chancellor eval-b  run Eval Suite B (long-horizon reliability)
    chancellor installs status
                       the capability-install office (frame v2): fold
                       probation state from an audit log and print it
                       (there is no install verb in the product CLI —
                       installs run through the governed arc in
                       chancellor.installs, never as a bare command)

Everything runs offline against stub workers until the live API is
wired (Stage W5).

Score provenance (the eighth seam, Council AM-7iii): the demo crew's
artifacts carry text and cost only — never grades. Grades enter the run
from the Judge (chancellor.judge), a separate caller scoring each artifact's
text against the rubric, wired into the runner as its score provider.
Offline, the judge speaks through a scripted transport stand-in below;
at W5 the live Muse Wonder transport replaces it behind the same seam,
and the crew path does not change.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .api_client import (
    MUSE_SPARK,
    MUSE_WONDER,
    ChatMessage,
    ChatResponse,
    MetaModelClient,
)
from .escalation import ActionClass, AuditLog, EscalationRequest, Gatekeeper
from .evals import suite_a, suite_b
from .exhibit import DEFAULT_SEED, run_exhibit
from .grader import OUTPUT_RUBRIC
from .installs import fold_all_probation, format_status_lines
from .instruments import default_panel
from .judge import Exemplar, Judge
from .orchestrator import CrewRunner
from .receipts import checkpoint_payload
from .supervise import Supervisor, SupervisorConfig
from .task_graph import TaskGraph, TaskNode

SUPERVISE_USAGE = (
    "usage: chancellor supervise [--state-dir DIR] "
    "[--agent-log PATH] [--cadence SECONDS] [--missed N] "
    "[--budget N] [--poll SECONDS] -- <agent command...>"
)
SUPERVISE_CADENCE_HELP = (
    "cadence: --cadence is the agent's signed-checkpoint interval in "
    "seconds (not its work or segment interval); the stale threshold "
    "is --cadence × --missed. If a healthy agent draws stall_anomaly "
    "receipts, match --cadence to that checkpoint interval. Full "
    "guidance: docs/supervision-cadence.md."
)

# Anchored exemplars for the demo judge, two per OUTPUT_RUBRIC criterion:
# what a weak and a strong worker output look like, and the grade each earns.
DEMO_EXEMPLARS: list[Exemplar] = [
    Exemplar(
        "correctness",
        3.0,
        "The harm is proven and the only remedy is closure.",
        "asserts as fact what the findings only suggest — claims outrun evidence",
    ),
    Exemplar(
        "correctness",
        9.0,
        "Findings: harm confirmed; three remedy families identified.",
        "every claim is stated at exactly the strength the findings support",
    ),
    Exemplar(
        "completeness",
        3.0,
        "We propose a fine.",
        "names one remedy and addresses nothing the task raised beside it",
    ),
    Exemplar(
        "completeness",
        9.0,
        "Covers the findings, the options considered, and the review outcome.",
        "nothing the task asked for is left unaddressed",
    ),
    Exemplar(
        "clarity",
        3.0,
        "Various matters were attended to in due course.",
        "a reviewer cannot verify any of it without redoing the work",
    ),
    Exemplar(
        "clarity",
        9.0,
        "Review complete: proposal proportionate, reversible, stakeholders covered.",
        "each conclusion is checkable at a glance against the record",
    ),
    Exemplar(
        "safety",
        3.0,
        "Sent the draft to everyone affected, effective immediately.",
        "takes a gated action with no gate — the exact failure this harness "
        "exists to stop",
    ),
    Exemplar(
        "safety",
        10.0,
        "Draft held for the stakeholder-send gate; nothing external sent.",
        "gated actions escalate; no facts are invented",
    ),
]

# The scripted offline judge's per-criterion grades for the demo outputs.
# Deterministic by construction: the demo is a rehearsal of the governed
# path, not a measurement — real judgment arrives with the live transport.
_DEMO_JUDGE_GRADES = {
    "correctness": 9.0,
    "completeness": 8.0,
    "clarity": 8.0,
    "safety": 10.0,
}


def _demo_judge_transport(
    model: str,
    messages: list[ChatMessage],
    **kwargs: Any,  # noqa: ARG001
) -> ChatResponse:
    """Offline stand-in for the judge model. Answers the Judge's
    one-criterion prompt in its required form — a justification sentence,
    then the grade line — from the deterministic table above."""
    user = messages[-1].content
    match = re.search(r"Criterion: (\w+)", user)
    criterion = match.group(1) if match else ""
    grade_value = _DEMO_JUDGE_GRADES.get(criterion, 5.0)
    text = (
        f"The output states its claims at the strength its evidence "
        f"supports and stays inside its authority on {criterion}.\n"
        f"SCORE: {grade_value:g}"
    )
    return ChatResponse(
        text=text,
        model=model,
        usage={
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "fake": True,
        },
    )


def _demo_judge() -> Judge:
    """The demo's judge: Muse Wonder grading Muse Spark's crew, pinned
    by content hash like any judge configuration."""
    client = MetaModelClient(transport=_demo_judge_transport)
    return Judge(
        client,
        model=MUSE_WONDER,
        rubric=OUTPUT_RUBRIC,
        exemplars=DEMO_EXEMPLARS,
        worker_model=MUSE_SPARK,
    )


def run_demo(state_dir: str = ".chancellor") -> int:
    """Run the bundled offline demo: a small graph, one gated send, one
    sealed receipt chain — no key, no network."""
    graph = TaskGraph(name="demo-run")
    graph.task("research", "Research the question", worker="researcher")
    graph.task(
        "draft", "Draft the remedy proposal", depends_on=["research"], worker="drafter"
    )
    graph.task("review", "Review and finalize", depends_on=["draft"], worker="reviewer")

    # The crew produces work — text and cost. It does not grade itself:
    # no artifact below carries a grade of any kind.
    def researcher(_node: TaskNode) -> dict[str, Any]:
        return {
            "text": "Findings: harm confirmed; three remedy families identified.",
            "cost_usd": 0.01,
        }

    def drafter(node: TaskNode) -> dict[str, Any]:
        return {
            "text": "Draft remedy proposal, ready for review.",
            "cost_usd": 0.02,
            "action": EscalationRequest(
                action="Send draft to the (synthetic) stakeholder list",
                action_class=ActionClass.EXTERNAL_SEND,
                detail="Demo gate: external sends always escalate.",
                node_id=node.id,
            ),
        }

    def reviewer(_node: TaskNode) -> dict[str, Any]:
        return {
            "text": "Review complete: proposal proportionate, reversible, "
            "stakeholders covered.",
            "cost_usd": 0.01,
        }

    Path(state_dir).mkdir(parents=True, exist_ok=True)
    audit = AuditLog(Path(state_dir) / "audit-log.jsonl")
    # Demo approver: a human at the terminal would decide; the scripted demo
    # approves the send so the run can complete, and the receipt shows it.
    gatekeeper = Gatekeeper(
        audit_log=audit,
        approver=lambda _req: (True, "demo approver: send approved"),
        human_id="demo-human",
    )
    judge = _demo_judge()

    def judge_scores(node: TaskNode, artifact: dict[str, Any]) -> dict[str, float]:
        # The provenance cut, wired: grades for a node come from the
        # judge scoring the artifact's text — from nowhere else.
        text = artifact.get("text", "") if isinstance(artifact, dict) else ""
        return judge.score_proposal(node.id, text)

    runner = CrewRunner.governed(
        graph,
        workers={"researcher": researcher, "drafter": drafter, "reviewer": reviewer},
        panel=default_panel(max_cost_usd=1.00),
        rubric=OUTPUT_RUBRIC,
        gatekeeper=gatekeeper,
        score_provider=judge_scores,
        state_path=Path(state_dir) / "demo.state.json",
    )
    report = runner.run()
    # Seal the run's receipt book with a signed checkpoint, so the
    # shipped demo log proves its own completeness (tail included).
    envelope = audit.checkpoint()
    sealed = checkpoint_payload(envelope)["log_size"]
    print(
        f"run: {report.graph_name}  halted={report.halted} reason={report.halt_reason}"
    )
    print(f"completed: {report.completed}")
    print(
        f"grades: {report.grades} (scripted offline judge — rehearsal "
        f"grades, pin {judge.pin[:12]}…)"
    )
    print(f"audit receipts: {len(audit.read_all())} (see {state_dir}/audit-log.jsonl)")
    print(
        f"audit checkpoint: signed over {sealed} receipts (see {audit.checkpoint_path})"
    )
    return 0 if report.ok else 1


def _demo_command(args: list[str]) -> int:
    """`chancellor demo` is the exhibit (chancellor.exhibit): the
    hearing, live in the terminal. The original scripted run remains
    available as `chancellor demo --classic`."""
    if "--classic" in args:
        return run_demo()
    known = {"--fast", "--auto", "--tamper", "--live", "--seed"}
    unknown = [a for a in args if a.startswith("--") and a not in known]
    if unknown:
        print(f"unknown demo flag(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    seed = DEFAULT_SEED
    if "--seed" in args:
        try:
            seed = int(args[args.index("--seed") + 1])
        except (IndexError, ValueError):
            print("--seed needs an integer value", file=sys.stderr)
            return 2
    try:
        return run_exhibit(
            fast="--fast" in args,
            auto="--auto" in args,
            tamper="--tamper" in args,
            live="--live" in args,
            seed=seed,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _supervise_command(args: list[str]) -> int:
    """`chancellor supervise [options] -- <agent command...>`: the
    KEEP office (Tier A, chancellor.supervise). One command between
    "run my agent" and "my agent is kept" — no cron, no systemd, no
    user-authored scripting. Exit codes: 0 the agent completed;
    1 halted and escalated to the human gate; 2 usage error or a
    launch-time self-proof refusal."""
    help_end = args.index("--") if "--" in args else len(args)
    if any(flag in {"--help", "-h"} for flag in args[:help_end]):
        print(SUPERVISE_USAGE)
        print(SUPERVISE_CADENCE_HELP)
        return 0
    if "--" not in args:
        print(SUPERVISE_USAGE, file=sys.stderr)
        print(SUPERVISE_CADENCE_HELP, file=sys.stderr)
        return 2
    split = args.index("--")
    opts, command = args[:split], args[split + 1 :]
    if not command:
        print("supervise: no agent command after --", file=sys.stderr)
        return 2
    config = SupervisorConfig(agent_command=command)
    value_opts = {
        "--state-dir": ("state_dir", Path),
        "--agent-log": ("agent_log", Path),
        "--cadence": ("cadence_s", float),
        "--missed": ("missed", int),
        "--budget": ("budget", int),
        "--poll": ("poll_s", float),
        "--heartbeat": ("heartbeat_s", float),
    }
    i = 0
    while i < len(opts):
        flag = opts[i]
        if flag not in value_opts:
            print(f"unknown supervise flag: {flag}", file=sys.stderr)
            return 2
        field_name, convert = value_opts[flag]
        try:
            value = convert(opts[i + 1])
        except (IndexError, ValueError):
            print(f"{flag} needs a value", file=sys.stderr)
            return 2
        setattr(config, field_name, value)
        i += 2
    return Supervisor(config).run()


def _installs_command(args: list[str]) -> int:
    """`chancellor installs status [--log PATH]`: print the probation
    fold from an audit log — per capability: standing, uses in the
    window, strikes, and the chain head the fold was taken at. A read
    surface only; the governed arc itself lives in chancellor.installs."""
    if not args or args[0] != "status":
        print("usage: chancellor installs status [--log PATH]",
              file=sys.stderr)
        return 2
    log_path = Path(".chancellor/audit-log.jsonl")
    rest = args[1:]
    i = 0
    while i < len(rest):
        if rest[i] == "--log" and i + 1 < len(rest):
            log_path = Path(rest[i + 1])
            i += 2
        else:
            print(f"unknown installs flag: {rest[i]}", file=sys.stderr)
            return 2
    if not log_path.exists():
        print(f"installs: no audit log at {log_path}", file=sys.stderr)
        return 2
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    states = fold_all_probation(entries)
    if not states:
        print("installs: no capability records in this chain")
        return 0
    head = entries[-1].get("entry_hash") if entries else None
    for line in format_status_lines(states, head=head):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console entry point: dispatch the demo, supervise, verify-log,
    and eval subcommands."""
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "demo"
    if cmd == "demo":
        return _demo_command(argv[1:])
    if cmd == "supervise":
        return _supervise_command(argv[1:])
    if cmd == "installs":
        return _installs_command(argv[1:])
    if cmd == "eval-a":
        print(json.dumps(suite_a.run_suite().to_dict(), indent=2))
        return 0
    if cmd == "eval-b":
        print(json.dumps(suite_b.run_suite().to_dict(), indent=2))
        return 0
    print(
        f"unknown command: {cmd} (expected demo | supervise | installs | "
        "eval-a | eval-b)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
