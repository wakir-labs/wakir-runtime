#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Operator health-check tool for the Phase-1b V-908 federation
# evaluator substrate.
#
# What it does
# ------------
#
# 1. Inspects the ``wakir-federation-routes`` NATS-JetStream KV bucket
#    that backs the Phase-1b federation route registry. The bucket
#    name and documented configuration come straight from the
#    ``wirelang.federation.route_registry_nats_kv_backend`` module
#    (single source of truth; this tool does not duplicate the
#    constants).
#
# 2. Performs a snapshot read of the bucket via
#    :class:`NatsKvRouteRegistry.snapshot` and reports operator-relevant
#    statistics: total entry count, count of entries currently inside
#    their ``[active_from, active_until)`` window, count of entries
#    carrying a non-``None`` ``wat_anchor_manifest_id`` (cross-review
#    Zone 2 surface), and the count of poisoned envelopes encountered
#    (entries that decode-fail and would abort a real evaluator pass).
#
# 3. Verifies the live bucket configuration against
#    :data:`route_registry_nats_kv_backend.BUCKET_CONFIG`. Drift is
#    reported in ``{want, got}`` form, never auto-corrected. The
#    drift contract is identical to ``check-nats-kv-health.py`` for
#    the four Phase-1 buckets.
#
# 4. Optional N2-evaluator smoke: when supplied a ``--probe-route``,
#    the tool runs one :meth:`FederationEvaluator.evaluate_federation_route`
#    against the live snapshot using a synthetic
#    :class:`FederationContext`. The smoke is gated behind the
#    ``--probe-route`` flag because it requires the operator to know
#    a route_id that exists in the registry; without the flag the
#    tool stays a pure structural health check.
#
# 5. Emits a structured JSON report on stdout (stable shape) plus a
#    human-readable progress log on stderr. JSON-on-stdout is the
#    contract operator-tooling pipelines parse (cron-driven monitoring
#    is a Sprint-3 follow-up; the JSON shape is stable for that
#    consumer).
#
# Why a separate tool from ``check-nats-kv-health.py``
# ----------------------------------------------------
#
# ``check-nats-kv-health.py`` is the Phase-1 NATS-KV substrate health
# probe. It checks the four Phase-1 buckets that the orchestrator
# read-through cache layer depends on; it does not understand the
# value envelopes, only the bucket configuration.
#
# This Tag-7 tool is the next layer up: it understands the V-908
# federation-route value envelope (schema URI, RFC 3339 timestamps,
# optional WAT anchor field) and exercises the N2 evaluator surface
# end-to-end. Keeping the tools separate respects domain boundaries:
# Phase-1 substrate health vs. Phase-1b V-908 evaluator health are
# operationally distinct concerns. An operator running the Phase-1b
# pilot wants both green; a Phase-1 cluster without federation
# routes only wants the Phase-1 tool green.
#
# Cross-reference: this tool consumes the wirelang-eng-side modules at
# ``wirelang/federation/n2_evaluator.py`` (Tag-3) and
# ``wirelang/federation/route_registry_nats_kv_backend.py`` (Tag-4)
# byte-precisely. It does not redeclare any of the wirelang-eng-owned
# constants; the only additions are operator-facing
# (CLI / JSON-shape / runbook §6).
#
# Usage
# -----
#
#   python3 scripts/check-federation-evaluator-health.py
#   python3 scripts/check-federation-evaluator-health.py --servers nats://prod:4222
#   python3 scripts/check-federation-evaluator-health.py --dry-run
#   python3 scripts/check-federation-evaluator-health.py --skip-jsz
#   python3 scripts/check-federation-evaluator-health.py \
#       --probe-route "wakir->partner-A->treasury" \
#       --probe-ftd-id "did:web:wakir.dev:ftd:v1"
#
# Authentication: reads ``WAKIR_NATS_TOKEN`` from the env if set,
# same convention as the Tag-2 / Tag-6 scripts. Phase-2 SPIFFE
# JWT-SVID auth is a follow-up tracked in the orchestrator runbook.
#
# Exit codes
# ----------
#
#   0  bucket present and at the documented configuration; snapshot
#      decoded cleanly; ``/jsz`` healthy (or skipped); optional
#      ``--probe-route`` smoke accepted (or not requested)
#   1  unrecoverable error: connection failure, ``nats-py`` missing,
#      ``/jsz`` HTTP non-2xx (when not skipped), invalid CLI args,
#      wirelang-eng-side module import failure
#   2  bucket missing OR drift detected OR poisoned envelope(s) in
#      snapshot OR optional ``--probe-route`` smoke rejected
#
# Tests
# -----
#
# Hermetic pytest suite at
# ``tests/orchestrator/test_check_federation_evaluator_health.py``.
# Live-smoke tests gated on ``WAKIR_NATS_LIVE=1`` run against a real
# cluster (Box-3 compose plus ``wakir-federation-routes`` bucket
# initialised by hand).

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------
# wirelang-eng-side single-source-of-truth import
# ---------------------------------------------------------------------
#
# This tool intentionally does NOT redeclare the bucket name or its
# configuration. The wirelang-eng-side module is the ratified source. A
# regression test (``test_bucket_config_matches_route_registry_backend``)
# pins this dependency.
#
# Import is best-effort at module load: tests that exercise the
# planner against the local mock surface need the symbols available.
# The CLI ``main`` re-checks the import and reports a clean exit-1
# error if the package is unavailable on the operator host.

try:
    from wirelang.federation.route_registry_nats_kv_backend import (
        BUCKET_NAME as WL_BUCKET_NAME,
        BUCKET_CONFIG as WL_BUCKET_CONFIG,
        VALUE_SCHEMA as WL_VALUE_SCHEMA,
        NatsKvRouteRegistry,
        RouteRegistryEnvelopeError,
    )
    from wirelang.federation.n2_evaluator import (
        FederationContext,
        FederationEvaluator,
        FederationPredicateError,
        InMemoryRouteRegistry,
        RouteRegistryEntry,
    )

    _WL_IMPORT_ERROR: Optional[BaseException] = None
except Exception as exc:  # pragma: no cover - import-error path
    WL_BUCKET_NAME = "wakir-federation-routes"
    WL_BUCKET_CONFIG = {}
    WL_VALUE_SCHEMA = "wakir.federation.route-registry-entry/1"
    NatsKvRouteRegistry = None  # type: ignore[assignment]
    RouteRegistryEnvelopeError = Exception  # type: ignore[assignment]
    FederationContext = None  # type: ignore[assignment]
    FederationEvaluator = None  # type: ignore[assignment]
    FederationPredicateError = Exception  # type: ignore[assignment]
    InMemoryRouteRegistry = None  # type: ignore[assignment]
    RouteRegistryEntry = None  # type: ignore[assignment]
    _WL_IMPORT_ERROR = exc


# ---------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------


@dataclass
class BucketCheck:
    """Live-cluster observation for the federation-routes bucket.

    ``status`` is one of ``"ok"``, ``"missing"``, ``"drift"``, ``"error"``.
    ``drift`` carries the per-field ``{want, got}`` diff; an empty dict
    means "no drift".
    """

    name: str
    status: str
    detail: str = ""
    drift: dict = field(default_factory=dict)


@dataclass
class SnapshotCheck:
    """Outcome of the bucket snapshot read.

    ``status`` is one of ``"ok"``, ``"poisoned"``, ``"skipped"``, ``"error"``.

    - ``ok``: snapshot decoded cleanly; counters populated.
    - ``poisoned``: at least one envelope failed to decode; the
      evaluator would abort against this bucket. Operator action
      required.
    - ``skipped``: dry-run, or bucket-missing chain.
    - ``error``: connection / API error.
    """

    status: str
    detail: str = ""
    total: int = 0
    active: int = 0
    expired: int = 0
    not_yet_active: int = 0
    with_wat_anchor: int = 0
    poisoned_keys: list = field(default_factory=list)


@dataclass
class EvaluatorProbe:
    """Outcome of the optional ``--probe-route`` N2-evaluator smoke.

    ``status`` is one of ``"ok"``, ``"reject"``, ``"skipped"``, ``"error"``.
    """

    status: str
    detail: str = ""
    route_id: Optional[str] = None
    ftd_id: Optional[str] = None
    error_kind: Optional[str] = None


@dataclass
class JszProbe:
    """Outcome of the ``/jsz`` HTTP connectivity probe."""

    status: str
    detail: str = ""
    http_status: Optional[int] = None


@dataclass
class FederationHealthReport:
    """One ``check-federation-evaluator-health`` invocation outcome."""

    servers: str
    jsz_url: str
    bucket_name: str
    dry_run: bool
    jsz: JszProbe
    bucket: BucketCheck
    snapshot: SnapshotCheck
    evaluator: EvaluatorProbe

    def to_json(self) -> str:
        return json.dumps(
            {
                "servers": self.servers,
                "jsz_url": self.jsz_url,
                "bucket_name": self.bucket_name,
                "dry_run": self.dry_run,
                "jsz": asdict(self.jsz),
                "bucket": asdict(self.bucket),
                "snapshot": asdict(self.snapshot),
                "evaluator": asdict(self.evaluator),
            },
            sort_keys=True,
            separators=(",", ":"),
        )


# ---------------------------------------------------------------------
# Bucket-config drift comparator
# ---------------------------------------------------------------------


def _bucket_config_drift(
    config: Mapping[str, Any], status: Mapping[str, Any]
) -> dict:
    """Return per-field ``{want, got}`` drift dict.

    Mirrors the comparison logic in ``check-nats-kv-health.py`` so
    operators see the same shape across the two tools. Five fields
    are checked: ``history``, ``ttl``, ``max_value_size``, ``storage``,
    ``replicas``. The ``ttl`` field is read from
    ``BUCKET_CONFIG["ttl_seconds"]`` and compared against the live
    ``status["ttl"]``; ``nats-py`` returns float seconds in some
    versions, which we coerce to int before comparison.
    """
    diffs: dict[str, dict[str, Any]] = {}

    spec_view = {
        "history": config.get("history"),
        "ttl": config.get("ttl_seconds"),
        "max_value_size": config.get("max_value_size"),
        "storage": config.get("storage"),
        "replicas": config.get("replicas"),
    }
    for key, want in spec_view.items():
        if want is None:
            continue
        got = status.get(key)
        if key == "ttl" and isinstance(got, float):
            got = int(got)
        if got is None:
            continue
        if got != want:
            diffs[key] = {"want": want, "got": got}
    return diffs


# ---------------------------------------------------------------------
# Bucket inspector (read-only)
# ---------------------------------------------------------------------


async def inspect_bucket(
    js: Any,
    bucket_name: str,
    config: Mapping[str, Any],
) -> tuple[BucketCheck, Optional[Any]]:
    """Inspect the federation-routes bucket against its documented config.

    Returns the :class:`BucketCheck` plus the raw KV handle (or
    ``None`` if the bucket is missing or an error occurred). The
    handle is reused by the snapshot phase so we only pay one
    ``js.key_value`` round-trip.
    """
    try:
        kv = await _safe_get_kv(js, bucket_name)
    except Exception as exc:
        return (
            BucketCheck(
                name=bucket_name, status="error", detail=repr(exc)
            ),
            None,
        )

    if kv is None:
        return (
            BucketCheck(
                name=bucket_name,
                status="missing",
                detail=(
                    "bucket is not present on the live cluster; create "
                    "it with the operator runbook §6.2 procedure"
                ),
            ),
            None,
        )

    try:
        status = await _status_as_mapping(kv)
    except Exception as exc:
        return (
            BucketCheck(
                name=bucket_name, status="error", detail=repr(exc)
            ),
            kv,
        )

    diffs = _bucket_config_drift(config, status)
    if diffs:
        return (
            BucketCheck(
                name=bucket_name,
                status="drift",
                detail=(
                    "live bucket config diverges from "
                    "route_registry_nats_kv_backend.BUCKET_CONFIG"
                ),
                drift=diffs,
            ),
            kv,
        )
    return (
        BucketCheck(
            name=bucket_name,
            status="ok",
            detail="federation-routes bucket present at documented configuration",
        ),
        kv,
    )


async def _safe_get_kv(js: Any, name: str) -> Optional[Any]:
    """NotFound-class-name heuristic. Same shape as the Tag-6 tool."""
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
    raw = await kv.status()
    if isinstance(raw, Mapping):
        return dict(raw)
    out: dict[str, Any] = {}
    for k in ("history", "ttl", "max_value_size", "storage", "replicas"):
        if hasattr(raw, k):
            out[k] = getattr(raw, k)
    return out


# ---------------------------------------------------------------------
# Snapshot inspector (read-only)
# ---------------------------------------------------------------------


async def snapshot_bucket(
    kv: Any,
    *,
    eval_now: datetime,
) -> SnapshotCheck:
    """Run a :class:`NatsKvRouteRegistry.snapshot` and tally statistics.

    The snapshot is read-only: it lists keys, reads each value, and
    decodes the envelope. Poisoned envelopes are caught per-key so
    one bad row does not hide statistics from the rest. The aggregate
    ``status`` is ``"poisoned"`` if at least one envelope failed.

    Statistics:

    - ``total``: number of keys observed in the bucket.
    - ``active``: entries whose window includes ``eval_now``.
    - ``expired``: entries whose ``active_until`` has passed.
    - ``not_yet_active``: entries whose ``active_from`` is in the
      future relative to ``eval_now``.
    - ``with_wat_anchor``: subset of ``total`` carrying a non-``None``
      ``wat_anchor_manifest_id`` (Z2 cross-review surface).
    - ``poisoned_keys``: list of route_ids whose envelope failed to
      decode.

    The snapshot does NOT run the N2 evaluator; that is the
    ``--probe-route`` phase. Keeping this phase pure-data means the
    operator gets a forensic view even when the evaluator surface
    is broken (e.g. a future protocol revision that the running
    binary does not yet understand).
    """
    if NatsKvRouteRegistry is None:  # pragma: no cover - import-error
        return SnapshotCheck(
            status="error",
            detail=(
                "wirelang-eng-side modules unavailable; "
                "see exit-code 1 contract in script header"
            ),
        )

    try:
        keys = await _list_keys(kv)
    except Exception as exc:
        return SnapshotCheck(
            status="error", detail=f"keys() failed: {exc!r}"
        )

    total = 0
    active = 0
    expired = 0
    not_yet_active = 0
    with_wat_anchor = 0
    poisoned: list[str] = []

    backend = NatsKvRouteRegistry(kv=kv)

    for key in keys:
        total += 1
        try:
            entry = await backend.get(key)
        except RouteRegistryEnvelopeError as exc:
            poisoned.append(key)
            continue
        except Exception as exc:
            return SnapshotCheck(
                status="error",
                detail=f"get({key!r}) raised {type(exc).__name__}: {exc}",
                total=total,
                active=active,
                expired=expired,
                not_yet_active=not_yet_active,
                with_wat_anchor=with_wat_anchor,
                poisoned_keys=poisoned,
            )

        if entry is None:
            # Tombstoned between list and get; subtract from total so
            # the report reflects observable rows only.
            total -= 1
            continue

        if entry.wat_anchor_manifest_id is not None:
            with_wat_anchor += 1

        if eval_now < entry.active_from:
            not_yet_active += 1
        elif (
            entry.active_until is not None
            and eval_now >= entry.active_until
        ):
            expired += 1
        else:
            active += 1

    if poisoned:
        return SnapshotCheck(
            status="poisoned",
            detail=(
                f"{len(poisoned)} envelope(s) failed to decode; "
                "the N2 evaluator would abort against this bucket"
            ),
            total=total,
            active=active,
            expired=expired,
            not_yet_active=not_yet_active,
            with_wat_anchor=with_wat_anchor,
            poisoned_keys=sorted(poisoned),
        )
    return SnapshotCheck(
        status="ok",
        detail=(
            f"snapshot decoded cleanly; {active}/{total} active at "
            f"{eval_now.isoformat()}"
        ),
        total=total,
        active=active,
        expired=expired,
        not_yet_active=not_yet_active,
        with_wat_anchor=with_wat_anchor,
        poisoned_keys=[],
    )


async def _list_keys(kv: Any) -> list:
    """Same adapter shape as the wirelang-eng-side backend."""
    if hasattr(kv, "keys"):
        result = kv.keys()
        if hasattr(result, "__await__"):
            result = await result
        if hasattr(result, "__aiter__"):
            collected: list = []
            async for k in result:
                collected.append(k)
            return collected
        return list(result)
    raise RuntimeError("KV handle has no keys() method")


# ---------------------------------------------------------------------
# Synthetic FederationContext for the optional N2-evaluator smoke
# ---------------------------------------------------------------------


def _build_synthetic_context(
    *,
    snapshot_registry: Any,
    ftd_id: str,
    eval_now: datetime,
) -> Any:
    """Build a synthetic :class:`FederationContext` for the smoke probe.

    The wirelang-eng-side ``FederationContext`` requires a verified
    ``FederatedResolveResult``; for the operator smoke we only need
    its ``ftd_id`` and ``verified_at`` fields. We therefore use a
    minimal duck-typed object rather than running a full
    federation_resolver pass; the smoke's purpose is to confirm
    the evaluator is wired-up against the live snapshot, not to
    re-verify the FTD chain (which has its own hermetic tests on
    the wirelang-eng side).
    """
    if FederationContext is None or FederationEvaluator is None:
        raise RuntimeError("wirelang-eng-side modules unavailable")

    @dataclass(frozen=True)
    class _SmokeResolve:
        ftd_id: str
        verified_at: datetime

    resolve = _SmokeResolve(ftd_id=ftd_id, verified_at=eval_now)
    return FederationContext(
        federated_resolve=resolve,
        route_registry=snapshot_registry,
        eval_now=eval_now,
    )


def evaluator_probe(
    *,
    snapshot_registry: Any,
    route_id: str,
    ftd_id: str,
    eval_now: datetime,
) -> EvaluatorProbe:
    """Run one ``federation_route`` smoke against the snapshot."""
    if FederationEvaluator is None:
        return EvaluatorProbe(
            status="error",
            detail="wirelang-eng-side modules unavailable",
            route_id=route_id,
            ftd_id=ftd_id,
        )

    try:
        ctx = _build_synthetic_context(
            snapshot_registry=snapshot_registry,
            ftd_id=ftd_id,
            eval_now=eval_now,
        )
    except Exception as exc:
        return EvaluatorProbe(
            status="error",
            detail=f"context build failed: {exc!r}",
            route_id=route_id,
            ftd_id=ftd_id,
        )

    evaluator = FederationEvaluator(ctx)
    try:
        evaluator.evaluate_federation_route(route_id)
    except FederationPredicateError as exc:
        return EvaluatorProbe(
            status="reject",
            detail=str(exc),
            route_id=route_id,
            ftd_id=ftd_id,
            error_kind=type(exc).__name__,
        )
    except Exception as exc:
        return EvaluatorProbe(
            status="error",
            detail=f"unexpected {type(exc).__name__}: {exc}",
            route_id=route_id,
            ftd_id=ftd_id,
            error_kind=type(exc).__name__,
        )
    return EvaluatorProbe(
        status="ok",
        detail=f"federation_route({route_id!r}) accepted",
        route_id=route_id,
        ftd_id=ftd_id,
    )


# ---------------------------------------------------------------------
# /jsz HTTP probe (re-used from Tag-6, kept local for drop-in copy)
# ---------------------------------------------------------------------


def probe_jsz(
    url: str,
    *,
    timeout_s: float = 3.0,
    urlopen: Any = None,
) -> JszProbe:
    """Probe the JetStream HTTP introspection endpoint.

    Same shape as the Tag-6 ``check-nats-kv-health.py`` probe; kept
    local so this script remains a single-file drop-in for an
    operator host.
    """
    if urlopen is None:
        from urllib.request import urlopen as _real_urlopen

        urlopen = _real_urlopen

    try:
        resp = urlopen(url, timeout=timeout_s)
    except Exception as exc:
        return JszProbe(
            status="unreachable",
            detail=f"{type(exc).__name__}: {exc}",
            http_status=None,
        )
    try:
        http_status = getattr(resp, "status", None)
        if http_status is None and hasattr(resp, "getcode"):
            http_status = resp.getcode()
        if http_status is None or not (200 <= int(http_status) < 300):
            return JszProbe(
                status="unreachable",
                detail=f"non-2xx status: {http_status}",
                http_status=int(http_status) if http_status is not None else None,
            )
        return JszProbe(
            status="ok",
            detail="JetStream introspection endpoint healthy",
            http_status=int(http_status),
        )
    finally:
        close = getattr(resp, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


# ---------------------------------------------------------------------
# Dry-run report renderer
# ---------------------------------------------------------------------


def _render_dry_run_report(
    servers: str, jsz_url: str
) -> FederationHealthReport:
    """Render a plan-only report. No I/O; matches CLI ``--dry-run``."""
    return FederationHealthReport(
        servers=servers,
        jsz_url=jsz_url,
        bucket_name=WL_BUCKET_NAME,
        dry_run=True,
        jsz=JszProbe(
            status="skipped",
            detail=f"dry-run: would probe /jsz at {jsz_url}",
            http_status=None,
        ),
        bucket=BucketCheck(
            name=WL_BUCKET_NAME,
            status="ok",
            detail=(
                "dry-run: would inspect "
                f"history={WL_BUCKET_CONFIG.get('history')} "
                f"ttl={WL_BUCKET_CONFIG.get('ttl_seconds')}s "
                f"max_value={WL_BUCKET_CONFIG.get('max_value_size')}B "
                f"storage={WL_BUCKET_CONFIG.get('storage')} "
                f"replicas={WL_BUCKET_CONFIG.get('replicas')}"
            ),
        ),
        snapshot=SnapshotCheck(
            status="skipped",
            detail="dry-run: would snapshot the bucket and tally statistics",
        ),
        evaluator=EvaluatorProbe(
            status="skipped",
            detail="dry-run: would run --probe-route smoke if requested",
        ),
    )


# ---------------------------------------------------------------------
# Exit-code contract
# ---------------------------------------------------------------------


def _exit_code_for(report: FederationHealthReport) -> int:
    """Documented exit code for the operator pipeline.

    Order of dominance (highest first):

    - 1 (unrecoverable): jsz unreachable (when not skipped) OR
      bucket inspection error OR snapshot error OR evaluator
      error-kind ``error`` (vs. ``reject``).
    - 2 (operational drift): bucket missing OR drift OR snapshot
      poisoned OR evaluator reject.
    - 0 (clean): everything ok.
    """
    if report.jsz.status == "unreachable":
        return 1
    if report.bucket.status == "error":
        return 1
    if report.snapshot.status == "error":
        return 1
    if report.evaluator.status == "error":
        return 1
    if report.bucket.status in ("missing", "drift"):
        return 2
    if report.snapshot.status == "poisoned":
        return 2
    if report.evaluator.status == "reject":
        return 2
    return 0


# ---------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check-federation-evaluator-health",
        description=(
            "Operator health-check for the Phase-1b V-908 federation "
            "evaluator substrate."
        ),
    )
    parser.add_argument(
        "--servers",
        default=os.environ.get("WAKIR_NATS_SERVERS", "nats://127.0.0.1:4222"),
        help=(
            "NATS server URL (default: env WAKIR_NATS_SERVERS or "
            "nats://127.0.0.1:4222)"
        ),
    )
    parser.add_argument(
        "--jsz-url",
        default=os.environ.get(
            "WAKIR_NATS_JSZ_URL", "http://127.0.0.1:8222/jsz"
        ),
        help="HTTP URL of the JetStream /jsz endpoint",
    )
    parser.add_argument(
        "--skip-jsz",
        action="store_true",
        help="Skip the /jsz HTTP probe (KV-only mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan only; do not connect or snapshot",
    )
    parser.add_argument(
        "--probe-route",
        default=None,
        help=(
            "Optional N2-evaluator smoke: a route_id to evaluate "
            "against the live snapshot. Requires --probe-ftd-id."
        ),
    )
    parser.add_argument(
        "--probe-ftd-id",
        default=None,
        help=(
            "FTD id to use as the synthetic FederationContext.ftd_id "
            "for the --probe-route smoke."
        ),
    )
    return parser


def _stderr_log(message: str) -> None:
    print(f"[check-federation-evaluator-health] {message}", file=sys.stderr)


async def _connect_and_run(
    *,
    servers: str,
    eval_now: datetime,
    probe_route: Optional[str],
    probe_ftd_id: Optional[str],
) -> tuple[BucketCheck, SnapshotCheck, EvaluatorProbe]:
    """Open one NATS connection, inspect, snapshot, optionally probe.

    Lazy import of ``nats-py`` so the script remains importable in a
    sandbox / on a host without the package; the live path needs it.
    """
    try:
        import nats  # type: ignore[import-not-found]
    except ImportError as exc:
        return (
            BucketCheck(
                name=WL_BUCKET_NAME,
                status="error",
                detail=f"nats-py not installed: {exc!r}",
            ),
            SnapshotCheck(
                status="error",
                detail="snapshot skipped: nats-py not installed",
            ),
            EvaluatorProbe(
                status="skipped" if probe_route is None else "error",
                detail="evaluator skipped: nats-py not installed",
                route_id=probe_route,
                ftd_id=probe_ftd_id,
            ),
        )

    token = os.environ.get("WAKIR_NATS_TOKEN")
    connect_kwargs: dict[str, Any] = {"servers": servers}
    if token:
        connect_kwargs["token"] = token

    nc = await nats.connect(**connect_kwargs)
    try:
        js = nc.jetstream()
        bucket_check, kv = await inspect_bucket(
            js, WL_BUCKET_NAME, WL_BUCKET_CONFIG
        )
        if kv is None or bucket_check.status in ("missing", "error"):
            snapshot = SnapshotCheck(
                status="skipped",
                detail=(
                    "snapshot skipped: bucket not available "
                    f"({bucket_check.status})"
                ),
            )
            evaluator = EvaluatorProbe(
                status=(
                    "skipped"
                    if probe_route is None
                    else "error"
                ),
                detail=(
                    "evaluator skipped: bucket not available"
                    if probe_route is not None
                    else "no probe requested"
                ),
                route_id=probe_route,
                ftd_id=probe_ftd_id,
            )
            return bucket_check, snapshot, evaluator

        snapshot = await snapshot_bucket(kv, eval_now=eval_now)

        if probe_route is None:
            evaluator = EvaluatorProbe(
                status="skipped",
                detail="no --probe-route requested",
            )
        elif probe_ftd_id is None:
            evaluator = EvaluatorProbe(
                status="error",
                detail="--probe-route requires --probe-ftd-id",
                route_id=probe_route,
            )
        elif snapshot.status not in ("ok",):
            evaluator = EvaluatorProbe(
                status="error",
                detail=(
                    "evaluator skipped: snapshot status is "
                    f"{snapshot.status!r}"
                ),
                route_id=probe_route,
                ftd_id=probe_ftd_id,
            )
        else:
            backend = NatsKvRouteRegistry(kv=kv)
            registry = await backend.snapshot()
            evaluator = evaluator_probe(
                snapshot_registry=registry,
                route_id=probe_route,
                ftd_id=probe_ftd_id,
                eval_now=eval_now,
            )

        return bucket_check, snapshot, evaluator
    finally:
        try:
            await nc.drain()
        except Exception:
            pass
        try:
            await nc.close()
        except Exception:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if _WL_IMPORT_ERROR is not None:
        _stderr_log(
            "wirelang-eng-side wirelang.federation modules unavailable: "
            f"{_WL_IMPORT_ERROR!r}"
        )
        _stderr_log(
            "ensure the wakir-runtime package is on PYTHONPATH "
            "or installed (see runbook §6.1)"
        )
        return 1

    if args.dry_run:
        report = _render_dry_run_report(args.servers, args.jsz_url)
        _stderr_log(
            f"dry-run: would inspect bucket {WL_BUCKET_NAME!r} at "
            f"{args.servers!r}"
        )
        sys.stdout.write(report.to_json())
        sys.stdout.write("\n")
        return 0

    if args.skip_jsz:
        jsz = JszProbe(
            status="skipped",
            detail="JSZ probe skipped via --skip-jsz",
            http_status=None,
        )
    else:
        jsz = probe_jsz(args.jsz_url)
        _stderr_log(f"jsz: {jsz.status} ({jsz.detail})")

    eval_now = datetime.now(timezone.utc)

    try:
        bucket_check, snapshot, evaluator = asyncio.run(
            _connect_and_run(
                servers=args.servers,
                eval_now=eval_now,
                probe_route=args.probe_route,
                probe_ftd_id=args.probe_ftd_id,
            )
        )
    except Exception as exc:
        _stderr_log(f"connect/run failed: {type(exc).__name__}: {exc}")
        bucket_check = BucketCheck(
            name=WL_BUCKET_NAME,
            status="error",
            detail=f"{type(exc).__name__}: {exc}",
        )
        snapshot = SnapshotCheck(
            status="error", detail="connect failure"
        )
        evaluator = EvaluatorProbe(
            status=(
                "skipped" if args.probe_route is None else "error"
            ),
            detail="connect failure",
            route_id=args.probe_route,
            ftd_id=args.probe_ftd_id,
        )

    _stderr_log(
        f"bucket: {bucket_check.status} | snapshot: {snapshot.status} "
        f"({snapshot.total} entries, {snapshot.active} active) | "
        f"evaluator: {evaluator.status}"
    )

    report = FederationHealthReport(
        servers=args.servers,
        jsz_url=args.jsz_url,
        bucket_name=WL_BUCKET_NAME,
        dry_run=False,
        jsz=jsz,
        bucket=bucket_check,
        snapshot=snapshot,
        evaluator=evaluator,
    )
    sys.stdout.write(report.to_json())
    sys.stdout.write("\n")
    return _exit_code_for(report)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
