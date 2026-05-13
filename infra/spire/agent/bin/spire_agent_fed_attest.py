# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic CLI Mock for Sprint-8 Tag-2 SPIRE-Agent-Sidecar cross-trust-
domain X.509-SVID issuance patterns.

This module mirrors the Sprint-8 Tag-1 ``spire_fed_bundle.py`` CLI shape
(import-target for tests, thin wrapper exposed as ``spire-agent-fed-
attest`` shim). It is a Mock/Stub — no live SPIRE-Agent socket is
contacted, no real X.509 material is produced, no cryptographic
properties are claimed. The hermetic goal is to assert the
selector-to-trust-domain mapping pattern and the JWT-SVID fallback path
that Reza's RealNatsConnectionAdapter consumes
(``SPIRE_AGENT_SOCKET=none`` → ``mock-jwt`` auth_mode).

Two subcommands:

* ``fetch-x509``: Given a Workload-Selector (uid:gid:path) and a
  trust-domain hint (wakir.test or partner.test), emit a deterministic
  Mock X.509-SVID descriptor JSON. The selector-to-trust-domain
  mapping is the substrate-level invariant: the same agent can mint
  SVIDs in either trust-domain depending on the selector — this is
  the Cross-Trust-Domain X.509-SVID-Issuance pattern that Tag-2
  surfaces hermetically (no real SVID; selector-mapping shape only).

* ``fetch-jwt``: Given a workload selector and an audience, emit a
  deterministic Mock JWT-SVID descriptor JSON. This is the path
  Reza's RealAdapter consumes when ``SPIRE_AGENT_SOCKET`` is
  ``none`` / unset — the adapter falls back to ``auth_mode="mock-
  jwt"`` and uses a hermetic JWT placeholder. The Tag-2 CLI emits
  the same shape the adapter expects on the SPIRE-side of the
  fallback boundary, so the end-to-end fallback contract is
  testable hermetically from both ends.

Both subcommands are deterministic given the same inputs (no
clock, no random, no network) — the suite asserts this property in
``tests/test_spire_agent_fed_attest_cli.py``.

This module is import-safe: importing it does NOT run the CLI. The
``main()`` entrypoint is only called when invoked as a script (or via
the ``spire-agent-fed-attest`` shim).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any


# Trust-domain literals — accepted set is the Tag-1 federation pair.
# Adding more requires a federates_with block on the server side; this
# Mock keeps the closed-set invariant tested by
# tests/test_spire_agent_fed_attest_cli.py.
_TRUST_DOMAINS_TAG1: frozenset[str] = frozenset(
    {"wakir.test", "partner.test"}
)


# Selector form: uid:gid:path. The Mock validates that all three
# components are present; in real SPIRE the WorkloadAttestor "unix"
# plugin emits selectors derived from /proc and the unix-socket peer.
def _parse_selector(selector: str) -> tuple[str, str, str]:
    parts = selector.split(":", 2)
    if len(parts) != 3:
        raise ValueError(
            f"selector must be uid:gid:path; got {selector!r}"
        )
    uid, gid, path = parts
    if not uid or not gid or not path:
        raise ValueError(
            f"selector components must be non-empty; got {selector!r}"
        )
    return uid, gid, path


def _hermetic_seed(*parts: str) -> str:
    """Deterministic hex digest from input parts.

    Used to derive Mock SVID identifiers so the same input always
    yields the same output (test determinism).
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def fetch_x509_svid(
    selector: str,
    trust_domain: str,
) -> dict[str, Any]:
    """Mock X.509-SVID descriptor.

    The returned dict is a JSON-serializable descriptor — NOT a real
    X.509-SVID. The ``spiffe_id`` follows the SPIFFE-ID URI form
    ``spiffe://<trust_domain>/workload/<seed>``; the ``cert_hint`` is
    a deterministic hex digest derived from the selector + trust-
    domain inputs.

    Raises ValueError on unknown trust-domain or malformed selector.
    """
    if trust_domain not in _TRUST_DOMAINS_TAG1:
        raise ValueError(
            f"trust_domain {trust_domain!r} not in Tag-1 federation pair "
            f"{sorted(_TRUST_DOMAINS_TAG1)!r}"
        )
    uid, gid, path = _parse_selector(selector)
    seed = _hermetic_seed("x509", trust_domain, uid, gid, path)
    return {
        "kind": "x509-svid-mock",
        "spiffe_id": f"spiffe://{trust_domain}/workload/{seed[:16]}",
        "trust_domain": trust_domain,
        "selector": {"uid": uid, "gid": gid, "path": path},
        "cert_hint": seed,
        "_hermetic_marker": "sprint-8-tag-2-spire-agent-fed-attest",
    }


def fetch_jwt_svid(
    selector: str,
    audience: str,
    trust_domain: str,
) -> dict[str, Any]:
    """Mock JWT-SVID descriptor.

    JWT-SVID fallback path — this is the shape Reza's
    RealNatsConnectionAdapter consumes when ``SPIRE_AGENT_SOCKET``
    is unset/none and the adapter falls back to ``auth_mode="mock-
    jwt"`` (Sprint-8 Tag-1 RealAdapter-Mirror substance).

    The audience is part of the seed so different audiences yield
    different Mock tokens (test determinism + audience-binding
    pattern).

    Raises ValueError on unknown trust-domain, malformed selector,
    or empty audience.
    """
    if trust_domain not in _TRUST_DOMAINS_TAG1:
        raise ValueError(
            f"trust_domain {trust_domain!r} not in Tag-1 federation pair "
            f"{sorted(_TRUST_DOMAINS_TAG1)!r}"
        )
    if not audience:
        raise ValueError("audience must be non-empty")
    uid, gid, path = _parse_selector(selector)
    seed = _hermetic_seed("jwt", trust_domain, audience, uid, gid, path)
    return {
        "kind": "jwt-svid-mock",
        "spiffe_id": f"spiffe://{trust_domain}/workload/{seed[:16]}",
        "trust_domain": trust_domain,
        "audience": audience,
        "selector": {"uid": uid, "gid": gid, "path": path},
        "token_hint": seed,
        # Fallback contract: matches the auth_mode literal the
        # RealNatsConnectionAdapter records when SPIRE_AGENT_SOCKET
        # is unset/none. End-to-end fallback contract is testable
        # hermetically from both ends.
        "auth_mode_marker": "mock-jwt",
        "_hermetic_marker": "sprint-8-tag-2-spire-agent-fed-attest",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spire-agent-fed-attest",
        description=(
            "Hermetic Mock CLI for Sprint-8 Tag-2 SPIRE-Agent cross-"
            "trust-domain SVID issuance patterns. No live SPIRE-Agent "
            "socket is contacted."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    x509 = sub.add_parser(
        "fetch-x509",
        help="Mock X.509-SVID for a workload selector + trust-domain.",
    )
    x509.add_argument("--selector", required=True, help="uid:gid:path")
    x509.add_argument(
        "--trust-domain",
        required=True,
        choices=sorted(_TRUST_DOMAINS_TAG1),
    )

    jwt = sub.add_parser(
        "fetch-jwt",
        help=(
            "Mock JWT-SVID for a workload selector + audience + "
            "trust-domain. Fallback path for SPIRE_AGENT_SOCKET=none."
        ),
    )
    jwt.add_argument("--selector", required=True, help="uid:gid:path")
    jwt.add_argument("--audience", required=True)
    jwt.add_argument(
        "--trust-domain",
        required=True,
        choices=sorted(_TRUST_DOMAINS_TAG1),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "fetch-x509":
            out = fetch_x509_svid(args.selector, args.trust_domain)
        elif args.cmd == "fetch-jwt":
            out = fetch_jwt_svid(
                args.selector, args.audience, args.trust_domain
            )
        else:  # pragma: no cover — argparse already enforces required.
            parser.error(f"unknown subcommand {args.cmd!r}")
            return 2
    except ValueError as exc:
        # Exit-code 2 matches Sprint-8 Tag-1 spire-fed-bundle convention
        # (trust-domain mismatch guard).
        print(f"spire-agent-fed-attest: error: {exc}", file=sys.stderr)
        return 2

    json.dump(out, sys.stdout, sort_keys=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — entry-point shim.
    sys.exit(main())
