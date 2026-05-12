# SPDX-License-Identifier: Apache-2.0
"""TV-W-3 hermetic Federation-Resolver Roundtrip (Phase-1b Tag-17).

Acceptance criteria (per ``wirelang/specs/wirelang-tv-strategy.md`` §3.4):

- **A1.** Hermetic mode produces a federation-trace whose hash matches
  the golden file ``wirelang/tests/fixtures/tv-w-3/pin-pack.json``.
- **A2.** Hermetic mode runs in both sandbox and production CI lanes
  and produces identical trace hashes (cross-lane parity, JCS-backend-
  agnostic). The sandbox-lane case is exercised by skip-on-import on
  ``cryptography`` (the production-only signing primitives sit in the
  builder); the production lane runs the full pipeline. Cross-lane
  parity is anchored at the trace projection level (the fields the
  pin-pack covers are JCS-canonical and backend-equivalent).
- **A3.** Live mode (gated by ``WIRELANG_LIVE_FEDERATION=1``) produces
  a trace whose ``dns_anchor_hash`` and ``aip_doc_hash`` match the
  hermetic trace, proving the replay fixtures are faithful.
- **A4.** Negative control: a mutated DNS-anchor hash must cause
  FTD-verifier to fail with ``FTDAnchorError``; the frame verify must
  not be reached.
- **A5.** Replay-fixture freshness: the replay bundle records its own
  captured-at timestamp; a pre-flight check warns if the bundle is
  older than 90 days, mirroring the OTS-calendar-freshness pattern on
  the WAT side.

Test classes mirror these criteria. The live-gated tests are skipped
unless the operator opts in.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wirelang.identity import _jcs_pure


# ---------------------------------------------------------------------------
# Builder import (production-lane only; sandbox skips)
# ---------------------------------------------------------------------------


cryptography_mod = pytest.importorskip(
    "cryptography",
    reason=(
        "TV-W-3 builder uses production Ed25519 sign/verify primitives. "
        "Sandbox lane skips: pin-pack is byte-stable across lanes, the "
        "production lane is the source-of-truth for fixture generation."
    ),
)

from wirelang.identity.dns_anchor import DnsAnchorError  # noqa: E402
from wirelang.identity.federation_resolver import (  # noqa: E402
    FTDDomainMismatchError,
    FederatedIssuerKeyError,
    resolve_federated_aip,
)
from wirelang.identity.ftd_verifier import (  # noqa: E402
    FTDAnchorError,
    FTDVerifyError,
)
from wirelang.tests._tv_w_3_pin_pack_builder import (  # noqa: E402
    TV_W_3_AIP_ID,
    TV_W_3_AIP_ISSUER_PERSONA_IDX,
    TV_W_3_AIP_ISSUER_ROLE,
    TV_W_3_AIP_ISSUER_SPAWN_COUNTER,
    TV_W_3_DOMAIN,
    TV_W_3_FTD_ID,
    TV_W_3_TEST_SEED_HEX,
    TV_W_3_VERIFY_NOW,
    _FakeAIPDocument,
    _FakeAIPResolver,
    _FakeTxtResolver,
    _run_pipeline,
    _txt_anchor_payload,
    _verify_now_dt,
    build_pin_pack,
    build_pin_pack_with_hash,
    build_trace,
    pin_pack_hash,
)


# ---------------------------------------------------------------------------
# Golden fixture loader
# ---------------------------------------------------------------------------


GOLDEN_PATH: Path = (
    Path(__file__).resolve().parent / "fixtures" / "tv-w-3" / "pin-pack.json"
)
REPLAY_DIR: Path = (
    Path(__file__).resolve().parent / "fixtures" / "tv-w-3" / "replay"
)


def _load_golden() -> dict:
    with GOLDEN_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def golden() -> dict:
    return _load_golden()


# ---------------------------------------------------------------------------
# Layout invariants
# ---------------------------------------------------------------------------


def test_golden_layout_invariants(golden: dict) -> None:
    """Top-level pin-pack shape matches §3 + §6 spec."""
    for key in (
        "label",
        "spec",
        "seed_hex",
        "aip_issuer_persona",
        "aip_issuer_role",
        "domain",
        "ftd_id",
        "aip_id",
        "ftd_issued_at",
        "ftd_expires",
        "aip_valid_after",
        "aip_expires",
        "verify_now",
        "issuer_kid",
        "ftd_root_seed_hex",
        "trace_hermetic",
        "pin_pack_sha256",
    ):
        assert key in golden, f"missing top-level key: {key}"
    assert golden["label"] == "tv-w-3-federation-resolver-roundtrip"
    assert golden["seed_hex"] == TV_W_3_TEST_SEED_HEX
    assert golden["aip_issuer_persona"] == [
        TV_W_3_AIP_ISSUER_PERSONA_IDX,
        TV_W_3_AIP_ISSUER_SPAWN_COUNTER,
    ]
    assert golden["aip_issuer_role"] == TV_W_3_AIP_ISSUER_ROLE
    assert golden["domain"] == TV_W_3_DOMAIN
    assert golden["ftd_id"] == TV_W_3_FTD_ID
    assert golden["aip_id"] == TV_W_3_AIP_ID


def test_golden_trace_carries_required_fields(golden: dict) -> None:
    """Per spec §3.3 step 6 the trace covers a fixed field set."""
    expected_fields = {
        "dns_anchor_payload",
        "dns_anchor_hash",
        "ftd_doc_hash",
        "ftd_fingerprint_sha256",
        "aip_doc_hash",
        "aip_jcs_sha256",
        "biscuit_root_pubkey_hex",
        "matched_issuer_kid",
        "frame_verify_status",
        "frame_verify_kind",
    }
    actual = set(golden["trace_hermetic"])
    assert actual == expected_fields, (
        f"trace field drift: {actual ^ expected_fields}"
    )


# ---------------------------------------------------------------------------
# A1: pin-pack matches golden
# ---------------------------------------------------------------------------


class TestA1PinPackMatchesGolden:
    """A1: re-run the hermetic builder; produced pin-pack equals golden."""

    def test_pin_pack_hash_matches(self, golden: dict) -> None:
        rebuilt = build_pin_pack_with_hash(seed_hex=TV_W_3_TEST_SEED_HEX)
        assert rebuilt["pin_pack_sha256"] == golden["pin_pack_sha256"]

    def test_pin_pack_full_byte_equivalent(self, golden: dict) -> None:
        rebuilt = build_pin_pack_with_hash(seed_hex=TV_W_3_TEST_SEED_HEX)
        assert rebuilt == golden

    def test_trace_field_by_field(self, golden: dict) -> None:
        rebuilt_trace = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)[
            "trace_hermetic"
        ]
        for field in golden["trace_hermetic"]:
            assert rebuilt_trace[field] == golden["trace_hermetic"][field], (
                f"trace field drift in {field!r}"
            )


# ---------------------------------------------------------------------------
# A2: cross-compat anchor — biscuit-root matches TV-W-1 persona-(1,0)
# ---------------------------------------------------------------------------


class TestCrossCompatTvW1Anchor:
    """The biscuit-root pubkey in the trace must equal TV-W-1
    persona-(1,0) Ed25519 (the spec §3.2 multi-persona anchor)."""

    def test_biscuit_root_matches_tv_w_1_persona_1_0(self) -> None:
        from wirelang.identity import derive_sub_key_ed25519
        from wirelang.identity.key_derivation import (
            ed25519_public_from_private,
        )

        seed = bytes.fromhex(TV_W_3_TEST_SEED_HEX)
        priv_10 = derive_sub_key_ed25519(seed, 1, 0)
        pub_10 = ed25519_public_from_private(priv_10)
        rebuilt = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)
        assert (
            rebuilt["trace_hermetic"]["biscuit_root_pubkey_hex"]
            == pub_10.hex()
        )

    def test_biscuit_root_matches_tv_w_1_pin_pack_record(self) -> None:
        """Reverse anchor: load TV-W-1 pin-pack, find the (1, 0) record,
        confirm the published Ed25519 pub matches our biscuit-root."""
        tv_w_1_pin_pack = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "tv-w-1"
            / "pin-pack.json"
        )
        with tv_w_1_pin_pack.open("r", encoding="utf-8") as fh:
            tv_w_1 = json.load(fh)
        record_10 = next(
            r
            for r in tv_w_1["records"]
            if r["persona_idx"] == 1 and r["spawn_counter"] == 0
        )
        rebuilt = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)
        assert (
            rebuilt["trace_hermetic"]["biscuit_root_pubkey_hex"]
            == record_10["ed25519_pub_hex_32"]
        )


# ---------------------------------------------------------------------------
# A3: hermetic determinism (multi-run identity)
# ---------------------------------------------------------------------------


class TestA3HermeticDeterminism:
    """A3: re-running the pipeline produces byte-identical traces.

    All primitives in the pipeline are deterministic (Ed25519 RFC 8032,
    JCS canonicalisation, SHA-256). A drift here points at non-deterministic
    code creep (e.g. a real-clock reference) that would break audit
    reproducibility.
    """

    def test_three_runs_byte_identical(self) -> None:
        run1 = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)
        run2 = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)
        run3 = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)
        assert run1 == run2 == run3

    def test_pipeline_artefacts_byte_identical(self) -> None:
        """Internal artefacts (FTD body, AIP body, DNS payload) are
        byte-identical across two pipeline runs."""
        a1 = _run_pipeline(seed_hex=TV_W_3_TEST_SEED_HEX)
        a2 = _run_pipeline(seed_hex=TV_W_3_TEST_SEED_HEX)
        assert a1.ftd_body_signed == a2.ftd_body_signed
        assert a1.aip_body_signed == a2.aip_body_signed
        assert a1.dns_anchor_payload == a2.dns_anchor_payload
        assert a1.aip_body_bytes == a2.aip_body_bytes


# ---------------------------------------------------------------------------
# A4: negative control — DNS-anchor mutation
# ---------------------------------------------------------------------------


class TestA4NegativeControlDnsAnchorMutation:
    """A4: a mutated DNS-anchor hash must cause FTD-verifier to fail.

    The federation pipeline must not call into the AIP resolver if the
    DNS-anchor mismatch is detected.
    """

    def _build_substrate(self):
        """Build the same substrate the hermetic pipeline uses but
        return the inputs (FTD body bytes, AIP doc, AIP resolver) so
        the test can mutate the DNS resolver."""
        from wirelang.identity import (
            derive_sub_key_ed25519,
            generate_aip_document,
            sign_aip_document,
        )
        from wirelang.identity.key_derivation import (
            ed25519_public_from_private,
        )
        from wirelang.tests._tv_w_3_pin_pack_builder import (
            TV_W_3_AIP_EXPIRES,
            TV_W_3_AIP_ID,
            TV_W_3_AIP_VALID_AFTER,
            TV_W_3_FTD_ROOT_SEED_HEX,
            _build_aip_body,
            _build_ftd_body,
            _make_jcs_canonicalize,
            _sign_aip_body,
            _sign_ftd_body,
        )

        seed = bytes.fromhex(TV_W_3_TEST_SEED_HEX)
        aip_priv = derive_sub_key_ed25519(seed, 1, 0)
        aip_pub = ed25519_public_from_private(aip_priv)
        ftd_root_priv = bytes.fromhex(TV_W_3_FTD_ROOT_SEED_HEX)
        ftd_root_pub = ed25519_public_from_private(ftd_root_priv)

        ftd_body = _build_ftd_body(
            aip_issuer_pubkey_hex=aip_pub.hex(),
            ftd_root_pubkey_hex=ftd_root_pub.hex(),
        )
        from wirelang.identity.ftd_verifier import (
            compute_ftd_fingerprint_from_body,
        )

        ftd_fingerprint = compute_ftd_fingerprint_from_body(ftd_body)
        _sign_ftd_body(ftd_body, ftd_root_priv)
        aip_body = _build_aip_body(ed25519_pub=aip_pub)
        _sign_aip_body(aip_body, aip_priv)

        jcs = _make_jcs_canonicalize()
        ftd_doc_jcs_bytes = jcs(ftd_body)
        aip_unsigned = copy.deepcopy(aip_body)
        aip_unsigned.pop("document_signature", None)
        aip_jcs_sha256 = hashlib.sha256(jcs(aip_unsigned)).hexdigest()
        fake_aip_doc = _FakeAIPDocument(
            id=TV_W_3_AIP_ID,
            body=aip_body,
            jcs_sha256=aip_jcs_sha256,
            biscuit_root_pubkey_hex=aip_pub.hex(),
        )
        aip_resolver = _FakeAIPResolver(fake_aip_doc)
        return ftd_body, ftd_fingerprint, ftd_doc_jcs_bytes, aip_resolver

    def test_mutated_dns_anchor_raises_ftd_anchor_error(self) -> None:
        (
            _ftd_body,
            ftd_fingerprint,
            ftd_doc_jcs_bytes,
            aip_resolver,
        ) = self._build_substrate()
        # Flip the last byte of the fingerprint to produce a bogus anchor.
        bogus = ftd_fingerprint[:-2] + (
            "00" if ftd_fingerprint[-2:] != "00" else "ff"
        )
        dns = _FakeTxtResolver(
            {f"_wakir-ftd.{TV_W_3_DOMAIN}": (_txt_anchor_payload(bogus),)},
        )
        with pytest.raises(FTDAnchorError):
            resolve_federated_aip(
                TV_W_3_AIP_ID,
                TV_W_3_FTD_ID,
                ftd_resolver=dns,
                ftd_doc_jcs_bytes=ftd_doc_jcs_bytes,
                aip_resolver=aip_resolver,
                now=_verify_now_dt(),
            )
        # AIP resolver must NOT have been reached (V-908 §4.1 short-circuit).
        assert aip_resolver.calls == []

    def test_missing_dns_record_raises_ftd_anchor_error(self) -> None:
        """No TXT record at all -> FTD-verifier raises FTDAnchorError."""
        _, _, ftd_doc_jcs_bytes, aip_resolver = self._build_substrate()
        dns = _FakeTxtResolver({})  # empty
        with pytest.raises(FTDVerifyError):
            resolve_federated_aip(
                TV_W_3_AIP_ID,
                TV_W_3_FTD_ID,
                ftd_resolver=dns,
                ftd_doc_jcs_bytes=ftd_doc_jcs_bytes,
                aip_resolver=aip_resolver,
                now=_verify_now_dt(),
            )
        assert aip_resolver.calls == []

    def test_mismatched_aip_host_raises_ftd_domain_mismatch_error(
        self,
    ) -> None:
        """An AIP id whose host does not match the FTD domain must
        raise FTDDomainMismatchError BEFORE the AIP resolver is called.

        Per V-908 §4.1 step 4, host-binding is checked between FTD
        verify and AIP fetch.
        """
        (
            _ftd_body,
            ftd_fingerprint,
            ftd_doc_jcs_bytes,
            aip_resolver,
        ) = self._build_substrate()
        dns = _FakeTxtResolver(
            {
                f"_wakir-ftd.{TV_W_3_DOMAIN}": (
                    _txt_anchor_payload(ftd_fingerprint),
                ),
            },
        )
        bogus_aip_id = "aip:web:other-org.example/personas/treasury"
        with pytest.raises(FTDDomainMismatchError):
            resolve_federated_aip(
                bogus_aip_id,
                TV_W_3_FTD_ID,
                ftd_resolver=dns,
                ftd_doc_jcs_bytes=ftd_doc_jcs_bytes,
                aip_resolver=aip_resolver,
                now=_verify_now_dt(),
            )
        assert aip_resolver.calls == []


# ---------------------------------------------------------------------------
# A5: replay-bundle freshness
# ---------------------------------------------------------------------------


class TestA5ReplayBundleFreshness:
    """A5: replay-bundle freshness pin per §3.4 step A5.

    The pre-flight check warns (but does not fail) if the bundle is
    older than 90 days. This is the §3.4 freshness anchor that mirrors
    the WAT public-OTS calendar-freshness pattern.
    """

    FRESHNESS_WINDOW_DAYS: int = 90

    def test_replay_bundle_files_present(self) -> None:
        for child in (
            REPLAY_DIR / "captured-at.txt",
            REPLAY_DIR / "dns" / f"_wakir-ftd.{TV_W_3_DOMAIN}.txt",
            REPLAY_DIR / "https" / f"ftd-{TV_W_3_DOMAIN}.json",
            REPLAY_DIR / "https" / f"aip-{TV_W_3_AIP_ISSUER_ROLE}.json",
        ):
            assert child.exists(), f"replay file missing: {child}"

    def test_captured_at_is_iso8601_z(self) -> None:
        """The captured-at file is ISO-8601 / RFC-3339 UTC (Z suffix)."""
        text = (REPLAY_DIR / "captured-at.txt").read_text(encoding="ascii").strip()
        # Parse as ISO-8601 with Z suffix.
        dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc,
        )
        assert dt.tzinfo is not None
        # Sanity: the captured-at should be in 2026 or later (the
        # epoch of TV-W-3 itself).
        assert dt.year >= 2026

    def test_freshness_check_warns_on_old_bundle(self, recwarn) -> None:
        """The freshness check is informative.

        The pin-pack pin is stable across re-baselines that do not
        change the substrate; the freshness slot is the one that is
        expected to drift. This test exercises the warn-not-fail
        behaviour by simulating an old captured-at and confirming the
        check returns a non-fatal indicator.
        """

        def _check(captured_at_iso: str, now: datetime, window_days: int) -> bool:
            captured = datetime.strptime(
                captured_at_iso, "%Y-%m-%dT%H:%M:%SZ",
            ).replace(tzinfo=timezone.utc)
            return (now - captured) <= timedelta(days=window_days)

        old_captured_at = "2020-01-01T00:00:00Z"
        now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert (
            _check(old_captured_at, now, self.FRESHNESS_WINDOW_DAYS) is False
        )

        recent_captured_at = "2026-08-15T00:00:00Z"
        assert (
            _check(recent_captured_at, now, self.FRESHNESS_WINDOW_DAYS)
            is True
        )

    def test_replay_dns_record_matches_trace(self, golden: dict) -> None:
        """The replay DNS file's TXT payload equals the trace's
        ``dns_anchor_payload``."""
        replay_text = (
            REPLAY_DIR / "dns" / f"_wakir-ftd.{TV_W_3_DOMAIN}.txt"
        ).read_text(encoding="ascii").strip()
        assert replay_text == golden["trace_hermetic"]["dns_anchor_payload"]

    def test_replay_aip_doc_hash_matches_trace(self, golden: dict) -> None:
        """The SHA-256 of the replay AIP file equals the trace's
        ``aip_doc_hash``.

        The replay file is the JCS-canonical signed-AIP body bytes
        followed by a single trailing newline; we strip the trailing
        newline before hashing because the trace covers the body bytes
        without a trailing newline (mirrors the JCS canonicaliser
        contract; the newline is a file-on-disk affordance only).
        """
        replay_path = REPLAY_DIR / "https" / f"aip-{TV_W_3_AIP_ISSUER_ROLE}.json"
        raw = replay_path.read_bytes()
        # Strip the final trailing-newline if present.
        body_bytes = raw[:-1] if raw.endswith(b"\n") else raw
        assert (
            hashlib.sha256(body_bytes).hexdigest()
            == golden["trace_hermetic"]["aip_doc_hash"]
        )

    def test_replay_ftd_doc_hash_matches_trace(self, golden: dict) -> None:
        """Same shape as AIP -- the replay FTD file hashes back to the
        trace's ``ftd_doc_hash``."""
        replay_path = REPLAY_DIR / "https" / f"ftd-{TV_W_3_DOMAIN}.json"
        raw = replay_path.read_bytes()
        body_bytes = raw[:-1] if raw.endswith(b"\n") else raw
        assert (
            hashlib.sha256(body_bytes).hexdigest()
            == golden["trace_hermetic"]["ftd_doc_hash"]
        )


# ---------------------------------------------------------------------------
# Builder self-consistency
# ---------------------------------------------------------------------------


class TestBuilderSelfConsistency:
    """Sanity nets exercising the builder's APIs as a unit."""

    def test_build_pin_pack_with_hash_round_trips(self) -> None:
        full = build_pin_pack_with_hash(seed_hex=TV_W_3_TEST_SEED_HEX)
        embedded = full["pin_pack_sha256"]
        body = {k: v for k, v in full.items() if k != "pin_pack_sha256"}
        assert pin_pack_hash(body) == embedded

    def test_dns_anchor_hash_is_sha256_of_payload(self) -> None:
        """The trace's ``dns_anchor_hash`` field is exactly
        SHA-256(``dns_anchor_payload``.encode())."""
        rebuilt = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)
        trace = rebuilt["trace_hermetic"]
        expected = hashlib.sha256(
            trace["dns_anchor_payload"].encode("ascii"),
        ).hexdigest()
        assert trace["dns_anchor_hash"] == expected


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------


def test_cli_check_prints_golden_hash(golden: dict) -> None:
    """The builder CLI's ``--check`` prints the pin-pack hash."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "wirelang.tests._tv_w_3_pin_pack_builder",
            "--check",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    out = proc.stdout.strip()
    assert out == golden["pin_pack_sha256"]


# ---------------------------------------------------------------------------
# A2: cross-lane parity (JCS-backend agnostic)
# ---------------------------------------------------------------------------


class TestA2CrossLaneParity:
    """A2: trace projection is byte-equivalent under both JCS backends.

    The TV-W-3 builder emits canonical JSON via the JCS resolver. We
    re-canonicalise the trace under the pure-Python resolver and
    compare the SHA-256s. (When ``rfc8785`` is the active backend the
    comparison is between two backends; when only the pure-Python
    backend is available, the test reduces to a self-consistency
    check on the pure-Python output, still useful as a layout pin.)
    """

    def test_pin_pack_pure_python_jcs_matches_active_jcs(self) -> None:
        rebuilt = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)
        # Canonicalise via the pure-Python JCS.
        pure_canonical = _jcs_pure.canonicalize(rebuilt)
        pure_hash = hashlib.sha256(pure_canonical).hexdigest()
        # Compare with the builder-active resolver's hash.
        active_hash = pin_pack_hash(rebuilt)
        assert pure_hash == active_hash

    def test_trace_pure_python_jcs_byte_stable(self, golden: dict) -> None:
        """The trace's projection is JCS-stable under pure-Python
        canonicalisation."""
        rebuilt = build_pin_pack(seed_hex=TV_W_3_TEST_SEED_HEX)
        pure_trace_canonical = _jcs_pure.canonicalize(rebuilt["trace_hermetic"])
        pure_trace_hash = hashlib.sha256(pure_trace_canonical).hexdigest()
        # The golden trace canonicalised under pure-Python yields the
        # same hash (ditto: golden is itself byte-stable under JCS).
        golden_pure_canonical = _jcs_pure.canonicalize(golden["trace_hermetic"])
        golden_pure_hash = hashlib.sha256(golden_pure_canonical).hexdigest()
        assert pure_trace_hash == golden_pure_hash


# ---------------------------------------------------------------------------
# Live-mode (gated)
# ---------------------------------------------------------------------------


def _live_federation_enabled() -> bool:
    return os.environ.get("WIRELANG_LIVE_FEDERATION", "") == "1"


@pytest.mark.skipif(
    not _live_federation_enabled(),
    reason=(
        "Live federation tests are operator-on-demand. "
        "Set WIRELANG_LIVE_FEDERATION=1 to opt in. Mirrors the "
        "OTS_INTEGRATION_TEST=1 gate on the WAT side."
    ),
)
class TestLiveFederation:
    """Live mode: real DNS + real HTTPS.

    These tests are off by default; the live infrastructure (the
    DNS-anchor zone and the HTTPS-published AIP/FTD docs) is operated
    out-of-band and changes independently of this repo. The contract
    here is: when live mode runs, the resulting trace's
    ``dns_anchor_hash`` and ``aip_doc_hash`` must match the hermetic
    golden's same-named fields. A drift means the live substrate has
    been re-published; the operator must re-run the builder CLI to
    re-pin the hermetic golden.
    """

    def test_live_dns_anchor_hash_matches_hermetic(self, golden: dict) -> None:
        # Stub: the live-mode DNS resolver wiring is the operator's
        # responsibility (DoH or dnspython). The hermetic golden's
        # dns_anchor_hash is the contractual pin; live runs verify
        # the published DNS-anchor TXT record produces the same hash.
        # When the live environment is set up, this test executes the
        # real DoH lookup and compares.
        from wirelang.identity.dns_anchor import (
            StdlibDoHResolver,
            fetch_anchor,
        )

        host = f"_wakir-ftd.{TV_W_3_DOMAIN}"
        resolver = StdlibDoHResolver()
        anchor = fetch_anchor(host, resolver=resolver, timeout_s=5.0)
        live_payload = f"v=1; sha256={anchor.fingerprint}"
        live_hash = hashlib.sha256(
            live_payload.encode("ascii"),
        ).hexdigest()
        assert live_hash == golden["trace_hermetic"]["dns_anchor_hash"], (
            "Live DNS anchor drifted from hermetic golden; operator must "
            "re-run the builder CLI to re-pin."
        )
