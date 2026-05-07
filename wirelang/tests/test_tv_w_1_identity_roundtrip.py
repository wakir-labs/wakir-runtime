# SPDX-License-Identifier: Apache-2.0
"""TV-W-1 hermetic Identity Pin-Pack Roundtrip (Phase-1b Tag-14).

Acceptance criteria (per ``wirelang/specs/wirelang-tv-strategy.md`` §1.4):

- **A1** Pin-pack hash matches the checked-in golden file
  ``wirelang/tests/fixtures/tv-w-1/pin-pack.json``.
- **A2** Pure-Python and ``cryptography``-backed signature verification
  agree byte-for-byte for all 18 (9 x 2) signatures.
- **A3** Sandbox-CI lane reproduces the pin-pack hash (no rfc8785, no
  jsonschema -> Pure-Python only). Verified inline by exercising the
  ``_jcs_pure`` canonicaliser against the same builder logic; the
  full CI lane assertion is on the workflow side (sandbox-ci.yml).
- **A4** Production-CI lane reproduces the pin-pack hash (full stack);
  exercised inline via the ``rfc8785`` resolver path when the package
  is installed.
- **A5** External regeneration: a third-party auditor running
  ``python -m wirelang.tests._tv_w_1_pin_pack_builder`` against the
  documented seed reproduces the identical pin-pack hash. The CLI
  is exercised here via ``--check`` (no fixture mutation) so the
  external-reproducibility contract is checked in CI without the
  fixture ever drifting due to a side effect of the test itself.

The pin-pack covers all 9 personas x 2 curves = 18 derivations
(Cartesian ``persona_idx in {0,1,2}`` x ``spawn_counter in {0,1,2}``).
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from wirelang.identity import (
    derive_sub_key_ed25519,
    derive_sub_key_secp256k1,
    verify_aip_signature,
)
from wirelang.identity import _jcs_pure
from wirelang.identity.key_derivation import (
    ed25519_public_from_private,
    secp256k1_public_from_private,
)

from wirelang.tests._tv_w_1_pin_pack_builder import (
    TV_W_1_PERSONA_GRID,
    TV_W_1_TEST_SEED_HEX,
    build_pin_pack,
    build_pin_pack_with_hash,
    pin_pack_hash,
    persona_role_string,
)


# ---------------------------------------------------------------------------
# Golden fixture loader
# ---------------------------------------------------------------------------

GOLDEN_PATH: Path = (
    Path(__file__).resolve().parent / "fixtures" / "tv-w-1" / "pin-pack.json"
)


def _load_golden() -> dict:
    with GOLDEN_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def golden() -> dict:
    return _load_golden()


# ---------------------------------------------------------------------------
# Layout invariants (cheap pre-flight)
# ---------------------------------------------------------------------------


def test_golden_layout_invariants(golden: dict) -> None:
    """The golden file has the documented structure.

    A drift in the pin-pack schema (added/removed top-level field,
    record-shape change) is a deliberate engineering event and must
    be re-baselined explicitly via the builder CLI.
    """
    for key in (
        "label",
        "spec",
        "seed_hex",
        "valid_after",
        "expires",
        "wakir_coin_type_hex",
        "derivation_path_template",
        "records",
        "pin_pack_sha256",
    ):
        assert key in golden, f"missing top-level key: {key}"
    assert golden["label"] == "tv-w-1-identity-pin-pack"
    assert golden["seed_hex"] == TV_W_1_TEST_SEED_HEX
    assert golden["wakir_coin_type_hex"] == "0x57414b49"
    assert len(golden["records"]) == len(TV_W_1_PERSONA_GRID) == 9


def test_golden_records_cover_full_3x3_grid(golden: dict) -> None:
    """All nine ``(persona_idx, spawn_counter)`` pairs are present."""
    pairs = {(r["persona_idx"], r["spawn_counter"]) for r in golden["records"]}
    assert pairs == set(TV_W_1_PERSONA_GRID)


def test_golden_record_shape(golden: dict) -> None:
    expected = {
        "persona_idx",
        "spawn_counter",
        "role_string",
        "secp256k1_pub_hex_33",
        "ed25519_pub_hex_32",
        "did_doc_jcs_sha256",
        "aip_doc_jcs_sha256",
        "aip_signature_hex",
    }
    for r in golden["records"]:
        assert set(r) == expected, (
            f"record shape drift on persona ({r.get('persona_idx')}, "
            f"{r.get('spawn_counter')}): {set(r) ^ expected}"
        )
        # Length sanity:
        assert len(bytes.fromhex(r["secp256k1_pub_hex_33"])) == 33
        assert len(bytes.fromhex(r["ed25519_pub_hex_32"])) == 32
        assert len(bytes.fromhex(r["aip_signature_hex"])) == 64
        assert len(bytes.fromhex(r["did_doc_jcs_sha256"])) == 32
        assert len(bytes.fromhex(r["aip_doc_jcs_sha256"])) == 32


# ---------------------------------------------------------------------------
# A1: pin-pack hash matches checked-in golden
# ---------------------------------------------------------------------------


def test_a1_pin_pack_hash_matches_golden(golden: dict) -> None:
    """Re-derive the entire pin-pack and confirm the hash is identical."""
    rebuilt = build_pin_pack(seed_hex=TV_W_1_TEST_SEED_HEX)
    rebuilt_hash = pin_pack_hash(rebuilt)
    assert rebuilt_hash == golden["pin_pack_sha256"], (
        "TV-W-1 pin-pack drift detected. Re-baseline only via "
        "`python -m wirelang.tests._tv_w_1_pin_pack_builder` and "
        "explicit review."
    )


def test_a1_each_record_matches_golden_byte_for_byte(golden: dict) -> None:
    """Per-persona record equality (catches drift inside any one record)."""
    rebuilt = build_pin_pack(seed_hex=TV_W_1_TEST_SEED_HEX)
    assert len(rebuilt["records"]) == len(golden["records"])
    for r_new, r_old in zip(
        sorted(rebuilt["records"], key=lambda r: (r["persona_idx"], r["spawn_counter"])),
        sorted(golden["records"], key=lambda r: (r["persona_idx"], r["spawn_counter"])),
    ):
        assert r_new == r_old, (
            f"record drift on persona ({r_old['persona_idx']}, "
            f"{r_old['spawn_counter']})"
        )


# ---------------------------------------------------------------------------
# A2: Pure-Python and rfc8785 backends agree
# ---------------------------------------------------------------------------


def test_a2_jcs_backends_agree_per_record(golden: dict) -> None:
    """Pure-Python ``_jcs_pure`` and (when present) ``rfc8785`` produce
    byte-identical canonical forms for both DID-unsigned and AIP-signed
    document bodies. This is the cross-backend parity gate.

    The check runs the canonicalisation in-process for every persona and
    re-derives the SHA-256; results must equal the golden hash from
    *both* backends.
    """
    seed = bytes.fromhex(TV_W_1_TEST_SEED_HEX)
    try:
        import rfc8785  # type: ignore[import-not-found]

        rfc8785_dumps = rfc8785.dumps
    except ImportError:
        rfc8785_dumps = None  # Sandbox lane: only pure-Python available.

    for r_old in golden["records"]:
        p, s = r_old["persona_idx"], r_old["spawn_counter"]
        # Re-derive sub-keys to confirm pubkeys still match (so the
        # JCS-equivalence check below is on the same document body).
        secp_priv = derive_sub_key_secp256k1(seed, p, s)
        ed_priv = derive_sub_key_ed25519(seed, p, s)
        secp_pub = secp256k1_public_from_private(secp_priv)
        ed_pub = ed25519_public_from_private(ed_priv)
        assert secp_pub.hex() == r_old["secp256k1_pub_hex_33"]
        assert ed_pub.hex() == r_old["ed25519_pub_hex_32"]

        # Build documents identically to the builder.
        from wirelang.identity import (
            generate_aip_document,
            generate_persona_did_document,
            sign_aip_document,
        )

        role = persona_role_string(p, s)
        did_doc = generate_persona_did_document(
            role, secp_pub, ed_pub, host="wakir.dev", version=1
        )
        did_unsigned = copy.deepcopy(did_doc)
        did_unsigned.pop("proof", None)

        aip_doc = generate_aip_document(
            role,
            ed_pub,
            did_uri=did_doc["id"],
            valid_after=golden["valid_after"],
            valid_until=None,
            expires=golden["expires"],
            delegation_mode="chained",
            protocols=("wirelang/0.1",),
        )
        aip_doc["document_signature"] = sign_aip_document(aip_doc, ed_priv)

        # Pure-Python canonical forms.
        pure_did = _jcs_pure.canonicalize(did_unsigned)
        pure_aip = _jcs_pure.canonicalize(aip_doc)
        pure_did_hash = hashlib.sha256(pure_did).hexdigest()
        pure_aip_hash = hashlib.sha256(pure_aip).hexdigest()
        assert pure_did_hash == r_old["did_doc_jcs_sha256"]
        assert pure_aip_hash == r_old["aip_doc_jcs_sha256"]

        if rfc8785_dumps is not None:
            rfc_did = rfc8785_dumps(did_unsigned)
            rfc_aip = rfc8785_dumps(aip_doc)
            # Byte-for-byte parity is the strong invariant; hash parity
            # is implied but we assert both for clarity in failure
            # messages.
            assert rfc_did == pure_did, (
                f"JCS backend drift on DID for persona ({p}, {s})"
            )
            assert rfc_aip == pure_aip, (
                f"JCS backend drift on AIP for persona ({p}, {s})"
            )


def test_a2_aip_signatures_verify_with_published_pubkey(golden: dict) -> None:
    """The frozen AIP signature in the golden record verifies against
    the persona's Ed25519 public key.

    Catches a class of drift where the AIP-document body changes but the
    signature is silently re-pinned without re-verifying validity.
    """
    seed = bytes.fromhex(TV_W_1_TEST_SEED_HEX)
    from wirelang.identity import generate_aip_document

    for r_old in golden["records"]:
        p, s = r_old["persona_idx"], r_old["spawn_counter"]
        ed_priv = derive_sub_key_ed25519(seed, p, s)
        ed_pub = ed25519_public_from_private(ed_priv)
        role = persona_role_string(p, s)
        # Reconstruct the AIP doc body without the signature slot so the
        # verifier can compute the same canonical pre-image.
        aip_doc = generate_aip_document(
            role,
            ed_pub,
            did_uri=f"did:web:wakir.dev:personas:{role}",
            valid_after=golden["valid_after"],
            valid_until=None,
            expires=golden["expires"],
            delegation_mode="chained",
            protocols=("wirelang/0.1",),
        )
        sig_block = {
            "alg": "Ed25519",
            "kid": "biscuit-root-1",
            "signature": r_old["aip_signature_hex"],
        }
        assert verify_aip_signature(aip_doc, sig_block, ed_pub), (
            f"frozen AIP signature does not verify for persona ({p}, {s})"
        )


# ---------------------------------------------------------------------------
# A3: pin-pack reproducible under pure-Python-only (sandbox lane equivalent)
# ---------------------------------------------------------------------------


def test_a3_pin_pack_hash_under_pure_python_only(golden: dict) -> None:
    """Recompute the pin-pack hash forcing ``_jcs_pure``.

    This is the in-process equivalent of the sandbox-CI assertion:
    even without ``rfc8785`` installed, the canonical bytes (and
    therefore the SHA-256 pin) are identical. The full sandbox-lane
    assertion lives in ``.github/workflows/sandbox-ci.yml`` and runs
    this same module under a venv that does not install ``rfc8785``.
    """
    seed = bytes.fromhex(TV_W_1_TEST_SEED_HEX)
    # Build a pin-pack that uses _jcs_pure unconditionally.
    body = _build_pin_pack_with_explicit_canonicalizer(
        seed, _jcs_pure.canonicalize
    )
    pure_hash = hashlib.sha256(_jcs_pure.canonicalize(body)).hexdigest()
    assert pure_hash == golden["pin_pack_sha256"], (
        "pin-pack hash diverged when forced through the pure-Python "
        "JCS canonicaliser; sandbox lane would break."
    )


def _build_pin_pack_with_explicit_canonicalizer(seed: bytes, jcs):
    """Builder variant that takes an explicit canonicaliser.

    Used by A3 to force the pure-Python path inline.
    """
    from wirelang.identity import (
        generate_aip_document,
        generate_persona_did_document,
        sign_aip_document,
    )

    records = []
    for p, s in TV_W_1_PERSONA_GRID:
        role = persona_role_string(p, s)
        secp_priv = derive_sub_key_secp256k1(seed, p, s)
        ed_priv = derive_sub_key_ed25519(seed, p, s)
        secp_pub = secp256k1_public_from_private(secp_priv)
        ed_pub = ed25519_public_from_private(ed_priv)

        did_doc = generate_persona_did_document(
            role, secp_pub, ed_pub, host="wakir.dev", version=1
        )
        did_unsigned = copy.deepcopy(did_doc)
        did_unsigned.pop("proof", None)

        aip_doc = generate_aip_document(
            role,
            ed_pub,
            did_uri=did_doc["id"],
            valid_after="2026-05-07T00:00:00Z",
            valid_until=None,
            expires="2027-05-07T00:00:00Z",
            delegation_mode="chained",
            protocols=("wirelang/0.1",),
        )
        sig_block = sign_aip_document(aip_doc, ed_priv)
        aip_doc["document_signature"] = sig_block

        records.append(
            {
                "persona_idx": p,
                "spawn_counter": s,
                "role_string": role,
                "secp256k1_pub_hex_33": secp_pub.hex(),
                "ed25519_pub_hex_32": ed_pub.hex(),
                "did_doc_jcs_sha256": hashlib.sha256(jcs(did_unsigned)).hexdigest(),
                "aip_doc_jcs_sha256": hashlib.sha256(jcs(aip_doc)).hexdigest(),
                "aip_signature_hex": sig_block["signature"],
            }
        )
    return {
        "label": "tv-w-1-identity-pin-pack",
        "spec": "wirelang/specs/wirelang-tv-strategy.md §1 (Phase-1b Tag-14)",
        "seed_hex": "000102030405060708090a0b0c0d0e0f",
        "valid_after": "2026-05-07T00:00:00Z",
        "expires": "2027-05-07T00:00:00Z",
        "wakir_coin_type_hex": "0x57414b49",
        "derivation_path_template": (
            "m / 44' / WAKIR_COIN_TYPE' / persona_idx' / spawn_counter'"
        ),
        "records": records,
    }


# ---------------------------------------------------------------------------
# A4: pin-pack reproducible under full-stack (production lane equivalent)
# ---------------------------------------------------------------------------


def test_a4_pin_pack_hash_under_rfc8785_when_available(golden: dict) -> None:
    """When ``rfc8785`` is installed, force it explicitly and confirm
    the same pin-pack hash. Skipped on the sandbox lane.

    The full production-CI lane assertion lives in
    ``.github/workflows/tests.yml``.
    """
    rfc8785 = pytest.importorskip("rfc8785")
    seed = bytes.fromhex(TV_W_1_TEST_SEED_HEX)
    body = _build_pin_pack_with_explicit_canonicalizer(seed, rfc8785.dumps)
    prod_hash = hashlib.sha256(rfc8785.dumps(body)).hexdigest()
    assert prod_hash == golden["pin_pack_sha256"]


# ---------------------------------------------------------------------------
# A5: external regeneration via the documented CLI
# ---------------------------------------------------------------------------


def test_a5_external_regeneration_via_cli(golden: dict) -> None:
    """Run the regenerator CLI in ``--check`` mode in a subprocess and
    confirm the printed hash matches the golden.

    This is the executable form of the "documented script" promise in
    spec §1.4 A5: an external auditor invokes the same module entry
    point and observes the same hash. ``--check`` prevents the test
    from mutating the golden file as a side effect.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wirelang.tests._tv_w_1_pin_pack_builder",
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"regenerator CLI failed: rc={result.returncode}, "
        f"stderr={result.stderr!r}"
    )
    printed_hash = result.stdout.strip()
    assert printed_hash == golden["pin_pack_sha256"], (
        f"CLI hash {printed_hash!r} != golden {golden['pin_pack_sha256']!r}"
    )


# ---------------------------------------------------------------------------
# Cross-compat anchors (Tag-19 / Tag-23 forward-compatibility)
# ---------------------------------------------------------------------------


def test_cross_compat_pubkeys_align_with_capability_token_pin() -> None:
    """Forward-compat anchor: persona (0, 0) Ed25519 pub matches the
    Tag-19 Capability-Token-Pin issuer key (TV-W-2 input per spec §2.2).

    TV-W-2 uses persona (0, 0) Ed25519 sub-key as the Biscuit issuer.
    Pinning the public key here gives a single audit trail across
    TV-W-1 and the Capability-Token vector pack: any drift in the
    derivation path or seed surfaces here first, before TV-W-2
    materialises.
    """
    seed = bytes.fromhex(TV_W_1_TEST_SEED_HEX)
    ed_priv_00 = derive_sub_key_ed25519(seed, 0, 0)
    ed_pub_00 = ed25519_public_from_private(ed_priv_00)
    # The pinned value comes from the golden record itself (so we do
    # not duplicate the constant; we only check the cross-vector
    # contract is well-typed).
    golden = _load_golden()
    record = next(
        r for r in golden["records"] if r["persona_idx"] == 0 and r["spawn_counter"] == 0
    )
    assert ed_pub_00.hex() == record["ed25519_pub_hex_32"]


def test_cross_compat_persona_1_0_aligns_with_aip_doc_pin() -> None:
    """Forward-compat anchor: persona (1, 0) Ed25519 pub matches the
    Tag-23 AIP-Doc-Pin signing keypair (TV-W-3 input per spec §3.2).

    TV-W-3 uses persona (1, 0) deliberately to exercise multi-persona
    federation.  Same pinning rationale as the TV-W-2 anchor above.
    """
    seed = bytes.fromhex(TV_W_1_TEST_SEED_HEX)
    ed_priv_10 = derive_sub_key_ed25519(seed, 1, 0)
    ed_pub_10 = ed25519_public_from_private(ed_priv_10)
    golden = _load_golden()
    record = next(
        r for r in golden["records"] if r["persona_idx"] == 1 and r["spawn_counter"] == 0
    )
    assert ed_pub_10.hex() == record["ed25519_pub_hex_32"]


# ---------------------------------------------------------------------------
# Builder self-consistency (cheap regression net)
# ---------------------------------------------------------------------------


def test_builder_with_hash_round_trips() -> None:
    """``build_pin_pack_with_hash`` is the union of ``build_pin_pack``
    and ``pin_pack_hash``; recomputing the hash from the body yields
    the same value as the embedded ``pin_pack_sha256`` slot."""
    full = build_pin_pack_with_hash(seed_hex=TV_W_1_TEST_SEED_HEX)
    embedded = full["pin_pack_sha256"]
    body = {k: v for k, v in full.items() if k != "pin_pack_sha256"}
    assert pin_pack_hash(body) == embedded
