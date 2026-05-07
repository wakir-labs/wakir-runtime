# SPDX-License-Identifier: Apache-2.0
"""V-908 DNS-anchor resolver.

This module implements the Phase-1b DNS-anchor lookup used by the
Federation-Trust-Document (FTD) verification pipeline specified in
``wirelang/specs/wakir-v-908-federation-resolver-spec.md`` (V-908).

The V-908 spec, §3.4, defines the DNS anchor TXT record at
``_wakir-ftd.<host>`` as carrying a single-string payload of shape::

    v=1; sha256=<64-hex>

where the hex is the canonical FTD-doc fingerprint per §2.1
(``SHA-256(JCS(body without document_signature))``). This module's
responsibility is to fetch the TXT record set, pick the V-908 anchor
record(s), validate the format, and return a :class:`DnsAnchor` on
success or raise :class:`DnsAnchorError` on any failure.

The module is library-agnostic. The resolver behind ``resolve_txt`` is
expressed as a :class:`TxtResolver` :class:`~typing.Protocol`. Two
implementations ship with the module:

* :class:`StdlibDoHResolver` -- DNS-over-HTTPS (RFC 8484 JSON profile)
  via ``urllib.request`` and ``json``. Phase-1b default. Has zero
  third-party dependencies and runs in environments without ``pip``.
* :class:`DnsPythonResolver` -- conventional UDP/TCP DNS via the
  ``dnspython`` library. Optional. Imports lazily so the module is
  importable on systems without ``dnspython`` installed; raises
  :class:`DnsAnchorError` on construction if the library is missing.

Tests inject a custom resolver implementing the same protocol; no
HTTP- or socket-monkeypatching is required.

The Phase-1b boundary is deliberate: this module **only** does DNS
resolution and TXT-record parsing. The fingerprint comparison against
the canonical FTD-doc body, the FTD signature verification, and the
cache poisoning behaviour described in V-908 §4.3 all live in the
caller (the federation resolver, item I-5 PS-4).

V-908 spec cross-references:

* §3 ("Identifier and resolution path") -- resolution flow.
* §3.4 ("DNS anchor") -- TXT-record format ``v=1; sha256=<64-hex>``,
  multi-string-TXT handling, and DNSSEC stance.
* §6.1 ("Phase-1b targets") -- this module is one of the listed
  Phase-1b deliverables (DNS-anchor check inside
  ``federation_resolver.py``).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Protocol


# Per V-908 spec §3.4, the TXT-record payload is exactly
# ``v=1; sha256=<64-hex>`` (lowercase). Whitespace after the semicolon
# is tolerated; the V-908 spec wording uses the form with a single
# space, but DNS providers and zone file authors normalise spacing
# inconsistently. The regex tolerates any inter-token whitespace
# *except* leading/trailing slack on the full string -- callers
# pre-strip outer whitespace before passing to :func:`parse_anchor`.
_TXT_RE = re.compile(r"^v=1;\s*sha256=([0-9a-f]{64})$")


# Phase-1b minimum cache TTL, in seconds. V-908 spec §3.4 plus
# Tag-4 risk-item §8.2 ("TTL-spoofing-risiko bei niedrigen Cache-TTLs"):
# we refuse to honour DNS-derived TTLs below this floor when the caller
# uses :func:`fetch_anchor` to drive a cache. The actual cache lives in
# the federation resolver (item I-5), not here; this floor is the
# normatively-minimum value that callers MUST clamp against. See
# V-908 spec §3.4 for the spec-level wording added in Tag-5 (B-Mikro).
MIN_TTL_FLOOR_S: int = 60


class DnsAnchorError(Exception):
    """Raised when a DNS anchor cannot be resolved or fails to parse.

    A single error type is used for all V-908 anchor-resolution
    failures; the federation resolver maps this to the more specific
    :class:`FTDAnchorError` / :class:`FTDNotFoundError` per V-908 §4.6.
    """


@dataclass(frozen=True)
class DnsAnchor:
    """A successfully-resolved V-908 DNS anchor.

    Attributes:
        host: The DNS query name, including the ``_wakir-ftd.`` prefix
            (e.g. ``"_wakir-ftd.peer-org.example"``).
        fingerprint: The canonical FTD-doc fingerprint as 64 lowercase
            hex characters.
    """

    host: str
    fingerprint: str


class TxtResolver(Protocol):
    """Pluggable DNS TXT-record resolver protocol.

    Implementations MUST return TXT-record strings as ASCII-decoded
    Python strings, with surrounding zone-file quotes already stripped
    and multi-character-string TXT records (RFC 1035 §3.3.14) already
    concatenated into a single string per the V-908 §3.4 normative
    rule (Tag-5 minor edit; see §3.4 of the spec for canonical wording).

    Returning ``[]`` means NXDOMAIN, NoAnswer, or a successful query
    with no TXT records. The caller distinguishes "absent" from
    "transport failure"; transport failures MUST be raised as
    :class:`DnsAnchorError`.
    """

    def resolve_txt(self, name: str, *, timeout_s: float = 3.0) -> list[str]:
        ...


# ---------------------------------------------------------------------------
# StdlibDoHResolver -- Phase-1b default
# ---------------------------------------------------------------------------


class StdlibDoHResolver:
    """DNS-over-HTTPS resolver using only the Python standard library.

    Implements :class:`TxtResolver` against RFC 8484 JSON-formatted
    DoH endpoints. Zero third-party dependencies; works in any
    environment that has ``urllib`` and ``json`` (i.e. all CPython
    deployments since 3.x).

    The default provider list rotates between Google Public DNS and
    Cloudflare DNS. On any provider failure (timeout, HTTP non-200,
    JSON parse error, ``Status != 0`` other than NXDOMAIN-on-success),
    the resolver fails over to the next provider in the list. After
    all providers fail it raises :class:`DnsAnchorError` carrying the
    last-seen exception; the caller does not retry.

    Tag-4 verification (2026-05-06): both providers return RFC-8484
    JSON with HTTP 200 and ``Status: 0`` for live ``example.com``
    TXT lookups in the project sandbox. Tag-4 outbox §1 / §7.

    Args:
        providers: Tuple of DoH JSON endpoint URLs. Default is
            Google + Cloudflare. Test fixtures and ops failover may
            override.
        user_agent: User-Agent string sent with each DoH request.
            Default is ``"wakir-runtime/0.1 (+v908)"`` to keep the
            outbound footprint identifiable to peers and to ourselves
            in DoH-provider logs. Not security-relevant.
    """

    DEFAULT_PROVIDERS: tuple[str, ...] = (
        "https://dns.google/resolve",
        "https://cloudflare-dns.com/dns-query",
    )

    DEFAULT_USER_AGENT = "wakir-runtime/0.1 (+v908)"

    # DNS RR type code 16 = TXT (RFC 1035 §3.2.2).
    _TXT_RR_TYPE = 16

    def __init__(
        self,
        providers: Iterable[str] | None = None,
        *,
        user_agent: str | None = None,
    ) -> None:
        if providers is None:
            self._providers: tuple[str, ...] = self.DEFAULT_PROVIDERS
        else:
            self._providers = tuple(providers)
        if not self._providers:
            raise ValueError("StdlibDoHResolver requires at least one provider URL")
        self._user_agent = user_agent or self.DEFAULT_USER_AGENT

    def resolve_txt(self, name: str, *, timeout_s: float = 3.0) -> list[str]:
        if not name:
            raise DnsAnchorError("resolve_txt requires a non-empty name")

        last_err: BaseException | None = None
        for url in self._providers:
            try:
                return self._query_one(url, name, timeout_s=timeout_s)
            except _DohSoftFailure as soft:
                # Soft failures (transport, HTTP-non-200, JSON-decode,
                # provider-side SERVFAIL) drive provider failover.
                last_err = soft.__cause__ or soft
                continue
        raise DnsAnchorError(f"all DoH providers failed for {name!r}: {last_err!r}") from last_err

    # ---- internal helpers -------------------------------------------------

    def _query_one(self, url: str, name: str, *, timeout_s: float) -> list[str]:
        request_url = f"{url}?name={name}&type=TXT"
        req = urllib.request.Request(
            request_url,
            headers={
                "accept": "application/dns-json",
                "user-agent": self._user_agent,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                if resp.status != 200:
                    raise _DohSoftFailure(f"HTTP {resp.status} from {url}")
                body = resp.read()
        except urllib.error.URLError as e:
            raise _DohSoftFailure(f"transport error to {url}: {e!r}") from e
        except TimeoutError as e:  # pragma: no cover -- urllib raises socket.timeout subclass
            raise _DohSoftFailure(f"timeout to {url}: {e!r}") from e

        try:
            payload = json.loads(body)
        except (ValueError, json.JSONDecodeError) as e:
            raise _DohSoftFailure(f"invalid JSON from {url}: {e!r}") from e

        # Status field semantics per RFC 8484 / DoH-JSON conventions:
        #  0 NOERROR -- pick TXT records (may still be empty)
        #  3 NXDOMAIN -- absence; return []
        #  any other -- treat as soft failure (failover to next provider)
        status = payload.get("Status")
        if status == 3:
            return []
        if status != 0:
            raise _DohSoftFailure(f"DoH non-success Status={status!r} from {url}")

        answers = payload.get("Answer") or []
        return list(self._extract_txt_strings(answers))

    def _extract_txt_strings(self, answers: list[dict]) -> Iterable[str]:
        """Pull TXT strings out of a DoH JSON Answer array.

        Each Answer entry has ``type`` (DNS RR type), ``data`` (the
        RR data as a string), plus other fields we ignore here.

        RFC 1035 §3.3.14 allows a TXT RR to consist of multiple
        ``<character-string>`` segments. DoH-JSON encodes such records
        as ``"first" "second"`` (space-separated, each segment quoted)
        in the ``data`` field. V-908 §3.4 (Tag-5 minor edit) requires
        the resolver to concatenate these segments before returning,
        so the caller sees the same single-string payload regardless
        of the wire-level segmentation.

        We implement the concatenation by tokenising on quoted
        substrings: each ``"..."`` segment becomes one piece, and the
        pieces are joined with no separator (RFC 1035 §3.3.14 wording).
        """
        for entry in answers:
            if entry.get("type") != self._TXT_RR_TYPE:
                continue
            raw = entry.get("data", "")
            yield self._concat_multi_string_txt(raw)

    @staticmethod
    def _concat_multi_string_txt(raw: str) -> str:
        """Concatenate RFC 1035 §3.3.14 multi-character-string TXT data.

        Single-string case (``"foo"``) returns ``foo``. Multi-string
        case (``"foo" "bar"``) returns ``foobar``. Unquoted DoH data
        is returned as-is (some providers omit quoting for simple
        ASCII payloads).
        """
        if not raw:
            return ""
        # Fast path: unquoted single payload.
        if not raw.startswith('"'):
            return raw
        # Multi-string path: tokenise quoted segments. We do NOT use a
        # full RFC-1035 escape-aware decoder here; V-908 anchor records
        # carry only ``v``, ``=``, ``;``, hex, and SP/TAB whitespace
        # which are quote-clean. If a future spec extension introduces
        # escaped characters in V-908 anchors, this routine grows.
        out: list[str] = []
        i = 0
        n = len(raw)
        while i < n:
            if raw[i] != '"':
                # Inter-segment whitespace; skip.
                i += 1
                continue
            # Find the closing quote. For Phase-1b we treat the segment
            # as opaque between matching quotes; no backslash-escapes.
            end = raw.find('"', i + 1)
            if end == -1:
                # Malformed quoting -- fall back to the raw payload
                # minus only outer quotes. The caller's parse step
                # will reject if it does not match the V-908 shape.
                return raw.strip('"')
            out.append(raw[i + 1 : end])
            i = end + 1
        return "".join(out)


class _DohSoftFailure(Exception):
    """Internal: a DoH provider-call failure that should drive failover."""


# ---------------------------------------------------------------------------
# DnsPythonResolver -- optional, lazy-import
# ---------------------------------------------------------------------------


class DnsPythonResolver:
    """Conventional DNS resolver via the ``dnspython`` library.

    Requires ``dnspython`` to be installed in the runtime; this is
    deliberately *not* a hard dependency of this module so the
    StdlibDoHResolver path remains usable in dependency-restricted
    environments.

    Future-default note (Tag-4 outbox §1.2): once the
    ``dnspython``-pip-install policy is decided (PS-1, owned by CTO /
    CEO), this resolver becomes the production default for deployments
    where ``dnspython`` is on the path. DoH stays as a fallback for
    sandbox / minimal-dep environments and as the implementation-
    equivalence cross-check (Tag-4 outbox §2.3 test category 3).

    Args:
        nameservers: Optional explicit list of resolver IPs. ``None``
            means "use the OS-default resolver list" (recommended for
            Phase-1b; a deployment that needs a private resolver
            overrides this).
    """

    def __init__(self, nameservers: list[str] | None = None) -> None:
        try:
            import dns.resolver  # noqa: F401  -- presence check only
        except ImportError as e:
            raise DnsAnchorError(
                "DnsPythonResolver requires the 'dnspython' package; "
                "use StdlibDoHResolver or install dnspython"
            ) from e
        self._nameservers = nameservers

    def resolve_txt(self, name: str, *, timeout_s: float = 3.0) -> list[str]:
        # Imported lazily on each call to keep the cold-import cost
        # off the StdlibDoHResolver hot path. The module-level import
        # in __init__ guarantees the package is installed; this
        # in-method import is essentially free after the first call.
        import dns.exception
        import dns.resolver

        r = dns.resolver.Resolver(configure=True)
        if self._nameservers:
            r.nameservers = list(self._nameservers)
        r.lifetime = timeout_s
        try:
            ans = r.resolve(name, "TXT")
        except dns.resolver.NXDOMAIN:
            return []
        except dns.resolver.NoAnswer:
            return []
        except dns.exception.DNSException as e:
            raise DnsAnchorError(f"dnspython resolve failed for {name!r}: {e!r}") from e

        out: list[str] = []
        for rdata in ans:
            # rdata.strings is a tuple of bytes, one per
            # <character-string> segment (RFC 1035 §3.3.14). We
            # concatenate per V-908 §3.4 to give the caller a single
            # string regardless of multi-string segmentation.
            joined = b"".join(rdata.strings).decode("ascii", errors="replace")
            out.append(joined)
        return out


# ---------------------------------------------------------------------------
# Anchor parser -- backend-independent
# ---------------------------------------------------------------------------


def parse_anchor(host: str, txt_records: Iterable[str]) -> DnsAnchor:
    """Pick and validate the V-908 anchor TXT record from a TXT-set.

    Args:
        host: The DNS query name (informational; copied into the
            returned :class:`DnsAnchor`).
        txt_records: TXT-record strings as returned by a
            :class:`TxtResolver`. Whitespace is stripped on each
            record before pattern-matching; case-sensitive matching
            is enforced (V-908 §3.4 requires lowercase hex).

    Returns:
        The :class:`DnsAnchor` for the matching record.

    Raises:
        DnsAnchorError: if no record matches the V-908 shape, or if
            two records match with conflicting fingerprints
            (ambiguous anchor; V-908 trust-model violation).
    """
    matches: list[str] = []
    for s in txt_records:
        m = _TXT_RE.match(s.strip())
        if m:
            matches.append(m.group(1))
    if not matches:
        raise DnsAnchorError(f"no V-908 anchor TXT record at {host!r}")
    distinct = set(matches)
    if len(distinct) > 1:
        raise DnsAnchorError(
            f"ambiguous anchors at {host!r}: {sorted(distinct)!r}"
        )
    return DnsAnchor(host=host, fingerprint=matches[0])


def fetch_anchor(
    resolver: TxtResolver,
    host: str,
    *,
    timeout_s: float = 3.0,
) -> DnsAnchor:
    """Resolve TXT records and parse the V-908 anchor.

    This is the high-level entry point used by the federation
    resolver pipeline (V-908 §4.1 step 2).

    Args:
        resolver: A :class:`TxtResolver` implementation.
        host: Fully-qualified DNS name including the ``_wakir-ftd.``
            prefix (e.g. ``"_wakir-ftd.peer-org.example"``).
        timeout_s: Per-call timeout passed to the resolver.

    Returns:
        The resolved :class:`DnsAnchor`.

    Raises:
        DnsAnchorError: on resolver transport failure, absent record,
            malformed record, or ambiguous record set.
    """
    txt = resolver.resolve_txt(host, timeout_s=timeout_s)
    return parse_anchor(host, txt)


__all__ = [
    "DnsAnchor",
    "DnsAnchorError",
    "DnsPythonResolver",
    "MIN_TTL_FLOOR_S",
    "StdlibDoHResolver",
    "TxtResolver",
    "fetch_anchor",
    "parse_anchor",
]
