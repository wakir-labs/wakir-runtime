# SPDX-License-Identifier: Apache-2.0
"""SLIP-39 Shamir cold-storage split for Wakir persona seeds.

This module wraps the SatoshiLabs reference implementation
(``shamir-mnemonic`` on PyPI, MIT-licensed) and exposes a small,
typed surface tailored to the Wakir Phase-1a 2-of-3 cold-storage
pattern (ADR-0023b §3, consensus marker D-2).

Why a wrapper, not a re-implementation:

- SLIP-39 is non-trivial: GF(256) polynomial arithmetic, RS1024
  Reed-Solomon checksum, custom 1024-word lexicon, group/member two-
  level sharing. A correct from-scratch port would be several hundred
  lines plus its own test-vector battery.
- The reference library is published by the spec authors (SatoshiLabs)
  and matches the SLIP-39 specification by construction. License is
  MIT, compatible with our Apache-2.0 distribution.
- The library README explicitly warns the implementation is **not
  side-channel hardened**. For our use-case (offline cold-storage
  recovery, single-use ceremonies, no online attacker) this is
  acceptable; we document the constraint here and call it out in
  the spec doc so future production-bound use is gated by a
  hardened replacement (Phase-2+ backlog).

References (URL-200-stamped 2026-05-06):

- SLIP-0039 spec: <https://github.com/satoshilabs/slips/blob/master/slip-0039.md>
- Reference impl: <https://github.com/trezor/python-shamir-mnemonic>
- PyPI package: <https://pypi.org/project/shamir-mnemonic/>
  (version 0.3.0, MIT, last release 2024-05-16)
- Test vectors: <https://github.com/trezor/python-shamir-mnemonic/blob/master/vectors.json>

Wakir conventions:

- Default split is **2-of-3** (Phase-1a, ADR-0023b §3): three shares,
  any two reconstruct the master. Single group, single-level threshold.
- Master secret is the persona seed (16 or 32 bytes per SLIP-39).
- Passphrase support is exposed but defaults to empty: Wakir Phase-1a
  uses physical custody of the share artefacts as the security
  boundary, not memorised passphrases.
- ``extendable=True`` (SLIP-39 0.3.x default) is preserved so shares
  can be re-generated for the same master without an iteration-
  exponent collision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import shamir_mnemonic as _sm


# ---------------------------------------------------------------------------
# Phase-1a defaults (ADR-0023b §3, consensus marker D-2)
# ---------------------------------------------------------------------------

PHASE_1A_THRESHOLD: int = 2
PHASE_1A_TOTAL_SHARES: int = 3


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShamirShare:
    """A single SLIP-39 share in the Wakir cold-storage scheme.

    Attributes:
        share_index: zero-based ordinal of this share in the issuance
            run (0..total_shares-1). Stable per generation; not the
            SLIP-39 internal member index.
        share_mnemonic: the SLIP-39 mnemonic string (space-separated
            words). This is the artefact that goes onto paper / metal.
        threshold: SLIP-39 ``member_threshold`` of the group containing
            this share (Wakir Phase-1a: 2).
        total_shares: SLIP-39 ``member_count`` of the group (Phase-1a: 3).
        member_index: SLIP-39 internal member index (decoded from the
            mnemonic). Equal to ``share_index`` for the single-group
            Phase-1a layout, but exposed separately because callers
            using multi-group layouts (Phase-2+) cannot rely on the
            equality.
    """

    share_index: int
    share_mnemonic: str
    threshold: int
    total_shares: int
    member_index: int

    @property
    def share_data(self) -> bytes:
        """Return the binary representation of this share.

        SLIP-39 mnemonics are decoded to a byte string for archival
        contexts that prefer binary over the word list (e.g., engraving
        plates that already carry the SLIP-39 lexicon as a lookup
        table). The returned bytes are the SLIP-39 share-value
        (post-encryption GF(256) coefficients, before mnemonic
        encoding); the RS1024 checksum and group/member identifiers
        are *not* part of this slice and live in the dedicated
        ``threshold``, ``total_shares`` and ``member_index`` fields
        of :class:`ShamirShare`.
        """
        return bytes(_sm.share.Share.from_mnemonic(self.share_mnemonic).value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def split_master_secret(
    master: bytes,
    shares_n: int = PHASE_1A_TOTAL_SHARES,
    threshold_t: int = PHASE_1A_THRESHOLD,
    *,
    passphrase: bytes = b"",
) -> list[ShamirShare]:
    """Split a master secret into SLIP-39 shares.

    Args:
        master: the master secret to split. Per SLIP-39 the byte length
            MUST be 16 (128-bit secret) or 32 (256-bit secret), and
            even within those sizes only multiples of 2 bytes are valid.
            Wakir persona seeds are typically 32 bytes.
        shares_n: total number of shares to generate (``M`` in the
            spec). Defaults to the Phase-1a Wakir convention of 3.
        threshold_t: minimum number of shares required for recovery
            (``T`` in the spec). Defaults to the Phase-1a convention
            of 2. MUST satisfy ``1 <= T <= M``.
        passphrase: SLIP-39 passphrase. Defaults to empty (Wakir
            Phase-1a relies on physical custody, not a passphrase).

    Returns:
        A list of :class:`ShamirShare` of length ``shares_n``, in
        the order issued by SLIP-39.

    Raises:
        ValueError: on master length, threshold or share-count
            violations.
    """
    if len(master) not in (16, 32):
        raise ValueError(
            "SLIP-39 master secret length must be 16 or 32 bytes; "
            f"got {len(master)} bytes"
        )
    if shares_n < 1 or shares_n > 16:
        raise ValueError("shares_n must be in [1, 16]")
    if threshold_t < 1 or threshold_t > shares_n:
        raise ValueError("threshold_t must satisfy 1 <= T <= shares_n")

    # SLIP-39 group layout: a single group with (T, M).
    grouped = _sm.generate_mnemonics(
        group_threshold=1,
        groups=[(threshold_t, shares_n)],
        master_secret=master,
        passphrase=passphrase,
    )
    mnemonics = grouped[0]
    shares: list[ShamirShare] = []
    for idx, mnemonic in enumerate(mnemonics):
        decoded = _sm.share.Share.from_mnemonic(mnemonic)
        # SLIP-39 ``Share.index`` is the member index within the group
        # (0..member_count-1). For the single-group Phase-1a layout
        # this matches ``share_index``, but multi-group layouts
        # (Phase-2+) would let the two diverge, so we keep them
        # separate from the start.
        shares.append(
            ShamirShare(
                share_index=idx,
                share_mnemonic=mnemonic,
                threshold=threshold_t,
                total_shares=shares_n,
                member_index=decoded.index,
            )
        )
    return shares


def combine_shamir_shares(
    shares: Sequence[ShamirShare],
    *,
    passphrase: bytes = b"",
) -> bytes:
    """Reconstruct the master secret from a set of SLIP-39 shares.

    Args:
        shares: at least ``threshold`` distinct shares, all from the
            same generation (i.e., produced by the same
            :func:`split_master_secret` call).
        passphrase: must match the passphrase used at split time.

    Returns:
        The reconstructed master secret.

    Raises:
        ValueError: if too few shares are supplied or the supplied
            shares fail SLIP-39 internal consistency checks.
    """
    if len(shares) < 1:
        raise ValueError("at least one share is required")
    threshold = shares[0].threshold
    # Caller may supply more than threshold; SLIP-39 still recovers.
    # But fewer than threshold MUST fail explicitly.
    if len(shares) < threshold:
        raise ValueError(
            f"need at least {threshold} shares to reconstruct; "
            f"got {len(shares)}"
        )
    mnemonics = [s.share_mnemonic for s in shares]
    try:
        return _sm.combine_mnemonics(mnemonics, passphrase=passphrase)
    except _sm.MnemonicError as exc:
        # Re-raise as ValueError so callers do not need to import the
        # third-party exception type.
        raise ValueError(f"SLIP-39 combine failed: {exc}") from exc
