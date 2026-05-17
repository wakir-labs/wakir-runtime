#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""phase-3c-trigger-gate-aggregator — Tag-24 Phase-3c readiness aggregator.

Background
----------

ADR-0065 (approved 2026-05-17) declares the Phase-3c cutover sequence:
the persona-engine default-backend flips from Python to Rust across
seven production-default switches once five trigger-gates are all
green. The trigger-gates are:

1.  **Phase-3b 7/7 completeness** — all seven backend resolvers wired
    in :mod:`wirelang.persona_engine.rust_backend_switch` (Tag-17
    recovery + state_backing, Tag-18 fsm, Tag-19 v907_verify, Tag-20
    bridge_diff, Tag-22 subscribe_loop, Tag-23 anchor_emitter).

2.  **Cosign-Policy 7-binary inventory** — every Rust-CLI binary the
    switch subprocess-bridges to is declared in
    ``policies/cosign-policy-phase-3b.yaml`` so the keyless Sigstore
    verification covers the full surface. The Tag-23 update extended
    the inventory from 4 to 5; the Kai Tag-24 PR extends it to 7
    (subscribe_loop + anchor_emitter).

3.  **Quadlet-Installer 7-binary inventory** — same seven binaries
    referenced by ``quadlet/wakir-rust-cli.container`` so the
    host-side installer ships the full surface. The Tag-22 installer
    inventoried 5; the Kai Tag-24 PR extends to 7.

4.  **Backend-Decision-Observability baseline** — the Tag-22 SRE
    aggregator (``scripts/backend-decision-observability.py``) must
    exist AND ≥7 days of JSONL evidence must have accumulated so the
    cutover decision rests on real fallback-rate data, not on a
    cold-start guess. The baseline path is supplied via the
    ``WAKIR_PHASE_3C_OBS_BASELINE_PATH`` ENV; absent ENV ⇒ skip-with-
    warning (yellow), not a hard fail. This matches the operator-hand
    workflow where the baseline file is staged via scp/rsync from the
    Pilot-VM the day before the cutover-review.

5.  **Live-VM-Acceptance Driver existence** — the Tag-19 deliverable
    (``scripts/ci-live-vm-phase-3b-driver.sh``) is the substrate the
    ``.github/workflows/live-vm-acceptance.yml`` matrix shells out to.
    Without it the Phase-3b acceptance lane cannot run, so any
    Phase-3c cutover would fly blind on the actual host-bring-up
    contract.

Posture
-------

This aggregator does NOT execute any cosign / podman / systemctl
invocation. It validates the **declarative substrate** that the
Phase-3c cutover decision rests on. Live verification stays
operator-hand per ``docs/operations/live-vm-acceptance-phase-3b.md``
and per the sandbox-host-trennung discipline
(``feedback_sandbox_host_trennung.md``).

The output is a JSON go/no-go report with per-gate evidence, plus an
exit-code that CI can consume:

  * ``0`` — all five gates green; ``ready_for_phase_3c=true``.
  * ``1`` — at least one gate yellow (warning), none red.
  * ``2`` — at least one gate red.

Usage
-----

::

    # Default human-readable summary, exit-code reflects status.
    python scripts/phase-3c-trigger-gate-aggregator.py

    # Machine-readable JSON to stdout (for piping into jq).
    python scripts/phase-3c-trigger-gate-aggregator.py --json

    # Override the expected Rust-CLI binary inventory size (default 7).
    python scripts/phase-3c-trigger-gate-aggregator.py --target-binary-count 7

    # Use a custom repo root (useful in CI matrix jobs).
    python scripts/phase-3c-trigger-gate-aggregator.py --repo-root /workspace
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Default Rust-CLI binary inventory count expected once the Kai Tag-24
#: PR has landed. Seven components: recovery, state_backing, fsm,
#: v907_verify, bridge_diff, subscribe_loop, anchor_emitter.
DEFAULT_TARGET_BINARY_COUNT = 7


#: ENV that points at the on-disk backend-decision JSONL baseline.
#: When the ENV is unset the Gate-4 evaluation yields ``yellow``
#: (skip-with-warning) rather than ``red``, matching the operator-hand
#: workflow where the baseline file is staged shortly before the
#: cutover-review.
OBSERVABILITY_BASELINE_PATH_ENV = "WAKIR_PHASE_3C_OBS_BASELINE_PATH"


#: Minimum number of distinct JSONL days that must be present in the
#: baseline file before Gate-4 turns green. ADR-0065 declares seven
#: days as the cutover-confidence floor.
DEFAULT_BASELINE_MIN_DAYS = 7


#: Repo-relative paths that the gates check. Centralised so the test
#: suite can assert their stability.
PATH_RUST_BACKEND_SWITCH = Path("wirelang/persona_engine/rust_backend_switch.py")
PATH_COSIGN_POLICY = Path("policies/cosign-policy-phase-3b.yaml")
PATH_QUADLET_INSTALLER = Path("quadlet/wakir-rust-cli.container")
PATH_OBS_AGGREGATOR = Path("scripts/backend-decision-observability.py")
PATH_LIVE_VM_DRIVER = Path("scripts/ci-live-vm-phase-3b-driver.sh")

#: Tag-25 baseline-tracker. When present, Gate-4 enriches its
#: ``evidence`` block with the tracker's per-component split + burn-up
#: data under ``evidence["tracker_report"]``. The base Gate-4
#: tri-state status is preserved (the tracker is additive, not
#: authoritative); the tracker's own thresholds are independent.
PATH_OBS_BASELINE_TRACKER = Path("scripts/phase-3c-observability-baseline-tracker.py")


#: The seven Phase-3b backend resolvers. The Gate-1 evaluator searches
#: for each name as a function definition in
#: :data:`PATH_RUST_BACKEND_SWITCH`. Order matches the landing
#: chronology (Tag-17 → Tag-23) for stable evidence-output.
PHASE_3B_RESOLVER_NAMES = (
    "resolve_recovery_backend",
    "resolve_state_backing_backend",
    "resolve_fsm_backend",
    "resolve_v907_verify_backend",
    "resolve_bridge_diff_backend",
    "resolve_subscribe_loop_backend",
    "resolve_anchor_emitter_backend",
)


# ---------------------------------------------------------------------------
# Result-types
# ---------------------------------------------------------------------------


class GateStatus(str, enum.Enum):
    """Tri-state gate status. String-enum so it round-trips through JSON."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclasses.dataclass(frozen=True)
class GateResult:
    """Outcome of a single trigger-gate evaluation."""

    id: str
    name: str
    status: GateStatus
    evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "evidence": self.evidence,
        }


@dataclasses.dataclass(frozen=True)
class AggregatorReport:
    """Top-level aggregator report. ``ready_for_phase_3c`` ⇔ all green."""

    gates: List[GateResult]
    all_green: bool
    ready_for_phase_3c: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "wakir.phase-3c.trigger-gate-report/1",
            "gates": [g.to_dict() for g in self.gates],
            "all_green": self.all_green,
            "ready_for_phase_3c": self.ready_for_phase_3c,
        }

    @property
    def exit_code(self) -> int:
        if any(g.status is GateStatus.RED for g in self.gates):
            return 2
        if any(g.status is GateStatus.YELLOW for g in self.gates):
            return 1
        return 0


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _read_text_safe(path: Path) -> Optional[str]:
    """Return file contents, or ``None`` if the file is missing."""

    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        # Surface unexpected I/O errors as evidence (Gate goes red).
        return f"__READ_ERROR__:{exc}"


# ---------------------------------------------------------------------------
# Gate-1: Phase-3b 7/7 backend resolvers
# ---------------------------------------------------------------------------


def _count_resolver_defs(source: str) -> Dict[str, bool]:
    """Map each expected resolver name → bool (def-found in source).

    The check is a literal regex match on ``def <name>(``; this is
    deliberately the same shape the existing module's docstring uses
    and is robust against ``async def``/decorator noise (no false
    positives on substring matches in comments because the regex
    requires the ``def `` prefix).
    """

    out: Dict[str, bool] = {}
    for name in PHASE_3B_RESOLVER_NAMES:
        # Word-boundary on the name; the trailing ``(`` ensures we hit
        # a function definition, not a comment-mention.
        pattern = rf"^def {re.escape(name)}\("
        out[name] = re.search(pattern, source, flags=re.MULTILINE) is not None
    return out


def evaluate_gate_1_phase_3b_resolvers(repo_root: Path) -> GateResult:
    """Gate-1: all 7 Phase-3b backend-resolvers wired in the switch module."""

    target = repo_root / PATH_RUST_BACKEND_SWITCH
    src = _read_text_safe(target)
    if src is None:
        return GateResult(
            id="gate-1",
            name="phase-3b-7-resolvers",
            status=GateStatus.RED,
            evidence={
                "path": str(PATH_RUST_BACKEND_SWITCH),
                "error": "file-missing",
                "expected_resolvers": list(PHASE_3B_RESOLVER_NAMES),
                "found_count": 0,
                "expected_count": len(PHASE_3B_RESOLVER_NAMES),
            },
        )
    if src.startswith("__READ_ERROR__:"):
        return GateResult(
            id="gate-1",
            name="phase-3b-7-resolvers",
            status=GateStatus.RED,
            evidence={
                "path": str(PATH_RUST_BACKEND_SWITCH),
                "error": src,
            },
        )

    resolver_presence = _count_resolver_defs(src)
    found = [n for n, ok in resolver_presence.items() if ok]
    missing = [n for n, ok in resolver_presence.items() if not ok]
    expected_count = len(PHASE_3B_RESOLVER_NAMES)
    status = GateStatus.GREEN if not missing else GateStatus.RED

    return GateResult(
        id="gate-1",
        name="phase-3b-7-resolvers",
        status=status,
        evidence={
            "path": str(PATH_RUST_BACKEND_SWITCH),
            "expected_resolvers": list(PHASE_3B_RESOLVER_NAMES),
            "found_resolvers": found,
            "missing_resolvers": missing,
            "found_count": len(found),
            "expected_count": expected_count,
        },
    )


# ---------------------------------------------------------------------------
# Gate-2: Cosign-Policy N-binary inventory
# ---------------------------------------------------------------------------


def _load_yaml_inventory(source: str) -> Optional[List[Dict[str, Any]]]:
    """Parse the cosign policy YAML and return the ``binaries`` list.

    Returns ``None`` when the YAML is unparseable OR when the
    ``binaries`` key is missing / not a list. The caller turns that
    into a ``red`` evidence record.
    """

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        # PyYAML is part of the wakir-runtime baseline (pyproject)
        # but defensively report rather than crash if absent.
        return None
    try:
        doc = yaml.safe_load(source)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict):
        return None
    binaries = doc.get("binaries")
    if not isinstance(binaries, list):
        return None
    return binaries


def evaluate_gate_2_cosign_inventory(
    repo_root: Path, target_count: int
) -> GateResult:
    """Gate-2: cosign policy lists exactly ``target_count`` binaries."""

    target = repo_root / PATH_COSIGN_POLICY
    src = _read_text_safe(target)
    if src is None or (isinstance(src, str) and src.startswith("__READ_ERROR__:")):
        return GateResult(
            id="gate-2",
            name="cosign-policy-binary-inventory",
            status=GateStatus.RED,
            evidence={
                "path": str(PATH_COSIGN_POLICY),
                "error": "file-missing" if src is None else src,
                "expected_count": target_count,
                "found_count": 0,
            },
        )

    binaries = _load_yaml_inventory(src)
    if binaries is None:
        return GateResult(
            id="gate-2",
            name="cosign-policy-binary-inventory",
            status=GateStatus.RED,
            evidence={
                "path": str(PATH_COSIGN_POLICY),
                "error": "yaml-unparseable-or-missing-binaries-key",
                "expected_count": target_count,
                "found_count": 0,
            },
        )

    binary_names = [
        str(entry.get("name", "<unnamed>"))
        for entry in binaries
        if isinstance(entry, dict)
    ]
    found_count = len(binary_names)

    if found_count == target_count:
        status = GateStatus.GREEN
    elif found_count < target_count:
        # Under-target ⇒ yellow (work-in-progress, not catastrophic).
        # The Kai Tag-24 PR is the in-flight extension; treating this
        # as yellow lets the aggregator clearly signal "not ready yet"
        # without escalating to a hard cutover-blocker.
        status = GateStatus.YELLOW
    else:
        # Over-target ⇒ red (unexpected drift; investigate before
        # cutover — extra binaries may not be policy-covered correctly).
        status = GateStatus.RED

    return GateResult(
        id="gate-2",
        name="cosign-policy-binary-inventory",
        status=status,
        evidence={
            "path": str(PATH_COSIGN_POLICY),
            "expected_count": target_count,
            "found_count": found_count,
            "binary_names": binary_names,
        },
    )


# ---------------------------------------------------------------------------
# Gate-3: Quadlet-Installer N-binary inventory
# ---------------------------------------------------------------------------


#: The Quadlet installer enumerates the binaries inside a shell ``for``
#: loop in the ``Exec=`` line. We count the ``wakir-persona-engine-*``
#: tokens — robust against the loop-syntax (no false positives on the
#: surrounding ``set -e``, ``install``, ``test`` invocations).
QUADLET_BINARY_TOKEN_RE = re.compile(r"\bwakir-persona-engine-([a-z0-9][a-z0-9-]*)\b")


def evaluate_gate_3_quadlet_inventory(
    repo_root: Path, target_count: int
) -> GateResult:
    """Gate-3: quadlet installer references exactly ``target_count`` binaries."""

    target = repo_root / PATH_QUADLET_INSTALLER
    src = _read_text_safe(target)
    if src is None or (isinstance(src, str) and src.startswith("__READ_ERROR__:")):
        return GateResult(
            id="gate-3",
            name="quadlet-installer-binary-inventory",
            status=GateStatus.RED,
            evidence={
                "path": str(PATH_QUADLET_INSTALLER),
                "error": "file-missing" if src is None else src,
                "expected_count": target_count,
                "found_count": 0,
            },
        )

    # Only count tokens that appear on the ``Exec=`` line (or anywhere
    # in the file is also fine — the installer references each binary
    # both in the Exec loop and in the file-level comment block). The
    # set() collapses duplicate mentions so the count reflects DISTINCT
    # binaries, which is what the inventory invariant is about.
    matches = QUADLET_BINARY_TOKEN_RE.findall(src)
    distinct = sorted(set(matches))
    found_count = len(distinct)

    if found_count == target_count:
        status = GateStatus.GREEN
    elif found_count < target_count:
        status = GateStatus.YELLOW
    else:
        status = GateStatus.RED

    return GateResult(
        id="gate-3",
        name="quadlet-installer-binary-inventory",
        status=status,
        evidence={
            "path": str(PATH_QUADLET_INSTALLER),
            "expected_count": target_count,
            "found_count": found_count,
            "binary_components": distinct,
        },
    )


# ---------------------------------------------------------------------------
# Gate-4: Backend-Decision-Observability baseline
# ---------------------------------------------------------------------------


_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _count_distinct_jsonl_days(jsonl_path: Path) -> int:
    """Count distinct UTC days present in the backend-decision JSONL.

    The aggregator emits records with a ``ts`` field (ISO-8601 UTC).
    Counting *distinct days* — not record count — matches the
    ADR-0065 cutover-confidence floor (seven days of operational
    evidence, regardless of boot frequency).

    Tolerant reader: lines that do not parse as JSON, or lack a ``ts``
    field, are silently ignored. We surface the *distinct day count*
    as evidence; the caller compares it against the threshold.
    """

    distinct: set[str] = set()
    try:
        with jsonl_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(rec, dict):
                    continue
                ts = rec.get("ts") or rec.get("timestamp") or rec.get("time")
                if not isinstance(ts, str):
                    continue
                m = _ISO_DATE_RE.search(ts)
                if m:
                    distinct.add(m.group(0))
    except (FileNotFoundError, OSError):
        return 0
    return len(distinct)


def _try_load_baseline_tracker(repo_root: Path):
    """Best-effort import of the Tag-25 baseline-tracker module.

    Returns the imported module, or ``None`` when the script is
    absent / fails to load. We deliberately swallow load-errors: the
    tracker is an *additive* enrichment for Gate-4; the aggregator's
    own tri-state logic must continue to work when the tracker is
    missing or broken.
    """

    tracker_path = repo_root / PATH_OBS_BASELINE_TRACKER
    if not tracker_path.is_file():
        return None
    try:
        import importlib.util
        import sys as _sys

        mod_name = "phase_3c_observability_baseline_tracker"
        cached = _sys.modules.get(mod_name)
        if cached is not None:
            return cached
        spec = importlib.util.spec_from_file_location(mod_name, tracker_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        # Register BEFORE exec_module: Python 3.12+ dataclasses look up
        # the defining module via ``sys.modules[__module__]`` during
        # class construction, so a module that defines dataclasses
        # must be present in ``sys.modules`` at exec time.
        _sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            # Roll back partial registration on failure so a subsequent
            # retry sees a clean slate.
            _sys.modules.pop(mod_name, None)
            raise
        return mod
    except Exception:
        return None


def _enrich_gate_4_with_tracker(
    evidence: Dict[str, Any],
    *,
    repo_root: Path,
    baseline_path_str: Optional[str],
    min_days: int,
) -> None:
    """Augment Gate-4 evidence with the tracker's per-component report.

    Mutates ``evidence`` in place. Silent on tracker absence/failure
    — the base Gate-4 tri-state status is the authoritative signal,
    the tracker is purely an operator-side richer view.
    """

    tracker = _try_load_baseline_tracker(repo_root)
    if tracker is None:
        return
    try:
        jsonl_path = Path(baseline_path_str) if baseline_path_str else None
        report = tracker.build_report(jsonl_path, min_days=min_days)
        evidence["tracker_report"] = report.to_dict()
    except Exception:
        # Tracker invocation must never crash the aggregator.
        return


def evaluate_gate_4_observability_baseline(
    repo_root: Path,
    *,
    env: Optional[Dict[str, str]] = None,
    min_days: int = DEFAULT_BASELINE_MIN_DAYS,
) -> GateResult:
    """Gate-4: observability aggregator present + ≥``min_days`` of baseline JSONL.

    The first sub-condition (aggregator script existence) is hard:
    missing aggregator ⇒ red. The second sub-condition (baseline
    file) is operator-hand-staged; absent ENV ⇒ yellow (skip-with-
    warning), present ENV but file missing / empty / too-few-days ⇒
    yellow with explicit evidence.
    """

    env_map = env if env is not None else os.environ

    # Sub-condition A: aggregator script must exist.
    aggregator_path = repo_root / PATH_OBS_AGGREGATOR
    aggregator_present = aggregator_path.is_file()

    # Sub-condition B: baseline path resolution.
    baseline_path_str = env_map.get(OBSERVABILITY_BASELINE_PATH_ENV)
    baseline_evidence: Dict[str, Any] = {
        "env_name": OBSERVABILITY_BASELINE_PATH_ENV,
        "env_value": baseline_path_str,
    }

    if not aggregator_present:
        evidence: Dict[str, Any] = {
            "aggregator_path": str(PATH_OBS_AGGREGATOR),
            "aggregator_present": False,
            "baseline": baseline_evidence,
            "min_days_required": min_days,
        }
        _enrich_gate_4_with_tracker(
            evidence,
            repo_root=repo_root,
            baseline_path_str=baseline_path_str,
            min_days=min_days,
        )
        return GateResult(
            id="gate-4",
            name="backend-decision-observability-baseline",
            status=GateStatus.RED,
            evidence=evidence,
        )

    if not baseline_path_str:
        # ENV unset — skip-with-warning per the operator-hand workflow.
        baseline_evidence["reason"] = "env-not-set"
        evidence = {
            "aggregator_path": str(PATH_OBS_AGGREGATOR),
            "aggregator_present": True,
            "baseline": baseline_evidence,
            "min_days_required": min_days,
            "baseline_days_found": 0,
        }
        _enrich_gate_4_with_tracker(
            evidence,
            repo_root=repo_root,
            baseline_path_str=baseline_path_str,
            min_days=min_days,
        )
        return GateResult(
            id="gate-4",
            name="backend-decision-observability-baseline",
            status=GateStatus.YELLOW,
            evidence=evidence,
        )

    baseline_path = Path(baseline_path_str)
    if not baseline_path.is_file():
        baseline_evidence["reason"] = "file-not-found"
        evidence = {
            "aggregator_path": str(PATH_OBS_AGGREGATOR),
            "aggregator_present": True,
            "baseline": baseline_evidence,
            "min_days_required": min_days,
            "baseline_days_found": 0,
        }
        _enrich_gate_4_with_tracker(
            evidence,
            repo_root=repo_root,
            baseline_path_str=baseline_path_str,
            min_days=min_days,
        )
        return GateResult(
            id="gate-4",
            name="backend-decision-observability-baseline",
            status=GateStatus.YELLOW,
            evidence=evidence,
        )

    days_found = _count_distinct_jsonl_days(baseline_path)
    baseline_evidence["reason"] = (
        "baseline-too-short" if days_found < min_days else "baseline-meets-threshold"
    )

    status = GateStatus.GREEN if days_found >= min_days else GateStatus.YELLOW

    evidence = {
        "aggregator_path": str(PATH_OBS_AGGREGATOR),
        "aggregator_present": True,
        "baseline": baseline_evidence,
        "min_days_required": min_days,
        "baseline_days_found": days_found,
    }
    _enrich_gate_4_with_tracker(
        evidence,
        repo_root=repo_root,
        baseline_path_str=baseline_path_str,
        min_days=min_days,
    )
    return GateResult(
        id="gate-4",
        name="backend-decision-observability-baseline",
        status=status,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Gate-5: Live-VM-Acceptance Driver existence
# ---------------------------------------------------------------------------


def evaluate_gate_5_live_vm_driver(repo_root: Path) -> GateResult:
    """Gate-5: Phase-3b live-VM-acceptance driver script is present + executable-bit set."""

    target = repo_root / PATH_LIVE_VM_DRIVER
    if not target.is_file():
        return GateResult(
            id="gate-5",
            name="live-vm-acceptance-driver",
            status=GateStatus.RED,
            evidence={
                "path": str(PATH_LIVE_VM_DRIVER),
                "exists": False,
                "executable": False,
            },
        )

    # The Phase-3b live-VM-acceptance workflow shells out via
    # ``if [[ -x "${DRIVER}" ]]; then``. A non-executable driver would
    # silently fall back to the workflow-side stub, which would let
    # Phase-3c proceed on stub-data. Flag that as a yellow.
    executable = os.access(target, os.X_OK)

    return GateResult(
        id="gate-5",
        name="live-vm-acceptance-driver",
        status=GateStatus.GREEN if executable else GateStatus.YELLOW,
        evidence={
            "path": str(PATH_LIVE_VM_DRIVER),
            "exists": True,
            "executable": executable,
        },
    )


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def aggregate(
    repo_root: Path,
    *,
    target_binary_count: int = DEFAULT_TARGET_BINARY_COUNT,
    env: Optional[Dict[str, str]] = None,
    min_baseline_days: int = DEFAULT_BASELINE_MIN_DAYS,
) -> AggregatorReport:
    """Run all five trigger-gate evaluators and assemble the report."""

    gates: List[GateResult] = [
        evaluate_gate_1_phase_3b_resolvers(repo_root),
        evaluate_gate_2_cosign_inventory(repo_root, target_binary_count),
        evaluate_gate_3_quadlet_inventory(repo_root, target_binary_count),
        evaluate_gate_4_observability_baseline(
            repo_root, env=env, min_days=min_baseline_days
        ),
        evaluate_gate_5_live_vm_driver(repo_root),
    ]
    all_green = all(g.status is GateStatus.GREEN for g in gates)
    return AggregatorReport(
        gates=gates,
        all_green=all_green,
        ready_for_phase_3c=all_green,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_human(report: AggregatorReport) -> str:
    """Render the report as a human-readable summary."""

    lines: List[str] = []
    lines.append("Phase-3c Trigger-Gate Aggregator")
    lines.append("=" * 64)
    for g in report.gates:
        marker = {
            GateStatus.GREEN: "[OK]",
            GateStatus.YELLOW: "[WARN]",
            GateStatus.RED: "[FAIL]",
        }[g.status]
        lines.append(f"  {marker:7s} {g.id}  {g.name}")
        ev = g.evidence
        if "found_count" in ev and "expected_count" in ev:
            lines.append(
                f"            inventory: {ev['found_count']}/{ev['expected_count']}"
            )
        if "missing_resolvers" in ev and ev["missing_resolvers"]:
            lines.append(f"            missing: {', '.join(ev['missing_resolvers'])}")
        if "baseline" in ev:
            base = ev["baseline"]
            lines.append(
                f"            baseline_days: {ev.get('baseline_days_found', 0)}"
                f"/{ev.get('min_days_required', 0)}"
                f"  reason: {base.get('reason', '<n/a>')}"
            )
        if "executable" in ev:
            lines.append(f"            executable: {ev['executable']}")
    lines.append("-" * 64)
    verdict = "READY" if report.ready_for_phase_3c else "NOT-READY"
    lines.append(f"  Phase-3c: {verdict}  (all_green={report.all_green})")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phase-3c-trigger-gate-aggregator",
        description="Aggregate the five Phase-3c trigger-gates into a go/no-go report.",
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: parent of scripts/).",
    )
    p.add_argument(
        "--target-binary-count",
        type=int,
        default=DEFAULT_TARGET_BINARY_COUNT,
        help="Expected Rust-CLI binary inventory size for gates 2 + 3.",
    )
    p.add_argument(
        "--min-baseline-days",
        type=int,
        default=DEFAULT_BASELINE_MIN_DAYS,
        help="Distinct-day floor for gate-4 observability baseline.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human summary.",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    else:
        repo_root = args.repo_root.resolve()

    report = aggregate(
        repo_root,
        target_binary_count=args.target_binary_count,
        min_baseline_days=args.min_baseline_days,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_format_human(report))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
