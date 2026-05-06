# SPDX-License-Identifier: Apache-2.0
"""Wirelang identity-substrate module.

Implements the Wakir two-curve-stack key derivation, persona DID-document
generation and AIP-document generation in conformance with the Phase-1a
consensus marker (Cross-Review Zone 1).

- secp256k1 axis: BIP-32 hierarchical-deterministic keys for DID
  verification methods, Bitcoin-OTS anchoring (consumer: WAT) and
  treasury wallets (consumer: CFO).
- Ed25519 axis: SLIP-0010 hierarchical-deterministic keys for Biscuit
  authority/append block signatures and the AIP-document
  ``biscuit_root_pubkey`` extension.

The two axes share a single persona seed so that a single SLIP-39
Shamir cold-storage pattern recovers both master keys.

Public API:

- :func:`derive_persona_master_secp256k1`
- :func:`derive_persona_master_ed25519`
- :func:`derive_sub_key_secp256k1`
- :func:`derive_sub_key_ed25519`
- :func:`generate_persona_did_document`
- :func:`generate_aip_document`
- :func:`split_master_secret`
- :func:`combine_shamir_shares`
- :func:`simulate_recovery`
- :func:`sign_aip_document` / :func:`verify_aip_signature`
- :func:`sign_did_document` / :func:`verify_did_signature`
- :class:`ShamirShare`, :class:`RecoveryDrillResult`
- :data:`WAKIR_COIN_TYPE`
"""

from .key_derivation import (
    WAKIR_COIN_TYPE,
    derive_persona_master_ed25519,
    derive_persona_master_secp256k1,
    derive_sub_key_ed25519,
    derive_sub_key_secp256k1,
)
from .did_document import generate_persona_did_document
from .aip_document import generate_aip_document
from .shamir_split import (
    PHASE_1A_THRESHOLD,
    PHASE_1A_TOTAL_SHARES,
    ShamirShare,
    combine_shamir_shares,
    split_master_secret,
)
from .recovery_drill import RecoveryDrillResult, simulate_recovery
from .aip_signing import sign_aip_document, verify_aip_signature
from .did_document_signing import sign_did_document, verify_did_signature

__all__ = [
    "WAKIR_COIN_TYPE",
    "PHASE_1A_THRESHOLD",
    "PHASE_1A_TOTAL_SHARES",
    "derive_persona_master_secp256k1",
    "derive_persona_master_ed25519",
    "derive_sub_key_secp256k1",
    "derive_sub_key_ed25519",
    "generate_persona_did_document",
    "generate_aip_document",
    "ShamirShare",
    "RecoveryDrillResult",
    "split_master_secret",
    "combine_shamir_shares",
    "simulate_recovery",
    "sign_aip_document",
    "verify_aip_signature",
    "sign_did_document",
    "verify_did_signature",
]
