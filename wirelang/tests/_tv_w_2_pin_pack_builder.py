# SPDX-License-Identifier: Apache-2.0
"""TV-W-2 capability-token multi-step pin-pack builder (Phase-1b Tag-16).

Implements the deterministic builder for the TV-W-2 vector specified
in ``wirelang/specs/wirelang-tv-strategy.md`` §2 and pin-stabilised by
``wirelang/specs/datalog-caveat-vocabulary-phase-2.md`` §6.

Pipeline (per spec §2.3):

1. Build authority block (Block 0) signed by the issuer Ed25519 key.
   Issuer keypair is the TV-W-1 persona ``(0, 0)`` Ed25519 sub-key
   so the cross-vector anchor in
   ``test_tv_w_1_identity_roundtrip.py::test_cross_compat_pubkeys_align_with_capability_token_pin``
   pins the TV-W-2 input.
2. Append Block 1 (scope-narrowing) signed by Block-0's
   ``next_pubkey``.
3. Append Block 2 (rate-limit) signed by Block-1's ``next_pubkey``.
4. Optional sealing: produce a ``proof_block`` over the chain.
5. Run the verifier in three presentation contexts (α/β/γ).
6. Emit a deterministic verification-trace JSON for each context
   plus a top-level pin-pack that hashes the chain and the three
   traces.

Determinism notes:

- All Ed25519 sub-keys (issuer key for Block 0, ``next_pubkey``
  chain) are derived deterministically from the TV-W-1 seed.
  Specifically, the chain ``next_pubkey`` is derived from the
  TV-W-1 seed via a labelled SHA-256 expansion so producer logic
  remains pinnable without needing a full BIP-32 tree.
- Ed25519 (RFC 8032) signatures are deterministic-k; signature
  bytes are byte-stable across re-runs.
- Caveat-set hashes follow §4-CSC from the Phase-2 vocabulary and
  are computed via :mod:`wirelang.canonical.caveat_set`. Producer
  caveat-emission order is deliberately *unsorted* in this builder
  so the §4-CSC sort step is exercised on the production side.
- Verifier traces are JCS-canonicalised; the top-level pin-pack
  hash is SHA-256 of JCS of the body without the hash slot.

Brand-Guide §9: persona role-strings are mechanical
(``tv-w-2-issuer-0-0``, ``consumer-A``, ``consumer-B``,
``consumer-C``); no clear personal names enter this file or the
golden fixtures.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Callable, Iterable, List, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from wirelang.canonical.caveat_set import (
    canonical_caveat_set_bytes,
    canonical_caveat_set_hash,
    canonicalize_caveat_set,
)
from wirelang.identity import (
    derive_sub_key_ed25519,
)
from wirelang.identity.key_derivation import (
    ed25519_public_from_private,
)


# ---------------------------------------------------------------------------
# Pinned inputs (per spec §2.2)
# ---------------------------------------------------------------------------

# Same BIP-32 test-vector-1 seed as TV-W-1; ensures the issuer key
# anchors the TV-W-1 cross-compat pin.
TV_W_2_TEST_SEED_HEX: str = "000102030405060708090a0b0c0d0e0f"

# Issuer persona index (matches the TV-W-1 persona-(0,0) Ed25519 cross-
# compat anchor specified in spec §2.2 and asserted in the TV-W-1 test
# ``test_cross_compat_pubkeys_align_with_capability_token_pin``).
TV_W_2_ISSUER_PERSONA_IDX: int = 0
TV_W_2_ISSUER_SPAWN_COUNTER: int = 0
TV_W_2_ISSUER_ROLE: str = (
    f"tv-w-2-issuer-{TV_W_2_ISSUER_PERSONA_IDX}-{TV_W_2_ISSUER_SPAWN_COUNTER}"
)

# Pinned validity window. Same shape as TV-W-1's pinned timestamps so
# β-context (after-not-after) can use a verifier-time strictly past
# `not_after` while α/γ stay inside the window.
TV_W_2_NOT_BEFORE: str = "2026-05-07T00:00:00Z"
TV_W_2_NOT_AFTER: str = "2027-05-07T00:00:00Z"
TV_W_2_NONCE: str = "9f2b1c4a7d8e3f60a1b2c3d4e5f60718"

# Three audience role-strings per spec §2.2.
AUDIENCE_PRIMARY: str = "role=consumer-A"
AUDIENCE_NARROWED: str = "role=consumer-A,scope=read-only"
AUDIENCE_GAMMA: str = "role=consumer-B"  # mismatched audience for context γ
AUDIENCE_RATE_LIMITED: str = "role=consumer-A,scope=read-only,rate=capped"

# Pinned caveat sets. Producer-internal order is intentionally NOT
# lexicographic so §4-CSC sort is exercised at fixture time (this is
# the documented test condition under spec §6.4 "producer-internal
# caveat-emission-order change does not break the guarantee").
AUTHORITY_CAVEATS: Tuple[str, ...] = (
    'check if env("prod")',
    'check if action("read.balance")',
    'check if audience("role=consumer-A")',
)
APPEND_1_CAVEATS: Tuple[str, ...] = (
    'check if read_only(true)',
    'check if action("read.balance")',  # duplicate of authority caveat -> §4-CSC dedup is *per-block* (not cross-block); keep for clarity
)
APPEND_2_CAVEATS: Tuple[str, ...] = (
    'check if rate_limit($n), $n <= 100',
)

# Three presentation contexts per spec §2.3 step 5.
TV_W_2_CONTEXT_ALPHA: str = "alpha"  # within all caveats -> accept
TV_W_2_CONTEXT_BETA: str = "beta"    # after not_after -> reject
TV_W_2_CONTEXT_GAMMA: str = "gamma"  # mismatched audience -> reject

# Pinned verifier wall-clock per context (RFC 3339).
CONTEXT_TIMES: dict = {
    TV_W_2_CONTEXT_ALPHA: "2026-09-01T12:00:00Z",  # inside window
    TV_W_2_CONTEXT_BETA:  "2027-06-01T12:00:00Z",  # after not_after
    TV_W_2_CONTEXT_GAMMA: "2026-09-01T12:00:00Z",  # inside window, but...
}
# Audience claimed by the inbound request, per context.
CONTEXT_AUDIENCE: dict = {
    TV_W_2_CONTEXT_ALPHA: AUDIENCE_PRIMARY,
    TV_W_2_CONTEXT_BETA:  AUDIENCE_PRIMARY,
    TV_W_2_CONTEXT_GAMMA: AUDIENCE_GAMMA,  # mismatch
}


# ---------------------------------------------------------------------------
# JCS resolver indirection (Tag-9)
# ---------------------------------------------------------------------------


def _make_jcs_canonicalize() -> Callable[[object], bytes]:
    """Return the active JCS canonicaliser (rfc8785 if available else pure)."""
    try:
        import rfc8785  # type: ignore[import-not-found]

        return rfc8785.dumps
    except ImportError:  # pragma: no cover -- exercised on sandbox lane.
        from wirelang.identity import _jcs_pure

        return _jcs_pure.canonicalize


# ---------------------------------------------------------------------------
# Deterministic next-pubkey chain
# ---------------------------------------------------------------------------


def _derive_chain_seed(label: bytes, parent_seed: bytes) -> bytes:
    """Derive a deterministic 32-byte child seed from a parent seed.

    Used to produce ``next_pubkey`` Ed25519 keypairs along the
    Biscuit append-block chain without standing up a full BIP-32
    tree. The construction is::

        SHA-256( b"tv-w-2-chain|" + label + b"|" + parent_seed )

    The label disambiguates each chain-step so two consumers that
    share a parent seed but address different chain positions cannot
    collide. The output is a valid Ed25519 raw private key (any
    32-byte string is admissible; Ed25519 hashes the seed internally
    per RFC 8032).
    """
    h = hashlib.sha256()
    h.update(b"tv-w-2-chain|")
    h.update(label)
    h.update(b"|")
    h.update(parent_seed)
    return h.digest()


# ---------------------------------------------------------------------------
# Block payload construction
# ---------------------------------------------------------------------------


def _block_payload(
    *,
    block_index: int,
    issuer_did: str,
    audience_pattern: str,
    caveats: Tuple[str, ...],
    not_before: str | None,
    not_after: str | None,
    nonce: str | None,
    next_pubkey_hex: str,
    prev_signature_hex: str | None,
) -> dict:
    """Return the JCS-signing payload for one block.

    Authority block (index 0) carries ``not_before``, ``not_after``
    and ``nonce``; append blocks reference the previous block's
    signature instead. The resulting dict is the input to the JCS
    canonicaliser; the SHA-256 of the canonical bytes is the
    signing pre-image.
    """
    payload: dict = {
        "block_index": block_index,
        "issuer_did": issuer_did,
        "audience_pattern": audience_pattern,
        "caveats": list(caveats),  # producer-emitted order, NOT canonical
        "next_pubkey": next_pubkey_hex,
    }
    if block_index == 0:
        # Authority-block-only fields per layer-3-capability-token.md §2.1.
        assert not_before is not None and not_after is not None and nonce is not None
        payload["not_before"] = not_before
        payload["not_after"] = not_after
        payload["nonce"] = nonce
    else:
        # Append-block-only field per layer-3-capability-token.md §2.2.
        assert prev_signature_hex is not None
        payload["prev_signature"] = prev_signature_hex
    return payload


def _sign_block_payload(payload: dict, signer_priv32: bytes) -> str:
    """JCS-canonicalise + SHA-256 + Ed25519 sign; return signature hex."""
    jcs = _make_jcs_canonicalize()
    digest = hashlib.sha256(jcs(payload)).digest()
    sk = Ed25519PrivateKey.from_private_bytes(signer_priv32)
    return sk.sign(digest).hex()


def _block_hash(payload: dict) -> str:
    """SHA-256 of the JCS-canonicalised block payload (hex)."""
    jcs = _make_jcs_canonicalize()
    return hashlib.sha256(jcs(payload)).hexdigest()


# ---------------------------------------------------------------------------
# Chain construction
# ---------------------------------------------------------------------------


def build_chain(
    *,
    seed_hex: str = TV_W_2_TEST_SEED_HEX,
) -> dict:
    """Build the full Biscuit-shaped chain (authority + 2 append + sealing).

    Returns a dict with the chain in JSON projection plus the raw
    32-byte private seeds for each step (used by the verifier
    side; not pinned in the golden fixture).
    """
    seed = bytes.fromhex(seed_hex)

    # Issuer (Block 0) keypair: TV-W-1 persona-(0,0) Ed25519 sub-key.
    issuer_priv = derive_sub_key_ed25519(
        seed, TV_W_2_ISSUER_PERSONA_IDX, TV_W_2_ISSUER_SPAWN_COUNTER
    )
    issuer_pub = ed25519_public_from_private(issuer_priv)

    # Block 0 next_pubkey: the keypair that will sign Block 1.
    block0_next_priv = _derive_chain_seed(b"block0->block1", seed)
    block0_next_pub = ed25519_public_from_private(block0_next_priv)

    # Block 1 next_pubkey: keypair signing Block 2.
    block1_next_priv = _derive_chain_seed(b"block1->block2", seed)
    block1_next_pub = ed25519_public_from_private(block1_next_priv)

    # Block 2 next_pubkey: keypair available for sealing or further
    # attenuation. (Sealing uses this slot's pubkey as the sealing
    # signer in our JSON projection.)
    block2_next_priv = _derive_chain_seed(b"block2->seal", seed)
    block2_next_pub = ed25519_public_from_private(block2_next_priv)

    issuer_did = f"aip:web:wakir.dev/{TV_W_2_ISSUER_ROLE}"

    # ---- Block 0 (authority) ----
    block0_payload = _block_payload(
        block_index=0,
        issuer_did=issuer_did,
        audience_pattern=AUDIENCE_PRIMARY,
        caveats=AUTHORITY_CAVEATS,
        not_before=TV_W_2_NOT_BEFORE,
        not_after=TV_W_2_NOT_AFTER,
        nonce=TV_W_2_NONCE,
        next_pubkey_hex=block0_next_pub.hex(),
        prev_signature_hex=None,
    )
    block0_signature = _sign_block_payload(block0_payload, issuer_priv)

    # ---- Block 1 (scope-narrowing) ----
    block1_payload = _block_payload(
        block_index=1,
        issuer_did=issuer_did,
        audience_pattern=AUDIENCE_NARROWED,
        caveats=APPEND_1_CAVEATS,
        not_before=None,
        not_after=None,
        nonce=None,
        next_pubkey_hex=block1_next_pub.hex(),
        prev_signature_hex=block0_signature,
    )
    block1_signature = _sign_block_payload(block1_payload, block0_next_priv)

    # ---- Block 2 (rate-limit) ----
    block2_payload = _block_payload(
        block_index=2,
        issuer_did=issuer_did,
        audience_pattern=AUDIENCE_RATE_LIMITED,
        caveats=APPEND_2_CAVEATS,
        not_before=None,
        not_after=None,
        nonce=None,
        next_pubkey_hex=block2_next_pub.hex(),
        prev_signature_hex=block1_signature,
    )
    block2_signature = _sign_block_payload(block2_payload, block1_next_priv)

    # ---- Sealing block ----
    sealing_input = {
        "label": "tv-w-2-sealing",
        "block2_signature": block2_signature,
        "block2_next_pubkey": block2_next_pub.hex(),
        "sealed_at": "2026-05-07T01:00:00Z",
    }
    sealing_signature = _sign_block_payload(sealing_input, block2_next_priv)

    return {
        "chain": [
            {
                "payload": block0_payload,
                "signature": block0_signature,
                "block_hash": _block_hash(block0_payload),
            },
            {
                "payload": block1_payload,
                "signature": block1_signature,
                "block_hash": _block_hash(block1_payload),
            },
            {
                "payload": block2_payload,
                "signature": block2_signature,
                "block_hash": _block_hash(block2_payload),
            },
        ],
        "sealing": {
            "input": sealing_input,
            "signature": sealing_signature,
        },
        "pubkeys": {
            "issuer": issuer_pub.hex(),
            "block0_next": block0_next_pub.hex(),
            "block1_next": block1_next_pub.hex(),
            "block2_next": block2_next_pub.hex(),
        },
        "private_seeds": {
            # Not pinned — used by the verifier in-process to reproduce.
            "issuer": issuer_priv.hex(),
            "block0_next": block0_next_priv.hex(),
            "block1_next": block1_next_priv.hex(),
            "block2_next": block2_next_priv.hex(),
        },
    }


# ---------------------------------------------------------------------------
# Verifier (Pure-Python, deterministic)
# ---------------------------------------------------------------------------


def _ed25519_verify(pub32: bytes, signature_hex: str, payload: dict) -> bool:
    """Verify Ed25519 signature over SHA-256(JCS(payload))."""
    jcs = _make_jcs_canonicalize()
    digest = hashlib.sha256(jcs(payload)).digest()
    pk = Ed25519PublicKey.from_public_bytes(pub32)
    try:
        pk.verify(bytes.fromhex(signature_hex), digest)
        return True
    except Exception:  # noqa: BLE001 - cryptography raises InvalidSignature
        return False


def _within_time_window(verify_time: str, not_before: str, not_after: str) -> bool:
    """RFC-3339 lexicographic comparison.

    All pinned timestamps in this builder use the same Z-suffixed
    profile so byte-lexicographic comparison agrees with temporal
    order. (No tz-offset variation in the pin-pack.)
    """
    return not_before <= verify_time <= not_after


def verify_chain_under_context(chain: dict, context: str) -> dict:
    """Run the verifier against the chain under one presentation context.

    Returns the deterministic verification-trace dict per spec §6.1.
    The caveat-set-hashes field is computed via §4-CSC.
    """
    verify_time = CONTEXT_TIMES[context]
    audience_in_request = CONTEXT_AUDIENCE[context]

    blocks = chain["chain"]

    # Step 1: signature chain. Each block's signature must verify
    # against the *previous* block's next_pubkey (or issuer for
    # block 0).
    issuer_pub = bytes.fromhex(chain["pubkeys"]["issuer"])
    block0 = blocks[0]
    sig_ok_0 = _ed25519_verify(issuer_pub, block0["signature"], block0["payload"])

    block1 = blocks[1]
    block0_next = bytes.fromhex(block0["payload"]["next_pubkey"])
    sig_ok_1 = _ed25519_verify(block0_next, block1["signature"], block1["payload"])

    block2 = blocks[2]
    block1_next = bytes.fromhex(block1["payload"]["next_pubkey"])
    sig_ok_2 = _ed25519_verify(block1_next, block2["signature"], block2["payload"])

    if not (sig_ok_0 and sig_ok_1 and sig_ok_2):
        return _trace(
            context=context,
            blocks=blocks,
            verify_status="reject",
            verify_reason="signature-chain-invalid",
        )

    # Step 2: time-window check (only authority-block carries window).
    not_before = block0["payload"]["not_before"]
    not_after = block0["payload"]["not_after"]
    if not _within_time_window(verify_time, not_before, not_after):
        return _trace(
            context=context,
            blocks=blocks,
            verify_status="reject",
            verify_reason="time-bound-violated",
        )

    # Step 3: audience-pattern match (authority-block primary audience).
    if not _audience_matches(audience_in_request, block0["payload"]["audience_pattern"]):
        return _trace(
            context=context,
            blocks=blocks,
            verify_status="reject",
            verify_reason="audience-pattern-mismatch",
        )

    # Step 4: attenuation-monotonicity (each append block's audience is
    # a refinement of its parent). For TV-W-2 the refinement is a
    # prefix-string check on the role-string; this matches the
    # pin-stable role-string convention used throughout the builder.
    if not _audience_matches(block1["payload"]["audience_pattern"], block0["payload"]["audience_pattern"]):
        return _trace(
            context=context,
            blocks=blocks,
            verify_status="reject",
            verify_reason="attenuation-violation",
        )
    if not _audience_matches(block2["payload"]["audience_pattern"], block1["payload"]["audience_pattern"]):
        return _trace(
            context=context,
            blocks=blocks,
            verify_status="reject",
            verify_reason="attenuation-violation",
        )

    # All gates pass.
    return _trace(
        context=context,
        blocks=blocks,
        verify_status="accept",
        verify_reason=None,
    )


def _audience_matches(claim: str, pattern: str) -> bool:
    """Audience-pattern matching: claim must extend the pattern.

    A claim ``role=consumer-A,scope=read-only`` matches the pattern
    ``role=consumer-A`` because every pattern attribute is also in
    the claim. A claim ``role=consumer-B`` does not match
    ``role=consumer-A``. This is a minimal but pin-stable
    string-prefix-on-attributes match; a full attribute-DSL is out
    of scope for TV-W-2 (the goal is acceptance/rejection deltas
    across α/β/γ, not full pattern grammar).
    """
    pat_attrs = dict(_split_attrs(pattern))
    claim_attrs = dict(_split_attrs(claim))
    for k, v in pat_attrs.items():
        if claim_attrs.get(k) != v:
            return False
    return True


def _split_attrs(s: str) -> Iterable[Tuple[str, str]]:
    for piece in s.split(","):
        if "=" in piece:
            k, v = piece.split("=", 1)
            yield k.strip(), v.strip()


def _trace(*, context: str, blocks: list, verify_status: str, verify_reason: str | None) -> dict:
    """Construct the verification-trace JSON per spec §6.1."""
    block_hashes = [b["block_hash"] for b in blocks]
    caveat_set_hashes = [
        canonical_caveat_set_hash(b["payload"]["caveats"]).hex()
        for b in blocks
    ]
    next_pubkeys = [b["payload"]["next_pubkey"] for b in blocks]
    return {
        "context": context,
        "block_hashes": block_hashes,
        "caveat_set_hashes": caveat_set_hashes,
        "verify_status": verify_status,
        "verify_reason": verify_reason,
        "next_pubkeys": next_pubkeys,
    }


# ---------------------------------------------------------------------------
# Pin-pack assembly
# ---------------------------------------------------------------------------


def build_pin_pack(*, seed_hex: str = TV_W_2_TEST_SEED_HEX) -> dict:
    """Build the full TV-W-2 pin-pack body (without the top-level hash)."""
    chain = build_chain(seed_hex=seed_hex)

    traces = {
        TV_W_2_CONTEXT_ALPHA: verify_chain_under_context(chain, TV_W_2_CONTEXT_ALPHA),
        TV_W_2_CONTEXT_BETA: verify_chain_under_context(chain, TV_W_2_CONTEXT_BETA),
        TV_W_2_CONTEXT_GAMMA: verify_chain_under_context(chain, TV_W_2_CONTEXT_GAMMA),
    }

    # The pin-pack does NOT carry the private seeds; they are
    # in-process-only. We project the chain into a pin-stable form.
    chain_projection = {
        "issuer_pub_hex_32": chain["pubkeys"]["issuer"],
        "block0_next_pub_hex_32": chain["pubkeys"]["block0_next"],
        "block1_next_pub_hex_32": chain["pubkeys"]["block1_next"],
        "block2_next_pub_hex_32": chain["pubkeys"]["block2_next"],
        "block0": chain["chain"][0],
        "block1": chain["chain"][1],
        "block2": chain["chain"][2],
        "sealing": chain["sealing"],
    }

    return {
        "label": "tv-w-2-capability-token-multi-step",
        "spec": "wirelang/specs/wirelang-tv-strategy.md §2 (Phase-1b Tag-16)",
        "csc_spec": "wirelang/specs/datalog-caveat-vocabulary-phase-2.md §4 + §6",
        "seed_hex": seed_hex,
        "issuer_persona": [TV_W_2_ISSUER_PERSONA_IDX, TV_W_2_ISSUER_SPAWN_COUNTER],
        "issuer_role": TV_W_2_ISSUER_ROLE,
        "not_before": TV_W_2_NOT_BEFORE,
        "not_after": TV_W_2_NOT_AFTER,
        "nonce": TV_W_2_NONCE,
        "context_times": CONTEXT_TIMES,
        "context_audience": CONTEXT_AUDIENCE,
        "chain": chain_projection,
        "traces": traces,
    }


def pin_pack_hash(pin_pack: dict) -> str:
    """SHA-256 of JCS of the pin-pack body."""
    jcs = _make_jcs_canonicalize()
    return hashlib.sha256(jcs(pin_pack)).hexdigest()


def build_pin_pack_with_hash(*, seed_hex: str = TV_W_2_TEST_SEED_HEX) -> dict:
    """Build the pin-pack including the top-level ``pin_pack_sha256``."""
    body = build_pin_pack(seed_hex=seed_hex)
    body["pin_pack_sha256"] = pin_pack_hash(body)
    return body


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_fixture_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "fixtures"
        / "tv-w-2"
        / "pin-pack.json"
    )


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the TV-W-2 capability-token multi-step pin-pack "
            "golden fixture. External auditors can run this against the "
            "documented seed to reproduce the pin-pack hash (acceptance "
            "criterion A1)."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_default_fixture_path(),
        help="Output path for the pin-pack JSON.",
    )
    parser.add_argument(
        "--seed-hex",
        default=TV_W_2_TEST_SEED_HEX,
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
