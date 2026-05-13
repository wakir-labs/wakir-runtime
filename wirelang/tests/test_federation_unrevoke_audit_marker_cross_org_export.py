# SPDX-License-Identifier: Apache-2.0
"""Tests for the Phase-2 Sprint-7 Tag-5 UnrevokeAuditMarker
cross-org export surface
(``wirelang.federation.unrevoke_audit_marker_cross_org_export``).

Test inventory (T-UMCX-01..07):

- T-UMCX-01 happy-path export with default classifier ->
  :class:`ExportedUnrevokeAuditMarker` carrying:
  ``export_schema == EXPORT_SCHEMA``, ``route_id`` from
  attestation, ``unrevoke_reason_class == OTHER``,
  ``previous_revocation_reason_hash`` non-None (raw text not
  exposed), ``marker_id`` BLAKE2b-256 32-byte digest.

- T-UMCX-02 absent-reason path (source marker has
  ``unrevoke_reason=None`` and ``previous_revocation_reason=None``)
  produces export with ``unrevoke_reason_class == UNSPECIFIED``
  and ``previous_revocation_reason_hash is None``.

- T-UMCX-03 ``previous_revocation_reason_hash`` is BLAKE2b-256-hex-
  deterministic for the same (route_id, raw) pair across two
  separate export invocations: hex match. The same raw text
  under two **different** route_ids produces two **different**
  hashes (route-scoping defence).

- T-UMCX-04 pluggable classifier extension: a fake classifier that
  maps the substring "amend" to
  :class:`UnrevokeReasonClass.POLICY_AMENDMENT` is honoured by
  the exporter; the resulting envelope's
  ``unrevoke_reason_class`` carries the categorical class.

- T-UMCX-05 raw-narrative-leak defence: directly constructing an
  :class:`ExportedUnrevokeAuditMarker` subclass that declares a
  ``unrevoke_reason`` attribute raises
  :class:`RawNarrativeLeakError`.

- T-UMCX-06 round-trip determinism: exporting the same source
  marker twice (under the same attestation, regardless of
  exporter-clock) yields byte-equal ``marker_id`` (because
  ``exported_at`` is excluded from the canonical payload).

- T-UMCX-07 marker_id attestation-binding: the same source
  marker exported under two different attestations (different
  ``route_id``) yields two different ``marker_id`` values —
  the marker_id is route-bound, so a cross-org audit-leaf
  anchored to a different attestation has a distinct identity.

All tests are hermetic: no network, no FS. The exporter consumes
a constructed :class:`MultiOrgRouteAttestation` and a constructed
:class:`UnrevokeAuditMarker`.

ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this test file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

from wirelang.federation.multi_org_substrate import (
    MultiOrgRouteAttestation,
)
from wirelang.federation.unrevoke_audit_marker_cross_org_export import (
    DEFAULT_CLASSIFIER,
    EXPORT_SCHEMA,
    ExportedUnrevokeAuditMarker,
    RawNarrativeLeakError,
    UnrevokeAuditMarkerCrossOrgExporter,
    UnrevokeAuditMarkerShapeError,
    UnrevokeReasonClass,
    _compute_marker_id,
    _route_scoped_reason_hash,
)
from wirelang.schemas.capability_policy_nats_kv_backend import (
    UnrevokeAuditMarker,
)


# ---------------------------------------------------------------------------
# Time helpers / shared fixtures
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


def _make_attestation(route_id: str = "wakir-corp-a/peer-corp-b") -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=route_id,
        peer_trust_domain="corp-b.example.com",
        peer_audit_anchor_did="did:web:corp-b.example.com",
        is_mock=False,
    )


def _make_marker_with_reasons() -> UnrevokeAuditMarker:
    return UnrevokeAuditMarker(
        unrevoke_reason="operator-recovery after substrate hiccup",
        previous_revoked_at=_utc(2026, 5, 10, 14, 30),
        previous_revocation_reason="suspected key compromise",
    )


def _make_marker_no_reasons() -> UnrevokeAuditMarker:
    return UnrevokeAuditMarker(
        unrevoke_reason=None,
        previous_revoked_at=_utc(2026, 5, 10, 14, 30),
        previous_revocation_reason=None,
    )


# ---------------------------------------------------------------------------
# T-UMCX-01: happy-path export with default classifier
# ---------------------------------------------------------------------------


def test_export_happy_path_default_classifier_produces_envelope():
    """T-UMCX-01 happy-path: default classifier maps any present
    reason to OTHER; raw narrative fields are absent on the
    envelope; reason_hash is a 64-char hex; marker_id is 32 bytes.
    """
    exporter = UnrevokeAuditMarkerCrossOrgExporter()
    attestation = _make_attestation()
    marker = _make_marker_with_reasons()

    exported = exporter.export(marker=marker, attestation=attestation)

    assert isinstance(exported, ExportedUnrevokeAuditMarker)
    assert exported.export_schema == EXPORT_SCHEMA
    assert exported.route_id == attestation.route_id
    assert exported.unrevoke_reason_class == UnrevokeReasonClass.OTHER
    assert isinstance(exported.marker_id, bytes)
    assert len(exported.marker_id) == 32
    assert exported.previous_revoked_at == marker.previous_revoked_at
    assert exported.previous_revocation_reason_hash is not None
    assert len(exported.previous_revocation_reason_hash) == 64
    # The raw narrative MUST NOT appear anywhere on the envelope
    # (defence-in-depth check at the value level).
    serialised = repr(exported)
    assert "operator-recovery after substrate hiccup" not in serialised
    assert "suspected key compromise" not in serialised


# ---------------------------------------------------------------------------
# T-UMCX-02: absent-reason path
# ---------------------------------------------------------------------------


def test_export_absent_reason_path_yields_unspecified_and_no_hash():
    """T-UMCX-02 absent-reason: ``unrevoke_reason=None`` ->
    ``UnrevokeReasonClass.UNSPECIFIED``;
    ``previous_revocation_reason=None`` -> reason_hash is None.
    """
    exporter = UnrevokeAuditMarkerCrossOrgExporter()
    attestation = _make_attestation()
    marker = _make_marker_no_reasons()

    exported = exporter.export(marker=marker, attestation=attestation)

    assert (
        exported.unrevoke_reason_class
        == UnrevokeReasonClass.UNSPECIFIED
    )
    assert exported.previous_revocation_reason_hash is None
    # marker_id still computes (over schema/route_id/timing/class).
    assert len(exported.marker_id) == 32


# ---------------------------------------------------------------------------
# T-UMCX-03: hash determinism + route-scoping
# ---------------------------------------------------------------------------


def test_reason_hash_is_deterministic_per_route_and_route_scoped():
    """T-UMCX-03 hash determinism: the same (route_id, raw) pair
    yields the same hex digest across two invocations; two
    different route_ids yield two different digests
    (route-scoping defence against cross-route fingerprint
    correlation).
    """
    h1 = _route_scoped_reason_hash(
        route_id="wakir-corp-a/peer-corp-b",
        raw="suspected key compromise",
    )
    h2 = _route_scoped_reason_hash(
        route_id="wakir-corp-a/peer-corp-b",
        raw="suspected key compromise",
    )
    assert h1 == h2
    assert len(h1) == 64

    h3 = _route_scoped_reason_hash(
        route_id="wakir-corp-a/peer-corp-c",
        raw="suspected key compromise",
    )
    assert h1 != h3


# ---------------------------------------------------------------------------
# T-UMCX-04: pluggable classifier extension
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeSubstringClassifier:
    """Test fixture: maps any reason containing "amend" to
    POLICY_AMENDMENT; "recovery" to OPERATOR_RECOVERY; None to
    UNSPECIFIED; else OTHER.
    """

    def classify(self, raw):
        if raw is None:
            return UnrevokeReasonClass.UNSPECIFIED
        lowered = raw.lower()
        if "amend" in lowered:
            return UnrevokeReasonClass.POLICY_AMENDMENT
        if "recovery" in lowered:
            return UnrevokeReasonClass.OPERATOR_RECOVERY
        return UnrevokeReasonClass.OTHER


def test_export_honours_pluggable_classifier():
    """T-UMCX-04 pluggable classifier: a fake classifier mapping
    "amend" -> POLICY_AMENDMENT is honoured by the exporter; the
    resulting envelope carries POLICY_AMENDMENT in
    ``unrevoke_reason_class`` and the raw text is still stripped.
    """
    exporter = UnrevokeAuditMarkerCrossOrgExporter(
        classifier=_FakeSubstringClassifier()
    )
    attestation = _make_attestation()
    marker = UnrevokeAuditMarker(
        unrevoke_reason="policy amend per Q2-revision",
        previous_revoked_at=_utc(2026, 5, 10, 14, 30),
        previous_revocation_reason=None,
    )

    exported = exporter.export(marker=marker, attestation=attestation)

    assert (
        exported.unrevoke_reason_class
        == UnrevokeReasonClass.POLICY_AMENDMENT
    )
    # The pluggable classifier path STILL strips raw narrative.
    serialised = repr(exported)
    assert "policy amend per Q2-revision" not in serialised


# ---------------------------------------------------------------------------
# T-UMCX-05: raw-narrative-leak defence (subclass with extra field)
# ---------------------------------------------------------------------------


def test_subclass_declaring_raw_narrative_field_is_rejected():
    """T-UMCX-05 raw-narrative-leak: a subclass that declares a
    ``unrevoke_reason`` attribute (bypassing the exporter) is
    rejected by :class:`ExportedUnrevokeAuditMarker.__post_init__`
    via :class:`RawNarrativeLeakError`.

    The exporter never emits raw narrative; this gate protects
    against a constructor-bypass call path.
    """

    class _SubclassWithLeak(ExportedUnrevokeAuditMarker):
        # Add a class-level attribute that mirrors the forbidden
        # raw-narrative field name. The __post_init__ raw-leak
        # gate checks `hasattr(type(self), forbidden)` and must
        # raise.
        unrevoke_reason = "operator-prose-here"

    with pytest.raises(RawNarrativeLeakError) as excinfo:
        _SubclassWithLeak(
            export_schema=EXPORT_SCHEMA,
            route_id="r/x",
            marker_id=b"\x00" * 32,
            previous_revoked_at=_utc(2026, 5, 10),
            unrevoke_reason_class=UnrevokeReasonClass.OTHER,
            previous_revocation_reason_hash=None,
            exported_at=_utc(2026, 5, 11),
        )

    assert excinfo.value.field_name == "unrevoke_reason"


# ---------------------------------------------------------------------------
# T-UMCX-06: round-trip / marker_id is timing-invariant
# ---------------------------------------------------------------------------


def test_marker_id_is_timing_invariant_across_re_exports():
    """T-UMCX-06 round-trip determinism: re-exporting the same
    source marker (under the same attestation) at a different
    wall-clock yields a byte-equal ``marker_id``. The
    ``exported_at`` field is excluded from the canonical payload
    by design, so the marker_id is a stable audit-leaf identifier
    across re-exports.
    """
    attestation = _make_attestation()
    marker = _make_marker_with_reasons()

    clock_a = lambda: _utc(2026, 5, 11, 10, 0)
    clock_b = lambda: _utc(2026, 5, 12, 22, 0)

    exporter_a = UnrevokeAuditMarkerCrossOrgExporter(clock=clock_a)
    exporter_b = UnrevokeAuditMarkerCrossOrgExporter(clock=clock_b)

    exported_a = exporter_a.export(marker=marker, attestation=attestation)
    exported_b = exporter_b.export(marker=marker, attestation=attestation)

    assert exported_a.marker_id == exported_b.marker_id
    # But the exported_at fields ARE different (timing surfaces
    # exist; they just do not contribute to marker_id).
    assert exported_a.exported_at != exported_b.exported_at


# ---------------------------------------------------------------------------
# T-UMCX-07: marker_id attestation-binding
# ---------------------------------------------------------------------------


def test_marker_id_differs_per_attestation_route_binding():
    """T-UMCX-07 attestation-binding: the same source marker
    exported under two **different** attestations
    (different ``route_id``) yields two **different**
    ``marker_id`` values. The marker_id is route-bound so a
    cross-org audit-leaf anchored to a different attestation
    has a distinct identity.
    """
    marker = _make_marker_with_reasons()
    attestation_b = _make_attestation("wakir-corp-a/peer-corp-b")
    attestation_c = _make_attestation("wakir-corp-a/peer-corp-c")

    exporter = UnrevokeAuditMarkerCrossOrgExporter()
    exported_b = exporter.export(marker=marker, attestation=attestation_b)
    exported_c = exporter.export(marker=marker, attestation=attestation_c)

    assert exported_b.route_id != exported_c.route_id
    assert exported_b.marker_id != exported_c.marker_id
    # And the per-route reason-hash is also different (T-UMCX-03
    # already covers determinism; this confirms the path through
    # the export surface honours route-scoping).
    assert (
        exported_b.previous_revocation_reason_hash
        != exported_c.previous_revocation_reason_hash
    )
