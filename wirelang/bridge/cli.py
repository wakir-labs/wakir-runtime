# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""``bridge-forward subscribe-loop-summary`` CLI — Sprint-Bridge-Forward-CLI-MINI.

Operator-facing probe surface that emits a single-shot snapshot of
subscribe-loop telemetry keyed by subject-pattern. Companion to
:mod:`wirelang.cli.bridge_forward` (Sprint-10 Tag-6 publisher).

Substance scope
---------------

One subcommand: ``subscribe-loop-summary``. Emits a JSON object (or
human-readable line) with exactly the five keys defined by Amara PR
#116 §5 substance-bestaetigungs-item:

- ``subject_pattern`` (str) — the NATS subject pattern the
  subscribe-loop is bound to, e.g.
  ``wakir.dev.agent.agent.task.assigned.*``.
- ``current_lag_seconds`` (float | None) — wall-clock seconds between
  the most recent inbound envelope's ``ts_utc`` and probe-now. ``None``
  when no inbound has ever been observed (or the snapshot does not
  carry a timestamp).
- ``messages_processed_total`` (int) — monotonic count of envelopes
  ``_handle_message_inner`` accepted-and-completed (i.e. excludes
  malformed envelopes that took the audit-annotation path).
- ``active_consumers`` (int) — number of subscribe-loop instances
  currently bound to the subject pattern. For the persona-engine this
  is the number of running ``NatsSubscribeLoop`` tasks; in live JS-pull
  mode this is the JetStream consumer-info ``num_pending`` mirror.
- ``last_message_at`` (RFC3339 UTC str | None) — ``ts_utc`` of the
  most recent inbound envelope. ``None`` when no inbound has ever been
  observed.

Hermetic-test discipline
------------------------

The hermetic test surface (``tests/test_bridge_forward_cli.py``) drives
this CLI WITHOUT importing ``nats-py``:

- ``--snapshot-file <path>`` reads a pre-baked JSON snapshot from disk.
  The NATS-mock-fixture creates this file deterministically.
- ``main()`` accepts an optional ``snapshot_loader`` keyword for in-
  process injection (used by tests that don't want to round-trip via
  the filesystem).

The Live-NATS path (``--live --nats-url ...``) is implemented as a
lazy-imported probe against JetStream stream-info + consumer-info. It
is NOT covered by these hermetic tests; it ships behind the Operator-
Hand-Live-VM Acceptance-Gate (Amara TV-LVD).

Spec-Anker
----------

- ``wirelang/specs/bridge-forward-pipe-v1.md`` (Sprint-10 Tag-6)
- ``wirelang/persona_engine/nats_subscribe_loop.py`` (subscribe-loop
  ground truth — owner Selin OI-PEFR-3)
- Amara PR #116 §5 (CLI-Substance-Bestaetigung, Reza primary owner)
- ADR-0058 (Wakir-Runtime + Wirelang protocol-layer)
- Selin Sprint-Pengine-13 Bug-42 (subscribe-loop inventory trigger)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, TextIO


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

#: Schema-id literal for the subscribe-loop-summary snapshot envelope.
#: Mirrors :data:`wirelang.cli.bridge_forward.AGENT_TASK_ASSIGNED_SCHEMA`
#: convention; single source of truth — keep in sync with the spec.
SUBSCRIBE_LOOP_SUMMARY_SCHEMA = "wakir.bridge.subscribe-loop-summary/1"

#: The five required keys per Amara PR #116 §5.
REQUIRED_SUMMARY_KEYS = (
    "subject_pattern",
    "current_lag_seconds",
    "messages_processed_total",
    "active_consumers",
    "last_message_at",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SummaryFormatError(ValueError):
    """Snapshot input failed an invariant check."""


# ---------------------------------------------------------------------------
# Snapshot validation
# ---------------------------------------------------------------------------


def validate_summary(snapshot: Mapping[str, Any]) -> dict:
    """Validate the snapshot dict against the §5 contract.

    Returns a *new* dict with keys in canonical order (the five keys
    listed in ``REQUIRED_SUMMARY_KEYS``, in that order). Raises
    :class:`SummaryFormatError` on any contract violation.
    """
    if not isinstance(snapshot, Mapping):
        raise SummaryFormatError(
            f"snapshot must be a mapping, got {type(snapshot).__name__}"
        )

    missing = [k for k in REQUIRED_SUMMARY_KEYS if k not in snapshot]
    if missing:
        raise SummaryFormatError(
            f"snapshot missing required keys: {sorted(missing)!r}"
        )

    extra = [k for k in snapshot.keys() if k not in REQUIRED_SUMMARY_KEYS]
    if extra:
        raise SummaryFormatError(
            f"snapshot has unexpected keys: {sorted(extra)!r}"
        )

    subject_pattern = snapshot["subject_pattern"]
    if not isinstance(subject_pattern, str) or not subject_pattern:
        raise SummaryFormatError(
            "subject_pattern must be a non-empty string"
        )
    # The persona-engine subject template is
    # `wakir.<env>.agent.agent.task.assigned.<persona-slug-or-glob>`.
    # We enforce the wakir.<env>. prefix here so the summary cannot
    # silently surface a wrong-env pattern.
    if not subject_pattern.startswith("wakir."):
        raise SummaryFormatError(
            f"subject_pattern must begin with 'wakir.', got "
            f"{subject_pattern!r}"
        )

    current_lag_seconds = snapshot["current_lag_seconds"]
    if current_lag_seconds is not None:
        if not isinstance(current_lag_seconds, (int, float)) or isinstance(
            current_lag_seconds, bool
        ):
            raise SummaryFormatError(
                "current_lag_seconds must be a number or null"
            )
        if current_lag_seconds < 0:
            raise SummaryFormatError(
                "current_lag_seconds must be >= 0 when not null"
            )

    messages_processed_total = snapshot["messages_processed_total"]
    if (
        not isinstance(messages_processed_total, int)
        or isinstance(messages_processed_total, bool)
        or messages_processed_total < 0
    ):
        raise SummaryFormatError(
            "messages_processed_total must be a non-negative int"
        )

    active_consumers = snapshot["active_consumers"]
    if (
        not isinstance(active_consumers, int)
        or isinstance(active_consumers, bool)
        or active_consumers < 0
    ):
        raise SummaryFormatError(
            "active_consumers must be a non-negative int"
        )

    last_message_at = snapshot["last_message_at"]
    if last_message_at is not None:
        if not isinstance(last_message_at, str) or not last_message_at:
            raise SummaryFormatError(
                "last_message_at must be a non-empty RFC3339 string or null"
            )
        # Best-effort RFC3339-Z parse; the persona-engine emits
        # %Y-%m-%dT%H:%M:%SZ via _utc_now_rfc3339().
        try:
            _parse_rfc3339_z(last_message_at)
        except ValueError as exc:
            raise SummaryFormatError(
                f"last_message_at not RFC3339-Z parseable: {exc}"
            ) from exc

    # Cross-field invariant: if last_message_at is None, we cannot have
    # a non-null current_lag_seconds either (the lag is defined against
    # last_message_at).
    if last_message_at is None and current_lag_seconds is not None:
        raise SummaryFormatError(
            "current_lag_seconds must be null when last_message_at is null"
        )

    # Cross-field invariant: if messages_processed_total > 0, we MUST
    # have observed at least one message, so last_message_at is set.
    if messages_processed_total > 0 and last_message_at is None:
        raise SummaryFormatError(
            "last_message_at must be set when messages_processed_total > 0"
        )

    # Canonical ordering — return a fresh dict so downstream is
    # confident the output is byte-stable.
    return {k: snapshot[k] for k in REQUIRED_SUMMARY_KEYS}


def _parse_rfc3339_z(value: str) -> datetime:
    """Parse RFC3339 Z-suffixed timestamps. Mirrors the persona-engine."""
    # The persona-engine emits %Y-%m-%dT%H:%M:%SZ; we accept that and
    # also the slightly more permissive datetime.fromisoformat() output
    # (which understands +00:00 but not Z prior to 3.11). Replace 'Z'
    # with +00:00 for compatibility across Python versions.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# Snapshot loading (hermetic path)
# ---------------------------------------------------------------------------


SnapshotLoader = Callable[[], Mapping[str, Any]]


def load_snapshot_from_file(path: str) -> dict:
    """Hermetic snapshot loader. Reads UTF-8 JSON from ``path``.

    Returns the parsed dict (NOT validated). Use :func:`validate_summary`
    to enforce the contract.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SummaryFormatError(
            f"snapshot file at {path!r} did not parse to a JSON object"
        )
    return data


# ---------------------------------------------------------------------------
# Live snapshot probe (lazy-imported, NOT hermetic)
# ---------------------------------------------------------------------------


def live_snapshot_probe(
    nats_url: str,
    subject_pattern: str,
    stream_name: Optional[str] = None,
    consumer_name: Optional[str] = None,
    timeout_seconds: float = 5.0,
) -> dict:  # pragma: no cover - exercised by Operator-Hand-Live-VM
    """Live JetStream probe — lazy-imports ``nats-py``.

    Returns a snapshot dict with the five contract keys. This path is
    NOT exercised by the hermetic test suite; the Operator-Hand-Live-VM
    smoke (Amara TV-LVD) covers it.

    Behaviour:

    - Connect to ``nats_url`` (token via ``WAKIR_NATS_TOKEN`` env if
      present).
    - Query JetStream stream-info for ``stream_name`` (defaults to the
      subject-pattern's leading dotted segments; operator-overridable).
    - Query JetStream consumer-info for ``consumer_name`` if provided;
      otherwise count all consumers bound to the stream.
    - Derive ``last_message_at`` from ``stream_info.state.last_ts``.
    - Compute ``current_lag_seconds`` as ``now - last_message_at``.
    - ``messages_processed_total`` = ``stream_info.state.messages``.
    - ``active_consumers`` = number of consumers on the stream.
    """
    import asyncio

    import nats  # type: ignore

    async def _probe() -> dict:
        token = os.environ.get("WAKIR_NATS_TOKEN") or None
        nc = await nats.connect(nats_url, token=token)
        try:
            js = nc.jetstream()
            # Operator can pin stream-name; otherwise the JetStream
            # `find_stream_name_by_subject` helper is the official path.
            if stream_name is None:
                resolved_stream = await js.find_stream_name_by_subject(
                    subject_pattern
                )
            else:
                resolved_stream = stream_name
            stream_info = await js.stream_info(resolved_stream)
            state = stream_info.state
            # `consumer_count` is the canonical JS field; nats-py exposes
            # it via `stream_info.state.consumer_count`.
            active_consumers = int(getattr(state, "consumer_count", 0))
            messages_processed_total = int(getattr(state, "messages", 0))
            last_ts = getattr(state, "last_ts", None)
            if last_ts is not None:
                # JetStream `last_ts` is an RFC3339 string in nats-py.
                last_message_at = (
                    last_ts if isinstance(last_ts, str) else last_ts.isoformat()
                )
                now = datetime.now(tz=timezone.utc)
                current_lag_seconds = (
                    now - _parse_rfc3339_z(last_message_at)
                ).total_seconds()
                if current_lag_seconds < 0:
                    # Clock-drift between probe and stream; clamp.
                    current_lag_seconds = 0.0
            else:
                last_message_at = None
                current_lag_seconds = None
            return {
                "subject_pattern": subject_pattern,
                "current_lag_seconds": current_lag_seconds,
                "messages_processed_total": messages_processed_total,
                "active_consumers": active_consumers,
                "last_message_at": last_message_at,
            }
        finally:
            await nc.drain()

    return asyncio.run(asyncio.wait_for(_probe(), timeout=timeout_seconds))


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def format_summary_json(summary: Mapping[str, Any]) -> str:
    """Render the summary as a one-line JSON document.

    Uses ``json.dumps(sort_keys=True, separators=(",", ":"))`` for
    byte-stable output. Trailing newline is appended by the caller.
    """
    return json.dumps(
        dict(summary),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def format_summary_line(summary: Mapping[str, Any]) -> str:
    """Render the summary as a human-readable single-line message.

    The shape is operator-stable and deliberately compact. Example::

        subject_pattern=wakir.dev.agent.agent.task.assigned.* \
            lag=12.34s processed=42 consumers=1 last=2026-05-16T18:22:11Z

    ``lag=none`` and ``last=none`` are emitted when the corresponding
    snapshot value is ``None``.
    """
    lag = summary["current_lag_seconds"]
    last = summary["last_message_at"]
    lag_str = "none" if lag is None else f"{lag:.2f}s"
    last_str = "none" if last is None else last
    return (
        f"subject_pattern={summary['subject_pattern']} "
        f"lag={lag_str} "
        f"processed={summary['messages_processed_total']} "
        f"consumers={summary['active_consumers']} "
        f"last={last_str}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wakir-bridge subscribe-loop-summary",
        description=(
            "Single-shot subscribe-loop telemetry snapshot. Schema: "
            f"{SUBSCRIBE_LOOP_SUMMARY_SCHEMA}. Five keys: subject_pattern, "
            "current_lag_seconds, messages_processed_total, "
            "active_consumers, last_message_at. Default output --json; "
            "use --summary for a human-readable line."
        ),
    )
    # Output mode (mutually exclusive; --json is default-True).
    out = p.add_mutually_exclusive_group()
    out.add_argument(
        "--json",
        dest="output_mode",
        action="store_const",
        const="json",
        help="emit one-line JSON (default)",
    )
    out.add_argument(
        "--summary",
        dest="output_mode",
        action="store_const",
        const="summary",
        help="emit a human-readable single line",
    )
    p.set_defaults(output_mode="json")

    # Input source — exactly one of --snapshot-file, --snapshot-stdin,
    # --live is required.
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--snapshot-file",
        help=(
            "read a deterministic JSON snapshot from this path "
            "(hermetic-test surface). The file MUST contain the five "
            "contract keys."
        ),
    )
    src.add_argument(
        "--snapshot-stdin",
        action="store_true",
        help="read a JSON snapshot from stdin (hermetic-test surface)",
    )
    src.add_argument(
        "--live",
        action="store_true",
        help=(
            "probe a live JetStream stream — lazy-imports nats-py. "
            "Operator-Hand-Live-VM path, NOT covered by hermetic tests."
        ),
    )

    # Live-mode parameters.
    p.add_argument(
        "--nats-url",
        default=os.environ.get("WAKIR_NATS_URL", "nats://wakir-nats:4222"),
        help="NATS URL for --live mode",
    )
    p.add_argument(
        "--subject-pattern",
        help=(
            "Subject pattern for --live mode, e.g. "
            "'wakir.dev.agent.agent.task.assigned.*'. Required when "
            "--live is set."
        ),
    )
    p.add_argument(
        "--stream-name",
        help=(
            "JetStream stream name override (--live mode). Default: "
            "resolved via JetStream find_stream_name_by_subject."
        ),
    )
    p.add_argument(
        "--timeout-seconds",
        type=float,
        default=5.0,
        help="--live probe timeout (default 5.0)",
    )
    return p


def _load_snapshot_dispatch(
    args: argparse.Namespace,
    *,
    snapshot_loader: Optional[SnapshotLoader] = None,
    stdin_stream: Optional[TextIO] = None,
) -> dict:
    """Resolve the snapshot source per the CLI args.

    Priority:
    1. ``snapshot_loader`` keyword (in-process test injection).
    2. ``--snapshot-file <path>`` (hermetic).
    3. ``--snapshot-stdin`` (hermetic).
    4. ``--live`` (Operator-Hand, lazy-imports nats-py).
    """
    if snapshot_loader is not None:
        return dict(snapshot_loader())

    if args.snapshot_file:
        return load_snapshot_from_file(args.snapshot_file)

    if args.snapshot_stdin:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        raw = stream.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SummaryFormatError(
                f"--snapshot-stdin: not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise SummaryFormatError(
                "--snapshot-stdin: JSON root must be an object"
            )
        return data

    # --live path. We validate the operator-supplied subject_pattern
    # early so misuse fails before the lazy nats-py import.
    if not args.subject_pattern:
        raise SummaryFormatError(
            "--live requires --subject-pattern"
        )
    return live_snapshot_probe(
        nats_url=args.nats_url,
        subject_pattern=args.subject_pattern,
        stream_name=args.stream_name,
        timeout_seconds=args.timeout_seconds,
    )


def main(
    argv: Optional[list] = None,
    *,
    snapshot_loader: Optional[SnapshotLoader] = None,
    stdin_stream: Optional[TextIO] = None,
    stdout_stream: Optional[TextIO] = None,
) -> int:
    """CLI entry point.

    Returns:
        0 on success.
        1 on argument / format errors (operator-facing).
        2 on snapshot validation errors (contract violation).
        3 on live-probe errors (network / NATS).

    Keyword args (test seams):
        snapshot_loader: in-process snapshot source override; bypasses
            the ``--snapshot-*`` and ``--live`` arg dispatch.
        stdin_stream: override for ``sys.stdin`` (hermetic --snapshot-
            stdin path).
        stdout_stream: override for ``sys.stdout`` (output capture).
    """
    args = _build_parser().parse_args(argv)
    out = stdout_stream if stdout_stream is not None else sys.stdout

    try:
        raw_snapshot = _load_snapshot_dispatch(
            args,
            snapshot_loader=snapshot_loader,
            stdin_stream=stdin_stream,
        )
    except SummaryFormatError as exc:
        print(
            f"[wakir-bridge subscribe-loop-summary] ERROR: {exc}",
            file=sys.stderr,
        )
        return 1
    except FileNotFoundError as exc:
        print(
            f"[wakir-bridge subscribe-loop-summary] ERROR: "
            f"snapshot file not found: {exc}",
            file=sys.stderr,
        )
        return 1
    except json.JSONDecodeError as exc:
        print(
            f"[wakir-bridge subscribe-loop-summary] ERROR: "
            f"snapshot is not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # pragma: no cover - live-mode catch-all
        print(
            f"[wakir-bridge subscribe-loop-summary] ERROR: "
            f"live probe failed: {exc!r}",
            file=sys.stderr,
        )
        return 3

    try:
        summary = validate_summary(raw_snapshot)
    except SummaryFormatError as exc:
        print(
            f"[wakir-bridge subscribe-loop-summary] ERROR: "
            f"snapshot contract violation: {exc}",
            file=sys.stderr,
        )
        return 2

    if args.output_mode == "summary":
        out.write(format_summary_line(summary))
        out.write("\n")
    else:
        out.write(format_summary_json(summary))
        out.write("\n")
    out.flush()
    return 0


__all__ = [
    "REQUIRED_SUMMARY_KEYS",
    "SUBSCRIBE_LOOP_SUMMARY_SCHEMA",
    "SnapshotLoader",
    "SummaryFormatError",
    "format_summary_json",
    "format_summary_line",
    "live_snapshot_probe",
    "load_snapshot_from_file",
    "main",
    "validate_summary",
]


if __name__ == "__main__":
    sys.exit(main())
