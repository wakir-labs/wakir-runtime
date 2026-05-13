# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""spire-fed-bundle-rotator — hermetic Cross-Trust-Domain Bundle Auto-
Rotation CLI for the Phase-2 Sprint-8 Tag-3 federation substrate.

Tag-1 + Tag-2 set up static cross-trust-domain bundles:
``spire-fed-bundle export`` produces a single-key JWKS, the peer
imports it as bootstrap anchor, the agent consumes it. In production
the SPIRE-Server's CA key rotates (default cadence 24h) and the
federated peer must accept BOTH the old and the new key during a
grace-window, then drop the old key once the rotation is complete.
This CLI orchestrates that lifecycle hermetically.

Rotation lifecycle (each step is its own subcommand):

  1) ``rotate``: append a NEW key to an existing trust-bundle JWKS
     while keeping the OLD key. The result is a two-key JWKS where
     both keys are valid for the grace-window. The new key carries a
     ``_wakir_issued_at`` ISO-8601 UTC timestamp marker; the old key
     carries a ``_wakir_not_after`` ISO-8601 UTC timestamp marker
     (now + grace-window).

  2) ``list``: print the JWKS-set contents (one row per key: kid,
     issued_at, not_after, status [valid | grace | expired]).

  3) ``expire``: remove keys whose ``_wakir_not_after`` is in the
     past (relative to ``--now`` argument; the CLI never reads the
     wall-clock implicitly). The result is the post-grace JWKS with
     only the still-valid keys.

  4) ``verify``: given a JWKS and a ``--kid``, return exit-code 0
     if the kid is in the bundle AND still valid (issued_at <= now
     AND (not_after is None OR not_after > now)); exit-code 2
     otherwise. The verification reason is printed to stderr.

The lifecycle subcommands are deterministic given the same inputs
(no clock, no random, no network) — all timestamps are taken from
explicit ``--now`` / ``--issued-at`` arguments. The hermetic test
surface asserts this property end-to-end.

Hermetic-fixture-marker invariant: the rotator preserves the
``_wakir_hermetic_fixture`` / ``_wakir_trust_domain`` markers from
the Tag-1 ``spire-fed-bundle`` CLI on the OLD key; the NEW key is
generated with a rotation-counter suffix appended to the ``kid``
discriminator so the two keys are distinguishable in JWKS-set
verify.

Cross-trust-domain isolation: rotation of a ``wakir.test`` bundle
does NOT touch ``partner.test`` bundles. The CLI refuses to operate
on a bundle whose trust-domain literal does NOT match the
``--trust-domain`` argument (mirror of Tag-1
``spire-fed-bundle import`` trust-domain mismatch guard).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# RFC 7515 §2 ``kid`` opaque; we constrain trust-domain literal shape
# to match Tag-1 ``spire-fed-bundle``.
_TRUST_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def _validate_trust_domain(td: str) -> str:
    if not _TRUST_DOMAIN_RE.match(td):
        raise ValueError(
            f"trust-domain {td!r} is not a valid SPIFFE-trust-domain "
            "literal (DNS-label-style, lowercase, dot-separated)"
        )
    return td


def _parse_iso_utc(stamp: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp. Accepts both ``Z`` and ``+00:00``
    suffixes; rejects naive (timezone-less) timestamps.

    Raises ValueError on malformed or non-UTC inputs.
    """
    # Accept the canonical ISO-8601 ``Z`` suffix by replacing it with
    # ``+00:00`` (datetime.fromisoformat handles the latter natively).
    s = stamp.rstrip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(
            f"timestamp {stamp!r} is not a valid ISO-8601 datetime: {exc}"
        ) from None
    if dt.tzinfo is None:
        raise ValueError(
            f"timestamp {stamp!r} is timezone-naive; must be UTC "
            "(suffix ``Z`` or ``+00:00``)"
        )
    if dt.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(
            f"timestamp {stamp!r} has non-UTC timezone offset; "
            "rotator requires UTC (suffix ``Z`` or ``+00:00``)"
        )
    return dt.astimezone(timezone.utc)


def _format_iso_utc(dt: datetime) -> str:
    """Format a UTC datetime as canonical ``YYYY-MM-DDTHH:MM:SS+00:00``.

    The format MUST be stable for the hermetic-fixture roundtrip test
    (two rotations with the same inputs MUST yield bit-identical JWKS).
    """
    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(
            "internal error: _format_iso_utc requires a UTC-aware datetime"
        )
    # Strip microseconds for stability.
    dt = dt.replace(microsecond=0)
    return dt.isoformat()


def _deterministic_jwk_coord(td: str, axis: str, rotation_counter: int) -> str:
    """Produce a deterministic 32-byte base64url-encoded coordinate.

    Mirrors Tag-1 ``spire_fed_bundle._deterministic_jwk_coord`` but
    additionally folds the rotation-counter into the seed so each
    rotation generation produces a distinct key.
    """
    digest = hashlib.sha256(
        f"{td}:{axis}:rot{rotation_counter}".encode("utf-8")
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _new_jwk(
    trust_domain: str,
    rotation_counter: int,
    issued_at: datetime,
) -> dict[str, Any]:
    """Construct a new JWK for the given trust-domain + rotation-counter.

    The ``kid`` carries both the trust-domain literal and the rotation-
    counter so JWKS-set verify can distinguish old/new keys without
    re-hashing the coordinates.
    """
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _deterministic_jwk_coord(trust_domain, "x", rotation_counter),
        "y": _deterministic_jwk_coord(trust_domain, "y", rotation_counter),
        "kid": (
            f"spiffe://{trust_domain}/spire/server/"
            f"fixture-key-rot{rotation_counter}"
        ),
        "use": "x509-svid",
        "_wakir_hermetic_fixture": True,
        "_wakir_trust_domain": trust_domain,
        "_wakir_rotation_counter": rotation_counter,
        "_wakir_issued_at": _format_iso_utc(issued_at),
    }


# ---------------------------------------------------------------------
# Trust-domain consistency
# ---------------------------------------------------------------------


def _read_jwks(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    doc = json.loads(text)
    if not isinstance(doc, dict) or "keys" not in doc:
        raise ValueError(
            f"JWKS shape error in {path}: top-level must be an object "
            "with a 'keys' array"
        )
    keys = doc["keys"]
    if not isinstance(keys, list) or not keys:
        raise ValueError(
            f"JWKS shape error in {path}: 'keys' must be a non-empty array"
        )
    return doc


def _write_jwks(path: Path, doc: dict[str, Any]) -> None:
    out = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(out, encoding="utf-8")


def _assert_trust_domain_consistency(doc: dict[str, Any], td: str) -> None:
    """Refuse to operate on a bundle whose hermetic-fixture marker does
    NOT match ``td``. Mirror of Tag-1 ``spire-fed-bundle import``
    trust-domain mismatch guard, applied to the in-place rotation path.

    Live SPIRE-Server JWKS bundles (no hermetic-fixture marker) skip
    this check; the trust-domain literal is then a pure operator
    assertion as in Tag-1 import.
    """
    for i, jwk in enumerate(doc["keys"]):
        if not isinstance(jwk, dict):
            raise ValueError(f"JWK #{i} is not an object")
        marker = jwk.get("_wakir_trust_domain")
        if marker is not None and marker != td:
            raise ValueError(
                f"JWK #{i} carries hermetic-fixture marker "
                f"_wakir_trust_domain={marker!r} but rotate requested "
                f"--trust-domain={td!r}; trust-domain mismatch (refusing "
                "to cross-pollinate trust-domain bundles)"
            )


def _max_rotation_counter(doc: dict[str, Any]) -> int:
    """Return the highest ``_wakir_rotation_counter`` in the JWKS, or
    0 if no key carries the marker (first-rotation case)."""
    max_n = 0
    for jwk in doc["keys"]:
        n = jwk.get("_wakir_rotation_counter")
        if isinstance(n, int) and n > max_n:
            max_n = n
    return max_n


# ---------------------------------------------------------------------
# rotate
# ---------------------------------------------------------------------


def rotate_bundle(
    trust_domain: str,
    in_path: Path,
    out_path: Path,
    *,
    now: datetime,
    grace_seconds: int,
) -> dict[str, Any]:
    """Append a new key to the JWKS at ``in_path`` and write the
    result to ``out_path``. The old key(s) get a ``_wakir_not_after``
    marker = now + grace_seconds; the new key is fresh (no
    ``_wakir_not_after``, ``_wakir_issued_at`` = now).

    Returns the new JWKS document. Refuses to operate if ``in_path``
    carries a hermetic-fixture marker for a different trust-domain.
    """
    if grace_seconds < 0:
        raise ValueError(
            f"grace_seconds must be >= 0; got {grace_seconds}"
        )
    td = _validate_trust_domain(trust_domain)
    doc = _read_jwks(in_path)
    _assert_trust_domain_consistency(doc, td)

    # Mark all existing keys with a ``_wakir_not_after`` = now + grace.
    # If a key already carries ``_wakir_not_after``, we KEEP the
    # earliest of the two (subsequent rotations don't extend the
    # grace-window of a key that was already scheduled for expiry).
    new_keys: list[dict[str, Any]] = []
    grace_dt = datetime.fromtimestamp(
        int(now.timestamp()) + grace_seconds, tz=timezone.utc
    )
    grace_stamp = _format_iso_utc(grace_dt)
    for jwk in doc["keys"]:
        jwk_copy = dict(jwk)
        existing = jwk_copy.get("_wakir_not_after")
        if existing is None:
            jwk_copy["_wakir_not_after"] = grace_stamp
        else:
            existing_dt = _parse_iso_utc(existing)
            if grace_dt < existing_dt:
                jwk_copy["_wakir_not_after"] = grace_stamp
            # else keep existing (don't extend a shorter window).
        new_keys.append(jwk_copy)

    rotation_counter = _max_rotation_counter(doc) + 1
    new_keys.append(_new_jwk(td, rotation_counter, now))

    new_doc: dict[str, Any] = {"keys": new_keys}
    _write_jwks(out_path, new_doc)
    return new_doc


# ---------------------------------------------------------------------
# list
# ---------------------------------------------------------------------


def _key_status(jwk: dict[str, Any], now: datetime) -> str:
    """Return 'valid' | 'grace' | 'expired' for the given key."""
    not_after_raw = jwk.get("_wakir_not_after")
    if not_after_raw is None:
        return "valid"
    not_after = _parse_iso_utc(not_after_raw)
    if not_after <= now:
        return "expired"
    return "grace"


def list_keys(
    in_path: Path,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return one row per key: kid, issued_at, not_after, status."""
    doc = _read_jwks(in_path)
    rows: list[dict[str, Any]] = []
    for jwk in doc["keys"]:
        rows.append(
            {
                "kid": jwk.get("kid", "<missing>"),
                "issued_at": jwk.get("_wakir_issued_at"),
                "not_after": jwk.get("_wakir_not_after"),
                "status": _key_status(jwk, now),
                "rotation_counter": jwk.get("_wakir_rotation_counter"),
            }
        )
    return rows


# ---------------------------------------------------------------------
# expire
# ---------------------------------------------------------------------


def expire_bundle(
    trust_domain: str,
    in_path: Path,
    out_path: Path,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Drop keys whose ``_wakir_not_after`` is <= now. Refuses to
    leave the bundle empty (at least one key must remain — the
    operator must rotate BEFORE expiring the last key).
    """
    td = _validate_trust_domain(trust_domain)
    doc = _read_jwks(in_path)
    _assert_trust_domain_consistency(doc, td)
    kept: list[dict[str, Any]] = []
    for jwk in doc["keys"]:
        if _key_status(jwk, now) != "expired":
            kept.append(jwk)
    if not kept:
        raise ValueError(
            f"expire would leave {in_path} with zero valid keys at "
            f"now={_format_iso_utc(now)}; refusing (rotate first, then "
            "expire after the new key is in place)"
        )
    new_doc = {"keys": kept}
    _write_jwks(out_path, new_doc)
    return new_doc


# ---------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------


def verify_kid(
    in_path: Path,
    kid: str,
    now: datetime,
) -> tuple[bool, str]:
    """Return (accepted, reason).

    accepted=True iff the kid is in the bundle AND
      issued_at is None OR issued_at <= now (not-yet-issued check)
      AND
      not_after is None OR not_after > now (grace/expiry check).
    """
    doc = _read_jwks(in_path)
    for jwk in doc["keys"]:
        if jwk.get("kid") != kid:
            continue
        issued_at_raw = jwk.get("_wakir_issued_at")
        if issued_at_raw is not None:
            issued_at = _parse_iso_utc(issued_at_raw)
            if issued_at > now:
                return (
                    False,
                    f"kid {kid!r} found but issued_at "
                    f"{_format_iso_utc(issued_at)} is in the future of "
                    f"now {_format_iso_utc(now)}",
                )
        status = _key_status(jwk, now)
        if status == "expired":
            return (
                False,
                f"kid {kid!r} found but expired at "
                f"_wakir_not_after={jwk.get('_wakir_not_after')!r}",
            )
        return (True, f"kid {kid!r} status={status}")
    return (False, f"kid {kid!r} not in bundle")


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spire-fed-bundle-rotator",
        description=(
            "Cross-Trust-Domain Bundle Auto-Rotation CLI for the Wakir "
            "SPIRE-Federation-Bundle-Endpoint substrate (Phase-2 Sprint-8 "
            "Tag-3). Hermetic mode: all timestamps from --now / --issued-"
            "at arguments; no wall-clock, no random, no network."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # rotate
    p_rotate = sub.add_parser(
        "rotate",
        help=(
            "Append a new key to the JWKS; mark existing keys "
            "with _wakir_not_after = now + grace-seconds."
        ),
    )
    p_rotate.add_argument("--trust-domain", required=True)
    p_rotate.add_argument("--in-file", required=True, type=Path)
    p_rotate.add_argument("--out", required=True, type=Path)
    p_rotate.add_argument(
        "--now",
        required=True,
        help="ISO-8601 UTC timestamp for the rotation moment.",
    )
    p_rotate.add_argument(
        "--grace-seconds",
        type=int,
        default=86400,
        help=(
            "Grace-window duration in seconds before the OLD key(s) "
            "expire. Default 86400 (24h) — production cadence."
        ),
    )

    # list
    p_list = sub.add_parser(
        "list",
        help="Print one row per key with status (valid | grace | expired).",
    )
    p_list.add_argument("--in-file", required=True, type=Path)
    p_list.add_argument(
        "--now",
        required=True,
        help="ISO-8601 UTC timestamp for the status evaluation.",
    )
    p_list.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the human-readable table.",
    )

    # expire
    p_expire = sub.add_parser(
        "expire",
        help=(
            "Drop keys whose _wakir_not_after is <= now. Refuses to "
            "leave the bundle empty."
        ),
    )
    p_expire.add_argument("--trust-domain", required=True)
    p_expire.add_argument("--in-file", required=True, type=Path)
    p_expire.add_argument("--out", required=True, type=Path)
    p_expire.add_argument(
        "--now",
        required=True,
        help="ISO-8601 UTC timestamp for the expiry evaluation.",
    )

    # verify
    p_verify = sub.add_parser(
        "verify",
        help=(
            "Check whether --kid is in the bundle AND still valid at "
            "--now. Exit 0 on accept, 2 on reject."
        ),
    )
    p_verify.add_argument("--in-file", required=True, type=Path)
    p_verify.add_argument("--kid", required=True)
    p_verify.add_argument(
        "--now",
        required=True,
        help="ISO-8601 UTC timestamp for the verify evaluation.",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "rotate":
            now = _parse_iso_utc(args.now)
            rotate_bundle(
                args.trust_domain,
                args.in_file,
                args.out,
                now=now,
                grace_seconds=args.grace_seconds,
            )
            sys.stderr.write(
                f"rotated {args.in_file} → {args.out} "
                f"(trust-domain={args.trust_domain}, now={_format_iso_utc(now)}, "
                f"grace-seconds={args.grace_seconds})\n"
            )
            return 0

        if args.cmd == "list":
            now = _parse_iso_utc(args.now)
            rows = list_keys(args.in_file, now)
            if args.json:
                json.dump(rows, sys.stdout, indent=2, sort_keys=True)
                sys.stdout.write("\n")
            else:
                sys.stdout.write(
                    f"{'kid':<60}  {'status':<8}  "
                    f"{'issued_at':<26}  not_after\n"
                )
                for row in rows:
                    sys.stdout.write(
                        f"{row['kid']:<60}  "
                        f"{row['status']:<8}  "
                        f"{(row['issued_at'] or '-'):<26}  "
                        f"{row['not_after'] or '-'}\n"
                    )
            return 0

        if args.cmd == "expire":
            now = _parse_iso_utc(args.now)
            new_doc = expire_bundle(
                args.trust_domain, args.in_file, args.out, now=now
            )
            n = len(new_doc["keys"])
            sys.stderr.write(
                f"expired {args.in_file} → {args.out} "
                f"(trust-domain={args.trust_domain}, now={_format_iso_utc(now)}, "
                f"kept {n} key{'s' if n != 1 else ''})\n"
            )
            return 0

        if args.cmd == "verify":
            now = _parse_iso_utc(args.now)
            accepted, reason = verify_kid(args.in_file, args.kid, now)
            sys.stderr.write(f"verify: {reason}\n")
            return 0 if accepted else 2

    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"spire-fed-bundle-rotator: error: {exc}\n")
        return 2

    return 0  # pragma: no cover — argparse forces a subcommand


if __name__ == "__main__":
    raise SystemExit(main())
