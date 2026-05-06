# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Esplora HTTP fallback.

The Esplora client and ``verify_receipt``'s Tag-15 fallback path are
exercised entirely in-process: ``urllib.request.urlopen`` is patched
to a canned-response stub so no network call leaves the test runner.
This keeps CI deterministic and polite against blockstream.info.

Test inventory (Tag-15 spec §Item 1):

- (a) Cache-Miss + HTTP-200 + match — happy path, sidecar files
  created.
- (b) Cache-Hit — second call uses the sidecar files, no HTTP.
- (c) Block-hash-mismatch / negative path — Esplora returns a
  body that does not parse as a valid block hash; the call must
  raise EsploraError, and the verify_receipt fallback must report
  False.

Plus enough surrounding tests to give the fallback a fighting chance
in production: extract_block_heights_from_info parsing, sidecar
staleness invalidation, base-URL override, verify_receipt
integration with both branches of the local-node path.
"""

from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from pathlib import Path
from typing import Optional
from unittest import mock

import pytest

from wat.anchor import esplora, ots_anchor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# A real, recent main-net block hash (height 948183). Pinned because
# the OTS receipt currently in .runtime/ for TV-1 cites this same
# height; using the real hash keeps the test value-checked.
TV1_HEIGHT = 948183
TV1_HASH = "00000000000000000000ec730435b01d9bdd9de0a10f1a8c4a33ea27e52b2110"


class FakeResponse(io.BytesIO):
    """Minimal stand-in for :class:`http.client.HTTPResponse`.

    Implements just the surface ``urllib.request.urlopen`` is used
    for in :func:`wat.anchor.esplora._http_get_text`: a context
    manager with a ``status`` attribute and a ``read()`` method.
    """

    def __init__(self, body: bytes, *, status: int = 200) -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """An isolated directory the Esplora client may write into."""
    d = tmp_path / "hour-archive"
    d.mkdir()
    return d


def _patch_urlopen(body: bytes, *, status: int = 200):
    """Return a ``mock.patch`` against esplora's urlopen."""
    return mock.patch.object(
        esplora.urllib.request,
        "urlopen",
        return_value=FakeResponse(body, status=status),
    )


# ---------------------------------------------------------------------------
# extract_block_heights_from_info — parser tests
# ---------------------------------------------------------------------------


def test_extract_heights_from_finalised_info_blob() -> None:
    """A finalised receipt info blob yields the attested height(s)."""
    blob = (
        "    verify PendingAttestation('https://alice.btc...')\n"
        "    verify BitcoinBlockHeaderAttestation(948183)\n"
        "    verify PendingAttestation('https://bob.btc...')\n"
    )
    assert esplora.extract_block_heights_from_info(blob) == [948183]


def test_extract_heights_from_pending_info_blob() -> None:
    """A pending-only receipt info blob yields no heights."""
    blob = (
        "    verify PendingAttestation('https://alice.btc...')\n"
        "    verify PendingAttestation('https://bob.btc...')\n"
    )
    assert esplora.extract_block_heights_from_info(blob) == []


def test_extract_heights_dedupes_and_preserves_order() -> None:
    """Multiple branches that finalised on the same block dedupe."""
    blob = (
        "BitcoinBlockHeaderAttestation(948183)\n"
        "BitcoinBlockHeaderAttestation(948200)\n"
        "BitcoinBlockHeaderAttestation(948183)\n"
    )
    assert esplora.extract_block_heights_from_info(blob) == [948183, 948200]


def test_extract_heights_handles_empty_blob() -> None:
    assert esplora.extract_block_heights_from_info("") == []
    assert esplora.extract_block_heights_from_info(None or "") == []  # noqa: PT017


# ---------------------------------------------------------------------------
# fetch_block_hash_at_height — happy and error paths
# ---------------------------------------------------------------------------


def test_fetch_block_hash_returns_hex_on_200() -> None:
    body = (TV1_HASH + "\n").encode()
    with _patch_urlopen(body):
        got = esplora.fetch_block_hash_at_height(TV1_HEIGHT)
    assert got == TV1_HASH


def test_fetch_block_hash_uppercase_response_lowered() -> None:
    body = (TV1_HASH.upper() + "\n").encode()
    with _patch_urlopen(body):
        got = esplora.fetch_block_hash_at_height(TV1_HEIGHT)
    assert got == TV1_HASH


def test_fetch_block_hash_rejects_negative_height() -> None:
    with pytest.raises(esplora.EsploraError, match="non-negative"):
        esplora.fetch_block_hash_at_height(-1)


def test_fetch_block_hash_rejects_malformed_body() -> None:
    """Esplora returning anything that is not a 64-hex-char string fails fast."""
    with _patch_urlopen(b"not a hash\n"):
        with pytest.raises(esplora.EsploraError, match="malformed"):
            esplora.fetch_block_hash_at_height(TV1_HEIGHT)


def test_fetch_block_hash_propagates_http_error() -> None:
    """A 404 from Esplora surfaces as EsploraError, not HTTPError."""
    err = urllib.error.HTTPError(
        url="https://blockstream.info/api/block-height/9999999999",
        code=404,
        msg="Not Found",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )
    with mock.patch.object(esplora.urllib.request, "urlopen", side_effect=err):
        with pytest.raises(esplora.EsploraError, match="HTTP 404"):
            esplora.fetch_block_hash_at_height(9999999999)


def test_fetch_block_hash_uses_env_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """``WAKIR_ESPLORA_BASE_URL`` overrides the default endpoint."""
    monkeypatch.setenv("WAKIR_ESPLORA_BASE_URL", "https://mempool.space/api")
    body = (TV1_HASH + "\n").encode()
    with mock.patch.object(
        esplora.urllib.request,
        "urlopen",
        return_value=FakeResponse(body),
    ) as patched:
        esplora.fetch_block_hash_at_height(TV1_HEIGHT)
    called_url = patched.call_args.args[0].full_url
    assert called_url == f"https://mempool.space/api/block-height/{TV1_HEIGHT}"


# ---------------------------------------------------------------------------
# lookup_block_with_cache — Item-1 (a) cache-miss
# ---------------------------------------------------------------------------


def test_lookup_block_with_cache_miss_fetches_and_persists(
    cache_dir: Path,
) -> None:
    """Item-1 (a): cache miss + HTTP 200 + sidecar files written."""
    body = (TV1_HASH + "\n").encode()
    with _patch_urlopen(body) as patched:
        result = esplora.lookup_block_with_cache(TV1_HEIGHT, cache_dir)
    assert result.height == TV1_HEIGHT
    assert result.block_hash == TV1_HASH
    assert result.cached is False

    height_file = cache_dir / esplora.BLOCK_HEIGHT_CACHE_FILE
    hash_file = cache_dir / esplora.BLOCK_HASH_CACHE_FILE
    assert height_file.exists() and hash_file.exists()
    assert int(height_file.read_text().strip()) == TV1_HEIGHT
    assert hash_file.read_text().strip() == TV1_HASH
    assert patched.call_count == 1


# ---------------------------------------------------------------------------
# lookup_block_with_cache — Item-1 (b) cache-hit
# ---------------------------------------------------------------------------


def test_lookup_block_with_cache_hit_skips_http(cache_dir: Path) -> None:
    """Item-1 (b): a populated sidecar makes the next call avoid HTTP."""
    (cache_dir / esplora.BLOCK_HEIGHT_CACHE_FILE).write_text(
        f"{TV1_HEIGHT}\n", encoding="utf-8"
    )
    (cache_dir / esplora.BLOCK_HASH_CACHE_FILE).write_text(
        f"{TV1_HASH}\n", encoding="utf-8"
    )
    with mock.patch.object(esplora.urllib.request, "urlopen") as patched:
        result = esplora.lookup_block_with_cache(TV1_HEIGHT, cache_dir)
    assert result.cached is True
    assert result.block_hash == TV1_HASH
    assert patched.call_count == 0


def test_lookup_block_with_cache_stale_height_refetches(cache_dir: Path) -> None:
    """A sidecar with the wrong height is treated as cache-miss."""
    (cache_dir / esplora.BLOCK_HEIGHT_CACHE_FILE).write_text(
        "999\n", encoding="utf-8"
    )
    (cache_dir / esplora.BLOCK_HASH_CACHE_FILE).write_text(
        f"{TV1_HASH}\n", encoding="utf-8"
    )
    body = (TV1_HASH + "\n").encode()
    with _patch_urlopen(body) as patched:
        result = esplora.lookup_block_with_cache(TV1_HEIGHT, cache_dir)
    assert result.cached is False
    assert patched.call_count == 1
    assert int(
        (cache_dir / esplora.BLOCK_HEIGHT_CACHE_FILE).read_text().strip()
    ) == TV1_HEIGHT


def test_lookup_block_with_cache_corrupt_hash_refetches(cache_dir: Path) -> None:
    """A sidecar hash that is not 64 hex chars is treated as cache-miss."""
    (cache_dir / esplora.BLOCK_HEIGHT_CACHE_FILE).write_text(
        f"{TV1_HEIGHT}\n", encoding="utf-8"
    )
    (cache_dir / esplora.BLOCK_HASH_CACHE_FILE).write_text(
        "garbage\n", encoding="utf-8"
    )
    body = (TV1_HASH + "\n").encode()
    with _patch_urlopen(body):
        result = esplora.lookup_block_with_cache(TV1_HEIGHT, cache_dir)
    assert result.cached is False


def test_lookup_block_with_cache_missing_dir_raises(tmp_path: Path) -> None:
    """The function refuses to silently create the cache directory."""
    with pytest.raises(esplora.EsploraError, match="cache directory"):
        esplora.lookup_block_with_cache(TV1_HEIGHT, tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# verify_receipt fallback wiring — Item-1 happy path on a live receipt
# ---------------------------------------------------------------------------


@pytest.fixture
def receipt_archive_with_finalised(tmp_path: Path) -> Path:
    """Build an archive directory with a fake .ots receipt + root.bin.

    The receipt is a placeholder file; we mock both ``ots verify``
    (returns no Success!, simulating no-local-node) and ``ots info``
    (returns a finalised attestation line). The Esplora client is
    patched to return the canonical hash.
    """
    archive = tmp_path / "wat-archive" / "2026-05-06T14"
    archive.mkdir(parents=True)
    receipt = archive / "root.bin.ots"
    receipt.write_bytes(b"placeholder ots receipt body")
    return receipt


def _ots_completed_process(
    *, returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ots", "verify", "stub"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_verify_receipt_esplora_path_returns_true_on_block_match(
    receipt_archive_with_finalised: Path,
) -> None:
    """End-to-end Item-1 (a): no local node, Esplora confirms block exists."""
    receipt = receipt_archive_with_finalised
    merkle_root = b"\x00" * 32

    info_blob = (
        "    verify PendingAttestation('https://alice.btc...')\n"
        "    verify BitcoinBlockHeaderAttestation(948183)\n"
    )

    def fake_run_ots(args, *_, **__):  # noqa: ANN001
        if args[0] == "verify":
            # No "Success!" -> simulates missing local Bitcoin node.
            return _ots_completed_process(
                returncode=1,
                stderr="Verifying ... no block-header source.",
            )
        if args[0] == "info":
            return _ots_completed_process(returncode=0, stdout=info_blob)
        raise AssertionError(f"unexpected ots invocation: {args!r}")

    body = (TV1_HASH + "\n").encode()
    with mock.patch.object(ots_anchor, "_run_ots", side_effect=fake_run_ots):
        with _patch_urlopen(body):
            ok = ots_anchor.verify_receipt(receipt, merkle_root)
    assert ok is True

    # And the sidecar was persisted next to the receipt.
    cache_dir = receipt.parent
    assert (cache_dir / esplora.BLOCK_HASH_CACHE_FILE).exists()
    assert (
        cache_dir / esplora.BLOCK_HASH_CACHE_FILE
    ).read_text(encoding="utf-8").strip() == TV1_HASH


def test_verify_receipt_esplora_path_short_circuits_on_local_success(
    receipt_archive_with_finalised: Path,
) -> None:
    """When ``ots verify`` itself returns Success!, no Esplora call happens."""
    receipt = receipt_archive_with_finalised
    merkle_root = b"\x00" * 32

    def fake_run_ots(args, *_, **__):  # noqa: ANN001
        return _ots_completed_process(
            returncode=0,
            stdout="Success!\nBitcoin block 948183 attests existence",
        )

    with mock.patch.object(ots_anchor, "_run_ots", side_effect=fake_run_ots):
        with mock.patch.object(esplora.urllib.request, "urlopen") as urlopen:
            ok = ots_anchor.verify_receipt(receipt, merkle_root)
    assert ok is True
    assert urlopen.call_count == 0


def test_verify_receipt_esplora_disabled_falls_through_to_false(
    receipt_archive_with_finalised: Path,
) -> None:
    """``esplora_fallback=False`` reverts to legacy behaviour."""
    receipt = receipt_archive_with_finalised
    merkle_root = b"\x00" * 32

    def fake_run_ots(args, *_, **__):  # noqa: ANN001
        return _ots_completed_process(
            returncode=1, stderr="no Success! line"
        )

    with mock.patch.object(ots_anchor, "_run_ots", side_effect=fake_run_ots):
        ok = ots_anchor.verify_receipt(
            receipt, merkle_root, esplora_fallback=False
        )
    assert ok is False


def test_verify_receipt_esplora_returns_false_on_no_finalised_attestation(
    receipt_archive_with_finalised: Path,
) -> None:
    """Pure-pending receipt: Esplora fallback finds no heights, returns False."""
    receipt = receipt_archive_with_finalised
    merkle_root = b"\x00" * 32

    info_blob = (
        "    verify PendingAttestation('https://alice.btc...')\n"
        "    verify PendingAttestation('https://bob.btc...')\n"
    )

    def fake_run_ots(args, *_, **__):  # noqa: ANN001
        if args[0] == "verify":
            return _ots_completed_process(returncode=1, stderr="pending")
        if args[0] == "info":
            return _ots_completed_process(returncode=0, stdout=info_blob)
        raise AssertionError(f"unexpected ots invocation: {args!r}")

    with mock.patch.object(ots_anchor, "_run_ots", side_effect=fake_run_ots):
        with mock.patch.object(esplora.urllib.request, "urlopen") as urlopen:
            ok = ots_anchor.verify_receipt(receipt, merkle_root)
    assert ok is False
    # Esplora itself should never have been called: no heights to check.
    assert urlopen.call_count == 0


def test_verify_receipt_esplora_returns_false_on_malformed_response(
    receipt_archive_with_finalised: Path,
) -> None:
    """Item-1 (c) negative path: Esplora returns garbage -> False."""
    receipt = receipt_archive_with_finalised
    merkle_root = b"\x00" * 32

    info_blob = "    verify BitcoinBlockHeaderAttestation(948183)\n"

    def fake_run_ots(args, *_, **__):  # noqa: ANN001
        if args[0] == "verify":
            return _ots_completed_process(returncode=1, stderr="no node")
        if args[0] == "info":
            return _ots_completed_process(returncode=0, stdout=info_blob)
        raise AssertionError(f"unexpected ots invocation: {args!r}")

    with mock.patch.object(ots_anchor, "_run_ots", side_effect=fake_run_ots):
        with _patch_urlopen(b"definitely not a block hash\n"):
            ok = ots_anchor.verify_receipt(receipt, merkle_root)
    assert ok is False


def test_verify_receipt_esplora_returns_false_on_http_error(
    receipt_archive_with_finalised: Path,
) -> None:
    """Esplora HTTP error path: fall through to False instead of raising."""
    receipt = receipt_archive_with_finalised
    merkle_root = b"\x00" * 32

    info_blob = "    verify BitcoinBlockHeaderAttestation(948183)\n"

    def fake_run_ots(args, *_, **__):  # noqa: ANN001
        if args[0] == "verify":
            return _ots_completed_process(returncode=1, stderr="no node")
        if args[0] == "info":
            return _ots_completed_process(returncode=0, stdout=info_blob)
        raise AssertionError(f"unexpected ots invocation: {args!r}")

    err = urllib.error.URLError("DNS failure")
    with mock.patch.object(ots_anchor, "_run_ots", side_effect=fake_run_ots):
        with mock.patch.object(
            esplora.urllib.request, "urlopen", side_effect=err
        ):
            ok = ots_anchor.verify_receipt(receipt, merkle_root)
    assert ok is False


# ---------------------------------------------------------------------------
# verify_receipt fallback wiring — Item-1 (b) cache-hit path
# ---------------------------------------------------------------------------


def test_verify_receipt_esplora_uses_cache_on_repeat_call(
    receipt_archive_with_finalised: Path,
) -> None:
    """Item-1 (b) end-to-end: second verify avoids the HTTP round trip."""
    receipt = receipt_archive_with_finalised
    merkle_root = b"\x00" * 32

    info_blob = "    verify BitcoinBlockHeaderAttestation(948183)\n"

    def fake_run_ots(args, *_, **__):  # noqa: ANN001
        if args[0] == "verify":
            return _ots_completed_process(returncode=1, stderr="no node")
        if args[0] == "info":
            return _ots_completed_process(returncode=0, stdout=info_blob)
        raise AssertionError(f"unexpected ots invocation: {args!r}")

    body = (TV1_HASH + "\n").encode()

    with mock.patch.object(ots_anchor, "_run_ots", side_effect=fake_run_ots):
        with mock.patch.object(
            esplora.urllib.request,
            "urlopen",
            return_value=FakeResponse(body),
        ) as urlopen:
            ok1 = ots_anchor.verify_receipt(receipt, merkle_root)
            ok2 = ots_anchor.verify_receipt(receipt, merkle_root)

    assert ok1 is True and ok2 is True
    # First call hit Esplora; second served from cache.
    assert urlopen.call_count == 1
