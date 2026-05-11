#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Health-check tool for the Phase-1b NATS-JetStream KV substrate.
#
# What it does
# ------------
#
# 1. Probes the NATS server's JetStream HTTP endpoint (``/jsz``, default
#    ``http://127.0.0.1:8222/jsz``) for substrate connectivity. The
#    same endpoint that the compose ``healthcheck`` uses; a non-2xx
#    response means the JetStream subsystem is unreachable.
# 2. Connects via ``nats-py`` (JetStream KV API) and confirms each
#    documented Phase-1 bucket is present:
#
#      - ``wakir-schemas``                  Wirelang schema-registry
#                                           cache (consumed by
#                                           ``wirelang.schemas.
#                                           registry_nats_kv_backend``,
#                                           Sprint-3 Tag-1)
#      - ``wakir-aip-cache``                AIP-Document resolver cache
#      - ``wakir-ftd-cache``                Federation-Trust-Document
#                                           cache
#      - ``wakir-ftd-poisoned``             FTD poison-list marker bucket
#      - ``wakir-schema-registry-entries``  Wirelang schema-registry
#                                           storage (5th bucket added
#                                           Sprint-4 Tag-4, Phase-2-
#                                           reserved; no Phase-1b
#                                           consumer)
#
# 3. Compares each bucket's live configuration to the documented
#    Phase-1 inventory and reports any drift in {want, got} form.
#    Drift is reported, never auto-corrected. The contract mirrors
#    ``init-nats-buckets.py``: this tool only inspects, it never
#    creates or mutates a bucket.
#
# 4. Emits a structured JSON report to stdout (one document per
#    invocation) plus a human-readable progress log to stderr. The
#    JSON shape is the contract the operator-tooling pipeline parses
#    (cron-driven monitoring is a Sprint-3 follow-up; the JSON shape
#    is stable for that consumer).
#
# Why a separate tool from ``init-nats-buckets.py``: the init tool's
# job is to *create* buckets (one-shot, bring-up-time, write-side).
# The health-check tool's job is to *observe* the live cluster
# (read-only, repeatable, every-few-minutes-if-cron). Keeping them
# separate means an operator can run the health check on any Phase-1b
# node without write credentials, and the read-side cannot accidentally
# drift the cluster by re-applying configuration.
#
# Usage
# -----
#
#   python3 scripts/check-nats-kv-health.py                # local
#   python3 scripts/check-nats-kv-health.py --servers nats://prod:4222
#   python3 scripts/check-nats-kv-health.py --dry-run      # plan only
#   python3 scripts/check-nats-kv-health.py --bucket wakir-schemas
#   python3 scripts/check-nats-kv-health.py --skip-jsz     # KV-only
#
# Authentication: reads ``WAKIR_NATS_TOKEN`` from the env if set and
# passes it on the JetStream connect. Infisical-injected env is the
# Phase-1b convention; Phase-2 SPIFFE JWT-SVID auth is a follow-up.
#
# Exit codes
# ----------
#
#   0  every requested bucket is present and at the documented
#      configuration; ``/jsz`` returned a healthy payload (or was
#      explicitly skipped)
#   1  unrecoverable error: connection failure, ``nats-py`` missing,
#      ``/jsz`` HTTP non-2xx (when not skipped), invalid CLI args
#   2  at least one drift detected OR at least one bucket missing
#
# Tests
# -----
#
# Hermetic pytest suite at
# ``tests/orchestrator/test_check_nats_kv_health.py`` exercises the
# planner against an in-memory mock JetStream surface plus a stubbed
# urlopen for the ``/jsz`` probe. The module is import-clean (no
# top-level NATS / HTTP I/O) so tests can call the functions
# directly without monkeypatching network code. Live-smoke tests
# gated on ``WAKIR_NATS_LIVE=1`` run against a real cluster (Box-3
# compose) and are skipped by default.

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
# This module re-declares the inventory rather than importing it from
# ``init-nats-buckets.py``. Rationale: the init script lives at
# ``scripts/init-nats-buckets.py`` (a hyphenated filename, not a
# package) and importing it would force test infrastructure into both
# tools. The inventory is short and stable; duplicating it keeps each
# script standalone and copy-paste-friendly onto a jump host.
#
# A drift between the two inventories is caught by
# ``test_inventory_matches_init_nats_buckets``.

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
)


# ---------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------


@dataclass
class BucketCheck:
    """One observation for one bucket.

    ``status`` is one of:

    - ``"ok"``        -- bucket present and at documented configuration
    - ``"missing"``   -- bucket absent from the live cluster
    - ``"drift"``     -- bucket present but configuration diverges
    - ``"error"``     -- per-bucket exception caught while inspecting
    """

    name: str
    status: str
    detail: str = ""
    drift: dict = field(default_factory=dict)


@dataclass
class JszProbe:
    """Outcome of the ``/jsz`` HTTP connectivity probe.

    ``status`` is one of ``"ok"``, ``"unreachable"``, ``"skipped"``.
    ``http_status`` is the HTTP status code on a 2xx response, ``None``
    on skip / unreachable.
    """

    status: str
    detail: str = ""
    http_status: Optional[int] = None


@dataclass
class HealthReport:
    """Outcome of one ``check-nats-kv-health`` invocation."""

    servers: str
    jsz_url: str
    dry_run: bool
    jsz: JszProbe
    checks: list = field(default_factory=list)

    @property
    def ok(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")

    @property
    def missing(self) -> int:
        return sum(1 for c in self.checks if c.status == "missing")

    @property
    def drift(self) -> int:
        return sum(1 for c in self.checks if c.status == "drift")

    @property
    def error(self) -> int:
        return sum(1 for c in self.checks if c.status == "error")

    def to_json(self) -> str:
        return json.dumps(
            {
                "servers": self.servers,
                "jsz_url": self.jsz_url,
                "dry_run": self.dry_run,
                "jsz": asdict(self.jsz),
                "summary": {
                    "ok": self.ok,
                    "missing": self.missing,
                    "drift": self.drift,
                    "error": self.error,
                    "total": len(self.checks),
                },
                "checks": [asdict(c) for c in self.checks],
            },
            sort_keys=True,
            separators=(",", ":"),
        )


# ---------------------------------------------------------------------
# JetStream KV inspector (network-free; mock-friendly)
# ---------------------------------------------------------------------


def _bucket_status_drift(spec: BucketSpec, status: Mapping[str, Any]) -> dict:
    """Return a dict of fields where the live status diverges from the spec.

    Empty dict == no drift. Each entry is
    ``{field: {"want": ..., "got": ...}}``. Mirrors the comparison logic
    in ``init-nats-buckets.py`` so the two tools agree on what counts
    as drift; the cross-tool agreement is regression-tested.
    """
    diffs: dict[str, dict[str, Any]] = {}

    spec_view = {
        "history": spec.history,
        "ttl": spec.ttl_seconds,
        "max_value_size": spec.max_value_size,
        "storage": spec.storage,
        "replicas": spec.replicas,
    }
    for key, want in spec_view.items():
        got = status.get(key)
        if key == "ttl" and isinstance(got, float):
            got = int(got)
        if got is None:
            # Field not observable on this status payload; skip rather
            # than false-positive-drift.
            continue
        if got != want:
            diffs[key] = {"want": want, "got": got}
    return diffs


async def inspect_buckets(
    js: Any,
    specs: Iterable[BucketSpec],
) -> list[BucketCheck]:
    """Read-only inspection of the live cluster against ``specs``.

    ``js`` is a JetStream context with the ``nats-py`` API surface used
    here (same subset as ``init-nats-buckets.plan_and_apply``):

    - ``await js.key_value(bucket=name)`` raises if the bucket is
      absent; otherwise returns a KV handle.
    - ``await kv.status()`` returns an object whose attributes include
      ``history``, ``ttl``, ``max_value_size``, ``storage``, ``replicas``
      (real ``nats-py``) or a Mapping-like object for the test mock.

    The inspector NEVER calls ``create_key_value`` or any write API.
    Idempotence is trivial: it has no side effects.
    """
    checks: list[BucketCheck] = []
    for spec in specs:
        try:
            existing = await _safe_get_kv(js, spec.name)
        except Exception as exc:
            checks.append(
                BucketCheck(name=spec.name, status="error", detail=repr(exc))
            )
            continue

        if existing is None:
            checks.append(
                BucketCheck(
                    name=spec.name,
                    status="missing",
                    detail=(
                        "bucket is not present on the live cluster; run "
                        "scripts/init-nats-buckets.py to create it"
                    ),
                )
            )
            continue

        try:
            status = await _status_as_mapping(existing)
        except Exception as exc:
            checks.append(
                BucketCheck(name=spec.name, status="error", detail=repr(exc))
            )
            continue
        diffs = _bucket_status_drift(spec, status)
        if diffs:
            checks.append(
                BucketCheck(
                    name=spec.name,
                    status="drift",
                    detail="live config diverges from documented Phase-1 config",
                    drift=diffs,
                )
            )
        else:
            checks.append(
                BucketCheck(
                    name=spec.name,
                    status="ok",
                    detail=spec.description,
                )
            )
    return checks


async def _safe_get_kv(js: Any, name: str) -> Optional[Any]:
    """Return a KV handle for ``name`` or ``None`` if the bucket is absent.

    Same NotFound-class-name heuristic as in ``init-nats-buckets.py``.
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
    """Return the bucket status as a plain mapping for drift comparison."""
    raw = await kv.status()
    if isinstance(raw, Mapping):
        return dict(raw)
    out: dict[str, Any] = {}
    for k in ("history", "ttl", "max_value_size", "storage", "replicas"):
        if hasattr(raw, k):
            out[k] = getattr(raw, k)
    return out


# ---------------------------------------------------------------------
# /jsz HTTP connectivity probe
# ---------------------------------------------------------------------


def probe_jsz(
    url: str,
    *,
    timeout_s: float = 3.0,
    urlopen: Any = None,
) -> JszProbe:
    """Probe the JetStream HTTP introspection endpoint.

    ``urlopen`` is injectable for hermetic tests; default uses
    ``urllib.request.urlopen`` from the stdlib (no third-party HTTP
    dependency). A 2xx response is healthy; anything else maps to
    ``unreachable``.

    The probe deliberately does not parse the JSON body: a healthy
    ``/jsz`` response is sufficient evidence that JetStream is up;
    deeper introspection (stream counts, message counts) is out of
    scope for the Phase-1b health check.
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
        # urlopen returns an HTTPResponse-like object; ``.status`` is
        # the modern attribute, ``.getcode()`` is the legacy fallback.
        code = getattr(resp, "status", None)
        if code is None and hasattr(resp, "getcode"):
            code = resp.getcode()
        # Drain a small read to keep the connection clean (some test
        # stubs assert on read; real urlopen doesn't require it).
        try:
            resp.read(1)  # at most one byte; we never parse the body
        except Exception:
            pass
    finally:
        try:
            resp.close()
        except Exception:
            pass

    if isinstance(code, int) and 200 <= code < 300:
        return JszProbe(status="ok", detail="2xx from /jsz", http_status=code)
    return JszProbe(
        status="unreachable",
        detail=f"non-2xx from /jsz: {code!r}",
        http_status=code if isinstance(code, int) else None,
    )


# ---------------------------------------------------------------------
# Connection wrapper (only invoked from the CLI entry point)
# ---------------------------------------------------------------------


async def _connect_and_inspect(
    servers: str,
    specs: Sequence[BucketSpec],
    *,
    token: Optional[str],
) -> list[BucketCheck]:
    """Real connection path used by ``main()``; not exercised in tests.

    Tests call ``inspect_buckets`` directly with an in-memory mock
    JetStream context. Keeping this connection wrapper out of the
    test path means we do not depend on ``nats-py`` at unit-test time.
    """
    import nats  # type: ignore

    nc = await nats.connect(servers, token=token)
    try:
        js = nc.jetstream()
        return await inspect_buckets(js, specs)
    finally:
        await nc.drain()


# ---------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------


def _select_specs(
    requested: Optional[Sequence[str]],
    inventory: Sequence[BucketSpec] = PHASE_1_BUCKETS,
) -> list[BucketSpec]:
    """Filter the bucket inventory by ``--bucket`` selectors."""
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
        prog="check-nats-kv-health",
        description=(
            "Phase-1b NATS-JetStream KV substrate health check (read-only)."
        ),
    )
    p.add_argument(
        "--servers",
        default=os.environ.get(
            "WAKIR_NATS_SERVERS", "nats://127.0.0.1:4222"
        ),
        help="NATS server URL(s); falls back to $WAKIR_NATS_SERVERS or localhost",
    )
    p.add_argument(
        "--jsz-url",
        default=os.environ.get(
            "WAKIR_NATS_JSZ_URL", "http://127.0.0.1:8222/jsz"
        ),
        help="JetStream HTTP introspection URL (default loopback:8222/jsz)",
    )
    p.add_argument(
        "--bucket",
        action="append",
        default=None,
        help="check a single bucket (repeatable); default is all Phase-1 buckets",
    )
    p.add_argument(
        "--skip-jsz",
        action="store_true",
        help="skip the /jsz HTTP probe (KV-only health check)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "describe what would be checked but do not open any connection"
        ),
    )
    return p


def _exit_code_for(report: HealthReport) -> int:
    """Map a report to a process exit code per the documented contract.

    Contract:

    - exit 0 when every requested bucket is ``ok`` and ``/jsz`` is ok
      (or skipped).
    - exit 2 when at least one bucket is ``missing`` or ``drift`` and
      no error/connectivity issue is present.
    - exit 1 on a connectivity / per-bucket error or an unreachable
      ``/jsz`` (when not skipped). This dominates any drift signal:
      we cannot trust the drift reading if the substrate is not
      reachable.

    Drift dominates ``ok``; error/unreachable dominates drift. The
    ordering matches the cron-monitor consumer expectation
    (1=red/page, 2=yellow/triage, 0=green).
    """
    if report.error > 0:
        return 1
    if report.jsz.status == "unreachable":
        return 1
    if report.missing > 0 or report.drift > 0:
        return 2
    return 0


def _render_dry_run_report(
    servers: str,
    jsz_url: str,
    skip_jsz: bool,
    specs: Sequence[BucketSpec],
) -> HealthReport:
    """Build a no-side-effect plan report for ``--dry-run``."""
    jsz = JszProbe(
        status="skipped",
        detail=(
            "dry-run: would probe /jsz at "
            f"{jsz_url}" if not skip_jsz else "dry-run: --skip-jsz"
        ),
        http_status=None,
    )
    checks = [
        BucketCheck(
            name=spec.name,
            status="ok",
            detail=(
                "dry-run: would inspect "
                f"history={spec.history} "
                f"ttl={spec.ttl_seconds}s "
                f"max_value={spec.max_value_size}B "
                f"storage={spec.storage} replicas={spec.replicas}"
            ),
        )
        for spec in specs
    ]
    return HealthReport(
        servers=servers,
        jsz_url=jsz_url,
        dry_run=True,
        jsz=jsz,
        checks=checks,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        specs = _select_specs(args.bucket)
    except ValueError as exc:
        print(f"[check-nats-kv-health] ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        report = _render_dry_run_report(
            args.servers, args.jsz_url, args.skip_jsz, specs
        )
        for check in report.checks:
            print(
                f"[check-nats-kv-health] {check.name}: {check.status} ({check.detail})",
                file=sys.stderr,
            )
        print(report.to_json())
        # Dry-run never fails: no I/O, no possible drift.
        return 0

    # /jsz probe (skippable)
    if args.skip_jsz:
        jsz = JszProbe(status="skipped", detail="--skip-jsz")
    else:
        jsz = probe_jsz(args.jsz_url)

    token = os.environ.get("WAKIR_NATS_TOKEN") or None

    try:
        checks = asyncio.run(
            _connect_and_inspect(args.servers, specs, token=token)
        )
    except ImportError as exc:
        print(
            f"[check-nats-kv-health] ERROR: nats-py is not installed: {exc}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"[check-nats-kv-health] ERROR: connection or inspector failure: {exc!r}",
            file=sys.stderr,
        )
        return 1

    report = HealthReport(
        servers=args.servers,
        jsz_url=args.jsz_url,
        dry_run=False,
        jsz=jsz,
        checks=checks,
    )

    # Stderr: human log; stdout: JSON report.
    print(
        f"[check-nats-kv-health] /jsz: {report.jsz.status} ({report.jsz.detail})",
        file=sys.stderr,
    )
    for check in report.checks:
        line = f"[check-nats-kv-health] {check.name}: {check.status}"
        if check.detail:
            line += f"  ({check.detail})"
        if check.drift:
            line += f"  drift={check.drift}"
        print(line, file=sys.stderr)
    print(report.to_json())
    return _exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
