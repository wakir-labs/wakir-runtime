# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ./LICENSE-BSL.md.
# Change Date: four (4) years after first publication of this release.
# Change License: Apache License 2.0.

"""Top-level ``wat`` command-line dispatcher.

This module exposes the operator-facing ``wat`` console script as a
thin facade over the more specialised CLIs under :mod:`wat.cmd` and
:mod:`wat.verify`. It owns *only* the dispatch table and the
``anchor-receipt`` sub-command, which is a Phase-2 Observability
helper called out by PR #116 §5 (Cross-Review-Pflicht für on-VM-CLI).

``wat anchor-receipt`` purpose
------------------------------

Operators running Live-VM acceptance tests (and Henrik's audit
sample §4-A/§4-B) need a quick, machine-readable view of *one* WAT
pipeline hour without having to know the layout of
``meta/timestamps/wat/<hour>/``. The receipt CLI emits a tight JSON
object with exactly the five fields PR #116 §5 calls out:

- ``ots_receipt_path``      — filesystem path to ``root.bin.ots``,
                              or empty string if no receipt exists.
- ``bitcoin_block_height``  — integer block height, or ``null`` if
                              the receipt has not been upgraded yet.
- ``verifier_state``        — ``"finalized"`` | ``"pending"`` |
                              ``"failed"``.
- ``anchor_root_hex``       — hex-encoded 32-byte Merkle root of the
                              hour, read from the manifest, or empty
                              string if no manifest exists.
- ``wat_manifest_path``     — filesystem path to ``manifest.json``,
                              or empty string if no manifest exists.

The contract is intentionally minimal so that downstream Operator-
Hand TV-LVD vectors can assert against the JSON shape without
coupling to the full manifest schema (which is ``wat-manifest/2.0``
and considerably wider).

Hermetic mode
-------------

Production callers want ``verifier_state`` to reflect the actual
Bitcoin attestation status, which requires shelling out to ``ots
info`` for the receipt. Tests, however, run inside the unit-test
sandbox without an ``ots`` binary on PATH, so they pass
``--no-info-probe`` (or call :func:`build_anchor_receipt` with
``info_probe=False``) and rely on the receipt-status sidecar (see
below). Both paths produce the same JSON schema; only the source of
``verifier_state`` differs.

Receipt-status sidecar
----------------------

If the hour directory contains an optional ``receipt-status.json``
file with keys ``bitcoin_block_height`` (int | null) and
``verifier_state`` (string), those values take precedence over the
``ots info`` probe. The sidecar is written by the hourly anchor
pipeline (or by the backfill upgrade) so that ``wat anchor-receipt``
can answer queries without re-running ``ots info`` on every call.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default archive root for the per-hour WAT receipt tree. Mirrors
#: :mod:`wat.verify.cli` so the two CLIs share a single source of
#: truth for archive layout.
DEFAULT_ARCHIVE_DIR = "meta/timestamps/wat"

#: Per-hour manifest filename. Same source-of-truth pin as
#: :data:`wat.verify.cli.MANIFEST_FILENAME`.
MANIFEST_FILENAME = "manifest.json"

#: Per-hour raw Merkle root file.
ROOT_BIN_FILENAME = "root.bin"

#: Per-hour OpenTimestamps receipt.
RECEIPT_FILENAME = "root.bin.ots"

#: Optional sidecar that records the upgraded receipt status without
#: requiring an ``ots info`` probe. Written by the backfill driver
#: after a successful ``upgrade_pending`` call.
RECEIPT_STATUS_FILENAME = "receipt-status.json"

#: Valid values for the ``verifier_state`` field. The CLI rejects any
#: sidecar value not in this set so a typo in the upgrade-driver
#: cannot silently propagate.
VALID_VERIFIER_STATES = ("finalized", "pending", "failed")

#: Hour-slot regex matching ``YYYY-MM-DDTHH``. Single source-of-truth
#: with :mod:`wat.ingestion.spool_writer`; duplicated here to keep
#: the dispatcher import-graph free of the ingestion module.
HOUR_SLOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}$")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AnchorReceiptReport:
    """Plain-data result of ``wat anchor-receipt`` for a single hour.

    Fields are 1:1 with the five JSON keys defined in PR #116 §5; the
    dataclass exists so Python callers (e.g. on-VM smoke tests) can
    consume the result without going through ``json.loads`` on the
    CLI's stdout.
    """

    ots_receipt_path: str
    bitcoin_block_height: Optional[int]
    verifier_state: str
    anchor_root_hex: str
    wat_manifest_path: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ots_receipt_path": self.ots_receipt_path,
            "bitcoin_block_height": self.bitcoin_block_height,
            "verifier_state": self.verifier_state,
            "anchor_root_hex": self.anchor_root_hex,
            "wat_manifest_path": self.wat_manifest_path,
        }


# ---------------------------------------------------------------------------
# Hour resolution
# ---------------------------------------------------------------------------


def _validate_hour_slot(hour: str) -> str:
    if not HOUR_SLOT_RE.match(hour):
        raise ValueError(
            f"hour {hour!r} is not in YYYY-MM-DDTHH form (UTC, two-digit hour)"
        )
    return hour


def resolve_latest_hour(archive_dir: Path) -> str:
    """Return the lexicographically greatest hour slot under ``archive_dir``.

    Lexicographic order matches chronological order because the slot
    format is fixed-width ``YYYY-MM-DDTHH``. Only directories whose
    name matches :data:`HOUR_SLOT_RE` are considered, so a stray
    ``_pending`` working directory cannot shadow the real latest
    hour.

    Raises
    ------
    FileNotFoundError
        If the archive directory does not exist or contains no
        well-formed hour-slot subdirectories.
    """
    if not archive_dir.exists():
        raise FileNotFoundError(f"archive directory does not exist: {archive_dir}")
    slots = sorted(
        entry.name
        for entry in archive_dir.iterdir()
        if entry.is_dir() and HOUR_SLOT_RE.match(entry.name)
    )
    if not slots:
        raise FileNotFoundError(
            f"no hour-slot subdirectories under {archive_dir}"
        )
    return slots[-1]


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------


def _load_manifest_root(manifest_path: Path) -> str:
    """Return the hex Merkle root recorded in ``manifest.json``.

    Returns an empty string if the file is missing or malformed --
    the caller decides whether that constitutes ``"failed"``.
    """
    if not manifest_path.exists():
        return ""
    try:
        with manifest_path.open("r", encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return ""
    root = blob.get("merkle_root", "")
    if not isinstance(root, str):
        return ""
    return root


def _load_status_sidecar(status_path: Path) -> Optional[dict[str, Any]]:
    """Return parsed sidecar dict, or ``None`` if missing / malformed."""
    if not status_path.exists():
        return None
    try:
        with status_path.open("r", encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(blob, dict):
        return None
    return blob


def _probe_ots_info(receipt_path: Path) -> Optional[int]:
    """Return Bitcoin block height from ``ots info``, or ``None``.

    The implementation deliberately shells out via the same
    :mod:`subprocess` boundary the rest of the anchor pipeline uses
    (see :mod:`wat.anchor.ots_anchor`) so that monkey-patching
    ``subprocess.run`` in tests still works. Failures (missing
    ``ots`` binary, non-zero exit, no block-height line) are
    swallowed and reported as ``None`` -- the caller falls back to
    ``"pending"``.
    """
    if shutil.which("ots") is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 — explicit args, no shell.
            ["ots", "info", str(receipt_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    blob = (result.stdout or "") + "\n" + (result.stderr or "")
    for line in blob.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("bitcoin block"):
            parts = stripped.split()
            if len(parts) >= 3 and parts[2].isdigit():
                return int(parts[2])
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_anchor_receipt(
    hour_dir: Path,
    *,
    info_probe: bool = True,
) -> AnchorReceiptReport:
    """Assemble the anchor-receipt report for a single hour directory.

    Parameters
    ----------
    hour_dir:
        Directory ``<archive>/<YYYY-MM-DDTHH>/``. Need not exist; a
        missing directory yields ``verifier_state == "failed"`` with
        all path fields empty.
    info_probe:
        When True (default), and no ``receipt-status.json`` sidecar
        is found, the CLI shells out to ``ots info`` to read the
        Bitcoin block height. Tests pass ``info_probe=False`` to
        stay hermetic; the resulting state is ``"pending"`` when a
        receipt exists but no sidecar carries a height.

    Returns
    -------
    AnchorReceiptReport
        Fully populated, JSON-serialisable result.
    """
    manifest_path = hour_dir / MANIFEST_FILENAME
    receipt_path = hour_dir / RECEIPT_FILENAME
    status_path = hour_dir / RECEIPT_STATUS_FILENAME

    manifest_exists = manifest_path.exists()
    receipt_exists = receipt_path.exists()

    anchor_root_hex = _load_manifest_root(manifest_path) if manifest_exists else ""
    manifest_str = str(manifest_path) if manifest_exists else ""
    receipt_str = str(receipt_path) if receipt_exists else ""

    # No receipt at all -> failed. We still surface the manifest path
    # if one exists, because the caller may want to diagnose the gap
    # between a sealed hour and a missing OTS submission.
    if not receipt_exists:
        return AnchorReceiptReport(
            ots_receipt_path="",
            bitcoin_block_height=None,
            verifier_state="failed",
            anchor_root_hex=anchor_root_hex,
            wat_manifest_path=manifest_str,
        )

    # Receipt present. Prefer sidecar over subprocess probe.
    bitcoin_block_height: Optional[int] = None
    verifier_state: Optional[str] = None

    sidecar = _load_status_sidecar(status_path)
    if sidecar is not None:
        raw_state = sidecar.get("verifier_state")
        if isinstance(raw_state, str) and raw_state in VALID_VERIFIER_STATES:
            verifier_state = raw_state
            # Only trust the height when the state itself was
            # well-formed; an unknown state value invalidates the
            # whole sidecar from the operator-contract perspective.
            raw_height = sidecar.get("bitcoin_block_height")
            if isinstance(raw_height, int) and not isinstance(raw_height, bool):
                bitcoin_block_height = raw_height

    if verifier_state is None and info_probe:
        probed_height = _probe_ots_info(receipt_path)
        if probed_height is not None:
            bitcoin_block_height = probed_height
            verifier_state = "finalized"

    if verifier_state is None:
        # Receipt file exists, no upgrade record yet.
        verifier_state = "pending"

    # Defensive consistency check: if the sidecar declares "finalized"
    # but did not supply a height, downgrade to "pending" rather than
    # publish an internally inconsistent report.
    if verifier_state == "finalized" and bitcoin_block_height is None:
        verifier_state = "pending"

    return AnchorReceiptReport(
        ots_receipt_path=receipt_str,
        bitcoin_block_height=bitcoin_block_height,
        verifier_state=verifier_state,
        anchor_root_hex=anchor_root_hex,
        wat_manifest_path=manifest_str,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_summary(report: AnchorReceiptReport, hour: str) -> str:
    """Render a short human-readable summary of an anchor-receipt report."""
    height = (
        str(report.bitcoin_block_height)
        if report.bitcoin_block_height is not None
        else "(none)"
    )
    root = report.anchor_root_hex or "(unknown)"
    receipt = report.ots_receipt_path or "(missing)"
    return (
        f"hour:         {hour}\n"
        f"state:        {report.verifier_state}\n"
        f"block_height: {height}\n"
        f"root:         {root}\n"
        f"receipt:      {receipt}\n"
        f"manifest:     {report.wat_manifest_path or '(missing)'}"
    )


def format_json(report: AnchorReceiptReport) -> str:
    """Render a deterministic JSON line for the report.

    ``sort_keys`` keeps the output stable so on-VM smoke tests can
    diff against a fixture without floating field order.
    """
    return json.dumps(report.to_json_dict(), sort_keys=True)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Return the configured argument parser for ``wat``."""
    parser = argparse.ArgumentParser(
        prog="wat",
        description=(
            "Top-level Wakir Audit Trail (WAT) command-line dispatcher. "
            "Subcommands cover observability and audit-sampling helpers "
            "that complement the per-domain CLIs under wat.cmd.*."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_anchor = sub.add_parser(
        "anchor-receipt",
        help="Emit JSON / summary for the OTS anchor of a WAT pipeline hour.",
        description=(
            "Report the anchor-receipt status of a single WAT pipeline "
            "hour. Output schema (JSON): ots_receipt_path, "
            "bitcoin_block_height, verifier_state, anchor_root_hex, "
            "wat_manifest_path."
        ),
    )
    target = p_anchor.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--hour",
        metavar="YYYY-MM-DDTHH",
        help="UTC hour slot to query (e.g. 2026-05-16T14).",
    )
    target.add_argument(
        "--latest",
        action="store_true",
        help="Query the most recent hour slot found under --archive-dir.",
    )
    p_anchor.add_argument(
        "--archive-dir",
        default=DEFAULT_ARCHIVE_DIR,
        help=(
            "Root of the WAT receipt archive tree "
            "(default: %(default)s)."
        ),
    )
    fmt = p_anchor.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json",
        dest="fmt",
        action="store_const",
        const="json",
        help="Emit a deterministic single-line JSON object (default).",
    )
    fmt.add_argument(
        "--summary",
        dest="fmt",
        action="store_const",
        const="summary",
        help="Emit a multi-line human-readable summary instead of JSON.",
    )
    p_anchor.set_defaults(fmt="json")
    p_anchor.add_argument(
        "--no-info-probe",
        action="store_true",
        help=(
            "Do not shell out to 'ots info' for block-height "
            "discovery; rely on receipt-status.json sidecar only. "
            "Used by hermetic tests."
        ),
    )

    return parser


def _run_anchor_receipt(args: argparse.Namespace) -> int:
    archive_dir = Path(args.archive_dir)

    if args.latest:
        try:
            hour = resolve_latest_hour(archive_dir)
        except FileNotFoundError as exc:
            print(f"anchor-receipt error: {exc}", file=sys.stderr)
            return 2
    else:
        try:
            hour = _validate_hour_slot(args.hour)
        except ValueError as exc:
            print(f"anchor-receipt error: {exc}", file=sys.stderr)
            return 64

    hour_dir = archive_dir / hour
    report = build_anchor_receipt(
        hour_dir,
        info_probe=not args.no_info_probe,
    )

    if args.fmt == "summary":
        print(format_summary(report, hour))
    else:
        print(format_json(report))

    # Exit code: 0 if the report is finalized, 3 if pending (caller can
    # treat that as "retry later"), 4 if failed. Operators chaining
    # this CLI into shell pipelines rely on these codes.
    if report.verifier_state == "finalized":
        return 0
    if report.verifier_state == "pending":
        return 3
    return 4


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``wat`` console-script entry point. Returns a Unix exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "anchor-receipt":
        return _run_anchor_receipt(args)

    parser.error(f"unknown sub-command: {args.cmd}")
    return 2  # pragma: no cover -- argparse.error raises SystemExit


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "AnchorReceiptReport",
    "DEFAULT_ARCHIVE_DIR",
    "MANIFEST_FILENAME",
    "RECEIPT_FILENAME",
    "RECEIPT_STATUS_FILENAME",
    "ROOT_BIN_FILENAME",
    "VALID_VERIFIER_STATES",
    "build_anchor_receipt",
    "build_parser",
    "format_json",
    "format_summary",
    "main",
    "resolve_latest_hour",
]
