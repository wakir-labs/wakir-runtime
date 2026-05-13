# SPDX-License-Identifier: Apache-2.0
"""Multi-org-attestation cross-bucket live-tail replicator.

Phase-2 Sprint-7 Tag-6 lands the **live-tail replicator** as the
continuous-stream composition layer on top of the Sprint-7 Tag-2
:func:`bootstrap_multi_org_attestation_target_from_source` one-shot
bootstrap. Together the two surfaces form the **full cross-bucket
replication suite** for the ``wakir-multi-org-attestations`` bucket
(pattern-mirror on the Sprint-6 Tag-6 capability-policy
cross-bucket replicator at
:mod:`wirelang.schemas.capability_policy_replication`).

Surface
-------

This module ships a single primary class plus three lightweight
co-types (re-exported from the Tag-2 backend for caller-side
convenience):

- :class:`MultiOrgAttestationReplicator` — the replicator orchestrator.
  Composes Tag-2 backend ``snapshot`` + ``watch`` + ``put`` /
  ``put_with_revision`` into a one-way (source → target)
  durable-stream replicator. The replicator is async; the caller
  is responsible for opening the underlying NATS KV handles on
  both backends.

The Tag-2 :func:`bootstrap_multi_org_attestation_target_from_source`
remains the one-shot bootstrap entry-point and is composed by the
replicator on every :meth:`MultiOrgAttestationReplicator.run` call
(modulo the ``bootstrap`` opt-out flag).

Composition contract
--------------------

The replicator composes three Sprint-7 Tag-2 surfaces that already
shipped:

- **Bootstrap pass (Sprint-7 Tag-2):** the replicator delegates to
  :func:`bootstrap_multi_org_attestation_target_from_source` for the
  initial-sync phase. The bootstrap pass is idempotent against
  re-runs (byte-equal records are no-ops), honours the optional
  filter, and counts monotonic-invariant breaches separately from
  live-tail breaches (mirror of the Sprint-6 Tag-6 capability-
  policy replicator's bootstrap/live counter split).
- **Live-tail (Sprint-7 Tag-2 watch-stream):** the replicator opens
  a :func:`open_watch_stream` over the source backend and consumes
  decoded :class:`MultiOrgAttestationWatchEvent` instances one at a
  time. Each event is filtered, then routed to the target's write
  or delete path per the configured conflict policy.
- **Conflict policies (Sprint-7 Tag-2):** writes go through either
  :meth:`NatsKvMultiOrgAttestationRegistry.put` (SOURCE_WINS,
  default — LWW with in-band monotonic-invariant gate) or
  :meth:`NatsKvMultiOrgAttestationRegistry.put_with_revision`
  (CAS_PIN — pinned against the target's observed revision, with
  the same monotonic-invariant gate running BEFORE the CAS check).
  The two policies share the same monotonic-invariant guarantee
  (the gate runs at the backend layer in both cases); they differ
  in concurrent-write handling.

The replicator is **a thin composition** — no new backend surface,
no new envelope shape, no schema-version bump on the per-record
envelope. The Tag-6 spec-bump (v0.27.0 → v0.28.0) reflects the new
composition surface, not a new substrate.

Reused-from-Tag-2 surfaces (no re-definition)
---------------------------------------------

The replicator re-uses (does NOT re-define) these Sprint-7 Tag-2
public types:

- :class:`MultiOrgAttestationReplicationConflictPolicy` —
  enum SOURCE_WINS / CAS_PIN.
- :class:`MultiOrgAttestationReplicationDecision` —
  enum APPLY / SKIP for filter callables.
- :data:`MultiOrgAttestationReplicationFilter` —
  ``Callable[[MultiOrgAttestationWatchEvent], …Decision]``.
- :class:`MultiOrgAttestationReplicationMetrics` —
  ten-counter dataclass; the replicator updates it in-place across
  bootstrap + live-tail.
- :class:`MultiOrgAttestationWatchEvent`,
  :class:`MultiOrgAttestationWatchOp`,
  :func:`open_watch_stream`,
  :class:`MultiOrgAttestationCasConflict`,
  :class:`MultiOrgAttestationMonotonicConflict`,
  :class:`MultiOrgAttestationEnvelopeError`.

The Tag-2 ``MultiOrgAttestationReplicationMetrics`` dataclass
already carries every counter the live-tail needs
(``events_applied_put``, ``events_applied_delete``,
``events_skipped_by_filter``, ``cas_conflicts``,
``monotonic_breaches``, ``envelope_errors``); the Tag-6 replicator
populates those during the watch-stream loop while the bootstrap
pass already populates the ``bootstrap_*`` counters.

Resume-from-revision (Tag-6 surface)
------------------------------------

The replicator tracks the highest revision observed on the live
tail in the additive :attr:`MultiOrgAttestationReplicator.last_revision`
field. This counter is the **resume signal** for operator-side
tooling: on a crash-restart, an operator can read the persisted
``last_revision`` and (in Phase-3) pass it back as a resume cursor
to ``watch(..., resume_from=...)``. Tag-6 itself does NOT bake the
resume cursor into the watch-stream open call — that requires
nats-py adapter support which we keep out of scope for the
90-min Tag-6 budget (mirror of the Sprint-6 Tag-6 capability-
policy replicator's Phase-3-reserved resume semantics). The
Tag-6 replicator's contract is therefore:

- ``last_revision`` advances monotonically across every observed
  live-tail event (PUT, DELETE, PURGE — applied or filtered).
  Bootstrap-pass revisions are NOT reflected (the bootstrap pass
  reads via ``snapshot`` + ``list_keys`` + ``get_with_revision``,
  which surface per-record revisions but NOT a stream-level
  high-water-mark; resume from a partial bootstrap is structurally
  always a full re-bootstrap, which the bootstrap pass treats as
  idempotent).
- ``last_revision`` is observable via the public attribute;
  operators wire it through to whatever persistence shape they
  prefer (typically a sibling KV slot or a sidecar journal).
- A re-issue of :meth:`run` on the same replicator instance does
  NOT reset ``last_revision``; operators that want a clean restart
  construct a fresh replicator.

Halt policy
-----------

The replicator surfaces three halt flags (each defaulting to a
"continue and count" posture, mirror of the Sprint-6 Tag-6
capability-policy replicator):

- ``halt_on_envelope_error`` (default ``True``): a poisoned
  source-side envelope terminates :meth:`run` with the
  :class:`MultiOrgAttestationEnvelopeError` re-raised. The
  ``envelope_errors`` counter advances first.
- ``halt_on_cas_conflict`` (default ``False``): under ``CAS_PIN``
  policy, a CAS conflict terminates :meth:`run` with the
  :class:`MultiOrgAttestationCasConflict` re-raised. Counter
  ``cas_conflicts`` advances first.
- ``halt_on_monotonic_breach`` (default ``False``): a
  monotonic-invariant breach under either policy terminates
  :meth:`run` with the
  :class:`MultiOrgAttestationMonotonicConflict` re-raised. Counter
  ``monotonic_breaches`` advances first.

The "continue and count" defaults mean the replicator does NOT
crash on a hostile or misconfigured peer-side stream by default;
operators observe failures via the metrics counter and decide the
response asynchronously. Aggressive operators flip the halt flag
to ``True`` for the relevant counter and let the supervisor
restart the replicator.

Determinism contract
--------------------

- A bootstrap-only run (``run(bootstrap=True)`` with a watch-stream
  that terminates immediately) leaves the target's keyset
  byte-equal to the source's keyset (modulo filter rejections),
  identical to a direct call to
  :func:`bootstrap_multi_org_attestation_target_from_source`.
- A live-tail-only run (``run(bootstrap=False)`` on a target that
  was pre-bootstrapped) applies every observed event to the
  target via the configured conflict policy. Filtered-out events
  are observed and counted but not applied.
- A re-issue of :meth:`run` on the same instance composes a fresh
  bootstrap pass (unless suppressed) and a fresh watch-stream;
  ``last_revision`` carries over (operators that want a clean
  resume construct a new replicator).

Phase-2 boundary (NOT in Tag-6)
-------------------------------

The replicator does NOT implement:

- **Bidirectional replication.** Tag-6 is one-way (source →
  target). Bidirectional replication requires conflict-free
  CRDT-style merges and is out of scope for Phase-2.
- **Multi-source fan-in.** Tag-6 has exactly one source backend
  and one target backend per replicator instance.
- **Watch-stream resume-from-revision wire-up.** The cursor is
  tracked but not consumed by the open-call (Phase-3 enhancement
  with nats-py adapter support).
- **Token-level capability-token-burst propagation.** The
  replicator carries **attestation-level** records (the
  authority-gesture envelope). Biscuit v3 token-level revocation-
  list propagation is a Phase-3 Datalog-substrate slot.

Cross-references
----------------

- Sprint-7 Tag-2 backend module (bootstrap pass owner):
  :mod:`wirelang.federation.multi_org_attestation_nats_kv_backend`.
- Sprint-6 Tag-6 capability-policy replicator (pattern source):
  :mod:`wirelang.schemas.capability_policy_replication`.
- Sprint-7 Tag-5 :class:`UnrevokeAuditMarkerCrossOrgExporter`
  (cross-org privacy boundary on a different axis): the live-tail
  replicator MAY propagate attestations referencing peer policy
  pointers whose downstream audit-trail entries are cross-org
  exported via the Tag-5 module. The two modules compose
  orthogonally: the replicator mirrors the attestation envelope
  byte-precisely; the exporter handles the audit-trail
  pseudonymisation. No coupling is needed at the Tag-6 layer.

ADR-0050 Tool-Surface-Stempel: this file was authored using Read,
Edit, Write, Bash. No Agent-Tool, no WebFetch.

ADR-0049 Pre-Box-Worktree: ``/tmp/reza-sprint-7-tag-6-runtime``
with ``-runtime`` suffix from Tag-5-Tip ``d0669f9``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from .multi_org_attestation_nats_kv_backend import (
    MultiOrgAttestationCasConflict,
    MultiOrgAttestationEnvelopeError,
    MultiOrgAttestationMonotonicConflict,
    MultiOrgAttestationReplicationConflictPolicy,
    MultiOrgAttestationReplicationDecision,
    MultiOrgAttestationReplicationFilter,
    MultiOrgAttestationReplicationMetrics,
    MultiOrgAttestationWatchEvent,
    MultiOrgAttestationWatchOp,
    NatsKvMultiOrgAttestationRegistry,
    _accept_all_attestation,
    bootstrap_multi_org_attestation_target_from_source,
    open_watch_stream,
)


# ---------------------------------------------------------------------------
# Sprint-9 Tag-3 Teil B — detect_replay-callsite-mirror hook
# ---------------------------------------------------------------------------
#
# The replicator's primary payload is the multi-org-attestation envelope
# (an authority-gesture, not a capability-event payload). Sprint-9 Tag-1
# shipped the symmetric :func:`detect_replay` gate for
# :class:`ExportedCaveatOverrideEvent` envelopes; the durable
# :class:`NatsKvSequenceNumberLedger` (Sprint-9 Tag-2) lets a downstream
# verifier persist per-pair last-seen sequence numbers cross-process.
#
# The live-tail replicator's contribution to that gate is **structural,
# not semantic**: the replicator is the single chokepoint a hostile
# cross-org event must traverse before reaching the target bucket.
# If we wire a replay-detector hook *before* the apply step, every
# replicator deployment trivially inherits the same replay-protection
# guarantee that an in-band verifier would assert on each consumer side.
#
# Hook contract
# -------------
#
# ``ReplayDetectorFn`` is a callable
# ``(event) -> ReplayDetectorDecision`` invoked AFTER the filter and
# BEFORE the apply step. If the decision is ``REPLAY``, the event is
# dropped (no PUT/DELETE on the target) and the per-org replay-drop
# counter advances. If the decision is ``PASS_THROUGH``, the replicator
# routes the event normally.
#
# The hook is operator-supplied. The default no-op implementation
# (:func:`_default_pass_through`) is wired when ``replay_detector_fn``
# is unset; with the default, the replicator's behaviour is
# byte-identical to Sprint-7 Tag-6.
#
# The hook signature receives the watch event (not a token-burst
# payload) because the replicator's stream carries the attestation
# envelope. Operators who want to wire :func:`detect_replay` for
# CaveatOverrideExport-events on the same cross-org channel build a
# thin shim that extracts the relevant route_id / chain_hash /
# sequence triple from the event surface and delegates to their
# verifier-side ledger; the replicator-side hook gives them a single
# attachment point.


from enum import Enum


class ReplayDetectorDecision(str, Enum):
    """Two-valued decision for the replay-detector hook.

    - ``PASS_THROUGH``: the event is not a replay; the replicator
      routes it normally through the conflict policy.
    - ``REPLAY``: the event is a known replay; the replicator drops
      it (no target-side write) and advances the per-org replay-drop
      counter.

    The hook MAY also raise an exception to halt the replicator;
    that path surfaces via the underlying try/except in
    :meth:`MultiOrgAttestationReplicator._consume_event` and respects
    the operator's halt policy.
    """

    PASS_THROUGH = "pass_through"
    REPLAY = "replay"


ReplayDetectorFn = Callable[
    [MultiOrgAttestationWatchEvent], ReplayDetectorDecision
]


def _default_pass_through(
    event: MultiOrgAttestationWatchEvent,
) -> ReplayDetectorDecision:
    """Default no-op replay detector: every event passes through.

    With the default, the replicator's behaviour is byte-identical
    to Sprint-7 Tag-6 (no replay-protection layer). Operators wire
    their own detector for the cross-org capability-event stream.
    """
    return ReplayDetectorDecision.PASS_THROUGH


__all__ = [
    "MultiOrgAttestationReplicator",
    "ReplayDetectorDecision",
    "ReplayDetectorFn",
]


@dataclass
class MultiOrgAttestationReplicator:
    """One-way multi-org-attestation replicator (source → target).

    Composes the Sprint-7 Tag-2 :func:`bootstrap_multi_org_attestation_
    target_from_source` (initial sync) and the Sprint-7 Tag-2
    :func:`open_watch_stream` (continuous live tail) into a single
    one-way replicator. Pattern-mirror on the Sprint-6 Tag-6
    capability-policy replicator at
    :class:`~wirelang.schemas.capability_policy_replication.CapabilityPolicyReplicator`.

    Construction is cheap: the replicator performs no I/O until
    :meth:`run` is awaited. The caller is responsible for opening the
    underlying NATS KV handles on both backends; the replicator does
    not establish NATS connections itself.

    Conflict policy
    ---------------

    - :attr:`MultiOrgAttestationReplicationConflictPolicy.SOURCE_WINS`
      (default): target writes go through
      :meth:`NatsKvMultiOrgAttestationRegistry.put` (LWW). The
      monotonic-invariant gate runs in-band on every write
      (Sprint-7 Tag-2 backend contract); a breach surfaces as
      :class:`MultiOrgAttestationMonotonicConflict`, the
      ``monotonic_breaches`` counter advances, and the replicator
      continues (or re-raises if ``halt_on_monotonic_breach`` is
      set).
    - :attr:`MultiOrgAttestationReplicationConflictPolicy.CAS_PIN`:
      target writes go through
      :meth:`NatsKvMultiOrgAttestationRegistry.put_with_revision`
      against the target's currently-observed revision (read via
      :meth:`NatsKvMultiOrgAttestationRegistry.get_with_revision`
      just before the write). The Tag-2 backend gate ordering runs
      the monotonic-invariant check BEFORE the CAS-pin check, so a
      revoked-authority race cannot sneak in via a stale-revision
      window. A CAS conflict (concurrent target-side mutation)
      surfaces as :class:`MultiOrgAttestationCasConflict`, advances
      the ``cas_conflicts`` counter, and the replicator continues by
      default.

    Filter
    ------

    The optional ``filter_fn`` is invoked on every observed event
    (bootstrap synthetic events AND live tail events alike). A
    ``SKIP`` decision means the event is NOT applied to the target;
    the relevant ``*_skipped_by_filter`` counter advances.

    Halt policy
    -----------

    All three halt flags default to "continue and count" so a noisy
    or hostile source stream does NOT crash the replicator:

    - ``halt_on_envelope_error`` (default ``True``): re-raise on
      first envelope poison.
    - ``halt_on_cas_conflict`` (default ``False``): re-raise on
      first CAS conflict (CAS_PIN policy only).
    - ``halt_on_monotonic_breach`` (default ``False``): re-raise on
      first monotonic-invariant breach.

    Stop policy
    -----------

    The replicator runs until the source watch-stream terminates
    (``StopAsyncIteration``) or an unhandled exception bubbles up.
    Operators that want a finite run pass a watch-stream that itself
    terminates; production operators run :meth:`run` inside an
    asyncio task they cancel on shutdown.

    Resume cursor
    -------------

    :attr:`last_revision` tracks the highest revision observed on
    the live tail. Operators that want a crash-restart resume cursor
    read this value (typically through a sidecar journal) and re-bake
    it into their resume-from-revision policy. Tag-6 does NOT wire
    the cursor back into the watch-stream open call; that is a
    Phase-3 enhancement.
    """

    source: NatsKvMultiOrgAttestationRegistry
    target: NatsKvMultiOrgAttestationRegistry
    conflict_policy: MultiOrgAttestationReplicationConflictPolicy = (
        MultiOrgAttestationReplicationConflictPolicy.SOURCE_WINS
    )
    filter_fn: Optional[MultiOrgAttestationReplicationFilter] = None
    halt_on_envelope_error: bool = True
    halt_on_cas_conflict: bool = False
    halt_on_monotonic_breach: bool = False
    metrics: MultiOrgAttestationReplicationMetrics = field(
        default_factory=MultiOrgAttestationReplicationMetrics
    )
    last_revision: int = 0

    # Sprint-9 Tag-3 Teil B — detect_replay-callsite-mirror.
    # Operator-supplied hook invoked AFTER the filter and BEFORE the
    # apply step. Default: no-op pass-through (byte-identical to
    # Sprint-7 Tag-6). See module docstring for the contract.
    replay_detector_fn: ReplayDetectorFn = field(
        default=_default_pass_through
    )
    # Per-org replay-drop counter (Sprint-9 Tag-3 Teil B). The
    # replicator carries one bucket per peer ``org_id`` it has
    # observed on the live tail; the ``org_id`` is sourced from the
    # event's :attr:`MultiOrgAttestationWatchEvent.attestation.
    # peer_trust_domain` (the peer's trust-domain id; "org-id" in the
    # cross-org-federation taxonomy). DELETE / PURGE events whose
    # attestation has already been removed lack a peer_trust_domain
    # surface; for those events the counter falls back to the
    # synthetic key ``"<unknown>"``.
    replay_drops_per_org: Dict[str, int] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.source, NatsKvMultiOrgAttestationRegistry
        ):
            raise TypeError(
                "source must be a NatsKvMultiOrgAttestationRegistry"
            )
        if not isinstance(
            self.target, NatsKvMultiOrgAttestationRegistry
        ):
            raise TypeError(
                "target must be a NatsKvMultiOrgAttestationRegistry"
            )
        if self.source is self.target:
            raise ValueError(
                "source and target must be distinct backends "
                "(self-replication is not supported)"
            )
        if not isinstance(
            self.conflict_policy,
            MultiOrgAttestationReplicationConflictPolicy,
        ):
            raise TypeError(
                "conflict_policy must be a "
                "MultiOrgAttestationReplicationConflictPolicy, "
                f"got {type(self.conflict_policy).__name__}"
            )
        if self.filter_fn is None:
            self.filter_fn = _accept_all_attestation

    async def bootstrap(
        self,
    ) -> MultiOrgAttestationReplicationMetrics:
        """Run the one-shot bootstrap pass via the Tag-2 helper.

        Convenience method that delegates to
        :func:`bootstrap_multi_org_attestation_target_from_source`
        with the replicator's configured policy, filter, and shared
        metrics object. Updates :attr:`metrics` in-place.
        """
        return await bootstrap_multi_org_attestation_target_from_source(
            source=self.source,
            target=self.target,
            policy=self.conflict_policy,
            filter_fn=self.filter_fn,
            metrics=self.metrics,
        )

    async def _apply_put(
        self, event: MultiOrgAttestationWatchEvent
    ) -> None:
        """Apply a PUT event to the target via the conflict policy.

        Routes through :meth:`NatsKvMultiOrgAttestationRegistry.put`
        (SOURCE_WINS) or
        :meth:`NatsKvMultiOrgAttestationRegistry.put_with_revision`
        (CAS_PIN). The Tag-2 backend's monotonic-invariant gate runs
        in-band on either path; a breach raises
        :class:`MultiOrgAttestationMonotonicConflict`. CAS conflicts
        surface only under CAS_PIN.
        """
        if event.attestation is None:
            raise MultiOrgAttestationEnvelopeError(
                "PUT MultiOrgAttestationWatchEvent must carry a "
                f"non-None attestation; route_id={event.route_id!r}"
            )
        try:
            if (
                self.conflict_policy
                is MultiOrgAttestationReplicationConflictPolicy.CAS_PIN
            ):
                existing = await self.target.get_with_revision(
                    event.route_id
                )
                if existing is None:
                    await self.target.put(event.attestation)
                else:
                    _, observed_revision = existing
                    await self.target.put_with_revision(
                        event.attestation, observed_revision
                    )
            else:
                await self.target.put(event.attestation)
            self.metrics.events_applied_put += 1
        except MultiOrgAttestationMonotonicConflict:
            self.metrics.monotonic_breaches += 1
            if self.halt_on_monotonic_breach:
                raise
        except MultiOrgAttestationCasConflict:
            self.metrics.cas_conflicts += 1
            if self.halt_on_cas_conflict:
                raise

    async def _apply_delete(
        self, event: MultiOrgAttestationWatchEvent
    ) -> None:
        """Apply a DELETE / PURGE event to the target.

        Backend ``delete`` is a no-op if the key is already absent.
        The operator's intent is that the target reflects the
        absence; that intent is honoured regardless of the live
        target state. Counter advances on every DELETE / PURGE
        observation (apply succeeded by no-op semantics).
        """
        await self.target.delete(event.route_id)
        self.metrics.events_applied_delete += 1

    async def _consume_event(
        self, event: MultiOrgAttestationWatchEvent
    ) -> None:
        """Filter + replay-detect + route one event.

        Updates :attr:`last_revision` for every observed event
        (filter accept and filter reject alike). The resume cursor
        is a stream-level high-water mark, NOT a target-write mark.

        Sprint-9 Tag-3 Teil B: between the filter and the apply
        step, the operator-supplied :attr:`replay_detector_fn` is
        invoked. A ``REPLAY`` decision drops the event (no target
        write) and advances the per-org replay-drop counter; a
        ``PASS_THROUGH`` decision routes normally.
        """
        if event.revision > self.last_revision:
            self.last_revision = event.revision
        decision = self.filter_fn(event)
        if not isinstance(
            decision, MultiOrgAttestationReplicationDecision
        ):
            raise TypeError(
                "filter_fn must return a "
                "MultiOrgAttestationReplicationDecision, got "
                f"{type(decision).__name__}"
            )
        if (
            decision
            is MultiOrgAttestationReplicationDecision.SKIP
        ):
            self.metrics.events_skipped_by_filter += 1
            return

        # Sprint-9 Tag-3 Teil B — replay-detector hook.
        replay_decision = self.replay_detector_fn(event)
        if not isinstance(
            replay_decision, ReplayDetectorDecision
        ):
            raise TypeError(
                "replay_detector_fn must return a "
                "ReplayDetectorDecision, got "
                f"{type(replay_decision).__name__}"
            )
        if replay_decision is ReplayDetectorDecision.REPLAY:
            self._record_replay_drop(event)
            return

        if event.op is MultiOrgAttestationWatchOp.PUT:
            await self._apply_put(event)
        else:
            # DELETE / PURGE: same target-side action (the bucket
            # state on the target reflects the source's absence).
            await self._apply_delete(event)

    def _record_replay_drop(
        self, event: MultiOrgAttestationWatchEvent
    ) -> None:
        """Advance the per-org replay-drop counter for ``event``.

        Sourcing the ``org_id``:

        - For PUT events the peer trust-domain is available on
          :attr:`event.attestation.peer_trust_domain`.
        - For DELETE / PURGE events the attestation surface MAY be
          ``None`` (the source bucket no longer carries it); the
          counter falls back to the synthetic ``"<unknown>"`` key.

        The replay-drop counter is purely informational and not
        load-bearing for replay-protection itself; the protection
        is the missing target-side write. The counter exists so
        operators can observe replay activity per peer.
        """
        org_id: Optional[str] = None
        att = event.attestation
        if att is not None:
            org_id = getattr(att, "peer_trust_domain", None)
        key = org_id if org_id else "<unknown>"
        self.replay_drops_per_org[key] = (
            self.replay_drops_per_org.get(key, 0) + 1
        )

    @property
    def total_replay_drops(self) -> int:
        """Sum of replay-drop counters across all observed peers.

        Convenience accessor for operators that only care about the
        global drop count (e.g. a Prometheus gauge).
        """
        return sum(self.replay_drops_per_org.values())

    async def run(
        self, *, bootstrap: bool = True
    ) -> MultiOrgAttestationReplicationMetrics:
        """Run the replicator: bootstrap, then consume the watch-stream.

        Args:
            bootstrap: if ``True`` (default), run the bootstrap pass
                before opening the watch-stream. Operators who have
                already bootstrapped the target can pass ``False``.

        Returns:
            The replicator's :attr:`metrics` object (same instance
            as :attr:`metrics`; the caller may discard or persist).

        Raises:
            MultiOrgAttestationEnvelopeError: a poisoned envelope on
                the source watch-stream (under default
                ``halt_on_envelope_error=True``). The metrics
                counter ``envelope_errors`` is incremented before
                re-raise.
            MultiOrgAttestationCasConflict: a target-side CAS
                conflict (under ``CAS_PIN`` policy with
                ``halt_on_cas_conflict=True``).
            MultiOrgAttestationMonotonicConflict: a target-side
                monotonic-invariant breach (under either policy
                with ``halt_on_monotonic_breach=True``).
        """
        if bootstrap:
            await self.bootstrap()

        stream = await open_watch_stream(self.source)
        try:
            async for event in stream:
                try:
                    await self._consume_event(event)
                except MultiOrgAttestationEnvelopeError:
                    self.metrics.envelope_errors += 1
                    if self.halt_on_envelope_error:
                        raise
        except MultiOrgAttestationEnvelopeError:
            # The decoder inside the stream itself raised; the
            # iterator has terminated. Surface the failure if the
            # halt policy demands it; otherwise swallow and return.
            self.metrics.envelope_errors += 1
            if self.halt_on_envelope_error:
                raise
        finally:
            await stream.__aexit__(None, None, None)

        return self.metrics
