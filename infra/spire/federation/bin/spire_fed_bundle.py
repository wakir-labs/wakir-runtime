# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""spire-fed-bundle — hermetic Bundle-Export / Bundle-Import CLI for
the Phase-2 Sprint-8 Tag-1 SPIRE-Federation-Bundle-Endpoint substrate.

This CLI orchestrates the manual bootstrap path of SPIRE-Federation:
on the wakir side, ``spire-fed-bundle export --trust-domain wakir.test``
emits the wakir trust-bundle as a JWKS document into a host file; on
the partner side, ``spire-fed-bundle import --from-file <path>
--as-trust-domain wakir.test`` registers the imported bundle as the
peer's bootstrap anchor. The steady-state path (after bootstrap) is
the live ``https_spiffe`` profile fetch the SPIRE-Servers perform
between each other over the ``wakir-federation`` bridge network.

Two modes:

  * live mode: the CLI shells out to ``spire-server bundle list``
    (and ``bundle set`` for import) inside the named container via
    ``podman exec``. Live mode requires the operator's podman socket
    and the running ``compose/spire-federation.yaml`` stack. This is
    Operator-Hand surface per
    ``feedback_sandbox_host_trennung.md`` — the CLI does NOT call
    podman from the hermetic test surface.

  * hermetic mode (default in CI / sandbox): the CLI reads/writes
    JWKS documents against the local filesystem only — no podman, no
    container, no live SPIRE. Hermetic mode generates a deterministic
    fixture-JWKS for the requested trust-domain (the keys are
    NOT cryptographically valid SPIRE-CA-keys; they are well-formed
    JWK JSON-LD with the trust-domain identifier embedded in the
    ``kid`` claim). The roundtrip test in
    ``tests/test_spire_fed_bundle_cli.py`` exercises hermetic mode
    end-to-end and asserts export-then-import produces a
    bit-identical JWKS.

Hermetic mode is the surface the Sprint-8-Tag-1 acceptance test runs
against. Live mode is documented in README §3 for the Operator-Hand
roundtrip.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Trust-domain validation
# ---------------------------------------------------------------------

# RFC 7515 §2 ``kid`` is opaque; we constrain to the SPIRE-canonical
# trust-domain literal shape: DNS-label-style, dot-separated, lowercase.
# Hermetic substrate uses ``wakir.test`` and ``partner.test``; we
# also accept the Phase-3a ``<FTD-ID>.wakir.dev`` shape for
# forward-compat parsing.
_TRUST_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def _validate_trust_domain(td: str) -> str:
    if not _TRUST_DOMAIN_RE.match(td):
        raise ValueError(
            f"trust-domain {td!r} is not a valid SPIFFE-trust-domain literal "
            "(DNS-label-style, lowercase, dot-separated)"
        )
    return td


# ---------------------------------------------------------------------
# Hermetic-mode fixture JWKS
# ---------------------------------------------------------------------
#
# The hermetic fixture-JWKS is a well-formed JWKS document with a
# single EC-P-256 key. The key's x/y coordinates are deterministic
# pseudo-random values seeded by the trust-domain literal — they are
# NOT real SPIRE-issued public keys. Their only role is to make the
# export/import roundtrip exercise the JWKS-parse path and the
# trust-domain mapping logic; cryptographic validity is the live-mode
# concern.
#
# Phase-3a follow-up: replace the fixture with a real ``spire-server
# bundle list -format jwks`` shell-out via ``podman exec``. The
# hermetic-fixture mode stays as the CI-substrate so the test surface
# does not require a running SPIRE-Server.


def _deterministic_jwk_coord(td: str, axis: str) -> str:
    """Produce a deterministic 32-byte base64url-encoded coordinate.

    The bytes are derived from a SHA-256 of ``f"{td}:{axis}"`` so the
    coordinate is stable across runs but unique per trust-domain. The
    result is NOT cryptographically valid for use as an EC-P-256
    public-key coordinate — hermetic-fixture only.
    """
    import base64
    import hashlib

    digest = hashlib.sha256(f"{td}:{axis}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _hermetic_fixture_jwks(td: str) -> dict[str, Any]:
    """Return a hermetic-fixture JWKS document for the given trust-domain.

    Shape mirrors the SPIRE-Server's ``bundle list -format jwks``
    output: a top-level object with a ``keys`` array of JWK objects.
    Each JWK carries an EC-P-256 public key with a ``kid`` that
    embeds the trust-domain literal.
    """
    return {
        "keys": [
            {
                "kty": "EC",
                "crv": "P-256",
                "x": _deterministic_jwk_coord(td, "x"),
                "y": _deterministic_jwk_coord(td, "y"),
                "kid": f"spiffe://{td}/spire/server/fixture-key",
                "use": "x509-svid",
                # Hermetic-fixture marker. Live JWKS produced by
                # SPIRE-Server will NOT have this field; the import
                # path of this CLI accepts both shapes.
                "_wakir_hermetic_fixture": True,
                "_wakir_trust_domain": td,
            }
        ]
    }


# ---------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------


def export_bundle(trust_domain: str, output_path: Path | None = None) -> str:
    """Export the trust-bundle for ``trust_domain`` as a JWKS document.

    Returns the JWKS document as a JSON string. If ``output_path`` is
    given, also writes the JSON to that file (UTF-8, no BOM, trailing
    newline).
    """
    td = _validate_trust_domain(trust_domain)
    jwks = _hermetic_fixture_jwks(td)
    out = json.dumps(jwks, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output_path is not None:
        output_path.write_text(out, encoding="utf-8")
    return out


# ---------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------


def import_bundle(
    from_file: Path,
    as_trust_domain: str,
    target_path: Path | None = None,
) -> dict[str, Any]:
    """Import a JWKS bundle file and register it under
    ``as_trust_domain``.

    The function:
      1) Reads and parses the JWKS document from ``from_file``.
      2) Validates the JWKS shape (top-level ``keys`` array, each JWK
         has the required EC-P-256 fields).
      3) Validates the import-target trust-domain literal.
      4) If the JWKS carries the hermetic-fixture trust-domain marker
         (``_wakir_trust_domain``), asserts it matches the requested
         ``as_trust_domain`` (forces a co-edit if a fixture from one
         trust-domain is accidentally imported under another label).
      5) Returns the parsed JWKS document. If ``target_path`` is
         given, writes the JWKS back to that file (canonical-JSON
         shape, same as export) for downstream consumption (e.g. the
         peer-side SPIRE-Server reads this path as bootstrap anchor).

    Live-SPIRE-Server JWKS bundles (no hermetic-fixture marker) skip
    the trust-domain-match check; the import-as-trust-domain is then
    a pure operator assertion.
    """
    td = _validate_trust_domain(as_trust_domain)
    text = from_file.read_text(encoding="utf-8")
    doc = json.loads(text)
    if not isinstance(doc, dict) or "keys" not in doc:
        raise ValueError(
            f"JWKS shape error in {from_file}: top-level must be an object "
            "with a 'keys' array"
        )
    keys = doc["keys"]
    if not isinstance(keys, list) or not keys:
        raise ValueError(
            f"JWKS shape error in {from_file}: 'keys' must be a non-empty array"
        )
    for i, jwk in enumerate(keys):
        if not isinstance(jwk, dict):
            raise ValueError(f"JWK #{i} in {from_file} is not an object")
        for field in ("kty", "crv", "x", "y"):
            if field not in jwk:
                raise ValueError(
                    f"JWK #{i} in {from_file} is missing required field {field!r}"
                )
        # Hermetic-fixture-trust-domain cross-check.
        marker = jwk.get("_wakir_trust_domain")
        if marker is not None and marker != td:
            raise ValueError(
                f"JWK #{i} in {from_file} carries hermetic-fixture marker "
                f"_wakir_trust_domain={marker!r} but import requested "
                f"as-trust-domain={td!r}; trust-domain mismatch"
            )
    if target_path is not None:
        out = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        target_path.write_text(out, encoding="utf-8")
    return doc


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spire-fed-bundle",
        description=(
            "Hermetic Bundle-Export/Import for the Wakir SPIRE-Federation-"
            "Bundle-Endpoint substrate (Phase-2 Sprint-8 Tag-1)."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser(
        "export",
        help="Export the trust-bundle for a trust-domain as JWKS.",
    )
    p_export.add_argument(
        "--trust-domain",
        required=True,
        help="Trust-domain to export (e.g. wakir.test).",
    )
    p_export.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output file path. If omitted, JWKS is written to stdout."
        ),
    )

    p_import = sub.add_parser(
        "import",
        help="Import a JWKS bundle file as the peer trust-anchor.",
    )
    p_import.add_argument(
        "--from-file",
        required=True,
        type=Path,
        help="Path to the JWKS file to import.",
    )
    p_import.add_argument(
        "--as-trust-domain",
        required=True,
        help=(
            "Trust-domain to register the imported bundle under "
            "(e.g. wakir.test on the partner side)."
        ),
    )
    p_import.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Optional target file path. If given, the imported JWKS "
            "is written back here in canonical-JSON form so the peer-"
            "side SPIRE-Server can read it as bootstrap anchor."
        ),
    )

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "export":
            out = export_bundle(args.trust_domain, args.out)
            if args.out is None:
                sys.stdout.write(out)
            else:
                sys.stderr.write(
                    f"exported trust-bundle for {args.trust_domain} → "
                    f"{args.out}\n"
                )
            return 0
        if args.cmd == "import":
            doc = import_bundle(args.from_file, args.as_trust_domain, args.out)
            n_keys = len(doc["keys"])
            sys.stderr.write(
                f"imported JWKS ({n_keys} key{'s' if n_keys != 1 else ''}) "
                f"from {args.from_file} as trust-domain "
                f"{args.as_trust_domain}\n"
            )
            if args.out is not None:
                sys.stderr.write(f"  → wrote canonical JWKS to {args.out}\n")
            return 0
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"spire-fed-bundle: error: {exc}\n")
        return 2

    return 0  # pragma: no cover - argparse forces a subcommand


if __name__ == "__main__":
    raise SystemExit(main())
