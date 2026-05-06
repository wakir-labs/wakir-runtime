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

Note:
- We import :mod:`shamir_mnemonic` directly only for the canonical
  test-vector verification. The Wakir wrapper API is exercised
  through :mod:`wirelang.identity.shamir_split`.
"""

from __future__ import annotations

import pytest

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

    This vector exercises the *combine* path through our wrapper
    (since we cannot reproduce the issuance with a fixed-RNG seed
    on top of the upstream library), and is the strongest external
    conformance signal we can ship without a custom RNG injection.
    """
    m1 = (
        "shadow pistol academic always adequate wildlife fancy gross "
        "oasis cylinder mustang wrist rescue view short owner flip "
        "making coding armed"
    )
    m2 = (
        "shadow pistol academic acid actress prayer class unknown "
        "daughter sweater depict flip twice unkind craft early "
        "superior advocate guest smoking"
    )
    expected_master = bytes.fromhex("b43ceb7e57a0ea8766221624d01b0864")

    # Wrap the canonical mnemonics into ShamirShare so the wrapper
    # combine path is exercised end-to-end.
    s1 = ShamirShare(
        share_index=0,
        share_mnemonic=m1,
        threshold=2,
        total_shares=3,
        member_index=0,
    )
    s2 = ShamirShare(
        share_index=1,
        share_mnemonic=m2,
        threshold=2,
        total_shares=3,
        member_index=1,
    )
    recovered = combine_shamir_shares([s1, s2], passphrase=b"TREZOR")
    assert recovered == expected_master


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


def test_combine_corrupted_share_raises_value_error() -> None:
    shares = split_master_secret(MASTER_32)
    # Corrupt a share by altering one word.
    bad_words = shares[0].share_mnemonic.split()
    bad_words[5] = "academic"  # any wordlist-valid but wrong word
    corrupted = ShamirShare(
        share_index=shares[0].share_index,
        share_mnemonic=" ".join(bad_words),
        threshold=shares[0].threshold,
        total_shares=shares[0].total_shares,
        member_index=shares[0].member_index,
    )
    with pytest.raises(ValueError):
        combine_shamir_shares([corrupted, shares[1]])


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
