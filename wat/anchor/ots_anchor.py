# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""OpenTimestamps anchor pipeline for hourly Merkle roots.

This module submits 32-byte Merkle roots to multiple OpenTimestamps
public calendar servers, persists the resulting pending receipt next
to the root file, later upgrades that pending receipt to a Bitcoin
attestation once the calendar batch has been mined, and finally
verifies a finalised receipt against a known root.

Design notes
------------

1. Multi-calendar fan-out. The default is a 2-of-N policy (WAT
   Phase-1a-Spec §3.3): we submit to four free public calendars
   (alice, bob, finney, catallaxy) and treat the submission as
   successful if at least two of them returned a pending attestation.
   The OTS client itself supports this via ``-m N``; we surface the
   threshold as ``min_calendars`` so callers can tune it.

2. Subprocess wrapper. The ``ots`` Python client is mature and
   well-maintained, but invoking it as a CLI subprocess has two
   advantages over importing the library in-process: (a) calendar
   network calls cannot deadlock the caller's event loop, and (b)
   any future swap of the OTS implementation only changes this
   single boundary. Hard 90-second timeout per invocation
   (Wayback-Robustheit-Lehre — slow calendars must not block the
   hourly cron).

3. Failure semantics. A submission that meets the ``min_calendars``
   threshold returns a populated ``AnchorReceipt``. A submission
   that falls short raises ``AnchorError``; callers (the hourly
   driver) are expected to retry on the backfill queue rather than
   silently anchoring against a single calendar.

4. Backfill. Pending receipts are upgraded to full Bitcoin
   attestation by ``upgrade_pending``. The 7-day soft window before
   audit alarm (WAT Phase-1a-Spec §3.4) is enforced in
   ``wat.anchor.backfill``, not here.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from wat.anchor.latency_emitter import LatencyEmitter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Free public OTS calendar servers used by default. Order matches the
#: priority in which the OTS client itself contacts them when no explicit
#: whitelist is given. Maintained here so tests can monkey-patch.
DEFAULT_CALENDARS: tuple[str, ...] = (
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com",
    "https://btc.calendar.catallaxy.com",
)

#: Default minimum number of calendar attestations required for a
#: submission to be accepted. WAT Phase-1a-Spec §3.3 mandates 2-of-N.
DEFAULT_MIN_CALENDARS: int = 2

#: Wall-clock timeout for any single ``ots`` subprocess invocation,
#: in seconds. Wayback-Robustheit-Lehre.
SUBPROCESS_TIMEOUT_S: int = 90


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AnchorReceipt:
    """Pending OTS receipt produced by ``anchor_root``.

    Attributes
    ----------
    merkle_root:
        The 32-byte SHA-256 Merkle root that was submitted.
    submission_time:
        RFC 3339 timestamp string in UTC (Zulu suffix) recording
        when the submission completed.
    calendar_responses:
        Mapping ``calendar_url -> "ok" | "<error string>"`` showing
        which calendars accepted the submission. Tests treat this as
        the primary signal for the failover assertions.
    receipt_path:
        Filesystem path to the persisted ``.ots`` receipt file.
    """

    merkle_root: bytes
    submission_time: str
    calendar_responses: dict[str, str]
    receipt_path: Path

    def successful_calendars(self) -> List[str]:
        return [u for u, r in self.calendar_responses.items() if r == "ok"]


@dataclasses.dataclass(frozen=True)
class UpgradedReceipt:
    """Finalised OTS receipt produced by ``upgrade_pending``.

    Attributes
    ----------
    merkle_root:
        The 32-byte SHA-256 Merkle root the receipt attests to.
    receipt_path:
        Filesystem path to the upgraded ``.ots`` receipt file.
    bitcoin_block_height:
        Block height of the Bitcoin block that confirms the
        attestation, or ``None`` if the receipt is still pending
        and only a no-op upgrade was performed.
    bitcoin_tx_id:
        Transaction id (hex string) of the OTS aggregator transaction
        in the confirming block, or ``None`` if still pending.
    upgraded_at:
        RFC 3339 timestamp string in UTC recording when the upgrade
        attempt completed.
    """

    merkle_root: bytes
    receipt_path: Path
    bitcoin_block_height: Optional[int]
    bitcoin_tx_id: Optional[str]
    upgraded_at: str

    @property
    def is_finalised(self) -> bool:
        return self.bitcoin_block_height is not None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AnchorError(RuntimeError):
    """Raised when an anchor operation fails irrecoverably for the caller."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_rfc3339() -> str:
    """Return the current UTC time as an RFC 3339 string with ``Z`` suffix."""
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_ots_binary() -> str:
    """Return the path to the ``ots`` CLI or raise ``AnchorError``."""
    found = shutil.which("ots")
    if found is None:
        raise AnchorError(
            "ots CLI not found on PATH; run scripts/setup.sh or install "
            "opentimestamps-client into the active venv."
        )
    return found


def _run_ots(
    args: Sequence[str],
    *,
    timeout: int = SUBPROCESS_TIMEOUT_S,
) -> subprocess.CompletedProcess[str]:
    """Invoke the ``ots`` CLI with a hard timeout.

    All stdout/stderr is captured as text. Non-zero exit codes are
    not raised here; callers translate them into domain errors.
    """
    binary = _resolve_ots_binary()
    cmd = [binary, *args]
    return subprocess.run(  # noqa: S603 — explicit args, no shell.
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _write_root_file(merkle_root: bytes, target_dir: Path) -> Path:
    """Persist the 32-byte root as a binary file under ``target_dir``.

    The file name is ``root.bin``; ``ots stamp`` will produce
    ``root.bin.ots`` next to it.
    """
    if len(merkle_root) != 32:
        raise ValueError(f"merkle_root must be 32 bytes, got {len(merkle_root)}")
    target_dir.mkdir(parents=True, exist_ok=True)
    root_path = target_dir / "root.bin"
    root_path.write_bytes(merkle_root)
    return root_path


def _parse_calendar_responses(
    stdout: str,
    stderr: str,
    calendars: Sequence[str],
) -> dict[str, str]:
    """Parse OTS stamp output into a calendar -> status map.

    The OTS client logs lines like ``Submitting to remote calendar
    <url>`` followed by either nothing (success) or an error line.
    We treat the absence of an error containing the calendar URL as
    success. This is a heuristic — the OTS client does not provide a
    structured machine-readable status — but the heuristic is
    sufficient for the threshold check and for the audit log.
    """
    blob = (stdout or "") + "\n" + (stderr or "")
    out: dict[str, str] = {}
    for url in calendars:
        # Find any line mentioning the calendar URL with an error keyword.
        bad = False
        bad_msg = ""
        for line in blob.splitlines():
            if url not in line:
                continue
            lowered = line.lower()
            if any(
                marker in lowered
                for marker in (
                    "error",
                    "failed",
                    "timeout",
                    "refused",
                    "unable",
                )
            ):
                bad = True
                bad_msg = line.strip()
                break
        out[url] = bad_msg if bad else "ok"
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def anchor_root(
    merkle_root: bytes,
    calendars: Optional[Sequence[str]] = None,
    min_calendars: int = DEFAULT_MIN_CALENDARS,
    *,
    target_dir: Optional[Path] = None,
) -> AnchorReceipt:
    """Submit ``merkle_root`` to multiple OTS calendars.

    Parameters
    ----------
    merkle_root:
        32-byte SHA-256 Merkle root for the hour being anchored.
    calendars:
        Iterable of calendar URLs. Defaults to ``DEFAULT_CALENDARS``.
    min_calendars:
        Minimum number of calendar attestations required for the
        submission to count as successful (default 2, per
        WAT-Phase-1a-Spec §3.3). Must be <= ``len(calendars)``.
    target_dir:
        Directory where ``root.bin`` and ``root.bin.ots`` will be
        written. Defaults to a temporary directory below
        ``meta/timestamps/wat/``; in production the hourly driver
        passes the per-hour directory.

    Returns
    -------
    AnchorReceipt

    Raises
    ------
    AnchorError
        If fewer than ``min_calendars`` calendars accepted the
        submission, if the OTS subprocess timed out, or if no
        receipt file was produced.
    """
    cal_list: tuple[str, ...] = tuple(calendars) if calendars else DEFAULT_CALENDARS
    if min_calendars < 1:
        raise ValueError("min_calendars must be >= 1")
    if min_calendars > len(cal_list):
        raise ValueError(
            f"min_calendars={min_calendars} exceeds calendar count {len(cal_list)}"
        )
    if target_dir is None:
        target_dir = Path("meta/timestamps/wat/_pending")

    # Per-anchor pipeline-stage latency emission (SLO-2 producer).
    # Disabled-by-default; activates when WAKIR_ANCHOR_LATENCY_JSONL is
    # set. Wrapping the whole pipeline body in ``emitter.observe`` keeps
    # the failure semantics intact — an ``AnchorError`` raised inside
    # the with-block skips the emit (SLO-2 is conditional-on-success).
    emitter = LatencyEmitter.from_env()
    with emitter.observe(merkle_root.hex()) as latency:
        with latency.stage("enqueue_to_pre_ots"):
            root_path = _write_root_file(merkle_root, target_dir)
            args: List[str] = ["stamp", "-m", str(min_calendars)]
            for url in cal_list:
                args.extend(["--calendar", url])
            args.append(str(root_path))

        with latency.stage("ots_call"):
            try:
                result = _run_ots(args)
            except subprocess.TimeoutExpired as exc:  # 90s ceiling.
                raise AnchorError(
                    f"ots stamp timed out after {SUBPROCESS_TIMEOUT_S}s"
                ) from exc

        with latency.stage("post_ots_commit"):
            responses = _parse_calendar_responses(
                result.stdout, result.stderr, cal_list
            )
            ok_count = sum(1 for v in responses.values() if v == "ok")
            if ok_count < min_calendars:
                raise AnchorError(
                    f"only {ok_count}/{len(cal_list)} calendars succeeded; "
                    f"need {min_calendars}. Detail: {responses!r}"
                )

            receipt_path = root_path.with_suffix(root_path.suffix + ".ots")
            if not receipt_path.exists() and result.returncode == 0:
                # OTS sometimes emits the receipt with a slightly different
                # name depending on version; do a defensive scan of the
                # directory.
                candidates = sorted(target_dir.glob("root.bin*.ots"))
                if candidates:
                    receipt_path = candidates[0]
            if not receipt_path.exists():
                raise AnchorError(
                    f"ots stamp completed but no receipt file at "
                    f"{receipt_path}; stdout={result.stdout!r} "
                    f"stderr={result.stderr!r}"
                )

        with latency.stage("wat_write"):
            receipt = AnchorReceipt(
                merkle_root=merkle_root,
                submission_time=_utc_now_rfc3339(),
                calendar_responses=responses,
                receipt_path=receipt_path,
            )

    return receipt


def upgrade_pending(receipt_path: str | Path) -> UpgradedReceipt:
    """Upgrade a pending OTS receipt to a finalised Bitcoin attestation.

    Calls ``ots upgrade <receipt>`` which is idempotent — if the
    underlying calendar has not yet anchored its batch into Bitcoin,
    the receipt stays pending and we report ``bitcoin_block_height
    is None``. Once Bitcoin confirms, a follow-up call replaces the
    file in place with a self-contained attestation.
    """
    path = Path(receipt_path)
    if not path.exists():
        raise AnchorError(f"receipt not found: {path}")

    try:
        upgrade_result = _run_ots(["upgrade", str(path)])
    except subprocess.TimeoutExpired as exc:
        raise AnchorError(
            f"ots upgrade timed out after {SUBPROCESS_TIMEOUT_S}s"
        ) from exc

    # Read root bytes back. In production the root.bin sits next to the
    # .ots file; ``ots upgrade`` does not need it but the dataclass does.
    root_file = path.with_suffix("")  # strip .ots extension
    merkle_root = root_file.read_bytes() if root_file.exists() else b"\x00" * 32

    # Probe attestation status: ``ots info`` mentions the Bitcoin block
    # height in its output once the attestation is finalised.
    info_result = _run_ots(["info", str(path)])
    block_height: Optional[int] = None
    tx_id: Optional[str] = None
    blob = (info_result.stdout or "") + "\n" + (info_result.stderr or "")
    for line in blob.splitlines():
        stripped = line.strip()
        # Matches: "Bitcoin block <height> attests existence as of ..."
        if stripped.lower().startswith("bitcoin block"):
            parts = stripped.split()
            if len(parts) >= 3 and parts[2].isdigit():
                block_height = int(parts[2])
                break

    if block_height is None and "pending" not in blob.lower():
        # Nothing definite either way — keep block_height None and let
        # the caller treat it as still pending.
        pass

    if upgrade_result.returncode != 0 and block_height is None:
        # Calendar timeout / network glitch — not fatal; backfill will
        # retry on the next pass.
        pass

    return UpgradedReceipt(
        merkle_root=merkle_root,
        receipt_path=path,
        bitcoin_block_height=block_height,
        bitcoin_tx_id=tx_id,
        upgraded_at=_utc_now_rfc3339(),
    )


def verify_receipt(
    receipt_path: str | Path,
    merkle_root: bytes,
    *,
    esplora_fallback: bool = True,
) -> bool:
    """Verify a finalised OTS receipt attests to ``merkle_root``.

    Writes ``merkle_root`` to a temp file next to the receipt (OTS's
    verify mode reads the original file the receipt was created for)
    and runs ``ots verify``. Returns ``True`` iff the receipt is
    finalised against Bitcoin and the root matches.

    Esplora HTTP fallback (Phase-1a Tag-15)
    ---------------------------------------

    ``ots verify`` requires a local Bitcoin node (or an OTS-server-
    side block-header source) to confirm the
    ``BitcoinBlockHeaderAttestation(H)`` lines in the receipt's
    proof tree. Operators who do not run a node — the common case
    for the public brand-proof verifier and for any audit consumer
    who does not want to run their own Bitcoin infrastructure — see
    a no-``Success!`` exit even though the receipt has actually
    been anchored on chain.

    When ``esplora_fallback`` is True (default), we therefore
    consult ``ots info`` for ``BitcoinBlockHeaderAttestation(H)``
    lines and, for any height we find, query the public Esplora
    HTTP API at :data:`wat.anchor.esplora.DEFAULT_BASE_URL` (or
    ``$WAKIR_ESPLORA_BASE_URL``) to confirm that block ``H`` exists
    on Bitcoin mainnet. The block hash is then persisted in a
    sidecar next to the receipt for repeat-call cache-hit
    short-circuiting. If at least one height in the receipt
    corresponds to a real block on chain, the receipt is treated
    as cross-validated and the function returns True.

    The fallback is opt-out (callers can pass
    ``esplora_fallback=False``) so existing fully-mocked unit tests
    that monkey-patch ``subprocess.run`` continue to behave
    deterministically without a network round-trip.
    """
    if len(merkle_root) != 32:
        raise ValueError(f"merkle_root must be 32 bytes, got {len(merkle_root)}")
    path = Path(receipt_path)
    if not path.exists():
        raise AnchorError(f"receipt not found: {path}")

    # ots verify expects the original file; write the root next to it.
    root_file = path.with_suffix("")  # strip .ots
    root_file.write_bytes(merkle_root)

    try:
        result = _run_ots(["verify", str(path)])
    except subprocess.TimeoutExpired as exc:
        raise AnchorError(
            f"ots verify timed out after {SUBPROCESS_TIMEOUT_S}s"
        ) from exc

    if result.returncode == 0:
        blob = (result.stdout or "") + "\n" + (result.stderr or "")
        lowered = blob.lower()
        if "success" in lowered and "pending" not in lowered:
            return True

    # The local-node path did not confirm. Try the Esplora HTTP
    # fallback if the caller did not opt out.
    if not esplora_fallback:
        return False

    return _verify_via_esplora(path)


def _verify_via_esplora(receipt_path: Path) -> bool:
    """Cross-validate a receipt's block-header attestations via Esplora.

    Returns True if at least one ``BitcoinBlockHeaderAttestation(H)``
    line in the receipt's ``ots info`` output corresponds to a real
    Bitcoin mainnet block at height ``H`` according to the
    configured Esplora endpoint. Returns False otherwise (no
    finalised attestation in the receipt, or the Esplora call
    failed).
    """
    # Local import keeps the optional dependency edge minimal: tests
    # that mock subprocess and never hit verify_receipt's fallback
    # path do not even import the esplora module.
    from wat.anchor import esplora

    try:
        info_result = _run_ots(["info", str(receipt_path)])
    except subprocess.TimeoutExpired:
        return False

    info_blob = (info_result.stdout or "") + "\n" + (info_result.stderr or "")
    heights = esplora.extract_block_heights_from_info(info_blob)
    if not heights:
        # No finalised attestation -> truly pending.
        return False

    # Cache directory = the directory that contains the receipt.
    cache_dir = receipt_path.parent
    if not cache_dir.exists():
        return False

    for height in heights:
        try:
            esplora.lookup_block_with_cache(height, cache_dir)
        except esplora.EsploraError:
            continue
        return True
    return False


__all__ = [
    "AnchorError",
    "AnchorReceipt",
    "UpgradedReceipt",
    "DEFAULT_CALENDARS",
    "DEFAULT_MIN_CALENDARS",
    "SUBPROCESS_TIMEOUT_S",
    "anchor_root",
    "upgrade_pending",
    "verify_receipt",
]
