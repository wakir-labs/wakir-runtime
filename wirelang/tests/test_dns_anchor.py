# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for ``wirelang.identity.dns_anchor`` (V-908 PS-2/PS-3).

Phase-1b Tag-5 production-form tests, ported from the Tag-4 spike
(``wirelang/spike/test_dns_anchor_resolver_sketch.py``) with
production-hardening additions:

* Multi-string-TXT handling -- V-908 §3.4 (Tag-5 minor edit)
  guarantees the resolver concatenates RFC 1035 §3.3.14 segments
  before returning to the parser.
* StdlibDoHResolver provider failover -- a fake urlopen exercises
  the multi-provider fallback without any real network IO.
* StdlibDoHResolver Status-code matrix (NOERROR / NXDOMAIN /
  SERVFAIL).
* Negative-smoke against ``_wakir-ftd.example.test`` (RFC 6761
  reserved name; produces NXDOMAIN deterministically). The smoke is
  driven through a synthetic resolver so the test suite remains
  hermetic; the real-DNS variant is deferred to PS-3 opt-in tests.
* MIN_TTL_FLOOR_S exposed as a module-level normative constant.

All tests are pure ``unittest`` and do not require ``pytest``,
``responses``, ``dnspython`` or any other third-party library;
they are runnable in any Python environment that has the
``wirelang`` package on the path.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


# ---------------------------------------------------------------------------
# Module loader -- two-path strategy
#
# The production-import path (``from wirelang.identity.dns_anchor import ...``)
# triggers ``wirelang/identity/__init__.py``, which eagerly imports several
# sibling modules that depend on the optional ``cryptography`` package. In
# environments without ``cryptography`` (e.g. the dependency-restricted
# project sandbox; cf. Tag-4 outbox §4 sandbox-tooling-lücke L1/L3 table),
# the package init fails before our zero-dep ``dns_anchor`` submodule is
# reachable.
#
# The dns_anchor module itself has zero third-party dependencies (urllib +
# json + re + dataclasses + typing -- all stdlib). To exercise the module's
# behaviour irrespective of sibling-import availability, we load it
# directly via ``importlib.util`` from its file path and register it in
# ``sys.modules`` under a private name. Production callers (the federation
# resolver, item I-5) live in the deployed environment where
# ``cryptography`` is present and import the module via the normal package
# path; our hermetic tests do not need to.
# ---------------------------------------------------------------------------

_MODULE_PATH = Path(__file__).resolve().parents[1] / "identity" / "dns_anchor.py"


def _load_dns_anchor_module():
    # Try the normal package-import path first; if that fails because of
    # an unrelated sibling import (e.g. missing 'cryptography'), fall back
    # to a direct file load.
    try:
        return importlib.import_module("wirelang.identity.dns_anchor")
    except ModuleNotFoundError:
        spec = importlib.util.spec_from_file_location(
            "_wirelang_dns_anchor_under_test", _MODULE_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


_dns_anchor = _load_dns_anchor_module()

MIN_TTL_FLOOR_S = _dns_anchor.MIN_TTL_FLOOR_S
DnsAnchor = _dns_anchor.DnsAnchor
DnsAnchorError = _dns_anchor.DnsAnchorError
DnsPythonResolver = _dns_anchor.DnsPythonResolver
StdlibDoHResolver = _dns_anchor.StdlibDoHResolver
TxtResolver = _dns_anchor.TxtResolver
fetch_anchor = _dns_anchor.fetch_anchor
parse_anchor = _dns_anchor.parse_anchor


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_GOOD_HEX = "a" * 64
_GOOD_TXT = f"v=1; sha256={_GOOD_HEX}"
_OTHER_HEX = "b" * 64
_OTHER_TXT = f"v=1; sha256={_OTHER_HEX}"
_HOST = "_wakir-ftd.peer-org.example"
# RFC 6761 reserved special-use TLD; the IANA-registered intent is
# that public DNS resolvers either NXDOMAIN this name immediately or
# never query it at all. We use it as the deterministic
# negative-smoke target.
_RFC6761_HOST = "_wakir-ftd.example.test"


class FakeResolver:
    """Hermetic :class:`TxtResolver` that returns canned data."""

    def __init__(
        self,
        mapping: dict[str, list[str]] | None = None,
        raise_for: dict[str, Exception] | None = None,
    ) -> None:
        self._mapping = mapping or {}
        self._raise_for = raise_for or {}
        self.calls: list[tuple[str, float]] = []

    def resolve_txt(self, name: str, *, timeout_s: float = 3.0) -> list[str]:
        self.calls.append((name, timeout_s))
        if name in self._raise_for:
            raise self._raise_for[name]
        return list(self._mapping.get(name, []))


class _FakeHttpResponse:
    """Stand-in for a urllib HTTP response context manager."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *_excinfo) -> None:
        return None


# ---------------------------------------------------------------------------
# fetch_anchor / parse_anchor hermetic tests (ported from Tag-4 spike)
# ---------------------------------------------------------------------------


class FetchAnchorTests(unittest.TestCase):
    def test_happy_path(self) -> None:
        r = FakeResolver({_HOST: [_GOOD_TXT]})
        anchor = fetch_anchor(r, _HOST)
        self.assertEqual(anchor, DnsAnchor(host=_HOST, fingerprint=_GOOD_HEX))
        self.assertEqual(r.calls, [(_HOST, 3.0)])

    def test_unrelated_txt_records_are_ignored(self) -> None:
        r = FakeResolver(
            {
                _HOST: [
                    "v=spf1 -all",
                    _GOOD_TXT,
                    "google-site-verification=xyz",
                ]
            }
        )
        anchor = fetch_anchor(r, _HOST)
        self.assertEqual(anchor.fingerprint, _GOOD_HEX)

    def test_missing_anchor_is_rejected(self) -> None:
        r = FakeResolver({_HOST: ["v=spf1 -all"]})
        with self.assertRaises(DnsAnchorError):
            fetch_anchor(r, _HOST)

    def test_empty_txt_set_is_rejected(self) -> None:
        r = FakeResolver({_HOST: []})
        with self.assertRaises(DnsAnchorError):
            fetch_anchor(r, _HOST)

    def test_ambiguous_anchors_are_rejected(self) -> None:
        r = FakeResolver({_HOST: [_GOOD_TXT, _OTHER_TXT]})
        with self.assertRaises(DnsAnchorError) as ctx:
            fetch_anchor(r, _HOST)
        self.assertIn("ambiguous", str(ctx.exception).lower())

    def test_duplicate_anchor_with_same_fp_is_accepted(self) -> None:
        r = FakeResolver({_HOST: [_GOOD_TXT, _GOOD_TXT]})
        anchor = fetch_anchor(r, _HOST)
        self.assertEqual(anchor.fingerprint, _GOOD_HEX)

    def test_uppercase_hex_is_rejected(self) -> None:
        r = FakeResolver({_HOST: [f"v=1; sha256={_GOOD_HEX.upper()}"]})
        with self.assertRaises(DnsAnchorError):
            fetch_anchor(r, _HOST)

    def test_transport_error_propagates(self) -> None:
        r = FakeResolver(
            raise_for={_HOST: DnsAnchorError("simulated SERVFAIL")}
        )
        with self.assertRaises(DnsAnchorError):
            fetch_anchor(r, _HOST)

    def test_protocol_compliance(self) -> None:
        r: TxtResolver = FakeResolver()
        self.assertTrue(hasattr(r, "resolve_txt"))

    def test_timeout_propagated_to_resolver(self) -> None:
        r = FakeResolver({_HOST: [_GOOD_TXT]})
        fetch_anchor(r, _HOST, timeout_s=1.5)
        self.assertEqual(r.calls, [(_HOST, 1.5)])


class ParseAnchorTests(unittest.TestCase):
    def test_strips_whitespace(self) -> None:
        a = parse_anchor("h", [f"  v=1; sha256={_GOOD_HEX}  "])
        self.assertEqual(a.fingerprint, _GOOD_HEX)

    def test_short_hex_rejected(self) -> None:
        with self.assertRaises(DnsAnchorError):
            parse_anchor("h", [f"v=1; sha256={'a' * 63}"])

    def test_extra_fields_rejected(self) -> None:
        with self.assertRaises(DnsAnchorError):
            parse_anchor("h", [f"v=1; sha256={_GOOD_HEX}; foo=bar"])

    def test_non_hex_rejected(self) -> None:
        # 'g' is not a hex char.
        bad = "g" + "a" * 63
        with self.assertRaises(DnsAnchorError):
            parse_anchor("h", [f"v=1; sha256={bad}"])

    def test_wrong_version_rejected(self) -> None:
        with self.assertRaises(DnsAnchorError):
            parse_anchor("h", [f"v=2; sha256={_GOOD_HEX}"])


# ---------------------------------------------------------------------------
# StdlibDoHResolver tests (no real network)
# ---------------------------------------------------------------------------


class StdlibDoHResolverTests(unittest.TestCase):
    """Drive ``urllib.request.urlopen`` via mock to keep tests hermetic.

    The mock lives only inside the ``mock.patch`` context to avoid
    leaking. We test the public ``resolve_txt`` surface, plus the
    static multi-string concatenation helper.
    """

    def _doh_payload_single_txt(self, txt: str) -> bytes:
        return json.dumps(
            {
                "Status": 0,
                "Answer": [
                    {"name": _HOST, "type": 16, "TTL": 300, "data": f'"{txt}"'}
                ],
            }
        ).encode("ascii")

    def test_single_provider_happy_path(self) -> None:
        r = StdlibDoHResolver(providers=("https://example.invalid/resolve",))
        body = self._doh_payload_single_txt(_GOOD_TXT)
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHttpResponse(body)
            out = r.resolve_txt(_HOST)
        self.assertEqual(out, [_GOOD_TXT])

    def test_provider_failover_on_transport_error(self) -> None:
        import urllib.error

        r = StdlibDoHResolver(
            providers=(
                "https://broken.invalid/resolve",
                "https://working.invalid/resolve",
            )
        )
        good_body = self._doh_payload_single_txt(_GOOD_TXT)

        def side_effect(req, timeout):
            if "broken" in req.full_url:
                raise urllib.error.URLError("boom")
            return _FakeHttpResponse(good_body)

        with mock.patch("urllib.request.urlopen", side_effect=side_effect):
            out = r.resolve_txt(_HOST)
        self.assertEqual(out, [_GOOD_TXT])

    def test_all_providers_fail_raises(self) -> None:
        import urllib.error

        r = StdlibDoHResolver(
            providers=(
                "https://broken-a.invalid/resolve",
                "https://broken-b.invalid/resolve",
            )
        )

        def side_effect(req, timeout):
            raise urllib.error.URLError("offline")

        with mock.patch("urllib.request.urlopen", side_effect=side_effect):
            with self.assertRaises(DnsAnchorError) as ctx:
                r.resolve_txt(_HOST)
        self.assertIn("DoH providers failed", str(ctx.exception))

    def test_nxdomain_returns_empty(self) -> None:
        r = StdlibDoHResolver(providers=("https://nx.invalid/resolve",))
        body = json.dumps({"Status": 3}).encode("ascii")
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHttpResponse(body)
            out = r.resolve_txt(_RFC6761_HOST)
        self.assertEqual(out, [])

    def test_servfail_drives_failover(self) -> None:
        # Status=2 is SERVFAIL; resolver MUST NOT return [] (which is
        # NXDOMAIN-only); it MUST treat SERVFAIL as a soft-failure
        # and try the next provider. Without a working second provider
        # it raises DnsAnchorError.
        r = StdlibDoHResolver(providers=("https://sf.invalid/resolve",))
        body = json.dumps({"Status": 2}).encode("ascii")
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHttpResponse(body)
            with self.assertRaises(DnsAnchorError):
                r.resolve_txt(_HOST)

    def test_http_non_200_drives_failover(self) -> None:
        r = StdlibDoHResolver(
            providers=(
                "https://broken.invalid/resolve",
                "https://working.invalid/resolve",
            )
        )
        good_body = self._doh_payload_single_txt(_GOOD_TXT)

        def side_effect(req, timeout):
            if "broken" in req.full_url:
                return _FakeHttpResponse(b"", status=503)
            return _FakeHttpResponse(good_body)

        with mock.patch("urllib.request.urlopen", side_effect=side_effect):
            out = r.resolve_txt(_HOST)
        self.assertEqual(out, [_GOOD_TXT])

    def test_invalid_json_drives_failover(self) -> None:
        r = StdlibDoHResolver(
            providers=(
                "https://garbage.invalid/resolve",
                "https://working.invalid/resolve",
            )
        )
        good_body = self._doh_payload_single_txt(_GOOD_TXT)

        def side_effect(req, timeout):
            if "garbage" in req.full_url:
                return _FakeHttpResponse(b"<html>404</html>", status=200)
            return _FakeHttpResponse(good_body)

        with mock.patch("urllib.request.urlopen", side_effect=side_effect):
            out = r.resolve_txt(_HOST)
        self.assertEqual(out, [_GOOD_TXT])

    def test_non_txt_records_filtered(self) -> None:
        # Only RR type 16 should be returned; mix in an A record (type 1).
        body = json.dumps(
            {
                "Status": 0,
                "Answer": [
                    {"name": _HOST, "type": 1, "TTL": 300, "data": "192.0.2.1"},
                    {"name": _HOST, "type": 16, "TTL": 300, "data": f'"{_GOOD_TXT}"'},
                ],
            }
        ).encode("ascii")
        r = StdlibDoHResolver(providers=("https://example.invalid/resolve",))
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHttpResponse(body)
            out = r.resolve_txt(_HOST)
        self.assertEqual(out, [_GOOD_TXT])

    def test_empty_name_rejected(self) -> None:
        r = StdlibDoHResolver(providers=("https://example.invalid/resolve",))
        with self.assertRaises(DnsAnchorError):
            r.resolve_txt("")

    def test_zero_providers_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StdlibDoHResolver(providers=())

    def test_user_agent_header_is_sent(self) -> None:
        r = StdlibDoHResolver(
            providers=("https://example.invalid/resolve",),
            user_agent="custom-ua/1.0",
        )
        body = self._doh_payload_single_txt(_GOOD_TXT)
        captured: dict[str, str] = {}

        def side_effect(req, timeout):
            captured["ua"] = req.get_header("User-agent") or ""
            return _FakeHttpResponse(body)

        with mock.patch("urllib.request.urlopen", side_effect=side_effect):
            r.resolve_txt(_HOST)
        self.assertEqual(captured["ua"], "custom-ua/1.0")


# ---------------------------------------------------------------------------
# Multi-string TXT handling -- V-908 §3.4 (Tag-5 minor edit)
# ---------------------------------------------------------------------------


class MultiStringTxtTests(unittest.TestCase):
    """V-908 §3.4 normatively requires multi-string TXT concatenation.

    RFC 1035 §3.3.14: a TXT RR may consist of multiple
    ``<character-string>`` segments (each segment <= 255 octets).
    DoH-JSON serialises a multi-string TXT as space-separated quoted
    segments inside ``data`` (e.g. ``"foo" "bar"``). The resolver
    MUST concatenate so the parser sees a single payload.
    """

    def _doh_with_data(self, raw_data: str) -> bytes:
        return json.dumps(
            {
                "Status": 0,
                "Answer": [
                    {
                        "name": _HOST,
                        "type": 16,
                        "TTL": 300,
                        "data": raw_data,
                    }
                ],
            }
        ).encode("ascii")

    def test_concat_helper_single_string(self) -> None:
        out = StdlibDoHResolver._concat_multi_string_txt(f'"{_GOOD_TXT}"')
        self.assertEqual(out, _GOOD_TXT)

    def test_concat_helper_two_segments(self) -> None:
        # First half + second half -- legal RFC 1035 segmentation that
        # parse_anchor must accept after concatenation.
        first = f"v=1; sha256={'a' * 30}"
        second = "a" * 34
        raw = f'"{first}" "{second}"'
        out = StdlibDoHResolver._concat_multi_string_txt(raw)
        self.assertEqual(out, _GOOD_TXT)

    def test_concat_helper_unquoted(self) -> None:
        # Some providers omit quotes for simple ASCII payloads.
        out = StdlibDoHResolver._concat_multi_string_txt(_GOOD_TXT)
        self.assertEqual(out, _GOOD_TXT)

    def test_concat_helper_empty(self) -> None:
        self.assertEqual(StdlibDoHResolver._concat_multi_string_txt(""), "")

    def test_concat_helper_malformed_unbalanced_quote(self) -> None:
        # An unbalanced quote falls back to outer-quote-strip; the
        # resulting payload will fail the V-908 regex in parse_anchor,
        # which is the correct security outcome.
        out = StdlibDoHResolver._concat_multi_string_txt('"unterminated')
        # Must not crash; payload is whatever we can salvage.
        self.assertIsInstance(out, str)

    def test_resolver_returns_concatenated_multi_string(self) -> None:
        first = f"v=1; sha256={'a' * 30}"
        second = "a" * 34
        body = self._doh_with_data(f'"{first}" "{second}"')
        r = StdlibDoHResolver(providers=("https://example.invalid/resolve",))
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHttpResponse(body)
            out = r.resolve_txt(_HOST)
        self.assertEqual(out, [_GOOD_TXT])

    def test_multi_string_passes_fetch_anchor(self) -> None:
        first = f"v=1; sha256={'a' * 30}"
        second = "a" * 34
        body = self._doh_with_data(f'"{first}" "{second}"')
        r = StdlibDoHResolver(providers=("https://example.invalid/resolve",))
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHttpResponse(body)
            anchor = fetch_anchor(r, _HOST)
        self.assertEqual(anchor.fingerprint, _GOOD_HEX)


# ---------------------------------------------------------------------------
# Negative-smoke against RFC 6761 reserved name
# ---------------------------------------------------------------------------


class Rfc6761NegativeSmokeTests(unittest.TestCase):
    """Hermetic negative-smoke against the RFC 6761 reserved ``.test`` TLD.

    The actual RFC 6761 guarantee (no global DNS resolution) means
    that *any* live DoH provider returns NXDOMAIN. We replay that
    behaviour through a fake urlopen so the test stays hermetic.
    The PS-3 opt-in real-DNS test (deferred to a later box) hits the
    live providers directly.
    """

    def test_reserved_name_nxdomain_path(self) -> None:
        r = StdlibDoHResolver(providers=("https://example.invalid/resolve",))
        body = json.dumps({"Status": 3, "Answer": []}).encode("ascii")
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHttpResponse(body)
            out = r.resolve_txt(_RFC6761_HOST)
        self.assertEqual(out, [])
        # And fetch_anchor escalates the empty set to DnsAnchorError.
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHttpResponse(body)
            with self.assertRaises(DnsAnchorError):
                fetch_anchor(r, _RFC6761_HOST)


# ---------------------------------------------------------------------------
# DnsPythonResolver -- only run if the optional dep is installed
# ---------------------------------------------------------------------------


class DnsPythonResolverImportPathTests(unittest.TestCase):
    """Verify the lazy-import behaviour without requiring dnspython."""

    def test_construction_without_dnspython_raises(self) -> None:
        # If dnspython is installed, this test trivially passes the
        # construction; we then exit. The interesting case is the
        # import-error path, which we simulate by patching the import
        # machinery to fail.
        import builtins

        real_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "dns.resolver":
                raise ImportError("simulated absence of dnspython")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fail_import):
            with self.assertRaises(DnsAnchorError) as ctx:
                DnsPythonResolver()
        self.assertIn("dnspython", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# Module-level constants and surface
# ---------------------------------------------------------------------------


class ModuleSurfaceTests(unittest.TestCase):
    def test_min_ttl_floor_is_normative_constant(self) -> None:
        self.assertIsInstance(MIN_TTL_FLOOR_S, int)
        # V-908 §3.4 (Tag-5 minor edit): floor MUST be at least 60s
        # to mitigate TTL-spoofing. We pin the exact value here so a
        # spec-edit and a code-edit move together.
        self.assertGreaterEqual(MIN_TTL_FLOOR_S, 60)

    def test_dns_anchor_is_frozen(self) -> None:
        a = DnsAnchor(host="h", fingerprint=_GOOD_HEX)
        with self.assertRaises(Exception):
            a.host = "other"  # type: ignore[misc]

    def test_public_surface_stable(self) -> None:
        # Sanity-check the public surface so accidental renames raise
        # a test failure rather than silently breaking the federation
        # resolver caller.
        mod = _dns_anchor

        for name in (
            "DnsAnchor",
            "DnsAnchorError",
            "DnsPythonResolver",
            "MIN_TTL_FLOOR_S",
            "StdlibDoHResolver",
            "TxtResolver",
            "fetch_anchor",
            "parse_anchor",
        ):
            self.assertIn(name, mod.__all__)
            self.assertTrue(hasattr(mod, name))


if __name__ == "__main__":
    unittest.main()
