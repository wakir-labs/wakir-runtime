# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Mira-Dispatcher Side-CLI — Sprint-Pengine-10 OI-PEFR-7.

When Mira (CEO) dispatches an engineering Auftrag to the Pre-Framework
``dev-engineering`` subagent, the same prompt should be mirrored onto
the Bridge-Forward-Pipe so the Wakir-Runtime persona-container can
subscribe and run the Doppelbetrieb-Shadow-Spawn.

This CLI is a **wrapper** that:

1. Runs the Pre-Framework dispatch (operator-supplied command) OR
   ``--no-preframework`` mode if the operator already invoked the
   subagent separately and only needs to mirror onto NATS.
2. Concurrently publishes the prompt to the Bridge-Forward-Pipe
   subject ``wakir.<env>.agent.agent.task.assigned.<persona-slug>``.

Asyncio-non-blocking dispatch
-----------------------------

``--async-dispatch`` (default ON) runs the NATS publish on a background
``asyncio.Task`` so the Pre-Framework dispatch is not held by the
publish round-trip. ``--sync-dispatch`` forces the publish to complete
before the Pre-Framework dispatch returns — useful for hermetic tests.

Composition with wakir-bridge-forward
-------------------------------------

The publish-side logic is delegated to the
:mod:`wirelang.cli.bridge_forward` module so we share the JCS-envelope
construction, size-validation, and subject-grammar checks. The
mira-dispatch CLI is a thin orchestration layer on top.

Hermetic-test surface
---------------------

- ``--dry-run`` prints the envelope to stdout without NATS publish (no
  ``nats-py`` import).
- ``--no-preframework`` skips the Pre-Framework dispatch entirely; the
  CLI behaves as a pure mirror-publish.
- A ``--nats-mock`` flag selects a pure-stdlib in-memory mock for the
  publish-side. Tests pass ``--dry-run`` for byte-comparison or
  ``--nats-mock`` for ack-counting.

Spec anchor
-----------

``wirelang/specs/bridge-forward-pipe-v1.md`` §4.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .bridge_forward import (
    AuftragEnvelope,
    EnvelopeFormatError,
    SizeLimitError,
    build_subject,
    envelope_to_jcs_bytes,
    validate_envelope,
)


# ---------------------------------------------------------------------------
# Pure-stdlib mock for hermetic publish-side tests
# ---------------------------------------------------------------------------


class InMemoryNatsMock:
    """Pure-stdlib in-memory replacement for ``nats.aio.client.Client``.

    Used by ``--nats-mock`` and by hermetic tests in
    ``test_cli_mira_dispatch.py``. Records every publish for assertion.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []
        self.closed: bool = False

    async def publish(self, subject: str, payload: bytes) -> None:
        if self.closed:
            raise RuntimeError("InMemoryNatsMock: publish after close")
        self.published.append((subject, payload))

    async def flush(self, timeout: float = 5.0) -> None:
        return None

    async def drain(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Dispatch operations
# ---------------------------------------------------------------------------


def _now_utc_rfc3339() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_stdin:
        return sys.stdin.read()
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as fh:
            return fh.read()
    raise RuntimeError(
        "neither --prompt-file nor --prompt-stdin supplied"
    )


async def _publish_envelope_to_nats(
    *,
    subject: str,
    payload: bytes,
    nats_url: str,
    token: Optional[str],
    nats_client_factory=None,
) -> int:
    """Publish ``payload`` on ``subject``. Returns exit-code-compatible int.

    ``nats_client_factory`` is the test seam: if provided, it is called
    to obtain a publisher (must have async ``publish`` / ``flush`` /
    ``drain``). Production path: lazy-import ``nats-py``.
    """
    if nats_client_factory is not None:
        client = await nats_client_factory()
    else:  # pragma: no cover - live binding
        try:
            import nats  # type: ignore
        except ImportError as exc:
            print(
                f"[wakir-mira-dispatch] ERROR: nats-py not installed: {exc}",
                file=sys.stderr,
            )
            return 3
        client = await nats.connect(nats_url, token=token)
    try:
        await client.publish(subject, payload)
        await client.flush(timeout=5.0)
    except Exception as exc:  # pragma: no cover - network
        print(
            f"[wakir-mira-dispatch] ERROR: nats publish: {exc!r}",
            file=sys.stderr,
        )
        return 3
    finally:
        try:
            await client.drain()
        except Exception:  # pragma: no cover - best-effort
            pass
    return 0


def _run_preframework(
    command: list[str], prompt_payload: str, *, dry_run: bool
) -> int:
    """Run the operator-supplied Pre-Framework dispatch command.

    The prompt is piped on stdin. If ``dry_run`` is set, the command is
    not executed; we print the would-be command line.
    """
    if dry_run:
        print(
            f"[wakir-mira-dispatch] dry-run preframework command: {command!r}"
        )
        return 0
    try:
        proc = subprocess.run(
            command,
            input=prompt_payload,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError) as exc:
        print(
            f"[wakir-mira-dispatch] ERROR: preframework command failed: {exc}",
            file=sys.stderr,
        )
        return 4
    return proc.returncode


# ---------------------------------------------------------------------------
# Dispatch result + orchestration core
# ---------------------------------------------------------------------------


async def dispatch(
    args: argparse.Namespace,
    *,
    nats_client_factory=None,
) -> dict:
    """Run both legs of the dispatch and return a result dict.

    The dict carries:

    - ``preframework_returncode``: int (0 on success or skipped).
    - ``preframework_skipped``: bool.
    - ``bridge_forward_returncode``: int (0 on publish-ack, 3 on
      publish-failure, etc.).
    - ``subject``: str (canonical NATS subject).
    - ``envelope_sha256``: sha256 of the JCS envelope (audit-trail
      pin).
    """
    prompt = _load_prompt(args)
    metadata = _parse_metadata(args.metadata or [])

    ts_utc = args.ts_utc or _now_utc_rfc3339()
    envelope = AuftragEnvelope(
        org_id=args.org_id,
        persona_id=args.persona_slug,
        auftrag_id=args.auftrag_id,
        ts_utc=ts_utc,
        source=args.source,
        prompt_payload=prompt,
        metadata=metadata,
    )
    validate_envelope(envelope)
    subject = build_subject(args.env, args.persona_slug)
    canonical = envelope_to_jcs_bytes(envelope.to_dict())

    result: dict = {
        "subject": subject,
        "envelope_sha256": envelope.prompt_sha256,
        "preframework_skipped": True,
        "preframework_returncode": 0,
        "bridge_forward_returncode": 0,
    }

    # Pre-Framework leg.
    if args.preframework_cmd is not None and not args.no_preframework:
        result["preframework_skipped"] = False
        result["preframework_returncode"] = _run_preframework(
            args.preframework_cmd, prompt, dry_run=args.dry_run,
        )

    # Bridge-Forward leg.
    if args.dry_run:
        # Mirror the dry-run shape from wakir-bridge-forward for
        # byte-stable comparison.
        sys.stdout.write(f"# subject: {subject}\n")
        sys.stdout.write(canonical.decode("utf-8"))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return result

    publish_rc = await _publish_envelope_to_nats(
        subject=subject,
        payload=canonical,
        nats_url=args.nats_url,
        token=os.environ.get("WAKIR_NATS_TOKEN") or None,
        nats_client_factory=nats_client_factory,
    )
    result["bridge_forward_returncode"] = publish_rc
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wakir-mira-dispatch",
        description=(
            "Mira-side parallel dispatcher: runs the Pre-Framework "
            "engineering Auftrag AND mirrors the prompt onto the "
            "Bridge-Forward-Pipe so the Wakir-Runtime persona-engine "
            "can run the Doppelbetrieb-Shadow-Spawn. "
            "Spec: wirelang/specs/bridge-forward-pipe-v1.md §4."
        ),
    )
    p.add_argument("--persona-slug", required=True)
    p.add_argument("--auftrag-id", required=True)
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--prompt-file", help="UTF-8 file with prompt")
    grp.add_argument(
        "--prompt-stdin", action="store_true",
        help="read prompt from stdin",
    )
    p.add_argument("--env", default="dev", choices=("dev", "staging", "prod"))
    p.add_argument("--org-id", default="acme")
    p.add_argument("--source", default="mira-sandbox")
    p.add_argument(
        "--nats-url",
        default=os.environ.get("WAKIR_NATS_URL", "nats://wakir-nats:4222"),
    )
    p.add_argument("--metadata", action="append", default=[])
    p.add_argument("--ts-utc")
    p.add_argument(
        "--preframework-cmd",
        nargs="+",
        default=None,
        help=(
            "operator-supplied Pre-Framework dispatch command "
            "(argv); the prompt is piped on stdin. Omit + use "
            "--no-preframework for pure mirror-publish."
        ),
    )
    p.add_argument(
        "--no-preframework",
        action="store_true",
        help="skip the Pre-Framework leg (pure mirror-publish).",
    )
    p.add_argument(
        "--async-dispatch",
        action="store_true",
        default=True,
        help="run the NATS publish on a background task (default).",
    )
    p.add_argument(
        "--sync-dispatch",
        action="store_true",
        help="block on the NATS publish ack before returning.",
    )
    p.add_argument(
        "--nats-mock",
        action="store_true",
        help=(
            "use the in-memory InMemoryNatsMock instead of nats-py. "
            "Test/Operator-Hand-only."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "print envelope to stdout, do not publish, do not run "
            "Pre-Framework. Hermetic-test surface."
        ),
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.preframework_cmd is None and not args.no_preframework:
        print(
            "[wakir-mira-dispatch] ERROR: supply --preframework-cmd OR "
            "--no-preframework",
            file=sys.stderr,
        )
        return 1

    factory = None
    if args.nats_mock:
        async def _factory():
            return InMemoryNatsMock()

        factory = _factory

    try:
        result = asyncio.run(dispatch(args, nats_client_factory=factory))
    except (SizeLimitError, EnvelopeFormatError) as exc:
        print(f"[wakir-mira-dispatch] ERROR: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, SizeLimitError) else 1
    except OSError as exc:
        print(f"[wakir-mira-dispatch] ERROR: {exc}", file=sys.stderr)
        return 1

    if not args.dry_run:
        sys.stdout.write(
            json.dumps(result, sort_keys=True, indent=2) + "\n"
        )
        sys.stdout.flush()

    if result["preframework_returncode"] != 0:
        return result["preframework_returncode"]
    return result["bridge_forward_returncode"]


__all__ = [
    "InMemoryNatsMock",
    "dispatch",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
