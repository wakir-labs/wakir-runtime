# SPDX-License-Identifier: Apache-2.0
"""Quarterly recovery-drill simulator for SLIP-39 cold-storage shares.

The drill validates the operational invariant of the Wakir 2-of-3
cold-storage pattern (ADR-0023b §3, consensus marker D-2):

> If any single share is permanently lost, the remaining shares MUST
> still reconstruct the master secret.

Recovery-drill cadence is **quarterly** by Wakir convention (consensus
marker D-2): on the first business day of each quarter, the operator
runs this simulator over the live share inventory to confirm that
recovery still works on the current artefacts. The simulator does not
touch the artefacts; it consumes the in-memory :class:`ShamirShare`
list returned by :func:`wirelang.identity.shamir_split.split_master_secret`.

Failure modes the drill catches:

- A share artefact has degraded (engraving error, photo corruption,
  paper rot) and re-decoding produces a different mnemonic than the
  one originally issued.
- A share was issued under a different generation (passphrase or
  extendable-flag drift) and no longer combines with its siblings.
- The recorded ``threshold`` no longer matches the actual SLIP-39
  parameters embedded in the share mnemonic.

The drill does not by itself catch physical loss — it consumes a
list of present shares and *simulates* the loss of one of them.
Physical-presence verification is the operator's job before invoking
the drill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .shamir_split import ShamirShare, combine_shamir_shares


@dataclass(frozen=True)
class RecoveryDrillResult:
    """Outcome of one quarterly recovery-drill run.

    Attributes:
        success: True iff recovery succeeded with the lossy subset and
            (if a known master is supplied) matched the expected master.
        attempts: number of share-loss simulations executed (one per
            share index in a comprehensive drill).
        threshold_met: True iff each simulated subset still met the
            recorded threshold (i.e., the input set was at least
            ``threshold + 1`` shares deep). When False, the drill
            reported *correctly* that the configuration is one-loss-
            fatal — recovery itself was not attempted on those rounds.
        lost_share_index: ``share_index`` of the share that was
            simulated as lost in the *failing* round, or ``None`` if
            all rounds succeeded.
        recovered_master: bytes recovered in the most recent successful
            attempt, or ``None`` if no attempt succeeded.
        per_round_outcomes: list of per-round ``(lost_index,
            recovered_ok)`` tuples for audit-trail integration.
    """

    success: bool
    attempts: int
    threshold_met: bool
    lost_share_index: int | None
    recovered_master: bytes | None
    per_round_outcomes: list[tuple[int, bool]] = field(default_factory=list)


def simulate_recovery(
    shares: Sequence[ShamirShare],
    threshold: int,
    *,
    expected_master: bytes | None = None,
    passphrase: bytes = b"",
) -> RecoveryDrillResult:
    """Simulate share loss and verify recovery for each one-loss case.

    For each share in the input set, the drill removes that share,
    attempts recovery from the remaining shares, and records the
    outcome. A drill is **successful** only if every one-loss case
    recovers, and (when ``expected_master`` is supplied) every
    recovery matches the expected master.

    Args:
        shares: the in-memory share inventory. Length MUST be at least
            ``threshold + 1`` for a meaningful one-loss drill; if
            length equals ``threshold`` exactly, the drill records
            ``threshold_met=False`` and does not attempt recovery
            (any loss is fatal in that configuration, by definition).
        threshold: the recovery threshold ``T`` (Wakir Phase-1a: 2).
        expected_master: optional. If supplied, recovery output is
            compared against this master and any mismatch fails the
            drill. If omitted, the drill only checks that recovery
            *succeeds*; integrity against an external reference is
            the caller's responsibility.
        passphrase: SLIP-39 passphrase used at split-time. Must match.

    Returns:
        A :class:`RecoveryDrillResult` summarising the run.

    Raises:
        ValueError: on empty share list or threshold mismatch.
    """
    if not shares:
        raise ValueError("shares must not be empty")
    if threshold < 1:
        raise ValueError("threshold must be >= 1")
    for s in shares:
        if s.threshold != threshold:
            raise ValueError(
                f"share {s.share_index} has threshold {s.threshold}, "
                f"expected {threshold}"
            )

    # If there are not enough shares to survive a single loss, report
    # that as a configuration finding without attempting recovery.
    if len(shares) <= threshold:
        return RecoveryDrillResult(
            success=False,
            attempts=0,
            threshold_met=False,
            lost_share_index=None,
            recovered_master=None,
            per_round_outcomes=[],
        )

    per_round: list[tuple[int, bool]] = []
    last_recovered: bytes | None = None
    first_failure_idx: int | None = None
    overall_ok = True

    for lost in shares:
        remaining = [s for s in shares if s.share_index != lost.share_index]
        # SLIP-39 (and the reference combine) requires exactly
        # ``threshold`` mnemonics. If the input set has more than
        # ``threshold + 1`` shares, the one-loss subset is still
        # over-sized; trim down to the first ``threshold`` shares of
        # the remainder so the drill exercises the *minimum* recovery
        # quorum, which is the property we actually want to verify.
        recover_subset = remaining[:threshold]
        try:
            recovered = combine_shamir_shares(
                recover_subset, passphrase=passphrase
            )
        except ValueError:
            per_round.append((lost.share_index, False))
            if first_failure_idx is None:
                first_failure_idx = lost.share_index
            overall_ok = False
            continue
        ok = (expected_master is None) or (recovered == expected_master)
        per_round.append((lost.share_index, ok))
        if ok:
            last_recovered = recovered
        else:
            if first_failure_idx is None:
                first_failure_idx = lost.share_index
            overall_ok = False

    return RecoveryDrillResult(
        success=overall_ok,
        attempts=len(per_round),
        threshold_met=True,
        lost_share_index=first_failure_idx,
        recovered_master=last_recovered,
        per_round_outcomes=per_round,
    )
