"""Instrument checks — and the fail-closed rule.

Before an output is accepted, it passes a panel of instrument checks
(schema shape, non-empty, cost ceiling, banned terms). The defining rule
of Warden: **a check that errors is a check that FAILED.** A broken gauge
is a stop signal, never a pass. There is no configuration flag to change
this.

Two composition-level rules complete the posture (W1):
  * An EMPTY panel certifies nothing. A panel with zero checks reports
    failure, never a green light assembled from no evidence.
  * A check that does not answer within its time bound has not passed:
    absence of a verdict within the bound is a DENY. A hung check is
    fail-closed, not fail-stuck — the panel moves on without it.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_CHECK_TIMEOUT_S = 10.0


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class PanelResult:
    ok: bool
    results: list[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.ok]

    @property
    def halt_reason(self) -> str | None:
        if self.ok:
            return None
        return "; ".join(f"{r.name}: {r.detail}" for r in self.failures)


Check = Callable[[Any], "CheckResult | bool"]


class InstrumentPanel:
    def __init__(self, timeout_s: float | None = DEFAULT_CHECK_TIMEOUT_S):
        self.checks: dict[str, Check] = {}
        # Per-check verdict bound. None disables the bound (checks run
        # inline); any finite bound turns a hang into a denial.
        self.timeout_s = timeout_s

    def register(self, name: str, fn: Check) -> "InstrumentPanel":
        self.checks[name] = fn
        return self

    def __len__(self) -> int:
        return len(self.checks)

    def _run_check(self, name: str, fn: Check, artifact: Any) -> CheckResult:
        """Run one check under its time bound. Any exception, garbage
        return, or timeout is a FAILURE — never an exception out, never
        a pass."""
        try:
            if self.timeout_s is None:
                r = fn(artifact)
            else:
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                try:
                    future = executor.submit(fn, artifact)
                    r = future.result(timeout=self.timeout_s)
                except concurrent.futures.TimeoutError:
                    return CheckResult(
                        name=name, ok=False,
                        detail=(f"check timed out after {self.timeout_s}s — "
                                "no verdict within bound is a deny (fail-closed)"))
                finally:
                    # Never block on a hung check: abandon the thread.
                    executor.shutdown(wait=False)
        except Exception as exc:  # FAIL-CLOSED: instrument error == failure
            return CheckResult(
                name=name, ok=False,
                detail=f"instrument error: {type(exc).__name__}: {exc}")
        if isinstance(r, bool):
            return CheckResult(name=name, ok=r,
                               detail="" if r else "check returned False")
        if isinstance(r, CheckResult):
            if r.name != name:
                return CheckResult(name=name, ok=r.ok, detail=r.detail)
            return r
        return CheckResult(
            name=name, ok=False,
            detail=f"instrument returned garbage: {type(r).__name__} "
                   "is not a CheckResult (fail-closed)")

    def run_all(self, artifact: Any) -> PanelResult:
        if not self.checks:
            # FAIL-CLOSED: zero checks is zero evidence, not a pass.
            return PanelResult(ok=False, results=[CheckResult(
                name="empty_panel", ok=False,
                detail="panel has no checks registered — an empty panel "
                       "certifies nothing (fail-closed)")])
        results = [self._run_check(name, fn, artifact)
                   for name, fn in self.checks.items()]
        return PanelResult(ok=all(r.ok for r in results), results=results)


# -- built-in checks ---------------------------------------------------------
# Worker artifacts are dicts: {"text": str, "cost_usd": float, ...}

def check_non_empty(artifact: Any) -> CheckResult:
    text = artifact.get("text", "") if isinstance(artifact, dict) else str(artifact)
    ok = bool(str(text).strip())
    return CheckResult("non_empty_output", ok,
                       "" if ok else "output text is empty")


def check_required_keys(*keys: str) -> Check:
    def _check(artifact: Any) -> CheckResult:
        if not isinstance(artifact, dict):
            return CheckResult("required_keys", False, "artifact is not a mapping")
        missing = [k for k in keys if k not in artifact]
        return CheckResult("required_keys", not missing,
                           "" if not missing else f"missing keys: {missing}")
    return _check


def check_cost_ceiling(max_usd: float) -> Check:
    def _check(artifact: Any) -> CheckResult:
        cost = float(artifact.get("cost_usd", 0.0)) if isinstance(artifact, dict) else 0.0
        ok = cost <= max_usd
        return CheckResult("cost_ceiling", ok,
                           "" if ok else f"cost ${cost:.4f} exceeds ceiling ${max_usd:.2f}")
    return _check


def check_banned_terms(*terms: str) -> Check:
    lowered = [t.lower() for t in terms]

    def _check(artifact: Any) -> CheckResult:
        text = artifact.get("text", "") if isinstance(artifact, dict) else str(artifact)
        hits = [t for t in lowered if t in str(text).lower()]
        return CheckResult("banned_terms", not hits,
                           "" if not hits else f"banned terms present: {hits}")
    return _check


def default_panel(max_cost_usd: float | None = None,
                  banned_terms: tuple[str, ...] = ()) -> InstrumentPanel:
    panel = InstrumentPanel()
    panel.register("non_empty_output", check_non_empty)
    panel.register("required_keys", check_required_keys("text"))
    if max_cost_usd is not None:
        panel.register("cost_ceiling", check_cost_ceiling(max_cost_usd))
    if banned_terms:
        panel.register("banned_terms", check_banned_terms(*banned_terms))
    return panel
