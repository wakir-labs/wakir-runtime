# SPDX-License-Identifier: BUSL-1.1
"""Multi-Marker-Policy-Composition engine (Sprint-8 Tag-3).

Sprint-8 Tag-2 (``cross_org_attenuation_verifier``) introduced
``BridgeRevocationMarker`` as an orthogonal Detector-1 surface
that composes on top of the N3 chain walker. In production,
however, a single Wirelang Layer-3 capability-token can pick up
*several* marker events over its lifecycle, and those events are
not orthogonal at the per-token axis:

- A token issued in Org-A is **revoked** by the bucket holder
  (``policy.revoked_at`` set; Sprint-6 Tag-1 revocation event).
- The same token is later **unrevoked** by deliberate operator
  gesture (Sprint-6 Tag-7 + Tag-9 ``UnrevokeAuditMarker``).
- Or the token is **re-issued** under a new key after a routine
  refresh (Sprint-8 Tag-3 ``ReIssuanceMarker``, defined here).
- Or a downstream verifier observes a **caveat-override**: the
  issuer-side caveat chain was narrowed *after* the token was
  minted (Sprint-8 Tag-3 ``CaveatOverrideMarker``, defined here).
- And independently the FTD-bridge the token's chain traverses
  may have been **revoked** at-or-before the token's mint time
  (Sprint-8 Tag-2 ``BridgeRevocationMarker``).

The four marker families are orthogonal in their *origin* (they
arise on independent surfaces: capability-policy bucket, audit-
trail, lifecycle refresh, bridge registry) but they MUST collapse
to **a single end-verdict** at the capability-token-lifecycle
axis when an external auditor asks: "is this token active right
now, and if not, why not?".

This module defines that composition. The design constraints
that drive it are:

1. **Ordering is observational**, not authoritative. The marker
   stack carries each marker's ``event_at`` wall-clock; the
   reduction sorts on that axis. We do NOT trust caller-side
   ordering: the same stack reduces to the same verdict
   regardless of insertion order. This is deliberate to keep
   the reduction stable across cross-org replication paths
   that may deliver events out-of-order.
2. **Reduction is pure**: no I/O, no clock, no mutation. The
   ``MarkerStack`` is frozen by construction; the reducer
   ``reduce_marker_stack`` returns a new ``CompositionVerdict``.
3. **Conflicting markers are explicit errors**, never silent. If
   the marker stack is internally inconsistent (e.g. an unrevoke
   whose ``previous_revoked_at`` does not match any revoke event,
   or a re-issuance event for a token that has not been revoked
   first), the reducer raises a typed
   :class:`MarkerCompositionConflictError`. We never invent a
   verdict in the face of conflicting evidence.
4. **The reduced verdict is a closed enumeration**: ``ACTIVE``,
   ``REVOKED``, ``RE_ISSUED``, ``BRIDGE_BLOCKED``,
   ``CAVEAT_OVERRIDDEN``. A token cannot be in two of these
   states simultaneously; if the stack would imply that, the
   reducer raises :class:`MarkerCompositionConflictError`.

Reduction rules (canonical)
---------------------------

Given a marker stack sorted by ``event_at`` ascending, the
reducer walks the events and applies these rules:

- ``RevokeEvent``: transitions ``ACTIVE -> REVOKED`` (and
  records the revocation reason / instant on the verdict). If
  the prior state was already ``REVOKED`` and no ``UnrevokeEvent``
  intervened, this is a duplicate-revoke; the reducer accepts
  the most recent ``revoked_at`` (later-wins) but emits an audit
  trace entry.
- ``UnrevokeEvent``: transitions ``REVOKED -> ACTIVE`` iff the
  ``UnrevokeEvent.previous_revoked_at`` matches the prior
  ``RevokeEvent.revoked_at`` byte-equally. Mismatch raises
  :class:`MarkerCompositionConflictError`.
- ``ReIssuanceEvent``: only valid if the prior state is
  ``REVOKED`` (a re-issuance of an active token is structurally
  ill-formed: the active token would still be valid). Transitions
  ``REVOKED -> RE_ISSUED``. A re-issued token cannot be unrevoked
  back to active: once a new token-id supersedes, the old token-id
  is terminal.
- ``CaveatOverrideEvent``: transitions any non-terminal state to
  ``CAVEAT_OVERRIDDEN`` *iff* the override's
  ``original_caveat_set`` matches the issuer-side caveat chain
  the token was minted under (causal-chain integrity). Mismatch
  raises :class:`MarkerCompositionConflictError`. ``CAVEAT_OVERRIDDEN``
  is terminal (no further events accepted on the same token).
- ``BridgeRevokedEvent``: a separate orthogonal axis from the
  revoke/unrevoke/re-issuance lifecycle. The reducer's verdict
  carries a separate ``bridge_blocked`` flag. If
  ``bridge_blocked`` is set AND the lifecycle state would
  otherwise be ``ACTIVE``, the *effective* verdict is
  ``BRIDGE_BLOCKED``; the lifecycle state is preserved on the
  verdict for forensics (callers can distinguish "the token is
  revoked AND the bridge is also blocked" from "the token is
  active but the bridge is blocked").

Audit-trace
-----------

Every reduction emits an ordered ``audit_trace`` of structured
records (one per marker consumed, in event-time order). This
gives downstream auditors a deterministic forensics surface:
they can replay the reduction without re-running it. The trace
is part of the ``CompositionVerdict`` and is byte-equal across
repeated reductions of the same stack.

Out-of-order arrivals
---------------------

The reducer sorts on ``event_at`` ascending before applying
rules. Two events with the same ``event_at`` instant are
sub-ordered by an explicit ``tie_break`` int (caller-supplied,
defaulting to ``0``). Same ``(event_at, tie_break)`` tuple from
two distinct events raises
:class:`MarkerCompositionConflictError` because the reduction
becomes non-deterministic.

Empty stack
-----------

An empty marker stack reduces to ``ACTIVE`` with an empty
audit-trace. This is the canonical "no lifecycle events yet"
verdict for a freshly-minted token.

Cross-review hooks
------------------

- **Zone 1 (Identity-Substrate):** ``BridgeRevokedEvent`` carries
  the ``(source_ftd_id, target_ftd_id)`` pair via its embedded
  :class:`BridgeRevocationMarker`; the marker is the same dataclass
  as in :mod:`wirelang.federation.cross_org_attenuation_verifier`,
  re-imported here to keep a single source of truth.
- **Zone 2 (WAT × Wirelang):** each marker event carries an
  optional ``wat_anchor_manifest_id`` for downstream WAT-leaf
  audit emission; the composition verdict surfaces the full
  anchor chain so a single WAT snapshot covers the lifecycle.
- **Zone 3 (OTS-Schema-Anker):** the four event-marker schemas
  are reserved for future schema-registry entries; the Phase-2
  anchor is out of scope for Tag-3.

References (URL-stamped 2026-05-13):

- ``BridgeRevocationMarker``: ``wirelang/federation/cross_org_attenuation_verifier.py``
  (Sprint-8 Tag-2).
- ``UnrevokeAuditMarker``: ``wirelang/schemas/capability_policy_nats_kv_backend.py``
  (Sprint-6 Tag-9).
- Spec §5.15: ``wirelang/specs/schema-registry-spec.md`` v0.30.0
  (this Tag-3 entry).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable, List, Optional, Tuple

from .cross_org_attenuation_verifier import BridgeRevocationMarker
from .n2_evaluator import FederationPredicateError


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class MarkerCompositionError(FederationPredicateError):
    """Base class for Multi-Marker-Composition failures.

    Inherits from :class:`FederationPredicateError` so callers that
    short-circuit on any federation-axis error uniformly handle
    composition failures.
    """


class MarkerCompositionArgumentError(MarkerCompositionError):
    """Raised when a marker-stack argument fails the syntactic
    shape contract (wrong type, missing field, non-timezone-aware
    datetime, etc.)."""


class MarkerCompositionConflictError(MarkerCompositionError):
    """Raised when the marker stack is internally inconsistent
    and no single end-verdict can be derived.

    Examples:
        - ``UnrevokeEvent.previous_revoked_at`` does not match the
          prior ``RevokeEvent.revoked_at``.
        - ``ReIssuanceEvent`` arrives on a token whose state is
          ``ACTIVE`` (no prior revocation).
        - ``CaveatOverrideEvent.original_caveat_set`` does not
          match the issuer-side caveat chain.
        - Two events with identical ``(event_at, tie_break)``
          (deterministic ordering broken).
    """


# ---------------------------------------------------------------------------
# Verdict state enumeration
# ---------------------------------------------------------------------------


class CompositionState(str, Enum):
    """Closed enumeration of lifecycle-axis verdict states.

    The four mutually-exclusive states are:

    - ``ACTIVE``: the token is currently valid on the
      capability-token-lifecycle axis. Subject to additional
      bridge-blocking forensics (see ``CompositionVerdict.effective``).
    - ``REVOKED``: the token is currently revoked. May still be
      transitioned to ``ACTIVE`` by a later ``UnrevokeEvent`` or
      to ``RE_ISSUED`` by a later ``ReIssuanceEvent``.
    - ``RE_ISSUED``: the token has been superseded by a new
      token-id. Terminal on the lifecycle axis.
    - ``CAVEAT_OVERRIDDEN``: the issuer-side caveat chain has
      been narrowed after mint. Terminal on the lifecycle axis.
    """

    ACTIVE = "active"
    REVOKED = "revoked"
    RE_ISSUED = "re_issued"
    CAVEAT_OVERRIDDEN = "caveat_overridden"


class EffectiveVerdict(str, Enum):
    """Closed enumeration of effective end-verdicts.

    The effective verdict folds the orthogonal bridge-blocking
    axis into the lifecycle state:

    - ``ACTIVE``: lifecycle ``ACTIVE`` AND no bridge-block.
    - ``REVOKED``: lifecycle ``REVOKED`` (bridge-block does not
      surface separately; the token is revoked regardless).
    - ``RE_ISSUED``: lifecycle ``RE_ISSUED``.
    - ``CAVEAT_OVERRIDDEN``: lifecycle ``CAVEAT_OVERRIDDEN``.
    - ``BRIDGE_BLOCKED``: lifecycle would otherwise be ``ACTIVE``
      but the bridge is blocked; the token is not currently
      verifiable through this chain.
    """

    ACTIVE = "active"
    REVOKED = "revoked"
    RE_ISSUED = "re_issued"
    CAVEAT_OVERRIDDEN = "caveat_overridden"
    BRIDGE_BLOCKED = "bridge_blocked"


# ---------------------------------------------------------------------------
# Event marker dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevokeEvent:
    """A capability-policy revocation event.

    Attributes:
        event_at: wall-clock at which the revocation took effect
            on the bucket (the ``policy.revoked_at`` instant).
            MUST be timezone-aware.
        revocation_reason: optional operator-supplied free-form
            audit string. ``None`` if the revocation carried no
            reason.
        tie_break: integer used to deterministically order
            events whose ``event_at`` is identical. Defaults to
            ``0``. Two events with the same ``(event_at, tie_break)``
            tuple in the same stack raise
            :class:`MarkerCompositionConflictError`.
        wat_anchor_manifest_id: optional WAT-leaf anchor
            manifest id for downstream audit emission. ``None``
            if no anchor was emitted for this event.
    """

    event_at: datetime
    revocation_reason: Optional[str] = None
    tie_break: int = 0
    wat_anchor_manifest_id: Optional[str] = None

    def __post_init__(self) -> None:
        _check_aware_datetime(self.event_at, "RevokeEvent.event_at")
        if self.revocation_reason is not None and not isinstance(
            self.revocation_reason, str
        ):
            raise MarkerCompositionArgumentError(
                f"RevokeEvent.revocation_reason must be a string or None: "
                f"type={type(self.revocation_reason).__name__}"
            )
        if not isinstance(self.tie_break, int):
            raise MarkerCompositionArgumentError(
                f"RevokeEvent.tie_break must be int: type="
                f"{type(self.tie_break).__name__}"
            )


@dataclass(frozen=True)
class UnrevokeEvent:
    """An operator-deliberate unrevoke audit event.

    Mirrors :class:`wirelang.schemas.capability_policy_nats_kv_backend.UnrevokeAuditMarker`
    on the composition axis. The semantic contract is preserved:
    ``previous_revoked_at`` MUST byte-equal the prior
    ``RevokeEvent.event_at`` for the unrevoke to be accepted.

    Attributes:
        event_at: wall-clock at which the unrevoke gesture was
            applied. MUST be strictly after the prior revoke's
            ``event_at`` (validated by the reducer).
        previous_revoked_at: the prior ``RevokeEvent.event_at``
            instant; cross-checked against the reducer's prior
            state. Mismatch raises
            :class:`MarkerCompositionConflictError`.
        unrevoke_reason: optional operator-supplied free-form
            audit string mirroring the prior receipt.
        tie_break: deterministic-ordering tie-breaker (see
            :class:`RevokeEvent`).
        wat_anchor_manifest_id: optional WAT-leaf anchor.
    """

    event_at: datetime
    previous_revoked_at: datetime
    unrevoke_reason: Optional[str] = None
    tie_break: int = 0
    wat_anchor_manifest_id: Optional[str] = None

    def __post_init__(self) -> None:
        _check_aware_datetime(self.event_at, "UnrevokeEvent.event_at")
        _check_aware_datetime(
            self.previous_revoked_at, "UnrevokeEvent.previous_revoked_at"
        )
        if self.unrevoke_reason is not None and not isinstance(
            self.unrevoke_reason, str
        ):
            raise MarkerCompositionArgumentError(
                f"UnrevokeEvent.unrevoke_reason must be a string or None: "
                f"type={type(self.unrevoke_reason).__name__}"
            )
        if not isinstance(self.tie_break, int):
            raise MarkerCompositionArgumentError(
                f"UnrevokeEvent.tie_break must be int: type="
                f"{type(self.tie_break).__name__}"
            )


@dataclass(frozen=True)
class ReIssuanceEvent:
    """A token-refresh re-issuance event.

    A re-issuance supersedes the old token-id with a new one;
    the old token-id is terminally retired (no further lifecycle
    events accepted on it). Re-issuance is only valid on a
    prior-revoked token; a re-issuance of an active token is
    structurally ill-formed and raises
    :class:`MarkerCompositionConflictError`.

    Attributes:
        event_at: wall-clock at which the re-issuance was minted.
        new_token_id: the new token-id that supersedes the old.
            MUST be a non-empty string.
        re_issuance_reason: optional operator-supplied audit
            string explaining the refresh (e.g. ``"key-rotation"``
            or ``"caveat-narrowing"``).
        tie_break: deterministic-ordering tie-breaker.
        wat_anchor_manifest_id: optional WAT-leaf anchor.
    """

    event_at: datetime
    new_token_id: str
    re_issuance_reason: Optional[str] = None
    tie_break: int = 0
    wat_anchor_manifest_id: Optional[str] = None

    def __post_init__(self) -> None:
        _check_aware_datetime(self.event_at, "ReIssuanceEvent.event_at")
        if not isinstance(self.new_token_id, str) or not self.new_token_id:
            raise MarkerCompositionArgumentError(
                "ReIssuanceEvent.new_token_id must be a non-empty string"
            )
        if self.re_issuance_reason is not None and not isinstance(
            self.re_issuance_reason, str
        ):
            raise MarkerCompositionArgumentError(
                f"ReIssuanceEvent.re_issuance_reason must be a string or None: "
                f"type={type(self.re_issuance_reason).__name__}"
            )
        if not isinstance(self.tie_break, int):
            raise MarkerCompositionArgumentError(
                f"ReIssuanceEvent.tie_break must be int: type="
                f"{type(self.tie_break).__name__}"
            )


@dataclass(frozen=True)
class CaveatOverrideEvent:
    """A verifier-observed issuer-side caveat-narrowing event.

    The override carries the issuer-side caveat-chain the token
    was minted under (``original_caveat_set``) and the narrowed
    set the issuer subsequently published (``narrowed_caveat_set``).
    The reducer enforces the causal-chain integrity invariant:
    ``original_caveat_set`` MUST byte-equal the issuer-side
    caveat chain known to the prior reducer state (which the
    caller supplies via ``MarkerStack.original_caveat_set``).

    Attributes:
        event_at: wall-clock at which the override was observed.
        original_caveat_set: the issuer-side caveat-chain the
            token was minted under, as a tuple of
            ``(predicate, args)`` pairs. ``args`` is itself a
            tuple of hashable values.
        narrowed_caveat_set: the issuer-side caveat-chain after
            the override.
        override_reason: optional operator-supplied audit string.
        tie_break: deterministic-ordering tie-breaker.
        wat_anchor_manifest_id: optional WAT-leaf anchor.
    """

    event_at: datetime
    original_caveat_set: Tuple[Tuple[str, Tuple[object, ...]], ...]
    narrowed_caveat_set: Tuple[Tuple[str, Tuple[object, ...]], ...]
    override_reason: Optional[str] = None
    tie_break: int = 0
    wat_anchor_manifest_id: Optional[str] = None

    def __post_init__(self) -> None:
        _check_aware_datetime(self.event_at, "CaveatOverrideEvent.event_at")
        _check_caveat_set(
            self.original_caveat_set, "CaveatOverrideEvent.original_caveat_set"
        )
        _check_caveat_set(
            self.narrowed_caveat_set, "CaveatOverrideEvent.narrowed_caveat_set"
        )
        if self.override_reason is not None and not isinstance(
            self.override_reason, str
        ):
            raise MarkerCompositionArgumentError(
                f"CaveatOverrideEvent.override_reason must be a string or None: "
                f"type={type(self.override_reason).__name__}"
            )
        if not isinstance(self.tie_break, int):
            raise MarkerCompositionArgumentError(
                f"CaveatOverrideEvent.tie_break must be int: type="
                f"{type(self.tie_break).__name__}"
            )


@dataclass(frozen=True)
class BridgeRevokedEvent:
    """A trust-domain-bridge revocation event on the composition axis.

    Wraps a Sprint-8 Tag-2 :class:`BridgeRevocationMarker` and
    attaches the composition-axis bookkeeping
    (``tie_break``, ``wat_anchor_manifest_id``). The
    ``minted_at`` cross-check against the marker's
    ``revoked_at`` is performed by the reducer using
    ``MarkerStack.minted_at`` (caller-supplied; the bridge-block
    only fires if ``marker.bridge_was_revoked_for_mint(minted_at)``
    is true).

    Attributes:
        marker: the :class:`BridgeRevocationMarker` from
            :mod:`wirelang.federation.cross_org_attenuation_verifier`.
        tie_break: deterministic-ordering tie-breaker.
        wat_anchor_manifest_id: optional WAT-leaf anchor.
    """

    marker: BridgeRevocationMarker
    tie_break: int = 0
    wat_anchor_manifest_id: Optional[str] = None

    @property
    def event_at(self) -> datetime:
        """The bridge's ``revoked_at`` instant, surfaced for the
        reducer's event-time sort.

        Same axis as the other event markers: the reducer sorts
        on ``event_at`` ascending. For bridge events the
        canonical event-time is the bridge's revocation instant.
        """
        return self.marker.revoked_at

    def __post_init__(self) -> None:
        if not isinstance(self.marker, BridgeRevocationMarker):
            raise MarkerCompositionArgumentError(
                f"BridgeRevokedEvent.marker must be BridgeRevocationMarker: "
                f"type={type(self.marker).__name__}"
            )
        if not isinstance(self.tie_break, int):
            raise MarkerCompositionArgumentError(
                f"BridgeRevokedEvent.tie_break must be int: type="
                f"{type(self.tie_break).__name__}"
            )


# ---------------------------------------------------------------------------
# Marker stack and verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditTraceEntry:
    """One ordered audit-trace record emitted by the reducer.

    Attributes:
        event_at: the event's wall-clock.
        tie_break: the event's deterministic-ordering
            tie-breaker.
        event_kind: a short string label
            (``"revoke"``, ``"unrevoke"``, ``"re_issuance"``,
            ``"caveat_override"``, ``"bridge_revoked"``).
        outcome: a short string label describing the reducer's
            response (e.g. ``"transition:active->revoked"``,
            ``"transition:revoked->active"``,
            ``"bridge_block_armed"``).
        wat_anchor_manifest_id: surfaced unchanged from the
            event for downstream audit emission.
    """

    event_at: datetime
    tie_break: int
    event_kind: str
    outcome: str
    wat_anchor_manifest_id: Optional[str]


@dataclass(frozen=True)
class CompositionVerdict:
    """Aggregate verdict for a successful marker-stack reduction.

    Attributes:
        state: the lifecycle-axis state
            (:class:`CompositionState`).
        effective: the effective end-verdict
            (:class:`EffectiveVerdict`) folding in the
            bridge-blocking orthogonal axis.
        bridge_blocked: ``True`` iff a
            :class:`BridgeRevokedEvent` fired for the token's
            ``minted_at`` anchor.
        revocation_reason: the last-applied revocation reason
            if the lifecycle is currently ``REVOKED``; otherwise
            ``None``.
        revoked_at: the lifecycle-axis revocation instant if
            currently ``REVOKED``; otherwise ``None``.
        new_token_id: the superseding token-id if currently
            ``RE_ISSUED``; otherwise ``None``.
        narrowed_caveat_set: the narrowed caveat-chain if
            currently ``CAVEAT_OVERRIDDEN``; otherwise ``None``.
        audit_trace: ordered tuple of audit-trace entries, one
            per marker consumed, in event-time order.
        wat_anchor_chain: ordered tuple of WAT-leaf anchor
            manifest ids in event-time order. ``None`` entries
            for events without an anchor.
    """

    state: CompositionState
    effective: EffectiveVerdict
    bridge_blocked: bool
    revocation_reason: Optional[str]
    revoked_at: Optional[datetime]
    new_token_id: Optional[str]
    narrowed_caveat_set: Optional[
        Tuple[Tuple[str, Tuple[object, ...]], ...]
    ]
    audit_trace: Tuple[AuditTraceEntry, ...]
    wat_anchor_chain: Tuple[Optional[str], ...]


@dataclass(frozen=True)
class MarkerStack:
    """Ordered marker stack for one capability-token lifecycle.

    The stack carries all observed events for one token-id. The
    reducer sorts on ``event_at`` ascending before applying
    rules.

    Attributes:
        token_id: the capability-token-id this stack belongs to.
            Surfaced on the verdict for cross-stack debugging
            but not used in the reduction itself.
        minted_at: the token's mint-time wall-clock. Required
            for bridge-revocation cross-checks. MUST be
            timezone-aware.
        original_caveat_set: the issuer-side caveat-chain the
            token was minted under. Required for caveat-override
            causal-chain integrity. ``None`` is allowed for
            tokens whose caveat axis is not yet tracked; in that
            case any :class:`CaveatOverrideEvent` raises
            :class:`MarkerCompositionConflictError` (no causal
            chain to verify against).
        events: tuple of marker events. May be empty (yields
            ``ACTIVE`` verdict with empty trace).
    """

    token_id: str
    minted_at: datetime
    original_caveat_set: Optional[Tuple[Tuple[str, Tuple[object, ...]], ...]]
    events: Tuple[
        "RevokeEvent | UnrevokeEvent | ReIssuanceEvent | "
        "CaveatOverrideEvent | BridgeRevokedEvent",
        ...,
    ] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.token_id, str) or not self.token_id:
            raise MarkerCompositionArgumentError(
                "MarkerStack.token_id must be a non-empty string"
            )
        _check_aware_datetime(self.minted_at, "MarkerStack.minted_at")
        if self.original_caveat_set is not None:
            _check_caveat_set(
                self.original_caveat_set, "MarkerStack.original_caveat_set"
            )
        for i, event in enumerate(self.events):
            if not isinstance(
                event,
                (
                    RevokeEvent,
                    UnrevokeEvent,
                    ReIssuanceEvent,
                    CaveatOverrideEvent,
                    BridgeRevokedEvent,
                ),
            ):
                raise MarkerCompositionArgumentError(
                    f"MarkerStack.events[{i}] must be a marker event: "
                    f"type={type(event).__name__}"
                )


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------


def reduce_marker_stack(stack: MarkerStack) -> CompositionVerdict:
    """Reduce a :class:`MarkerStack` to a single :class:`CompositionVerdict`.

    The reduction is pure (no I/O, no clock, no mutation) and
    deterministic (same stack -> same verdict, byte-equal across
    repeated calls).

    Algorithm:

    1. Sort events on ``(event_at, tie_break)`` ascending. Detect
       duplicate ordering keys and raise
       :class:`MarkerCompositionConflictError`.
    2. Walk events; apply per-event rules to update the
       lifecycle-state machine and the bridge-block flag.
    3. Fold the lifecycle state + bridge-block flag into the
       effective verdict.
    4. Emit the audit-trace and anchor-chain in event-time order.

    Raises:
        MarkerCompositionConflictError: when the stack is
            internally inconsistent (see class docstring for
            examples).
    """
    if not isinstance(stack, MarkerStack):
        raise MarkerCompositionArgumentError(
            f"stack must be MarkerStack: type={type(stack).__name__}"
        )

    sorted_events = _sort_and_validate_ordering(stack.events)

    state = CompositionState.ACTIVE
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None
    new_token_id: Optional[str] = None
    narrowed_caveat_set: Optional[
        Tuple[Tuple[str, Tuple[object, ...]], ...]
    ] = None
    bridge_blocked = False

    audit_trace: List[AuditTraceEntry] = []
    wat_anchor_chain: List[Optional[str]] = []

    for event in sorted_events:
        if isinstance(event, RevokeEvent):
            outcome = _apply_revoke(state, event)
            if state == CompositionState.ACTIVE:
                state = CompositionState.REVOKED
                revoked_at = event.event_at
                revocation_reason = event.revocation_reason
            elif state == CompositionState.REVOKED:
                # Duplicate revoke; later-wins on the revoked_at
                # instant. Audit-trace captures the duplicate.
                revoked_at = event.event_at
                revocation_reason = event.revocation_reason
            else:
                raise MarkerCompositionConflictError(
                    f"RevokeEvent at {event.event_at.isoformat()} arrived "
                    f"on terminal state {state.value!r}; the token is "
                    f"no longer revocable"
                )

        elif isinstance(event, UnrevokeEvent):
            if state != CompositionState.REVOKED:
                raise MarkerCompositionConflictError(
                    f"UnrevokeEvent at {event.event_at.isoformat()} arrived "
                    f"on state {state.value!r}; an unrevoke requires a "
                    f"prior revoke (state==REVOKED)"
                )
            if revoked_at is None or event.previous_revoked_at != revoked_at:
                raise MarkerCompositionConflictError(
                    f"UnrevokeEvent.previous_revoked_at "
                    f"{event.previous_revoked_at.isoformat()} does not match "
                    f"the prior RevokeEvent.event_at "
                    f"{revoked_at.isoformat() if revoked_at else 'None'}; "
                    f"unrevoke causal-chain is broken"
                )
            if event.event_at <= revoked_at:
                raise MarkerCompositionConflictError(
                    f"UnrevokeEvent.event_at {event.event_at.isoformat()} "
                    f"is not strictly after prior revoke "
                    f"{revoked_at.isoformat()}; unrevoke MUST follow revoke "
                    f"in event-time"
                )
            outcome = "transition:revoked->active"
            state = CompositionState.ACTIVE
            revoked_at = None
            revocation_reason = None

        elif isinstance(event, ReIssuanceEvent):
            if state != CompositionState.REVOKED:
                raise MarkerCompositionConflictError(
                    f"ReIssuanceEvent at {event.event_at.isoformat()} arrived "
                    f"on state {state.value!r}; a re-issuance requires a "
                    f"prior revoke (state==REVOKED); re-issuing an active "
                    f"token is structurally ill-formed"
                )
            outcome = (
                f"transition:revoked->re_issued(new_token_id="
                f"{event.new_token_id!r})"
            )
            state = CompositionState.RE_ISSUED
            new_token_id = event.new_token_id
            revoked_at = None
            revocation_reason = None

        elif isinstance(event, CaveatOverrideEvent):
            if state in (
                CompositionState.RE_ISSUED,
                CompositionState.CAVEAT_OVERRIDDEN,
            ):
                raise MarkerCompositionConflictError(
                    f"CaveatOverrideEvent at {event.event_at.isoformat()} "
                    f"arrived on terminal state {state.value!r}; the token "
                    f"is no longer subject to caveat-axis overrides"
                )
            if stack.original_caveat_set is None:
                raise MarkerCompositionConflictError(
                    f"CaveatOverrideEvent at {event.event_at.isoformat()} "
                    f"requires MarkerStack.original_caveat_set to verify "
                    f"causal-chain integrity; got None"
                )
            if event.original_caveat_set != stack.original_caveat_set:
                raise MarkerCompositionConflictError(
                    f"CaveatOverrideEvent.original_caveat_set does not match "
                    f"MarkerStack.original_caveat_set; caveat causal-chain "
                    f"is broken at {event.event_at.isoformat()}"
                )
            outcome = (
                f"transition:{state.value}->caveat_overridden"
            )
            state = CompositionState.CAVEAT_OVERRIDDEN
            narrowed_caveat_set = event.narrowed_caveat_set
            revoked_at = None
            revocation_reason = None

        elif isinstance(event, BridgeRevokedEvent):
            if event.marker.bridge_was_revoked_for_mint(stack.minted_at):
                outcome = "bridge_block_armed"
                bridge_blocked = True
            else:
                outcome = "bridge_block_skipped:revoked_after_mint"
            # Bridge events do NOT alter the lifecycle state.

        else:  # pragma: no cover — exhaustively guarded by MarkerStack.__post_init__
            raise MarkerCompositionArgumentError(
                f"unknown marker-event type: {type(event).__name__}"
            )

        audit_trace.append(
            AuditTraceEntry(
                event_at=event.event_at,
                tie_break=event.tie_break,
                event_kind=_event_kind(event),
                outcome=outcome,
                wat_anchor_manifest_id=event.wat_anchor_manifest_id,
            )
        )
        wat_anchor_chain.append(event.wat_anchor_manifest_id)

    effective = _fold_effective(state, bridge_blocked)

    return CompositionVerdict(
        state=state,
        effective=effective,
        bridge_blocked=bridge_blocked,
        revocation_reason=revocation_reason,
        revoked_at=revoked_at,
        new_token_id=new_token_id,
        narrowed_caveat_set=narrowed_caveat_set,
        audit_trace=tuple(audit_trace),
        wat_anchor_chain=tuple(wat_anchor_chain),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _sort_and_validate_ordering(events):
    """Sort events on ``(event_at, tie_break)``; detect dup keys."""
    keyed = [((e.event_at, e.tie_break), e) for e in events]
    keyed.sort(key=lambda pair: pair[0])
    seen = set()
    for key, _e in keyed:
        if key in seen:
            raise MarkerCompositionConflictError(
                f"duplicate ordering key (event_at={key[0].isoformat()}, "
                f"tie_break={key[1]}) in marker stack; deterministic "
                f"reduction is not possible"
            )
        seen.add(key)
    return [e for _k, e in keyed]


def _apply_revoke(state: CompositionState, event: RevokeEvent) -> str:
    if state == CompositionState.ACTIVE:
        return "transition:active->revoked"
    if state == CompositionState.REVOKED:
        return "duplicate_revoke:later_wins"
    # Other states caught by caller and raised explicitly.
    return f"transition:{state.value}->revoked"


def _event_kind(event) -> str:
    if isinstance(event, RevokeEvent):
        return "revoke"
    if isinstance(event, UnrevokeEvent):
        return "unrevoke"
    if isinstance(event, ReIssuanceEvent):
        return "re_issuance"
    if isinstance(event, CaveatOverrideEvent):
        return "caveat_override"
    if isinstance(event, BridgeRevokedEvent):
        return "bridge_revoked"
    return "unknown"  # pragma: no cover


def _fold_effective(
    state: CompositionState, bridge_blocked: bool
) -> EffectiveVerdict:
    if state == CompositionState.RE_ISSUED:
        return EffectiveVerdict.RE_ISSUED
    if state == CompositionState.CAVEAT_OVERRIDDEN:
        return EffectiveVerdict.CAVEAT_OVERRIDDEN
    if state == CompositionState.REVOKED:
        return EffectiveVerdict.REVOKED
    # state == ACTIVE
    if bridge_blocked:
        return EffectiveVerdict.BRIDGE_BLOCKED
    return EffectiveVerdict.ACTIVE


def _check_aware_datetime(value, label: str) -> None:
    if not isinstance(value, datetime):
        raise MarkerCompositionArgumentError(
            f"{label} must be a datetime: type={type(value).__name__}"
        )
    if value.tzinfo is None:
        raise MarkerCompositionArgumentError(
            f"{label} must be timezone-aware"
        )


def _check_caveat_set(value, label: str) -> None:
    if not isinstance(value, tuple):
        raise MarkerCompositionArgumentError(
            f"{label} must be a tuple of (predicate, args) pairs: "
            f"type={type(value).__name__}"
        )
    for i, item in enumerate(value):
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], tuple)
        ):
            raise MarkerCompositionArgumentError(
                f"{label}[{i}] must be a (predicate:str, args:tuple) pair: "
                f"got {item!r}"
            )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


__all__ = [
    "MarkerCompositionError",
    "MarkerCompositionArgumentError",
    "MarkerCompositionConflictError",
    "CompositionState",
    "EffectiveVerdict",
    "RevokeEvent",
    "UnrevokeEvent",
    "ReIssuanceEvent",
    "CaveatOverrideEvent",
    "BridgeRevokedEvent",
    "AuditTraceEntry",
    "CompositionVerdict",
    "MarkerStack",
    "reduce_marker_stack",
]
