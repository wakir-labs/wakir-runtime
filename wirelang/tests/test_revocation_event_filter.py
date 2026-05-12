# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the capability-policy revocation-event-filter
surface (Phase-2 Sprint-6 Tag-3, consumer-side symmetry to Sprint-6
Tag-1 backend revocation-axis).

Tested surfaces on
:mod:`wirelang.schemas.capability_policy_nats_kv_backend`:

- :class:`RevocationEventKind` (6 enum members — Sprint-6 Tag-9 added
  ``EXPLICIT_UNREVOKE``)
- :class:`ClassifiedRevocationEvent` (frozen dataclass)
- :class:`RevocationEventClassifier` (stateful classifier; Sprint-6
  Tag-9 extended with operator-deliberate-unrevoke marker logic)
- :class:`UnrevokeAuditMarker` (Sprint-6 Tag-9, attached to the
  envelope by the publisher-CLI ``unrevoke`` subcommand)
- :func:`filter_revocation_events` (async generator; Sprint-6 Tag-9
  default kinds set extended with ``EXPLICIT_UNREVOKE``)

The consumer-side surface mirrors the Sprint-6 Tag-1 backend write
invariants: once a key is revoked, subsequent PUTs MUST preserve
``revoked_at`` byte-equally; an apparent un-revoke or an advanced /
retreated ``revoked_at`` is a witness of substrate corruption or
out-of-band tampering and surfaces as REVOCATION_MONOTONIC_BREACH.
The classifier is an observation layer, not an enforcement layer:
it surfaces the kind for the consumer to act on, it does not raise
on breach.

Test inventory (T-CPP-REVF-01..12 from Sprint-6 Tag-3, T-CPP-REVF-13..19
added Sprint-6 Tag-9 + 2 aux probes):

- T-CPP-REVF-01: classify(PUT, no-prior, revoked_at=None)
  -> NOT_REVOCATION_RELATED.
- T-CPP-REVF-02: classify(PUT, no-prior, revoked_at=set)
  -> REVOCATION_TRANSITION.
- T-CPP-REVF-03: classify(PUT, prior-unrevoked, revoked_at=set)
  -> REVOCATION_TRANSITION (the un-revoked -> revoked transition).
- T-CPP-REVF-04: classify(PUT, prior-revoked, same revoked_at,
  different revocation_reason) -> REVOCATION_REFRESH.
- T-CPP-REVF-05: classify(PUT, prior-revoked, revoked_at=None)
  -> REVOCATION_MONOTONIC_BREACH (apparent un-revoke, no marker).
- T-CPP-REVF-06: classify(PUT, prior-revoked, different revoked_at)
  -> REVOCATION_MONOTONIC_BREACH (advance/retreat).
- T-CPP-REVF-07: classify(DELETE, any prior) -> KEY_REMOVED;
  classifier drops the key from its map (re-introduction via PUT is
  classified against fresh no-prior).
- T-CPP-REVF-08: classify(PURGE, any prior) -> KEY_REMOVED (parallel
  to DELETE).
- T-CPP-REVF-09: seed_from_records(...) primes the classifier's state;
  subsequent PUT with same revoked_at is REVOCATION_REFRESH (no
  unwarranted TRANSITION on first event for a seeded key).
- T-CPP-REVF-10: classify(PUT, prior=None, key_had_prior_state=True)
  -> prior_revoked_at field is None AND prior_state was present
  (regression check: the prior_revoked_at field encodes value, not
  presence; classifier-internal membership is tracked separately).
- T-CPP-REVF-11: classify rejects non-CapabilityPolicyWatchEvent input
  with TypeError.
- T-CPP-REVF-12: classify(PUT) with record=None raises
  CapabilityPolicyEnvelopeError (defensive invariant; would not
  normally occur because the decoder rejects it earlier).
- T-CPP-REVF-13 (Sprint-6 Tag-9, positive): classify(PUT, prior-
  revoked X, revoked_at=None, marker.previous_revoked_at=X) ->
  EXPLICIT_UNREVOKE (operator-deliberate gesture authenticated by
  the matching marker; classifier advances per-key state to None).
- T-CPP-REVF-14 (Sprint-6 Tag-9, negative — mismatched marker):
  classify(PUT, prior-revoked X, revoked_at=None,
  marker.previous_revoked_at=Y != X) -> REVOCATION_MONOTONIC_BREACH
  (marker references a prior instant the classifier never observed;
  cannot authenticate the gesture; falls through to BREACH).
- T-CPP-REVF-15 (Sprint-6 Tag-9, negative — no marker):
  classify(PUT, prior-revoked, revoked_at=None, marker=None) ->
  REVOCATION_MONOTONIC_BREACH (unmarked unrevoke is structurally
  indistinguishable from out-of-band tampering; the louder kind
  wins by safe default — preserves Sprint-6 Tag-3 T-CPP-REVF-05).
- T-CPP-REVF-16 (Sprint-6 Tag-9, marker ignored on non-unrevoke
  shape): CapabilityPolicyRecord constructor rejects a marker on a
  still-revoked policy (revoked_at != None + marker -> validation
  error), so the marker is structurally suppressed on
  REVOCATION_REFRESH / REVOCATION_TRANSITION shapes.
- T-CPP-REVF-17 (Sprint-6 Tag-9, default kinds include
  EXPLICIT_UNREVOKE): filter_revocation_events with kinds=None
  surfaces EXPLICIT_UNREVOKE alongside TRANSITION / REFRESH /
  BREACH; NOT_REVOCATION_RELATED and KEY_REMOVED still filtered.
- T-CPP-REVF-18 (Sprint-6 Tag-9, envelope round-trip with marker):
  _record_to_envelope / _envelope_to_record preserve the
  unrevoke_audit_marker byte-equally.
- T-CPP-REVF-19 (Sprint-6 Tag-9, envelope back-compat):
  _envelope_to_record on a pre-Tag-9 envelope (no
  unrevoke_audit_marker key) decodes byte-equally with
  unrevoke_audit_marker=None.
- T-CPP-REVF-aux-async-gen: filter_revocation_events yields only
  matching kinds; classifier sees every event (state stays
  consistent across yielded / non-yielded events).
- T-CPP-REVF-aux-type-rejection: filter_revocation_events rejects
  non-classifier and non-frozenset arguments with TypeError.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional, Tuple

import pytest

from wirelang.schemas.capability_policy_nats_kv_backend import (
    CapabilityPolicyEnvelopeError,
    CapabilityPolicyRecord,
    CapabilityPolicyValidationError,
    CapabilityPolicyWatchEvent,
    CapabilityPolicyWatchOp,
    ClassifiedRevocationEvent,
    RevocationEventClassifier,
    RevocationEventKind,
    UnrevokeAuditMarker,
    _envelope_to_record,
    _record_to_envelope,
    filter_revocation_events,
    key_for_policy_pair,
)
from wirelang.schemas.registered_by_capability import CapabilityPolicy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_REGISTERED_AT = datetime(2026, 5, 11, 22, 0, 0, tzinfo=timezone.utc)
_REVOKED_AT_A = datetime(2026, 5, 11, 22, 30, 0, tzinfo=timezone.utc)
_REVOKED_AT_B = datetime(2026, 5, 11, 23, 0, 0, tzinfo=timezone.utc)


def _make_policy(
    *,
    registered_by: str = "wirelang-eng",
    revoked_at: Optional[datetime] = None,
    revocation_reason: Optional[str] = None,
) -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=("biscuit-root-1",),
        allowed_triples=(("wire", "layer-1-*"),),
        revoked_at=revoked_at,
        revocation_reason=revocation_reason,
    )


def _make_record(
    *,
    registered_by: str = "wirelang-eng",
    policy_id: str = "policy-A",
    revoked_at: Optional[datetime] = None,
    revocation_reason: Optional[str] = None,
    unrevoke_audit_marker: Optional[UnrevokeAuditMarker] = None,
) -> CapabilityPolicyRecord:
    return CapabilityPolicyRecord(
        policy=_make_policy(
            registered_by=registered_by,
            revoked_at=revoked_at,
            revocation_reason=revocation_reason,
        ),
        policy_id=policy_id,
        registered_by_publisher="wirelang-eng",
        registered_at=_REGISTERED_AT,
        unrevoke_audit_marker=unrevoke_audit_marker,
    )


def _put_event(
    record: CapabilityPolicyRecord, revision: int = 1
) -> CapabilityPolicyWatchEvent:
    return CapabilityPolicyWatchEvent(
        op=CapabilityPolicyWatchOp.PUT,
        key=record.key,
        record=record,
        revision=revision,
    )


def _delete_event(
    key: str, revision: int = 2
) -> CapabilityPolicyWatchEvent:
    return CapabilityPolicyWatchEvent(
        op=CapabilityPolicyWatchOp.DELETE,
        key=key,
        record=None,
        revision=revision,
    )


def _purge_event(
    key: str, revision: int = 2
) -> CapabilityPolicyWatchEvent:
    return CapabilityPolicyWatchEvent(
        op=CapabilityPolicyWatchOp.PURGE,
        key=key,
        record=None,
        revision=revision,
    )


# ---------------------------------------------------------------------------
# Core classifier tests (T-CPP-REVF-01..12)
# ---------------------------------------------------------------------------


def test_classify_put_no_prior_no_revoke_is_not_revocation_related():
    """T-CPP-REVF-01: PUT, no-prior, revoked_at=None
    -> NOT_REVOCATION_RELATED.
    """
    classifier = RevocationEventClassifier()
    record = _make_record(revoked_at=None)
    classified = classifier.classify(_put_event(record))

    assert classified.kind is RevocationEventKind.NOT_REVOCATION_RELATED
    assert classified.prior_revoked_at is None
    assert classified.current_revoked_at is None
    assert classified.current_revocation_reason is None
    # State map advanced: key is now known with revoked_at=None.
    assert classifier.known_keys() == [record.key]
    assert classifier.last_revoked_at(record.key) is None


def test_classify_put_no_prior_with_revoke_is_transition():
    """T-CPP-REVF-02: PUT, no-prior, revoked_at=set
    -> REVOCATION_TRANSITION.
    """
    classifier = RevocationEventClassifier()
    record = _make_record(
        revoked_at=_REVOKED_AT_A, revocation_reason="rotated key"
    )
    classified = classifier.classify(_put_event(record))

    assert classified.kind is RevocationEventKind.REVOCATION_TRANSITION
    assert classified.prior_revoked_at is None
    assert classified.current_revoked_at == _REVOKED_AT_A
    assert classified.current_revocation_reason == "rotated key"
    # State map: key now revoked at _REVOKED_AT_A.
    assert classifier.last_revoked_at(record.key) == _REVOKED_AT_A


def test_classify_put_prior_unrevoked_to_revoked_is_transition():
    """T-CPP-REVF-03: PUT, prior-unrevoked, revoked_at=set
    -> REVOCATION_TRANSITION (the unrevoked -> revoked moment).
    """
    classifier = RevocationEventClassifier()
    record_unrevoked = _make_record(revoked_at=None)
    classifier.classify(_put_event(record_unrevoked, revision=1))

    record_revoked = _make_record(
        revoked_at=_REVOKED_AT_A,
        revocation_reason="compromise audit triggered",
    )
    classified = classifier.classify(_put_event(record_revoked, revision=2))

    assert classified.kind is RevocationEventKind.REVOCATION_TRANSITION
    assert classified.prior_revoked_at is None
    assert classified.current_revoked_at == _REVOKED_AT_A
    assert (
        classified.current_revocation_reason
        == "compromise audit triggered"
    )


def test_classify_put_prior_revoked_same_revoked_at_is_refresh():
    """T-CPP-REVF-04: PUT, prior-revoked, same revoked_at, different
    revocation_reason -> REVOCATION_REFRESH.
    """
    classifier = RevocationEventClassifier()
    record_first = _make_record(
        revoked_at=_REVOKED_AT_A, revocation_reason="initial reason"
    )
    classifier.classify(_put_event(record_first, revision=1))

    record_refresh = _make_record(
        revoked_at=_REVOKED_AT_A,
        revocation_reason="augmented audit context",
    )
    classified = classifier.classify(_put_event(record_refresh, revision=2))

    assert classified.kind is RevocationEventKind.REVOCATION_REFRESH
    assert classified.prior_revoked_at == _REVOKED_AT_A
    assert classified.current_revoked_at == _REVOKED_AT_A
    assert (
        classified.current_revocation_reason
        == "augmented audit context"
    )


def test_classify_put_prior_revoked_to_none_is_monotonic_breach():
    """T-CPP-REVF-05: PUT, prior-revoked, revoked_at=None
    -> REVOCATION_MONOTONIC_BREACH (apparent un-revoke).

    Backend invariants from Sprint-6 Tag-1 forbid this write; observing
    it on the watch-stream is a witness of substrate corruption or
    out-of-band tampering. The classifier surfaces the kind without
    raising.
    """
    classifier = RevocationEventClassifier()
    record_revoked = _make_record(revoked_at=_REVOKED_AT_A)
    classifier.classify(_put_event(record_revoked, revision=1))

    record_unrevoke_attempt = _make_record(revoked_at=None)
    classified = classifier.classify(
        _put_event(record_unrevoke_attempt, revision=2)
    )

    assert (
        classified.kind
        is RevocationEventKind.REVOCATION_MONOTONIC_BREACH
    )
    assert classified.prior_revoked_at == _REVOKED_AT_A
    assert classified.current_revoked_at is None
    # State map: classifier accepted the new state (it observes, does
    # not enforce). Downstream consumers decide what to do.
    assert classifier.last_revoked_at(record_revoked.key) is None


def test_classify_put_prior_revoked_different_revoked_at_is_breach():
    """T-CPP-REVF-06: PUT, prior-revoked, different revoked_at
    -> REVOCATION_MONOTONIC_BREACH (advance or retreat).

    Both advance (revoked_at strictly later than prior) and retreat
    (revoked_at strictly earlier than prior) are forbidden by Sprint-6
    Tag-1 backend invariants. The classifier treats them
    identically: any non-equal incoming revoked_at against a prior
    revocation is a breach.
    """
    classifier = RevocationEventClassifier()

    # Advance case.
    record_first = _make_record(
        registered_by="advance-issuer",
        policy_id="adv-A",
        revoked_at=_REVOKED_AT_A,
    )
    classifier.classify(_put_event(record_first, revision=1))
    record_advance = _make_record(
        registered_by="advance-issuer",
        policy_id="adv-A",
        revoked_at=_REVOKED_AT_B,
    )
    classified_advance = classifier.classify(
        _put_event(record_advance, revision=2)
    )
    assert (
        classified_advance.kind
        is RevocationEventKind.REVOCATION_MONOTONIC_BREACH
    )
    assert classified_advance.prior_revoked_at == _REVOKED_AT_A
    assert classified_advance.current_revoked_at == _REVOKED_AT_B

    # Retreat case (different key to isolate state).
    classifier2 = RevocationEventClassifier()
    record_first_b = _make_record(
        registered_by="retreat-issuer",
        policy_id="ret-A",
        revoked_at=_REVOKED_AT_B,
    )
    classifier2.classify(_put_event(record_first_b, revision=1))
    record_retreat = _make_record(
        registered_by="retreat-issuer",
        policy_id="ret-A",
        revoked_at=_REVOKED_AT_A,
    )
    classified_retreat = classifier2.classify(
        _put_event(record_retreat, revision=2)
    )
    assert (
        classified_retreat.kind
        is RevocationEventKind.REVOCATION_MONOTONIC_BREACH
    )
    assert classified_retreat.prior_revoked_at == _REVOKED_AT_B
    assert classified_retreat.current_revoked_at == _REVOKED_AT_A


def test_classify_delete_drops_key_and_resets_lineage():
    """T-CPP-REVF-07: classify(DELETE, any prior) -> KEY_REMOVED;
    classifier drops the key. Subsequent PUT for the same key is
    classified against fresh no-prior state.
    """
    classifier = RevocationEventClassifier()
    record_revoked = _make_record(revoked_at=_REVOKED_AT_A)
    classifier.classify(_put_event(record_revoked, revision=1))
    assert classifier.last_revoked_at(record_revoked.key) == _REVOKED_AT_A

    delete_classified = classifier.classify(
        _delete_event(record_revoked.key, revision=2)
    )
    assert delete_classified.kind is RevocationEventKind.KEY_REMOVED
    assert delete_classified.prior_revoked_at == _REVOKED_AT_A
    assert delete_classified.current_revoked_at is None
    # Key dropped from classifier map.
    assert record_revoked.key not in classifier.known_keys()
    assert classifier.last_revoked_at(record_revoked.key) is None

    # Re-introduction: PUT against the same key now sees fresh no-prior.
    # A revoked record is classified as TRANSITION (not REFRESH or
    # BREACH) because the lineage was severed.
    record_reintro = _make_record(revoked_at=_REVOKED_AT_B)
    re_classified = classifier.classify(
        _put_event(record_reintro, revision=3)
    )
    assert re_classified.kind is RevocationEventKind.REVOCATION_TRANSITION
    assert re_classified.prior_revoked_at is None
    assert re_classified.current_revoked_at == _REVOKED_AT_B


def test_classify_purge_drops_key_like_delete():
    """T-CPP-REVF-08: classify(PURGE, any prior) -> KEY_REMOVED
    (parallel to DELETE).
    """
    classifier = RevocationEventClassifier()
    record_revoked = _make_record(revoked_at=_REVOKED_AT_A)
    classifier.classify(_put_event(record_revoked, revision=1))

    purge_classified = classifier.classify(
        _purge_event(record_revoked.key, revision=2)
    )
    assert purge_classified.kind is RevocationEventKind.KEY_REMOVED
    assert purge_classified.prior_revoked_at == _REVOKED_AT_A
    assert purge_classified.current_revoked_at is None
    assert record_revoked.key not in classifier.known_keys()


def test_seed_from_records_primes_classifier_state():
    """T-CPP-REVF-09: seed_from_records(...) primes the per-key state
    map. A subsequent PUT with same revoked_at is REVOCATION_REFRESH,
    not REVOCATION_TRANSITION (the seed represents the prior state).
    """
    classifier = RevocationEventClassifier()
    seed_records = [
        _make_record(
            registered_by="seed-issuer",
            policy_id="seed-A",
            revoked_at=_REVOKED_AT_A,
            revocation_reason="seeded",
        ),
        _make_record(
            registered_by="seed-issuer",
            policy_id="seed-B",
            revoked_at=None,
        ),
    ]
    classifier.seed_from_records(seed_records)

    # Seeded keys are tracked.
    assert sorted(classifier.known_keys()) == sorted(
        [r.key for r in seed_records]
    )
    assert classifier.last_revoked_at(seed_records[0].key) == _REVOKED_AT_A
    assert classifier.last_revoked_at(seed_records[1].key) is None

    # PUT with same revoked_at -> REFRESH (not TRANSITION).
    refresh_record = _make_record(
        registered_by="seed-issuer",
        policy_id="seed-A",
        revoked_at=_REVOKED_AT_A,
        revocation_reason="post-restart audit refresh",
    )
    refresh_classified = classifier.classify(
        _put_event(refresh_record, revision=10)
    )
    assert refresh_classified.kind is RevocationEventKind.REVOCATION_REFRESH
    assert refresh_classified.prior_revoked_at == _REVOKED_AT_A

    # Seed idempotency: re-seeding with same input does not change state.
    classifier.seed_from_records(seed_records)
    # State for seed-A is now overridden BACK to _REVOKED_AT_A (the
    # seed wins; this is intentional, callers should not interleave
    # seed and classify).
    assert classifier.last_revoked_at(seed_records[0].key) == _REVOKED_AT_A


def test_seed_from_records_rejects_non_record_input():
    """T-CPP-REVF-09b (aux): seed_from_records raises on non-record
    inputs.
    """
    classifier = RevocationEventClassifier()
    with pytest.raises(CapabilityPolicyValidationError):
        classifier.seed_from_records([object()])


def test_prior_revoked_at_distinguishes_absent_from_unrevoked():
    """T-CPP-REVF-10: prior_revoked_at field encodes VALUE (None or
    instant), not membership. A key that was observed as unrevoked
    has prior_revoked_at=None on the next event; a key that was never
    observed also has prior_revoked_at=None. The classifier's
    known_keys() distinguishes the two cases.
    """
    classifier = RevocationEventClassifier()
    record_unrevoked = _make_record(revoked_at=None)
    classifier.classify(_put_event(record_unrevoked, revision=1))
    # The key is now known with revoked_at=None.
    assert record_unrevoked.key in classifier.known_keys()

    # A second event for the same key sees prior_revoked_at=None but
    # the key WAS known.
    record_unrevoked_again = _make_record(revoked_at=None)
    classified = classifier.classify(
        _put_event(record_unrevoked_again, revision=2)
    )
    assert classified.kind is RevocationEventKind.NOT_REVOCATION_RELATED
    assert classified.prior_revoked_at is None

    # Different key, never observed: prior_revoked_at=None as well.
    new_record = _make_record(
        registered_by="new-issuer",
        policy_id="new-A",
        revoked_at=None,
    )
    classified_new = classifier.classify(_put_event(new_record, revision=3))
    assert (
        classified_new.kind is RevocationEventKind.NOT_REVOCATION_RELATED
    )
    assert classified_new.prior_revoked_at is None


def test_classify_rejects_non_event_input():
    """T-CPP-REVF-11: classify rejects non-CapabilityPolicyWatchEvent
    input with TypeError.
    """
    classifier = RevocationEventClassifier()
    with pytest.raises(TypeError):
        classifier.classify(object())
    with pytest.raises(TypeError):
        classifier.classify({"op": "PUT", "key": "k", "record": None})


def test_classify_put_with_none_record_raises_envelope_error():
    """T-CPP-REVF-12: classify(PUT) with record=None raises
    CapabilityPolicyEnvelopeError. The decoder normally rejects this
    earlier; the classifier re-asserts the invariant defensively so a
    hand-built event surface does not silently classify as
    NOT_REVOCATION_RELATED.
    """
    classifier = RevocationEventClassifier()
    malformed = CapabilityPolicyWatchEvent(
        op=CapabilityPolicyWatchOp.PUT,
        key=key_for_policy_pair("issuer-x", "policy-x"),
        record=None,  # invalid for PUT
        revision=1,
    )
    with pytest.raises(CapabilityPolicyEnvelopeError):
        classifier.classify(malformed)


# ---------------------------------------------------------------------------
# filter_revocation_events async-generator tests (T-CPP-REVF-aux-*)
# ---------------------------------------------------------------------------


class _ListAsyncStream:
    """Trivial async-iterator wrapping a list of events. Used by the
    filter-generator tests to drive deterministic event sequences
    without spinning up a real watch handle.
    """

    def __init__(self, events):
        self._items = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def test_filter_revocation_events_yields_only_matching_kinds():
    """T-CPP-REVF-aux-async-gen: filter_revocation_events surfaces
    only the configured kinds, but the underlying classifier sees
    every event (state stays consistent for the BREACH-detection
    invariant).
    """
    record_unrevoked = _make_record(
        registered_by="filter-issuer",
        policy_id="filter-A",
        revoked_at=None,
    )
    record_revoked = _make_record(
        registered_by="filter-issuer",
        policy_id="filter-A",
        revoked_at=_REVOKED_AT_A,
    )
    record_refresh = _make_record(
        registered_by="filter-issuer",
        policy_id="filter-A",
        revoked_at=_REVOKED_AT_A,
        revocation_reason="audit refresh",
    )

    events = [
        _put_event(record_unrevoked, revision=1),  # NOT_REVOCATION
        _put_event(record_revoked, revision=2),  # TRANSITION
        _put_event(record_refresh, revision=3),  # REFRESH
        _delete_event(record_unrevoked.key, revision=4),  # KEY_REMOVED
    ]

    classifier = RevocationEventClassifier()

    async def _collect():
        results = []
        async for c in filter_revocation_events(
            _ListAsyncStream(events),
            classifier=classifier,
            kinds=frozenset({
                RevocationEventKind.REVOCATION_TRANSITION,
                RevocationEventKind.REVOCATION_REFRESH,
            }),
        ):
            results.append(c)
        return results

    yielded = asyncio.run(_collect())
    kinds = [c.kind for c in yielded]
    assert kinds == [
        RevocationEventKind.REVOCATION_TRANSITION,
        RevocationEventKind.REVOCATION_REFRESH,
    ]
    # Classifier saw EVERY event (state consistency check).
    # After DELETE, the key is dropped from known_keys.
    assert record_unrevoked.key not in classifier.known_keys()


def test_filter_revocation_events_default_kinds_surface_revocation_axis():
    """T-CPP-REVF-aux-default-kinds: when kinds=None, the default
    surfaces REVOCATION_TRANSITION + REVOCATION_REFRESH +
    REVOCATION_MONOTONIC_BREACH + EXPLICIT_UNREVOKE (the four
    revocation-axis kinds — three from Sprint-6 Tag-3 plus the
    Sprint-6 Tag-9 operator-deliberate-unrevoke kind).
    NOT_REVOCATION_RELATED and KEY_REMOVED are filtered out by
    default.
    """
    record_unrevoked = _make_record(revoked_at=None)
    record_revoked = _make_record(revoked_at=_REVOKED_AT_A)
    record_unrevoke_attempt = _make_record(revoked_at=None)

    events = [
        _put_event(record_unrevoked, revision=1),  # NOT_REVOCATION
        _put_event(record_revoked, revision=2),  # TRANSITION
        _put_event(record_unrevoke_attempt, revision=3),  # BREACH
        _delete_event(record_revoked.key, revision=4),  # KEY_REMOVED
    ]

    async def _collect():
        results = []
        async for c in filter_revocation_events(_ListAsyncStream(events)):
            results.append(c)
        return results

    yielded = asyncio.run(_collect())
    kinds = [c.kind for c in yielded]
    assert kinds == [
        RevocationEventKind.REVOCATION_TRANSITION,
        RevocationEventKind.REVOCATION_MONOTONIC_BREACH,
    ]


def test_filter_revocation_events_rejects_bad_classifier_argument():
    """T-CPP-REVF-aux-type-rejection-1: filter_revocation_events
    rejects non-classifier ``classifier`` argument.
    """

    async def _run():
        gen = filter_revocation_events(
            _ListAsyncStream([]), classifier=object()
        )
        async for _ in gen:
            pass

    with pytest.raises(TypeError, match="classifier must be"):
        asyncio.run(_run())


def test_filter_revocation_events_rejects_bad_kinds_argument():
    """T-CPP-REVF-aux-type-rejection-2: filter_revocation_events
    rejects non-frozenset ``kinds`` argument and frozensets containing
    non-RevocationEventKind members.
    """

    async def _run_bad_type():
        gen = filter_revocation_events(_ListAsyncStream([]), kinds=42)
        async for _ in gen:
            pass

    with pytest.raises(TypeError, match="kinds must be"):
        asyncio.run(_run_bad_type())

    async def _run_bad_member():
        gen = filter_revocation_events(
            _ListAsyncStream([]),
            kinds=frozenset({"not-a-kind"}),
        )
        async for _ in gen:
            pass

    with pytest.raises(TypeError, match="kinds members must be"):
        asyncio.run(_run_bad_member())


# ---------------------------------------------------------------------------
# Sprint-6 Tag-9: EXPLICIT_UNREVOKE classifier-extension tests
# ---------------------------------------------------------------------------


def test_classify_put_prior_revoked_marker_match_is_explicit_unrevoke():
    """T-CPP-REVF-13: PUT, prior-revoked X, revoked_at=None,
    unrevoke_audit_marker with previous_revoked_at=X
    -> EXPLICIT_UNREVOKE.

    The operator-deliberate gesture is authenticated by the marker's
    previous_revoked_at matching the classifier's per-key prior view.
    After classification, the per-key state advances to None
    (consistent with the actual transition; subsequent events for the
    same key are classified against unrevoked-prior).
    """
    classifier = RevocationEventClassifier()
    # Establish prior-revoked state.
    record_revoked = _make_record(
        revoked_at=_REVOKED_AT_A, revocation_reason="rotated key"
    )
    classifier.classify(_put_event(record_revoked, revision=1))
    assert classifier.last_revoked_at(record_revoked.key) == _REVOKED_AT_A

    # Operator-deliberate unrevoke via the Sprint-6 Tag-7 subcommand:
    # marker present, previous_revoked_at matches.
    marker = UnrevokeAuditMarker(
        unrevoke_reason="false-positive audit, restore",
        previous_revoked_at=_REVOKED_AT_A,
        previous_revocation_reason="rotated key",
    )
    record_unrevoked = _make_record(
        revoked_at=None,
        revocation_reason=None,
        unrevoke_audit_marker=marker,
    )
    classified = classifier.classify(
        _put_event(record_unrevoked, revision=2)
    )

    assert classified.kind is RevocationEventKind.EXPLICIT_UNREVOKE
    assert classified.prior_revoked_at == _REVOKED_AT_A
    assert classified.current_revoked_at is None
    assert classified.current_revocation_reason is None
    # Per-key state advances to None (unrevoked); a subsequent
    # revoke would be classified as TRANSITION from unrevoked-prior.
    assert classifier.last_revoked_at(record_unrevoked.key) is None


def test_classify_put_prior_revoked_marker_mismatch_is_breach():
    """T-CPP-REVF-14: PUT, prior-revoked X, revoked_at=None,
    unrevoke_audit_marker with previous_revoked_at=Y != X
    -> REVOCATION_MONOTONIC_BREACH.

    A marker referencing a previous_revoked_at the classifier did not
    observe cannot authenticate the gesture. The safe default is the
    louder kind: BREACH, on the same footing as the unmarked case.
    The classifier still advances per-key state to None (the
    incoming record's revoked_at).
    """
    classifier = RevocationEventClassifier()
    record_revoked = _make_record(revoked_at=_REVOKED_AT_A)
    classifier.classify(_put_event(record_revoked, revision=1))

    # Marker references a DIFFERENT prior instant.
    marker = UnrevokeAuditMarker(
        unrevoke_reason="stale receipt — wrong prior view",
        previous_revoked_at=_REVOKED_AT_B,  # != _REVOKED_AT_A
        previous_revocation_reason=None,
    )
    record_unrevoked = _make_record(
        revoked_at=None,
        unrevoke_audit_marker=marker,
    )
    classified = classifier.classify(
        _put_event(record_unrevoked, revision=2)
    )

    assert (
        classified.kind
        is RevocationEventKind.REVOCATION_MONOTONIC_BREACH
    )
    assert classified.prior_revoked_at == _REVOKED_AT_A
    assert classified.current_revoked_at is None


def test_classify_put_prior_revoked_no_marker_is_breach_preserved():
    """T-CPP-REVF-15: PUT, prior-revoked, revoked_at=None,
    unrevoke_audit_marker=None -> REVOCATION_MONOTONIC_BREACH.

    Regression guard on Sprint-6 Tag-3 T-CPP-REVF-05 semantics: a
    marker-less unrevoke shape is structurally indistinguishable
    from out-of-band tampering and must continue to surface as
    BREACH. The Sprint-6 Tag-9 EXPLICIT_UNREVOKE kind is opt-in via
    the marker; absence preserves Sprint-6 Tag-3 behaviour
    byte-equally.
    """
    classifier = RevocationEventClassifier()
    record_revoked = _make_record(revoked_at=_REVOKED_AT_A)
    classifier.classify(_put_event(record_revoked, revision=1))

    record_unrevoked = _make_record(
        revoked_at=None, unrevoke_audit_marker=None
    )
    classified = classifier.classify(
        _put_event(record_unrevoked, revision=2)
    )

    assert (
        classified.kind
        is RevocationEventKind.REVOCATION_MONOTONIC_BREACH
    )


def test_record_constructor_rejects_marker_on_still_revoked_policy():
    """T-CPP-REVF-16: CapabilityPolicyRecord constructor rejects an
    unrevoke_audit_marker on a policy whose revoked_at is non-None.

    The marker witnesses the operator-deliberate *transition to
    unrevoked*; carrying it on a still-revoked policy is a self-
    inconsistent envelope. The constructor refuses so the bucket
    can never persist the contradiction, and the classifier never
    has to defend against the shape at runtime.

    This is the structural suppression that lets the classifier
    treat marker presence as a load-bearing signal ONLY on the
    prior-revoked-to-unrevoked transition.
    """
    marker = UnrevokeAuditMarker(
        unrevoke_reason="ignored",
        previous_revoked_at=_REVOKED_AT_A,
        previous_revocation_reason=None,
    )
    # The policy is still revoked — constructing the record with
    # a marker must fail.
    with pytest.raises(
        CapabilityPolicyValidationError,
        match="unrevoke_audit_marker requires policy.revoked_at",
    ):
        CapabilityPolicyRecord(
            policy=_make_policy(revoked_at=_REVOKED_AT_B),
            policy_id="policy-A",
            registered_by_publisher="wirelang-eng",
            registered_at=_REGISTERED_AT,
            unrevoke_audit_marker=marker,
        )


def test_filter_default_kinds_surface_explicit_unrevoke():
    """T-CPP-REVF-17: filter_revocation_events with kinds=None
    surfaces EXPLICIT_UNREVOKE alongside TRANSITION / REFRESH /
    BREACH; NOT_REVOCATION_RELATED and KEY_REMOVED remain filtered.
    """
    record_unrevoked = _make_record(revoked_at=None)
    record_revoked = _make_record(revoked_at=_REVOKED_AT_A)
    marker = UnrevokeAuditMarker(
        unrevoke_reason="restore",
        previous_revoked_at=_REVOKED_AT_A,
        previous_revocation_reason=None,
    )
    record_explicit_unrevoke = _make_record(
        revoked_at=None, unrevoke_audit_marker=marker
    )

    events = [
        _put_event(record_unrevoked, revision=1),  # NOT_REVOCATION
        _put_event(record_revoked, revision=2),  # TRANSITION
        _put_event(record_explicit_unrevoke, revision=3),  # EXPLICIT_UNREVOKE
        _delete_event(record_revoked.key, revision=4),  # KEY_REMOVED
    ]

    async def _collect():
        results = []
        async for c in filter_revocation_events(_ListAsyncStream(events)):
            results.append(c)
        return results

    yielded = asyncio.run(_collect())
    kinds = [c.kind for c in yielded]
    assert kinds == [
        RevocationEventKind.REVOCATION_TRANSITION,
        RevocationEventKind.EXPLICIT_UNREVOKE,
    ]
    # NOT_REVOCATION_RELATED and KEY_REMOVED filtered by default.


def test_envelope_round_trip_preserves_unrevoke_audit_marker():
    """T-CPP-REVF-18: _record_to_envelope / _envelope_to_record round-
    trip preserves the unrevoke_audit_marker byte-equally.

    The marker survives serialise -> deserialise as a fully-formed
    :class:`UnrevokeAuditMarker` whose fields equal the original.
    Byte-stability of the canonical-JSON envelope is preserved
    (sort_keys=True), so two encoders agree on the wire bytes.
    """
    marker = UnrevokeAuditMarker(
        unrevoke_reason="false-positive audit, restore",
        previous_revoked_at=_REVOKED_AT_A,
        previous_revocation_reason="rotated key",
    )
    record = _make_record(
        revoked_at=None,
        unrevoke_audit_marker=marker,
    )
    blob = _record_to_envelope(record)
    decoded = _envelope_to_record(blob)

    assert decoded.unrevoke_audit_marker is not None
    assert (
        decoded.unrevoke_audit_marker.unrevoke_reason
        == "false-positive audit, restore"
    )
    assert (
        decoded.unrevoke_audit_marker.previous_revoked_at
        == _REVOKED_AT_A
    )
    assert (
        decoded.unrevoke_audit_marker.previous_revocation_reason
        == "rotated key"
    )
    # Byte-stability: re-encoding the decoded record yields the same
    # bytes (canonical JSON, sort_keys=True).
    assert _record_to_envelope(decoded) == blob


def test_envelope_back_compat_without_marker_key():
    """T-CPP-REVF-19: _envelope_to_record on a pre-Sprint-6 Tag-9
    envelope (no ``unrevoke_audit_marker`` key) decodes byte-equally
    with ``unrevoke_audit_marker=None``.

    This is the backward-compatibility invariant: any pre-Tag-9
    write path (publish, revoke, replication, Sprint-6 Tag-1..8
    paths) produced envelopes without the key, and the decoder
    treats absence as "no marker" without raising.
    """
    # Sprint-6 Tag-7 unrevoke would NOT have written this shape
    # (Tag-7 wrote the un-revoked record without a marker; this
    # test pins that the decoder accepts the historical shape).
    record_legacy = _make_record(
        revoked_at=_REVOKED_AT_A,
        revocation_reason="legacy revoke",
        unrevoke_audit_marker=None,
    )
    blob_legacy = _record_to_envelope(record_legacy)
    # Confirm the wire-bytes contain no marker key.
    import json as _json

    parsed = _json.loads(blob_legacy.decode("utf-8"))
    assert "unrevoke_audit_marker" not in parsed

    decoded = _envelope_to_record(blob_legacy)
    assert decoded.unrevoke_audit_marker is None
    # The rest of the record is byte-equal to the original.
    assert decoded.policy.revoked_at == _REVOKED_AT_A
    assert decoded.policy.revocation_reason == "legacy revoke"


def test_envelope_decoder_rejects_poisoned_marker_sub_object():
    """T-CPP-REVF-aux-poisoned-marker: the decoder rejects a marker
    sub-object with a missing required field (defensive: a partial
    marker shape on the wire is a poisoned envelope, not a silent
    "no marker" pass-through).
    """
    # Hand-craft a poisoned envelope: marker dict with a missing key.
    record = _make_record(revoked_at=None)
    base = _record_to_envelope(record)
    import json as _json

    payload = _json.loads(base.decode("utf-8"))
    payload["unrevoke_audit_marker"] = {
        # missing "previous_revoked_at" and "previous_revocation_reason"
        "unrevoke_reason": "poisoned",
    }
    poisoned = _json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    with pytest.raises(
        CapabilityPolicyEnvelopeError,
        match="unrevoke_audit_marker missing required field",
    ):
        _envelope_to_record(poisoned)
