# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""PEM/PKCS#8 ``--sign-key`` format acceptance tests.

Sprint-6-Tag-5 Item 2 (Mira multi-item box). Sprint-6-Tag-3
Folge-Item 2 follow-up: extend the aggregator's ``--sign-key``
acceptance from hex-only to ``hex + unencrypted PEM/PKCS#8``.
Format is detected by content sniff (PEM begins with ``-----BEGIN``);
the hex path is unchanged and remains the canonical compact form.

Coverage matrix
---------------

Positive:

* hex (sanity re-pin, format unchanged): build_command(sign_key=<hex
  file>) produces signed manifest. Existing tests in
  ``test_aggregator_signing.py`` cover this thoroughly; one
  byte-identical-output cross-check pin lives here so the cross-
  format equivalence is asserted in one place.
* PEM/PKCS#8 unencrypted: build_command(sign_key=<PEM file>)
  produces signed manifest with the same signature bytes as the
  hex-Variant when both key files carry the same underlying seed.
* PEM produced by openssl genpkey shape (-----BEGIN PRIVATE KEY-----
  PKCS#8 envelope): accepted.

Negative:

* PEM, but not Ed25519 (RSA): rejected with algorithm-specific
  error message.
* PEM, but malformed: rejected with PEM-malformed error.
* Encrypted PEM (PKCS#8 with passphrase): rejected; the
  unattended cron has no place to source a passphrase.
* Non-PEM, non-hex garbage: hex-fail message (backward-compat with
  the existing ``test_sign_key_not_hex`` expectation).

Backward-compat
---------------

All existing ``--sign-key`` hex tests in
``test_aggregator_signing.py`` keep passing unchanged. The format
detection is non-disruptive: only files whose stripped first line
starts with ``-----BEGIN`` route to the PEM path; everything else
takes the original hex path.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wat.cmd.aggregator_cli import (
    ValidationError,
    build_command,
)
from wat.identity.manifest_signing import (
    SIGNATURE_FIELD,
    VerifyMode,
    verify_manifest_signature,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(idx: int, hour: str = "2026-05-11T12") -> Dict[str, str]:
    return {
        "event_id": f"evt-sig-pem-{idx:04d}",
        "time": f"{hour}:{idx:02d}:00Z",
        "payload_hash": f"{idx:064x}",
        "capability_token_hash": f"{(idx + 1):064x}",
    }


def _write_jsonl(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _ed25519_keypair() -> Tuple[Ed25519PrivateKey, bytes, bytes]:
    """Return ``(priv-object, seed-bytes, pub-bytes)``."""
    priv = Ed25519PrivateKey.generate()
    return (
        priv,
        priv.private_bytes_raw(),
        priv.public_key().public_bytes_raw(),
    )


def _write_pem_pkcs8_unencrypted(priv: Ed25519PrivateKey, path: Path) -> Path:
    """Write the priv key as unencrypted PKCS#8 PEM (openssl format)."""
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    return path


def _write_pem_pkcs8_encrypted(
    priv: Ed25519PrivateKey, path: Path, passphrase: bytes
) -> Path:
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase),
    )
    path.write_bytes(pem)
    return path


def _write_rsa_pem(path: Path) -> Path:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    return path


# ---------------------------------------------------------------------------
# Positive: PEM/PKCS#8 accepted
# ---------------------------------------------------------------------------


def test_build_command_signed_with_pem_pkcs8(tmp_path: Path) -> None:
    """T-WAT-SIG-AGG-PEM-01: PEM/PKCS#8 produces a verifiable signed manifest.

    Same aggregator path as hex; the PEM is parsed via
    ``cryptography``'s ``load_pem_private_key`` into the same raw
    seed the hex path would have produced.
    """
    priv, _seed, pub = _ed25519_keypair()
    key_file = _write_pem_pkcs8_unencrypted(priv, tmp_path / "key.pem")
    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, [_make_event(i) for i in range(3)])
    out = tmp_path / "manifest.json"

    manifest = build_command(
        hour="2026-05-11T12",
        input_events=spool,
        output_manifest=out,
        sign_key=key_file,
        sign_kid="kid-agg-sig-pem-01",
    )

    assert SIGNATURE_FIELD in manifest
    sig = manifest[SIGNATURE_FIELD]
    assert sig["alg"] == "Ed25519"
    assert sig["kid"] == "kid-agg-sig-pem-01"

    # Verifier-side round-trip: signed manifest verifies under the
    # public key derived from the same PEM.
    assert verify_manifest_signature(
        manifest,
        pub,
        mode=VerifyMode.STRICT,
    ) is True


def test_build_command_pem_and_hex_produce_identical_signature_bytes(
    tmp_path: Path,
) -> None:
    """T-WAT-SIG-AGG-PEM-02: cross-format equivalence pin.

    For the same underlying seed, the hex and PEM key files must
    produce byte-identical signature bytes on the same manifest body
    (Ed25519 is deterministic per RFC 8032; the aggregator must not
    materialise a different key from the same seed depending on
    file format). This is the substantive backward-compat guarantee:
    rotating an operator from hex to PEM cannot change which manifests
    historically verify.
    """
    priv, seed, _pub = _ed25519_keypair()

    hex_file = tmp_path / "key.hex"
    hex_file.write_text(seed.hex(), encoding="utf-8")

    pem_file = _write_pem_pkcs8_unencrypted(priv, tmp_path / "key.pem")

    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, [_make_event(i) for i in range(3)])

    # Hour A: hex.
    out_hex = tmp_path / "manifest-hex.json"
    m_hex = build_command(
        hour="2026-05-11T12",
        input_events=spool,
        output_manifest=out_hex,
        sign_key=hex_file,
        sign_kid="kid-cross-format-eq",
    )

    # Hour B (identical body): PEM.
    out_pem = tmp_path / "manifest-pem.json"
    m_pem = build_command(
        hour="2026-05-11T12",
        input_events=spool,
        output_manifest=out_pem,
        sign_key=pem_file,
        sign_kid="kid-cross-format-eq",
    )

    assert m_hex[SIGNATURE_FIELD]["signature"] == m_pem[SIGNATURE_FIELD]["signature"], (
        "hex and PEM with the same underlying seed must produce "
        "byte-identical signature bytes"
    )
    assert m_hex[SIGNATURE_FIELD]["kid"] == m_pem[SIGNATURE_FIELD]["kid"]
    assert m_hex[SIGNATURE_FIELD]["alg"] == m_pem[SIGNATURE_FIELD]["alg"]


def test_build_command_pem_with_leading_whitespace_accepted(tmp_path: Path) -> None:
    """T-WAT-SIG-AGG-PEM-03: leading whitespace before PEM header is tolerated.

    Operators who copy-paste PEM material from email / chat clients
    often acquire leading whitespace. The format sniff strips the
    raw payload before checking the BEGIN marker, so this still
    routes to the PEM path.
    """
    priv, _seed, _pub = _ed25519_keypair()
    pem_bytes = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "key.pem"
    # Prepend stray whitespace operators commonly introduce.
    key_file.write_bytes(b"   \n  " + pem_bytes)

    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, [_make_event(0)])
    out = tmp_path / "manifest.json"

    manifest = build_command(
        hour="2026-05-11T12",
        input_events=spool,
        output_manifest=out,
        sign_key=key_file,
        sign_kid="kid-agg-sig-pem-ws",
    )
    assert SIGNATURE_FIELD in manifest


# ---------------------------------------------------------------------------
# Positive: hex still works (backward-compat sanity)
# ---------------------------------------------------------------------------


def test_build_command_hex_still_accepted_after_pem_extension(tmp_path: Path) -> None:
    """T-WAT-SIG-AGG-PEM-04: hex path unchanged by the PEM extension.

    The format sniff routes only PEM-marked files to the new path;
    everything else takes the original hex path. This pin guards
    against an accidental regression in the format-detection branch.
    """
    priv, seed, pub = _ed25519_keypair()
    hex_file = tmp_path / "key.hex"
    hex_file.write_text(seed.hex() + "\n", encoding="utf-8")  # trailing NL.

    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, [_make_event(0)])
    out = tmp_path / "manifest.json"

    manifest = build_command(
        hour="2026-05-11T12",
        input_events=spool,
        output_manifest=out,
        sign_key=hex_file,
        sign_kid="kid-hex-backcompat",
    )
    assert SIGNATURE_FIELD in manifest
    assert verify_manifest_signature(
        manifest, pub, mode=VerifyMode.STRICT
    ) is True


# ---------------------------------------------------------------------------
# Negative: non-Ed25519 PEM rejected
# ---------------------------------------------------------------------------


def test_build_command_pem_rsa_rejected(tmp_path: Path) -> None:
    """T-WAT-SIG-AGG-PEM-NEG-01: RSA PEM rejected with type-specific error.

    Operator-readability: an operator who mis-pasted an RSA private
    key gets a message naming the expected algorithm rather than a
    cryptography-library stack trace.
    """
    key_file = _write_rsa_pem(tmp_path / "rsa.pem")
    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, [_make_event(0)])
    out = tmp_path / "manifest.json"

    with pytest.raises(ValidationError, match="must be an Ed25519 private key"):
        build_command(
            hour="2026-05-11T12",
            input_events=spool,
            output_manifest=out,
            sign_key=key_file,
            sign_kid="kid-pem-rsa-rejected",
        )


# ---------------------------------------------------------------------------
# Negative: malformed PEM rejected
# ---------------------------------------------------------------------------


def test_build_command_pem_malformed_rejected(tmp_path: Path) -> None:
    """T-WAT-SIG-AGG-PEM-NEG-02: malformed PEM rejected with PEM-specific error.

    A file that LOOKS like PEM (BEGIN marker present) but whose body
    is malformed must surface as a PEM-malformed error, not silently
    fall through to the hex path.
    """
    key_file = tmp_path / "broken.pem"
    key_file.write_text(
        "-----BEGIN PRIVATE KEY-----\n"
        "this-is-not-valid-base64-PEM-data\n"
        "-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, [_make_event(0)])
    out = tmp_path / "manifest.json"

    with pytest.raises(ValidationError, match="PEM is malformed"):
        build_command(
            hour="2026-05-11T12",
            input_events=spool,
            output_manifest=out,
            sign_key=key_file,
            sign_kid="kid-pem-malformed",
        )


# ---------------------------------------------------------------------------
# Negative: encrypted PEM rejected
# ---------------------------------------------------------------------------


def test_build_command_pem_encrypted_rejected(tmp_path: Path) -> None:
    """T-WAT-SIG-AGG-PEM-NEG-03: encrypted PEM rejected on the agg path.

    The unattended cron driver has no place to source a passphrase.
    Encrypted PEMs surface a clear error so the operator decrypts
    into a tmpfs file ahead of the cron call rather than wondering
    why the signing call hangs / crashes obscurely.
    """
    priv, _seed, _pub = _ed25519_keypair()
    key_file = _write_pem_pkcs8_encrypted(
        priv, tmp_path / "enc.pem", b"correct-horse-battery-staple"
    )
    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, [_make_event(0)])
    out = tmp_path / "manifest.json"

    with pytest.raises(ValidationError, match="PEM is encrypted"):
        build_command(
            hour="2026-05-11T12",
            input_events=spool,
            output_manifest=out,
            sign_key=key_file,
            sign_kid="kid-pem-encrypted",
        )


# ---------------------------------------------------------------------------
# Backward-compat: non-PEM non-hex still surfaces as hex-fail
# ---------------------------------------------------------------------------


def test_build_command_non_pem_non_hex_falls_through_to_hex_fail(
    tmp_path: Path,
) -> None:
    """T-WAT-SIG-AGG-PEM-NEG-04: garbage payload routes to hex path.

    A file that is neither PEM (no BEGIN marker) nor valid hex falls
    through to the original hex error message. Backward-compat with
    the Sprint-6-Tag-3 ``test_sign_key_not_hex`` expectation in
    ``test_aggregator_signing.py``.
    """
    key_file = tmp_path / "garbage.bin"
    key_file.write_text("definitely-not-hex-or-PEM", encoding="utf-8")
    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, [_make_event(0)])
    out = tmp_path / "manifest.json"

    with pytest.raises(ValidationError, match="not valid hex"):
        build_command(
            hour="2026-05-11T12",
            input_events=spool,
            output_manifest=out,
            sign_key=key_file,
            sign_kid="kid-fallthrough",
        )
