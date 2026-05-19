#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cosign-Strict-Mode Readiness Check (Tag-54, Kai).

Context
-------

Tag-45 PR #294 (Quadlet+Cosign 15-Binary substrate refresh) and
Tag-47 PR #318 (Cosign-Keyless-OIDC-Drift-Probe) ship the cosign
substrate that gates the Phase-3b carrier-image trust-chain. Both
substrates today run in **audit-only** posture:

  * ``cosign-keyless-oidc-drift-probe.yml`` is scheduled daily but
    is NOT a required-status-check; verdict surfaces only via
    Job-Summary + artefact + notify-event on non-GREEN.
  * ``cosign-verify-images.yml`` is ``workflow_dispatch`` only —
    Operator-Hand-Hand recipe per pin refresh; not blocking any PR.
  * The 15-binary inventory ``expected_image_digest`` slot still
    carries the ``DIGEST_PENDING_KAI_CROSS_REVIEW`` placeholder for
    several entries (Operator-Hand resolution pending).

Flipping cosign into **strict mode** means three substrate changes
applied in lock-step:

  S1. Promote ``cosign-verify-images.yml`` to ``pull_request`` +
      ``push`` triggers with a path filter on the carrier-image
      Containerfile + the 15-binary inventory YAML + the Quadlet
      installer. PRs that would land an unsigned / digest-drifted
      pin are red'd at CI level.
  S2. Promote ``cosign-keyless-oidc-drift-probe.yml`` from daily-
      audit to per-PR-required-status-check with the
      ``exit_non_zero_on_drift=true`` workflow input wired into the
      ``pull_request`` trigger.
  S3. Add both job display-names to ``wakir-runtime`` branch-
      protection required-status-checks per
      ``docs/operations/branch-protection-required-status-checks.md``.

This script is the **readiness check**: it verifies the six
acceptance-gate conditions S1..S3 require before they are safe to
flip. The shape is the same one ``CROSS_REPO_DRIFT_ENFORCE=true``
already follows (see
``docs/operations/cross-repo-drift-enforce-flip-readiness.md`` §6).

Acceptance-gate matrix (Tag-54)
-------------------------------

The six gates the script evaluates:

  G1. ``placeholder_digest_count`` — every binary in the 15-binary
      cosign-policy inventory has a real ``sha256:[hex]`` digest
      (NOT ``DIGEST_PENDING_KAI_CROSS_REVIEW``).
      Threshold: ``== 0``.
  G2. ``pinned_trust_root_completeness`` — the pinned-trust-root
      JSON has real Fulcio CA SHA + Rekor shard ID (NOT
      ``PENDING_OPERATOR_HAND_REFRESH``).
      Threshold: both fields populated.
  G3. ``last_drift_probe_verdict`` — the most recent
      cosign-keyless-OIDC-drift-probe envelope on disk reports
      aggregate_verdict == GREEN. (The script reads the latest
      ``state/cosign-drift/last-probe-envelope.json`` if present;
      if absent it returns NOT-CHECKED for this gate, which BLOCKS
      readiness — operator must run the probe + capture the envelope.)
      Threshold: ``GREEN``.
  G4. ``policy_inventory_size`` — the cosign-policy carries the
      Tag-45 canonical 15 binaries (matches
      ``TAG45_BINARY_INVENTORY`` order). A policy with 14 or 16
      binaries means the inventory drifted from the canonical set
      and the strict-flip would either over-block (missing entries
      get policy-rejected) or under-block (extra entries are not
      gated).
      Threshold: ``== 15``.
  G5. ``cross_substrate_parity`` — the Quadlet installer
      (``quadlet/wakir-rust-cli.container``) iterates the same
      15 binaries as the policy. Drift here means CI would gate
      the carrier image even though the install-path side of the
      substrate is out of sync — flipping strict would red PRs that
      legitimately update one side first.
      Threshold: ``== 0`` parity diffs.
  G6. ``required_status_check_displaynames_known`` — the script
      knows the exact GitHub-Actions job display-names for the two
      workflows that must become required-status-checks. Per
      ``feedback_branch_protection_check_names.md`` the names must
      match exactly; this gate is a self-check that the readiness-
      check script holds the canonical names so the strict-flip PR
      doesn't drift the required-status-check rule (gate names ->
      job display names).
      Threshold: both names present and non-empty.

A run that meets all six gates is **strict-flip-ready**. A run
that misses any gate blocks the flip and surfaces which gate failed.

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 this script
NEVER calls cosign / crane / skopeo / podman / network egress. It
reads four files from disk only:

  * ``policies/cosign-policy-phase-3b.yaml``
  * ``state/cosign-drift/pinned-trust-root.json``
  * ``state/cosign-drift/last-probe-envelope.json`` (optional)
  * ``quadlet/wakir-rust-cli.container`` (optional, for G5)

The strict-flip itself is **Operator-Hand** — this script only
reports readiness. The Operator-Hand recipe lives in
``docs/operations/cosign-strict-mode-activation.md`` (Tag-54
sibling document).

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure-
function, hermetic-test target. The I/O wrappers
(``load_policy_yaml``, ``load_pinned_trust_root``,
``load_probe_envelope``, ``load_quadlet_installer``,
``write_json_envelope``, ``write_markdown_summary``) are at the
bottom.

Anchors
-------

  * Tag-45 PR #294 — Quadlet+Cosign 15-Binary substrate refresh.
  * Tag-47 PR #318 — Cosign-Keyless-OIDC-Drift-Probe daily tracker.
  * ``docs/operations/cross-repo-drift-enforce-flip-readiness.md``
    — sibling readiness-flow for CROSS_REPO_DRIFT_ENFORCE.
  * ``feedback_branch_protection_check_names.md`` — exact-name
    required-status-check rule.
  * ADR-0066 §AR-Hand-Gate — pre-cutover stability over ~3-day
    window is AR-Hand-Sign-Off pre-condition.

Author: Kai Hoffmann (Dev-Engineering-3 / Container-Orchestration)
Tag: 54 (KW-23 pre-KW-24 strict-mode-prep)
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

#: Canonical 15-binary inventory (Tag-45). MUST match the policy YAML
#: byte-for-byte; G4 verifies the policy is in lock-step.
TAG45_CANONICAL_INVENTORY: Tuple[str, ...] = (
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

#: Placeholder digest string the policy uses pre-Operator-Hand-resolve.
PLACEHOLDER_DIGEST: str = "sha256:DIGEST_PENDING_KAI_CROSS_REVIEW"

#: Placeholder strings the pinned-trust-root uses pre-Operator-Hand-refresh.
PLACEHOLDER_TRUST_ROOT: str = "PENDING_OPERATOR_HAND_REFRESH"

#: Real-digest regexp (sha256 + 64 hex chars).
REAL_DIGEST_RE: re.Pattern[str] = re.compile(r"^sha256:[a-f0-9]{64}$")

#: Real-Fulcio-CA-SHA regexp (raw 64-hex-char SHA-256, no prefix).
REAL_FULCIO_SHA_RE: re.Pattern[str] = re.compile(r"^[a-f0-9]{64}$")

#: Real-Rekor-shard-id regexp (non-empty, non-placeholder, allows the
#: upstream Sigstore shard naming convention which is non-trivial —
#: we accept any non-empty string that is not the placeholder).
REAL_REKOR_SHARD_RE: re.Pattern[str] = re.compile(r"^\S+$")

#: Canonical required-status-check display names for the two workflows
#: that must become required after the strict-flip. G6 is a self-check
#: that this script holds the right names (per
#: feedback_branch_protection_check_names.md).
STRICT_MODE_REQUIRED_CHECKS: Tuple[str, ...] = (
    "cosign verify SPIRE images",
    "Cosign-Keyless-OIDC-Drift-Probe (daily)",
)

#: Gate severity ordering: lowest -> highest.
GATE_VERDICTS: Tuple[str, ...] = (
    "GREEN",
    "NOT-CHECKED",
    "BLOCKED",
)


# ---------------------------------------------------------------------------
# Dataclasses (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyInventoryView:
    """Lightweight view of the cosign policy substrate for gate G1+G4."""

    schema_version: str
    carrier_expected_image_digest: str
    binary_names: Tuple[str, ...]


@dataclass(frozen=True)
class PinnedTrustRootView:
    """View of the pinned-trust-root JSON for gate G2."""

    fulcio_root_ca_sha256: str
    rekor_log_shard_id: str
    cosign_installer_action: str


@dataclass(frozen=True)
class ProbeEnvelopeView:
    """View of the last drift-probe envelope for gate G3."""

    aggregate_verdict: str
    probe_ts: float


@dataclass(frozen=True)
class QuadletInstallerView:
    """View of the Quadlet installer file for gate G5.

    The script does NOT parse Quadlet syntax; it grep-extracts the
    canonical binary names (the installer references each binary by
    its in-image path + the binary-name suffix).
    """

    binary_names: Tuple[str, ...]
    """Names extracted from the installer; tuple order matches first-
    occurrence order in the file. The G5 check is set-equality with
    TAG45_CANONICAL_INVENTORY."""


@dataclass(frozen=True)
class GateResult:
    """The per-gate result the readiness-check emits."""

    gate_id: str
    """G1..G6."""

    verdict: str
    """One of GATE_VERDICTS."""

    summary: str
    """Short one-line summary the operator reads."""

    detail: str = ""
    """Optional multi-line detail (NOT in markdown summary; in JSON envelope)."""


@dataclass(frozen=True)
class ReadinessRun:
    """The full envelope the readiness-check emits per run."""

    run_ts: float
    aggregate_verdict: str
    """GREEN (all gates green) / BLOCKED (any non-green) / NOT-CHECKED
    (one or more gates returned NOT-CHECKED)."""

    gate_results: Tuple[GateResult, ...]


# ---------------------------------------------------------------------------
# Pure functions: policy + trust-root + probe + quadlet parsing
# ---------------------------------------------------------------------------


def policy_view_from_raw(raw: Mapping[str, object]) -> PolicyInventoryView:
    """Build a PolicyInventoryView from a raw YAML-parsed dict.

    Pure: no I/O. Tolerates malformed dicts by yielding empty fields;
    the gate-evaluation logic then surfaces the missing data.
    """
    schema = str(raw.get("schema_version", ""))

    policy_blk = raw.get("policy", {})
    carrier_digest = ""
    if isinstance(policy_blk, Mapping):
        carrier = policy_blk.get("carrier_image", {})
        if isinstance(carrier, Mapping):
            carrier_digest = str(carrier.get("expected_image_digest", ""))

    binaries = raw.get("binaries", [])
    names: List[str] = []
    if isinstance(binaries, Sequence):
        for entry in binaries:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name", ""))
            if name:
                names.append(name)

    return PolicyInventoryView(
        schema_version=schema,
        carrier_expected_image_digest=carrier_digest,
        binary_names=tuple(names),
    )


def trust_root_view_from_raw(
    raw: Mapping[str, object],
) -> PinnedTrustRootView:
    """Build a PinnedTrustRootView from a raw JSON-parsed dict."""
    return PinnedTrustRootView(
        fulcio_root_ca_sha256=str(raw.get("fulcio_root_ca_sha256", "")),
        rekor_log_shard_id=str(raw.get("rekor_log_shard_id", "")),
        cosign_installer_action=str(raw.get("cosign_installer_action", "")),
    )


def probe_envelope_view_from_raw(
    raw: Mapping[str, object],
) -> ProbeEnvelopeView:
    """Build a ProbeEnvelopeView from a raw JSON-parsed dict."""
    return ProbeEnvelopeView(
        aggregate_verdict=str(raw.get("aggregate_verdict", "")),
        probe_ts=float(raw.get("probe_ts", 0.0) or 0.0),
    )


def quadlet_installer_binary_names_from_text(text: str) -> Tuple[str, ...]:
    """Grep-extract the canonical binary names from Quadlet installer text.

    Pure: no I/O. The Quadlet installer references each binary by
    its in-image path of the form
    ``/opt/wakir/bin/wakir-persona-engine-<name>``. We extract <name>
    via regexp. Order matches first occurrence.

    The regexp tolerates trailing-suffix variants (e.g. ``-welle4``)
    because the Tag-33 Mini-Welle introduced ``state-backing-welle4``
    as a first-class binary with the ``-welle4`` suffix in its name.
    """
    # Match the canonical in-image path + capture the suffix.
    pat = re.compile(
        r"/opt/wakir/bin/wakir-persona-engine-([a-z0-9][a-z0-9\-]*[a-z0-9])"
    )
    found: List[str] = []
    seen: set[str] = set()
    for match in pat.finditer(text):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        found.append(name)
    return tuple(found)


# ---------------------------------------------------------------------------
# Pure functions: gate evaluation
# ---------------------------------------------------------------------------


def evaluate_gate_g1_placeholder_digests(
    policy: PolicyInventoryView,
    raw_binaries: Sequence[Mapping[str, object]],
) -> GateResult:
    """G1: every binary has a real sha256: digest (no placeholders).

    The per-binary digest lives in the policy at
    ``binaries[i].expected_image_digest`` OR falls back to the
    carrier-image-level digest (Tag-45 convention: all 15 binaries
    ship in the same carrier image, so the carrier-level digest is
    the canonical one).
    """
    if not policy.binary_names:
        return GateResult(
            gate_id="G1",
            verdict="NOT-CHECKED",
            summary="policy has zero binaries — cannot evaluate G1",
        )

    placeholders: List[str] = []
    missing: List[str] = []

    for entry in raw_binaries:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", ""))
        if not name:
            continue
        per_binary_digest = str(entry.get("expected_image_digest", ""))
        # Fall back to carrier-level digest if per-binary not set.
        effective = per_binary_digest or policy.carrier_expected_image_digest
        if not effective:
            missing.append(name)
            continue
        if effective == PLACEHOLDER_DIGEST:
            placeholders.append(name)
            continue
        if not REAL_DIGEST_RE.match(effective):
            placeholders.append(f"{name} (malformed: {effective})")

    if missing:
        return GateResult(
            gate_id="G1",
            verdict="BLOCKED",
            summary=f"G1 BLOCKED — {len(missing)} binary/binaries have no digest at all",
            detail="missing digest entries: " + ", ".join(missing),
        )
    if placeholders:
        return GateResult(
            gate_id="G1",
            verdict="BLOCKED",
            summary=(
                f"G1 BLOCKED — {len(placeholders)} binary/binaries still carry "
                f"the DIGEST_PENDING_KAI_CROSS_REVIEW placeholder or a malformed digest"
            ),
            detail="placeholder/malformed entries: " + ", ".join(placeholders),
        )
    return GateResult(
        gate_id="G1",
        verdict="GREEN",
        summary=f"G1 GREEN — all {len(policy.binary_names)} binaries carry real sha256 digests",
    )


def evaluate_gate_g2_trust_root_completeness(
    trust_root: PinnedTrustRootView,
) -> GateResult:
    """G2: pinned-trust-root has real Fulcio CA SHA + Rekor shard ID."""
    if trust_root.fulcio_root_ca_sha256 == PLACEHOLDER_TRUST_ROOT:
        return GateResult(
            gate_id="G2",
            verdict="BLOCKED",
            summary="G2 BLOCKED — fulcio_root_ca_sha256 still carries PENDING_OPERATOR_HAND_REFRESH",
        )
    if trust_root.rekor_log_shard_id == PLACEHOLDER_TRUST_ROOT:
        return GateResult(
            gate_id="G2",
            verdict="BLOCKED",
            summary="G2 BLOCKED — rekor_log_shard_id still carries PENDING_OPERATOR_HAND_REFRESH",
        )
    if not REAL_FULCIO_SHA_RE.match(trust_root.fulcio_root_ca_sha256):
        return GateResult(
            gate_id="G2",
            verdict="BLOCKED",
            summary=(
                f"G2 BLOCKED — fulcio_root_ca_sha256 not a 64-hex-char SHA-256: "
                f"{trust_root.fulcio_root_ca_sha256!r}"
            ),
        )
    if not REAL_REKOR_SHARD_RE.match(trust_root.rekor_log_shard_id):
        return GateResult(
            gate_id="G2",
            verdict="BLOCKED",
            summary=(
                f"G2 BLOCKED — rekor_log_shard_id empty or whitespace-only: "
                f"{trust_root.rekor_log_shard_id!r}"
            ),
        )
    return GateResult(
        gate_id="G2",
        verdict="GREEN",
        summary="G2 GREEN — pinned-trust-root has real Fulcio CA SHA + Rekor shard ID",
    )


def evaluate_gate_g3_last_probe_verdict(
    envelope: Optional[ProbeEnvelopeView],
) -> GateResult:
    """G3: last cosign-keyless-OIDC-drift-probe envelope aggregate is GREEN."""
    if envelope is None:
        return GateResult(
            gate_id="G3",
            verdict="NOT-CHECKED",
            summary=(
                "G3 NOT-CHECKED — last-probe-envelope.json missing on disk; "
                "operator must run the drift-probe and capture its envelope"
            ),
        )
    verdict = envelope.aggregate_verdict
    if verdict == "GREEN":
        return GateResult(
            gate_id="G3",
            verdict="GREEN",
            summary=f"G3 GREEN — last drift-probe verdict is GREEN (ts={envelope.probe_ts})",
        )
    return GateResult(
        gate_id="G3",
        verdict="BLOCKED",
        summary=(
            f"G3 BLOCKED — last drift-probe verdict is {verdict!r} "
            f"(must be GREEN to flip strict)"
        ),
    )


def evaluate_gate_g4_inventory_size(
    policy: PolicyInventoryView,
) -> GateResult:
    """G4: policy carries the Tag-45 canonical 15 binaries in canonical order."""
    expected = TAG45_CANONICAL_INVENTORY
    actual = policy.binary_names
    if len(actual) != len(expected):
        return GateResult(
            gate_id="G4",
            verdict="BLOCKED",
            summary=(
                f"G4 BLOCKED — policy inventory has {len(actual)} binaries, "
                f"expected {len(expected)} (Tag-45 canonical inventory)"
            ),
            detail=f"actual: {actual!r}\nexpected: {expected!r}",
        )
    if actual != expected:
        # Same length, different order or different names.
        return GateResult(
            gate_id="G4",
            verdict="BLOCKED",
            summary=(
                "G4 BLOCKED — policy inventory drifted from canonical Tag-45 "
                "order (set or order differs)"
            ),
            detail=f"actual: {actual!r}\nexpected: {expected!r}",
        )
    return GateResult(
        gate_id="G4",
        verdict="GREEN",
        summary=f"G4 GREEN — policy carries the canonical 15 binaries in canonical order",
    )


def evaluate_gate_g5_cross_substrate_parity(
    policy: PolicyInventoryView,
    quadlet: Optional[QuadletInstallerView],
) -> GateResult:
    """G5: Quadlet installer iterates the same 15 binaries as the policy."""
    if quadlet is None:
        return GateResult(
            gate_id="G5",
            verdict="NOT-CHECKED",
            summary="G5 NOT-CHECKED — Quadlet installer file missing on disk",
        )
    policy_set = set(policy.binary_names)
    quadlet_set = set(quadlet.binary_names)
    only_in_policy = policy_set - quadlet_set
    only_in_quadlet = quadlet_set - policy_set
    if only_in_policy or only_in_quadlet:
        return GateResult(
            gate_id="G5",
            verdict="BLOCKED",
            summary=(
                f"G5 BLOCKED — cross-substrate parity drift: "
                f"{len(only_in_policy)} in policy not in quadlet, "
                f"{len(only_in_quadlet)} in quadlet not in policy"
            ),
            detail=(
                f"only-in-policy: {sorted(only_in_policy)!r}\n"
                f"only-in-quadlet: {sorted(only_in_quadlet)!r}"
            ),
        )
    return GateResult(
        gate_id="G5",
        verdict="GREEN",
        summary=(
            f"G5 GREEN — Quadlet installer and policy iterate the same "
            f"{len(policy_set)} binaries"
        ),
    )


def evaluate_gate_g6_required_check_names_known() -> GateResult:
    """G6: this script holds the canonical required-status-check display names.

    Self-check that the strict-flip recipe references the exact GitHub-
    Actions job display names (per feedback_branch_protection_check_names.md).
    """
    if not STRICT_MODE_REQUIRED_CHECKS:
        return GateResult(
            gate_id="G6",
            verdict="BLOCKED",
            summary="G6 BLOCKED — STRICT_MODE_REQUIRED_CHECKS tuple is empty",
        )
    for name in STRICT_MODE_REQUIRED_CHECKS:
        if not name or not name.strip():
            return GateResult(
                gate_id="G6",
                verdict="BLOCKED",
                summary=(
                    f"G6 BLOCKED — empty/whitespace required-status-check "
                    f"display name: {name!r}"
                ),
            )
    return GateResult(
        gate_id="G6",
        verdict="GREEN",
        summary=(
            f"G6 GREEN — readiness-check holds {len(STRICT_MODE_REQUIRED_CHECKS)} "
            f"canonical required-status-check display names"
        ),
        detail="known names: " + ", ".join(STRICT_MODE_REQUIRED_CHECKS),
    )


def aggregate_run_verdict(
    gate_results: Sequence[GateResult],
) -> str:
    """Aggregate the run verdict from the per-gate verdicts.

    Rule:
      * BLOCKED if any gate is BLOCKED.
      * NOT-CHECKED if no BLOCKED but any NOT-CHECKED.
      * GREEN if all GREEN.

    A run that contains any NOT-CHECKED gate blocks the strict-flip
    (same posture as cross-repo-drift Step-1 baseline run-id check).
    """
    has_blocked = any(g.verdict == "BLOCKED" for g in gate_results)
    if has_blocked:
        return "BLOCKED"
    has_not_checked = any(g.verdict == "NOT-CHECKED" for g in gate_results)
    if has_not_checked:
        return "NOT-CHECKED"
    return "GREEN"


def render_markdown_summary(run: ReadinessRun) -> str:
    """Render a Markdown summary suitable for GITHUB_STEP_SUMMARY."""
    lines: List[str] = []
    lines.append("## Cosign-Strict-Mode Readiness Check (Tag-54)")
    lines.append("")
    badge_map = {
        "GREEN": "GREEN — strict-flip-ready",
        "NOT-CHECKED": "NOT-CHECKED — one or more gates need operator data",
        "BLOCKED": "BLOCKED — one or more gates failed",
    }
    badge = badge_map.get(run.aggregate_verdict, run.aggregate_verdict)
    lines.append(f"**Aggregate verdict:** {badge}")
    lines.append(f"**Run ts:** `{run.run_ts}`")
    lines.append("")
    lines.append("| Gate | Verdict | Summary |")
    lines.append("|---|---|---|")
    for gate in run.gate_results:
        # Escape pipe characters in summary to keep markdown table well-formed.
        safe_summary = gate.summary.replace("|", "\\|")
        lines.append(f"| {gate.gate_id} | {gate.verdict} | {safe_summary} |")
    lines.append("")
    lines.append(
        "Strict-flip recipe: see `docs/operations/cosign-strict-mode-activation.md`."
    )
    return "\n".join(lines) + "\n"


def envelope_to_json(run: ReadinessRun) -> str:
    """Render the readiness-run as a JSON envelope (stable key order)."""
    payload = {
        "schema": "wakir.cosign-strict-mode.readiness-check/1",
        "run_ts": run.run_ts,
        "aggregate_verdict": run.aggregate_verdict,
        "gate_results": [
            {
                "gate_id": g.gate_id,
                "verdict": g.verdict,
                "summary": g.summary,
                "detail": g.detail,
            }
            for g in run.gate_results
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# --- I/O boundary ---
# ---------------------------------------------------------------------------


def load_policy_yaml(path: Path) -> Tuple[PolicyInventoryView, Sequence[Mapping[str, object]]]:
    """Load the cosign-policy YAML; return (policy-view, raw-binaries).

    The raw-binaries list is returned alongside the view so G1 can
    re-walk the per-binary entries (the view only carries names).
    """
    import yaml  # local import — keeps the pure section truly stdlib-only

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"policy YAML at {path} is not a mapping")
    view = policy_view_from_raw(raw)
    raw_binaries = raw.get("binaries", []) or []
    if not isinstance(raw_binaries, Sequence):
        raw_binaries = []
    return view, raw_binaries


def load_pinned_trust_root(path: Path) -> PinnedTrustRootView:
    """Load the pinned-trust-root JSON; return the view."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"pinned-trust-root JSON at {path} is not a mapping")
    return trust_root_view_from_raw(raw)


def load_probe_envelope(path: Path) -> Optional[ProbeEnvelopeView]:
    """Load the last-probe-envelope JSON; return view or None if missing."""
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        return None
    return probe_envelope_view_from_raw(raw)


def load_quadlet_installer(path: Path) -> Optional[QuadletInstallerView]:
    """Load the Quadlet installer text + extract binary names."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    names = quadlet_installer_binary_names_from_text(text)
    return QuadletInstallerView(binary_names=names)


def write_json_envelope(path: Path, run: ReadinessRun) -> None:
    """Write the readiness-run JSON envelope."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(envelope_to_json(run), encoding="utf-8")


def write_markdown_summary(path: Path, run: ReadinessRun) -> None:
    """Write the readiness-run Markdown summary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown_summary(run), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Cosign-Strict-Mode Readiness Check (Tag-54). "
            "Evaluates six acceptance-gates pre-strict-flip."
        ),
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("policies/cosign-policy-phase-3b.yaml"),
        help="Path to the cosign-policy YAML.",
    )
    parser.add_argument(
        "--pinned-trust-root",
        type=Path,
        default=Path("state/cosign-drift/pinned-trust-root.json"),
        help="Path to the pinned-trust-root JSON.",
    )
    parser.add_argument(
        "--last-probe-envelope",
        type=Path,
        default=Path("state/cosign-drift/last-probe-envelope.json"),
        help=(
            "Path to the last cosign-keyless-OIDC-drift-probe envelope. "
            "If absent, gate G3 returns NOT-CHECKED (which blocks readiness)."
        ),
    )
    parser.add_argument(
        "--quadlet-installer",
        type=Path,
        default=Path("quadlet/wakir-rust-cli.container"),
        help=(
            "Path to the Quadlet installer file. "
            "If absent, gate G5 returns NOT-CHECKED (which blocks readiness)."
        ),
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Write the run envelope as JSON to this path.",
    )
    parser.add_argument(
        "--out-markdown",
        type=Path,
        default=None,
        help="Write the run summary as Markdown to this path.",
    )
    parser.add_argument(
        "--exit-non-zero-on-block",
        action="store_true",
        help=(
            "Exit non-zero when the aggregate verdict is not GREEN. "
            "Useful when the script is wired into a workflow that should "
            "red the run on a non-ready substrate."
        ),
    )
    args = parser.parse_args(argv)

    policy, raw_binaries = load_policy_yaml(args.policy)
    trust_root = load_pinned_trust_root(args.pinned_trust_root)
    envelope = load_probe_envelope(args.last_probe_envelope)
    quadlet = load_quadlet_installer(args.quadlet_installer)

    gate_results: Tuple[GateResult, ...] = (
        evaluate_gate_g1_placeholder_digests(policy, raw_binaries),
        evaluate_gate_g2_trust_root_completeness(trust_root),
        evaluate_gate_g3_last_probe_verdict(envelope),
        evaluate_gate_g4_inventory_size(policy),
        evaluate_gate_g5_cross_substrate_parity(policy, quadlet),
        evaluate_gate_g6_required_check_names_known(),
    )

    aggregate = aggregate_run_verdict(gate_results)

    run = ReadinessRun(
        run_ts=time.time(),
        aggregate_verdict=aggregate,
        gate_results=gate_results,
    )

    if args.out_json is not None:
        write_json_envelope(args.out_json, run)
    if args.out_markdown is not None:
        write_markdown_summary(args.out_markdown, run)

    # Always print the markdown summary to stdout so an operator running
    # this in a terminal sees the verdict at-a-glance.
    sys.stdout.write(render_markdown_summary(run))

    if args.exit_non_zero_on_block and aggregate != "GREEN":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
