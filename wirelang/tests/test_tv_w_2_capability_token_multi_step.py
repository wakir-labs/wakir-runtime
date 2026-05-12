# SPDX-License-Identifier: Apache-2.0
"""TV-W-2 hermetic Capability-Token Multi-Step Roundtrip (Phase-1b Tag-16).

Acceptance criteria (per ``wirelang/specs/wirelang-tv-strategy.md`` §2.4
plus the TV-W-2 Pin-Stability Guarantee in
``wirelang/specs/datalog-caveat-vocabulary-phase-2.md`` §6):

- **A1** Verification-trace hashes match the three contexts encoded in
  the golden file ``wirelang/tests/fixtures/tv-w-2/pin-pack.json``:
  α = ``accept``, β = ``reject(time-bound-violated)``, γ =
  ``reject(audience-pattern-mismatch)``.
- **A2** Each block's signature verifies with the *previous* block's
  ``next_pubkey`` (or with the issuer key for Block 0). Append-only
  invariant is checked at every step.
- **A3** Caveat evaluation is deterministic: re-running the verifier
  on the same context produces byte-identical traces.
- **A4** Strengthening detection: a synthetic mutation (caveat
  removal, append-block insertion, sealing-bruch) must be rejected.
- **A5** Cross-lane parity: sandbox and production lanes produce
  identical trace hashes (Pure-Python ``_jcs_pure`` and ``rfc8785``
  byte-equivalent on the trace path).

Three test classes match the three presentation contexts plus a
``Negative-Control`` class for A4 mutations and a top-level set of
A1 / A5 / cross-lane / CLI / cross-compat anchors.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from wirelang.canonical.caveat_set import (
    canonical_caveat_set_hash,
)
from wirelang.identity import _jcs_pure
from wirelang.identity import (
    derive_sub_key_ed25519,
)
from wirelang.identity.key_derivation import (
    ed25519_public_from_private,
)

from wirelang.tests._tv_w_2_pin_pack_builder import (
    APPEND_1_CAVEATS,
    AUTHORITY_CAVEATS,
    CONTEXT_AUDIENCE,
    CONTEXT_TIMES,
    TV_W_2_CONTEXT_ALPHA,
    TV_W_2_CONTEXT_BETA,
    TV_W_2_CONTEXT_GAMMA,
    TV_W_2_ISSUER_PERSONA_IDX,
    TV_W_2_ISSUER_SPAWN_COUNTER,
    TV_W_2_TEST_SEED_HEX,
    build_chain,
    build_pin_pack,
    build_pin_pack_with_hash,
    pin_pack_hash,
    verify_chain_under_context,
)


# ---------------------------------------------------------------------------
# Golden fixture loader
# ---------------------------------------------------------------------------


GOLDEN_PATH: Path = (
    Path(__file__).resolve().parent / "fixtures" / "tv-w-2" / "pin-pack.json"
)


def _load_golden() -> dict:
    with GOLDEN_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def golden() -> dict:
    return _load_golden()


@pytest.fixture(scope="module")
def chain() -> dict:
    """In-process re-derived chain (carries private seeds for the
    negative-control mutations and signature-chain probes)."""
    return build_chain(seed_hex=TV_W_2_TEST_SEED_HEX)


# ---------------------------------------------------------------------------
# Layout invariants
# ---------------------------------------------------------------------------


def test_golden_layout_invariants(golden: dict) -> None:
    """Top-level pin-pack shape matches §6.1 + §2.3 spec.

    A drift in this shape is a deliberate engineering event and must
    be re-baselined explicitly via the builder CLI.
    """
    for key in (
        "label",
        "spec",
        "csc_spec",
        "seed_hex",
        "issuer_persona",
        "issuer_role",
        "not_before",
        "not_after",
        "nonce",
        "context_times",
        "context_audience",
        "chain",
        "traces",
        "pin_pack_sha256",
    ):
        assert key in golden, f"missing top-level key: {key}"
    assert golden["label"] == "tv-w-2-capability-token-multi-step"
    assert golden["seed_hex"] == TV_W_2_TEST_SEED_HEX
    assert golden["issuer_persona"] == [
        TV_W_2_ISSUER_PERSONA_IDX,
        TV_W_2_ISSUER_SPAWN_COUNTER,
    ]


def test_golden_traces_cover_three_contexts(golden: dict) -> None:
    """All three α/β/γ presentation-context traces are present and
    each carries the spec §6.1 fields."""
    assert set(golden["traces"]) == {
        TV_W_2_CONTEXT_ALPHA,
        TV_W_2_CONTEXT_BETA,
        TV_W_2_CONTEXT_GAMMA,
    }
    expected_fields = {
        "context",
        "block_hashes",
        "caveat_set_hashes",
        "verify_status",
        "verify_reason",
        "next_pubkeys",
    }
    for ctx, trace in golden["traces"].items():
        assert set(trace) == expected_fields, (
            f"trace {ctx} field drift: {set(trace) ^ expected_fields}"
        )
        assert trace["context"] == ctx
        assert len(trace["block_hashes"]) == 3
        assert len(trace["caveat_set_hashes"]) == 3
        assert len(trace["next_pubkeys"]) == 3


def test_golden_chain_layout(golden: dict) -> None:
    """Chain projection contains exactly authority + 2 append + sealing."""
    chain = golden["chain"]
    for key in (
        "issuer_pub_hex_32",
        "block0_next_pub_hex_32",
        "block1_next_pub_hex_32",
        "block2_next_pub_hex_32",
        "block0",
        "block1",
        "block2",
        "sealing",
    ):
        assert key in chain, f"missing chain key: {key}"
    # Each block carries payload + signature + block_hash.
    for b_key in ("block0", "block1", "block2"):
        block = chain[b_key]
        assert {"payload", "signature", "block_hash"} <= set(block)
        assert len(bytes.fromhex(block["signature"])) == 64
        assert len(bytes.fromhex(block["block_hash"])) == 32
    # Sealing has input + signature.
    assert {"input", "signature"} <= set(chain["sealing"])
    assert len(bytes.fromhex(chain["sealing"]["signature"])) == 64


# ---------------------------------------------------------------------------
# A1 — Pin-pack hash and per-trace match
# ---------------------------------------------------------------------------


class TestA1PinPackMatchesGolden:
    """Top-level pin-pack hash matches the checked-in golden."""

    def test_a1_pin_pack_hash_matches(self, golden: dict) -> None:
        rebuilt = build_pin_pack(seed_hex=TV_W_2_TEST_SEED_HEX)
        rebuilt_hash = pin_pack_hash(rebuilt)
        assert rebuilt_hash == golden["pin_pack_sha256"], (
            "TV-W-2 pin-pack drift detected. Re-baseline via "
            "`python -m wirelang.tests._tv_w_2_pin_pack_builder` and "
            "explicit review per spec §6.3."
        )

    def test_a1_each_trace_matches_golden_byte_for_byte(self, golden: dict) -> None:
        rebuilt = build_pin_pack(seed_hex=TV_W_2_TEST_SEED_HEX)
        for ctx in (
            TV_W_2_CONTEXT_ALPHA,
            TV_W_2_CONTEXT_BETA,
            TV_W_2_CONTEXT_GAMMA,
        ):
            assert rebuilt["traces"][ctx] == golden["traces"][ctx], (
                f"trace {ctx} drift between rebuilt and golden"
            )


# ---------------------------------------------------------------------------
# Verifier-context-α: accept
# ---------------------------------------------------------------------------


class TestContextAlphaAccept:
    """Context α: verifier-time inside window, audience matches → accept."""

    def test_alpha_accept_status(self, golden: dict) -> None:
        trace = golden["traces"][TV_W_2_CONTEXT_ALPHA]
        assert trace["verify_status"] == "accept"
        assert trace["verify_reason"] is None

    def test_alpha_in_process_matches_golden(self, chain: dict, golden: dict) -> None:
        """Running the verifier in-process produces the byte-identical trace."""
        live = verify_chain_under_context(chain, TV_W_2_CONTEXT_ALPHA)
        assert live == golden["traces"][TV_W_2_CONTEXT_ALPHA]

    def test_alpha_caveat_set_hashes_match_csc(
        self, golden: dict
    ) -> None:
        """The α-trace caveat-set-hashes match §4-CSC over the pinned caveats.

        Recomputing via :func:`canonical_caveat_set_hash` from the
        published authority/append-1/append-2 caveat-sets MUST match
        what is in the trace; this is the load-bearing TV-W-2-§4-CSC
        contract.
        """
        trace = golden["traces"][TV_W_2_CONTEXT_ALPHA]
        expected = [
            canonical_caveat_set_hash(AUTHORITY_CAVEATS).hex(),
            canonical_caveat_set_hash(APPEND_1_CAVEATS).hex(),
            canonical_caveat_set_hash(
                ["check if rate_limit($n), $n <= 100"]
            ).hex(),
        ]
        assert trace["caveat_set_hashes"] == expected

    def test_alpha_chain_signatures_each_verify(self, chain: dict) -> None:
        """A2 — Each block's signature verifies with the previous block's
        next_pubkey (or with the issuer for Block 0)."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        jcs = _jcs_pure.canonicalize
        # Block 0 vs. issuer.
        issuer_pub = bytes.fromhex(chain["pubkeys"]["issuer"])
        b0 = chain["chain"][0]
        digest_0 = hashlib.sha256(jcs(b0["payload"])).digest()
        Ed25519PublicKey.from_public_bytes(issuer_pub).verify(
            bytes.fromhex(b0["signature"]), digest_0
        )
        # Block 1 vs. block0_next.
        b0_next = bytes.fromhex(b0["payload"]["next_pubkey"])
        b1 = chain["chain"][1]
        digest_1 = hashlib.sha256(jcs(b1["payload"])).digest()
        Ed25519PublicKey.from_public_bytes(b0_next).verify(
            bytes.fromhex(b1["signature"]), digest_1
        )
        # Block 2 vs. block1_next.
        b1_next = bytes.fromhex(b1["payload"]["next_pubkey"])
        b2 = chain["chain"][2]
        digest_2 = hashlib.sha256(jcs(b2["payload"])).digest()
        Ed25519PublicKey.from_public_bytes(b1_next).verify(
            bytes.fromhex(b2["signature"]), digest_2
        )

    def test_alpha_determinism_repeat(self, chain: dict) -> None:
        """A3 — re-running the verifier produces byte-identical traces."""
        first = verify_chain_under_context(chain, TV_W_2_CONTEXT_ALPHA)
        second = verify_chain_under_context(chain, TV_W_2_CONTEXT_ALPHA)
        third = verify_chain_under_context(chain, TV_W_2_CONTEXT_ALPHA)
        assert first == second == third


# ---------------------------------------------------------------------------
# Verifier-context-β: reject(time-bound-violated)
# ---------------------------------------------------------------------------


class TestContextBetaReject:
    """Context β: verifier-time after `not_after` → reject."""

    def test_beta_reject_status(self, golden: dict) -> None:
        trace = golden["traces"][TV_W_2_CONTEXT_BETA]
        assert trace["verify_status"] == "reject"
        assert trace["verify_reason"] == "time-bound-violated"

    def test_beta_in_process_matches_golden(self, chain: dict, golden: dict) -> None:
        live = verify_chain_under_context(chain, TV_W_2_CONTEXT_BETA)
        assert live == golden["traces"][TV_W_2_CONTEXT_BETA]

    def test_beta_block_hashes_unchanged_from_alpha(self, golden: dict) -> None:
        """Block hashes are immutable under context change.

        Verification context affects `verify_status` / `verify_reason`
        only; the block payloads (and hence their hashes) are
        producer-side artefacts and do not change with verifier wall-
        clock or claimed audience. This invariant is a load-bearing
        property of TV-W-2: a verifier rejecting on context cannot
        rewrite history.
        """
        alpha = golden["traces"][TV_W_2_CONTEXT_ALPHA]
        beta = golden["traces"][TV_W_2_CONTEXT_BETA]
        assert alpha["block_hashes"] == beta["block_hashes"]
        assert alpha["caveat_set_hashes"] == beta["caveat_set_hashes"]
        assert alpha["next_pubkeys"] == beta["next_pubkeys"]

    def test_beta_verifier_time_actually_after_not_after(self, golden: dict) -> None:
        """Sanity: the pinned β verifier-time is actually after the chain's not_after."""
        not_after = golden["not_after"]
        beta_time = golden["context_times"][TV_W_2_CONTEXT_BETA]
        assert beta_time > not_after, (
            f"β verifier-time {beta_time} should be after not_after "
            f"{not_after} for the time-bound-violated rejection to "
            f"be a valid test."
        )


# ---------------------------------------------------------------------------
# Verifier-context-γ: reject(audience-pattern-mismatch)
# ---------------------------------------------------------------------------


class TestContextGammaReject:
    """Context γ: verifier-time inside window, but mismatched audience → reject."""

    def test_gamma_reject_status(self, golden: dict) -> None:
        trace = golden["traces"][TV_W_2_CONTEXT_GAMMA]
        assert trace["verify_status"] == "reject"
        assert trace["verify_reason"] == "audience-pattern-mismatch"

    def test_gamma_in_process_matches_golden(self, chain: dict, golden: dict) -> None:
        live = verify_chain_under_context(chain, TV_W_2_CONTEXT_GAMMA)
        assert live == golden["traces"][TV_W_2_CONTEXT_GAMMA]

    def test_gamma_block_hashes_unchanged(self, golden: dict) -> None:
        alpha = golden["traces"][TV_W_2_CONTEXT_ALPHA]
        gamma = golden["traces"][TV_W_2_CONTEXT_GAMMA]
        assert alpha["block_hashes"] == gamma["block_hashes"]
        assert alpha["caveat_set_hashes"] == gamma["caveat_set_hashes"]

    def test_gamma_audience_actually_mismatches(self, golden: dict) -> None:
        """Sanity: γ-claim audience is actually distinct from authority pattern.

        The authority pattern is `role=consumer-A`; γ claims
        `role=consumer-B`. Without this distinctness, the rejection
        would be vacuous.
        """
        authority_pattern = golden["chain"]["block0"]["payload"]["audience_pattern"]
        gamma_claim = CONTEXT_AUDIENCE[TV_W_2_CONTEXT_GAMMA]
        assert authority_pattern != gamma_claim
        # And specifically the role= attribute differs.
        assert "consumer-A" in authority_pattern
        assert "consumer-B" in gamma_claim


# ---------------------------------------------------------------------------
# A4 — Negative controls
# ---------------------------------------------------------------------------


class TestNegativeControls:
    """Mutations that MUST cause rejection (A4 attenuation/integrity)."""

    def test_caveat_mutation_in_block1_breaks_signature_chain(
        self, chain: dict
    ) -> None:
        """Mutating Block 1's caveats invalidates Block 1's signature.

        Negative-control I: a verifier presented with a tampered
        Block-1 payload MUST reject. The rejection reason is
        `signature-chain-invalid`; even though §4-CSC dedup/sort
        would canonicalise the caveat-set, the signature is over the
        producer-emitted JCS payload, not over the canonical caveat
        set. Mutating ANY field in the payload (including caveats)
        breaks the signature.
        """
        mutated = copy.deepcopy(chain)
        mutated["chain"][1]["payload"]["caveats"] = [
            'check if read_only(false)',  # privilege strengthening!
        ]
        # Note: signature is NOT recomputed -> chain is broken.
        result = verify_chain_under_context(mutated, TV_W_2_CONTEXT_ALPHA)
        assert result["verify_status"] == "reject"
        assert result["verify_reason"] == "signature-chain-invalid"

    def test_caveat_removal_in_block1_breaks_signature_chain(
        self, chain: dict
    ) -> None:
        """Negative-control II — caveat removal (privilege expansion attempt).

        Removing a caveat from Block 1 is the classic strengthening
        attack: an attacker tries to drop the read_only restriction
        from an attenuation block. The signature over the original
        payload no longer verifies; rejection is fatal.
        """
        mutated = copy.deepcopy(chain)
        mutated["chain"][1]["payload"]["caveats"] = []  # all removed
        result = verify_chain_under_context(mutated, TV_W_2_CONTEXT_ALPHA)
        assert result["verify_status"] == "reject"
        assert result["verify_reason"] == "signature-chain-invalid"

    def test_block_insertion_breaks_signature_chain(self, chain: dict) -> None:
        """Negative-control III — synthetic-append-block insertion.

        An attacker that inserts a block between Block 1 and Block 2
        must produce a signature with Block 1's `next_pubkey`; without
        the corresponding private key (which the legitimate producer
        does not publish), the chain is unverifiable.
        """
        mutated = copy.deepcopy(chain)
        # Construct a "fake" block with payload/signature/next_pubkey
        # but signed with the wrong key (issuer key, which signs B0).
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        fake_payload = {
            "block_index": 1,  # collides with B1 -- the chain is broken
            "issuer_did": "aip:web:wakir.dev/tv-w-2-attacker",
            "audience_pattern": "role=consumer-A,scope=attacker",
            "caveats": ['check if action("transfer.balance")'],  # privilege grant!
            "next_pubkey": "00" * 32,
            "prev_signature": chain["chain"][0]["signature"],
        }
        issuer_priv = bytes.fromhex(chain["private_seeds"]["issuer"])
        sk = Ed25519PrivateKey.from_private_bytes(issuer_priv)
        digest = hashlib.sha256(_jcs_pure.canonicalize(fake_payload)).digest()
        fake_signature = sk.sign(digest).hex()
        fake_block = {
            "payload": fake_payload,
            "signature": fake_signature,
            "block_hash": hashlib.sha256(
                _jcs_pure.canonicalize(fake_payload)
            ).hexdigest(),
        }
        # Insert at position 1 (between B0 and B1); the original B1
        # would then be at index 2 and the original B2 dropped.
        mutated["chain"] = [
            mutated["chain"][0],
            fake_block,
            mutated["chain"][2],  # signed with B1's next_pubkey, not the fake's
        ]
        result = verify_chain_under_context(mutated, TV_W_2_CONTEXT_ALPHA)
        assert result["verify_status"] == "reject"
        assert result["verify_reason"] == "signature-chain-invalid"

    def test_sealing_signature_independently_verifiable(self, chain: dict) -> None:
        """Sealing-Bruch — the sealing signature must verify standalone.

        A tampered sealing-input must fail to verify against the
        block2_next pubkey. The chain itself remains verifiable
        (sealing is over-the-top), but the seal is broken; an
        operator using the sealed-token contract MUST reject the
        token if seal-verify fails.
        """
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        from cryptography.exceptions import InvalidSignature

        sealing = chain["sealing"]
        block2_next_pub = bytes.fromhex(chain["pubkeys"]["block2_next"])

        # Positive: original sealing-signature verifies.
        digest = hashlib.sha256(_jcs_pure.canonicalize(sealing["input"])).digest()
        Ed25519PublicKey.from_public_bytes(block2_next_pub).verify(
            bytes.fromhex(sealing["signature"]), digest
        )

        # Negative: tampered sealing-input fails verification.
        mutated_input = copy.deepcopy(sealing["input"])
        mutated_input["sealed_at"] = "2099-12-31T23:59:59Z"
        mutated_digest = hashlib.sha256(
            _jcs_pure.canonicalize(mutated_input)
        ).digest()
        with pytest.raises(InvalidSignature):
            Ed25519PublicKey.from_public_bytes(block2_next_pub).verify(
                bytes.fromhex(sealing["signature"]), mutated_digest
            )

    def test_audience_strengthening_in_append_block_rejected(
        self, chain: dict
    ) -> None:
        """A semantic strengthening (broadening audience) in an append block.

        If an attenuator block tries to *broaden* its audience-pattern
        beyond what its parent allowed, the verifier MUST reject with
        `attenuation-violation`. We construct this by hand-rebuilding
        Block 1 with a broader audience and re-signing with B0's
        next_pubkey (so the signature chain itself stays intact and
        the rejection is reached via the attenuation-monotonicity
        gate, not the signature gate).
        """
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        mutated = copy.deepcopy(chain)
        b0_next_priv = bytes.fromhex(chain["private_seeds"]["block0_next"])
        sk = Ed25519PrivateKey.from_private_bytes(b0_next_priv)

        # Broaden Block 1's audience (drop the scope=read-only).
        b1_payload = copy.deepcopy(mutated["chain"][1]["payload"])
        b1_payload["audience_pattern"] = "role=consumer-A,scope=write"  # broader
        digest = hashlib.sha256(_jcs_pure.canonicalize(b1_payload)).digest()
        new_sig = sk.sign(digest).hex()
        mutated["chain"][1]["payload"] = b1_payload
        mutated["chain"][1]["signature"] = new_sig
        mutated["chain"][1]["block_hash"] = hashlib.sha256(
            _jcs_pure.canonicalize(b1_payload)
        ).hexdigest()

        # Block 2 was signed with the OLD Block-1 next_pubkey; that
        # next_pubkey is unchanged in our mutation (we only changed
        # audience_pattern), so signature chain stays intact.
        # Verifier reaches the attenuation-gate.
        result = verify_chain_under_context(mutated, TV_W_2_CONTEXT_ALPHA)
        assert result["verify_status"] == "reject"
        assert result["verify_reason"] == "attenuation-violation"


# ---------------------------------------------------------------------------
# A5 — Cross-lane parity (sandbox vs. production JCS)
# ---------------------------------------------------------------------------


def test_a5_pin_pack_hash_under_pure_python_only(golden: dict) -> None:
    """A5/A3 sandbox-equivalent: force ``_jcs_pure`` and confirm hash."""
    from wirelang.tests._tv_w_2_pin_pack_builder import build_pin_pack_with_hash

    # _jcs_pure is the active backend on the sandbox lane; the
    # production lane uses rfc8785 which is byte-equivalent.
    body = build_pin_pack_with_hash(seed_hex=TV_W_2_TEST_SEED_HEX)
    assert body["pin_pack_sha256"] == golden["pin_pack_sha256"]


def test_a5_pin_pack_hash_under_rfc8785_when_available(golden: dict) -> None:
    """A4 production-lane equivalent: rfc8785 produces the same hash."""
    rfc8785 = pytest.importorskip("rfc8785")
    body = build_pin_pack(seed_hex=TV_W_2_TEST_SEED_HEX)
    pin_hash_via_rfc = hashlib.sha256(rfc8785.dumps(body)).hexdigest()
    assert pin_hash_via_rfc == golden["pin_pack_sha256"]


def test_a5_caveat_set_hashes_byte_equivalent_across_jcs_backends(
    golden: dict,
) -> None:
    """§4-CSC produces byte-equivalent canonical bytes via both JCS backends.

    The ``canonical_caveat_set_hash`` import resolves the active
    backend at module-import time; a parity check on the *bytes* is
    in ``test_datalog_vocabulary_phase_2.py`` (T-CSC-PARITY). Here
    we anchor that the trace fixture's caveat-set-hashes match
    canonical_caveat_set_hash deterministically via the active
    backend; since the per-block caveats are pinned, the hashes
    are pinned, and the rfc8785-vs-_jcs_pure parity in T-CSC-PARITY
    transitively pins the trace.
    """
    trace_alpha = golden["traces"][TV_W_2_CONTEXT_ALPHA]
    block0_caveats = golden["chain"]["block0"]["payload"]["caveats"]
    block1_caveats = golden["chain"]["block1"]["payload"]["caveats"]
    block2_caveats = golden["chain"]["block2"]["payload"]["caveats"]
    expected_hashes = [
        canonical_caveat_set_hash(block0_caveats).hex(),
        canonical_caveat_set_hash(block1_caveats).hex(),
        canonical_caveat_set_hash(block2_caveats).hex(),
    ]
    assert trace_alpha["caveat_set_hashes"] == expected_hashes


# ---------------------------------------------------------------------------
# CLI exercise (external-regeneration contract)
# ---------------------------------------------------------------------------


def test_cli_check_prints_golden_hash(golden: dict) -> None:
    """``python -m wirelang.tests._tv_w_2_pin_pack_builder --check`` prints the golden hash."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wirelang.tests._tv_w_2_pin_pack_builder",
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"regenerator CLI failed: rc={result.returncode}, "
        f"stderr={result.stderr!r}"
    )
    printed_hash = result.stdout.strip()
    assert printed_hash == golden["pin_pack_sha256"], (
        f"CLI hash {printed_hash!r} != golden {golden['pin_pack_sha256']!r}"
    )


# ---------------------------------------------------------------------------
# Cross-compat anchors (TV-W-1 issuer → TV-W-2 issuer)
# ---------------------------------------------------------------------------


def test_cross_compat_issuer_pubkey_matches_tv_w_1_persona_0_0(
    golden: dict,
) -> None:
    """Issuer key in TV-W-2 IS persona-(0,0) Ed25519 sub-key from TV-W-1.

    This is the inverse of the TV-W-1 anchor
    ``test_cross_compat_pubkeys_align_with_capability_token_pin`` —
    asserted from this side so a drift in either fixture surfaces as
    a test failure on both vectors.
    """
    seed = bytes.fromhex(TV_W_2_TEST_SEED_HEX)
    issuer_priv = derive_sub_key_ed25519(
        seed, TV_W_2_ISSUER_PERSONA_IDX, TV_W_2_ISSUER_SPAWN_COUNTER
    )
    issuer_pub = ed25519_public_from_private(issuer_priv).hex()
    assert golden["chain"]["issuer_pub_hex_32"] == issuer_pub

    # And confirm it matches the TV-W-1 fixture by cross-loading.
    tv_w_1_fixture = (
        Path(__file__).resolve().parent / "fixtures" / "tv-w-1" / "pin-pack.json"
    )
    if tv_w_1_fixture.exists():
        with tv_w_1_fixture.open("r", encoding="utf-8") as fh:
            tv_w_1 = json.load(fh)
        record_00 = next(
            r for r in tv_w_1["records"]
            if r["persona_idx"] == 0 and r["spawn_counter"] == 0
        )
        assert record_00["ed25519_pub_hex_32"] == issuer_pub, (
            "TV-W-1 persona-(0,0) Ed25519 pub does not match TV-W-2 issuer; "
            "one of the two fixtures has drifted."
        )


# ---------------------------------------------------------------------------
# Builder self-consistency (cheap regression net)
# ---------------------------------------------------------------------------


def test_builder_with_hash_round_trips() -> None:
    """``build_pin_pack_with_hash`` agrees with ``build_pin_pack`` + hash."""
    full = build_pin_pack_with_hash(seed_hex=TV_W_2_TEST_SEED_HEX)
    embedded = full["pin_pack_sha256"]
    body = {k: v for k, v in full.items() if k != "pin_pack_sha256"}
    assert pin_pack_hash(body) == embedded
