# SPDX-License-Identifier: Apache-2.0
"""Tests for the two-curve-stack hierarchical-deterministic key derivation.

Includes verification against the canonical test vectors from BIP-32
(seed ``000102030405060708090a0b0c0d0e0f``) and SLIP-0010 (same seed,
ed25519 master).
"""

from __future__ import annotations

import pytest

from wirelang.identity import (
    WAKIR_COIN_TYPE,
    derive_persona_master_ed25519,
    derive_persona_master_secp256k1,
    derive_sub_key_ed25519,
    derive_sub_key_secp256k1,
)
from wirelang.identity.key_derivation import (
    ed25519_public_from_private,
    secp256k1_public_from_private,
)


# ---------------------------------------------------------------------------
# Canonical test vector 1 ("seed1") shared by BIP-32 and SLIP-0010.
# Source URLs (URL-200-verified 2026-05-06):
#   - https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki
#   - https://github.com/satoshilabs/slips/blob/master/slip-0010.md
# ---------------------------------------------------------------------------
SEED1 = bytes.fromhex("000102030405060708090a0b0c0d0e0f")

# BIP-32 test vector 1, m: master private key in hex.
BIP32_TV1_MASTER_PRIV_HEX = (
    "e8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35"
)
# Compressed public key for the BIP-32 test-vector-1 master.
BIP32_TV1_MASTER_PUB_HEX = (
    "0339a36013301597daef41fbe593a02cc513d0b55527ec2df1050e2e8ff49c85c2"
)

# SLIP-0010 test vector 1 (ed25519), m: master private key in hex.
SLIP10_TV1_MASTER_PRIV_HEX = (
    "2b4be7f19ee27bbf30c667b642d5f4aa69fd169872f8fc3059c08ebae2eb19e7"
)
# SLIP-0010 test-vector-1 master public key (32 raw bytes, A above).
SLIP10_TV1_MASTER_PUB_HEX = (
    "a4b2856bfec510abab89753fac1ac0e1112364e7d250545963f135f2a33188ed"
)


# ---------------------------------------------------------------------------
# secp256k1 BIP-32
# ---------------------------------------------------------------------------


def test_secp256k1_master_matches_bip32_test_vector_1() -> None:
    """Library verification against the canonical BIP-32 test vector.

    If this fails, our HMAC-SHA512 / point-arithmetic stack is off and
    every other derivation in this module is suspect.
    """
    master = derive_persona_master_secp256k1(SEED1)
    assert master.hex() == BIP32_TV1_MASTER_PRIV_HEX


def test_secp256k1_master_pubkey_matches_bip32_test_vector_1() -> None:
    master = derive_persona_master_secp256k1(SEED1)
    pub = secp256k1_public_from_private(master, compressed=True)
    assert pub.hex() == BIP32_TV1_MASTER_PUB_HEX
    assert len(pub) == 33  # compressed point


def test_secp256k1_seed_too_short_raises() -> None:
    with pytest.raises(ValueError, match="seed length"):
        derive_persona_master_secp256k1(b"\x00" * 8)


def test_secp256k1_seed_too_long_raises() -> None:
    with pytest.raises(ValueError, match="seed length"):
        derive_persona_master_secp256k1(b"\x00" * 65)


def test_secp256k1_sub_key_deterministic_under_same_inputs() -> None:
    a = derive_sub_key_secp256k1(SEED1, persona_idx=0, spawn_counter=0)
    b = derive_sub_key_secp256k1(SEED1, persona_idx=0, spawn_counter=0)
    assert a == b
    assert len(a) == 32


def test_secp256k1_sub_key_distinct_per_spawn_counter() -> None:
    a = derive_sub_key_secp256k1(SEED1, persona_idx=0, spawn_counter=0)
    b = derive_sub_key_secp256k1(SEED1, persona_idx=0, spawn_counter=1)
    assert a != b


def test_secp256k1_sub_key_distinct_per_persona_idx() -> None:
    a = derive_sub_key_secp256k1(SEED1, persona_idx=0, spawn_counter=7)
    b = derive_sub_key_secp256k1(SEED1, persona_idx=1, spawn_counter=7)
    assert a != b


def test_secp256k1_sub_key_rejects_negative_indices() -> None:
    with pytest.raises(ValueError, match="persona_idx"):
        derive_sub_key_secp256k1(SEED1, persona_idx=-1, spawn_counter=0)
    with pytest.raises(ValueError, match="spawn_counter"):
        derive_sub_key_secp256k1(SEED1, persona_idx=0, spawn_counter=-1)


def test_secp256k1_sub_key_rejects_indices_at_or_above_2_to_31() -> None:
    with pytest.raises(ValueError):
        derive_sub_key_secp256k1(
            SEED1, persona_idx=2**31, spawn_counter=0
        )
    with pytest.raises(ValueError):
        derive_sub_key_secp256k1(
            SEED1, persona_idx=0, spawn_counter=2**31
        )


# ---------------------------------------------------------------------------
# Ed25519 SLIP-0010
# ---------------------------------------------------------------------------


def test_ed25519_master_matches_slip10_test_vector_1() -> None:
    """Library verification against the canonical SLIP-0010 test vector."""
    master = derive_persona_master_ed25519(SEED1)
    assert master.hex() == SLIP10_TV1_MASTER_PRIV_HEX


def test_ed25519_master_pubkey_matches_slip10_test_vector_1() -> None:
    master = derive_persona_master_ed25519(SEED1)
    pub = ed25519_public_from_private(master)
    assert pub.hex() == SLIP10_TV1_MASTER_PUB_HEX
    assert len(pub) == 32


def test_ed25519_seed_too_short_raises() -> None:
    with pytest.raises(ValueError, match="seed length"):
        derive_persona_master_ed25519(b"\x00" * 8)


def test_ed25519_sub_key_deterministic_under_same_inputs() -> None:
    a = derive_sub_key_ed25519(SEED1, persona_idx=0, spawn_counter=0)
    b = derive_sub_key_ed25519(SEED1, persona_idx=0, spawn_counter=0)
    assert a == b
    assert len(a) == 32


def test_ed25519_sub_key_distinct_per_spawn_counter() -> None:
    a = derive_sub_key_ed25519(SEED1, persona_idx=0, spawn_counter=0)
    b = derive_sub_key_ed25519(SEED1, persona_idx=0, spawn_counter=1)
    assert a != b


def test_ed25519_sub_key_distinct_per_persona_idx() -> None:
    a = derive_sub_key_ed25519(SEED1, persona_idx=2, spawn_counter=5)
    b = derive_sub_key_ed25519(SEED1, persona_idx=3, spawn_counter=5)
    assert a != b


def test_ed25519_sub_key_rejects_invalid_indices() -> None:
    with pytest.raises(ValueError):
        derive_sub_key_ed25519(SEED1, persona_idx=-1, spawn_counter=0)
    with pytest.raises(ValueError):
        derive_sub_key_ed25519(SEED1, persona_idx=2**31, spawn_counter=0)


# ---------------------------------------------------------------------------
# Cross-curve consistency
# ---------------------------------------------------------------------------


def test_two_curve_masters_differ_for_same_seed() -> None:
    """The same persona seed MUST produce two distinct master keys.

    Same seed feeding HMAC-SHA512 with two different keys (``"Bitcoin
    seed"`` vs. ``"ed25519 seed"``) MUST never collide. Equality would
    indicate a catastrophic bug.
    """
    s1 = derive_persona_master_secp256k1(SEED1)
    e1 = derive_persona_master_ed25519(SEED1)
    assert s1 != e1


def test_two_curve_subkeys_differ_for_same_path() -> None:
    s = derive_sub_key_secp256k1(SEED1, persona_idx=0, spawn_counter=0)
    e = derive_sub_key_ed25519(SEED1, persona_idx=0, spawn_counter=0)
    assert s != e


def test_wakir_coin_type_constant_is_in_hardened_range() -> None:
    """The Wakir coin-type sentinel must live in the hardened-index region.

    BIP-32/BIP-44 hardened indices are >= 2**31. Our path concatenates
    ``WAKIR_COIN_TYPE + HARDENED_OFFSET``; that means the *raw* coin
    type itself must be < 2**31 to avoid overflow into the 32-bit space.
    """
    assert 0 < WAKIR_COIN_TYPE < 2**31


def test_two_curve_paths_use_same_persona_and_spawn_indices() -> None:
    """Path symmetry check: both curves derive at identical depth.

    This is the implementation-side contract behind the cross-review
    consensus marker §1.2.4 (Curve-Mapping table): a single
    ``(persona_idx, spawn_counter)`` tuple addresses both curves.
    """
    s_a = derive_sub_key_secp256k1(SEED1, persona_idx=4, spawn_counter=12)
    s_b = derive_sub_key_secp256k1(SEED1, persona_idx=4, spawn_counter=12)
    e_a = derive_sub_key_ed25519(SEED1, persona_idx=4, spawn_counter=12)
    e_b = derive_sub_key_ed25519(SEED1, persona_idx=4, spawn_counter=12)
    assert s_a == s_b
    assert e_a == e_b
    assert s_a != e_a
