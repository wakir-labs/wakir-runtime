# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for ``wirelang.identity.aip_https_backend`` (V-908 PS-6).

Phase-1b Tag-8 production-form tests. The module under test is
``wirelang/identity/aip_https_backend.py`` (Tag-8 PS-6 HTTPS-backend
for AIP-document fetch, V-908 §3.3).

All tests are hermetic: a fake ``urlopen`` is injected into
:class:`HTTPSDocumentTransport` so no real HTTPS calls leave the
process. Assertions cover the V-908 §3.3 transport invariants
(HTTPS-only, redirect ceiling, no credentials, body-size ceiling,
ETag round-trip) plus the
:class:`~wirelang.identity.federation_resolver.AIPResolverLike`
composition layer.

The Phase-1a Tag-21 ``aip_resolver`` requires ``rfc8785`` and
``jsonschema`` which are not installed in the project sandbox. We
therefore inject a stub ``verify_fn`` for the
:class:`HTTPSAipResolver` composition tests; the verify contract
itself is tested at the Phase-1a layer.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import unittest
import urllib.error
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Module loader -- two-path strategy (analogous to test_dns_anchor)
# ---------------------------------------------------------------------------

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "identity" / "aip_https_backend.py"
)


def _load_module():
    try:
        return importlib.import_module("wirelang.identity.aip_https_backend")
    except ModuleNotFoundError:
        spec = importlib.util.spec_from_file_location(
            "_wirelang_aip_https_backend_under_test", _MODULE_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


_mod = _load_module()

DEFAULT_MAX_BODY_BYTES = _mod.DEFAULT_MAX_BODY_BYTES
DEFAULT_MAX_REDIRECTS = _mod.DEFAULT_MAX_REDIRECTS
DEFAULT_TIMEOUT_S = _mod.DEFAULT_TIMEOUT_S
DEFAULT_USER_AGENT = _mod.DEFAULT_USER_AGENT
HTTPSAipResolver = _mod.HTTPSAipResolver
HTTPSAipResolverCache = _mod.HTTPSAipResolverCache
HTTPSBackendError = _mod.HTTPSBackendError
HTTPSBodySizeError = _mod.HTTPSBodySizeError
HTTPSDocumentNotModified = _mod.HTTPSDocumentNotModified
HTTPSDocumentResponse = _mod.HTTPSDocumentResponse
HTTPSDocumentTransport = _mod.HTTPSDocumentTransport
HTTPSPayloadError = _mod.HTTPSPayloadError
HTTPSRedirectError = _mod.HTTPSRedirectError
HTTPSSchemeError = _mod.HTTPSSchemeError
HTTPSStatusError = _mod.HTTPSStatusError
HTTPSTransportError = _mod.HTTPSTransportError


# ---------------------------------------------------------------------------
# Fake urllib pieces
# ---------------------------------------------------------------------------


class _FakeHeaders(dict):
    """Mapping-shaped HTTPMessage stand-in.

    urllib's response exposes headers via an HTTPMessage which behaves
    like a case-insensitive Mapping. The transport's
    :func:`_headers_to_mapping` accepts any Mapping; the test fakes
    just use a lowercased dict, which is the Mapping shape the
    transport actually walks.
    """

    def get(self, key, default=None):
        return super().get(key.lower() if isinstance(key, str) else key, default)


@dataclass
class _FakeResponse:
    """Stand-in for the object returned by ``urllib.request.urlopen``.

    Has ``status``, ``read(n)``, and ``headers``. The transport reads
    only those attributes plus optional ``getcode()`` (not exercised
    here since ``status`` is always set).
    """

    status: int
    body: bytes
    headers: _FakeHeaders

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            return self.body
        return self.body[:n]


@dataclass
class _Call:
    """Captures one urlopen invocation for assertion."""

    url: str
    method: str
    headers: dict
    timeout: float


class _FakeUrlopen:
    """Programmable urlopen replacement for the transport tests.

    Each call consumes the next response from the FIFO ``script`` --
    a list of either :class:`_FakeResponse` (success) or ``Exception``
    instances (raised). Calls are recorded on ``calls`` for assertion.
    """

    def __init__(self, script: list[object]) -> None:
        self._script = list(script)
        self.calls: list[_Call] = []

    def __call__(self, request, *, timeout, context=None):
        # Capture state before consuming the script entry so that an
        # exception still leaves a trail for assertions.
        headers_dict = {
            (k.lower() if isinstance(k, str) else k): v
            for (k, v) in (request.header_items() or [])
        }
        self.calls.append(
            _Call(
                url=request.full_url,
                method=request.get_method(),
                headers=headers_dict,
                timeout=float(timeout),
            )
        )
        if not self._script:
            raise AssertionError(
                "FakeUrlopen called more times than scripted; call %d to %r"
                % (len(self.calls), request.full_url)
            )
        next_step = self._script.pop(0)
        if isinstance(next_step, BaseException):
            raise next_step
        return next_step


def _make_response(
    body: dict | bytes,
    *,
    status: int = 200,
    etag: str | None = None,
    cache_control: str | None = None,
    content_type: str = "application/json",
    extra_headers: dict | None = None,
) -> _FakeResponse:
    if isinstance(body, dict):
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    elif isinstance(body, bytes):
        raw = body
    else:
        raise TypeError(f"unsupported body type {type(body).__name__}")
    headers = _FakeHeaders()
    if etag is not None:
        headers["etag"] = etag
    if cache_control is not None:
        headers["cache-control"] = cache_control
    if content_type is not None:
        headers["content-type"] = content_type
    if extra_headers:
        for k, v in extra_headers.items():
            headers[k.lower()] = v
    return _FakeResponse(status=status, body=raw, headers=headers)


def _make_http_error(
    url: str,
    code: int,
    *,
    location: str | None = None,
    etag: str | None = None,
) -> urllib.error.HTTPError:
    headers = _FakeHeaders()
    if location is not None:
        headers["location"] = location
    if etag is not None:
        headers["etag"] = etag
    err = urllib.error.HTTPError(url, code, f"HTTP {code}", headers, None)
    # Python 3.14's HTTPError allocates an internal addinfourl/tempfile
    # wrapper when ``fp`` is None; we close it eagerly to avoid
    # ResourceWarning noise during test teardown. The error stays
    # raisable; ``.close()`` only releases the underlying file handle.
    try:
        err.close()
    except Exception:
        pass
    return err


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_AIP_URL = "https://peer-org.example/aip/aip-1.json"
_AIP_BODY = {
    "aip": "0.1.0",
    "id": "aip:web:peer-org.example/aip-1",
    "biscuit_root_pubkey": "bb" * 32,
}


# ---------------------------------------------------------------------------
# Section A -- Scheme enforcement (V-908 §3.3 HTTPS-only)
# ---------------------------------------------------------------------------


class SchemeEnforcementTests(unittest.TestCase):
    def test_http_url_rejected(self) -> None:
        t = HTTPSDocumentTransport(urlopen=_FakeUrlopen([]))
        with self.assertRaises(HTTPSSchemeError) as cm:
            t.get("http://peer-org.example/aip/x.json")
        self.assertIn("https://", str(cm.exception))

    def test_ftp_url_rejected(self) -> None:
        t = HTTPSDocumentTransport(urlopen=_FakeUrlopen([]))
        with self.assertRaises(HTTPSSchemeError):
            t.get("ftp://peer-org.example/aip/x.json")

    def test_empty_url_rejected(self) -> None:
        t = HTTPSDocumentTransport(urlopen=_FakeUrlopen([]))
        with self.assertRaises(HTTPSSchemeError):
            t.get("")

    def test_unparseable_url_rejected(self) -> None:
        t = HTTPSDocumentTransport(urlopen=_FakeUrlopen([]))
        with self.assertRaises(HTTPSSchemeError):
            t.get("not-a-url")

    def test_uppercase_scheme_accepted(self) -> None:
        # urllib handles scheme case-folding; we only fail-fast on
        # non-https schemes. Construct a fake response so the call
        # would succeed if urllib accepts the URL.
        fake = _FakeUrlopen([_make_response(_AIP_BODY)])
        t = HTTPSDocumentTransport(urlopen=fake)
        resp = t.get("HTTPS://peer-org.example/aip/x.json")
        self.assertEqual(resp.body, _AIP_BODY)


# ---------------------------------------------------------------------------
# Section B -- Happy path / response shape
# ---------------------------------------------------------------------------


class HappyPathTests(unittest.TestCase):
    def test_200_json_returns_response(self) -> None:
        fake = _FakeUrlopen([_make_response(_AIP_BODY, etag='"v1"',
                                             cache_control="public, max-age=300")])
        t = HTTPSDocumentTransport(urlopen=fake)
        resp = t.get(_AIP_URL)
        self.assertIsInstance(resp, HTTPSDocumentResponse)
        self.assertEqual(resp.url, _AIP_URL)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, _AIP_BODY)
        self.assertEqual(
            resp.body_bytes,
            json.dumps(_AIP_BODY, separators=(",", ":")).encode("utf-8"),
        )
        self.assertEqual(resp.etag, '"v1"')
        self.assertEqual(resp.cache_control, "public, max-age=300")
        self.assertEqual(resp.max_age_s, 300)
        self.assertEqual(resp.content_type, "application/json")

    def test_request_headers_include_user_agent_and_accept(self) -> None:
        fake = _FakeUrlopen([_make_response(_AIP_BODY)])
        t = HTTPSDocumentTransport(urlopen=fake, user_agent="custom-ua/1.0")
        t.get(_AIP_URL)
        sent = fake.calls[0].headers
        self.assertEqual(sent.get("user-agent"), "custom-ua/1.0")
        self.assertEqual(sent.get("accept"), "application/json")
        self.assertEqual(fake.calls[0].method, "GET")
        self.assertEqual(fake.calls[0].timeout, DEFAULT_TIMEOUT_S)

    def test_credentials_headers_dropped(self) -> None:
        # V-908 §3.3 forbids Authorization / Cookie. The transport
        # silently drops them rather than raising; this asserts the
        # silent-drop behaviour.
        fake = _FakeUrlopen([_make_response(_AIP_BODY)])
        t = HTTPSDocumentTransport(urlopen=fake)
        t.get(
            _AIP_URL,
            extra_headers={
                "Authorization": "Bearer xyz",
                "Cookie": "session=abc",
                "Proxy-Authorization": "Basic xx",
                "X-Trace-Id": "abc-123",
            },
        )
        sent = fake.calls[0].headers
        self.assertNotIn("authorization", sent)
        self.assertNotIn("cookie", sent)
        self.assertNotIn("proxy-authorization", sent)
        self.assertEqual(sent.get("x-trace-id"), "abc-123")

    def test_max_age_parsing_robustness(self) -> None:
        cases = [
            ("max-age=0", 0),
            ("public, max-age=3600", 3600),
            ("no-cache, no-store", None),
            ("max-age=-1", None),
            ("max-age=abc", None),
            ("MAX-AGE=42", 42),
            ("", None),
        ]
        for cc, expected in cases:
            with self.subTest(cc=cc):
                fake = _FakeUrlopen(
                    [_make_response(_AIP_BODY, cache_control=cc)]
                )
                t = HTTPSDocumentTransport(urlopen=fake)
                resp = t.get(_AIP_URL)
                self.assertEqual(resp.max_age_s, expected)


# ---------------------------------------------------------------------------
# Section C -- Status-code matrix (404, 5xx, 304)
# ---------------------------------------------------------------------------


class StatusCodeTests(unittest.TestCase):
    def test_404_raises_status_error(self) -> None:
        fake = _FakeUrlopen([_make_http_error(_AIP_URL, 404)])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSStatusError) as cm:
            t.get(_AIP_URL)
        self.assertEqual(cm.exception.status, 404)
        self.assertEqual(cm.exception.url, _AIP_URL)

    def test_500_raises_status_error(self) -> None:
        fake = _FakeUrlopen([_make_http_error(_AIP_URL, 500)])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSStatusError) as cm:
            t.get(_AIP_URL)
        self.assertEqual(cm.exception.status, 500)

    def test_503_raises_status_error(self) -> None:
        fake = _FakeUrlopen([_make_http_error(_AIP_URL, 503)])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSStatusError):
            t.get(_AIP_URL)

    def test_304_without_if_none_match_still_raises(self) -> None:
        # If we did not send If-None-Match, a 304 is unexpected behaviour
        # from the server, but we still surface it as the typed
        # "not modified" exception so the caller can handle it.
        fake = _FakeUrlopen([_make_http_error(_AIP_URL, 304, etag='"v1"')])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSDocumentNotModified) as cm:
            t.get(_AIP_URL)
        self.assertEqual(cm.exception.etag, '"v1"')

    def test_304_with_if_none_match_raises_not_modified(self) -> None:
        fake = _FakeUrlopen([_make_http_error(_AIP_URL, 304, etag='"v1"')])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSDocumentNotModified):
            t.get(_AIP_URL, if_none_match='"v1"')
        sent = fake.calls[0].headers
        self.assertEqual(sent.get("if-none-match"), '"v1"')


# ---------------------------------------------------------------------------
# Section D -- Transport-error mapping
# ---------------------------------------------------------------------------


class TransportErrorTests(unittest.TestCase):
    def test_url_error_maps_to_transport_error(self) -> None:
        fake = _FakeUrlopen([urllib.error.URLError("connection refused")])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSTransportError) as cm:
            t.get(_AIP_URL)
        self.assertIn("connection refused", str(cm.exception))
        self.assertEqual(cm.exception.url, _AIP_URL)

    def test_dns_failure_maps_to_transport_error(self) -> None:
        # urllib raises URLError wrapping a socket gaierror for DNS
        # failures; we just need any URLError instance.
        fake = _FakeUrlopen([urllib.error.URLError("dns: name not known")])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSTransportError):
            t.get(_AIP_URL)


# ---------------------------------------------------------------------------
# Section E -- Body-size enforcement
# ---------------------------------------------------------------------------


class BodySizeTests(unittest.TestCase):
    def test_oversize_body_rejected(self) -> None:
        # Body that just exceeds the configured ceiling.
        big = b"{" + b" " * 200 + b"}"  # JSON-parseable filler ~ 202 bytes
        fake = _FakeUrlopen(
            [_make_response(big, etag=None, cache_control=None,
                             content_type="application/json")]
        )
        t = HTTPSDocumentTransport(urlopen=fake, max_body_bytes=100)
        with self.assertRaises(HTTPSBodySizeError) as cm:
            t.get(_AIP_URL)
        self.assertIn("100 bytes", str(cm.exception))

    def test_at_ceiling_body_accepted(self) -> None:
        # Construct a JSON body whose serialised length is exactly at
        # the ceiling. Padding the body via spaces inside a JSON
        # string keeps it parseable.
        ceiling = 64
        # {"x":"....."} with the right number of '.' to reach exactly ceiling.
        prefix = b'{"x":"'
        suffix = b'"}'
        pad_n = ceiling - len(prefix) - len(suffix)
        self.assertGreater(pad_n, 0)
        body = prefix + (b"." * pad_n) + suffix
        self.assertEqual(len(body), ceiling)
        fake = _FakeUrlopen([_make_response(body)])
        t = HTTPSDocumentTransport(urlopen=fake, max_body_bytes=ceiling)
        resp = t.get(_AIP_URL)
        self.assertEqual(resp.body_bytes, body)


# ---------------------------------------------------------------------------
# Section F -- Redirect handling
# ---------------------------------------------------------------------------


class RedirectTests(unittest.TestCase):
    def test_one_redirect_followed(self) -> None:
        target = "https://peer-org.example/aip/aip-1-final.json"
        fake = _FakeUrlopen(
            [
                _make_http_error(_AIP_URL, 301, location=target),
                _make_response(_AIP_BODY),
            ]
        )
        t = HTTPSDocumentTransport(urlopen=fake, max_redirects=1)
        resp = t.get(_AIP_URL)
        self.assertEqual(resp.url, target)
        self.assertEqual(resp.body, _AIP_BODY)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0].url, _AIP_URL)
        self.assertEqual(fake.calls[1].url, target)

    def test_two_redirects_exceed_default_budget(self) -> None:
        intermediate = "https://peer-org.example/aip/aip-1-mid.json"
        target = "https://peer-org.example/aip/aip-1-final.json"
        fake = _FakeUrlopen(
            [
                _make_http_error(_AIP_URL, 302, location=intermediate),
                _make_http_error(intermediate, 302, location=target),
            ]
        )
        t = HTTPSDocumentTransport(urlopen=fake, max_redirects=1)
        with self.assertRaises(HTTPSRedirectError):
            t.get(_AIP_URL)

    def test_zero_redirects_refuses_first_redirect(self) -> None:
        target = "https://peer-org.example/aip/aip-1-final.json"
        fake = _FakeUrlopen(
            [_make_http_error(_AIP_URL, 301, location=target)]
        )
        t = HTTPSDocumentTransport(urlopen=fake, max_redirects=0)
        with self.assertRaises(HTTPSRedirectError):
            t.get(_AIP_URL)

    def test_redirect_to_http_rejected(self) -> None:
        # A redirect to a non-HTTPS URL must be rejected (no plaintext
        # downgrade).
        target = "http://peer-org.example/aip/aip-1-final.json"
        fake = _FakeUrlopen(
            [_make_http_error(_AIP_URL, 302, location=target)]
        )
        t = HTTPSDocumentTransport(urlopen=fake, max_redirects=2)
        with self.assertRaises(HTTPSSchemeError):
            t.get(_AIP_URL)

    def test_redirect_without_location_rejected(self) -> None:
        fake = _FakeUrlopen([_make_http_error(_AIP_URL, 302, location=None)])
        t = HTTPSDocumentTransport(urlopen=fake, max_redirects=2)
        with self.assertRaises(HTTPSStatusError) as cm:
            t.get(_AIP_URL)
        self.assertEqual(cm.exception.status, 302)


# ---------------------------------------------------------------------------
# Section G -- JSON / payload validity
# ---------------------------------------------------------------------------


class PayloadValidityTests(unittest.TestCase):
    def test_malformed_json_rejected(self) -> None:
        fake = _FakeUrlopen([_make_response(b"not-json")])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSPayloadError) as cm:
            t.get(_AIP_URL)
        self.assertIn("not valid JSON", str(cm.exception))

    def test_non_object_json_rejected(self) -> None:
        # A bare JSON list is parseable but not a dict; AIP shape is
        # always a JSON object so the transport rejects.
        fake = _FakeUrlopen([_make_response(b'["a","b"]')])
        t = HTTPSDocumentTransport(urlopen=fake)
        with self.assertRaises(HTTPSPayloadError) as cm:
            t.get(_AIP_URL)
        self.assertIn("not a JSON object", str(cm.exception))


# ---------------------------------------------------------------------------
# Section H -- Constructor validation
# ---------------------------------------------------------------------------


class ConstructorValidationTests(unittest.TestCase):
    def test_zero_timeout_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HTTPSDocumentTransport(timeout_s=0, urlopen=_FakeUrlopen([]))

    def test_negative_timeout_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HTTPSDocumentTransport(timeout_s=-1, urlopen=_FakeUrlopen([]))

    def test_zero_body_size_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HTTPSDocumentTransport(max_body_bytes=0, urlopen=_FakeUrlopen([]))

    def test_negative_redirects_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HTTPSDocumentTransport(max_redirects=-1, urlopen=_FakeUrlopen([]))

    def test_empty_user_agent_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HTTPSDocumentTransport(user_agent="", urlopen=_FakeUrlopen([]))


# ---------------------------------------------------------------------------
# Section I -- HTTPSAipResolver composition (AIPResolverLike)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StubAipDocument:
    """AIPDocumentLike-shaped stub returned by the test verify_fn."""

    id: str
    body: dict
    jcs_sha256: str
    biscuit_root_pubkey_hex: str


class HTTPSAipResolverTests(unittest.TestCase):
    def _stub_verify(self, uri: str, body_bytes: bytes, body: dict):
        # Pretend-verify: return a stub doc with deterministic
        # downstream fields. The federation pipeline does not re-derive
        # these; it consumes them as-is.
        return _StubAipDocument(
            id=body.get("id", uri),
            body=body,
            jcs_sha256="aa" * 32,
            biscuit_root_pubkey_hex=body.get("biscuit_root_pubkey", "bb" * 32),
        )

    def test_resolve_round_trip(self) -> None:
        fake = _FakeUrlopen([_make_response(_AIP_BODY)])
        transport = HTTPSDocumentTransport(urlopen=fake)
        resolver = HTTPSAipResolver(transport=transport, verify_fn=self._stub_verify)
        doc = resolver.resolve(_AIP_URL)
        self.assertEqual(doc.id, _AIP_BODY["id"])
        self.assertEqual(doc.biscuit_root_pubkey_hex, "bb" * 32)
        self.assertEqual(doc.body, _AIP_BODY)

    def test_resolve_propagates_transport_error(self) -> None:
        fake = _FakeUrlopen([_make_http_error(_AIP_URL, 404)])
        transport = HTTPSDocumentTransport(urlopen=fake)
        resolver = HTTPSAipResolver(transport=transport, verify_fn=self._stub_verify)
        with self.assertRaises(HTTPSStatusError):
            resolver.resolve(_AIP_URL)

    def test_resolve_propagates_verify_error(self) -> None:
        class _VerifyFailure(Exception):
            pass

        def boom(uri, body_bytes, body):
            raise _VerifyFailure("schema check failed")

        fake = _FakeUrlopen([_make_response(_AIP_BODY)])
        transport = HTTPSDocumentTransport(urlopen=fake)
        resolver = HTTPSAipResolver(transport=transport, verify_fn=boom)
        with self.assertRaises(_VerifyFailure):
            resolver.resolve(_AIP_URL)

    def test_etag_cache_round_trip(self) -> None:
        # First call: transport returns 200 + ETag; cache stores doc.
        # Second call: transport returns 304; resolver returns cached.
        fake = _FakeUrlopen(
            [
                _make_response(_AIP_BODY, etag='"v1"',
                                cache_control="public, max-age=600"),
                _make_http_error(_AIP_URL, 304, etag='"v1"'),
            ]
        )
        transport = HTTPSDocumentTransport(urlopen=fake)
        cache = HTTPSAipResolverCache()
        resolver = HTTPSAipResolver(
            transport=transport, verify_fn=self._stub_verify, cache=cache
        )

        doc1 = resolver.resolve(_AIP_URL)
        self.assertIn(_AIP_URL, cache)
        doc2 = resolver.resolve(_AIP_URL)
        # Same document object reused on 304.
        self.assertIs(doc1, doc2)
        # On the second call we sent If-None-Match with the cached ETag.
        sent = fake.calls[1].headers
        self.assertEqual(sent.get("if-none-match"), '"v1"')

    def test_protocol_compliance(self) -> None:
        # The composition layer must satisfy AIPResolverLike. We
        # import it through the federation_resolver module by spec
        # path (the federation_resolver itself depends on
        # cryptography-using siblings via the package init, which is
        # absent in the sandbox). A direct duck-type check is enough:
        # the resolver exposes a callable resolve(uri) -> document.
        transport = HTTPSDocumentTransport(urlopen=_FakeUrlopen([]))
        resolver = HTTPSAipResolver(transport=transport, verify_fn=self._stub_verify)
        self.assertTrue(callable(getattr(resolver, "resolve", None)))


# ---------------------------------------------------------------------------
# Section J -- Cache LRU semantics
# ---------------------------------------------------------------------------


class HTTPSAipResolverCacheTests(unittest.TestCase):
    def test_evicts_oldest(self) -> None:
        cache = HTTPSAipResolverCache(max_entries=2)
        cache.put("a", "etag-a", "doc-a")
        cache.put("b", "etag-b", "doc-b")
        cache.put("c", "etag-c", "doc-c")
        self.assertNotIn("a", cache)
        self.assertIn("b", cache)
        self.assertIn("c", cache)
        self.assertEqual(len(cache), 2)

    def test_overwrite_refreshes_lru_position(self) -> None:
        cache = HTTPSAipResolverCache(max_entries=2)
        cache.put("a", "etag-a", "doc-a")
        cache.put("b", "etag-b", "doc-b")
        # Refresh "a" -- it should move to the most-recent position.
        cache.put("a", "etag-a2", "doc-a2")
        # Adding "c" should now evict "b", not "a".
        cache.put("c", "etag-c", "doc-c")
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)
        self.assertIn("c", cache)
        self.assertEqual(cache.get("a").etag, "etag-a2")

    def test_max_entries_validation(self) -> None:
        with self.assertRaises(ValueError):
            HTTPSAipResolverCache(max_entries=0)
        with self.assertRaises(ValueError):
            HTTPSAipResolverCache(max_entries=-1)


# ---------------------------------------------------------------------------
# Section K -- Module surface stability
# ---------------------------------------------------------------------------


class ModuleSurfaceTests(unittest.TestCase):
    def test_all_exports_present(self) -> None:
        expected = {
            "DEFAULT_TIMEOUT_S",
            "DEFAULT_MAX_BODY_BYTES",
            "DEFAULT_MAX_REDIRECTS",
            "DEFAULT_USER_AGENT",
            "AipVerifyFn",
            "HTTPSBackendError",
            "HTTPSSchemeError",
            "HTTPSTransportError",
            "HTTPSStatusError",
            "HTTPSRedirectError",
            "HTTPSBodySizeError",
            "HTTPSPayloadError",
            "HTTPSDocumentNotModified",
            "HTTPSDocumentResponse",
            "HTTPSDocumentTransport",
            "HTTPSAipResolver",
            "HTTPSAipResolverCache",
        }
        self.assertEqual(set(_mod.__all__), expected)

    def test_error_hierarchy(self) -> None:
        self.assertTrue(issubclass(HTTPSSchemeError, HTTPSBackendError))
        self.assertTrue(issubclass(HTTPSTransportError, HTTPSBackendError))
        self.assertTrue(issubclass(HTTPSStatusError, HTTPSBackendError))
        self.assertTrue(issubclass(HTTPSRedirectError, HTTPSBackendError))
        self.assertTrue(issubclass(HTTPSBodySizeError, HTTPSBackendError))
        self.assertTrue(issubclass(HTTPSPayloadError, HTTPSBackendError))
        self.assertTrue(issubclass(HTTPSDocumentNotModified, HTTPSBackendError))

    def test_response_is_frozen(self) -> None:
        fake = _FakeUrlopen([_make_response(_AIP_BODY)])
        t = HTTPSDocumentTransport(urlopen=fake)
        resp = t.get(_AIP_URL)
        with self.assertRaises(Exception):
            resp.url = "https://other"  # type: ignore[misc]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
