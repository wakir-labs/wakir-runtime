# SPDX-License-Identifier: Apache-2.0
"""Wirelang identity-substrate module.

Protocol-layer consolidation (ADR-0062 Cut-2, 2026-05-16)
---------------------------------------------------------
The Apache-2.0 surface of this package (all submodules EXCEPT
``federation_resolver``) is also published as
``wakir_protocol.identity_substrate`` under the standalone
``wakir-labs/wakir-protocol`` repository. The in-tree copy under
``wirelang.identity`` is the runtime-internal mirror.

``federation_resolver`` is BUSL-1.1 runtime-internal substrate and
stays in this repository; it is NOT mirrored to ``wakir-protocol``.

External adopters who want only the identity-substrate primitives
should depend on ``wakir-protocol`` and import from
``wakir_protocol.identity_substrate`` directly.

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

Lazy-import discipline (Sprint-9 Tag-4)
---------------------------------------

This package eagerly imports **no submodule that has a top-level
``cryptography`` dependency**. The crypto-bearing surfaces
(``key_derivation``, ``aip_signing``, ``did_document_signing``) are
exposed through :pep:`562` ``__getattr__`` so that importing a sibling
submodule (e.g. ``wirelang.identity.federation_resolver``, which
itself carries no crypto dependency) does NOT transitively load
``cryptography`` via this package's ``__init__``.

Background: the Sprint-9 Tag-1 NATS-KV bucket provisioner imports
``wirelang.federation.marker_stack_kv`` for its bucket-naming
constants. That module's import chain transitively reaches
``wirelang.identity.federation_resolver`` (via
``wirelang.federation.n2_evaluator``). Before Tag-4 this triggered
the eager ``from .key_derivation import …`` in this ``__init__``,
which in turn required the ``cryptography`` package — breaking the
operator-side ``nats-kv-bucket-init`` container image that
intentionally ships a minimal Python runtime without cryptography.

The Tag-4 lazy-import pattern decouples the crypto dependency from
the package-init step:

- Consumers that only need crypto-free submodules
  (``federation_resolver``, ``aip_document_transport_fetch``,
  ``aip_signature_verification_cache``, ``kid_resolver``,
  ``shamir_split``, ``recovery_drill``, ``did_document``,
  ``aip_document``) pay no ``cryptography`` import cost.
- Consumers that need crypto-bearing names
  (``derive_sub_key_secp256k1``, ``sign_aip_document``,
  ``verify_did_signature``, …) trigger the underlying submodule
  load on first attribute access via ``__getattr__``. The
  ``cryptography`` ``ModuleNotFoundError`` surfaces at that point,
  not at unrelated sibling-import time.

This is byte-stable for every existing consumer: the public
attribute-access shape is unchanged, only the eager-load timing
moves.

Public API (unchanged from Tag-3):

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

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Crypto-free submodules can be imported eagerly: none of them pull
# ``cryptography`` at module top-level. They participate in the public
# API directly.
from .aip_document import generate_aip_document
from .aip_document_transport_fetch import (
    AipDnsAnchorMismatchError,
    AipDocumentTransportError,
    AipFetchResult,
    AipUrlSchemeError,
    aip_web_to_https_url,
    fetch_aip_document,
)
from .did_document import generate_persona_did_document
from .kid_resolver import (
    KidResolverError,
    ResolvedPublicKey,
    list_resolvable_kids,
    resolve_kid,
)
# NOTE: ``shamir_split`` (and the transitively-dependent
# ``recovery_drill``) import ``shamir_mnemonic`` at module top level.
# That C-dependency is part of the production runtime extras but is
# absent from the minimal NATS-KV bucket-provisioner container image.
# Move them to the lazy surface so package-init stays dep-light.

# ---------------------------------------------------------------------------
# Lazy crypto-bearing API (PEP 562 __getattr__)
# ---------------------------------------------------------------------------
#
# These three submodules import ``cryptography`` at top level and are
# therefore loaded on first attribute access via ``__getattr__``.
# Importing the package itself (or any of the crypto-free submodules
# above) does NOT load them.

# Mapping: public attribute name -> (submodule_basename, attribute_in_submodule)
_LAZY_CRYPTO_ATTRS: dict[str, tuple[str, str]] = {
    # key_derivation
    "WAKIR_COIN_TYPE": ("key_derivation", "WAKIR_COIN_TYPE"),
    "derive_persona_master_secp256k1": (
        "key_derivation",
        "derive_persona_master_secp256k1",
    ),
    "derive_persona_master_ed25519": (
        "key_derivation",
        "derive_persona_master_ed25519",
    ),
    "derive_sub_key_secp256k1": ("key_derivation", "derive_sub_key_secp256k1"),
    "derive_sub_key_ed25519": ("key_derivation", "derive_sub_key_ed25519"),
    # aip_signing
    "sign_aip_document": ("aip_signing", "sign_aip_document"),
    "verify_aip_signature": ("aip_signing", "verify_aip_signature"),
    # did_document_signing
    "sign_did_document": ("did_document_signing", "sign_did_document"),
    "verify_did_signature": ("did_document_signing", "verify_did_signature"),
    # aip_signature_verification_cache transitively pulls aip_signing,
    # which has a top-level cryptography import. Keep it lazy so that
    # the package init stays crypto-free.
    "AipSignatureVerificationCache": (
        "aip_signature_verification_cache",
        "AipSignatureVerificationCache",
    ),
    "CacheStats": ("aip_signature_verification_cache", "CacheStats"),
    "cached_verify_aip_signature": (
        "aip_signature_verification_cache",
        "cached_verify_aip_signature",
    ),
    # shamir_split has a top-level shamir-mnemonic dependency that is
    # not part of the slim bucket-provisioner container; lazy-load so
    # crypto-free consumers (federation_resolver, etc.) stay light.
    "PHASE_1A_THRESHOLD": ("shamir_split", "PHASE_1A_THRESHOLD"),
    "PHASE_1A_TOTAL_SHARES": ("shamir_split", "PHASE_1A_TOTAL_SHARES"),
    "ShamirShare": ("shamir_split", "ShamirShare"),
    "combine_shamir_shares": ("shamir_split", "combine_shamir_shares"),
    "split_master_secret": ("shamir_split", "split_master_secret"),
    # recovery_drill transitively imports shamir_split.
    "RecoveryDrillResult": ("recovery_drill", "RecoveryDrillResult"),
    "simulate_recovery": ("recovery_drill", "simulate_recovery"),
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute resolver.

    Loads a crypto-bearing submodule on first access and caches the
    resolved attribute on the package module so subsequent accesses
    are a normal attribute lookup.
    """
    target = _LAZY_CRYPTO_ATTRS.get(name)
    if target is None:
        raise AttributeError(
            f"module 'wirelang.identity' has no attribute {name!r}"
        )
    submodule_name, attr_name = target
    from importlib import import_module

    submodule = import_module(f".{submodule_name}", __name__)
    value = getattr(submodule, attr_name)
    # Cache on the package module so the next access is direct.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy attributes to dir() and IDE-introspection."""
    return sorted(set(globals().keys()) | set(_LAZY_CRYPTO_ATTRS.keys()))


if TYPE_CHECKING:  # pragma: no cover - import for type-checker only
    # Re-import for static type-checkers: these names are
    # available at runtime via __getattr__ but type-checkers
    # benefit from a concrete declaration.
    from .aip_signature_verification_cache import (
        AipSignatureVerificationCache,
        CacheStats,
        cached_verify_aip_signature,
    )
    from .aip_signing import sign_aip_document, verify_aip_signature
    from .did_document_signing import sign_did_document, verify_did_signature
    from .key_derivation import (
        WAKIR_COIN_TYPE,
        derive_persona_master_ed25519,
        derive_persona_master_secp256k1,
        derive_sub_key_ed25519,
        derive_sub_key_secp256k1,
    )
    from .recovery_drill import RecoveryDrillResult, simulate_recovery
    from .shamir_split import (
        PHASE_1A_THRESHOLD,
        PHASE_1A_TOTAL_SHARES,
        ShamirShare,
        combine_shamir_shares,
        split_master_secret,
    )


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
    "KidResolverError",
    "ResolvedPublicKey",
    "resolve_kid",
    "list_resolvable_kids",
    "AipDocumentTransportError",
    "AipDnsAnchorMismatchError",
    "AipFetchResult",
    "AipUrlSchemeError",
    "aip_web_to_https_url",
    "fetch_aip_document",
    "AipSignatureVerificationCache",
    "CacheStats",
    "cached_verify_aip_signature",
]
