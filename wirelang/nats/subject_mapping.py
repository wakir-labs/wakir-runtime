# SPDX-License-Identifier: Apache-2.0
"""NATS subject naming convention and mapping for the Wakir Wirelang
transport substrate.

This module is the operational counterpart of
``specs/nats-subject-mapping-v1.md`` (Phase-1b Sprint-2 Tag-1, S2-Item
I-1). It provides deterministic build / parse / validate helpers for
the canonical subject form

    wakir.<env>.<domain>.<event_type>[.<sub_id>]

and enforces the four-anchor abstraction (Wakir-org / persona /
Wirelang-TV / federation host) documented in §6 of the spec.

The schema regex at ``wirelang/schemas/layer-0-transport.json``
``subject.pattern`` is the single source of pattern truth. This
module narrows but does not widen that regex. The wildcard /
subject-filter rules (W1..W9) are enforced for stream patterns
and consumer filters per §7.

Public surface (re-exported from :mod:`wirelang.nats.__init__`):

- :class:`SubjectV1`
- :class:`SubjectFormatError`
- :func:`build_subject`
- :func:`parse_subject`
- :func:`roundtrip`
- :func:`validate_stream_pattern`
- :func:`validate_consumer_filter`
- :func:`schema_for_subject`
- :func:`persona_slug`
- :func:`tv_anchor`
- :func:`federation_host_slug`

Determinism invariants (T-NSM-01..10) live in
``tests/test_nats_subject_mapping.py``.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Reserved environment tokens (§3 R1, schema regex).
RESERVED_ENVS: Tuple[str, ...] = ("dev", "staging", "prod")

#: Reserved domain anchors (§4).
RESERVED_DOMAINS: Tuple[str, ...] = (
    "agent",
    "wat",
    "aip",
    "cap",
    "federation",
    "meta",
    "treasury",
    "comms",
)

#: Reserved event-type prefixes per domain (§5). The value is a tuple
#: of fully-qualified event_type strings (the form that goes into the
#: subject token).
RESERVED_EVENT_TYPES: dict[str, Tuple[str, ...]] = {
    "aip": (
        "aip.document.published",
        "aip.document.rotated",
        "aip.document.revoked",
        "aip.document.fetched",
    ),
    "cap": (
        "cap.token.issued",
        "cap.token.appended",
        "cap.token.sealed",
        "cap.token.revoked",
        "cap.token.verified",
    ),
    "federation": (
        "federation.ftd.published",
        "federation.ftd.rotated",
        "federation.peer.admitted",
        "federation.route.added",
        "federation.route.removed",
    ),
    "wat": (
        "wat.audit.anchor.created",
        "wat.leaf.federated.attached",
    ),
    "agent": (
        "agent.task.assigned",
        "agent.task.accepted",
        "agent.task.completed",
    ),
    "meta": (
        "meta.schema.deprecation",
        "meta.vocabulary.bumped",
        "meta.capability.issued",
    ),
    "treasury": (),  # reserved, not yet wired
    "comms": (),     # reserved, not yet wired
}

#: Schema-Registry inventory hint (§8). Maps domain × event_type-prefix
#: to the canonical schema $id that consumers SHOULD expect on the
#: CloudEvents ``schemaid`` attribute. Advisory, not authoritative.
_SCHEMA_INVENTORY = {
    "aip.document": "https://wakir.dev/wirelang/schema/aip-document/0.1.0",
    "cap.token": "https://wakir.dev/wirelang/schema/layer-3-capability-token/0.1.0",
    "federation.ftd": "https://wakir.dev/wirelang/schema/federation-trust-document/0.1.0",
    "federation.peer": "https://wakir.dev/wirelang/schema/federation-trust-document/0.1.0",
    "federation.route": "https://wakir.dev/wirelang/schema/federation-trust-document/0.1.0",
    "wat.audit": None,        # Tomás-owner schema, no Wirelang authoritative hint
    "wat.leaf": None,
    "agent.task": "https://wakir.dev/wirelang/schema/layer-2-semantic/0.1.0",
    "meta.schema": "https://wakir.dev/wirelang/schema/layer-2-semantic/0.1.0",
    "meta.vocabulary": "https://wakir.dev/wirelang/schema/layer-2-semantic/0.1.0",
    "meta.capability": "https://wakir.dev/wirelang/schema/layer-2-semantic/0.1.0",
}

#: Maximum sub_id length in octets (§3 R4).
MAX_SUB_ID_OCTETS = 64

# ---------------------------------------------------------------------------
# Regexes (kept in lock-step with schemas/layer-0-transport.json)
# ---------------------------------------------------------------------------

# Mirror of the schema regex — used for end-to-end compatibility
# verification (T-NSM-10). Single source of truth remains the schema
# JSON file; this constant is a compile-time mirror that the test
# suite asserts identical against the on-disk schema.
SCHEMA_SUBJECT_REGEX = re.compile(
    r"^wakir\.(dev|staging|prod)\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_.-]*(\.[a-zA-Z0-9_.-]+)?$"
)

# Token regexes (per §3 table)
_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_SUB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_PERSONA_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")
_TV_ANCHOR_RE = re.compile(r"^tv\.w\.(\d+)(?:\.([a-z0-9-]+))?$")
_FEDERATION_HOST_SLUG_RE = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SubjectFormatError(ValueError):
    """Raised when a subject string violates a Wirelang rule.

    The exception message embeds the rule id (``R1``..``R5``,
    ``W1``..``W9``) for grep-friendly diagnostics.
    """


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubjectV1:
    """Parsed Wirelang NATS subject (v1)."""

    env: str
    domain: str
    event_type: str
    sub_id: Optional[str] = None

    def to_string(self) -> str:
        return build_subject(self.env, self.domain, self.event_type, self.sub_id)


# ---------------------------------------------------------------------------
# Build / parse
# ---------------------------------------------------------------------------


def build_subject(
    env: str,
    domain: str,
    event_type: str,
    sub_id: Optional[str] = None,
) -> str:
    """Build a canonical Wirelang NATS subject string.

    Raises:
        SubjectFormatError: if any rule R1..R5 is violated, or the
            resulting string would not match the schema regex.
    """

    # R1: lowercase ASCII for env, domain, event_type
    if env != env.lower():
        raise SubjectFormatError(f"R1: env must be lowercase ASCII, got {env!r}")

    # Schema constraint: env enum
    if env not in RESERVED_ENVS:
        raise SubjectFormatError(
            f"R1: env must be one of {RESERVED_ENVS}, got {env!r}"
        )

    if not _DOMAIN_RE.match(domain):
        raise SubjectFormatError(
            f"R1/R2: domain {domain!r} must match {_DOMAIN_RE.pattern}"
        )

    # §4 reserved domains — soft warn for unknown (R5 spirit, forward-compat)
    if domain not in RESERVED_DOMAINS:
        warnings.warn(
            f"domain {domain!r} is not in the §4 reserved list "
            f"{RESERVED_DOMAINS}; accepting for forward-compatibility "
            f"(R5). Phase-1b Sprint-2 Tag-1 may tighten to hard-reject "
            f"in v1.1.",
            stacklevel=2,
        )

    if not _EVENT_TYPE_RE.match(event_type):
        raise SubjectFormatError(
            f"R3: event_type {event_type!r} must match {_EVENT_TYPE_RE.pattern}"
        )

    if sub_id is not None:
        if len(sub_id) < 1:
            raise SubjectFormatError("R4: sub_id must be ≥ 1 character when present")
        if len(sub_id.encode("utf-8")) > MAX_SUB_ID_OCTETS:
            raise SubjectFormatError(
                f"R4: sub_id exceeds {MAX_SUB_ID_OCTETS} octets"
            )
        if not _SUB_ID_RE.match(sub_id):
            raise SubjectFormatError(
                f"R4: sub_id {sub_id!r} must match {_SUB_ID_RE.pattern}"
            )

    parts = ["wakir", env, domain, event_type]
    if sub_id is not None:
        parts.append(sub_id)
    subject = ".".join(parts)

    # T-NSM-10: schema-regex compatibility
    if not SCHEMA_SUBJECT_REGEX.match(subject):
        raise SubjectFormatError(
            f"R0: built subject {subject!r} does not match schema regex"
        )

    return subject


def parse_subject(subject: str) -> SubjectV1:
    """Parse a canonical Wirelang NATS subject string.

    Raises:
        SubjectFormatError: on regex mismatch or rule violations.
    """

    if not isinstance(subject, str) or not subject:
        raise SubjectFormatError("R0: subject must be a non-empty string")

    if not SCHEMA_SUBJECT_REGEX.match(subject):
        raise SubjectFormatError(
            f"R0: subject {subject!r} does not match schema regex"
        )

    # The regex's last group captures everything after the third dot
    # (including additional dots inside event_type). To recover the
    # four logical anchors, walk the tokens deterministically:
    #
    #   wakir . <env> . <domain> . <event_type ...> [. <sub_id>]
    #
    # We know:
    #   - tokens[0] == "wakir"
    #   - tokens[1] ∈ RESERVED_ENVS
    #   - tokens[2] is the domain
    #   - tokens[3:] is event_type [+ optional sub_id]
    #
    # We disambiguate the optional sub_id by looking at:
    #   (a) last token is a recognised persona-slug, OR
    #   (b) tokens >= 5 with last token matching _SUB_ID_RE and a
    #       known event_type prefix at tokens[3..-1].
    #
    # For determinism we use a simple, conservative rule: if the
    # last token can be interpreted as a sub_id under §6 anchors
    # (persona, tv.w.<n>[.<step>], or federation host-slug) and the
    # event_type without the last token is a §5-reserved prefix,
    # then split off the sub_id. Otherwise treat all trailing
    # tokens as event_type.

    tokens = subject.split(".")
    assert tokens[0] == "wakir"
    env = tokens[1]
    domain = tokens[2]

    if env not in RESERVED_ENVS:  # belt-and-braces, regex already enforces
        raise SubjectFormatError(
            f"R1: env must be one of {RESERVED_ENVS}, got {env!r}"
        )
    if not _DOMAIN_RE.match(domain):
        raise SubjectFormatError(
            f"R1/R2: domain {domain!r} must match {_DOMAIN_RE.pattern}"
        )

    rest = tokens[3:]
    if not rest:
        raise SubjectFormatError("R3: subject must contain an event_type token")

    sub_id: Optional[str] = None
    event_type = ".".join(rest)

    # Try to peel off a sub_id from the end if the prefix is reserved
    # in §5 and the last token looks like a sub_id anchor. This keeps
    # the build/parse roundtrip exact under conservative assumptions
    # AND honours forward-compat (unknown event_types stay intact).
    if len(rest) >= 2:
        candidate_event_type = ".".join(rest[:-1])
        candidate_sub_id = rest[-1]
        if (
            domain in RESERVED_EVENT_TYPES
            and candidate_event_type in RESERVED_EVENT_TYPES[domain]
            and _looks_like_sub_id_anchor(candidate_sub_id)
        ):
            event_type = candidate_event_type
            sub_id = candidate_sub_id

        # Special handling for TV anchors that carry a step
        # ("tv.w.2.issued") — the dotted form can land partly in
        # event_type. Recover by walking back further if event_type
        # ends with a recognised event_type AND the trailing tail
        # forms a TV anchor.
        if sub_id is None and len(rest) >= 4:
            for split in range(len(rest) - 1, 0, -1):
                candidate_event_type = ".".join(rest[:split])
                candidate_sub_id = ".".join(rest[split:])
                if (
                    domain in RESERVED_EVENT_TYPES
                    and candidate_event_type in RESERVED_EVENT_TYPES[domain]
                    and _looks_like_sub_id_anchor(candidate_sub_id)
                ):
                    event_type = candidate_event_type
                    sub_id = candidate_sub_id
                    break

    if not _EVENT_TYPE_RE.match(event_type):
        raise SubjectFormatError(
            f"R3: event_type {event_type!r} must match {_EVENT_TYPE_RE.pattern}"
        )

    if sub_id is not None:
        if len(sub_id.encode("utf-8")) > MAX_SUB_ID_OCTETS:
            raise SubjectFormatError(
                f"R4: sub_id exceeds {MAX_SUB_ID_OCTETS} octets"
            )

    return SubjectV1(env=env, domain=domain, event_type=event_type, sub_id=sub_id)


def roundtrip(subject: str) -> str:
    """Parse and rebuild ``subject``; output is byte-identical for
    canonical inputs (T-NSM-02)."""

    parsed = parse_subject(subject)
    return build_subject(parsed.env, parsed.domain, parsed.event_type, parsed.sub_id)


# ---------------------------------------------------------------------------
# Anchor extraction (§6)
# ---------------------------------------------------------------------------


def _looks_like_sub_id_anchor(sub_id: str) -> bool:
    """Conservative classifier: is ``sub_id`` recognisable as one of
    the §6 anchors?"""

    if persona_slug(sub_id) is not None:
        return True
    if tv_anchor(sub_id) is not None:
        return True
    if _FEDERATION_HOST_SLUG_RE.match(sub_id):
        # Federation host-slug per §6.4 R6 (.→- stripping). The slug
        # is dot-stable form — no embedded dots.
        if "." not in sub_id:
            return True
    return False


def persona_slug(sub_id: Optional[str]) -> Optional[str]:
    """Return the persona slug if ``sub_id`` matches §6.2, else None."""

    if sub_id is None:
        return None
    if _PERSONA_SLUG_RE.match(sub_id):
        return sub_id
    return None


def tv_anchor(sub_id: Optional[str]) -> Optional[Tuple[int, Optional[str]]]:
    """Return ``(n, step)`` if ``sub_id`` matches §6.3, else None."""

    if sub_id is None:
        return None
    m = _TV_ANCHOR_RE.match(sub_id)
    if not m:
        return None
    n = int(m.group(1))
    step = m.group(2)
    return (n, step)


def federation_host_slug(host_fqdn: str) -> str:
    """Normalise an FQDN to the §6.4 R6 host-slug form.

    Replaces ``.`` with ``-`` so that the slug is dot-stable as a
    single sub_id token. Idempotent (T-NSM-06).

    Raises:
        SubjectFormatError: if the input cannot be normalised to a
            valid sub_id token.
    """

    if not isinstance(host_fqdn, str) or not host_fqdn:
        raise SubjectFormatError("R6: host_fqdn must be a non-empty string")

    slug = host_fqdn.lower().replace(".", "-")

    # Allow already-normalised input idempotently
    if not re.match(r"^[a-z0-9-]+$", slug):
        raise SubjectFormatError(
            f"R6: host_fqdn {host_fqdn!r} contains characters that cannot "
            f"be normalised to a host-slug"
        )

    if len(slug.encode("utf-8")) > MAX_SUB_ID_OCTETS:
        raise SubjectFormatError(
            f"R4/R6: normalised host-slug {slug!r} exceeds {MAX_SUB_ID_OCTETS} octets"
        )

    return slug


# ---------------------------------------------------------------------------
# Wildcard / subject-filter validation (§7)
# ---------------------------------------------------------------------------


def validate_stream_pattern(pattern: str) -> None:
    """Validate a JetStream stream ``subjects[]`` entry against
    rules W1..W3 (§7.1).

    Raises:
        SubjectFormatError: on rule violation.
    """

    if not isinstance(pattern, str) or not pattern:
        raise SubjectFormatError("W1: stream pattern must be a non-empty string")

    tokens = pattern.split(".")

    # W1: must be rooted at wakir.<env>.<domain>.>
    if tokens[0] != "wakir":
        raise SubjectFormatError(
            f"W1: stream pattern {pattern!r} must be rooted at 'wakir' org anchor"
        )

    # W2: cross-env stream FORBIDDEN — checked BEFORE length check so
    # short cross-env wildcards ("wakir.>") are diagnosed with the
    # correct rule id. tokens[1] is env-position when present; if
    # absent, treat as cross-env wildcard implicitly.
    if len(tokens) < 2 or tokens[1] in ("*", ">"):
        env_token = tokens[1] if len(tokens) >= 2 else "<missing>"
        raise SubjectFormatError(
            f"W2: cross-env stream pattern FORBIDDEN; env wildcard {env_token!r}"
        )

    if len(tokens) < 4:
        raise SubjectFormatError(
            f"W1: stream pattern {pattern!r} must include env+domain"
        )

    env = tokens[1]
    if env not in RESERVED_ENVS:
        raise SubjectFormatError(
            f"W2: env {env!r} must be one of {RESERVED_ENVS}"
        )

    domain = tokens[2]
    if domain in ("*", ">"):
        raise SubjectFormatError(
            f"W1: stream pattern {pattern!r} must pin a single domain "
            f"(not {domain!r})"
        )

    # W3: cross-org stream FORBIDDEN at v1 — already enforced by W1
    # (org anchor is fixed literal "wakir").


def validate_consumer_filter(pattern: str) -> None:
    """Validate a consumer subscription filter against rules W4..W6
    (§7.2).

    Raises:
        SubjectFormatError: on rule violation.
    """

    if not isinstance(pattern, str) or not pattern:
        raise SubjectFormatError("W4: consumer filter must be a non-empty string")

    tokens = pattern.split(".")

    if tokens[0] != "wakir":
        raise SubjectFormatError(
            f"W4: consumer filter {pattern!r} must be rooted at 'wakir' org anchor"
        )

    if len(tokens) < 3:
        raise SubjectFormatError(
            f"W4: consumer filter {pattern!r} too short"
        )

    env = tokens[1]
    if env in ("*", ">"):
        raise SubjectFormatError(
            f"W2: cross-env consumer filter FORBIDDEN; env wildcard {env!r}"
        )
    if env not in RESERVED_ENVS:
        raise SubjectFormatError(
            f"W4: env {env!r} must be one of {RESERVED_ENVS}"
        )

    if len(tokens) < 4:
        raise SubjectFormatError(
            f"W4: consumer filter {pattern!r} must include domain"
        )

    domain = tokens[2]
    if domain in ("*", ">") and tokens[2] == "*":
        raise SubjectFormatError(
            f"W4: consumer filter {pattern!r} must pin a single domain"
        )

    # W6: forbid `*` at the event_type slot — event_type is dot-prefixed
    # and `*` matches a single token only, which is ambiguous against
    # reverse-DNS event_types.
    if len(tokens) >= 5:
        # Position 3 is the start of event_type. If it's "*", reject.
        if tokens[3] == "*":
            raise SubjectFormatError(
                f"W6: '*' at event_type position is ambiguous against "
                f"reverse-DNS event_types; use '>' after <domain> instead "
                f"(pattern={pattern!r})"
            )

    # Otherwise pattern is acceptable. Stream-pattern callers should
    # use validate_stream_pattern instead.


# ---------------------------------------------------------------------------
# Schema-Registry inventory hint (§8)
# ---------------------------------------------------------------------------


def schema_for_subject(subject: str) -> Optional[str]:
    """Advisory hint: which schema $id should the CloudEvents
    ``schemaid`` carry for this subject?

    Returns None when the subject does not have a Wirelang-authoritative
    schema (e.g. WAT-domain events owned by Tomás).
    """

    parsed = parse_subject(subject)
    # Lookup by domain.event_type-prefix (first two dotted tokens of
    # event_type). This mirrors the §8 inventory table.
    et_tokens = parsed.event_type.split(".")
    if len(et_tokens) < 2:
        return None
    prefix = ".".join(et_tokens[:2])
    return _SCHEMA_INVENTORY.get(prefix)
