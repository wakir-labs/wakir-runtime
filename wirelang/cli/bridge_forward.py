# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bridge-Forward-Pipe publisher CLI — Sprint-10 Tag-6 substrate-closer.

This module is the Mira-side publisher for the Doppelbetrieb-Auftrags-
Mirror (spec: ``wirelang/specs/bridge-forward-pipe-v1.md``).

When Mira runs an engineering Auftrag against the Pre-Framework Tomás-
Spawn (``Agent(subagent_type=dev-engineering, prompt=...)``), this CLI
mirrors the prompt onto the canonical NATS subject

    wakir.<env>.agent.agent.task.assigned.<persona-slug>

so the Wakir-Runtime Tomás-Container can subscribe and execute the same
Auftrag as a Shadow-Spawn. Output-side wiring (engineering-output
envelope on the companion subject) is owned by the persona-engine
async-engine-wrapper (Selin OI-PEFR-3).

Hermetic-test surface (stdout/dry-run path)
-------------------------------------------

The CLI's ``--dry-run`` mode produces the canonical JCS envelope on
stdout WITHOUT importing nats-py and WITHOUT touching a NATS server.
This is the hermetic test surface in
``wirelang/tests/cli/test_bridge_forward.py``.

The live-NATS-publish path is exercised by the Mira-Hand-SSH-Smoke-
Test (Operator-Hand-Pfad, sandbox boundary per
``feedback_sandbox_host_trennung.md``).

Determinism
-----------

The JCS envelope is byte-deterministic across repeats for the same
inputs (``ts_utc`` is the only non-deterministic field; the CLI accepts
``--ts-utc`` for deterministic testing). The hermetic test injects a
fixed ``--ts-utc`` and asserts byte-identity against a golden envelope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Schema-id literal for the agent.task.assigned envelope. Single source
#: of truth — keep in sync with the spec §3.1.
AGENT_TASK_ASSIGNED_SCHEMA = "wakir.agent.task-assigned/1"

#: Subject template for the canonical agent.task.assigned forward-pipe.
#: Materialised by :func:`build_subject` to honour the
#: subject-mapping-v1.md regex contract.
SUBJECT_TEMPLATE = "wakir.{env}.agent.agent.task.assigned.{persona_slug}"

#: Size envelope (spec §3.3).
MAX_PROMPT_PAYLOAD_BYTES = 256 * 1024
MAX_AUFTRAG_ID_OCTETS = 64
MAX_METADATA_BYTES = 8 * 1024


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SizeLimitError(ValueError):
    """Payload exceeded the spec §3.3 size envelope."""


class EnvelopeFormatError(ValueError):
    """Envelope-construction failed an invariant check."""


# ---------------------------------------------------------------------------
# Envelope construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuftragEnvelope:
    """Bridge-Forward-Pipe envelope (spec §3.1)."""

    org_id: str
    persona_id: str
    auftrag_id: str
    ts_utc: str
    source: str
    prompt_payload: str
    metadata: dict = field(default_factory=dict)

    @property
    def prompt_sha256(self) -> str:
        h = hashlib.sha256(self.prompt_payload.encode("utf-8")).hexdigest()
        return f"sha256:{h}"

    def to_dict(self) -> dict:
        return {
            "schema": AGENT_TASK_ASSIGNED_SCHEMA,
            "event_kind": "agent.task.assigned",
            "org_id": self.org_id,
            "persona_id": self.persona_id,
            "auftrag_id": self.auftrag_id,
            "ts_utc": self.ts_utc,
            "source": self.source,
            "prompt_sha256": self.prompt_sha256,
            "prompt_payload": self.prompt_payload,
            "metadata": dict(self.metadata),
        }


def build_subject(env: str, persona_slug: str) -> str:
    """Build the canonical agent.task.assigned subject.

    Honours the subject-mapping-v1 regex
    ``^wakir\\.(dev|staging|prod)\\.[a-z][a-z0-9_-]*\\.[a-z][a-z0-9_.-]*(\\.[a-zA-Z0-9_.-]+)?$``.
    """
    import re

    if env not in ("dev", "staging", "prod"):
        raise EnvelopeFormatError(
            f"env must be one of dev/staging/prod, got {env!r}"
        )
    # Lowercase-strict, leading-letter-strict: matches the schema regex
    # ``[a-z][a-z0-9_-]*`` for the <sub_id> persona-slug slot.
    if not re.match(r"^[a-z][a-z0-9_-]*$", persona_slug):
        raise EnvelopeFormatError(
            f"persona_slug must match [a-z][a-z0-9_-]*, got {persona_slug!r}"
        )
    return SUBJECT_TEMPLATE.format(env=env, persona_slug=persona_slug)


def envelope_to_jcs_bytes(envelope: dict) -> bytes:
    """Render the envelope dict as JCS-canonical UTF-8 bytes.

    Uses ``json.dumps(sort_keys=True, separators=(",", ":"),
    ensure_ascii=False)`` — the same JCS-light convention used by
    ``marker_stack_emit.py`` (RFC 8785 strict-canonical not required;
    determinism-across-repeats is the floor).
    """
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def validate_envelope(envelope: AuftragEnvelope) -> None:
    """Apply the §3.3 size-envelope invariants. Raises SizeLimitError."""
    if len(envelope.prompt_payload.encode("utf-8")) > MAX_PROMPT_PAYLOAD_BYTES:
        raise SizeLimitError(
            f"prompt_payload exceeds {MAX_PROMPT_PAYLOAD_BYTES} bytes"
        )
    if len(envelope.auftrag_id.encode("utf-8")) > MAX_AUFTRAG_ID_OCTETS:
        raise SizeLimitError(
            f"auftrag_id exceeds {MAX_AUFTRAG_ID_OCTETS} octets"
        )
    meta_bytes = envelope_to_jcs_bytes(envelope.metadata)
    if len(meta_bytes) > MAX_METADATA_BYTES:
        raise SizeLimitError(
            f"metadata exceeds {MAX_METADATA_BYTES} bytes JCS-serialised"
        )


def _parse_metadata(kv_pairs: list[str]) -> dict:
    out: dict = {}
    for pair in kv_pairs or []:
        if "=" not in pair:
            raise EnvelopeFormatError(
                f"--metadata expects key=value, got {pair!r}"
            )
        k, _, v = pair.partition("=")
        out[k.strip()] = v
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wakir-bridge-forward",
        description=(
            "Mira-side Bridge-Forward-Pipe publisher. Mirrors a Tomás-"
            "Persona Auftrag onto the Doppelbetrieb-NATS-subject so the "
            "Wakir-Runtime Shadow-Spawn can subscribe and execute in "
            "parallel. Spec: wirelang/specs/bridge-forward-pipe-v1.md"
        ),
    )
    p.add_argument("--persona-slug", required=True, help="e.g. tomas")
    p.add_argument("--auftrag-id", required=True, help="round-trip key")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--prompt-file",
        help="path to UTF-8 file holding the Auftrag prompt",
    )
    grp.add_argument(
        "--prompt-stdin",
        action="store_true",
        help="read prompt from stdin",
    )
    p.add_argument("--env", default="dev", choices=("dev", "staging", "prod"))
    p.add_argument("--org-id", default="acme")
    p.add_argument("--source", default="mira-sandbox")
    p.add_argument(
        "--nats-url",
        default=os.environ.get("WAKIR_NATS_URL", "nats://wakir-nats:4222"),
    )
    p.add_argument(
        "--metadata",
        action="append",
        default=[],
        help="repeat for each key=value pair",
    )
    p.add_argument(
        "--ts-utc",
        help="RFC3339 UTC timestamp, default now (Z-suffix, sec-precision)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "render the JCS envelope to stdout, do not publish — hermetic "
            "test surface; does not import nats-py."
        ),
    )
    # Tag-41 Bug-42 — Adapter-B substrate. Defaults to ``core`` per
    # spec wirelang-spec-v0-2 §13.5 (Bridge-Forward-Pipe v1 binds
    # core). Operators MAY set ``--publish-mode jetstream`` to
    # match a JetStream-pull subscriber (spec §13.4 Adapter B).
    # The env-var ``WAKIR_NATS_PUBLISH_MODE`` is the default
    # surface if no CLI flag is passed.
    p.add_argument(
        "--publish-mode",
        choices=("core", "jetstream"),
        default=None,
        help=(
            "publish surface: 'core' (nc.publish) or 'jetstream' "
            "(js.publish). Defaults to env $WAKIR_NATS_PUBLISH_MODE "
            "or 'core'. See spec §13."
        ),
    )
    p.add_argument(
        "--jetstream-stream",
        default=os.environ.get("WAKIR_NATS_JETSTREAM_STREAM"),
        help=(
            "JetStream stream name (required when --publish-mode is "
            "'jetstream'). Defaults to env $WAKIR_NATS_JETSTREAM_STREAM."
        ),
    )
    return p


def _now_utc_rfc3339() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    # Load prompt.
    if args.prompt_stdin:
        prompt_payload = sys.stdin.read()
    else:
        try:
            with open(args.prompt_file, "r", encoding="utf-8") as fh:
                prompt_payload = fh.read()
        except OSError as exc:
            print(
                f"[wakir-bridge-forward] ERROR: cannot read prompt-file: {exc}",
                file=sys.stderr,
            )
            return 1

    # Build envelope.
    try:
        metadata = _parse_metadata(args.metadata)
    except EnvelopeFormatError as exc:
        print(f"[wakir-bridge-forward] ERROR: {exc}", file=sys.stderr)
        return 1

    ts_utc = args.ts_utc or _now_utc_rfc3339()
    envelope = AuftragEnvelope(
        org_id=args.org_id,
        persona_id=args.persona_slug,
        auftrag_id=args.auftrag_id,
        ts_utc=ts_utc,
        source=args.source,
        prompt_payload=prompt_payload,
        metadata=metadata,
    )

    try:
        validate_envelope(envelope)
    except SizeLimitError as exc:
        print(f"[wakir-bridge-forward] ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        subject = build_subject(args.env, args.persona_slug)
    except EnvelopeFormatError as exc:
        print(f"[wakir-bridge-forward] ERROR: {exc}", file=sys.stderr)
        return 1

    canonical = envelope_to_jcs_bytes(envelope.to_dict())

    # Tag-41 Bug-42 — resolve publish-mode early so dry-run also
    # records the operator declaration. Mirror the live-path
    # resolver below.
    from wirelang.persona_engine.publish_mode_contract import (
        resolve_publish_mode as _resolve_publish_mode_dry,
    )
    if args.publish_mode is not None:
        dry_publish_mode = args.publish_mode
    else:
        try:
            dry_publish_mode = _resolve_publish_mode_dry()
        except ValueError:
            # In dry-run mode, malformed env-var falls back to ``core``
            # without erroring — the operator is exercising the
            # envelope shape, not bringing up live publishes.
            dry_publish_mode = "core"

    # Dry-run = stdout + return. Hermetic-test surface.
    if args.dry_run:
        # Write as UTF-8 text — sys.stdout may be a StringIO in tests
        # (no .buffer attribute). The canonical bytes are already
        # UTF-8 by construction. The line ordering preserves the
        # Sprint-10 contract (line 0 = subject comment, line 1 =
        # canonical envelope) so existing tests stay valid. The
        # Tag-41 publish_mode declaration is appended as a trailer
        # comment so operators see the surface declaration without
        # disturbing the envelope's line position.
        sys.stdout.write(f"# subject: {subject}\n")
        sys.stdout.write(canonical.decode("utf-8"))
        sys.stdout.write("\n")
        sys.stdout.write(f"# publish_mode: {dry_publish_mode}\n")
        sys.stdout.flush()
        return 0

    # Tag-41 Bug-42 — resolve the publish-mode (CLI flag > env-var >
    # default ``core``). The mode determines whether we go through
    # the core ``nc.publish`` path or the JetStream ``js.publish``
    # path (Adapter B per spec §13.4).
    from wirelang.persona_engine.publish_mode_contract import (
        PUBLISH_MODE_CORE,
        PUBLISH_MODE_JETSTREAM,
        resolve_publish_mode,
    )
    if args.publish_mode is not None:
        publish_mode = args.publish_mode
    else:
        try:
            publish_mode = resolve_publish_mode()
        except ValueError as exc:
            print(
                f"[wakir-bridge-forward] ERROR: env-misconfig: {exc}",
                file=sys.stderr,
            )
            return 1
    if (
        publish_mode == PUBLISH_MODE_JETSTREAM
        and not args.jetstream_stream
    ):
        print(
            "[wakir-bridge-forward] ERROR: --publish-mode jetstream "
            "requires --jetstream-stream (or env "
            "$WAKIR_NATS_JETSTREAM_STREAM)",
            file=sys.stderr,
        )
        return 1

    # Live-publish path — lazy import per the marker_stack_emit
    # pattern so tests run without nats-py installed.
    try:
        import asyncio

        import nats  # type: ignore

        async def _publish() -> None:
            token = os.environ.get("WAKIR_NATS_TOKEN") or None
            nc = await nats.connect(args.nats_url, token=token)
            try:
                if publish_mode == PUBLISH_MODE_JETSTREAM:
                    js = nc.jetstream()
                    # js.publish raises on stream-not-found or
                    # subject-mismatch; let the outer except handle.
                    await js.publish(
                        subject,
                        canonical,
                        stream=args.jetstream_stream,
                    )
                else:
                    await nc.publish(subject, canonical)
                # Flush to ensure the publish ack reaches the server.
                await nc.flush(timeout=5.0)
            finally:
                await nc.drain()

        asyncio.run(_publish())
    except ImportError as exc:
        print(
            f"[wakir-bridge-forward] ERROR: nats-py not installed: {exc}",
            file=sys.stderr,
        )
        return 3
    except Exception as exc:  # pragma: no cover - network errors
        print(
            f"[wakir-bridge-forward] ERROR: nats publish: {exc!r}",
            file=sys.stderr,
        )
        return 3

    # Echo the canonical envelope to stdout for operator-pipe-able
    # audit-trail (Doppelbetrieb-Score-CLI consumes this shape).
    sys.stdout.write(f"# subject: {subject}\n")
    sys.stdout.write(canonical.decode("utf-8"))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


__all__ = [
    "AGENT_TASK_ASSIGNED_SCHEMA",
    "AuftragEnvelope",
    "EnvelopeFormatError",
    "SizeLimitError",
    "build_subject",
    "envelope_to_jcs_bytes",
    "main",
    "validate_envelope",
]


if __name__ == "__main__":
    sys.exit(main())
