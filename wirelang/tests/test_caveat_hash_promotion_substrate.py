# SPDX-License-Identifier: Apache-2.0
"""ADR-0052 caveat_hash Class-P Promotion — Substrate + Ratified-Promotion Tests.

These tests cover two phases of the ``caveat_hash(self_hash)`` Class-P
promotion path:

Phase A (substrate readiness, T-CHP-01..06 + aux, Sprint-2 Tag-2):
  Verifier-side algorithm "extract self_hash, recompute over the
  surrounding caveat-set excluding the predicate, compare" defined on
  top of §4-CSC. Recomputation is idempotent and order-independent
  (a property inherited from §4-CSC sort+dedup). Promotion is
  backward-compatible with TV-W-2 pin stability: the
  `caveat_set_hashes` already pinned in TV-W-2 fixtures stay
  byte-stable when a caveat-set is augmented by a `caveat_hash(...)`
  predicate that *names the very same hash* — because the predicate
  itself is excluded from the recomputation.

Phase B (ratified-promotion, T-CHP-07..11, Sprint-6 Tag-8):
  ADR-0052 (approved 2026-05-12) ratified Option B — promotion as a
  v0.2.0 → v0.2.1 schema patch. These additional tests pin the
  ratified surface end-to-end: the dedicated pattern-arm admits
  exactly the canonical literal shape, the TV-W-2 golden
  ``pin_pack_sha256`` recomputes byte-stably under the promotion,
  and the residual reservation of ``persona_pin`` still bites at
  the schema level.

Test IDs T-CHP-01..06 follow the §4-CSC test naming convention;
T-CHP-07..11 follow the ADR-0052 ratification-test convention.

Pinned to ADR-0052 (``decisions/0052-class-p-promotion-caveat-hash.md``).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from wirelang.canonical.caveat_set import (
    canonical_caveat_set_bytes,
    canonical_caveat_set_hash,
    canonicalize_caveat_set,
)


# ---------------------------------------------------------------------------
# Verifier-side helper — the algorithm the promotion ADR ratifies
# ---------------------------------------------------------------------------

# Per the promotion-ADR draft §3, a verifier processing a caveat-set
# that contains exactly one `caveat_hash("<64-hex>")` predicate computes
# self_hash over the *remaining* caveats (after §4-CSC). The predicate
# itself is excluded so the hash is well-defined.
_CAVEAT_HASH_RE = re.compile(
    r'^\s*caveat_hash\(\s*"([0-9a-f]{64})"\s*\)\s*$'
)


def _split_self_hash_predicate(
    caveats: list[str],
) -> tuple[list[str], list[bytes]]:
    """Return (remaining-caveats, list-of-declared-hashes).

    The declared list preserves the order encountered (used for the
    'exactly one' check in the promotion ADR §3).
    """
    remaining: list[str] = []
    declared: list[bytes] = []
    for c in caveats:
        m = _CAVEAT_HASH_RE.match(c)
        if m is None:
            remaining.append(c)
        else:
            declared.append(bytes.fromhex(m.group(1)))
    return remaining, declared


def verify_caveat_hash_self_reference(caveats: list[str]) -> bool:
    """Return True iff the (single) declared self_hash matches §4-CSC of the rest.

    Promotion-ADR §3 verifier rule:

      * Zero `caveat_hash` predicates: predicate not present → True
        (the caveat-set is not constrained by self-reference).
      * Exactly one `caveat_hash("<hex>")` predicate: True iff
        `bytes.fromhex(hex) == canonical_caveat_set_hash(rest)`.
      * Two or more: False (split-attack guard, ADR §4.2).
    """
    remaining, declared = _split_self_hash_predicate(caveats)
    if not declared:
        return True
    if len(declared) > 1:
        return False
    expected = canonical_caveat_set_hash(remaining)
    return declared[0] == expected


# ---------------------------------------------------------------------------
# T-CHP-01 — declared hash matches §4-CSC over the remaining caveats
# ---------------------------------------------------------------------------


def test_chp_01_declared_self_hash_matches_canonical_recompute() -> None:
    rest = [
        'time($t), $t < 2026-12-31T23:59:59Z',
        'action("read"), action("write")',
        'persona("alice")',
    ]
    declared = canonical_caveat_set_hash(rest).hex()
    full = rest + [f'caveat_hash("{declared}")']
    assert verify_caveat_hash_self_reference(full) is True


# ---------------------------------------------------------------------------
# T-CHP-02 — hash mismatch is rejected
# ---------------------------------------------------------------------------


def test_chp_02_mismatched_self_hash_rejected() -> None:
    rest = ['action("read")']
    bogus = "00" * 32
    full = rest + [f'caveat_hash("{bogus}")']
    assert verify_caveat_hash_self_reference(full) is False


# ---------------------------------------------------------------------------
# T-CHP-03 — order-independence (Phase-2 §4-CSC sort step)
# ---------------------------------------------------------------------------


def test_chp_03_self_hash_is_order_independent() -> None:
    """A producer that emits caveats in a different order produces the
    same self_hash. This invariant is inherited from §4-CSC sort.
    """
    canonical_a = [
        'action("read")',
        'persona("alice")',
        'time($t), $t < 2026-06-01T00:00:00Z',
    ]
    canonical_b = list(reversed(canonical_a))
    h_a = canonical_caveat_set_hash(canonical_a)
    h_b = canonical_caveat_set_hash(canonical_b)
    assert h_a == h_b
    full_a = canonical_a + [f'caveat_hash("{h_a.hex()}")']
    full_b = canonical_b + [f'caveat_hash("{h_b.hex()}")']
    assert verify_caveat_hash_self_reference(full_a) is True
    assert verify_caveat_hash_self_reference(full_b) is True


# ---------------------------------------------------------------------------
# T-CHP-04 — split-attack guard (two self-references rejected)
# ---------------------------------------------------------------------------


def test_chp_04_two_self_hash_predicates_rejected() -> None:
    rest = ['action("read")']
    h1 = canonical_caveat_set_hash(rest).hex()
    full = rest + [f'caveat_hash("{h1}")', f'caveat_hash("{h1}")']
    assert verify_caveat_hash_self_reference(full) is False


# ---------------------------------------------------------------------------
# T-CHP-05 — empty self-reference (no predicate) is permissive
# ---------------------------------------------------------------------------


def test_chp_05_no_self_hash_predicate_is_permissive() -> None:
    """Backward compatibility: a v0.1.x caveat-set without
    `caveat_hash` is still well-formed under the promotion rule.
    """
    rest = ['action("read")', 'persona("alice")']
    assert verify_caveat_hash_self_reference(rest) is True


# ---------------------------------------------------------------------------
# T-CHP-06 — TV-W-2 pin-stability is preserved
# ---------------------------------------------------------------------------


def test_chp_06_caveat_set_hash_unchanged_when_predicate_excluded() -> None:
    """Promotion is a no-op for the TV-W-2 `caveat_set_hashes` pin field
    *as long as* the verifier excludes the `caveat_hash` predicate from
    the recomputation. This test pins that invariant explicitly.
    """
    rest = [
        'action("read")',
        'persona("alice")',
        'time($t), $t < 2026-12-31T23:59:59Z',
    ]
    h_pre = canonical_caveat_set_hash(rest)
    full = rest + [f'caveat_hash("{h_pre.hex()}")']
    # Verifier strips the predicate before recompute.
    remaining, _ = _split_self_hash_predicate(full)
    h_post = canonical_caveat_set_hash(remaining)
    assert h_pre == h_post, (
        "TV-W-2 pin would shift if verifier did not exclude predicate"
    )


# ---------------------------------------------------------------------------
# Sanity: pure-§4-CSC primitives still consistent under augmentation
# ---------------------------------------------------------------------------


def test_chp_aux_canonical_bytes_are_deterministic_under_dedup() -> None:
    rest = ['action("read")', 'action("read")']
    bytes_a = canonical_caveat_set_bytes(rest)
    bytes_b = canonical_caveat_set_bytes(['action("read")'])
    assert bytes_a == bytes_b
    canon = canonicalize_caveat_set(rest)
    assert canon == ['action("read")']
    # Hash matches what verify_caveat_hash_self_reference will recompute.
    h = hashlib.sha256(bytes_a).digest()
    assert h == canonical_caveat_set_hash(rest)


# ===========================================================================
# Phase B — ADR-0052 ratified-promotion tests (Sprint-6 Tag-8)
# ===========================================================================
#
# These tests anchor the v0.2.0 → v0.2.1 schema bump. They are the
# Mira-Trigger-pflichtige acceptance for Tag-8: schema admits the
# canonical literal, the TV-W-2 golden pin-pack hash recomputes
# byte-equal, the residual Class-P reservation (`persona_pin`)
# still bites, and the v0.2.1 ratification surface is materialised.


WIRELANG_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PATH = WIRELANG_ROOT / "schemas" / "datalog-caveat.json"
_TV_W_2_PIN_PACK_PATH = (
    WIRELANG_ROOT / "tests" / "fixtures" / "tv-w-2" / "pin-pack.json"
)

# ADR-0052 substance vorlage anchor: the TV-W-2 pin-pack sha256 that
# the promotion MUST keep byte-stable. This is the embedded
# ``pin_pack_sha256`` slot in the TV-W-2 golden fixture; it is the
# hash of the JCS-canonical body without the hash slot.
_TV_W_2_PIN_PACK_HASH_GOLDEN = (
    "ddf115456893bd5b15c0ab1c501f22a0b68caaf39a06ec2d2b103e940bdd7532"
)


# ---------------------------------------------------------------------------
# T-CHP-07 — TV-W-2 pin-pack hash byte-stable under promotion (golden hex)
# ---------------------------------------------------------------------------


def test_chp_07_tv_w_2_pin_pack_hash_golden_matches() -> None:
    """T-CHP-07 — golden ``pin_pack_sha256`` matches ADR-0052 vorlage.

    Reads the TV-W-2 golden fixture and asserts that the embedded
    ``pin_pack_sha256`` field is byte-equal to the hash recorded in
    ADR-0052's substance vorlage (``ddf11545…d7532``). The v0.2.1
    promotion is **not** a producer-side change to TV-W-2 — the
    builder still computes the same caveat-set hashes per §4-CSC
    because the recompute algorithm excludes ``caveat_hash`` from
    the input set. This test is therefore a pin-stability beleg in
    the strict sense: the bytes that were pinned at Tag-16 are the
    bytes that are still pinned post-promotion.
    """
    with _TV_W_2_PIN_PACK_PATH.open("r", encoding="utf-8") as fh:
        pin_pack = json.load(fh)
    embedded = pin_pack["pin_pack_sha256"]
    assert embedded == _TV_W_2_PIN_PACK_HASH_GOLDEN, (
        "TV-W-2 pin-pack hash drifted from ADR-0052 vorlage; "
        f"observed {embedded!r}, expected {_TV_W_2_PIN_PACK_HASH_GOLDEN!r}"
    )


# ---------------------------------------------------------------------------
# T-CHP-08 — caveat-set-hash byte-equal under augment-with-self-reference
# ---------------------------------------------------------------------------


def test_chp_08_caveat_set_hash_byte_equal_under_augment() -> None:
    """T-CHP-08 — augmenting a caveat-set with ``caveat_hash(...)`` does
    NOT shift the §4-CSC hash of the *underlying* caveats.

    This is the explicit operationalisation of T-CHP-06 against every
    TV-W-2-class caveat-set shape. The verifier strips the
    self-reference predicate before recompute (algorithm definition
    in ADR-0052 §3); the hash of the stripped set equals the hash of
    the original set. For TV-W-2's three blocks we synthesise the
    augmented form, strip, and recompute — and pin byte-equality.
    """
    tv_w_2_block_caveats = [
        # Block 0
        [
            'check if env("prod")',
            'check if action("read.balance")',
            'check if audience("role=consumer-A")',
        ],
        # Block 1
        [
            'check if read_only(true)',
            'check if action("read.balance")',
        ],
        # Block 2
        [
            'check if rate_limit($n), $n <= 100',
        ],
    ]
    for caveats in tv_w_2_block_caveats:
        h_pre = canonical_caveat_set_hash(caveats)
        augmented = caveats + [f'caveat_hash("{h_pre.hex()}")']
        remaining, declared = _split_self_hash_predicate(augmented)
        assert remaining == caveats, (
            "Strip step changed the caveat-set body unexpectedly"
        )
        assert len(declared) == 1
        h_post = canonical_caveat_set_hash(remaining)
        assert h_pre == h_post


# ---------------------------------------------------------------------------
# T-CHP-09 — v0.2.1 schema `$id` is the promotion-target version
# ---------------------------------------------------------------------------


def test_chp_09_schema_id_is_021_post_promotion() -> None:
    """T-CHP-09 — ``datalog-caveat.json`` ``$id`` is bumped to ``0.2.1``.

    The schema-file bump is the load-bearing ratification artefact
    for ADR-0052. This probe pins the ``$id`` so a future accidental
    revert to ``0.2.0`` (or skip-ahead to ``0.3.0``) fails fast.
    """
    with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    assert schema["$id"] == (
        "https://wakir.dev/wirelang/schema/datalog-caveat/0.2.1"
    ), schema["$id"]


# ---------------------------------------------------------------------------
# T-CHP-10 — schema-level rejection of canonical-shape mutations
# ---------------------------------------------------------------------------


def test_chp_10_schema_pattern_rejects_alias_caveat_self_hash() -> None:
    """T-CHP-10 — the §3.5 alias ``caveat_self_hash`` is NOT admitted.

    The Phase-2 ratification §3.5 extends reservation to obvious
    aliases (``caveat_self_hash`` listed verbatim). The v0.2.1
    promotion lands the canonical name ``caveat_hash`` only — the
    alias stays unadmitted. A v0.2.1 producer that accidentally emits
    ``caveat_self_hash(...)`` MUST fail at the schema-validation
    boundary, NOT at the Datalog-evaluation boundary.
    """
    # Construct against the regex pattern directly so we do not depend
    # on jsonschema being importable (Phase-1b sandbox-CI lane).
    with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    pattern = re.compile(schema["items"]["pattern"])
    alias = 'caveat_self_hash("' + "a" * 64 + '")'
    assert pattern.match(alias) is None, (
        "Alias caveat_self_hash accidentally admitted by v0.2.1 schema"
    )


# ---------------------------------------------------------------------------
# T-CHP-11 — schema pattern admits the canonical literal but not variants
# ---------------------------------------------------------------------------


def test_chp_11_schema_pattern_admits_canonical_literal() -> None:
    """T-CHP-11 — the dedicated promotion pattern arm matches exactly.

    Probes the second alternation arm of the v0.2.1 pattern:
    ``^\\s*caveat_hash\\(\\s*"[0-9a-f]{64}"\\s*\\)\\s*$``. The arm
    admits leading/trailing whitespace (so a producer that emits a
    cosmetically-indented caveat string still validates) but pins
    the inner shape to a quoted 64-char lower-hex literal. Variable
    arguments (``$h``) and upper-case hex are rejected.
    """
    with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    pattern = re.compile(schema["items"]["pattern"])

    good = 'caveat_hash("' + "0" * 64 + '")'
    assert pattern.match(good) is not None

    # Leading whitespace is admitted by the dedicated arm (per
    # §7 algorithmischen Pre-Image stripping rule).
    indented = '  caveat_hash("' + "0" * 64 + '")  '
    assert pattern.match(indented) is not None

    bad_shapes = [
        'caveat_hash($h)',
        'caveat_hash("' + "A" * 64 + '")',
        'caveat_hash("' + "0" * 63 + '")',
        'caveat_hash(' + "0" * 64 + ')',
        'caveat_hash("not-hex-content-here-not-hex-content-here-not-hex-cont")',
    ]
    for s in bad_shapes:
        assert pattern.match(s) is None, (
            f"v0.2.1 schema arm accidentally admitted variant: {s!r}"
        )
