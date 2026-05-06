# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Esplora HTTP client for Bitcoin block-header lookup.

This module exists to break the local-Bitcoin-node coupling in
``wat.anchor.ots_anchor.verify_receipt``. The OTS CLI's ``ots verify``
needs a Bitcoin block-header source to attest "this block actually
exists at the height claimed by the receipt's
``BitcoinBlockHeaderAttestation``"; without a node it returns no
"Success!" and our wrapper reads that as ``pending``. For an
auditability deliverable that is unhelpful — a finalised receipt
should verify against any honest Bitcoin observer, not only against
operators who happen to run their own node.

Esplora is the boring-tech fallback. It is a free, public,
Apache-2.0-licensed HTTP API whose flagship deployment lives at
``blockstream.info`` and whose protocol is also implemented at
``mempool.space``. Two endpoints are sufficient for our needs:

- ``GET /api/block-height/<H>`` — returns the canonical block hash
  at height ``H`` as a plain-text 64-char hex string.
- ``GET /api/block/<hash>`` — returns a JSON object with at least
  ``id``, ``height``, and ``merkle_root`` fields.

Cross-validation contract
-------------------------

This module does not re-implement OTS proof-tree walking. It runs the
narrow check specified by the Phase-1a Tag-15 brief: given a block
height ``H`` extracted from a finalised OTS receipt's
``BitcoinBlockHeaderAttestation`` line, confirm via Esplora that the
block exists at that height on Bitcoin mainnet, and return the block
hash for the caller to record. A future Phase-1b extension can also
recompute the OTS proof leaf and compare against the block's
``merkle_root`` for a full proof-tree validation; the current
contract is intentionally limited to "block exists at claimed
height" because that is what the Tag-15 spec asks for and because
the OTS proof-tree walk has its own ``pyopentimestamps`` library
surface we do not want to re-export.

Caching
-------

The module also writes a sidecar file under the receipt's hour
directory named ``bitcoin_block.txt`` recording the block height,
and a companion ``bitcoin_block_hash.txt`` recording the hash.
Re-validation of the same receipt after the cache files exist
short-circuits the HTTP call. This keeps repeat ``wakir-verify``
runs in the millisecond range and is polite against the public
Esplora deployment.

Endpoints, courtesy, fallback
-----------------------------

Default base URL: ``https://blockstream.info/api``. No formal rate
limit is published; we apply a 10-second per-call timeout and rely
on the sidecar cache for repeat lookups. For operators who prefer
mempool.space (same Esplora API surface), the
``WAKIR_ESPLORA_BASE_URL`` environment variable overrides the
default. A future Phase-1b extension can add a self-hosted
``esplora`` deployment as a third option without touching the
caller surface; the dependency surface here is intentionally
``urllib.request`` (stdlib only) to keep the offline brand-proof
verifier dependency-free.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default Esplora HTTP API base URL. Overridable per-environment via
#: ``WAKIR_ESPLORA_BASE_URL`` so operators can swap to mempool.space
#: or a self-hosted instance without code changes.
DEFAULT_BASE_URL: str = "https://blockstream.info/api"

#: Per-call HTTP timeout, in seconds. Esplora typically responds in
#: 150-300ms; ten seconds covers a slow link without blocking the
#: hourly verify driver indefinitely.
HTTP_TIMEOUT_S: float = 10.0

#: Sidecar filename for the cached Bitcoin block height. Mirrors the
#: name already used by the upgrade pipeline so a single audit walk
#: surfaces both sources of truth identically.
BLOCK_HEIGHT_CACHE_FILE: str = "bitcoin_block.txt"

#: Sidecar filename for the cached Bitcoin block hash. Distinct from
#: the height file so that operators reading the archive directly
#: can correlate height->hash without re-hitting the network.
BLOCK_HASH_CACHE_FILE: str = "bitcoin_block_hash.txt"

#: Bitcoin block hashes are 32 bytes -> 64 lowercase hex characters
#: with leading zeroes. The compiled regex stays at module scope so
#: hot-path validation does not pay the compile cost per call.
_BLOCK_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

#: User-Agent header. Identifies Wakir Labs as the caller for the
#: Esplora operator without leaking the receipt being verified.
_USER_AGENT: str = "wakir-runtime/0.0.1 (+https://wakir.dev)"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EsploraError(RuntimeError):
    """Raised for any Esplora-side failure: HTTP error, malformed body."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BlockLookupResult:
    """Outcome of an Esplora block-header lookup.

    Attributes
    ----------
    height:
        The block height that was queried (mirrored back so callers
        do not have to retain it separately).
    block_hash:
        Lowercase 64-char hex string. The canonical block hash at the
        queried height on Bitcoin mainnet.
    cached:
        ``True`` when the result was served from the on-disk sidecar
        cache, ``False`` when it required an HTTP round-trip. Tests
        and the Tag-15 brand-demo memo both consume this signal to
        report cache-hit rate.
    """

    height: int
    block_hash: str
    cached: bool


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _resolve_base_url() -> str:
    """Return the Esplora base URL for the current environment."""
    env = os.environ.get("WAKIR_ESPLORA_BASE_URL", "").strip()
    return env or DEFAULT_BASE_URL


def _http_get_text(url: str, *, timeout: float = HTTP_TIMEOUT_S) -> str:
    """Issue a ``GET`` and return the response body as text.

    A thin wrapper around :func:`urllib.request.urlopen` whose only
    job is to attach the ``User-Agent`` header, normalise both
    network and HTTP errors into :class:`EsploraError`, and decode
    the body as UTF-8.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status = getattr(resp, "status", 200)
            if status != 200:
                raise EsploraError(
                    f"esplora GET {url} returned HTTP {status}"
                )
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise EsploraError(
            f"esplora GET {url} returned HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise EsploraError(
            f"esplora GET {url} failed at network layer: {exc.reason}"
        ) from exc
    except TimeoutError as exc:  # urllib.request raises TimeoutError on socket timeout
        raise EsploraError(
            f"esplora GET {url} timed out after {timeout}s"
        ) from exc
    return body.decode("utf-8").strip()


# ---------------------------------------------------------------------------
# Public API: block-by-height
# ---------------------------------------------------------------------------


def fetch_block_hash_at_height(
    height: int,
    *,
    base_url: Optional[str] = None,
    timeout: float = HTTP_TIMEOUT_S,
) -> str:
    """Fetch the canonical Bitcoin block hash at ``height`` from Esplora.

    Parameters
    ----------
    height:
        Non-negative block height. The genesis block is height 0.
    base_url:
        Override the Esplora base URL. ``None`` (the default) uses
        :func:`_resolve_base_url`.
    timeout:
        Per-call HTTP timeout, in seconds.

    Returns
    -------
    str
        Lowercase 64-char hex string; the canonical block hash at
        the queried height.

    Raises
    ------
    EsploraError
        If the HTTP call fails, the response body is not a valid
        block-hash hex string, or the height is negative.
    """
    if height < 0:
        raise EsploraError(f"block height must be non-negative, got {height}")

    base = base_url if base_url is not None else _resolve_base_url()
    url = f"{base.rstrip('/')}/block-height/{height}"
    body = _http_get_text(url, timeout=timeout)
    block_hash = body.strip().lower()
    if not _BLOCK_HASH_RE.fullmatch(block_hash):
        raise EsploraError(
            f"esplora returned malformed block hash for height {height}: "
            f"{body!r}"
        )
    return block_hash


# ---------------------------------------------------------------------------
# Public API: cached block lookup with sidecar persistence
# ---------------------------------------------------------------------------


def lookup_block_with_cache(
    height: int,
    cache_dir: Path,
    *,
    base_url: Optional[str] = None,
    timeout: float = HTTP_TIMEOUT_S,
) -> BlockLookupResult:
    """Cached variant of :func:`fetch_block_hash_at_height`.

    On first call for a given hour archive directory the function
    issues an HTTP GET to Esplora and persists both the height and
    the hash next to the receipt as plain-text sidecar files. On
    subsequent calls — by either ``wakir-verify`` re-runs or other
    tooling reading the same archive — the sidecar files short-circuit
    the network call.

    Cache invalidation strategy: a sidecar with a height that does
    not match the requested height is treated as stale and replaced.
    A sidecar whose hash format is corrupt is also replaced. Tests
    cover both.

    Parameters
    ----------
    height:
        Block height to look up.
    cache_dir:
        Directory in which to read/write the sidecar files. Must
        already exist; the caller (the verify CLI) owns the
        archive-tree layout. The function does not create the
        directory because doing so silently could hide
        archive-misconfiguration bugs.
    base_url, timeout:
        Forwarded to :func:`fetch_block_hash_at_height` on cache miss.

    Returns
    -------
    BlockLookupResult
    """
    if not cache_dir.exists() or not cache_dir.is_dir():
        raise EsploraError(
            f"cache directory does not exist: {cache_dir}"
        )

    height_file = cache_dir / BLOCK_HEIGHT_CACHE_FILE
    hash_file = cache_dir / BLOCK_HASH_CACHE_FILE

    cached_hash = _read_cached_hash(height_file, hash_file, height)
    if cached_hash is not None:
        return BlockLookupResult(
            height=height,
            block_hash=cached_hash,
            cached=True,
        )

    block_hash = fetch_block_hash_at_height(
        height, base_url=base_url, timeout=timeout
    )

    # Persist the sidecar atomically: write through a tmp file then
    # rename. ``urllib`` already validated the body shape so we can
    # write without re-checking, but the rename keeps the cache
    # coherent if a concurrent reader touches the file mid-write.
    _atomic_write(height_file, f"{height}\n")
    _atomic_write(hash_file, f"{block_hash}\n")

    return BlockLookupResult(
        height=height,
        block_hash=block_hash,
        cached=False,
    )


def _read_cached_hash(
    height_file: Path,
    hash_file: Path,
    expected_height: int,
) -> Optional[str]:
    """Read the sidecar files and return the cached hash or ``None``.

    Returns ``None`` (cache miss / stale) when:

    - either sidecar file is absent,
    - the height-file contents are not parseable as int,
    - the cached height does not match ``expected_height``,
    - the cached hash does not look like a 64-hex-char string.
    """
    if not height_file.exists() or not hash_file.exists():
        return None
    try:
        cached_height = int(height_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if cached_height != expected_height:
        return None
    try:
        cached_hash = hash_file.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    if not _BLOCK_HASH_RE.fullmatch(cached_hash):
        return None
    return cached_hash


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via tmp-file + rename for crash safety."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Public API: receipt cross-validation helper
# ---------------------------------------------------------------------------


#: Regex for OTS info output lines that announce a finalised block
#: attestation. Matches both the historic
#: ``Bitcoin block <H> attests existence as of ...`` form emitted by
#: ``ots info`` on a finalised receipt and the
#: ``verify BitcoinBlockHeaderAttestation(<H>)`` form found inside
#: the proof tree of a finalised receipt's full info dump.
_BLOCK_HEIGHT_LINE_RE = re.compile(
    r"BitcoinBlockHeaderAttestation\((\d+)\)"
    r"|^Bitcoin\s+block\s+(\d+)\b",
    re.IGNORECASE | re.MULTILINE,
)


def extract_block_heights_from_info(info_blob: str) -> list[int]:
    """Extract Bitcoin block heights from an ``ots info`` output blob.

    A finalised OTS receipt mentions one ``BitcoinBlockHeaderAttestation(H)``
    line per calendar branch that has been anchored. A pending receipt
    has none. Returns the heights in first-seen order, deduplicated.
    """
    seen: set[int] = set()
    out: list[int] = []
    for match in _BLOCK_HEIGHT_LINE_RE.finditer(info_blob or ""):
        # The two alternatives produce captures in groups 1 and 2.
        height_str = match.group(1) or match.group(2)
        if height_str is None:
            continue
        try:
            height = int(height_str)
        except ValueError:
            continue
        if height in seen:
            continue
        seen.add(height)
        out.append(height)
    return out


__all__ = [
    "BLOCK_HASH_CACHE_FILE",
    "BLOCK_HEIGHT_CACHE_FILE",
    "BlockLookupResult",
    "DEFAULT_BASE_URL",
    "EsploraError",
    "HTTP_TIMEOUT_S",
    "extract_block_heights_from_info",
    "fetch_block_hash_at_height",
    "lookup_block_with_cache",
]
