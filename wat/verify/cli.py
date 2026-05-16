# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Server-side verification CLI for WAT hourly anchors.

Given an ``event_id`` and an archive directory of hourly WAT receipts
this CLI reconstructs the full chain of evidence:

1. locate the hour-slot manifest that contains the event,
2. recompute the leaf hash from the four B1-consensus fields
   (``event_id`` / ``time`` / ``payload_hash`` / ``capability_token_hash``),
3. rebuild a Bitcoin-pattern inclusion proof from the manifest's
   recorded leaf order,
4. verify the proof against the manifest's stored Merkle root,
5. shell out to :func:`wat.anchor.ots_anchor.verify_receipt` to
   confirm the OTS receipt for that hour attests to the same root
   on Bitcoin.

Status semantics
----------------

The CLI emits one of three outcomes for every event:

- ``verified`` — proof reconstructs to the manifest root *and* the
  OTS receipt is finalised on Bitcoin against that same root.
- ``pending`` — proof reconstructs cleanly but the OTS receipt has
  not yet been upgraded to a Bitcoin attestation. This is the
  expected state for hours less than ~6 hours old; it is also the
  state during the soft-window-but-not-yet-breached period
  (WAT-Phase-1a-Spec §3.4).
- ``failed`` — anything else: missing manifest, event not in
  manifest, proof mismatch, OTS verify failure.

Convenience layer
-----------------

This is the operator-facing convenience verifier (BSL 1.1) that
runs against the local manifest store. The public, offline
brand-proof verifier ships separately under ``wakir_verify/`` in
Apache-2.0 form (Phase 1a KW 23 deliverable per
WAT-Phase-1a-Spec §8.1).

Manifest format (Phase 1a)
--------------------------

Each hour slot lives in ``<archive>/<YYYY-MM-DDTHH>/`` and contains:

- ``manifest.json`` — JSON object with the keys
  ``hour_slot`` (string, ``YYYY-MM-DDTHH``),
  ``merkle_root`` (hex-encoded 32-byte root),
  ``event_count`` (int),
  ``events`` (list of objects with the four B1-consensus fields,
  in the same order they were hashed into the tree),
  ``submission_time`` (RFC 3339 string, optional),
  ``calendar_responses`` (mapping, optional).
- ``root.bin`` — the 32-byte raw Merkle root, written by
  :mod:`wat.anchor.ots_anchor` so that ``ots verify`` can read it
  back during OTS receipt verification.
- ``root.bin.ots`` — the OpenTimestamps receipt.

The manifest format is intentionally JSON-and-hex rather than a
binary container so that an auditor can ``less`` the file and
correlate events without any Wakir tooling. The format is part of
the Phase-1a brand-proof contract; breaking changes require a
manifest schema bump.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from wat.anchor.ots_anchor import AnchorError, verify_receipt
from wat.merkle.aggregator import (
    build_merkle_tree,
    compute_leaf_hash,
    merkle_proof,
    verify_merkle_proof,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Per-hour manifest filename, written by the aggregator. Single source
#: of truth for both the writer (`wat.merkle.aggregator`, day 5) and
#: this verifier — a typo here breaks audit verifiability silently.
MANIFEST_FILENAME = "manifest.json"

#: Per-hour root binary, written by the OTS anchor pipeline. Mirrors
#: ``ots stamp``'s expected naming so that ``ots verify`` finds the
#: original payload next to the receipt.
ROOT_BIN_FILENAME = "root.bin"

#: Per-hour OTS receipt filename.
RECEIPT_FILENAME = "root.bin.ots"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class VerificationResult:
    """Outcome of verifying a single ``event_id`` against the archive.

    Attributes
    ----------
    event_id:
        The event identifier the caller asked about.
    merkle_root:
        Hex-encoded Merkle root of the hour the event landed in, or
        empty string if the event was never located.
    bitcoin_block_height:
        Block height that confirms the OTS attestation, or ``None``
        if still pending or never reached.
    verification_status:
        One of ``"verified"``, ``"pending"``, ``"failed"``,
        ``"chain-mismatch"``.
    error_msg:
        Human-readable diagnostic when ``verification_status`` is
        not ``"verified"``; empty otherwise.
    hour_slot:
        ``YYYY-MM-DDTHH`` slot label of the hour the event was found
        in, or empty string when the event was not located.
    chain_status:
        Optional chain-check outcome when ``--chain-check`` is set:
        ``"chain-verified"`` (prev_hour_root walked and matched),
        ``"chain-skipped"`` (prev_hour_root is null at this hour --
        cold-start or empty-hour boundary), ``"chain-mismatch"``
        (prev_hour_root recorded does not match the previous hour's
        actual root). Empty string when the chain-check was not
        requested.
    """

    event_id: str
    merkle_root: str
    bitcoin_block_height: Optional[int]
    verification_status: str  # "verified" | "pending" | "failed" | "chain-mismatch"
    error_msg: str = ""
    hour_slot: str = ""
    chain_status: str = ""


# ---------------------------------------------------------------------------
# Manifest loading and proof reconstruction
# ---------------------------------------------------------------------------


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Read and shallow-validate a manifest JSON file."""
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    for required in ("hour_slot", "merkle_root", "events"):
        if required not in manifest:
            raise ValueError(
                f"manifest at {manifest_path} missing required key '{required}'"
            )
    if not isinstance(manifest["events"], list):
        raise ValueError(f"manifest 'events' at {manifest_path} is not a list")
    return manifest


def _event_to_leaf(event: dict[str, Any]) -> bytes:
    """Compute the WAT leaf hash for a manifest event entry."""
    try:
        return compute_leaf_hash(
            event_id=event["event_id"],
            time=event["time"],
            payload_hash=event["payload_hash"],
            capability_token_hash=event["capability_token_hash"],
        )
    except KeyError as exc:
        raise ValueError(
            f"event entry missing required B1 field: {exc.args[0]}"
        ) from exc


def lookup_event_in_hour(
    event_id: str,
    hour_slot: str,
    archive_dir: str | Path,
) -> Tuple[bytes, List[bytes]]:
    """Locate an event inside an hour-slot manifest.

    Parameters
    ----------
    event_id:
        Event identifier to search for.
    hour_slot:
        ``YYYY-MM-DDTHH`` directory label inside ``archive_dir``.
    archive_dir:
        Root of the receipt archive tree.

    Returns
    -------
    tuple
        ``(leaf_hash, all_leaves)`` where ``leaf_hash`` is the
        recomputed 32-byte leaf for the event and ``all_leaves`` is
        the full ordered list of leaves from that hour, suitable for
        :func:`reconstruct_proof_from_leaves`.

    Raises
    ------
    FileNotFoundError
        If the hour slot or its manifest do not exist.
    LookupError
        If no event in the hour matches ``event_id``.
    """
    archive = Path(archive_dir)
    hour_dir = archive / hour_slot
    manifest_path = hour_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"manifest not found for hour {hour_slot}: {manifest_path}"
        )

    manifest = _load_manifest(manifest_path)
    events = manifest["events"]

    # Build the full leaf list in manifest order so we can reconstruct
    # any inclusion proof from this single pass.
    all_leaves: List[bytes] = [_event_to_leaf(ev) for ev in events]

    # Find the requested event by id. We do not de-duplicate: the
    # first match wins, which matches aggregator semantics where
    # event_ids are unique per hour.
    for idx, ev in enumerate(events):
        if ev.get("event_id") == event_id:
            return all_leaves[idx], all_leaves

    raise LookupError(
        f"event_id {event_id!r} not present in hour {hour_slot}"
    )


def reconstruct_proof_from_leaves(
    leaf_bytes: bytes,
    all_leaves: Sequence[bytes],
) -> List[Tuple[bytes, str]]:
    """Rebuild the inclusion proof for ``leaf_bytes`` from the leaf set.

    Thin wrapper around :func:`wat.merkle.aggregator.merkle_proof`
    that hides the leaf-index lookup. Lifted out so tests can
    exercise the lookup-by-bytes path directly.
    """
    if len(leaf_bytes) != 32:
        raise ValueError(
            f"leaf_bytes must be 32 bytes, got {len(leaf_bytes)}"
        )
    try:
        index = next(i for i, leaf in enumerate(all_leaves) if leaf == leaf_bytes)
    except StopIteration as exc:
        raise LookupError("leaf not present in leaf list") from exc
    return merkle_proof(list(all_leaves), index)


# ---------------------------------------------------------------------------
# Top-level verification
# ---------------------------------------------------------------------------


def _find_hour_slot_for_event(
    event_id: str,
    archive_dir: Path,
) -> Optional[str]:
    """Scan the archive for the hour slot that contains ``event_id``.

    Linear scan in chronological order. For Phase 1a the archive
    is small enough (one directory per hour, ~24·365 = 8760 entries
    per year) that a directory walk per query is acceptable. A
    Phase-1b indexed lookup is on the backlog.
    """
    if not archive_dir.exists() or not archive_dir.is_dir():
        return None
    # Hour slots sort lexicographically by ISO-8601 prefix; iterate
    # newest-first so a fresh event resolves quickly.
    hour_dirs = sorted(
        (p for p in archive_dir.iterdir() if p.is_dir()),
        reverse=True,
    )
    for hour_dir in hour_dirs:
        manifest_path = hour_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            continue
        try:
            manifest = _load_manifest(manifest_path)
        except (json.JSONDecodeError, ValueError):
            # Skip corrupt manifests; the audit alarm handles them.
            continue
        for ev in manifest["events"]:
            if ev.get("event_id") == event_id:
                return manifest["hour_slot"]
    return None


def _previous_hour_slot(hour_slot: str) -> Optional[str]:
    """Return the ``YYYY-MM-DDTHH`` label one hour before ``hour_slot``.

    The slot label is parseable as ``%Y-%m-%dT%H``; we add a
    ``:00:00Z`` suffix to make it RFC-3339 and walk back via stdlib
    datetime so DST and month-boundary edge cases come out right.
    Returns ``None`` if the slot label is unparseable -- defensive
    only; the writer guarantees the format.
    """
    import datetime as _dt

    try:
        anchor = _dt.datetime.strptime(hour_slot, "%Y-%m-%dT%H").replace(
            tzinfo=_dt.timezone.utc
        )
    except ValueError:
        return None
    prev = anchor - _dt.timedelta(hours=1)
    return prev.strftime("%Y-%m-%dT%H")


def _check_hour_chain(
    archive: Path,
    hour_slot: str,
    manifest: dict[str, Any],
) -> Tuple[str, str]:
    """Validate the ``prev_hour_root`` link at the start of ``hour_slot``.

    Returns a 2-tuple ``(chain_status, error_msg)`` where
    ``chain_status`` is one of ``"chain-verified"``, ``"chain-skipped"``,
    ``"chain-mismatch"``. ``error_msg`` is empty on the verified and
    skipped paths, populated on a mismatch.

    Skipped cases:

    - Manifest does not carry the ``prev_hour_root`` key at all
      (legacy pre-Tag-8 manifest from before the always-emit fix).
    - ``prev_hour_root`` is ``null`` -- cold-start of the audit trail
      or post-gap chain boundary; either way there is no link to walk.

    Mismatch cases:

    - Previous-hour manifest exists and its ``merkle_root`` does NOT
      match the ``prev_hour_root`` recorded in the current manifest.
    - Previous-hour manifest cannot be located while
      ``prev_hour_root`` is non-null (gap-with-claimed-link is itself
      a chain break).
    """
    prev_hour_root = manifest.get("prev_hour_root", "__missing__")
    if prev_hour_root == "__missing__" or prev_hour_root is None:
        return ("chain-skipped", "")

    prev_slot = _previous_hour_slot(hour_slot)
    if prev_slot is None:
        return (
            "chain-mismatch",
            f"hour_slot {hour_slot!r} unparseable; cannot resolve previous hour",
        )

    prev_manifest_path = archive / prev_slot / MANIFEST_FILENAME
    if not prev_manifest_path.exists():
        return (
            "chain-mismatch",
            (
                f"prev_hour_root claims {prev_hour_root} but no manifest "
                f"exists at {prev_manifest_path} -- chain break at gap"
            ),
        )

    try:
        prev_manifest = _load_manifest(prev_manifest_path)
    except (json.JSONDecodeError, ValueError) as exc:
        return (
            "chain-mismatch",
            f"previous-hour manifest at {prev_manifest_path} unreadable: {exc}",
        )

    actual_prev_root = prev_manifest.get("merkle_root")
    if actual_prev_root != prev_hour_root:
        return (
            "chain-mismatch",
            (
                f"prev_hour_root drift: manifest claims {prev_hour_root!r} "
                f"but {prev_slot} actual root is {actual_prev_root!r}"
            ),
        )
    return ("chain-verified", "")


def verify_event(
    event_id: str,
    archive_dir: str | Path,
    *,
    chain_check: bool = False,
) -> VerificationResult:
    """Verify a single event end-to-end against the WAT archive.

    Steps:

    1. Find the hour slot that contains the event.
    2. Recompute the leaf hash from the manifest's four B1 fields.
    3. Rebuild the inclusion proof and check it against the
       manifest's stored Merkle root.
    4. Run ``ots verify`` on the hour's receipt against that root.
    5. (optional, ``chain_check=True``) Resolve the previous-hour
       manifest and confirm its ``merkle_root`` matches the current
       manifest's ``prev_hour_root`` slot.
    """
    archive = Path(archive_dir)
    if not archive.exists() or not archive.is_dir():
        return VerificationResult(
            event_id=event_id,
            merkle_root="",
            bitcoin_block_height=None,
            verification_status="failed",
            error_msg=f"archive directory not found: {archive}",
        )

    hour_slot = _find_hour_slot_for_event(event_id, archive)
    if hour_slot is None:
        return VerificationResult(
            event_id=event_id,
            merkle_root="",
            bitcoin_block_height=None,
            verification_status="failed",
            error_msg=f"event_id {event_id!r} not found in any hour manifest",
        )

    try:
        leaf, all_leaves = lookup_event_in_hour(event_id, hour_slot, archive)
    except (FileNotFoundError, LookupError, ValueError) as exc:
        return VerificationResult(
            event_id=event_id,
            merkle_root="",
            bitcoin_block_height=None,
            verification_status="failed",
            error_msg=str(exc),
            hour_slot=hour_slot,
        )

    manifest = _load_manifest(archive / hour_slot / MANIFEST_FILENAME)
    expected_root_hex = manifest["merkle_root"]
    try:
        expected_root = bytes.fromhex(expected_root_hex)
    except ValueError as exc:
        return VerificationResult(
            event_id=event_id,
            merkle_root=expected_root_hex,
            bitcoin_block_height=None,
            verification_status="failed",
            error_msg=f"manifest merkle_root is not valid hex: {exc}",
            hour_slot=hour_slot,
        )

    # Sanity: the leaves we just hashed must rebuild to the manifest root.
    rebuilt_root, _levels = build_merkle_tree(all_leaves)
    if rebuilt_root != expected_root:
        return VerificationResult(
            event_id=event_id,
            merkle_root=expected_root_hex,
            bitcoin_block_height=None,
            verification_status="failed",
            error_msg=(
                "manifest root mismatch: events rebuild to "
                f"{rebuilt_root.hex()} but manifest claims {expected_root_hex}"
            ),
            hour_slot=hour_slot,
        )

    # Inclusion proof for this specific event.
    proof = reconstruct_proof_from_leaves(leaf, all_leaves)
    if not verify_merkle_proof(leaf, proof, expected_root):
        return VerificationResult(
            event_id=event_id,
            merkle_root=expected_root_hex,
            bitcoin_block_height=None,
            verification_status="failed",
            error_msg="inclusion proof failed to reconstruct to manifest root",
            hour_slot=hour_slot,
        )

    # OTS receipt verification.
    receipt_path = archive / hour_slot / RECEIPT_FILENAME
    if not receipt_path.exists():
        return VerificationResult(
            event_id=event_id,
            merkle_root=expected_root_hex,
            bitcoin_block_height=None,
            verification_status="failed",
            error_msg=f"OTS receipt missing for hour {hour_slot}: {receipt_path}",
            hour_slot=hour_slot,
        )

    try:
        ots_ok = verify_receipt(receipt_path, expected_root)
    except (AnchorError, ValueError) as exc:
        # A still-pending receipt surfaces here as an OTS verify failure;
        # keep the proof result and report pending state.
        return VerificationResult(
            event_id=event_id,
            merkle_root=expected_root_hex,
            bitcoin_block_height=None,
            verification_status="pending",
            error_msg=f"OTS verify did not complete: {exc}",
            hour_slot=hour_slot,
        )

    if not ots_ok:
        # `verify_receipt` returns False for both a real mismatch and
        # for a still-pending receipt. We treat it as pending only if
        # the receipt file exists; a hash-mismatch case has already
        # been caught above by the rebuilt-root check.
        return VerificationResult(
            event_id=event_id,
            merkle_root=expected_root_hex,
            bitcoin_block_height=None,
            verification_status="pending",
            error_msg=(
                "OTS receipt not yet finalised on Bitcoin "
                "(or verify failed for a transient reason)"
            ),
            hour_slot=hour_slot,
        )

    # Block height is recorded by the upgrade pipeline in a sidecar
    # file when known; absence here is fine — the receipt itself is
    # the source of truth and it has been verified.
    block_height: Optional[int] = None
    block_meta = archive / hour_slot / "bitcoin_block.txt"
    if block_meta.exists():
        try:
            block_height = int(block_meta.read_text(encoding="utf-8").strip())
        except ValueError:
            block_height = None

    # Optional chain-check: walk one step back via prev_hour_root and
    # confirm the link. Failure here downgrades the result to
    # ``chain-mismatch`` even though the inclusion proof itself was
    # clean -- a chain break is still an audit-trail integrity event.
    chain_status = ""
    if chain_check:
        chain_status, chain_err = _check_hour_chain(archive, hour_slot, manifest)
        if chain_status == "chain-mismatch":
            return VerificationResult(
                event_id=event_id,
                merkle_root=expected_root_hex,
                bitcoin_block_height=block_height,
                verification_status="chain-mismatch",
                error_msg=chain_err,
                hour_slot=hour_slot,
                chain_status=chain_status,
            )

    return VerificationResult(
        event_id=event_id,
        merkle_root=expected_root_hex,
        bitcoin_block_height=block_height,
        verification_status="verified",
        error_msg="",
        hour_slot=hour_slot,
        chain_status=chain_status,
    )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Return the configured argument parser."""
    parser = argparse.ArgumentParser(
        prog="wakir-wat-verify",
        description=(
            "Verify a WAT event end-to-end: leaf hash, inclusion "
            "proof, OTS receipt, Bitcoin attestation. Server-side "
            "convenience verifier (BUSL-1.1); the offline Apache-2.0 "
            "brand-proof verifier ships separately as `wakir-verify` "
            "from the wakir-labs/wakir-verify repository."
        ),
    )
    parser.add_argument(
        "event_id",
        help="Event identifier as recorded in the hour manifest.",
    )
    parser.add_argument(
        "--archive-dir",
        default="meta/timestamps/wat",
        help="Root of the WAT receipt archive (default: %(default)s).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-step progress; emit only the result line.",
    )
    parser.add_argument(
        "--chain-check",
        action="store_true",
        help=(
            "Additionally validate the prev_hour_root link by loading the "
            "previous hour's manifest and comparing roots. Skipped when "
            "prev_hour_root is null (cold-start or empty-hour boundary). "
            "Mismatch yields exit code 4."
        ),
    )
    return parser


def _format_human(result: VerificationResult, *, quiet: bool) -> str:
    if quiet:
        if result.chain_status:
            return (
                f"{result.verification_status}\t{result.chain_status}\t"
                f"{result.event_id}"
            )
        return f"{result.verification_status}\t{result.event_id}"
    lines = [
        f"event_id:       {result.event_id}",
        f"hour_slot:      {result.hour_slot or '(not found)'}",
        f"merkle_root:    {result.merkle_root or '(not found)'}",
        f"block_height:   {result.bitcoin_block_height if result.bitcoin_block_height is not None else '(none)'}",
        f"status:         {result.verification_status}",
    ]
    if result.chain_status:
        lines.append(f"chain_status:   {result.chain_status}")
    if result.error_msg:
        lines.append(f"error:          {result.error_msg}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a Unix exit code.

    Exit codes
    ----------

    0   verified (and chain-verified, if ``--chain-check`` was set)
    1   failed (proof or OTS-receipt mismatch, missing manifest, ...)
    3   pending (proof OK, OTS receipt not yet finalised on Bitcoin)
    4   chain-mismatch (Tag-8 addition; ``--chain-check`` only)
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    result = verify_event(
        args.event_id,
        args.archive_dir,
        chain_check=args.chain_check,
    )
    print(_format_human(result, quiet=args.quiet))

    if result.verification_status == "verified":
        return 0
    if result.verification_status == "pending":
        return 3
    if result.verification_status == "chain-mismatch":
        return 4
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "MANIFEST_FILENAME",
    "RECEIPT_FILENAME",
    "ROOT_BIN_FILENAME",
    "VerificationResult",
    "build_parser",
    "lookup_event_in_hour",
    "main",
    "reconstruct_proof_from_leaves",
    "verify_event",
]
