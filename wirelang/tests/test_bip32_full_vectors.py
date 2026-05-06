# SPDX-License-Identifier: Apache-2.0
"""Full BIP-32 test-vector regression suite (vectors 1, 2 and 3).

Vector 1 is also covered inline by ``test_identity_key_derivation``;
the fixtures here mirror it and add Vectors 2 and 3 from the canonical
BIP-32 test-vector table.

Source URL (200-stamped 2026-05-06):
    https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki

The Wakir-public ``derive_*`` API hardcodes the
``m/44'/WAKIR'/persona'/spawn'`` path, so this module exercises the
underlying CKD primitives via the package-internal helpers
(``_secp256k1_master_from_seed``, ``_ckd_priv_secp256k1``). That keeps
production callers on the safe Wakir-path API while still letting the
test suite verify the math against the canonical spec vectors.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirelang.identity.key_derivation import (
    _ckd_priv_secp256k1,
    _ExtendedKey,
    _secp256k1_master_from_seed,
    secp256k1_public_from_private,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "bip32-vectors"
)


def _load_vector(name: str) -> dict:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_path(path: str) -> list[int]:
    """Parse a BIP-32 path like ``m/0/2147483647H`` into raw 32-bit indices.

    A trailing ``H`` (or ``'``) marks a hardened index, which sets bit 31.
    """
    if path == "m":
        return []
    parts = path.split("/")
    assert parts[0] == "m", f"path must start with m: {path}"
    indices: list[int] = []
    for p in parts[1:]:
        hardened = p.endswith("H") or p.endswith("'")
        if hardened:
            p = p[:-1]
        idx = int(p)
        if hardened:
            idx += 0x8000_0000
        indices.append(idx)
    return indices


def _derive(seed: bytes, indices: list[int]) -> _ExtendedKey:
    node = _secp256k1_master_from_seed(seed)
    for idx in indices:
        node = _ckd_priv_secp256k1(node, idx)
    return node


# ---------------------------------------------------------------------------
# Generated parametrisation: every (vector, chain-entry) pair becomes a
# pytest case. Failures point at the exact vector + path that broke.
# ---------------------------------------------------------------------------


def _all_chain_cases() -> list[tuple[str, str, dict]]:
    """Return ``(vector_label, path, entry)`` tuples for every chain step."""
    cases: list[tuple[str, str, dict]] = []
    for fname in ("vector-1.json", "vector-2.json", "vector-3.json"):
        v = _load_vector(fname)
        label = v["vector_label"]
        for entry in v["chain"]:
            cases.append((label, entry["path"], entry))
    return cases


CHAIN_CASES = _all_chain_cases()


@pytest.mark.parametrize(
    "vector_label,path,entry",
    CHAIN_CASES,
    ids=[f"{lbl}::{p}" for lbl, p, _ in CHAIN_CASES],
)
def test_bip32_chain_step_matches_spec(
    vector_label: str, path: str, entry: dict
) -> None:
    """For each spec chain step, derived priv/chain/pub MUST match.

    This is the canonical regression check: any future change to
    HMAC-SHA512, point arithmetic, or hardened-index handling will fail
    at least one of these cases and pinpoint the broken step.
    """
    # Fetch the seed from the parent vector (re-loaded by label).
    seed_hex = next(
        v["seed_hex"]
        for v in (
            _load_vector("vector-1.json"),
            _load_vector("vector-2.json"),
            _load_vector("vector-3.json"),
        )
        if v["vector_label"] == vector_label
    )
    seed = bytes.fromhex(seed_hex)
    indices = _parse_path(path)
    node = _derive(seed, indices)
    assert node.private_key.hex() == entry["priv_hex_32"], (
        f"{vector_label} {path}: private key mismatch"
    )
    assert node.chain_code.hex() == entry["chain_code"], (
        f"{vector_label} {path}: chain code mismatch"
    )
    pub = secp256k1_public_from_private(node.private_key, compressed=True)
    assert pub.hex() == entry["pub_hex_33"], (
        f"{vector_label} {path}: compressed public key mismatch"
    )


# ---------------------------------------------------------------------------
# Cross-check the fixture self-consistency (priv→pub and seed-shape).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fname", ["vector-1.json", "vector-2.json", "vector-3.json"]
)
def test_fixtures_internally_consistent(fname: str) -> None:
    """Fixture invariants: hex-form lengths, child_num and depth are sane.

    This is a fixture-quality test, not a derivation test; it catches
    accidental edits to the JSON fixtures (wrong hex length, wrong
    depth) before they masquerade as real-derivation failures.
    """
    v = _load_vector(fname)
    assert v["spec"] == "BIP-32"
    assert isinstance(v["seed_hex"], str)
    assert len(bytes.fromhex(v["seed_hex"])) >= 16
    seen_depths: list[int] = []
    for entry in v["chain"]:
        assert len(bytes.fromhex(entry["priv_hex_32"])) == 32
        assert len(bytes.fromhex(entry["chain_code"])) == 32
        assert len(bytes.fromhex(entry["pub_hex_33"])) == 33
        assert entry["pub_hex_33"][:2] in {"02", "03"}
        assert 0 <= entry["depth"] <= 255
        assert 0 <= entry["child_num"] < 2**32
        seen_depths.append(entry["depth"])
    # depths are monotonically non-decreasing and start at 0
    assert seen_depths[0] == 0
    for prev, cur in zip(seen_depths, seen_depths[1:]):
        assert cur == prev + 1, (
            f"{fname}: depths must increase by 1; got {prev} -> {cur}"
        )


def test_vector_3_master_priv_starts_with_leading_zero_byte() -> None:
    """TV3 is the historical 'leading-zero priv' regression vector.

    If our priv-key serialisation ever drops a leading 0x00 byte, this
    test fires before the more general parametrised test does, so the
    failure message stays diagnostic.
    """
    v = _load_vector("vector-3.json")
    master = next(e for e in v["chain"] if e["path"] == "m")
    assert master["priv_hex_32"].startswith("00")
