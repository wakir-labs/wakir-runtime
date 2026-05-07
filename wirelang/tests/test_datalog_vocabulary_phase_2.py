# SPDX-License-Identifier: Apache-2.0
"""Determinism tests for Datalog Caveat Vocabulary Phase-2 (v0.2 ratified).

Spec reference: ``wirelang/specs/datalog-caveat-vocabulary-phase-2.md``.

The catalogue here implements §10 of the spec: ten determinism probes
covering the §4-CSC canonicalisation rule (T-CSC-01..T-CSC-06) and the
§3 / §5 schema-admission semantics (T-V0.2-01..T-V0.2-04).

Cross-lane parity (sandbox vs production lane) is asserted directly
in T-CSC-PARITY: the rfc8785-backed and Pure-Python paths MUST
produce byte-identical output for every probe input.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from wirelang.canonical.caveat_set import (
    canonical_caveat_set_bytes,
    canonical_caveat_set_hash,
    canonicalize_caveat_set,
    _canonical_caveat_set_bytes_pure,
    _canonical_caveat_set_hash_pure,
)


WIRELANG_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = WIRELANG_ROOT / "schemas" / "datalog-caveat.json"


# ---------------------------------------------------------------------------
# §4-CSC canonicalisation determinism probes
# ---------------------------------------------------------------------------


def test_t_csc_01_empty_caveat_set_is_canonical() -> None:
    """T-CSC-01 — empty caveat-set serialises to JCS empty array.

    The pre-image is the byte sequence ``b"[]"`` and its SHA-256 is
    the constant pinned in spec §10.
    """
    expected_bytes = b"[]"
    expected_hash_hex = (
        "4f53cda18c2baa0c0354bb5f9a3ecbe5"
        "ed12ab4d8e11ba873c2f11161202b945"
    )

    assert canonical_caveat_set_bytes([]) == expected_bytes
    assert canonical_caveat_set_hash([]).hex() == expected_hash_hex
    # Pure-Python parity.
    assert _canonical_caveat_set_bytes_pure([]) == expected_bytes
    assert _canonical_caveat_set_hash_pure([]).hex() == expected_hash_hex


def test_t_csc_02_single_caveat_canonicalisation() -> None:
    """T-CSC-02 — single-caveat hash is recomputable from JCS by hand.

    For a single caveat ``action("treasury.read.balance")`` the
    canonical JCS-array encoding is
    ``["action(\"treasury.read.balance\")"]`` (with the inner quotes
    JSON-string-escaped). We recompute the hash via the function and
    via a hand-built JCS string and compare byte-for-byte.
    """
    caveat = 'action("treasury.read.balance")'
    via_function = canonical_caveat_set_hash([caveat])
    # Hand-built JCS: a JSON array of one string. RFC 8785 mandates
    # no insignificant whitespace and JSON-string escaping for the
    # inner double-quotes.
    hand_built = b'["action(\\"treasury.read.balance\\")"]'
    via_hand = hashlib.sha256(hand_built).digest()
    assert via_function == via_hand


def test_t_csc_03_whitespace_normalisation() -> None:
    """T-CSC-03 — whitespace-equivalent caveats produce the same hash.

    The §4.1 step 1 normaliser collapses runs of ASCII space, TAB,
    CR, LF to a single ASCII space. Two semantically identical
    caveat-sets that differ only in interior whitespace MUST produce
    identical ``caveat_set_hash`` values.
    """
    a = ["time($t), $t < 2026-12-31T23:59:59Z"]
    b = ["time($t),  \t$t  <  2026-12-31T23:59:59Z"]  # extra ws + tab
    c = ["time($t),\n$t < 2026-12-31T23:59:59Z"]  # newline
    d = ["  time($t), $t < 2026-12-31T23:59:59Z  "]  # leading/trailing
    h_a = canonical_caveat_set_hash(a)
    assert canonical_caveat_set_hash(b) == h_a
    assert canonical_caveat_set_hash(c) == h_a
    assert canonical_caveat_set_hash(d) == h_a


def test_t_csc_04_dedup_preserves_single_occurrence() -> None:
    """T-CSC-04 — duplicate caveats collapse to a single occurrence.

    A caveat-set ``[c, c]`` MUST produce the same ``caveat_set_hash``
    as ``[c]``. Per Biscuit-Datalog set semantics, a duplicate
    caveat is a no-op; the hash MUST agree.
    """
    c = "read_only(true)"
    h_single = canonical_caveat_set_hash([c])
    h_dup = canonical_caveat_set_hash([c, c])
    h_triple = canonical_caveat_set_hash([c, c, c])
    assert h_single == h_dup == h_triple


def test_t_csc_05_sort_produces_order_independence() -> None:
    """T-CSC-05 — caveat-set order does not affect the hash.

    For any two admissible caveats ``a, b``, ``canonical([a, b])``
    and ``canonical([b, a])`` MUST produce the same hash. We
    exercise a representative cross-product of v0.1 and v0.2
    predicates.
    """
    pairs = [
        ('action("x")', 'env("prod")'),
        ('audience("did:web:wakir.dev/personas/role-a")', "rate_limit(10)"),
        ("read_only(true)", "not_before(2026-05-06T00:00:00Z)"),
        ("not_before(2026-05-06T00:00:00Z)", "not_after(2026-05-13T00:00:00Z)"),
        # NEW v0.2 federation predicates also order-independent.
        ('peer_org("aip:web:partner-a/personas/treasury-issuer")',
         'federation_route("wakir->partner-a->treasury")'),
    ]
    for a, b in pairs:
        h_ab = canonical_caveat_set_hash([a, b])
        h_ba = canonical_caveat_set_hash([b, a])
        assert h_ab == h_ba, f"order-dependence on ({a!r}, {b!r})"


def test_t_csc_06_jcs_array_idempotence() -> None:
    """T-CSC-06 — re-canonicalising the canonical bytes is a no-op.

    Round-tripping the canonical JCS-array byte sequence through
    ``json.loads`` and re-canonicalising MUST produce the identical
    byte sequence. This is the idempotence invariant of §4.
    """
    caveats = [
        'action("treasury.read.balance")',
        'env("prod")',
        "read_only(true)",
        'audience("did:web:wakir.dev/personas/role-a")',
        "rate_limit(100)",
    ]
    first = canonical_caveat_set_bytes(caveats)
    parsed = json.loads(first.decode("utf-8"))
    second = canonical_caveat_set_bytes(parsed)
    assert first == second, "canonicalisation is not idempotent"


# ---------------------------------------------------------------------------
# §3 / §5 schema-admission tests (Phase-2 vocabulary classification)
# ---------------------------------------------------------------------------
#
# The schema-admission tests below need the jsonschema validator.
# We attempt the import lazily so the §4-CSC determinism tests above
# run on the sandbox-CI lane (which does not install jsonschema), and
# only the schema-admission tests are skipped there.

try:
    import jsonschema as _jsonschema  # noqa: F401
    _Draft202012Validator = _jsonschema.Draft202012Validator
    _HAS_JSONSCHEMA = True
except ImportError:
    _Draft202012Validator = None  # type: ignore[assignment]
    _HAS_JSONSCHEMA = False


@pytest.fixture(scope="module")
def datalog_caveat_validator_v02():
    if not _HAS_JSONSCHEMA:
        pytest.skip("jsonschema not installed (sandbox-CI lane)")
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    _Draft202012Validator.check_schema(schema)
    # Sanity: this test module assumes v0.2.0 schema.
    assert schema["$id"].endswith("/0.2.0"), schema["$id"]
    return _Draft202012Validator(schema)


def test_t_v02_01_schema_admits_peer_org(datalog_caveat_validator_v02) -> None:
    """T-V0.2-01 — schema admits the ratified `peer_org` N2 predicate."""
    datalog_caveat_validator_v02.validate([
        'peer_org("aip:web:partner-a/personas/treasury-issuer")',
    ])


def test_t_v02_02_schema_admits_federation_route(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2-02 — schema admits the ratified `federation_route` N2."""
    datalog_caveat_validator_v02.validate([
        'federation_route("wakir->partner-a->treasury")',
    ])


def test_t_v02_03_schema_rejects_class_r_predicates(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2-03 — Class R (reserved-without-substrate) is not admitted.

    Each Class R predicate name MUST be rejected by the v0.2 schema.
    The reservation lives at the vocabulary level (verifier
    fail-closed), not the schema level.
    """
    class_r_samples = [
        'zk_proof_valid("4f9c...e108", "vk-1")',
        'zk_reputation_threshold(80, "wakir-default")',
        'cross_org_quota($n, $org)',
        'persona_state("active")',
        'persona_attested_after(2026-05-01T00:00:00Z)',
        'wat_inclusion_proof_valid("a1b2...", "manifest-2026-W19")',
    ]
    for c in class_r_samples:
        errors = list(
            datalog_caveat_validator_v02.iter_errors([c])
        )
        assert errors, f"Class R predicate accidentally admitted: {c!r}"


def test_t_v02_04_schema_rejects_class_p_predicates(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2-04 — Class P (patch-eligible-not-ratified) is not admitted.

    `persona_pin` and `caveat_hash` are reserved-but-not-promoted in
    v0.2; the schema MUST reject them. Promotion is its own
    ratification event.
    """
    class_p_samples = [
        'persona_pin("4f9c8a3b1e7d2c0a")',
        'caveat_hash("c1b2d3e4f5061728")',
    ]
    for c in class_p_samples:
        errors = list(
            datalog_caveat_validator_v02.iter_errors([c])
        )
        assert errors, f"Class P predicate accidentally admitted: {c!r}"


# ---------------------------------------------------------------------------
# Cross-lane parity (T-CSC-PARITY)
# ---------------------------------------------------------------------------


def test_t_csc_parity_rfc8785_vs_pure_python() -> None:
    """T-CSC-PARITY — production-lane and sandbox-lane agree byte-for-byte.

    For a representative cross-section of inputs, the rfc8785-backed
    canonicalisation and the Pure-Python fallback MUST produce the
    same byte sequence and the same hash. This is the cross-lane
    parity invariant from spec §6.2.
    """
    cases: list[list[str]] = [
        [],
        ['action("x")'],
        [
            "time($t), $t < 2026-12-31T23:59:59Z",
            'audience("did:web:wakir.dev/personas/role-a")',
            'env("prod")',
            "read_only(true)",
            "rate_limit(100)",
        ],
        [
            # Whitespace-noisy and dup-noisy inputs to exercise
            # all four steps of §4.1 in one case.
            "  time($t), $t < 2026-12-31T23:59:59Z  ",
            "time($t),\t$t < 2026-12-31T23:59:59Z",
            'env("prod")',
            'env("prod")',
        ],
        [
            'peer_org("aip:web:partner-a/personas/treasury-issuer")',
            'federation_route("wakir->partner-a->treasury")',
            'agent_did("did:web:wakir.dev/personas/cfo-agent")',
        ],
    ]
    for caveats in cases:
        b_via_default = canonical_caveat_set_bytes(caveats)
        b_via_pure = _canonical_caveat_set_bytes_pure(caveats)
        assert b_via_default == b_via_pure, (
            f"cross-lane byte-divergence on {caveats!r}"
        )
        assert (
            canonical_caveat_set_hash(caveats)
            == _canonical_caveat_set_hash_pure(caveats)
        )


# ---------------------------------------------------------------------------
# Defensive guards (input-shape contract)
# ---------------------------------------------------------------------------


def test_canonicalize_rejects_non_string_caveat() -> None:
    """A non-string caveat must raise TypeError at normalisation time.

    The canonicaliser is the entry point for any caveat-set; it
    refuses to silently coerce non-strings.
    """
    with pytest.raises(TypeError):
        canonicalize_caveat_set(["action(\"x\")", 42])  # type: ignore[list-item]


def test_canonicalize_returns_fresh_list() -> None:
    """The canonicaliser does not mutate its input."""
    inp = ['env("prod")', 'action("x")']
    inp_copy = list(inp)
    out = canonicalize_caveat_set(inp)
    assert inp == inp_copy, "input was mutated"
    assert out is not inp, "output aliased the input"


def test_canonical_set_is_lex_sorted() -> None:
    """The canonicalised list MUST be lex-sorted (UTF-8 byte order)."""
    inp = ['env("prod")', 'action("x")', "read_only(true)"]
    out = canonicalize_caveat_set(inp)
    assert out == sorted(set(inp), key=lambda s: s.encode("utf-8"))


def test_caveat_set_hash_is_32_bytes() -> None:
    """The hash is SHA-256 → 32 raw bytes (256 bits)."""
    h = canonical_caveat_set_hash(['action("x")'])
    assert isinstance(h, bytes) and len(h) == 32


# ---------------------------------------------------------------------------
# Round-trip: canonicalise → JCS-decode → canonicalise (idempotence)
# ---------------------------------------------------------------------------


def test_t_csc_idempotence_under_round_trip_full_set() -> None:
    """Idempotence sweeps a full Phase-1a caveat-set.

    Belt-and-braces against T-CSC-06: re-canonicalising the canonical
    bytes for a *full* Phase-1a caveat-set must produce the identical
    bytes.
    """
    caveats = [
        "time($t), $t > 2026-05-06T00:00:00Z, $t < 2026-05-13T00:00:00Z",
        'audience("did:web:wakir.dev/personas/treasury-agent")',
        'agent_did("did:web:wakir.dev/personas/cfo-agent")',
        'operation("read_balance")',
        "action_count_max(10)",
        "read_only(true)",
        'env("prod")',
        "rate_limit(100)",
        "attenuation_depth_max(2)",
        'wat_anchor("anchor-2026-05-06-w19")',
    ]
    first = canonical_caveat_set_bytes(caveats)
    parsed = json.loads(first.decode("utf-8"))
    second = canonical_caveat_set_bytes(parsed)
    assert first == second
