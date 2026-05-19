# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic invariants for the Cosign-Strict-Mode Readiness Check (Tag-54).

Mirrors the pure-function-vs-IO split of
``scripts/observability/cosign-strict-mode-readiness-check.py``: the
tests target the pure functions ABOVE the I/O boundary; no podman /
cosign / network egress.

Test-vector naming:
  TV-SM-NN  — readiness-check substrate test, NN = ordinal.

Invariants (≥12, target 16; Tag-55 closeout: extended to ≥27):

  TV-SM-01  inventory constant matches Tag-45 canonical size (15).
  TV-SM-02  inventory constant order is deterministic + frozen.
  TV-SM-03  policy_view_from_raw extracts the 15-binary inventory.
  TV-SM-04  policy_view_from_raw tolerates malformed dict.
  TV-SM-05  trust_root_view_from_raw round-trips the four axes.
  TV-SM-06  probe_envelope_view_from_raw round-trips aggregate_verdict.
  TV-SM-07  quadlet_installer_binary_names_from_text grep-extracts
            the canonical names from a realistic installer fixture.
  TV-SM-08  G1 BLOCKED on placeholder digest in policy.
  TV-SM-09  G1 GREEN on all real sha256 digests.
  TV-SM-10  G2 BLOCKED on PENDING_OPERATOR_HAND_REFRESH in trust-root.
  TV-SM-11  G2 GREEN on real Fulcio CA SHA + Rekor shard ID.
  TV-SM-12  G3 NOT-CHECKED when envelope is None (file missing).
  TV-SM-13  G3 BLOCKED when last probe verdict is non-GREEN.
  TV-SM-14  G4 BLOCKED on inventory drift (size mismatch).
  TV-SM-15  G5 BLOCKED on quadlet-vs-policy set drift.
  TV-SM-16  G6 GREEN — required-status-check names are non-empty.
  TV-SM-17  aggregate_run_verdict precedence BLOCKED > NOT-CHECKED > GREEN.
  TV-SM-18  render_markdown_summary contains all six gate rows.
  TV-SM-19  envelope_to_json carries schema + run_ts + per-gate rows.

  Tag-55 closeout additions:
  TV-SM-20  load_quadlet_installer_glob returns None when no matches.
  TV-SM-21  load_quadlet_installer_glob unions binary-names across all
            matched Quadlet files in deterministic sorted-path order.
  TV-SM-22  glob loader dedupes names across files.
  TV-SM-23  on-disk Welle-4..7 Quadlets each declare exactly their
            single welle-suffix binary name (regression pin).
  TV-SM-24  on-disk policy YAML has the canonical 15 binaries in the
            canonical order (G4 substrate-pin).
  TV-SM-25  on-disk Quadlet glob unions to the canonical 15 binary
            set (G5 substrate-pin post Tag-55 Welle-4..7 add).
  TV-SM-26  on-disk last-probe-envelope.json is present and parses to
            an aggregate_verdict (G3 substrate-pin).
  TV-SM-27  G5 GREEN evaluator on a quadlet view that carries the
            canonical 15 set (set-equality, order-insensitive).
  TV-SM-28  REAL_DIGEST_RE only accepts well-formed sha256 + 64 hex.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Tuple

import pytest


# ---------------------------------------------------------------------------
# Module-load helper (the script's filename has a hyphen, so we load via
# importlib.util.spec_from_file_location).
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "observability" / "cosign-strict-mode-readiness-check.py"


@pytest.fixture(scope="module")
def smod():
    """Load the readiness-check module from its hyphenated filename.

    Note: must register the module in ``sys.modules`` BEFORE
    ``exec_module`` so dataclass introspection (Python 3.14
    dataclasses._is_type) can resolve the module via
    ``sys.modules[cls.__module__]``.
    """
    spec = importlib.util.spec_from_file_location(
        "cosign_strict_mode_readiness_check",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cosign_strict_mode_readiness_check"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Constant invariants
# ---------------------------------------------------------------------------


def test_tv_sm_01_inventory_size_matches_tag45_canonical(smod):
    """TV-SM-01: TAG45_CANONICAL_INVENTORY carries exactly 15 entries."""
    assert len(smod.TAG45_CANONICAL_INVENTORY) == 15


def test_tv_sm_02_inventory_order_is_frozen(smod):
    """TV-SM-02: the canonical order is the Tag-45 chronological order.

    The first nine entries land Tag-17..Tag-31; the Welle-4..7 four
    entries land Tag-33; the last two (bridge-audit-replay,
    migrate-version) land Tag-37/Tag-38 (Phase-3a 14./15. Modul).
    """
    expected: Tuple[str, ...] = (
        "recovery",
        "state-backing",
        "fsm",
        "v907-verify",
        "bridge-diff",
        "subscribe-loop",
        "anchor-emitter",
        "svid-workload-identity",
        "bridge-audit-writer",
        "state-backing-welle4",
        "fsm-welle5",
        "subscribe-loop-welle6",
        "recovery-welle7",
        "bridge-audit-replay",
        "migrate-version",
    )
    assert smod.TAG45_CANONICAL_INVENTORY == expected


# ---------------------------------------------------------------------------
# Pure-function parsing tests
# ---------------------------------------------------------------------------


def _real_digest(seed: int = 0) -> str:
    """Generate a syntactically-valid sha256:[64-hex] string."""
    hex_chars = "0123456789abcdef"
    body = "".join(hex_chars[(seed + i) % 16] for i in range(64))
    return f"sha256:{body}"


def _real_fulcio_sha(seed: int = 1) -> str:
    """Generate a 64-hex-char SHA-256 body (no sha256: prefix)."""
    hex_chars = "0123456789abcdef"
    return "".join(hex_chars[(seed + i) % 16] for i in range(64))


def _canonical_policy_raw():
    """Build a synthetic policy-raw dict that matches the canonical 15."""
    return {
        "schema_version": "wakir.cosign-policy.phase-3b/1",
        "policy": {
            "carrier_image": {
                "expected_image_digest": _real_digest(seed=7),
            },
            "certificate_identity_regexp": r"https://github\.com/wakir-labs/wakir-runtime/",
            "certificate_oidc_issuer": "https://token.actions.githubusercontent.com",
        },
        "binaries": [{"name": n} for n in (
            "recovery",
            "state-backing",
            "fsm",
            "v907-verify",
            "bridge-diff",
            "subscribe-loop",
            "anchor-emitter",
            "svid-workload-identity",
            "bridge-audit-writer",
            "state-backing-welle4",
            "fsm-welle5",
            "subscribe-loop-welle6",
            "recovery-welle7",
            "bridge-audit-replay",
            "migrate-version",
        )],
    }


def test_tv_sm_03_policy_view_extracts_inventory(smod):
    """TV-SM-03: policy_view_from_raw extracts the 15-binary inventory."""
    view = smod.policy_view_from_raw(_canonical_policy_raw())
    assert view.binary_names == smod.TAG45_CANONICAL_INVENTORY
    assert view.schema_version == "wakir.cosign-policy.phase-3b/1"
    assert smod.REAL_DIGEST_RE.match(view.carrier_expected_image_digest)


def test_tv_sm_04_policy_view_tolerates_malformed(smod):
    """TV-SM-04: policy_view_from_raw yields empty fields on malformed dict."""
    view = smod.policy_view_from_raw({})
    assert view.schema_version == ""
    assert view.carrier_expected_image_digest == ""
    assert view.binary_names == ()


def test_tv_sm_05_trust_root_view_round_trips(smod):
    """TV-SM-05: trust_root_view_from_raw round-trips the four axes."""
    sha = _real_fulcio_sha()
    raw = {
        "cosign_installer_action": "sigstore/cosign-installer@v3",
        "cosign_installer_semver_major": "v3",
        "fulcio_root_ca_sha256": sha,
        "rekor_log_shard_id": "shard-2026-q2",
    }
    view = smod.trust_root_view_from_raw(raw)
    assert view.fulcio_root_ca_sha256 == sha
    assert view.rekor_log_shard_id == "shard-2026-q2"
    assert view.cosign_installer_action == "sigstore/cosign-installer@v3"


def test_tv_sm_06_probe_envelope_view_round_trips(smod):
    """TV-SM-06: probe_envelope_view_from_raw round-trips aggregate_verdict."""
    view = smod.probe_envelope_view_from_raw({
        "aggregate_verdict": "GREEN",
        "probe_ts": 12345.0,
    })
    assert view.aggregate_verdict == "GREEN"
    assert view.probe_ts == 12345.0


def test_tv_sm_07_quadlet_installer_name_extraction(smod):
    """TV-SM-07: quadlet grep extracts canonical names + skips duplicates."""
    text = """
    # Sample Quadlet installer fragment
    /opt/wakir/bin/wakir-persona-engine-recovery --probe
    /opt/wakir/bin/wakir-persona-engine-state-backing --probe
    /opt/wakir/bin/wakir-persona-engine-fsm --probe
    # duplicate reference should be deduped
    /opt/wakir/bin/wakir-persona-engine-recovery --info
    /opt/wakir/bin/wakir-persona-engine-state-backing-welle4 --probe
    """
    names = smod.quadlet_installer_binary_names_from_text(text)
    assert names == (
        "recovery",
        "state-backing",
        "fsm",
        "state-backing-welle4",
    )


# ---------------------------------------------------------------------------
# Gate G1..G6 evaluation tests
# ---------------------------------------------------------------------------


def test_tv_sm_08_g1_blocked_on_placeholder_digest(smod):
    """TV-SM-08: G1 BLOCKED when carrier digest is the PENDING placeholder."""
    raw = _canonical_policy_raw()
    raw["policy"]["carrier_image"]["expected_image_digest"] = smod.PLACEHOLDER_DIGEST
    view = smod.policy_view_from_raw(raw)
    result = smod.evaluate_gate_g1_placeholder_digests(view, raw["binaries"])
    assert result.gate_id == "G1"
    assert result.verdict == "BLOCKED"
    assert "DIGEST_PENDING_KAI_CROSS_REVIEW" in result.summary


def test_tv_sm_09_g1_green_on_all_real_digests(smod):
    """TV-SM-09: G1 GREEN when carrier digest is a real sha256."""
    raw = _canonical_policy_raw()
    view = smod.policy_view_from_raw(raw)
    result = smod.evaluate_gate_g1_placeholder_digests(view, raw["binaries"])
    assert result.gate_id == "G1"
    assert result.verdict == "GREEN"


def test_tv_sm_10_g2_blocked_on_pending_trust_root(smod):
    """TV-SM-10: G2 BLOCKED when fulcio_root_ca_sha256 is PENDING."""
    view = smod.PinnedTrustRootView(
        fulcio_root_ca_sha256=smod.PLACEHOLDER_TRUST_ROOT,
        rekor_log_shard_id="shard-2026-q2",
        cosign_installer_action="sigstore/cosign-installer@v3",
    )
    result = smod.evaluate_gate_g2_trust_root_completeness(view)
    assert result.gate_id == "G2"
    assert result.verdict == "BLOCKED"
    assert "PENDING_OPERATOR_HAND_REFRESH" in result.summary


def test_tv_sm_11_g2_green_on_real_trust_root(smod):
    """TV-SM-11: G2 GREEN when both pinned fields are real."""
    view = smod.PinnedTrustRootView(
        fulcio_root_ca_sha256=_real_fulcio_sha(),
        rekor_log_shard_id="shard-2026-q2",
        cosign_installer_action="sigstore/cosign-installer@v3",
    )
    result = smod.evaluate_gate_g2_trust_root_completeness(view)
    assert result.gate_id == "G2"
    assert result.verdict == "GREEN"


def test_tv_sm_12_g3_not_checked_on_missing_envelope(smod):
    """TV-SM-12: G3 NOT-CHECKED when envelope is None."""
    result = smod.evaluate_gate_g3_last_probe_verdict(None)
    assert result.gate_id == "G3"
    assert result.verdict == "NOT-CHECKED"


def test_tv_sm_13_g3_blocked_on_nongreen_last_probe(smod):
    """TV-SM-13: G3 BLOCKED when last probe verdict is non-GREEN."""
    view = smod.ProbeEnvelopeView(aggregate_verdict="DRIFT-TRUST-ROOT", probe_ts=0.0)
    result = smod.evaluate_gate_g3_last_probe_verdict(view)
    assert result.gate_id == "G3"
    assert result.verdict == "BLOCKED"
    assert "DRIFT-TRUST-ROOT" in result.summary


def test_tv_sm_14_g4_blocked_on_inventory_size_drift(smod):
    """TV-SM-14: G4 BLOCKED when inventory size != 15."""
    raw = _canonical_policy_raw()
    raw["binaries"] = raw["binaries"][:14]  # drop one
    view = smod.policy_view_from_raw(raw)
    result = smod.evaluate_gate_g4_inventory_size(view)
    assert result.gate_id == "G4"
    assert result.verdict == "BLOCKED"
    assert "14" in result.summary


def test_tv_sm_15_g5_blocked_on_quadlet_policy_set_drift(smod):
    """TV-SM-15: G5 BLOCKED when quadlet and policy iterate different sets."""
    policy = smod.PolicyInventoryView(
        schema_version="wakir.cosign-policy.phase-3b/1",
        carrier_expected_image_digest=_real_digest(),
        binary_names=smod.TAG45_CANONICAL_INVENTORY,
    )
    quadlet = smod.QuadletInstallerView(
        binary_names=smod.TAG45_CANONICAL_INVENTORY[:14],
    )
    result = smod.evaluate_gate_g5_cross_substrate_parity(policy, quadlet)
    assert result.gate_id == "G5"
    assert result.verdict == "BLOCKED"
    assert "parity drift" in result.summary


def test_tv_sm_16_g6_green_on_known_required_check_names(smod):
    """TV-SM-16: G6 GREEN — required-status-check names are non-empty."""
    result = smod.evaluate_gate_g6_required_check_names_known()
    assert result.gate_id == "G6"
    assert result.verdict == "GREEN"
    assert all(n.strip() for n in smod.STRICT_MODE_REQUIRED_CHECKS)


# ---------------------------------------------------------------------------
# Aggregate + rendering tests
# ---------------------------------------------------------------------------


def test_tv_sm_17_aggregate_verdict_precedence(smod):
    """TV-SM-17: BLOCKED > NOT-CHECKED > GREEN."""
    g_green = smod.GateResult(gate_id="G1", verdict="GREEN", summary="ok")
    g_not_checked = smod.GateResult(gate_id="G2", verdict="NOT-CHECKED", summary="nc")
    g_blocked = smod.GateResult(gate_id="G3", verdict="BLOCKED", summary="blk")

    # All-GREEN -> GREEN
    assert smod.aggregate_run_verdict([g_green, g_green, g_green]) == "GREEN"
    # GREEN + NOT-CHECKED -> NOT-CHECKED
    assert smod.aggregate_run_verdict([g_green, g_not_checked, g_green]) == "NOT-CHECKED"
    # GREEN + NOT-CHECKED + BLOCKED -> BLOCKED
    assert smod.aggregate_run_verdict([g_green, g_not_checked, g_blocked]) == "BLOCKED"
    # GREEN + BLOCKED -> BLOCKED (no NOT-CHECKED needed)
    assert smod.aggregate_run_verdict([g_green, g_blocked]) == "BLOCKED"


def test_tv_sm_18_markdown_summary_contains_all_six_gates(smod):
    """TV-SM-18: render_markdown_summary contains all six gate rows."""
    gates = tuple(
        smod.GateResult(gate_id=gid, verdict="GREEN", summary=f"{gid} ok")
        for gid in ("G1", "G2", "G3", "G4", "G5", "G6")
    )
    run = smod.ReadinessRun(run_ts=1234.5, aggregate_verdict="GREEN", gate_results=gates)
    md = smod.render_markdown_summary(run)
    for gid in ("G1", "G2", "G3", "G4", "G5", "G6"):
        assert f"| {gid} |" in md, f"row for {gid} missing"
    assert "Aggregate verdict" in md
    assert "strict-flip-ready" in md


def test_tv_sm_19_json_envelope_schema_and_rows(smod):
    """TV-SM-19: envelope_to_json carries schema + run_ts + per-gate rows."""
    gates = (
        smod.GateResult(gate_id="G1", verdict="GREEN", summary="g1 ok"),
        smod.GateResult(gate_id="G2", verdict="BLOCKED", summary="g2 bad", detail="x"),
    )
    run = smod.ReadinessRun(run_ts=42.0, aggregate_verdict="BLOCKED", gate_results=gates)
    js = smod.envelope_to_json(run)
    payload = json.loads(js)
    assert payload["schema"] == "wakir.cosign-strict-mode.readiness-check/1"
    assert payload["run_ts"] == 42.0
    assert payload["aggregate_verdict"] == "BLOCKED"
    assert len(payload["gate_results"]) == 2
    assert payload["gate_results"][0]["gate_id"] == "G1"
    assert payload["gate_results"][1]["detail"] == "x"


# ---------------------------------------------------------------------------
# Tag-55 closeout tests (glob loader + on-disk substrate pins)
# ---------------------------------------------------------------------------


def test_tv_sm_20_glob_loader_returns_none_on_empty(smod, tmp_path):
    """TV-SM-20: glob loader returns None when no Quadlets match."""
    result = smod.load_quadlet_installer_glob(tmp_path, "no-such-*.container")
    assert result is None


def test_tv_sm_21_glob_loader_unions_names_sorted_path(smod, tmp_path):
    """TV-SM-21: glob loader unions binary-names in sorted-path order."""
    # Two synthetic Quadlets — first carries A,B; second carries C.
    (tmp_path / "quadlet").mkdir()
    (tmp_path / "quadlet" / "a.container").write_text(
        "/opt/wakir/bin/wakir-persona-engine-recovery\n"
        "/opt/wakir/bin/wakir-persona-engine-fsm\n"
    )
    (tmp_path / "quadlet" / "b.container").write_text(
        "/opt/wakir/bin/wakir-persona-engine-state-backing\n"
    )
    result = smod.load_quadlet_installer_glob(
        tmp_path, "quadlet/*.container"
    )
    assert result is not None
    # a.container loads first (sorted-path), so its names appear first.
    assert result.binary_names == ("recovery", "fsm", "state-backing")


def test_tv_sm_22_glob_loader_dedupes_across_files(smod, tmp_path):
    """TV-SM-22: glob loader dedupes binary-names across files."""
    (tmp_path / "quadlet").mkdir()
    (tmp_path / "quadlet" / "a.container").write_text(
        "/opt/wakir/bin/wakir-persona-engine-recovery\n"
    )
    (tmp_path / "quadlet" / "b.container").write_text(
        # Same name as a.container; the union should keep one entry.
        "/opt/wakir/bin/wakir-persona-engine-recovery\n"
        "/opt/wakir/bin/wakir-persona-engine-fsm\n"
    )
    result = smod.load_quadlet_installer_glob(
        tmp_path, "quadlet/*.container"
    )
    assert result is not None
    assert result.binary_names == ("recovery", "fsm")


def test_tv_sm_23_welle_quadlets_declare_single_binary(smod):
    """TV-SM-23: each on-disk Welle-N Quadlet declares exactly its
    single welle-suffix binary name (regression pin against accidental
    drift where a sibling-shape Quadlet is copy-paste-edited and ends
    up listing a wrong/extra binary).
    """
    expected = {
        "welle4": "state-backing-welle4",
        "welle5": "fsm-welle5",
        "welle6": "subscribe-loop-welle6",
        "welle7": "recovery-welle7",
    }
    for suffix, binary in expected.items():
        path = _REPO_ROOT / "quadlet" / f"wakir-rust-cli-{suffix}.container"
        assert path.exists(), f"Quadlet missing on disk: {path}"
        text = path.read_text(encoding="utf-8")
        names = smod.quadlet_installer_binary_names_from_text(text)
        # Each welle-Quadlet must reference EXACTLY its single binary
        # (anchor comment + Exec= path both contribute, but dedup
        # collapses to one).
        assert names == (binary,), (
            f"{path.name} declares {names!r}, expected ({binary!r},)"
        )


def test_tv_sm_24_on_disk_policy_carries_canonical_15(smod):
    """TV-SM-24: on-disk policy YAML has canonical 15 in canonical order.

    Reads the real policy file (the script's load_policy_yaml requires
    pyyaml; we keep this test inside the I/O substrate test surface
    because it pins the on-disk substrate that G4 evaluates).
    """
    pytest_yaml = pytest.importorskip("yaml")
    policy_path = _REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
    raw = pytest_yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    view = smod.policy_view_from_raw(raw)
    assert view.binary_names == smod.TAG45_CANONICAL_INVENTORY


def test_tv_sm_25_on_disk_quadlet_glob_unions_to_canonical_15(smod):
    """TV-SM-25: the on-disk Quadlet glob unions to the canonical 15
    binary set (G5 substrate-pin post Tag-55 Welle-4..7 add)."""
    result = smod.load_quadlet_installer_glob(
        _REPO_ROOT, "quadlet/wakir-rust-cli*.container"
    )
    assert result is not None
    assert set(result.binary_names) == set(smod.TAG45_CANONICAL_INVENTORY)
    assert len(result.binary_names) == 15


def test_tv_sm_26_on_disk_last_probe_envelope_present(smod):
    """TV-SM-26: on-disk last-probe-envelope.json parses to a verdict.

    The Tag-55 closeout commits a baseline-mode drift-probe envelope to
    state/cosign-drift/last-probe-envelope.json so G3 evaluates against
    a real on-disk envelope rather than NOT-CHECKED.
    """
    envelope_path = (
        _REPO_ROOT / "state" / "cosign-drift" / "last-probe-envelope.json"
    )
    assert envelope_path.exists(), (
        f"missing on-disk last-probe-envelope.json at {envelope_path}"
    )
    raw = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert "aggregate_verdict" in raw
    assert raw["aggregate_verdict"] in (
        "GREEN",
        "NOT-CHECKED",
        "DRIFT-WORKFLOW-PATH",
        "DRIFT-CERTIFICATE-ISSUER",
        "DRIFT-OIDC-IDENTITY",
        "DRIFT-TRUST-ROOT",
    )
    # Tag-55 closeout committed a GREEN baseline envelope so G3 flips
    # GREEN immediately on a fresh checkout.
    assert raw["aggregate_verdict"] == "GREEN"


def test_tv_sm_27_g5_green_on_full_canonical_set(smod):
    """TV-SM-27: G5 GREEN on a quadlet view that carries the canonical
    15 binary set (set-equality, order-insensitive)."""
    policy = smod.PolicyInventoryView(
        schema_version="wakir.cosign-policy.phase-3b/1",
        carrier_expected_image_digest=_real_digest(),
        binary_names=smod.TAG45_CANONICAL_INVENTORY,
    )
    # Reverse-order quadlet view -- set-equality so order does NOT
    # matter for the G5 verdict.
    quadlet = smod.QuadletInstallerView(
        binary_names=tuple(reversed(smod.TAG45_CANONICAL_INVENTORY)),
    )
    result = smod.evaluate_gate_g5_cross_substrate_parity(policy, quadlet)
    assert result.gate_id == "G5"
    assert result.verdict == "GREEN"


def test_tv_sm_28_real_digest_regex_strictness(smod):
    """TV-SM-28: REAL_DIGEST_RE only accepts well-formed sha256 + 64 hex."""
    valid = "sha256:" + "a" * 64
    assert smod.REAL_DIGEST_RE.match(valid)
    # Too short
    assert not smod.REAL_DIGEST_RE.match("sha256:abc")
    # Wrong algo prefix
    assert not smod.REAL_DIGEST_RE.match("sha512:" + "a" * 64)
    # Uppercase rejected (canonical sha256 is lowercase)
    assert not smod.REAL_DIGEST_RE.match("sha256:" + "A" * 64)
    # Placeholder rejected
    assert not smod.REAL_DIGEST_RE.match(smod.PLACEHOLDER_DIGEST)
