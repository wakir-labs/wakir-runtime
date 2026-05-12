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
    # Sanity: this test module assumes v0.2.1 schema (post-ADR-0052
    # Class-P-Promotion of `caveat_hash`; Sprint-6 Tag-8 ratification).
    # Pre-ADR-0052 the assertion pinned ``/0.2.0``; the promotion bump
    # is additive and is exercised by the dedicated T-V0.2.1-* probes
    # below.
    assert schema["$id"].endswith("/0.2.1"), schema["$id"]
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


def test_t_v02_04_schema_rejects_residual_class_p_predicates(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2-04 — residual Class P (not-yet-promoted) is not admitted.

    After the v0.2.1 ADR-0052 promotion of `caveat_hash`, `persona_pin`
    is the only remaining Class-P predicate; the schema MUST still
    reject it. Promotion of `persona_pin` is its own future
    ratification event (no ADR yet).

    Pre-ADR-0052 this test rejected both `persona_pin` AND
    `caveat_hash`; the latter is now admitted by the v0.2.1 schema
    and is exercised positively by T-V0.2.1-01 below.
    """
    class_p_samples = [
        'persona_pin("4f9c8a3b1e7d2c0a")',
    ]
    for c in class_p_samples:
        errors = list(
            datalog_caveat_validator_v02.iter_errors([c])
        )
        assert errors, f"Residual Class P predicate accidentally admitted: {c!r}"


# ---------------------------------------------------------------------------
# v0.2.1 ADR-0052 Class-P-Promotion schema-admission probes
# ---------------------------------------------------------------------------
#
# ADR-0052 (approved 2026-05-12) promotes `caveat_hash(self_hash)` from
# Class P (patch-eligible) to Class N1 via a v0.2.0 → v0.2.1 schema
# patch. The promotion is additive: existing v0.2.0 caveats still
# validate; v0.2.1 additionally admits the fixed-shape
# `caveat_hash("<64-hex>")` literal. The verifier-side recompute
# algorithm is specified in
# `datalog-caveat-vocabulary-phase-2.md` §7 and is exercised by
# `test_caveat_hash_promotion_substrate.py` (T-CHP-01..06).


def test_t_v021_01_schema_admits_caveat_hash_with_lowercase_hex(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2.1-01 — v0.2.1 admits `caveat_hash("<64-lower-hex>")`."""
    lower_hex = "a" * 64
    datalog_caveat_validator_v02.validate([
        f'caveat_hash("{lower_hex}")',
    ])


def test_t_v021_02_schema_rejects_caveat_hash_with_uppercase_hex(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2.1-02 — v0.2.1 rejects upper-case hex (lower-case only).

    The dedicated pattern arm pins ``[0-9a-f]`` so a producer cannot
    smuggle a mixed-case or upper-case hex literal past the schema.
    Lower-case hex is the canonical pre-image form computed by
    :func:`canonical_caveat_set_hash` (returning :class:`bytes`,
    rendered via ``.hex()`` which is lower-case in Python).
    """
    upper_hex = "A" * 64
    errors = list(
        datalog_caveat_validator_v02.iter_errors([
            f'caveat_hash("{upper_hex}")',
        ])
    )
    assert errors, "Upper-case hex accidentally admitted"


def test_t_v021_03_schema_rejects_caveat_hash_with_wrong_length(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2.1-03 — v0.2.1 rejects hex literals shorter or longer than 64."""
    bad_samples = [
        'caveat_hash("abc")',
        'caveat_hash("' + "a" * 63 + '")',
        'caveat_hash("' + "a" * 65 + '")',
    ]
    for c in bad_samples:
        errors = list(datalog_caveat_validator_v02.iter_errors([c]))
        assert errors, f"Bad-length caveat_hash literal admitted: {c!r}"


def test_t_v021_04_schema_rejects_caveat_hash_with_unquoted_arg(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2.1-04 — v0.2.1 rejects bare-variable or unquoted argument.

    The promotion pattern arm pins the argument to a quoted hex
    literal; a producer emitting ``caveat_hash($h)`` or
    ``caveat_hash(deadbeef…)`` (no quotes) fails the schema. This
    protects the verifier-side recompute from variable-substitution
    smuggling attacks.
    """
    bad_samples = [
        'caveat_hash($h)',
        'caveat_hash(' + "a" * 64 + ')',
    ]
    for c in bad_samples:
        errors = list(datalog_caveat_validator_v02.iter_errors([c]))
        assert errors, f"Unquoted caveat_hash argument admitted: {c!r}"


def test_t_v021_05_schema_admission_is_additive_over_v020(
    datalog_caveat_validator_v02,
) -> None:
    """T-V0.2.1-05 — every v0.2.0 caveat shape still validates on v0.2.1.

    Additivity check: the 22 N1∪N2 predicate forms that were
    schema-admitted on v0.2.0 remain admitted on v0.2.1. The
    promotion of `caveat_hash` is a strict superset of the v0.2.0
    admission surface.
    """
    n1_n2_samples = [
        'action("read")',
        'env("prod")',
        'time($t), $t < 2026-12-31T23:59:59Z',
        'audience("role=consumer-A")',
        'operation("read")',
        'action_count_max(10)',
        'read_only(true)',
        'attests("4f9c8a3b")',
        'wat_anchor("manifest-id-x")',
        'rate_limit(100)',
        'agent_did("aip:web:wakir.dev/personas/cfo")',
        'parent_token("token-id")',
        'nonce("9f2b1c4a7d8e3f60a1b2c3d4e5f60718")',
        'spawn_counter_max(5)',
        'attenuation_depth_max(3)',
        'tee_required(true)',
        'allowed_methods("GET, POST")',
        'geo_region("eu-central")',
        'not_before(2026-05-01T00:00:00Z)',
        'not_after(2027-05-01T00:00:00Z)',
        'peer_org("aip:web:partner-a/personas/treasury-issuer")',
        'federation_route("wakir->partner-a->treasury")',
    ]
    for c in n1_n2_samples:
        datalog_caveat_validator_v02.validate([c])


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
