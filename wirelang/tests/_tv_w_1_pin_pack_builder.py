# SPDX-License-Identifier: Apache-2.0
"""TV-W-1 pin-pack builder (deterministic 9 personas x 2 curves roundtrip).

This is the single source of truth for the TV-W-1 hermetic golden
fixture. It is invoked

- by ``test_tv_w_1_identity_roundtrip.py`` for in-process pin-pack
  re-derivation, and
- as a CLI from ``scripts/regenerate_tv_w_1_pin_pack.py`` for
  external / operator-driven regeneration.

The builder is deterministic: given the BIP-32 test-vector-1 seed and
the fixed enumeration ``persona_idx in {0,1,2}`` x
``spawn_counter in {0,1,2}``, the per-persona records and the
top-level pin-pack hash are byte-stable.

Determinism notes:

- Ed25519 signatures are deterministic (RFC 8032 mandates
  deterministic-k); the AIP ``document_signature`` is therefore
  byte-pinned.
- ECDSA-secp256k1 in our stack is **not** deterministic
  (``cryptography.hazmat`` does not enforce RFC 6979 here). The DID
  document carries a non-deterministic ``proof`` slot that we
  deliberately exclude from the pin-pack hash. We pin the unsigned
  DID-document JCS-SHA-256 instead, which is byte-stable.
- The pin-pack body itself is JCS-canonicalised; SHA-256 of those
  canonical bytes is the top-level pin.

Brand-Guide §9: all persona_id values are role-strings derived
mechanically from ``(persona_idx, spawn_counter)``; no clear personal
names ever enter this file or the produced fixture.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Callable

from wirelang.identity import (
    derive_sub_key_ed25519,
    derive_sub_key_secp256k1,
    generate_aip_document,
    generate_persona_did_document,
    sign_aip_document,
)
from wirelang.identity.key_derivation import (
    ed25519_public_from_private,
    secp256k1_public_from_private,
)


# ---------------------------------------------------------------------------
# Pinned inputs (per spec §1.2 of wirelang-tv-strategy.md)
# ---------------------------------------------------------------------------

# BIP-32 test-vector 1 seed (also SLIP-0010 ed25519 test-vector 1 seed).
# Pinned; the test fixture for both BIP-32 and SLIP-0010 is built on this
# seed so the master keys themselves are external-spec-anchored.
TV_W_1_TEST_SEED_HEX: str = "000102030405060708090a0b0c0d0e0f"

# Fixed ``valid_after`` / ``expires`` so the AIP document body is
# fully byte-stable. (``generate_aip_document`` defaults these to
# ``datetime.now``, which would re-randomise the body.)
TV_W_1_VALID_AFTER: str = "2026-05-07T00:00:00Z"
TV_W_1_EXPIRES: str = "2027-05-07T00:00:00Z"

# Cartesian enumeration. Spec mandates 9 personas (3 x 3).
TV_W_1_PERSONA_GRID: tuple[tuple[int, int], ...] = tuple(
    (p, s) for p in range(3) for s in range(3)
)


def persona_role_string(persona_idx: int, spawn_counter: int) -> str:
    """Return the deterministic role-string for a (persona_idx, spawn) pair.

    Role-strings only; no clear names. Format chosen to be
    publication-safe in the AIP-document ``id`` and DID
    ``persona-id`` slots (no slashes, no colons).
    """
    return f"tv-w-1-persona-{persona_idx}-{spawn_counter}"


# ---------------------------------------------------------------------------
# JCS resolver indirection (Tag-9)
# ---------------------------------------------------------------------------


def _make_jcs_canonicalize() -> Callable[[object], bytes]:
    """Return the active JCS canonicaliser (rfc8785 if available else pure-Python).

    The pin-pack must be reproducible on both lanes (Tag-11 sandbox
    without rfc8785 + Tag-12 production with rfc8785). The two
    backends are byte-equivalent for the document shapes used here;
    that equivalence is itself anchored by
    ``test_pure_python_fallback.py`` and re-verified per pin-pack
    record by acceptance criterion A2.
    """
    try:
        import rfc8785  # type: ignore[import-not-found]

        return rfc8785.dumps
    except ImportError:  # pragma: no cover -- exercised on sandbox lane.
        from wirelang.identity import _jcs_pure

        return _jcs_pure.canonicalize


def _build_persona_record(
    seed: bytes,
    persona_idx: int,
    spawn_counter: int,
    jcs: Callable[[object], bytes],
) -> dict:
    """Run the full Wakir identity pipeline for one (persona_idx, spawn) pair.

    Steps mirror spec §1.3 of wirelang-tv-strategy.md exactly.
    """
    role = persona_role_string(persona_idx, spawn_counter)

    # 1. + 2. Two-curve sub-key derivation.
    secp_priv = derive_sub_key_secp256k1(seed, persona_idx, spawn_counter)
    ed_priv = derive_sub_key_ed25519(seed, persona_idx, spawn_counter)
    secp_pub = secp256k1_public_from_private(secp_priv)
    ed_pub = ed25519_public_from_private(ed_priv)

    # 3. DID document (unsigned body; proof slot is deliberately omitted
    #    from the pinned record because ECDSA-secp256k1 is non-deterministic;
    #    the pin-pack hashes the unsigned body instead).
    did_doc = generate_persona_did_document(
        role,
        secp_pub,
        ed_pub,
        host="wakir.dev",
        version=1,
    )
    # Strip any potentially-present ``proof`` slot defensively; the
    # canonicaliser is not allowed to see the non-deterministic
    # signature when computing the pinned hash.
    did_doc_unsigned = copy.deepcopy(did_doc)
    did_doc_unsigned.pop("proof", None)
    did_doc_canonical = jcs(did_doc_unsigned)
    did_doc_hash = hashlib.sha256(did_doc_canonical).hexdigest()

    # 4. AIP document with the persona's Ed25519 public key as
    #    biscuit-root. Pin valid_after/expires for byte-stability.
    aip_doc = generate_aip_document(
        role,
        ed_pub,
        did_uri=did_doc["id"],
        valid_after=TV_W_1_VALID_AFTER,
        valid_until=None,
        expires=TV_W_1_EXPIRES,
        delegation_mode="chained",
        protocols=("wirelang/0.1",),
    )

    # 5. Sign AIP document. Ed25519 is deterministic, so the
    #    signature is byte-stable and can be pinned.
    aip_signature_block = sign_aip_document(aip_doc, ed_priv)
    aip_doc_signed = copy.deepcopy(aip_doc)
    aip_doc_signed["document_signature"] = aip_signature_block

    # AIP-document hash for the pin-pack: hash of the canonicalised
    # *signed* document. This catches drift in the signing slot too.
    aip_doc_canonical_signed = jcs(aip_doc_signed)
    aip_doc_hash = hashlib.sha256(aip_doc_canonical_signed).hexdigest()

    return {
        "persona_idx": persona_idx,
        "spawn_counter": spawn_counter,
        "role_string": role,
        "secp256k1_pub_hex_33": secp_pub.hex(),
        "ed25519_pub_hex_32": ed_pub.hex(),
        "did_doc_jcs_sha256": did_doc_hash,
        "aip_doc_jcs_sha256": aip_doc_hash,
        "aip_signature_hex": aip_signature_block["signature"],
    }


def build_pin_pack(*, seed_hex: str = TV_W_1_TEST_SEED_HEX) -> dict:
    """Build the full TV-W-1 pin-pack body (without the top-level hash).

    Returns the pin-pack as a Python dict whose JCS canonical form is
    SHA-256-hashable to produce the top-level pin. Callers that want
    the hash should call :func:`pin_pack_hash`.
    """
    seed = bytes.fromhex(seed_hex)
    jcs = _make_jcs_canonicalize()
    records = [
        _build_persona_record(seed, p, s, jcs) for (p, s) in TV_W_1_PERSONA_GRID
    ]
    return {
        "label": "tv-w-1-identity-pin-pack",
        "spec": "wirelang/specs/wirelang-tv-strategy.md §1 (Phase-1b Tag-14)",
        "seed_hex": seed_hex,
        "valid_after": TV_W_1_VALID_AFTER,
        "expires": TV_W_1_EXPIRES,
        "wakir_coin_type_hex": "0x57414b49",
        "derivation_path_template": (
            "m / 44' / WAKIR_COIN_TYPE' / persona_idx' / spawn_counter'"
        ),
        "records": records,
    }


def pin_pack_hash(pin_pack: dict) -> str:
    """Return the SHA-256-of-JCS pin for a pin-pack body."""
    jcs = _make_jcs_canonicalize()
    return hashlib.sha256(jcs(pin_pack)).hexdigest()


def build_pin_pack_with_hash(*, seed_hex: str = TV_W_1_TEST_SEED_HEX) -> dict:
    """Build the full pin-pack including the top-level ``pin_pack_sha256``.

    The top-level hash is the SHA-256 of JCS of the pin-pack
    *without* the hash slot itself (mirrors the AIP / DID self-
    signature stripping convention).
    """
    body = build_pin_pack(seed_hex=seed_hex)
    body["pin_pack_sha256"] = pin_pack_hash(body)
    return body


# ---------------------------------------------------------------------------
# CLI entry-point: regenerate the golden fixture.
# ---------------------------------------------------------------------------


def _default_fixture_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "fixtures"
        / "tv-w-1"
        / "pin-pack.json"
    )


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the TV-W-1 identity pin-pack golden fixture. "
            "External auditors can run this against the documented seed "
            "to reproduce the pin-pack hash (acceptance criterion A5)."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_default_fixture_path(),
        help="Output path for the pin-pack JSON (default: fixtures/tv-w-1/pin-pack.json).",
    )
    parser.add_argument(
        "--seed-hex",
        default=TV_W_1_TEST_SEED_HEX,
        help="Override the BIP-32 test seed (hex). Default: BIP-32 test-vector 1.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only print the pin-pack hash; do not write the file.",
    )
    ns = parser.parse_args(argv)

    pin_pack = build_pin_pack_with_hash(seed_hex=ns.seed_hex)
    if ns.check:
        print(pin_pack["pin_pack_sha256"])
        return 0
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    with ns.out.open("w", encoding="utf-8") as fh:
        json.dump(pin_pack, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(f"wrote {ns.out} (pin_pack_sha256 = {pin_pack['pin_pack_sha256']})")
    return 0


if __name__ == "__main__":  # pragma: no cover -- CLI entry-point
    sys.exit(_cli(sys.argv[1:]))
