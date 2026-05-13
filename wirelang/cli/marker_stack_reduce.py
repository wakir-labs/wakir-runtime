# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Operator-facing marker-stack reducer CLI (Phase-2 Sprint-9 Tag-3 Teil A).

Sprint-8 Tag-3 shipped the in-memory marker-stack reducer
(``wirelang.federation.marker_composition.reduce_marker_stack``);
Sprint-8 Tag-4 shipped the durable per-org marker-stack KV backend
(``wirelang.federation.marker_stack_kv.NatsKvMarkerStackBackend``).
Together they form the API surface a verifier or audit-emitter
uses to re-constitute and reduce the marker stack for one
capability-token-id.

This module is the **operator-facing CLI** wrapping that surface.
It exposes one entry-point — ``wakir-marker-stack-reduce`` — which:

1. Connects to an operator-supplied NATS-JetStream cluster
   (live path) OR receives an injected backend (test path).
2. Resolves the per-org marker-stack bucket via
   :func:`wirelang.federation.marker_stack_kv.bucket_name_for_org`.
3. Reconstitutes the :class:`MarkerStack` for the requested
   ``--capability-token`` and reduces it to a
   :class:`CompositionVerdict`.
4. Emits one of two output modes (selected by ``--format``):

   - ``pretty`` (default): a human-readable rendering with a
     symbol per marker-kind (R / U / RI / CO / BR), chronological
     ordering by ``event_at``, and a final-verdict block.
   - ``json``: a stable JSON document for pipeline consumption.

The CLI is hermetic by construction: the live NATS connection
factory and the marker-stack backend factory are swappable
(constructor-injection on :class:`OperatorRunner`). Tests inject
mock backends; the live-path is operator-hand by sandbox-boundary
policy (Mira-Sandbox vs. Host-Operations Trennung — claude-dev
cannot speak to the host's nats-py runtime).

Surface
-------

- :func:`main(argv)` — the CLI entry-point. Returns an integer
  exit code suitable for ``sys.exit``.
- :class:`OperatorRunner` — the testable orchestrator. Constructor
  accepts:

  - ``open_backend_async``: ``async (servers, token, org_id) ->
    NatsKvMarkerStackBackend``. Defaults to a live nats-py wire-up
    factory that is **never invoked in tests**.
  - ``stdout`` / ``stderr``: writeable streams (default
    :data:`sys.stdout` / :data:`sys.stderr`).

- :func:`pretty_print_verdict(verdict, *, token_id)` — pure
  formatter. Returns the multi-line pretty-print string. No I/O.
- :func:`verdict_to_json(verdict, *, token_id, org_id)` — pure
  serialiser. Returns the JSON string with stable ordering.

Marker-symbol legend
--------------------

============== ===========
event_kind     symbol
============== ===========
revoke         R
unrevoke       U
re_issuance    RI
caveat_override CO
bridge_revoked BR
============== ===========

The legend is exposed as the module-level :data:`MARKER_SYMBOLS`
mapping; consumers that need to render audit traces outside the
CLI can import the mapping directly.

Pretty-print format
-------------------

Stable across Tag-3+. A consumer that pipes the pretty output
into a downstream tool can rely on the line-shape and ordering.
Format example::

    capability-token: cap-token-42
    org: orbit
    final-verdict:
      state:               REVOKED
      effective:           REVOKED
      bridge_blocked:      false
      revocation_reason:   compromise
      revoked_at:          2026-05-13T08:00:00+00:00
      new_token_id:        (none)
      narrowed_caveat_set: (none)
    audit-trace (3 markers, chronological):
      [001] 2026-05-13T07:00:00+00:00  R   revoke               transition:active->revoked
      [002] 2026-05-13T07:30:00+00:00  U   unrevoke             transition:revoked->active
      [003] 2026-05-13T08:00:00+00:00  R   revoke               transition:active->revoked
    wat-anchor-chain (3):
      [001] (none)
      [002] manifest-7
      [003] (none)

Empty stack
-----------

An empty stack reduces to ``ACTIVE``/``ACTIVE`` with an empty
audit-trace; the CLI renders it deterministically without an
audit-trace block::

    capability-token: cap-token-42
    org: orbit
    final-verdict:
      state:               ACTIVE
      effective:           ACTIVE
      bridge_blocked:      false
      revocation_reason:   (none)
      revoked_at:          (none)
      new_token_id:        (none)
      narrowed_caveat_set: (none)
    audit-trace (0 markers, chronological):
      (no markers)
    wat-anchor-chain (0):
      (no anchors)

Token not found
---------------

If :meth:`NatsKvMarkerStackBackend.get_marker_stack` returns
``None`` (no events logged for this token-id), the CLI emits a
diagnostic line on stderr and returns exit code 3. In JSON mode
the body is ``{"capability_token": ..., "org": ..., "found":
false}``.

Sandbox-boundary
----------------

The live NATS connection factory uses ``nats.aio.client.NATSClient``
+ ``nats.js.JetStreamContext``; importing this module does NOT
import nats-py (the live factory is gated behind a runtime
import). Tests do not exercise the live factory at all.

ADR-0050 Tool-Surface-Stempel: this module was authored using
Read, Edit, Write, Bash. No Agent-Tool, no WebFetch.
ADR-0049 Pre-Box-Worktree: ``/tmp/reza-sprint-9-tag-3-operator-
cli-replicator-runtime`` with ``-runtime`` suffix from the
Tag-2-Branch tip ``98b3556``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Sequence, TextIO

from wirelang.federation.marker_composition import (
    CompositionVerdict,
    reduce_marker_stack,
)
from wirelang.federation.marker_stack_kv import (
    NatsKvMarkerStackBackend,
    bucket_name_for_org,
)


__all__ = [
    "MARKER_SYMBOLS",
    "OperatorRunner",
    "main",
    "pretty_print_verdict",
    "verdict_to_json",
]


# ---------------------------------------------------------------------------
# Marker symbol mapping
# ---------------------------------------------------------------------------

# Stable mapping from marker-composition event_kind to a short
# operator-facing symbol. Keys mirror the labels emitted by
# :class:`wirelang.federation.marker_composition.AuditTraceEntry`
# (the ``event_kind`` field). The CLI renders this symbol in the
# audit-trace block; downstream consumers that build their own
# render pass can import this mapping directly.
MARKER_SYMBOLS: dict = {
    "revoke": "R",
    "unrevoke": "U",
    "re_issuance": "RI",
    "caveat_override": "CO",
    "bridge_revoked": "BR",
}


# ---------------------------------------------------------------------------
# Pure formatters
# ---------------------------------------------------------------------------


def _fmt_optional(value: Any) -> str:
    """Render ``None`` as the literal ``"(none)"`` placeholder.

    Used by both pretty and JSON paths so the pretty output is
    stable; in JSON mode we surface real ``None`` values, not
    ``"(none)"`` strings (see :func:`verdict_to_json`).
    """
    if value is None:
        return "(none)"
    return str(value)


def _fmt_caveat_set(value: Any) -> str:
    """Render a narrowed-caveat-set tuple as a compact one-liner.

    Returns ``"(none)"`` for ``None``. Otherwise renders the tuple
    via ``repr`` (the canonical caveat-set shape is a deterministic
    tuple-of-tuples; ``repr`` gives a stable, parseable rendering).
    """
    if value is None:
        return "(none)"
    return repr(value)


def _fmt_isoformat(value: Optional[datetime]) -> str:
    """Render a timezone-aware datetime via ``isoformat()`` or
    ``"(none)"`` for ``None``.
    """
    if value is None:
        return "(none)"
    return value.isoformat()


def pretty_print_verdict(
    verdict: CompositionVerdict,
    *,
    token_id: str,
    org_id: str,
) -> str:
    """Render a :class:`CompositionVerdict` as the operator-facing
    pretty-print text block.

    The format is stable across Tag-3+; pretty-print-format-
    stability is enforced by hermetic tests in
    :mod:`tests.test_cli_marker_stack_reduce`.

    The audit trace is rendered in event-time order (the order
    the reducer emits). The trace is ALWAYS sorted by the reducer
    on ``(event_at, tie_break)`` ascending; the CLI does NOT
    re-sort.

    Args:
        verdict: the reducer's :class:`CompositionVerdict`.
        token_id: the capability-token-id this verdict belongs to;
            surfaced as the first header line.
        org_id: the per-org bucket id the stack was sourced from;
            surfaced as the second header line.

    Returns:
        A multi-line string ending with a newline.
    """
    if not isinstance(verdict, CompositionVerdict):
        raise TypeError(
            f"verdict must be CompositionVerdict; got "
            f"type={type(verdict).__name__}"
        )
    if not isinstance(token_id, str) or not token_id:
        raise ValueError("token_id must be a non-empty string")
    if not isinstance(org_id, str) or not org_id:
        raise ValueError("org_id must be a non-empty string")

    lines = []
    lines.append(f"capability-token: {token_id}")
    lines.append(f"org: {org_id}")
    lines.append("final-verdict:")
    lines.append(f"  state:               {verdict.state.value}")
    lines.append(f"  effective:           {verdict.effective.value}")
    lines.append(
        f"  bridge_blocked:      "
        f"{'true' if verdict.bridge_blocked else 'false'}"
    )
    lines.append(
        f"  revocation_reason:   "
        f"{_fmt_optional(verdict.revocation_reason)}"
    )
    lines.append(
        f"  revoked_at:          {_fmt_isoformat(verdict.revoked_at)}"
    )
    lines.append(
        f"  new_token_id:        {_fmt_optional(verdict.new_token_id)}"
    )
    lines.append(
        f"  narrowed_caveat_set: "
        f"{_fmt_caveat_set(verdict.narrowed_caveat_set)}"
    )

    trace = verdict.audit_trace
    lines.append(
        f"audit-trace ({len(trace)} markers, chronological):"
    )
    if not trace:
        lines.append("  (no markers)")
    else:
        for i, entry in enumerate(trace, start=1):
            symbol = MARKER_SYMBOLS.get(entry.event_kind, "??")
            lines.append(
                f"  [{i:03d}] {entry.event_at.isoformat()}  "
                f"{symbol:<3} {entry.event_kind:<20} {entry.outcome}"
            )

    anchors = verdict.wat_anchor_chain
    lines.append(f"wat-anchor-chain ({len(anchors)}):")
    if not anchors:
        lines.append("  (no anchors)")
    else:
        for i, anchor in enumerate(anchors, start=1):
            lines.append(f"  [{i:03d}] {_fmt_optional(anchor)}")

    return "\n".join(lines) + "\n"


def verdict_to_json(
    verdict: CompositionVerdict,
    *,
    token_id: str,
    org_id: str,
) -> str:
    """Render a :class:`CompositionVerdict` as a stable JSON string.

    The shape is stable across Tag-3+; JSON-schema-stability is
    enforced by hermetic tests in
    :mod:`tests.test_cli_marker_stack_reduce`.

    Top-level shape::

        {
          "capability_token": "<token-id>",
          "org": "<org-id>",
          "found": true,
          "verdict": {
            "state": "<CompositionState>",
            "effective": "<EffectiveVerdict>",
            "bridge_blocked": <bool>,
            "revocation_reason": <str or null>,
            "revoked_at": <isoformat or null>,
            "new_token_id": <str or null>,
            "narrowed_caveat_set": <serialised-tuple or null>,
            "audit_trace": [
              {
                "event_at": "<isoformat>",
                "tie_break": <int>,
                "event_kind": "<kind>",
                "symbol": "<R/U/RI/CO/BR>",
                "outcome": "<outcome>",
                "wat_anchor_manifest_id": <str or null>
              }, ...
            ],
            "wat_anchor_chain": [<str or null>, ...]
          }
        }

    Returns:
        A JSON string with ``sort_keys=True`` and a stable compact
        separator pair.
    """
    if not isinstance(verdict, CompositionVerdict):
        raise TypeError(
            f"verdict must be CompositionVerdict; got "
            f"type={type(verdict).__name__}"
        )
    payload = {
        "capability_token": token_id,
        "org": org_id,
        "found": True,
        "verdict": {
            "state": verdict.state.value,
            "effective": verdict.effective.value,
            "bridge_blocked": bool(verdict.bridge_blocked),
            "revocation_reason": verdict.revocation_reason,
            "revoked_at": (
                verdict.revoked_at.isoformat()
                if verdict.revoked_at is not None
                else None
            ),
            "new_token_id": verdict.new_token_id,
            "narrowed_caveat_set": (
                _serialise_caveat_set(verdict.narrowed_caveat_set)
                if verdict.narrowed_caveat_set is not None
                else None
            ),
            "audit_trace": [
                {
                    "event_at": entry.event_at.isoformat(),
                    "tie_break": int(entry.tie_break),
                    "event_kind": entry.event_kind,
                    "symbol": MARKER_SYMBOLS.get(
                        entry.event_kind, "??"
                    ),
                    "outcome": entry.outcome,
                    "wat_anchor_manifest_id": (
                        entry.wat_anchor_manifest_id
                    ),
                }
                for entry in verdict.audit_trace
            ],
            "wat_anchor_chain": list(verdict.wat_anchor_chain),
        },
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )


def _serialise_caveat_set(
    caveat_set: Any,
) -> list:
    """Convert a tuple-of-tuples narrowed caveat-set into a
    JSON-serialisable list-of-lists.

    The reducer surfaces ``narrowed_caveat_set`` as a tuple of
    ``(caveat_name, args_tuple)`` pairs; the JSON path serialises
    them as a list of ``[name, list(args)]`` pairs so the document
    stays JSON-pure.
    """
    out = []
    for name, args in caveat_set:
        out.append([str(name), list(args)])
    return out


def not_found_to_json(*, token_id: str, org_id: str) -> str:
    """Render the ``found=false`` shape for an empty-lookup result
    in JSON mode."""
    return json.dumps(
        {
            "capability_token": token_id,
            "org": org_id,
            "found": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


# ---------------------------------------------------------------------------
# Operator runner
# ---------------------------------------------------------------------------


BackendOpener = Callable[
    [str, Optional[str], str], "Awaitable[NatsKvMarkerStackBackend]"
]


async def _live_open_backend(
    servers: str, token: Optional[str], org_id: str
) -> NatsKvMarkerStackBackend:
    """Live NATS-JetStream backend opener (operator-hand path).

    This factory is **never invoked in tests**; the hermetic test
    suite injects a mock backend on :class:`OperatorRunner`.

    Raises:
        RuntimeError: when nats-py is not installed in the
            operator's environment.
    """
    try:
        import nats  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - operator-hand path
        raise RuntimeError(
            "nats-py is required for live operator runs; install "
            "the nats-py extra or invoke the CLI from an operator "
            "environment that has it on the path"
        ) from exc
    connect_kwargs: dict = {"servers": [servers]}
    if token is not None:
        connect_kwargs["token"] = token
    nc = await nats.connect(**connect_kwargs)  # pragma: no cover
    js = nc.jetstream()  # pragma: no cover
    bucket = bucket_name_for_org(org_id)  # pragma: no cover
    kv = await js.key_value(bucket)  # pragma: no cover
    return NatsKvMarkerStackBackend(  # pragma: no cover
        org_id=org_id, kv=kv
    )


@dataclass
class OperatorRunner:
    """Testable orchestrator for the ``wakir-marker-stack-reduce`` CLI.

    Construction is cheap: no I/O happens until :meth:`reduce_one`
    is awaited.

    Attributes:
        open_backend_async: factory invoked once per CLI run to
            obtain a :class:`NatsKvMarkerStackBackend` for the
            requested ``org_id``. The default is the live
            nats-py wire-up; tests inject a mock that returns an
            in-memory backend.
        stdout: writable stream for the rendered output.
        stderr: writable stream for diagnostics.
    """

    open_backend_async: BackendOpener = _live_open_backend
    stdout: TextIO = sys.stdout
    stderr: TextIO = sys.stderr

    async def reduce_one(
        self,
        *,
        servers: str,
        token: Optional[str],
        org_id: str,
        capability_token_id: str,
        output_format: str,
    ) -> int:
        """Reduce one capability-token's marker stack and render.

        Returns:
            ``0`` on a successful reduction, ``3`` if the
            backend has no events logged for the token-id,
            ``1`` on backend errors.
        """
        if output_format not in ("pretty", "json"):
            raise ValueError(
                f"output_format must be 'pretty' or 'json'; "
                f"got {output_format!r}"
            )
        backend = await self.open_backend_async(
            servers, token, org_id
        )
        try:
            stack = await backend.get_marker_stack(
                org_id=org_id,
                capability_token_id=capability_token_id,
            )
        except Exception as exc:
            print(
                f"[wakir-marker-stack-reduce] backend error: "
                f"{type(exc).__name__}: {exc}",
                file=self.stderr,
            )
            return 1

        if stack is None:
            if output_format == "json":
                print(
                    not_found_to_json(
                        token_id=capability_token_id, org_id=org_id
                    ),
                    file=self.stdout,
                )
            else:
                print(
                    f"capability-token: {capability_token_id}\n"
                    f"org: {org_id}\n"
                    f"(no events logged for this token-id; "
                    f"backend returned None)",
                    file=self.stdout,
                )
            return 3

        try:
            verdict = reduce_marker_stack(stack)
        except Exception as exc:
            print(
                f"[wakir-marker-stack-reduce] reducer error: "
                f"{type(exc).__name__}: {exc}",
                file=self.stderr,
            )
            return 1

        if output_format == "pretty":
            self.stdout.write(
                pretty_print_verdict(
                    verdict,
                    token_id=capability_token_id,
                    org_id=org_id,
                )
            )
        else:
            print(
                verdict_to_json(
                    verdict,
                    token_id=capability_token_id,
                    org_id=org_id,
                ),
                file=self.stdout,
            )
        return 0


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wakir-marker-stack-reduce",
        description=(
            "Reduce a per-org marker stack for one capability-"
            "token-id and emit the audit trace (Phase-2 Sprint-9 "
            "Tag-3 Teil A)."
        ),
    )
    p.add_argument(
        "--servers",
        default=os.environ.get(
            "WAKIR_NATS_SERVERS", "nats://127.0.0.1:4222"
        ),
        help="NATS server URL(s); falls back to $WAKIR_NATS_SERVERS",
    )
    p.add_argument(
        "--org",
        required=True,
        help="org_id (mapped to bucket name via "
        "wirelang.federation.marker_stack_kv.bucket_name_for_org)",
    )
    p.add_argument(
        "--capability-token",
        required=True,
        dest="capability_token",
        help="capability-token-id (hash) to reduce",
    )
    p.add_argument(
        "--format",
        choices=("pretty", "json"),
        default="pretty",
        help="output format (default: pretty)",
    )
    return p


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    runner: Optional[OperatorRunner] = None,
) -> int:
    """CLI entry-point; returns an exit code.

    The ``runner`` keyword argument is the test-injection seam.
    The bin shim always calls ``main(argv)`` without ``runner``,
    so the live path runs. Hermetic tests construct an
    :class:`OperatorRunner` with a mock ``open_backend_async`` and
    pass it as ``runner=...``.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if runner is None:
        runner = OperatorRunner()
    token = os.environ.get("WAKIR_NATS_TOKEN") or None
    try:
        return asyncio.run(
            runner.reduce_one(
                servers=args.servers,
                token=token,
                org_id=args.org,
                capability_token_id=args.capability_token,
                output_format=args.format,
            )
        )
    except KeyboardInterrupt:
        print(
            "[wakir-marker-stack-reduce] interrupted",
            file=runner.stderr,
        )
        return 130
