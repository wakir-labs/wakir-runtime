#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for
``scripts/observability/cosign-keyless-oidc-drift-probe.py``.

Tag-47 Kai — Cosign-Keyless-OIDC-Drift-Probe.

Coverage targets the pure-function core (no live cosign / network).
The 16 tests in this file cover:

  * 4 trust-root verdict invariants (TV-DR-01 .. TV-DR-04)
  * 5 per-binary OIDC verdict invariants (TV-OI-01 .. TV-OI-05)
  * 3 aggregate-verdict invariants (TV-AG-01 .. TV-AG-03)
  * 3 rendering invariants (TV-RD-01 .. TV-RD-03)
  * 1 substrate-shape invariant (TV-SU-01)

Total: 16 hermetic invariants — comfortably above the >=12 target.

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 these tests
NEVER call cosign / crane / podman / network. They construct
in-memory PolicySnapshot + snapshot fixtures and assert the
verdict-axis transitions.

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the probe module from its hyphenated path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_PROBE_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "cosign-keyless-oidc-drift-probe.py"
)

_spec = importlib.util.spec_from_file_location(
    "cosign_keyless_oidc_drift_probe", str(_PROBE_PATH)
)
assert _spec is not None
assert _spec.loader is not None
probe = importlib.util.module_from_spec(_spec)
sys.modules["cosign_keyless_oidc_drift_probe"] = probe
_spec.loader.exec_module(probe)


# ---------------------------------------------------------------------------
# Fixture helpers.
# ---------------------------------------------------------------------------


def _mk_policy(*, names=None, workflow_by_name=None):
    if names is None:
        names = probe.TAG45_BINARY_INVENTORY
    if workflow_by_name is None:
        workflow_by_name = {
            n: ".github/workflows/build-wakir-persona-engine.yml"
            for n in names
        }
    return probe.PolicySnapshot(
        schema_version="wakir.cosign-policy.phase-3b/1",
        certificate_identity_regexp=(
            r"https://github\.com/wakir-labs/wakir-runtime/"
        ),
        certificate_oidc_issuer=probe.CANONICAL_OIDC_ISSUER,
        binary_names=tuple(names),
        binary_to_build_workflow=dict(workflow_by_name),
    )


def _mk_trust_root(
    *,
    cosign_action="sigstore/cosign-installer@v3",
    semver_major="v3",
    fulcio_sha="a" * 64,
    rekor_shard="rekor.sigstore.dev-2022",
):
    return probe.TrustRootSnapshot(
        cosign_installer_action=cosign_action,
        cosign_installer_semver_major=semver_major,
        fulcio_root_ca_sha256=fulcio_sha,
        rekor_log_shard_id=rekor_shard,
    )


def _mk_oidc_snapshot(name, *, identity=None, issuer=None, wf_path=None):
    if identity is None:
        identity = (
            f"{probe.CANONICAL_IDENTITY_PREFIX}"
            f".github/workflows/build-wakir-persona-engine.yml"
            f"@refs/heads/main"
        )
    if issuer is None:
        issuer = probe.CANONICAL_OIDC_ISSUER
    if wf_path is None:
        wf_path = ".github/workflows/build-wakir-persona-engine.yml"
    return probe.BinaryOIDCSnapshot(
        binary_name=name,
        certificate_identity=identity,
        certificate_oidc_issuer=issuer,
        build_workflow_path=wf_path,
    )


# ---------------------------------------------------------------------------
# TV-DR — Trust-Root drift verdict invariants
# ---------------------------------------------------------------------------


def test_tv_dr_01_trust_root_green_when_identical():
    """TV-DR-01: identical pinned + current => GREEN."""
    pinned = _mk_trust_root()
    current = _mk_trust_root()
    verdict, reason = probe.evaluate_trust_root(pinned, current)
    assert verdict == "GREEN"
    assert "consistent" in reason


def test_tv_dr_02_trust_root_drift_on_cosign_installer_rollover():
    """TV-DR-02: installer SemVer-major delta => DRIFT-TRUST-ROOT."""
    pinned = _mk_trust_root(semver_major="v3")
    current = _mk_trust_root(
        cosign_action="sigstore/cosign-installer@v4",
        semver_major="v4",
    )
    verdict, reason = probe.evaluate_trust_root(pinned, current)
    assert verdict == "DRIFT-TRUST-ROOT"
    assert "cosign_installer_semver_major" in reason
    assert "v3" in reason and "v4" in reason


def test_tv_dr_03_trust_root_drift_on_fulcio_rotation():
    """TV-DR-03: Fulcio CA SHA-256 delta => DRIFT-TRUST-ROOT."""
    pinned = _mk_trust_root(fulcio_sha="a" * 64)
    current = _mk_trust_root(fulcio_sha="b" * 64)
    verdict, reason = probe.evaluate_trust_root(pinned, current)
    assert verdict == "DRIFT-TRUST-ROOT"
    assert "fulcio_root_ca_sha256" in reason


def test_tv_dr_04_trust_root_none_current_is_not_drift():
    """TV-DR-04: None current_trust_root => GREEN with 'not probed'."""
    pinned = _mk_trust_root()
    verdict, reason = probe.evaluate_trust_root(pinned, None)
    assert verdict == "GREEN"
    assert "not probed" in reason


# ---------------------------------------------------------------------------
# TV-OI — Per-binary OIDC drift verdict invariants
# ---------------------------------------------------------------------------


def test_tv_oi_01_binary_oidc_green_baseline():
    """TV-OI-01: well-formed snapshot matches policy => GREEN."""
    policy = _mk_policy()
    snap = _mk_oidc_snapshot("recovery")
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    v = probe.evaluate_binary_oidc(policy, snap, workflows)
    assert v.binary_name == "recovery"
    assert v.verdict == "GREEN"
    assert v.reason == ""


def test_tv_oi_02_binary_oidc_drift_on_issuer_mismatch():
    """TV-OI-02: issuer URL mismatch => DRIFT-CERTIFICATE-ISSUER."""
    policy = _mk_policy()
    snap = _mk_oidc_snapshot(
        "fsm",
        issuer="https://malicious-mirror.example/oidc",
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    v = probe.evaluate_binary_oidc(policy, snap, workflows)
    assert v.verdict == "DRIFT-CERTIFICATE-ISSUER"
    assert "malicious-mirror" in v.reason


def test_tv_oi_03_binary_oidc_drift_on_identity_regexp_miss():
    """TV-OI-03: identity URL does not match regexp => DRIFT-OIDC-IDENTITY."""
    policy = _mk_policy()
    snap = _mk_oidc_snapshot(
        "v907-verify",
        identity="https://github.com/some-other-org/some-repo/wf@main",
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    v = probe.evaluate_binary_oidc(policy, snap, workflows)
    assert v.verdict == "DRIFT-OIDC-IDENTITY"
    assert "some-other-org" in v.reason


def test_tv_oi_04_binary_oidc_drift_on_missing_workflow():
    """TV-OI-04: build_workflow path absent on disk => DRIFT-WORKFLOW-PATH."""
    policy = _mk_policy(
        workflow_by_name={"recovery": ".github/workflows/does-not-exist.yml"}
    )
    snap = _mk_oidc_snapshot("recovery")
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    v = probe.evaluate_binary_oidc(policy, snap, workflows)
    assert v.verdict == "DRIFT-WORKFLOW-PATH"
    assert "does-not-exist" in v.reason


def test_tv_oi_05_workflow_drift_severity_beats_issuer_drift():
    """TV-OI-05: severity ordering — substrate-fixable wins over chain-issue.

    A binary with BOTH a missing workflow AND a wrong issuer must
    report DRIFT-WORKFLOW-PATH (the substrate-side issue), not
    DRIFT-CERTIFICATE-ISSUER (the chain-of-trust issue). This is the
    documented severity ordering in the docstring.
    """
    policy = _mk_policy(
        workflow_by_name={"fsm": ".github/workflows/does-not-exist.yml"}
    )
    snap = _mk_oidc_snapshot(
        "fsm",
        issuer="https://malicious-mirror.example/oidc",
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    v = probe.evaluate_binary_oidc(policy, snap, workflows)
    assert v.verdict == "DRIFT-WORKFLOW-PATH"


# ---------------------------------------------------------------------------
# TV-AG — Aggregate verdict invariants
# ---------------------------------------------------------------------------


def test_tv_ag_01_aggregate_all_green_when_clean():
    """TV-AG-01: clean snapshot for all 15 binaries => aggregate GREEN."""
    policy = _mk_policy()
    pinned_tr = _mk_trust_root()
    snapshots = tuple(
        _mk_oidc_snapshot(n) for n in probe.TAG45_BINARY_INVENTORY
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    run = probe.evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=pinned_tr,
        per_binary_snapshots=snapshots,
        workflow_paths_on_disk=workflows,
        probe_ts=1718000000.0,
    )
    assert run.aggregate_verdict == "GREEN"
    assert len(run.per_binary) == 15
    assert all(v.verdict == "GREEN" for v in run.per_binary)
    assert run.trust_root_axis == "GREEN"


def test_tv_ag_02_aggregate_worst_of_all_with_partial_snapshot():
    """TV-AG-02: missing snapshot for some binaries => NOT-CHECKED rows,
    aggregate worst-of-all promotes correctly."""
    policy = _mk_policy()
    pinned_tr = _mk_trust_root()
    # Only the first 3 binaries get a snapshot; the rest become NOT-CHECKED.
    snapshots = (
        _mk_oidc_snapshot("recovery"),
        _mk_oidc_snapshot("state-backing"),
        _mk_oidc_snapshot("fsm"),
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    run = probe.evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=pinned_tr,
        per_binary_snapshots=snapshots,
        workflow_paths_on_disk=workflows,
        probe_ts=1718000000.0,
    )
    assert run.aggregate_verdict == "NOT-CHECKED"
    not_checked = [v for v in run.per_binary if v.verdict == "NOT-CHECKED"]
    assert len(not_checked) == 12


def test_tv_ag_03_aggregate_trust_root_drift_wins_over_oidc_drift():
    """TV-AG-03: trust-root drift severity > OIDC drift severity."""
    policy = _mk_policy()
    pinned_tr = _mk_trust_root(semver_major="v3")
    drifted_tr = _mk_trust_root(
        cosign_action="sigstore/cosign-installer@v4",
        semver_major="v4",
    )
    # One binary has an OIDC-issuer drift.
    snapshots = (
        _mk_oidc_snapshot(
            "recovery",
            issuer="https://malicious-mirror.example/oidc",
        ),
    ) + tuple(
        _mk_oidc_snapshot(n)
        for n in probe.TAG45_BINARY_INVENTORY[1:]
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    run = probe.evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=drifted_tr,
        per_binary_snapshots=snapshots,
        workflow_paths_on_disk=workflows,
        probe_ts=1718000000.0,
    )
    # Trust-root has higher severity than DRIFT-CERTIFICATE-ISSUER.
    assert run.aggregate_verdict == "DRIFT-TRUST-ROOT"
    assert run.trust_root_axis == "DRIFT-TRUST-ROOT"


# ---------------------------------------------------------------------------
# TV-RD — Rendering invariants
# ---------------------------------------------------------------------------


def test_tv_rd_01_json_envelope_is_stable_and_sorted():
    """TV-RD-01: JSON envelope is deterministic + parseable."""
    policy = _mk_policy()
    pinned_tr = _mk_trust_root()
    snapshots = tuple(
        _mk_oidc_snapshot(n) for n in probe.TAG45_BINARY_INVENTORY
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    run = probe.evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=pinned_tr,
        per_binary_snapshots=snapshots,
        workflow_paths_on_disk=workflows,
        probe_ts=1718000000.0,
    )
    raw = probe.render_json_envelope(run)
    parsed = json.loads(raw)
    assert parsed["schema"] == "wakir.observability.cosign-drift-probe/1"
    assert parsed["aggregate_verdict"] == "GREEN"
    assert parsed["probe_ts"] == 1718000000
    assert len(parsed["per_binary"]) == 15
    # Deterministic: re-render produces the same bytes.
    raw_2 = probe.render_json_envelope(run)
    assert raw == raw_2


def test_tv_rd_02_prometheus_textfile_has_expected_metric_names():
    """TV-RD-02: Prometheus textfile carries the three canonical metrics."""
    policy = _mk_policy()
    pinned_tr = _mk_trust_root()
    snapshots = tuple(
        _mk_oidc_snapshot(n) for n in probe.TAG45_BINARY_INVENTORY
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    run = probe.evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=pinned_tr,
        per_binary_snapshots=snapshots,
        workflow_paths_on_disk=workflows,
        probe_ts=1718000000.0,
    )
    text = probe.render_prometheus_textfile(run)
    assert "wakir_cosign_drift_probe_aggregate " in text
    assert "wakir_cosign_drift_probe_per_binary{" in text
    assert "wakir_cosign_drift_probe_trust_root " in text
    # All 15 binaries are exposed as gauge rows.
    for n in probe.TAG45_BINARY_INVENTORY:
        assert f'binary="{n}"' in text


def test_tv_rd_03_markdown_summary_shows_action_section_only_when_drift():
    """TV-RD-03: 'Operator action' section appears on drift, not on GREEN."""
    policy = _mk_policy()
    pinned_tr = _mk_trust_root()

    # GREEN case: no 'Operator action' section.
    snapshots_green = tuple(
        _mk_oidc_snapshot(n) for n in probe.TAG45_BINARY_INVENTORY
    )
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    run_green = probe.evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=pinned_tr,
        per_binary_snapshots=snapshots_green,
        workflow_paths_on_disk=workflows,
        probe_ts=1718000000.0,
    )
    md_green = probe.render_markdown_summary(run_green)
    assert "Operator action" not in md_green
    assert "GREEN" in md_green

    # DRIFT case: 'Operator action' section present.
    drifted_tr = _mk_trust_root(fulcio_sha="b" * 64)
    run_drift = probe.evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=drifted_tr,
        per_binary_snapshots=snapshots_green,
        workflow_paths_on_disk=workflows,
        probe_ts=1718000000.0,
    )
    md_drift = probe.render_markdown_summary(run_drift)
    assert "Operator action" in md_drift
    assert "DRIFT-TRUST-ROOT" in md_drift


# ---------------------------------------------------------------------------
# TV-SU — Substrate-shape invariant
# ---------------------------------------------------------------------------


def test_tv_su_01_policy_from_raw_handles_tag45_15_binary_shape():
    """TV-SU-01: policy_from_raw parses the Tag-45 15-binary inventory."""
    raw = {
        "schema_version": "wakir.cosign-policy.phase-3b/1",
        "policy": {
            "certificate_identity_regexp": (
                r"https://github\.com/wakir-labs/wakir-runtime/"
            ),
            "certificate_oidc_issuer": probe.CANONICAL_OIDC_ISSUER,
            "carrier_image": {
                "build_workflow": (
                    ".github/workflows/build-wakir-persona-engine.yml"
                ),
            },
        },
        "binaries": [
            {"name": n} for n in probe.TAG45_BINARY_INVENTORY
        ],
    }
    snap = probe.policy_from_raw(raw)
    assert snap.schema_version == "wakir.cosign-policy.phase-3b/1"
    assert snap.binary_names == probe.TAG45_BINARY_INVENTORY
    assert len(snap.binary_to_build_workflow) == 15
    # All 15 binaries inherit the carrier-image-level workflow.
    for n in probe.TAG45_BINARY_INVENTORY:
        assert (
            snap.binary_to_build_workflow[n]
            == ".github/workflows/build-wakir-persona-engine.yml"
        )


# ---------------------------------------------------------------------------
# Bonus: synthesise_baseline_snapshot round-trip
# ---------------------------------------------------------------------------


def test_baseline_snapshot_round_trip_is_all_green():
    """A synthesised baseline snapshot, fed back into evaluate_run,
    produces an all-GREEN aggregate. This is the daily CI-workflow's
    substrate-consistency probe contract."""
    policy = _mk_policy()
    pinned_tr = _mk_trust_root()
    workflows = (".github/workflows/build-wakir-persona-engine.yml",)
    raw_snap = probe.synthesise_baseline_snapshot(
        policy, pinned_tr, workflows
    )
    cur_tr = probe.trust_root_from_raw(raw_snap)
    per_binary = probe.binary_oidc_snapshots_from_raw(raw_snap)
    run = probe.evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=cur_tr,
        per_binary_snapshots=per_binary,
        workflow_paths_on_disk=workflows,
        probe_ts=1718000000.0,
    )
    assert run.aggregate_verdict == "GREEN"
    assert run.trust_root_axis == "GREEN"
    assert all(v.verdict == "GREEN" for v in run.per_binary)
    assert len(run.per_binary) == 15
