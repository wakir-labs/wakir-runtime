# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3-Marathon-Anti-Pattern coverage — hermetic negative-tests pinning
the anti-pattern boundaries that the Tag-40 / Tag-41 / Tag-43 positive-
test stack does not exhaustively probe.

Auftrag-Anker
-------------

- Tag-44 Amara Auftrag — Marathon-E2E-Anti-Pattern-Test-Erweiterung
  (Continuous-Mode, Aufsichtsrat 2026-05-18). Where the Tag-43
  ``test_marathon_schluss_acceptance_drill.py`` pins the *positive*
  marathon-sequence end-to-end and its five anti-false-positive
  NEG-axis cases, this Tag-44 file pins **ten dedicated anti-pattern
  failure-modes** that the marathon-control-surface must reject by
  construction:

    * AP-1   Phase-3-COMPLETE marker race  (two parallel workflows
             cannot both emit the marker file)
    * AP-2   Welle-Sign-Off replay         (a sign-off file cannot be
             accepted twice for the same Welle)
    * AP-3   Audit-Trail corruption        (Welle-3 ``bridge_audit_writer``
             cutover-window cannot corrupt audit-records;
             self-reference-trap probe)
    * AP-4   Cross-Welle state-leak        (Welle-4 ``state_backing``
             cutover cannot leak FSM-states into Welle-5)
    * AP-5   Sign-Off timestamp drift      (sign-off ISOs must be
             monotonically non-decreasing KW-24 < KW-25 < KW-26 < KW-27)
    * AP-6   AR-Hand ratification bypass   (AC-5 cannot be satisfied by
             a dummy stamp-file; filename-pattern + payload-shape
             strict)
    * AP-7   IIA-1130 Welle-7 self-audit trap (Henrik sign-off on
             Welle-7 is rejected by audit-archive flag; AR-Hand is the
             only admissible Welle-7-Pre-Auditor)
    * AP-8   Cutover-day timing drift      (cutover only Mo-Fr
             09:00-14:00 CEST; nights and weekends rejected)
    * AP-9   Rollback cascade              (Welle-3 rollback blocks
             Welle-4..7 cutover; aggregate marker not set)
    * AP-10  COMPLETE-marker false-positive via empty state-files
             (empty / zero-length state-files MUST BLOCK, not pass)

- ADR-0066 §Beschluss + §Wochen-Plan — the four-Wochen-Cadence
  (KW-24 -> KW-27) provides the timestamp anchors and the Welle-3
  Pre-Audit-Path / Welle-7 IIA-1130 Pre-Auditor-Decision shape.
- ADR-0065 §Verifikations-Plan + §AC-4 — the Cross-Review-Consensus
  shape and the AC-1..AC-5 anchors.
- ``.github/workflows/phase-3-complete-marker.yml`` — Tomás Tag-40
  marker-workflow whose ``concurrency.group=phase-3-complete-marker``
  + ``cancel-in-progress: false`` clause is the production-anchor
  for AP-1 (race-rejection by serialisation, not by retry).

Cross-spawn-Konsistenz (Tag-44)
-------------------------------

- Companion (positive marathon-sequence): Tag-43
  ``test_marathon_schluss_acceptance_drill.py``. This Tag-44 file
  re-imports the marathon contract surface (KW_TO_WELLEN,
  PerKwSignOffBundle shape, Phase3CompleteAcceptanceCriteria) and
  reuses the per-Welle sign-off-marker shape from Tag-40 so the
  anti-pattern oracles stay in lock-step with the positive contract.
- Companion (marker state-machine): Tag-40
  ``test_phase_3_final_regression.py`` — re-uses
  :data:`ADR_0066_REIHENFOLGE` + :data:`MARATHON_TRACE_TIMESTAMPS`.
- Companion (per-day walkthrough): Tag-41
  ``test_cutover_day_e2e_drill.py`` — re-uses the Cutover-Mittwoch
  drill schedule shape for AP-8 timing-window validation.
- Companion (audit-spec): Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle
  + ``docs/audit/phase-3-cutover-schluss-audit-spec.md`` §IIA-1130
  Pt-5 — the AP-7 anti-pattern probe mirrors Henrik's spec
  prohibition.

Why a separate suite (vs. extending Tag-43 NEG axis)
----------------------------------------------------

* The Tag-43 NEG axis pins five **anti-false-positive** cases at the
  granularity of "given a partly-incomplete marathon, the marker does
  not fire". Those five cases live at the marathon-aggregate layer.
* The Tag-44 anti-pattern suite pins **ten dedicated anti-pattern
  failure-modes** at the *control-plane* layer: race-rejection,
  replay-rejection, corruption-rejection, leak-rejection,
  drift-rejection, bypass-rejection, self-audit-rejection, timing-
  rejection, cascade-rejection, false-positive-rejection. These are
  *invariants of the control surface itself*, not "what happens when
  one Welle did not sign off".
* Keeping them in a dedicated file means the Tag-43 marathon-positive
  suite is not polluted with control-plane probes, and the Tag-44
  anti-pattern oracles can be re-used by future audit-spec drills
  without re-importing the marathon-sequence contract.

Test budget
-----------

20 tests across ten AP-axes (two tests per axis: one happy-path
admissibility-confirmation that the AP-rejection-rule fires on a
*violating* input, plus one happy-path confirmation that the same
rule accepts a *non-violating* input):

AP-1 — Phase-3-COMPLETE-Marker race (2 tests)
AP-2 — Welle-Sign-Off replay (2 tests)
AP-3 — Audit-Trail corruption (2 tests)
AP-4 — Cross-Welle state-leak (2 tests)
AP-5 — Sign-Off timestamp drift (2 tests)
AP-6 — AR-Hand ratification bypass (2 tests)
AP-7 — IIA-1130 Welle-7 self-audit trap (2 tests)
AP-8 — Cutover-day timing drift (2 tests)
AP-9 — Rollback cascade (2 tests)
AP-10 — COMPLETE-marker false-positive via empty state-files (2 tests)

Vermutungs-Kennzeichnung (P2)
-----------------------------

* The Tag-40 marker-workflow's ``concurrency`` clause is the
  production-anchor for AP-1. This test file does not simulate the
  GitHub-Actions runner; it asserts the pre-image control-surface
  invariant (one in-flight marker-emission per repo at a time) via a
  pure-Python in-test serialisation oracle. The oracle is consistent
  with the workflow's behaviour: a second parallel dispatch must wait
  for the first to complete, and the file-system write of
  ``state/phase-3-complete-marker.json`` MUST be the unique
  serialisation-point.
* AP-3 (Self-Reference-Trap-Anti-Pattern-Probe): Welle-3
  ``bridge_audit_writer`` cuts over the audit-trail writer itself.
  During the cutover-window, an audit-record MUST be writable to
  *either* the legacy writer or the new writer, never neither (no
  corruption-window). This test pins that invariant on a synthetic
  ledger; it does not exercise the live audit-trail.
* AP-7 IIA-1130: the in-test ``audit-archive.md`` flag is the
  contract-anchor for "Henrik may not sign Welle-7". The substantive
  in-repo flag lives in Henrik's audit-spec; this test file mirrors
  the flag and asserts the rejection.

License: Apache-2.0 (parity with sibling Phase-3c artefacts).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import pytest


# ---------------------------------------------------------------------------
# Companion-module loaders.
#
# We import the Tag-40 final-regression module (ADR-0066-Reihenfolge,
# marker state-machine, marathon-trace timestamps) and the Tag-43
# marathon-schluss module (KW_TO_WELLEN, PerKwSignOffBundle,
# Phase3CompleteAcceptanceCriteria) so the anti-pattern oracles
# stay in lock-step with the positive contract surface.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _load_companion_test_module(filename: str, module_name: str) -> Any:
    """Load a sibling phase_3c test module so we can reuse its constants."""
    test_path = _repo_root() / "tests" / "phase_3c" / filename
    if not test_path.is_file():
        pytest.fail(f"companion test module not found at {test_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(test_path))
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {test_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# Tag-40 final-regression: ADR-0066-Reihenfolge + marker state-machine.
_TAG40 = _load_companion_test_module(
    "test_phase_3_final_regression.py",
    "phase_3c_tag40_final_regression_for_tag44_anti_patterns",
)

# Tag-43 marathon-schluss: KW_TO_WELLEN + PerKwSignOffBundle +
# Phase3CompleteAcceptanceCriteria (the AC-1..AC-5 predicate shape).
_TAG43 = _load_companion_test_module(
    "test_marathon_schluss_acceptance_drill.py",
    "phase_3c_tag43_marathon_schluss_for_tag44_anti_patterns",
)


ADR_0066_REIHENFOLGE = _TAG40.ADR_0066_REIHENFOLGE
ADR_0065_AC_4_PERSONAS: FrozenSet[str] = _TAG40.ADR_0065_AC_4_PERSONAS
WELLE_ENDE_GATES: Tuple[str, ...] = _TAG40.WELLE_ENDE_GATES
MARATHON_TRACE_TIMESTAMPS = _TAG40.MARATHON_TRACE_TIMESTAMPS
SignOffMarker = _TAG40.SignOffMarker
Phase3CompleteMarkerStateMachine = _TAG40.Phase3CompleteMarkerStateMachine
Phase3CompleteMarkerVerdict = _TAG40.Phase3CompleteMarkerVerdict

KW_TO_WELLEN: Mapping[int, Tuple[int, ...]] = _TAG43.KW_TO_WELLEN


# ---------------------------------------------------------------------------
# AP-1 — Phase-3-COMPLETE-Marker race oracle.
#
# The Tomás Tag-40 marker-workflow's ``concurrency`` clause serialises
# marker-emission: at most one in-flight emission per repo. This in-test
# oracle is a pure-Python serialisation gate that mirrors the workflow's
# invariant: two parallel ``acquire`` calls MUST yield (admitted, denied)
# for the second caller, never (admitted, admitted).
# ---------------------------------------------------------------------------


@dataclass
class MarkerEmissionLease:
    """A single-holder lease over the Phase-3-COMPLETE-marker emission slot.

    The lease is held by the first acquirer; subsequent acquirers receive
    ``False``. The lease releases when ``release`` is called (mirroring the
    workflow's "job-complete" signal).

    Equivalent invariant in production (workflow):
        concurrency:
          group: phase-3-complete-marker
          cancel-in-progress: false

    The pure-Python oracle is *deliberately* simpler than a real mutex —
    no timeouts, no reentrancy, no waiting. The two production guarantees
    we care about are:

      1.  At any instant, at most one holder.
      2.  The unique holder produces the unique marker-file write.
    """

    _held_by: Optional[str] = None
    _write_history: List[Tuple[str, str]] = field(default_factory=list)

    def acquire(self, holder_id: str) -> bool:
        """Attempt to acquire the lease. Returns ``True`` on success."""
        if self._held_by is None:
            self._held_by = holder_id
            return True
        return False

    def write_marker(self, holder_id: str, marker_payload_sha: str) -> bool:
        """Write the marker file. Rejects writes from non-holders.

        Returns ``True`` if the write was admitted (the holder is the
        registered holder) and recorded in the write history.
        """
        if self._held_by != holder_id:
            return False
        self._write_history.append((holder_id, marker_payload_sha))
        return True

    def release(self, holder_id: str) -> bool:
        """Release the lease. Idempotent for non-holders."""
        if self._held_by == holder_id:
            self._held_by = None
            return True
        return False

    @property
    def write_history(self) -> Tuple[Tuple[str, str], ...]:
        """Return the immutable tuple of (holder_id, marker_sha) writes."""
        return tuple(self._write_history)


# ---------------------------------------------------------------------------
# AP-2 — Welle-Sign-Off replay oracle.
#
# A sign-off-file is keyed by (welle_number, commit_sha). The ingester
# MUST reject a second submission with the same key, even if the payload
# differs ("idempotency via natural key"). The oracle below is the
# pure-Python pre-image of the GitHub-Actions check that the workflow
# performs against ``state/welle-{N}-sign-off.json``.
# ---------------------------------------------------------------------------


@dataclass
class SignOffIdempotencyLedger:
    """Records (welle, commit_sha) pairs that have been admitted.

    A second submission with the same key is rejected. The ledger is the
    in-test pre-image of the workflow's "the file is already in main"
    check; in production the ledger is the file system itself.
    """

    _admitted: Dict[Tuple[int, str], str] = field(default_factory=dict)

    def admit(self, welle: int, commit_sha: str, status: str) -> bool:
        """Admit a sign-off. Returns ``False`` if the key is already known."""
        key = (welle, commit_sha)
        if key in self._admitted:
            return False
        self._admitted[key] = status
        return True

    @property
    def admitted_count(self) -> int:
        """Return the number of admitted (welle, sha) records."""
        return len(self._admitted)

    def status_for(self, welle: int, commit_sha: str) -> Optional[str]:
        """Return the admitted status for the (welle, sha) pair, if any."""
        return self._admitted.get((welle, commit_sha))


# ---------------------------------------------------------------------------
# AP-3 — Audit-Trail corruption oracle (Self-Reference-Trap-Anti-Pattern).
#
# Welle-3 cuts over the ``bridge_audit_writer`` itself; every other
# component writes audit-records *into* the audit-trail, and Welle-3 is
# the one component whose cutover changes *who is writing the trail*.
# This is the self-reference trap: during the cutover-window, who is
# writing the records that prove the cutover happened?
#
# The invariant is: *no audit-record may be lost during the cutover-
# window*. The cutover-window MUST be a strict ordering "old writer
# drains, new writer picks up", never a both-off interregnum.
#
# The oracle below is a synthetic ledger that simulates the cutover-
# window and asserts no corruption-window exists.
# ---------------------------------------------------------------------------


@dataclass
class BridgeAuditWriterCutoverLedger:
    """Synthetic audit-record ledger for the Welle-3 cutover-window.

    Models the audit-trail as a list of (record_id, writer_id) tuples and
    enforces the invariant that every record is owned by exactly one of
    the legacy and new writers — never neither, never both.
    """

    legacy_writer_id: str = "bridge_audit_writer_v1"
    new_writer_id: str = "bridge_audit_writer_v2"
    _records: List[Tuple[str, str]] = field(default_factory=list)
    _legacy_drained: bool = False
    _new_active: bool = False
    _state: str = "pre-cutover"  # pre-cutover | drain | new-active | post-cutover

    def begin_cutover_window(self) -> None:
        """Transition pre-cutover -> drain."""
        assert self._state == "pre-cutover", (
            "cutover begin must follow pre-cutover, not "
            f"{self._state!r}"
        )
        self._state = "drain"

    def drain_legacy_writer(self) -> None:
        """Mark the legacy writer drained. Must occur in drain-state."""
        assert self._state == "drain", (
            f"drain_legacy_writer requires state=drain, got {self._state!r}"
        )
        self._legacy_drained = True

    def activate_new_writer(self) -> None:
        """Activate the new writer. Requires legacy drained first.

        The strict ordering — drain before activate — is the invariant
        that prevents an interregnum. If the new writer were activated
        before the legacy drained, records could be written to both
        writers and lost during reconciliation. If the new writer were
        activated after the legacy *stopped* (rather than drained), a
        gap would exist.
        """
        assert self._state == "drain", (
            f"activate_new_writer requires state=drain, got {self._state!r}"
        )
        assert self._legacy_drained, (
            "activate_new_writer requires legacy writer to have drained"
        )
        self._new_active = True
        self._state = "new-active"

    def finalize_cutover(self) -> None:
        """Transition new-active -> post-cutover."""
        assert self._state == "new-active", (
            f"finalize_cutover requires state=new-active, got {self._state!r}"
        )
        self._state = "post-cutover"

    def write_audit_record(self, record_id: str) -> str:
        """Write a record. Returns the writer that took it."""
        if self._state == "pre-cutover":
            writer = self.legacy_writer_id
        elif self._state == "drain":
            # During drain, legacy is still writing.
            writer = self.legacy_writer_id
        elif self._state == "new-active":
            writer = self.new_writer_id
        elif self._state == "post-cutover":
            writer = self.new_writer_id
        else:  # pragma: no cover — defensive
            raise AssertionError(f"unexpected state {self._state!r}")
        self._records.append((record_id, writer))
        return writer

    @property
    def records(self) -> Tuple[Tuple[str, str], ...]:
        """Return the immutable record history."""
        return tuple(self._records)

    def has_corruption_window(self) -> bool:
        """Return True iff any record is owned by an unknown writer
        or no writer at all (the corruption-window we forbid).
        """
        known = {self.legacy_writer_id, self.new_writer_id}
        return any(w not in known or not w for _, w in self._records)


# ---------------------------------------------------------------------------
# AP-4 — Cross-Welle FSM-state-leak oracle.
#
# Welle-4 cuts over ``state_backing``; Welle-5 cuts over
# ``lifecycle_state_machine``. Both interact with persona FSM state.
# The invariant is: the Welle-4 cutover MUST NOT leave FSM-state
# residue that the Welle-5 cutover then reads as legitimate state.
# In production the boundary is enforced by a namespace prefix on
# the state-backing keys; this oracle simulates that.
# ---------------------------------------------------------------------------


@dataclass
class StateBackingLeakLedger:
    """Synthetic state-backing key-value store with welle-scoped prefixes.

    A key written under the Welle-4 prefix MUST NOT be visible to a
    Welle-5 read. Cross-welle visibility is the leak we forbid.
    """

    welle_4_prefix: str = "welle-4/"
    welle_5_prefix: str = "welle-5/"
    _store: Dict[str, str] = field(default_factory=dict)

    def write(self, welle: int, key: str, value: str) -> None:
        """Write ``key=value`` under the per-welle prefix."""
        prefix = self._prefix_for(welle)
        self._store[prefix + key] = value

    def read(self, welle: int, key: str) -> Optional[str]:
        """Read ``key`` under the per-welle prefix. Returns ``None`` if
        the key is absent under this prefix (even if it exists under a
        sibling prefix — the namespace boundary is the invariant)."""
        prefix = self._prefix_for(welle)
        return self._store.get(prefix + key)

    def _prefix_for(self, welle: int) -> str:
        if welle == 4:
            return self.welle_4_prefix
        if welle == 5:
            return self.welle_5_prefix
        raise ValueError(f"unsupported welle for state-backing leak ledger: {welle}")

    def keys_under_prefix(self, welle: int) -> Tuple[str, ...]:
        """Return the keys under the welle's prefix, sorted."""
        prefix = self._prefix_for(welle)
        return tuple(sorted(k for k in self._store if k.startswith(prefix)))


# ---------------------------------------------------------------------------
# AP-5 — Sign-Off timestamp monotonicity.
#
# The marathon's per-KW sign-off-Freitag timestamps MUST be
# monotonically non-decreasing KW-24 < KW-25 < KW-26 < KW-27 (the
# four-Wochen-Cadence is a strict total order). The oracle below
# extracts the timestamps from MARATHON_TRACE_TIMESTAMPS and asserts
# strict monotonicity.
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> _dt.datetime:
    """Parse an ISO-8601 timestamp into an aware datetime."""
    return _dt.datetime.fromisoformat(ts)


def signoff_isos_in_kw_order() -> Tuple[Tuple[int, str], ...]:
    """Return ``((kw, signoff_iso), ...)`` ordered by KW ascending."""
    rows = sorted(MARATHON_TRACE_TIMESTAMPS, key=lambda r: r[0])
    return tuple((kw, freitag_iso) for kw, _mw, _do, freitag_iso in rows)


def is_strictly_monotonic_in_kw_order(rows: Sequence[Tuple[int, str]]) -> bool:
    """Return True iff the (kw, iso) rows are strictly ascending in both axes."""
    if not rows:
        return True
    prev_kw, prev_ts = None, None
    for kw, ts in rows:
        ts_parsed = _parse_iso(ts)
        if prev_kw is not None:
            assert prev_ts is not None
            if kw <= prev_kw:
                return False
            if ts_parsed <= prev_ts:
                return False
        prev_kw, prev_ts = kw, ts_parsed
    return True


# ---------------------------------------------------------------------------
# AP-6 — AR-Hand ratification bypass oracle.
#
# AC-5 in the marker-workflow checks
# ``state/ar-hand-phase-3-complete-stamp.json`` for
# ``ar_hand_ratification=True`` AND a non-empty ``ar_hand_quote``. A
# dummy file with the right filename but a wrong payload — or the right
# payload but a wrong filename — MUST be rejected.
# ---------------------------------------------------------------------------


# Required filename pattern per the workflow.
AR_HAND_STAMP_FILENAME = "state/ar-hand-phase-3-complete-stamp.json"

# Required JSON shape per the workflow.
AR_HAND_STAMP_REQUIRED_KEYS: FrozenSet[str] = frozenset(
    {"ar_hand_ratification", "ar_hand_quote", "timestamp_utc"}
)


@dataclass(frozen=True)
class ArHandStampCandidate:
    """An AR-Hand-stamp candidate as the workflow would observe it.

    Combines the filename pattern check and the payload-shape check
    into one oracle.
    """

    filename: str
    payload: Mapping[str, Any]

    def is_admissible(self) -> bool:
        """Return True iff filename pattern AND payload shape match."""
        if self.filename != AR_HAND_STAMP_FILENAME:
            return False
        if not AR_HAND_STAMP_REQUIRED_KEYS.issubset(self.payload.keys()):
            return False
        if self.payload.get("ar_hand_ratification") is not True:
            return False
        quote = self.payload.get("ar_hand_quote")
        if not isinstance(quote, str) or not quote.strip():
            return False
        return True


# ---------------------------------------------------------------------------
# AP-7 — IIA-1130 Welle-7 self-audit trap.
#
# Per Henrik's audit-spec §IIA-1130 Pt-5: Internal Audit may not be the
# marker-actor. Concretely, Henrik's sign-off MUST NOT be the sign-off
# that admits Welle-7 sign-off — the Welle-7 sign-off requires the
# AR-Hand-Pre-Auditor-Decision (per Tag-43 marathon-schluss
# ``Welle7PreAuditorDecision``). The audit-archive-flag below is the
# in-test contract anchor.
# ---------------------------------------------------------------------------


AUDIT_ARCHIVE_FLAG_WELLE_7_HENRIK_REJECTED: str = (
    "IIA-1130: Henrik (Internal Audit) is REJECTED as Welle-7 sign-off"
    " actor; AR-Hand-Pre-Auditor-Decision is the only admissible signer."
)


@dataclass
class Welle7SignOffSubmission:
    """A sign-off submission for Welle-7 with signer-identity tracking."""

    signer_role: str  # "ar_hand" | "henrik_internal_audit" | other
    signer_id: str
    payload: Mapping[str, Any]


def admit_welle_7_signoff(submission: Welle7SignOffSubmission) -> Tuple[bool, str]:
    """Return ``(admitted, reason)`` for a Welle-7 sign-off submission.

    Rejects all internal-audit signers (IIA-1130) and admits AR-Hand
    submissions with the required payload shape.
    """
    if submission.signer_role == "henrik_internal_audit":
        return (False, AUDIT_ARCHIVE_FLAG_WELLE_7_HENRIK_REJECTED)
    if submission.signer_role != "ar_hand":
        return (False, f"non-AR-Hand signer rejected: role={submission.signer_role!r}")
    if not submission.payload.get("welle_7_pre_auditor_decision_present"):
        return (False, "missing welle_7_pre_auditor_decision_present=True")
    if not submission.payload.get("iia_1130_independence_anchor"):
        return (False, "missing iia_1130_independence_anchor")
    return (True, "admitted")


# ---------------------------------------------------------------------------
# AP-8 — Cutover-day timing drift.
#
# ADR-0066 §Wochen-Plan fixes Cutover-Mittwoch as the cutover-day. The
# Tomás runbook (and the Tag-41 cutover-day drill) constrain the
# cutover-window to Mo-Fr 09:00-14:00 CEST. Nights, weekends, and
# off-hour weekday windows must be rejected.
#
# We model the window as a strict predicate over a datetime and assert
# both the rejection (off-hour / weekend) and the admission (on-hour
# weekday) cases.
# ---------------------------------------------------------------------------


# Per ADR-0066 + Tomás runbook: cutover only Mon-Fri 09:00 - 14:00 CEST.
CUTOVER_WINDOW_DAYS_OF_WEEK: FrozenSet[int] = frozenset({0, 1, 2, 3, 4})  # Mon..Fri
CUTOVER_WINDOW_START_HOUR: int = 9
CUTOVER_WINDOW_END_HOUR: int = 14  # exclusive upper bound


def is_within_cutover_window(ts: _dt.datetime) -> bool:
    """Return True iff ``ts`` falls in the cutover-window (Mo-Fr 09-14 CEST)."""
    if ts.weekday() not in CUTOVER_WINDOW_DAYS_OF_WEEK:
        return False
    if ts.hour < CUTOVER_WINDOW_START_HOUR:
        return False
    if ts.hour >= CUTOVER_WINDOW_END_HOUR:
        return False
    return True


# ---------------------------------------------------------------------------
# AP-9 — Rollback cascade.
#
# If Welle-3 (Henrik-Caution risk-class, Pre-Audit-Path) is rolled back,
# the marathon-sequence MUST block all subsequent cutovers (Welle-4..7)
# because their cross-modul-drift assertion depends on the Welle-3
# bridge_audit_writer being in its new state. The aggregate marker MUST
# NOT be set.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RollbackCascadeVerdict:
    """The aggregate verdict after applying a Welle-3 rollback."""

    welle_3_rolled_back: bool
    blocked_wellen: Tuple[int, ...]
    marker_admissible: bool
    blocking_reason: str


def apply_welle_3_rollback_cascade(rollback_welle_numbers: Sequence[int]) -> RollbackCascadeVerdict:
    """Return the cascade verdict for a set of rolled-back wellen.

    If Welle-3 is in the rollback set, all Welle-4..7 are also blocked
    (regardless of whether they individually rolled back) and the
    aggregate Phase-3-COMPLETE marker MUST be inadmissible.
    """
    rb = frozenset(rollback_welle_numbers)
    welle_3 = 3 in rb
    if welle_3:
        blocked = tuple(sorted({3, 4, 5, 6, 7} | set(rb)))
        return RollbackCascadeVerdict(
            welle_3_rolled_back=True,
            blocked_wellen=blocked,
            marker_admissible=False,
            blocking_reason="welle-3-rollback-cascade-blocks-welle-4..7",
        )
    return RollbackCascadeVerdict(
        welle_3_rolled_back=False,
        blocked_wellen=tuple(sorted(rb)),
        marker_admissible=not bool(rb),
        blocking_reason="" if not rb else "individual-welle-rollback",
    )


# ---------------------------------------------------------------------------
# AP-10 — COMPLETE-marker false-positive via empty state-files.
#
# An empty file (zero bytes) or a file containing ``{}`` MUST NOT be
# accepted by any of the AC-1..AC-5 checks. The workflow probe extracts
# specific fields from each state-file; an empty / minimal file MUST
# fail every probe.
# ---------------------------------------------------------------------------


def state_file_passes_ac1_probe(payload_text: str) -> bool:
    """AC-1 probe: requires sign_off_status in {green, yellow_henrik_hand_approval}."""
    try:
        d = json.loads(payload_text) if payload_text.strip() else None
    except json.JSONDecodeError:
        return False
    if not isinstance(d, dict):
        return False
    return d.get("sign_off_status") in {"green", "yellow_henrik_hand_approval"}


def state_file_passes_ac3_probe(payload_text: str, expected: Tuple[int, int]) -> bool:
    """AC-3 probe: requires (completed_count, total_count) == expected."""
    try:
        d = json.loads(payload_text) if payload_text.strip() else None
    except json.JSONDecodeError:
        return False
    if not isinstance(d, dict):
        return False
    if d.get("completed_count") != expected[0]:
        return False
    if d.get("total_count") != expected[1]:
        return False
    return True


def state_file_passes_ac4_probe(payload_text: str) -> bool:
    """AC-4 probe: requires verdict='ratified' AND R-A1..R-A6 all 'verified'."""
    try:
        d = json.loads(payload_text) if payload_text.strip() else None
    except json.JSONDecodeError:
        return False
    if not isinstance(d, dict):
        return False
    if d.get("verdict") != "ratified":
        return False
    m = d.get("r_a_mitigation_status")
    if not isinstance(m, dict):
        return False
    required = ("R-A1", "R-A2", "R-A3", "R-A4", "R-A5", "R-A6")
    return all(m.get(k) == "verified" for k in required)


def state_file_passes_ac5_probe(payload_text: str) -> bool:
    """AC-5 probe: requires ar_hand_ratification=True AND non-empty quote."""
    try:
        d = json.loads(payload_text) if payload_text.strip() else None
    except json.JSONDecodeError:
        return False
    if not isinstance(d, dict):
        return False
    if d.get("ar_hand_ratification") is not True:
        return False
    quote = d.get("ar_hand_quote")
    if not isinstance(quote, str) or not quote.strip():
        return False
    return True


# ---------------------------------------------------------------------------
# Helpers reused across tests.
# ---------------------------------------------------------------------------


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _make_green_signoff_marker(welle: int, kw: int) -> SignOffMarker:
    """Build a synthetic green SignOffMarker for the given welle/kw."""
    mw_iso, do_iso, fr_iso = next(
        (mw, do, fr) for k, mw, do, fr in MARATHON_TRACE_TIMESTAMPS if k == kw
    )
    return SignOffMarker(
        welle_number=welle,
        status="signed-off",
        ac_1_5_green=True,
        ac_4_consensus_personas=ADR_0065_AC_4_PERSONAS,
        cross_welle_drift_assert="green",
        cutover_iso=mw_iso,
        signoff_iso=fr_iso,
    )


# ===========================================================================
# AP-1 — Phase-3-COMPLETE-Marker race
# ===========================================================================


class TestAp1MarkerRace:
    """AP-1: two parallel marker-emission attempts cannot both succeed."""

    def test_ap_1_two_parallel_acquirers_yields_one_admit_one_deny(self) -> None:
        """The unique-holder invariant pins AP-1: only one concurrent
        emission attempt is admitted; the second must be denied."""
        lease = MarkerEmissionLease()

        first_admitted = lease.acquire(holder_id="workflow-run-A")
        second_admitted = lease.acquire(holder_id="workflow-run-B")

        # Exactly one True, exactly one False (a race that yields both
        # True would be AP-1's anti-pattern realisation).
        assert first_admitted is True
        assert second_admitted is False
        # The held_by attribute confirms which holder won the race.
        assert lease._held_by == "workflow-run-A"

        # The denied workflow MUST also be denied at the write-step
        # (the workflow-level concurrency clause prevents both write,
        # but a defensive write-step rejection is the second line of
        # defense the in-test oracle pins).
        write_admitted_by_loser = lease.write_marker(
            holder_id="workflow-run-B",
            marker_payload_sha=_sha("loser-payload"),
        )
        assert write_admitted_by_loser is False
        assert lease.write_history == ()

        # The winner can write exactly one marker file.
        winner_write = lease.write_marker(
            holder_id="workflow-run-A",
            marker_payload_sha=_sha("winner-payload"),
        )
        assert winner_write is True
        assert len(lease.write_history) == 1
        assert lease.write_history[0][0] == "workflow-run-A"

    def test_ap_1_serial_acquire_release_admits_both_in_sequence(self) -> None:
        """Confirms the rule rejects only *parallel* attempts: two
        sequential (acquire, release) cycles MUST both be admitted."""
        lease = MarkerEmissionLease()

        admitted_a = lease.acquire(holder_id="workflow-run-A")
        assert admitted_a is True
        released_a = lease.release(holder_id="workflow-run-A")
        assert released_a is True

        admitted_b = lease.acquire(holder_id="workflow-run-B")
        assert admitted_b is True
        assert lease._held_by == "workflow-run-B"


# ===========================================================================
# AP-2 — Welle-Sign-Off replay
# ===========================================================================


class TestAp2SignOffReplay:
    """AP-2: a sign-off file cannot be admitted twice for the same Welle."""

    def test_ap_2_replay_with_same_welle_and_sha_is_rejected(self) -> None:
        """Idempotency-key (welle_number, commit_sha): second admit-call
        with the same key MUST return False; the ledger MUST keep only
        one record for that key."""
        ledger = SignOffIdempotencyLedger()

        first = ledger.admit(welle=3, commit_sha="abc123def456", status="green")
        assert first is True
        assert ledger.admitted_count == 1

        # Same welle, same commit_sha, different status — STILL replay,
        # STILL rejected. The natural-key replay-rejection rule is the
        # invariant, not the payload-shape.
        second = ledger.admit(
            welle=3,
            commit_sha="abc123def456",
            status="yellow_henrik_hand_approval",
        )
        assert second is False
        # The original status is preserved (no shadow write).
        assert ledger.status_for(3, "abc123def456") == "green"
        assert ledger.admitted_count == 1

    def test_ap_2_different_sha_or_welle_is_a_distinct_submission(self) -> None:
        """The replay-key is (welle, sha) pair. Different sha for the
        same welle is a *new* submission and MUST be admitted (this is
        the legitimate case of a Welle being re-signed-off on a later
        commit after a fixup). Same applies for different welle, same
        sha (different module, accidental sha-collision-impossible in
        production, but the key-rule still holds)."""
        ledger = SignOffIdempotencyLedger()

        assert ledger.admit(welle=4, commit_sha="sha-first", status="green") is True
        # Same welle, different sha — admitted.
        assert ledger.admit(welle=4, commit_sha="sha-second", status="green") is True
        # Different welle, first sha — admitted.
        assert ledger.admit(welle=5, commit_sha="sha-first", status="green") is True

        assert ledger.admitted_count == 3


# ===========================================================================
# AP-3 — Audit-Trail corruption (Self-Reference-Trap)
# ===========================================================================


class TestAp3AuditTrailCorruption:
    """AP-3: Welle-3 bridge_audit_writer cutover must not corrupt the trail."""

    def test_ap_3_legal_cutover_sequence_leaves_no_corruption_window(self) -> None:
        """The legal sequence pre-cutover -> drain -> drain-complete ->
        activate -> finalize MUST result in every record owned by a
        known writer (legacy or new), never neither."""
        ledger = BridgeAuditWriterCutoverLedger()

        # Phase 1: pre-cutover. Records owned by legacy.
        for i in range(3):
            owner = ledger.write_audit_record(f"pre-{i}")
            assert owner == ledger.legacy_writer_id

        # Phase 2: enter cutover. Drain phase still uses legacy.
        ledger.begin_cutover_window()
        owner_drain = ledger.write_audit_record("drain-1")
        assert owner_drain == ledger.legacy_writer_id

        # Phase 3: drain legacy, then activate new.
        ledger.drain_legacy_writer()
        ledger.activate_new_writer()
        owner_new = ledger.write_audit_record("new-1")
        assert owner_new == ledger.new_writer_id

        # Phase 4: post-cutover. New writer owns all subsequent records.
        ledger.finalize_cutover()
        for i in range(3):
            owner = ledger.write_audit_record(f"post-{i}")
            assert owner == ledger.new_writer_id

        # Invariant: no corruption-window.
        assert ledger.has_corruption_window() is False

        # All records present, no gaps.
        assert len(ledger.records) == 3 + 1 + 1 + 3
        # No record is owned by an unknown writer.
        known_writers = {ledger.legacy_writer_id, ledger.new_writer_id}
        for rec_id, writer in ledger.records:
            assert writer in known_writers, f"{rec_id} owned by unknown {writer!r}"

    def test_ap_3_illegal_activate_before_drain_is_rejected(self) -> None:
        """The drain-before-activate ordering is the invariant. Trying
        to activate the new writer before legacy drain MUST raise
        (in production this is detected by the cutover-runbook check
        and the operator-hand-gate; in the test it is an assertion)."""
        ledger = BridgeAuditWriterCutoverLedger()
        ledger.begin_cutover_window()

        # Skip the drain step.
        with pytest.raises(AssertionError):
            ledger.activate_new_writer()

        # The state is still 'drain' — no records have been corrupted.
        assert ledger._state == "drain"
        assert ledger.has_corruption_window() is False


# ===========================================================================
# AP-4 — Cross-Welle FSM-state leak
# ===========================================================================


class TestAp4CrossWelleStateLeak:
    """AP-4: Welle-4 state-backing cutover must not leak FSM-state to Welle-5."""

    def test_ap_4_welle_5_read_under_its_own_prefix_does_not_see_welle_4_data(self) -> None:
        """A key written under the welle-4 prefix MUST NOT be visible
        to a welle-5 read for the same key."""
        ledger = StateBackingLeakLedger()

        # Welle-4 writes a state-backing entry.
        ledger.write(welle=4, key="persona-alpha-fsm-state", value="active")

        # Welle-5 reads the same key under its prefix — MUST return None.
        leaked = ledger.read(welle=5, key="persona-alpha-fsm-state")
        assert leaked is None, (
            "AP-4 violation: welle-5 read leaked welle-4 state-backing entry"
        )

        # Welle-4 can still read its own data.
        own = ledger.read(welle=4, key="persona-alpha-fsm-state")
        assert own == "active"

        # The keys under each prefix are disjoint.
        w4_keys = ledger.keys_under_prefix(4)
        w5_keys = ledger.keys_under_prefix(5)
        assert w4_keys == ("welle-4/persona-alpha-fsm-state",)
        assert w5_keys == ()

    def test_ap_4_welle_5_writes_are_invisible_to_welle_4_reads(self) -> None:
        """Symmetric to the first test: welle-5 writes MUST NOT be
        visible to welle-4 reads. The namespace boundary is bidirectional."""
        ledger = StateBackingLeakLedger()

        ledger.write(welle=5, key="persona-beta-fsm-state", value="inactive")

        leaked = ledger.read(welle=4, key="persona-beta-fsm-state")
        assert leaked is None

        own = ledger.read(welle=5, key="persona-beta-fsm-state")
        assert own == "inactive"


# ===========================================================================
# AP-5 — Sign-Off timestamp monotonicity
# ===========================================================================


class TestAp5SignOffTimestampDrift:
    """AP-5: Sign-Off timestamps must be monotonically ascending KW-24..KW-27."""

    def test_ap_5_canonical_marathon_trace_is_strictly_monotonic(self) -> None:
        """The ADR-0066 four-Wochen-Cadence timestamps MUST be strictly
        ascending in both KW and ISO-time dimensions."""
        rows = signoff_isos_in_kw_order()

        assert len(rows) == 4
        kws = [kw for kw, _ in rows]
        assert kws == [24, 25, 26, 27]

        # All timestamps parse and ascend strictly.
        parsed = [_parse_iso(ts) for _, ts in rows]
        for i in range(1, len(parsed)):
            assert parsed[i] > parsed[i - 1], (
                f"AP-5 violation: signoff KW-{rows[i][0]} timestamp {rows[i][1]} "
                f"is not strictly after KW-{rows[i-1][0]} {rows[i-1][1]}"
            )

        # The monotonicity oracle agrees.
        assert is_strictly_monotonic_in_kw_order(rows) is True

    def test_ap_5_drift_violating_sequence_is_rejected(self) -> None:
        """A synthetic out-of-order sequence (e.g. KW-26 sign-off before
        KW-25 sign-off) MUST be detected by the monotonicity oracle."""
        # Build a drift-violating tuple: swap KW-25 and KW-26 timestamps.
        canonical = list(signoff_isos_in_kw_order())
        # Swap the two middle timestamps' isos but keep their kw labels.
        drifted: List[Tuple[int, str]] = [
            (canonical[0][0], canonical[0][1]),
            (canonical[1][0], canonical[2][1]),  # KW-25 now carries KW-26's iso
            (canonical[2][0], canonical[1][1]),  # KW-26 now carries KW-25's iso
            (canonical[3][0], canonical[3][1]),
        ]

        assert is_strictly_monotonic_in_kw_order(drifted) is False

        # Another violation: same iso twice (not strictly ascending).
        same_iso: List[Tuple[int, str]] = [
            (24, "2026-06-12T17:00:00+02:00"),
            (25, "2026-06-12T17:00:00+02:00"),
            (26, "2026-06-26T17:00:00+02:00"),
            (27, "2026-07-03T17:00:00+02:00"),
        ]
        assert is_strictly_monotonic_in_kw_order(same_iso) is False


# ===========================================================================
# AP-6 — AR-Hand ratification bypass
# ===========================================================================


class TestAp6ArHandBypass:
    """AP-6: AC-5 cannot be satisfied by a dummy file with wrong shape."""

    def test_ap_6_canonical_stamp_is_admissible(self) -> None:
        """A correctly-named file with the required payload shape MUST
        be admitted by the AP-6 oracle."""
        candidate = ArHandStampCandidate(
            filename=AR_HAND_STAMP_FILENAME,
            payload={
                "ar_hand_ratification": True,
                "ar_hand_quote": "ratified per AR-session 2026-07-03",
                "timestamp_utc": "2026-07-03T15:00:00Z",
            },
        )
        assert candidate.is_admissible() is True

    def test_ap_6_bypass_attempts_are_rejected(self) -> None:
        """Eight bypass variants — wrong filename, missing key, wrong
        boolean, empty quote, wrong types — MUST all be rejected."""
        base_payload = {
            "ar_hand_ratification": True,
            "ar_hand_quote": "ratified",
            "timestamp_utc": "2026-07-03T15:00:00Z",
        }

        # Wrong filename.
        wrong_name = ArHandStampCandidate(
            filename="state/ar-hand-fake-stamp.json",
            payload=base_payload,
        )
        assert wrong_name.is_admissible() is False

        # Missing ar_hand_ratification.
        no_rat = ArHandStampCandidate(
            filename=AR_HAND_STAMP_FILENAME,
            payload={
                "ar_hand_quote": "ratified",
                "timestamp_utc": "2026-07-03T15:00:00Z",
            },
        )
        assert no_rat.is_admissible() is False

        # ar_hand_ratification=False.
        false_rat = ArHandStampCandidate(
            filename=AR_HAND_STAMP_FILENAME,
            payload={
                "ar_hand_ratification": False,
                "ar_hand_quote": "ratified",
                "timestamp_utc": "2026-07-03T15:00:00Z",
            },
        )
        assert false_rat.is_admissible() is False

        # ar_hand_ratification as string "True" (type-strict rejection).
        wrong_type = ArHandStampCandidate(
            filename=AR_HAND_STAMP_FILENAME,
            payload={
                "ar_hand_ratification": "True",
                "ar_hand_quote": "ratified",
                "timestamp_utc": "2026-07-03T15:00:00Z",
            },
        )
        assert wrong_type.is_admissible() is False

        # Empty ar_hand_quote.
        empty_quote = ArHandStampCandidate(
            filename=AR_HAND_STAMP_FILENAME,
            payload={
                "ar_hand_ratification": True,
                "ar_hand_quote": "",
                "timestamp_utc": "2026-07-03T15:00:00Z",
            },
        )
        assert empty_quote.is_admissible() is False

        # Whitespace-only quote (treated as empty).
        ws_quote = ArHandStampCandidate(
            filename=AR_HAND_STAMP_FILENAME,
            payload={
                "ar_hand_ratification": True,
                "ar_hand_quote": "   \t\n  ",
                "timestamp_utc": "2026-07-03T15:00:00Z",
            },
        )
        assert ws_quote.is_admissible() is False

        # Missing timestamp_utc.
        no_ts = ArHandStampCandidate(
            filename=AR_HAND_STAMP_FILENAME,
            payload={
                "ar_hand_ratification": True,
                "ar_hand_quote": "ratified",
            },
        )
        assert no_ts.is_admissible() is False

        # ar_hand_quote as non-string.
        non_str_quote = ArHandStampCandidate(
            filename=AR_HAND_STAMP_FILENAME,
            payload={
                "ar_hand_ratification": True,
                "ar_hand_quote": ["ratified"],
                "timestamp_utc": "2026-07-03T15:00:00Z",
            },
        )
        assert non_str_quote.is_admissible() is False


# ===========================================================================
# AP-7 — IIA-1130 Welle-7 self-audit trap
# ===========================================================================


class TestAp7Iia1130Welle7SelfAuditTrap:
    """AP-7: Henrik's sign-off on Welle-7 must be rejected; AR-Hand only."""

    def test_ap_7_henrik_internal_audit_signer_is_rejected(self) -> None:
        """A submission with signer_role='henrik_internal_audit' MUST
        be rejected with the IIA-1130 archive flag as the reason."""
        submission = Welle7SignOffSubmission(
            signer_role="henrik_internal_audit",
            signer_id="henrik-voss",
            payload={
                "welle_7_pre_auditor_decision_present": True,
                "iia_1130_independence_anchor": "henrik-self-anchored",
            },
        )

        admitted, reason = admit_welle_7_signoff(submission)
        assert admitted is False
        assert "IIA-1130" in reason
        assert "Internal Audit" in reason
        assert "REJECTED" in reason

        # Other roles outside the {ar_hand} allow-list also rejected.
        for foreign_role in ("mira_ceo", "tomas_engineering", "ad_hoc_external"):
            sub = Welle7SignOffSubmission(
                signer_role=foreign_role,
                signer_id="x",
                payload={
                    "welle_7_pre_auditor_decision_present": True,
                    "iia_1130_independence_anchor": "anchor-x",
                },
            )
            adm, why = admit_welle_7_signoff(sub)
            assert adm is False, f"role {foreign_role!r} unexpectedly admitted"
            assert "rejected" in why

    def test_ap_7_ar_hand_signer_with_complete_payload_is_admitted(self) -> None:
        """An AR-Hand submission with the welle-7 pre-auditor-decision
        plus the IIA-1130 independence-anchor MUST be admitted."""
        submission = Welle7SignOffSubmission(
            signer_role="ar_hand",
            signer_id="ar-hand-session-kw-27",
            payload={
                "welle_7_pre_auditor_decision_present": True,
                "iia_1130_independence_anchor": "ar-hand-kw-27-anchor",
            },
        )
        admitted, reason = admit_welle_7_signoff(submission)
        assert admitted is True
        assert reason == "admitted"

        # AR-Hand without the pre-auditor-decision is rejected.
        no_decision = replace(
            submission,
            payload={
                # No welle_7_pre_auditor_decision_present.
                "iia_1130_independence_anchor": "ar-hand-kw-27-anchor",
            },
        )
        adm, why = admit_welle_7_signoff(no_decision)
        assert adm is False
        assert "welle_7_pre_auditor_decision_present" in why

        # AR-Hand without the independence-anchor is rejected.
        no_anchor = replace(
            submission,
            payload={
                "welle_7_pre_auditor_decision_present": True,
                # No iia_1130_independence_anchor.
            },
        )
        adm, why = admit_welle_7_signoff(no_anchor)
        assert adm is False
        assert "iia_1130_independence_anchor" in why


# ===========================================================================
# AP-8 — Cutover-day timing drift
# ===========================================================================


class TestAp8CutoverTimingDrift:
    """AP-8: cutover only Mo-Fr 09:00-14:00 CEST; off-windows rejected."""

    def test_ap_8_canonical_cutover_mittwoche_are_in_window(self) -> None:
        """The four Cutover-Mittwoche from MARATHON_TRACE_TIMESTAMPS all
        fall within the Mo-Fr 09:00-14:00 CEST window."""
        for kw, mw_iso, _do_iso, _fr_iso in MARATHON_TRACE_TIMESTAMPS:
            ts = _parse_iso(mw_iso)
            assert is_within_cutover_window(ts), (
                f"AP-8 violation: KW-{kw} Cutover-Mittwoch {mw_iso} "
                "is not in the Mo-Fr 09-14 CEST window"
            )
            # Spot-check: Wednesday = weekday 2.
            assert ts.weekday() == 2, (
                f"KW-{kw} Cutover-Mittwoch fell on weekday {ts.weekday()}, "
                "expected 2 (Wednesday)"
            )

    def test_ap_8_off_window_timestamps_are_rejected(self) -> None:
        """Various off-window timestamps — night, weekend, before 9,
        after 14 — MUST all be rejected by the window oracle."""
        cest = _dt.timezone(_dt.timedelta(hours=2))

        # Saturday 11:00 — weekend.
        saturday = _dt.datetime(2026, 6, 13, 11, 0, tzinfo=cest)
        assert saturday.weekday() == 5
        assert is_within_cutover_window(saturday) is False

        # Sunday 11:00 — weekend.
        sunday = _dt.datetime(2026, 6, 14, 11, 0, tzinfo=cest)
        assert sunday.weekday() == 6
        assert is_within_cutover_window(sunday) is False

        # Wednesday 02:00 — night (before 09).
        wed_night = _dt.datetime(2026, 6, 10, 2, 0, tzinfo=cest)
        assert is_within_cutover_window(wed_night) is False

        # Wednesday 08:59 — one minute before 09:00.
        wed_just_before = _dt.datetime(2026, 6, 10, 8, 59, tzinfo=cest)
        assert is_within_cutover_window(wed_just_before) is False

        # Wednesday 14:00 — exactly at the upper bound (exclusive).
        wed_at_upper = _dt.datetime(2026, 6, 10, 14, 0, tzinfo=cest)
        assert is_within_cutover_window(wed_at_upper) is False

        # Wednesday 14:30 — after window.
        wed_after = _dt.datetime(2026, 6, 10, 14, 30, tzinfo=cest)
        assert is_within_cutover_window(wed_after) is False

        # Wednesday 23:00 — late night.
        wed_late = _dt.datetime(2026, 6, 10, 23, 0, tzinfo=cest)
        assert is_within_cutover_window(wed_late) is False

        # Confirm a known-good control case still passes.
        wed_in_window = _dt.datetime(2026, 6, 10, 9, 0, tzinfo=cest)
        assert is_within_cutover_window(wed_in_window) is True


# ===========================================================================
# AP-9 — Rollback cascade
# ===========================================================================


class TestAp9RollbackCascade:
    """AP-9: Welle-3 rollback blocks Welle-4..7 cutover; marker not set."""

    def test_ap_9_welle_3_rollback_blocks_all_subsequent_wellen(self) -> None:
        """If Welle-3 rolls back, the cascade MUST mark Welle-4..7 as
        blocked and the aggregate marker MUST be inadmissible."""
        verdict = apply_welle_3_rollback_cascade(rollback_welle_numbers=[3])

        assert verdict.welle_3_rolled_back is True
        # Welle-3 plus Welle-4..7 are blocked.
        assert set(verdict.blocked_wellen) == {3, 4, 5, 6, 7}
        # Marker MUST NOT be admissible.
        assert verdict.marker_admissible is False
        assert "welle-3" in verdict.blocking_reason.lower()

        # Cross-check via the Tag-40 state-machine: a Welle-3 rollback
        # plus six green sign-offs MUST still fail the marker.
        markers_by_num: Dict[int, SignOffMarker] = {}
        for w, kw in ((1, 24), (2, 24), (3, 25), (4, 26), (5, 26), (6, 27), (7, 27)):
            if w == 3:
                markers_by_num[w] = SignOffMarker(
                    welle_number=3,
                    status="rolled-back",
                    ac_1_5_green=False,
                    ac_4_consensus_personas=frozenset(),
                    cross_welle_drift_assert="blocker",
                    cutover_iso="2026-06-17T09:00:00+02:00",
                    signoff_iso="2026-06-19T17:00:00+02:00",
                )
            else:
                markers_by_num[w] = _make_green_signoff_marker(w, kw)
        # All Welle-Ende-Gates green (we are testing the cascade-rule,
        # not the WE-1..WE-4 rule).
        we_gates = {g: True for g in WELLE_ENDE_GATES}
        sm = Phase3CompleteMarkerStateMachine(
            markers=markers_by_num, welle_ende_gates=we_gates
        )
        sm_verdict = sm.compute_verdict()
        assert sm_verdict.phase_3_complete is False
        assert sm_verdict.cascade_blocked is True

    def test_ap_9_no_rollback_yields_admissible_marker_path(self) -> None:
        """Empty rollback-set MUST yield a not-yet-blocked verdict and
        the marker-admissible flag MUST be True at this layer (other
        AC-checks still apply downstream)."""
        verdict = apply_welle_3_rollback_cascade(rollback_welle_numbers=[])

        assert verdict.welle_3_rolled_back is False
        assert verdict.blocked_wellen == ()
        assert verdict.marker_admissible is True
        assert verdict.blocking_reason == ""

        # An isolated Welle-6 rollback (which is post-Welle-3 in the
        # cascade direction) does NOT cascade backwards; only Welle-3
        # has cascade semantics (per the runbook). Welle-6 rollback
        # alone still blocks the marker (because Welle-6 sign-off is
        # missing) but does not block Welle-4..5.
        v6 = apply_welle_3_rollback_cascade(rollback_welle_numbers=[6])
        assert v6.welle_3_rolled_back is False
        assert v6.blocked_wellen == (6,)
        # Marker not admissible because at least one Welle did roll back.
        assert v6.marker_admissible is False


# ===========================================================================
# AP-10 — COMPLETE-marker false-positive via empty state-files
# ===========================================================================


class TestAp10EmptyStateFileFalsePositive:
    """AP-10: empty / missing state-files MUST block, not pass."""

    def test_ap_10_empty_or_minimal_payloads_fail_all_probes(self) -> None:
        """Six degenerate payloads — empty string, ``{}``, whitespace,
        non-JSON, JSON-array, JSON-null — MUST fail every AC probe."""
        degenerate_payloads = [
            "",
            "{}",
            "   \n\t  ",
            "not json at all",
            "[]",
            "null",
        ]

        for payload in degenerate_payloads:
            assert state_file_passes_ac1_probe(payload) is False, (
                f"AP-10 violation: AC-1 admitted degenerate payload {payload!r}"
            )
            assert state_file_passes_ac3_probe(payload, expected=(15, 15)) is False, (
                f"AP-10 violation: AC-3 admitted degenerate payload {payload!r}"
            )
            assert state_file_passes_ac4_probe(payload) is False, (
                f"AP-10 violation: AC-4 admitted degenerate payload {payload!r}"
            )
            assert state_file_passes_ac5_probe(payload) is False, (
                f"AP-10 violation: AC-5 admitted degenerate payload {payload!r}"
            )

    def test_ap_10_well_shaped_payloads_pass_their_respective_probes(self) -> None:
        """Confirms the negative result above is not a false-rejection:
        well-shaped payloads pass their respective probes."""
        # AC-1: sign-off with status=green.
        ac1_payload = json.dumps(
            {"sign_off_status": "green", "commit_sha": "abc"}
        )
        assert state_file_passes_ac1_probe(ac1_payload) is True
        # AC-1: yellow_henrik_hand_approval also passes.
        ac1_yellow = json.dumps(
            {"sign_off_status": "yellow_henrik_hand_approval", "commit_sha": "abc"}
        )
        assert state_file_passes_ac1_probe(ac1_yellow) is True
        # AC-1: other status values fail.
        ac1_red = json.dumps(
            {"sign_off_status": "red", "commit_sha": "abc"}
        )
        assert state_file_passes_ac1_probe(ac1_red) is False

        # AC-3: closure counts match expected.
        ac3_payload = json.dumps({"completed_count": 15, "total_count": 15})
        assert state_file_passes_ac3_probe(ac3_payload, expected=(15, 15)) is True
        # AC-3: mismatched count fails.
        ac3_short = json.dumps({"completed_count": 14, "total_count": 15})
        assert state_file_passes_ac3_probe(ac3_short, expected=(15, 15)) is False

        # AC-4: verdict ratified + all R-A1..R-A6 verified.
        ac4_payload = json.dumps(
            {
                "verdict": "ratified",
                "r_a_mitigation_status": {
                    "R-A1": "verified",
                    "R-A2": "verified",
                    "R-A3": "verified",
                    "R-A4": "verified",
                    "R-A5": "verified",
                    "R-A6": "verified",
                },
            }
        )
        assert state_file_passes_ac4_probe(ac4_payload) is True
        # AC-4: one R-A flag missing → fail.
        ac4_short = json.dumps(
            {
                "verdict": "ratified",
                "r_a_mitigation_status": {
                    "R-A1": "verified",
                    "R-A2": "verified",
                    "R-A3": "verified",
                    "R-A4": "verified",
                    "R-A5": "verified",
                    # R-A6 missing.
                },
            }
        )
        assert state_file_passes_ac4_probe(ac4_short) is False

        # AC-5: ar_hand_ratification=True + non-empty quote.
        ac5_payload = json.dumps(
            {
                "ar_hand_ratification": True,
                "ar_hand_quote": "ratified per AR-session 2026-07-03",
                "timestamp_utc": "2026-07-03T15:00:00Z",
            }
        )
        assert state_file_passes_ac5_probe(ac5_payload) is True
        # AC-5: quote whitespace-only → fail.
        ac5_ws = json.dumps(
            {
                "ar_hand_ratification": True,
                "ar_hand_quote": "   ",
                "timestamp_utc": "2026-07-03T15:00:00Z",
            }
        )
        assert state_file_passes_ac5_probe(ac5_ws) is False
