# SPDX-License-Identifier: Apache-2.0
"""Two-curve-stack hierarchical-deterministic key derivation for Wakir.

This module implements:

- BIP-32 master and hardened-child derivation for **secp256k1** (used for
  DID verification methods, Bitcoin-OTS anchoring and treasury wallets).
- SLIP-0010 master and hardened-child derivation for **Ed25519** (used
  for Biscuit authority/append-block signatures and AIP
  ``biscuit_root_pubkey``).

Both axes share a single persona seed; for production use the seed is
expected to be a BIP-39 mnemonic-derived 64-byte seed (see Cross-Review
Zone 1 consensus correction §2.5: "common persona seed → BIP-32 +
SLIP-0010").

References (URL-200-verified 2026-05-06):

- BIP-32: <https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki>
- SLIP-0010: <https://github.com/satoshilabs/slips/blob/master/slip-0010.md>
- BIP-44 path layout: ``m / purpose' / coin_type' / account' / change / address_index``
- Wakir Phase-1a path convention (consensus marker §1.2.4):
  ``m / 44' / WAKIR_COIN_TYPE' / persona_idx' / spawn_counter`` for
  secp256k1; ``m / 44' / WAKIR_COIN_TYPE' / persona_idx' / spawn_counter'``
  for Ed25519 (hardened-only per SLIP-0010).

Implementation notes:

- Pure-Python derivation on top of HMAC-SHA512 and the elliptic-curve
  primitives from ``cryptography`` (secp256k1) / RFC 8032 ed25519.
  We deliberately do not depend on ``bip32utils`` because that library
  does not implement SLIP-0010 (Ed25519 path is undefined in BIP-32);
  carrying the few lines of HMAC-SHA512 derivation ourselves is the
  smaller and more transparent surface.
- Hardened-only derivation: secp256k1 supports both, but we expose only
  the hardened path because it matches the Wakir convention and keeps
  the surface symmetric with SLIP-0010 (which has no non-hardened path).
- Verified against BIP-32 test vector 1 (seed
  ``000102030405060708090a0b0c0d0e0f``) and SLIP-0010 ed25519 test
  vector 1 (same seed) in :mod:`wirelang.tests.test_identity_key_derivation`.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)


# ---------------------------------------------------------------------------
# Wakir coin-type for BIP-44 / SLIP-0010 paths.
#
# SLIP-0044 is the canonical registry; we use a deterministic placeholder
# in the unassigned range (>= 0x80000000) until/unless Wakir registers a
# coin type officially. Treating this as an internal constant means we do
# not block on external registration.
WAKIR_COIN_TYPE: int = 0x57414B49  # ASCII 'WAKI', within hardened range
# ---------------------------------------------------------------------------

HARDENED_OFFSET: int = 0x8000_0000

# secp256k1 group order n (RFC 5639, SEC2). Needed for the BIP-32 child
# derivation step; cryptography does not expose n directly.
SECP256K1_N: int = (
    0xFFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFE_BAAE_DCE6_AF48_A03B_BFD2_5E8C_D036_4141
)


# ---------------------------------------------------------------------------
# secp256k1 BIP-32
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ExtendedKey:
    """Internal carrier for an extended (private-key, chain-code) pair."""

    private_key: bytes  # 32 bytes
    chain_code: bytes  # 32 bytes


def _hmac_sha512(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha512).digest()


def _secp256k1_master_from_seed(seed: bytes) -> _ExtendedKey:
    """BIP-32 master-key derivation. ``seed`` MUST be 16-64 bytes."""
    if not 16 <= len(seed) <= 64:
        raise ValueError("BIP-32 seed length must be between 16 and 64 bytes")
    i = _hmac_sha512(b"Bitcoin seed", seed)
    il, ir = i[:32], i[32:]
    il_int = int.from_bytes(il, "big")
    if il_int == 0 or il_int >= SECP256K1_N:
        # Vanishingly unlikely for any real seed; explicit per BIP-32.
        raise ValueError("invalid master key (IL out of range); pick a different seed")
    return _ExtendedKey(private_key=il, chain_code=ir)


def _secp256k1_pubkey_compressed(priv32: bytes) -> bytes:
    sk = ec.derive_private_key(int.from_bytes(priv32, "big"), ec.SECP256K1())
    return sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)


def _ckd_priv_secp256k1(parent: _ExtendedKey, index: int) -> _ExtendedKey:
    """BIP-32 CKDpriv: derive child extended key from parent.

    Hardened indices (``index >= 2**31``) feed the parent private key into
    the HMAC; non-hardened feed the parent's compressed public key.
    """
    if index < 0 or index >= 2**32:
        raise ValueError("derivation index out of range")
    if index >= HARDENED_OFFSET:
        data = b"\x00" + parent.private_key + struct.pack(">I", index)
    else:
        data = _secp256k1_pubkey_compressed(parent.private_key) + struct.pack(">I", index)
    i = _hmac_sha512(parent.chain_code, data)
    il, ir = i[:32], i[32:]
    il_int = int.from_bytes(il, "big")
    if il_int >= SECP256K1_N:
        raise ValueError("invalid child key (IL >= n); pick a different index")
    parent_int = int.from_bytes(parent.private_key, "big")
    child_int = (il_int + parent_int) % SECP256K1_N
    if child_int == 0:
        raise ValueError("invalid child key (zero); pick a different index")
    return _ExtendedKey(
        private_key=child_int.to_bytes(32, "big"),
        chain_code=ir,
    )


def derive_persona_master_secp256k1(seed: bytes) -> bytes:
    """Return the 32-byte secp256k1 master private key for a persona.

    Wakir convention: the seed is the BIP-39-derived 64-byte seed; the
    master is the BIP-32 root key (``m``). The chain code is *not*
    exposed by this function because higher-level derivation goes through
    :func:`derive_sub_key_secp256k1`, which internally re-derives the
    full extended key from the same seed for each call. That keeps the
    public API stateless and makes hot-path key handling explicit.

    For applications that need stateful BIP-32 use, call
    :func:`_secp256k1_master_from_seed` directly (private API).
    """
    return _secp256k1_master_from_seed(seed).private_key


def derive_sub_key_secp256k1(
    seed: bytes, persona_idx: int, spawn_counter: int
) -> bytes:
    """Derive a hardened secp256k1 sub-key for a spawned sub-agent.

    Path: ``m / 44' / WAKIR_COIN_TYPE' / persona_idx' / spawn_counter'``
    (all four levels hardened, per Wakir consensus marker §1.2.4 with the
    additional choice to harden ``spawn_counter`` so the resulting
    sub-key cannot be derived from public material alone).

    Args:
        seed: persona seed (16-64 bytes; typically a 64-byte BIP-39 seed).
        persona_idx: non-negative, < 2**31.
        spawn_counter: non-negative, < 2**31.

    Returns:
        The 32-byte child private key.
    """
    if not 0 <= persona_idx < HARDENED_OFFSET:
        raise ValueError("persona_idx must be in [0, 2**31)")
    if not 0 <= spawn_counter < HARDENED_OFFSET:
        raise ValueError("spawn_counter must be in [0, 2**31)")

    node = _secp256k1_master_from_seed(seed)
    for i in (44, WAKIR_COIN_TYPE, persona_idx, spawn_counter):
        node = _ckd_priv_secp256k1(node, i + HARDENED_OFFSET)
    return node.private_key


# ---------------------------------------------------------------------------
# Ed25519 SLIP-0010
# ---------------------------------------------------------------------------


def _ed25519_master_from_seed(seed: bytes) -> _ExtendedKey:
    """SLIP-0010 master-key derivation for Ed25519.

    Per SLIP-0010, every 32-byte sequence is a valid Ed25519 private
    key, so the retry loop required for secp256k1 does not apply.
    """
    if not 16 <= len(seed) <= 64:
        raise ValueError("SLIP-0010 seed length must be between 16 and 64 bytes")
    i = _hmac_sha512(b"ed25519 seed", seed)
    return _ExtendedKey(private_key=i[:32], chain_code=i[32:])


def _ckd_priv_ed25519(parent: _ExtendedKey, index: int) -> _ExtendedKey:
    """SLIP-0010 CKDpriv for Ed25519. Hardened indices only."""
    if index < HARDENED_OFFSET or index >= 2**32:
        raise ValueError(
            "SLIP-0010 ed25519 supports only hardened indices (>= 2**31)"
        )
    data = b"\x00" + parent.private_key + struct.pack(">I", index)
    i = _hmac_sha512(parent.chain_code, data)
    return _ExtendedKey(private_key=i[:32], chain_code=i[32:])


def derive_persona_master_ed25519(seed: bytes) -> bytes:
    """Return the 32-byte Ed25519 master private key for a persona.

    See :func:`derive_persona_master_secp256k1` for the design rationale
    of returning the private key only (stateless API).
    """
    return _ed25519_master_from_seed(seed).private_key


def derive_sub_key_ed25519(
    seed: bytes, persona_idx: int, spawn_counter: int
) -> bytes:
    """Derive a hardened Ed25519 sub-key for a spawned sub-agent.

    Path: ``m / 44' / WAKIR_COIN_TYPE' / persona_idx' / spawn_counter'``
    (SLIP-0010 mandates hardened-only, so all levels are implicitly
    hardened).

    Args:
        seed: persona seed (16-64 bytes; typically a 64-byte BIP-39 seed).
        persona_idx: non-negative, < 2**31.
        spawn_counter: non-negative, < 2**31.

    Returns:
        The 32-byte child private key. Use
        :func:`ed25519_public_from_private` (or :class:`Ed25519PrivateKey`
        directly) to obtain the matching public key.
    """
    if not 0 <= persona_idx < HARDENED_OFFSET:
        raise ValueError("persona_idx must be in [0, 2**31)")
    if not 0 <= spawn_counter < HARDENED_OFFSET:
        raise ValueError("spawn_counter must be in [0, 2**31)")

    node = _ed25519_master_from_seed(seed)
    for i in (44, WAKIR_COIN_TYPE, persona_idx, spawn_counter):
        node = _ckd_priv_ed25519(node, i + HARDENED_OFFSET)
    return node.private_key


# ---------------------------------------------------------------------------
# Public-key helpers (both curves)
# ---------------------------------------------------------------------------


def secp256k1_public_from_private(priv32: bytes, compressed: bool = True) -> bytes:
    """Return the secp256k1 public key for a 32-byte private scalar.

    Returns the 33-byte compressed point by default (DID-document and
    ``aip-document.json`` ``key_hex`` for ``alg=secp256k1`` use the
    compressed form, 66 hex chars).
    """
    if len(priv32) != 32:
        raise ValueError("secp256k1 private key must be 32 bytes")
    sk = ec.derive_private_key(int.from_bytes(priv32, "big"), ec.SECP256K1())
    if compressed:
        return sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    return sk.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def ed25519_public_from_private(priv32: bytes) -> bytes:
    """Return the 32-byte Ed25519 public key for a 32-byte private seed."""
    if len(priv32) != 32:
        raise ValueError("Ed25519 private key must be 32 bytes")
    sk = Ed25519PrivateKey.from_private_bytes(priv32)
    return sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
