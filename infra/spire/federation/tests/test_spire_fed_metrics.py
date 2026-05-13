# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Phase-2 Sprint-8 Tag-4
``spire-fed-metrics`` Prometheus-text-format metrics surface.

Surfaces covered:

  * Metric-Schema: every metric name has the canonical ``# HELP``
    and ``# TYPE`` comment per Prometheus 0.0.4 text-format spec.
  * Counter-Inkrement: increment_cache_hit / increment_cache_miss /
    increment_rotation_event are visible in render() output.
  * Gauge-Updates: changing the JWKS file on disk changes the
    next render()'s active-keys gauge (no caching).
  * Empty-Initial-State: a fresh registry exposes all metric NAMES
    with value 0 (no silently-missing metrics).
  * Rotation-Event-Type-Validation: invalid type strings rejected.
  * HTTP-/metrics-Endpoint: serves the rendered text with correct
    Content-Type.
  * HTTP-Unknown-Path-404: spurious paths return 404.
  * Label-Order-Stable: re-rendering with no state change yields
    byte-identical output (determinism for OTS-style hashing).
"""

from __future__ import annotations

import http.client
import importlib.util
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
FED_DIR = HERE.parent
METRICS_PATH = FED_DIR / "bin" / "spire_fed_metrics.py"
FED_BUNDLE_PATH = FED_DIR / "bin" / "spire_fed_bundle.py"
ROTATOR_PATH = FED_DIR / "bin" / "spire_fed_bundle_rotator.py"


@pytest.fixture(scope="module")
def metrics_mod():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_metrics_under_test", METRICS_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_metrics_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fed_bundle():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_for_metrics_tests", FED_BUNDLE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle_for_metrics_tests"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rotator():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_rotator_for_metrics_tests", ROTATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle_rotator_for_metrics_tests"] = mod
    spec.loader.exec_module(mod)
    return mod


T0 = datetime(2026, 5, 13, 0, 0, 0, tzinfo=timezone.utc)
T0_PLUS_1H = datetime(2026, 5, 13, 1, 0, 0, tzinfo=timezone.utc)


def _seed_bundle(fed_bundle, td: str, dst: Path) -> Path:
    fed_bundle.main(["export", "--trust-domain", td, "--out", str(dst)])
    return dst


def _get(server, path: str) -> tuple[int, bytes, dict[str, str]]:
    host, port = server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    headers = dict(resp.getheaders())
    conn.close()
    return resp.status, body, headers


def _server_thread(server):
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------
# Registry: schema + initial state
# ---------------------------------------------------------------------


def test_empty_initial_state_all_metrics_named(metrics_mod, tmp_path):
    """A freshly-constructed registry MUST expose all five metric
    names with value 0 (Prometheus convention: no silently-missing
    metric)."""
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    text = reg.render()
    # All five metric names present.
    expected_names = {
        "wakir_federation_bundle_cache_hits_total",
        "wakir_federation_bundle_cache_misses_total",
        "wakir_federation_rotation_events_total",
        "wakir_federation_active_keys",
        "wakir_federation_agent_connections",
    }
    for name in expected_names:
        assert f"# HELP {name}" in text, f"missing HELP for {name}"
        assert f"# TYPE {name}" in text, f"missing TYPE for {name}"
    # Counter sums are zero (the rotation_events counter has three
    # labelled series, all zero).
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        # Each metric line ends with a space-separated value; in the
        # initial state every value is 0.
        if line.strip():
            value = line.split()[-1]
            assert value == "0", f"non-zero initial value: {line}"


def test_metric_types_per_prometheus_spec(metrics_mod, tmp_path):
    """# TYPE declarations MUST match the Prometheus spec literals."""
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    text = reg.render()
    assert (
        "# TYPE wakir_federation_bundle_cache_hits_total counter" in text
    )
    assert (
        "# TYPE wakir_federation_bundle_cache_misses_total counter" in text
    )
    assert (
        "# TYPE wakir_federation_rotation_events_total counter" in text
    )
    assert "# TYPE wakir_federation_active_keys gauge" in text
    assert "# TYPE wakir_federation_agent_connections gauge" in text


def test_text_format_trailing_newline(metrics_mod, tmp_path):
    """Prometheus text-format requires a trailing newline."""
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    text = reg.render()
    assert text.endswith("\n")


# ---------------------------------------------------------------------
# Counter increments
# ---------------------------------------------------------------------


def test_counter_increment_cache_hits(metrics_mod, tmp_path):
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    reg.increment_cache_hit()
    reg.increment_cache_hit(2)
    text = reg.render()
    assert (
        'wakir_federation_bundle_cache_hits_total'
        '{trust_domain="wakir.test"} 3' in text
    )


def test_counter_increment_cache_misses(metrics_mod, tmp_path):
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    reg.increment_cache_miss(5)
    text = reg.render()
    assert (
        'wakir_federation_bundle_cache_misses_total'
        '{trust_domain="wakir.test"} 5' in text
    )


def test_counter_rotation_events_multi_label(metrics_mod, tmp_path):
    """All three rotation_event types are emitted as distinct series."""
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    reg.increment_rotation_event("rotate", 4)
    reg.increment_rotation_event("expire", 2)
    reg.increment_rotation_event("cross-td-refuse", 1)
    text = reg.render()
    assert (
        'wakir_federation_rotation_events_total'
        '{trust_domain="wakir.test",type="rotate"} 4' in text
    )
    assert (
        'wakir_federation_rotation_events_total'
        '{trust_domain="wakir.test",type="expire"} 2' in text
    )
    assert (
        'wakir_federation_rotation_events_total'
        '{trust_domain="wakir.test",type="cross-td-refuse"} 1' in text
    )


def test_rotation_event_invalid_type_rejected(metrics_mod, tmp_path):
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    with pytest.raises(ValueError, match="rotation event type"):
        reg.increment_rotation_event("not-a-real-type")


# ---------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------


def test_gauge_active_keys_tracks_bundle_state(
    metrics_mod, fed_bundle, rotator, tmp_path
):
    """Mutating the JWKS file on disk MUST change the next render's
    active_keys gauge — no caching, no staleness."""
    bundle_path = tmp_path / "b.json"
    _seed_bundle(fed_bundle, "wakir.test", bundle_path)

    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=bundle_path,
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0_PLUS_1H,
    )
    # Single-key seed → gauge=1.
    text = reg.render()
    assert (
        'wakir_federation_active_keys{trust_domain="wakir.test"} 1' in text
    )

    # Rotate to two keys (in grace window at T0_PLUS_1H).
    rotated = tmp_path / "rotated.json"
    rotator.main(
        [
            "rotate",
            "--trust-domain",
            "wakir.test",
            "--in-file",
            str(bundle_path),
            "--out",
            str(rotated),
            "--now",
            "2026-05-13T00:30:00+00:00",
            "--grace-seconds",
            "86400",
        ]
    )
    # Re-target the registry at the rotated bundle.
    reg.bundle_path = rotated
    text2 = reg.render()
    assert (
        'wakir_federation_active_keys{trust_domain="wakir.test"} 2'
        in text2
    )


def test_gauge_agent_connections_from_provider(metrics_mod, tmp_path):
    """The agent_connections gauge comes from the provider callable."""
    state = {"n": 7}
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: state["n"],
        now_provider=lambda: T0,
    )
    text = reg.render()
    assert (
        'wakir_federation_agent_connections{trust_domain="wakir.test"} 7'
        in text
    )
    # Mutate the provider state — next render reflects the change.
    state["n"] = 3
    text2 = reg.render()
    assert (
        'wakir_federation_agent_connections{trust_domain="wakir.test"} 3'
        in text2
    )


def test_gauge_active_keys_empty_when_bundle_missing(metrics_mod, tmp_path):
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "definitely-not-here.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    text = reg.render()
    assert (
        'wakir_federation_active_keys{trust_domain="wakir.test"} 0' in text
    )


# ---------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------


def test_render_is_deterministic(metrics_mod, fed_bundle, tmp_path):
    """Two render() calls with no state change MUST produce
    bit-identical output (no timestamp leak, no map-iteration
    ordering surprises)."""
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=bundle,
        agent_connections_provider=lambda: 4,
        now_provider=lambda: T0,
    )
    reg.increment_cache_hit(2)
    reg.increment_rotation_event("rotate")
    a = reg.render()
    b = reg.render()
    assert a == b


# ---------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------


def test_http_metrics_endpoint_serves_text(
    metrics_mod, fed_bundle, tmp_path
):
    bundle = _seed_bundle(fed_bundle, "wakir.test", tmp_path / "b.json")
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=bundle,
        agent_connections_provider=lambda: 2,
        now_provider=lambda: T0,
    )
    reg.increment_cache_hit(11)
    server = metrics_mod.serve(
        registry=reg, bind_host="127.0.0.1", bind_port=0
    )
    _server_thread(server)
    try:
        status, body, headers = _get(server, "/metrics")
        assert status == 200
        assert headers["Content-Type"].startswith(
            "text/plain; version=0.0.4"
        )
        text = body.decode("utf-8")
        assert (
            'wakir_federation_bundle_cache_hits_total'
            '{trust_domain="wakir.test"} 11' in text
        )
        assert (
            'wakir_federation_active_keys'
            '{trust_domain="wakir.test"} 1' in text
        )
        assert (
            'wakir_federation_agent_connections'
            '{trust_domain="wakir.test"} 2' in text
        )
    finally:
        server.shutdown()
        server.server_close()


def test_http_unknown_path_returns_404(metrics_mod, tmp_path):
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    server = metrics_mod.serve(
        registry=reg, bind_host="127.0.0.1", bind_port=0
    )
    _server_thread(server)
    try:
        status, body, _ = _get(server, "/spurious")
        assert status == 404
        assert b"not found" in body
    finally:
        server.shutdown()
        server.server_close()


def test_http_root_index_points_to_metrics(metrics_mod, tmp_path):
    reg = metrics_mod.MetricsRegistry(
        trust_domain="wakir.test",
        bundle_path=tmp_path / "missing.json",
        agent_connections_provider=lambda: 0,
        now_provider=lambda: T0,
    )
    server = metrics_mod.serve(
        registry=reg, bind_host="127.0.0.1", bind_port=0
    )
    _server_thread(server)
    try:
        status, body, _ = _get(server, "/")
        assert status == 200
        assert b"/metrics" in body
    finally:
        server.shutdown()
        server.server_close()


def test_invalid_trust_domain_rejected(metrics_mod, tmp_path):
    with pytest.raises(ValueError, match="trust-domain"):
        metrics_mod.MetricsRegistry(
            trust_domain="UPPERCASE.test",
            bundle_path=tmp_path / "x.json",
            agent_connections_provider=lambda: 0,
        )
