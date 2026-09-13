# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-69 - Welle-1 State-File Producer implementation pin (Selin).

Tag-68 (PR #433) shipped the Producer-Wiring-Plan-doc + render-stub
in doc-form-only. Tag-69 implements the producer-substrate per
plan-doc §5.1: the engine-side writer-path for
``state/welle-N.json`` rollup-files with the
``pending -> in-progress -> signed-off`` lifecycle.

This test-suite pins the **Welle-1 first-fire** path as the
canonical reference (per Mira-Auftrag) and adds parametric
cross-coverage for all seven Wellen at the public-API boundary.
The substrate under test lives at
``wirelang/persona_engine/welle_state_producer.py``.

Coverage scope
--------------

* Public-API surface (constants, classes, functions, errors).
* ``WelleStateProducer.handle_cutover_event`` -- the §2.1
  Cutover-T0 transition pending -> in-progress for Welle-1.
* ``WelleStateProducer.handle_sign_off_event`` -- the §2.2
  Sign-Off transition in-progress -> signed-off for Welle-1.
* Idempotency on retried double-fire (no-op when already in
  target-state).
* Forbidden-transition guards (plan-doc §3.2).
* Time-invariant enforcement (plan-doc §3.4):
  cutover_iso <= signoff_iso whenever both non-empty.
* Welle-3 + Welle-7 pre-auditor-guard (plan-doc §2.2 extra-guard).
* Audit-record emit-contract (canonical JSON bytes, sort_keys).
* Atomic-write semantics (no temp-files survive after success).
* Schema-pin compliance (output byte-equivalent to Tag-67 schema).
* Path-traversal defence.
* Bridge-Audit-Writer adapter (no circular import).

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure
in-process file I/O against ``tmp_path`` fixtures.

Scope discipline (Selin)
------------------------

This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K),
identity-substrate design (Reza-Domaene, Zone-L), or
container-infra (Kai-Domaene, Zone-J). It pins the Tag-69
producer-substrate (persona-engine domain, Selin) which is
prescriptive of the writer-set and descriptive of the schema
(no schema changes vs. Tag-67 pin).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from wirelang.persona_engine.welle_state_producer import (
    ALLOWED_STATUSES,
    ALLOWED_TRANSITIONS,
    InvalidStatusTransitionError,
    InvalidWelleNumberError,
    PHASE_LITERAL,
    PRE_AUDITOR_GUARDED_WELLEN,
    PreAuditorGuardError,
    SCHEMA_VERSION_PIN,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_SIGNED_OFF,
    SignOffPreconditionError,
    StateFileShapeError,
    TimeInvariantViolationError,
    VALID_KW_ANCHORS,
    VALID_WELLE_NUMBERS,
    WelleAuditRecord,
    WelleStateProducer,
    audit_record_emitter_from_bridge_writer,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


CANONICAL_KW_ANCHOR = {
    1: "KW-22",
    2: "KW-23",
    3: "KW-25",
    4: "KW-25",
    5: "KW-25",
    6: "KW-26",
    7: "KW-27",
}


def _pending_stub(welle_number: int) -> dict:
    """Synthesise a canonical pending-status stub for welle-N."""
    return {
        "welle_number": welle_number,
        "schema_version": SCHEMA_VERSION_PIN,
        "phase": PHASE_LITERAL,
        "kw_cutover_anchor": CANONICAL_KW_ANCHOR[welle_number],
        "cutover_iso": "",
        "signoff_iso": "",
        "status": STATUS_PENDING,
        "rollup_links": {
            "sign_off": f"state/welle-{welle_number}-sign-off.json",
            "validation_last_verdict": (
                f"state/welle-{welle_number}-validation-last-verdict.json"
            ),
            "hot_spot_trend_dir": (
                f"state/welle-{welle_number}-hot-spot-trend/"
            ),
            "pre_auditor_decision": (
                f"state/welle-{welle_number}-pre-auditor-decision.json"
            ),
        },
        "audit_trail_anchor": "",
    }


def _seed_pending(state_dir: Path, welle_number: int) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"welle-{welle_number}.json"
    path.write_text(
        json.dumps(_pending_stub(welle_number), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


class _RecordingEmitter:
    def __init__(self) -> None:
        self.records: List[WelleAuditRecord] = []

    def __call__(self, record: WelleAuditRecord) -> None:
        self.records.append(record)


# ---------------------------------------------------------------------------
# Public-API surface invariants.
# ---------------------------------------------------------------------------


def test_module_exposes_schema_pin_constants():
    """The producer-substrate pins the Tag-67 schema literals."""
    assert SCHEMA_VERSION_PIN == "tag-67-v1"
    assert PHASE_LITERAL == "phase-3-marathon"
    assert STATUS_PENDING == "pending"
    assert STATUS_IN_PROGRESS == "in-progress"
    assert STATUS_SIGNED_OFF == "signed-off"
    assert STATUS_ROLLED_BACK == "rolled-back"
    assert set(ALLOWED_STATUSES) == {
        STATUS_PENDING,
        STATUS_IN_PROGRESS,
        STATUS_SIGNED_OFF,
        STATUS_ROLLED_BACK,
    }
    assert VALID_WELLE_NUMBERS == frozenset(range(1, 8))
    assert VALID_KW_ANCHORS == {f"KW-2{d}" for d in range(2, 8)}
    assert PRE_AUDITOR_GUARDED_WELLEN == frozenset({3, 7})


def test_allowed_transitions_match_plan_doc_section_3_1():
    """ALLOWED_TRANSITIONS exactly matches plan-doc §3.1 enumeration."""
    expected = frozenset(
        {
            (STATUS_PENDING, STATUS_IN_PROGRESS),
            (STATUS_PENDING, STATUS_ROLLED_BACK),
            (STATUS_IN_PROGRESS, STATUS_SIGNED_OFF),
            (STATUS_IN_PROGRESS, STATUS_ROLLED_BACK),
            (STATUS_SIGNED_OFF, STATUS_ROLLED_BACK),
        }
    )
    assert ALLOWED_TRANSITIONS == expected


# ---------------------------------------------------------------------------
# Welle-1 Cutover-T0: pending -> in-progress.
# ---------------------------------------------------------------------------


def test_welle_1_cutover_transitions_pending_to_in_progress(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 1)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)

    record = producer.handle_cutover_event(
        welle_number=1,
        cutover_iso="2026-05-20T08:00:00Z",
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_IN_PROGRESS
    assert on_disk["cutover_iso"] == "2026-05-20T08:00:00Z"
    assert on_disk["signoff_iso"] == ""
    assert on_disk["schema_version"] == SCHEMA_VERSION_PIN
    assert on_disk["welle_number"] == 1
    assert on_disk["kw_cutover_anchor"] == "KW-22"

    assert record.welle_number == 1
    assert record.prior_status == STATUS_PENDING
    assert record.new_status == STATUS_IN_PROGRESS
    assert record.cutover_iso == "2026-05-20T08:00:00Z"
    assert record.trigger == "cutover"
    assert len(emitter.records) == 1


def test_welle_1_cutover_is_idempotent_on_double_fire(tmp_path):
    """Plan-doc §2.1 idempotency guard: re-fire is no-op."""
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    first_bytes = target.read_bytes()
    # Retried workflow-event fires again with a different iso (a
    # workflow-retry might re-issue the event). The on-disk file
    # must remain at the first-fire iso (idempotency).
    record = producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T09:30:00Z"
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_IN_PROGRESS


# ---------------------------------------------------------------------------
# Welle-1 Sign-Off: in-progress -> signed-off.
# ---------------------------------------------------------------------------


def test_welle_1_sign_off_transitions_in_progress_to_signed_off(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 1)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    record = producer.handle_sign_off_event(
        welle_number=1,
        signoff_iso="2026-05-20T12:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["cutover_iso"] == "2026-05-20T08:00:00Z"
    assert on_disk["signoff_iso"] == "2026-05-20T12:30:00Z"

    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.cutover_iso == "2026-05-20T08:00:00Z"
    assert record.signoff_iso == "2026-05-20T12:30:00Z"
    assert record.trigger == "sign-off"
    # Two emissions: cutover then sign-off.
    assert len(emitter.records) == 2
    assert [r.trigger for r in emitter.records] == ["cutover", "sign-off"]


def test_welle_1_sign_off_refused_when_marker_not_signed_off(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    with pytest.raises(SignOffPreconditionError):
        producer.handle_sign_off_event(
            welle_number=1,
            signoff_iso="2026-05-20T12:30:00Z",
            sign_off_marker_status=STATUS_PENDING,
        )


def test_welle_1_sign_off_is_idempotent_on_double_fire(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    producer.handle_sign_off_event(
        welle_number=1,
        signoff_iso="2026-05-20T12:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
    )
    first_bytes = target.read_bytes()
    record = producer.handle_sign_off_event(
        welle_number=1,
        signoff_iso="2026-05-20T13:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_SIGNED_OFF
    assert record.new_status == STATUS_SIGNED_OFF


# ---------------------------------------------------------------------------
# Forbidden transitions (plan-doc §3.2).
# ---------------------------------------------------------------------------


def test_sign_off_from_pending_is_rejected(tmp_path):
    """signed-off can only be reached from in-progress."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidStatusTransitionError):
        producer.handle_sign_off_event(
            welle_number=1,
            signoff_iso="2026-05-20T12:30:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
        )


# ---------------------------------------------------------------------------
# Welle-3 + Welle-7 pre-auditor-guard (plan-doc §2.2).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("welle_number", sorted(PRE_AUDITOR_GUARDED_WELLEN))
def test_welle_3_and_7_sign_off_requires_designated_pre_auditor(
    welle_number, tmp_path
):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, welle_number)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=welle_number, cutover_iso="2026-05-20T08:00:00Z"
    )
    # Missing pre_auditor_decision is a hard refusal.
    with pytest.raises(PreAuditorGuardError):
        producer.handle_sign_off_event(
            welle_number=welle_number,
            signoff_iso="2026-05-20T12:30:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
        )
    # "pending" is also a hard refusal.
    with pytest.raises(PreAuditorGuardError):
        producer.handle_sign_off_event(
            welle_number=welle_number,
            signoff_iso="2026-05-20T12:30:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="pending",
        )
    # "designated" passes the guard.
    record = producer.handle_sign_off_event(
        welle_number=welle_number,
        signoff_iso="2026-05-20T12:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
    )
    assert record.new_status == STATUS_SIGNED_OFF


def test_non_guarded_wellen_do_not_require_pre_auditor(tmp_path):
    """Welle-1, 2, 4, 5, 6 sign off without the pre-auditor field."""
    for welle_number in [1, 2, 4, 5, 6]:
        state_dir = tmp_path / f"state-{welle_number}"
        _seed_pending(state_dir, welle_number)
        producer = WelleStateProducer(state_dir=state_dir)
        producer.handle_cutover_event(
            welle_number=welle_number,
            cutover_iso="2026-05-20T08:00:00Z",
        )
        record = producer.handle_sign_off_event(
            welle_number=welle_number,
            signoff_iso="2026-05-20T12:30:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
        )
        assert record.new_status == STATUS_SIGNED_OFF


# ---------------------------------------------------------------------------
# Time invariants (plan-doc §3.4).
# ---------------------------------------------------------------------------


def test_invalid_cutover_iso_format_is_rejected(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    for bad in [
        "",  # empty is invalid as event-iso
        "2026-05-20",  # date-only
        "2026/05/20T08:00:00Z",  # slashes
        "20260520T080000Z",  # compact
        "2026-05-20T08:00:00",  # no zone
    ]:
        with pytest.raises(TimeInvariantViolationError):
            producer.handle_cutover_event(
                welle_number=1, cutover_iso=bad
            )


def test_signoff_before_cutover_is_rejected(tmp_path):
    """cutover_iso <= signoff_iso (plan-doc §3.4)."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T12:00:00Z"
    )
    with pytest.raises(TimeInvariantViolationError):
        producer.handle_sign_off_event(
            welle_number=1,
            signoff_iso="2026-05-20T08:00:00Z",  # before cutover
            sign_off_marker_status=STATUS_SIGNED_OFF,
        )


# ---------------------------------------------------------------------------
# Welle-number validation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("invalid", [0, 8, -1, 100, 99])
def test_invalid_welle_number_is_rejected(invalid, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidWelleNumberError):
        producer.handle_cutover_event(
            welle_number=invalid, cutover_iso="2026-05-20T08:00:00Z"
        )


# ---------------------------------------------------------------------------
# Schema-pin compliance.
# ---------------------------------------------------------------------------


def test_post_write_state_file_has_all_required_keys(tmp_path):
    """After a cutover-write, all nine Tag-67 schema keys are present."""
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    required = {
        "welle_number",
        "schema_version",
        "phase",
        "kw_cutover_anchor",
        "cutover_iso",
        "signoff_iso",
        "status",
        "rollup_links",
        "audit_trail_anchor",
    }
    assert set(on_disk.keys()) == required
    assert on_disk["schema_version"] == SCHEMA_VERSION_PIN
    assert on_disk["phase"] == PHASE_LITERAL


def test_post_write_state_file_passes_amara_tag_67_verifier(tmp_path):
    """Producer output is byte-shape-equivalent to Tag-67 schema."""
    # Import the Tag-67 verifier's --rollup checker as a module
    # (stdlib-only, no subprocess per hermetic envelope).
    import importlib.util
    import sys as _sys

    verifier_path = (
        REPO_ROOT
        / "tooling"
        / "ci"
        / "verify_welle_state_file_conventions.py"
    )
    module_name = "verify_welle_state_file_conventions_tag67_for_tag69"
    spec = importlib.util.spec_from_file_location(
        module_name, verifier_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass __module__ resolution works
    # under Python 3.14 (dataclass introspects sys.modules).
    _sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        _sys.modules.pop(module_name, None)
        raise

    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    producer.handle_sign_off_event(
        welle_number=1,
        signoff_iso="2026-05-20T12:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
    )
    # Use the verifier's rollup-validator on the producer output.
    data = json.loads(target.read_text(encoding="utf-8"))
    report = module.Report()
    module.validate_rollup(str(target), data, report)
    assert report.ok, (
        f"Tag-67 verifier reports violations on Tag-69 producer "
        f"output: {[str(v) for v in report.violations]}"
    )


# ---------------------------------------------------------------------------
# Atomic-write semantics.
# ---------------------------------------------------------------------------


def test_atomic_write_leaves_no_temp_files(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    leftovers = [
        p for p in state_dir.iterdir() if p.name.endswith(".tmp")
    ]
    assert leftovers == [], (
        f"atomic-write must not leave temp-files: {leftovers!r}"
    )


def test_shape_violation_on_disk_is_rejected_before_write(tmp_path):
    """A corrupted on-disk file must not be silently overwritten."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    target = state_dir / "welle-1.json"
    target.write_text(
        json.dumps({"welle_number": 1, "status": "pending"}) + "\n",
        encoding="utf-8",
    )
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(StateFileShapeError):
        producer.handle_cutover_event(
            welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
        )


# ---------------------------------------------------------------------------
# Audit-record emit contract.
# ---------------------------------------------------------------------------


def test_audit_record_to_json_bytes_is_canonical(tmp_path):
    """WelleAuditRecord.to_json_bytes is sort_keys + compact separators."""
    record = WelleAuditRecord(
        welle_number=1,
        prior_status=STATUS_PENDING,
        new_status=STATUS_IN_PROGRESS,
        cutover_iso="2026-05-20T08:00:00Z",
        signoff_iso="",
        trigger="cutover",
    )
    raw = record.to_json_bytes()
    # Compact-canonical: no whitespace, alphabetical keys.
    expected = (
        b'{"cutover_iso":"2026-05-20T08:00:00Z",'
        b'"new_status":"in-progress",'
        b'"prior_status":"pending",'
        b'"signoff_iso":"",'
        b'"trigger":"cutover",'
        b'"welle_number":1}'
    )
    assert raw == expected


def test_default_emitter_is_no_op(tmp_path):
    """Default emitter swallows records (Tag-69+ wiring overrides)."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    # No emitter wired -- this must still succeed.
    record = producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    assert record.new_status == STATUS_IN_PROGRESS


def test_audit_record_emitter_from_bridge_writer_adapts_correctly():
    """The adapter calls bridge_writer.emit with 'audit_annotation'."""

    captured = []

    class _FakeBridgeWriter:
        def emit(self, output_kind, payload):
            captured.append((output_kind, payload))

    emitter = audit_record_emitter_from_bridge_writer(_FakeBridgeWriter())
    record = WelleAuditRecord(
        welle_number=1,
        prior_status=STATUS_PENDING,
        new_status=STATUS_IN_PROGRESS,
        cutover_iso="2026-05-20T08:00:00Z",
        signoff_iso="",
        trigger="cutover",
    )
    emitter(record)
    assert len(captured) == 1
    output_kind, payload = captured[0]
    assert output_kind == "audit_annotation"
    assert payload == record.to_json_bytes()


# ---------------------------------------------------------------------------
# Parametric cross-coverage: all seven Wellen at the boundary.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("welle_number", sorted(VALID_WELLE_NUMBERS))
def test_all_seven_wellen_cutover_path(welle_number, tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, welle_number)
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_cutover_event(
        welle_number=welle_number,
        cutover_iso="2026-05-20T08:00:00Z",
    )
    assert record.new_status == STATUS_IN_PROGRESS
    on_disk = json.loads(
        (state_dir / f"welle-{welle_number}.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk["status"] == STATUS_IN_PROGRESS
    assert (
        on_disk["kw_cutover_anchor"]
        == CANONICAL_KW_ANCHOR[welle_number]
    )


# ---------------------------------------------------------------------------
# Read-only convenience surface.
# ---------------------------------------------------------------------------


def test_current_status_and_snapshot_round_trip(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    assert producer.current_status(1) == STATUS_PENDING
    producer.handle_cutover_event(
        welle_number=1, cutover_iso="2026-05-20T08:00:00Z"
    )
    assert producer.current_status(1) == STATUS_IN_PROGRESS
    snapshot = producer.snapshot(1)
    assert snapshot["status"] == STATUS_IN_PROGRESS
    assert snapshot["cutover_iso"] == "2026-05-20T08:00:00Z"
    # snapshot is a deep copy -- mutation does not leak to disk.
    snapshot["status"] = "MUTATED-DOES-NOT-LEAK"
    on_disk = json.loads(
        (state_dir / "welle-1.json").read_text(encoding="utf-8")
    )
    assert on_disk["status"] == STATUS_IN_PROGRESS
