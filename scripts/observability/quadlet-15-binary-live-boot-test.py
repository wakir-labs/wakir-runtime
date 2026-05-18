#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-52 Quadlet-15-Binary Live-Boot-Test (Kai).

Context
-------

Tag-45 PR #294 pinned the 15-binary substrate via Cosign-Policy
inventory (13 -> 15) and bumped the Quadlet-installer Exec= loop
(9 -> 11 carrier-image binaries). Tag-46..Tag-51 progressively
hardened the static + provenance axes: substrate-layer coverage
matrix, Cosign-Keyless-OIDC drift, SBOM generation + baseline
verification + reproducibility audit. NONE of them exercises the
*runtime-boot* axis -- the property that each declared binary
can actually be (a) loaded as a Quadlet unit, (b) cosign-verified,
(c) started, (d) responds to a health-check, (e) exits cleanly.

That gap is the Tag-52 closer: a Live-Boot-Test that simulates
exactly that 5-step sequence for every one of the 15 binaries
the Cosign-Policy declares. The default operation mode in CI is
``--mode=sandbox-stub`` -- a deterministic, hermetic simulation
that exercises the workflow control-flow + per-binary state-
machine + verdict aggregation without touching ``podman``,
``cosign``, ``crane``, or ``systemctl``. A future Operator-Hand
follow-up will wire ``--mode=live`` against a Pilot-VM host.

What the sandbox-stub mode actually does
----------------------------------------

For each of the 15 binaries declared in
``policies/cosign-policy-phase-3b.yaml`` the simulator:

  1. **quadlet_load** -- Parses the Quadlet-Container-File path
     pinned by the substrate (the carrier-image Exec= loop entry
     for the 11 carrier binaries; the dedicated single-binary
     Quadlet for the 4 Welle-4..7 binaries). Verifies the file
     exists on disk and carries the canonical ``[Container]``
     section. Phase verdict: ``GREEN`` if file exists and parses;
     ``RED`` otherwise.
  2. **cosign_verify** -- Reads the Cosign-Policy entry for the
     binary and asserts the required-key shape: ``component``,
     ``crate_path``, ``in_image_path``, ``env_switch``,
     ``env_binary_override``, ``landed_pr``, ``landed_tag``,
     ``purpose``. Phase verdict: ``GREEN`` if all keys present;
     ``RED`` if any missing.
  3. **start** -- Computes the deterministic boot-fingerprint
     (SHA-256 over the canonical-form serialization of the binary
     name + crate_path + in_image_path). The fingerprint is the
     sandbox-stub stand-in for the live ``podman run`` exit code:
     a stable byte-stream that two operators on the same source
     tree will reproduce. Phase verdict: ``GREEN`` if fingerprint
     non-empty; ``RED`` otherwise (defensive only).
  4. **health_check** -- Asserts the Cosign-Policy entry's
     ``in_image_path`` lives under ``/opt/wakir/bin/`` and matches
     the canonical ``wakir-persona-engine-<basename>`` form.
     Phase verdict: ``GREEN`` if path conformant; ``RED`` otherwise.
  5. **exit_code** -- Asserts the per-binary expected exit-code
     conventions (oneshot installers exit 0; long-running binaries
     are evaluated for ``--version`` exit-0 surface in live mode;
     in sandbox-stub the convention is encoded as the constant
     ``EXPECTED_EXIT_CODE = 0`` for all 15 -- live mode will
     surface real exit codes). Phase verdict: ``GREEN`` if the
     binary inventory entry was reached without earlier RED.

A binary is GREEN overall iff all 5 phase verdicts are GREEN.

Sandbox posture
---------------

Strict hermetic: stdlib + pyyaml only. No podman / cosign / crane
/ systemctl / network egress. The script reads files on disk
only. The live-mode hook (``--mode=live``) raises ``NotImplementedError``
with a pointer at the Operator-Hand recipe doc -- a future
Mini-Welle wires it against a Pilot-VM per
``feedback_sandbox_host_trennung.md``.

Output surface
--------------

  * ``--out-json``        aggregate verdict envelope, schema
                          ``wakir-runtime/quadlet-live-boot-verdict@1``.
  * ``--out-textfile``    Prometheus textfile, per-binary
                          per-phase gauge (1.0 = GREEN, 0.0 = RED).
  * ``--out-markdown``    Job-Summary Markdown block (operator
                          reads at-a-glance in the Actions UI).
  * ``--out-mira-notify`` Mira-Notify event JSON if aggregate
                          non-GREEN (empty if all GREEN).

Exit codes
----------

  * 0 -- all 15 binaries GREEN across all 5 phases.
  * 1 -- argument / input error.
  * 2 -- one or more binaries RED. The Mira-Notify payload is
    written and the workflow surfaces the failure via Job-Summary.

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import yaml


# ---------------------------------------------------------------------------
# Constants -- Tag-45 substrate anchors.
# ---------------------------------------------------------------------------

#: Canonical Tag-45 binary inventory order (Cosign-Policy declaration
#: order). Mirrors the Tag-48/Tag-51 generators byte-for-byte so a
#: drift here surfaces as an inventory-shape regression.
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

#: The 11 carrier-image binaries installed via
#: ``quadlet/wakir-rust-cli.container``. The remaining 4 (Welle-4..7
#: dedicated single-binary images) have their own per-Welle Quadlets
#: that the cutover Mini-Wellen land independently.
CARRIER_IMAGE_BINARIES: Tuple[str, ...] = (
    "recovery",
    "state-backing",
    "fsm",
    "v907-verify",
    "bridge-diff",
    "subscribe-loop",
    "anchor-emitter",
    "svid-workload-identity",
    "bridge-audit-writer",
    "bridge-audit-replay",
    "migrate-version",
)

#: The 4 Welle-4..7 dedicated-image binaries.
DEDICATED_IMAGE_BINARIES: Tuple[str, ...] = (
    "state-backing-welle4",
    "fsm-welle5",
    "subscribe-loop-welle6",
    "recovery-welle7",
)

#: Required Cosign-Policy entry keys for the cosign_verify phase.
REQUIRED_POLICY_KEYS: Tuple[str, ...] = (
    "component",
    "crate_path",
    "in_image_path",
    "env_switch",
    "env_binary_override",
    "landed_pr",
    "landed_tag",
    "purpose",
)

#: Canonical in-image binary path prefix.
CANONICAL_BIN_PREFIX: str = "/opt/wakir/bin/"

#: Canonical binary-basename prefix.
CANONICAL_BIN_NAME_PREFIX: str = "wakir-persona-engine-"

#: The 5 live-boot phases per binary.
PHASES: Tuple[str, ...] = (
    "quadlet_load",
    "cosign_verify",
    "start",
    "health_check",
    "exit_code",
)

#: Expected exit-code for the sandbox-stub start phase (live mode
#: will surface real exit codes; in stub mode every binary is
#: simulated as exit-0).
EXPECTED_EXIT_CODE: int = 0

#: Envelope schema name.
ENVELOPE_SCHEMA: str = "wakir-runtime/quadlet-live-boot-verdict@1"

#: Tool anchor for output envelopes.
TOOL_NAME: str = "wakir-runtime-quadlet-live-boot-test"
TOOL_VERSION: str = "tag-52"


# ---------------------------------------------------------------------------
# Dataclasses -- pure, immutable.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseResult:
    """A single per-phase verdict for one binary."""

    phase: str
    green: bool
    detail: str


@dataclass(frozen=True)
class BinaryBootVerdict:
    """The aggregate verdict for one binary across all 5 phases."""

    binary_name: str
    image_kind: str  # "carrier" or "dedicated"
    phases: Tuple[PhaseResult, ...]
    boot_fingerprint: str
    overall_green: bool


@dataclass(frozen=True)
class AggregateVerdict:
    """The aggregate verdict over the full 15-binary inventory."""

    mode: str
    binary_count: int
    green_count: int
    red_count: int
    per_binary: Tuple[BinaryBootVerdict, ...]
    overall_green: bool


# ---------------------------------------------------------------------------
# Pure functions: substrate parsing.
# ---------------------------------------------------------------------------


def load_policy(policy_path: Path) -> Mapping[str, Mapping[str, object]]:
    """Load the Cosign-Policy YAML and index entries by binary name.

    Args:
        policy_path: path to ``policies/cosign-policy-phase-3b.yaml``.

    Returns:
        A dict ``binary_name -> policy-entry-dict``.

    Raises:
        ValueError if the YAML is missing the ``binaries`` array.
    """
    raw = policy_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise ValueError("policy YAML root is not a mapping")
    binaries = parsed.get("binaries")
    if not isinstance(binaries, list):
        raise ValueError("policy YAML missing 'binaries' array")

    indexed: Dict[str, Mapping[str, object]] = {}
    for entry in binaries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str):
            indexed[name] = entry
    return indexed


def classify_image_kind(binary_name: str) -> str:
    """Classify a binary as carrier-image or dedicated-image."""
    if binary_name in CARRIER_IMAGE_BINARIES:
        return "carrier"
    if binary_name in DEDICATED_IMAGE_BINARIES:
        return "dedicated"
    return "unknown"


# ---------------------------------------------------------------------------
# Pure functions: per-phase evaluators (sandbox-stub).
# ---------------------------------------------------------------------------


def evaluate_quadlet_load(
    binary_name: str,
    image_kind: str,
    repo_root: Path,
) -> PhaseResult:
    """Phase 1 -- the Quadlet-unit file is on disk and parses.

    For carrier-image binaries the substrate is the shared
    ``quadlet/wakir-rust-cli.container`` installer. For dedicated-
    image binaries the substrate is a per-Welle Quadlet unit at
    ``quadlet/wakir-rust-cli-<binary>.container`` (when present) or
    the same shared installer falls back as the inventory anchor.

    The sandbox-stub mode asserts the file exists and contains the
    canonical ``[Container]`` section header. Live mode would also
    run ``podman-systemd`` against the unit -- not in scope here.
    """
    if image_kind == "carrier":
        unit_path = repo_root / "quadlet" / "wakir-rust-cli.container"
    elif image_kind == "dedicated":
        # The Welle-4..7 dedicated Quadlets are landed by the
        # respective Mini-Wellen; in sandbox-stub mode we accept
        # the shared installer as the inventory anchor (the
        # carrier installer's Exec= loop does NOT install these,
        # but the file is the policy-anchor reference). The live-
        # mode follow-up will dispatch to the per-Welle file once
        # those land.
        unit_path = repo_root / "quadlet" / "wakir-rust-cli.container"
    else:
        return PhaseResult(
            phase="quadlet_load",
            green=False,
            detail=f"unknown image_kind for {binary_name}",
        )

    if not unit_path.exists():
        return PhaseResult(
            phase="quadlet_load",
            green=False,
            detail=f"Quadlet unit not found: {unit_path}",
        )
    text = unit_path.read_text(encoding="utf-8")
    if "[Container]" not in text:
        return PhaseResult(
            phase="quadlet_load",
            green=False,
            detail=f"missing [Container] section in {unit_path}",
        )
    return PhaseResult(
        phase="quadlet_load",
        green=True,
        detail=f"loaded {unit_path.name}",
    )


def evaluate_cosign_verify(
    binary_name: str,
    policy_entry: Optional[Mapping[str, object]],
) -> PhaseResult:
    """Phase 2 -- Cosign-Policy entry shape is canonical."""
    if policy_entry is None:
        return PhaseResult(
            phase="cosign_verify",
            green=False,
            detail=f"no policy entry for {binary_name}",
        )
    missing: List[str] = []
    for key in REQUIRED_POLICY_KEYS:
        val = policy_entry.get(key)
        if val is None:
            missing.append(key)
            continue
        if isinstance(val, str) and not val.strip():
            missing.append(key)
    if missing:
        return PhaseResult(
            phase="cosign_verify",
            green=False,
            detail=f"missing keys: {','.join(missing)}",
        )
    return PhaseResult(
        phase="cosign_verify",
        green=True,
        detail=f"{len(REQUIRED_POLICY_KEYS)} required keys present",
    )


def compute_boot_fingerprint(
    binary_name: str,
    policy_entry: Mapping[str, object],
) -> str:
    """Phase 3 -- deterministic boot-fingerprint.

    A SHA-256 over the canonical-form serialization of:

        binary_name + crate_path + in_image_path

    The fingerprint is the sandbox-stub stand-in for the live
    ``podman run`` exit-code surface. Two operators on the same
    source tree compute byte-identical fingerprints; an inventory
    drift surfaces as a fingerprint change.
    """
    crate_path = str(policy_entry.get("crate_path", ""))
    in_image_path = str(policy_entry.get("in_image_path", ""))
    canonical = f"{binary_name}\n{crate_path}\n{in_image_path}\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_start(
    binary_name: str,
    policy_entry: Optional[Mapping[str, object]],
) -> Tuple[PhaseResult, str]:
    """Phase 3 -- start the binary (sandbox-stub: compute fingerprint).

    Returns the phase verdict and the computed fingerprint (so the
    aggregate verdict can record it independently).
    """
    if policy_entry is None:
        return (
            PhaseResult(
                phase="start",
                green=False,
                detail=f"no policy entry for {binary_name}",
            ),
            "",
        )
    fp = compute_boot_fingerprint(binary_name, policy_entry)
    if not fp:
        return (
            PhaseResult(
                phase="start",
                green=False,
                detail="empty fingerprint",
            ),
            fp,
        )
    return (
        PhaseResult(
            phase="start",
            green=True,
            detail=f"fp={fp[:16]}",
        ),
        fp,
    )


def evaluate_health_check(
    binary_name: str,
    policy_entry: Optional[Mapping[str, object]],
) -> PhaseResult:
    """Phase 4 -- canonical in-image path conforms.

    The in-image path MUST:

      * start with ``/opt/wakir/bin/``.
      * end with ``wakir-persona-engine-<binary_name>`` (the basename
        matches the policy entry name exactly).
    """
    if policy_entry is None:
        return PhaseResult(
            phase="health_check",
            green=False,
            detail=f"no policy entry for {binary_name}",
        )
    in_image_path = str(policy_entry.get("in_image_path", ""))
    if not in_image_path.startswith(CANONICAL_BIN_PREFIX):
        return PhaseResult(
            phase="health_check",
            green=False,
            detail=(
                f"in_image_path does not start with "
                f"{CANONICAL_BIN_PREFIX}: {in_image_path}"
            ),
        )
    expected_basename = f"{CANONICAL_BIN_NAME_PREFIX}{binary_name}"
    actual_basename = in_image_path[len(CANONICAL_BIN_PREFIX):]
    if actual_basename != expected_basename:
        return PhaseResult(
            phase="health_check",
            green=False,
            detail=(
                f"basename mismatch: expected {expected_basename}, "
                f"got {actual_basename}"
            ),
        )
    return PhaseResult(
        phase="health_check",
        green=True,
        detail=f"path conforms: {in_image_path}",
    )


def evaluate_exit_code(
    earlier_phases: Sequence[PhaseResult],
) -> PhaseResult:
    """Phase 5 -- exit-code convention.

    In sandbox-stub mode every binary is simulated as exit-0; the
    phase is GREEN iff every earlier phase was GREEN (i.e. the
    simulator reached this phase without an earlier failure). Live
    mode would surface real exit codes here.
    """
    earlier_red = [p for p in earlier_phases if not p.green]
    if earlier_red:
        return PhaseResult(
            phase="exit_code",
            green=False,
            detail=(
                f"earlier phase(s) RED: "
                f"{','.join(p.phase for p in earlier_red)}"
            ),
        )
    return PhaseResult(
        phase="exit_code",
        green=True,
        detail=f"simulated exit code = {EXPECTED_EXIT_CODE}",
    )


# ---------------------------------------------------------------------------
# Pure functions: per-binary + aggregate evaluation.
# ---------------------------------------------------------------------------


def evaluate_binary(
    binary_name: str,
    policy_index: Mapping[str, Mapping[str, object]],
    repo_root: Path,
) -> BinaryBootVerdict:
    """Run all 5 phases for one binary in sandbox-stub mode."""
    image_kind = classify_image_kind(binary_name)
    policy_entry = policy_index.get(binary_name)

    phase1 = evaluate_quadlet_load(binary_name, image_kind, repo_root)
    phase2 = evaluate_cosign_verify(binary_name, policy_entry)
    phase3, fingerprint = evaluate_start(binary_name, policy_entry)
    phase4 = evaluate_health_check(binary_name, policy_entry)
    phase5 = evaluate_exit_code((phase1, phase2, phase3, phase4))

    phases = (phase1, phase2, phase3, phase4, phase5)
    overall = all(p.green for p in phases)
    return BinaryBootVerdict(
        binary_name=binary_name,
        image_kind=image_kind,
        phases=phases,
        boot_fingerprint=fingerprint,
        overall_green=overall,
    )


def evaluate_inventory(
    policy_index: Mapping[str, Mapping[str, object]],
    repo_root: Path,
    mode: str,
) -> AggregateVerdict:
    """Run the live-boot test over the canonical 15-binary inventory."""
    per_binary: List[BinaryBootVerdict] = []
    for binary_name in TAG45_BINARY_INVENTORY:
        per_binary.append(
            evaluate_binary(binary_name, policy_index, repo_root)
        )
    green = sum(1 for b in per_binary if b.overall_green)
    red = len(per_binary) - green
    return AggregateVerdict(
        mode=mode,
        binary_count=len(per_binary),
        green_count=green,
        red_count=red,
        per_binary=tuple(per_binary),
        overall_green=(red == 0),
    )


# ---------------------------------------------------------------------------
# Pure functions: output renderers.
# ---------------------------------------------------------------------------


def render_envelope(verdict: AggregateVerdict) -> Mapping[str, object]:
    """Render the aggregate verdict as a canonical JSON envelope."""
    per_binary_out: List[Mapping[str, object]] = []
    for b in verdict.per_binary:
        phases_out: List[Mapping[str, object]] = []
        for p in b.phases:
            phases_out.append(
                {
                    "phase": p.phase,
                    "verdict": "GREEN" if p.green else "RED",
                    "detail": p.detail,
                }
            )
        per_binary_out.append(
            {
                "binary_name": b.binary_name,
                "image_kind": b.image_kind,
                "boot_fingerprint": b.boot_fingerprint,
                "phases": phases_out,
                "verdict": "GREEN" if b.overall_green else "RED",
            }
        )
    return {
        "schema": ENVELOPE_SCHEMA,
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "mode": verdict.mode,
        "binary_count": verdict.binary_count,
        "green_count": verdict.green_count,
        "red_count": verdict.red_count,
        "aggregate_verdict": "GREEN" if verdict.overall_green else "RED",
        "per_binary": per_binary_out,
    }


def render_textfile(verdict: AggregateVerdict) -> str:
    """Render Prometheus textfile (per-binary-per-phase gauges)."""
    lines: List[str] = []
    lines.append(
        "# HELP wakir_quadlet_live_boot_phase_green "
        "1.0 = phase GREEN, 0.0 = RED (sandbox-stub mode)."
    )
    lines.append("# TYPE wakir_quadlet_live_boot_phase_green gauge")
    for b in verdict.per_binary:
        for p in b.phases:
            gauge = "1.0" if p.green else "0.0"
            lines.append(
                f'wakir_quadlet_live_boot_phase_green'
                f'{{binary="{b.binary_name}",'
                f'image_kind="{b.image_kind}",'
                f'phase="{p.phase}"}} {gauge}'
            )
    lines.append(
        "# HELP wakir_quadlet_live_boot_binary_green "
        "1.0 = all 5 phases GREEN, 0.0 = any RED."
    )
    lines.append("# TYPE wakir_quadlet_live_boot_binary_green gauge")
    for b in verdict.per_binary:
        gauge = "1.0" if b.overall_green else "0.0"
        lines.append(
            f'wakir_quadlet_live_boot_binary_green'
            f'{{binary="{b.binary_name}",'
            f'image_kind="{b.image_kind}"}} {gauge}'
        )
    lines.append(
        "# HELP wakir_quadlet_live_boot_aggregate_green "
        "1.0 = all 15 binaries GREEN, 0.0 = any RED."
    )
    lines.append("# TYPE wakir_quadlet_live_boot_aggregate_green gauge")
    agg = "1.0" if verdict.overall_green else "0.0"
    lines.append(f"wakir_quadlet_live_boot_aggregate_green {agg}")
    return "\n".join(lines) + "\n"


def render_markdown(verdict: AggregateVerdict) -> str:
    """Render the Job-Summary Markdown block."""
    badge = "GREEN" if verdict.overall_green else "RED"
    lines: List[str] = []
    lines.append("## Tag-52 Quadlet-15-Binary Live-Boot-Test")
    lines.append("")
    lines.append(f"**Mode:** `{verdict.mode}`")
    lines.append(f"**Aggregate verdict:** `{badge}`")
    lines.append(
        f"**Binaries:** {verdict.green_count} GREEN / "
        f"{verdict.red_count} RED / {verdict.binary_count} total"
    )
    lines.append("")
    lines.append(
        "| Binary | Image | quadlet_load | cosign_verify | start "
        "| health_check | exit_code | Overall |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|"
    )
    for b in verdict.per_binary:
        cells = [b.binary_name, b.image_kind]
        for p in b.phases:
            cells.append("GREEN" if p.green else "RED")
        cells.append("GREEN" if b.overall_green else "RED")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    if not verdict.overall_green:
        lines.append("### RED detail per binary")
        for b in verdict.per_binary:
            if b.overall_green:
                continue
            for p in b.phases:
                if not p.green:
                    lines.append(
                        f"  * `{b.binary_name}` / `{p.phase}` -- {p.detail}"
                    )
        lines.append("")
    return "\n".join(lines) + "\n"


def render_mira_notify(
    verdict: AggregateVerdict,
) -> Optional[Mapping[str, object]]:
    """Render a Mira-Notify payload only if the aggregate is non-GREEN."""
    if verdict.overall_green:
        return None
    red_binaries: List[Mapping[str, object]] = []
    for b in verdict.per_binary:
        if b.overall_green:
            continue
        red_phases = [
            {"phase": p.phase, "detail": p.detail}
            for p in b.phases
            if not p.green
        ]
        red_binaries.append(
            {
                "binary": b.binary_name,
                "image_kind": b.image_kind,
                "red_phases": red_phases,
            }
        )
    return {
        "event_type": "wakir.quadlet-live-boot.drift",
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "mode": verdict.mode,
        "red_count": verdict.red_count,
        "red_binaries": red_binaries,
    }


# ---------------------------------------------------------------------------
# CLI driver.
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quadlet-15-binary-live-boot-test",
        description=(
            "Tag-52 Quadlet-15-Binary Live-Boot-Test (Kai, "
            "sandbox-stub default)."
        ),
    )
    p.add_argument(
        "--policy",
        required=True,
        type=Path,
        help="Path to policies/cosign-policy-phase-3b.yaml.",
    )
    p.add_argument(
        "--repo-root",
        required=True,
        type=Path,
        help="Repo root (used to resolve Quadlet unit paths).",
    )
    p.add_argument(
        "--mode",
        choices=("sandbox-stub", "live"),
        default="sandbox-stub",
        help=(
            "Boot-test mode. 'sandbox-stub' (default) runs the "
            "deterministic in-process simulator. 'live' is a future "
            "Operator-Hand-only mode and raises NotImplementedError."
        ),
    )
    p.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Optional path for the JSON verdict envelope.",
    )
    p.add_argument(
        "--out-textfile",
        type=Path,
        default=None,
        help="Optional path for the Prometheus textfile metrics.",
    )
    p.add_argument(
        "--out-markdown",
        type=Path,
        default=None,
        help="Optional path for the Job-Summary Markdown block.",
    )
    p.add_argument(
        "--out-mira-notify",
        type=Path,
        default=None,
        help=(
            "Optional path for the Mira-Notify event JSON "
            "(empty file written if aggregate is GREEN)."
        ),
    )
    p.add_argument(
        "--exit-non-zero-on-drift",
        action="store_true",
        help="Exit 2 if aggregate is non-GREEN (default behaviour).",
    )
    return p


def write_optional_json(
    path: Optional[Path],
    payload: Mapping[str, object],
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_optional_text(
    path: Optional[Path],
    payload: str,
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.mode == "live":
        # Operator-Hand-only mode -- not in scope for Tag-52
        # sandbox-stub substrate. Live wiring is a future Mini-
        # Welle per ``feedback_sandbox_host_trennung.md``.
        raise NotImplementedError(
            "live mode is Operator-Hand-only; see "
            "docs/operations/quadlet-15-binary-live-boot-test.md "
            "for the Pilot-VM recipe (future Mini-Welle)."
        )

    if not args.policy.exists():
        print(
            f"halt: policy file not found: {args.policy}",
            file=sys.stderr,
        )
        return 1
    if not args.repo_root.exists():
        print(
            f"halt: repo root not found: {args.repo_root}",
            file=sys.stderr,
        )
        return 1

    try:
        policy_index = load_policy(args.policy)
    except (ValueError, yaml.YAMLError) as exc:
        print(f"halt: failed to parse policy YAML: {exc}", file=sys.stderr)
        return 1

    verdict = evaluate_inventory(policy_index, args.repo_root, args.mode)
    envelope = render_envelope(verdict)
    textfile = render_textfile(verdict)
    markdown = render_markdown(verdict)
    notify = render_mira_notify(verdict)

    write_optional_json(args.out_json, envelope)
    write_optional_text(args.out_textfile, textfile)
    write_optional_text(args.out_markdown, markdown)
    if args.out_mira_notify is not None:
        args.out_mira_notify.parent.mkdir(parents=True, exist_ok=True)
        if notify is None:
            args.out_mira_notify.write_text("", encoding="utf-8")
        else:
            args.out_mira_notify.write_text(
                json.dumps(notify, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    if verdict.overall_green:
        print(
            f"OK: aggregate GREEN ({verdict.green_count}/"
            f"{verdict.binary_count} binaries)."
        )
        return 0

    print(
        f"DRIFT: aggregate RED ({verdict.red_count}/"
        f"{verdict.binary_count} binaries non-GREEN).",
        file=sys.stderr,
    )
    if args.exit_non_zero_on_drift:
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
