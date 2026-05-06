# SPDX-License-Identifier: Apache-2.0
"""Tests for the quarterly recovery-drill simulator.

Verifies:

- The Phase-1a default 2-of-3 layout passes a one-loss drill on every
  share index (consensus marker D-2: any single share loss is
  recoverable).
- A 3-of-5 layout passes a one-loss drill (recovery uses any 3 of
  the remaining 4).
- A 2-of-2 layout *fails* a one-loss drill with ``threshold_met=False``
  because any loss is fatal in that configuration.
- A drill against an explicit ``expected_master`` flags mismatches.
- Defensive checks: empty share list, threshold mismatch.
"""

from __future__ import annotations

import pytest

from wirelang.identity.shamir_split import (
    ShamirShare,
    split_master_secret,
)
from wirelang.identity.recovery_drill import (
    RecoveryDrillResult,
    simulate_recovery,
)


MASTER_32 = bytes.fromhex(
    "00112233445566778899aabbccddeeff" "00112233445566778899aabbccddeeff"
)


def test_phase_1a_default_2_of_3_drill_succeeds() -> None:
    """Phase-1a 2-of-3 (Wakir convention): drill must always pass."""
    shares = split_master_secret(MASTER_32)
    result = simulate_recovery(shares, threshold=2, expected_master=MASTER_32)
    assert result.success is True
    assert result.threshold_met is True
    assert result.attempts == 3
    assert all(ok for _, ok in result.per_round_outcomes)
    assert result.recovered_master == MASTER_32
    assert result.lost_share_index is None


def test_3_of_5_drill_succeeds_against_one_loss() -> None:
    shares = split_master_secret(MASTER_32, shares_n=5, threshold_t=3)
    result = simulate_recovery(shares, threshold=3, expected_master=MASTER_32)
    assert result.success is True
    assert result.attempts == 5
    assert result.threshold_met is True


def test_2_of_2_drill_fails_with_threshold_not_met_flag() -> None:
    """2-of-2 has no margin; one loss is fatal — drill records this."""
    shares = split_master_secret(MASTER_32, shares_n=2, threshold_t=2)
    result = simulate_recovery(shares, threshold=2)
    assert result.success is False
    assert result.threshold_met is False
    assert result.attempts == 0
    assert result.recovered_master is None


def test_drill_without_expected_master_only_checks_recovery_succeeds() -> None:
    """If no expected master is supplied the drill still validates structure."""
    shares = split_master_secret(MASTER_32)
    result = simulate_recovery(shares, threshold=2)
    assert result.success is True
    # recovered_master is populated even without external comparison.
    assert result.recovered_master == MASTER_32


def test_drill_flags_master_mismatch_when_expected_master_wrong() -> None:
    """If the operator supplies a wrong expected master the drill fails."""
    shares = split_master_secret(MASTER_32)
    wrong_master = bytes(32)
    result = simulate_recovery(
        shares, threshold=2, expected_master=wrong_master
    )
    assert result.success is False
    assert result.threshold_met is True
    # All three rounds report mismatch.
    assert all(not ok for _, ok in result.per_round_outcomes)
    assert result.lost_share_index in {0, 1, 2}


def test_drill_rejects_empty_shares_list() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        simulate_recovery([], threshold=2)


def test_drill_rejects_threshold_below_one() -> None:
    shares = split_master_secret(MASTER_32)
    with pytest.raises(ValueError, match="threshold"):
        simulate_recovery(shares, threshold=0)


def test_drill_rejects_share_threshold_mismatch() -> None:
    """Drill cross-checks each share's recorded threshold."""
    shares = split_master_secret(MASTER_32)
    # Forge a share with a wrong recorded threshold.
    forged = ShamirShare(
        share_index=shares[0].share_index,
        share_mnemonic=shares[0].share_mnemonic,
        threshold=99,  # bogus
        total_shares=shares[0].total_shares,
        member_index=shares[0].member_index,
    )
    bag = [forged] + list(shares[1:])
    with pytest.raises(ValueError, match="threshold"):
        simulate_recovery(bag, threshold=2)


def test_drill_outcome_per_round_records_lost_index() -> None:
    """The per-round trace MUST cover every share once."""
    shares = split_master_secret(MASTER_32)
    result = simulate_recovery(shares, threshold=2)
    indices = sorted(idx for idx, _ in result.per_round_outcomes)
    assert indices == [0, 1, 2]


def test_drill_result_dataclass_is_frozen() -> None:
    """Defensive: the result is intended for audit-trail integration."""
    shares = split_master_secret(MASTER_32)
    result = simulate_recovery(shares, threshold=2)
    with pytest.raises((AttributeError, Exception)):
        # frozen dataclasses raise FrozenInstanceError; tolerant match.
        result.success = False  # type: ignore[misc]
    # Ensure it is the expected type.
    assert isinstance(result, RecoveryDrillResult)
