# SPDX-License-Identifier: BUSL-1.1
"""Tests for svid_workload_identity (Zone-L, spec §3.7.4 R3)."""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

from wirelang.persona_engine.svid_workload_identity import (
    DEFAULT_WORKLOAD_API_SOCKET_PATH,
    SPIFFE_ENDPOINT_SOCKET_ENV,
    SPIFFE_ID_TEMPLATE,
    SvidProbeResult,
    expected_spiffe_id_for,
    probe_workload_api_socket,
    resolve_socket_path,
)


def test_default_socket_path_constant_matches_quadlet():
    assert DEFAULT_WORKLOAD_API_SOCKET_PATH == "/run/spire/agent-sockets/api.sock"


def test_spiffe_id_template_shape():
    assert SPIFFE_ID_TEMPLATE == "spiffe://wakir.{org_id}/persona/{persona_id}"


def test_expected_spiffe_id_substitutes():
    sid = expected_spiffe_id_for("acme", "tomas")
    assert sid == "spiffe://wakir.acme/persona/tomas"


def test_resolve_socket_path_default():
    p = resolve_socket_path({})
    assert p == DEFAULT_WORKLOAD_API_SOCKET_PATH


def test_resolve_socket_path_from_env_with_unix_prefix():
    p = resolve_socket_path(
        {SPIFFE_ENDPOINT_SOCKET_ENV: "unix:///var/run/foo.sock"}
    )
    assert p == "/var/run/foo.sock"


def test_resolve_socket_path_from_env_without_prefix():
    p = resolve_socket_path({SPIFFE_ENDPOINT_SOCKET_ENV: "/tmp/bar.sock"})
    assert p == "/tmp/bar.sock"


def test_probe_socket_absent(tmp_path):
    nonexistent = tmp_path / "no-such-sock"
    result = probe_workload_api_socket(
        org_id="acme",
        persona_id="tomas",
        socket_path=str(nonexistent),
    )
    assert result.socket_present is False
    assert result.socket_connectable is False
    assert result.expected_spiffe_id == "spiffe://wakir.acme/persona/tomas"


def test_probe_socket_present_and_connectable(tmp_path):
    sock_path = tmp_path / "api.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_path))
    srv.listen(1)
    try:
        result = probe_workload_api_socket(
            org_id="acme",
            persona_id="tomas",
            socket_path=str(sock_path),
            timeout_sec=1.0,
        )
        assert result.socket_present is True
        assert result.socket_connectable is True
    finally:
        srv.close()


def test_probe_returns_rfc3339_timestamp(tmp_path):
    result = probe_workload_api_socket(
        org_id="acme",
        persona_id="tomas",
        socket_path=str(tmp_path / "nope"),
    )
    # RFC 3339 second-precision UTC: 2026-05-15T15:00:00Z shape
    assert result.probed_at_utc.endswith("Z")
    assert "T" in result.probed_at_utc
    assert len(result.probed_at_utc) == 20  # YYYY-MM-DDTHH:MM:SSZ
