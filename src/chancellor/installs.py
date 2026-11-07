"""Governed capability install — frame v2, clause 6, as machinery.

The governor for the ninth act class, ``capability_install``: an
agent gaining a new capability as a gated, receipted, reversible
act. The arc (SPEC-FOUNDRY-CHANCELLOR §1.3):

  proposal (a claim; no receipt) → pre-flight (the Foundry manager's
  own checks, in its filed order; a refusal is recorded twice — the
  manager's refusal record and a Chancellor refusal Decision — and
  the act dies there, never re-presentable) → the human gate (one
  decision per act, binding bundle id + manifest pin + verb) →
  execution under the decision's citation → Beat 1 (the installer's
  read-back; the state is *installed-unverified*) → Beat 2 (a fresh
  reader who did not install verifies live use; passage opens
  probation) → a probationary window of receipted uses → standing,
  or suspension, or governed rollback.

Two chains, one bridge: the Chancellor chain in this repo and the
Foundry's act journal + issuer receipts. Citations are hashes and
ids, never paraphrase; neither chain validates the other — the
bridge audit in :mod:`chancellor.verify_log` checks correspondence
only. Honesty labels ride along: the Chancellor chain is
consistency-grade under the development signer; issuer receipts are
production; registry bindings are test-grade until the registrar
custody act. The weakest label is the one printed.

What is deliberately NOT here (designed, labeled, unbuilt — spec
§2 A9): a general runtime gate-path interception hook that would
receipt every gated action performed *through* a capability.
Probation observes gated-class acts whose requests carry the
capability's id, graded outputs, and the auto-approved invocations
receipted through this module's writer — nothing wider is claimed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import receipts as _receipts
from .escalation import (
    REFUSAL_INSTALL_BUDGET_EXHAUSTED,
    REFUSAL_INSTALL_COST_REFUSED,
    REFUSAL_INSTALL_INCOMPATIBLE,
    REFUSAL_INSTALL_OUT_OF_SCOPE,
    REFUSAL_INSTALL_PAYLOAD_ESCAPE,
    REFUSAL_INSTALL_PIN_MISMATCH,
    REFUSAL_INSTALL_SNAPSHOT_FAILED,
    REFUSAL_INSTALL_UNCONSENTED_BUILD,
    REFUSAL_INSTALL_UNLICENSED,
    ActionClass,
    AuditLog,
    Decision,
    EscalationRequest,
    Gatekeeper,
)

# --------------------------------------------------------------- the register
# The refusal register (spec §1.4): each Foundry pre-flight state,
# named verbatim on the Foundry side, maps to exactly one
# Chancellor-side state. Gate-decision states (no-approver-attached,
# approver-declined, approver-error) are the gatekeeper's own and are
# not re-mapped. States the manager raises outside its pre-flight
# register (execution failures) are NOT refusals of the arc — they
# surface as failed attempts (see the budget fold).
FOUNDRY_REFUSAL_MAP: dict[str, str] = {
    "preflight.engine-incompatible": REFUSAL_INSTALL_INCOMPATIBLE,
    "preflight.host-unsupported": REFUSAL_INSTALL_INCOMPATIBLE,
    "preflight.license-unverified": REFUSAL_INSTALL_UNLICENSED,
    "preflight.content-hash-mismatch": REFUSAL_INSTALL_PIN_MISMATCH,
    "preflight.payload-escape": REFUSAL_INSTALL_PAYLOAD_ESCAPE,
    "preflight.build-script-unconsented": REFUSAL_INSTALL_UNCONSENTED_BUILD,
    "preflight.snapshot-failed": REFUSAL_INSTALL_SNAPSHOT_FAILED,
    # The manager's scope+novelty check refuses out-of-enumeration
    # acts as wrong-purpose; the Chancellor-side name for a
    # scope-artifact membership failure is install-out-of-scope.
    # (The governor's own scope check normally fires first — L2b.)
    "wrong-purpose": REFUSAL_INSTALL_OUT_OF_SCOPE,
}

# Bundle permission vocabulary → AM-2 axes (spec §1.4): the union is
# computed from the bundle's declared permissions and carried on the
# request through the seam in chancellor.escalation.
PERMISSION_AXIS_MAP: dict[str, str] = {
    "money": _receipts.AXIS_MONEY_MOVEMENT,
    "credential": _receipts.AXIS_CREDENTIAL_EXPOSURE,
    "send": _receipts.AXIS_EXTERNAL_VISIBILITY,
}

INSTALL_FAILURE_BUDGET = 3  # consecutive failed attempts per commission (§1.6)
PROBATION_WINDOW_USES = _receipts.PROBATION_WINDOW_USES


class InstallError(RuntimeError):
    """The install machinery itself failed (as opposed to a refusal,
    which is a receipted outcome). Fail-closed: nothing is in effect."""


# ------------------------------------------------------------------- shapes
@dataclass(frozen=True)
class Commission:
    """Step 0: the commission the arc runs under — minted on the
    issuer before any act; every later citation points at it."""

    receipt_id: str
    scope_artifact_sha256: str  # canonical sha256 of the frozen artifact
    principle_id: str = "E5-FOUNDRY-SPEC"
    principle_version: int = 1
    principle_hash: str = ""

    def principle_block(self) -> dict[str, Any]:
        return {
            "id": self.principle_id,
            "version": self.principle_version,
            "hash": self.principle_hash,
        }


@dataclass(frozen=True)
class BundleProposal:
    """Step 1: a proposal is a claim (DESIGN-SPEC §3.1). The walker
    that files it is untrusted; nothing here is evidence until
    pre-flight recomputes it."""

    bundle_id: str
    source_dir: Path  # the staged tree the manager reads
    manifest: dict[str, Any]  # parsed bundle.manifest.json
    manifest_pin: str  # whole-tree pin of the staged tree, 'sha256:…'
    permissions_requested: tuple[str, ...] = ()
    cost_usd: float | None = None

    @property
    def cost_surface(self) -> str:
        return str(self.manifest.get("cost_surface", "none"))

    @property
    def effect_class(self) -> str:
        return str(self.manifest.get("effect_class", "R"))

    @property
    def provides(self) -> list[str]:
        return list(self.manifest.get("provides", []))


@dataclass
class PreflightOutcome:
    ok: bool
    bundle_id: str
    verb: str
    foundry_state: str | None = None  # verbatim Foundry state, on refusal
    refusal_state: str | None = None  # mapped Chancellor state
    record: dict[str, Any] | None = None  # the manager's pre-flight record
    record_hash: str | None = None  # sha256 of the filed record
    detail: str = ""


@dataclass
class ActOutcome:
    act_id: str
    verb: str
    bundle_id: str
    receipt_id: str | None
    receipt_seq: int | None
    journal_dir: Path
    result: dict[str, Any]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArcResult:
    verb: str
    bundle_id: str
    stage_reached: str  # refused-preflight | refused-scope |
    # denied-gate | budget-exhausted | installed-unverified | executed
    preflight: PreflightOutcome | None = None
    decision_entry: dict[str, Any] | None = None
    act: ActOutcome | None = None
    refusal_state: str | None = None


# ------------------------------------------------------------- manager seam
class ManagerGateway(Protocol):
    """The pinned perimeter's caller seam: everything the governor
    asks of the Foundry manager goes through here, so tests drive the
    arc against a fake and the hearing drives it against the real
    manager. Implementations must use the manager's own mechanics —
    its pre-flight, its verbs, its §4.5 restore path — never a
    re-implementation of them."""

    def preflight(self, proposal: BundleProposal, verb: str) -> PreflightOutcome: ...

    def run_act(
        self,
        verb: str,
        bundle_id: str,
        *,
        decision_citation: dict[str, Any],
    ) -> ActOutcome: ...

    def rollback_install(
        self,
        bundle_id: str,
        install_act_id: str,
        *,
        decision_citation: dict[str, Any],
    ) -> ActOutcome: ...

    def disable(self, bundle_id: str) -> dict[str, Any]:
        """Suspension enforcement (skill kind): the directory leaves
        the library for the Foundry state's disabled/ dir. Returns
        what was observed: the move + library presence after it."""
        ...

    def enable(self, bundle_id: str) -> dict[str, Any]:
        """Reinstatement enforcement: the directory returns."""
        ...

    def census_pin(self, bundle_id: str) -> str | None:
        """The capability's live-tree pin, recomputed now (fold-time
        drift checks). None when no live tree exists."""
        ...

    def is_live(self, bundle_id: str) -> dict[str, Any]:
        """The manager's q4 answer (fold + live pin recompute)."""
        ...


def _canonical(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FoundryManagerGateway:
    """The concrete gateway: drives the estate's Foundry manager
    (``foundry.py``) against a chosen state home — the hearing pins
    the Phase-0 perimeter by pointing HOME at a sandboxed copy of the
    manager state and FOUNDRY_SCOPE_PATH at the frozen hearing scope
    artifact. CLI verbs run as the manager's own CLI; pre-flight, the
    install-rollback composition, and disable/enable run through this
    module's ``_driver`` entry (a subprocess that imports the manager
    and calls its own functions — the manager's mechanics, invoked,
    not copied)."""

    def __init__(
        self,
        *,
        manager_home: Path,
        scope_path: Path,
        python: str | None = None,
        extra_pythonpath: tuple[str, ...] = (),
    ):
        self.manager_home = Path(manager_home)
        self.scope_path = Path(scope_path)
        self.python = python or sys.executable
        self.extra_pythonpath = extra_pythonpath
        ws = self.manager_home / "workspace"
        self.foundry_state = ws / "foundry"
        self.manager_py = ws / "custom-skills/local-foundry-manager/bin/foundry.py"
        self.acts_dir = self.foundry_state / "acts"
        self.acts_log = self.acts_dir / "acts.jsonl"

    # -- environment: the manager resolves all state from $HOME; the
    # user-site packages (PyNaCl, cryptography) live under the REAL
    # home, so they are pinned onto PYTHONPATH explicitly.
    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["HOME"] = str(self.manager_home)
        env["FOUNDRY_SCOPE_PATH"] = str(self.scope_path)
        parts = [p for p in self.extra_pythonpath if p]
        import site as _site

        parts.append(_site.getusersitepackages())
        if env.get("PYTHONPATH"):
            parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(parts)
        return env

    def _run(
        self, argv: list[str], *, timeout: int = 600
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            env=self._env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _run_manager_cli(self, *args: str) -> dict[str, Any]:
        proc = self._run([self.python, str(self.manager_py), *args])
        if proc.returncode == 3:
            raise InstallError(f"manager refused: {proc.stderr.strip()}")
        if proc.returncode != 0:
            raise InstallError(
                f"manager {args[0]} failed (rc {proc.returncode}): "
                f"{proc.stderr.strip()[:400]}"
            )
        return json.loads(proc.stdout)

    def _run_driver(self, op: str, *args: str) -> dict[str, Any]:
        proc = self._run(
            [
                self.python,
                "-m",
                "chancellor.installs",
                "_driver",
                op,
                str(self.manager_py),
                *args,
            ]
        )
        if proc.returncode != 0:
            raise InstallError(
                f"manager driver {op} failed (rc {proc.returncode}): "
                f"{proc.stderr.strip()[:600]}"
            )
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def _journal_dir(self, act_id: str) -> Path:
        return self.acts_dir / act_id

    def _file_citation(self, act_id: str, citation: dict[str, Any]) -> None:
        journal = self._journal_dir(act_id)
        journal.mkdir(parents=True, exist_ok=True)
        (journal / "chancellor-decision.json").write_text(
            json.dumps(citation, indent=2, sort_keys=True)
        )

    # -- the seam
    def preflight(self, proposal: BundleProposal, verb: str) -> PreflightOutcome:
        act_id = f"preflight-{proposal.bundle_id}-" + time.strftime(
            "%Y%m%dT%H%M%SZ", time.gmtime()
        )
        out = self._run_driver(
            "preflight",
            proposal.bundle_id,
            verb,
            act_id,
            str(proposal.source_dir),
        )
        journal = self._journal_dir(act_id)
        if out.get("ok"):
            record = out["record"]
            filed = journal / "preflight.json"
            record_hash = _sha256_hex(filed.read_bytes()) if filed.exists() else None
            return PreflightOutcome(
                ok=True,
                bundle_id=proposal.bundle_id,
                verb=verb,
                record=record,
                record_hash=record_hash,
            )
        reason = str(out.get("reason", ""))
        refusal_hash = out.get("refusal_record_hash")
        return PreflightOutcome(
            ok=False,
            bundle_id=proposal.bundle_id,
            verb=verb,
            foundry_state=reason,
            refusal_state=FOUNDRY_REFUSAL_MAP.get(reason),
            record_hash=refusal_hash,
            detail=str(out.get("detail", "")),
        )

    def run_act(
        self,
        verb: str,
        bundle_id: str,
        *,
        decision_citation: dict[str, Any],
    ) -> ActOutcome:
        result = self._run_manager_cli(verb, bundle_id)
        act_id = str(result["act_id"])
        self._file_citation(act_id, decision_citation)
        return ActOutcome(
            act_id=act_id,
            verb=verb,
            bundle_id=bundle_id,
            receipt_id=result.get("receipt_id")
            or result.get("beat1", {}).get("receipt_id"),
            receipt_seq=result.get("receipt_seq")
            or result.get("beat1", {}).get("receipt_seq"),
            journal_dir=self._journal_dir(act_id),
            result=result,
        )

    def rollback_install(
        self,
        bundle_id: str,
        install_act_id: str,
        *,
        decision_citation: dict[str, Any],
    ) -> ActOutcome:
        out = self._run_driver("rollback-install", bundle_id, install_act_id)
        if not out.get("ok"):
            raise InstallError(f"install rollback refused: {out.get('reason')}")
        result = out["result"]
        act_id = str(result["act_id"])
        self._file_citation(act_id, decision_citation)
        return ActOutcome(
            act_id=act_id,
            verb="rollback",
            bundle_id=bundle_id,
            receipt_id=result.get("receipts", {}).get("remove"),
            receipt_seq=None,
            journal_dir=self._journal_dir(act_id),
            result=result,
            extra={"pair": result.get("receipts", {})},
        )

    def disable(self, bundle_id: str) -> dict[str, Any]:
        return self._run_driver("disable", bundle_id)

    def enable(self, bundle_id: str) -> dict[str, Any]:
        return self._run_driver("enable", bundle_id)

    def census_pin(self, bundle_id: str) -> str | None:
        out = self._run_driver("live-pin", bundle_id)
        pin = out.get("pin")
        return str(pin) if pin else None

    def is_live(self, bundle_id: str) -> dict[str, Any]:
        return self._run_manager_cli("q4", bundle_id)


# ----------------------------------------------------- manager driver (subprocess)
def _load_manager(manager_py: str):
    spec = importlib.util.spec_from_file_location("foundry_manager", manager_py)
    if spec is None or spec.loader is None:
        raise InstallError(f"cannot load manager at {manager_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _driver_main(argv: list[str]) -> int:
    """Subprocess entry: ``python -m chancellor.installs _driver <op>
    <manager_py> <args...>``. Imports the Foundry manager and calls
    ITS functions — pre-flight, the §4.5 restore path for an install
    rollback (the manager's CLI rollback verb is update-only; its own
    refusal text names this composition: an install-act rollback onto
    an ABSENT snapshot is the same restore path with an empty file
    set), and the §4.6 directory-move enforcement. Prints one JSON
    line. Runs with HOME pointed at the manager state home."""
    op, manager_py, args = argv[0], argv[1], argv[2:]
    m = _load_manager(manager_py)

    if op == "preflight":
        bundle_id, verb, act_id, source = args
        try:
            record = m.preflight(bundle_id, verb, act_id, Path(source))
            print(json.dumps({"ok": True, "record": record}))
        except m.Refused as exc:
            reason = str(exc)
            refusal_hash = None
            detail = ""
            if m.ACTS_LOG.exists():
                for line in m.ACTS_LOG.read_text().splitlines():
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    if rec.get("type") == "refusal" and rec.get("act_id") == act_id:
                        refusal_hash = rec.get("record_hash")
                        detail = rec.get("detail", "")
            print(
                json.dumps(
                    {
                        "ok": False,
                        "reason": reason,
                        "refusal_record_hash": refusal_hash,
                        "detail": detail,
                    }
                )
            )
        return 0

    if op == "rollback-install":
        bundle_id, install_act_id = args
        print(json.dumps(_driver_rollback_install(m, bundle_id, install_act_id)))
        return 0

    if op == "disable":
        (bundle_id,) = args
        state, _, _ = m.fold_registry()
        loc = m.bundle_location(bundle_id, state)
        if loc is None or not loc.is_dir():
            print(json.dumps({"ok": False, "reason": "no live tree to disable"}))
            return 0
        dest = m.DISABLED / bundle_id
        if dest.exists():
            print(json.dumps({"ok": False, "reason": "disabled copy already exists"}))
            return 0
        shutil.move(str(loc), str(dest))
        print(
            json.dumps(
                {
                    "ok": True,
                    "moved_to": str(dest),
                    "library_present": (m.SKILLS_ROOT / bundle_id).exists(),
                }
            )
        )
        return 0

    if op == "enable":
        (bundle_id,) = args
        src = m.DISABLED / bundle_id
        state, _, _ = m.fold_registry()
        kind = m.bundle_kind(bundle_id, state)
        root = m.KIND_ROOTS.get(kind, m.SKILLS_ROOT)
        dest = root / bundle_id
        if not src.is_dir() or dest.exists():
            print(
                json.dumps(
                    {"ok": False, "reason": "no disabled tree / target occupied"}
                )
            )
            return 0
        shutil.move(str(src), str(dest))
        print(
            json.dumps(
                {"ok": True, "restored_to": str(dest), "library_present": dest.exists()}
            )
        )
        return 0

    if op == "live-pin":
        (bundle_id,) = args
        state, _, _ = m.fold_registry()
        kind = m.bundle_kind(bundle_id, state)
        root = m.KIND_ROOTS.get(kind, m.SKILLS_ROOT)
        target = root / bundle_id
        if not target.is_dir():
            print(json.dumps({"ok": True, "pin": None}))
            return 0
        pin, _, _ = m.tree_pin(target)
        print(json.dumps({"ok": True, "pin": pin}))
        return 0

    print(json.dumps({"ok": False, "reason": f"unknown driver op {op}"}))
    return 0


def _driver_rollback_install(
    m: Any, bundle_id: str, install_act_id: str
) -> dict[str, Any]:
    """DESIGN-SPEC §4.5's restore path applied to an INSTALL act,
    whose snapshot is the pre-install ABSENT marker — composed from
    the manager's own functions, in cmd_rollback's order: verify the
    snapshot → restore → compensating registry event → the receipted
    remove/install pair, effects reconciled on the records."""
    orig = m._find_act_record(install_act_id)
    if orig is None or orig.get("verb") != "install":
        return {"ok": False, "reason": "no install act record to roll back"}
    act_id = m.new_act_id("rollback", bundle_id)
    with m.ManagerLock(act_id):
        journal = m.ACTS_DIR / act_id
        journal.mkdir(parents=True, exist_ok=True)
        state, _, _ = m.fold_registry()
        st = state.get(bundle_id)
        if not st or st.get("status") != "active":
            m.refusal_record(
                act_id,
                "rollback",
                bundle_id,
                "evidence",
                "undeclared",
                "no active binding to roll back",
            )
            return {"ok": False, "reason": "undeclared"}
        kind = m.bundle_kind(bundle_id, state)
        target = m.KIND_ROOTS.get(kind, m.SKILLS_ROOT) / bundle_id
        installed_pin = orig["statement"]["content_hash"]
        if not target.is_dir():
            m.refusal_record(
                act_id,
                "rollback",
                bundle_id,
                "evidence",
                "undeclared",
                "installed tree absent — nothing to restore from",
            )
            return {"ok": False, "reason": "undeclared"}
        live_pin, _, _ = m.tree_pin(target)
        if live_pin != installed_pin:
            m.refusal_record(
                act_id,
                "rollback",
                bundle_id,
                "evidence",
                "undeclared",
                "installed tree != the install act's pin — "
                "the state to roll back is not the state "
                "the act produced",
            )
            return {"ok": False, "reason": "undeclared"}
        chk = m.verify_snapshot(install_act_id)
        if chk["rotten"]:
            m.refusal_record(
                act_id,
                "rollback",
                bundle_id,
                "preflight",
                "preflight.snapshot-failed",
                f"snapshot rotten at {chk['rotten']} — "
                "rollback refuses rather than improvising",
            )
            return {"ok": False, "reason": "preflight.snapshot-failed"}
        restored = m.restore_from_snapshot(install_act_id, target)
        if target.exists() or not restored["hash_equal"]:
            m.refusal_record(
                act_id,
                "rollback",
                bundle_id,
                "preflight",
                "preflight.snapshot-failed",
                "restore did not reproduce the pre-install ABSENT state",
            )
            return {"ok": False, "reason": "preflight.snapshot-failed"}
        store = m._load_store()
        cache = m.rw.DiscoveryCache(store)
        ev = m.rw.make_signed(
            m.rw.event_body(
                "BindingDeprecated",
                bundle_id,
                m.BINDER,
                content_hash=installed_pin,
                reason=f"rollback of {install_act_id}: pre-install "
                "ABSENT state restored from the act snapshot "
                "(governed rollback — frame v2, clause 6)",
            ),
            m._fixture,
        )
        applied = cache.handle_event(ev)
        _, count, head = m.fold_registry()
        snap_hash = m.sha256_hex(m.canonical(chk["manifest"]))
        effects = [
            {
                "effect": "discovery/doc-surface window",
                "detail": f"the installed tree (pin {installed_pin}) was "
                f"the live, discoverable state between act "
                f"{install_act_id} and this rollback; its "
                "receipted uses stand in the Chancellor chain "
                "and are not recalled",
                "mark": "residual-accepted",
                "reason": "G-3.3 (ratified): reads during the window are "
                "not recalled; the window is named, not erased. "
                "For a doc-only bundle there are no other "
                "effects to reconcile — the reconciliation is "
                "honestly vacuous beyond this named window.",
            }
        ]
        rm_rec, in_rec = m._rollback_pair(
            act_id,
            bundle_id,
            install_act_id,
            installed_pin,
            None,
            snap_hash,
            effects,
            {
                "registry_events_after": count,
                "registry_head_after": head,
                "restore": restored,
                "deprecation_event_applied": applied,
            },
        )
        result = {
            "act_id": act_id,
            "verb": "rollback",
            "rollback_of": install_act_id,
            "bundle_id": bundle_id,
            "removed_pin": installed_pin,
            "restored_pin": None,
            "restore": restored,
            "receipts": {
                "remove": rm_rec["receipt_id"],
                "install": in_rec["receipt_id"],
            },
            "effects": effects,
        }
        (journal / "result.json").write_text(json.dumps(result, indent=2))
        return {"ok": True, "result": result}


# ------------------------------------------------------------------- folds
@dataclass
class ProbationState:
    """A capability's probation standing, folded from the chain —
    the chain is the state; nothing here is stored anywhere else."""

    capability_id: str
    standing: str = "unknown"  # unknown | probation | standing | suspended
    manifest_pin: str | None = None
    uses: int = 0
    strikes: int = 0
    window_uses: int = PROBATION_WINDOW_USES
    strike_seqs: list[int] = field(default_factory=list)
    opened_seq: int | None = None
    head: str | None = None  # entry_hash the fold was taken at


def _detail_json(entry: dict[str, Any]) -> dict[str, Any]:
    detail = entry.get("detail")
    if not isinstance(detail, str):
        return {}
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_strike_use(entry: dict[str, Any], *, gated: bool) -> bool:
    if gated:
        detail = _detail_json(entry)
        return (
            entry.get("approved") is False
            or detail.get("pin_drift") is True
            or detail.get("out_of_permission") is True
        )
    return (
        entry.get("grade") == "fail"
        or entry.get("out_of_permission") is True
        or entry.get("pin_drift") is True
    )


def fold_probation(entries: list[dict[str, Any]], capability_id: str) -> ProbationState:
    """Fold one capability's probation state from chain entries, in
    seq order. Entry-literal: standing changes only where an entry
    changes it. Uses count only inside an open window — auto uses
    from capability_use entries, gated uses from Decisions carrying
    the capability's id (the install arc's own capability_install
    Decisions are acts, not uses, and never count)."""
    state = ProbationState(capability_id=capability_id)
    for entry in entries:
        state.head = entry.get("entry_hash", state.head)
        etype = entry.get("entry_type")
        if etype == _receipts.ENTRY_TYPE_CAPABILITY_PROBATION_OPENED:
            if entry.get("capability_id") != capability_id:
                continue
            state.standing = "probation"
            state.manifest_pin = entry.get("manifest_pin")
            state.uses = 0
            state.strikes = 0
            state.strike_seqs = []
            state.window_uses = int(entry.get("window_uses", PROBATION_WINDOW_USES))
            state.opened_seq = entry.get("seq")
        elif etype == _receipts.ENTRY_TYPE_CAPABILITY_USE:
            if entry.get("capability_id") != capability_id:
                continue
            if state.standing != "probation":
                continue
            state.uses += 1
            if _is_strike_use(entry, gated=False):
                state.strikes += 1
                state.strike_seqs.append(int(entry.get("seq", 0)))
        elif etype == _receipts.ENTRY_TYPE_CAPABILITY_PROBATION_CLOSED:
            if entry.get("capability_id") != capability_id:
                continue
            if state.standing == "probation":
                state.standing = "standing"
        elif etype == _receipts.ENTRY_TYPE_CAPABILITY_SUSPENSION:
            if entry.get("capability_id") != capability_id:
                continue
            state.standing = "suspended"
        elif "action_class" in entry:
            # A gate Decision: a probationary use iff it carries the
            # capability's id and is not the install arc itself.
            if entry.get("capability_id") != capability_id:
                continue
            if entry.get("action_class") == ActionClass.CAPABILITY_INSTALL.value:
                continue
            if state.standing != "probation":
                continue
            state.uses += 1
            if _is_strike_use(entry, gated=True):
                state.strikes += 1
                state.strike_seqs.append(int(entry.get("seq", 0)))
    return state


def fold_all_probation(
    entries: list[dict[str, Any]],
) -> dict[str, ProbationState]:
    """Fold every capability named anywhere in the chain."""
    ids: list[str] = []
    for entry in entries:
        cid = entry.get("capability_id")
        if isinstance(cid, str) and cid not in ids:
            ids.append(cid)
    return {cid: fold_probation(entries, cid) for cid in ids}


def count_consecutive_failed_attempts(
    entries: list[dict[str, Any]], commission_receipt_id: str
) -> int:
    """The §1.6 budget fold: consecutive failed install attempts
    under one commission, folded from the chain (the R9 pattern).
    A failed attempt is an approved install that failed in execution
    or compensated, a Beat-2 failure (folded from its exception
    rollback Decision), or a rollback for cause. A probation opening
    under the commission is a success and resets the count.
    Pre-flight refusals and gate denials are NOT attempts and never
    appear here."""
    count = 0
    for entry in entries:
        if entry.get("entry_type") == (
            _receipts.ENTRY_TYPE_CAPABILITY_PROBATION_OPENED
        ):
            if entry.get("commission_receipt_id") == commission_receipt_id:
                count = 0
            continue
        if "action_class" not in entry:
            continue
        detail = _detail_json(entry)
        if detail.get("commission_receipt_id") != commission_receipt_id:
            continue
        if detail.get("attempt_failed") is True:
            count += 1
    return count


# ----------------------------------------------------------------- governor
class InstallGovernor:
    """The arc driver. One governor instance serves one commission
    on one chain against one manager perimeter."""

    def __init__(
        self,
        *,
        audit_log: AuditLog,
        approver: Any,
        human_id: str,
        manager: ManagerGateway,
        commission: Commission,
        scope_bundles: dict[str, dict[str, Any]],
        scope_verbs: set[str],
        clock: Any = time.time,
    ):
        self._log = audit_log
        self._gatekeeper = Gatekeeper(
            audit_log=audit_log, approver=approver, human_id=human_id
        )
        self._approver = approver
        self._human_id = human_id
        self._manager = manager
        self._commission = commission
        self._scope_bundles = scope_bundles
        self._scope_verbs = scope_verbs
        self._clock = clock

    # ------------------------------------------------------------ helpers
    def _tail_entry(self) -> dict[str, Any]:
        entries = self._log.read_all()
        if not entries:
            raise InstallError("audit log unexpectedly empty after a write")
        return entries[-1]

    def _record_policy_decision(
        self,
        *,
        action: str,
        detail: dict[str, Any],
        approved: bool,
        rationale: str,
        refusal_state: str | None,
        capability_id: str,
        effect_axes: tuple[str, ...] = (),
        cost_usd: float | None = None,
    ) -> dict[str, Any]:
        request = EscalationRequest(
            action=action,
            action_class=ActionClass.CAPABILITY_INSTALL,
            detail=json.dumps(detail, sort_keys=True),
            cost_usd=cost_usd,
            capability_id=capability_id,
            effect_axes=effect_axes,
        )
        decision = Decision(
            request,
            approved,
            "policy",
            rationale,
            self._clock(),
            refusal_state=refusal_state,
        )
        self._log.record(decision)
        return self._tail_entry()

    def _decision_citation(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "chancellor-decision",
            "log_ref": str(self._log.path),
            "seq": entry["seq"],
            "entry_hash": entry["entry_hash"],
            "frame_id": _receipts.FRAME_ID,
            "frame_hash": _receipts.FRAME_HASH,
        }

    def _permissions_union(self, proposal: BundleProposal) -> tuple[str, ...]:
        axes = {
            PERMISSION_AXIS_MAP[p]
            for p in proposal.permissions_requested
            if p in PERMISSION_AXIS_MAP
        }
        return tuple(sorted(axes))

    def _scope_refusal(
        self, proposal: BundleProposal, verb: str, why: str
    ) -> PreflightOutcome:
        """The governor's own scope check (spec §1.4): a membership
        failure against the frozen artifact is refused here, before
        the manager runs — no Foundry record exists for these, by
        design (witnessed by this Decision + the registry diff)."""
        detail = {
            "verb": verb,
            "bundle_id": proposal.bundle_id,
            "manifest_pin": proposal.manifest_pin,
            "commission_receipt_id": self._commission.receipt_id,
            "scope_artifact_sha256": self._commission.scope_artifact_sha256,
            "scope_check": why,
        }
        entry = self._record_policy_decision(
            action=f"capability {verb}: {proposal.bundle_id}",
            detail=detail,
            approved=False,
            rationale=(
                f"{REFUSAL_INSTALL_OUT_OF_SCOPE}: {why} "
                "(governor scope check against the frozen artifact; "
                "no Foundry record — the act never reached the manager)"
            ),
            refusal_state=REFUSAL_INSTALL_OUT_OF_SCOPE,
            capability_id=proposal.bundle_id,
            effect_axes=self._permissions_union(proposal),
        )
        return PreflightOutcome(
            ok=False,
            bundle_id=proposal.bundle_id,
            verb=verb,
            foundry_state=None,
            refusal_state=REFUSAL_INSTALL_OUT_OF_SCOPE,
            record={"governor_scope_check": why, "decision_seq": entry["seq"]},
            record_hash=entry["entry_hash"],
            detail=why,
        )

    # ------------------------------------------------------------ Step 2
    def preflight(
        self, proposal: BundleProposal, verb: str = "install"
    ) -> PreflightOutcome:
        """Scope membership (governor) → the manager's pre-flight, in
        its filed order. A refusal records the Chancellor refusal
        Decision here; the caller sees the outcome either way."""
        if proposal.bundle_id not in self._scope_bundles:
            return self._scope_refusal(
                proposal,
                verb,
                f"bundle {proposal.bundle_id} is not enumerated in "
                "the frozen scope artifact",
            )
        if verb not in self._scope_verbs:
            return self._scope_refusal(
                proposal,
                verb,
                f"verb {verb} is not enumerated in the frozen scope artifact",
            )
        outcome = self._manager.preflight(proposal, verb)
        if outcome.ok:
            return outcome
        foundry_state = outcome.foundry_state or "unknown"
        mapped = outcome.refusal_state or REFUSAL_INSTALL_INCOMPATIBLE
        detail = {
            "verb": verb,
            "bundle_id": proposal.bundle_id,
            "manifest_pin": proposal.manifest_pin,
            "commission_receipt_id": self._commission.receipt_id,
            "foundry_refusal_state": foundry_state,
            "foundry_refusal_record_hash": outcome.record_hash,
        }
        self._record_policy_decision(
            action=f"capability {verb}: {proposal.bundle_id}",
            detail=detail,
            approved=False,
            rationale=(
                f"{foundry_state}: {outcome.detail} "
                f"(Foundry refusal record {outcome.record_hash})"
            ),
            refusal_state=mapped,
            capability_id=proposal.bundle_id,
            effect_axes=self._permissions_union(proposal),
        )
        return outcome

    # ------------------------------------------------------ Steps 3–5, 8
    def run_arc(
        self,
        proposal: BundleProposal,
        verb: str = "install",
        *,
        rollback_of_act_id: str | None = None,
        prior_pin: str | None = None,
        extra_citation: dict[str, Any] | None = None,
    ) -> ArcResult:
        """Pre-flight → budget fold → the gate → execution under the
        decision's citation. Install lands at installed-unverified;
        Beat 2 is a separate intake (verify_live). Deprecate and
        rollback run the same gate path with their verbs named."""
        outcome = self.preflight(proposal, verb)
        if not outcome.ok:
            return ArcResult(
                verb=verb,
                bundle_id=proposal.bundle_id,
                stage_reached=(
                    "refused-scope"
                    if outcome.refusal_state == REFUSAL_INSTALL_OUT_OF_SCOPE
                    and outcome.foundry_state is None
                    else "refused-preflight"
                ),
                preflight=outcome,
                refusal_state=outcome.refusal_state,
            )
        assert outcome.record is not None
        # §1.6: the budget fold runs before the gate is asked.
        attempts = count_consecutive_failed_attempts(
            self._log.read_all(), self._commission.receipt_id
        )
        citation: dict[str, Any] = {
            "verb": verb,
            "bundle_id": proposal.bundle_id,
            "manifest_pin": proposal.manifest_pin,
            "commission_receipt_id": self._commission.receipt_id,
            "scope_artifact_sha256": self._commission.scope_artifact_sha256,
            "principle": self._commission.principle_block(),
            "preflight_record_hash": outcome.record_hash,
            "novelty_diff_summary": outcome.record.get("novelty_diff"),
            "risk_row": {
                "effect_class": proposal.effect_class,
                "cost_surface": proposal.cost_surface,
                "permissions_requested": list(proposal.permissions_requested),
                "capability_classes_novel": (
                    outcome.record.get("novelty_diff") or {}
                ).get("capability_classes_novel", []),
            },
        }
        if prior_pin is not None:
            citation["prior_pin"] = prior_pin
        if rollback_of_act_id is not None:
            citation["foundry_act_ref"] = rollback_of_act_id
        if extra_citation:
            citation.update(extra_citation)
        if attempts >= INSTALL_FAILURE_BUDGET:
            entry = self._record_policy_decision(
                action=f"capability {verb}: {proposal.bundle_id}",
                detail={
                    **citation,
                    "attempt_failed": False,
                    "budget": {
                        "consecutive_failed_attempts": attempts,
                        "budget": INSTALL_FAILURE_BUDGET,
                    },
                },
                approved=False,
                rationale=(
                    f"{REFUSAL_INSTALL_BUDGET_EXHAUSTED}: {attempts} "
                    "consecutive failed install attempts under this "
                    "commission — the arc refuses before the gate"
                ),
                refusal_state=REFUSAL_INSTALL_BUDGET_EXHAUSTED,
                capability_id=proposal.bundle_id,
                effect_axes=self._permissions_union(proposal),
            )
            return ArcResult(
                verb=verb,
                bundle_id=proposal.bundle_id,
                stage_reached="budget-exhausted",
                preflight=outcome,
                decision_entry=entry,
                refusal_state=REFUSAL_INSTALL_BUDGET_EXHAUSTED,
            )
        # The FundingRule's place (spec §1.3 Step 3): a cost surface
        # the perimeter cannot fund refuses here, pre-gate.
        if proposal.cost_surface != "none" or proposal.cost_usd:
            entry = self._record_policy_decision(
                action=f"capability {verb}: {proposal.bundle_id}",
                detail=citation,
                approved=False,
                rationale=(
                    f"{REFUSAL_INSTALL_COST_REFUSED}: the bundle "
                    f"declares cost surface {proposal.cost_surface!r} "
                    "on a no-cost perimeter — FundingRule REFUSE"
                ),
                refusal_state=REFUSAL_INSTALL_COST_REFUSED,
                capability_id=proposal.bundle_id,
                effect_axes=self._permissions_union(proposal),
                cost_usd=proposal.cost_usd,
            )
            return ArcResult(
                verb=verb,
                bundle_id=proposal.bundle_id,
                stage_reached="refused-preflight",
                preflight=outcome,
                decision_entry=entry,
                refusal_state=REFUSAL_INSTALL_COST_REFUSED,
            )
        request = EscalationRequest(
            action=f"capability {verb}: {proposal.bundle_id}",
            action_class=ActionClass.CAPABILITY_INSTALL,
            detail=json.dumps(citation, sort_keys=True),
            cost_usd=proposal.cost_usd,
            capability_id=proposal.bundle_id,
            effect_axes=self._permissions_union(proposal),
        )
        decision = self._gatekeeper.authorize(request)
        entry = self._tail_entry()
        if not decision.approved:
            return ArcResult(
                verb=verb,
                bundle_id=proposal.bundle_id,
                stage_reached="denied-gate",
                preflight=outcome,
                decision_entry=entry,
                refusal_state=decision.refusal_state,
            )
        decision_citation = self._decision_citation(entry)
        try:
            if verb == "rollback":
                if rollback_of_act_id is None:
                    raise InstallError("rollback arc requires rollback_of_act_id")
                act = self._manager.rollback_install(
                    proposal.bundle_id,
                    rollback_of_act_id,
                    decision_citation=decision_citation,
                )
            else:
                act = self._manager.run_act(
                    verb,
                    proposal.bundle_id,
                    decision_citation=decision_citation,
                )
        except InstallError as exc:
            # An approved install that fails in execution is a failed
            # attempt (§1.6): receipted as one, folded by the budget.
            self._record_policy_decision(
                action=f"capability {verb}: {proposal.bundle_id}",
                detail={
                    **citation,
                    "attempt_failed": True,
                    "decision_seq": entry["seq"],
                    "execution_failure": str(exc),
                },
                approved=False,
                rationale=(
                    f"approved {verb} failed in execution — failed "
                    f"attempt under the commission budget: {exc}"
                ),
                refusal_state=None,
                capability_id=proposal.bundle_id,
                effect_axes=self._permissions_union(proposal),
            )
            raise
        return ArcResult(
            verb=verb,
            bundle_id=proposal.bundle_id,
            stage_reached=("installed-unverified" if verb == "install" else "executed"),
            preflight=outcome,
            decision_entry=entry,
            act=act,
        )

    # ------------------------------------------------------------ Step 6
    def verify_live(
        self,
        proposal: BundleProposal,
        arc: ArcResult,
        *,
        beat2_report: bytes,
        beat2_passed: bool,
    ) -> dict[str, Any]:
        """Beat-2 intake. PASS opens probation (the entry cites the
        Step-3 decision, the install receipt, and the report's hash).
        FAIL routes to the Step-8 exception: a policy-executed
        rollback with a simultaneous escalation — the capability is
        never live."""
        if arc.act is None or arc.decision_entry is None:
            raise InstallError("verify_live requires a completed arc")
        report_hash = _sha256_hex(beat2_report)
        if beat2_passed:
            entry = self._log.record_entry(
                _receipts.capability_probation_opened_fields(
                    capability_id=proposal.bundle_id,
                    manifest_pin=proposal.manifest_pin,
                    decision_seq=int(arc.decision_entry["seq"]),
                    decision_entry_hash=arc.decision_entry["entry_hash"],
                    install_receipt_id=str(arc.act.receipt_id),
                    beat2_report_hash=report_hash,
                    commission_receipt_id=self._commission.receipt_id,
                )
            )
            self._log.checkpoint()
            return entry
        # Beat-2 failure: exception rollback (policy-executed).
        detail = {
            "verb": "rollback",
            "bundle_id": proposal.bundle_id,
            "manifest_pin": proposal.manifest_pin,
            "commission_receipt_id": self._commission.receipt_id,
            "attempt_failed": True,
            "cause": "beat2-failure",
            "beat2_report_hash": report_hash,
            "install_decision_seq": arc.decision_entry["seq"],
            "foundry_act_ref": arc.act.act_id,
        }
        decision_entry = self._record_policy_decision(
            action=f"capability rollback: {proposal.bundle_id}",
            detail=detail,
            approved=True,
            rationale=(
                "Beat 2 failed — the capability never went live; "
                "policy-executed rollback under the Step-8 exception"
            ),
            refusal_state=None,
            capability_id=proposal.bundle_id,
        )
        act = self._manager.rollback_install(
            proposal.bundle_id,
            arc.act.act_id,
            decision_citation=self._decision_citation(decision_entry),
        )
        self._escalate(
            f"capability rollback on Beat-2 failure: {proposal.bundle_id}",
            {
                "capability_id": proposal.bundle_id,
                "cause": "beat2-failure",
                "rollback_decision_seq": decision_entry["seq"],
                "rollback_act_id": act.act_id,
            },
        )
        return decision_entry

    # ------------------------------------------------------- probation P2
    def record_use(
        self,
        capability_id: str,
        *,
        invocation: str,
        grade: str | None = None,
        out_of_permission: bool = False,
    ) -> dict[str, Any]:
        """One receipted auto-approved use during probation. The
        fold-time pin check runs first (P4): a census pin that
        disagrees with the probation pin stamps this use as a
        pin-drift strike. After the use lands, the fold decides:
        suspension (two strikes, or a one-strike event) in one
        motion, else closure at the window's end."""
        entries = self._log.read_all()
        state = fold_probation(entries, capability_id)
        if state.standing != "probation" or state.manifest_pin is None:
            raise InstallError(
                f"capability {capability_id} is not in probation "
                f"(standing: {state.standing}) — use not receipted"
            )
        live_pin = self._manager.census_pin(capability_id)
        pin_drift = live_pin != state.manifest_pin
        entry = self._log.record_entry(
            _receipts.capability_use_fields(
                capability_id=capability_id,
                manifest_pin=state.manifest_pin,
                invocation=invocation,
                grade=grade,
                out_of_permission=out_of_permission,
                pin_drift=pin_drift,
            )
        )
        self._after_use(capability_id, entry)
        return entry

    def submit_gated_use(
        self, capability_id: str, request: EscalationRequest
    ) -> Decision:
        """A gated-class use of a probationary capability: the gate
        Decision is the use record (P2). The governor stamps the
        capability's id and the fold-time drift fact onto the request
        before the gate decides, so the fold — any fold — counts the
        use and its strikes from the chain alone."""
        entries = self._log.read_all()
        state = fold_probation(entries, capability_id)
        if state.standing != "probation" or state.manifest_pin is None:
            raise InstallError(
                f"capability {capability_id} is not in probation "
                f"(standing: {state.standing}) — use not presented"
            )
        live_pin = self._manager.census_pin(capability_id)
        detail = _detail_json({"detail": request.detail})
        detail["pin_drift"] = live_pin != state.manifest_pin
        detail["capability_use"] = True
        request.capability_id = capability_id
        request.detail = json.dumps(detail, sort_keys=True)
        decision = self._gatekeeper.authorize(request)
        entry = self._tail_entry()
        self._after_use(capability_id, entry)
        return decision

    def _after_use(self, capability_id: str, use_entry: dict[str, Any]) -> None:
        state = fold_probation(self._log.read_all(), capability_id)
        if state.standing != "probation":
            return
        seq = int(use_entry.get("seq", 0))
        if use_entry.get("pin_drift") is True or (
            _detail_json(use_entry).get("pin_drift") is True
        ):
            self.suspend(
                capability_id,
                reason=_receipts.SUSPENSION_REASON_PIN_DRIFT,
                strike_seqs=[seq],
            )
        elif use_entry.get("out_of_permission") is True or (
            _detail_json(use_entry).get("out_of_permission") is True
        ):
            self.suspend(
                capability_id,
                reason=_receipts.SUSPENSION_REASON_OUT_OF_PERMISSION,
                strike_seqs=[seq],
            )
        elif state.strikes >= 2:
            self.suspend(
                capability_id,
                reason=_receipts.SUSPENSION_REASON_TWO_STRIKES,
                strike_seqs=list(state.strike_seqs),
            )
        elif state.uses >= state.window_uses:
            assert state.manifest_pin is not None
            self._log.record_entry(
                _receipts.capability_probation_closed_fields(
                    capability_id=capability_id,
                    manifest_pin=state.manifest_pin,
                    uses=state.uses,
                    strikes=state.strikes,
                )
            )
            self._log.checkpoint()

    # ------------------------------------------------------------ P5
    def suspend(
        self,
        capability_id: str,
        *,
        reason: str,
        strike_seqs: list[int],
    ) -> dict[str, Any]:
        """Suspension in ONE motion (P5): (a) the suspension entry,
        strikes cited by seq; (b) Foundry disable enforcement under
        the entry's citation — the directory leaves the library, no
        registry event (suspension is not deprecation; the binding
        stands, disabled); (c) the escalation Decision, in the
        supervisor's escalation receipt shape."""
        state = fold_probation(self._log.read_all(), capability_id)
        if state.manifest_pin is None:
            raise InstallError(
                f"capability {capability_id} has no probation record to suspend"
            )
        entry = self._log.record_entry(
            _receipts.capability_suspension_fields(
                capability_id=capability_id,
                manifest_pin=state.manifest_pin,
                strike_seqs=strike_seqs,
                reason=reason,
            )
        )
        enforcement = self._manager.disable(capability_id)
        if not enforcement.get("ok") or enforcement.get("library_present"):
            raise InstallError(
                f"suspension enforcement failed for {capability_id}: {enforcement}"
            )
        self._escalate(
            f"capability suspension: {capability_id}",
            {
                "capability_id": capability_id,
                "suspension_entry_hash": entry["entry_hash"],
                "strike_seqs": strike_seqs,
                "reason": reason,
            },
        )
        return entry

    def _escalate(self, reason: str, detail: dict[str, Any]) -> Decision:
        """The supervisor's escalation receipt shape (supervise.py's
        _escalate): an IRREVERSIBLE-class Decision through a
        Gatekeeper over the same log, human_id 'supervisor-human',
        detail carrying event='escalation' — so the supervision fold
        reads it as an escalation, and the chain is checkpointed
        after it."""
        gatekeeper = Gatekeeper(
            audit_log=self._log,
            approver=self._approver,
            human_id="supervisor-human",
        )
        request = EscalationRequest(
            action=f"supervisor escalation: {reason}",
            action_class=ActionClass.IRREVERSIBLE,
            detail=json.dumps({"event": "escalation", **detail}, sort_keys=True),
        )
        decision = gatekeeper.authorize(request)
        self._log.checkpoint()
        return decision

    # ------------------------------------------------------------ status
    def status(self, capability_id: str) -> ProbationState:
        return fold_probation(self._log.read_all(), capability_id)

    def status_all(self) -> dict[str, ProbationState]:
        return fold_all_probation(self._log.read_all())


def format_status_lines(
    states: dict[str, ProbationState], *, head: str | None
) -> list[str]:
    """The printed fold (P6): per capability — uses in window,
    strikes, standing, and the chain head the fold was taken at."""
    lines = []
    for capability_id in sorted(states):
        st = states[capability_id]
        lines.append(
            f"{capability_id}: standing={st.standing} "
            f"uses={st.uses}/{st.window_uses} strikes={st.strikes} "
            f"pin={st.manifest_pin} folded_at={head}"
        )
    return lines


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_driver":
        raise SystemExit(_driver_main(sys.argv[2:]))
    print(
        "chancellor.installs: the governed capability-install arc "
        "(frame v2, clause 6). See docs/foundry-install-spec.md."
    )
    raise SystemExit(2)
