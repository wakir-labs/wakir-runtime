# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""spire-fed-health — Federation-Bundle-Endpoint Health-Check substrate
for the Phase-2 Sprint-8 Tag-4 monitoring surface.

Today the SPIRE-Federation-Bundle-Endpoint (Tag-1) serves JWKS on
host port 8443 (wakir side) / 8444 (partner side). Operator-Hand and
monitoring tooling can only verify endpoint health by parsing the
JWKS document — there is no boolean ``up/down`` answer and no
``how-many-keys-active`` answer that a Prometheus scrape or a systemd
``ExecStartPost`` probe could consume.

Tag-4 splits this into two artefacts:

  * ``spire_fed_health`` (this module): a tiny HTTP server that
    exposes a ``/health`` endpoint returning a structured JSON
    status document. Liveness is "the endpoint replies"; readiness is
    "the bundle is non-empty AND at least one active key exists AND
    the rotation-system is not in an error state". Both states map
    to standard HTTP status codes (200 healthy, 503 unready).

  * ``spire_fed_metrics`` (sibling module): a Prometheus-text-format
    metrics endpoint covering cache hits/misses, rotation events,
    active-keys gauge, and agent-connection gauge.

Both modules are hermetic by construction:

  * No podman, no container, no live SPIRE — they read JWKS bundle
    files from the local filesystem (the same bundle files the
    Tag-1/Tag-3 CLIs produce).

  * No wall-clock dependency for status calculation — the
    ``last_rotation_at`` timestamp is read out of the JWKS keys'
    ``_wakir_issued_at`` marker, and the readiness check uses a
    ``now`` argument (defaults to wall-clock, but tests override via
    ``--now`` for determinism).

  * No network dependency — the HTTP server is bound to loopback by
    default and exits cleanly on SIGTERM.

The intent: this is the OPERATIONAL-OBSERVABILITY layer of the
Federation-Bundle-Endpoint substrate. Live SPIRE-Server health is the
upstream ``/opt/spire/bin/spire-server healthcheck`` invocation in the
Quadlet ``HealthCmd``; ``spire-fed-health`` adds the BUNDLE-side
introspection that scriptable monitoring tools (Prometheus blackbox,
systemd ConditionPathExists, manual ``curl``) can consume.

Status-document shape (stable for Phase-2 Sprint-8 Tag-4 — bumped via
SemVer-style ``_schema_version`` field for future evolution):

    {
      "_schema_version": 1,
      "status": "healthy" | "unready" | "error",
      "trust_domain": "wakir.test",
      "active_keys": 2,
      "last_rotation_at": "2026-05-13T01:30:00+00:00" | null,
      "agent_connections": 3,
      "checks": {
        "bundle_present": true,
        "bundle_non_empty": true,
        "active_key_count_ok": true,
        "rotation_error_state": false
      }
    }

The ``agent_connections`` field is a hermetic-fixture surface for
Tag-4: in Phase-2c+ it will be populated from the SPIRE-Agent's
``/run/spire/agent-sockets/api.sock`` admin-API or a Workload-API
counter. For now the server accepts ``--agent-connections N`` as a
CLI argument so the operator can wire it from an external source
(e.g. ``podman ps --filter network=wakir-federation --format json |
jq length``).
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
from typing import Any


# Re-use the rotator's parsing primitives via sibling-file load (the
# bin/ directory has no __init__.py — the Tag-1/Tag-3 CLIs are loaded
# the same way by the hermetic test surface). This keeps the trust-
# domain validation and key-status logic single-source-of-truth shared
# with the rotator, without forcing a package install step.
_HERE = Path(__file__).resolve().parent
_ROTATOR_PATH = _HERE / "spire_fed_bundle_rotator.py"


def _load_rotator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_rotator_helpers", _ROTATOR_PATH
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
_parse_iso_utc = _rotator._parse_iso_utc
_format_iso_utc = _rotator._format_iso_utc
_key_status = _rotator._key_status


_SCHEMA_VERSION = 1


def _read_jwks_or_none(path: Path) -> dict[str, Any] | None:
    """Read a JWKS file, returning ``None`` if the file is missing,
    empty, or unparseable. Shape-errors are surfaced as ``None`` so
    the readiness check can return ``unready`` rather than crashing
    the health server."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        doc = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    keys = doc.get("keys")
    if not isinstance(keys, list):
        return None
    return doc


def _count_active_keys(doc: dict[str, Any] | None, now: datetime) -> int:
    """Count keys that are not in 'expired' state at ``now``.

    A key is 'active' iff ``_key_status(jwk, now)`` is 'valid' or
    'grace'. Keys without rotation markers (no ``_wakir_not_after``)
    are 'valid' by definition (single-key bundles, pre-rotation).
    """
    if doc is None:
        return 0
    n = 0
    for jwk in doc.get("keys", []):
        if not isinstance(jwk, dict):
            continue
        try:
            status = _key_status(jwk, now)
        except ValueError:
            # Malformed ``_wakir_not_after`` — treat as inactive.
            continue
        if status != "expired":
            n += 1
    return n


def _latest_issued_at(doc: dict[str, Any] | None) -> str | None:
    """Return the latest ``_wakir_issued_at`` timestamp from the JWKS,
    formatted as ISO-8601 UTC. Returns ``None`` if no key carries the
    marker (pre-rotation bundles, malformed bundles)."""
    if doc is None:
        return None
    latest: datetime | None = None
    for jwk in doc.get("keys", []):
        if not isinstance(jwk, dict):
            continue
        stamp = jwk.get("_wakir_issued_at")
        if not isinstance(stamp, str):
            continue
        try:
            dt = _parse_iso_utc(stamp)
        except ValueError:
            continue
        if latest is None or dt > latest:
            latest = dt
    if latest is None:
        return None
    return _format_iso_utc(latest)


def compute_status(
    *,
    trust_domain: str,
    bundle_path: Path,
    now: datetime,
    agent_connections: int,
    rotation_error: bool = False,
    min_active_keys: int = 1,
) -> dict[str, Any]:
    """Compute the structured health-status document.

    Status mapping:
      * ``error``: rotation system is in an error state (caller-
        signalled via ``rotation_error=True``).
      * ``unready``: bundle is missing, malformed, empty, or has
        fewer than ``min_active_keys`` non-expired keys.
      * ``healthy``: all readiness checks pass.

    Liveness ("can answer the request") is implied by the function
    returning at all; this is the readiness model.
    """
    td = _validate_trust_domain(trust_domain)
    doc = _read_jwks_or_none(bundle_path)
    bundle_present = doc is not None
    bundle_non_empty = bundle_present and bool(doc.get("keys"))
    active_keys = _count_active_keys(doc, now)
    active_key_count_ok = active_keys >= min_active_keys
    last_rotation_at = _latest_issued_at(doc)

    if rotation_error:
        status = "error"
    elif not (bundle_present and bundle_non_empty and active_key_count_ok):
        status = "unready"
    else:
        status = "healthy"

    return {
        "_schema_version": _SCHEMA_VERSION,
        "status": status,
        "trust_domain": td,
        "active_keys": active_keys,
        "last_rotation_at": last_rotation_at,
        "agent_connections": agent_connections,
        "checks": {
            "bundle_present": bundle_present,
            "bundle_non_empty": bundle_non_empty,
            "active_key_count_ok": active_key_count_ok,
            "rotation_error_state": rotation_error,
        },
    }


# ---------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------


class HealthRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler exposing ``/health``, ``/healthz`` (alias),
    ``/live``, and ``/ready`` endpoints.

      * ``/health`` and ``/healthz``: full status document; HTTP 200
        if status=healthy, 503 if status=unready, 500 if status=error.
      * ``/live``: bare liveness probe — always 200 if the server can
        answer (response body: ``{"status": "alive"}``).
      * ``/ready``: readiness probe — same status codes as ``/health``
        but a smaller body (``{"status": "<state>"}``).
    """

    # Suppress the default request-logging chatter on stderr; the
    # operator can re-enable via ``--verbose``.
    quiet: bool = True

    # Class-level config injected by ``serve()``.
    config: dict[str, Any] | None = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if not self.quiet:
            super().log_message(format, *args)

    def _send_json(self, status_code: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _compute(self) -> dict[str, Any]:
        cfg = type(self).config
        if cfg is None:
            return {
                "_schema_version": _SCHEMA_VERSION,
                "status": "error",
                "trust_domain": "<unconfigured>",
                "active_keys": 0,
                "last_rotation_at": None,
                "agent_connections": 0,
                "checks": {
                    "bundle_present": False,
                    "bundle_non_empty": False,
                    "active_key_count_ok": False,
                    "rotation_error_state": True,
                },
            }
        now_provider = cfg.get("now_provider")
        if callable(now_provider):
            now = now_provider()
        else:
            now = datetime.now(tz=timezone.utc)
        return compute_status(
            trust_domain=cfg["trust_domain"],
            bundle_path=cfg["bundle_path"],
            now=now,
            agent_connections=cfg.get("agent_connections", 0),
            rotation_error=cfg.get("rotation_error", False),
            min_active_keys=cfg.get("min_active_keys", 1),
        )

    def _status_to_http(self, status: str) -> int:
        if status == "healthy":
            return 200
        if status == "unready":
            return 503
        return 500  # error

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0]
        if path in ("/live", "/liveness"):
            self._send_json(200, {"status": "alive"})
            return
        if path in ("/health", "/healthz", "/ready", "/readiness"):
            body = self._compute()
            code = self._status_to_http(body["status"])
            if path in ("/ready", "/readiness"):
                self._send_json(code, {"status": body["status"]})
            else:
                self._send_json(code, body)
            return
        self._send_json(404, {"status": "not_found", "path": path})


def serve(
    *,
    trust_domain: str,
    bundle_path: Path,
    bind_host: str = "127.0.0.1",
    bind_port: int = 8444,
    agent_connections: int = 0,
    rotation_error: bool = False,
    min_active_keys: int = 1,
    now_provider: Any = None,
    verbose: bool = False,
) -> ThreadingHTTPServer:
    """Construct (but do NOT block on) a ThreadingHTTPServer.

    The caller is responsible for invoking ``serve_forever()`` or
    ``handle_request()`` as appropriate. The hermetic test surface
    constructs the server, spawns a thread that calls
    ``serve_forever``, exercises the endpoints via ``http.client``,
    then calls ``shutdown()`` + ``server_close()`` to tear down.
    """
    cfg: dict[str, Any] = {
        "trust_domain": _validate_trust_domain(trust_domain),
        "bundle_path": Path(bundle_path),
        "agent_connections": int(agent_connections),
        "rotation_error": bool(rotation_error),
        "min_active_keys": int(min_active_keys),
        "now_provider": now_provider,
    }

    class _BoundHandler(HealthRequestHandler):
        pass

    _BoundHandler.config = cfg
    _BoundHandler.quiet = not verbose

    server = ThreadingHTTPServer((bind_host, bind_port), _BoundHandler)
    return server


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spire-fed-health",
        description=(
            "Federation-Bundle-Endpoint Health-Check HTTP-server "
            "(Phase-2 Sprint-8 Tag-4). Reads a JWKS file from disk "
            "and exposes /health, /live, /ready over HTTP."
        ),
    )
    p.add_argument("--trust-domain", required=True)
    p.add_argument(
        "--bundle-path",
        required=True,
        type=Path,
        help=(
            "Path to the JWKS file produced by spire-fed-bundle / "
            "spire-fed-bundle-rotator."
        ),
    )
    p.add_argument("--bind-host", default="127.0.0.1")
    p.add_argument("--bind-port", type=int, default=8444)
    p.add_argument(
        "--agent-connections",
        type=int,
        default=0,
        help=(
            "Number of active SPIRE-Agent connections to report. "
            "Phase-2 Sprint-8 Tag-4: operator-provided integer; "
            "Phase-2c+ will be auto-populated from the SPIRE-Agent "
            "Workload-API admin counter."
        ),
    )
    p.add_argument(
        "--rotation-error",
        action="store_true",
        help=(
            "Mark the rotation-system as being in an error state. The "
            "/health endpoint then returns HTTP 500 with status=error."
        ),
    )
    p.add_argument(
        "--min-active-keys",
        type=int,
        default=1,
        help=(
            "Minimum number of non-expired keys required for readiness."
        ),
    )
    p.add_argument(
        "--once",
        action="store_true",
        help=(
            "Serve exactly one request, then exit (hermetic test "
            "surface)."
        ),
    )
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        server = serve(
            trust_domain=args.trust_domain,
            bundle_path=args.bundle_path,
            bind_host=args.bind_host,
            bind_port=args.bind_port,
            agent_connections=args.agent_connections,
            rotation_error=args.rotation_error,
            min_active_keys=args.min_active_keys,
            verbose=args.verbose,
        )
    except ValueError as exc:
        sys.stderr.write(f"spire-fed-health: error: {exc}\n")
        return 2

    sys.stderr.write(
        f"spire-fed-health: listening on http://{args.bind_host}:"
        f"{args.bind_port}/ (trust-domain={args.trust_domain}, "
        f"bundle-path={args.bundle_path})\n"
    )

    if args.once:
        server.handle_request()
        server.server_close()
        return 0

    # Install a SIGTERM handler so ``systemctl stop`` exits cleanly.
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
