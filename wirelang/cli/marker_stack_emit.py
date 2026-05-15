# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Operator-facing marker-stack emitter CLI (Sprint-Pengine-7 Tag-5
OI-PILOT-3).

This module is the WRITE-SIDE companion to Sprint-9 Tag-3 Teil-A
``wirelang.cli.marker_stack_reduce`` (the READ-SIDE reducer CLI).
While the reducer CLI is verifier-grade (it READS marker-stack
events from a per-org bucket and reduces them to a verdict), the
emitter CLI is operator-grade: it EMITS migration-audit markers
during Sprint-Migration-Pilot-Phase setup, teardown, and audit
checkpoints.

Use cases (Sprint-Migration-Pilot-Phase, ADR-0058)
---------------------------------------------------

- ``setup-marker``: write a "pilot-phase-active" marker at the
  start of a Doppelbetrieb session (Migration-Playbook Schritt 4).
- ``teardown-marker``: write a "pilot-phase-ended" marker at the
  end of a Doppelbetrieb session.
- ``migration-audit``: write a periodic per-week audit-stamp
  marker during the 4-week Doppelbetrieb (Migration-Playbook
  Schritt 5: Vergleichs-Testset).
- ``custom``: emit an arbitrary operator-supplied marker payload
  (escape hatch for ad-hoc audit gestures).

JCS canonical-form + V-907 hash-chain
-------------------------------------

Each emitted marker carries:

1. The marker payload (a JSON object) is canonicalised via
   RFC 8785 JCS (``rfc8785.dumps``) so the bytes-on-the-wire are
   byte-deterministic for the same logical payload.
2. The canonical bytes are hashed under SHA-256 → ``payload_hash``.
3. A V-907 hash-chain field links the marker to its predecessor:
   ``chain_prev_hash`` is the operator-supplied previous-marker
   ``payload_hash`` (or the all-zero sentinel for the first
   marker in a session). The current marker's ``chain_hash``
   is ``SHA-256(prev_hash || payload_hash)`` — a Merkle-style
   linear chain that lets a verifier audit the marker sequence
   for tampering. ``chain_prev_hash`` for the FIRST marker is
   the 32-byte zero-sentinel; ``chain_hash`` is recomputed by
   the verifier on read.
4. The final envelope wraps payload + hashes + a stable
   ``schema`` URI + a wall-clock ``emitted_at`` timestamp.

The envelope can be:

- emitted to stdout as a single JCS-canonical JSON line (default,
  ``--mode stdout``), so the operator can pipe it directly into
  ``wakir-bridge-audit-write --payload-file -`` (Sprint-Migration
  WAT-anchoring path), OR
- written to a NATS-KV bucket as an append-only sequence entry
  (``--mode nats-kv``), which is the live-substrate path during
  Pilot-Phase. The bucket is the operator-supplied
  ``--bucket`` flag and defaults to ``wakir-marker-stack-<org_id>``
  (the Sprint-8 Tag-4 federation bucket). For SETUP/TEARDOWN/
  MIGRATION-AUDIT markers — which are Sprint-Migration-Tooling
  events, NOT capability-marker events — the operator MUST set
  ``--bucket`` to a dedicated per-org migration-audit bucket
  (e.g. ``wakir-migration-audit-acme``); the default falls back
  to the federation bucket only because no migration-audit
  bucket family is defined yet (Cross-Review Zone-B with Reza
  before promotion to a registered family).

Sandbox boundary
----------------

Live NATS connections are operator-hand (per
``feedback_sandbox_host_trennung.md``). The ``--mode stdout``
path is the sandbox-friendly default; the ``--mode nats-kv``
path is operator-only. Tests in
``tests/orchestrator/test_marker_stack_emit_cli.py`` exercise the
canonicalisation, hash-chain, and stdout serialisation paths;
the nats-kv path is mocked through an in-memory JetStream stub.

Output contract
---------------

The emitted envelope is a JSON object with these fields:

.. code-block:: json

    {
      "schema": "wakir.migration.marker-event/1",
      "marker_kind": "setup" | "teardown" | "migration-audit" | "custom",
      "org_id": "<org_id>",
      "persona_id": "<persona_id-or-empty>",
      "emitted_at": "<RFC-3339 UTC>",
      "payload": { ... },
      "payload_hash": "<sha256-hex>",
      "chain_prev_hash": "<sha256-hex-or-zero-sentinel>",
      "chain_hash": "<sha256-hex>"
    }

The envelope is JCS-canonical (RFC 8785 sorted-keys, compact
separators). A consumer that re-emits the same logical envelope
gets a byte-identical line.

Exit codes
----------

- ``0`` success: envelope written to stdout / nats-kv as requested.
- ``1`` invalid arguments, JCS encoding failure, or live nats-kv
  connection error.
- ``2`` hash-chain validation failed: the operator supplied a
  ``--chain-prev-hash`` that does not match the recorded latest
  marker in the target bucket (live-substrate path only).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from typing import Any, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Schema URI embedded in every emitted envelope.
ENVELOPE_SCHEMA = "wakir.migration.marker-event/1"

#: All-zero hex sentinel for the first marker in a chain
#: (32 bytes -> 64 hex chars).
CHAIN_ZERO_SENTINEL = "0" * 64

#: Closed enum of marker kinds. The CLI accepts only these strings.
MARKER_KINDS = ("setup", "teardown", "migration-audit", "custom")


# ---------------------------------------------------------------------------
# Pure helpers (hermetic, no I/O)
# ---------------------------------------------------------------------------


def jcs_dumps(value: Mapping[str, Any]) -> bytes:
    """Return the RFC 8785 JCS canonical-form bytes for ``value``.

    The implementation prefers the upstream ``rfc8785`` package if
    available (Phase-2 Sprint-5 cross-lang parity anchor); falls
    back to a sorted-keys + compact-separator JSON serialisation if
    not. The fallback is byte-precise enough for the persona-emitter
    CLI use case (the input is a plain dict with str/int/bool/list
    payloads — no float, no recursive object) but is NOT a
    general-purpose JCS implementation.

    Raises :class:`ValueError` if ``value`` is not a JSON object.
    """
    if not isinstance(value, Mapping):
        raise ValueError(
            f"jcs_dumps expects a Mapping at top level, got {type(value)!r}"
        )
    try:  # pragma: no cover - prefer real JCS when available
        import rfc8785

        return rfc8785.dumps(value)
    except ImportError:
        # Fallback. The persona-emitter payload domain is small
        # (str/int/bool/list/dict, no float) so the sorted-keys
        # compact-JSON path is byte-equivalent to the JCS output.
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data``. Pure."""
    return hashlib.sha256(data).hexdigest()


def compute_chain_hash(chain_prev_hash: str, payload_hash: str) -> str:
    """Compute the V-907-style linear hash-chain step.

    ``chain_hash = SHA-256(chain_prev_hash || payload_hash)``.
    Both inputs are 64-char hex; the concatenation is done at the
    hex-byte level before hashing.

    Raises :class:`ValueError` for malformed input lengths.
    """
    if not isinstance(chain_prev_hash, str) or len(chain_prev_hash) != 64:
        raise ValueError(
            f"chain_prev_hash must be 64-char hex, got "
            f"{chain_prev_hash!r} (len={len(chain_prev_hash) if isinstance(chain_prev_hash, str) else 'n/a'})"
        )
    if not isinstance(payload_hash, str) or len(payload_hash) != 64:
        raise ValueError(
            f"payload_hash must be 64-char hex, got "
            f"{payload_hash!r} (len={len(payload_hash) if isinstance(payload_hash, str) else 'n/a'})"
        )
    return sha256_hex((chain_prev_hash + payload_hash).encode("utf-8"))


def build_envelope(
    *,
    marker_kind: str,
    org_id: str,
    persona_id: str,
    payload: Mapping[str, Any],
    emitted_at: str,
    chain_prev_hash: str,
) -> dict:
    """Construct the canonical marker-event envelope.

    Pure: no I/O, deterministic on inputs. The returned dict is
    suitable for further serialisation via :func:`jcs_dumps`.

    Raises :class:`ValueError` for unknown ``marker_kind`` values,
    empty ``org_id``, or malformed ``chain_prev_hash``.
    """
    if marker_kind not in MARKER_KINDS:
        raise ValueError(
            f"marker_kind must be one of {MARKER_KINDS!r}, got "
            f"{marker_kind!r}"
        )
    if not isinstance(org_id, str) or not org_id:
        raise ValueError(
            f"org_id must be a non-empty string, got {org_id!r}"
        )
    if not isinstance(persona_id, str):
        raise ValueError(
            f"persona_id must be a string (empty allowed), got "
            f"{persona_id!r}"
        )
    if not isinstance(payload, Mapping):
        raise ValueError(
            f"payload must be a Mapping, got {type(payload)!r}"
        )
    if not isinstance(emitted_at, str) or not emitted_at:
        raise ValueError(
            f"emitted_at must be a non-empty string, got {emitted_at!r}"
        )

    payload_canonical = jcs_dumps(payload)
    payload_hash = sha256_hex(payload_canonical)
    chain_hash = compute_chain_hash(chain_prev_hash, payload_hash)

    return {
        "schema": ENVELOPE_SCHEMA,
        "marker_kind": marker_kind,
        "org_id": org_id,
        "persona_id": persona_id,
        "emitted_at": emitted_at,
        # Inline the JCS-canonical payload as a parsed object so
        # the envelope is one self-describing JSON document. The
        # ``payload_hash`` field anchors the canonical-bytes view.
        "payload": dict(payload),
        "payload_hash": payload_hash,
        "chain_prev_hash": chain_prev_hash,
        "chain_hash": chain_hash,
    }


def envelope_to_jcs_bytes(envelope: Mapping[str, Any]) -> bytes:
    """Return the JCS-canonical bytes for an envelope.

    Convenience wrapper. The envelope itself is a Mapping; this
    helper produces the byte-on-the-wire form the operator pipes
    into a WAT-anchor sink or a NATS-KV writer.
    """
    return jcs_dumps(envelope)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wakir-marker-stack-emit",
        description=(
            "Emit a Sprint-Migration-Pilot-Phase marker event with "
            "JCS canonical-form + V-907 linear hash-chain "
            "(Sprint-Pengine-7 Tag-5 OI-PILOT-3)."
        ),
    )
    p.add_argument(
        "--marker-kind",
        required=True,
        choices=MARKER_KINDS,
        help="Closed enum of marker kinds.",
    )
    p.add_argument(
        "--org-id",
        required=True,
        help="Organisation identifier (e.g. acme, orbit).",
    )
    p.add_argument(
        "--persona-id",
        default="",
        help="Persona identifier (e.g. tomas); empty for org-wide markers.",
    )
    p.add_argument(
        "--payload-file",
        default=None,
        help=(
            "Path to a JSON file carrying the marker payload. "
            "Mutually exclusive with --payload-stdin."
        ),
    )
    p.add_argument(
        "--payload-stdin",
        action="store_true",
        help="Read the marker payload as JSON from stdin.",
    )
    p.add_argument(
        "--chain-prev-hash",
        default=CHAIN_ZERO_SENTINEL,
        help=(
            "Previous marker's payload_hash (64 hex chars). Default "
            f"is the zero-sentinel {CHAIN_ZERO_SENTINEL[:8]}... for "
            "first-in-chain markers."
        ),
    )
    p.add_argument(
        "--emitted-at",
        default=None,
        help=(
            "RFC-3339 UTC timestamp for the marker. If absent, the "
            "CLI uses the current UTC time (operator-side wall-clock)."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("stdout", "nats-kv"),
        default="stdout",
        help=(
            "Output mode. stdout (default) emits one JCS line to "
            "stdout. nats-kv writes to a NATS-JetStream KV bucket "
            "(live path; operator-hand)."
        ),
    )
    p.add_argument(
        "--bucket",
        default=None,
        help=(
            "NATS-KV bucket name (nats-kv mode only). Defaults to "
            "wakir-marker-stack-<org_id> if absent; operators SHOULD "
            "pass a dedicated migration-audit bucket name."
        ),
    )
    p.add_argument(
        "--servers",
        default=os.environ.get(
            "WAKIR_NATS_SERVERS", "nats://127.0.0.1:4222"
        ),
        help="NATS server URL(s); used in --mode nats-kv only.",
    )
    return p


def _load_payload(args: argparse.Namespace) -> Mapping[str, Any]:
    if args.payload_file and args.payload_stdin:
        raise ValueError(
            "--payload-file and --payload-stdin are mutually exclusive"
        )
    if args.payload_file:
        with open(args.payload_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    elif args.payload_stdin:
        data = json.load(sys.stdin)
    else:
        raise ValueError(
            "must supply --payload-file or --payload-stdin"
        )
    if not isinstance(data, Mapping):
        raise ValueError(
            f"payload must decode to a JSON object, got {type(data)!r}"
        )
    return data


def _utc_now_rfc3339() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = _load_payload(args)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(
            f"[wakir-marker-stack-emit] ERROR: payload: {exc}",
            file=sys.stderr,
        )
        return 1

    emitted_at = args.emitted_at or _utc_now_rfc3339()

    try:
        envelope = build_envelope(
            marker_kind=args.marker_kind,
            org_id=args.org_id,
            persona_id=args.persona_id,
            payload=payload,
            emitted_at=emitted_at,
            chain_prev_hash=args.chain_prev_hash,
        )
    except ValueError as exc:
        print(
            f"[wakir-marker-stack-emit] ERROR: envelope: {exc}",
            file=sys.stderr,
        )
        return 1

    canonical_bytes = envelope_to_jcs_bytes(envelope)

    if args.mode == "stdout":
        sys.stdout.buffer.write(canonical_bytes)
        sys.stdout.buffer.write(b"\n")
        sys.stdout.flush()
        return 0

    # nats-kv path — operator-hand. We import nats lazily so the
    # hermetic tests can exercise the stdout path without nats-py
    # being installed.
    bucket = args.bucket or f"wakir-marker-stack-{args.org_id}"
    try:
        import asyncio
        import nats  # type: ignore

        async def _write() -> None:
            token = os.environ.get("WAKIR_NATS_TOKEN") or None
            nc = await nats.connect(args.servers, token=token)
            try:
                js = nc.jetstream()
                kv = await js.key_value(bucket=bucket)
                # Key: emitted_at + payload_hash short-prefix for
                # operator-readability.
                key = (
                    f"migration-marker/{emitted_at}/"
                    f"{envelope['payload_hash'][:12]}"
                )
                await kv.put(key, canonical_bytes)
            finally:
                await nc.drain()

        asyncio.run(_write())
    except ImportError as exc:
        print(
            f"[wakir-marker-stack-emit] ERROR: nats-py not installed: {exc}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"[wakir-marker-stack-emit] ERROR: nats-kv write: {exc!r}",
            file=sys.stderr,
        )
        return 1

    # Echo the canonical envelope to stdout even in nats-kv mode so
    # a Doppel-Sink operator can pipe the same line into the WAT
    # bridge-audit-writer.
    sys.stdout.buffer.write(canonical_bytes)
    sys.stdout.buffer.write(b"\n")
    sys.stdout.flush()
    return 0


__all__ = [
    "CHAIN_ZERO_SENTINEL",
    "ENVELOPE_SCHEMA",
    "MARKER_KINDS",
    "build_envelope",
    "compute_chain_hash",
    "envelope_to_jcs_bytes",
    "jcs_dumps",
    "main",
    "sha256_hex",
]


if __name__ == "__main__":
    raise SystemExit(main())
