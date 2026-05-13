# SPDX-License-Identifier: BUSL-1.1
"""UnrevokeAuditMarker cross-org export surface.

Phase-2 Sprint-7 Tag-5 lands the cross-org export pattern for the
Sprint-6 Tag-9
:class:`~wirelang.schemas.capability_policy_nats_kv_backend.UnrevokeAuditMarker`.
The marker is a load-bearing audit-trail-artefact within a single
Wakir-Org bucket: the watch-stream classifier from Sprint-6 Tag-3
uses the marker to distinguish operator-deliberate unrevoke
(``EXPLICIT_UNREVOKE``) from substrate-corruption /
out-of-band-override (``REVOCATION_MONOTONIC_BREACH``). For
**multi-org federation** scenarios (Sprint-7 Tag-1+ substrate), the
internal marker MUST NOT leak naively across an org boundary: the
marker carries free-form operator-supplied text
(``unrevoke_reason``) and operator-supplied prior-revocation text
(``previous_revocation_reason``), both of which are Wakir-internal
audit narrative and a Brand-Guide-§9-No-Go for cross-org export.

The cross-org export surface introduced here mediates the
boundary. The exporter:

1. **Strips** the raw operator-supplied free-form text fields
   (``unrevoke_reason``, ``previous_revocation_reason``) so they
   never appear in the exported envelope.
2. **Pseudonymises** identity-adjacent fields per ADR-0031 D4
   (``did:web`` + Pseudonymisierungs-Pattern):
   ``previous_revocation_reason`` is hashed via BLAKE2b-256
   with a route-scoped key, producing
   ``previous_revocation_reason_hash`` — an
   audit-deterministic-but-not-back-readable digest that lets a
   peer compare two markers' prior-revocation-reasons for
   equality without learning the text.
3. **Categorises** the operator gesture via a pluggable
   :class:`UnrevokeReasonClassifier` Protocol that maps free-form
   text into one of the categorical
   :class:`UnrevokeReasonClass` enum values (default classifier:
   :attr:`UnrevokeReasonClass.OTHER` — fail-safe; the operator is
   responsible for installing a richer classifier if they want a
   finer category surface).
4. **Retains raw** only the strictly-timing fields
   (``previous_revoked_at``, ``exported_at``) and the
   non-identity envelope fields (``route_id``, ``export_schema``,
   ``marker_id``).

Resulting envelope: :class:`ExportedUnrevokeAuditMarker`,
frozen-dataclass. The :attr:`ExportedUnrevokeAuditMarker.marker_id`
is a BLAKE2b-256 digest over a JCS-compatible canonicalised
payload mixing the export-schema, route-id, previous-revoked-at,
reason-class, and the optional reason-hash; re-exporting a
byte-equal source marker against the same route attestation
produces a byte-equal ``marker_id`` (timing-invariant).

Pseudonymisation pattern (ADR-0031 D4 alignment)
================================================

ADR-0031 D4 specifies, for Persona-Identity-Cross-Org-Resolution,
the pattern "Public-Key + Rolle, kein Klarname" (public key plus
role descriptor, no clear name). The same logic applies to
audit-trail fields: cross-org export reveals **structure** (an
unrevoke happened, at this timing, in this category) without
revealing **narrative** (the operator's free-form prose).
Concretely:

============================================  ==========================  ==============================
Field                                          Treatment                    Rationale
============================================  ==========================  ==============================
``previous_revoked_at``                        raw (retained)               Timing-only, no identity
``unrevoke_reason`` (raw)                      **stripped**                 Free-form operator narrative
``unrevoke_reason_class`` (categorised)        retained                     Categorical, finite-set
``previous_revocation_reason`` (raw)           **stripped**                 Free-form operator narrative
``previous_revocation_reason_hash``            BLAKE2b-256-hashed           Equality-comparable, not reversible
``route_id``                                   raw (retained)               Already a federation surface
``schema``                                     raw (retained)               Constant per export-schema
``marker_id``                                  computed (retained)          Stable audit-leaf identifier
``exported_at``                                raw (retained)               Timing-only, no identity
============================================  ==========================  ==============================

The exporter does NOT export the source-org operator identity
(``registered_by_publisher`` from the record): that field lives on
the record-envelope, not on the marker itself, so the cross-org
export surface — which consumes the marker, not the record —
cannot leak the operator identity by construction. (A future
extension that wanted to publish the marker *with* its record-
wrapper would require a separate `CapabilityPolicyRecord` cross-
org exporter — out of scope for Tag-5.)

The hash for ``previous_revocation_reason_hash`` is keyed by the
``route_id`` to prevent cross-route equality-correlation: the
same operator-prose under two different cross-org routes
produces two different hashes, so a peer cannot accumulate a
cross-route reason-fingerprint database.

Failure-mode hierarchy
======================

All errors parent on
:class:`~wirelang.federation.multi_org_substrate.MultiOrgSubstrateError`
so existing catch-base callers absorb every exporter surface
uniformly.

- :class:`UnrevokeAuditMarkerCrossOrgExportError` — base.
- :class:`UnrevokeAuditMarkerShapeError` — malformed input (wrong
  type, tz-naive timestamp, missing route_id, etc.).
- :class:`RawNarrativeLeakError` — defence-in-depth: raised iff a
  callsite tries to construct an
  :class:`ExportedUnrevokeAuditMarker` carrying a raw narrative
  field (``unrevoke_reason`` or ``previous_revocation_reason``).
  The exporter never emits these fields itself; this error
  protects against a constructor-bypass call path.

The exporter is **fail-closed** on every shape gate. A malformed
marker yields no partial export.

WAT-Audit-Federation-Annex anchoring
====================================

The export artefact carries the schema URI
``wakir.federation.unrevoke-audit-marker-export/1`` so the
WAT-Audit-Federation-Annex (Tomás D-1, forthcoming) can anchor
exported markers into both peer-org and Wakir-org WAT merkle
leaves with a stable label. Phase-1b convention applies:
``wakir.`` prefix, kebab-case noun, integer version suffix. The
:attr:`ExportedUnrevokeAuditMarker.marker_id` is the load-bearing
leaf-anchor field — it is BLAKE2b-256 (32 bytes), JCS-canonical,
and route-scoped, mirroring the
:attr:`~wirelang.federation.capability_attenuation_chain_verifier.VerifiedAttenuationChain.chain_hash`
and
:attr:`~wirelang.federation.spiffe_cross_trust_domain_bridge.BRIDGE_RESOLUTION_SCHEMA`
conventions established Tag-3..Tag-4.

ADR-0050 Tool-Surface-Stempel
=============================

This file was authored using Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this module.

ADR-0049 Pre-Box-Worktree
=========================

This module was authored in an isolated worktree
``/tmp/reza-sprint-7-tag-5-runtime`` with the ``-runtime``
suffix from Tag-4-Tip ``3e2ebbe``. Tag-5 substantively depends
on Sprint-6 Tag-9
:class:`~wirelang.schemas.capability_policy_nats_kv_backend.UnrevokeAuditMarker`
and Sprint-7 Tag-1
:class:`~wirelang.federation.multi_org_substrate.MultiOrgRouteAttestation`.
The worktree is cleaned up after the β-push.

Cross-references
================

- Sprint-6 Tag-9 ``UnrevokeAuditMarker``:
  ``wirelang/schemas/capability_policy_nats_kv_backend.py``.
- Sprint-6 Tag-3 revocation-event-filter classifier
  (consumes the marker on the watch-side):
  ``wirelang/schemas/revocation_event_filter.py``.
- Sprint-7 Tag-1 federation substrate
  (``MultiOrgRouteAttestation`` carrier of the export route):
  ``wirelang/federation/multi_org_substrate.py``.
- Sprint-7 Tag-2 NATS-KV backend (durable target):
  ``wirelang/federation/multi_org_attestation_nats_kv_backend.py``.
- ADR-0031 D4 Pseudonymisierungs-Pattern.

Version
=======

``wakir.federation.unrevoke-audit-marker-export/1``.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from .multi_org_substrate import (
    MultiOrgRouteAttestation,
    MultiOrgSubstrateError,
)
from ..schemas.capability_policy_nats_kv_backend import (
    UnrevokeAuditMarker,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Schema-URI for the exported-unrevoke-audit-marker artefact.
#: Consumed by the WAT-Audit-Federation-Annex (Tomás D-1,
#: forthcoming) when anchoring an exported marker into both
#: peer-org and Wakir-org WAT merkle leaves. Phase-1b convention:
#: ``wakir.`` prefix, kebab-case noun, integer version suffix.
EXPORT_SCHEMA: str = "wakir.federation.unrevoke-audit-marker-export/1"


#: BLAKE2b key personalisation for ``previous_revocation_reason``
#: pseudonymisation. The hash is route-scoped: the same operator
#: text under two different cross-org routes produces two
#: different hashes so a peer cannot accumulate a cross-route
#: reason-fingerprint database. The personalisation byte-string
#: is fixed at module load (no dynamic salting on construction)
#: so the export is deterministic across exporter invocations.
_REASON_HASH_PERSONALISATION: bytes = b"wakir-ump-1\x00\x00\x00\x00\x00"
# BLAKE2b personalisation must be exactly 16 bytes.
assert len(_REASON_HASH_PERSONALISATION) == 16


# ---------------------------------------------------------------------------
# Reason-classification enum + default classifier
# ---------------------------------------------------------------------------


class UnrevokeReasonClass(str, enum.Enum):
    """Categorical surface for the operator-supplied
    ``unrevoke_reason``.

    The exporter classifies the free-form
    :attr:`UnrevokeAuditMarker.unrevoke_reason` (or absence
    thereof) into one of these values. The classifier itself is
    pluggable via :class:`UnrevokeReasonClassifier`; the default
    classifier (built-in fallback)
    :func:`_DEFAULT_CLASSIFIER` maps every present reason to
    :attr:`OTHER` and absent reason to :attr:`UNSPECIFIED`. An
    operator who wants finer categorisation MUST install a richer
    classifier.

    The enum is :class:`str`-valued so JCS-canonical JSON encoding
    is straightforward.

    Values:

    - :attr:`UNSPECIFIED`: source marker carried ``unrevoke_reason
      = None``. The operator did not record a reason.
    - :attr:`OPERATOR_RECOVERY`: operator-recovery gesture
      (substrate-state recovery after corruption or
      operator-error in the original revoke).
    - :attr:`POLICY_AMENDMENT`: deliberate policy-amendment
      gesture (the original revoke is being walked back because
      the underlying policy is being amended).
    - :attr:`INVESTIGATION_CLEARED`: an investigation has cleared
      the original cause for revocation.
    - :attr:`OTHER`: present but uncategorisable by the installed
      classifier. The default fallback value for any present
      :attr:`UnrevokeAuditMarker.unrevoke_reason`.
    """

    UNSPECIFIED = "UNSPECIFIED"
    OPERATOR_RECOVERY = "OPERATOR_RECOVERY"
    POLICY_AMENDMENT = "POLICY_AMENDMENT"
    INVESTIGATION_CLEARED = "INVESTIGATION_CLEARED"
    OTHER = "OTHER"


class UnrevokeReasonClassifier(Protocol):
    """Pluggable classifier from raw ``unrevoke_reason`` text to
    :class:`UnrevokeReasonClass`.

    Implementations:

    - The hermetic test path supplies a deterministic classifier
      with pre-canned (substring -> class) mappings.
    - Production deployments supply a classifier that consults
      an operator-managed policy table.

    Contract:

    - The classifier MUST be a pure function of its input.
    - The classifier MUST return a member of
      :class:`UnrevokeReasonClass`. A return value of any other
      type surfaces as :class:`UnrevokeAuditMarkerShapeError`.
    - The classifier MUST handle the ``raw is None`` input
      (operator did not record a reason) and MUST return
      :attr:`UnrevokeReasonClass.UNSPECIFIED` in that case. The
      exporter validates this contract; a classifier that returns
      a different class for ``None`` input is a contract breach
      and surfaces as :class:`UnrevokeAuditMarkerShapeError`.
    """

    def classify(self, raw: Optional[str]) -> UnrevokeReasonClass:
        ...


def _default_classifier_classify(
    raw: Optional[str],
) -> UnrevokeReasonClass:
    """Default classifier implementation.

    Returns:
        :attr:`UnrevokeReasonClass.UNSPECIFIED` iff ``raw is None``,
        else :attr:`UnrevokeReasonClass.OTHER`. The default is
        fail-safe: an operator who has not installed a richer
        classifier never accidentally leaks operator prose via a
        categorical surface that happens to align with the
        text content.
    """
    if raw is None:
        return UnrevokeReasonClass.UNSPECIFIED
    return UnrevokeReasonClass.OTHER


@dataclass(frozen=True)
class _DefaultUnrevokeReasonClassifier:
    """Default :class:`UnrevokeReasonClassifier` implementation.

    Frozen dataclass holding no state. Use the module-level
    constant :data:`DEFAULT_CLASSIFIER` rather than constructing
    a fresh instance.
    """

    def classify(self, raw: Optional[str]) -> UnrevokeReasonClass:
        return _default_classifier_classify(raw)


#: Module-level default classifier instance. Used iff the
#: caller does not pass ``classifier=`` to the exporter.
DEFAULT_CLASSIFIER: UnrevokeReasonClassifier = (
    _DefaultUnrevokeReasonClassifier()
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UnrevokeAuditMarkerCrossOrgExportError(MultiOrgSubstrateError):
    """Base class for unrevoke-audit-marker cross-org export
    errors.

    Inherits :class:`MultiOrgSubstrateError` so downstream callers
    that already catch the substrate base catch every exporter
    surface without broadening their handler. New error types
    added in future tag-iterations MUST parent here.
    """


class UnrevokeAuditMarkerShapeError(
    UnrevokeAuditMarkerCrossOrgExportError
):
    """The input marker / attestation is structurally malformed.

    Examples: marker is None, attestation is None, attestation
    type wrong, marker type wrong, classifier returns
    non-:class:`UnrevokeReasonClass` value, classifier returns
    non-``UNSPECIFIED`` for ``None`` input.
    """


class RawNarrativeLeakError(
    UnrevokeAuditMarkerCrossOrgExportError
):
    """Defence-in-depth: a callsite attempted to construct an
    :class:`ExportedUnrevokeAuditMarker` carrying a raw narrative
    field.

    The exporter never emits raw operator prose; this error
    protects against a constructor-bypass call path (test code
    or a future programmer trying to short-circuit the exporter).
    Surfaces only from
    :meth:`ExportedUnrevokeAuditMarker.__post_init__`.

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
# Export envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportedUnrevokeAuditMarker:
    """The cross-org export envelope of an
    :class:`UnrevokeAuditMarker`.

    Frozen, equality-by-value, safe to anchor into WAT-Audit-
    Federation-Annex merkle leaves. The :attr:`marker_id` is a
    BLAKE2b-256 digest over a JCS-compatible canonicalised
    representation of the envelope — re-exporting a byte-equal
    source marker against the same route attestation yields a
    byte-equal :attr:`marker_id`.

    Attributes:
        export_schema: always :data:`EXPORT_SCHEMA`. Carried so
            downstream consumers do not need to know the constant.
        route_id: the
            :attr:`MultiOrgRouteAttestation.route_id` the export
            was scoped to. Route-scoping prevents cross-route
            equality-correlation on
            :attr:`previous_revocation_reason_hash`.
        marker_id: BLAKE2b-256 digest (32 bytes) of the
            canonicalised envelope payload. Stable across
            re-export of byte-equal source markers under the
            same route_id.
        previous_revoked_at: the source marker's
            :attr:`UnrevokeAuditMarker.previous_revoked_at`
            (timing-only, no identity — retained raw).
        unrevoke_reason_class: classification of the source
            marker's free-form ``unrevoke_reason`` by the
            installed :class:`UnrevokeReasonClassifier`.
        previous_revocation_reason_hash: BLAKE2b-256-hex digest
            of the source marker's
            ``previous_revocation_reason`` keyed by ``route_id``,
            or ``None`` iff the source marker carried
            ``previous_revocation_reason = None``. Equality-
            comparable across two exports for the same route_id,
            but not reversible to the raw text.
        exported_at: when the export was computed (timezone-aware
            UTC). Distinct from any source-marker timestamp.

    Invariants enforced by :meth:`__post_init__`:

    - ``export_schema == EXPORT_SCHEMA``.
    - ``route_id`` non-empty string.
    - ``marker_id`` is :class:`bytes` of length 32.
    - ``previous_revoked_at`` is tz-aware datetime.
    - ``unrevoke_reason_class`` is a :class:`UnrevokeReasonClass`.
    - ``previous_revocation_reason_hash`` is either ``None`` or a
      64-char hex string (BLAKE2b-256 hex form).
    - ``exported_at`` is tz-aware datetime.
    - No raw narrative fields present (defence-in-depth via
      :class:`RawNarrativeLeakError`).
    """

    export_schema: str
    route_id: str
    marker_id: bytes
    previous_revoked_at: datetime
    unrevoke_reason_class: UnrevokeReasonClass
    previous_revocation_reason_hash: Optional[str]
    exported_at: datetime

    # Defence-in-depth: a callsite that tries to attach a raw
    # narrative field via __dict__-bypass or a subclass with extra
    # slots is rejected. The dataclass's __slots__-equivalent
    # behaviour (frozen=True + no extra attributes set in
    # __post_init__) makes the surface narrow. We additionally
    # check that no attribute with a "raw" narrative name leaks
    # via an unexpected attribute. Frozen dataclasses prevent
    # attribute assignment outside __init__, so this check is
    # forward-looking for subclass usage.

    def __post_init__(self) -> None:
        if self.export_schema != EXPORT_SCHEMA:
            raise UnrevokeAuditMarkerShapeError(
                f"export_schema must equal {EXPORT_SCHEMA!r}; "
                f"got {self.export_schema!r}"
            )
        if (
            not isinstance(self.route_id, str)
            or self.route_id == ""
        ):
            raise UnrevokeAuditMarkerShapeError(
                f"route_id must be a non-empty string; got "
                f"{self.route_id!r}"
            )
        if (
            not isinstance(self.marker_id, bytes)
            or len(self.marker_id) != 32
        ):
            raise UnrevokeAuditMarkerShapeError(
                f"marker_id must be 32 bytes (BLAKE2b-256); got "
                f"type={type(self.marker_id).__name__}, len="
                f"{len(self.marker_id) if isinstance(self.marker_id, (bytes, bytearray)) else 'n/a'}"
            )
        if not isinstance(self.previous_revoked_at, datetime):
            raise UnrevokeAuditMarkerShapeError(
                f"previous_revoked_at must be a datetime; got "
                f"type={type(self.previous_revoked_at).__name__}"
            )
        if self.previous_revoked_at.tzinfo is None:
            raise UnrevokeAuditMarkerShapeError(
                "previous_revoked_at must be timezone-aware"
            )
        if not isinstance(
            self.unrevoke_reason_class, UnrevokeReasonClass
        ):
            raise UnrevokeAuditMarkerShapeError(
                f"unrevoke_reason_class must be an "
                f"UnrevokeReasonClass; got type="
                f"{type(self.unrevoke_reason_class).__name__}"
            )
        if self.previous_revocation_reason_hash is not None:
            if (
                not isinstance(
                    self.previous_revocation_reason_hash, str
                )
                or len(self.previous_revocation_reason_hash) != 64
            ):
                raise UnrevokeAuditMarkerShapeError(
                    f"previous_revocation_reason_hash must be a "
                    f"64-char hex string or None; got len="
                    f"{len(self.previous_revocation_reason_hash) if isinstance(self.previous_revocation_reason_hash, str) else 'n/a'}, "
                    f"type={type(self.previous_revocation_reason_hash).__name__}"
                )
            try:
                int(self.previous_revocation_reason_hash, 16)
            except ValueError as exc:
                raise UnrevokeAuditMarkerShapeError(
                    f"previous_revocation_reason_hash must be a "
                    f"hex string; got "
                    f"{self.previous_revocation_reason_hash!r}"
                ) from exc
        if not isinstance(self.exported_at, datetime):
            raise UnrevokeAuditMarkerShapeError(
                f"exported_at must be a datetime; got type="
                f"{type(self.exported_at).__name__}"
            )
        if self.exported_at.tzinfo is None:
            raise UnrevokeAuditMarkerShapeError(
                "exported_at must be timezone-aware"
            )
        # Raw-narrative leak gate: forbid attributes named
        # ``unrevoke_reason`` or ``previous_revocation_reason``
        # (the raw forms) from appearing on the envelope. Frozen
        # dataclasses prevent attribute injection, but a subclass
        # could declare them as additional fields; this gate
        # catches that.
        for forbidden in (
            "unrevoke_reason",
            "previous_revocation_reason",
        ):
            if forbidden in self.__dict__ or hasattr(
                type(self), forbidden
            ):
                offender = (
                    self.__dict__.get(forbidden)
                    if forbidden in self.__dict__
                    else getattr(type(self), forbidden)
                )
                raise RawNarrativeLeakError(
                    f"ExportedUnrevokeAuditMarker may not carry "
                    f"the raw narrative field {forbidden!r}; "
                    f"found on instance",
                    field_name=forbidden,
                    type_name=type(offender).__name__,
                )


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnrevokeAuditMarkerCrossOrgExporter:
    """Stateless exporter from
    :class:`UnrevokeAuditMarker` to
    :class:`ExportedUnrevokeAuditMarker`.

    The exporter is a frozen, equality-by-value dataclass holding
    only the pluggable classifier reference. Construction is
    cheap; one exporter instance can be reused across many
    export calls and shared across asyncio tasks.

    Pseudonymisation pattern (ADR-0031 D4) is hard-wired:

    1. Strip raw ``unrevoke_reason`` and
       ``previous_revocation_reason`` text.
    2. Classify ``unrevoke_reason`` via the installed
       :class:`UnrevokeReasonClassifier`.
    3. Hash ``previous_revocation_reason`` via BLAKE2b-256 keyed
       by ``route_id`` (if present).
    4. Retain raw timing fields, schema, route_id, marker_id.

    Failure modes are typed and structured.
    """

    classifier: UnrevokeReasonClassifier = field(
        default=DEFAULT_CLASSIFIER
    )
    clock: Optional[Any] = field(default=None)

    def _now(self) -> datetime:
        if self.clock is not None:
            value = self.clock()
            if not isinstance(value, datetime):
                raise TypeError(
                    "UnrevokeAuditMarkerCrossOrgExporter.clock "
                    "must return a datetime"
                )
            if value.tzinfo is None:
                raise ValueError(
                    "UnrevokeAuditMarkerCrossOrgExporter.clock "
                    "must return a timezone-aware UTC datetime"
                )
            return value
        return datetime.now(timezone.utc)

    def export(
        self,
        *,
        marker: UnrevokeAuditMarker,
        attestation: MultiOrgRouteAttestation,
    ) -> ExportedUnrevokeAuditMarker:
        """Export a single :class:`UnrevokeAuditMarker` for the
        given cross-org route.

        Parameters:
            marker: the source-org marker to export.
            attestation: the :class:`MultiOrgRouteAttestation`
                whose :attr:`MultiOrgRouteAttestation.route_id`
                scopes the export. Route-scoping prevents
                cross-route equality-correlation on the
                ``previous_revocation_reason_hash`` field.

        Returns:
            :class:`ExportedUnrevokeAuditMarker`.

        Raises:
            :class:`UnrevokeAuditMarkerShapeError` on any input
            type / content breach.
        """
        # Shape gate (marker).
        if not isinstance(marker, UnrevokeAuditMarker):
            raise UnrevokeAuditMarkerShapeError(
                f"marker must be an UnrevokeAuditMarker; got "
                f"type={type(marker).__name__}"
            )
        # Shape gate (attestation).
        if not isinstance(attestation, MultiOrgRouteAttestation):
            raise UnrevokeAuditMarkerShapeError(
                f"attestation must be a MultiOrgRouteAttestation; "
                f"got type={type(attestation).__name__}"
            )

        # Classify the operator-supplied reason. Pluggable; the
        # default classifier maps every present reason to OTHER
        # and absent to UNSPECIFIED. We invoke the classifier in
        # a try/except so a buggy classifier surfaces as a typed
        # shape-error rather than an opaque traceback.
        try:
            reason_class = self.classifier.classify(
                marker.unrevoke_reason
            )
        except Exception as exc:  # noqa: BLE001
            raise UnrevokeAuditMarkerShapeError(
                f"classifier raised on classify(raw="
                f"{marker.unrevoke_reason!r}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(reason_class, UnrevokeReasonClass):
            raise UnrevokeAuditMarkerShapeError(
                f"classifier returned non-UnrevokeReasonClass "
                f"value: type={type(reason_class).__name__}"
            )
        # Contract: None input -> UNSPECIFIED. Catch classifier-
        # contract breach so the export surface has a stable
        # invariant downstream consumers can rely on.
        if marker.unrevoke_reason is None and reason_class != (
            UnrevokeReasonClass.UNSPECIFIED
        ):
            raise UnrevokeAuditMarkerShapeError(
                f"classifier returned {reason_class!r} for "
                f"None unrevoke_reason; contract requires "
                f"UNSPECIFIED"
            )

        # Pseudonymise previous_revocation_reason (if present).
        reason_hash: Optional[str]
        if marker.previous_revocation_reason is None:
            reason_hash = None
        else:
            reason_hash = _route_scoped_reason_hash(
                route_id=attestation.route_id,
                raw=marker.previous_revocation_reason,
            )

        exported_at = self._now()

        # Compute marker_id over the canonical envelope payload.
        marker_id = _compute_marker_id(
            route_id=attestation.route_id,
            previous_revoked_at=marker.previous_revoked_at,
            reason_class=reason_class,
            reason_hash=reason_hash,
        )

        return ExportedUnrevokeAuditMarker(
            export_schema=EXPORT_SCHEMA,
            route_id=attestation.route_id,
            marker_id=marker_id,
            previous_revoked_at=marker.previous_revoked_at,
            unrevoke_reason_class=reason_class,
            previous_revocation_reason_hash=reason_hash,
            exported_at=exported_at,
        )


# ---------------------------------------------------------------------------
# Canonical hash helpers
# ---------------------------------------------------------------------------


def _route_scoped_reason_hash(*, route_id: str, raw: str) -> str:
    """BLAKE2b-256-hex digest of ``raw`` keyed by ``route_id``.

    The key derivation: BLAKE2b's :paramref:`key` parameter
    (cryptographic keyed hash) accepts up to 64 bytes. We pass
    the UTF-8-encoded ``route_id`` truncated/padded to 64 bytes
    so the key is unambiguously bound to the route_id. The
    personalisation (16 bytes) is a module-level constant
    distinguishing this hash use from
    :func:`_compute_marker_id`.

    The output is the lower-case hex form (64 chars). Hex form
    is JCS-canonical (string-typed, deterministic byte
    representation) so the marker_id payload can embed it
    directly.
    """
    key = route_id.encode("utf-8")
    # BLAKE2b key must be <= 64 bytes. Truncation is acceptable
    # because the personalisation provides an extra distinct
    # 16-byte domain separator; the only correctness requirement
    # is that two different route_ids produce two different keys.
    # Two route_ids whose first 64 UTF-8 bytes collide already
    # collide on the SHA-family identity surface used elsewhere
    # in the federation layer, so this is consistent.
    key = key[:64]
    h = hashlib.blake2b(
        digest_size=32,
        key=key,
        person=_REASON_HASH_PERSONALISATION,
    )
    h.update(raw.encode("utf-8"))
    return h.hexdigest()


def _compute_marker_id(
    *,
    route_id: str,
    previous_revoked_at: datetime,
    reason_class: UnrevokeReasonClass,
    reason_hash: Optional[str],
) -> bytes:
    """BLAKE2b-256 digest over a canonicalised export payload.

    The payload mixes:

    - :data:`EXPORT_SCHEMA` (domain-separator so a future schema
      bump produces a different digest).
    - ``route_id`` (an export anchored to a different route
      produces a different marker_id even if the marker content
      is byte-equal).
    - ``previous_revoked_at`` as ISO-8601 UTC.
    - ``unrevoke_reason_class`` as enum-value string.
    - ``previous_revocation_reason_hash`` as 64-char hex or null.

    Notably the payload does NOT include ``exported_at`` so
    re-exporting the same source marker at a different wall-clock
    produces a byte-equal :attr:`marker_id`. This makes the
    marker_id a stable audit-leaf identifier across re-exports.
    """
    payload = {
        "schema": EXPORT_SCHEMA,
        "route_id": route_id,
        "previous_revoked_at": previous_revoked_at.astimezone(
            timezone.utc
        ).isoformat(),
        "unrevoke_reason_class": reason_class.value,
        "previous_revocation_reason_hash": reason_hash,
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
    "UnrevokeReasonClass",
    "UnrevokeReasonClassifier",
    "UnrevokeAuditMarkerCrossOrgExportError",
    "UnrevokeAuditMarkerShapeError",
    "RawNarrativeLeakError",
    "ExportedUnrevokeAuditMarker",
    "UnrevokeAuditMarkerCrossOrgExporter",
]
