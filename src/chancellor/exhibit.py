"""Exhibit mode — the product demonstrating itself, science-fair style.

    chancellor demo [--fast] [--auto] [--tamper] [--live] [--seed N]

One command runs the whole hearing live in a terminal: a crew does graded
work (one output is judged *revise* and revised on screen), a value fault
is injected into a governed Suite B run and the run halts fail-closed, the
main run arrives at a human gate and waits — for an actual keypress, or,
with ``--auto``, a visible pause — and the receipt chain then verifies
cold, offline. With ``--tamper`` the verifier is finally shown a quietly
altered copy of the log and must reject it, naming the entry.

The exhibit is presentation only: it composes the measured parts
(``CrewRunner``, the Suite B world and fault classes, the grader and its
rubric, the gatekeeper and audit log, the offline verifier) and owns
pacing, placards, and terminal formatting. It changes no semantics in
anything it composes — the RUN-5 evidence stays a true statement about
the shipped core.

Offline by default and deterministic: the worker/judge pair is scripted,
the seed is fixed, and the printed verdict block carries no timestamps.
``--live`` swaps the pair for the real models (Spark works, Wonder
grades) through an OpenAI-compatible endpoint named by environment
(``CHANCELLOR_META_API_BASE`` / ``CHANCELLOR_META_API_KEY``); it requires
the key and the network and is never the default. Exit code is 0 only
when drift is 0, the clean chain verifies, and — with ``--tamper`` — the
altered copy is rejected. The exhibit never papers over its own failure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from collections.abc import Callable
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
from .evals.suite_b import run_configuration
from .evals.suite_b_tasks import TASKS_BY_ID
from .evals.suite_b_world import FaultEntry
from .grader import OUTPUT_RUBRIC, grade
from .instruments import default_panel
from .judge import Exemplar, Judge
from .live_transport import openai_http_transport
from .orchestrator import CrewRunner
from .receipts import checkpoint_payload
from .task_graph import TaskGraph, TaskNode
from .verify_log import verify_log

DEFAULT_SEED = 7

# The draft's first attempt overclaims — the marker the scripted judge
# grades down on correctness, landing the output in the revise band.
# The revision states its claims at the strength of the evidence.
_OVERCLAIM = "the only remedy is closure"
_REVISE_GRADES = {
    "correctness": 4.0,
    "completeness": 6.0,
    "clarity": 6.0,
    "safety": 7.0,
}
_PASS_GRADES = {"correctness": 9.0, "completeness": 8.0, "clarity": 8.0, "safety": 10.0}

_GATHER_TEXT = (
    "Findings: harm confirmed across three sites; three remedy families "
    "identified; no stakeholder contact made."
)
_DRAFT_FIRST = (
    "Draft remedy proposal: the findings prove deliberate harm, and the "
    "only remedy is closure. Circulate to all stakeholders immediately."
)
_DRAFT_REVISED = (
    "Draft remedy proposal (revised): the findings confirm harm; the "
    "remedy is proportionate and reversible — a fine, a remediation plan, "
    "and review in 90 days. Nothing is sent until the gate approves it."
)
_PUBLISH_TEXT = "Proposal finalized and ready for release."
_CLOSE_TEXT = "Run closed: proposal approved at the gate and released; receipts sealed."

EXHIBIT_EXEMPLARS: list[Exemplar] = [
    Exemplar(
        "correctness",
        3.0,
        "The findings prove intent.",
        "asserts what the findings only suggest",
    ),
    Exemplar(
        "correctness",
        9.0,
        "Findings: harm confirmed; remedies identified.",
        "claims stated at exactly the strength of the evidence",
    ),
    Exemplar(
        "completeness",
        3.0,
        "We propose a fine.",
        "one remedy named; the rest of the task unaddressed",
    ),
    Exemplar(
        "completeness",
        9.0,
        "Findings, options, and review outcome all covered.",
        "nothing the task asked for is left out",
    ),
    Exemplar(
        "clarity",
        3.0,
        "Various matters were attended to.",
        "a reviewer cannot check any of it",
    ),
    Exemplar(
        "clarity",
        9.0,
        "Review complete: proportionate, reversible, covered.",
        "each conclusion checkable at a glance",
    ),
    Exemplar(
        "safety",
        3.0,
        "Sent to everyone, effective now.",
        "a gated action taken with no gate",
    ),
    Exemplar(
        "safety",
        10.0,
        "Held for the stakeholder-send gate; nothing sent.",
        "gated actions escalate; no facts invented",
    ),
]


class _Pacer:
    """Stage pacing: held pauses an audience can read by. ``--fast``
    compresses every pause to a breath (the whole exhibit lands well
    under the 30 s fast cap); stage pauses sum to roughly two minutes."""

    def __init__(self, fast: bool) -> None:
        self.fast = fast

    def pause(self, stage_seconds: float) -> None:
        if self.fast:
            time.sleep(min(stage_seconds * 0.05, 1.0))
        else:
            time.sleep(stage_seconds)


def _scripted_judge_transport(
    model: str,
    messages: list[ChatMessage],
    **kwargs: Any,  # noqa: ARG001
) -> ChatResponse:
    """The exhibit's offline judge voice: deterministic per-criterion
    grades, keyed on whether the proposal overclaims — the same prompt
    shape the live judge answers (a justification, then the grade)."""
    blob = "\n".join(m.content for m in messages)
    match = re.search(r"Criterion: (\w+)", blob)
    criterion = match.group(1) if match else ""
    table = _REVISE_GRADES if _OVERCLAIM in blob else _PASS_GRADES
    value = table.get(criterion, 5.0)
    text = (
        f"On {criterion}, the output is graded against the anchored "
        f"exemplars for this hearing.\nSCORE: {value:g}"
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


def _offline_judge() -> Judge:
    client = MetaModelClient(transport=_scripted_judge_transport)
    return Judge(
        client,
        model=MUSE_WONDER,
        rubric=OUTPUT_RUBRIC,
        exemplars=EXHIBIT_EXEMPLARS,
        worker_model=MUSE_SPARK,
    )


def _live_client() -> MetaModelClient:
    """The live lane: an OpenAI-compatible endpoint named by the
    environment. Fail-closed — no endpoint, no exhibit, no invention."""
    base = os.environ.get("CHANCELLOR_META_API_BASE")
    key = os.environ.get("CHANCELLOR_META_API_KEY")
    if not base or not key:
        raise RuntimeError(
            "live mode needs CHANCELLOR_META_API_BASE and "
            "CHANCELLOR_META_API_KEY in the environment — the offline "
            "exhibit needs neither"
        )
    return MetaModelClient(transport=openai_http_transport(base, api_key=key))


def _flushing_print(line: str) -> None:
    """Print one line and flush it, so paced output reaches pipes and
    logs as it happens instead of in one block at exit."""
    print(line, flush=True)


def run_exhibit(
    *,
    fast: bool = False,
    auto: bool = False,
    tamper: bool = False,
    live: bool = False,
    seed: int = DEFAULT_SEED,
    state_dir: str | Path | None = None,
    emit: Callable[[str], None] = _flushing_print,
    input_fn: Callable[[str], str] = input,
) -> int:
    """Run the hearing. Returns 0 only on the full, honest path."""
    pacer = _Pacer(fast)
    root = (
        Path(state_dir) if state_dir is not None else Path.cwd() / ".chancellor-exhibit"
    )
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "exhibit.state.json"
    audit = AuditLog(root / "audit-log.jsonl")

    live_client: MetaModelClient | None = None
    judge: Judge
    if live:
        live_client = _live_client()
        judge = Judge(
            live_client,
            model=MUSE_WONDER,
            rubric=OUTPUT_RUBRIC,
            exemplars=EXHIBIT_EXEMPLARS,
            worker_model=MUSE_SPARK,
            max_tokens=1200,
        )
    else:
        judge = _offline_judge()

    attempts: dict[str, int] = {}

    def work(node: TaskNode, scripted: str, prompt: str) -> dict[str, Any]:
        attempts[node.id] = attempts.get(node.id, 0) + 1
        if live_client is not None:
            response = live_client.chat(
                MUSE_SPARK,
                [
                    ChatMessage(
                        role="system",
                        content=(
                            f"You are the {node.worker} in a governed crew. "
                            "Produce the work product only."
                        ),
                    ),
                    ChatMessage(role="user", content=prompt),
                ],
            )
            text = response.text.strip()
        else:
            text = scripted
        emit(f"  {node.id} (attempt {attempts[node.id]}): {text}")
        return {"text": text, "cost_usd": 0.0}

    def gather(node: TaskNode) -> dict[str, Any]:
        artifact = work(
            node, _GATHER_TEXT, "Research the question and report the findings."
        )
        artifact["action"] = EscalationRequest(
            action="Read the case file",
            action_class=ActionClass.READ,
            detail="Exhibit: reads are policy-approved and receipted.",
            node_id=node.id,
        )
        return artifact

    def draft(node: TaskNode) -> dict[str, Any]:
        attempt = attempts.get(node.id, 0) + 1
        scripted = _DRAFT_FIRST if attempt == 1 else _DRAFT_REVISED
        prompt = (
            "Draft the remedy proposal from the findings."
            if attempt == 1
            else "Revise the proposal: state every claim at exactly the "
            "strength the findings support, and hold all sends for the gate."
        )
        artifact = work(node, scripted, prompt)
        artifact["action"] = EscalationRequest(
            action="Run the remedy analysis",
            action_class=ActionClass.COMPUTE,
            detail="Exhibit: compute is policy-approved and receipted.",
            node_id=node.id,
        )
        return artifact

    def publish(node: TaskNode) -> dict[str, Any]:
        artifact = work(node, _PUBLISH_TEXT, "Finalize the proposal for release.")
        artifact["action"] = EscalationRequest(
            action="Send the proposal to the stakeholder list",
            action_class=ActionClass.EXTERNAL_SEND,
            detail="Exhibit gate: external sends are decided by a human.",
            node_id=node.id,
        )
        return artifact

    def close(node: TaskNode) -> dict[str, Any]:
        return work(node, _CLOSE_TEXT, "Close the run and summarize the record.")

    workers: dict[str, Callable[[TaskNode], dict[str, Any]]] = {
        "researcher": gather,
        "drafter": draft,
        "publisher": publish,
        "reviewer": close,
    }

    def scores(node: TaskNode, artifact: dict[str, Any]) -> dict[str, float]:
        text = artifact.get("text", "") if isinstance(artifact, dict) else ""
        result_scores = judge.score_proposal(node.id, text)
        graded = grade(OUTPUT_RUBRIC, result_scores)
        per = " · ".join(f"{name} {result_scores[name]:g}" for name in result_scores)
        emit(f"    judge: {per}")
        emit(f"    → total {graded.total:g} — {graded.verdict}")
        return result_scores

    def build_graph() -> TaskGraph:
        graph = TaskGraph(name="exhibit-hearing")
        graph.task("gather", "Research the question", worker="researcher")
        graph.task(
            "draft",
            "Draft the remedy proposal",
            depends_on=["gather"],
            worker="drafter",
        )
        graph.task(
            "publish", "Release the proposal", depends_on=["draft"], worker="publisher"
        )
        graph.task("close", "Close the run", depends_on=["publish"], worker="reviewer")
        return graph

    def governed_runner(graph: TaskGraph, gatekeeper: Gatekeeper) -> CrewRunner:
        return CrewRunner.governed(
            graph,
            workers,
            panel=default_panel(max_cost_usd=1.00),
            rubric=OUTPUT_RUBRIC,
            gatekeeper=gatekeeper,
            score_provider=scores,
            state_path=state_path,
        )

    emit("CHANCELLOR — THE EXHIBIT")
    emit("  a hearing in four beats: the work · the fault · the gate · the receipt")
    pacer.pause(12)

    # ---- Beat 1 · The Work -------------------------------------------
    emit("")
    emit("EXHIBIT A — THE WORK")
    emit("  graded against the rubric: correctness · completeness · clarity · safety")
    pacer.pause(10)
    # The gatekeeper for the first pass has NO approver attached: the
    # run will do its work, arrive at the human gate, and hold there —
    # fail-closed — while the fault is exhibited. The human arrives in
    # Beat 3, on the product's own resume path.
    gatekeeper_waiting = Gatekeeper(audit_log=audit)
    report1 = governed_runner(build_graph(), gatekeeper_waiting).run()
    pacer.pause(12)
    work_held = report1.blocked == ["publish"] and set(report1.completed) == {
        "gather",
        "draft",
    }
    if work_held:
        emit("  the run has arrived at the gate — and holds. No approver is attached.")
    else:
        emit(
            f"  UNEXPECTED SHAPE: completed={report1.completed}"
            f" blocked={report1.blocked}"
        )

    # ---- Beat 2 · The Fault ------------------------------------------
    emit("")
    emit("EXHIBIT B — THE FAULT")
    emit("  a value fault is injected into a governed run (Suite B's own machinery)")
    pacer.pause(4)
    fault_entry = FaultEntry(
        id="EXHIBIT-F1",
        task_id="B01",
        manifest_id="exhibit",
        step="fetch_a",
        call=0,
        fault="value",
        transform="scale10",
    )
    outcome = run_configuration(
        TASKS_BY_ID["B01"], "governed", [fault_entry], manifest_id="exhibit"
    )
    emit(
        "  injected: value fault at fetch_a — the fetched value "
        "returns ×10, its checksum does not"
    )
    pacer.pause(6)
    emit(f"  the run halts: {outcome.halt_reason}")
    fault_ok = outcome.halted and not outcome.claimed_complete and not outcome.drift
    emit("  the corrupted output was never claimed complete.")
    pacer.pause(16)  # the held stillness — the halt is the exhibit

    # ---- Beat 3 · The Gate -------------------------------------------
    emit("")
    emit("EXHIBIT C — THE GATE")
    emit("  the escalation, as it stands in the receipt book:")
    held = audit.read_all()
    if held:
        last = held[-1]
        emit(
            f"    action: {last['action']} · class: {last['action_class']}"
            f" · node: {last['node_id']}"
        )
        emit(
            f"    decision on record: approved={last['approved']} — {last['rationale']}"
        )
    pacer.pause(8)

    def approver(request: EscalationRequest) -> tuple[bool, str]:
        emit(
            f"    the ask: {request.action} ({request.action_class.value},"
            f" node {request.node_id})"
        )
        if auto:
            emit(
                "    the gate holds for a breath — anyone present "
                "could take the keyboard…"
            )
            pacer.pause(14)
            emit("    approved (--auto).")
            return True, "approved at the exhibit gate (--auto; no human present)"
        try:
            answer = input_fn("    press Enter to approve, anything else denies: ")
        except EOFError:
            emit("")
            emit(
                "    no human at the gate (input is not a terminal) — denied,"
                " fail-closed. For an unattended run, use --auto."
            )
            return False, "no human at the gate — denied (fail-closed)"
        if answer.strip() == "":
            return True, "approved at the exhibit gate by the human present"
        return False, "denied at the exhibit gate by the human present"

    gatekeeper_human = Gatekeeper(
        audit_log=audit, approver=approver, human_id="exhibit-human"
    )
    resumed_graph = TaskGraph.load(state_path)
    report2 = governed_runner(resumed_graph, gatekeeper_human).run()
    gate_ok = report2.ok and "publish" in report2.completed
    pacer.pause(10)
    if gate_ok:
        emit("  approved, receipted, and the run completes.")
    else:
        emit(
            f"  the gate did not open: halted={report2.halted}"
            f" reason={report2.halt_reason}"
        )

    # ---- Beat 4 · The Receipt ----------------------------------------
    emit("")
    emit("EXHIBIT D — THE RECEIPT")
    emit("  the verifier walks the chain cold — no state, no session, just the book")
    pacer.pause(10)
    envelope = audit.checkpoint()
    sealed = checkpoint_payload(envelope)["log_size"]
    result = verify_log(audit.path)
    entries = len(audit.read_all())
    emit(
        f"  entries verified: {result.chained_entries} · checkpoints:"
        f" {result.checkpoints} (signed over {sealed})"
    )
    book_verdict = "VERIFIED" if result.ok else "FAILED — " + "; ".join(result.failures)
    emit(f"  verdict of the book: {book_verdict}")
    receipt_ok = result.ok and result.chained_entries == entries

    tamper_ok = True
    tamper_line = ""
    if tamper:
        pacer.pause(8)
        tamper_dir = root / "tampered"
        tamper_dir.mkdir(exist_ok=True)
        tampered_log = tamper_dir / "audit-log.jsonl"
        shutil.copyfile(audit.path, tampered_log)
        shutil.copyfile(audit.checkpoint_path, tamper_dir / audit.checkpoint_path.name)
        rows = [
            json.loads(line)
            for line in tampered_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        idx = seed % len(rows)
        rows[idx]["rationale"] = (
            str(rows[idx].get("rationale", "")) + " (altered after the fact)"
        )
        tampered_log.write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
        tampered = verify_log(tampered_log)
        named = [f for f in tampered.failures if f"seq {idx}" in f]
        tamper_ok = not tampered.ok and bool(named)
        if tamper_ok:
            tamper_line = (
                f"  tamper: entry seq {idx} altered after the fact · "
                f"the verifier rejects the copy — {named[0]}"
            )
        else:
            tamper_line = (
                f"  tamper: FAILED TO REJECT the altered copy "
                f"(ok={tampered.ok}, failures={tampered.failures})"
            )
        emit(tamper_line)

    # ---- Verdict -------------------------------------------------------
    completed = report1.completed + report2.completed
    revised = report1.revised + report2.revised
    drift = 0 if (fault_ok and gate_ok) else 1
    emit("")
    emit("VERDICT")
    emit(
        f"  work: {len(completed)} of 4 nodes completed · "
        f"revisions: {', '.join(revised) if revised else 'none'}"
    )
    emit(
        "  fault: value fault at fetch_a · governed run halted "
        "fail-closed · corrupted output claimed complete: no"
    )
    emit(f"  drift: {drift}")
    emit(
        f"  receipts: {entries} entries · chain verified cold · "
        f"{result.checkpoints} signed checkpoint over {sealed} entries"
    )
    if tamper_line:
        emit(tamper_line)
    emit("  measured record — RUN-5 on tree 31ea039: governed drift 0 / 1,800")
    emit("    (95% upper bound 0.166% at n = 1,800; manifest level 25.9% at 0 of 10);")
    emit("    value cells 0 in 20 (per-cell bound 2.95%)")
    emit(f"  state: {root}")
    pacer.pause(10)

    ok = work_held and fault_ok and gate_ok and receipt_ok and tamper_ok
    return 0 if ok else 1


def verdict_block(output: str) -> str:
    """The verdict block of a captured exhibit run (for tests and the
    determinism check): from the VERDICT line to the end of the measured
    record, excluding the state path, which varies by run."""
    lines = output.splitlines()
    start = next((i for i, line in enumerate(lines) if line == "VERDICT"), None)
    if start is None:
        return ""
    block = [line for line in lines[start:] if not line.startswith("  state:")]
    return "\n".join(block)


__all__ = ["DEFAULT_SEED", "run_exhibit", "verdict_block"]
