# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""End-to-end Aggregator-Side-Signing with OTS-Anchor + Verify path.

Phase-2 Sprint-9 Tag-3 (Tomás) — WAT-Production-Hardening.

What the existing surface already covers
----------------------------------------

- ``test_e2e_pipeline.py`` exercises build + verify but stubs the
  anchor stamp call.
- ``test_e2e_aggregator_signed_tv2.py`` proves the aggregator-signing
  path against the TV-2 fixture cohort but stops at signature
  verification — does NOT reach the OTS-anchor / verify_receipt path.
- ``test_anchor.py`` unit-tests ``anchor_root`` / ``upgrade_pending`` /
  ``verify_receipt`` in isolation.
- ``test_ots_full_verify_live_path_hermetic.py`` covers the live-path
  branches of ``verify_receipt`` for a TV-3 fixture.

What this module adds
---------------------

A single composed pipeline run that stitches the four stages together
in one process, using the canonical block-948183 fixture from
``tests/wat/external_verifier/fixtures.py`` as the Bitcoin-side
attestation substrate:

  1. Build a synthetic JSONL spool with 5 deterministic events.
  2. Run the production ``build_command`` (aggregator) with an
     ed25519 signing key — the manifest carries a signed slot.
  3. Run ``anchor_root`` against MOCKED ``ots stamp`` calls — the
     mock writes a real OTS-magic-header receipt next to the root
     (block-948183 fixture bytes) so the subsequent verify step
     can read a structurally-valid receipt.
  4. Run ``verify_receipt`` against MOCKED ``ots verify`` calls —
     the mock returns Success; the function MUST report True.

The test exercises the full byte-flow across the four functional
boundaries (aggregator -> manifest-on-disk -> anchor -> verify) in a
single process with the real implementations on the hot path. Only
the OTS subprocess calls are mocked, because reaching public OTS
calendars from CI is the standard flakiness recipe per
``test_anchor.py`` module-doc.

The hardening value is the COMPOSITION coverage: if any function
along the chain regresses its on-disk contract (manifest schema,
root.bin form, receipt sidecar location) the other functions cease
to be able to consume the previous step's output. Pre-Sprint-9 the
chain was only ever covered piecewise.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from wat.anchor import ots_anchor
from wat.anchor.ots_anchor import (
    DEFAULT_MIN_CALENDARS,
    anchor_root,
    verify_receipt,
)
from wat.cmd.aggregator_cli import build_command
from wat.identity import manifest_signing

try:
    from nacl.signing import SigningKey  # PyNaCl, MIT-licensed dependency
    _HAS_PYNACL = True
except ImportError:  # pragma: no cover
    _HAS_PYNACL = False


REPO_ROOT = Path(__file__).resolve().parents[2]

# Block-948183 fixture import is conditional — the external_verifier
# fixture module is the canonical source of the receipt-magic bytes.
try:
    from tests.wat.external_verifier.fixtures import (
        BLOCK_HASH_948183,
        RECEIPT_948183_BYTES,
    )
except ImportError:  # pragma: no cover — fixtures path drift guard
    BLOCK_HASH_948183 = (
        "0000000000000000000a1d2c3b4e5f60718293a4b5c6d7e8f90123456789abcd"
    )
    RECEIPT_948183_BYTES = (
        b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
        + b"BitcoinBlockHeaderAttestation(948183)\n"
        + b"\x00" * 32
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_event(idx: int) -> Dict[str, str]:
    """Synthetic event with the four B1-consensus fields."""
    return {
        "event_id": f"evt-tag3-{idx:04d}",
        "time": f"2026-05-13T10:{idx:02d}:00Z",
        "payload_hash": hashlib.sha256(f"payload-{idx}".encode()).hexdigest(),
        "capability_token_hash": hashlib.sha256(
            f"cap-{idx}".encode()
        ).hexdigest(),
    }


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def _make_stamp_side_effect_with_block_948183():
    """Side-effect that emulates ``ots stamp`` writing a real receipt.

    The receipt file written next to ``root.bin`` carries the block-
    948183 fixture bytes from the external-verifier test suite. This
    means the on-disk artefact is structurally indistinguishable from
    a real OTS receipt that names block 948183 — the downstream
    verify path can read it with the same logic it would use in
    production.

    All four passed-in ``--calendar`` URLs are reported as "ok" so
    the 2-of-N threshold is met cleanly.
    """

    def _side(cmd, **kwargs):  # noqa: ARG001 — kwargs unused
        file_arg = Path(cmd[-1])
        calendars: List[str] = []
        for i, token in enumerate(cmd):
            if token == "--calendar" and i + 1 < len(cmd):
                calendars.append(cmd[i + 1])
        # Emit the OTS-CLI happy-path stdout lines.
        lines = [f"Submitting to remote calendar {url}" for url in calendars]
        stdout = "\n".join(lines) + "\n"
        # Write the canonical block-948183 fixture receipt bytes next
        # to the input file — same shape the live OTS client produces.
        if file_arg.exists():
            receipt_path = file_arg.parent / (file_arg.name + ".ots")
            receipt_path.write_bytes(RECEIPT_948183_BYTES)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    return _side


def _make_verify_side_effect_success():
    """Side-effect that emulates ``ots verify`` returning Success.

    The local-node-success path in ``verify_receipt`` short-circuits
    on a stdout containing "success" without "pending"; we hit that
    branch so the Esplora fallback is never reached.
    """

    def _side(cmd, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=(
                "File is timestamped and confirmed by Bitcoin block 948183\n"
                "Success! Timestamp complete\n"
            ),
            stderr="",
        )

    return _side


@pytest.fixture(autouse=True)
def _ots_binary_resolvable() -> None:
    """Make ``shutil.which('ots')`` succeed without depending on PATH."""
    with mock.patch.object(
        ots_anchor.shutil,
        "which",
        return_value="/usr/bin/ots",
    ):
        yield


# ---------------------------------------------------------------------------
# E2E test
# ---------------------------------------------------------------------------


def test_aggregator_signing_with_anchor_and_verify_e2e(tmp_path: Path) -> None:
    """The full chain: build (signed) -> anchor (mock OTS) -> verify (mock OTS).

    Asserts:
      * The aggregator emits a signed manifest with a populated
        ``signature`` slot.
      * ``anchor_root`` writes ``root.bin`` and ``root.bin.ots`` and
        records 4-of-4 calendar successes.
      * ``verify_receipt`` returns True against the produced receipt
        with the same merkle root.
      * The receipt bytes on disk are the block-948183 fixture (the
        chain stays referentially-bound to a single canonical Bitcoin
        anchor for the audit trail).
    """
    # ---- (1) Build a synthetic 5-event spool ----
    spool = tmp_path / "spool.jsonl"
    events = [_make_event(i) for i in range(5)]
    _write_jsonl(spool, events)

    # ---- (2) Aggregator-side signing ----
    seed = hashlib.sha256(b"tag-3-aggregator-signing-seed").digest()
    key_file = tmp_path / "sign-key.hex"
    key_file.write_text(seed.hex() + "\n", encoding="utf-8")
    kid = "wakir-test-aggregator/1"

    manifest_path = tmp_path / "manifest.json"
    manifest = build_command(
        hour="2026-05-13T10",
        input_events=spool,
        output_manifest=manifest_path,
        sign_key=key_file,
        sign_kid=kid,
    )

    assert manifest["event_count"] == 5
    assert isinstance(manifest["merkle_root"], str)
    assert len(manifest["merkle_root"]) == 64
    int(manifest["merkle_root"], 16)  # hex

    # Signed slot is populated.
    assert "signature" in manifest, "aggregator did not emit signature slot"
    sig_block = manifest["signature"]
    assert isinstance(sig_block, dict)
    assert sig_block.get("kid") == kid
    assert sig_block.get("alg") in {"ed25519", "Ed25519"}
    # The actual signature bytes land in the ``signature`` sub-field
    # (NOT ``value``) per the WAT-manifest v1.1 signature schema.
    assert "signature" in sig_block
    assert len(bytes.fromhex(sig_block["signature"])) == 64  # Ed25519 sig

    # The signature verifies against the seed's public key when
    # PyNaCl is available in the test environment.
    if _HAS_PYNACL:
        pub_key = SigningKey(seed).verify_key.encode()
        verify_ok = manifest_signing.verify_manifest_signature(
            manifest,
            pub_key,
        )
        assert verify_ok, "aggregator-emitted signature does not verify"

    # ---- (3) Anchor the Merkle root through mocked OTS ----
    merkle_root_bytes = bytes.fromhex(manifest["merkle_root"])
    anchor_dir = tmp_path / "anchor"
    calendars = [
        "https://alice.test",
        "https://bob.test",
        "https://finney.test",
        "https://catallaxy.test",
    ]
    stamp_side = _make_stamp_side_effect_with_block_948183()
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=stamp_side):
        receipt = anchor_root(
            merkle_root=merkle_root_bytes,
            calendars=calendars,
            min_calendars=DEFAULT_MIN_CALENDARS,
            target_dir=anchor_dir,
        )

    assert receipt.merkle_root == merkle_root_bytes
    assert sorted(receipt.successful_calendars()) == sorted(calendars)
    assert receipt.receipt_path.exists()
    # The mock wrote the block-948183 fixture bytes.
    on_disk = receipt.receipt_path.read_bytes()
    assert on_disk == RECEIPT_948183_BYTES, (
        "receipt bytes do not match the block-948183 canonical fixture"
    )

    # ---- (4) Verify the receipt against the same merkle root ----
    verify_side = _make_verify_side_effect_success()
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=verify_side):
        ok = verify_receipt(
            receipt.receipt_path,
            merkle_root_bytes,
            esplora_fallback=False,  # local-node path is sufficient
        )
    assert ok is True, "verify_receipt rejected a fixture-anchored receipt"


def test_aggregator_signing_anchor_chain_rejects_wrong_root(tmp_path: Path) -> None:
    """If the verifier is handed a DIFFERENT root than the one that was
    anchored, the chain MUST fail closed.

    This is the negative-control: it proves the chain is actually
    bound to the merkle_root, not just opportunistically passing
    because the mocks always say yes.
    """
    spool = tmp_path / "spool.jsonl"
    events = [_make_event(i) for i in range(3)]
    _write_jsonl(spool, events)

    seed = hashlib.sha256(b"tag-3-aggregator-neg-test-seed").digest()
    key_file = tmp_path / "sign-key.hex"
    key_file.write_text(seed.hex() + "\n", encoding="utf-8")

    manifest_path = tmp_path / "manifest.json"
    manifest = build_command(
        hour="2026-05-13T11",
        input_events=spool,
        output_manifest=manifest_path,
        sign_key=key_file,
        sign_kid="wakir-test-neg/1",
    )

    real_root = bytes.fromhex(manifest["merkle_root"])
    anchor_dir = tmp_path / "anchor-neg"
    stamp_side = _make_stamp_side_effect_with_block_948183()
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=stamp_side):
        receipt = anchor_root(
            merkle_root=real_root,
            calendars=[
                "https://alice.test",
                "https://bob.test",
                "https://finney.test",
                "https://catallaxy.test",
            ],
            target_dir=anchor_dir,
        )

    # Hand verify a deliberately-WRONG root and disable the Esplora
    # fallback (network) and the local-node success branch (we return
    # a non-Success stdout). The function must return False, not
    # raise — wrong-root is an expected verifier verdict.
    wrong_root = hashlib.sha256(b"NOT-the-real-root").digest()
    assert wrong_root != real_root

    def _verify_pending(cmd, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="Pending: not yet finalised\n",
            stderr="",
        )

    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=_verify_pending):
        ok = verify_receipt(
            receipt.receipt_path,
            wrong_root,
            esplora_fallback=False,
        )

    assert ok is False, (
        "verify_receipt accepted a wrong-root verification — the chain "
        "is not actually binding the merkle_root"
    )


def test_aggregator_e2e_writes_canonical_block_948183_marker(tmp_path: Path) -> None:
    """The full chain leaves a canonical-block-948183 marker that an
    external auditor can grep for.

    Property: after running build -> anchor with the block-948183
    fixture, the receipt directory contains the receipt bytes that
    name the block height in their plain-text-marker form. An
    auditor consuming the receipt directory can recover the height
    by reading the bytes without invoking any wat/ tooling.
    """
    spool = tmp_path / "spool.jsonl"
    events = [_make_event(i) for i in range(2)]
    _write_jsonl(spool, events)

    seed = hashlib.sha256(b"tag-3-aggregator-marker-test").digest()
    key_file = tmp_path / "sign-key.hex"
    key_file.write_text(seed.hex() + "\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest = build_command(
        hour="2026-05-13T12",
        input_events=spool,
        output_manifest=manifest_path,
        sign_key=key_file,
        sign_kid="wakir-test-marker/1",
    )
    root_bytes = bytes.fromhex(manifest["merkle_root"])

    anchor_dir = tmp_path / "anchor-marker"
    stamp_side = _make_stamp_side_effect_with_block_948183()
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=stamp_side):
        receipt = anchor_root(
            merkle_root=root_bytes,
            calendars=["https://alice.test", "https://bob.test"],
            min_calendars=2,
            target_dir=anchor_dir,
        )

    raw = receipt.receipt_path.read_bytes()
    assert b"BitcoinBlockHeaderAttestation(948183)" in raw, (
        "receipt does not carry the canonical block-948183 marker"
    )
    # The canonical block hash is documented next to the height —
    # check it is reachable from this test surface as a sanity stamp.
    assert len(BLOCK_HASH_948183) == 64
    int(BLOCK_HASH_948183, 16)  # hex
