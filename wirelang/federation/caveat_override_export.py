# SPDX-License-Identifier: Apache-2.0
"""CaveatOverrideEvent cross-org export surface.

Phase-2 Sprint-9 Tag-1 lands the cross-org export pattern for the
Sprint-8 Tag-3
:class:`~wirelang.federation.marker_composition.CaveatOverrideEvent`.
The event is a load-bearing lifecycle-axis-artefact within a single
Wakir-Org marker-composition reducer: a verifier observes that the
issuer-side caveat chain was narrowed *after* the token was minted
and emits a ``CaveatOverrideEvent`` so the composition reducer
collapses the lifecycle to the terminal ``CAVEAT_OVERRIDDEN`` state.
For **multi-org federation** scenarios (Sprint-7 Tag-1+ substrate),
the internal event MUST NOT leak naively across an org boundary:
the event carries operator-supplied free-form text
(``override_reason``) and the full pre/post caveat-chains
(``original_caveat_set`` / ``narrowed_caveat_set``) which embed
arbitrary operator-supplied predicate arguments. Both are
Wakir-internal narrative and a Brand-Guide-§9-No-Go for cross-org
export.

Pattern alignment
=================

This module mirrors the Sprint-7 Tag-5
:mod:`wirelang.federation.unrevoke_audit_marker_cross_org_export`
exporter (load-bearing
:class:`~wirelang.federation.unrevoke_audit_marker_cross_org_export.UnrevokeAuditMarkerCrossOrgExporter`).
The same pseudonymisation pattern (ADR-0031 D4) applies:

1. **Strip** raw operator-supplied free-form text
   (``override_reason``) so it never appears in the exported
   envelope.
2. **Pseudonymise** the pre/post caveat-chains via route-scoped
   BLAKE2b-256 hashing — producing
   ``original_caveat_chain_hash`` and ``narrowed_caveat_chain_hash``.
   These are audit-deterministic-but-not-back-readable digests
   that let a peer compare two override events' caveat-chains for
   equality without learning the predicate arguments.
3. **Categorise** the operator gesture via a pluggable
   :class:`CaveatOverrideReasonClassifier` Protocol that maps
   free-form text into one of the categorical
   :class:`CaveatOverrideReasonClass` enum values.
4. **Categorise** the structural narrowing via
   :class:`CaveatNarrowingClass`: a closed enumeration describing
   *how* the chain was narrowed (e.g. ``SUBSET_PROPER`` —
   narrowed is a proper subset of original;
   ``DISJOINT_PREDICATES`` — narrowed contains predicate-names
   absent from original, a structurally ill-formed override;
   ``EQUAL`` — caveat-set unchanged but reason recorded;
   ``UNKNOWN`` — fallback).
5. **Retain raw** only timing fields (``event_at``,
   ``exported_at``), envelope fields (``route_id``,
   ``export_schema``, ``override_event_id``), and the integer
   ``sequence_number`` (replay-protection).

Resulting envelope: :class:`ExportedCaveatOverrideEvent`,
frozen-dataclass. The
:attr:`ExportedCaveatOverrideEvent.override_event_id` is a
BLAKE2b-256 digest over a JCS-compatible canonicalised payload
mixing the export-schema, route-id, event_at, sequence_number,
narrowing-class, reason-class, and the optional chain-hashes;
re-exporting a byte-equal source event against the same route
attestation **at the same sequence_number** produces a byte-equal
``override_event_id`` (timing-invariant; sequence-aware).

Replay-protection (Sprint-9 Tag-1 substantive new gate)
=======================================================

Cross-org-export markers carry an integer ``sequence_number``
that is monotonically per-(route_id, override_event_id) tracked
by the exporter. Two semantics:

- Within a single exporter instance: the exporter rejects
  re-export of the same source event at a sequence_number
  less-than-or-equal-to the last seen sequence for the
  (route_id, original_caveat_chain_hash) tuple. This blocks a
  naive bridge-cycle re-replay where Org-A exports to Org-B and
  Org-B exports back to Org-A at the same sequence.
- Across exporter instances: the
  :class:`SequenceNumberLedger` Protocol abstracts the durable
  ledger (default: in-memory; production: NATS-KV bucket
  ``wakir-caveat-override-export-sequence-{org_id}``,
  out-of-scope for Tag-1). The ledger surfaces:

  - :meth:`SequenceNumberLedger.next_sequence(route_id, chain_hash)`:
    returns the next allowed sequence_number for the pair.
  - :meth:`SequenceNumberLedger.record_export(route_id, chain_hash, sequence)`:
    durably records the export at the given sequence; raises
    :class:`CaveatOverrideExportReplayError` iff the sequence is
    not strictly greater than the last recorded sequence for
    the pair.

Bridge-verification: an Org-B verifier that consumes an
:class:`ExportedCaveatOverrideEvent` from Org-A MUST track the
``sequence_number`` per (route_id, original_caveat_chain_hash)
tuple and reject any event whose sequence is not strictly
greater than the last seen.
:func:`detect_replay` exposes the symmetric
verifier-side check.

Cross-org-witnesses
===================

Each exported event MAY carry a tuple of
:class:`CrossOrgWitness` entries — additional route-attestations
that the source-org operator endorses as having observed the
same override. The witnesses are part of the canonical payload
(they contribute to ``override_event_id``) so a verifier in
Org-B can verify both that:

(a) The exporting Org-A signed the export under route_id ``R``.
(b) The override was independently witnessed under the
    additional :class:`CrossOrgWitness` routes.

Witnesses are byte-deterministic: re-exporting the same event
with the same witnesses (in any order — they are sorted by the
exporter prior to canonicalisation) yields a byte-equal
``override_event_id``.

Audit-trace
===========

Each exported event carries a tuple of
:class:`AuditTraceEntry` records mirroring the on-reducer
``AuditTraceEntry`` from
:mod:`wirelang.federation.marker_composition`. The exporter
projects only structural fields (``event_at``, ``event_kind``,
``outcome``, ``wat_anchor_manifest_id``); it does NOT export
free-form reason text (the reducer's internal trace may carry
raw reason text but the export surface strips it).

Failure-mode hierarchy
======================

All errors parent on
:class:`~wirelang.federation.multi_org_substrate.MultiOrgSubstrateError`
so existing catch-base callers absorb every exporter surface
uniformly.

- :class:`CaveatOverrideExportError` — base.
- :class:`CaveatOverrideExportShapeError` — malformed input
  (wrong type, tz-naive timestamp, missing route_id, negative
  sequence_number, etc.).
- :class:`CaveatOverrideExportReplayError` — sequence_number
  monotonicity breach (re-replay detected).
- :class:`CaveatOverrideExportRawNarrativeLeakError` —
  defence-in-depth: raised iff a callsite tries to construct an
  :class:`ExportedCaveatOverrideEvent` carrying a raw narrative
  field.

The exporter is **fail-closed** on every shape gate. A malformed
event yields no partial export.

WAT-Audit-Federation-Annex anchoring
====================================

The export artefact carries the schema URI
``wakir.federation.caveat-override-event-export/1`` so the
WAT-Audit-Federation-Annex (Tomás D-1, forthcoming) can anchor
exported events into both peer-org and Wakir-org WAT merkle
leaves with a stable label.

ADR-0050 Tool-Surface-Stempel
=============================

This file was authored using Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this module.

ADR-0049 Pre-Box-Worktree
=========================

This module was authored in an isolated worktree
``/tmp/reza-sprint-9-tag-1-caveat-override-export-runtime`` with
the ``-runtime`` suffix from ``origin/main`` (Sprint-8 Tag-4
post-merge tip). The worktree is cleaned up after the β-push.

Cross-references
================

- Sprint-8 Tag-3 ``CaveatOverrideEvent``:
  ``wirelang/federation/marker_composition.py``.
- Sprint-7 Tag-5 ``UnrevokeAuditMarker`` cross-org export
  (pattern source):
  ``wirelang/federation/unrevoke_audit_marker_cross_org_export.py``.
- Sprint-7 Tag-1 federation substrate
  (``MultiOrgRouteAttestation`` carrier of the export route):
  ``wirelang/federation/multi_org_substrate.py``.
- ADR-0031 D4 Pseudonymisierungs-Pattern.

Version
=======

``wakir.federation.caveat-override-event-export/1``.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol, Tuple

from .marker_composition import CaveatOverrideEvent
from .multi_org_substrate import (
    MultiOrgRouteAttestation,
    MultiOrgSubstrateError,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Schema-URI for the exported-caveat-override-event artefact.
#: Phase-1b convention: ``wakir.`` prefix, kebab-case noun,
#: integer version suffix.
EXPORT_SCHEMA: str = "wakir.federation.caveat-override-event-export/1"


#: BLAKE2b key personalisation for caveat-chain hashing. The hash
#: is route-scoped so two different cross-org routes produce two
#: different chain-hashes for the same caveat-set. The
#: personalisation byte-string is fixed at module load (no
#: dynamic salting on construction) so the export is
#: deterministic across exporter invocations.
_CHAIN_HASH_PERSONALISATION: bytes = b"wakir-coee1\x00\x00\x00\x00\x00"
assert len(_CHAIN_HASH_PERSONALISATION) == 16


#: BLAKE2b key personalisation for ``override_reason``
#: pseudonymisation. Distinct from the chain-hash personalisation
#: to provide hash-domain separation.
_REASON_HASH_PERSONALISATION: bytes = b"wakir-coer1\x00\x00\x00\x00\x00"
assert len(_REASON_HASH_PERSONALISATION) == 16


# ---------------------------------------------------------------------------
# Reason-classification enum + default classifier
# ---------------------------------------------------------------------------


class CaveatOverrideReasonClass(str, enum.Enum):
    """Categorical surface for the operator-supplied
    ``override_reason``.

    The exporter classifies the free-form
    :attr:`CaveatOverrideEvent.override_reason` (or absence
    thereof) into one of these values. The classifier itself is
    pluggable via :class:`CaveatOverrideReasonClassifier`; the
    default classifier (built-in fallback) maps every present
    reason to :attr:`OTHER` and absent reason to
    :attr:`UNSPECIFIED`. An operator who wants finer
    categorisation MUST install a richer classifier.

    Values:

    - :attr:`UNSPECIFIED`: source event carried ``override_reason
      = None``.
    - :attr:`KEY_COMPROMISE_RESPONSE`: caveat-narrowing in
      response to a suspected upstream key compromise.
    - :attr:`POLICY_AMENDMENT`: deliberate policy-amendment
      gesture.
    - :attr:`SCOPE_TIGHTENING`: operator gesture tightening the
      scope of permissions (no incident).
    - :attr:`OTHER`: present but uncategorisable by the installed
      classifier.
    """

    UNSPECIFIED = "UNSPECIFIED"
    KEY_COMPROMISE_RESPONSE = "KEY_COMPROMISE_RESPONSE"
    POLICY_AMENDMENT = "POLICY_AMENDMENT"
    SCOPE_TIGHTENING = "SCOPE_TIGHTENING"
    OTHER = "OTHER"


class CaveatOverrideReasonClassifier(Protocol):
    """Pluggable classifier from raw ``override_reason`` text to
    :class:`CaveatOverrideReasonClass`.

    Contract:

    - The classifier MUST be a pure function of its input.
    - The classifier MUST return a member of
      :class:`CaveatOverrideReasonClass`.
    - The classifier MUST return
      :attr:`CaveatOverrideReasonClass.UNSPECIFIED` iff ``raw is
      None``. The exporter validates this contract; a classifier
      that returns a different class for ``None`` input is a
      contract breach.
    """

    def classify(self, raw: Optional[str]) -> CaveatOverrideReasonClass:
        ...


def _default_classifier_classify(
    raw: Optional[str],
) -> CaveatOverrideReasonClass:
    """Default classifier: ``None`` -> UNSPECIFIED, else OTHER.

    Fail-safe: an operator who has not installed a richer
    classifier never accidentally leaks operator prose via a
    categorical surface that happens to align with the text
    content.
    """
    if raw is None:
        return CaveatOverrideReasonClass.UNSPECIFIED
    return CaveatOverrideReasonClass.OTHER


@dataclass(frozen=True)
class _DefaultCaveatOverrideReasonClassifier:
    """Default :class:`CaveatOverrideReasonClassifier`
    implementation.

    Frozen dataclass holding no state. Use the module-level
    constant :data:`DEFAULT_CLASSIFIER` rather than constructing
    a fresh instance.
    """

    def classify(
        self, raw: Optional[str]
    ) -> CaveatOverrideReasonClass:
        return _default_classifier_classify(raw)


#: Module-level default classifier instance.
DEFAULT_CLASSIFIER: CaveatOverrideReasonClassifier = (
    _DefaultCaveatOverrideReasonClassifier()
)


# ---------------------------------------------------------------------------
# Caveat-narrowing-class enum
# ---------------------------------------------------------------------------


class CaveatNarrowingClass(str, enum.Enum):
    """Categorical surface for the structural relationship
    between ``original_caveat_set`` and ``narrowed_caveat_set``.

    Computed by the exporter from the *structure* (predicate
    names + arguments) of the two sets — no free-form text leaks.

    Values:

    - :attr:`SUBSET_PROPER`: ``narrowed`` is a strict subset of
      ``original`` (the caveat chain was narrowed by *removing*
      one or more caveats). This is the canonical
      caveat-override gesture.
    - :attr:`SUBSET_EQUAL`: ``narrowed`` equals ``original``.
      Permitted (an override may record a reason without
      changing the chain) but the verifier MAY treat this as a
      no-op.
    - :attr:`SUPERSET`: ``narrowed`` is a strict superset of
      ``original`` — structurally ill-formed (override is meant
      to *narrow*, not expand). Operators MAY still export
      structurally-ill-formed events for forensic visibility;
      the categorical surface lets a peer-verifier filter them.
    - :attr:`INTERSECT_PARTIAL`: ``narrowed`` and ``original``
      have a non-empty intersection but neither is a subset of
      the other — structurally suspicious (the chain was both
      narrowed and expanded).
    - :attr:`DISJOINT`: ``narrowed`` and ``original`` are
      disjoint — structurally ill-formed (the chain was
      replaced).
    """

    SUBSET_PROPER = "SUBSET_PROPER"
    SUBSET_EQUAL = "SUBSET_EQUAL"
    SUPERSET = "SUPERSET"
    INTERSECT_PARTIAL = "INTERSECT_PARTIAL"
    DISJOINT = "DISJOINT"


def _classify_narrowing(
    original: Tuple[Tuple[str, Tuple[object, ...]], ...],
    narrowed: Tuple[Tuple[str, Tuple[object, ...]], ...],
) -> CaveatNarrowingClass:
    """Pure structural classifier.

    Uses set-of-(predicate, args) equality / subset / superset
    semantics. Caveat-chains are converted to frozensets of
    ``(predicate, args)`` tuples for the comparison; this is
    well-defined because ``_check_caveat_set`` (in
    :mod:`marker_composition`) already enforces hashable
    arguments.
    """
    o_set = frozenset(original)
    n_set = frozenset(narrowed)
    if o_set == n_set:
        return CaveatNarrowingClass.SUBSET_EQUAL
    if n_set < o_set:
        return CaveatNarrowingClass.SUBSET_PROPER
    if n_set > o_set:
        return CaveatNarrowingClass.SUPERSET
    if o_set & n_set:
        return CaveatNarrowingClass.INTERSECT_PARTIAL
    return CaveatNarrowingClass.DISJOINT


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CaveatOverrideExportError(MultiOrgSubstrateError):
    """Base class for caveat-override-event cross-org export
    errors.

    Inherits :class:`MultiOrgSubstrateError` so downstream callers
    that already catch the substrate base catch every exporter
    surface without broadening their handler.
    """


class CaveatOverrideExportShapeError(CaveatOverrideExportError):
    """The input event / attestation / sequence is structurally
    malformed.
    """


class CaveatOverrideExportReplayError(CaveatOverrideExportError):
    """Replay-protection breach: sequence_number is not strictly
    greater than the last seen sequence for the
    (route_id, original_caveat_chain_hash) pair.

    Attributes:
        route_id: the export route on which the replay was
            detected.
        chain_hash: the original-caveat-chain-hash subject to
            replay.
        last_seen_sequence: the highest sequence_number previously
            recorded for the pair.
        attempted_sequence: the sequence_number that triggered
            the breach.
    """

    def __init__(
        self,
        message: str,
        *,
        route_id: Optional[str] = None,
        chain_hash: Optional[str] = None,
        last_seen_sequence: Optional[int] = None,
        attempted_sequence: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.route_id = route_id
        self.chain_hash = chain_hash
        self.last_seen_sequence = last_seen_sequence
        self.attempted_sequence = attempted_sequence


class CaveatOverrideExportRawNarrativeLeakError(
    CaveatOverrideExportError
):
    """Defence-in-depth: a callsite attempted to construct an
    :class:`ExportedCaveatOverrideEvent` carrying a raw narrative
    field.

    Attributes:
        field_name: name of the field that carried raw narrative.
        type_name: type of the offending value.
    """

    def __init__(
        self,
        message: str,
        *,
        field_name: Optional[str] = None,
        type_name: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.field_name = field_name
        self.type_name = type_name


# ---------------------------------------------------------------------------
# Audit-trace + cross-org-witness types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditTraceEntry:
    """A single audit-trace projection in the cross-org export.

    Structural fields only — no free-form text. Mirrors the
    composition-reducer's internal
    :class:`~wirelang.federation.marker_composition.AuditTraceEntry`
    but without the operator-supplied ``outcome_reason``.

    Attributes:
        event_at: wall-clock at which the original event was
            observed (timezone-aware UTC).
        event_kind: closed-string enumeration of the underlying
            event family (``"revoke"``, ``"unrevoke"``,
            ``"re_issuance"``, ``"caveat_override"``,
            ``"bridge_revoked"``).
        outcome: closed-string enumeration of the reducer
            outcome (``"applied"``, ``"skipped"``,
            ``"terminal"``).
        wat_anchor_manifest_id: optional WAT-leaf anchor.
    """

    event_at: datetime
    event_kind: str
    outcome: str
    wat_anchor_manifest_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_at, datetime):
            raise CaveatOverrideExportShapeError(
                f"AuditTraceEntry.event_at must be a datetime: "
                f"type={type(self.event_at).__name__}"
            )
        if self.event_at.tzinfo is None:
            raise CaveatOverrideExportShapeError(
                "AuditTraceEntry.event_at must be timezone-aware"
            )
        if not isinstance(self.event_kind, str) or not self.event_kind:
            raise CaveatOverrideExportShapeError(
                f"AuditTraceEntry.event_kind must be a non-empty "
                f"string: {self.event_kind!r}"
            )
        if not isinstance(self.outcome, str) or not self.outcome:
            raise CaveatOverrideExportShapeError(
                f"AuditTraceEntry.outcome must be a non-empty "
                f"string: {self.outcome!r}"
            )
        if self.wat_anchor_manifest_id is not None and not isinstance(
            self.wat_anchor_manifest_id, str
        ):
            raise CaveatOverrideExportShapeError(
                f"AuditTraceEntry.wat_anchor_manifest_id must be "
                f"str or None: "
                f"type={type(self.wat_anchor_manifest_id).__name__}"
            )


@dataclass(frozen=True)
class CrossOrgWitness:
    """A single cross-org witness entry attached to an exported
    override event.

    The witness asserts that the override was independently
    observed under the given route-attestation. Witnesses
    contribute to the canonical ``override_event_id`` payload so
    a verifier can confirm both the export-route and the witness
    routes byte-deterministically.

    Attributes:
        route_id: the witness route_id (distinct from the
            primary export route_id).
        peer_trust_domain: the SPIFFE trust-domain of the
            witness peer.
        observed_at: timezone-aware UTC instant at which the
            witness observed the override.
    """

    route_id: str
    peer_trust_domain: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.route_id, str) or not self.route_id:
            raise CaveatOverrideExportShapeError(
                f"CrossOrgWitness.route_id must be a non-empty "
                f"string: {self.route_id!r}"
            )
        if (
            not isinstance(self.peer_trust_domain, str)
            or not self.peer_trust_domain
        ):
            raise CaveatOverrideExportShapeError(
                f"CrossOrgWitness.peer_trust_domain must be a "
                f"non-empty string: {self.peer_trust_domain!r}"
            )
        if not isinstance(self.observed_at, datetime):
            raise CaveatOverrideExportShapeError(
                f"CrossOrgWitness.observed_at must be a "
                f"datetime: type={type(self.observed_at).__name__}"
            )
        if self.observed_at.tzinfo is None:
            raise CaveatOverrideExportShapeError(
                "CrossOrgWitness.observed_at must be timezone-aware"
            )


# ---------------------------------------------------------------------------
# Sequence-number ledger
# ---------------------------------------------------------------------------


class SequenceNumberLedger(Protocol):
    """Durable ledger of (route_id, chain_hash) -> last_sequence.

    The default in-memory implementation
    :class:`InMemorySequenceNumberLedger` is suitable for tests
    and single-process exporters; production deployments install
    a NATS-KV-backed ledger (Sprint-9 Tag-N+ slot).
    """

    def next_sequence(
        self, *, route_id: str, chain_hash: str
    ) -> int:
        """Return the next sequence_number the exporter should
        use for the pair.

        Implementations MAY return ``last_seen + 1`` if a last
        sequence exists, else ``1``. The first sequence
        emitted for any (route_id, chain_hash) pair is ``1``
        (not ``0``); the ``0`` sentinel is reserved as "no
        prior export".
        """
        ...

    def record_export(
        self,
        *,
        route_id: str,
        chain_hash: str,
        sequence: int,
    ) -> None:
        """Durably record an export at the given sequence.

        Raises:
            :class:`CaveatOverrideExportReplayError` iff the
            sequence is not strictly greater than the last
            recorded sequence for the pair.
        """
        ...

    def last_seen(
        self, *, route_id: str, chain_hash: str
    ) -> int:
        """Return the highest sequence_number previously
        recorded for the pair, or ``0`` if none.
        """
        ...


@dataclass
class InMemorySequenceNumberLedger:
    """In-memory implementation of :class:`SequenceNumberLedger`.

    Hermetic-test-grade and single-process-exporter-grade. NOT
    durable; restart-on-crash loses the ledger state. Production
    deployments install a NATS-KV-backed ledger (Sprint-9 Tag-N+
    slot).
    """

    _state: Dict[Tuple[str, str], int] = field(default_factory=dict)

    def next_sequence(
        self, *, route_id: str, chain_hash: str
    ) -> int:
        last = self._state.get((route_id, chain_hash), 0)
        return last + 1

    def record_export(
        self,
        *,
        route_id: str,
        chain_hash: str,
        sequence: int,
    ) -> None:
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise CaveatOverrideExportShapeError(
                f"sequence must be int: "
                f"type={type(sequence).__name__}"
            )
        if sequence < 1:
            raise CaveatOverrideExportShapeError(
                f"sequence must be >= 1: got {sequence}"
            )
        last = self._state.get((route_id, chain_hash), 0)
        if sequence <= last:
            raise CaveatOverrideExportReplayError(
                f"sequence {sequence} is not strictly greater "
                f"than last_seen {last} for "
                f"(route_id={route_id!r}, "
                f"chain_hash={chain_hash!r})",
                route_id=route_id,
                chain_hash=chain_hash,
                last_seen_sequence=last,
                attempted_sequence=sequence,
            )
        self._state[(route_id, chain_hash)] = sequence

    def last_seen(
        self, *, route_id: str, chain_hash: str
    ) -> int:
        return self._state.get((route_id, chain_hash), 0)


# ---------------------------------------------------------------------------
# Export envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportedCaveatOverrideEvent:
    """The cross-org export envelope of a
    :class:`CaveatOverrideEvent`.

    Frozen, equality-by-value, safe to anchor into WAT-Audit-
    Federation-Annex merkle leaves. The
    :attr:`override_event_id` is a BLAKE2b-256 digest over a
    JCS-compatible canonicalised representation of the envelope —
    re-exporting a byte-equal source event against the same route
    attestation at the same sequence_number yields a byte-equal
    :attr:`override_event_id`.

    Attributes:
        export_schema: always :data:`EXPORT_SCHEMA`.
        route_id: the export route_id.
        sequence_number: monotonically increasing per
            (route_id, original_caveat_chain_hash) tuple. The
            first export for any pair is ``1``.
        override_event_id: BLAKE2b-256 digest (32 bytes) of the
            canonicalised envelope payload. Stable across
            re-export of byte-equal source events under the
            same route_id at the same sequence_number.
        event_at: source event's
            :attr:`CaveatOverrideEvent.event_at`
            (timing-only — retained raw).
        original_caveat_chain_hash: BLAKE2b-256-hex digest
            (64 chars) of the source event's
            ``original_caveat_set``, route-scoped.
        narrowed_caveat_chain_hash: BLAKE2b-256-hex digest
            (64 chars) of the source event's
            ``narrowed_caveat_set``, route-scoped.
        caveat_narrowing_class: structural classification.
        override_reason_class: classification of the operator-
            supplied free-form reason.
        override_reason_hash: route-scoped BLAKE2b-256-hex digest
            of the raw ``override_reason``, or ``None`` if the
            source event carried ``override_reason = None``.
        audit_trace: ordered tuple of :class:`AuditTraceEntry`
            structural-only records.
        cross_org_witnesses: sorted tuple of
            :class:`CrossOrgWitness` entries (sorted by
            ``(route_id, peer_trust_domain, observed_at)`` for
            canonical equality).
        exported_at: when the export was computed (timezone-aware
            UTC).

    Invariants enforced by :meth:`__post_init__`:

    - ``export_schema == EXPORT_SCHEMA``.
    - ``route_id`` non-empty string.
    - ``sequence_number`` positive integer.
    - ``override_event_id`` is :class:`bytes` of length 32.
    - ``event_at`` is tz-aware datetime.
    - ``original_caveat_chain_hash`` and
      ``narrowed_caveat_chain_hash`` are 64-char hex strings.
    - ``caveat_narrowing_class`` is a
      :class:`CaveatNarrowingClass`.
    - ``override_reason_class`` is a
      :class:`CaveatOverrideReasonClass`.
    - ``override_reason_hash`` is either ``None`` or a 64-char
      hex string.
    - ``audit_trace`` is a tuple of
      :class:`AuditTraceEntry` instances.
    - ``cross_org_witnesses`` is a tuple of
      :class:`CrossOrgWitness` instances.
    - ``exported_at`` is tz-aware datetime.
    - No raw narrative fields present (defence-in-depth via
      :class:`CaveatOverrideExportRawNarrativeLeakError`).
    """

    export_schema: str
    route_id: str
    sequence_number: int
    override_event_id: bytes
    event_at: datetime
    original_caveat_chain_hash: str
    narrowed_caveat_chain_hash: str
    caveat_narrowing_class: CaveatNarrowingClass
    override_reason_class: CaveatOverrideReasonClass
    override_reason_hash: Optional[str]
    audit_trace: Tuple[AuditTraceEntry, ...]
    cross_org_witnesses: Tuple[CrossOrgWitness, ...]
    exported_at: datetime

    def __post_init__(self) -> None:
        if self.export_schema != EXPORT_SCHEMA:
            raise CaveatOverrideExportShapeError(
                f"export_schema must equal {EXPORT_SCHEMA!r}; "
                f"got {self.export_schema!r}"
            )
        if not isinstance(self.route_id, str) or self.route_id == "":
            raise CaveatOverrideExportShapeError(
                f"route_id must be a non-empty string; got "
                f"{self.route_id!r}"
            )
        if (
            not isinstance(self.sequence_number, int)
            or isinstance(self.sequence_number, bool)
            or self.sequence_number < 1
        ):
            raise CaveatOverrideExportShapeError(
                f"sequence_number must be int >= 1; got "
                f"{self.sequence_number!r}"
            )
        if (
            not isinstance(self.override_event_id, bytes)
            or len(self.override_event_id) != 32
        ):
            raise CaveatOverrideExportShapeError(
                f"override_event_id must be 32 bytes "
                f"(BLAKE2b-256); got "
                f"type={type(self.override_event_id).__name__}, "
                f"len="
                f"{len(self.override_event_id) if isinstance(self.override_event_id, (bytes, bytearray)) else 'n/a'}"
            )
        for ts_name, ts in (
            ("event_at", self.event_at),
            ("exported_at", self.exported_at),
        ):
            if not isinstance(ts, datetime):
                raise CaveatOverrideExportShapeError(
                    f"{ts_name} must be a datetime; got "
                    f"type={type(ts).__name__}"
                )
            if ts.tzinfo is None:
                raise CaveatOverrideExportShapeError(
                    f"{ts_name} must be timezone-aware"
                )
        for h_name, h in (
            ("original_caveat_chain_hash", self.original_caveat_chain_hash),
            ("narrowed_caveat_chain_hash", self.narrowed_caveat_chain_hash),
        ):
            if not isinstance(h, str) or len(h) != 64:
                raise CaveatOverrideExportShapeError(
                    f"{h_name} must be a 64-char hex string; got "
                    f"len={len(h) if isinstance(h, str) else 'n/a'}, "
                    f"type={type(h).__name__}"
                )
            try:
                int(h, 16)
            except ValueError as exc:
                raise CaveatOverrideExportShapeError(
                    f"{h_name} must be a hex string; got {h!r}"
                ) from exc
        if not isinstance(
            self.caveat_narrowing_class, CaveatNarrowingClass
        ):
            raise CaveatOverrideExportShapeError(
                f"caveat_narrowing_class must be a "
                f"CaveatNarrowingClass; got type="
                f"{type(self.caveat_narrowing_class).__name__}"
            )
        if not isinstance(
            self.override_reason_class, CaveatOverrideReasonClass
        ):
            raise CaveatOverrideExportShapeError(
                f"override_reason_class must be a "
                f"CaveatOverrideReasonClass; got type="
                f"{type(self.override_reason_class).__name__}"
            )
        if self.override_reason_hash is not None:
            if (
                not isinstance(self.override_reason_hash, str)
                or len(self.override_reason_hash) != 64
            ):
                raise CaveatOverrideExportShapeError(
                    f"override_reason_hash must be a 64-char hex "
                    f"string or None; got "
                    f"type={type(self.override_reason_hash).__name__}, "
                    f"len="
                    f"{len(self.override_reason_hash) if isinstance(self.override_reason_hash, str) else 'n/a'}"
                )
            try:
                int(self.override_reason_hash, 16)
            except ValueError as exc:
                raise CaveatOverrideExportShapeError(
                    f"override_reason_hash must be a hex string; "
                    f"got {self.override_reason_hash!r}"
                ) from exc
        if not isinstance(self.audit_trace, tuple):
            raise CaveatOverrideExportShapeError(
                f"audit_trace must be a tuple; got "
                f"type={type(self.audit_trace).__name__}"
            )
        for idx, entry in enumerate(self.audit_trace):
            if not isinstance(entry, AuditTraceEntry):
                raise CaveatOverrideExportShapeError(
                    f"audit_trace[{idx}] must be an "
                    f"AuditTraceEntry; got "
                    f"type={type(entry).__name__}"
                )
        if not isinstance(self.cross_org_witnesses, tuple):
            raise CaveatOverrideExportShapeError(
                f"cross_org_witnesses must be a tuple; got "
                f"type={type(self.cross_org_witnesses).__name__}"
            )
        for idx, witness in enumerate(self.cross_org_witnesses):
            if not isinstance(witness, CrossOrgWitness):
                raise CaveatOverrideExportShapeError(
                    f"cross_org_witnesses[{idx}] must be a "
                    f"CrossOrgWitness; got "
                    f"type={type(witness).__name__}"
                )
        # Raw-narrative leak gate.
        for forbidden in (
            "override_reason",
            "original_caveat_set",
            "narrowed_caveat_set",
        ):
            if forbidden in self.__dict__ or hasattr(
                type(self), forbidden
            ):
                offender = (
                    self.__dict__.get(forbidden)
                    if forbidden in self.__dict__
                    else getattr(type(self), forbidden)
                )
                raise CaveatOverrideExportRawNarrativeLeakError(
                    f"ExportedCaveatOverrideEvent may not carry "
                    f"the raw narrative field {forbidden!r}; "
                    f"found on instance",
                    field_name=forbidden,
                    type_name=type(offender).__name__,
                )


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaveatOverrideEventCrossOrgExporter:
    """Stateless exporter from
    :class:`CaveatOverrideEvent` to
    :class:`ExportedCaveatOverrideEvent`.

    The exporter is a frozen dataclass holding pluggable
    classifier and ledger references plus an optional clock.
    Construction is cheap; one exporter instance can be reused
    across many export calls.

    Pseudonymisation pattern (ADR-0031 D4) is hard-wired:

    1. Strip raw ``override_reason``.
    2. Strip raw ``original_caveat_set`` / ``narrowed_caveat_set``
       (replaced by route-scoped chain-hashes).
    3. Classify ``override_reason`` via the installed
       :class:`CaveatOverrideReasonClassifier`.
    4. Classify structural narrowing via
       :func:`_classify_narrowing`.
    5. Hash ``override_reason`` via BLAKE2b-256 keyed by
       ``route_id`` (if present).
    6. Retain raw timing fields, schema, route_id,
       sequence_number, override_event_id.

    Replay-protection is enforced via the installed
    :class:`SequenceNumberLedger`. Failure modes are typed and
    structured.
    """

    classifier: CaveatOverrideReasonClassifier = field(
        default=DEFAULT_CLASSIFIER
    )
    ledger: SequenceNumberLedger = field(
        default_factory=InMemorySequenceNumberLedger
    )
    clock: Optional[Any] = field(default=None)

    def _now(self) -> datetime:
        if self.clock is not None:
            value = self.clock()
            if not isinstance(value, datetime):
                raise TypeError(
                    "CaveatOverrideEventCrossOrgExporter.clock "
                    "must return a datetime"
                )
            if value.tzinfo is None:
                raise ValueError(
                    "CaveatOverrideEventCrossOrgExporter.clock "
                    "must return a timezone-aware UTC datetime"
                )
            return value
        return datetime.now(timezone.utc)

    def export(
        self,
        *,
        event: CaveatOverrideEvent,
        attestation: MultiOrgRouteAttestation,
        audit_trace: Tuple[AuditTraceEntry, ...] = (),
        cross_org_witnesses: Tuple[CrossOrgWitness, ...] = (),
        sequence_number: Optional[int] = None,
    ) -> ExportedCaveatOverrideEvent:
        """Export a single :class:`CaveatOverrideEvent` for the
        given cross-org route.

        Parameters:
            event: the source-org event to export.
            attestation: the route attestation.
            audit_trace: optional ordered tuple of structural
                audit-trace entries to attach.
            cross_org_witnesses: optional tuple of cross-org
                witnesses; they are sorted canonically by the
                exporter prior to canonicalisation so witness-
                insertion-order is irrelevant.
            sequence_number: optional explicit sequence_number.
                If ``None``, the exporter consults the ledger for
                the next sequence. If provided, the exporter
                still records-and-validates against the ledger
                (so replay is detected).

        Returns:
            :class:`ExportedCaveatOverrideEvent`.

        Raises:
            :class:`CaveatOverrideExportShapeError` on any input
            type / content breach.
            :class:`CaveatOverrideExportReplayError` on
            sequence_number monotonicity breach.
        """
        # Shape gates.
        if not isinstance(event, CaveatOverrideEvent):
            raise CaveatOverrideExportShapeError(
                f"event must be a CaveatOverrideEvent; got "
                f"type={type(event).__name__}"
            )
        if not isinstance(attestation, MultiOrgRouteAttestation):
            raise CaveatOverrideExportShapeError(
                f"attestation must be a MultiOrgRouteAttestation; "
                f"got type={type(attestation).__name__}"
            )
        if not isinstance(audit_trace, tuple):
            raise CaveatOverrideExportShapeError(
                f"audit_trace must be a tuple; got "
                f"type={type(audit_trace).__name__}"
            )
        for idx, entry in enumerate(audit_trace):
            if not isinstance(entry, AuditTraceEntry):
                raise CaveatOverrideExportShapeError(
                    f"audit_trace[{idx}] must be an "
                    f"AuditTraceEntry; got "
                    f"type={type(entry).__name__}"
                )
        if not isinstance(cross_org_witnesses, tuple):
            raise CaveatOverrideExportShapeError(
                f"cross_org_witnesses must be a tuple; got "
                f"type={type(cross_org_witnesses).__name__}"
            )
        for idx, witness in enumerate(cross_org_witnesses):
            if not isinstance(witness, CrossOrgWitness):
                raise CaveatOverrideExportShapeError(
                    f"cross_org_witnesses[{idx}] must be a "
                    f"CrossOrgWitness; got "
                    f"type={type(witness).__name__}"
                )

        # Classify operator gesture.
        try:
            reason_class = self.classifier.classify(
                event.override_reason
            )
        except Exception as exc:  # noqa: BLE001
            raise CaveatOverrideExportShapeError(
                f"classifier raised on classify(raw="
                f"{event.override_reason!r}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(reason_class, CaveatOverrideReasonClass):
            raise CaveatOverrideExportShapeError(
                f"classifier returned non-CaveatOverrideReasonClass "
                f"value: type={type(reason_class).__name__}"
            )
        if event.override_reason is None and reason_class != (
            CaveatOverrideReasonClass.UNSPECIFIED
        ):
            raise CaveatOverrideExportShapeError(
                f"classifier returned {reason_class!r} for None "
                f"override_reason; contract requires UNSPECIFIED"
            )

        # Structural narrowing classification.
        narrowing_class = _classify_narrowing(
            event.original_caveat_set, event.narrowed_caveat_set
        )

        # Hash caveat-chains (route-scoped).
        original_chain_hash = _route_scoped_chain_hash(
            route_id=attestation.route_id,
            caveat_set=event.original_caveat_set,
        )
        narrowed_chain_hash = _route_scoped_chain_hash(
            route_id=attestation.route_id,
            caveat_set=event.narrowed_caveat_set,
        )

        # Hash override_reason (route-scoped, if present).
        reason_hash: Optional[str]
        if event.override_reason is None:
            reason_hash = None
        else:
            reason_hash = _route_scoped_reason_hash(
                route_id=attestation.route_id,
                raw=event.override_reason,
            )

        # Sort witnesses canonically prior to canonicalisation.
        sorted_witnesses = tuple(
            sorted(
                cross_org_witnesses,
                key=lambda w: (
                    w.route_id,
                    w.peer_trust_domain,
                    w.observed_at.astimezone(timezone.utc).isoformat(),
                ),
            )
        )

        # Resolve sequence_number.
        if sequence_number is None:
            seq = self.ledger.next_sequence(
                route_id=attestation.route_id,
                chain_hash=original_chain_hash,
            )
        else:
            if not isinstance(sequence_number, int) or isinstance(
                sequence_number, bool
            ):
                raise CaveatOverrideExportShapeError(
                    f"sequence_number must be int: "
                    f"type={type(sequence_number).__name__}"
                )
            if sequence_number < 1:
                raise CaveatOverrideExportShapeError(
                    f"sequence_number must be >= 1: got "
                    f"{sequence_number}"
                )
            seq = sequence_number

        # Record in ledger (raises on replay).
        self.ledger.record_export(
            route_id=attestation.route_id,
            chain_hash=original_chain_hash,
            sequence=seq,
        )

        exported_at = self._now()

        # Compute override_event_id.
        override_event_id = _compute_override_event_id(
            route_id=attestation.route_id,
            sequence_number=seq,
            event_at=event.event_at,
            original_chain_hash=original_chain_hash,
            narrowed_chain_hash=narrowed_chain_hash,
            narrowing_class=narrowing_class,
            reason_class=reason_class,
            reason_hash=reason_hash,
            audit_trace=audit_trace,
            cross_org_witnesses=sorted_witnesses,
        )

        return ExportedCaveatOverrideEvent(
            export_schema=EXPORT_SCHEMA,
            route_id=attestation.route_id,
            sequence_number=seq,
            override_event_id=override_event_id,
            event_at=event.event_at,
            original_caveat_chain_hash=original_chain_hash,
            narrowed_caveat_chain_hash=narrowed_chain_hash,
            caveat_narrowing_class=narrowing_class,
            override_reason_class=reason_class,
            override_reason_hash=reason_hash,
            audit_trace=audit_trace,
            cross_org_witnesses=sorted_witnesses,
            exported_at=exported_at,
        )


# ---------------------------------------------------------------------------
# Verifier-side replay-detection
# ---------------------------------------------------------------------------


def detect_replay(
    *,
    exported: ExportedCaveatOverrideEvent,
    ledger: SequenceNumberLedger,
) -> None:
    """Symmetric verifier-side replay-protection gate.

    A verifier in Org-B that consumes an
    :class:`ExportedCaveatOverrideEvent` from Org-A SHOULD call
    :func:`detect_replay` against its own
    :class:`SequenceNumberLedger`. The function records the
    exported event into the verifier-side ledger and raises
    :class:`CaveatOverrideExportReplayError` iff the sequence is
    not strictly greater than the verifier's last seen.

    This blocks bridge-cycle re-replay: a hostile bridge that
    cycles an exported event back through Org-B's verifier
    cannot replay it at the same or lower sequence_number.

    Parameters:
        exported: the export envelope just received.
        ledger: the verifier-side
            :class:`SequenceNumberLedger`.

    Raises:
        :class:`CaveatOverrideExportReplayError` on replay.
        :class:`CaveatOverrideExportShapeError` on input shape
        breach.
    """
    if not isinstance(exported, ExportedCaveatOverrideEvent):
        raise CaveatOverrideExportShapeError(
            f"exported must be an ExportedCaveatOverrideEvent; "
            f"got type={type(exported).__name__}"
        )
    ledger.record_export(
        route_id=exported.route_id,
        chain_hash=exported.original_caveat_chain_hash,
        sequence=exported.sequence_number,
    )


# ---------------------------------------------------------------------------
# Canonical hash helpers
# ---------------------------------------------------------------------------


def _canonicalise_caveat_set(
    caveat_set: Tuple[Tuple[str, Tuple[object, ...]], ...],
) -> str:
    """Convert a caveat-set to a JCS-canonical JSON string.

    The set is converted to a sorted list of [predicate, args]
    pairs, where args is a list. Sorting is by (predicate, args)
    tuple lexicographically. The output is suitable as input to
    a BLAKE2b digest.

    Note: this canonicalisation does NOT hash the caveat args
    themselves; it serialises them. The output IS the
    pre-hash payload. The hash is route-scoped via
    :func:`_route_scoped_chain_hash`.
    """

    def _stringify_args(args: Tuple[object, ...]) -> list:
        # JSON only supports str/int/float/bool/None/list/dict.
        # Caveat args MAY include tuples (themselves containing
        # primitives); we recursively convert tuple-of-args to
        # list-of-args for JSON serialisation. Other hashable
        # types (bytes, datetimes) we convert to their str()
        # form for deterministic serialisation.
        out: list = []
        for a in args:
            if isinstance(a, (str, int, float, bool)) or a is None:
                out.append(a)
            elif isinstance(a, tuple):
                out.append(_stringify_args(a))
            elif isinstance(a, bytes):
                out.append(f"<bytes:{a.hex()}>")
            elif isinstance(a, datetime):
                out.append(
                    a.astimezone(timezone.utc).isoformat()
                    if a.tzinfo is not None
                    else a.isoformat()
                )
            else:
                out.append(repr(a))
        return out

    pairs = [
        [predicate, _stringify_args(args)]
        for (predicate, args) in caveat_set
    ]
    pairs.sort(key=lambda p: json.dumps(p, sort_keys=True, separators=(",", ":")))
    return json.dumps(pairs, sort_keys=True, separators=(",", ":"))


def _route_scoped_chain_hash(
    *,
    route_id: str,
    caveat_set: Tuple[Tuple[str, Tuple[object, ...]], ...],
) -> str:
    """BLAKE2b-256-hex digest of a caveat-set keyed by ``route_id``.

    Route-scoping prevents cross-route equality-correlation: the
    same caveat-set under two different cross-org routes
    produces two different chain-hashes.
    """
    key = route_id.encode("utf-8")[:64]
    h = hashlib.blake2b(
        digest_size=32,
        key=key,
        person=_CHAIN_HASH_PERSONALISATION,
    )
    h.update(_canonicalise_caveat_set(caveat_set).encode("utf-8"))
    return h.hexdigest()


def _route_scoped_reason_hash(*, route_id: str, raw: str) -> str:
    """BLAKE2b-256-hex digest of ``raw`` keyed by ``route_id``.

    The personalisation byte-string is distinct from
    :data:`_CHAIN_HASH_PERSONALISATION` so a reason text equal to
    a caveat-set canonicalisation does not collide on the digest.
    """
    key = route_id.encode("utf-8")[:64]
    h = hashlib.blake2b(
        digest_size=32,
        key=key,
        person=_REASON_HASH_PERSONALISATION,
    )
    h.update(raw.encode("utf-8"))
    return h.hexdigest()


def _audit_trace_to_canonical(
    audit_trace: Tuple[AuditTraceEntry, ...],
) -> list:
    return [
        {
            "event_at": entry.event_at.astimezone(timezone.utc).isoformat(),
            "event_kind": entry.event_kind,
            "outcome": entry.outcome,
            "wat_anchor_manifest_id": entry.wat_anchor_manifest_id,
        }
        for entry in audit_trace
    ]


def _witnesses_to_canonical(
    witnesses: Tuple[CrossOrgWitness, ...],
) -> list:
    return [
        {
            "route_id": w.route_id,
            "peer_trust_domain": w.peer_trust_domain,
            "observed_at": w.observed_at.astimezone(
                timezone.utc
            ).isoformat(),
        }
        for w in witnesses
    ]


def _compute_override_event_id(
    *,
    route_id: str,
    sequence_number: int,
    event_at: datetime,
    original_chain_hash: str,
    narrowed_chain_hash: str,
    narrowing_class: CaveatNarrowingClass,
    reason_class: CaveatOverrideReasonClass,
    reason_hash: Optional[str],
    audit_trace: Tuple[AuditTraceEntry, ...],
    cross_org_witnesses: Tuple[CrossOrgWitness, ...],
) -> bytes:
    """BLAKE2b-256 digest over a canonicalised export payload.

    The payload mixes the export-schema (domain-separator), the
    route_id, the sequence_number, the event_at, the chain-hashes,
    the classification surfaces, and the audit/witness tuples.
    Notably ``exported_at`` is NOT included so re-exporting the
    same source event at a different wall-clock produces a
    byte-equal :attr:`override_event_id`.
    """
    payload = {
        "schema": EXPORT_SCHEMA,
        "route_id": route_id,
        "sequence_number": sequence_number,
        "event_at": event_at.astimezone(timezone.utc).isoformat(),
        "original_caveat_chain_hash": original_chain_hash,
        "narrowed_caveat_chain_hash": narrowed_chain_hash,
        "caveat_narrowing_class": narrowing_class.value,
        "override_reason_class": reason_class.value,
        "override_reason_hash": reason_hash,
        "audit_trace": _audit_trace_to_canonical(audit_trace),
        "cross_org_witnesses": _witnesses_to_canonical(
            cross_org_witnesses
        ),
    }
    payload_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.blake2b(payload_bytes, digest_size=32).digest()


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "EXPORT_SCHEMA",
    "DEFAULT_CLASSIFIER",
    "CaveatOverrideReasonClass",
    "CaveatOverrideReasonClassifier",
    "CaveatNarrowingClass",
    "AuditTraceEntry",
    "CrossOrgWitness",
    "SequenceNumberLedger",
    "InMemorySequenceNumberLedger",
    "CaveatOverrideExportError",
    "CaveatOverrideExportShapeError",
    "CaveatOverrideExportReplayError",
    "CaveatOverrideExportRawNarrativeLeakError",
    "ExportedCaveatOverrideEvent",
    "CaveatOverrideEventCrossOrgExporter",
    "detect_replay",
]
