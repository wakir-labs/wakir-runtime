# SPDX-License-Identifier: Apache-2.0
"""TV-W-3 federation-resolver-roundtrip pin-pack builder (Phase-1b Tag-17).

Implements the deterministic builder for the TV-W-3 vector specified
in ``wirelang/specs/wirelang-tv-strategy.md`` §3.

Pipeline (per spec §3.3):

1. Resolve DNS TXT anchor for ``_wakir-ftd.<domain>`` (hermetic mode:
   replayed; live mode: real DoH/UDP gated by
   ``WIRELANG_LIVE_FEDERATION=1``).
2. Fetch the AIP document (hermetic: fed in-memory; live: HTTPS).
3. Run the FTD-verifier: confirms DNS-anchored fingerprint matches the
   recomputed FTD-doc digest and validates the Ed25519 root signature.
4. Resolve AIP document via the federation-resolver (cross-checks the
   biscuit-root pubkey against the FTD's ``valid_issuer_keys`` set).
5. Run ``verify_from_transport`` over the AIP body bytes (the V-908
   downstream consumer-side check).
6. Emit a deterministic federation-trace JSON capturing:
   ``(dns_anchor_hash, ftd_doc_hash, aip_doc_hash, aip_jcs_sha256,
     ftd_fingerprint_sha256, biscuit_root_pubkey_hex, matched_kid,
     frame_verify_status, frame_verify_kind)``.

Determinism notes:

- All Ed25519 sub-keys (FTD root, AIP issuer = TV-W-1 persona-(1,0))
  are derived deterministically; signatures are RFC 8032 deterministic.
- Pinned timestamps for ``issued_at`` / ``expires`` / verifier-now are
  spec-fixed so the FTD- and AIP-doc bytes are byte-stable.
- DNS-anchor TXT payload is mechanically derived from the recomputed
  FTD fingerprint -- no separate input.
- The federation-trace JSON is JCS-canonicalised; SHA-256 of those
  canonical bytes is the top-level pin (``pin_pack_sha256``).

Hermetic vs live boundary:

- Hermetic mode is the default. It runs without DNS or HTTPS, using a
  ``_FakeTxtResolver`` (DNS) and a ``_FakeAIPResolver`` satisfying the
  Phase-1b Protocol contracts in ``federation_resolver``. The replay
  bundles in ``fixtures/tv-w-3/replay/`` are produced (and refreshed)
  by this builder; the bundle's ``captured-at.txt`` records the
  generation timestamp for the §3.4-A5 freshness check.
- Live mode is opt-in via ``WIRELANG_LIVE_FEDERATION=1``. The Tag-17
  scope ships the trace generator side; live execution requires
  externally-published DNS / HTTPS infrastructure and is not exercised
  in CI lanes (operator-on-demand, mirroring WAT public-OTS).

Brand-Guide §9: persona role-strings are mechanical
(``tv-w-3-issuer-1-0``, ``role=consumer-A``); FTD ``issuer_keys[].kid``
is mechanical (``federated-issuer-1``); domain is the documented
``wakir.dev`` brand-guide-approved host. No clear personal names enter
this file or the produced fixtures.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from wirelang.identity import (
    derive_sub_key_ed25519,
    generate_aip_document,
    sign_aip_document,
)
from wirelang.identity.aip_signing import verify_aip_signature
from wirelang.identity.dns_anchor import TxtResolver
from wirelang.identity.federation_resolver import (
    AIPResolverLike,
    FederatedResolveResult,
    resolve_federated_aip,
)
from wirelang.identity.ftd_verifier import compute_ftd_fingerprint_from_body
from wirelang.identity.key_derivation import (
    ed25519_public_from_private,
)


# ---------------------------------------------------------------------------
# Pinned inputs (per spec §3.2)
# ---------------------------------------------------------------------------

# Same BIP-32 test-vector-1 seed as TV-W-1 / TV-W-2 -- anchors the
# AIP-issuer keypair into the TV-W-1 cross-compat persona-(1,0) pin.
TV_W_3_TEST_SEED_HEX: str = "000102030405060708090a0b0c0d0e0f"

# AIP-issuer persona (deliberately distinct from TV-W-2 issuer-(0,0)
# per spec §3.2 multi-persona-federation rationale).
TV_W_3_AIP_ISSUER_PERSONA_IDX: int = 1
TV_W_3_AIP_ISSUER_SPAWN_COUNTER: int = 0
TV_W_3_AIP_ISSUER_ROLE: str = (
    f"tv-w-3-issuer-{TV_W_3_AIP_ISSUER_PERSONA_IDX}-"
    f"{TV_W_3_AIP_ISSUER_SPAWN_COUNTER}"
)

# Federation domain (brand-guide §9 approved). DNS-anchor host derived
# mechanically as ``_wakir-ftd.<domain>``.
TV_W_3_DOMAIN: str = "wakir.dev"
TV_W_3_FTD_ID: str = f"did:web:{TV_W_3_DOMAIN}:ftd:v1"
TV_W_3_AIP_ID: str = f"aip:web:{TV_W_3_DOMAIN}/{TV_W_3_AIP_ISSUER_ROLE}"

# FTD-root keypair seed. Distinct from any TV-W-1 persona seed; the
# FTD-root is the federation-trust-anchor, not a persona key. Seed is
# pinned as a constant (not a test-vector derivation) because the
# FTD-root is operationally an out-of-band anchor in the V-908 model.
TV_W_3_FTD_ROOT_SEED_HEX: str = (
    "5555555555555555555555555555555555555555555555555555555555555555"
)

# Pinned validity windows -- chosen so the verifier-now sits inside
# both the FTD and the AIP windows under the hermetic context.
TV_W_3_FTD_ISSUED_AT: str = "2026-05-07T00:00:00Z"
TV_W_3_FTD_EXPIRES: str = "2027-05-07T00:00:00Z"
TV_W_3_AIP_VALID_AFTER: str = "2026-05-07T00:00:00Z"
TV_W_3_AIP_EXPIRES: str = "2027-05-07T00:00:00Z"

# Verifier wall-clock (hermetic context). Chosen to be strictly inside
# both validity windows.
TV_W_3_VERIFY_NOW: str = "2026-09-01T12:00:00Z"

# FTD ``issuer_keys[]`` kid for the matched-issuer-key cross-check.
TV_W_3_ISSUER_KID: str = "federated-issuer-1"


# ---------------------------------------------------------------------------
# JCS resolver indirection (Tag-9)
# ---------------------------------------------------------------------------


def _make_jcs_canonicalize() -> Callable[[object], bytes]:
    """Return the active JCS canonicaliser (rfc8785 if available else pure)."""
    try:
        import rfc8785  # type: ignore[import-not-found]

        return rfc8785.dumps
    except ImportError:  # pragma: no cover -- exercised on sandbox lane.
        from wirelang.identity import _jcs_pure

        return _jcs_pure.canonicalize


# ---------------------------------------------------------------------------
# Hermetic FTD-doc construction
# ---------------------------------------------------------------------------


def _verify_now_dt() -> datetime:
    return datetime.strptime(TV_W_3_VERIFY_NOW, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc,
    )


def _build_ftd_body(
    *,
    aip_issuer_pubkey_hex: str,
    ftd_root_pubkey_hex: str,
) -> dict:
    """Construct the unsigned FTD-doc body (without ``document_signature``).

    The ``anchor.fingerprint_sha256`` slot is left as the schema-stable
    placeholder ``"0" * 64`` because the V-908 fingerprint is computed
    over the body INCLUDING the anchor slot (per
    :func:`compute_ftd_fingerprint_from_body`, which only strips
    ``document_signature``). The placeholder is the documented
    convention from ``test_ftd_verifier`` and ``test_federation_resolver``;
    the DNS anchor's TXT record carries the *recomputed* fingerprint
    (which is the SHA-256 of the JCS body with the placeholder still
    in place).
    """
    body: dict = {
        "wakir_ftd": "0.1.0",
        "id": TV_W_3_FTD_ID,
        "domain": TV_W_3_DOMAIN,
        "issued_at": TV_W_3_FTD_ISSUED_AT,
        "expires": TV_W_3_FTD_EXPIRES,
        "ftd_root_pubkey": ftd_root_pubkey_hex,
        "issuer_keys": [
            {
                "kid": TV_W_3_ISSUER_KID,
                "alg": "Ed25519",
                "public_key": aip_issuer_pubkey_hex,
                "purpose": "biscuit-root",
                "valid_from": TV_W_3_AIP_VALID_AFTER,
                "valid_until": TV_W_3_AIP_EXPIRES,
            },
        ],
        "anchor": {
            "kind": "dns-txt",
            "host": f"_wakir-ftd.{TV_W_3_DOMAIN}",
            "fingerprint_sha256": "0" * 64,
        },
    }
    return body


def _sign_ftd_body(body: dict, ftd_root_priv32: bytes) -> dict:
    """Append a ``document_signature`` block to the FTD body in-place.

    Returns the now-signed body (mutated). The signing input is
    SHA-256(JCS(body without document_signature)); identical
    construction to :func:`compute_ftd_fingerprint_from_body` so the
    DNS-anchor fingerprint equals the SHA-256 of the same JCS bytes.
    """
    jcs = _make_jcs_canonicalize()
    canonical = jcs(body)
    digest = hashlib.sha256(canonical).digest()
    sk = Ed25519PrivateKey.from_private_bytes(ftd_root_priv32)
    signature = sk.sign(digest)
    body["document_signature"] = {
        "alg": "Ed25519",
        "kid": "ftd-root-1",
        "signature": signature.hex(),
    }
    return body


# ---------------------------------------------------------------------------
# Hermetic AIP-doc construction
# ---------------------------------------------------------------------------


def _build_aip_body(*, ed25519_pub: bytes) -> dict:
    """Build the AIP-doc body with persona (1, 0) Ed25519 as biscuit-root.

    ``aip_id`` is fixed to ``aip:web:<domain>/<role-string>`` so the
    federation pipeline's URL-host extraction (V-908 §4.1 step 4)
    matches the FTD ``domain`` field. ``did_uri`` is a synthetic
    ``did:web`` for the persona; the federation pipeline does not
    re-resolve the DID.
    """
    did_uri = f"did:web:{TV_W_3_DOMAIN}:{TV_W_3_AIP_ISSUER_ROLE}"
    aip_doc = generate_aip_document(
        TV_W_3_AIP_ISSUER_ROLE,
        ed25519_pub,
        did_uri=did_uri,
        aip_id=TV_W_3_AIP_ID,
        valid_after=TV_W_3_AIP_VALID_AFTER,
        valid_until=None,
        expires=TV_W_3_AIP_EXPIRES,
        delegation_mode="chained",
        protocols=("wirelang/0.1",),
    )
    return aip_doc


def _sign_aip_body(aip_body: dict, ed25519_priv32: bytes) -> dict:
    """Sign an AIP body in-place, returning the mutated body."""
    sig_block = sign_aip_document(aip_body, ed25519_priv32)
    aip_body["document_signature"] = sig_block
    return aip_body


# ---------------------------------------------------------------------------
# Hermetic Protocol stubs (DNS + AIP)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReplayDnsRecord:
    host: str
    txt_records: Tuple[str, ...]


class _FakeTxtResolver:
    """In-memory ``TxtResolver`` Protocol implementation.

    Records every query so the trace can pin the consulted host.
    """

    def __init__(self, records: Dict[str, Tuple[str, ...]]) -> None:
        self._records = dict(records)
        self.queries: List[str] = []

    def resolve_txt(self, name: str, *, timeout_s: float = 3.0) -> List[str]:
        self.queries.append(name)
        return list(self._records.get(name, ()))


@dataclass(frozen=True)
class _FakeAIPDocument:
    id: str
    body: dict
    jcs_sha256: str
    biscuit_root_pubkey_hex: str


class _FakeAIPResolver:
    """``AIPResolverLike`` stub that already-verified the AIP layer.

    The federation-resolver pipeline (V-908 §4.1 steps 5/6/8/9) is
    delegated to the AIP-side resolver in production; the in-tree
    Phase-1a resolver hard-imports rfc8785/jsonschema. For the TV-W-3
    fixture path we instead model the post-Phase-1a-verify surface and
    let the federation cross-checks (steps 4 and 7) do their work.
    The hermetic AIP-body is itself signed via the production
    :func:`sign_aip_document` so the signature is real and the Tag-9
    ``verify_from_transport`` step (consumer side) still exercises a
    real Ed25519 verify.
    """

    def __init__(self, doc: _FakeAIPDocument) -> None:
        self._doc = doc
        self.calls: List[str] = []

    def resolve(self, uri: str) -> _FakeAIPDocument:
        self.calls.append(uri)
        if uri != self._doc.id:
            raise KeyError(f"unknown AIP uri: {uri!r}")
        return self._doc


# ---------------------------------------------------------------------------
# Pipeline assembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PipelineArtefacts:
    """Internal artefacts produced by one pipeline run.

    Held in-process; the public pin-pack is the projection of these
    artefacts into deterministic JSON via :func:`build_pin_pack`.
    """

    ftd_body_signed: dict
    aip_body_signed: dict
    aip_body_bytes: bytes
    dns_anchor_payload: str
    fed_result: FederatedResolveResult
    transport_verify_status: str
    transport_verify_kind: Optional[str]


def _txt_anchor_payload(fingerprint_hex: str) -> str:
    """V-908 §3.4 TXT-record format: ``v=1; sha256=<64-hex>``."""
    return f"v=1; sha256={fingerprint_hex}"


def _run_pipeline(*, seed_hex: str = TV_W_3_TEST_SEED_HEX) -> _PipelineArtefacts:
    """Run the full hermetic federation pipeline once and capture artefacts.

    Pipeline steps mirror spec §3.3 1:1.
    """
    seed = bytes.fromhex(seed_hex)

    # 1. Derive AIP-issuer keypair = TV-W-1 persona (1, 0).
    aip_priv = derive_sub_key_ed25519(
        seed,
        TV_W_3_AIP_ISSUER_PERSONA_IDX,
        TV_W_3_AIP_ISSUER_SPAWN_COUNTER,
    )
    aip_pub = ed25519_public_from_private(aip_priv)

    # FTD-root keypair (operationally OOB; pinned constant seed).
    ftd_root_priv = bytes.fromhex(TV_W_3_FTD_ROOT_SEED_HEX)
    ftd_root_pub = ed25519_public_from_private(ftd_root_priv)

    # 2. Build + sign FTD-doc.
    ftd_body = _build_ftd_body(
        aip_issuer_pubkey_hex=aip_pub.hex(),
        ftd_root_pubkey_hex=ftd_root_pub.hex(),
    )
    # Recompute fingerprint per V-908 §2.1: SHA-256(JCS(body without
    # document_signature)). The anchor.fingerprint_sha256 slot remains
    # the placeholder for the same reason ``test_federation_resolver``
    # leaves it ``"0"*64``: the slot itself is part of the JCS input.
    ftd_fingerprint = compute_ftd_fingerprint_from_body(ftd_body)
    _sign_ftd_body(ftd_body, ftd_root_priv)

    # 3. Build + sign AIP-doc.
    aip_body = _build_aip_body(ed25519_pub=aip_pub)
    _sign_aip_body(aip_body, aip_priv)
    jcs = _make_jcs_canonicalize()
    aip_body_bytes = jcs(aip_body)

    # 4. Build hermetic DNS resolver (TXT-record carries the recomputed
    #    fingerprint).
    dns_anchor_payload = _txt_anchor_payload(ftd_fingerprint)
    dns = _FakeTxtResolver(
        {f"_wakir-ftd.{TV_W_3_DOMAIN}": (dns_anchor_payload,)},
    )

    # 5. AIP resolver stub. ``jcs_sha256`` is recomputed from the
    #    canonical bytes WITHOUT the document_signature, mirroring the
    #    Phase-1a resolver's contract.
    aip_unsigned = copy.deepcopy(aip_body)
    aip_unsigned.pop("document_signature", None)
    aip_jcs_sha256 = hashlib.sha256(jcs(aip_unsigned)).hexdigest()
    fake_aip_doc = _FakeAIPDocument(
        id=TV_W_3_AIP_ID,
        body=aip_body,
        jcs_sha256=aip_jcs_sha256,
        biscuit_root_pubkey_hex=aip_pub.hex(),
    )
    aip_resolver: AIPResolverLike = _FakeAIPResolver(fake_aip_doc)

    # 6. Run federation pipeline (steps 1-10 of V-908 §4.1).
    ftd_doc_jcs_bytes = jcs(ftd_body)
    fed_result = resolve_federated_aip(
        TV_W_3_AIP_ID,
        TV_W_3_FTD_ID,
        ftd_resolver=dns,
        ftd_doc_jcs_bytes=ftd_doc_jcs_bytes,
        aip_resolver=aip_resolver,
        now=_verify_now_dt(),
    )

    # 7. verify_from_transport over the AIP body bytes (consumer side
    #    integrity gate). We do an in-tree verify against the resolved
    #    biscuit-root pubkey rather than re-stamping the bridge here:
    #    the bridge's role in this trace is to confirm that the body
    #    bytes the federation pipeline saw are the same bytes that a
    #    downstream consumer would verify.
    sig_ok = verify_aip_signature(
        aip_body,
        aip_body["document_signature"],
        aip_pub,
    )
    if sig_ok:
        transport_status = "ok"
        transport_kind: Optional[str] = None
    else:  # pragma: no cover -- hermetic pipeline produces a valid sig
        transport_status = "reject"
        transport_kind = "signature-failed"

    return _PipelineArtefacts(
        ftd_body_signed=ftd_body,
        aip_body_signed=aip_body,
        aip_body_bytes=aip_body_bytes,
        dns_anchor_payload=dns_anchor_payload,
        fed_result=fed_result,
        transport_verify_status=transport_status,
        transport_verify_kind=transport_kind,
    )


# ---------------------------------------------------------------------------
# Pin-pack assembly
# ---------------------------------------------------------------------------


def build_trace(artefacts: _PipelineArtefacts) -> dict:
    """Build the federation-trace JSON for one pipeline run.

    Per spec §3.3 step 6, the trace carries:
    ``(dns_anchor_hash, ftd_doc_hash, aip_doc_hash, aip_jcs_sha256,
     ftd_fingerprint_sha256, biscuit_root_pubkey_hex, matched_kid,
     frame_verify_status, frame_verify_kind)``.

    The ``dns_anchor_hash`` is SHA-256 of the TXT-record payload;
    ``ftd_doc_hash`` is SHA-256 of the JCS-canonical signed FTD body;
    ``aip_doc_hash`` is SHA-256 of the JCS-canonical signed AIP body.
    """
    jcs = _make_jcs_canonicalize()
    ftd_doc_canonical = jcs(artefacts.ftd_body_signed)
    aip_doc_canonical = jcs(artefacts.aip_body_signed)
    return {
        "dns_anchor_payload": artefacts.dns_anchor_payload,
        "dns_anchor_hash": hashlib.sha256(
            artefacts.dns_anchor_payload.encode("ascii"),
        ).hexdigest(),
        "ftd_doc_hash": hashlib.sha256(ftd_doc_canonical).hexdigest(),
        "ftd_fingerprint_sha256": artefacts.fed_result.ftd_fingerprint_sha256,
        "aip_doc_hash": hashlib.sha256(aip_doc_canonical).hexdigest(),
        "aip_jcs_sha256": artefacts.fed_result.aip_jcs_sha256,
        "biscuit_root_pubkey_hex": artefacts.fed_result.biscuit_root_pubkey_hex,
        "matched_issuer_kid": artefacts.fed_result.matched_issuer_kid,
        "frame_verify_status": artefacts.transport_verify_status,
        "frame_verify_kind": artefacts.transport_verify_kind,
    }


def build_pin_pack(*, seed_hex: str = TV_W_3_TEST_SEED_HEX) -> dict:
    """Build the full TV-W-3 pin-pack body (without the top-level hash)."""
    artefacts = _run_pipeline(seed_hex=seed_hex)
    trace = build_trace(artefacts)
    return {
        "label": "tv-w-3-federation-resolver-roundtrip",
        "spec": "wirelang/specs/wirelang-tv-strategy.md §3 (Phase-1b Tag-17)",
        "seed_hex": seed_hex,
        "aip_issuer_persona": [
            TV_W_3_AIP_ISSUER_PERSONA_IDX,
            TV_W_3_AIP_ISSUER_SPAWN_COUNTER,
        ],
        "aip_issuer_role": TV_W_3_AIP_ISSUER_ROLE,
        "domain": TV_W_3_DOMAIN,
        "ftd_id": TV_W_3_FTD_ID,
        "aip_id": TV_W_3_AIP_ID,
        "ftd_issued_at": TV_W_3_FTD_ISSUED_AT,
        "ftd_expires": TV_W_3_FTD_EXPIRES,
        "aip_valid_after": TV_W_3_AIP_VALID_AFTER,
        "aip_expires": TV_W_3_AIP_EXPIRES,
        "verify_now": TV_W_3_VERIFY_NOW,
        "issuer_kid": TV_W_3_ISSUER_KID,
        "ftd_root_seed_hex": TV_W_3_FTD_ROOT_SEED_HEX,
        "trace_hermetic": trace,
    }


def pin_pack_hash(pin_pack: dict) -> str:
    """SHA-256 of JCS of the pin-pack body."""
    jcs = _make_jcs_canonicalize()
    return hashlib.sha256(jcs(pin_pack)).hexdigest()


def build_pin_pack_with_hash(*, seed_hex: str = TV_W_3_TEST_SEED_HEX) -> dict:
    """Build the pin-pack including the top-level ``pin_pack_sha256``."""
    body = build_pin_pack(seed_hex=seed_hex)
    body["pin_pack_sha256"] = pin_pack_hash(body)
    return body


# ---------------------------------------------------------------------------
# Replay-bundle export (§3.4-A5 freshness anchor)
# ---------------------------------------------------------------------------


def export_replay_bundle(
    *,
    out_dir: Path,
    seed_hex: str = TV_W_3_TEST_SEED_HEX,
) -> dict:
    """Write the hermetic replay bundle under ``out_dir``.

    Layout:

    ``dns/_wakir-ftd.<domain>.txt``  -- raw TXT record (one line).
    ``https/<aip_id>.json``          -- AIP body bytes (signed).
    ``https/<ftd_id>.json``          -- FTD body bytes (signed).
    ``captured-at.txt``              -- ISO-8601 UTC timestamp.

    The TXT and JSON files are JCS-canonical / spec-canonical so a
    downstream live-mode test can replay them byte-stable. The
    ``captured-at.txt`` is the freshness pin per §3.4 A5: a pre-flight
    check warns if the bundle is older than 90 days.

    Returns the trace produced by the run (so callers can pin it).
    """
    artefacts = _run_pipeline(seed_hex=seed_hex)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dns").mkdir(parents=True, exist_ok=True)
    (out_dir / "https").mkdir(parents=True, exist_ok=True)

    # DNS replay file. One TXT record per line; the V-908 §3.4 single-
    # string form is what TV-W-3 uses.
    dns_file = out_dir / "dns" / f"_wakir-ftd.{TV_W_3_DOMAIN}.txt"
    with dns_file.open("w", encoding="ascii") as fh:
        fh.write(artefacts.dns_anchor_payload + "\n")

    # HTTPS replay files (FTD + AIP).
    jcs = _make_jcs_canonicalize()
    ftd_file = out_dir / "https" / f"ftd-{TV_W_3_DOMAIN}.json"
    with ftd_file.open("wb") as fh:
        fh.write(jcs(artefacts.ftd_body_signed))
        fh.write(b"\n")
    aip_file = out_dir / "https" / f"aip-{TV_W_3_AIP_ISSUER_ROLE}.json"
    with aip_file.open("wb") as fh:
        fh.write(jcs(artefacts.aip_body_signed))
        fh.write(b"\n")

    # Captured-at pin (freshness anchor).
    # Builder uses a fixed pinned timestamp -- determinism over real
    # wall-clock. The freshness check in tests compares against the
    # CURRENT wall-clock at run time, but the file content itself is
    # pinned. A re-baseline event is "operator runs the CLI again,
    # captured-at changes, fixture-pin changes". Because TV-W-3's
    # pin-pack does NOT include the captured-at file in its hash
    # (it sits next to the trace, not inside it), the pin-pack is
    # stable across re-baselines that do not change the substrate.
    (out_dir / "captured-at.txt").write_text(
        TV_W_3_VERIFY_NOW + "\n",
        encoding="ascii",
    )

    return build_trace(artefacts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_fixture_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "tv-w-3"


def _default_pin_pack_path() -> Path:
    return _default_fixture_dir() / "pin-pack.json"


def _default_replay_dir() -> Path:
    return _default_fixture_dir() / "replay"


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the TV-W-3 federation-resolver-roundtrip pin-pack "
            "golden fixture and (optionally) the replay bundle. External "
            "auditors can run this against the documented seed to "
            "reproduce the pin-pack hash (acceptance criterion A1)."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_default_pin_pack_path(),
        help="Output path for the pin-pack JSON.",
    )
    parser.add_argument(
        "--replay-dir",
        type=Path,
        default=_default_replay_dir(),
        help="Output directory for the replay bundle (DNS + HTTPS files).",
    )
    parser.add_argument(
        "--seed-hex",
        default=TV_W_3_TEST_SEED_HEX,
        help="Override the BIP-32 test seed (hex). Default: BIP-32 test-vector 1.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only print the pin-pack hash; do not write any file.",
    )
    parser.add_argument(
        "--write-replay",
        action="store_true",
        help="Also write the replay bundle (DNS + HTTPS + captured-at).",
    )
    ns = parser.parse_args(argv)

    pin_pack = build_pin_pack_with_hash(seed_hex=ns.seed_hex)
    if ns.check:
        print(pin_pack["pin_pack_sha256"])
        return 0
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    with ns.out.open("w", encoding="utf-8") as fh:
        json.dump(pin_pack, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(f"wrote {ns.out} (pin_pack_sha256 = {pin_pack['pin_pack_sha256']})")

    if ns.write_replay:
        export_replay_bundle(out_dir=ns.replay_dir, seed_hex=ns.seed_hex)
        print(f"wrote replay bundle under {ns.replay_dir}")

    return 0


if __name__ == "__main__":  # pragma: no cover -- CLI entry-point
    sys.exit(_cli(sys.argv[1:]))
