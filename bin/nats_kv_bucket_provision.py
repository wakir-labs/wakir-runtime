# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# This file is the sandbox-side driver baked into the
# `ghcr.io/wakir-labs/wakir-provisioner` image and is part of the
# Wakir Provisioner module. Licensed under the Business Source
# License 1.1; see
# `infra/spire/federation/provisioner/LICENSE-BSL.md`.
# Change Date: 2030-05-13 (four years after the first BSL-licensed
# image publication, `wakir-provisioner:0.1.2`).
# Change License: Apache License 2.0.
"""Per-org NATS-JetStream KV bucket provisioner (Phase-2 Sprint-9 Tag-1,
Sprint-9 Tag-2 multi-family extension).

Sprint-8 Tag-4 (`wirelang.federation.marker_stack_kv`) introduced
the marker-stack-event bucket FAMILY: one bucket per organisation,
named ``wakir-marker-stack-{org_id}``. Sprint-9 Tag-2 introduced a
second per-org family (`wirelang.federation.sequence_number_ledger_kv`):
``wakir-caveat-override-export-sequence-{org_id}``. Both families
share the same per-org isolation contract; they differ only on
``max_value_size`` (32 KiB for marker-stack, 4 KiB for the ledger)
and ``description``. The Sprint-2/4/5 inventory in
``scripts/init-nats-buckets.py`` was hard-coded for a fixed seven-
bucket layout where bucket names were inventory-globals. That driver
cannot enrol per-org buckets because the org-id is supplied at runtime
by the operator (multiple buckets per organisation onboarded into the
federation).

This module is the per-org tier:

1. Accepts a non-empty list of ``org_id`` values (CLI flag or env var),
   validates each one against
   ``wirelang.federation.marker_stack_kv._IDENT_RE`` (URI-safe ASCII
   subset, no slashes, no whitespace).
2. For each ``org_id``, derives the canonical bucket name for each
   registered per-org family via the family's ``bucket_name_for_org``
   and ensures every bucket exists with the documented
   ``BUCKET_CONFIG``.
3. Idempotency contract: re-running against a cluster that already
   has a bucket is a no-op. Drift between the live config and the
   documented ``BUCKET_CONFIG`` is REPORTED, never auto-corrected
   (mirrors the Sprint-5 Tag-2 ``init-nats-buckets`` semantics).
4. Emits a structured JSON report on stdout and a human-readable log
   line per bucket on stderr.

Bucket-family registry (Sprint-9 Tag-2)
---------------------------------------

The driver carries a small registry of per-org families it
provisions. Each family entry sources its constants byte-precisely
from the Wirelang-side single-source-of-truth module:

- **marker-stack** (Sprint-8 Tag-4):
  ``wirelang.federation.marker_stack_kv`` — append-only per-org
  marker-event log; ``max_value_size=32_768``.
- **sequence-ledger** (Sprint-9 Tag-2):
  ``wirelang.federation.sequence_number_ledger_kv`` — durable
  ``SequenceNumberLedger`` cell-per-pair store with CAS-pin;
  ``max_value_size=4_096``. Imported defensively: if the Wirelang-
  side module is absent (e.g. Reza-Tag-2 not yet merged into the
  consuming branch), this family is skipped silently and the
  driver continues to provision marker-stack buckets only.

Adding a new per-org family is a three-line extension: import the
canonical constants, append a :class:`BucketFamily` instance to
:data:`BUCKET_FAMILIES`. The hermetic test surface re-asserts the
cross-reference invariant for every registered family.

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
# constants for every per-org bucket family. Importing them here
# guarantees the driver and the consumers agree byte-precisely.
#
# Sprint-9 Tag-4 import-path posture
# ----------------------------------
# The provisioner is a SUBSTRATE-SHAPING driver: its job is to ensure
# per-org JetStream KV buckets exist with the documented config. It
# does NOT need any of the cryptographic / identity-stack machinery
# the Wirelang Sprint-8 Tag-4 ``marker_stack_kv`` module pulls in
# transitively (the identity-stack import chain on the live tip:
# ``marker_stack_kv -> n2_evaluator -> identity.federation_resolver
# -> identity.__init__ -> identity.key_derivation -> cryptography``).
#
# The Sprint-9 Tag-4 live-bring-up on the Pilot-VM exposed the
# transitive import as a runtime crash on a base image that does not
# ship ``cryptography`` (Mira-Bug-Bilanz 2026-05-13, Bug 6). The
# wakir-provisioner image (Tomás Sprint-9 Tag-4, Option A) ships
# ``cryptography`` so the transitive chain resolves regardless; the
# constants-only import path below (Reza Sprint-9 Tag-4, Option C)
# flattens the chain so a future image that does NOT ship
# ``cryptography`` still works.
#
# The two tracks are additive defence-in-depth: the image gap closure
# unblocks the Pilot bring-up TODAY without depending on Reza
# Sprint-9 Tag-4 merge timing, and the constants-only import path
# eliminates a class of unnecessary transitive dependencies once Reza
# Sprint-9 Tag-4 lands on the consuming branch.
#
# The defensive try-chain below probes the lightweight constants-only
# module first (Reza Sprint-9 Tag-4 target name) and falls back to
# the full module on tips that don't yet carry the disentangled
# layer. The Reza-side module name is documented in
# ``2026-05-13-tomas-sprint-9-tag-4-bucket-init-image-fix.md`` as an
# assumption to be ratified; if Reza picks a different name, the
# fallback path still works.
# ---------------------------------------------------------------------------

# The Sprint-8 Tag-4 module is the canonical owner of the marker-stack
# bucket name prefix, the bucket-config mapping, and the validated
# bucket-name derivation. We import them and propagate them; we DO NOT
# re-encode. Probe the constants-only target first (Reza Sprint-9
# Tag-4 disentanglement); fall back to the full module on baseline
# tips that don't yet carry it.
try:  # pragma: no cover - import-path probe
    from wirelang.federation.marker_stack_kv_constants import (  # noqa: E402
        BUCKET_CONFIG as MARKER_STACK_BUCKET_CONFIG,
        BUCKET_NAME_PREFIX as MARKER_STACK_BUCKET_NAME_PREFIX,
        bucket_name_for_org as _marker_stack_bucket_name_for_org,
    )
except ImportError:  # pragma: no cover - baseline path
    from wirelang.federation.marker_stack_kv import (  # noqa: E402
        BUCKET_CONFIG as MARKER_STACK_BUCKET_CONFIG,
        BUCKET_NAME_PREFIX as MARKER_STACK_BUCKET_NAME_PREFIX,
        bucket_name_for_org as _marker_stack_bucket_name_for_org,
    )

# Tag-1 backwards-compatibility alias: the single-family era exposed
# ``bucket_name_for_org`` as a module-level name. We keep that alias
# pointing at the marker-stack family so Tag-1 hermetic tests
# continue to pass byte-precisely.
bucket_name_for_org = _marker_stack_bucket_name_for_org

# The Sprint-9 Tag-2 module is the canonical owner of the durable
# sequence-number-ledger bucket family. Defensive import: when the
# consuming branch does not yet carry the Tag-2 module (e.g. the
# Wirelang-side PR is still under review), the driver gracefully
# degrades to the marker-stack family only. Same constants-only
# probe + fallback as the marker-stack family above.
try:  # pragma: no cover - constants-only probe
    from wirelang.federation.sequence_number_ledger_kv_constants import (  # noqa: E402
        BUCKET_CONFIG as SEQUENCE_LEDGER_BUCKET_CONFIG,
        BUCKET_NAME_PREFIX as SEQUENCE_LEDGER_BUCKET_NAME_PREFIX,
        bucket_name_for_org as _sequence_ledger_bucket_name_for_org,
    )
    _HAS_SEQUENCE_LEDGER_FAMILY = True
except ImportError:  # pragma: no cover - fall back to full module
    try:
        from wirelang.federation.sequence_number_ledger_kv import (  # noqa: E402
            BUCKET_CONFIG as SEQUENCE_LEDGER_BUCKET_CONFIG,
            BUCKET_NAME_PREFIX as SEQUENCE_LEDGER_BUCKET_NAME_PREFIX,
            bucket_name_for_org as _sequence_ledger_bucket_name_for_org,
        )
        _HAS_SEQUENCE_LEDGER_FAMILY = True
    except ImportError:
        SEQUENCE_LEDGER_BUCKET_CONFIG = None  # type: ignore[assignment]
        SEQUENCE_LEDGER_BUCKET_NAME_PREFIX = None  # type: ignore[assignment]
        _sequence_ledger_bucket_name_for_org = None  # type: ignore[assignment]
        _HAS_SEQUENCE_LEDGER_FAMILY = False


# ---------------------------------------------------------------------------
# Bucket-family registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BucketFamily:
    """One per-org bucket family the driver provisions.

    Each family carries a stable ``family_id`` (used in JSON
    payloads and human logs), the canonical Wirelang-side prefix
    + config + derivation function. Fields are sourced byte-
    precisely from the Wirelang-side module that owns the family.
    """

    family_id: str
    bucket_name_prefix: str
    bucket_config: Mapping[str, Any]
    bucket_name_for_org: Any  # Callable[[str], str]


def _registered_families() -> List[BucketFamily]:
    """Return the registered per-org bucket families.

    Order is deterministic: marker-stack first (Sprint-8 Tag-4
    legacy alphabetical anchor), sequence-ledger second when
    available (Sprint-9 Tag-2 paired-update).
    """
    families: List[BucketFamily] = [
        BucketFamily(
            family_id="marker-stack",
            bucket_name_prefix=MARKER_STACK_BUCKET_NAME_PREFIX,
            bucket_config=MARKER_STACK_BUCKET_CONFIG,
            bucket_name_for_org=_marker_stack_bucket_name_for_org,
        ),
    ]
    if _HAS_SEQUENCE_LEDGER_FAMILY:
        families.append(
            BucketFamily(
                family_id="sequence-ledger",
                bucket_name_prefix=SEQUENCE_LEDGER_BUCKET_NAME_PREFIX,
                bucket_config=SEQUENCE_LEDGER_BUCKET_CONFIG,
                bucket_name_for_org=_sequence_ledger_bucket_name_for_org,
            )
        )
    return families


BUCKET_FAMILIES: List[BucketFamily] = _registered_families()


# ---------------------------------------------------------------------------
# Action records
# ---------------------------------------------------------------------------


@dataclass
class BucketAction:
    """One planner decision for one per-org bucket.

    ``status`` is one of ``"created"``, ``"unchanged"``, ``"drift"``,
    ``"would_create"`` (dry-run), or ``"error"``. ``family`` is the
    bucket-family identifier (e.g. ``"marker-stack"``,
    ``"sequence-ledger"``); empty string on Tag-1-shape error
    actions that fail before family resolution.
    """

    org_id: str
    bucket: str
    status: str
    detail: str = ""
    drift: dict = field(default_factory=dict)
    family: str = ""


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


def spec_for_org(
    org_id: str,
    *,
    family: Optional[BucketFamily] = None,
) -> Mapping[str, Any]:
    """Translate an ``org_id`` into the kwargs expected by
    ``nats.js.JetStreamContext.create_key_value``.

    The values are sourced byte-precisely from the family's
    ``bucket_config`` (single-source-of-truth on the Wirelang
    side); this function adds the ``bucket`` field (derived from
    ``org_id``) and re-keys the ``ttl_seconds`` field to the
    nats-py ``ttl`` name.

    ``family`` defaults to the marker-stack family for Tag-1
    backwards-compatibility. Pass a registered :class:`BucketFamily`
    to request the spec for a different family.

    Raises :class:`ValueError` for a malformed ``org_id`` (delegates
    to the family's ``bucket_name_for_org``).
    """
    fam = family if family is not None else BUCKET_FAMILIES[0]
    bucket = fam.bucket_name_for_org(org_id)
    cfg = fam.bucket_config
    return {
        "bucket": bucket,
        "description": str(cfg["description"]),
        "history": int(cfg["history"]),
        "ttl": int(cfg["ttl_seconds"]),
        "max_value_size": int(cfg["max_value_size"]),
        "storage": str(cfg["storage"]),
        "replicas": int(cfg["replicas"]),
    }


def _drift_diff(
    status: Mapping[str, Any],
    *,
    family: Optional[BucketFamily] = None,
) -> dict:
    """Return a dict of fields where ``status`` diverges from the
    family's canonical Wirelang-side ``BUCKET_CONFIG``.

    Empty dict == no drift. Each entry is
    ``{field: {"want": ..., "got": ...}}``. ``description`` is not
    checked (operators sometimes annotate it).

    ``family`` defaults to the marker-stack family for Tag-1
    backwards-compatibility.
    """
    fam = family if family is not None else BUCKET_FAMILIES[0]
    cfg = fam.bucket_config
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
    families: Optional[Sequence[BucketFamily]] = None,
) -> List[BucketAction]:
    """Idempotently ensure every registered per-org bucket exists
    for every requested ``org_id``.

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

    For every distinct ``org_id`` input the planner emits ONE action
    per registered family (in registry order: marker-stack first,
    then sequence-ledger when available). A malformed ``org_id``
    short-circuits the family loop with a single Tag-1-shape error
    action (matches the Tag-1 hermetic-test invariant that errored
    orgs do not get N action records).

    ``families`` defaults to :data:`BUCKET_FAMILIES`. Passing a
    custom sequence is the test-friendly hook for asserting the
    multi-family fan-out shape under controlled fixtures.

    Returns a list of :class:`BucketAction` records in stable order:
    org_id-major (input order, de-duplicated first-occurrence-wins),
    family-minor (registry order).
    """
    fams = list(families) if families is not None else list(BUCKET_FAMILIES)
    actions: List[BucketAction] = []
    seen_orgs: set[str] = set()
    for org_id in org_ids:
        if org_id in seen_orgs:
            # Idempotent input: ignore a repeated org_id silently.
            continue
        seen_orgs.add(org_id)

        # Pre-validate the org_id once before fanning out per
        # family: if the identifier is malformed every family
        # rejects it identically, so we emit ONE error action
        # (Tag-1-shape) rather than N.
        try:
            # Use the marker-stack family's derivation as the
            # canonical validator. Both registered families use
            # the same _ORG_ID_RE permitted-character pattern.
            _ = fams[0].bucket_name_for_org(org_id)
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

        for fam in fams:
            try:
                spec_kwargs = spec_for_org(org_id, family=fam)
            except ValueError as exc:
                # Defensive — already pre-validated above. Surface
                # any family-specific validator divergence as a
                # family-tagged error action.
                actions.append(
                    BucketAction(
                        org_id=org_id,
                        bucket="",
                        status="error",
                        detail=f"invalid org_id for family {fam.family_id}: {exc}",
                        family=fam.family_id,
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
                        family=fam.family_id,
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
                            family=fam.family_id,
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
                            family=fam.family_id,
                        )
                    )
                    continue
                actions.append(
                    BucketAction(
                        org_id=org_id,
                        bucket=bucket,
                        status="created",
                        detail=spec_kwargs["description"],
                        family=fam.family_id,
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
                        family=fam.family_id,
                    )
                )
                continue
            diffs = _drift_diff(status, family=fam)
            if diffs:
                actions.append(
                    BucketAction(
                        org_id=org_id,
                        bucket=bucket,
                        status="drift",
                        detail=(
                            f"live config diverges from "
                            f"{fam.family_id} BUCKET_CONFIG"
                        ),
                        drift=diffs,
                        family=fam.family_id,
                    )
                )
            else:
                actions.append(
                    BucketAction(
                        org_id=org_id,
                        bucket=bucket,
                        status="unchanged",
                        detail=spec_kwargs["description"],
                        family=fam.family_id,
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
    "BUCKET_FAMILIES",
    "BucketAction",
    "BucketFamily",
    "MARKER_STACK_BUCKET_CONFIG",
    "MARKER_STACK_BUCKET_NAME_PREFIX",
    "ProvisionReport",
    "SEQUENCE_LEDGER_BUCKET_CONFIG",
    "SEQUENCE_LEDGER_BUCKET_NAME_PREFIX",
    "_HAS_SEQUENCE_LEDGER_FAMILY",
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
