# SPDX-License-Identifier: BUSL-1.1
"""Tests for the Phase-2 Sprint-9 Tag-1 CaveatOverrideEvent
cross-org export surface
(``wirelang.federation.caveat_override_export``).

Test inventory (T-COX-01..T-COX-13):

- T-COX-01 happy-path export with default classifier produces an
  :class:`ExportedCaveatOverrideEvent` carrying expected fields
  (schema, route_id, sequence 1, 32-byte event_id, chain-hashes
  non-equal, narrowing-class SUBSET_PROPER, reason-class OTHER,
  raw narrative absent from repr).

- T-COX-02 absent-reason path: ``override_reason=None`` ->
  ``CaveatOverrideReasonClass.UNSPECIFIED`` and reason_hash None.

- T-COX-03 round-trip byte-equal verdict: two exports of the
  same source event under the same route_id at sequence_number 1
  (using two separate exporter instances with fresh ledgers)
  yield byte-equal ``override_event_id``, byte-equal chain
  hashes, byte-equal narrowing-class — `exported_at` differs
  but does not contribute to the event_id.

- T-COX-04 bridge-verifier byte-deterministic consumption: an
  exported event constructed by Org-A's exporter is byte-equal
  consumable by Org-B's verifier
  (:func:`detect_replay`) using a fresh ledger.

- T-COX-05 replay-detection within an exporter instance: a
  second export of the same source event at the same
  sequence_number is rejected with
  :class:`CaveatOverrideExportReplayError`.

- T-COX-06 sequence-number monotonicity: explicit
  ``sequence_number=5`` followed by ``sequence_number=3`` on
  the same (route_id, chain_hash) tuple raises the replay
  error (descending sequence rejected).

- T-COX-07 sequence-gap acceptance: sequence_number 1 then 5 is
  accepted (gaps allowed; only equal-or-less is forbidden).

- T-COX-08 cross-org-boundary verify: an export under
  attestation Org-A → Org-B and a separate export of the SAME
  source event under attestation Org-A → Org-C produces two
  different ``override_event_id`` values (route-scoping).

- T-COX-09 cross-org witness canonical-sort: two exporter calls
  with the same witnesses in two different insertion orders
  produce byte-equal ``override_event_id`` (witnesses are
  canonical-sorted before payload hashing).

- T-COX-10 nested-CaveatOverride chain: three sequential exports
  with monotonically narrowing caveat-sets each receive
  sequence-numbers 1, 2, 3 against the **first** chain-hash
  (sequence-namespace is keyed on the *original*
  caveat_chain_hash, NOT the narrowed); the third export's
  narrowing-class is SUBSET_PROPER (the second's narrowed is the
  third's original).

- T-COX-11 narrowing classifier: structural narrowing types
  SUPERSET / INTERSECT_PARTIAL / DISJOINT / SUBSET_EQUAL each
  resolve to the expected enum class.

- T-COX-12 pluggable classifier: a fake classifier mapping
  "amend" -> POLICY_AMENDMENT is honoured by the exporter.

- T-COX-13 raw-narrative-leak defence: a subclass that declares
  an ``override_reason`` attribute raises
  :class:`CaveatOverrideExportRawNarrativeLeakError` on
  construction.

All tests are hermetic: no network, no FS.

ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this test file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

from wirelang.federation.caveat_override_export import (
    AuditTraceEntry,
    CaveatNarrowingClass,
    CaveatOverrideEventCrossOrgExporter,
    CaveatOverrideExportRawNarrativeLeakError,
    CaveatOverrideExportReplayError,
    CaveatOverrideExportShapeError,
    CaveatOverrideReasonClass,
    CrossOrgWitness,
    EXPORT_SCHEMA,
    ExportedCaveatOverrideEvent,
    InMemorySequenceNumberLedger,
    detect_replay,
)
from wirelang.federation.marker_composition import (
    CaveatOverrideEvent,
)
from wirelang.federation.multi_org_substrate import (
    MultiOrgRouteAttestation,
)


# ---------------------------------------------------------------------------
# Time helpers / shared fixtures
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


def _make_attestation(
    route_id: str = "wakir-corp-a/peer-corp-b",
    peer_trust_domain: str = "corp-b.example.com",
) -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=route_id,
        peer_trust_domain=peer_trust_domain,
        peer_audit_anchor_did=f"did:web:{peer_trust_domain}",
        is_mock=False,
    )


def _make_event_with_reason(
    *,
    override_reason: Optional[str] = "suspected upstream key compromise",
    original=None,
    narrowed=None,
) -> CaveatOverrideEvent:
    # SUBSET_PROPER narrowing semantics: remove entire caveat
    # pairs from the chain (not modify their args). This matches
    # the structural set-of-(predicate, args) classifier in
    # :func:`_classify_narrowing`.
    original = original or (
        ("scope", ("read",)),
        ("audience", ("alice",)),
        ("ttl", (3600,)),
    )
    narrowed = narrowed or (
        ("scope", ("read",)),
        ("audience", ("alice",)),
    )
    return CaveatOverrideEvent(
        event_at=_utc(2026, 5, 13, 9, 0),
        original_caveat_set=original,
        narrowed_caveat_set=narrowed,
        override_reason=override_reason,
        tie_break=0,
        wat_anchor_manifest_id="manifest-abc",
    )


# ---------------------------------------------------------------------------
# T-COX-01: happy-path
# ---------------------------------------------------------------------------


def test_export_happy_path_default_classifier_produces_envelope():
    """T-COX-01 happy-path: default classifier maps present
    reason to OTHER; raw narrative absent on the envelope; chain
    hashes are 64-char hex; event_id is 32 bytes; narrowing-class
    is SUBSET_PROPER for a strict-subset narrowing.
    """
    exporter = CaveatOverrideEventCrossOrgExporter()
    attestation = _make_attestation()
    event = _make_event_with_reason()

    exported = exporter.export(event=event, attestation=attestation)

    assert isinstance(exported, ExportedCaveatOverrideEvent)
    assert exported.export_schema == EXPORT_SCHEMA
    assert exported.route_id == attestation.route_id
    assert exported.sequence_number == 1
    assert isinstance(exported.override_event_id, bytes)
    assert len(exported.override_event_id) == 32
    assert (
        exported.override_reason_class
        == CaveatOverrideReasonClass.OTHER
    )
    assert (
        exported.caveat_narrowing_class
        == CaveatNarrowingClass.SUBSET_PROPER
    )
    assert len(exported.original_caveat_chain_hash) == 64
    assert len(exported.narrowed_caveat_chain_hash) == 64
    # Different sets must produce different chain-hashes.
    assert (
        exported.original_caveat_chain_hash
        != exported.narrowed_caveat_chain_hash
    )
    assert exported.override_reason_hash is not None
    assert len(exported.override_reason_hash) == 64

    serialised = repr(exported)
    assert "suspected upstream key compromise" not in serialised
    # Predicate names are NOT considered raw narrative (they're
    # structural); they MAY appear in caveat-set repr, but we
    # never write the caveat-sets to the envelope.
    assert "narrowed_caveat_set" not in serialised
    assert "original_caveat_set" not in serialised


# ---------------------------------------------------------------------------
# T-COX-02: absent-reason
# ---------------------------------------------------------------------------


def test_export_absent_reason_path_yields_unspecified_and_no_hash():
    """T-COX-02 absent-reason: ``override_reason=None`` ->
    ``UNSPECIFIED`` and reason_hash None.
    """
    exporter = CaveatOverrideEventCrossOrgExporter()
    attestation = _make_attestation()
    event = _make_event_with_reason(override_reason=None)

    exported = exporter.export(event=event, attestation=attestation)

    assert (
        exported.override_reason_class
        == CaveatOverrideReasonClass.UNSPECIFIED
    )
    assert exported.override_reason_hash is None
    assert len(exported.override_event_id) == 32


# ---------------------------------------------------------------------------
# T-COX-03: round-trip byte-equal event_id
# ---------------------------------------------------------------------------


def test_round_trip_byte_equal_event_id_across_exporter_instances():
    """T-COX-03 round-trip determinism: two exports of the same
    source event under the same route_id at sequence_number 1
    (fresh exporter instances, fresh ledgers) yield byte-equal
    ``override_event_id``. ``exported_at`` differs but does not
    contribute.
    """
    attestation = _make_attestation()
    event = _make_event_with_reason()

    clock_a = lambda: _utc(2026, 5, 13, 10, 0)
    clock_b = lambda: _utc(2026, 5, 14, 22, 0)

    exporter_a = CaveatOverrideEventCrossOrgExporter(clock=clock_a)
    exporter_b = CaveatOverrideEventCrossOrgExporter(clock=clock_b)

    exported_a = exporter_a.export(event=event, attestation=attestation)
    exported_b = exporter_b.export(event=event, attestation=attestation)

    assert exported_a.override_event_id == exported_b.override_event_id
    assert (
        exported_a.original_caveat_chain_hash
        == exported_b.original_caveat_chain_hash
    )
    assert (
        exported_a.narrowed_caveat_chain_hash
        == exported_b.narrowed_caveat_chain_hash
    )
    assert exported_a.exported_at != exported_b.exported_at


# ---------------------------------------------------------------------------
# T-COX-04: bridge-verifier byte-deterministic consumption
# ---------------------------------------------------------------------------


def test_bridge_verifier_byte_deterministic_consumption():
    """T-COX-04 bridge-verifier: Org-A exporter produces an
    envelope; Org-B verifier consumes it via :func:`detect_replay`
    against a fresh ledger; consumption succeeds (no replay) and
    the verifier-side ledger now records the same sequence.
    """
    org_a_exporter = CaveatOverrideEventCrossOrgExporter()
    attestation = _make_attestation()
    event = _make_event_with_reason()

    exported = org_a_exporter.export(event=event, attestation=attestation)

    org_b_ledger = InMemorySequenceNumberLedger()
    # First-time consumption: no replay error.
    detect_replay(exported=exported, ledger=org_b_ledger)
    assert (
        org_b_ledger.last_seen(
            route_id=exported.route_id,
            chain_hash=exported.original_caveat_chain_hash,
        )
        == exported.sequence_number
    )


# ---------------------------------------------------------------------------
# T-COX-05: replay-detection within exporter
# ---------------------------------------------------------------------------


def test_replay_within_exporter_at_same_sequence_rejected():
    """T-COX-05 replay-detection: explicit sequence_number=1
    twice on the same exporter raises
    :class:`CaveatOverrideExportReplayError`.
    """
    exporter = CaveatOverrideEventCrossOrgExporter()
    attestation = _make_attestation()
    event = _make_event_with_reason()

    exporter.export(
        event=event, attestation=attestation, sequence_number=1
    )
    with pytest.raises(CaveatOverrideExportReplayError) as excinfo:
        exporter.export(
            event=event, attestation=attestation, sequence_number=1
        )
    assert excinfo.value.attempted_sequence == 1
    assert excinfo.value.last_seen_sequence == 1


# ---------------------------------------------------------------------------
# T-COX-06: monotonicity (descending sequence rejected)
# ---------------------------------------------------------------------------


def test_descending_sequence_rejected():
    """T-COX-06 monotonicity: sequence 5 then 3 on the same
    (route_id, chain_hash) raises replay error.
    """
    exporter = CaveatOverrideEventCrossOrgExporter()
    attestation = _make_attestation()
    event = _make_event_with_reason()

    exporter.export(
        event=event, attestation=attestation, sequence_number=5
    )
    with pytest.raises(CaveatOverrideExportReplayError) as excinfo:
        exporter.export(
            event=event, attestation=attestation, sequence_number=3
        )
    assert excinfo.value.last_seen_sequence == 5
    assert excinfo.value.attempted_sequence == 3


# ---------------------------------------------------------------------------
# T-COX-07: sequence-gap acceptance
# ---------------------------------------------------------------------------


def test_sequence_gap_accepted():
    """T-COX-07 sequence-gap: 1 then 5 is accepted (gaps allowed;
    only equal-or-less is forbidden).
    """
    exporter = CaveatOverrideEventCrossOrgExporter()
    attestation = _make_attestation()
    event = _make_event_with_reason()

    e1 = exporter.export(
        event=event, attestation=attestation, sequence_number=1
    )
    e2 = exporter.export(
        event=event, attestation=attestation, sequence_number=5
    )
    assert e1.sequence_number == 1
    assert e2.sequence_number == 5
    # event_ids differ because sequence_number contributes to
    # the canonical payload.
    assert e1.override_event_id != e2.override_event_id


# ---------------------------------------------------------------------------
# T-COX-08: cross-org-boundary verify (route-scoping)
# ---------------------------------------------------------------------------


def test_event_id_differs_per_attestation_route():
    """T-COX-08 cross-org-boundary: the same source event
    exported under two different attestations yields two
    different ``override_event_id`` values.
    """
    event = _make_event_with_reason()
    att_b = _make_attestation("wakir-corp-a/peer-corp-b", "corp-b.example.com")
    att_c = _make_attestation("wakir-corp-a/peer-corp-c", "corp-c.example.com")

    exporter = CaveatOverrideEventCrossOrgExporter()
    exported_b = exporter.export(event=event, attestation=att_b)
    exported_c = exporter.export(event=event, attestation=att_c)

    assert exported_b.route_id != exported_c.route_id
    assert exported_b.override_event_id != exported_c.override_event_id
    assert (
        exported_b.original_caveat_chain_hash
        != exported_c.original_caveat_chain_hash
    )
    assert (
        exported_b.override_reason_hash
        != exported_c.override_reason_hash
    )


# ---------------------------------------------------------------------------
# T-COX-09: cross-org witnesses canonical-sort
# ---------------------------------------------------------------------------


def test_cross_org_witnesses_canonical_sort_byte_equal_event_id():
    """T-COX-09 witness canonical-sort: two exporter calls with
    the same set of witnesses in different insertion orders
    produce byte-equal ``override_event_id``.
    """
    event = _make_event_with_reason()
    attestation = _make_attestation()
    w1 = CrossOrgWitness(
        route_id="r-1",
        peer_trust_domain="td-1.example.com",
        observed_at=_utc(2026, 5, 13, 8, 0),
    )
    w2 = CrossOrgWitness(
        route_id="r-2",
        peer_trust_domain="td-2.example.com",
        observed_at=_utc(2026, 5, 13, 9, 0),
    )
    w3 = CrossOrgWitness(
        route_id="r-3",
        peer_trust_domain="td-3.example.com",
        observed_at=_utc(2026, 5, 13, 10, 0),
    )

    # Two separate exporters with fresh ledgers (so sequence
    # numbers are both 1 and the only difference is witness
    # order on input).
    exporter_a = CaveatOverrideEventCrossOrgExporter()
    exporter_b = CaveatOverrideEventCrossOrgExporter()

    exp_a = exporter_a.export(
        event=event,
        attestation=attestation,
        cross_org_witnesses=(w1, w2, w3),
    )
    exp_b = exporter_b.export(
        event=event,
        attestation=attestation,
        cross_org_witnesses=(w3, w1, w2),
    )

    assert exp_a.override_event_id == exp_b.override_event_id
    # Both exporters' canonical-sort lands on the same tuple
    # order.
    assert exp_a.cross_org_witnesses == exp_b.cross_org_witnesses


# ---------------------------------------------------------------------------
# T-COX-10: nested-CaveatOverride chain
# ---------------------------------------------------------------------------


def test_nested_caveat_override_chain_sequence_keyed_on_original():
    """T-COX-10 nested chain: three sequential exports with
    monotonically narrowing caveat-sets. Each export keys the
    ledger by its OWN ``original_caveat_chain_hash`` (not a
    shared chain), so each pair starts at sequence_number 1.

    This is the documented semantic: the sequence-namespace is
    per (route_id, original_caveat_chain_hash); a chain of
    narrowings traverses distinct namespaces.
    """
    exporter = CaveatOverrideEventCrossOrgExporter()
    attestation = _make_attestation()

    # Pair-removal narrowing chain: each step drops one
    # (predicate, args) pair from the set.
    original = (
        ("scope", ("admin",)),
        ("scope", ("read",)),
        ("audience", ("alice",)),
        ("ttl", (3600,)),
    )
    narrowed_1 = (
        ("scope", ("read",)),
        ("audience", ("alice",)),
        ("ttl", (3600,)),
    )
    narrowed_2 = (
        ("scope", ("read",)),
        ("audience", ("alice",)),
    )

    event_1 = CaveatOverrideEvent(
        event_at=_utc(2026, 5, 13, 9, 0),
        original_caveat_set=original,
        narrowed_caveat_set=narrowed_1,
    )
    event_2 = CaveatOverrideEvent(
        event_at=_utc(2026, 5, 13, 10, 0),
        original_caveat_set=narrowed_1,
        narrowed_caveat_set=narrowed_2,
    )
    event_3 = CaveatOverrideEvent(
        event_at=_utc(2026, 5, 13, 11, 0),
        original_caveat_set=narrowed_2,
        narrowed_caveat_set=(("audience", ("alice",)),),
    )

    e1 = exporter.export(event=event_1, attestation=attestation)
    e2 = exporter.export(event=event_2, attestation=attestation)
    e3 = exporter.export(event=event_3, attestation=attestation)

    # Each export's original-chain-hash is distinct (because the
    # source caveat-sets are distinct).
    assert (
        e1.original_caveat_chain_hash
        != e2.original_caveat_chain_hash
    )
    assert (
        e2.original_caveat_chain_hash
        != e3.original_caveat_chain_hash
    )
    # Each export starts at sequence 1 in its own namespace.
    assert e1.sequence_number == 1
    assert e2.sequence_number == 1
    assert e3.sequence_number == 1
    # Causal-chain visibility: event_2's original chain equals
    # event_1's narrowed chain.
    assert (
        e1.narrowed_caveat_chain_hash
        == e2.original_caveat_chain_hash
    )
    assert (
        e2.narrowed_caveat_chain_hash
        == e3.original_caveat_chain_hash
    )
    # All three are SUBSET_PROPER narrowings.
    assert e1.caveat_narrowing_class == CaveatNarrowingClass.SUBSET_PROPER
    assert e2.caveat_narrowing_class == CaveatNarrowingClass.SUBSET_PROPER
    assert e3.caveat_narrowing_class == CaveatNarrowingClass.SUBSET_PROPER


# ---------------------------------------------------------------------------
# T-COX-11: structural narrowing classifier
# ---------------------------------------------------------------------------


def test_structural_narrowing_classifier_covers_all_classes():
    """T-COX-11 narrowing classifier: SUPERSET, INTERSECT_PARTIAL,
    DISJOINT, SUBSET_EQUAL each resolve correctly.
    """
    exporter = CaveatOverrideEventCrossOrgExporter()

    # SUPERSET: narrowed > original (structurally ill-formed but
    # still exportable for forensic visibility).
    event_superset = CaveatOverrideEvent(
        event_at=_utc(2026, 5, 13, 9, 0),
        original_caveat_set=(("scope", ("read",)),),
        narrowed_caveat_set=(
            ("scope", ("read",)),
            ("audience", ("alice",)),
        ),
    )
    # INTERSECT_PARTIAL: overlap but neither is subset.
    event_intersect = CaveatOverrideEvent(
        event_at=_utc(2026, 5, 13, 9, 1),
        original_caveat_set=(
            ("scope", ("read",)),
            ("audience", ("alice",)),
        ),
        narrowed_caveat_set=(
            ("scope", ("read",)),
            ("ttl", (3600,)),
        ),
    )
    # DISJOINT: no overlap.
    event_disjoint = CaveatOverrideEvent(
        event_at=_utc(2026, 5, 13, 9, 2),
        original_caveat_set=(("scope", ("read",)),),
        narrowed_caveat_set=(("audience", ("alice",)),),
    )
    # SUBSET_EQUAL: identical sets, override only records a
    # reason.
    event_equal = CaveatOverrideEvent(
        event_at=_utc(2026, 5, 13, 9, 3),
        original_caveat_set=(("scope", ("read",)),),
        narrowed_caveat_set=(("scope", ("read",)),),
        override_reason="reason-only override",
    )

    # Each event lives in its own (route_id, original-chain-hash)
    # namespace (originals are distinct).
    e_super = exporter.export(
        event=event_superset, attestation=_make_attestation()
    )
    e_inter = exporter.export(
        event=event_intersect, attestation=_make_attestation()
    )
    e_dis = exporter.export(
        event=event_disjoint, attestation=_make_attestation()
    )
    e_eq = exporter.export(
        event=event_equal, attestation=_make_attestation()
    )

    assert e_super.caveat_narrowing_class == CaveatNarrowingClass.SUPERSET
    assert (
        e_inter.caveat_narrowing_class
        == CaveatNarrowingClass.INTERSECT_PARTIAL
    )
    assert e_dis.caveat_narrowing_class == CaveatNarrowingClass.DISJOINT
    assert (
        e_eq.caveat_narrowing_class == CaveatNarrowingClass.SUBSET_EQUAL
    )


# ---------------------------------------------------------------------------
# T-COX-12: pluggable classifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeSubstringClassifier:
    """Test fixture: maps "amend" -> POLICY_AMENDMENT, "compromise"
    -> KEY_COMPROMISE_RESPONSE, None -> UNSPECIFIED, else OTHER.
    """

    def classify(self, raw):
        if raw is None:
            return CaveatOverrideReasonClass.UNSPECIFIED
        lowered = raw.lower()
        if "amend" in lowered:
            return CaveatOverrideReasonClass.POLICY_AMENDMENT
        if "compromise" in lowered:
            return CaveatOverrideReasonClass.KEY_COMPROMISE_RESPONSE
        return CaveatOverrideReasonClass.OTHER


def test_pluggable_classifier_honoured_and_raw_text_stripped():
    """T-COX-12 pluggable classifier: a fake classifier mapping
    "amend" -> POLICY_AMENDMENT is honoured; raw text is still
    stripped from the envelope.
    """
    exporter = CaveatOverrideEventCrossOrgExporter(
        classifier=_FakeSubstringClassifier()
    )
    attestation = _make_attestation()
    event = _make_event_with_reason(
        override_reason="policy amend per Q3 revision"
    )

    exported = exporter.export(event=event, attestation=attestation)
    assert (
        exported.override_reason_class
        == CaveatOverrideReasonClass.POLICY_AMENDMENT
    )
    serialised = repr(exported)
    assert "policy amend per Q3 revision" not in serialised


# ---------------------------------------------------------------------------
# T-COX-13: raw-narrative-leak defence (subclass with extra field)
# ---------------------------------------------------------------------------


def test_subclass_declaring_raw_override_reason_field_is_rejected():
    """T-COX-13 raw-narrative-leak: a subclass that declares an
    ``override_reason`` attribute is rejected by
    :class:`ExportedCaveatOverrideEvent.__post_init__` via
    :class:`CaveatOverrideExportRawNarrativeLeakError`.
    """

    class _SubclassWithLeak(ExportedCaveatOverrideEvent):
        override_reason = "operator-prose-here"

    with pytest.raises(
        CaveatOverrideExportRawNarrativeLeakError
    ) as excinfo:
        _SubclassWithLeak(
            export_schema=EXPORT_SCHEMA,
            route_id="r/x",
            sequence_number=1,
            override_event_id=b"\x00" * 32,
            event_at=_utc(2026, 5, 13, 9, 0),
            original_caveat_chain_hash="a" * 64,
            narrowed_caveat_chain_hash="b" * 64,
            caveat_narrowing_class=CaveatNarrowingClass.SUBSET_PROPER,
            override_reason_class=CaveatOverrideReasonClass.OTHER,
            override_reason_hash=None,
            audit_trace=(),
            cross_org_witnesses=(),
            exported_at=_utc(2026, 5, 13, 10, 0),
        )

    assert excinfo.value.field_name == "override_reason"


# ---------------------------------------------------------------------------
# Extra: shape gates negative coverage
# ---------------------------------------------------------------------------


def test_shape_gate_invalid_event_type_rejected():
    """Shape gate: a non-CaveatOverrideEvent input raises
    :class:`CaveatOverrideExportShapeError`.
    """
    exporter = CaveatOverrideEventCrossOrgExporter()
    attestation = _make_attestation()
    with pytest.raises(CaveatOverrideExportShapeError):
        exporter.export(event="not-an-event", attestation=attestation)  # type: ignore[arg-type]


def test_audit_trace_entry_naive_datetime_rejected():
    """AuditTraceEntry naive datetime raises shape error on
    construction.
    """
    with pytest.raises(CaveatOverrideExportShapeError):
        AuditTraceEntry(
            event_at=datetime(2026, 5, 13, 9, 0),
            event_kind="caveat_override",
            outcome="applied",
        )


def test_cross_org_witness_naive_datetime_rejected():
    """CrossOrgWitness naive datetime raises shape error on
    construction.
    """
    with pytest.raises(CaveatOverrideExportShapeError):
        CrossOrgWitness(
            route_id="r-1",
            peer_trust_domain="td-1.example.com",
            observed_at=datetime(2026, 5, 13, 9, 0),
        )
