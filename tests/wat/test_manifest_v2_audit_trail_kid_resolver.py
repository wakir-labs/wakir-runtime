# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Phase-2 Sprint-5 Tag-3 follow-up wire-ups.

Two Cross-Review items left explicitly open by Sprint-5 Tag-2 are
closed here:

1. **as_audit_trail_entry 11 -> 12 field update** for ``signature_status``
   (Lena Cross-Review consumption, additive within
   ``wakir-verify-manifest-v2/0``). The audit-trail-entry export contract
   now carries the signature verdict as the twelfth pinned key so the
   frontend AuditTrailEntry consumer can render a signature posture
   without re-walking ``branches[]``.

2. **Kid-Resolver-Bridge** to Reza Sprint-4 Tag-3
   :mod:`wirelang.identity.kid_resolver` via the WAT-side
   :mod:`wat.identity.anchor_kid` bridge (Sprint-4 Tag-5). The
   verifier-stub gains an optional ``verify_signature_aip_doc`` kwarg
   (and ``--verify-signature-aip-doc`` CLI flag) that resolves the
   signature slot's ``kid`` to a public key against an AIP document.
   Z-1-Cross-Review substance.

Tests are Apache-2.0 so external re-implementers can use them as
black-box conformance vectors against their own verifier wire-ups.

Test inventory (6 hermetic tests):

- T-WAT-AT-SIG-01 audit-trail-entry exposes signature_status under
  verified path (12-field check, value-pin).
- T-WAT-AT-SIG-02 audit-trail-entry default empty signature_status
  (backward-compat — no verification requested -> empty string).
- T-WAT-KID-RESOLVER-BRIDGE-01 happy path: AIP document carrying the
  signer's kid resolves to the matching public key and a signed
  manifest verifies via the bridge (no caller-supplied raw key).
- T-WAT-KID-RESOLVER-BRIDGE-02 wrong-kid path: AIP document does NOT
  carry the kid -> structural-error (bridge surface).
- T-WAT-KID-RESOLVER-BRIDGE-03 precedence: caller-supplied raw pubkey
  wins over the AIP-document bridge even when both are passed.
- T-WAT-KID-RESOLVER-BRIDGE-04 CLI flag + AIP-doc-path: end-to-end CLI
  invocation with --verify-signature-aip-doc resolves and verifies.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wat.identity.manifest_signing import (
    envelope_with_signature,
    sign_manifest,
)
from wat.merkle.aggregator import build_merkle_tree, compute_leaf_hash
from wat.verify.manifest_v2 import (
    ManifestV2Result,
    main as verifier_main,
    verify_manifest_v2_file,
)


# ---------------------------------------------------------------------------
# Fixtures: Ed25519 keypair from a fixed seed for byte-stable signatures.
# Mirrors the Sprint-5 Tag-2 wire-up tests so the two test files share
# vector-compat by construction.
# ---------------------------------------------------------------------------


_FIXED_SEED_HEX = (
    "5cbd7fdeefb8a25b85aaf80be58fd3da26d31a99318ef6cd28fd06f3fbb4b3a8"
)
_KID = "wat-anchor-2026-05"


def _fixed_keypair() -> tuple[bytes, bytes]:
    seed = bytes.fromhex(_FIXED_SEED_HEX)
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pub_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return seed, pub_bytes


def _other_keypair() -> tuple[bytes, bytes]:
    seed = hashlib.sha256(b"other-anchor-key-2026-05-11").digest()
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pub_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return seed, pub_bytes


# ---------------------------------------------------------------------------
# Manifest + AIP-document builders.
# ---------------------------------------------------------------------------


def _make_event(idx: int, *, capref_hash_hex: str = "") -> Dict[str, str]:
    return {
        "event_id": f"evt-{idx}",
        "time": f"2026-05-26T17:00:0{idx}Z",
        "payload_hash": hashlib.sha256(f"payload-{idx}".encode()).hexdigest(),
        "capability_token_hash": capref_hash_hex,
    }


def _build_v2_manifest(
    events: Sequence[Dict[str, str]],
    multi_cap: Dict[str, List[str]],
) -> Dict:
    leaves_bytes = [
        compute_leaf_hash(
            event_id=ev["event_id"],
            time=ev["time"],
            payload_hash=ev["payload_hash"],
            capability_token_hash=ev["capability_token_hash"],
        )
        for ev in events
    ]
    root, levels = build_merkle_tree(leaves_bytes)
    enriched_events = [
        {**ev, "leaf": leaves_bytes[i].hex()} for i, ev in enumerate(events)
    ]
    base: Dict[str, Any] = {
        "version": "wat-manifest/2.0",
        "hour_slot": "2026-05-26T17",
        "merkle_root": root.hex(),
        "event_count": len(events),
        "events": enriched_events,
        "leaves": [leaf.hex() for leaf in leaves_bytes],
        "tree_levels": [[node.hex() for node in level] for level in levels],
        "build_time": "2026-05-26T17:00:00Z",
    }
    multi_cap_events: Dict[str, Any] = {}
    distinct: set[str] = set()
    max_caps = 0
    for ev_id, caprefs in multi_cap.items():
        leaves = [bytes.fromhex(ref[len("sha256:"):]) for ref in caprefs]
        caprefs_root, _levels = build_merkle_tree(leaves)
        multi_cap_events[ev_id] = {
            "caprefs_full": list(caprefs),
            "caprefs_root": caprefs_root.hex(),
        }
        max_caps = max(max_caps, len(caprefs))
        distinct.update(caprefs)
    base["multi_cap_events"] = multi_cap_events
    base["multi_cap_summary"] = {
        "events_with_multi_cap": len(multi_cap_events),
        "max_caprefs_in_any_event": max_caps,
        "distinct_capability_token_hashes_in_hour": len(distinct),
    }
    return base


def _build_aip_doc(kid: str, pub_bytes: bytes) -> Dict[str, Any]:
    """Build a minimal AIP document with a single public-keys entry.

    Shape pinned to the canonical resolver contract
    (``wirelang.identity.kid_resolver.resolve_kid`` spec §5.9): an
    ``Ed25519`` entry with ``kid``, ``alg``, ``key_hex``, and the
    WAT-domain ``purpose="wat-anchor"`` filter.
    """
    return {
        "version": "aip/1.0",
        "subject": "did:web:example.test",
        "public_keys": [
            {
                "kid": kid,
                "alg": "Ed25519",
                "key_hex": pub_bytes.hex(),
                "purpose": "wat-anchor",
            }
        ],
    }


_CAPREF_1 = "sha256:" + hashlib.sha256(b"capref-1").hexdigest()
_CAPREF_2 = "sha256:" + hashlib.sha256(b"capref-2").hexdigest()


def _write_bytes(tmp_path: Path, blob: bytes, name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_bytes(blob)
    return path


# ---------------------------------------------------------------------------
# T-WAT-AT-SIG-01 audit-trail-entry exposes signature_status under verified
# ---------------------------------------------------------------------------


def test_t_wat_at_sig_01_audit_trail_entry_has_signature_status_verified(
    tmp_path: Path,
) -> None:
    """as_audit_trail_entry includes signature_status='verified' when
    the verifier resolved a signature happy-path.

    Lena Cross-Review-Konsumtion: the frontend AuditTrailEntry
    consumer reads the top-level signature_status to render a posture
    badge. The branches[] entry stays single (manifest-validity);
    signature does not add a second branch in Tag-3 — that is a
    separate paired-update gated on a follow-up Cross-Review.
    """
    priv, pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_bytes(tmp_path, envelope_bytes)

    result = verify_manifest_v2_file(
        path,
        verify_signature=True,
        verify_signature_public_key=pub,
    )
    entry = result.as_audit_trail_entry(hour_slot="2026-05-26T17", event_count=1)

    # 12-field pin.
    assert len(entry) == 12, f"expected 12 keys; got {len(entry)}: {sorted(entry)}"
    assert "signature_status" in entry
    assert entry["signature_status"] == "verified"
    # Mirror invariant: top-level field == as_dict() field.
    assert entry["signature_status"] == result.as_dict()["signature_status"]
    # branches[] unchanged — only manifest-validity, no signature branch.
    assert len(entry["branches"]) == 1
    assert entry["branches"][0]["label"] == "manifest-validity"
    # Determinism: re-dump byte-stable.
    dump_a = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    dump_b = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    assert dump_a == dump_b


# ---------------------------------------------------------------------------
# T-WAT-AT-SIG-02 audit-trail-entry default empty signature_status
# ---------------------------------------------------------------------------


def test_t_wat_at_sig_02_audit_trail_entry_signature_status_empty_by_default(
    tmp_path: Path,
) -> None:
    """Without verify_signature opt-in, audit-trail-entry carries
    signature_status='' (the 'no verdict requested' empty-string
    sentinel — distinct from the explicit 'unsigned-permissive' /
    'unsigned-strict' values).

    Backward-compat pin: a snapshot test in the frontend that pre-dates
    Tag-3 must see the empty string when no signature verification was
    requested. Frontends MUST treat empty-string as 'no verdict
    available' rather than 'unsigned'.
    """
    priv, _pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_bytes(tmp_path, envelope_bytes)

    # Default verify_signature=False.
    result = verify_manifest_v2_file(path)
    entry = result.as_audit_trail_entry()

    assert "signature_status" in entry
    assert entry["signature_status"] == "", (
        f"signature_status must be empty under default-off; got "
        f"{entry['signature_status']!r}"
    )
    # Confirm 12-key shape even when verification was not requested.
    assert len(entry) == 12


# ---------------------------------------------------------------------------
# T-WAT-KID-RESOLVER-BRIDGE-01 happy path
# ---------------------------------------------------------------------------


def test_t_wat_kid_resolver_bridge_01_happy_path(
    tmp_path: Path,
) -> None:
    """A signed manifest verifies via the AIP-document bridge.

    Setup: producer signs a v2 manifest with kid=_KID. The AIP
    document carries a public-keys entry with the same kid plus the
    raw public key. The verifier is asked to verify with the AIP-doc
    bridge (no caller-supplied raw key). The bridge resolves kid ->
    pubkey via the WAT-side wat.identity.anchor_kid, which delegates
    to wirelang.identity.kid_resolver (Reza Sprint-4 Tag-3,
    Z-1-Cross-Review-substance).

    The Tag-5 Tomás bridge module already lives on
    tomas/phase-1b-sprint-4-tag-5-wat-anchor-kid. The canonical
    resolver may or may not live on the verifier's branch; the test
    is parameterised on availability and skips with a clear reason if
    the resolver is not importable (so the test passes on either
    branch state).
    """
    try:
        from wat.identity.anchor_kid import is_kid_resolver_available
    except ImportError:
        import pytest as _pytest
        _pytest.skip("wat.identity.anchor_kid not available on this branch")

    if not is_kid_resolver_available():
        import pytest as _pytest
        _pytest.skip(
            "wirelang.identity.kid_resolver not importable (cross-branch "
            "merge gap; Identity-Substrate Sprint-4 Tag-3 not on this "
            "branch); bridge code path is exercised by tests below."
        )

    priv, pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_bytes(tmp_path, envelope_bytes)

    aip_doc = _build_aip_doc(_KID, pub)

    result = verify_manifest_v2_file(
        path,
        verify_signature=True,
        verify_signature_aip_doc=aip_doc,
    )

    assert result.ok, result.failure_reason
    assert result.signature_status == "verified"


# ---------------------------------------------------------------------------
# T-WAT-KID-RESOLVER-BRIDGE-02 wrong-kid / missing-bridge -> structural-error
# ---------------------------------------------------------------------------


def test_t_wat_kid_resolver_bridge_02_missing_bridge_or_wrong_kid_returns_structural_error(
    tmp_path: Path,
) -> None:
    """The bridge surfaces resolver failures as signature_status=
    'structural-error', with failure_reason starting 'signature:
    kid-resolver bridge:'.

    Two failure axes share this pin (single test guards both):

    - **Canonical resolver not importable** (Sprint-4 Tag-3 branch not
      on this verifier's branch). The bridge probe surfaces a
      'cross-branch merge gap' diagnostic.
    - **AIP document does NOT carry the kid**. The canonical resolver
      raises KidResolverError -> WatAnchorKidError -> structural-error
      with a 'kid not found' diagnostic.

    Either path terminates with a structural-error verdict; the test
    asserts the verdict and the failure_reason prefix without
    branching on the underlying cause (the bridge's job is to flatten
    both into a single observable for the caller).
    """
    priv, _pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_bytes(tmp_path, envelope_bytes)

    # AIP document with a DIFFERENT kid -> resolver path: kid-not-found.
    _, other_pub = _other_keypair()
    aip_doc = _build_aip_doc("not-the-signing-kid", other_pub)

    result = verify_manifest_v2_file(
        path,
        verify_signature=True,
        verify_signature_aip_doc=aip_doc,
    )

    assert not result.ok
    assert result.signature_status == "structural-error", (
        f"expected 'structural-error'; got {result.signature_status!r}, "
        f"failure_reason={result.failure_reason!r}"
    )
    assert result.failure_reason.startswith("signature: kid-resolver bridge:"), (
        f"expected 'signature: kid-resolver bridge:' prefix; got "
        f"{result.failure_reason!r}"
    )


# ---------------------------------------------------------------------------
# T-WAT-KID-RESOLVER-BRIDGE-03 caller-supplied pubkey precedence
# ---------------------------------------------------------------------------


def test_t_wat_kid_resolver_bridge_03_pubkey_wins_over_aip_doc(
    tmp_path: Path,
) -> None:
    """When BOTH verify_signature_public_key and verify_signature_aip_doc
    are supplied, the raw public-key wins and the bridge is skipped.

    Pin: a caller that already holds the right key never needs the
    resolver to run, even when an AIP document is also at hand. The
    bridge is a *convenience* path; the raw-key path is the cheap
    path. Concretely: even an AIP document with the WRONG kid does
    NOT cause a structural-error here, because the bridge does not
    execute.
    """
    priv, pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    path = _write_bytes(tmp_path, envelope_bytes)

    # AIP doc with a WRONG kid would fail the bridge — but the raw
    # pubkey is also supplied, so the bridge is skipped.
    _, other_pub = _other_keypair()
    aip_doc_with_wrong_kid = _build_aip_doc("not-the-signing-kid", other_pub)

    result = verify_manifest_v2_file(
        path,
        verify_signature=True,
        verify_signature_public_key=pub,  # the right key
        verify_signature_aip_doc=aip_doc_with_wrong_kid,  # would fail bridge
    )

    assert result.ok, result.failure_reason
    assert result.signature_status == "verified"


# ---------------------------------------------------------------------------
# T-WAT-KID-RESOLVER-BRIDGE-04 end-to-end CLI with --verify-signature-aip-doc
# ---------------------------------------------------------------------------


def test_t_wat_kid_resolver_bridge_04_cli_with_aip_doc_file(
    tmp_path: Path,
    capsys,
) -> None:
    """End-to-end CLI invocation with --verify-signature-aip-doc.

    Exercises the JSON-file load path on the CLI side and the bridge
    path inside verify_manifest_v2_file. The test SKIPS when the
    canonical resolver is not importable on this branch (cross-branch
    merge gap is exercised by T-02), so the CLI path is only asserted
    when the full chain is available.
    """
    try:
        from wat.identity.anchor_kid import is_kid_resolver_available
    except ImportError:
        import pytest as _pytest
        _pytest.skip("wat.identity.anchor_kid not available on this branch")

    if not is_kid_resolver_available():
        import pytest as _pytest
        _pytest.skip(
            "wirelang.identity.kid_resolver not importable; CLI happy "
            "path requires the canonical resolver branch."
        )

    priv, pub = _fixed_keypair()
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(events, multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]})
    signed = sign_manifest(manifest, priv, kid=_KID)
    envelope_bytes = envelope_with_signature(signed)
    manifest_path = _write_bytes(tmp_path, envelope_bytes, name="manifest.json")

    aip_doc = _build_aip_doc(_KID, pub)
    aip_doc_path = tmp_path / "aip-doc.json"
    aip_doc_path.write_text(json.dumps(aip_doc), encoding="utf-8")

    exit_code = verifier_main(
        [
            "--verify-signature",
            "--verify-signature-aip-doc",
            str(aip_doc_path),
            "--output",
            "json",
            str(manifest_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0, (
        f"CLI exit_code={exit_code}; stdout={captured.out!r}, "
        f"stderr={captured.err!r}"
    )
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == "wakir-verify-manifest-v2/0"
    assert payload["ok"] is True
    assert payload["signature_status"] == "verified"
    assert payload["failure_reason"] == ""
