# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Periodic WAT-anchoring driver for recovery_drill_outcome events
(Sprint-Pengine-7 Tag-5 OI-PILOT-4 + Cross-Pair Reza OI-PEF-11).

Sprint-Pengine-7 Tag-4 §3.7.4 introduced the impl-axis
recovery-workflow that emits one ``recovery_drill_outcome``
envelope per executed drill (DRILL_SVID_EXPIRED, DRILL_OOM_KILL,
DRILL_PANIC, DRILL_OTS_STALE, DRILL_WAT_ANCHOR_STALE). The
envelope is persisted to the persona-state NATS-KV bucket under
the ``recovery-audit/<drill_run_id>`` key prefix (OI-PILOT-2
schema, ``wirelang.persona.persona_state_kv``).

OI-PILOT-4 is the periodic WAT-anchoring side of that envelope
flow. A Quadlet timer fires this driver every ~15 minutes during
pilot phase; the driver:

1. Connects to the operator-supplied NATS cluster, opens the
   target persona-state bucket.
2. Iterates all ``recovery-audit/*`` keys.
3. For each envelope: parses the JSON, checks whether it carries
   a non-empty ``wat_anchored_at`` field. If so, skip
   (idempotent re-run).
4. If not anchored: spool the envelope to WAT via
   :func:`wat.anchor.bridge_audit_writer.write_bridge_audit`.
   The persona-id and action-type are derived from the envelope
   payload (``persona_id``, ``"recovery-drill-outcome"``); the
   payload-hash is the SHA-256 of the JCS-canonical envelope.
5. On WAT-write success: write the envelope back to NATS-KV with
   ``wat_anchored_at`` + ``wat_leaf_event_id`` + ``wat_spool_path``
   populated. This is the idempotency key — a re-run on a
   subsequent timer tick sees the populated field and skips.
6. Emit a structured JSON report on stdout summarising the run:
   number of envelopes seen, anchored, skipped (already
   anchored), errored.

Cross-Pair contract with Reza (OI-PEF-11)
------------------------------------------

The driver consumes the ``recovery_drill_outcome`` envelope schema
that Selin defines in Sprint-Pengine-7 Tag-4 §3.7.4 and the WAT-
anchoring bridge that Tomás/WAT-team owns; Reza's OI-PEF-11 is
the **schema-registry-Entry** that lets cross-org verifiers
re-parse the envelope from the wire. The driver here does NOT
re-encode the schema; it consumes the persona-state envelope
verbatim and forwards the canonical bytes to WAT. Schema-drift
detection is out of scope — Reza's schema-registry-Entry is the
single source of truth.

Sandbox boundary
----------------

Live NATS + WAT-spool writes are operator-hand (per
``feedback_sandbox_host_trennung.md``). The hermetic tests in
``tests/orchestrator/test_recovery_drill_anchor.py`` exercise the
:func:`anchor_one_envelope` and :func:`anchor_pass` paths against
in-memory mocks of the JetStream-KV and WAT-write surfaces.

Idempotency contract
--------------------

Running the driver twice in a row yields:

- First run: anchors all unanchored envelopes; writes
  ``wat_anchored_at`` back to NATS-KV.
- Second run: every envelope now carries
  ``wat_anchored_at`` → all skipped. No duplicate WAT spool
  entries.

A re-run after a partial failure (some envelopes anchored, some
errored) re-tries only the unanchored ones; the already-anchored
ones stay skipped.

Schema fields consumed
----------------------

The driver expects each envelope to carry at least:

- ``schema`` == ``"wakir.persona.recovery-drill-outcome/1"``
- ``drill_run_id`` (string)
- ``drill_class`` (one of the five Tag-3 §3.7.2.2 enum values)
- ``persona_id`` (string, matches the bucket's persona-suffix)
- ``org_id`` (string)
- ``outcome`` (one of ``"pass"``, ``"fail"``, ``"hard-cap-exceeded"``)
- ``emitted_at`` (RFC-3339 UTC)

Optional fields populated by THIS driver after successful anchor:

- ``wat_anchored_at`` (RFC-3339 UTC)
- ``wat_leaf_event_id`` (hex, 32 chars)
- ``wat_spool_path`` (absolute path string)
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Schema URI the driver expects on the wire. Mirrors the
#: ``wirelang.persona.persona_state_kv.RECOVERY_DRILL_OUTCOME_VALUE_SCHEMA``
#: constant; declared here independently for sandbox-friendly
#: hermetic tests.
RECOVERY_DRILL_OUTCOME_SCHEMA = "wakir.persona.recovery-drill-outcome/1"

#: NATS-KV key prefix the driver iterates. Mirrors
#: ``wirelang.persona.persona_state_kv.KEY_PREFIX_RECOVERY_AUDIT``.
RECOVERY_AUDIT_KEY_PREFIX = "recovery-audit/"

#: Action-type passed to the WAT bridge-audit-writer. Stable
#: across Tag-5+; the WAT-spool consumer keys on this string for
#: filtered queries.
WAT_ACTION_TYPE = "recovery-drill-outcome"


# ---------------------------------------------------------------------------
# Action records
# ---------------------------------------------------------------------------


@dataclass
class AnchorAction:
    """One driver decision for one envelope.

    ``status`` is one of:
    - ``"anchored"`` — newly anchored on this pass.
    - ``"skipped"`` — already carried ``wat_anchored_at`` on read.
    - ``"error"`` — anchoring failed (WAT or KV-put error).
    - ``"schema-rejected"`` — envelope schema URI did not match.
    """

    key: str
    drill_run_id: str
    status: str
    detail: str = ""


@dataclass
class AnchorReport:
    """Outcome of one full :func:`anchor_pass` invocation."""

    bucket: str
    actions: List[AnchorAction] = field(default_factory=list)

    @property
    def anchored(self) -> int:
        return sum(1 for a in self.actions if a.status == "anchored")

    @property
    def skipped(self) -> int:
        return sum(1 for a in self.actions if a.status == "skipped")

    @property
    def errors(self) -> int:
        return sum(1 for a in self.actions if a.status == "error")

    @property
    def schema_rejected(self) -> int:
        return sum(1 for a in self.actions if a.status == "schema-rejected")

    def to_json(self) -> str:
        return json.dumps(
            {
                "bucket": self.bucket,
                "summary": {
                    "anchored": self.anchored,
                    "skipped": self.skipped,
                    "errors": self.errors,
                    "schema_rejected": self.schema_rejected,
                    "total": len(self.actions),
                },
                "actions": [asdict(a) for a in self.actions],
            },
            sort_keys=True,
            separators=(",", ":"),
        )


# ---------------------------------------------------------------------------
# Pure helpers (hermetic, no I/O)
# ---------------------------------------------------------------------------


def envelope_jcs_bytes(envelope: Mapping[str, Any]) -> bytes:
    """Return the JCS-canonical bytes for an envelope.

    Implementation parity with
    :func:`wirelang.cli.marker_stack_emit.jcs_dumps`; declared
    locally so this module does not import the marker-emit CLI
    (which is a peer-domain Selin-side module).
    """
    try:  # pragma: no cover - prefer real JCS when available
        import rfc8785
        return rfc8785.dumps(dict(envelope))
    except ImportError:
        return json.dumps(
            dict(envelope),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


def envelope_payload_hash(envelope: Mapping[str, Any]) -> str:
    """Compute the SHA-256 hex digest of the JCS-canonical envelope.

    The WAT bridge-audit-writer expects a hex payload_hash; we
    canonicalise the envelope first so the hash is byte-deterministic
    for the same logical envelope.
    """
    return hashlib.sha256(envelope_jcs_bytes(envelope)).hexdigest()


def already_anchored(envelope: Mapping[str, Any]) -> bool:
    """Return True iff the envelope carries a non-empty
    ``wat_anchored_at`` field.

    The idempotency contract: a re-run on a populated field is
    a no-op skip.
    """
    val = envelope.get("wat_anchored_at")
    return isinstance(val, str) and bool(val.strip())


def schema_matches(envelope: Mapping[str, Any]) -> bool:
    """Return True iff the envelope's ``schema`` URI matches the
    documented Selin-side schema.
    """
    return envelope.get("schema") == RECOVERY_DRILL_OUTCOME_SCHEMA


# ---------------------------------------------------------------------------
# Anchor logic
# ---------------------------------------------------------------------------


async def anchor_one_envelope(
    *,
    kv: Any,
    key: str,
    envelope: Mapping[str, Any],
    wat_write_fn: Any,
    now_rfc3339: str,
) -> AnchorAction:
    """Anchor one envelope and write the anchored-back form to KV.

    Pure-ish: the only I/O is via the injected ``kv.put`` and
    ``wat_write_fn`` callables, both of which are mocked in
    hermetic tests.

    ``wat_write_fn`` MUST have the signature::

        (persona_id, action_type, payload_hash, metadata, event_time)
        -> object with .ok bool, .wat_spool_path str|None, .error str

    This is the de-facto interface of
    :func:`wat.anchor.bridge_audit_writer.write_bridge_audit`
    when partial-applied with operator-side ``spool_root`` +
    ``activity_log_path`` defaults.
    """
    drill_run_id = str(envelope.get("drill_run_id", ""))

    if not schema_matches(envelope):
        return AnchorAction(
            key=key,
            drill_run_id=drill_run_id,
            status="schema-rejected",
            detail=(
                f"envelope schema URI {envelope.get('schema')!r} does "
                f"not match {RECOVERY_DRILL_OUTCOME_SCHEMA!r}"
            ),
        )

    if already_anchored(envelope):
        return AnchorAction(
            key=key,
            drill_run_id=drill_run_id,
            status="skipped",
            detail=(
                f"already anchored at "
                f"{envelope.get('wat_anchored_at')!r}"
            ),
        )

    persona_id = str(envelope.get("persona_id", ""))
    if not persona_id:
        return AnchorAction(
            key=key,
            drill_run_id=drill_run_id,
            status="error",
            detail="envelope missing persona_id field",
        )

    payload_hash = envelope_payload_hash(envelope)
    metadata = {
        "ref": f"recovery-drill-{drill_run_id}",
        "drill_class": envelope.get("drill_class", ""),
        "outcome": envelope.get("outcome", ""),
    }

    try:
        write_result = wat_write_fn(
            persona_id=persona_id,
            action_type=WAT_ACTION_TYPE,
            payload_hash=payload_hash,
            metadata=metadata,
            event_time=envelope.get("emitted_at"),
        )
    except Exception as exc:  # noqa: BLE001 - operator wants the full error
        return AnchorAction(
            key=key,
            drill_run_id=drill_run_id,
            status="error",
            detail=f"wat write raised: {exc!r}",
        )

    if not getattr(write_result, "ok", False):
        return AnchorAction(
            key=key,
            drill_run_id=drill_run_id,
            status="error",
            detail=(
                f"wat write returned non-ok status: "
                f"{getattr(write_result, 'status', '?')!r} "
                f"error={getattr(write_result, 'error', '?')!r}"
            ),
        )

    # Write the anchored-back envelope to KV. The new fields are
    # appended without rewriting unrelated fields; field order is
    # preserved by JCS-canonical output.
    anchored = dict(envelope)
    anchored["wat_anchored_at"] = now_rfc3339
    spool_path = getattr(write_result, "wat_spool_path", None)
    if spool_path is not None:
        anchored["wat_spool_path"] = str(spool_path)
    # The bridge-audit-writer doesn't surface the leaf event_id
    # directly on the result; if the operator wants it for
    # cross-reference, the WAT-spool file carries it. We omit
    # ``wat_leaf_event_id`` here on purpose to avoid encoding a
    # cross-module-coupling surface that isn't on the bridge
    # writer's documented API.

    try:
        await kv.put(key, envelope_jcs_bytes(anchored))
    except Exception as exc:  # noqa: BLE001
        return AnchorAction(
            key=key,
            drill_run_id=drill_run_id,
            status="error",
            detail=(
                f"WAT anchor succeeded but KV write-back failed: {exc!r}"
            ),
        )

    return AnchorAction(
        key=key,
        drill_run_id=drill_run_id,
        status="anchored",
        detail=f"spool={spool_path!r}",
    )


async def anchor_pass(
    *,
    kv: Any,
    bucket: str,
    wat_write_fn: Any,
    now_rfc3339: str,
    keys: Optional[Iterable[str]] = None,
) -> AnchorReport:
    """Run one anchoring pass over all recovery-audit keys.

    ``kv`` is a JetStream-KV handle with the methods:

    - ``await kv.keys()`` returning an iterable of key strings.
    - ``await kv.get(key)`` returning an object whose ``.value``
      attribute is the raw bytes (or a Mapping; the driver
      accepts both).
    - ``await kv.put(key, value_bytes)`` storing the new bytes.

    ``keys`` is an explicit iterable for tests that want to skip
    the ``kv.keys()`` round-trip; production callers leave it
    None and let the driver enumerate.

    Returns an :class:`AnchorReport` summarising the pass.
    """
    if keys is None:
        raw_keys = await kv.keys()
        keys_list = [
            k for k in raw_keys
            if isinstance(k, str)
            and k.startswith(RECOVERY_AUDIT_KEY_PREFIX)
        ]
    else:
        keys_list = list(keys)

    report = AnchorReport(bucket=bucket)
    for key in keys_list:
        try:
            entry = await kv.get(key)
        except Exception as exc:  # noqa: BLE001
            report.actions.append(
                AnchorAction(
                    key=key,
                    drill_run_id="",
                    status="error",
                    detail=f"kv.get raised: {exc!r}",
                )
            )
            continue

        value = getattr(entry, "value", entry)
        if isinstance(value, (bytes, bytearray)):
            try:
                envelope = json.loads(bytes(value).decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                report.actions.append(
                    AnchorAction(
                        key=key,
                        drill_run_id="",
                        status="error",
                        detail=f"envelope JSON decode failed: {exc!r}",
                    )
                )
                continue
        elif isinstance(value, Mapping):
            envelope = dict(value)
        else:
            report.actions.append(
                AnchorAction(
                    key=key,
                    drill_run_id="",
                    status="error",
                    detail=(
                        f"unexpected entry.value type: {type(value)!r}"
                    ),
                )
            )
            continue

        action = await anchor_one_envelope(
            kv=kv,
            key=key,
            envelope=envelope,
            wat_write_fn=wat_write_fn,
            now_rfc3339=now_rfc3339,
        )
        report.actions.append(action)

    return report


# ---------------------------------------------------------------------------
# CLI entry-point (live path; not exercised in hermetic tests)
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wakir-recovery-drill-anchor",
        description=(
            "Anchor unanchored recovery_drill_outcome envelopes from "
            "a persona-state NATS-KV bucket to the WAT spool "
            "(Sprint-Pengine-7 Tag-5 OI-PILOT-4)."
        ),
    )
    p.add_argument(
        "--bucket",
        required=True,
        help=(
            "Persona-state KV bucket name "
            "(e.g. wakir-persona-state-acme-tomas)."
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
        "--spool-root",
        required=True,
        help="WAT spool root directory (operator-managed).",
    )
    p.add_argument(
        "--activity-log",
        required=True,
        help="Pre-Framework activity-log.md path.",
    )
    return p


def _utc_now_rfc3339() -> str:
    import datetime as dt
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:  # Live path imports inside main() so hermetic tests
          # don't require nats-py / the wat tree.
        import nats  # type: ignore
        from wat.anchor.bridge_audit_writer import write_bridge_audit
    except ImportError as exc:
        print(
            f"[wakir-recovery-drill-anchor] ERROR: missing runtime "
            f"dependency: {exc}",
            file=sys.stderr,
        )
        return 1

    def _wat_write(*, persona_id, action_type, payload_hash, metadata,
                   event_time):
        return write_bridge_audit(
            persona_id=persona_id,
            action_type=action_type,
            payload_hash=payload_hash,
            metadata=metadata,
            spool_root=args.spool_root,
            activity_log_path=args.activity_log,
            event_time=event_time,
        )

    async def _run() -> AnchorReport:
        token = os.environ.get("WAKIR_NATS_TOKEN") or None
        nc = await nats.connect(args.servers, token=token)
        try:
            js = nc.jetstream()
            kv = await js.key_value(bucket=args.bucket)
            return await anchor_pass(
                kv=kv,
                bucket=args.bucket,
                wat_write_fn=_wat_write,
                now_rfc3339=_utc_now_rfc3339(),
            )
        finally:
            await nc.drain()

    try:
        report = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        print(
            f"[wakir-recovery-drill-anchor] ERROR: pass failed: {exc!r}",
            file=sys.stderr,
        )
        return 1

    # Stderr: human log; stdout: JSON report.
    for action in report.actions:
        line = (
            f"[wakir-recovery-drill-anchor] key={action.key} "
            f"drill={action.drill_run_id} status={action.status}"
        )
        if action.detail:
            line += f"  ({action.detail})"
        print(line, file=sys.stderr)
    print(report.to_json())
    return 1 if report.errors > 0 else 0


__all__ = [
    "AnchorAction",
    "AnchorReport",
    "RECOVERY_AUDIT_KEY_PREFIX",
    "RECOVERY_DRILL_OUTCOME_SCHEMA",
    "WAT_ACTION_TYPE",
    "already_anchored",
    "anchor_one_envelope",
    "anchor_pass",
    "envelope_jcs_bytes",
    "envelope_payload_hash",
    "main",
    "schema_matches",
]


if __name__ == "__main__":
    raise SystemExit(main())
