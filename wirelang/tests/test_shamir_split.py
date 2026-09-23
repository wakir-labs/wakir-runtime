# SPDX-License-Identifier: Apache-2.0
"""Tests for the SLIP-39 cold-storage split wrapper.

Verifies:

- Round-trip split + combine for the Wakir Phase-1a default (2-of-3).
- Other valid configurations: 1-of-1, 3-of-5, threshold = total.
- The canonical SLIP-39 test vector "Basic sharing 2-of-3 (128 bits)"
  from python-shamir-mnemonic ``vectors.json`` (URL-200-stamped
  2026-05-06).
- Defensive checks: master length, threshold > total, threshold < 1,
  too few shares to combine, corrupted share.
- Corruption vectors that are deterministic by construction, with a
  negative control that proves an ineffective corruption fails loudly
  rather than passing silently (see the section comment below).

Note:
- We import:mod:`shamir_mnemonic` directly for the canonical
  test-vector verification, for the 1024-word lexicon used by the
  exhaustive corruption sweep, and for the RNG seam that pins the
  generated-share corruption vector. The Wakir wrapper API is
  exercised through:mod:`wirelang.identity.shamir_split`.
"""

from __future__ import annotations

import contextlib
import hashlib
import itertools

import pytest
import shamir_mnemonic as _sm

from wirelang.identity.shamir_split import (
    PHASE_1A_THRESHOLD,
    PHASE_1A_TOTAL_SHARES,
    ShamirShare,
    combine_shamir_shares,
    split_master_secret,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

# 32-byte master (Wakir persona-seed sized).
MASTER_32 = bytes.fromhex(
    "00112233445566778899aabbccddeeff" "00112233445566778899aabbccddeeff"
)
# 16-byte master (the smaller SLIP-39 entropy size, also valid).
MASTER_16 = bytes.fromhex("bb54aac4b89dc868ba37d9cc21b2cece")

# Canonical SLIP-39 vector "Basic sharing 2-of-3 (128 bits)" from
# python-shamir-mnemonic ``vectors.json``. Fixed strings, so any test
# built on them carries no randomness at all.
# Source URL-200-stamped 2026-09-23:
# <https://github.com/trezor/python-shamir-mnemonic>
CANONICAL_MNEMONIC_1 = (
    "shadow pistol academic always adequate wildlife fancy gross "
    "oasis cylinder mustang wrist rescue view short owner flip "
    "making coding armed"
)
CANONICAL_MNEMONIC_2 = (
    "shadow pistol academic acid actress prayer class unknown "
    "daughter sweater depict flip twice unkind craft early "
    "superior advocate guest smoking"
)
CANONICAL_MASTER = bytes.fromhex("b43ceb7e57a0ea8766221624d01b0864")


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


def test_default_2_of_3_round_trip_recovers_master() -> None:
    """Phase-1a default (consensus marker D-2): 2-of-3 round-trip."""
    shares = split_master_secret(MASTER_32)
    assert len(shares) == PHASE_1A_TOTAL_SHARES == 3
    assert all(s.threshold == PHASE_1A_THRESHOLD == 2 for s in shares)
    assert all(s.total_shares == 3 for s in shares)
    # Any 2 of 3 reconstruct.
    for i in range(3):
        for j in range(i + 1, 3):
            recovered = combine_shamir_shares([shares[i], shares[j]])
            assert recovered == MASTER_32, f"i={i} j={j} mismatch"


def test_1_of_1_trivial_split_round_trips() -> None:
    """1-of-1 is degenerate but valid; useful for unit-test isolation."""
    shares = split_master_secret(MASTER_16, shares_n=1, threshold_t=1)
    assert len(shares) == 1
    recovered = combine_shamir_shares(shares)
    assert recovered == MASTER_16


def test_3_of_5_split_round_trips_with_threshold_subset() -> None:
    shares = split_master_secret(MASTER_32, shares_n=5, threshold_t=3)
    assert len(shares) == 5
    # Pick a non-trivial subset of exactly threshold size.
    subset = [shares[0], shares[2], shares[4]]
    recovered = combine_shamir_shares(subset)
    assert recovered == MASTER_32


def test_threshold_equals_total_requires_all_shares() -> None:
    shares = split_master_secret(MASTER_16, shares_n=3, threshold_t=3)
    recovered = combine_shamir_shares(shares)
    assert recovered == MASTER_16


# ---------------------------------------------------------------------------
# SLIP-39 canonical test-vector verification
# ---------------------------------------------------------------------------


def test_slip39_canonical_basic_sharing_2_of_3_test_vector() -> None:
    """Canonical SLIP-39 "Basic sharing 2-of-3 (128 bits)" vector.

    Source: ``python-shamir-mnemonic/vectors.json`` (URL-200-stamped
    2026-05-06: <https://github.com/trezor/python-shamir-mnemonic>).
    Two of the three issued mnemonics combine under passphrase
    ``"TREZOR"`` to the documented master secret.

    This vector exercises the *combine* path through our wrapper and is
    the strongest external conformance signal available to us: the
    mnemonics are fixed strings produced by the spec authors, so it
    depends on no RNG of ours at all.

    Correction (2026-09-23): the earlier wording here claimed we
    "cannot reproduce the issuance with a fixed-RNG seed on top of the
    upstream library". That is not true -- the reference implementation
    exposes ``shamir_mnemonic.shamir.RANDOM_BYTES`` as a module-level
    seam and reassigns it itself in ``generate_vectors.py``. The
    corruption section below uses that seam. It does not change what
    *this* test is worth, but the claim was wrong and is withdrawn.
    """
    # Wrap the canonical mnemonics into ShamirShare so the wrapper
    # combine path is exercised end-to-end.
    s1 = ShamirShare(
        share_index=0,
        share_mnemonic=CANONICAL_MNEMONIC_1,
        threshold=2,
        total_shares=3,
        member_index=0,
    )
    s2 = ShamirShare(
        share_index=1,
        share_mnemonic=CANONICAL_MNEMONIC_2,
        threshold=2,
        total_shares=3,
        member_index=1,
    )
    recovered = combine_shamir_shares([s1, s2], passphrase=b"TREZOR")
    assert recovered == CANONICAL_MASTER


# ---------------------------------------------------------------------------
# Defensive / negative tests
# ---------------------------------------------------------------------------


def test_rejects_master_with_invalid_length() -> None:
    with pytest.raises(ValueError, match="master secret length"):
        split_master_secret(b"\x00" * 12)
    with pytest.raises(ValueError, match="master secret length"):
        split_master_secret(b"\x00" * 24)


def test_rejects_threshold_greater_than_shares_n() -> None:
    with pytest.raises(ValueError, match="threshold_t"):
        split_master_secret(MASTER_32, shares_n=3, threshold_t=4)


def test_rejects_threshold_below_one() -> None:
    with pytest.raises(ValueError, match="threshold_t"):
        split_master_secret(MASTER_32, shares_n=3, threshold_t=0)


def test_combine_too_few_shares_raises_value_error() -> None:
    shares = split_master_secret(MASTER_32)
    with pytest.raises(ValueError, match="at least 2"):
        combine_shamir_shares(shares[:1])


# ---------------------------------------------------------------------------
# Corruption vectors
# ---------------------------------------------------------------------------
#
# Why this section looks the way it does (Zone L, 2026-09-23).
#
# The earlier form of ``test_combine_corrupted_share_raises_value_error``
# generated a fresh 2-of-3 split and overwrote the word at index 5 of
# share 0 with the literal ``"academic"``. That is not a corruption; it
# is a corruption *attempt*. In a SLIP-39 mnemonic the first four words
# carry the identifier, the extendable flag, the iteration exponent and
# the group/member fields, and the last three words carry the RS1024
# checksum. Index 5 therefore sits inside the padded share-value field,
# whose content is effectively uniform over the 1024-word lexicon.
# ``"academic"`` is lexicon index 0. Whenever the draw already put
# ``"academic"`` at index 5, the assignment changed nothing, the share
# stayed valid, ``combine_shamir_shares`` returned the master, and
# pytest reported ``DID NOT RAISE ValueError``.
#
# Measured on this tree (shamir-mnemonic 0.3.0, CPython 3.14.7):
#
# - Exhaustive sweep over all 1024 lexicon words at the corruption
#   site: 1023 replacements raise, exactly one does not -- the word
#   that is already there. There is no second mechanism.
# - The rate at which the old vector degenerated is therefore the rate
#   at which the draw hits one specific lexicon entry, i.e. ~1/1024.
#
# The repair is neither a retry loop nor a ``flaky`` marker. Two
# independent changes remove the randomness from the outcome:
#
# 1. ``corrupt_mnemonic_word`` refuses a replacement that equals the
#    word already at the position. An ineffective corruption now fails
#    loudly and by name (``IneffectiveCorruption``) instead of turning
#    into a silent pass of the assertion under test.
# 2. The generated-share vector runs under a pinned RNG, so the
#    mnemonic under corruption is the same string on every run. The
#    hook used for this is the one upstream uses for the same purpose:
#    ``shamir_mnemonic.shamir.RANDOM_BYTES`` is reassigned in the
#    reference implementation's own ``generate_vectors.py`` (line 40,
#    HTTP 200 on 2026-09-23).
#
# ``test_corruption_helper_rejects_a_no_op_replacement`` is the
# negative control: it proves that the repaired construction goes red
# against a deliberately ineffective corruption rather than green.


class IneffectiveCorruption(AssertionError):
    """A corruption vector that would leave the mnemonic unchanged.

    Raised by :func:`corrupt_mnemonic_word`. It is an
    :class:`AssertionError` on purpose: a test that cannot build the
    input it claims to test has not passed, it has failed to run.
    """


def corrupt_mnemonic_word(mnemonic: str, position: int, replacement: str) -> str:
    """Replace one word of ``mnemonic`` and prove the replacement bites.

    Args:
        mnemonic: a SLIP-39 mnemonic (space-separated words).
        position: zero-based word index to overwrite.
        replacement: the word to write there. MUST differ from the word
            currently at ``position``.

    Returns:
        The corrupted mnemonic.

    Raises:
        IndexError: if ``position`` is outside the mnemonic.
        IneffectiveCorruption: if ``replacement`` is already the word at
            ``position``, i.e. the "corruption" would be a no-op and the
            resulting share would still be valid.
    """
    words = mnemonic.split()
    if not 0 <= position < len(words):
        raise IndexError(
            f"corruption position {position} is outside a {len(words)}-word "
            f"mnemonic"
        )
    if words[position] == replacement:
        raise IneffectiveCorruption(
            f"corruption at word {position} is a no-op: the mnemonic already "
            f"carries {replacement!r} at that position, so the resulting "
            f"share would still be valid and combine would succeed"
        )
    words[position] = replacement
    return " ".join(words)


def _pinned_random_bytes(seed: bytes):
    """Return a deterministic ``RANDOM_BYTES``-compatible callable."""
    counter = itertools.count()

    def random_bytes(length: int) -> bytes:
        out = bytearray()
        while len(out) < length:
            out += hashlib.shake_256(
                seed + next(counter).to_bytes(8, "big")
            ).digest(32)
        return bytes(out[:length])

    return random_bytes


@contextlib.contextmanager
def pinned_shamir_rng(seed: bytes):
    """Pin the reference implementation's RNG for the duration of a test.

    ``shamir_mnemonic.shamir.RANDOM_BYTES`` is the module-level seam the
    reference implementation itself reassigns to produce reproducible
    vectors (``generate_vectors.py``). If a future release removes it,
    this fails by name rather than silently reverting to a random draw.
    """
    module = _sm.shamir
    if not hasattr(module, "RANDOM_BYTES"):  # pragma: no cover - guard
        pytest.fail(
            "shamir_mnemonic.shamir.RANDOM_BYTES is gone; the deterministic "
            "corruption vector below would silently become probabilistic "
            "again. Re-pin the RNG against the new seam before relaxing "
            "this guard."
        )
    previous = module.RANDOM_BYTES
    module.RANDOM_BYTES = _pinned_random_bytes(seed)
    try:
        yield
    finally:
        module.RANDOM_BYTES = previous


# The corruption site. Words 0..3 are header fields and words -3..-1 are
# the RS1024 checksum; index 5 is inside the share-value field of both a
# 20-word (128-bit) and a 33-word (256-bit) mnemonic.
CORRUPTION_POSITION = 5

# Lexicon index 0. Named here so the one constant that made the old
# vector degenerate is visible rather than buried in an assignment.
CORRUPTION_WORD = "academic"

# Arbitrary but fixed. Any seed works; this one is pinned so the
# mnemonic under corruption is the same string on every run.
CORRUPTION_RNG_SEED = b"wakir/zone-l/shamir-corruption-vector/2026-09-23"


def test_pinned_rng_makes_the_split_reproducible() -> None:
    """The pinned RNG must actually pin the split.

    Without this, "fixed seed" is an assumption rather than a property,
    and the deterministic corruption vector below would rest on it.
    """
    before = _sm.shamir.RANDOM_BYTES
    with pinned_shamir_rng(CORRUPTION_RNG_SEED):
        assert _sm.shamir.RANDOM_BYTES is not before
        first = [s.share_mnemonic for s in split_master_secret(MASTER_32)]
    with pinned_shamir_rng(CORRUPTION_RNG_SEED):
        second = [s.share_mnemonic for s in split_master_secret(MASTER_32)]
    assert first == second
    assert _sm.shamir.RANDOM_BYTES is before, (
        "the pin leaked out of the context manager; every later test in the "
        "session would run against a fixed RNG"
    )


def test_combine_corrupted_share_raises_value_error() -> None:
    """A generated share with one altered word must be rejected.

    Deterministic by construction: pinned RNG, named corruption
    position, named replacement word, and a helper that refuses a
    replacement which would not change the mnemonic.
    """
    with pinned_shamir_rng(CORRUPTION_RNG_SEED):
        shares = split_master_secret(MASTER_32)
    corrupted = ShamirShare(
        share_index=shares[0].share_index,
        share_mnemonic=corrupt_mnemonic_word(
            shares[0].share_mnemonic, CORRUPTION_POSITION, CORRUPTION_WORD
        ),
        threshold=shares[0].threshold,
        total_shares=shares[0].total_shares,
        member_index=shares[0].member_index,
    )
    with pytest.raises(ValueError):
        combine_shamir_shares([corrupted, shares[1]])


def test_combine_corrupted_canonical_share_raises_value_error() -> None:
    """Same property on a mnemonic that carries no randomness at all.

    The canonical SLIP-39 vector is a fixed string, so this vector is
    independent of both our RNG pin and the reference implementation's
    generation path.
    """
    corrupted = ShamirShare(
        share_index=0,
        share_mnemonic=corrupt_mnemonic_word(
            CANONICAL_MNEMONIC_1, CORRUPTION_POSITION, CORRUPTION_WORD
        ),
        threshold=2,
        total_shares=3,
        member_index=0,
    )
    intact = ShamirShare(
        share_index=1,
        share_mnemonic=CANONICAL_MNEMONIC_2,
        threshold=2,
        total_shares=3,
        member_index=1,
    )
    with pytest.raises(ValueError):
        combine_shamir_shares([corrupted, intact], passphrase=b"TREZOR")


def test_corruption_helper_rejects_a_no_op_replacement() -> None:
    """Negative control for the two tests above.

    Hand the helper the word that is already at the position -- exactly
    the situation that made the old vector pass silently -- and it must
    go red, by name.
    """
    already_there = CANONICAL_MNEMONIC_1.split()[CORRUPTION_POSITION]
    with pytest.raises(IneffectiveCorruption):
        corrupt_mnemonic_word(
            CANONICAL_MNEMONIC_1, CORRUPTION_POSITION, already_there
        )
    # The same guard on the generated-share path.
    with pinned_shamir_rng(CORRUPTION_RNG_SEED):
        shares = split_master_secret(MASTER_32)
    mnemonic = shares[0].share_mnemonic
    with pytest.raises(IneffectiveCorruption):
        corrupt_mnemonic_word(
            mnemonic, CORRUPTION_POSITION, mnemonic.split()[CORRUPTION_POSITION]
        )


def test_every_effective_single_word_change_at_the_site_is_rejected() -> None:
    """Exhaustive statement of the property, over the whole lexicon.

    For the corruption site, each of the 1024 lexicon words either is
    the word already present (no corruption, combine succeeds and
    returns the documented master) or produces a mnemonic that
    ``combine_shamir_shares`` rejects with :class:`ValueError`. There is
    no third outcome, and in particular no word that silently yields a
    *different* master.
    """
    intact = ShamirShare(
        share_index=1,
        share_mnemonic=CANONICAL_MNEMONIC_2,
        threshold=2,
        total_shares=3,
        member_index=1,
    )
    words = CANONICAL_MNEMONIC_1.split()
    no_ops: list[str] = []
    silent: list[str] = []
    for candidate in _sm.wordlist.WORDLIST:
        if candidate == words[CORRUPTION_POSITION]:
            no_ops.append(candidate)
            continue
        corrupted = ShamirShare(
            share_index=0,
            share_mnemonic=corrupt_mnemonic_word(
                CANONICAL_MNEMONIC_1, CORRUPTION_POSITION, candidate
            ),
            threshold=2,
            total_shares=3,
            member_index=0,
        )
        try:
            combine_shamir_shares([corrupted, intact], passphrase=b"TREZOR")
        except ValueError:
            continue
        silent.append(candidate)

    assert silent == [], (
        f"{len(silent)} corrupted mnemonic(s) combined without raising: "
        f"{silent[:5]}"
    )
    assert no_ops == [words[CORRUPTION_POSITION]], (
        "exactly one lexicon word must be a no-op at the corruption site "
        f"(the one already there); got {no_ops}"
    )


def test_header_words_are_constant_for_the_phase_1a_layout() -> None:
    """Why the corruption site is not a header word.

    Word 2 of a SLIP-39 mnemonic packs group index, group threshold and
    the top bits of the group count. For the Wakir single-group layout
    all of those are zero, so word 2 is the lexicon's index-0 word --
    ``"academic"`` -- for *every* share we ever issue. A corruption that
    wrote ``"academic"`` there would be a no-op 100% of the time rather
    than ~0.1% of the time: the same defect, fully degenerate.

    This test exists so that a future edit which moves the corruption
    site has the trap written down next to it.
    """
    shares = split_master_secret(MASTER_32)
    assert {s.share_mnemonic.split()[2] for s in shares} == {"academic"}
    for share in shares:
        with pytest.raises(IneffectiveCorruption):
            corrupt_mnemonic_word(share.share_mnemonic, 2, "academic")


def test_share_data_is_32_bytes_for_256bit_master() -> None:
    """The SLIP-39 share value mirrors the master entropy size."""
    shares = split_master_secret(MASTER_32)
    for s in shares:
        assert len(s.share_data) == 32


def test_share_data_is_16_bytes_for_128bit_master() -> None:
    shares = split_master_secret(MASTER_16, shares_n=3, threshold_t=2)
    for s in shares:
        assert len(s.share_data) == 16


def test_share_index_and_member_index_align_for_single_group_layout() -> None:
    """Phase-1a single-group layout: share_index == member_index."""
    shares = split_master_secret(MASTER_32)
    for s in shares:
        assert s.share_index == s.member_index


def test_combine_rejects_more_than_threshold_shares() -> None:
    """SLIP-39 expects exactly ``threshold`` shares for combine.

    Supplying more than the threshold (e.g., all 3 of a 2-of-3 split)
    is rejected by the reference impl rather than silently using the
    first T. We propagate that strictness so a caller that accidentally
    over-supplies sees the issue immediately.
    """
    shares = split_master_secret(MASTER_32)
    with pytest.raises(ValueError, match="Wrong number of mnemonics"):
        combine_shamir_shares(shares)  # all 3, but threshold is 2
