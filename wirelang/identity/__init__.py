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

__all__ = [
    "WAKIR_COIN_TYPE",
    "derive_persona_master_secp256k1",
    "derive_persona_master_ed25519",
    "derive_sub_key_secp256k1",
    "derive_sub_key_ed25519",
    "generate_persona_did_document",
    "generate_aip_document",
]
