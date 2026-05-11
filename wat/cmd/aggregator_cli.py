# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Aggregator CLI for the WAT hourly anchor flow.

The ``wakir-merkle`` console script is the writer side of the
hourly contract. ``wat.verify.cli`` is the reader side; the two
modules share the on-disk manifest format documented in
``docs/wat-manifest-spec.md``.

Subcommands
-----------

``build``
    Read a JSONL spool of frame events for a single UTC hour,
    canonicalise them via JCS (RFC 8785), build a Bitcoin-pattern
    Merkle tree (see :mod:`wat.merkle.aggregator`), and emit the
    receipt manifest the verify-CLI consumes.

Phase 1a, day 5
---------------

Day 2 shipped the argparse skeleton; day 5 fills in the body and
introduces a proper subcommand surface so the next-day verify and
backfill commands can hang off the same script. The legacy flat
flags (``--input-file`` / ``--output-receipt``) used by the day-3
scaffold are still accepted for one release as a transitional alias
so the hourly cron does not flap during the rollout — see
``_legacy_to_build_args``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

from wat.merkle.aggregator import (
    build_merkle_tree,
    compute_leaf_hash,
)
# wat.identity.manifest_signing is imported lazily inside
# :func:`_sign_manifest_in_place` so the unsigned-aggregator path
# (the dominant cron path on rollout) stays free of the rfc8785 /
# cryptography import cost. The hourly subprocess driver in
# ``scripts/wat-hourly.sh`` runs without the test venv on some
# operator hosts; the lazy-import keeps that path importable when
# only the merkle/aggregator stack is installed.


# ---------------------------------------------------------------------------
# Manifest schema constants. Bumping the version requires a doc-spec update
# in ``docs/wat-manifest-spec.md`` and a coordinated change in the verify
# CLI. The reader currently tolerates unknown fields, so additive changes
# do not require a version bump; field-removal or semantic shifts do.
# ---------------------------------------------------------------------------

MANIFEST_VERSION = "wakir-wat-manifest/v1"

#: Required B1-consensus fields on every input event. Order is the
#: documented canonical order; the leaf-hash function uses JCS so the
#: physical order in the JSON object does not affect the digest, but we
#: validate against this set to catch missing fields early.
REQUIRED_FIELDS: tuple[str, ...] = (
    "event_id",
    "time",
    "payload_hash",
    "capability_token_hash",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """Raised when an input event fails B1-shape validation.

    Subclassing ``ValueError`` keeps the existing ``except ValueError``
    handlers in callers (and tests) working without churn while still
    letting tests assert on the more specific type when they care.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_rfc3339() -> str:
    """Return the current UTC time as an RFC 3339 string with ``Z`` suffix."""
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_events(input_path: Path) -> List[dict[str, Any]]:
    """Parse a JSONL spool into a list of event dicts.

    Empty / blank lines are skipped (operator-friendly: hand-edited
    spools often acquire trailing newlines). Malformed JSON raises
    ``ValidationError`` with the offending line number so the operator
    can locate the bad event without grepping.
    """
    if not input_path.exists():
        raise ValidationError(f"input file not found: {input_path}")

    events: List[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"{input_path}:{lineno}: invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(event, dict):
                raise ValidationError(
                    f"{input_path}:{lineno}: expected JSON object, got {type(event).__name__}"
                )
            events.append(event)
    return events


def _validate_events(events: Iterable[dict[str, Any]]) -> List[dict[str, Any]]:
    """Validate the B1-shape of every event and return them as a list.

    For each event, all four required fields must be present and must
    be strings. Any deviation raises ``ValidationError`` with the
    event index and the missing/wrong field — operators see a single
    actionable error rather than a stack trace.
    """
    validated: List[dict[str, Any]] = []
    for idx, event in enumerate(events):
        for field in REQUIRED_FIELDS:
            if field not in event:
                raise ValidationError(
                    f"event[{idx}]: missing required B1 field '{field}'; "
                    f"expected all of {list(REQUIRED_FIELDS)}"
                )
            if not isinstance(event[field], str):
                raise ValidationError(
                    f"event[{idx}].{field}: expected string, got "
                    f"{type(event[field]).__name__}"
                )
        validated.append(event)
    return validated


def _sorted_by_time_then_event_id(
    events: Sequence[dict[str, Any]],
) -> List[dict[str, Any]]:
    """Return events sorted by the ``(time, event_id)`` tuple, ascending.

    Per ``docs/wat-spool-spec.md`` §4 the canonical aggregator sort is
    lexicographic on the 2-tuple ``(time, event_id)``. Both fields are
    strings; the Wakir conventions (RFC 3339 ``Z``-suffixed UTC and
    UUIDv7 event IDs) are designed so lexicographic sort is also
    time-ordered. ``event_id`` breaks ties when two events share the
    same ``time`` value -- this is rare but possible at sub-second
    coalescing points.

    Sorting at build time is the deterministic-Merkle-root contract:
    two operators replaying the same hour with the same spool produce
    bit-identical manifests regardless of source ordering. The verify
    CLI relies on this property to recompute the leaf list in manifest
    order without consulting an external index.

    Phase-1a-Tag-8 fix: the previous implementation sorted by
    ``event_id`` only, which drifted from the spool-spec contract.
    The two sort keys agree for typical traffic (UUIDv7 monotonic with
    time) but disagree under coalesced timestamps or out-of-order
    bridge restart replays. Hash-consistency vectors are unaffected --
    they pin individual leaf hashes, not pack-roots.
    """
    return sorted(events, key=lambda ev: (ev["time"], ev["event_id"]))


# ---------------------------------------------------------------------------
# Backwards-compat alias. The Tag-7 internals re-exported this name on
# the module surface; keep it pointing at the new implementation so any
# in-repo or downstream caller that imported it directly does not break
# silently. The alias is private (leading underscore) so it is not part
# of the public API and can be removed in a later cleanup pass.
# ---------------------------------------------------------------------------
_sorted_by_event_id = _sorted_by_time_then_event_id


def _build_manifest_object(
    *,
    hour_slot: str,
    events: Sequence[dict[str, Any]],
    build_time: str,
    prev_hour_root: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble the manifest dict for a non-empty hour.

    Returns the manifest as an in-memory dict so callers can either
    serialise it to disk (production path) or assert on it directly
    (tests).

    ``prev_hour_root`` is the v1 reservation slot (``docs/wat-manifest-
    spec.md`` "prev_hour_root reservation"). It is optional in v1 with
    ``null`` as the default; v1 verifiers ignore the value, but writing
    it now lets v2 chain-check work over historical hours once the v2
    verifier ships. Phase-1a-Tag-7: emit only when explicitly supplied;
    Phase-1a-Tag-8 will wire the previous-hour discovery into the
    hourly driver so the field is populated automatically.
    """
    leaves_bytes: List[bytes] = []
    leaf_entries: List[dict[str, str]] = []
    for ev in events:
        leaf = compute_leaf_hash(
            event_id=ev["event_id"],
            time=ev["time"],
            payload_hash=ev["payload_hash"],
            capability_token_hash=ev["capability_token_hash"],
        )
        leaves_bytes.append(leaf)
        leaf_entries.append(
            {
                "event_id": ev["event_id"],
                "time": ev["time"],
                "payload_hash": ev["payload_hash"],
                "capability_token_hash": ev["capability_token_hash"],
                "leaf_hash": leaf.hex(),
            }
        )

    root, levels = build_merkle_tree(leaves_bytes)
    tree_levels_hex: List[List[str]] = [
        [node.hex() for node in level] for level in levels
    ]

    manifest: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "hour_slot": hour_slot,
        "merkle_root": root.hex(),
        "event_count": len(events),
        # ``events`` is the verify-CLI-facing key; ``leaves`` is an
        # alias added for the build-side schema documented in the
        # spec. They reference the same list to keep the manifest
        # internally consistent without doubling the payload size.
        "events": leaf_entries,
        "leaves": leaf_entries,
        "tree_levels": tree_levels_hex,
        "build_time": build_time,
        # Reservation slot per ``docs/wat-manifest-spec.md`` -- v1
        # writers always emit the field, defaulting to ``null`` when
        # no previous-hour root was discovered. v1 readers MUST
        # tolerate; v2 readers under ``--chain-check`` use the value
        # to walk the chain. Phase-1a-Tag-8 wires this from the
        # hourly driver via ``wat-hourly.sh`` automatic discovery.
        "prev_hour_root": prev_hour_root,
    }
    return manifest


def _build_empty_manifest(
    *,
    hour_slot: str,
    build_time: str,
    prev_hour_root: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble the manifest for an empty hour.

    An empty hour writes a manifest with ``merkle_root: null``. The
    pipeline driver checks this field and skips the anchor call so we
    never submit an all-zero or placeholder root to the OTS calendars.

    ``prev_hour_root`` follows the same v1-optional rule as the non-
    empty path. v2 will document the empty-hour-after-empty-hour case
    explicitly; until then writers MAY chain across empty hours by
    forwarding the previous root through.
    """
    manifest: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "hour_slot": hour_slot,
        "merkle_root": None,
        "event_count": 0,
        "events": [],
        "leaves": [],
        "tree_levels": [],
        "build_time": build_time,
        # Reservation slot per ``docs/wat-manifest-spec.md`` -- always
        # emitted in v1, defaulting to ``null``. An empty hour MAY
        # forward the previous-hour root through (operator-driven
        # decision; the v1 reader ignores either way), but the default
        # is a clean ``null`` so empty hours always compare equal.
        "prev_hour_root": prev_hour_root,
    }
    return manifest


# ---------------------------------------------------------------------------
# Aggregator-side signing (Phase-2 Sprint-6 Tag-3).
#
# The aggregator emits an Ed25519 detached signature on the hour-manifest
# when both ``--sign-key`` and ``--sign-kid`` are supplied (or the
# matching in-process ``sign_key`` / ``sign_kid`` arguments are passed
# through :func:`build_command`). The signing primitive
# (:func:`wat.identity.manifest_signing.sign_manifest`) is the same
# byte-shaped routine the verifier consumes via
# :func:`wat.verify.manifest_v2.verify_real_manifest_file` under
# ``verify_signature=True``. Closing this loop means a production
# manifest now ships with its signature slot embedded on disk; the
# downstream verifier-side wire-up (Sprint-5 Tag-2 / Sprint-6 Tag-2)
# accepts it end-to-end without further plumbing.
#
# Key-material handling is intentionally lightweight: the key file is a
# 64-char hex string holding the 32-byte raw Ed25519 seed. PEM / PKCS#8
# parsing is deferred to a later operator-tooling pass; the hex format
# matches the conventions used by the test fixtures and the AIP-document
# ``public_keys[].key_hex`` slot. A trailing newline is tolerated.
# ---------------------------------------------------------------------------


class _SigningConfigError(ValidationError):
    """Raised when signing is mis-configured (e.g. partial flag pair)."""


def _load_sign_key(path: str | Path) -> bytes:
    """Load a 32-byte Ed25519 raw seed from ``path``.

    Accepts a 64-char hex-encoded seed (matching the AIP-document
    ``key_hex`` convention) with an optional trailing newline.
    Operator-friendly errors: a missing file, a non-hex payload, and
    a wrong-length payload each surface a distinct message so a cron
    failure log points straight at the misconfiguration.
    """
    key_path = Path(path)
    if not key_path.exists():
        raise _SigningConfigError(f"signing key file not found: {key_path}")
    raw = key_path.read_text(encoding="utf-8").strip()
    try:
        seed = bytes.fromhex(raw)
    except ValueError as exc:
        raise _SigningConfigError(
            f"signing key file is not valid hex: {key_path}: {exc}"
        ) from exc
    if len(seed) != 32:
        raise _SigningConfigError(
            f"signing key must decode to 32 bytes; got {len(seed)} bytes "
            f"from {key_path}"
        )
    return seed


def _resolve_signing_config(
    *,
    sign_key: Optional[str | Path],
    sign_kid: Optional[str],
) -> Optional[tuple[bytes, str]]:
    """Return ``(seed_bytes, kid)`` when signing is enabled, else ``None``.

    Both ``sign_key`` and ``sign_kid`` must be supplied together. Partial
    configuration (one set, the other absent) is a hard error so a
    half-edited cron does not silently emit unsigned manifests while the
    operator believes signing is on.
    """
    if sign_key is None and sign_kid is None:
        return None
    if sign_key is None or sign_kid is None:
        raise _SigningConfigError(
            "--sign-key and --sign-kid must be supplied together; got "
            f"sign_key={sign_key!r}, sign_kid={sign_kid!r}"
        )
    if not isinstance(sign_kid, str) or sign_kid == "":
        raise _SigningConfigError(
            f"--sign-kid must be a non-empty string: got {sign_kid!r}"
        )
    seed = _load_sign_key(sign_key)
    return seed, sign_kid


def _sign_manifest_in_place(
    manifest: dict[str, Any],
    *,
    seed: bytes,
    kid: str,
) -> dict[str, Any]:
    """Return a new dict with the ``signature`` slot embedded.

    The input manifest is not mutated. The signing primitive strips and
    re-attaches the slot internally; we wrap that into the on-disk
    envelope shape the verifier consumes (signed manifest dict with the
    block under the top-level ``signature`` key).

    Cryptographic errors surface as :class:`ValidationError` so the
    aggregator main loop's existing handler reports them as a
    operator-actionable error (exit code 2) rather than a stack trace.

    The ``wat.identity.manifest_signing`` import is lazy here so the
    unsigned-aggregator code path (operator host without rfc8785 /
    cryptography in the active interpreter) keeps importing cleanly.
    Only the signing path pays the import cost, and only on the hour
    where signing is actually configured.
    """
    from wat.identity.manifest_signing import (  # noqa: PLC0415 — lazy by design
        SIGNATURE_FIELD,
        WatManifestSignatureError,
        sign_manifest,
    )

    try:
        signed = sign_manifest(manifest, seed, kid=kid)
    except WatManifestSignatureError as exc:
        raise _SigningConfigError(
            f"manifest signing failed: {exc}"
        ) from exc
    out = dict(signed.manifest)
    out[SIGNATURE_FIELD] = dict(signed.signature)
    return out


def _write_manifest(manifest: dict[str, Any], output_path: Path) -> None:
    """Serialise ``manifest`` to disk as pretty-printed UTF-8 JSON.

    Pretty-printing is deliberate: the manifest is part of the public
    audit-trail contract and an auditor may ``less`` it. JCS-style
    canonical JSON (no spaces, sorted keys) would produce smaller
    files but harm human inspection. The Merkle root in the file is
    derived from JCS canonicalisation of the *leaves*, so the on-disk
    JSON formatting does not affect verifiability.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# argparse plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Return the configured argument parser.

    The parser exposes the ``build`` subcommand as the production
    entry point. To avoid breaking the day-3 hourly cron during the
    rollout window, the legacy flat flags are still accepted on the
    top-level parser and rewritten into a synthetic ``build`` invocation
    in :func:`main` (see :func:`_legacy_to_build_args`).
    """
    parser = argparse.ArgumentParser(
        prog="wakir-merkle",
        description=(
            "Aggregate Wirelang frame events into an hourly Merkle tree "
            "and emit a receipt manifest for OTS anchoring."
        ),
    )

    sub = parser.add_subparsers(dest="cmd")

    p_build = sub.add_parser(
        "build",
        help="Build the hourly manifest from a JSONL event spool.",
    )
    p_build.add_argument(
        "--hour",
        required=True,
        help="UTC hour label, format YYYY-MM-DDTHH (e.g. 2026-05-06T17).",
    )
    p_build.add_argument(
        "--input-events",
        required=True,
        help="Path to a JSONL file with one event per line.",
    )
    p_build.add_argument(
        "--output-manifest",
        required=True,
        help="Path where the receipt manifest JSON will be written.",
    )
    p_build.add_argument(
        "--prev-hour-root",
        default=None,
        help=(
            "Optional 64-char hex Merkle root of the preceding hour. "
            "Reservation slot in v1; required in v2 for chain-check."
        ),
    )
    p_build.add_argument(
        "--sign-key",
        default=None,
        help=(
            "Path to a file containing a 64-char hex-encoded 32-byte "
            "Ed25519 raw seed used to sign the emitted manifest. Must "
            "be paired with --sign-kid; signing is disabled when both "
            "are omitted."
        ),
    )
    p_build.add_argument(
        "--sign-kid",
        default=None,
        help=(
            "Key identifier embedded in the signature block. Must "
            "match an AIP-document public_keys[].kid entry under the "
            "'wat-anchor' purpose for the downstream resolver path. "
            "Required when --sign-key is supplied."
        ),
    )

    # --- Legacy aliases (day-3 cron contract). Kept on the top-level
    # parser so that ``wakir-merkle --input-file ...`` keeps working
    # for one release. New callers should always use ``build``.
    parser.add_argument(
        "--input-file",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output-receipt",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--hour-legacy",
        dest="hour_legacy",
        default=None,
        help=argparse.SUPPRESS,
    )

    return parser


def _legacy_to_build_args(
    argv: Sequence[str],
) -> Optional[List[str]]:
    """Rewrite legacy flat invocation into a synthetic ``build`` invocation.

    Returns the rewritten argv list when legacy flags are present, or
    ``None`` when the caller passed a real subcommand. Mutates nothing.
    """
    if not argv:
        return None
    # If the first token is a known subcommand, no rewrite is needed.
    if argv[0] in ("build",):
        return None
    # Otherwise look for legacy flags. We're not trying to be a perfect
    # CLI parser here; missing fields will fall through to argparse's
    # own error reporting on the rewritten argv.
    has_legacy = any(
        flag in argv for flag in ("--input-file", "--output-receipt")
    )
    if not has_legacy:
        return None

    args = list(argv)
    rewritten: List[str] = ["build"]
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--input-file" and i + 1 < len(args):
            rewritten.extend(["--input-events", args[i + 1]])
            i += 2
        elif token == "--output-receipt" and i + 1 < len(args):
            rewritten.extend(["--output-manifest", args[i + 1]])
            i += 2
        elif token == "--hour" and i + 1 < len(args):
            rewritten.extend(["--hour", args[i + 1]])
            i += 2
        else:
            # Unknown legacy token — pass through; the build parser
            # will reject it with a clear error.
            rewritten.append(token)
            i += 1
    return rewritten


# ---------------------------------------------------------------------------
# Build command
# ---------------------------------------------------------------------------


def build_command(
    *,
    hour: str,
    input_events: str | Path,
    output_manifest: str | Path,
    prev_hour_root: Optional[str] = None,
    sign_key: Optional[str | Path] = None,
    sign_kid: Optional[str] = None,
) -> dict[str, Any]:
    """Execute the ``build`` subcommand and return the written manifest.

    Returning the manifest dict (rather than just an exit code) lets
    test code assert on it without re-reading the file. The function
    is also reusable by an in-process driver if we ever decide to
    skip the subprocess boundary.

    ``prev_hour_root`` is the v1 reservation slot. When supplied it
    is emitted into the manifest under the same field name; when
    omitted the field is absent (consensus marker A5: additive,
    v1-compatible).

    ``sign_key`` + ``sign_kid`` enable production-side signing
    (Sprint-6 Tag-3). When both are supplied, the manifest written to
    disk carries the optional top-level ``signature`` slot populated
    by :func:`wat.identity.manifest_signing.sign_manifest`. The
    returned dict mirrors the on-disk shape. Partial configuration
    (only one of the two) is a hard error.
    """
    input_path = Path(input_events)
    output_path = Path(output_manifest)
    build_time = _utc_now_rfc3339()

    signing = _resolve_signing_config(sign_key=sign_key, sign_kid=sign_kid)

    raw_events = _read_events(input_path)

    if not raw_events:
        manifest = _build_empty_manifest(
            hour_slot=hour,
            build_time=build_time,
            prev_hour_root=prev_hour_root,
        )
    else:
        validated = _validate_events(raw_events)
        sorted_events = _sorted_by_time_then_event_id(validated)
        manifest = _build_manifest_object(
            hour_slot=hour,
            events=sorted_events,
            build_time=build_time,
            prev_hour_root=prev_hour_root,
        )

    if signing is not None:
        seed, kid = signing
        manifest = _sign_manifest_in_place(manifest, seed=seed, kid=kid)

    _write_manifest(manifest, output_path)
    return manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a Unix exit code (0 on success).

    Exit codes
    ----------

    0   manifest written successfully (including empty-hour case)
    2   validation error (malformed JSON, missing B1 field, etc.)
    64  argparse usage error (handled by argparse via SystemExit(2);
        kept here for symmetry with anchor_cli)
    """
    raw_argv: List[str] = list(argv) if argv is not None else sys.argv[1:]

    rewritten = _legacy_to_build_args(raw_argv)
    if rewritten is not None:
        raw_argv = rewritten

    parser = build_parser()
    args = parser.parse_args(raw_argv)

    if args.cmd == "build":
        try:
            build_command(
                hour=args.hour,
                input_events=args.input_events,
                output_manifest=args.output_manifest,
                prev_hour_root=getattr(args, "prev_hour_root", None),
                sign_key=getattr(args, "sign_key", None),
                sign_kid=getattr(args, "sign_kid", None),
            )
        except ValidationError as exc:
            print(f"validation error: {exc}", file=sys.stderr)
            return 2
        return 0

    # No subcommand and no legacy flags — print help and exit non-zero
    # so a misconfigured cron fails loudly.
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "MANIFEST_VERSION",
    "REQUIRED_FIELDS",
    "ValidationError",
    "build_command",
    "build_parser",
    "main",
]
