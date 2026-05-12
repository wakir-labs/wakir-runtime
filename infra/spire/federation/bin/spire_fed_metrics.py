# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""spire-fed-metrics — Prometheus-text-format metrics surface for the
Phase-2 Sprint-8 Tag-4 Federation-Bundle-Endpoint substrate.

Sibling of ``spire_fed_health``: where the health endpoint answers
``up/down/unready`` to a probe, the metrics endpoint exposes Counter
and Gauge time-series for a Prometheus scrape. The exposition format
is the Prometheus 0.0.4 text protocol — no client library, no
external dependency, no protobuf path. Hermetic by construction.

Metric surface (stable for Phase-2 Sprint-8 Tag-4; future evolution
follows the Prometheus naming/labelling convention):

  * ``wakir_federation_bundle_cache_hits_total{trust_domain}``
      Counter — number of JWKS cache hits served from local cache
      since this process started.

  * ``wakir_federation_bundle_cache_misses_total{trust_domain}``
      Counter — number of JWKS cache misses (forced re-fetch from
      peer's bundle-endpoint).

  * ``wakir_federation_rotation_events_total{trust_domain, type}``
      Counter (labelled). type ∈ {rotate, expire, cross-td-refuse}.
      - rotate: a ``spire-fed-bundle-rotator rotate`` invocation
        produced a new JWKS.
      - expire: a ``spire-fed-bundle-rotator expire`` invocation
        dropped expired keys.
      - cross-td-refuse: a rotation/expire attempt was REFUSED because
        the bundle's hermetic-fixture marker did not match the
        requested trust-domain (cross-trust-domain isolation guard).

  * ``wakir_federation_active_keys{trust_domain}``
      Gauge — number of non-expired keys currently in the bundle.

  * ``wakir_federation_agent_connections{trust_domain}``
      Gauge — number of SPIRE-Agent connections currently attached
      to this trust-domain's federation surface.

Counters are in-process additive — the metrics server hosts a single
``MetricsRegistry`` instance that the rotation orchestration code can
``increment_*`` against. Gauges are read on each scrape from the
current JWKS bundle on disk (no race-window).

Hermetic test surface:

  * Counter-Inkrement: register an increment, scrape, observe value.
  * Gauge-Updates: write a JWKS file with N active keys, scrape,
    observe ``wakir_federation_active_keys = N``.
  * Empty-Initial-State: a freshly-constructed registry exposes the
    metric NAMES with value 0 (Prometheus convention — no metric
    silently missing).
  * Metric-Schema: exposition contains the canonical HELP and TYPE
    headers for each metric name (Prometheus text-format spec).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import signal
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any


# Re-use the rotator's parsing primitives via sibling-file load (mirror
# of ``spire_fed_health``).
_HERE = Path(__file__).resolve().parent
_ROTATOR_PATH = _HERE / "spire_fed_bundle_rotator.py"


def _load_rotator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_rotator_helpers_for_metrics", _ROTATOR_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(
            f"could not load rotator helpers from {_ROTATOR_PATH}"
        )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_rotator = _load_rotator()
_validate_trust_domain = _rotator._validate_trust_domain
_key_status = _rotator._key_status


# ---------------------------------------------------------------------
# Metric registry
# ---------------------------------------------------------------------


_VALID_ROTATION_TYPES = frozenset({"rotate", "expire", "cross-td-refuse"})


class MetricsRegistry:
    """In-process metrics registry.

    Thread-safe (Lock-guarded). The registry owns Counter state; Gauge
    state is computed on each ``render()`` from the JWKS bundle file
    on disk.

    All metrics carry a ``trust_domain`` label populated from the
    ``trust_domain`` constructor argument; the registry is scoped to a
    single trust-domain. The rotator's ``cross-td-refuse`` counter is
    therefore COUNTED on the trust-domain that refused (i.e. the
    trust-domain whose bundle was the operation target).
    """

    def __init__(
        self,
        *,
        trust_domain: str,
        bundle_path: Path,
        agent_connections_provider: Any = None,
        now_provider: Any = None,
    ) -> None:
        self.trust_domain = _validate_trust_domain(trust_domain)
        self.bundle_path = Path(bundle_path)
        self._agent_connections_provider = agent_connections_provider
        self._now_provider = now_provider
        self._lock = Lock()

        self._cache_hits = 0
        self._cache_misses = 0
        self._rotation_events: dict[str, int] = {
            t: 0 for t in _VALID_ROTATION_TYPES
        }

    # ---- Counter mutators ----

    def increment_cache_hit(self, n: int = 1) -> None:
        with self._lock:
            self._cache_hits += n

    def increment_cache_miss(self, n: int = 1) -> None:
        with self._lock:
            self._cache_misses += n

    def increment_rotation_event(self, type_: str, n: int = 1) -> None:
        if type_ not in _VALID_ROTATION_TYPES:
            raise ValueError(
                f"rotation event type {type_!r} is not valid; "
                f"must be one of {sorted(_VALID_ROTATION_TYPES)}"
            )
        with self._lock:
            self._rotation_events[type_] += n

    # ---- Snapshot reads ----

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "rotation_events": dict(self._rotation_events),
            }

    # ---- Gauge calculation ----

    def _current_now(self) -> datetime:
        if callable(self._now_provider):
            return self._now_provider()
        return datetime.now(tz=timezone.utc)

    def _read_jwks(self) -> dict[str, Any] | None:
        if not self.bundle_path.exists():
            return None
        try:
            text = self.bundle_path.read_text(encoding="utf-8")
            if not text.strip():
                return None
            doc = json.loads(text)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
            return None
        return doc

    def active_keys(self) -> int:
        doc = self._read_jwks()
        if doc is None:
            return 0
        now = self._current_now()
        n = 0
        for jwk in doc.get("keys", []):
            if not isinstance(jwk, dict):
                continue
            try:
                status = _key_status(jwk, now)
            except ValueError:
                continue
            if status != "expired":
                n += 1
        return n

    def agent_connections(self) -> int:
        if callable(self._agent_connections_provider):
            try:
                return int(self._agent_connections_provider())
            except (TypeError, ValueError):
                return 0
        return 0

    # ---- Prometheus text-format exposition ----

    def render(self) -> str:
        """Render all metrics in Prometheus 0.0.4 text-format."""
        snap = self.snapshot()
        td = self.trust_domain
        active = self.active_keys()
        connections = self.agent_connections()

        lines: list[str] = []

        # cache_hits_total
        lines.append(
            "# HELP wakir_federation_bundle_cache_hits_total "
            "Number of JWKS bundle cache hits served from local cache."
        )
        lines.append(
            "# TYPE wakir_federation_bundle_cache_hits_total counter"
        )
        lines.append(
            f'wakir_federation_bundle_cache_hits_total'
            f'{{trust_domain="{td}"}} {snap["cache_hits"]}'
        )

        # cache_misses_total
        lines.append(
            "# HELP wakir_federation_bundle_cache_misses_total "
            "Number of JWKS bundle cache misses forcing a peer re-fetch."
        )
        lines.append(
            "# TYPE wakir_federation_bundle_cache_misses_total counter"
        )
        lines.append(
            f'wakir_federation_bundle_cache_misses_total'
            f'{{trust_domain="{td}"}} {snap["cache_misses"]}'
        )

        # rotation_events_total (multi-label)
        lines.append(
            "# HELP wakir_federation_rotation_events_total "
            "Number of bundle rotation lifecycle events by type."
        )
        lines.append(
            "# TYPE wakir_federation_rotation_events_total counter"
        )
        # Emit in stable label-sorted order for hermetic test parity.
        for type_ in sorted(_VALID_ROTATION_TYPES):
            lines.append(
                f'wakir_federation_rotation_events_total'
                f'{{trust_domain="{td}",type="{type_}"}} '
                f'{snap["rotation_events"][type_]}'
            )

        # active_keys gauge
        lines.append(
            "# HELP wakir_federation_active_keys "
            "Number of non-expired keys currently in the trust bundle."
        )
        lines.append(
            "# TYPE wakir_federation_active_keys gauge"
        )
        lines.append(
            f'wakir_federation_active_keys'
            f'{{trust_domain="{td}"}} {active}'
        )

        # agent_connections gauge
        lines.append(
            "# HELP wakir_federation_agent_connections "
            "Number of SPIRE-Agent connections currently attached."
        )
        lines.append(
            "# TYPE wakir_federation_agent_connections gauge"
        )
        lines.append(
            f'wakir_federation_agent_connections'
            f'{{trust_domain="{td}"}} {connections}'
        )

        # Prometheus text-format requires a trailing newline.
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------


class MetricsRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler exposing ``/metrics`` in Prometheus text-format.

    A bare GET to ``/`` returns a one-liner index pointing at
    ``/metrics`` (HTTP 200). Any other path returns HTTP 404.
    """

    quiet: bool = True
    registry: MetricsRegistry | None = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if not self.quiet:
            super().log_message(format, *args)

    def _send_text(
        self,
        status_code: int,
        body: str,
        content_type: str = "text/plain; version=0.0.4; charset=utf-8",
    ) -> None:
        payload = body.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/metrics":
            reg = type(self).registry
            if reg is None:
                self._send_text(500, "metrics registry not configured\n")
                return
            self._send_text(200, reg.render())
            return
        if path in ("/", "/index", "/index.html"):
            self._send_text(
                200,
                "wakir-spire-fed-metrics — see /metrics\n",
                content_type="text/plain; charset=utf-8",
            )
            return
        self._send_text(404, f"not found: {path}\n")


def serve(
    *,
    registry: MetricsRegistry,
    bind_host: str = "127.0.0.1",
    bind_port: int = 8445,
    verbose: bool = False,
) -> ThreadingHTTPServer:
    """Construct a metrics ThreadingHTTPServer. Caller drives the loop."""

    class _BoundHandler(MetricsRequestHandler):
        pass

    _BoundHandler.registry = registry
    _BoundHandler.quiet = not verbose

    return ThreadingHTTPServer((bind_host, bind_port), _BoundHandler)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spire-fed-metrics",
        description=(
            "Federation-Bundle-Endpoint Prometheus-text-format metrics "
            "surface (Phase-2 Sprint-8 Tag-4). Hosts an in-process "
            "metric registry; the rotation orchestration calls into "
            "the registry to increment counters."
        ),
    )
    p.add_argument("--trust-domain", required=True)
    p.add_argument("--bundle-path", required=True, type=Path)
    p.add_argument("--bind-host", default="127.0.0.1")
    p.add_argument("--bind-port", type=int, default=8445)
    p.add_argument(
        "--agent-connections",
        type=int,
        default=0,
        help=(
            "Initial agent-connection count to report on the "
            "wakir_federation_agent_connections gauge. The orchestrator "
            "wires a real provider in Phase-2c+."
        ),
    )
    p.add_argument(
        "--render-once",
        action="store_true",
        help=(
            "Render the metrics text-format ONCE to stdout and exit. "
            "Used by the hermetic test surface and by ``curl`` "
            "smoke-checks during Operator-Hand verification."
        ),
    )
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        registry = MetricsRegistry(
            trust_domain=args.trust_domain,
            bundle_path=args.bundle_path,
            agent_connections_provider=lambda: args.agent_connections,
        )
    except ValueError as exc:
        sys.stderr.write(f"spire-fed-metrics: error: {exc}\n")
        return 2

    if args.render_once:
        sys.stdout.write(registry.render())
        return 0

    server = serve(
        registry=registry,
        bind_host=args.bind_host,
        bind_port=args.bind_port,
        verbose=args.verbose,
    )
    sys.stderr.write(
        f"spire-fed-metrics: listening on http://{args.bind_host}:"
        f"{args.bind_port}/metrics (trust-domain={args.trust_domain}, "
        f"bundle-path={args.bundle_path})\n"
    )

    def _stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
