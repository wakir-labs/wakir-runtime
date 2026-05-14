# SPDX-License-Identifier: BUSL-1.1
"""Hermetic tests for the Sprint-7 Pfad-B Tag-6 live HTTPS fetcher
(:mod:`wirelang.federation.spire_fed_bundle_live_https_fetcher`).

Hermeticity model
=================

These tests are **fully hermetic** — they do NOT depend on a live
SPIRE-Server, on the wakir-pilot/wakir-orbit VMs, on podman, or on
any operator-hand artefact. The wire-protocol surface (HTTPS GET
against a TLS endpoint) is stood up via :class:`http.server.
ThreadingHTTPServer` bound to loopback on an ephemeral port. The
TLS layer is provisioned with a self-signed cert generated in-test
via :mod:`cryptography`'s X.509 surface (already a project
dependency, see `pyproject.toml` ``dependencies`` list).

Mutation-Coverage matrix (Zone-Q-style)
=======================================

Each fail-closed gate has at least one positive test (a wire shape
that triggers it) and at least one negative test (a wire shape that
bypasses it but still surfaces a structurally distinct outcome):

+----------------------------+--------------------+------------------------+
| Error class                | Positive test      | Negative complement    |
+============================+====================+========================+
| ``UnpinnedTrustDomainError``| T-LIVE-HTTPS-03    | T-LIVE-HTTPS-01,02     |
+----------------------------+--------------------+------------------------+
| ``UrlTrustDomainMismatchError``| T-LIVE-HTTPS-04| T-LIVE-HTTPS-01        |
+----------------------------+--------------------+------------------------+
| ``LiveBundleFetchError``   | T-LIVE-HTTPS-05    | T-LIVE-HTTPS-01        |
+----------------------------+--------------------+------------------------+
| ``LiveBundleHttpStatusError``| T-LIVE-HTTPS-06,07| T-LIVE-HTTPS-01        |
+----------------------------+--------------------+------------------------+
| ``LiveBundleTimeoutError`` | T-LIVE-HTTPS-08    | T-LIVE-HTTPS-01        |
+----------------------------+--------------------+------------------------+
| ``LiveBundleTlsError``     | T-LIVE-HTTPS-09    | T-LIVE-HTTPS-01,02     |
+----------------------------+--------------------+------------------------+

Posture-validation gate (ValueError on ambiguous TLS posture) has
its own positive cases at T-LIVE-HTTPS-11,12.

Live-Integration opt-in
=======================

The test ``T-LIVE-INT`` is skipped by default. Set the env-var
``WAKIR_LIVE_PARTNER_URL`` to a SPIRE-Server bundle endpoint URL
(e.g. ``https://wakir-orbit:8443``) to opt in. The live test
exercises only the happy-path against a real SPIRE-Server; the
hermetic suite covers every fail-closed gate.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import http.server
import os
import socket
import ssl
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator, Optional, Tuple

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from wirelang.federation import (
    FetchedTrustBundle,
)
from wirelang.federation.spire_fed_bundle_live_https_fetcher import (
    DEFAULT_FETCH_TIMEOUT_SECONDS,
    LiveBundleFetchError,
    LiveBundleHttpStatusError,
    LiveBundleTimeoutError,
    LiveBundleTlsError,
    LiveHttpsSpireFedBundleFetcher,
    MAX_BUNDLE_BYTES,
    SPIRE_FED_BUNDLE_LIVE_HTTPS_FETCHER_SCHEMA,
)
from wirelang.federation.spire_fed_bundle_peer_fetcher import (
    UnpinnedTrustDomainError,
    UrlTrustDomainMismatchError,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_FIXTURE_JWKS = (
    b'{"keys":[{"kty":"EC","crv":"P-256","kid":"hermetic-test-key",'
    b'"use":"x509-svid","x":"AAAA","y":"BBBB"}]}'
)


def _make_self_signed_cert(
    hostname: str,
    tmp_path: Path,
) -> Tuple[Path, Path]:
    """Generate a self-signed RSA cert + key into ``tmp_path``.

    Returns ``(cert_path, key_path)``.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, hostname)]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(hostname), x509.DNSName("localhost")]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class _BundleHandler(http.server.BaseHTTPRequestHandler):
    """Per-test HTTP handler. Behaviour is steered by the
    ``mode`` attribute the server is configured with at startup."""

    server_version = "HermeticSpireMock/1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Silence test-server logs; the test harness prints failures
        # via pytest if something goes wrong.
        return

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        mode = getattr(self.server, "mode", "ok")
        body = getattr(self.server, "body", _FIXTURE_JWKS)
        if mode == "ok":
            if self.path != "/":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/jwk-set+json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif mode == "404":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
        elif mode == "500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"internal server error")
        elif mode == "empty":
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif mode == "oversize":
            big = b"a" * (MAX_BUNDLE_BYTES + 1024)
            self.send_response(200)
            self.send_header("Content-Length", str(len(big)))
            self.end_headers()
            self.wfile.write(big)
        elif mode == "slow":
            # Sleep longer than the configured client-timeout. The
            # client should trip a LiveBundleTimeoutError before the
            # body lands.
            time.sleep(getattr(self.server, "slow_seconds", 2.0))
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(500)
            self.end_headers()


class _MockTlsServer:
    """Context manager standing up a stdlib HTTPS server on loopback.

    Configurable mode (``ok``, ``404``, ``500``, ``empty``,
    ``oversize``, ``slow``). Returns ``(url, ca_cert_path)`` on
    entry.
    """

    def __init__(
        self,
        *,
        tmp_path: Path,
        mode: str = "ok",
        body: bytes = _FIXTURE_JWKS,
        slow_seconds: float = 2.0,
    ) -> None:
        self._tmp_path = tmp_path
        self._mode = mode
        self._body = body
        self._slow_seconds = slow_seconds
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.url: str = ""
        self.cert_path: Optional[Path] = None

    def __enter__(self) -> "_MockTlsServer":
        cert, key = _make_self_signed_cert("localhost", self._tmp_path)
        self.cert_path = cert
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _BundleHandler
        )
        # Stash test-mode + body onto the server instance; the
        # handler reads them off the server attribute.
        server.mode = self._mode  # type: ignore[attr-defined]
        server.body = self._body  # type: ignore[attr-defined]
        server.slow_seconds = self._slow_seconds  # type: ignore[attr-defined]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        port = server.server_address[1]
        self.url = f"https://localhost:{port}"
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


@pytest.fixture
def tls_server(tmp_path: Path) -> Iterator[_MockTlsServer]:
    with _MockTlsServer(tmp_path=tmp_path, mode="ok") as srv:
        yield srv


def _run(coro):
    """asyncio runner that works under any active loop state."""
    return asyncio.get_event_loop().run_until_complete(coro) if (
        False
    ) else asyncio.run(coro)


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-01: happy-path against a 200 mock.
# ---------------------------------------------------------------------------


def test_live_https_01_happy_path(tls_server: _MockTlsServer) -> None:
    fixed_clock = lambda: datetime(  # noqa: E731
        2026, 5, 15, 12, 0, tzinfo=timezone.utc
    )
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": tls_server.url},
        verify_ca_bundle_path=str(tls_server.cert_path),
        clock=fixed_clock,
    )
    result = asyncio.run(
        adapter.fetch(url=tls_server.url, trust_domain="orbit.test")
    )
    assert isinstance(result, FetchedTrustBundle)
    assert result.trust_domain == "orbit.test"
    assert result.url == tls_server.url
    assert result.bundle_bytes == _FIXTURE_JWKS
    assert result.fetched_at == fixed_clock()


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-02: insecure_tls=True path also succeeds (Phase-2c).
# ---------------------------------------------------------------------------


def test_live_https_02_insecure_tls_pilot_posture(
    tls_server: _MockTlsServer,
) -> None:
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": tls_server.url},
        insecure_tls=True,
    )
    result = asyncio.run(
        adapter.fetch(url=tls_server.url, trust_domain="orbit.test")
    )
    assert result.bundle_bytes == _FIXTURE_JWKS


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-03: unpinned trust-domain rejected.
# ---------------------------------------------------------------------------


def test_live_https_03_unpinned_trust_domain_rejected(
    tls_server: _MockTlsServer,
) -> None:
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": tls_server.url},
        insecure_tls=True,
    )
    with pytest.raises(UnpinnedTrustDomainError) as exc_info:
        asyncio.run(
            adapter.fetch(
                url=tls_server.url, trust_domain="rogue.test"
            )
        )
    err = exc_info.value
    assert err.trust_domain == "rogue.test"
    assert err.pinned == ("orbit.test",)


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-04: URL mismatch for a pinned trust-domain rejected.
# ---------------------------------------------------------------------------


def test_live_https_04_url_trust_domain_mismatch_rejected(
    tls_server: _MockTlsServer,
) -> None:
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": tls_server.url},
        insecure_tls=True,
    )
    with pytest.raises(UrlTrustDomainMismatchError) as exc_info:
        asyncio.run(
            adapter.fetch(
                url="https://attacker.example:8443",
                trust_domain="orbit.test",
            )
        )
    err = exc_info.value
    assert err.trust_domain == "orbit.test"
    assert err.requested_url == "https://attacker.example:8443"
    assert err.pinned_url == tls_server.url


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-05: connect refusal surfaces as LiveBundleFetchError.
# ---------------------------------------------------------------------------


def test_live_https_05_connect_refused_surfaces_fetch_error(
    tmp_path: Path,
) -> None:
    # Bind a socket to claim a port, then close it before the test.
    # The OS will not immediately re-bind (TIME_WAIT), so a connect
    # against the same port surfaces ECONNREFUSED.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    refused_url = f"https://localhost:{port}"
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": refused_url},
        insecure_tls=True,
        timeout_seconds=2.0,
    )
    with pytest.raises(LiveBundleFetchError) as exc_info:
        asyncio.run(
            adapter.fetch(url=refused_url, trust_domain="orbit.test")
        )
    assert exc_info.value.url == refused_url
    assert exc_info.value.cause is not None


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-06: 404 surfaces as LiveBundleHttpStatusError.
# ---------------------------------------------------------------------------


def test_live_https_06_404_surfaces_http_status_error(
    tmp_path: Path,
) -> None:
    with _MockTlsServer(tmp_path=tmp_path, mode="404") as srv:
        adapter = LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": srv.url},
            insecure_tls=True,
            timeout_seconds=5.0,
        )
        with pytest.raises(LiveBundleHttpStatusError) as exc_info:
            asyncio.run(
                adapter.fetch(url=srv.url, trust_domain="orbit.test")
            )
        assert exc_info.value.status == 404
        assert exc_info.value.url == srv.url


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-07: 500 surfaces as LiveBundleHttpStatusError.
# ---------------------------------------------------------------------------


def test_live_https_07_500_surfaces_http_status_error(
    tmp_path: Path,
) -> None:
    with _MockTlsServer(tmp_path=tmp_path, mode="500") as srv:
        adapter = LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": srv.url},
            insecure_tls=True,
            timeout_seconds=5.0,
        )
        with pytest.raises(LiveBundleHttpStatusError) as exc_info:
            asyncio.run(
                adapter.fetch(url=srv.url, trust_domain="orbit.test")
            )
        assert exc_info.value.status == 500


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-08: slow server trips the timeout.
# ---------------------------------------------------------------------------


def test_live_https_08_timeout_surfaces_timeout_error(
    tmp_path: Path,
) -> None:
    with _MockTlsServer(
        tmp_path=tmp_path, mode="slow", slow_seconds=3.0
    ) as srv:
        adapter = LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": srv.url},
            insecure_tls=True,
            timeout_seconds=1.0,
        )
        with pytest.raises(LiveBundleTimeoutError) as exc_info:
            asyncio.run(
                adapter.fetch(url=srv.url, trust_domain="orbit.test")
            )
        assert exc_info.value.timeout_seconds == 1.0
        assert exc_info.value.url == srv.url


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-09: TLS verification failure surfaces as TlsError.
# ---------------------------------------------------------------------------


def test_live_https_09_tls_verification_failure_surfaces_tls_error(
    tmp_path: Path,
) -> None:
    # Mock server has cert A; adapter is configured with a DIFFERENT
    # CA bundle (cert B) → the handshake fails because the server
    # cert does not chain to B.
    other_dir = tmp_path / "other_ca"
    other_dir.mkdir()
    other_cert, _ = _make_self_signed_cert("not-the-server", other_dir)
    with _MockTlsServer(tmp_path=tmp_path, mode="ok") as srv:
        adapter = LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": srv.url},
            verify_ca_bundle_path=str(other_cert),
            timeout_seconds=5.0,
        )
        with pytest.raises(LiveBundleTlsError) as exc_info:
            asyncio.run(
                adapter.fetch(url=srv.url, trust_domain="orbit.test")
            )
        assert exc_info.value.url == srv.url
        assert exc_info.value.cause is not None


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-10: schema-URI is stable.
# ---------------------------------------------------------------------------


def test_live_https_10_schema_uri_is_stable() -> None:
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": "https://wakir-orbit:8443"},
        insecure_tls=True,
    )
    assert (
        adapter.adapter_schema
        == SPIRE_FED_BUNDLE_LIVE_HTTPS_FETCHER_SCHEMA
    )
    assert (
        SPIRE_FED_BUNDLE_LIVE_HTTPS_FETCHER_SCHEMA
        == "wakir.federation.spire-fed-bundle-live-https-fetcher/1"
    )


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-11: posture ambiguity (both modes set) rejected.
# ---------------------------------------------------------------------------


def test_live_https_11_both_tls_modes_set_rejected(
    tmp_path: Path,
) -> None:
    cert, _ = _make_self_signed_cert("localhost", tmp_path)
    with pytest.raises(ValueError, match="mutually exclusive"):
        LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": "https://x:8443"},
            verify_ca_bundle_path=str(cert),
            insecure_tls=True,
        )


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-12: posture ambiguity (neither mode set) rejected.
# ---------------------------------------------------------------------------


def test_live_https_12_no_tls_posture_set_rejected() -> None:
    with pytest.raises(ValueError, match="no TLS posture configured"):
        LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": "https://x:8443"},
        )


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-13: oversized response body refused.
# ---------------------------------------------------------------------------


def test_live_https_13_oversize_body_refused(tmp_path: Path) -> None:
    with _MockTlsServer(tmp_path=tmp_path, mode="oversize") as srv:
        # Constrain max_bundle_bytes to 16 KiB so the test does not
        # have to fabricate a >1 MiB body.
        adapter = LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": srv.url},
            insecure_tls=True,
            timeout_seconds=5.0,
            max_bundle_bytes=16 * 1024,
        )
        with pytest.raises(LiveBundleFetchError) as exc_info:
            asyncio.run(
                adapter.fetch(url=srv.url, trust_domain="orbit.test")
            )
        assert "exceeded max_bundle_bytes" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-14: empty body refused.
# ---------------------------------------------------------------------------


def test_live_https_14_empty_body_refused(tmp_path: Path) -> None:
    with _MockTlsServer(tmp_path=tmp_path, mode="empty") as srv:
        adapter = LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": srv.url},
            insecure_tls=True,
            timeout_seconds=5.0,
        )
        with pytest.raises(LiveBundleFetchError) as exc_info:
            asyncio.run(
                adapter.fetch(url=srv.url, trust_domain="orbit.test")
            )
        assert "empty response body" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-15: defaults are the documented constants.
# ---------------------------------------------------------------------------


def test_live_https_15_defaults_documented() -> None:
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": "https://wakir-orbit:8443"},
        insecure_tls=True,
    )
    assert adapter.timeout_seconds == DEFAULT_FETCH_TIMEOUT_SECONDS
    assert adapter.max_bundle_bytes == MAX_BUNDLE_BYTES
    assert DEFAULT_FETCH_TIMEOUT_SECONDS == 10.0
    assert MAX_BUNDLE_BYTES == (1 << 20)


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-16: clock-injection rejects naive datetime.
# ---------------------------------------------------------------------------


def test_live_https_16_naive_clock_rejected(tls_server: _MockTlsServer) -> None:
    naive_clock = lambda: datetime(2026, 5, 15, 12, 0)  # noqa: E731
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": tls_server.url},
        insecure_tls=True,
        clock=naive_clock,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(
            adapter.fetch(url=tls_server.url, trust_domain="orbit.test")
        )


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-17: clock returning non-datetime rejected.
# ---------------------------------------------------------------------------


def test_live_https_17_non_datetime_clock_rejected(
    tls_server: _MockTlsServer,
) -> None:
    bad_clock = lambda: "not-a-datetime"  # noqa: E731
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={"orbit.test": tls_server.url},
        insecure_tls=True,
        clock=bad_clock,
    )
    with pytest.raises(TypeError, match="must return a datetime"):
        asyncio.run(
            adapter.fetch(url=tls_server.url, trust_domain="orbit.test")
        )


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-18: distinct trust-domains return distinct bundles.
# ---------------------------------------------------------------------------


def test_live_https_18_two_trust_domains_two_pinned_urls(
    tmp_path: Path,
) -> None:
    # Stand up two independent mock servers (each on a distinct
    # port + distinct body) and pin the adapter against both.
    body_a = b'{"keys":[{"kid":"orbit-key"}]}'
    body_b = b'{"keys":[{"kid":"pilot-key"}]}'
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    with _MockTlsServer(tmp_path=dir_a, mode="ok", body=body_a) as srv_a, \
         _MockTlsServer(tmp_path=dir_b, mode="ok", body=body_b) as srv_b:
        adapter = LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={
                "orbit.test": srv_a.url,
                "wakir.test": srv_b.url,
            },
            insecure_tls=True,
            timeout_seconds=5.0,
        )
        r_a = asyncio.run(
            adapter.fetch(url=srv_a.url, trust_domain="orbit.test")
        )
        r_b = asyncio.run(
            adapter.fetch(url=srv_b.url, trust_domain="wakir.test")
        )
        assert r_a.bundle_bytes == body_a
        assert r_b.bundle_bytes == body_b
        assert r_a.url != r_b.url


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-19: zero/negative timeout rejected at construction.
# ---------------------------------------------------------------------------


def test_live_https_19_bad_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": "https://x:8443"},
            insecure_tls=True,
            timeout_seconds=0,
        )
    with pytest.raises(ValueError, match="timeout_seconds"):
        LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": "https://x:8443"},
            insecure_tls=True,
            timeout_seconds=-1,
        )


# ---------------------------------------------------------------------------
# T-LIVE-HTTPS-20: zero/negative max_bundle_bytes rejected.
# ---------------------------------------------------------------------------


def test_live_https_20_bad_max_bytes_rejected() -> None:
    with pytest.raises(ValueError, match="max_bundle_bytes"):
        LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={"orbit.test": "https://x:8443"},
            insecure_tls=True,
            max_bundle_bytes=0,
        )


# ---------------------------------------------------------------------------
# T-LIVE-INT: optional live-VM-integration test.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("WAKIR_LIVE_PARTNER_URL"),
    reason=(
        "Live-Integration test opt-in. Set WAKIR_LIVE_PARTNER_URL "
        "to e.g. https://wakir-orbit:8443 to enable."
    ),
)
def test_live_int_live_partner_vm() -> None:
    url = os.environ["WAKIR_LIVE_PARTNER_URL"]
    trust_domain = os.environ.get(
        "WAKIR_LIVE_PARTNER_TRUST_DOMAIN", "orbit.test"
    )
    ca_path = os.environ.get("WAKIR_LIVE_PARTNER_CA_PATH")
    adapter = LiveHttpsSpireFedBundleFetcher(
        trust_domain_to_url={trust_domain: url},
        verify_ca_bundle_path=ca_path if ca_path else None,
        insecure_tls=(ca_path is None),
        timeout_seconds=15.0,
    )
    result = asyncio.run(
        adapter.fetch(url=url, trust_domain=trust_domain)
    )
    assert isinstance(result, FetchedTrustBundle)
    assert result.trust_domain == trust_domain
    assert result.url == url
    assert len(result.bundle_bytes) > 0
    # SPIRE-Server returns a JWKS. Don't parse it strictly here;
    # the bridge layer is what asserts JWKS shape. We just confirm
    # it starts with `{` (JSON object) which is the minimal sanity
    # check.
    assert result.bundle_bytes.lstrip().startswith(b"{")
