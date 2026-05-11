# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors

"""WAT-side anchor-kid resolver bridge — determinism tests.

Phase-1b Sprint-4 Tag-5: WAT-side parallel of the Identity-Substrate
``kid``-resolver (Identity-Substrate Sprint-4 Tag-3, ``wirelang.identity.kid_resolver``).
These tests exercise the WAT-domain reference shape, the resolver-
availability probe, and the canonical-resolver bridge under the
``purpose == "wat-anchor"`` filter.

Cross-Reference: Identity-Substrate Sprint-4 Tag-3 kid-resolver spec §5.9 (operational
contract) — the WAT-side does NOT re-implement the 6-step filter
chain; it delegates and applies the WAT-domain purpose-filter via
the canonical resolver's ``require_purpose`` parameter.

The 6 tests below split into two cohorts:

- **Standalone cohort (T-WAT-ANCHOR-KID-01..03):** exercise the
  WAT-domain reference primitives without the canonical resolver
  on the import path. Always run.
- **Bridge cohort (T-WAT-ANCHOR-KID-04..06):** exercise the
  bridge against a hand-built AIP document via the canonical
  resolver. Skipped cleanly when the canonical resolver branch
  has not merged yet (``pytest.importorskip``).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from wat.identity import (
    PURPOSE_WAT_ANCHOR,
    ResolvedAnchorKey,
    WatAnchorKidError,
    WatAnchorKidRef,
    is_kid_resolver_available,
    resolve_wat_anchor_kid,
    validate_anchor_kid_ref_shape,
)


# ---------------------------------------------------------------------------
# Fixture helpers.
# ---------------------------------------------------------------------------


# Two RFC 8032 test-vector public keys (32 raw bytes each), used as
# stand-in Ed25519 keys for hand-built AIP-document fragments. Picking
# RFC test vectors keeps the fixture byte-stable across runs and
# documents provenance for future Cross-Review-Zone-1 inspection.
_PUB_A_HEX: str = (
    "d75a980182b10ab7d54bfed3c964073a"
    "0ee172f3daa62325af021a68f707511a"
)
_PUB_B_HEX: str = (
    "3d4017c3e843895a92b70aa74d1b7ebc"
    "9c982ccf2ec4968cc0cd55f12af4660c"
)


def _aip_doc_with_wat_anchor(
    *,
    kid: str = "wat-anchor-2026",
    pub_hex: str = _PUB_A_HEX,
    purpose: str = "wat-anchor",
    validafter: str = "2026-05-01T00:00:00Z",
    validuntil: str | None = "2027-05-01T00:00:00Z",
    extra_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Hand-built minimal AIP doc with a single WAT-anchor entry.

    Matches the Identity-Substrate Sprint-4 Tag-3 fixture-builder convention
    (``_aip_doc_with_two_keys``) byte-shape so that a hypothetical
    cross-suite consumer reads the same field-layout. The
    ``extra_entries`` knob is for tests that need to vary the
    second public-key entry independently (e.g. duplicate-kid,
    wrong-purpose, wrong-alg cases).
    """
    public_keys: list[dict[str, Any]] = [
        {
            "kid": kid,
            "alg": "Ed25519",
            "key_hex": pub_hex,
            "validafter": validafter,
            "validuntil": validuntil,
            "purpose": purpose,
        }
    ]
    if extra_entries is not None:
        public_keys.extend(extra_entries)
    return {
        "aip": "1.0",
        "id": "aip:web:wakir.dev/personas/wat-anchor-test",
        "name": "wat-anchor-test",
        "public_keys": public_keys,
        "delegation": {"mode": "chained"},
        "protocols": ["wirelang/0.1"],
        "expires": "2027-05-01T00:00:00Z",
        "document_signature": {
            "alg": "Ed25519",
            "kid": kid,
            "signature": "00" * 64,
        },
    }


# ---------------------------------------------------------------------------
# Standalone cohort — no canonical-resolver dependency.
# ---------------------------------------------------------------------------


def test_T_WAT_ANCHOR_KID_01_ref_shape_validation_happy_and_failure_modes() -> None:
    """WAT-side reference shape: happy path + four failure modes.

    Pins :func:`validate_anchor_kid_ref_shape` as a callable that
    raises :class:`WatAnchorKidError` on every malformed input and
    returns ``None`` (implicitly) on the happy path. The four
    failure modes mirror the input-validation block of the canonical
    resolver's :func:`resolve_kid` (mapping-shape and kid-shape) but
    re-surfaced as the WAT-domain error type.
    """
    # Happy path: a well-formed WatAnchorKidRef passes silently.
    valid = WatAnchorKidRef(kid="wat-anchor-2026")
    assert validate_anchor_kid_ref_shape(valid) is None

    # With as_of: also valid.
    valid_with_as_of = WatAnchorKidRef(
        kid="wat-anchor-2026",
        as_of=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
    )
    assert validate_anchor_kid_ref_shape(valid_with_as_of) is None

    # Failure: not a WatAnchorKidRef at all.
    with pytest.raises(WatAnchorKidError, match="must be a WatAnchorKidRef"):
        validate_anchor_kid_ref_shape("wat-anchor-2026")  # type: ignore[arg-type]
    with pytest.raises(WatAnchorKidError, match="must be a WatAnchorKidRef"):
        validate_anchor_kid_ref_shape({"kid": "wat-anchor-2026"})  # type: ignore[arg-type]

    # Failure: empty-string kid.
    with pytest.raises(WatAnchorKidError, match="non-empty string"):
        validate_anchor_kid_ref_shape(WatAnchorKidRef(kid=""))

    # Failure: as_of is not a datetime.
    with pytest.raises(WatAnchorKidError, match="must be a datetime or None"):
        validate_anchor_kid_ref_shape(
            WatAnchorKidRef(kid="wat-anchor-2026", as_of="2026-06-01T00:00:00Z"),  # type: ignore[arg-type]
        )


def test_T_WAT_ANCHOR_KID_02_purpose_constant_matches_aip_schema_enum() -> None:
    """The :data:`PURPOSE_WAT_ANCHOR` constant is byte-equal to the
    enum value in the AIP-document schema.

    This is a Cross-Review-Zone-1 drift detector: if Identity-
    Substrate-engineering changes the enum value in
    ``wirelang/schemas/aip-document.json``
    ``public_keys[].purpose`` (e.g. renames ``"wat-anchor"`` to
    ``"wakir-wat-anchor"``), this test fails loud rather than the
    WAT-side resolver silently filtering every entry out.

    The schema-file is read once via :mod:`json` to avoid pulling in
    the jsonschema dependency — this test is hermetic-no-deps.
    """
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    aip_schema_path = repo_root / "wirelang" / "schemas" / "aip-document.json"
    schema = json.loads(aip_schema_path.read_text(encoding="utf-8"))

    purpose_enum = (
        schema["properties"]["public_keys"]["items"]
        ["properties"]["purpose"]["enum"]
    )
    assert PURPOSE_WAT_ANCHOR in purpose_enum, (
        f"PURPOSE_WAT_ANCHOR={PURPOSE_WAT_ANCHOR!r} drifted from the AIP-"
        f"document schema enum {purpose_enum!r}; cross-review-zone-1 "
        f"coordination with Identity-Substrate-engineering required."
    )
    # Pin the specific value too — a rename to "wakir-wat-anchor"
    # must show up as a Test #2 failure, not as Test #4 silently
    # filtering everything out.
    assert PURPOSE_WAT_ANCHOR == "wat-anchor"


def test_T_WAT_ANCHOR_KID_03_resolver_unavailable_yields_clean_wat_error() -> None:
    """When the canonical resolver is not on the import path,
    :func:`resolve_wat_anchor_kid` raises :class:`WatAnchorKidError`
    with a diagnostic that names the missing module.

    This test is the *cross-branch merge-gap* contract: the WAT-side
    must never silently no-op when the canonical resolver is absent.
    The diagnostic message must allow an operator to identify the
    missing module without re-reading source.

    The test runs in two regimes:

    1. **Resolver absent** (current branch state at Sprint-4 Tag-5
       publish time): the test exercises the real error path and
       asserts on the diagnostic.
    2. **Resolver present** (post-merge state with Identity-Substrate
       Sprint-4 Tag-3 on main): the test is skipped to avoid
       masking the bridge cohort's coverage.
    """
    if is_kid_resolver_available():
        pytest.skip(
            "canonical kid-resolver is on the import path; merge-gap "
            "test is irrelevant in this regime — bridge cohort "
            "exercises the resolver call instead."
        )

    ref = WatAnchorKidRef(kid="wat-anchor-2026")
    with pytest.raises(WatAnchorKidError, match="canonical kid-resolver not available"):
        resolve_wat_anchor_kid({"public_keys": []}, ref)


# ---------------------------------------------------------------------------
# Bridge cohort — depends on the canonical resolver.
# ---------------------------------------------------------------------------


def test_T_WAT_ANCHOR_KID_04_happy_path_resolves_wat_anchor_purpose() -> None:
    """Happy path: a single AIP-document entry with
    ``purpose == "wat-anchor"`` resolves through the bridge.

    The returned :class:`ResolvedAnchorKey` carries the 32-byte raw
    public key (decoded from the schema's ``key_hex``), the validity-
    window metadata, and the original kid byte-equal.
    """
    pytest.importorskip("wirelang.identity.kid_resolver")

    doc = _aip_doc_with_wat_anchor()
    ref = WatAnchorKidRef(kid="wat-anchor-2026")
    resolved = resolve_wat_anchor_kid(doc, ref)

    assert isinstance(resolved, ResolvedAnchorKey)
    assert resolved.kid == "wat-anchor-2026"
    assert resolved.public_key == bytes.fromhex(_PUB_A_HEX)
    assert len(resolved.public_key) == 32
    assert resolved.validafter == dt.datetime(
        2026, 5, 1, tzinfo=dt.timezone.utc,
    )
    assert resolved.validuntil == dt.datetime(
        2027, 5, 1, tzinfo=dt.timezone.utc,
    )


def test_T_WAT_ANCHOR_KID_05_wrong_purpose_entry_rejected() -> None:
    """An AIP-document entry whose ``purpose`` is *not* ``"wat-anchor"``
    is filtered out by the bridge and surfaces as a
    :class:`WatAnchorKidError` with the canonical
    :class:`KidResolverError` chained as ``__cause__``.

    This is the WAT-domain purpose-discipline pin: even if a kid is
    structurally resolvable (correct alg, correct key_hex, in
    validity window), it must NOT be accepted as an anchor key
    unless the AIP-document author marked it ``"wat-anchor"``. The
    canonical resolver's ``require_purpose`` parameter does the
    actual filtering; this test pins that the bridge wires it up.
    """
    pytest.importorskip("wirelang.identity.kid_resolver")
    from wirelang.identity.kid_resolver import KidResolverError

    # Single entry marked aip-signing (NOT wat-anchor). Identity-Substrate Sprint-4 Tag-3
    # canonical resolver would resolve this for purpose=aip-signing
    # but our bridge demands purpose=wat-anchor.
    doc = _aip_doc_with_wat_anchor(
        kid="aip-signing-2026",
        purpose="aip-signing",
    )
    ref = WatAnchorKidRef(kid="aip-signing-2026")
    with pytest.raises(WatAnchorKidError) as exc_info:
        resolve_wat_anchor_kid(doc, ref)
    assert "purpose" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, KidResolverError)


def test_T_WAT_ANCHOR_KID_06_kid_not_found_and_as_of_window_enforcement() -> None:
    """Two-in-one bridge-discipline test:

    1. **Kid-not-found:** an AIP-document with a single wat-anchor
       entry under one kid does NOT resolve a different kid; the
       bridge surfaces a :class:`WatAnchorKidError` with the
       canonical error chained.
    2. **Validity-window enforcement:** the ``as_of`` field of the
       :class:`WatAnchorKidRef` is forwarded to the canonical
       resolver. A wat-anchor entry valid 2026-05-01..2027-05-01
       does NOT resolve at ``as_of = 2025-12-01`` (before the
       window).

    Together these pin two of the six canonical-resolver filter
    steps (kid-found, validity-window) as actually reachable
    through the WAT-side bridge.
    """
    pytest.importorskip("wirelang.identity.kid_resolver")
    from wirelang.identity.kid_resolver import KidResolverError

    doc = _aip_doc_with_wat_anchor(kid="wat-anchor-2026")

    # Sub-case 1: kid mismatch.
    ref_unknown = WatAnchorKidRef(kid="wat-anchor-2099")
    with pytest.raises(WatAnchorKidError) as exc_info_a:
        resolve_wat_anchor_kid(doc, ref_unknown)
    assert "wat-anchor-2099" in str(exc_info_a.value) or "not found" in str(
        exc_info_a.value,
    )
    assert isinstance(exc_info_a.value.__cause__, KidResolverError)

    # Sub-case 2: as_of before validafter.
    ref_too_early = WatAnchorKidRef(
        kid="wat-anchor-2026",
        as_of=dt.datetime(2025, 12, 1, tzinfo=dt.timezone.utc),
    )
    with pytest.raises(WatAnchorKidError) as exc_info_b:
        resolve_wat_anchor_kid(doc, ref_too_early)
    assert isinstance(exc_info_b.value.__cause__, KidResolverError)
