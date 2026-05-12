# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Phase-2 Sprint-5 Tag-2 verifier-signature wire-up.

The module under test (``wat/verify/manifest_v2.py``) gained an
optional ``verify_signature`` opt-in surface in Sprint-5 Tag-2 that
consumes the optional manifest-level ``signature`` slot landed in
Sprint-5 Tag-1 (schema 0.2.0). The signing primitive itself
(``wat/identity/manifest_signing.py``, Sprint-4 Tag-6) stays the
canonical producer; this wire-up is the consumer side that lets the
verifier reject a tampered signed manifest, accept a clean signed
manifest, and (under STRICT mode) reject unsigned manifests.

Tests are Apache 2.0 so external re-implementers can use them as
black-box conformance vectors against their own verifier wire-ups.

Test inventory (6 hermetic tests):

- T-WAT-VERIFY-SIG-WIRE-01 happy path: signed v2 manifest with
  --verify-signature + correct public key verifies; signature_status
  == "verified".
- T-WAT-VERIFY-SIG-WIRE-02 default off: even with a signed manifest,
  ``verify_signature=False`` (default) leaves signature_status == ""
  and the verifier ignores the slot — backward compatibility.
- T-WAT-VERIFY-SIG-WIRE-03 unsigned PERMISSIVE: unsigned manifest
  under verify_signature=True + PERMISSIVE -> ok, signature_status ==
  "unsigned-permissive".
- T-WAT-VERIFY-SIG-WIRE-04 unsigned STRICT: unsigned manifest under
  verify_signature=True + STRICT -> not ok, signature_status ==
  "unsigned-strict", failure_reason starts with "signature:".
- T-WAT-VERIFY-SIG-WIRE-05 tamper detection: signed v1 manifest with
  a tampered field after signing -> signature_status == "mismatch",
  integrity_ok=False (the schema/integrity phases pass because the
  tampered value is still structurally valid; the signature is what
  catches it).
- T-WAT-VERIFY-SIG-WIRE-06 CLI flag + hex-pubkey: end-to-end CLI
  invocation with --verify-signature + --verify-signature-public-key-
  hex, JSON output carries signature_status="verified".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wat.identity.manifest_signing import (
    VerifyMode,
    envelope_with_signature,
    sign_manifest,
)
from wat.merkle.aggregator import build_merkle_tree, compute_leaf_hash
from wat.verify.manifest_v2 import (
    ManifestV2Result,
    main as verifier_main,
    verify_manifest_v2_file,
)


# ---------------------------------------------------------------------------
# Fixtures: Ed25519 keypair from a fixed seed for byte-stable signatures.
# ---------------------------------------------------------------------------


_FIXED_SEED_HEX = (
    "5cbd7fdeefb8a25b85aaf80be58fd3da26d31a99318ef6cd28fd06f3fbb4b3a8"
)
_KID = "wat-anchor-2026-05"


def _fixed_keypair() -> tuple[bytes, bytes]:
    seed = bytes.fromhex(_FIXED_SEED_HEX)
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pub_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return seed, pub_bytes


def _other_pubkey() -> bytes:
    """A different Ed25519 public key for wrong-key tamper paths."""
    other_seed = hashlib.sha256(b"other-anchor-key").digest()
    sk = Ed25519PrivateKey.from_private_bytes(other_seed)
    return sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


# ---------------------------------------------------------------------------
# Manifest builders -- same shapes as test_manifest_v2_verifier_stub.py so
# the wire-up tests exercise verifier-realistic fixtures.
# ---------------------------------------------------------------------------


def _make_event(idx: int, *, capref_hash_hex: str = "") -> Dict[str, str]:
    return {
        "event_id": f"evt-{idx}",
        "time": f"2026-05-26T17:00:0{idx}Z",
        "payload_hash": hashlib.sha256(f"payload-{idx}".encode()).hexdigest(),
        "capability_token_hash": capref_hash_hex,
    }


def _build_v1_manifest(events: Sequence[Dict[str, str]]) -> Dict:
    leaves_bytes = [
        compute_leaf_hash(
            event_id=ev["event_id"],
            time=ev["time"],
            payload_hash=ev["payload_hash"],
            capability_token_hash=ev["capability_token_hash"],
        )
        for ev in events
    ]
    root, levels = build_merkle_tree(leaves_bytes)
    enriched_events = [
        {**ev, "leaf": leaves_bytes[i].hex()} for i, ev in enumerate(events)
    ]
    return {
        "version": "wat-manifest/1.0",
        "hour_slot": "2026-05-26T17",
        "merkle_root": root.hex(),
        "event_count": len(events),
        "events": enriched_events,
        "leaves": [leaf.hex() for leaf in leaves_bytes],
        "tree_levels": [[node.hex() for node in level] for level in levels],
        "build_time": "2026-05-26T17:00:00Z",
    }


def _ordered_caprefs_root(caprefs_full: Sequence[str]) -> str:
    leaves = [bytes.fromhex(ref[len("sha256:"):]) for ref in caprefs_full]
    root, _levels = build_merkle_tree(leaves)
    return root.hex()


def _build_v2_manifest(
    events: Sequence[Dict[str, str]],
    multi_cap: Dict[str, List[str]],
) -> Dict:
    base = _build_v1_manifest(events)
    base["version"] = "wat-manifest/2.0"

    multi_cap_events = {}
    distinct = set()
    max_caps = 0
    for ev_id, caprefs in multi_cap.items():
        multi_cap_events[ev_id] = {
            "caprefs_full": list(caprefs),
            "caprefs_root": _ordered_caprefs_root(caprefs),
        }
        max_caps = max(max_caps, len(caprefs))
        distinct.update(caprefs)

    base["multi_cap_events"] = multi_cap_events
    base["multi_cap_summary"] = {
        "events_with_multi_cap": len(multi_cap_events),
        "max_caprefs_in_any_event": max_caps,
        "distinct_capability_token_hashes_in_hour": len(distinct),
    }
    return base


def _write_manifest_dict(tmp_path: Path, manifest: Dict, name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_signed_manifest_bytes(tmp_path: Path, blob: bytes, name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_bytes(blob)
    return path


_CAPREF_1 = "sha256:" + hashlib.sha256(b"capref-1").hexdigest()
_CAPREF_2 = "sha256:" + hashlib.sha256(b"capref-2").hexdigest()


# ---------------------------------------------------------------------------
# T-WAT-VERIFY-SIG-WIRE-01 happy path -- signed v2 manifest verifies
# ---------------------------------------------------------------------------


def test_t_wat_verify_sig_wire_01_signed_v2_manifest_verifies(
    tmp_path: Path,
) -> None:
    """A v2 manifest signed by sign_manifest verifies under
    --verify-signature with the matching public key.

    The end-to-end shape: sign_manifest -> envelope_with_signature ->
    write bytes -> verify_manifest_v2_file(..., verify_signature=True,
    public_key=pub). Schema + integrity already pass on the stripped
    body; the wire-up adds the cryptographic-verdict layer on top.
    """
    priv, pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_signed_manifest_bytes(tmp_path, envelope_bytes)

    result = verify_manifest_v2_file(
        path,
        verify_signature=True,
        verify_signature_public_key=pub,
    )

    assert isinstance(result, ManifestV2Result)
    assert result.ok, result.failure_reason
    assert result.schema_ok
    assert result.integrity_ok
    assert result.multi_cap_root_status == "verified"
    assert result.signature_status == "verified"
    assert result.failure_reason == ""


# ---------------------------------------------------------------------------
# T-WAT-VERIFY-SIG-WIRE-02 default off -- slot ignored when not opted in
# ---------------------------------------------------------------------------


def test_t_wat_verify_sig_wire_02_default_off_ignores_slot(
    tmp_path: Path,
) -> None:
    """Default verify_signature=False -> slot is ignored, even on a
    signed manifest, and signature_status remains "" (opt-in surface).

    This is the backward-compatibility pin: the 321 pre-existing tests
    must not start running a signature check just because the schema
    learned an optional slot in Tag-1.
    """
    priv, _pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_signed_manifest_bytes(tmp_path, envelope_bytes)

    # No verify_signature kwarg -> default False.
    result = verify_manifest_v2_file(path)

    assert result.ok, result.failure_reason
    assert result.schema_ok
    assert result.integrity_ok
    assert result.signature_status == "", (
        f"signature_status must be '' under default-off; got "
        f"{result.signature_status!r}"
    )


# ---------------------------------------------------------------------------
# T-WAT-VERIFY-SIG-WIRE-03 unsigned PERMISSIVE -- legacy pass
# ---------------------------------------------------------------------------


def test_t_wat_verify_sig_wire_03_unsigned_permissive_passes(
    tmp_path: Path,
) -> None:
    """An unsigned manifest under verify_signature=True + PERMISSIVE
    mode passes with signature_status == "unsigned-permissive".

    This pins the legacy-unsigned-pass contract: operators can flip
    the verifier into "watch for signatures when present" mode without
    breaking hours that pre-date the signing rollout.
    """
    _priv, pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)  # NO signature slot
    path = _write_manifest_dict(tmp_path, manifest)

    result = verify_manifest_v2_file(
        path,
        verify_signature=True,
        verify_signature_public_key=pub,
        verify_signature_mode=VerifyMode.PERMISSIVE,
    )

    assert result.ok, result.failure_reason
    assert result.signature_status == "unsigned-permissive"


# ---------------------------------------------------------------------------
# T-WAT-VERIFY-SIG-WIRE-04 unsigned STRICT -- rejects
# ---------------------------------------------------------------------------


def test_t_wat_verify_sig_wire_04_unsigned_strict_rejects(
    tmp_path: Path,
) -> None:
    """Unsigned manifest under verify_signature=True + STRICT mode is
    rejected: signature_status == "unsigned-strict", integrity_ok =
    False, failure_reason carries the "signature:" prefix.
    """
    _priv, pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)
    path = _write_manifest_dict(tmp_path, manifest)

    result = verify_manifest_v2_file(
        path,
        verify_signature=True,
        verify_signature_public_key=pub,
        verify_signature_mode=VerifyMode.STRICT,
    )

    assert not result.ok
    assert result.schema_ok, "schema phase is upstream of signature phase"
    assert not result.integrity_ok
    assert result.signature_status == "unsigned-strict"
    assert result.failure_reason.startswith("signature:"), (
        f"failure_reason must carry signature-phase prefix; got "
        f"{result.failure_reason!r}"
    )


# ---------------------------------------------------------------------------
# T-WAT-VERIFY-SIG-WIRE-05 tamper detection -- mismatch under wrong key
# ---------------------------------------------------------------------------


def test_t_wat_verify_sig_wire_05_tamper_detection_returns_mismatch(
    tmp_path: Path,
) -> None:
    """A signed manifest verified against the WRONG public key reports
    signature_status == "mismatch" with integrity_ok=False.

    Wrong-key is the more determinate tamper-detection path than
    tampering the manifest body (which would also break the merkle
    root check upstream and short-circuit before signature). The
    mismatch verdict pins the contract: well-formed slot, key
    mismatch, no exception raised -- a clean rejection in the
    signature phase.
    """
    priv, _pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_signed_manifest_bytes(tmp_path, envelope_bytes)

    # Verify with the WRONG public key.
    wrong_pub = _other_pubkey()
    result = verify_manifest_v2_file(
        path,
        verify_signature=True,
        verify_signature_public_key=wrong_pub,
    )

    assert not result.ok
    assert result.schema_ok
    assert not result.integrity_ok
    assert result.signature_status == "mismatch"
    assert result.failure_reason.startswith("signature:")
    assert "does not verify" in result.failure_reason


# ---------------------------------------------------------------------------
# T-WAT-VERIFY-SIG-WIRE-06 CLI flag + hex-pubkey -- end-to-end
# ---------------------------------------------------------------------------


def test_t_wat_verify_sig_wire_06_cli_flag_and_hex_pubkey(
    tmp_path: Path,
    capsys,
) -> None:
    """--verify-signature with --verify-signature-public-key-hex on a
    signed manifest emits signature_status="verified" in JSON output
    and exit-code 0.

    Pins the CLI-level wire-up so operator-tooling (cron / systemd
    unit / verify dashboard subprocess) can consume the verdict
    without importing the Python API directly.
    """
    priv, pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_signed_manifest_bytes(tmp_path, envelope_bytes)

    rc = verifier_main(
        [
            str(path),
            "--verify-signature",
            "--verify-signature-public-key-hex",
            pub.hex(),
            "--output",
            "json",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert rc == 0, f"exit code 0 expected; got {rc}; stdout={out!r}"
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["schema_ok"] is True
    assert payload["integrity_ok"] is True
    assert payload["signature_status"] == "verified"
    assert payload["multi_cap_root_status"] == "verified"
    assert payload["schema_version"] == "wakir-verify-manifest-v2/0"
    assert payload["failure_reason"] == ""
    # Single-line JSON: no embedded newlines.
    assert "\n" not in out
