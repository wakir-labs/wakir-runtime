#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cosign-Keyless-OIDC-Drift-Probe (Tag-47, Kai).

Context
-------

Tag-45 PR #294 (Quadlet+Cosign 15-Binary substrate refresh) closed
the Phase-3a-Foundation 15-module sweep in lock-step between the
``policies/cosign-policy-phase-3b.yaml`` 15-binary inventory and the
``quadlet/wakir-rust-cli.container`` 11-carrier-image installer.
Tag-46 PR #298 added the substrate-layer A6 coverage matrix
(``tests/infra/test_cosign_drift_coverage_a6.py``, 17 hermetic
invariants TV-A6-01..20). Both tests pin the static substrate shape
at the moment the policy YAML is read from disk.

What neither pins is the *time-axis* — the Sigstore Trust-Root and
the GitHub-Actions OIDC identity bound to the keyless-cosign chain
are externally-controlled artefacts that can change without our
substrate noticing:

  * The Sigstore Trust-Root (Fulcio CA, Rekor transparency-log,
    cosign-installer SemVer-major tag pin) is published by the
    upstream Sigstore project. Re-tags, action-runner-version
    rollovers, or transparency-log roots changing are silent from
    our substrate's POV.
  * The GitHub-Actions OIDC identity binding
    (``certificate_identity_regexp`` + ``certificate_oidc_issuer``)
    is pinned in our policy file, but the upstream OIDC issuer URL
    (``token.actions.githubusercontent.com``) and the per-workflow
    identity URL convention can both shift if GitHub re-pivots the
    Actions OIDC schema (cf. the 2023 ``id-token: write`` schema
    extension).

This probe tracks both axes daily and emits a per-binary drift
verdict so an operator notices upstream shifts within ~24h instead
of at the next cosign-verify failure.

Verdict-axis
------------

Each of the 15 binaries in the policy gets one verdict per probe run:

  * ``GREEN``                     — policy + snapshot consistent.
  * ``DRIFT-TRUST-ROOT``          — Sigstore Trust-Root delta vs.
                                     the pinned baseline (cosign
                                     installer SemVer-major tag,
                                     Fulcio CA cert SHA, Rekor
                                     transparency-log shard ID).
  * ``DRIFT-OIDC-IDENTITY``       — the per-binary build-workflow
                                     OIDC subject claim no longer
                                     matches the
                                     ``certificate_identity_regexp``
                                     pinned in the policy.
  * ``DRIFT-CERTIFICATE-ISSUER``  — the OIDC issuer URL in the
                                     snapshot deviates from
                                     ``certificate_oidc_issuer``.
  * ``DRIFT-WORKFLOW-PATH``       — the build-workflow file
                                     referenced by the policy entry
                                     no longer exists OR was
                                     renamed (substrate-side drift
                                     against the Sigstore-side
                                     identity claim).
  * ``NOT-CHECKED``               — snapshot data missing for this
                                     binary (e.g. probe ran in
                                     sandbox-dry-run mode and only
                                     a subset of axes were probed).

The aggregate verdict for the run is the worst-of-all-binaries
verdict in the ordering GREEN < NOT-CHECKED < DRIFT-WORKFLOW-PATH <
DRIFT-CERTIFICATE-ISSUER < DRIFT-OIDC-IDENTITY < DRIFT-TRUST-ROOT.

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 this script
NEVER calls cosign / crane / skopeo / podman against ``ghcr.io``.
It reads the policy YAML from disk + consumes a snapshot JSON that
was either:

  1. ``--mode=fixture`` — a pre-computed snapshot fixture file
     (the hermetic-test mode).
  2. ``--mode=baseline`` — the in-repo baseline snapshot at
     ``state/cosign-drift/baseline-snapshot.json`` (the daily
     CI-workflow checks the baseline against itself for substrate
     consistency; an Operator-Hand step refreshes the baseline
     against live cosign on a host with registry egress).

The "live cosign on a host with registry egress" step lives in
``docs/operations/cosign-keyless-oidc-drift-probe.md`` (Operator-
Hand recipe) — this script is hermetic-only.

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure-
function, hermetic-test target. The I/O wrappers
(``load_policy_yaml``, ``load_snapshot_json``,
``write_textfile``, ``write_json_envelope``,
``write_markdown_summary``) are isolated at the bottom.

Anchors
-------

  * Tag-45 PR #294 — Quadlet+Cosign 15-Binary substrate refresh.
  * Tag-46 PR #298 — A6 substrate-layer coverage matrix (17 hermetic
    invariants).
  * ADR-0066 §AR-Hand-Gate — pre-cutover stability over ~3-day
    window is AR-Hand-Sign-Off pre-condition.
  * feedback_sandbox_host_trennung.md — no live registry I/O from
    sandbox.
  * Sibling-script:
    ``scripts/observability/pre-cutover-probe-failure-rate-tracker.py``
    (Tag-42 Noa) — same Prometheus-textfile + fixture-mode pattern.
  * Sibling-test:
    ``tests/infra/test_cosign_drift_coverage_a6.py`` (Tag-46) — the
    substrate-layer A6 coverage matrix this probe extends along
    the time-axis.

Author: Kai Hoffmann (Dev-Engineering-3 / Container-Orchestration)
Tag: 47 (KW-22)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Canonical inventory order — must match the Tag-45 Cosign-Policy
#: 15-binary inventory (``policies/cosign-policy-phase-3b.yaml``)
#: byte-for-byte. The probe consumes the policy at runtime, but the
#: order constant exists so dashboards + textfile output is stable
#: across runs even when the policy is re-ordered (the policy enforces
#: chronological landing order; the probe enforces the same).
TAG45_BINARY_INVENTORY: Tuple[str, ...] = (
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

#: Verdict severity ordering (lowest -> highest).
VERDICT_SEVERITY: Tuple[str, ...] = (
    "GREEN",
    "NOT-CHECKED",
    "DRIFT-WORKFLOW-PATH",
    "DRIFT-CERTIFICATE-ISSUER",
    "DRIFT-OIDC-IDENTITY",
    "DRIFT-TRUST-ROOT",
)

#: Canonical GitHub-Actions OIDC issuer URL (anti-Fulcio-mirror-drift).
CANONICAL_OIDC_ISSUER: str = "https://token.actions.githubusercontent.com"

#: Canonical cosign-installer action source (anti-third-party-fork).
CANONICAL_COSIGN_INSTALLER: str = "sigstore/cosign-installer"

#: Canonical certificate-identity prefix (anti-wildcard-org-drift).
CANONICAL_IDENTITY_PREFIX: str = "https://github.com/wakir-labs/wakir-runtime/"


# ---------------------------------------------------------------------------
# Dataclasses (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrustRootSnapshot:
    """Snapshot of the Sigstore Trust-Root at the time of probe-run.

    The four axes pin the upstream substrate that a keyless-cosign
    verify call depends on. Drift on any of the four = re-verify
    every signature before trusting the run.
    """

    cosign_installer_action: str
    """e.g. 'sigstore/cosign-installer@v3' — anti-third-party-fork."""

    cosign_installer_semver_major: str
    """e.g. 'v3' — anti-silent-rollover from v3 to v4."""

    fulcio_root_ca_sha256: str
    """SHA-256 of the Fulcio root CA cert — anti-CA-rotation."""

    rekor_log_shard_id: str
    """Rekor transparency-log shard ID — anti-shard-cut-over."""


@dataclass(frozen=True)
class BinaryOIDCSnapshot:
    """Per-binary keyless-OIDC identity snapshot at probe time.

    The three axes pin the identity claim that a cosign-verify call
    would assert against. Drift on any of the three = the binary's
    signing chain no longer matches the pinned policy.
    """

    binary_name: str
    """One of TAG45_BINARY_INVENTORY."""

    certificate_identity: str
    """The full OIDC subject URL (workflow run path) the binary's
    keyless cert was issued for. Must start with
    CANONICAL_IDENTITY_PREFIX."""

    certificate_oidc_issuer: str
    """The OIDC issuer URL. Must equal CANONICAL_OIDC_ISSUER."""

    build_workflow_path: str
    """The on-disk workflow file path the policy references for this
    binary (e.g. '.github/workflows/build-wakir-persona-engine.yml').
    The probe asserts the file exists on the substrate side."""


@dataclass(frozen=True)
class PolicySnapshot:
    """The in-repo policy substrate at the time of probe-run.

    Decoupled from BinaryOIDCSnapshot so the probe can compare the
    pinned policy (left) against the snapshot of the live keyless-
    chain (right) without coupling the two reads.
    """

    schema_version: str
    certificate_identity_regexp: str
    certificate_oidc_issuer: str
    binary_names: Tuple[str, ...]
    binary_to_build_workflow: Mapping[str, str]


@dataclass(frozen=True)
class BinaryDriftVerdict:
    """The per-binary verdict the probe emits."""

    binary_name: str
    verdict: str
    reason: str = ""


@dataclass(frozen=True)
class ProbeRun:
    """The full envelope the probe emits per run."""

    probe_ts: float
    aggregate_verdict: str
    per_binary: Tuple[BinaryDriftVerdict, ...]
    trust_root_axis: str
    """Aggregate trust-root verdict: GREEN / DRIFT-TRUST-ROOT."""
    trust_root_reason: str = ""


# ---------------------------------------------------------------------------
# Pure functions: policy + snapshot parsing
# ---------------------------------------------------------------------------


def policy_from_raw(raw_policy: Mapping[str, object]) -> PolicySnapshot:
    """Build a PolicySnapshot from a raw YAML-parsed dict.

    Pure: no I/O. The caller decides whether the dict came from
    ``yaml.safe_load(open(path))`` (live mode) or a test fixture
    (hermetic mode).
    """
    schema = str(raw_policy.get("schema_version", ""))
    policy_blk = raw_policy.get("policy", {})
    if not isinstance(policy_blk, Mapping):
        raise ValueError("policy block missing or malformed")

    cert_id_regexp = str(policy_blk.get("certificate_identity_regexp", ""))
    cert_issuer = str(policy_blk.get("certificate_oidc_issuer", ""))

    binaries = raw_policy.get("binaries", [])
    if not isinstance(binaries, Sequence):
        raise ValueError("binaries block missing or malformed")

    names: List[str] = []
    workflow_by_name: Dict[str, str] = {}
    for entry in binaries:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", ""))
        if not name:
            continue
        names.append(name)
        # The policy YAML carries a per-binary 'build_workflow' OR
        # falls back to the carrier_image-level workflow. Tag-45
        # convention: ALL 15 binaries ship in the same carrier image,
        # so the workflow is identical for all (the
        # build-wakir-persona-engine.yml). We accept either schema.
        wf = entry.get("build_workflow")
        if not wf:
            carrier = policy_blk.get("carrier_image", {})
            if isinstance(carrier, Mapping):
                wf = carrier.get("build_workflow", "")
        workflow_by_name[name] = str(wf or "")

    return PolicySnapshot(
        schema_version=schema,
        certificate_identity_regexp=cert_id_regexp,
        certificate_oidc_issuer=cert_issuer,
        binary_names=tuple(names),
        binary_to_build_workflow=workflow_by_name,
    )


def trust_root_from_raw(
    raw: Mapping[str, object],
) -> Optional[TrustRootSnapshot]:
    """Build a TrustRootSnapshot from a raw snapshot dict.

    Returns None if the snapshot dict has no trust_root block.
    """
    block = raw.get("trust_root")
    if not isinstance(block, Mapping):
        return None
    return TrustRootSnapshot(
        cosign_installer_action=str(block.get("cosign_installer_action", "")),
        cosign_installer_semver_major=str(
            block.get("cosign_installer_semver_major", "")
        ),
        fulcio_root_ca_sha256=str(block.get("fulcio_root_ca_sha256", "")),
        rekor_log_shard_id=str(block.get("rekor_log_shard_id", "")),
    )


def binary_oidc_snapshots_from_raw(
    raw: Mapping[str, object],
) -> Tuple[BinaryOIDCSnapshot, ...]:
    """Build the per-binary OIDC-snapshot list from raw dict."""
    block = raw.get("per_binary_oidc", [])
    if not isinstance(block, Sequence):
        return ()
    out: List[BinaryOIDCSnapshot] = []
    for entry in block:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("binary_name", ""))
        if not name:
            continue
        out.append(
            BinaryOIDCSnapshot(
                binary_name=name,
                certificate_identity=str(entry.get("certificate_identity", "")),
                certificate_oidc_issuer=str(
                    entry.get("certificate_oidc_issuer", "")
                ),
                build_workflow_path=str(entry.get("build_workflow_path", "")),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Pure functions: drift evaluation
# ---------------------------------------------------------------------------


def evaluate_trust_root(
    pinned: TrustRootSnapshot,
    current: Optional[TrustRootSnapshot],
) -> Tuple[str, str]:
    """Compare pinned vs. current Trust-Root.

    Returns (verdict, reason). Verdict is one of
    "GREEN" or "DRIFT-TRUST-ROOT".

    A None ``current`` is NOT a drift — it means trust-root data
    was not captured this run. The caller flags the affected
    binaries as NOT-CHECKED separately.
    """
    if current is None:
        return ("GREEN", "trust-root axis not probed this run")

    diffs: List[str] = []
    if current.cosign_installer_action != pinned.cosign_installer_action:
        diffs.append(
            f"cosign_installer_action: {pinned.cosign_installer_action} -> "
            f"{current.cosign_installer_action}"
        )
    if (
        current.cosign_installer_semver_major
        != pinned.cosign_installer_semver_major
    ):
        diffs.append(
            f"cosign_installer_semver_major: "
            f"{pinned.cosign_installer_semver_major} -> "
            f"{current.cosign_installer_semver_major}"
        )
    if current.fulcio_root_ca_sha256 != pinned.fulcio_root_ca_sha256:
        diffs.append(
            f"fulcio_root_ca_sha256: {pinned.fulcio_root_ca_sha256} -> "
            f"{current.fulcio_root_ca_sha256}"
        )
    if current.rekor_log_shard_id != pinned.rekor_log_shard_id:
        diffs.append(
            f"rekor_log_shard_id: {pinned.rekor_log_shard_id} -> "
            f"{current.rekor_log_shard_id}"
        )

    if diffs:
        return ("DRIFT-TRUST-ROOT", "; ".join(diffs))
    return ("GREEN", "all four trust-root axes consistent")


def evaluate_binary_oidc(
    policy: PolicySnapshot,
    snapshot: BinaryOIDCSnapshot,
    workflow_paths_on_disk: Sequence[str],
) -> BinaryDriftVerdict:
    """Evaluate a single binary's OIDC identity drift.

    The four sub-axes (in severity order) are:
      1. DRIFT-WORKFLOW-PATH      — pinned workflow file missing on disk
      2. DRIFT-CERTIFICATE-ISSUER — issuer URL mismatch
      3. DRIFT-OIDC-IDENTITY      — identity regexp mismatch
      4. (else)                   — GREEN

    The lowest-numbered failing sub-axis wins (the most-substrate-
    side failure first; the upstream-identity-side failure last —
    so an operator reading the verdict sees substrate-fixable
    issues before chain-of-trust issues).
    """
    name = snapshot.binary_name

    # Sub-axis 1: workflow path
    expected_wf = policy.binary_to_build_workflow.get(name, "")
    if expected_wf and expected_wf not in workflow_paths_on_disk:
        return BinaryDriftVerdict(
            binary_name=name,
            verdict="DRIFT-WORKFLOW-PATH",
            reason=(
                f"policy points at build_workflow={expected_wf!r} "
                f"but no such path exists on disk"
            ),
        )

    # Sub-axis 2: issuer
    if snapshot.certificate_oidc_issuer != policy.certificate_oidc_issuer:
        return BinaryDriftVerdict(
            binary_name=name,
            verdict="DRIFT-CERTIFICATE-ISSUER",
            reason=(
                f"snapshot issuer={snapshot.certificate_oidc_issuer!r} "
                f"!= pinned issuer={policy.certificate_oidc_issuer!r}"
            ),
        )

    # Sub-axis 3: identity regexp match
    try:
        regexp = re.compile(policy.certificate_identity_regexp)
    except re.error as exc:
        return BinaryDriftVerdict(
            binary_name=name,
            verdict="DRIFT-OIDC-IDENTITY",
            reason=f"policy identity regexp not compilable: {exc}",
        )
    if not regexp.match(snapshot.certificate_identity):
        return BinaryDriftVerdict(
            binary_name=name,
            verdict="DRIFT-OIDC-IDENTITY",
            reason=(
                f"snapshot identity={snapshot.certificate_identity!r} "
                f"does not match pinned regexp="
                f"{policy.certificate_identity_regexp!r}"
            ),
        )

    return BinaryDriftVerdict(binary_name=name, verdict="GREEN", reason="")


def evaluate_run(
    policy: PolicySnapshot,
    pinned_trust_root: TrustRootSnapshot,
    current_trust_root: Optional[TrustRootSnapshot],
    per_binary_snapshots: Sequence[BinaryOIDCSnapshot],
    workflow_paths_on_disk: Sequence[str],
    *,
    probe_ts: float,
) -> ProbeRun:
    """Top-level evaluator. Pure.

    Builds a ProbeRun envelope by:
      1. Running the trust-root comparison.
      2. Iterating the policy's binary inventory and matching against
         the per-binary snapshots (NOT-CHECKED if a binary has no
         snapshot entry).
      3. Computing the aggregate verdict as worst-of-all.
    """
    tr_verdict, tr_reason = evaluate_trust_root(
        pinned_trust_root, current_trust_root
    )

    snapshot_by_name: Dict[str, BinaryOIDCSnapshot] = {
        s.binary_name: s for s in per_binary_snapshots
    }

    per_binary: List[BinaryDriftVerdict] = []
    for name in policy.binary_names:
        snap = snapshot_by_name.get(name)
        if snap is None:
            per_binary.append(
                BinaryDriftVerdict(
                    binary_name=name,
                    verdict="NOT-CHECKED",
                    reason="snapshot has no entry for this binary",
                )
            )
            continue
        per_binary.append(
            evaluate_binary_oidc(policy, snap, workflow_paths_on_disk)
        )

    # Aggregate: worst-of all per-binary verdicts ∪ trust-root verdict.
    all_verdicts: List[str] = [v.verdict for v in per_binary]
    all_verdicts.append(tr_verdict)
    aggregate = _worst_verdict(all_verdicts)

    return ProbeRun(
        probe_ts=probe_ts,
        aggregate_verdict=aggregate,
        per_binary=tuple(per_binary),
        trust_root_axis=tr_verdict,
        trust_root_reason=tr_reason,
    )


def _worst_verdict(verdicts: Sequence[str]) -> str:
    """Return the verdict with highest severity in VERDICT_SEVERITY."""
    severity = {v: i for i, v in enumerate(VERDICT_SEVERITY)}
    worst = "GREEN"
    worst_i = 0
    for v in verdicts:
        i = severity.get(v, len(VERDICT_SEVERITY))  # unknown == worst
        if i > worst_i:
            worst_i = i
            worst = v
    return worst


# ---------------------------------------------------------------------------
# Pure functions: rendering
# ---------------------------------------------------------------------------


def render_json_envelope(run: ProbeRun) -> str:
    """Render a stable, sorted, deterministic JSON envelope."""
    obj = {
        "schema": "wakir.observability.cosign-drift-probe/1",
        "probe_ts": int(run.probe_ts),
        "aggregate_verdict": run.aggregate_verdict,
        "trust_root_axis": {
            "verdict": run.trust_root_axis,
            "reason": run.trust_root_reason,
        },
        "per_binary": [
            {
                "binary_name": v.binary_name,
                "verdict": v.verdict,
                "reason": v.reason,
            }
            for v in run.per_binary
        ],
    }
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def render_prometheus_textfile(run: ProbeRun) -> str:
    """Render a Prometheus textfile exposing the verdict-axes."""
    lines: List[str] = []
    lines.append(
        "# HELP wakir_cosign_drift_probe_aggregate "
        "Aggregate cosign-drift-probe verdict (0=GREEN, 1=NOT-CHECKED, "
        "2=DRIFT-WORKFLOW-PATH, 3=DRIFT-CERTIFICATE-ISSUER, "
        "4=DRIFT-OIDC-IDENTITY, 5=DRIFT-TRUST-ROOT)."
    )
    lines.append("# TYPE wakir_cosign_drift_probe_aggregate gauge")
    sev = {v: i for i, v in enumerate(VERDICT_SEVERITY)}
    lines.append(
        f"wakir_cosign_drift_probe_aggregate "
        f"{sev.get(run.aggregate_verdict, len(VERDICT_SEVERITY))}"
    )
    lines.append("")
    lines.append(
        "# HELP wakir_cosign_drift_probe_per_binary "
        "Per-binary cosign-drift verdict."
    )
    lines.append("# TYPE wakir_cosign_drift_probe_per_binary gauge")
    for v in run.per_binary:
        lines.append(
            f'wakir_cosign_drift_probe_per_binary{{binary="{v.binary_name}",'
            f'verdict="{v.verdict}"}} '
            f"{sev.get(v.verdict, len(VERDICT_SEVERITY))}"
        )
    lines.append("")
    lines.append(
        "# HELP wakir_cosign_drift_probe_trust_root "
        "Trust-root axis verdict."
    )
    lines.append("# TYPE wakir_cosign_drift_probe_trust_root gauge")
    lines.append(
        f"wakir_cosign_drift_probe_trust_root "
        f"{sev.get(run.trust_root_axis, len(VERDICT_SEVERITY))}"
    )
    return "\n".join(lines) + "\n"


def render_markdown_summary(run: ProbeRun) -> str:
    """Render an operator-readable Markdown summary."""
    lines: List[str] = []
    lines.append("# Cosign-Keyless-OIDC-Drift-Probe — Run Summary")
    lines.append("")
    lines.append(f"- probe_ts: {int(run.probe_ts)}")
    lines.append(f"- aggregate verdict: **{run.aggregate_verdict}**")
    lines.append(
        f"- trust-root axis: **{run.trust_root_axis}** — "
        f"{run.trust_root_reason or '(no detail)'}"
    )
    lines.append("")
    lines.append("## Per-binary verdicts")
    lines.append("")
    lines.append("| Binary | Verdict | Reason |")
    lines.append("|---|---|---|")
    for v in run.per_binary:
        reason = v.reason.replace("|", "\\|") if v.reason else ""
        lines.append(f"| {v.binary_name} | {v.verdict} | {reason} |")
    lines.append("")
    if run.aggregate_verdict != "GREEN":
        lines.append("## Operator action")
        lines.append("")
        lines.append(
            "Aggregate verdict is non-GREEN. Operator-Hand recipe: "
            "review the drift reason(s) above against the Sigstore "
            "Rekor transparency log entries for the affected binary "
            "or trust-root axis. Halt rollout until the drift is "
            "reconciled (either by updating the pinned policy in a "
            "Zone-C cross-reviewed PR, or by rolling back the upstream "
            "Sigstore re-tag). See "
            "`docs/operations/cosign-keyless-oidc-drift-probe.md` for "
            "the full recipe."
        )
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Pure functions: snapshot helpers (for hermetic fixtures)
# ---------------------------------------------------------------------------


def synthesise_baseline_snapshot(
    policy: PolicySnapshot,
    pinned_trust_root: TrustRootSnapshot,
    workflow_paths_on_disk: Sequence[str],
) -> Dict[str, object]:
    """Build a synthetic 'all-GREEN' snapshot from policy + pinned TR.

    Used by the daily CI workflow's substrate-consistency probe: if
    no upstream snapshot is available (sandbox-no-egress), the
    probe runs against a self-consistent snapshot to verify the
    substrate hasn't drifted internally. This still catches:

      - workflow file renamed / deleted
      - policy schema changed
      - binary inventory drifted from the Tag-45 canonical 15
    """
    per_binary: List[Dict[str, str]] = []
    for name in policy.binary_names:
        wf = policy.binary_to_build_workflow.get(name, "")
        # Construct a synthetic identity URL that matches the regexp.
        identity = (
            f"{CANONICAL_IDENTITY_PREFIX}{wf}@refs/heads/main"
            if wf
            else f"{CANONICAL_IDENTITY_PREFIX}.github/workflows/synthetic.yml"
            "@refs/heads/main"
        )
        per_binary.append(
            {
                "binary_name": name,
                "certificate_identity": identity,
                "certificate_oidc_issuer": policy.certificate_oidc_issuer,
                "build_workflow_path": wf,
            }
        )
    return {
        "snapshot_ts": int(time.time()),
        "trust_root": {
            "cosign_installer_action": pinned_trust_root.cosign_installer_action,
            "cosign_installer_semver_major": (
                pinned_trust_root.cosign_installer_semver_major
            ),
            "fulcio_root_ca_sha256": pinned_trust_root.fulcio_root_ca_sha256,
            "rekor_log_shard_id": pinned_trust_root.rekor_log_shard_id,
        },
        "per_binary_oidc": per_binary,
    }


# ---------------------------------------------------------------------------
# --- I/O boundary ---
# Everything below performs filesystem or stdout I/O.
# ---------------------------------------------------------------------------


def load_policy_yaml(path: Path) -> Mapping[str, object]:
    """Read + parse the cosign-policy YAML."""
    import yaml  # local import: pure-function callers don't pay for yaml.

    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, Mapping):
        raise ValueError(f"policy YAML did not parse to a mapping: {path}")
    return parsed


def load_snapshot_json(path: Path) -> Mapping[str, object]:
    """Read + parse a snapshot JSON file."""
    text = path.read_text(encoding="utf-8")
    parsed = json.loads(text)
    if not isinstance(parsed, Mapping):
        raise ValueError(f"snapshot JSON did not parse to a mapping: {path}")
    return parsed


def discover_workflow_paths(repo_root: Path) -> Tuple[str, ...]:
    """Enumerate .github/workflows/*.yml relative to repo_root."""
    wf_dir = repo_root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return ()
    out: List[str] = []
    for entry in sorted(wf_dir.iterdir()):
        if entry.suffix in (".yml", ".yaml") and entry.is_file():
            out.append(f".github/workflows/{entry.name}")
    return tuple(out)


def write_textfile(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cosign-Keyless-OIDC-Drift-Probe (Tag-47). Tracks the "
            "Sigstore Trust-Root + per-binary OIDC-identity drift "
            "for the Tag-45 15-binary Cosign-Policy inventory."
        )
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("policies/cosign-policy-phase-3b.yaml"),
        help="Path to the cosign-policy YAML.",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help=(
            "Path to a snapshot JSON. If omitted with "
            "--mode=baseline, synthesise an all-GREEN snapshot from "
            "the pinned trust-root."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("baseline", "fixture"),
        default="baseline",
        help=(
            "baseline: substrate-consistency probe (no live cosign); "
            "fixture: read snapshot from --snapshot path."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (for workflow-path discovery).",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="If set, write JSON envelope here.",
    )
    parser.add_argument(
        "--out-textfile",
        type=Path,
        default=None,
        help="If set, write Prometheus textfile here.",
    )
    parser.add_argument(
        "--out-markdown",
        type=Path,
        default=None,
        help="If set, write Markdown operator summary here.",
    )
    parser.add_argument(
        "--exit-non-zero-on-drift",
        action="store_true",
        help=(
            "If set, exit with code 2 when aggregate verdict is not "
            "GREEN. Default is exit 0 (operator-hand triage)."
        ),
    )
    parser.add_argument(
        "--pinned-trust-root",
        type=Path,
        default=Path("state/cosign-drift/pinned-trust-root.json"),
        help="Path to the pinned-trust-root JSON.",
    )
    return parser.parse_args(argv)


def load_pinned_trust_root(path: Path) -> TrustRootSnapshot:
    """Load the pinned trust-root from disk.

    The pinned-trust-root is a check-in artefact that an Operator-
    Hand updates when the upstream Sigstore project re-tags. Schema:

      {
        "cosign_installer_action": "sigstore/cosign-installer@v3",
        "cosign_installer_semver_major": "v3",
        "fulcio_root_ca_sha256": "<64-hex>",
        "rekor_log_shard_id": "<shard-id>"
      }
    """
    text = path.read_text(encoding="utf-8")
    obj = json.loads(text)
    if not isinstance(obj, Mapping):
        raise ValueError(f"pinned trust-root JSON not a mapping: {path}")
    return TrustRootSnapshot(
        cosign_installer_action=str(obj.get("cosign_installer_action", "")),
        cosign_installer_semver_major=str(
            obj.get("cosign_installer_semver_major", "")
        ),
        fulcio_root_ca_sha256=str(obj.get("fulcio_root_ca_sha256", "")),
        rekor_log_shard_id=str(obj.get("rekor_log_shard_id", "")),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    raw_policy = load_policy_yaml(args.policy)
    policy = policy_from_raw(raw_policy)
    pinned_tr = load_pinned_trust_root(args.pinned_trust_root)
    workflow_paths = discover_workflow_paths(args.repo_root)

    if args.mode == "fixture":
        if args.snapshot is None:
            print("--mode=fixture requires --snapshot", file=sys.stderr)
            return 64
        raw_snap = load_snapshot_json(args.snapshot)
    else:
        # baseline mode: synthesise a self-consistent snapshot.
        raw_snap = synthesise_baseline_snapshot(
            policy, pinned_tr, workflow_paths
        )

    cur_tr = trust_root_from_raw(raw_snap)
    per_binary_snaps = binary_oidc_snapshots_from_raw(raw_snap)

    run = evaluate_run(
        policy=policy,
        pinned_trust_root=pinned_tr,
        current_trust_root=cur_tr,
        per_binary_snapshots=per_binary_snaps,
        workflow_paths_on_disk=workflow_paths,
        probe_ts=time.time(),
    )

    if args.out_json:
        write_textfile(args.out_json, render_json_envelope(run))
    if args.out_textfile:
        write_textfile(args.out_textfile, render_prometheus_textfile(run))
    if args.out_markdown:
        write_textfile(args.out_markdown, render_markdown_summary(run))

    print(render_markdown_summary(run))

    if args.exit_non_zero_on_drift and run.aggregate_verdict != "GREEN":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
