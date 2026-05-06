# SPDX-License-Identifier: Apache-2.0
"""Full SLIP-0010 ed25519 test-vector regression suite (vectors 1 and 2).

Source URL (200-stamped 2026-05-06):
    https://github.com/satoshilabs/slips/blob/master/slip-0010.md

Vector 1 is also covered inline by ``test_identity_key_derivation``;
fixtures here mirror it (every chain step rather than just the master)
and add Vector 2.

Public-key form note: the SLIP-0010 spec writes ed25519 public keys as
33 bytes with a leading ``0x00`` for size symmetry with secp256k1
compressed points. Our production helper
:func:`wirelang.identity.ed25519_public_from_private` returns the
32-byte raw form (RFC 8032). The fixture stores both
``pub_hex_33`` (spec table) and ``pub_hex_32`` (our library output)
so the test can cross-validate without having to munge the spec form.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirelang.identity.key_derivation import (
    _ckd_priv_ed25519,
    _ed25519_master_from_seed,
    _ExtendedKey,
    ed25519_public_from_private,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "slip0010-ed25519-vectors"
)


def _load_vector(name: str) -> dict:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _derive(seed: bytes, indices: list[int]) -> _ExtendedKey:
    node = _ed25519_master_from_seed(seed)
    for idx in indices:
        node = _ckd_priv_ed25519(node, idx)
    return node


# ---------------------------------------------------------------------------
# Per-step regression cases
# ---------------------------------------------------------------------------


def _all_chain_cases() -> list[tuple[str, str, dict]]:
    cases: list[tuple[str, str, dict]] = []
    for fname in ("vector-1.json", "vector-2.json"):
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
def test_slip0010_ed25519_chain_step_matches_spec(
    vector_label: str, path: str, entry: dict
) -> None:
    """Each spec chain step: derived priv, chain code and pub MUST match."""
    seed_hex = next(
        v["seed_hex"]
        for v in (
            _load_vector("vector-1.json"),
            _load_vector("vector-2.json"),
        )
        if v["vector_label"] == vector_label
    )
    seed = bytes.fromhex(seed_hex)
    node = _derive(seed, list(entry["child_indices"]))
    assert node.private_key.hex() == entry["priv_hex_32"], (
        f"{vector_label} {path}: private key mismatch"
    )
    assert node.chain_code.hex() == entry["chain_code"], (
        f"{vector_label} {path}: chain code mismatch"
    )
    pub = ed25519_public_from_private(node.private_key)
    assert pub.hex() == entry["pub_hex_32"], (
        f"{vector_label} {path}: 32-byte public key mismatch"
    )
    # Spec form: 0x00 || 32-byte pubkey
    assert ("00" + pub.hex()) == entry["pub_hex_33"], (
        f"{vector_label} {path}: spec-form (0x00 prefixed) public key mismatch"
    )


# ---------------------------------------------------------------------------
# Fixture-self-consistency tests (catch JSON edits separate from math drift)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fname", ["vector-1.json", "vector-2.json"])
def test_fixtures_internally_consistent(fname: str) -> None:
    v = _load_vector(fname)
    assert v["spec"].startswith("SLIP-0010")
    assert len(bytes.fromhex(v["seed_hex"])) >= 16
    last_indices: list[int] = []
    for entry in v["chain"]:
        assert len(bytes.fromhex(entry["priv_hex_32"])) == 32
        assert len(bytes.fromhex(entry["chain_code"])) == 32
        assert len(bytes.fromhex(entry["pub_hex_33"])) == 33
        assert len(bytes.fromhex(entry["pub_hex_32"])) == 32
        assert entry["pub_hex_33"].startswith("00")
        assert entry["pub_hex_33"][2:] == entry["pub_hex_32"]
        for idx in entry["child_indices"]:
            assert idx >= 0x8000_0000, (
                "SLIP-0010 ed25519 supports hardened indices only; "
                f"got {idx} in {entry['path']}"
            )
        # The chain extends by one step at a time, prepending all
        # previous indices.
        if last_indices:
            assert entry["child_indices"][: len(last_indices)] == last_indices
        last_indices = list(entry["child_indices"])


def test_master_keys_for_tv1_and_tv2_differ() -> None:
    """Different seeds MUST yield distinct masters; trivial sanity guard."""
    tv1 = _load_vector("vector-1.json")
    tv2 = _load_vector("vector-2.json")
    m1 = next(e for e in tv1["chain"] if e["path"] == "m")
    m2 = next(e for e in tv2["chain"] if e["path"] == "m")
    assert m1["priv_hex_32"] != m2["priv_hex_32"]
    assert m1["chain_code"] != m2["chain_code"]
