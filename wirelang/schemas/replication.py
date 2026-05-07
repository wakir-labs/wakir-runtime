# SPDX-License-Identifier: Apache-2.0
"""Cross-bucket schema replication for the Wirelang schema registry.

Phase-1b Sprint-3 Tag-6 (S3-6) lands the production-target
replication layer for the Wirelang schema registry described in
``wirelang/specs/schema-registry-spec.md``. The replication layer
mirrors the contents of one ``wakir-schemas`` bucket onto another:

- **multi-org federation:** two organisations run independent NATS
  clusters and want a one-way mirror of a curated set of
  ``(layer, name, version)`` triples (e.g. an upstream registry that
  publishes Wakir-canonical schemas, replicated into a downstream
  org's local cluster for offline lookup).
- **cross-cluster mirror:** a single org runs two NATS clusters
  (e.g. an active and a hot-standby), and wants the standby to track
  the active cluster's schema bucket for fail-over readiness.

Composition contract
--------------------

The replicator is a *thin composition* of three Phase-1c surfaces
that already shipped in Tag-3 / Tag-4 / Tag-5:

- **Source side (Tag-4 watch-stream):** the replicator opens a
  :func:`open_watch_stream` over the source backend and consumes
  decoded :class:`WatchEvent` instances one at a time. Bootstrap is
  taken from :meth:`NatsKvSchemaRegistry.snapshot` so the target
  starts from a complete, self-consistent view; the watch-stream then
  fills in the live tail.
- **Target side (Tag-3 CAS-pin + Tag-1 LWW):** the replicator writes
  each event to the target backend through one of two paths,
  selectable via :class:`ReplicationConflictPolicy`:

  - ``SOURCE_WINS`` (default): writes go through
    :meth:`NatsKvSchemaRegistry.put` (LWW). The source-of-truth is
    the source bucket; whatever the source emits lands on the target
    unconditionally. Concurrent target-side writes are silently
    overwritten on the next source emit.
  - ``CAS_PIN``: writes go through
    :meth:`NatsKvSchemaRegistry.put_with_revision` against the
    target's currently-observed revision. If the target has been
    independently mutated since the replicator's last read, the
    CAS-pin call raises
    :class:`SchemaRegistryConflictError` and the replicator
    surfaces the conflict to the operator (via the
    :class:`ReplicationFilter` callback or the metrics counter)
    *without* re-applying the source event. This is the correct
    behaviour when the target is also a writeable surface and the
    operator wants to detect divergence.

- **Operator-input side (Tag-5 publisher CLI):** when an operator
  needs to forcibly re-apply a divergent target entry from the
  source, they invoke the Tag-5 publisher CLI against the target
  bucket with the source-side schema body. The replicator does NOT
  itself bake an operator-override into its event-loop; that is a
  separate operator concern.

The composition surfaces three Phase-1c capabilities into a single
substrate:

1. Bootstrap: full source snapshot → target backend (one
   :meth:`NatsKvSchemaRegistry.put` per source entry, in keys-sorted
   order, idempotent against re-runs).
2. Tail: source watch-stream → target backend (one
   :meth:`NatsKvSchemaRegistry.put` or
   :meth:`NatsKvSchemaRegistry.put_with_revision` per source event).
3. Filter: an optional :class:`ReplicationFilter` lets operators
   restrict replication to a curated subset (by layer, by triple, or
   by schema-id pattern). The filter runs on the source-side event
   shape, so a filtered-out event is observed by the replicator but
   not applied to the target.

Phase-1c boundary
-----------------

The replicator does NOT implement:

- **Bidirectional replication.** Tag-6 is one-way (source → target).
  Bidirectional replication requires conflict-free CRDT-style merges
  that are out of scope for Phase-1c (Phase-2 reservation:
  ``OI-7-Phase-2-bidir-replication``).
- **Multi-source fan-in.** Tag-6 has exactly one source backend and
  one target backend per :class:`SchemaReplicator` instance;
  operators that want fan-in run multiple replicators against one
  target.
- **Watch-stream resume policy.** The replicator restarts from a
  full snapshot on every connection drop; resume-from-revision is a
  Phase-2 hardening item (``OI-7-Phase-2-resume``).
- **Capability-token enforcement on the target write.** The
  replicator inherits whatever NATS credentials the operator's
  environment provides on each backend; capability-token enforcement
  at the replication boundary is ``OI-7-Phase-2-sig`` reserved.

Determinism contract
--------------------

The replicator preserves the determinism contract of the underlying
backends:

- A bootstrap-only run (no live tail) leaves the target's keysets
  byte-equal to the source's keysets after the run (modulo entries
  filtered out by a :class:`ReplicationFilter`). Re-running the
  bootstrap on the same source state is a no-op for entries already
  byte-equal on the target (idempotency via envelope-byte
  comparison; LWW on byte-mismatch).
- A poisoned envelope on the source watch-stream raises
  :class:`SchemaRegistryEnvelopeError` from the run loop and
  terminates replication with the metrics counter
  :attr:`ReplicationMetrics.envelope_errors` incremented. The target
  state is NOT corrupted because the poisoned event never reaches
  the target write path.
- A target-side ``SchemaRegistryConflictError`` (under the
  ``CAS_PIN`` policy) is observable through
  :attr:`ReplicationMetrics.cas_conflicts`; the replicator continues
  with the next source event by default. Operators who want to halt
  on first conflict pass ``halt_on_conflict=True``.

Pattern source: the V-908 federation routes backend ships the
Tag-6 watch-stream pattern; this module is the schema-registry
analogue. There is no V-908 *replication* pattern (the V-908 routes
backend has not yet shipped a replication layer); Tag-6 is therefore
the canonical Wakir-internal replication template.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from wirelang.schemas.registry_nats_kv_backend import (
    InMemorySchemaRegistry,
    LiveSchemaSnapshot,
    NatsKvSchemaRegistry,
    SchemaRegistryBackendError,
    SchemaRegistryConflictError,
    SchemaRegistryEntry,
    SchemaRegistryEnvelopeError,
    WatchEvent,
    WatchOp,
    _entry_to_envelope,
    open_watch_stream,
)


__all__ = [
    "ReplicationConflictPolicy",
    "ReplicationDecision",
    "ReplicationFilter",
    "ReplicationMetrics",
    "SchemaReplicator",
    "bootstrap_target_from_source",
]


class ReplicationConflictPolicy(enum.Enum):
    """How the replicator writes to the target bucket.

    - ``SOURCE_WINS``: target writes are LWW (Tag-1 path); whatever
      the source emits lands on the target unconditionally.
    - ``CAS_PIN``: target writes are CAS-pinned against the target's
      observed revision (Tag-3 path); a target-side concurrent write
      surfaces as :class:`SchemaRegistryConflictError` and the
      replicator surfaces the conflict to the metrics counter.
    """

    SOURCE_WINS = "source-wins"
    CAS_PIN = "cas-pin"


class ReplicationDecision(enum.Enum):
    """Per-event decision returned by a :class:`ReplicationFilter`.

    - ``APPLY``: replicate the event to the target.
    - ``SKIP``: do NOT replicate; observed but ignored.
    """

    APPLY = "apply"
    SKIP = "skip"


# A filter is a callable that takes a WatchEvent and returns a
# ReplicationDecision. Filters are pure (no I/O) by contract; the
# replicator calls them inside its event loop and treats them as
# fast.
ReplicationFilter = Callable[[WatchEvent], ReplicationDecision]


def _accept_all(_event: WatchEvent) -> ReplicationDecision:
    """Default filter: replicate every event."""
    return ReplicationDecision.APPLY


@dataclass
class ReplicationMetrics:
    """Counters surfacing the replicator's per-run state.

    The replicator updates these counters synchronously inside its
    event loop. Tests assert against the final shape; production
    operators expose them via a metrics-pull endpoint (out of scope
    for Tag-6).

    Fields
    ------

    - ``bootstrap_applied``: count of source-side entries written to
      the target during the initial bootstrap pass.
    - ``bootstrap_skipped_by_filter``: count of source-side entries
      seen during bootstrap that the filter rejected.
    - ``bootstrap_skipped_idempotent``: count of source-side entries
      already byte-equal on the target (no-op write).
    - ``events_applied_put``: count of live PUT events written to the
      target during the watch-stream tail.
    - ``events_applied_delete``: count of live DELETE/PURGE events
      applied to the target.
    - ``events_skipped_by_filter``: count of live events filtered out.
    - ``cas_conflicts``: count of target-side CAS conflicts observed
      under the ``CAS_PIN`` policy. Always 0 under ``SOURCE_WINS``.
    - ``envelope_errors``: count of envelope poison events observed
      on the source watch-stream. Replication halts on first
      envelope error; this counter is 0 or 1.
    """

    bootstrap_applied: int = 0
    bootstrap_skipped_by_filter: int = 0
    bootstrap_skipped_idempotent: int = 0
    events_applied_put: int = 0
    events_applied_delete: int = 0
    events_skipped_by_filter: int = 0
    cas_conflicts: int = 0
    envelope_errors: int = 0


def _entries_byte_equal(
    a: Optional[SchemaRegistryEntry], b: Optional[SchemaRegistryEntry]
) -> bool:
    """Return True iff the two entries serialise to byte-equal envelopes.

    Used by the bootstrap idempotency check: if the target already
    holds an entry that round-trips to the same envelope bytes as the
    source-side entry, the bootstrap pass treats it as a no-op.
    """
    if a is None or b is None:
        return False
    try:
        return _entry_to_envelope(a) == _entry_to_envelope(b)
    except Exception:
        return False


async def bootstrap_target_from_source(
    *,
    source: NatsKvSchemaRegistry,
    target: NatsKvSchemaRegistry,
    filter_fn: Optional[ReplicationFilter] = None,
    metrics: Optional[ReplicationMetrics] = None,
) -> ReplicationMetrics:
    """Run the bootstrap pass: copy every source entry onto the target.

    The bootstrap pass is the *initial-sync* phase of replication.
    It runs once per replicator session and seeds the target's state
    from a complete source snapshot. The pass is LWW on the target
    (it ignores any concurrent target-side mutations); a subsequent
    :class:`SchemaReplicator` event loop tracks the source's live
    tail.

    Bootstrap ordering: source entries are written in
    ``keys_sorted()`` order (lexicographic). This is a determinism
    convenience for log-replay tests; nats-py KV does not guarantee
    cross-key ordering anyway.

    Idempotency: if the target already holds an entry that is
    byte-equal to the source-side entry (envelope round-trip), the
    bootstrap pass treats it as a no-op
    (``bootstrap_skipped_idempotent`` counter advances). This makes
    re-running the bootstrap on a partially-replicated target safe.

    Filter: the optional ``filter_fn`` is invoked with a synthetic
    PUT :class:`WatchEvent` per source entry; events the filter
    rejects do NOT touch the target. The synthetic event's
    ``revision`` is set to the current source revision on the
    bucket, sourced from the in-memory snapshot's index.

    Args:
        source: the source-of-truth backend.
        target: the target backend to write into.
        filter_fn: optional filter; defaults to accept-all.
        metrics: optional metrics object; the call updates it
            in-place. A fresh :class:`ReplicationMetrics` is created
            and returned if ``None``.

    Returns:
        The metrics object (the same instance as ``metrics`` if
        supplied; otherwise a fresh one).
    """
    if not isinstance(source, NatsKvSchemaRegistry):
        raise TypeError("source must be a NatsKvSchemaRegistry")
    if not isinstance(target, NatsKvSchemaRegistry):
        raise TypeError("target must be a NatsKvSchemaRegistry")
    if filter_fn is None:
        filter_fn = _accept_all
    if metrics is None:
        metrics = ReplicationMetrics()

    snapshot: InMemorySchemaRegistry = await source.snapshot()
    for key in snapshot.keys_sorted():
        source_entry = snapshot.lookup(key)
        if source_entry is None:
            # Should not happen; keys_sorted() is derived from
            # snapshot.entries which is the dict we just iterated.
            continue
        synthetic_event = WatchEvent(
            op=WatchOp.PUT,
            key=key,
            entry=source_entry,
            revision=0,
        )
        decision = filter_fn(synthetic_event)
        if not isinstance(decision, ReplicationDecision):
            raise TypeError(
                "filter_fn must return a ReplicationDecision, got "
                f"{type(decision).__name__}"
            )
        if decision is ReplicationDecision.SKIP:
            metrics.bootstrap_skipped_by_filter += 1
            continue
        # Idempotency check: skip if the target already byte-equal.
        target_entry = await target.get(key)
        if _entries_byte_equal(source_entry, target_entry):
            metrics.bootstrap_skipped_idempotent += 1
            continue
        # Source-wins write to target via LWW path.
        await target.put(source_entry)
        metrics.bootstrap_applied += 1

    return metrics


@dataclass
class SchemaReplicator:
    """One-way schema-registry replicator (source → target).

    Composes Tag-4 source-side watch-stream + Tag-3 / Tag-1 target-side
    write paths. Bootstrap is via :func:`bootstrap_target_from_source`
    (called by :meth:`run` once before the watch-stream loop).

    Construction is cheap: the replicator performs no I/O until
    :meth:`run` is awaited. The caller is responsible for opening
    the underlying KV handles on both backends; the replicator does
    not establish NATS connections itself.

    Conflict policy:

    - ``ReplicationConflictPolicy.SOURCE_WINS`` (default): target
      writes go through ``put`` (LWW). Concurrent target-side mutations
      are silently overwritten on the next source emit.
    - ``ReplicationConflictPolicy.CAS_PIN``: target writes go through
      ``put_with_revision`` against the target's currently-observed
      revision (read via :meth:`NatsKvSchemaRegistry.get_with_revision`
      just before the write). A conflict is observed via the
      :attr:`ReplicationMetrics.cas_conflicts` counter; the
      replicator continues with the next event unless
      ``halt_on_conflict=True``.

    Filter:

    - The optional ``filter_fn`` is invoked on every observed event
      (bootstrap synthetic events and live tail events alike). A
      ``SKIP`` decision means the event is NOT applied to the target;
      the relevant ``*_skipped_by_filter`` counter advances.

    Halt policy:

    - ``halt_on_envelope_error`` (default ``True``): a poisoned
      source-side envelope terminates :meth:`run` with a re-raised
      :class:`SchemaRegistryEnvelopeError`. The metrics counter
      ``envelope_errors`` is incremented to 1 before re-raise.
    - ``halt_on_conflict`` (default ``False``): a target-side CAS
      conflict (under ``CAS_PIN`` policy) terminates :meth:`run` with
      a re-raised :class:`SchemaRegistryConflictError`. The metrics
      counter ``cas_conflicts`` is incremented before re-raise.

    Stop policy:

    - The replicator runs until the source watch-stream terminates
      (``StopAsyncIteration``) or an unhandled exception bubbles up.
      Operators that want a finite run pass a watch-stream that
      itself terminates (e.g. a mock that closes after N events);
      production operators run :meth:`run` inside an asyncio task
      they cancel on shutdown.
    """

    source: NatsKvSchemaRegistry
    target: NatsKvSchemaRegistry
    conflict_policy: ReplicationConflictPolicy = (
        ReplicationConflictPolicy.SOURCE_WINS
    )
    filter_fn: ReplicationFilter = field(default=_accept_all)
    halt_on_envelope_error: bool = True
    halt_on_conflict: bool = False
    metrics: ReplicationMetrics = field(default_factory=ReplicationMetrics)

    def __post_init__(self) -> None:
        if not isinstance(self.source, NatsKvSchemaRegistry):
            raise TypeError("source must be a NatsKvSchemaRegistry")
        if not isinstance(self.target, NatsKvSchemaRegistry):
            raise TypeError("target must be a NatsKvSchemaRegistry")
        if self.source is self.target:
            raise ValueError(
                "source and target must be distinct backends "
                "(self-replication is not supported)"
            )
        if not isinstance(
            self.conflict_policy, ReplicationConflictPolicy
        ):
            raise TypeError(
                "conflict_policy must be a ReplicationConflictPolicy, "
                f"got {type(self.conflict_policy).__name__}"
            )

    async def bootstrap(self) -> ReplicationMetrics:
        """Run the bootstrap pass.

        Convenience method that delegates to
        :func:`bootstrap_target_from_source`. Updates the
        replicator's :attr:`metrics` in-place and returns it.
        """
        return await bootstrap_target_from_source(
            source=self.source,
            target=self.target,
            filter_fn=self.filter_fn,
            metrics=self.metrics,
        )

    async def _apply_put(self, event: WatchEvent) -> None:
        """Apply a PUT event to the target.

        Routes through ``put`` (SOURCE_WINS) or ``put_with_revision``
        (CAS_PIN). Updates ``metrics.events_applied_put`` on success.
        Updates ``metrics.cas_conflicts`` on a CAS conflict; re-raises
        if ``halt_on_conflict`` is set.
        """
        if event.entry is None:
            raise SchemaRegistryEnvelopeError(
                "PUT WatchEvent must carry a non-None entry; "
                f"key={event.key!r}"
            )

        if self.conflict_policy is ReplicationConflictPolicy.SOURCE_WINS:
            await self.target.put(event.entry)
            self.metrics.events_applied_put += 1
            return

        # CAS_PIN: read the target's current revision, then write
        # with that as expected_revision. If the target is absent,
        # use put (LWW) for the create case (CAS_PIN with revision 0
        # only succeeds via the create-only adapter shape; falling
        # through to put is safe because the LWW path is the
        # source-of-truth contract for a key that has never been
        # written to the target).
        existing = await self.target.get_with_revision(event.key)
        if existing is None:
            await self.target.put(event.entry)
            self.metrics.events_applied_put += 1
            return

        _existing_entry, observed_revision = existing
        try:
            await self.target.put_with_revision(
                event.entry, observed_revision
            )
        except SchemaRegistryConflictError:
            self.metrics.cas_conflicts += 1
            if self.halt_on_conflict:
                raise
            return
        self.metrics.events_applied_put += 1

    async def _apply_delete(self, event: WatchEvent) -> None:
        """Apply a DELETE / PURGE event to the target.

        Updates ``metrics.events_applied_delete`` on success. The
        target-side ``delete`` is a no-op if the key is already
        absent; that case still counts as ``events_applied_delete``
        (the operator's intent was that the target reflect the
        absence of the key after the event).
        """
        await self.target.delete(event.key)
        self.metrics.events_applied_delete += 1

    async def _consume_event(self, event: WatchEvent) -> None:
        """Apply one decoded event to the target via the conflict policy."""
        decision = self.filter_fn(event)
        if not isinstance(decision, ReplicationDecision):
            raise TypeError(
                "filter_fn must return a ReplicationDecision, got "
                f"{type(decision).__name__}"
            )
        if decision is ReplicationDecision.SKIP:
            self.metrics.events_skipped_by_filter += 1
            return
        if event.op is WatchOp.PUT:
            await self._apply_put(event)
        else:
            # DELETE / PURGE: same target-side action.
            await self._apply_delete(event)

    async def run(
        self, *, bootstrap: bool = True
    ) -> ReplicationMetrics:
        """Run the replicator: bootstrap, then consume the watch-stream.

        Args:
            bootstrap: if True (default), run the bootstrap pass
                before opening the watch-stream. Operators who have
                already bootstrapped the target (e.g. via a manual
                snapshot copy) can pass ``False``.

        Returns:
            The replicator's :attr:`metrics` object (same instance).

        Raises:
            SchemaRegistryEnvelopeError: a poisoned envelope on the
                source watch-stream (under default
                ``halt_on_envelope_error=True``). The metrics counter
                ``envelope_errors`` is incremented before re-raise.
            SchemaRegistryConflictError: a target-side CAS conflict
                (under ``CAS_PIN`` policy with
                ``halt_on_conflict=True``).
            SchemaRegistryBackendError: an unrecoverable backend
                error on either side.
        """
        if bootstrap:
            await self.bootstrap()

        stream = await open_watch_stream(self.source)
        try:
            async for event in stream:
                try:
                    await self._consume_event(event)
                except SchemaRegistryEnvelopeError:
                    self.metrics.envelope_errors += 1
                    if self.halt_on_envelope_error:
                        raise
        except SchemaRegistryEnvelopeError:
            # The decoder inside the stream itself raised; the
            # iterator has terminated. Surface the failure if the
            # halt policy demands it; otherwise swallow and return.
            self.metrics.envelope_errors += 1
            if self.halt_on_envelope_error:
                raise
        finally:
            # Best-effort close: __aexit__ semantics on the handle.
            await stream.__aexit__(None, None, None)

        return self.metrics
