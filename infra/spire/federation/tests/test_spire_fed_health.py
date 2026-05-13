# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Phase-2 Sprint-8 Tag-4
``spire-fed-health`` CLI / HTTP server.

Surfaces covered:

  * Status-Schema: the JSON body of ``/health`` carries the
    documented fields with stable types.
  * Liveness-Pfad: ``/live`` always returns HTTP 200 (the endpoint
    answered → it is alive), independent of bundle readiness.
  * Readiness-Pfad: ``/health`` returns 200/503/500 based on bundle
    state, active-key-count, and rotation-error flag.
  * Empty-Bundle-Edge-Case: a missing or empty JWKS file yields
    ``status="unready"`` with ``active_keys=0`` and HTTP 503 (NOT
    500 — empty bundle is a temporary state during initial bring-up,
    not an error).
  * Rotation-Mid-State: a two-key JWKS (post-rotate, pre-expire) is
    reported as healthy with active_keys=2 and last_rotation_at
    pointing at the NEW key's _wakir_issued_at.
  * Compute-Pure: the ``compute_status`` function is deterministic
    given fixed inputs (no clock leakage).
  * 404-on-other-paths: spurious paths return 404 with a
    structured JSON body.
  * Rotation-Error-Flag: --rotation-error → HTTP 500 status=error
    even when the bundle is otherwise readable.

All tests are network-hermetic: the HTTP server binds to ``127.0.0.1``
with port=0 (kernel-assigned ephemeral port) so the tests can run in
parallel without port collisions.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
FED_DIR = HERE.parent
HEALTH_PATH = FED_DIR / "bin" / "spire_fed_health.py"
FED_BUNDLE_PATH = FED_DIR / "bin" / "spire_fed_bundle.py"
ROTATOR_PATH = FED_DIR / "bin" / "spire_fed_bundle_rotator.py"


@pytest.fixture(scope="module")
def health_mod():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_health_under_test", HEALTH_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_health_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fed_bundle():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_for_health_tests", FED_BUNDLE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle_for_health_tests"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rotator():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_rotator_for_health_tests", ROTATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle_rotator_for_health_tests"] = mod
    spec.loader.exec_module(mod)
    return mod


# Canonical hermetic test timestamps.
T0 = datetime(2026, 5, 13, 0, 0, 0, tzinfo=timezone.utc)
T0_PLUS_1H = datetime(2026, 5, 13, 1, 0, 0, tzinfo=timezone.utc)
T0_PLUS_25H = datetime(2026, 5, 14, 1, 0, 0, tzinfo=timezone.utc)


def _seed_bundle(fed_bundle, td: str, dst: Path) -> Path:
    fed_bundle.main(["export", "--trust-domain", td, "--out", str(dst)])
    return dst


def _server_thread(server):
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


def _get(server, path: str) -> tuple[int, bytes, dict[str, str]]:
    host, port = server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    headers = dict(resp.getheaders())
    conn.close()
    return resp.status, body, headers


# ---------------------------------------------------------------------
# compute_status pure tests
# ---------------------------------------------------------------------


def test_compute_status_schema_shape(health_mod, fed_bundle, tmp_path):
    """The status document MUST carry the documented fields."""
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    status = health_mod.compute_status(
        trust_domain="wakir.test",
        bundle_path=bundle,
        now=T0,
        agent_connections=3,
    )
    # Top-level fields.
    assert status["_schema_version"] == 1
    assert status["status"] == "healthy"
    assert status["trust_domain"] == "wakir.test"
    assert status["active_keys"] == 1
    # last_rotation_at is None for the pre-rotation seed bundle (the
    # Tag-1 export does NOT carry _wakir_issued_at; only Tag-3 rotate
    # adds that marker).
    assert status["last_rotation_at"] is None
    assert status["agent_connections"] == 3
    # Checks substructure.
    checks = status["checks"]
    assert checks["bundle_present"] is True
    assert checks["bundle_non_empty"] is True
    assert checks["active_key_count_ok"] is True
    assert checks["rotation_error_state"] is False


def test_compute_status_empty_bundle_is_unready(health_mod, tmp_path):
    """A missing JWKS file → status=unready, active_keys=0."""
    missing = tmp_path / "does-not-exist.json"
    status = health_mod.compute_status(
        trust_domain="wakir.test",
        bundle_path=missing,
        now=T0,
        agent_connections=0,
    )
    assert status["status"] == "unready"
    assert status["active_keys"] == 0
    assert status["last_rotation_at"] is None
    assert status["checks"]["bundle_present"] is False
    assert status["checks"]["active_key_count_ok"] is False


def test_compute_status_malformed_bundle_is_unready(health_mod, tmp_path):
    """A JWKS file with garbage JSON → status=unready (NOT crash)."""
    p = tmp_path / "garbage.json"
    p.write_text("{ not json", encoding="utf-8")
    status = health_mod.compute_status(
        trust_domain="wakir.test",
        bundle_path=p,
        now=T0,
        agent_connections=0,
    )
    assert status["status"] == "unready"
    assert status["active_keys"] == 0
    assert status["checks"]["bundle_present"] is False


def test_compute_status_rotation_mid_state(
    health_mod, fed_bundle, rotator, tmp_path
):
    """Post-rotate + pre-expire two-key JWKS → healthy, active_keys=2,
    last_rotation_at = NEW key's _wakir_issued_at."""
    base = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "base.json")
    rotated = tmp_path / "rotated.json"
    rotator.main(
        [
            "rotate",
            "--trust-domain",
            "wakir.test",
            "--in-file",
            str(base),
            "--out",
            str(rotated),
            "--now",
            "2026-05-13T01:30:00+00:00",
            "--grace-seconds",
            "86400",
        ]
    )
    status = health_mod.compute_status(
        trust_domain="wakir.test",
        bundle_path=rotated,
        now=T0_PLUS_1H,
        agent_connections=2,
    )
    assert status["status"] == "healthy"
    assert status["active_keys"] == 2  # old (grace) + new (valid)
    # last_rotation_at points at the NEW key's _wakir_issued_at.
    assert status["last_rotation_at"] == "2026-05-13T01:30:00+00:00"


def test_compute_status_post_expire_single_key(
    health_mod, fed_bundle, rotator, tmp_path
):
    """After expire the bundle has exactly one (new) key → healthy,
    active_keys=1."""
    base = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "base.json")
    rotated = tmp_path / "rotated.json"
    expired = tmp_path / "expired.json"
    rotator.main(
        [
            "rotate",
            "--trust-domain",
            "wakir.test",
            "--in-file",
            str(base),
            "--out",
            str(rotated),
            "--now",
            "2026-05-13T01:30:00+00:00",
            "--grace-seconds",
            "86400",
        ]
    )
    rotator.main(
        [
            "expire",
            "--trust-domain",
            "wakir.test",
            "--in-file",
            str(rotated),
            "--out",
            str(expired),
            "--now",
            "2026-05-14T02:00:00+00:00",
        ]
    )
    status = health_mod.compute_status(
        trust_domain="wakir.test",
        bundle_path=expired,
        now=datetime(2026, 5, 14, 2, 1, 0, tzinfo=timezone.utc),
        agent_connections=0,
    )
    assert status["status"] == "healthy"
    assert status["active_keys"] == 1


def test_compute_status_rotation_error_overrides(
    health_mod, fed_bundle, tmp_path
):
    """rotation_error=True → status=error even with a readable bundle."""
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    status = health_mod.compute_status(
        trust_domain="wakir.test",
        bundle_path=bundle,
        now=T0,
        agent_connections=0,
        rotation_error=True,
    )
    assert status["status"] == "error"
    assert status["checks"]["rotation_error_state"] is True


def test_compute_status_min_active_keys_threshold(
    health_mod, fed_bundle, tmp_path
):
    """min_active_keys=2 with a single-key bundle → unready."""
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    status = health_mod.compute_status(
        trust_domain="wakir.test",
        bundle_path=bundle,
        now=T0,
        agent_connections=0,
        min_active_keys=2,
    )
    assert status["status"] == "unready"
    assert status["active_keys"] == 1
    assert status["checks"]["active_key_count_ok"] is False


def test_compute_status_invalid_trust_domain_rejected(health_mod, tmp_path):
    with pytest.raises(ValueError, match="trust-domain"):
        health_mod.compute_status(
            trust_domain="WAKIR.TEST",  # uppercase forbidden
            bundle_path=tmp_path / "x.json",
            now=T0,
            agent_connections=0,
        )


# ---------------------------------------------------------------------
# HTTP server tests
# ---------------------------------------------------------------------


def test_http_live_endpoint_always_200(health_mod, tmp_path):
    """``/live`` returns 200 even when the bundle file is missing."""
    missing = tmp_path / "missing.json"
    server = health_mod.serve(
        trust_domain="wakir.test",
        bundle_path=missing,
        bind_host="127.0.0.1",
        bind_port=0,
        agent_connections=0,
    )
    _server_thread(server)
    try:
        status, body, _ = _get(server, "/live")
        assert status == 200
        doc = json.loads(body)
        assert doc == {"status": "alive"}
    finally:
        server.shutdown()
        server.server_close()


def test_http_health_healthy_200(health_mod, fed_bundle, tmp_path):
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    server = health_mod.serve(
        trust_domain="wakir.test",
        bundle_path=bundle,
        bind_host="127.0.0.1",
        bind_port=0,
        agent_connections=5,
        now_provider=lambda: T0,
    )
    _server_thread(server)
    try:
        status, body, headers = _get(server, "/health")
        assert status == 200
        assert headers["Content-Type"] == "application/json"
        doc = json.loads(body)
        assert doc["status"] == "healthy"
        assert doc["trust_domain"] == "wakir.test"
        assert doc["active_keys"] == 1
        assert doc["agent_connections"] == 5
    finally:
        server.shutdown()
        server.server_close()


def test_http_health_unready_503_for_empty_bundle(health_mod, tmp_path):
    server = health_mod.serve(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        bind_host="127.0.0.1",
        bind_port=0,
        agent_connections=0,
    )
    _server_thread(server)
    try:
        status, body, _ = _get(server, "/health")
        assert status == 503
        doc = json.loads(body)
        assert doc["status"] == "unready"
        assert doc["active_keys"] == 0
    finally:
        server.shutdown()
        server.server_close()


def test_http_health_error_500_for_rotation_error(
    health_mod, fed_bundle, tmp_path
):
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    server = health_mod.serve(
        trust_domain="wakir.test",
        bundle_path=bundle,
        bind_host="127.0.0.1",
        bind_port=0,
        agent_connections=0,
        rotation_error=True,
        now_provider=lambda: T0,
    )
    _server_thread(server)
    try:
        status, body, _ = _get(server, "/health")
        assert status == 500
        doc = json.loads(body)
        assert doc["status"] == "error"
        assert doc["checks"]["rotation_error_state"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_http_ready_endpoint_compact_body(health_mod, fed_bundle, tmp_path):
    """``/ready`` returns the same status code as ``/health`` but a
    compact ``{"status": ...}`` body."""
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    server = health_mod.serve(
        trust_domain="wakir.test",
        bundle_path=bundle,
        bind_host="127.0.0.1",
        bind_port=0,
        agent_connections=0,
        now_provider=lambda: T0,
    )
    _server_thread(server)
    try:
        status, body, _ = _get(server, "/ready")
        assert status == 200
        doc = json.loads(body)
        assert doc == {"status": "healthy"}
        # No bloat — exactly one field.
        assert len(doc) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_http_unknown_path_404(health_mod, fed_bundle, tmp_path):
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    server = health_mod.serve(
        trust_domain="wakir.test",
        bundle_path=bundle,
        bind_host="127.0.0.1",
        bind_port=0,
        agent_connections=0,
    )
    _server_thread(server)
    try:
        status, body, _ = _get(server, "/no-such-thing")
        assert status == 404
        doc = json.loads(body)
        assert doc["status"] == "not_found"
        assert doc["path"] == "/no-such-thing"
    finally:
        server.shutdown()
        server.server_close()


def test_http_query_string_stripped(health_mod, fed_bundle, tmp_path):
    """Query strings on the path MUST NOT change endpoint routing."""
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    server = health_mod.serve(
        trust_domain="wakir.test",
        bundle_path=bundle,
        bind_host="127.0.0.1",
        bind_port=0,
        agent_connections=0,
        now_provider=lambda: T0,
    )
    _server_thread(server)
    try:
        status, body, _ = _get(server, "/health?source=prometheus")
        assert status == 200
        doc = json.loads(body)
        assert doc["status"] == "healthy"
    finally:
        server.shutdown()
        server.server_close()
