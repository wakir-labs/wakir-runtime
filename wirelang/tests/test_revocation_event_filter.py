# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the capability-policy revocation-event-filter
surface (Phase-2 Sprint-6 Tag-3, consumer-side symmetry to Sprint-6
Tag-1 backend revocation-axis).

Tested surfaces on
:mod:`wirelang.schemas.capability_policy_nats_kv_backend`:

- :class:`RevocationEventKind` (5 enum members)
- :class:`ClassifiedRevocationEvent` (frozen dataclass)
- :class:`RevocationEventClassifier` (stateful classifier)
- :func:`filter_revocation_events` (async generator)

The consumer-side surface mirrors the Sprint-6 Tag-1 backend write
invariants: once a key is revoked, subsequent PUTs MUST preserve
``revoked_at`` byte-equally; an apparent un-revoke or an advanced /
retreated ``revoked_at`` is a witness of substrate corruption or
out-of-band tampering and surfaces as REVOCATION_MONOTONIC_BREACH.
The classifier is an observation layer, not an enforcement layer:
it surfaces the kind for the consumer to act on, it does not raise
on breach.

Test inventory (T-CPP-REVF-01..12 + 2 aux probes):

- T-CPP-REVF-01: classify(PUT, no-prior, revoked_at=None)
  -> NOT_REVOCATION_RELATED.
- T-CPP-REVF-02: classify(PUT, no-prior, revoked_at=set)
  -> REVOCATION_TRANSITION.
- T-CPP-REVF-03: classify(PUT, prior-unrevoked, revoked_at=set)
  -> REVOCATION_TRANSITION (the un-revoked -> revoked transition).
- T-CPP-REVF-04: classify(PUT, prior-revoked, same revoked_at,
  different revocation_reason) -> REVOCATION_REFRESH.
- T-CPP-REVF-05: classify(PUT, prior-revoked, revoked_at=None)
  -> REVOCATION_MONOTONIC_BREACH (apparent un-revoke).
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
    REVOCATION_MONOTONIC_BREACH (the three revocation-axis kinds).
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
