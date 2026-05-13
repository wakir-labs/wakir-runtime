# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Per-org NATS-JetStream KV bucket provisioner (Phase-2 Sprint-9 Tag-1).

Sprint-8 Tag-4 (`wirelang.federation.marker_stack_kv`) introduced
the marker-stack-event bucket FAMILY: one bucket per organisation,
named ``wakir-marker-stack-{org_id}``. The Sprint-2/4/5 inventory in
``scripts/init-nats-buckets.py`` was hard-coded for a fixed seven-
bucket layout where bucket names were inventory-globals. That driver
cannot enrol per-org buckets because the org-id is supplied at runtime
by the operator (one bucket per organisation onboarded into the
federation).

This module is the per-org tier:

1. Accepts a non-empty list of ``org_id`` values (CLI flag or env var),
   validates each one against
   ``wirelang.federation.marker_stack_kv._IDENT_RE`` (URI-safe ASCII
   subset, no slashes, no whitespace).
2. For each ``org_id``, derives the canonical bucket name via
   ``wirelang.federation.marker_stack_kv.bucket_name_for_org`` and
   ensures the bucket exists with the documented
   ``BUCKET_CONFIG`` (history=1, ttl=0, max_value_size=32_768,
   storage="file", replicas=1).
3. Idempotency contract: re-running against a cluster that already
   has a bucket is a no-op. Drift between the live config and the
   documented ``BUCKET_CONFIG`` is REPORTED, never auto-corrected
   (mirrors the Sprint-5 Tag-2 ``init-nats-buckets`` semantics).
4. Emits a structured JSON report on stdout and a human-readable log
   line per bucket on stderr.

Why a separate driver
---------------------

The Sprint-5 ``init-nats-buckets`` driver has a fixed seven-bucket
inventory and a tight cross-reference to Wirelang-side BUCKET_CONFIG
constants. Layering per-org runtime buckets on top of that driver
would either:

- Make the inventory dynamic, breaking the Sprint-4-Tag-4 / Tag-5 /
  Sprint-5-Tag-2 byte-mirror anchor invariants between the
  orchestrator-side spec and the Wirelang-side consumer constants, or
- Spawn a per-org code-path that the existing driver's tests do not
  cover, increasing the risk that a bug in the per-org path silently
  ships.

A dedicated driver keeps the contracts crisp:

- ``scripts/init-nats-buckets.py`` owns the FIXED seven-bucket
  Phase-1b/2 inventory. Hermetic anchor invariants stay byte-precise.
- ``bin/nats-kv-bucket-provision`` (this module) owns the PER-ORG
  bucket family. The single bucket-config-source-of-truth is the
  Wirelang-side ``BUCKET_CONFIG`` constant in
  ``wirelang.federation.marker_stack_kv``; this driver imports that
  constant directly and never re-encodes the values, eliminating the
  drift surface.

Cross-reference invariants
--------------------------

This driver re-uses three Wirelang-side public-API constants:

- ``BUCKET_NAME_PREFIX`` — the ``"wakir-marker-stack-"`` prefix.
- ``BUCKET_CONFIG`` — the documented bucket configuration mapping.
- ``bucket_name_for_org`` — the validated bucket-name derivation.

If the Wirelang-side module changes any of these, this driver picks
up the change automatically (single source of truth). The hermetic
test suite (`tests/orchestrator/test_nats_kv_bucket_provision.py`)
asserts the re-export shape so a Wirelang-side rename breaks the
test before the driver ships broken to ops.

Bucket family layout (Sprint-8 Tag-4 reference)
-----------------------------------------------

For two organisations ``acme`` and ``orbit``, the provisioner ensures
these two buckets exist on a single NATS cluster:

- ``wakir-marker-stack-acme``
- ``wakir-marker-stack-orbit``

Each bucket carries:

- ``description``: "Wirelang persistent marker-stack event log (Phase-2)"
- ``history``: 1
- ``ttl_seconds``: 0 (unbounded; audit-trail invariant)
- ``max_value_size``: 32_768 (32 KiB; envelope-shape ceiling)
- ``storage``: "file"
- ``replicas``: 1 (Phase-1 single-node)

Cross-org isolation: each org operates against its own bucket,
keyed by ``org_id``. The Wirelang-side ``NatsKvMarkerStackBackend``
enforces the cross-org boundary at the application layer
(:class:`MarkerStackCrossOrgBoundaryError`). The provisioner does not
re-enforce that boundary — it is a substrate-shaping tool, not a
consumer.

Usage
-----

    python3 bin/nats-kv-bucket-provision \
        --org acme --org orbit                  # provision two orgs
    python3 bin/nats-kv-bucket-provision \
        --orgs-file /etc/wakir/onboarded-orgs   # newline-delimited file
    python3 bin/nats-kv-bucket-provision \
        --org acme --dry-run                    # plan only

The ``--orgs-file`` path is the per-host onboarded-orgs roster. One
``org_id`` per line; blank lines and ``#``-comments are ignored.

Authentication: same env-var contract as ``init-nats-buckets``
(``WAKIR_NATS_TOKEN`` for token auth, ``WAKIR_NATS_SERVERS`` for the
target servers URL).

Exit codes
----------

    0  every requested per-org bucket is at the documented config
    1  unrecoverable connection error, invalid arguments, or unknown
       Wirelang-side constants (cross-reference invariant broken)
    2  configuration drift detected (one or more existing per-org
       buckets diverge from the Wirelang-side ``BUCKET_CONFIG``)

Sandbox boundary
----------------

Live NATS connections are operator-hand per the
``feedback_sandbox_host_trennung.md`` memory: the sandbox process
never opens a host podman socket and never connects to a live NATS
cluster. The hermetic test surface (``tests/orchestrator/
test_nats_kv_bucket_provision.py``) drives ``plan_and_apply`` against
an in-memory mock JetStream context — no I/O, no network, no
filesystem mutation outside ``tmp_path``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Cross-reference: re-use the Wirelang-side single-source-of-truth
# constants for the marker-stack bucket family. Importing them here
# guarantees the driver and the consumer agree byte-precisely.
# ---------------------------------------------------------------------------

# The Sprint-8 Tag-4 module is the canonical owner of the bucket name
# prefix, the bucket-config mapping, and the validated bucket-name
# derivation. We import them and propagate them; we DO NOT re-encode.
from wirelang.federation.marker_stack_kv import (  # noqa: E402
    BUCKET_CONFIG as MARKER_STACK_BUCKET_CONFIG,
    BUCKET_NAME_PREFIX as MARKER_STACK_BUCKET_NAME_PREFIX,
    bucket_name_for_org,
)


# ---------------------------------------------------------------------------
# Action records
# ---------------------------------------------------------------------------


@dataclass
class BucketAction:
    """One planner decision for one per-org bucket.

    ``status`` is one of ``"created"``, ``"unchanged"``, ``"drift"``,
    ``"would_create"`` (dry-run), or ``"error"``.
    """

    org_id: str
    bucket: str
    status: str
    detail: str = ""
    drift: dict = field(default_factory=dict)


@dataclass
class ProvisionReport:
    """Outcome of one ``nats-kv-bucket-provision`` invocation."""

    servers: str
    dry_run: bool
    actions: List[BucketAction] = field(default_factory=list)

    @property
    def created(self) -> int:
        return sum(1 for a in self.actions if a.status == "created")

    @property
    def unchanged(self) -> int:
        return sum(1 for a in self.actions if a.status == "unchanged")

    @property
    def drift(self) -> int:
        return sum(1 for a in self.actions if a.status == "drift")

    @property
    def would_create(self) -> int:
        return sum(1 for a in self.actions if a.status == "would_create")

    def to_json(self) -> str:
        return json.dumps(
            {
                "servers": self.servers,
                "dry_run": self.dry_run,
                "summary": {
                    "created": self.created,
                    "unchanged": self.unchanged,
                    "drift": self.drift,
                    "would_create": self.would_create,
                    "total": len(self.actions),
                },
                "actions": [asdict(a) for a in self.actions],
            },
            sort_keys=True,
            separators=(",", ":"),
        )


# ---------------------------------------------------------------------------
# Org-id list parsing
# ---------------------------------------------------------------------------


def parse_orgs_file(path: Path) -> List[str]:
    """Parse a newline-delimited onboarded-orgs roster file.

    Each non-empty, non-comment line yields one ``org_id``. Comments
    start with ``#`` and run to end-of-line. Whitespace is stripped.
    Duplicate ``org_id`` values are de-duplicated while preserving the
    first-occurrence order.

    Raises :class:`FileNotFoundError` if ``path`` does not exist;
    raises :class:`ValueError` if any line is malformed (the
    permitted-character regex is enforced via
    ``bucket_name_for_org`` at call site, not here, so callers see a
    single source of validation truth).
    """
    contents = path.read_text(encoding="utf-8")
    seen: set[str] = set()
    out: List[str] = []
    for line_no, raw in enumerate(contents.splitlines(), start=1):
        # Strip comment tail.
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# Spec materialisation
# ---------------------------------------------------------------------------


def spec_for_org(org_id: str) -> Mapping[str, Any]:
    """Translate an ``org_id`` into the kwargs expected by
    ``nats.js.JetStreamContext.create_key_value``.

    The values are sourced byte-precisely from
    :data:`wirelang.federation.marker_stack_kv.BUCKET_CONFIG`; this
    function adds the ``bucket`` field (derived from ``org_id``) and
    re-keys the ``ttl_seconds`` field to the nats-py ``ttl`` name.

    Raises :class:`ValueError` for a malformed ``org_id`` (delegates
    to :func:`bucket_name_for_org`).
    """
    bucket = bucket_name_for_org(org_id)
    cfg = MARKER_STACK_BUCKET_CONFIG
    return {
        "bucket": bucket,
        "description": str(cfg["description"]),
        "history": int(cfg["history"]),
        "ttl": int(cfg["ttl_seconds"]),
        "max_value_size": int(cfg["max_value_size"]),
        "storage": str(cfg["storage"]),
        "replicas": int(cfg["replicas"]),
    }


def _drift_diff(status: Mapping[str, Any]) -> dict:
    """Return a dict of fields where ``status`` diverges from the
    canonical Wirelang-side ``BUCKET_CONFIG``.

    Empty dict == no drift. Each entry is
    ``{field: {"want": ..., "got": ...}}``. ``description`` is not
    checked (operators sometimes annotate it).
    """
    cfg = MARKER_STACK_BUCKET_CONFIG
    want = {
        "history": int(cfg["history"]),
        "ttl": int(cfg["ttl_seconds"]),
        "max_value_size": int(cfg["max_value_size"]),
        "storage": str(cfg["storage"]),
        "replicas": int(cfg["replicas"]),
    }
    diffs: dict[str, dict[str, Any]] = {}
    for key, expected in want.items():
        got = status.get(key)
        if key == "ttl" and isinstance(got, float):
            got = int(got)
        if got is None:
            # Field not observable on this status payload; skip
            # rather than false-positive-drift.
            continue
        if got != expected:
            diffs[key] = {"want": expected, "got": got}
    return diffs


# ---------------------------------------------------------------------------
# Planner (network-free; the JetStream surface is mock-friendly)
# ---------------------------------------------------------------------------


async def plan_and_apply(
    js: Any,
    org_ids: Iterable[str],
    *,
    dry_run: bool,
) -> List[BucketAction]:
    """Idempotently ensure one bucket per ``org_id`` exists.

    ``js`` is a JetStream context with the same nats-py surface
    used by ``scripts/init-nats-buckets.py``:

    - ``await js.key_value(bucket=name)`` raises if the bucket
      is missing; otherwise returns a KV handle.
    - ``await kv.status()`` returns an object whose attributes (or
      mapping keys) include ``history``, ``ttl``, ``max_value_size``,
      ``storage``, ``replicas``.
    - ``await js.create_key_value(**kwargs)`` creates a new bucket.

    The planner never deletes buckets. Drift is reported, not
    corrected. The planner never silently overwrites operator state.

    Returns a list of :class:`BucketAction` records in the same order
    as the input ``org_ids``.
    """
    actions: List[BucketAction] = []
    seen_orgs: set[str] = set()
    for org_id in org_ids:
        if org_id in seen_orgs:
            # Idempotent input: ignore a repeated org_id silently.
            continue
        seen_orgs.add(org_id)

        try:
            spec_kwargs = spec_for_org(org_id)
        except ValueError as exc:
            actions.append(
                BucketAction(
                    org_id=org_id,
                    bucket="",
                    status="error",
                    detail=f"invalid org_id: {exc}",
                )
            )
            continue
        bucket = spec_kwargs["bucket"]

        try:
            existing = await _safe_get_kv(js, bucket)
        except Exception as exc:
            actions.append(
                BucketAction(
                    org_id=org_id,
                    bucket=bucket,
                    status="error",
                    detail=repr(exc),
                )
            )
            continue

        if existing is None:
            if dry_run:
                actions.append(
                    BucketAction(
                        org_id=org_id,
                        bucket=bucket,
                        status="would_create",
                        detail=(
                            f"history={spec_kwargs['history']} "
                            f"ttl={spec_kwargs['ttl']}s "
                            f"max_value={spec_kwargs['max_value_size']}B "
                            f"storage={spec_kwargs['storage']} "
                            f"replicas={spec_kwargs['replicas']}"
                        ),
                    )
                )
                continue
            try:
                await js.create_key_value(**spec_kwargs)
            except Exception as exc:
                actions.append(
                    BucketAction(
                        org_id=org_id,
                        bucket=bucket,
                        status="error",
                        detail=repr(exc),
                    )
                )
                continue
            actions.append(
                BucketAction(
                    org_id=org_id,
                    bucket=bucket,
                    status="created",
                    detail=spec_kwargs["description"],
                )
            )
            continue

        # Bucket exists; check for drift.
        try:
            status = await _status_as_mapping(existing)
        except Exception as exc:
            actions.append(
                BucketAction(
                    org_id=org_id,
                    bucket=bucket,
                    status="error",
                    detail=repr(exc),
                )
            )
            continue
        diffs = _drift_diff(status)
        if diffs:
            actions.append(
                BucketAction(
                    org_id=org_id,
                    bucket=bucket,
                    status="drift",
                    detail=(
                        "live config diverges from Wirelang BUCKET_CONFIG"
                    ),
                    drift=diffs,
                )
            )
        else:
            actions.append(
                BucketAction(
                    org_id=org_id,
                    bucket=bucket,
                    status="unchanged",
                    detail=spec_kwargs["description"],
                )
            )
    return actions


async def _safe_get_kv(js: Any, name: str) -> Optional[Any]:
    """Return a KV handle for ``name`` or ``None`` if absent."""
    try:
        return await js.key_value(bucket=name)
    except KeyError:
        return None
    except Exception as exc:
        cls_name = type(exc).__name__
        if "NotFound" in cls_name or "DoesNotExist" in cls_name:
            return None
        raise


async def _status_as_mapping(kv: Any) -> Mapping[str, Any]:
    """Return the bucket status as a plain mapping."""
    raw = await kv.status()
    if isinstance(raw, Mapping):
        return dict(raw)
    out: dict[str, Any] = {}
    for k in ("history", "ttl", "max_value_size", "storage", "replicas"):
        if hasattr(raw, k):
            out[k] = getattr(raw, k)
    return out


# ---------------------------------------------------------------------------
# Connection wrapper (CLI entry-point only)
# ---------------------------------------------------------------------------


async def _connect_and_run(
    servers: str,
    org_ids: Sequence[str],
    *,
    dry_run: bool,
    token: Optional[str],
) -> ProvisionReport:
    """Real connection path used by ``main()``; not exercised in tests.

    Tests call ``plan_and_apply`` directly with an in-memory mock
    JetStream context.
    """
    import nats  # type: ignore

    nc = await nats.connect(servers, token=token)
    try:
        js = nc.jetstream()
        actions = await plan_and_apply(js, org_ids, dry_run=dry_run)
    finally:
        await nc.drain()
    return ProvisionReport(servers=servers, dry_run=dry_run, actions=actions)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nats-kv-bucket-provision",
        description=(
            "Idempotent per-org marker-stack-event bucket provisioner "
            "(Phase-2 Sprint-9 Tag-1)."
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
        action="append",
        default=None,
        dest="orgs",
        help="org_id to provision (repeatable)",
    )
    p.add_argument(
        "--orgs-file",
        type=Path,
        default=None,
        help=(
            "path to a newline-delimited file of org_ids; "
            "blank/# lines ignored; combined with --org flags"
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan but do not create any bucket",
    )
    return p


def _collect_org_ids(
    flag_orgs: Optional[Sequence[str]],
    orgs_file: Optional[Path],
) -> List[str]:
    """Merge CLI ``--org`` flags with a roster file.

    Order: file entries first (in file order), then ``--org`` flags
    (in argv order). Duplicates are de-duplicated, first-occurrence
    wins.

    Raises :class:`ValueError` if no orgs are provided at all.
    """
    out: List[str] = []
    seen: set[str] = set()
    if orgs_file is not None:
        for org_id in parse_orgs_file(orgs_file):
            if org_id in seen:
                continue
            seen.add(org_id)
            out.append(org_id)
    if flag_orgs:
        for org_id in flag_orgs:
            if org_id in seen:
                continue
            seen.add(org_id)
            out.append(org_id)
    if not out:
        raise ValueError(
            "no org_ids supplied; provide --org or --orgs-file"
        )
    return out


def _exit_code_for(report: ProvisionReport) -> int:
    if any(a.status == "error" for a in report.actions):
        return 1
    if report.drift > 0:
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        org_ids = _collect_org_ids(args.orgs, args.orgs_file)
    except (ValueError, FileNotFoundError) as exc:
        print(
            f"[nats-kv-bucket-provision] ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    token = os.environ.get("WAKIR_NATS_TOKEN") or None

    try:
        report = asyncio.run(
            _connect_and_run(
                args.servers, org_ids, dry_run=args.dry_run, token=token
            )
        )
    except ImportError as exc:
        print(
            f"[nats-kv-bucket-provision] ERROR: nats-py is not "
            f"installed: {exc}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"[nats-kv-bucket-provision] ERROR: connection or planner "
            f"failure: {exc!r}",
            file=sys.stderr,
        )
        return 1

    # Stderr: human log; stdout: JSON report.
    for action in report.actions:
        line = (
            f"[nats-kv-bucket-provision] org={action.org_id} "
            f"bucket={action.bucket}: {action.status}"
        )
        if action.detail:
            line += f"  ({action.detail})"
        if action.drift:
            line += f"  drift={action.drift}"
        print(line, file=sys.stderr)
    print(report.to_json())
    return _exit_code_for(report)


__all__ = [
    "BucketAction",
    "MARKER_STACK_BUCKET_CONFIG",
    "MARKER_STACK_BUCKET_NAME_PREFIX",
    "ProvisionReport",
    "_collect_org_ids",
    "_drift_diff",
    "bucket_name_for_org",
    "main",
    "parse_orgs_file",
    "plan_and_apply",
    "spec_for_org",
]


if __name__ == "__main__":
    raise SystemExit(main())
