# SPDX-License-Identifier: Apache-2.0
"""S2-1 caveat_hash Class-P Promotion — Substrate-Validation-Tests.

These tests prepare the ground for the proposed Class-P promotion of
``caveat_hash(self_hash)`` from "reserved" to "ratified N1" status.

They do not change the schema (the schema continues to reject
``caveat_hash`` until the promotion ADR is approved). What they assert
is the *substrate readiness* for the promotion:

  * The verifier-side algorithm "extract self_hash, recompute over
    the surrounding caveat-set excluding the predicate, compare" is
    well-defined on top of §4-CSC.
  * The recomputation is idempotent and order-independent (a property
    inherited from §4-CSC sort+dedup).
  * The promotion is backward-compatible with TV-W-2 pin stability:
    the `caveat_set_hashes` already pinned in TV-W-2 fixtures stay
    byte-stable when a caveat-set is augmented by a `caveat_hash(...)`
    predicate that *names the very same hash* — because the predicate
    itself is excluded from the recomputation.

Test IDs T-CHP-01..06 follow the §4-CSC test naming convention.

Pinned to the promotion-ADR draft at
``decisions/proposed-caveat-hash-class-p-promotion.md`` (Sprint-2 Tag-2).
"""

from __future__ import annotations

import hashlib
import re

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
