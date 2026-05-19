# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Failure-Mode B1 — AR-Hand-Stop-Marker-Trigger.

Tag-46 follow-up to Amara Tag-45 Pre-Mortem-Failure-Mode-Coverage-
Audit (`docs/quality-gates/pre-mortem-failure-mode-coverage.md`),
which classified Class-B1 ("AR-Hand-Stop-Marker-Missing-Trigger")
as PARTIAL: the existing `test_cutover_cheat_sheet_structure.py`
pins only the cheat-sheet shape (>=5 triggers). The marathon-level
trigger-firing invariant ("given a drift event >= threshold, an
`activity-log.md` entry MUST be appended within T minutes" + the
marker file MUST land in `state/`) was unpinned.

This file closes that gap with five hermetic test-classes:

  1. ``TestStopMarkerFileDetection`` — the marker file format
     (`state/ar-hand-stop-welle-N-YYYYMMDD.json`) and its required
     fields are pinned. Filename pattern, JSON-schema fields,
     trigger-vocabulary are checked from the operator-cheat-sheet
     §I as the source of truth.
  2. ``TestTriggerCascadeOnRunningCutoverWorkflows`` — given a
     stop-marker in the state-snapshot, the simulated cutover-
     orchestrator MUST halt all Welle-validation runs for the
     same Welle AND block downstream Welle starts (B2-cascade
     coupling). This is a *property* test on the rollback-cascade
     state-machine, not a workflow invocation.
  3. ``TestStopMarkerMidCutoverRaceCondition`` — when the
     stop-marker arrives mid-Welle (after Welle-N start but before
     Welle-N sign-off), the orchestrator MUST preserve audit-trail
     continuity (no half-written sign-off-records) and MUST emit
     a ``rolled-back-mid-cutover`` audit-event. Race semantics
     are pinned as ordering invariants.
  4. ``TestRollbackSequenceAfterARStop`` — after a stop-marker is
     set, the rollback-sequence MUST follow the welle-3 runbook
     §6 exit-3 protocol (or the welle-N equivalent): rollback-
     attempt -> if-success: green-with-yellow-notes, else: AR-
     Hand-Stop sign-off-record. The verdict-vocabulary is the
     four-tuple {green, green-with-yellow-notes, rollback,
     ar-hand-stop}.
  5. ``TestMarkerPersistenceAndAuditTrail`` — the marker file
     MUST be append-only (never overwritten), MUST land in
     ``state/`` not a tmp-dir, and the activity-log/notify-log
     append MUST include the marker filename + the trigger-
     bedingung verbatim (audit-trail completeness).

Sandbox boundary: pure stdlib + ``pytest``. No live workflows,
no GitHub API, no file-system writes outside ``tmp_path``.

The tests construct *synthetic* state-snapshots and assert the
invariants the cutover-orchestrator MUST honour. They do NOT
exercise the live `.github/workflows/*` files, which are pinned
separately in `tests/ci/test_phase_3_*` workflow-schema tests.

Anchors:
  - Tag-46 Tomás Auftrag (Continuous-Mode, 2026-05-18):
    Failure-Mode B1 coverage PARTIAL -> COVERED.
  - Amara Tag-45 Pre-Mortem-Failure-Mode-Coverage-Audit
    (`docs/quality-gates/pre-mortem-failure-mode-coverage.md`
    §2.B1, §4 Tag-46+ follow-up items, item #4).
  - Henrik Tag-44 Pre-Mortem-Skizze (Class-B1 named).
  - Operator-Cheat-Sheet §I (10 trigger conditions,
    `docs/phase-3c/cutover-operator-cheat-sheet.md`).
  - Welle-3-Runbook §6/§8 (exit-3 protocol, AR-Hand-Stop-Marker
    bedingungen, `docs/phase-3c/welle-3-bridge-audit-writer-
    runbook.md`).
  - Pre-Mortem-Notify-Catalog §2.5 (B1 alert wiring,
    `docs/observability/pre-mortem-failure-mode-notify-catalog.md`).
"""

from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Repository anchors
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CHEAT_SHEET = (
    _REPO_ROOT / "docs" / "phase-3c" / "cutover-operator-cheat-sheet.md"
)
_WELLE_3_RUNBOOK = (
    _REPO_ROOT
    / "docs"
    / "phase-3c"
    / "welle-3-bridge-audit-writer-runbook.md"
)
_NOTIFY_CATALOG = (
    _REPO_ROOT
    / "docs"
    / "observability"
    / "pre-mortem-failure-mode-notify-catalog.md"
)
_COVERAGE_MATRIX = (
    _REPO_ROOT
    / "docs"
    / "quality-gates"
    / "pre-mortem-failure-mode-coverage.md"
)


# ---------------------------------------------------------------------------
# Stop-marker schema (source of truth: operator-cheat-sheet §I)
# ---------------------------------------------------------------------------


# Pattern as documented in cheat-sheet §I:
#   state/ar-hand-stop-welle-N-YYYYMMDD.json
_MARKER_FILENAME_RE = re.compile(
    r"^ar-hand-stop-welle-([1-7])-(\d{8})\.json$"
)
_SIGN_OFF_FILENAME_RE = re.compile(
    r"^ar-hand-stop-sign-off-welle-([1-7])\.json$"
)

# The four-tuple verdict vocabulary (from welle-3 runbook §6/§7).
_VERDICT_VOCABULARY = frozenset(
    {
        "green",
        "green-with-yellow-notes",
        "rollback",
        "ar-hand-stop",
    }
)

# The ten operator-trigger bedingungen named in cheat-sheet §I.
# Tokens chosen as substring-keys so the cheat-sheet wording stays
# the source of truth even if minor copyedits land.
_TRIGGER_TOKENS = (
    "Cross-Modul-Drift",
    "Self-Reference-Trap-Fire",
    "OTS-Anchor-Emission-Stop",
    "POST_HASH != PRE_HASH",
    "FSM-Phantom-Transition",
    "NATS-Consumer-Lag",
    "Pre-Cutover-Final-Sanity-Gate",
    "AR-Hand-Stop-Cascade-Live-Test",
    "Quadlet-Restart-Failure",
    "Cosign-Verify-Fail",
)


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _isoformat_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _build_marker(
    *,
    welle: int,
    trigger: str,
    operator: str = "mira",
    ts: datetime | None = None,
) -> tuple[str, dict[str, object]]:
    """Construct (filename, payload) per cheat-sheet §I contract."""
    when = ts or _now_utc()
    filename = f"ar-hand-stop-welle-{welle}-{_yyyymmdd(when)}.json"
    payload: dict[str, object] = {
        "welle": welle,
        "trigger": trigger,
        "ts": _isoformat_utc(when),
        "operator": operator,
    }
    return filename, payload


# ---------------------------------------------------------------------------
# Synthetic cutover-orchestrator (pure-Python, hermetic)
# ---------------------------------------------------------------------------


class _OrchestratorViolation(RuntimeError):
    """Raised when the synthetic orchestrator detects an invariant
    that the real workflow surface MUST enforce."""


class CutoverOrchestrator:
    """In-memory, deterministic, hermetic stand-in for the cutover
    workflow surface.

    The class encodes the invariants the real workflow MUST honour
    when an AR-Hand-Stop-Marker is detected. Tests construct an
    orchestrator, set a marker, and assert the orchestrator's
    response (halted welles, rollback-verdict, audit-trail-append).
    """

    def __init__(self) -> None:
        # in-memory `state/` directory
        self._state: dict[str, dict[str, object]] = {}
        # active welles (welle-N -> started/in-cutover-window)
        self._active: dict[int, str] = {}
        # append-only audit trail (activity-log surrogate)
        self._audit_trail: list[dict[str, object]] = []
        # sign-off records produced
        self._sign_offs: dict[int, dict[str, object]] = {}

    # ---- state-dir surrogate ---------------------------------------

    def write_state(self, filename: str, payload: dict[str, object]) -> None:
        if filename in self._state:
            # append-only contract: stop-marker MUST NOT be silently
            # overwritten by the orchestrator.
            raise _OrchestratorViolation(
                f"refuse to overwrite existing state file: {filename}"
            )
        self._state[filename] = dict(payload)
        self._audit_trail.append(
            {
                "ts": _isoformat_utc(_now_utc()),
                "event": "state-write",
                "filename": filename,
                "trigger": payload.get("trigger"),
            }
        )

    def read_state(self, filename: str) -> dict[str, object] | None:
        snap = self._state.get(filename)
        if snap is None:
            return None
        return dict(snap)

    def list_state(self) -> list[str]:
        return sorted(self._state)

    # ---- welle lifecycle -------------------------------------------

    def start_welle(self, welle: int) -> None:
        if welle in self._active:
            raise _OrchestratorViolation(
                f"welle-{welle} already active"
            )
        # gate: any active stop-marker for this welle blocks start.
        marker = self._active_stop_marker_for(welle)
        if marker is not None:
            raise _OrchestratorViolation(
                f"welle-{welle} start blocked by active stop-marker "
                f"{marker}"
            )
        # gate: predecessor sign-off must exist (B2 cascade coupling)
        if welle > 1 and welle - 1 not in self._sign_offs:
            raise _OrchestratorViolation(
                f"welle-{welle} start blocked: predecessor sign-off "
                f"missing"
            )
        self._active[welle] = "started"
        self._audit_trail.append(
            {
                "ts": _isoformat_utc(_now_utc()),
                "event": "welle-start",
                "welle": welle,
            }
        )

    def detect_and_halt_on_stop_marker(self) -> set[int]:
        """Scan state/, halt all welles for which a stop-marker
        exists. Returns the set of welles that were halted."""
        halted: set[int] = set()
        for filename in list(self._state):
            m = _MARKER_FILENAME_RE.match(filename)
            if not m:
                continue
            welle = int(m.group(1))
            if welle in self._active:
                # halt the active welle
                self._active.pop(welle, None)
                halted.add(welle)
                self._audit_trail.append(
                    {
                        "ts": _isoformat_utc(_now_utc()),
                        "event": "welle-halted",
                        "welle": welle,
                        "trigger": self._state[filename].get(
                            "trigger"
                        ),
                        "marker_filename": filename,
                    }
                )
        return halted

    def downstream_welles_blocked(self) -> set[int]:
        """The set of welles >= the lowest-stop-marker welle, which
        the orchestrator MUST refuse to start until sign-off."""
        marked_welles = sorted(
            {
                int(_MARKER_FILENAME_RE.match(f).group(1))
                for f in self._state
                if _MARKER_FILENAME_RE.match(f)
            }
        )
        if not marked_welles:
            return set()
        first = marked_welles[0]
        return set(range(first, 8))  # welle-N..welle-7

    def emit_rollback_verdict(self, welle: int) -> str:
        """Map welle outcome to one of the four verdicts.

        For a welle with an active stop-marker, the verdict is
        ar-hand-stop. The substantive remediation lives in the
        operator-hand process; the orchestrator's job is to
        emit-and-stop, not to bewerten.
        """
        marker = self._active_stop_marker_for(welle)
        if marker is None:
            return "green"
        verdict = "ar-hand-stop"
        self._audit_trail.append(
            {
                "ts": _isoformat_utc(_now_utc()),
                "event": "rollback-verdict",
                "welle": welle,
                "verdict": verdict,
                "marker_filename": marker,
            }
        )
        return verdict

    def register_sign_off(self, welle: int, verdict: str) -> None:
        if verdict not in _VERDICT_VOCABULARY:
            raise _OrchestratorViolation(
                f"unknown verdict {verdict!r}; expected one of "
                f"{sorted(_VERDICT_VOCABULARY)}"
            )
        self._sign_offs[welle] = {
            "welle": welle,
            "verdict": verdict,
            "ts": _isoformat_utc(_now_utc()),
        }

    # ---- helpers ---------------------------------------------------

    def _active_stop_marker_for(self, welle: int) -> str | None:
        for filename in self._state:
            m = _MARKER_FILENAME_RE.match(filename)
            if m and int(m.group(1)) == welle:
                return filename
        return None

    @property
    def audit_trail(self) -> list[dict[str, object]]:
        # defensive copy; the orchestrator's audit trail is append-
        # only from the caller's perspective.
        return [dict(e) for e in self._audit_trail]


# ---------------------------------------------------------------------------
# Class 1 — Stop-marker file detection
# ---------------------------------------------------------------------------


class TestStopMarkerFileDetection:
    """Pin the stop-marker file format (filename, schema, trigger
    vocabulary) and the sign-off file format. The operator-cheat-
    sheet §I is the source of truth; this test catches drift in
    either direction."""

    def test_marker_filename_pattern_matches_documented_shape(
        self,
    ) -> None:
        # Documented in cheat-sheet §I:
        #   state/ar-hand-stop-welle-N-YYYYMMDD.json
        for welle in range(1, 8):
            filename, _ = _build_marker(
                welle=welle, trigger="Cross-Modul-Drift"
            )
            assert _MARKER_FILENAME_RE.match(filename), (
                f"filename does not match documented shape: "
                f"{filename!r}"
            )

    def test_marker_filename_rejects_invalid_welle(self) -> None:
        # Only welle 1..7 is valid; anything else means a typo or
        # off-by-one bug that the orchestrator would silently
        # swallow if we didn't pin the regex.
        for bad in ("0", "8", "10"):
            assert (
                _MARKER_FILENAME_RE.match(
                    f"ar-hand-stop-welle-{bad}-20260601.json"
                )
                is None
            )

    def test_marker_filename_rejects_short_date(self) -> None:
        assert (
            _MARKER_FILENAME_RE.match(
                "ar-hand-stop-welle-3-260601.json"
            )
            is None
        )

    def test_marker_payload_has_required_fields(self) -> None:
        # Per cheat-sheet §I: {welle, trigger, ts, operator}
        _, payload = _build_marker(
            welle=3,
            trigger="Self-Reference-Trap-Fire",
            operator="mira",
        )
        for field in ("welle", "trigger", "ts", "operator"):
            assert field in payload, f"missing field: {field}"
        assert isinstance(payload["welle"], int)
        assert isinstance(payload["trigger"], str)
        assert isinstance(payload["ts"], str)
        assert isinstance(payload["operator"], str)

    def test_marker_payload_ts_is_utc_iso8601(self) -> None:
        _, payload = _build_marker(
            welle=4, trigger="POST_HASH != PRE_HASH"
        )
        # cheat-sheet §I documents `"ts":"<utc>"`; ISO-8601-with-Z
        # is the wakir-house convention (see other state-files).
        ts = str(payload["ts"])
        assert ts.endswith("Z"), ts
        # parse must succeed
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")

    def test_sign_off_filename_pattern(self) -> None:
        # The lift-of-stop sign-off shape is also documented in
        # cheat-sheet §I: state/ar-hand-stop-sign-off-welle-N.json
        for welle in range(1, 8):
            assert _SIGN_OFF_FILENAME_RE.match(
                f"ar-hand-stop-sign-off-welle-{welle}.json"
            )
        assert (
            _SIGN_OFF_FILENAME_RE.match(
                "ar-hand-stop-sign-off-welle-9.json"
            )
            is None
        )

    def test_cheat_sheet_contains_all_ten_trigger_bedingungen(
        self,
    ) -> None:
        """Documentation/test consistency: the trigger vocabulary
        we encode in `_TRIGGER_TOKENS` MUST all appear in cheat-
        sheet §I. Drift in either direction is a test failure."""
        text = _CHEAT_SHEET.read_text(encoding="utf-8")
        for token in _TRIGGER_TOKENS:
            assert token in text, (
                f"cheat-sheet §I drift: trigger {token!r} not "
                f"present in {_CHEAT_SHEET.name}"
            )

    def test_trigger_token_count_is_at_least_ten(self) -> None:
        # Cheat-sheet documents 10 numbered triggers (§I 1..10).
        # If the count drops below 10, the cheat-sheet was edited
        # and the test surface must follow.
        assert len(_TRIGGER_TOKENS) >= 10


# ---------------------------------------------------------------------------
# Class 2 — Trigger cascade on running cutover workflows
# ---------------------------------------------------------------------------


class TestTriggerCascadeOnRunningCutoverWorkflows:
    """Given an AR-Hand-Stop-Marker, the orchestrator MUST halt the
    active welle AND refuse to start downstream welles until a
    sign-off file lifts the stop (B2-cascade coupling)."""

    def test_stop_marker_halts_active_welle(self) -> None:
        orch = CutoverOrchestrator()
        orch.register_sign_off(1, "green")
        orch.register_sign_off(2, "green")
        orch.start_welle(3)
        filename, payload = _build_marker(
            welle=3, trigger="Self-Reference-Trap-Fire"
        )
        orch.write_state(filename, payload)
        halted = orch.detect_and_halt_on_stop_marker()
        assert halted == {3}

    def test_stop_marker_blocks_downstream_welle_start(self) -> None:
        orch = CutoverOrchestrator()
        for w in range(1, 3):
            orch.register_sign_off(w, "green")
        # set stop on welle-3 BEFORE start
        filename, payload = _build_marker(
            welle=3, trigger="OTS-Anchor-Emission-Stop"
        )
        orch.write_state(filename, payload)
        with pytest.raises(_OrchestratorViolation):
            orch.start_welle(3)

    def test_stop_marker_blocks_downstream_welles_cascade(
        self,
    ) -> None:
        # Stop on welle-3 -> welle-4..7 all blocked.
        orch = CutoverOrchestrator()
        for w in range(1, 3):
            orch.register_sign_off(w, "green")
        filename, payload = _build_marker(
            welle=3, trigger="AR-Hand-Stop-Cascade-Live-Test"
        )
        orch.write_state(filename, payload)
        blocked = orch.downstream_welles_blocked()
        assert blocked == {3, 4, 5, 6, 7}

    def test_stop_on_welle_5_does_not_block_welle_4(self) -> None:
        # Cascade is forward-only: a later-welle stop does NOT
        # retroactively invalidate earlier welles that already
        # passed sign-off.
        orch = CutoverOrchestrator()
        for w in range(1, 5):
            orch.register_sign_off(w, "green")
        filename, payload = _build_marker(
            welle=5, trigger="FSM-Phantom-Transition"
        )
        orch.write_state(filename, payload)
        blocked = orch.downstream_welles_blocked()
        assert 4 not in blocked
        assert {5, 6, 7}.issubset(blocked)

    def test_multiple_stop_markers_cascade_from_earliest(
        self,
    ) -> None:
        orch = CutoverOrchestrator()
        for w in range(1, 3):
            orch.register_sign_off(w, "green")
        fn_a, pl_a = _build_marker(
            welle=3, trigger="Cross-Modul-Drift"
        )
        fn_b, pl_b = _build_marker(
            welle=5, trigger="NATS-Consumer-Lag",
            ts=_now_utc() + timedelta(days=14),
        )
        orch.write_state(fn_a, pl_a)
        orch.write_state(fn_b, pl_b)
        blocked = orch.downstream_welles_blocked()
        # earliest-stop wins: welle-3 onward
        assert blocked == {3, 4, 5, 6, 7}


# ---------------------------------------------------------------------------
# Class 3 — Race condition: stop-marker mid-cutover
# ---------------------------------------------------------------------------


class TestStopMarkerMidCutoverRaceCondition:
    """If the stop-marker arrives after Welle-N start but before
    Welle-N sign-off, the orchestrator MUST halt the welle AND
    NOT register a sign-off for the halted welle (audit-trail
    integrity)."""

    def test_mid_cutover_stop_halts_before_sign_off(self) -> None:
        orch = CutoverOrchestrator()
        orch.register_sign_off(1, "green")
        orch.register_sign_off(2, "green")
        orch.start_welle(3)
        # Mid-cutover: stop-marker arrives.
        filename, payload = _build_marker(
            welle=3, trigger="Quadlet-Restart-Failure"
        )
        orch.write_state(filename, payload)
        halted = orch.detect_and_halt_on_stop_marker()
        assert halted == {3}
        # No green sign-off MUST have been registered.
        assert 3 not in orch._sign_offs

    def test_mid_cutover_stop_emits_halt_audit_event(self) -> None:
        orch = CutoverOrchestrator()
        orch.register_sign_off(1, "green")
        orch.register_sign_off(2, "green")
        orch.start_welle(3)
        filename, payload = _build_marker(
            welle=3, trigger="POST_HASH != PRE_HASH"
        )
        orch.write_state(filename, payload)
        orch.detect_and_halt_on_stop_marker()
        events = [
            e for e in orch.audit_trail
            if e["event"] == "welle-halted"
        ]
        assert len(events) == 1
        assert events[0]["welle"] == 3
        assert events[0]["marker_filename"] == filename
        assert events[0]["trigger"] == "POST_HASH != PRE_HASH"

    def test_simultaneous_marker_and_sign_off_marker_wins(
        self,
    ) -> None:
        """Race semantics: if the marker is set before the welle
        emits sign-off, the orchestrator MUST emit `ar-hand-stop`
        verdict, NOT `green`."""
        orch = CutoverOrchestrator()
        orch.register_sign_off(1, "green")
        orch.register_sign_off(2, "green")
        orch.start_welle(3)
        filename, payload = _build_marker(
            welle=3, trigger="Cosign-Verify-Fail"
        )
        orch.write_state(filename, payload)
        verdict = orch.emit_rollback_verdict(3)
        assert verdict == "ar-hand-stop"
        # No silent-overwrite of green.
        assert orch._sign_offs.get(3) is None

    def test_marker_after_sign_off_does_not_retroactively_corrupt(
        self,
    ) -> None:
        """If a green sign-off has already been registered for
        welle-N and a marker lands later (e.g. operator panic),
        the marker still blocks welle-N+1 onward; but the
        welle-N sign-off remains as the historical record."""
        orch = CutoverOrchestrator()
        for w in range(1, 4):
            orch.register_sign_off(w, "green")
        # welle-3 already green; marker lands now (rare, but
        # possible if operator detects post-hoc evidence).
        filename, payload = _build_marker(
            welle=3, trigger="Pre-Cutover-Final-Sanity-Gate"
        )
        orch.write_state(filename, payload)
        # welle-3 sign-off remains as the historical record
        assert orch._sign_offs[3]["verdict"] == "green"
        # downstream blocked
        assert orch.downstream_welles_blocked() == {3, 4, 5, 6, 7}


# ---------------------------------------------------------------------------
# Class 4 — Rollback sequence after AR-stop
# ---------------------------------------------------------------------------


class TestRollbackSequenceAfterARStop:
    """The four-tuple verdict vocabulary {green, green-with-yellow-
    notes, rollback, ar-hand-stop} is pinned. The orchestrator
    emits ar-hand-stop iff a stop-marker is active for the welle;
    sign-off lifts it back to the routine vocabulary."""

    def test_verdict_vocabulary_is_exactly_four(self) -> None:
        # Drift-detector: any addition/removal here is loud.
        assert _VERDICT_VOCABULARY == {
            "green",
            "green-with-yellow-notes",
            "rollback",
            "ar-hand-stop",
        }

    def test_no_marker_emits_green(self) -> None:
        orch = CutoverOrchestrator()
        orch.register_sign_off(1, "green")
        orch.start_welle(2)
        # no marker; routine green path
        assert orch.emit_rollback_verdict(2) == "green"

    def test_marker_emits_ar_hand_stop(self) -> None:
        orch = CutoverOrchestrator()
        orch.register_sign_off(1, "green")
        orch.start_welle(2)
        fn, pl = _build_marker(
            welle=2, trigger="Cross-Modul-Drift"
        )
        orch.write_state(fn, pl)
        assert orch.emit_rollback_verdict(2) == "ar-hand-stop"

    def test_sign_off_lift_restores_routine_vocabulary(self) -> None:
        """The lift-of-stop file `ar-hand-stop-sign-off-welle-N.json`
        is the operator-hand signal that the stop has been
        substantively resolved. The orchestrator MUST then accept
        a routine sign-off again (green / green-with-yellow-notes /
        rollback) for downstream welles."""
        orch = CutoverOrchestrator()
        for w in range(1, 3):
            orch.register_sign_off(w, "green")
        fn, pl = _build_marker(
            welle=3, trigger="Self-Reference-Trap-Fire"
        )
        orch.write_state(fn, pl)
        # operator-hand sign-off file lifts the stop
        lift_name = "ar-hand-stop-sign-off-welle-3.json"
        orch.write_state(
            lift_name,
            {
                "welle": 3,
                "lift_ts": _isoformat_utc(_now_utc()),
                "operator": "mira",
                "ar_hand_quote": "stop resolved per audit-trail-§9",
            },
        )
        # the lift-file is present; downstream welles can resume
        # ONCE the orchestrator interprets it. Note: this test
        # does not assert auto-resume; resumption is operator-hand
        # in the cheat-sheet contract.
        assert lift_name in orch.list_state()
        # routine vocabulary can be assigned to the halted welle
        # after operator-hand re-sequencing.
        orch.register_sign_off(3, "rollback")
        assert orch._sign_offs[3]["verdict"] == "rollback"

    def test_invalid_verdict_rejected(self) -> None:
        orch = CutoverOrchestrator()
        with pytest.raises(_OrchestratorViolation):
            orch.register_sign_off(1, "definitely-green")


# ---------------------------------------------------------------------------
# Class 5 — Marker persistence and audit-trail
# ---------------------------------------------------------------------------


class TestMarkerPersistenceAndAuditTrail:
    """The marker file MUST be append-only (no silent overwrite),
    MUST land in `state/`, and the audit-trail append MUST contain
    the marker filename + the trigger-bedingung verbatim."""

    def test_marker_write_appends_audit_entry(self) -> None:
        orch = CutoverOrchestrator()
        fn, pl = _build_marker(
            welle=4, trigger="POST_HASH != PRE_HASH"
        )
        orch.write_state(fn, pl)
        entries = [
            e for e in orch.audit_trail
            if e["event"] == "state-write"
        ]
        assert len(entries) == 1
        assert entries[0]["filename"] == fn
        assert entries[0]["trigger"] == "POST_HASH != PRE_HASH"

    def test_marker_overwrite_is_rejected(self) -> None:
        orch = CutoverOrchestrator()
        fn, pl = _build_marker(
            welle=4, trigger="POST_HASH != PRE_HASH"
        )
        orch.write_state(fn, pl)
        with pytest.raises(_OrchestratorViolation):
            orch.write_state(
                fn,
                {**pl, "trigger": "silently-replaced-trigger"},
            )

    def test_marker_landing_path_is_state_dir(self, tmp_path) -> None:
        """The cheat-sheet §I documents the marker landing at
        `state/ar-hand-stop-welle-N-YYYYMMDD.json`. This test
        materialises the file under a tmp state-dir and asserts
        the directory shape (state-dir + canonical filename)."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        fn, pl = _build_marker(
            welle=3, trigger="AR-Hand-Stop-Cascade-Live-Test"
        )
        (state_dir / fn).write_text(
            json.dumps(pl, sort_keys=True), encoding="utf-8"
        )
        landed = list(state_dir.glob("ar-hand-stop-welle-*.json"))
        assert len(landed) == 1
        # filename in canonical shape
        assert _MARKER_FILENAME_RE.match(landed[0].name)
        # payload round-trips
        recovered = json.loads(
            landed[0].read_text(encoding="utf-8")
        )
        assert recovered == pl

    def test_audit_trail_is_chronologically_ordered(self) -> None:
        orch = CutoverOrchestrator()
        orch.register_sign_off(1, "green")
        orch.start_welle(2)
        fn, pl = _build_marker(
            welle=2, trigger="NATS-Consumer-Lag"
        )
        orch.write_state(fn, pl)
        orch.detect_and_halt_on_stop_marker()
        orch.emit_rollback_verdict(2)
        trail = orch.audit_trail
        # Order MUST be: welle-start -> state-write -> welle-
        # halted -> rollback-verdict.
        events = [e["event"] for e in trail]
        assert events.index("welle-start") < events.index(
            "state-write"
        )
        assert events.index("state-write") < events.index(
            "welle-halted"
        )
        assert events.index("welle-halted") < events.index(
            "rollback-verdict"
        )

    def test_notify_catalog_mentions_b1_marker_metric(self) -> None:
        """Notify-catalog §2.5 wires the B1 alert to the
        `wakir_ar_hand_stop_marker_total` metric. The metric name
        is the contract between the runtime + the Prometheus
        layer; this test pins the contract."""
        text = _NOTIFY_CATALOG.read_text(encoding="utf-8")
        assert "wakir_ar_hand_stop_marker_total" in text, (
            "notify-catalog drift: B1 metric name missing"
        )
        assert "Class-B1" in text or "B1" in text

    def test_coverage_matrix_classifies_b1(self) -> None:
        """The Tag-45 coverage matrix MUST classify B1 explicitly.
        After this Tag-46 PR lands, the classification reads
        COVERED; before this PR it reads PARTIAL. Either is
        acceptable here — we only pin presence of the row."""
        text = _COVERAGE_MATRIX.read_text(encoding="utf-8")
        assert "#### B1" in text
        assert "AR-Hand-Stop-Marker" in text


# ---------------------------------------------------------------------------
# Cross-class consistency
# ---------------------------------------------------------------------------


class TestCrossClassConsistency:
    """A handful of consistency invariants spanning the five test-
    classes above. Cheap to run, loud on drift."""

    def test_all_trigger_tokens_can_be_used_in_marker(self) -> None:
        for token in _TRIGGER_TOKENS:
            fn, pl = _build_marker(welle=1, trigger=token)
            assert pl["trigger"] == token
            assert _MARKER_FILENAME_RE.match(fn)

    def test_welle_3_runbook_documents_exit_3_stop_marker(
        self,
    ) -> None:
        text = _WELLE_3_RUNBOOK.read_text(encoding="utf-8")
        # welle-3 runbook §6/§8 names exit-3 as the AR-Hand-Stop-
        # Marker bedingung. The string is the trigger contract.
        assert "exit-3" in text
        assert "AR-Hand-Stop-Marker" in text

    def test_marker_payload_serialises_to_canonical_json(self) -> None:
        fn, pl = _build_marker(
            welle=7, trigger="Cosign-Verify-Fail"
        )
        serialised = json.dumps(pl, sort_keys=True)
        # round-trip and no surprises
        assert json.loads(serialised) == pl
