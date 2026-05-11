# SPDX-License-Identifier: Apache-2.0
"""Cross-bucket capability-policy replication for the Wirelang
capability-policy backend.

Phase-2 Sprint-6 Tag-6 (S6-6) lands the cross-bucket replication
layer for ``wakir-capability-policies``. The replication layer
mirrors the contents of one capability-policy bucket onto another
in the same shape as the Phase-1b Sprint-3 Tag-6 schema-registry
replication layer
(:mod:`wirelang.schemas.replication`), but with one cross-cutting
addition: replication MUST preserve the **revocation-monotonic
invariant** established in Phase-2 Sprint-6 Tag-1.

Use-cases (mirror of Sprint-3 Tag-6 schema-registry replicator):

- **multi-org federation:** two organisations run independent NATS
  clusters and want a one-way mirror of a curated set of capability
  policies (e.g. an upstream issuer publishes Wakir-canonical
  capability policies, replicated into a downstream org's local
  cluster for offline lookup).
- **cross-cluster mirror:** a single org runs two NATS clusters
  (e.g. an active and a hot-standby), and wants the standby to
  track the active cluster's capability-policies bucket for
  fail-over readiness.

Composition contract
--------------------

The replicator is a *thin composition* of three Phase-2 Sprint-5
and Sprint-6 surfaces that already shipped:

- **Source side (Sprint-5 Tag-5 watch-stream):** the replicator
  opens an :func:`open_capability_policy_watch_stream` over the
  source backend and consumes decoded
  :class:`CapabilityPolicyWatchEvent` instances one at a time.
  Bootstrap is taken from :meth:`NatsKvCapabilityPolicyBackend.snapshot`
  so the target starts from a complete, self-consistent view; the
  watch-stream then fills in the live tail.
- **Target side (Sprint-5 Tag-4 CAS-pin + Sprint-5 Tag-2 LWW +
  Sprint-6 Tag-1 revocation-monotonic invariant):** the replicator
  writes each event to the target backend through one of two paths,
  selectable via :class:`CapabilityPolicyReplicationConflictPolicy`:

  - ``SOURCE_WINS`` (default): writes go through
    :meth:`NatsKvCapabilityPolicyBackend.put` (LWW). The
    source-of-truth is the source bucket; whatever the source emits
    lands on the target unconditionally. **Note:** under SOURCE_WINS
    the target's revocation-monotonic invariant is NOT enforced at
    the backend (consistent with the Sprint-5 Tag-4 rationale that
    LWW writes are operator-deliberate). The replicator therefore
    surfaces an in-band check that refuses to overwrite a live
    revoked policy with an unrevoked envelope under SOURCE_WINS,
    via the :attr:`CapabilityPolicyReplicationMetrics.revocation_breaches`
    counter; this guards against a misconfigured source flowing a
    stale un-revoked envelope onto a revoked target.
  - ``CAS_PIN``: writes go through
    :meth:`NatsKvCapabilityPolicyBackend.put_with_revision` against
    the target's currently-observed revision. The Sprint-6 Tag-1
    revocation-monotonic gate then runs server-side; if the source
    emits an un-revoke or advance-instant envelope against a revoked
    target, the target raises
    :class:`CapabilityPolicyRevocationConflict` and the replicator
    surfaces it via :attr:`revocation_breaches`. CAS conflicts
    proper surface via :attr:`cas_conflicts`.

- **Operator-input side (Sprint-6 Tag-2 publisher-CLI revoke):**
  when an operator needs to deliberately revoke a policy on the
  source, they invoke the Tag-2 ``revoke`` subcommand against the
  source bucket; the resulting revocation envelope propagates to
  the target via the replicator's regular event-loop path. The
  replicator does NOT itself bake an operator-override into its
  event-loop; that is a separate operator concern.

The composition surfaces three substrate capabilities into a
single layer:

1. Bootstrap: full source snapshot → target backend (one
   :meth:`NatsKvCapabilityPolicyBackend.put` per source record, in
   keys-sorted order, idempotent against re-runs).
2. Tail: source watch-stream → target backend (one
   :meth:`NatsKvCapabilityPolicyBackend.put` or
   :meth:`NatsKvCapabilityPolicyBackend.put_with_revision` per
   source event).
3. Filter: an optional
   :class:`CapabilityPolicyReplicationFilter` lets operators
   restrict replication to a curated subset (by ``registered_by``,
   by ``(registered_by, policy_id)`` pair, or by revocation
   status). The filter runs on the source-side event shape, so a
   filtered-out event is observed by the replicator but not
   applied to the target.

Revocation-Monotonicity Contract (Tag-6)
----------------------------------------

The Sprint-6 Tag-1 backend-write invariant guarantees that on the
**CAS-pin path** the target never accepts an un-revoke
(``revoked_at: None`` against a revoked target) nor an
advance-instant write (``revoked_at`` strictly greater than the
live one). The replicator extends this invariant **cross-bucket**:

- **CAS_PIN policy:** the target enforces the invariant itself.
  A breach surfaces as :class:`CapabilityPolicyRevocationConflict`
  raised by ``put_with_revision``; the replicator catches it,
  advances :attr:`revocation_breaches`, and (by default) continues
  with the next event. The breach is also reflected in
  :attr:`cas_conflicts` because the CAS-pin write returned a
  refusal; the two counters are independent because a CAS conflict
  proper (concurrent revision drift) is a *different* failure mode
  from a revocation-breach (semantic monotonicity refusal). The
  ``halt_on_revocation_breach`` flag (default False) re-raises if
  the operator wants the replicator to stop on the first breach.
- **SOURCE_WINS policy:** the target's LWW path does NOT enforce
  the invariant. The replicator runs an in-band check BEFORE the
  ``put`` call: if the live target record carries a revocation
  AND the incoming source record either drops the revocation or
  advances the instant, the replicator refuses the write, advances
  :attr:`revocation_breaches`, and (by default) continues. This
  preserves the Sprint-6 Tag-1 monotonicity guarantee across
  buckets even under LWW propagation; an operator who deliberately
  wants to overwrite the revocation must use the Sprint-6 Tag-2
  publisher-CLI directly against the target.

The cross-bucket invariant is therefore: **once a key carries a
revocation on the target, no replication path will silently
overwrite it.** The breach is always observable through the
metrics counter, and operator intervention is always required to
proceed.

Phase-2 Sprint-6 boundary
-------------------------

The replicator does NOT implement:

- **Bidirectional replication.** Tag-6 is one-way (source →
  target). Bidirectional replication requires conflict-free
  CRDT-style merges that are out of scope for Sprint-6 (Phase-3
  reservation: bidir-replication slot).
- **Multi-source fan-in.** Tag-6 has exactly one source backend
  and one target backend per
  :class:`CapabilityPolicyReplicator` instance; operators that
  want fan-in run multiple replicators against one target.
- **Watch-stream resume policy.** The replicator restarts from
  a full snapshot on every connection drop; resume-from-revision
  is a Phase-3 hardening item (mirror of the schema-registry
  reservation).
- **Capability-token enforcement on the target write.** The
  replicator inherits whatever NATS credentials the operator's
  environment provides on each backend.
- **Token-level revocation propagation.** The replicator carries
  **policy-level** revocation envelopes (the Sprint-6 Tag-1
  authority gesture on the policy bundle). Biscuit v3 token-level
  revocation-list propagation is a Phase-3 Datalog-substrate slot.

Determinism contract
--------------------

The replicator preserves the determinism contract of the underlying
backends:

- A bootstrap-only run (no live tail) leaves the target's keysets
  byte-equal to the source's keysets after the run (modulo entries
  filtered out by a
  :class:`CapabilityPolicyReplicationFilter`). Re-running the
  bootstrap on the same source state is a no-op for records
  already byte-equal on the target (idempotency via envelope-byte
  comparison; LWW on byte-mismatch UNLESS the byte-mismatch is a
  revocation-breach, in which case the write is refused per the
  cross-bucket invariant).
- A poisoned envelope on the source watch-stream raises
  :class:`CapabilityPolicyEnvelopeError` from the run loop and
  terminates replication with the metrics counter
  :attr:`CapabilityPolicyReplicationMetrics.envelope_errors`
  incremented. The target state is NOT corrupted because the
  poisoned event never reaches the target write path.
- A target-side :class:`CapabilityPolicyConflictError` (under the
  ``CAS_PIN`` policy) is observable through
  :attr:`CapabilityPolicyReplicationMetrics.cas_conflicts`; the
  replicator continues with the next source event by default.
  A target-side :class:`CapabilityPolicyRevocationConflict` is
  observable through
  :attr:`CapabilityPolicyReplicationMetrics.revocation_breaches`;
  the replicator continues with the next source event by default.

Pattern source: the Sprint-3 Tag-6 schema-registry replicator
(:mod:`wirelang.schemas.replication`). Tag-6 is the
capability-policy analogue with the revocation-monotonic-invariant
extension; the SchemaRegistry replicator has no equivalent
invariant because schema-registry entries are append-only at the
``(layer, name, version)`` triple and do NOT carry a one-way
authority gesture.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from wirelang.schemas.capability_policy_nats_kv_backend import (
    CapabilityPolicyBackendError,
    CapabilityPolicyConflictError,
    CapabilityPolicyEnvelopeError,
    CapabilityPolicyRecord,
    CapabilityPolicyRevocationConflict,
    CapabilityPolicyWatchEvent,
    CapabilityPolicyWatchOp,
    NatsKvCapabilityPolicyBackend,
    _record_to_envelope,
    open_capability_policy_watch_stream,
)


__all__ = [
    "CapabilityPolicyReplicationConflictPolicy",
    "CapabilityPolicyReplicationDecision",
    "CapabilityPolicyReplicationFilter",
    "CapabilityPolicyReplicationMetrics",
    "CapabilityPolicyReplicator",
    "bootstrap_capability_policy_target_from_source",
]


class CapabilityPolicyReplicationConflictPolicy(enum.Enum):
    """How the replicator writes to the target capability-policy bucket.

    - ``SOURCE_WINS``: target writes are LWW (Sprint-5 Tag-2 path);
      whatever the source emits lands on the target unconditionally,
      with the single exception of revocation-monotonic refusals
      enforced in-band by the replicator (a live revoked target
      record is never silently overwritten with an unrevoked source
      record).
    - ``CAS_PIN``: target writes are CAS-pinned against the target's
      observed revision (Sprint-5 Tag-4 path); a target-side
      concurrent write surfaces as
      :class:`CapabilityPolicyConflictError` and the replicator
      surfaces the conflict to the metrics counter. A revocation-
      monotonic refusal surfaces as
      :class:`CapabilityPolicyRevocationConflict` and is counted
      separately.
    """

    SOURCE_WINS = "source-wins"
    CAS_PIN = "cas-pin"


class CapabilityPolicyReplicationDecision(enum.Enum):
    """Per-event decision returned by a
    :class:`CapabilityPolicyReplicationFilter`.

    - ``APPLY``: replicate the event to the target.
    - ``SKIP``: do NOT replicate; observed but ignored.
    """

    APPLY = "apply"
    SKIP = "skip"


# A filter is a callable that takes a CapabilityPolicyWatchEvent and
# returns a CapabilityPolicyReplicationDecision. Filters are pure
# (no I/O) by contract; the replicator calls them inside its event
# loop and treats them as fast.
CapabilityPolicyReplicationFilter = Callable[
    [CapabilityPolicyWatchEvent],
    CapabilityPolicyReplicationDecision,
]


def _accept_all(
    _event: CapabilityPolicyWatchEvent,
) -> CapabilityPolicyReplicationDecision:
    """Default filter: replicate every event."""
    return CapabilityPolicyReplicationDecision.APPLY


@dataclass
class CapabilityPolicyReplicationMetrics:
    """Counters surfacing the capability-policy replicator's per-run state.

    The replicator updates these counters synchronously inside its
    event loop. Tests assert against the final shape; production
    operators expose them via a metrics-pull endpoint (out of scope
    for Tag-6).

    Fields
    ------

    - ``bootstrap_applied``: count of source-side records written
      to the target during the initial bootstrap pass.
    - ``bootstrap_skipped_by_filter``: count of source-side records
      seen during bootstrap that the filter rejected.
    - ``bootstrap_skipped_idempotent``: count of source-side records
      already byte-equal on the target (no-op write).
    - ``bootstrap_revocation_breaches``: count of source-side
      records that, during bootstrap, would have un-revoked or
      advance-instant-overwritten a live revoked target record.
      The replicator refuses such writes under both policies; this
      counter advances under both SOURCE_WINS (in-band refusal)
      and CAS_PIN (server-side refusal) policies.
    - ``events_applied_put``: count of live PUT events written to
      the target during the watch-stream tail.
    - ``events_applied_delete``: count of live DELETE/PURGE events
      applied to the target.
    - ``events_skipped_by_filter``: count of live events filtered
      out.
    - ``cas_conflicts``: count of target-side CAS conflicts
      observed under the ``CAS_PIN`` policy. Always 0 under
      ``SOURCE_WINS``.
    - ``revocation_breaches``: count of revocation-monotonic
      refusals observed during the live tail (independent from the
      bootstrap counter). Advances under both policies; see
      ``bootstrap_revocation_breaches`` for the bootstrap-pass
      counterpart.
    - ``envelope_errors``: count of envelope poison events observed
      on the source watch-stream. Replication halts on first
      envelope error; this counter is 0 or 1.
    """

    bootstrap_applied: int = 0
    bootstrap_skipped_by_filter: int = 0
    bootstrap_skipped_idempotent: int = 0
    bootstrap_revocation_breaches: int = 0
    events_applied_put: int = 0
    events_applied_delete: int = 0
    events_skipped_by_filter: int = 0
    cas_conflicts: int = 0
    revocation_breaches: int = 0
    envelope_errors: int = 0


def _records_byte_equal(
    a: Optional[CapabilityPolicyRecord],
    b: Optional[CapabilityPolicyRecord],
) -> bool:
    """Return True iff the two records serialise to byte-equal envelopes.

    Used by the bootstrap idempotency check: if the target already
    holds a record that round-trips to the same envelope bytes as
    the source-side record, the bootstrap pass treats it as a no-op.
    """
    if a is None or b is None:
        return False
    try:
        return _record_to_envelope(a) == _record_to_envelope(b)
    except Exception:
        return False


def _is_revocation_breach(
    *,
    live: Optional[CapabilityPolicyRecord],
    incoming: CapabilityPolicyRecord,
) -> bool:
    """Return True iff applying ``incoming`` to ``live`` would breach
    the cross-bucket revocation-monotonic invariant.

    The invariant: if ``live`` carries a non-None ``revoked_at``,
    then ``incoming`` MUST carry the same ``revoked_at`` instant
    (an idempotent rewrite, e.g. note refresh). Otherwise the write
    is a breach (un-revoke if ``incoming.policy.revoked_at is None``;
    advance-instant if it is strictly different).

    Equal-instant rewrites are NOT a breach (so a
    ``revocation_reason`` note refresh on a revoked policy
    replicates cleanly).
    """
    if live is None:
        return False
    if live.policy.revoked_at is None:
        return False
    incoming_revoked_at = incoming.policy.revoked_at
    return incoming_revoked_at != live.policy.revoked_at


async def bootstrap_capability_policy_target_from_source(
    *,
    source: NatsKvCapabilityPolicyBackend,
    target: NatsKvCapabilityPolicyBackend,
    filter_fn: Optional[CapabilityPolicyReplicationFilter] = None,
    metrics: Optional[CapabilityPolicyReplicationMetrics] = None,
) -> CapabilityPolicyReplicationMetrics:
    """Run the bootstrap pass: copy every source record onto the target.

    The bootstrap pass is the *initial-sync* phase of replication.
    It runs once per replicator session and seeds the target's
    state from a complete source snapshot. The pass is LWW on the
    target (it ignores any concurrent target-side mutations) EXCEPT
    when the cross-bucket revocation-monotonic invariant would be
    breached, in which case the write is refused and
    :attr:`bootstrap_revocation_breaches` advances. A subsequent
    :class:`CapabilityPolicyReplicator` event loop tracks the
    source's live tail.

    Bootstrap ordering: source records are written in keys-sorted
    order (lexicographic on the
    ``capability-policies/<registered_by>/<policy_id>`` key
    space). This is a determinism convenience for log-replay
    tests; nats-py KV does not guarantee cross-key ordering anyway.

    Idempotency: if the target already holds a record that is
    byte-equal to the source-side record (envelope round-trip),
    the bootstrap pass treats it as a no-op
    (``bootstrap_skipped_idempotent`` counter advances). This
    makes re-running the bootstrap on a partially-replicated target
    safe.

    Filter: the optional ``filter_fn`` is invoked with a synthetic
    PUT :class:`CapabilityPolicyWatchEvent` per source record;
    events the filter rejects do NOT touch the target.

    Args:
        source: the source-of-truth capability-policy backend.
        target: the target capability-policy backend to write into.
        filter_fn: optional filter; defaults to accept-all.
        metrics: optional metrics object; the call updates it
            in-place. A fresh
            :class:`CapabilityPolicyReplicationMetrics` is created
            and returned if ``None``.

    Returns:
        The metrics object (the same instance as ``metrics`` if
        supplied; otherwise a fresh one).
    """
    if not isinstance(source, NatsKvCapabilityPolicyBackend):
        raise TypeError(
            "source must be a NatsKvCapabilityPolicyBackend"
        )
    if not isinstance(target, NatsKvCapabilityPolicyBackend):
        raise TypeError(
            "target must be a NatsKvCapabilityPolicyBackend"
        )
    if filter_fn is None:
        filter_fn = _accept_all
    if metrics is None:
        metrics = CapabilityPolicyReplicationMetrics()

    source_records = await source.snapshot()
    # Order by key for log-replay determinism.
    source_records_sorted = sorted(
        source_records, key=lambda r: r.key
    )
    for record in source_records_sorted:
        synthetic_event = CapabilityPolicyWatchEvent(
            op=CapabilityPolicyWatchOp.PUT,
            key=record.key,
            record=record,
            revision=0,
        )
        decision = filter_fn(synthetic_event)
        if not isinstance(
            decision, CapabilityPolicyReplicationDecision
        ):
            raise TypeError(
                "filter_fn must return a "
                "CapabilityPolicyReplicationDecision, got "
                f"{type(decision).__name__}"
            )
        if (
            decision
            is CapabilityPolicyReplicationDecision.SKIP
        ):
            metrics.bootstrap_skipped_by_filter += 1
            continue
        # Idempotency check: skip if the target already byte-equal.
        target_record = await target.get(record.key)
        if _records_byte_equal(record, target_record):
            metrics.bootstrap_skipped_idempotent += 1
            continue
        # Revocation-monotonic refusal: if the target holds a
        # revoked record and the incoming source record would
        # un-revoke or advance the instant, refuse and continue.
        if _is_revocation_breach(
            live=target_record, incoming=record
        ):
            metrics.bootstrap_revocation_breaches += 1
            continue
        # Source-wins write to target via LWW path.
        await target.put(record)
        metrics.bootstrap_applied += 1

    return metrics


@dataclass
class CapabilityPolicyReplicator:
    """One-way capability-policy replicator (source → target).

    Composes the Sprint-5 Tag-5 source-side watch-stream + the
    Sprint-5 Tag-4 / Tag-2 target-side write paths + the
    Sprint-6 Tag-1 revocation-monotonic invariant. Bootstrap is
    via :func:`bootstrap_capability_policy_target_from_source`
    (called by :meth:`run` once before the watch-stream loop).

    Construction is cheap: the replicator performs no I/O until
    :meth:`run` is awaited. The caller is responsible for opening
    the underlying KV handles on both backends; the replicator
    does not establish NATS connections itself.

    Conflict policy:

    - ``CapabilityPolicyReplicationConflictPolicy.SOURCE_WINS``
      (default): target writes go through ``put`` (LWW). The
      replicator runs an in-band revocation-monotonic check
      BEFORE the ``put`` call; concurrent target-side non-
      revocation mutations are silently overwritten on the next
      source emit.
    - ``CapabilityPolicyReplicationConflictPolicy.CAS_PIN``:
      target writes go through ``put_with_revision`` against the
      target's currently-observed revision (read via
      :meth:`NatsKvCapabilityPolicyBackend.get_with_revision`
      just before the write). The Sprint-6 Tag-1 server-side
      revocation-monotonic gate enforces the invariant; the
      replicator catches the
      :class:`CapabilityPolicyRevocationConflict` and surfaces it
      via :attr:`revocation_breaches`. A plain CAS conflict
      (revision drift) is observed via
      :attr:`cas_conflicts`.

    Filter:

    - The optional ``filter_fn`` is invoked on every observed
      event (bootstrap synthetic events and live tail events
      alike). A ``SKIP`` decision means the event is NOT applied
      to the target; the relevant ``*_skipped_by_filter`` counter
      advances.

    Halt policy:

    - ``halt_on_envelope_error`` (default ``True``): a poisoned
      source-side envelope terminates :meth:`run` with a
      re-raised :class:`CapabilityPolicyEnvelopeError`.
    - ``halt_on_conflict`` (default ``False``): a target-side CAS
      conflict (under ``CAS_PIN`` policy) terminates :meth:`run`
      with a re-raised :class:`CapabilityPolicyConflictError`.
    - ``halt_on_revocation_breach`` (default ``False``): a
      revocation-monotonic breach (LWW in-band refusal under
      ``SOURCE_WINS``, server-side
      :class:`CapabilityPolicyRevocationConflict` under
      ``CAS_PIN``) terminates :meth:`run` with the original
      exception re-raised (or a synthetic
      :class:`CapabilityPolicyRevocationConflict` if the
      SOURCE_WINS in-band path triggered the refusal).

    Stop policy:

    - The replicator runs until the source watch-stream
      terminates (``StopAsyncIteration``) or an unhandled
      exception bubbles up. Operators that want a finite run
      pass a watch-stream that itself terminates; production
      operators run :meth:`run` inside an asyncio task they
      cancel on shutdown.
    """

    source: NatsKvCapabilityPolicyBackend
    target: NatsKvCapabilityPolicyBackend
    conflict_policy: CapabilityPolicyReplicationConflictPolicy = (
        CapabilityPolicyReplicationConflictPolicy.SOURCE_WINS
    )
    filter_fn: CapabilityPolicyReplicationFilter = field(
        default=_accept_all
    )
    halt_on_envelope_error: bool = True
    halt_on_conflict: bool = False
    halt_on_revocation_breach: bool = False
    metrics: CapabilityPolicyReplicationMetrics = field(
        default_factory=CapabilityPolicyReplicationMetrics
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.source, NatsKvCapabilityPolicyBackend
        ):
            raise TypeError(
                "source must be a NatsKvCapabilityPolicyBackend"
            )
        if not isinstance(
            self.target, NatsKvCapabilityPolicyBackend
        ):
            raise TypeError(
                "target must be a NatsKvCapabilityPolicyBackend"
            )
        if self.source is self.target:
            raise ValueError(
                "source and target must be distinct backends "
                "(self-replication is not supported)"
            )
        if not isinstance(
            self.conflict_policy,
            CapabilityPolicyReplicationConflictPolicy,
        ):
            raise TypeError(
                "conflict_policy must be a "
                "CapabilityPolicyReplicationConflictPolicy, "
                f"got {type(self.conflict_policy).__name__}"
            )

    async def bootstrap(
        self,
    ) -> CapabilityPolicyReplicationMetrics:
        """Run the bootstrap pass.

        Convenience method that delegates to
        :func:`bootstrap_capability_policy_target_from_source`.
        Updates the replicator's :attr:`metrics` in-place and
        returns it.
        """
        return await bootstrap_capability_policy_target_from_source(
            source=self.source,
            target=self.target,
            filter_fn=self.filter_fn,
            metrics=self.metrics,
        )

    async def _apply_put(
        self, event: CapabilityPolicyWatchEvent
    ) -> None:
        """Apply a PUT event to the target.

        Routes through ``put`` (SOURCE_WINS) or
        ``put_with_revision`` (CAS_PIN). Updates
        ``metrics.events_applied_put`` on success. Updates
        ``metrics.cas_conflicts`` on a CAS conflict;
        ``metrics.revocation_breaches`` on a revocation-monotonic
        refusal; re-raises if the corresponding halt flag is set.
        """
        if event.record is None:
            raise CapabilityPolicyEnvelopeError(
                "PUT CapabilityPolicyWatchEvent must carry a "
                f"non-None record; key={event.key!r}"
            )

        if (
            self.conflict_policy
            is CapabilityPolicyReplicationConflictPolicy.SOURCE_WINS
        ):
            # In-band revocation-monotonic check on LWW path.
            live = await self.target.get(event.key)
            if _is_revocation_breach(
                live=live, incoming=event.record
            ):
                self.metrics.revocation_breaches += 1
                if self.halt_on_revocation_breach:
                    raise CapabilityPolicyRevocationConflict(
                        "cross-bucket replication refused to "
                        "overwrite a revoked target record under "
                        "SOURCE_WINS: "
                        f"key={event.key!r} "
                        f"live_revoked_at="
                        f"{live.policy.revoked_at!r} "
                        f"incoming_revoked_at="
                        f"{event.record.policy.revoked_at!r}",
                        key=event.key,
                        existing_revoked_at=(
                            live.policy.revoked_at
                            if live is not None
                            else None
                        ),
                        proposed_revoked_at=(
                            event.record.policy.revoked_at
                        ),
                    )
                return
            await self.target.put(event.record)
            self.metrics.events_applied_put += 1
            return

        # CAS_PIN: read the target's current revision, then write
        # with that as expected_revision. If the target is absent,
        # use put (LWW) for the create case (CAS-pin with revision
        # 0 only succeeds via the create-only adapter shape;
        # falling through to put is safe because the LWW path is
        # the source-of-truth contract for a key that has never
        # been written to the target).
        existing = await self.target.get_with_revision(event.key)
        if existing is None:
            await self.target.put(event.record)
            self.metrics.events_applied_put += 1
            return

        _existing_record, observed_revision = existing
        try:
            await self.target.put_with_revision(
                event.record, observed_revision
            )
        except CapabilityPolicyRevocationConflict:
            # Sprint-6 Tag-1 server-side gate: revocation-monotonic
            # invariant breached. Counted as a revocation breach
            # (NOT as a CAS conflict — the CAS check itself did
            # not run because the revocation gate is earlier).
            self.metrics.revocation_breaches += 1
            if self.halt_on_revocation_breach:
                raise
            return
        except CapabilityPolicyConflictError:
            self.metrics.cas_conflicts += 1
            if self.halt_on_conflict:
                raise
            return
        self.metrics.events_applied_put += 1

    async def _apply_delete(
        self, event: CapabilityPolicyWatchEvent
    ) -> None:
        """Apply a DELETE / PURGE event to the target.

        Updates ``metrics.events_applied_delete`` on success. The
        target-side ``delete`` is a no-op if the key is already
        absent; that case still counts as
        ``events_applied_delete`` (the operator's intent was that
        the target reflect the absence of the key after the
        event).

        DELETE / PURGE removes a revocation lineage from the
        target (substrate-level hard removal); a subsequent PUT
        for the same key has fresh prior-state on the target.
        This is consistent with the Sprint-6 Tag-3 revocation-
        event-classifier behaviour where DELETE drops the
        per-key state from the classifier.
        """
        await self.target.delete(event.key)
        self.metrics.events_applied_delete += 1

    async def _consume_event(
        self, event: CapabilityPolicyWatchEvent
    ) -> None:
        """Apply one decoded event to the target via the conflict policy."""
        decision = self.filter_fn(event)
        if not isinstance(
            decision, CapabilityPolicyReplicationDecision
        ):
            raise TypeError(
                "filter_fn must return a "
                "CapabilityPolicyReplicationDecision, got "
                f"{type(decision).__name__}"
            )
        if (
            decision
            is CapabilityPolicyReplicationDecision.SKIP
        ):
            self.metrics.events_skipped_by_filter += 1
            return
        if event.op is CapabilityPolicyWatchOp.PUT:
            await self._apply_put(event)
        else:
            # DELETE / PURGE: same target-side action.
            await self._apply_delete(event)

    async def run(
        self, *, bootstrap: bool = True
    ) -> CapabilityPolicyReplicationMetrics:
        """Run the replicator: bootstrap, then consume the watch-stream.

        Args:
            bootstrap: if True (default), run the bootstrap pass
                before opening the watch-stream. Operators who
                have already bootstrapped the target can pass
                ``False``.

        Returns:
            The replicator's :attr:`metrics` object (same
            instance).

        Raises:
            CapabilityPolicyEnvelopeError: a poisoned envelope on
                the source watch-stream (under default
                ``halt_on_envelope_error=True``). The metrics
                counter ``envelope_errors`` is incremented before
                re-raise.
            CapabilityPolicyConflictError: a target-side CAS
                conflict (under ``CAS_PIN`` policy with
                ``halt_on_conflict=True``).
            CapabilityPolicyRevocationConflict: a target-side
                revocation-monotonic breach (under either policy
                with ``halt_on_revocation_breach=True``).
            CapabilityPolicyBackendError: an unrecoverable backend
                error on either side.
        """
        if bootstrap:
            await self.bootstrap()

        stream = await open_capability_policy_watch_stream(
            self.source
        )
        try:
            async for event in stream:
                try:
                    await self._consume_event(event)
                except CapabilityPolicyEnvelopeError:
                    self.metrics.envelope_errors += 1
                    if self.halt_on_envelope_error:
                        raise
        except CapabilityPolicyEnvelopeError:
            # The decoder inside the stream itself raised; the
            # iterator has terminated. Surface the failure if
            # the halt policy demands it; otherwise swallow and
            # return.
            self.metrics.envelope_errors += 1
            if self.halt_on_envelope_error:
                raise
        finally:
            # Best-effort close: __aexit__ semantics on the
            # handle.
            await stream.__aexit__(None, None, None)

        return self.metrics
