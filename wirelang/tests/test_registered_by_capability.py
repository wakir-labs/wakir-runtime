# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for ``wirelang.schemas.registered_by_capability``.

Phase-2 Sprint-4 Tag-6. Tests cover the capability-policy bundle
shape, the registry lookup contract, the gating decision matrix
(allow / deny by every dimension: kid, triple, validity window,
disabled), the end-to-end composition with the Sprint-4 Tag-1
:class:`SignedSchemaRegistryEntry`, and the structural failure
contract.

All tests are hermetic: no real time, no I/O, no transport, no NATS.
Datetime arguments use timezone-aware UTC instances.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wirelang.schemas.entry_signing import (
    SignedSchemaRegistryEntry,
    sign_entry,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityGateDecision,
    CapabilityPolicy,
    CapabilityPolicyRegistry,
    DecisionSource,
    RegisteredByCapabilityError,
    check_registered_by_capability,
    gate_signed_entry,
)
from wirelang.schemas.registry_nats_kv_backend import SchemaRegistryEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_SEED_A: bytes = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
"""RFC 8032 test-vector 1 seed."""


def _keypair(seed: bytes) -> Tuple[bytes, bytes]:
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pk = sk.public_key()
    priv = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub


def _make_entry(
    *,
    layer: str = "layer-1-wire",
    name: str = "frame-envelope",
    version: str = "1",
    registered_by: str = "aip:web:wakir.dev/personas/treasury-issuer",
) -> SchemaRegistryEntry:
    """Construct a deterministic SchemaRegistryEntry for gating tests."""
    body = {
        "$id": (
            f"https://wakir.dev/wirelang/schema/{layer}/{name}/{version}"
        ),
        "type": "object",
    }
    return SchemaRegistryEntry(
        layer=layer,
        name=name,
        version=version,
        schema_id=body["$id"],
        schema_body=body,
        schema_body_sha256=("a" * 64),
        registered_at=datetime(2026, 5, 11, 18, 0, 0, tzinfo=timezone.utc),
        registered_by=registered_by,
        supersedes=None,
    )


def _basic_policy(
    *,
    registered_by: str = "aip:web:wakir.dev/personas/treasury-issuer",
    allowed_kids: Tuple[str, ...] = ("biscuit-root-1",),
    allowed_triples: Tuple[Tuple[str, str], ...] = (
        ("layer-1-wire", "frame-envelope"),
    ),
    not_before: "datetime | None" = None,
    not_after: "datetime | None" = None,
    disabled: bool = False,
    note: "str | None" = None,
) -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=allowed_kids,
        allowed_triples=allowed_triples,
        not_before=not_before,
        not_after=not_after,
        disabled=disabled,
        note=note,
    )


# ===========================================================================
# T-RBC-01 — construction defaults and bad-arg-grid
# ===========================================================================


class TestRbc01ConstructionGrid:
    def test_minimal_policy_constructs_with_defaults(self) -> None:
        p = _basic_policy()
        assert p.registered_by == "aip:web:wakir.dev/personas/treasury-issuer"
        assert p.allowed_kids == ("biscuit-root-1",)
        assert p.allowed_triples == (("layer-1-wire", "frame-envelope"),)
        assert p.not_before is None
        assert p.not_after is None
        assert p.disabled is False
        assert p.note is None

    @pytest.mark.parametrize(
        "kwargs,fragment",
        [
            ({"registered_by": ""}, "registered_by"),
            ({"allowed_kids": ()}, "allowed_kids"),
            ({"allowed_kids": ("",)}, "allowed_kids entries"),
            ({"allowed_triples": ()}, "allowed_triples"),
            (
                {"allowed_triples": (("layer-1-wire",),)},
                "allowed_triples entries",
            ),
            (
                {"allowed_triples": (("layer-1-wire", ""),)},
                "allowed_triples entries",
            ),
            ({"not_before": "2026-05-01"}, "not_before"),
            ({"not_after": 1234}, "not_after"),
            ({"disabled": "false"}, "disabled"),
            ({"note": 42}, "note"),
        ],
    )
    def test_bad_args_raise_structural_error(
        self, kwargs: dict, fragment: str
    ) -> None:
        base = dict(
            registered_by="aip:web:wakir.dev/personas/treasury-issuer",
            allowed_kids=("biscuit-root-1",),
            allowed_triples=(("layer-1-wire", "frame-envelope"),),
        )
        base.update(kwargs)
        with pytest.raises(RegisteredByCapabilityError) as exc:
            CapabilityPolicy(**base)
        assert fragment in str(exc.value)

    def test_inverted_validity_window_raises(self) -> None:
        nb = datetime(2026, 6, 1, tzinfo=timezone.utc)
        na = datetime(2026, 5, 1, tzinfo=timezone.utc)
        with pytest.raises(RegisteredByCapabilityError) as exc:
            _basic_policy(not_before=nb, not_after=na)
        assert "strictly less than" in str(exc.value)


# ===========================================================================
# T-RBC-02 — matching policy yields POLICY_MATCH allow
# ===========================================================================


class TestRbc02MatchingPolicyAllows:
    def test_basic_allow(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-1",
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is True
        assert decision.source is DecisionSource.POLICY_MATCH
        assert decision.policy is not None
        assert decision.policy.registered_by == entry.registered_by
        assert "policy match" in decision.reason

    def test_allow_decision_carries_policy_reference(self) -> None:
        registry = CapabilityPolicyRegistry()
        p = _basic_policy(note="Phase-2 transition seed policy")
        registry.add_policy(p)
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-1",
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is True
        assert decision.policy is p
        assert decision.policy.note == "Phase-2 transition seed policy"


# ===========================================================================
# T-RBC-03 — unknown registered_by yields NO_POLICY_FOR_ISSUER deny
# ===========================================================================


class TestRbc03UnknownIssuerDenies:
    def test_unknown_issuer(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        entry = _make_entry(registered_by="aip:web:wakir.dev/personas/intruder")
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-1",
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is False
        assert decision.source is DecisionSource.NO_POLICY_FOR_ISSUER
        assert decision.policy is None
        assert "intruder" in decision.reason

    def test_empty_registry_denies_any_issuer(self) -> None:
        registry = CapabilityPolicyRegistry()
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-1",
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is False
        assert decision.source is DecisionSource.NO_POLICY_FOR_ISSUER


# ===========================================================================
# T-RBC-04 — kid not in allowed_kids yields KID_NOT_ALLOWED deny
# ===========================================================================


class TestRbc04KidNotAllowed:
    def test_kid_not_in_allowed_kids(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(
            _basic_policy(allowed_kids=("biscuit-root-1", "biscuit-root-2"))
        )
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-3",  # not on the allow-list
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is False
        assert decision.source is DecisionSource.KID_NOT_ALLOWED
        assert "biscuit-root-3" in decision.reason
        assert "biscuit-root-1" in decision.reason  # allowed_kids printed

    def test_first_matching_kid_short_circuits(self) -> None:
        # Two policies under the same issuer with disjoint kid-sets;
        # the second policy carries the kid we present. The gate must
        # iterate to find it.
        registry = CapabilityPolicyRegistry()
        registry.add_policy(
            _basic_policy(allowed_kids=("biscuit-root-1",))
        )
        registry.add_policy(
            _basic_policy(allowed_kids=("biscuit-root-2",))
        )
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-2",
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is True
        assert decision.policy.allowed_kids == ("biscuit-root-2",)


# ===========================================================================
# T-RBC-05 — triple not covered by allowed_triples yields TRIPLE_NOT_ALLOWED
# ===========================================================================


class TestRbc05TripleNotAllowed:
    def test_layer_mismatch_denies(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(
            _basic_policy(
                allowed_triples=(("layer-1-wire", "frame-envelope"),)
            )
        )
        entry = _make_entry(layer="layer-2-semantic")
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-1",
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is False
        assert decision.source is DecisionSource.TRIPLE_NOT_ALLOWED
        assert "layer-2-semantic" in decision.reason

    def test_name_mismatch_denies(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(
            _basic_policy(
                allowed_triples=(("layer-1-wire", "frame-envelope"),)
            )
        )
        entry = _make_entry(name="audit-trail-leaf")
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-1",
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is False
        assert decision.source is DecisionSource.TRIPLE_NOT_ALLOWED
        assert "audit-trail-leaf" in decision.reason


# ===========================================================================
# T-RBC-06 — layer wildcard ("*") allows any layer
# ===========================================================================


class TestRbc06LayerWildcardAllows:
    def test_wildcard_layer_with_concrete_name(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(
            _basic_policy(allowed_triples=(("*", "frame-envelope"),))
        )
        entry_w = _make_entry(layer="layer-1-wire")
        entry_s = _make_entry(layer="layer-2-semantic")
        for e in (entry_w, entry_s):
            decision = check_registered_by_capability(
                e,
                {
                    "alg": "Ed25519",
                    "kid": "biscuit-root-1",
                    "signature": "00" * 64,
                },
                registry,
            )
            assert decision.allowed is True
            assert decision.source is DecisionSource.POLICY_MATCH

    def test_full_wildcard_allow(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(
            _basic_policy(allowed_triples=(("*", "*"),))
        )
        entry = _make_entry(layer="layer-9-novel", name="exotic-shape")
        decision = check_registered_by_capability(
            entry,
            {
                "alg": "Ed25519",
                "kid": "biscuit-root-1",
                "signature": "00" * 64,
            },
            registry,
        )
        assert decision.allowed is True


# ===========================================================================
# T-RBC-07 — name glob wildcard matches via fnmatch
# ===========================================================================


class TestRbc07NameGlobMatches:
    def test_prefix_glob_matches(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(
            _basic_policy(allowed_triples=(("layer-1-wire", "frame-*"),))
        )
        entry_match = _make_entry(name="frame-envelope")
        entry_match2 = _make_entry(name="frame-burst")
        entry_no = _make_entry(name="audit-trail")
        d1 = check_registered_by_capability(
            entry_match,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
        )
        d2 = check_registered_by_capability(
            entry_match2,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
        )
        d3 = check_registered_by_capability(
            entry_no,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
        )
        assert d1.allowed is True
        assert d2.allowed is True
        assert d3.allowed is False
        assert d3.source is DecisionSource.TRIPLE_NOT_ALLOWED

    def test_question_mark_glob(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(
            _basic_policy(allowed_triples=(("layer-1-wire", "frame-?"),))
        )
        entry_match = _make_entry(name="frame-a")
        entry_no = _make_entry(name="frame-ab")
        d1 = check_registered_by_capability(
            entry_match,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
        )
        d2 = check_registered_by_capability(
            entry_no,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
        )
        assert d1.allowed is True
        assert d2.allowed is False


# ===========================================================================
# T-RBC-08 — disabled policy is invisible to allow path; surfaces deny
# ===========================================================================


class TestRbc08DisabledPolicy:
    def test_disabled_policy_denies_when_sole(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy(disabled=True))
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
        )
        assert decision.allowed is False
        assert decision.source is DecisionSource.POLICY_DISABLED
        assert decision.policy is not None
        assert decision.policy.disabled is True

    def test_disabled_policy_alongside_enabled_allows(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy(disabled=True))
        registry.add_policy(_basic_policy(disabled=False))
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
        )
        assert decision.allowed is True
        assert decision.source is DecisionSource.POLICY_MATCH


# ===========================================================================
# T-RBC-09 — validity-window enforcement (OUTSIDE_VALIDITY_WINDOW deny)
# ===========================================================================


class TestRbc09ValidityWindow:
    def test_before_window_denies(self) -> None:
        nb = datetime(2026, 6, 1, tzinfo=timezone.utc)
        na = datetime(2026, 7, 1, tzinfo=timezone.utc)
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy(not_before=nb, not_after=na))
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        assert decision.allowed is False
        assert decision.source is DecisionSource.OUTSIDE_VALIDITY_WINDOW

    def test_after_window_denies(self) -> None:
        nb = datetime(2026, 6, 1, tzinfo=timezone.utc)
        na = datetime(2026, 7, 1, tzinfo=timezone.utc)
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy(not_before=nb, not_after=na))
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
            as_of=datetime(2026, 7, 1, tzinfo=timezone.utc),  # exclusive bound
        )
        assert decision.allowed is False
        assert decision.source is DecisionSource.OUTSIDE_VALIDITY_WINDOW

    def test_inside_window_allows(self) -> None:
        nb = datetime(2026, 6, 1, tzinfo=timezone.utc)
        na = datetime(2026, 7, 1, tzinfo=timezone.utc)
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy(not_before=nb, not_after=na))
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
        assert decision.allowed is True

    def test_as_of_omitted_skips_window_check(self) -> None:
        nb = datetime(2026, 6, 1, tzinfo=timezone.utc)
        na = datetime(2026, 7, 1, tzinfo=timezone.utc)
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy(not_before=nb, not_after=na))
        entry = _make_entry()
        decision = check_registered_by_capability(
            entry,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
            # as_of omitted: bypass window
        )
        assert decision.allowed is True


# ===========================================================================
# T-RBC-10 — gate_signed_entry composition with sign_entry (end-to-end)
# ===========================================================================


class TestRbc10GateSignedEntry:
    def test_gate_signed_entry_allows_real_signature(self) -> None:
        priv, _pub = _keypair(_SEED_A)
        entry = _make_entry()
        signed = sign_entry(entry, priv, kid="biscuit-root-1")
        assert isinstance(signed, SignedSchemaRegistryEntry)

        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())

        decision = gate_signed_entry(signed, registry)
        assert decision.allowed is True
        assert decision.source is DecisionSource.POLICY_MATCH

    def test_gate_signed_entry_denies_with_no_policy(self) -> None:
        priv, _pub = _keypair(_SEED_A)
        entry = _make_entry(
            registered_by="aip:web:wakir.dev/personas/unauthorised"
        )
        signed = sign_entry(entry, priv, kid="biscuit-root-1")
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())  # for a different issuer
        decision = gate_signed_entry(signed, registry)
        assert decision.allowed is False
        assert decision.source is DecisionSource.NO_POLICY_FOR_ISSUER

    def test_gate_signed_entry_rejects_non_signed_input(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        with pytest.raises(RegisteredByCapabilityError):
            gate_signed_entry(
                _make_entry(),  # bare entry, not signed
                registry,
            )


# ===========================================================================
# T-RBC-11 — decision dataclass immutability/equality, structural arg-grid
# ===========================================================================


class TestRbc11DecisionShape:
    def test_decision_is_frozen(self) -> None:
        d = CapabilityGateDecision(
            allowed=True,
            reason="r",
            source=DecisionSource.POLICY_MATCH,
            policy=None,
        )
        with pytest.raises(Exception):
            d.allowed = False  # type: ignore[misc]

    def test_decision_equality_by_value(self) -> None:
        d1 = CapabilityGateDecision(
            allowed=True,
            reason="r",
            source=DecisionSource.POLICY_MATCH,
            policy=None,
        )
        d2 = CapabilityGateDecision(
            allowed=True,
            reason="r",
            source=DecisionSource.POLICY_MATCH,
            policy=None,
        )
        assert d1 == d2

    def test_check_call_rejects_non_entry(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        with pytest.raises(RegisteredByCapabilityError):
            check_registered_by_capability(
                "not-an-entry",  # type: ignore[arg-type]
                {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
                registry,
            )

    def test_check_call_rejects_missing_kid_in_block(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        with pytest.raises(RegisteredByCapabilityError) as exc:
            check_registered_by_capability(
                _make_entry(),
                {"alg": "Ed25519", "signature": "00" * 64},  # no kid
                registry,
            )
        assert "'kid'" in str(exc.value)

    def test_check_call_rejects_non_mapping_block(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        with pytest.raises(RegisteredByCapabilityError):
            check_registered_by_capability(
                _make_entry(),
                "biscuit-root-1",  # type: ignore[arg-type]
                registry,
            )

    def test_check_call_rejects_non_registry(self) -> None:
        with pytest.raises(RegisteredByCapabilityError):
            check_registered_by_capability(
                _make_entry(),
                {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
                "not-a-registry",  # type: ignore[arg-type]
            )

    def test_check_call_rejects_non_datetime_as_of(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        with pytest.raises(RegisteredByCapabilityError):
            check_registered_by_capability(
                _make_entry(),
                {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
                registry,
                as_of="2026-05-11T18:00:00Z",  # type: ignore[arg-type]
            )

    def test_check_call_rejects_empty_kid(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        with pytest.raises(RegisteredByCapabilityError):
            check_registered_by_capability(
                _make_entry(),
                {"alg": "Ed25519", "kid": "", "signature": "00" * 64},
                registry,
            )


# ===========================================================================
# T-RBC-12 — registry list/lookup contract; multi-policy fallback ordering
# ===========================================================================


class TestRbc12RegistryAndFallbackOrdering:
    def test_list_issuers_and_policies_for(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        registry.add_policy(
            _basic_policy(
                registered_by="aip:web:wakir.dev/personas/other-issuer",
                allowed_kids=("biscuit-root-2",),
            )
        )
        issuers = registry.list_issuers()
        assert issuers == (
            "aip:web:wakir.dev/personas/other-issuer",
            "aip:web:wakir.dev/personas/treasury-issuer",
        )
        ps = registry.policies_for(
            "aip:web:wakir.dev/personas/treasury-issuer"
        )
        assert len(ps) == 1
        assert ps[0].allowed_kids == ("biscuit-root-1",)
        # Missing issuer returns an empty tuple, not an error.
        assert registry.policies_for("aip:web:wakir.dev/personas/ghost") == ()

    def test_policies_for_returns_defensive_tuple(self) -> None:
        registry = CapabilityPolicyRegistry()
        registry.add_policy(_basic_policy())
        ps = registry.policies_for(
            "aip:web:wakir.dev/personas/treasury-issuer"
        )
        # Tuple is immutable (defensive snapshot).
        assert isinstance(ps, tuple)
        # Adding another policy after snapshot does NOT mutate the
        # snapshot.
        registry.add_policy(
            _basic_policy(allowed_kids=("biscuit-root-2",))
        )
        assert len(ps) == 1
        ps2 = registry.policies_for(
            "aip:web:wakir.dev/personas/treasury-issuer"
        )
        assert len(ps2) == 2

    def test_add_policy_rejects_non_policy(self) -> None:
        registry = CapabilityPolicyRegistry()
        with pytest.raises(RegisteredByCapabilityError):
            registry.add_policy("not-a-policy")  # type: ignore[arg-type]

    def test_fallback_ordering_kid_beats_triple(self) -> None:
        """When two non-disabled policies fail at different stages,
        the first-encountered structural mismatch wins the deny
        reason: kid > triple > window > disabled is the *precedence*
        for *remembering* a deny (not the iteration order). The
        iteration order is FIFO; the first deny is recorded; later
        denies only replace the recorded one if they are a HIGHER-
        precedence source (so a triple-mismatch found *after* a
        kid-mismatch does NOT overwrite the kid record).

        This test pins the ordering: kid_not_allowed is recorded
        first, then a later policy with triple-mismatch does NOT
        replace it.
        """
        registry = CapabilityPolicyRegistry()
        # Policy 1: wrong kid; right triple
        registry.add_policy(
            _basic_policy(
                allowed_kids=("biscuit-root-99",),
                allowed_triples=(("layer-1-wire", "frame-envelope"),),
            )
        )
        # Policy 2: right kid; wrong triple
        registry.add_policy(
            _basic_policy(
                allowed_kids=("biscuit-root-1",),
                allowed_triples=(("layer-1-wire", "audit-trail"),),
            )
        )
        entry = _make_entry()  # layer-1-wire / frame-envelope
        decision = check_registered_by_capability(
            entry,
            {"alg": "Ed25519", "kid": "biscuit-root-1", "signature": "00" * 64},
            registry,
        )
        # Policy 2 should match (right kid, but wrong triple), so the
        # final fallback source is TRIPLE_NOT_ALLOWED (a higher-
        # precedence deny than the kid one recorded from policy 1).
        # This pins: deny precedence rises through the iteration, so
        # the most-specific failure surfaces to the audit log.
        assert decision.allowed is False
        assert decision.source is DecisionSource.TRIPLE_NOT_ALLOWED
