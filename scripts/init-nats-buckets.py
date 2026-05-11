#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Initialise the Phase-1b NATS-JetStream KV buckets used by the
# orchestrator read-through cache layer.
#
# What it does
# ------------
#
# 1. Connects to a NATS server (default ``nats://127.0.0.1:4222``)
#    using ``nats-py`` and the JetStream KV API.
# 2. Ensures the seven Phase-1 buckets exist with the documented
#    history / TTL / max_value_size / replicas / storage settings:
#
#      - ``wakir-schemas``                  Wirelang schema-registry
#                                           **cache** (Phase-1b; consumed
#                                           by ``wirelang.schemas.
#                                           registry_nats_kv_backend``,
#                                           Sprint-3 Tag-1)
#      - ``wakir-aip-cache``                AIP-Document resolver cache
#      - ``wakir-ftd-cache``                Federation-Trust-Document
#                                           cache
#      - ``wakir-ftd-poisoned``             FTD poison-list marker bucket
#      - ``wakir-schema-registry-entries``  Wirelang schema-registry
#                                           **source-of-truth storage**
#                                           (reserved for Phase-2
#                                           migration off the
#                                           ``wakir-schemas`` cache
#                                           bucket; 5th bucket added
#                                           Sprint-4 Tag-4 via the Z-B
#                                           paired-update with the
#                                           Wirelang-side track,
#                                           analogous to the Sprint-3
#                                           Tag-1 schema-registry
#                                           surface that established
#                                           the entry-envelope codec
#                                           ``wakir.wirelang.
#                                           schema-registry-entry/1``)
#      - ``wakir-federation-routes``        V-908 federation-route
#                                           registry consumed by the
#                                           Wirelang-side
#                                           ``wirelang.federation.
#                                           route_registry_nats_kv_
#                                           backend.NatsKvRouteRegistry``
#                                           (Sprint-2 Tag-4 backend +
#                                           Sprint-2 Tag-6 watch-stream
#                                           snapshot layer). Registered
#                                           as the 6th bucket Sprint-4
#                                           Tag-5 via the Z-B follow-up
#                                           paired-update, closing the
#                                           inventory-drift gap that
#                                           previously required an
#                                           operator-hand ``nats kv
#                                           add`` step per Runbook
#                                           §6.5
#      - ``wakir-capability-policies``      Capability-policy persistence
#                                           bucket, **reserved** for the
#                                           Phase-3 promotion of the
#                                           operator-local
#                                           ``--capability-registry``
#                                           JSON-file shape (Sprint-5
#                                           Tag-1 Wirelang publisher-CLI)
#                                           onto a cluster-wide
#                                           cross-invocation policy
#                                           store. Phase-1b / Phase-2
#                                           have NO live consumer on
#                                           this bucket; it is
#                                           registered ahead of time as
#                                           the 7th bucket Sprint-5
#                                           Tag-2 via the Z-B
#                                           paired-update with the
#                                           Wirelang-side track so the
#                                           Phase-3 operator bring-up
#                                           collapses into the routine
#                                           ``init-nats-buckets.py``
#                                           pass without an
#                                           out-of-band ``nats kv add``
#                                           step. The consumer-side
#                                           codec name and concrete
#                                           ``BUCKET_CONFIG`` constant
#                                           are owned by Reza
#                                           (Capability-Token-Layer
#                                           per Persona-Matrix §2);
#                                           the orchestrator side
#                                           ships a reservation-form
#                                           bucket-spec with
#                                           audit-friendly defaults
#                                           (history=10 for
#                                           rotation-audit, ttl
#                                           unbounded, 4 KiB max value
#                                           size mirroring the small
#                                           policy-marker shape of
#                                           ``wakir-ftd-poisoned``).
#                                           Cross-import mirror-test
#                                           against the Wirelang-side
#                                           ``BUCKET_CONFIG`` lands as
#                                           a follow-up once the
#                                           Reza-side encoder/decoder
#                                           module is committed
#                                           upstream.
#
# 3. Idempotency contract: re-running the script on a cluster that
#    already has the buckets is a no-op. If a bucket exists but with a
#    drift in its configuration (e.g. an operator manually changed the
#    history value), the script logs the drift and exits non-zero
#    *without* mutating the bucket. Reconfiguration is an explicit
#    operator action (use ``nats kv update`` or recreate by hand);
#    this script never silently overwrites operator state.
#
# 4. Emits a structured JSON report to stdout summarising the actions
#    taken (created / unchanged / drift) plus a human-readable line
#    log to stderr. JSON-on-stdout is the contract the orchestrator
#    container's init step parses on container start.
#
# Why a hand-rolled python script rather than a bash wrapper around
# the ``nats`` CLI: hermetic tests (the mock JetStream surface is
# trivial in python; mocking the CLI from bash is not), structured
# JSON output for the container init parser, and ADR-0035-Errata-1
# Phase-1b language choice. The script has zero dependency on the
# ``wakir-runtime`` package itself so an operator can copy it onto
# a jump host and run it against a remote NATS without installing
# the project. The only runtime dependency is ``nats-py``.
#
# Usage
# -----
#
#   python3 scripts/init-nats-buckets.py                  # local NATS
#   python3 scripts/init-nats-buckets.py --servers nats://prod:4222
#   python3 scripts/init-nats-buckets.py --dry-run        # plan only
#   python3 scripts/init-nats-buckets.py --bucket wakir-schemas
#
# Authentication: the script reads ``WAKIR_NATS_TOKEN`` from the
# environment if set and passes it as the JetStream connect token.
# Infisical-injected env is the Phase-1b convention; SPIFFE JWT-SVID
# auth is a Phase-2 follow-up tracked in the orchestrator runbook.
#
# Exit codes
# ----------
#
#   0  all requested buckets are at the documented configuration
#   1  unrecoverable connection error or invalid arguments
#   2  configuration drift detected (one or more existing buckets
#      do not match the documented configuration)
#
# Tests
# -----
#
# Hermetic pytest suite at
# ``tests/orchestrator/test_init_nats_buckets.py`` exercises the
# planner against an in-memory mock JetStream surface. The module is
# import-clean (no top-level NATS connect) so tests can call the
# functions directly without monkeypatching network code.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence


# ---------------------------------------------------------------------
# Bucket inventory (documented configuration)
# ---------------------------------------------------------------------
#
# The values below are the source-of-truth for the Phase-1 single-node
# NATS deployment. They mirror the bucket-config records in the
# orchestrator skeleton spec and the ``docs/runbooks/nats-kv-phase-1.md``
# runbook published with the Phase-1b Sprint-2 Tag-1 delivery.
#
# Drift-policy: any deviation between the live cluster and these values
# is a drift. The script reports drift, never auto-corrects it.

@dataclass(frozen=True)
class BucketSpec:
    """Documented configuration of a Phase-1 KV bucket."""

    name: str
    description: str
    history: int = 1
    ttl_seconds: int = 0  # 0 == unbounded
    max_value_size: int = 65_536  # 64 KiB
    storage: str = "file"
    replicas: int = 1


#: Inventory of Phase-1 NATS-JetStream KV buckets.
#:
#: Cross-references (Wirelang-side consumers, must stay byte-aligned;
#: a drift in any of these constants surfaces as a hermetic-test failure
#: in the consumer suite before it can hit a live cluster):
#:
#: * ``wakir-schemas`` — consumed by
#:   ``wirelang.schemas.registry_nats_kv_backend.NatsKvSchemaRegistry``
#:   (Phase-1b Sprint-3 Tag-1). The consumer pins its own
#:   ``BUCKET_CONFIG`` constant to the same field values; test
#:   ``T-SR-10`` (Wirelang suite) is the byte-precise anchor.
#:
#: * ``wakir-schema-registry-entries`` — **reserved** for the Phase-2
#:   schema-registry-storage migration. Phase-1b has no live consumer
#:   on this bucket; it is registered ahead of time so the operator
#:   bring-up procedure for Phase-2 collapses into the routine
#:   ``init-nats-buckets.py`` pass (no manual ``nats kv add`` step on
#:   the cluster). The bucket-config mirrors ``wakir-schemas`` so the
#:   Phase-2 migration is a value-copy without a config-drift step:
#:   same history (5), same max_value_size (256 KiB), same unbounded
#:   TTL. Sprint-4 Tag-4 paired-update with the Wirelang-side track,
#:   which owns the schema-registry consumer-side codec
#:   ``wakir.wirelang.schema-registry-entry/1``.
#:
#: * ``wakir-federation-routes`` — consumed by
#:   ``wirelang.federation.route_registry_nats_kv_backend.NatsKvRouteRegistry``
#:   (Sprint-2 Tag-4 read/write backend, Sprint-2 Tag-6 watch-stream
#:   snapshot layer). The Wirelang-side module exports
#:   ``BUCKET_NAME = "wakir-federation-routes"`` and a ``BUCKET_CONFIG``
#:   mapping (history=5, ttl_seconds=0, max_value_size=4096, storage=
#:   "file", replicas=1, description="V-908 federation-route registry
#:   (Phase-1b)"); the spec below mirrors those field values
#:   byte-precisely. Drift between the orchestrator-side and Wirelang-
#:   side constants is caught by the hermetic regression
#:   ``test_wakir_federation_routes_matches_wirelang_consumer_bucket_config``
#:   in the orchestrator suite plus the dual-anchor parity test
#:   ``test_inventory_matches_init_nats_buckets`` in the health-check
#:   suite. Sprint-4 Tag-5 paired-update closes the Sprint-2 Tag-7
#:   Z-B Schluss-Marker open follow-up that asked for this exact
#:   inventory entry; the hand-creation fallback (Runbook §6.5) is
#:   retained only as an out-of-band recreate recipe.
#:
#: * ``wakir-capability-policies`` — **reserved** for the Phase-3
#:   promotion of the operator-local ``--capability-registry``
#:   JSON-file shape (Sprint-5 Tag-1 Wirelang publisher-CLI; cf.
#:   ``wirelang/schemas/publisher_cli.py`` ``--capability-registry``
#:   / ``--gate`` flags and the Sprint-5 Tag-1 spec §5.13) onto a
#:   cluster-wide cross-invocation policy store. The bucket has NO
#:   live consumer in Phase-1b / Phase-2; it is registered ahead of
#:   time so the Phase-3 operator bring-up procedure collapses into
#:   the routine ``init-nats-buckets.py`` pass (no manual ``nats kv
#:   add`` step on the cluster). The concrete ``BUCKET_CONFIG``
#:   constant on the Wirelang-side will be exported by the
#:   Reza-owned encoder/decoder module when it lands (Capability-
#:   Token-Layer is Reza-owner per Persona-Matrix §2); the
#:   orchestrator side ships a reservation-form bucket-spec with
#:   audit-friendly defaults: ``history=10`` (capability-policy
#:   rotations want a deep audit trail, mirroring
#:   ``wakir-ftd-poisoned``), ``ttl_seconds=0`` (policies live until
#:   explicit rotation), ``max_value_size=4_096`` (a single
#:   serialised policy entry is small; mirrors the small-marker
#:   shape of ``wakir-ftd-poisoned``), ``storage="file"``,
#:   ``replicas=1`` (Phase-1 single-node). When the Wirelang-side
#:   module lands a ``BUCKET_CONFIG`` constant, a byte-mirror anchor
#:   test analogous to ``test_t_tag5_02_sixth_bucket_config_mirrors_
#:   wirelang_consumer_bucket_config`` lands as a follow-up; until
#:   then this entry stays in reservation-form (no cross-import
#:   pin). Sprint-5 Tag-2 paired-update with the Wirelang-side
#:   ``wakir-capability-policies`` Phase-3 reservation reference
#:   (Reza Sprint-5 Tag-1 §6 / Phase-3 follow-up slot, promoted to
#:   Sprint-5 Tag-2 add per Mira-Strategie-Hand 2026-05-11).
#:
#: Phase-1b boundary: the 5th bucket ``wakir-schema-registry-entries``
#: is created on cluster bring-up but is **not** consumed by any module
#: shipped in Phase-1b (Phase-2-reserved). The 6th bucket
#: ``wakir-federation-routes`` IS consumed by the Wirelang-side V-908
#: backend; pre-Sprint-4-Tag-5 the bucket was created out-of-band per
#: §6.5 of the runbook, this entry promotes it into the routine init
#: pass. The 7th bucket ``wakir-capability-policies`` is reserved for
#: Phase-3 capability-policy persistence — no Phase-1b / Phase-2
#: consumer ships on it; the bucket-spec lives in the inventory so the
#: future Phase-3 bring-up is value-copy only. Phase-2 schema-registry
#: migration (Wirelang-side OI-7-Phase-2 slot) will later switch
#: ``wirelang.schemas.registry_nats_kv_backend`` to point at the new
#: schema-registry-entries bucket (or layer a second backend over it;
#: the storage-vs-cache split is the consumer-side design decision the
#: Wirelang track owns).
PHASE_1_BUCKETS: tuple[BucketSpec, ...] = (
    BucketSpec(
        name="wakir-schemas",
        description="Wirelang schema registry cache (Phase-1)",
        history=5,
        ttl_seconds=0,
        max_value_size=262_144,  # 256 KiB
    ),
    BucketSpec(
        name="wakir-aip-cache",
        description="AIP-Document resolver cache (Phase-1)",
        history=1,
        ttl_seconds=3_600,
        max_value_size=65_536,
    ),
    BucketSpec(
        name="wakir-ftd-cache",
        description="Federation-Trust-Document cache (Phase-1)",
        history=1,
        ttl_seconds=3_600,
        max_value_size=65_536,
    ),
    BucketSpec(
        name="wakir-ftd-poisoned",
        description="Federation-Trust-Document poison-list marker (Phase-1)",
        history=10,
        ttl_seconds=0,
        max_value_size=4_096,
    ),
    BucketSpec(
        name="wakir-schema-registry-entries",
        description=(
            "Wirelang schema-registry source-of-truth storage "
            "(reserved Phase-2 migration off wakir-schemas cache)"
        ),
        history=5,
        ttl_seconds=0,
        max_value_size=262_144,  # 256 KiB, mirrors wakir-schemas
    ),
    BucketSpec(
        name="wakir-federation-routes",
        description="V-908 federation-route registry (Phase-1b)",
        history=5,
        ttl_seconds=0,
        max_value_size=4_096,  # mirrors Wirelang BUCKET_CONFIG
    ),
    BucketSpec(
        name="wakir-capability-policies",
        description=(
            "Capability-policy persistence (reserved Phase-3 promotion "
            "of operator-local --capability-registry JSON-file shape)"
        ),
        history=10,
        ttl_seconds=0,
        max_value_size=4_096,  # mirrors wakir-ftd-poisoned small-marker shape
    ),
)


# ---------------------------------------------------------------------
# Action records
# ---------------------------------------------------------------------


@dataclass
class BucketAction:
    """One planner decision for one bucket.

    ``status`` is one of ``"created"``, ``"unchanged"``, ``"drift"``,
    ``"would_create"`` (dry-run), or ``"error"``.
    """

    name: str
    status: str
    detail: str = ""
    drift: dict = field(default_factory=dict)


@dataclass
class InitReport:
    """Outcome of one ``init-nats-buckets`` invocation."""

    servers: str
    dry_run: bool
    actions: list = field(default_factory=list)

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


# ---------------------------------------------------------------------
# Planner (network-free; the JetStream-context surface is mock-friendly)
# ---------------------------------------------------------------------


def _spec_as_kv_config(spec: BucketSpec) -> dict[str, Any]:
    """Translate a ``BucketSpec`` into the kwargs expected by
    ``nats.js.JetStreamContext.create_key_value``.

    The ``nats-py`` API names are ``bucket``, ``description``,
    ``history``, ``ttl`` (seconds, int), ``max_value_size``,
    ``storage`` (``"file"`` or ``"memory"``), and ``replicas``.
    """
    return {
        "bucket": spec.name,
        "description": spec.description,
        "history": spec.history,
        "ttl": spec.ttl_seconds,
        "max_value_size": spec.max_value_size,
        "storage": spec.storage,
        "replicas": spec.replicas,
    }


def _bucket_status_drift(spec: BucketSpec, status: Mapping[str, Any]) -> dict:
    """Return a dict of fields where the live status diverges from the spec.

    Empty dict == no drift. Each entry is ``{field: {"want": ..., "got": ...}}``.
    Only fields that the planner can observe via the JetStream
    ``KeyValue.status()`` surface are checked. ``description`` is not
    asserted because some operators tweak it for runbook annotations.
    """
    diffs: dict[str, dict[str, Any]] = {}

    # nats-py surfaces these on KeyValueStatus
    spec_view = {
        "history": spec.history,
        "ttl": spec.ttl_seconds,
        "max_value_size": spec.max_value_size,
        "storage": spec.storage,
        "replicas": spec.replicas,
    }
    for key, want in spec_view.items():
        got = status.get(key)
        # nats-py status surfaces ttl as float seconds; normalise to int
        if key == "ttl" and isinstance(got, float):
            got = int(got)
        if got is None:
            # Field not observable on this status payload; skip rather
            # than false-positive-drift (different nats-py releases
            # surface different fields).
            continue
        if got != want:
            diffs[key] = {"want": want, "got": got}
    return diffs


async def plan_and_apply(
    js: Any,
    specs: Iterable[BucketSpec],
    *,
    dry_run: bool,
) -> list[BucketAction]:
    """Idempotently bring the live JetStream KV layout to ``specs``.

    ``js`` is a JetStream context with the ``nats-py`` API surface used
    here:

    - ``await js.key_value(bucket=name)`` raises if the bucket does not
      exist; otherwise returns a KV handle.
    - ``await kv.status()`` returns an object whose attributes include
      ``history``, ``ttl``, ``max_value_size``, ``storage``, ``replicas``
      (real ``nats-py``) or a Mapping-like object for the test mock.
    - ``await js.create_key_value(**spec_as_kv_config)`` creates a new
      bucket.

    The planner never deletes buckets. Drift is reported, not corrected.
    """
    actions: list[BucketAction] = []
    for spec in specs:
        try:
            existing = await _safe_get_kv(js, spec.name)
        except Exception as exc:
            actions.append(
                BucketAction(
                    name=spec.name, status="error", detail=repr(exc)
                )
            )
            continue

        if existing is None:
            if dry_run:
                actions.append(
                    BucketAction(
                        name=spec.name,
                        status="would_create",
                        detail=(
                            f"history={spec.history} "
                            f"ttl={spec.ttl_seconds}s "
                            f"max_value={spec.max_value_size}B "
                            f"storage={spec.storage} replicas={spec.replicas}"
                        ),
                    )
                )
                continue
            try:
                await js.create_key_value(**_spec_as_kv_config(spec))
            except Exception as exc:
                actions.append(
                    BucketAction(
                        name=spec.name, status="error", detail=repr(exc)
                    )
                )
                continue
            actions.append(
                BucketAction(
                    name=spec.name,
                    status="created",
                    detail=spec.description,
                )
            )
            continue

        # Bucket exists; check for drift.
        try:
            status = await _status_as_mapping(existing)
        except Exception as exc:
            actions.append(
                BucketAction(
                    name=spec.name, status="error", detail=repr(exc)
                )
            )
            continue
        diffs = _bucket_status_drift(spec, status)
        if diffs:
            actions.append(
                BucketAction(
                    name=spec.name,
                    status="drift",
                    detail="live config diverges from documented Phase-1 config",
                    drift=diffs,
                )
            )
        else:
            actions.append(
                BucketAction(
                    name=spec.name,
                    status="unchanged",
                    detail=spec.description,
                )
            )
    return actions


async def _safe_get_kv(js: Any, name: str) -> Optional[Any]:
    """Return a KV handle for ``name`` or ``None`` if the bucket is absent.

    ``nats-py`` raises a ``BucketNotFoundError`` for missing buckets;
    other transports may raise ``KeyError``. We treat any exception
    whose class name contains ``"NotFound"`` (or which is a plain
    ``KeyError``) as "bucket missing"; everything else propagates.
    """
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
    """Return the bucket status as a plain mapping for drift comparison.

    Real ``nats-py`` returns an object with attributes; mocks return
    a dict. We accept either.
    """
    raw = await kv.status()
    if isinstance(raw, Mapping):
        return dict(raw)
    out: dict[str, Any] = {}
    for k in ("history", "ttl", "max_value_size", "storage", "replicas"):
        if hasattr(raw, k):
            out[k] = getattr(raw, k)
    return out


# ---------------------------------------------------------------------
# Connection wrapper (only invoked from the CLI entry point)
# ---------------------------------------------------------------------


async def _connect_and_run(
    servers: str,
    specs: Sequence[BucketSpec],
    *,
    dry_run: bool,
    token: Optional[str],
) -> InitReport:
    """Real connection path used by ``main()``; not exercised in tests.

    Tests call ``plan_and_apply`` directly with an in-memory mock
    JetStream context. Keeping this connection wrapper out of the
    test path means we do not depend on ``nats-py`` being installed
    at unit-test time.
    """
    import nats  # type: ignore

    nc = await nats.connect(servers, token=token)
    try:
        js = nc.jetstream()
        actions = await plan_and_apply(js, specs, dry_run=dry_run)
    finally:
        await nc.drain()
    return InitReport(servers=servers, dry_run=dry_run, actions=actions)


# ---------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------


def _select_specs(
    requested: Optional[Sequence[str]],
    inventory: Sequence[BucketSpec] = PHASE_1_BUCKETS,
) -> list[BucketSpec]:
    """Filter the bucket inventory by ``--bucket`` selectors.

    Empty/None selector list means "all". Unknown names raise
    ``ValueError`` so the operator gets an immediate, loud failure
    rather than a silent no-op.
    """
    if not requested:
        return list(inventory)
    by_name = {spec.name: spec for spec in inventory}
    selected: list[BucketSpec] = []
    unknown: list[str] = []
    for name in requested:
        if name in by_name:
            selected.append(by_name[name])
        else:
            unknown.append(name)
    if unknown:
        known = ", ".join(sorted(by_name))
        raise ValueError(
            f"unknown bucket(s): {', '.join(unknown)}; known: {known}"
        )
    return selected


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="init-nats-buckets",
        description=(
            "Idempotent Phase-1b NATS-JetStream KV bucket initialiser."
        ),
    )
    p.add_argument(
        "--servers",
        default=os.environ.get("WAKIR_NATS_SERVERS", "nats://127.0.0.1:4222"),
        help="NATS server URL(s); falls back to $WAKIR_NATS_SERVERS or localhost",
    )
    p.add_argument(
        "--bucket",
        action="append",
        default=None,
        help="apply to a single bucket (repeatable); default is all Phase-1 buckets",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan but do not create any bucket",
    )
    return p


def _exit_code_for(report: InitReport) -> int:
    """Map a report to a process exit code per the documented contract."""
    if any(a.status == "error" for a in report.actions):
        return 1
    if report.drift > 0:
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        specs = _select_specs(args.bucket)
    except ValueError as exc:
        print(f"[init-nats-buckets] ERROR: {exc}", file=sys.stderr)
        return 1

    token = os.environ.get("WAKIR_NATS_TOKEN") or None

    try:
        report = asyncio.run(
            _connect_and_run(
                args.servers, specs, dry_run=args.dry_run, token=token
            )
        )
    except ImportError as exc:
        print(
            f"[init-nats-buckets] ERROR: nats-py is not installed: {exc}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"[init-nats-buckets] ERROR: connection or planner failure: {exc!r}",
            file=sys.stderr,
        )
        return 1

    # Stderr: human log; stdout: JSON report.
    for action in report.actions:
        line = f"[init-nats-buckets] {action.name}: {action.status}"
        if action.detail:
            line += f"  ({action.detail})"
        if action.drift:
            line += f"  drift={action.drift}"
        print(line, file=sys.stderr)
    print(report.to_json())
    return _exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
