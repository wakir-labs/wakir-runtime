#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Cross-repo sync audit — wakir-runtime <-> wakir-protocol (Tag-42, Reza).

Local-first companion to the CI tripwire workflow
`.github/workflows/cross-repo-drift-audit.yml`.

Purpose
=======

The CI workflow runs on every push/PR. This script provides the same
audit logic for *local* and *pre-CI* execution — Reza+Tomás
Cross-Review-Zone-3 (OTS-Schema-Anker compatibility) needs an off-CI
hand they can run against a cloned `wakir-protocol` worktree, on a
flight without GitHub access, and as a regression fixture for
hermetic tests.

The script is **stdlib-only** by design (matches Reza Tag-31
EXT-AUDIT-FOLGE allowlist-loader posture): no PyYAML, no requests,
no third-party deps. It will not pull the protocol repo over the
network — the caller passes `--protocol-root` pointing at an already-
checked-out wakir-protocol worktree. This keeps the script
hermetic-testable and offline-runnable.

What it audits
==============

Four substance classes, mirroring ADR-0062 Cut-2 surface:

  1. Wirelang Layer-0..3 JSON schemas
       wirelang/schemas/layer-{0,1,2,3}-*.json
       <-> wakir_protocol/schemas/layer-{0,1,2,3}-*.json
       (byte-identical, modulo allowlist)

  2. AIP-Document spec mirror
       wirelang/schemas/aip-document.json
       wirelang/identity/aip_document.py
       wirelang/identity/dns_anchor.py
       <-> wakir_protocol counterparts under
           wakir_protocol/schemas/ and wakir_protocol/identity_substrate/

  3. Capability-Token mirror
       wirelang/schemas/layer-3-capability-token.json
       wirelang/schemas/datalog-caveat.json
       wirelang/canonical/caveat_set.py
       <-> wakir_protocol counterparts.

  4. ADR-0066-Welle-Substanz cross-repo doc-consistency
       The 7 Welle-Substanz items (Smoke + Runbook + Validation +
       Phase-3a-Modul-Refs) live in runtime as
       `scripts/phase-3c/welle-N-...` /
       `docs/phase-3c/welle-N-...` /
       `.github/workflows/phase-3c-welle-N-validation.yml`.
       The protocol repo, per Cut-2, does NOT mirror runtime
       operational artefacts byte-for-byte — but it MUST document
       the welle inventory consistently in a top-level reference
       (default `docs/welle-substance.md`).

       Item 4 therefore checks (a) all 7 welles have the runtime
       triad (smoke + runbook + validation workflow + Phase-3a
       module references) present, and (b) the protocol-side
       welle-substance.md (if present) names each welle by canonical
       id — a *consistency* check, not a byte-mirror check. The
       protocol counterpart is optional in audit-only mode; a
       missing protocol file is reported as `info` (not drift),
       respecting the Cut-2 boundary.

Exit codes
==========

  0 = clean (or drift, allowlisted, in audit-only mode)
  0 = audit-only mode with un-allowlisted drift (warn only)
  1 = enforce-mode with un-allowlisted drift OR enforce-mode with
      missing-on-either-side OR malformed allowlist in enforce-mode
  2 = invocation error (missing --protocol-root, paths not found)

Output
======

  stdout: human-readable summary block (same shape as the CI job
          summary table).
  --report-path: optional markdown report written to the given path.
                 If the path is `reports/cross-repo-audit/<DATE>-runtime-protocol-sync.md`,
                 it matches the Tag-42 deliverable contract.
  --json: optional JSON tally dump, for downstream tooling /
          dashboard tracking.

Allowlist
=========

Read from `.cross-repo-drift-allowlist.yaml` at the runtime repo
root. PyYAML is NOT available (stdlib-only constraint), so we
implement a *minimal* YAML subset parser sufficient for the
documented allowlist format:

  allow: []
  # OR
  allow:
    - runtime: <path>
      protocol: <path>
      reason: <free text>
      follow_up: <optional>

If the file declares anything beyond `allow: <list of mappings with
runtime+protocol keys>`, we report `__MALFORMED__` and treat the
allowlist as empty (audit-only mirrors the CI workflow's soft-fail).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import pathlib
import re
import sys
from typing import Iterable, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Mirror-pair table — kept in sync with
# .github/workflows/cross-repo-drift-audit.yml `pairs=( ... )`.
#
# When adding rows, update BOTH the workflow and this table — Reza
# Tag-42 Cross-Review-Zone-3 contract.
#
# Format: (runtime_relative_path, protocol_relative_path, substance_class)
# substance_class is one of:
#   "layer-0..3-schema", "aip", "capability", "identity-substrate".
# ---------------------------------------------------------------------------

class MirrorPair(NamedTuple):
    runtime_path: str
    protocol_path: str
    substance_class: str


MIRROR_PAIRS: tuple[MirrorPair, ...] = (
    # ----- Wirelang Layer-0..3 schemas (substance class 1) -----
    MirrorPair(
        "wirelang/schemas/layer-0-transport.json",
        "wakir_protocol/schemas/layer-0-transport.json",
        "layer-0-schema",
    ),
    MirrorPair(
        "wirelang/schemas/layer-1-wire.json",
        "wakir_protocol/schemas/layer-1-wire.json",
        "layer-1-schema",
    ),
    MirrorPair(
        "wirelang/schemas/layer-2-semantic.json",
        "wakir_protocol/schemas/layer-2-semantic.json",
        "layer-2-schema",
    ),
    MirrorPair(
        "wirelang/schemas/layer-3-capability-token.json",
        "wakir_protocol/schemas/layer-3-capability-token.json",
        "layer-3-schema",
    ),
    # ----- AIP-Document spec mirror (substance class 2) -----
    MirrorPair(
        "wirelang/schemas/aip-document.json",
        "wakir_protocol/schemas/aip-document.json",
        "aip",
    ),
    MirrorPair(
        "wirelang/identity/aip_document.py",
        "wakir_protocol/identity_substrate/aip_document.py",
        "aip",
    ),
    MirrorPair(
        "wirelang/identity/dns_anchor.py",
        "wakir_protocol/identity_substrate/dns_anchor.py",
        "aip",
    ),
    # ----- Capability-Token mirror (substance class 3) -----
    MirrorPair(
        "wirelang/schemas/datalog-caveat.json",
        "wakir_protocol/schemas/datalog-caveat.json",
        "capability",
    ),
    MirrorPair(
        "wirelang/schemas/federation-trust-document.json",
        "wakir_protocol/schemas/federation-trust-document.json",
        "capability",
    ),
    MirrorPair(
        "wirelang/canonical/caveat_set.py",
        "wakir_protocol/canonical/caveat_set.py",
        "capability",
    ),
)


# ---------------------------------------------------------------------------
# ADR-0066 Welle inventory — substance class 4.
#
# Each welle has a runtime *triad*: cutover-smoke script, runbook
# (operations doc), validation GitHub-Actions workflow. Phase-3a
# module references are the bridge to the wirelang implementation
# crate / Python package.
#
# `protocol_doc_token` is the canonical id the protocol-side
# welle-substance.md is expected to mention (case-insensitive,
# substring match). The check is intentionally lax: a missing
# token on the protocol side is `info`, not `drift` — Cut-2
# does not require byte-mirroring of operational artefacts.
# ---------------------------------------------------------------------------

class WelleSubstance(NamedTuple):
    welle: int
    smoke_script: str
    runbook: str
    validation_workflow: str
    phase_3a_modules: tuple[str, ...]
    protocol_doc_token: str


WELLE_INVENTORY: tuple[WelleSubstance, ...] = (
    WelleSubstance(
        welle=1,
        smoke_script="scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py",
        runbook="docs/phase-3c/welle-1-v907-verify-runbook.md",
        validation_workflow=".github/workflows/phase-3c-welle-1-validation.yml",
        phase_3a_modules=("wirelang/persona_engine",),
        protocol_doc_token="welle-1",
    ),
    WelleSubstance(
        welle=2,
        smoke_script="scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py",
        runbook="docs/phase-3c/welle-2-svid-workload-identity-runbook.md",
        validation_workflow=".github/workflows/phase-3c-welle-2-validation.yml",
        phase_3a_modules=("wirelang/identity",),
        protocol_doc_token="welle-2",
    ),
    WelleSubstance(
        welle=3,
        smoke_script="scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py",
        runbook="docs/phase-3c/welle-3-bridge-audit-writer-runbook.md",
        validation_workflow=".github/workflows/phase-3c-welle-3-validation.yml",
        phase_3a_modules=("wirelang/bridge",),
        protocol_doc_token="welle-3",
    ),
    WelleSubstance(
        welle=4,
        smoke_script="scripts/phase-3c/welle-4-state-backing-cutover-smoke.py",
        runbook="docs/operations/phase-3c-welle-4-runbook.md",
        validation_workflow=".github/workflows/phase-3c-welle-4-validation.yml",
        phase_3a_modules=("wirelang/nats", "wirelang/federation"),
        protocol_doc_token="welle-4",
    ),
    WelleSubstance(
        welle=5,
        smoke_script="scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py",
        runbook="docs/operations/phase-3c-welle-5-runbook.md",
        validation_workflow=".github/workflows/phase-3c-welle-5-validation.yml",
        phase_3a_modules=("wirelang/persona", "wirelang/persona_engine"),
        protocol_doc_token="welle-5",
    ),
    WelleSubstance(
        welle=6,
        smoke_script="scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py",
        runbook="docs/operations/phase-3c-welle-6-runbook.md",
        validation_workflow=".github/workflows/phase-3c-welle-6-validation.yml",
        phase_3a_modules=("wirelang/nats",),
        protocol_doc_token="welle-6",
    ),
    WelleSubstance(
        welle=7,
        smoke_script="scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py",
        runbook="docs/operations/phase-3c-welle-7-runbook.md",
        validation_workflow=".github/workflows/phase-3c-welle-7-validation.yml",
        phase_3a_modules=("wirelang/identity",),
        protocol_doc_token="welle-7",
    ),
)


# ---------------------------------------------------------------------------
# Stdlib-only minimal YAML subset for `.cross-repo-drift-allowlist.yaml`.
#
# Accepts ONLY the documented shape:
#   allow: []
#   # OR
#   allow:
#     - runtime: <path>
#       protocol: <path>
#       reason: <free text>           # ignored (not load-bearing for audit)
#       follow_up: <free text>        # ignored
#
# Anything else => returns the sentinel "__MALFORMED__".
# ---------------------------------------------------------------------------

_ALLOWED_KEYS = {"runtime", "protocol", "reason", "follow_up"}


def parse_allowlist(text: str) -> list[tuple[str, str]] | str:
    """
    Return list of (runtime_path, protocol_path) tuples, or the
    sentinel string "__MALFORMED__" if the file does not match the
    documented shape.

    The parser is intentionally minimal — it does not handle YAML
    anchors, flow-style mappings, multi-line scalars, etc. The CI
    workflow's allowlist loader uses PyYAML but treats malformed
    input identically (drop to empty list with a warning).
    """
    lines = text.splitlines()
    # Strip BOM, normalize.
    cleaned: list[tuple[int, str]] = []
    for raw_idx, raw in enumerate(lines, start=1):
        # Strip comments first (only when `#` is preceded by
        # whitespace or starts the line — avoids stripping `#` from
        # inside quoted scalars, of which we accept none anyway).
        stripped = raw.rstrip()
        # Cut comments
        if "#" in stripped:
            # Cut at the first `#` that is at column 0 OR has a
            # space before it.
            hash_idx = -1
            for i, ch in enumerate(stripped):
                if ch == "#" and (i == 0 or stripped[i - 1].isspace()):
                    hash_idx = i
                    break
            if hash_idx >= 0:
                stripped = stripped[:hash_idx].rstrip()
        if stripped == "":
            continue
        cleaned.append((raw_idx, stripped))

    if not cleaned:
        # Empty file => no waivers.
        return []

    # First non-empty non-comment line must be `allow:` or `allow: []`.
    first_line = cleaned[0][1]
    m_inline = re.match(r"^allow\s*:\s*\[\s*\]\s*$", first_line)
    if m_inline:
        if len(cleaned) > 1:
            return "__MALFORMED__"
        return []

    if not re.match(r"^allow\s*:\s*$", first_line):
        return "__MALFORMED__"

    # Remaining lines must form list-of-mappings.
    entries: list[dict[str, str]] = []
    current: Optional[dict[str, str]] = None
    for _idx, line in cleaned[1:]:
        # List-item marker — open a new entry.
        m_item = re.match(r"^\s*-\s+(\w+)\s*:\s*(.*)$", line)
        if m_item:
            key = m_item.group(1)
            value = m_item.group(2).strip()
            if key not in _ALLOWED_KEYS:
                return "__MALFORMED__"
            if current is not None:
                entries.append(current)
            current = {key: value}
            continue
        # Continuation key on existing item.
        m_kv = re.match(r"^\s+(\w+)\s*:\s*(.*)$", line)
        if m_kv and current is not None:
            key = m_kv.group(1)
            value = m_kv.group(2).strip()
            if key not in _ALLOWED_KEYS:
                return "__MALFORMED__"
            current[key] = value
            continue
        return "__MALFORMED__"
    if current is not None:
        entries.append(current)

    out: list[tuple[str, str]] = []
    for e in entries:
        r = e.get("runtime", "")
        p = e.get("protocol", "")
        if not r or not p:
            return "__MALFORMED__"
        out.append((r, p))
    return out


# ---------------------------------------------------------------------------
# Mirror-pair drift detection.
# ---------------------------------------------------------------------------

def _sha256_of_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class PairResult(NamedTuple):
    runtime_path: str
    protocol_path: str
    substance_class: str
    status: str               # "ok" | "DRIFT" | "drift-allowed"
                              # | "missing-runtime" | "missing-protocol"
                              # | "missing-both"
    runtime_sha256: str       # "" if missing
    protocol_sha256: str      # "" if missing


def audit_mirror_pairs(
    runtime_root: pathlib.Path,
    protocol_root: pathlib.Path,
    allowlist: list[tuple[str, str]],
    pairs: Iterable[MirrorPair] = MIRROR_PAIRS,
) -> list[PairResult]:
    """
    Compute drift status for each mirror pair.

    The allowlist is matched by the *exact* (runtime, protocol)
    tuple. A drift with no matching allowlist entry is reported as
    `DRIFT`; a drift with a matching entry is `drift-allowed`.
    """
    allowset = set(allowlist)
    results: list[PairResult] = []
    for pair in pairs:
        runtime_abs = runtime_root / pair.runtime_path
        protocol_abs = protocol_root / pair.protocol_path

        r_present = runtime_abs.is_file()
        p_present = protocol_abs.is_file()

        runtime_sha = _sha256_of_file(runtime_abs) if r_present else ""
        protocol_sha = _sha256_of_file(protocol_abs) if p_present else ""

        if not r_present and not p_present:
            status = "missing-both"
        elif not r_present:
            status = "missing-runtime"
        elif not p_present:
            status = "missing-protocol"
        elif runtime_sha == protocol_sha:
            status = "ok"
        else:
            if (pair.runtime_path, pair.protocol_path) in allowset:
                status = "drift-allowed"
            else:
                status = "DRIFT"

        results.append(
            PairResult(
                runtime_path=pair.runtime_path,
                protocol_path=pair.protocol_path,
                substance_class=pair.substance_class,
                status=status,
                runtime_sha256=runtime_sha,
                protocol_sha256=protocol_sha,
            )
        )
    return results


# ---------------------------------------------------------------------------
# ADR-0066 Welle-Substanz consistency audit.
# ---------------------------------------------------------------------------

class WelleResult(NamedTuple):
    welle: int
    smoke_present: bool
    runbook_present: bool
    validation_workflow_present: bool
    phase_3a_modules_present: tuple[bool, ...]
    protocol_doc_mentions_welle: Optional[bool]  # None => protocol doc absent
    overall_status: str  # "ok" | "incomplete-runtime" | "consistent-runtime-only"


def audit_welle_inventory(
    runtime_root: pathlib.Path,
    protocol_welle_doc: Optional[pathlib.Path],
    inventory: Iterable[WelleSubstance] = WELLE_INVENTORY,
) -> list[WelleResult]:
    """
    For each welle, verify the runtime triad is present and (if the
    protocol-side welle-substance doc exists) that the welle is
    named there.

    A missing protocol doc is `consistent-runtime-only` for any
    runtime-complete welle — this is the Cut-2 boundary, not drift.
    """
    protocol_doc_text: Optional[str] = None
    if protocol_welle_doc is not None and protocol_welle_doc.is_file():
        try:
            protocol_doc_text = protocol_welle_doc.read_text(encoding="utf-8")
        except OSError:
            protocol_doc_text = None

    results: list[WelleResult] = []
    for w in inventory:
        smoke = (runtime_root / w.smoke_script).is_file()
        runbook = (runtime_root / w.runbook).is_file()
        wf = (runtime_root / w.validation_workflow).is_file()
        modules = tuple(
            (runtime_root / m).is_dir() for m in w.phase_3a_modules
        )

        runtime_complete = smoke and runbook and wf and all(modules)

        if protocol_doc_text is None:
            protocol_mention: Optional[bool] = None
        else:
            protocol_mention = (
                w.protocol_doc_token.lower() in protocol_doc_text.lower()
            )

        if not runtime_complete:
            overall = "incomplete-runtime"
        elif protocol_mention is None:
            overall = "consistent-runtime-only"
        elif protocol_mention:
            overall = "ok"
        else:
            overall = "protocol-doc-missing-mention"

        results.append(
            WelleResult(
                welle=w.welle,
                smoke_present=smoke,
                runbook_present=runbook,
                validation_workflow_present=wf,
                phase_3a_modules_present=modules,
                protocol_doc_mentions_welle=protocol_mention,
                overall_status=overall,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Report rendering.
# ---------------------------------------------------------------------------

def render_markdown_report(
    pair_results: list[PairResult],
    welle_results: list[WelleResult],
    runtime_root: pathlib.Path,
    protocol_root: pathlib.Path,
    protocol_head: str,
    runtime_head: str,
    enforce: bool,
    allowlist_malformed: bool,
    report_date: str,
) -> str:
    """
    Produce the markdown drift-report intended for
    `reports/cross-repo-audit/<DATE>-runtime-protocol-sync.md`.
    """
    ok = sum(1 for r in pair_results if r.status == "ok")
    drift = sum(1 for r in pair_results if r.status == "DRIFT")
    allowed = sum(1 for r in pair_results if r.status == "drift-allowed")
    missing = sum(
        1 for r in pair_results
        if r.status in ("missing-runtime", "missing-protocol", "missing-both")
    )

    welle_ok = sum(1 for w in welle_results if w.overall_status == "ok")
    welle_runtime_only = sum(
        1 for w in welle_results
        if w.overall_status == "consistent-runtime-only"
    )
    welle_incomplete = sum(
        1 for w in welle_results if w.overall_status == "incomplete-runtime"
    )
    welle_missing_mention = sum(
        1 for w in welle_results
        if w.overall_status == "protocol-doc-missing-mention"
    )

    out: list[str] = []
    out.append("<!--")
    out.append("SPDX-License-Identifier: CC-BY-4.0")
    out.append("Copyright (c) 2026 Callandor GmbH and contributors")
    out.append("-->")
    out.append("")
    out.append(f"# Cross-repo sync audit — {report_date}")
    out.append("")
    out.append("Tag-42 Reza Cross-Repo-Sync-Audit between `wakir-runtime`")
    out.append("(BUSL-dominant) and `wakir-protocol` (Apache-2.0 + CC-BY-4.0).")
    out.append("")
    out.append("## Audit baselines")
    out.append("")
    out.append(f"- Runtime root: `{runtime_root}`")
    out.append(f"- Runtime HEAD: `{runtime_head}`")
    out.append(f"- Protocol root: `{protocol_root}`")
    out.append(f"- Protocol HEAD: `{protocol_head}`")
    out.append(f"- Enforce mode: `{enforce}`")
    out.append(f"- Allowlist status: "
               f"`{'MALFORMED' if allowlist_malformed else 'ok'}`")
    out.append("")

    out.append("## Mirror-pair drift table (substance class 1-3)")
    out.append("")
    out.append("| Status | Class | Runtime | Protocol | r-SHA | p-SHA |")
    out.append("|---|---|---|---|---|---|")
    for r in pair_results:
        rsha = r.runtime_sha256[:12] if r.runtime_sha256 else "—"
        psha = r.protocol_sha256[:12] if r.protocol_sha256 else "—"
        out.append(
            f"| {r.status} | {r.substance_class} | "
            f"`{r.runtime_path}` | `{r.protocol_path}` | "
            f"`{rsha}` | `{psha}` |"
        )
    out.append("")
    out.append("### Mirror-pair tally")
    out.append("")
    out.append(f"- ok: {ok}")
    out.append(f"- drift (un-allowlisted): {drift}")
    out.append(f"- drift (allowlisted): {allowed}")
    out.append(f"- missing on either side: {missing}")
    out.append("")

    out.append("## ADR-0066 Welle-Substanz consistency (class 4)")
    out.append("")
    out.append("| Welle | Smoke | Runbook | Validation WF | Modules | Protocol mention | Status |")
    out.append("|---|---|---|---|---|---|---|")
    for w in welle_results:
        modules_str = "/".join("Y" if m else "N" for m in w.phase_3a_modules_present) \
            if w.phase_3a_modules_present else "—"
        mention = (
            "—" if w.protocol_doc_mentions_welle is None
            else ("Y" if w.protocol_doc_mentions_welle else "N")
        )
        out.append(
            f"| {w.welle} | "
            f"{'Y' if w.smoke_present else 'N'} | "
            f"{'Y' if w.runbook_present else 'N'} | "
            f"{'Y' if w.validation_workflow_present else 'N'} | "
            f"{modules_str} | "
            f"{mention} | "
            f"{w.overall_status} |"
        )
    out.append("")
    out.append("### Welle tally")
    out.append("")
    out.append(f"- ok (runtime-complete + protocol-mentioned): {welle_ok}")
    out.append(f"- consistent (runtime-complete, protocol doc absent): "
               f"{welle_runtime_only}")
    out.append(f"- protocol-doc-missing-mention: {welle_missing_mention}")
    out.append(f"- incomplete runtime triad: {welle_incomplete}")
    out.append("")

    # Recommendations.
    out.append("## Recommended mirror-sync actions")
    out.append("")
    if drift == 0 and missing == 0 and welle_incomplete == 0 \
       and welle_missing_mention == 0:
        out.append("- No actions required. Cross-repo sync is clean for the")
        out.append("  audited surface. Re-verify before each Tag-N closeout.")
    else:
        if drift > 0:
            out.append(f"- Resolve {drift} un-allowlisted drift item(s) by")
            out.append("  either lifting the runtime change into the protocol")
            out.append("  repo (1-way mirror sync) or admitting an allowlist")
            out.append("  entry in `.cross-repo-drift-allowlist.yaml` with a")
            out.append("  named reason and follow-up reference.")
        if missing > 0:
            out.append(f"- {missing} pair(s) have a missing counterpart on")
            out.append("  one side. Inspect whether this is a rename in")
            out.append("  flight (update both `MIRROR_PAIRS` and the workflow)")
            out.append("  or an unintended removal (restore + sync).")
        if welle_incomplete > 0:
            out.append(f"- {welle_incomplete} welle(s) have an incomplete")
            out.append("  runtime triad (smoke + runbook + validation +")
            out.append("  Phase-3a modules). Patch the welle inventory before")
            out.append("  flipping `CROSS_REPO_DRIFT_ENFORCE=true`.")
        if welle_missing_mention > 0:
            out.append(f"- {welle_missing_mention} welle(s) are runtime-complete")
            out.append("  but absent from the protocol-side welle-substance")
            out.append("  doc. This is an info-level finding (Cut-2 does not")
            out.append("  require operational-artefact byte-mirror), but for")
            out.append("  external-auditor readiness the protocol doc should")
            out.append("  enumerate all 7 welles by canonical id.")
    out.append("")

    out.append("## Phase-3-Marathon cross-repo readiness")
    out.append("")
    readiness_blocked = (drift > 0 or missing > 0
                        or welle_incomplete > 0 or allowlist_malformed)
    if not readiness_blocked:
        out.append("- Status: **READY** for Phase-3-Marathon (no blocking")
        out.append("  drift, no missing pairs, runtime triads complete).")
    else:
        out.append("- Status: **BLOCKED** until the recommended actions above")
        out.append("  close the cross-repo deltas. Re-run this audit after")
        out.append("  each remediation PR; record the new clean baseline in")
        out.append("  `docs/operations/cross-repo-drift-mirror-pair-status.md`.")
    out.append("")
    out.append("## Cross-references")
    out.append("")
    out.append("- ADR-0062 Cut-2 protocol-substance classification")
    out.append("  (`docs/decisions/cut2-protocol-substance-classification.md`)")
    out.append("- ADR-0066 Welle-Substanz roadmap")
    out.append("- `.github/workflows/cross-repo-drift-audit.yml` (CI tripwire,")
    out.append("  audit-only at the time of this report)")
    out.append("- `.cross-repo-drift-allowlist.yaml` (CI allowlist)")
    out.append("- `docs/operations/cross-repo-drift-runbook.md`")
    out.append("- `docs/operations/cross-repo-drift-mirror-pair-status.md`")
    out.append("")
    out.append("— Reza")
    out.append("")
    return "\n".join(out)


def summarize_to_stdout(
    pair_results: list[PairResult],
    welle_results: list[WelleResult],
    enforce: bool,
    allowlist_malformed: bool,
) -> None:
    ok = sum(1 for r in pair_results if r.status == "ok")
    drift = sum(1 for r in pair_results if r.status == "DRIFT")
    allowed = sum(1 for r in pair_results if r.status == "drift-allowed")
    missing = sum(
        1 for r in pair_results
        if r.status in ("missing-runtime", "missing-protocol", "missing-both")
    )
    welle_ok = sum(1 for w in welle_results if w.overall_status == "ok")
    welle_runtime_only = sum(
        1 for w in welle_results
        if w.overall_status == "consistent-runtime-only"
    )
    welle_incomplete = sum(
        1 for w in welle_results if w.overall_status == "incomplete-runtime"
    )
    welle_missing_mention = sum(
        1 for w in welle_results
        if w.overall_status == "protocol-doc-missing-mention"
    )

    print("cross-repo-sync-audit (Tag-42, Reza)")
    print(f"  enforce={enforce} allowlist_malformed={allowlist_malformed}")
    print(f"  mirror-pairs: ok={ok} drift={drift} allowed={allowed} missing={missing}")
    print(f"  welle-substance: ok={welle_ok} runtime-only={welle_runtime_only} "
          f"missing-mention={welle_missing_mention} incomplete={welle_incomplete}")
    for r in pair_results:
        if r.status not in ("ok", "drift-allowed"):
            print(f"    !! {r.status}: {r.runtime_path} <> {r.protocol_path}")
    for w in welle_results:
        if w.overall_status in ("incomplete-runtime", "protocol-doc-missing-mention"):
            print(f"    !! welle-{w.welle}: {w.overall_status}")


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def _utc_date_str() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def _git_head_short(repo_root: pathlib.Path) -> str:
    """
    Read `.git/HEAD` (and ref file if symbolic) without invoking git.
    Returns a 12-char hex prefix or `unknown`.
    """
    head_file = repo_root / ".git" / "HEAD"
    # git worktrees have `.git` as a *file* pointing to the real
    # gitdir — handle both shapes.
    git_dir: Optional[pathlib.Path] = None
    git_dot = repo_root / ".git"
    if git_dot.is_dir():
        git_dir = git_dot
    elif git_dot.is_file():
        try:
            content = git_dot.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                gd = content.split(":", 1)[1].strip()
                git_dir = pathlib.Path(gd)
                if not git_dir.is_absolute():
                    git_dir = (repo_root / git_dir).resolve()
        except OSError:
            git_dir = None
    if git_dir is None:
        return "unknown"
    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        return "unknown"
    try:
        head = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        # Try in main gitdir first; in worktrees, refs live in the
        # common directory pointed to by `commondir`.
        candidates = [git_dir / ref]
        commondir_file = git_dir / "commondir"
        if commondir_file.is_file():
            try:
                cd = commondir_file.read_text(encoding="utf-8").strip()
                cd_path = pathlib.Path(cd)
                if not cd_path.is_absolute():
                    cd_path = (git_dir / cd_path).resolve()
                candidates.append(cd_path / ref)
            except OSError:
                pass
        for c in candidates:
            if c.is_file():
                try:
                    return c.read_text(encoding="utf-8").strip()[:12]
                except OSError:
                    continue
        # Packed-refs fallback.
        for base in [git_dir, *(
            [pathlib.Path(commondir_file.read_text(encoding="utf-8").strip())]
            if commondir_file.is_file() else []
        )]:
            packed = base / "packed-refs"
            if packed.is_file():
                try:
                    for line in packed.read_text(encoding="utf-8").splitlines():
                        if line.endswith(" " + ref):
                            return line.split(" ", 1)[0][:12]
                except OSError:
                    continue
        return "unknown"
    return head[:12] if head else "unknown"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-repo sync audit between wakir-runtime and "
            "wakir-protocol (Tag-42, Reza, stdlib-only)."
        ),
    )
    parser.add_argument(
        "--runtime-root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
        help="Path to the wakir-runtime worktree (default: cwd).",
    )
    parser.add_argument(
        "--protocol-root",
        type=pathlib.Path,
        required=False,
        help=(
            "Path to a checked-out wakir-protocol worktree. "
            "Required for full audit; if omitted, only the runtime-"
            "side welle-triad check runs and mirror-pairs are "
            "reported as missing-protocol."
        ),
    )
    parser.add_argument(
        "--protocol-welle-doc",
        type=str,
        default="docs/welle-substance.md",
        help=(
            "Protocol-relative path to the welle-substance doc "
            "(default: docs/welle-substance.md). Used only for the "
            "class-4 consistency check."
        ),
    )
    parser.add_argument(
        "--allowlist",
        type=pathlib.Path,
        default=None,
        help=(
            "Path to .cross-repo-drift-allowlist.yaml "
            "(default: <runtime-root>/.cross-repo-drift-allowlist.yaml)."
        ),
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help=(
            "Enforce mode: exit non-zero on un-allowlisted drift or "
            "missing pairs. Audit-only (default) exits 0 unless the "
            "invocation itself failed."
        ),
    )
    parser.add_argument(
        "--report-path",
        type=pathlib.Path,
        default=None,
        help=(
            "Optional path to write a markdown drift report "
            "(suggested: reports/cross-repo-audit/"
            "<date>-runtime-protocol-sync.md)."
        ),
    )
    parser.add_argument(
        "--json",
        type=pathlib.Path,
        default=None,
        help="Optional path to dump JSON tally for downstream tooling.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override report date (YYYY-MM-DD); default: today UTC.",
    )

    args = parser.parse_args(argv)

    runtime_root: pathlib.Path = args.runtime_root.resolve()
    if not runtime_root.is_dir():
        print(f"error: --runtime-root not a directory: {runtime_root}",
              file=sys.stderr)
        return 2

    protocol_root: Optional[pathlib.Path] = None
    if args.protocol_root is not None:
        protocol_root = args.protocol_root.resolve()
        if not protocol_root.is_dir():
            print(f"error: --protocol-root not a directory: {protocol_root}",
                  file=sys.stderr)
            return 2

    allowlist_file = (
        args.allowlist
        if args.allowlist is not None
        else runtime_root / ".cross-repo-drift-allowlist.yaml"
    )

    allowlist: list[tuple[str, str]]
    allowlist_malformed = False
    if allowlist_file.is_file():
        try:
            text = allowlist_file.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"warning: cannot read allowlist {allowlist_file}: {exc}",
                  file=sys.stderr)
            allowlist = []
        else:
            parsed = parse_allowlist(text)
            if parsed == "__MALFORMED__":
                allowlist_malformed = True
                allowlist = []
                print(f"warning: allowlist {allowlist_file} is malformed; "
                      "treating as empty for this run", file=sys.stderr)
            else:
                allowlist = parsed  # type: ignore[assignment]
    else:
        allowlist = []

    # Mirror-pair audit.
    if protocol_root is not None:
        pair_results = audit_mirror_pairs(runtime_root, protocol_root, allowlist)
    else:
        # No protocol root: synthesize missing-protocol rows for the
        # full pair table so the report still enumerates the contract.
        pair_results = [
            PairResult(
                runtime_path=p.runtime_path,
                protocol_path=p.protocol_path,
                substance_class=p.substance_class,
                status="missing-protocol",
                runtime_sha256=(
                    _sha256_of_file(runtime_root / p.runtime_path)
                    if (runtime_root / p.runtime_path).is_file() else ""
                ),
                protocol_sha256="",
            )
            for p in MIRROR_PAIRS
        ]

    # Welle-substance audit.
    welle_doc: Optional[pathlib.Path] = None
    if protocol_root is not None and args.protocol_welle_doc:
        welle_doc = protocol_root / args.protocol_welle_doc
    welle_results = audit_welle_inventory(runtime_root, welle_doc)

    report_date = args.date or _utc_date_str()
    protocol_head = _git_head_short(protocol_root) if protocol_root else "absent"
    runtime_head = _git_head_short(runtime_root)

    # Stdout summary.
    summarize_to_stdout(
        pair_results, welle_results, args.enforce, allowlist_malformed
    )

    # Markdown report.
    if args.report_path is not None:
        report = render_markdown_report(
            pair_results,
            welle_results,
            runtime_root,
            protocol_root if protocol_root is not None else pathlib.Path("(absent)"),
            protocol_head,
            runtime_head,
            args.enforce,
            allowlist_malformed,
            report_date,
        )
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(report, encoding="utf-8")
        print(f"report written: {args.report_path}")

    # JSON dump.
    if args.json is not None:
        payload = {
            "report_date": report_date,
            "runtime_head": runtime_head,
            "protocol_head": protocol_head,
            "enforce": args.enforce,
            "allowlist_malformed": allowlist_malformed,
            "pairs": [r._asdict() for r in pair_results],
            "welle": [
                {**w._asdict(),
                 "phase_3a_modules_present": list(w.phase_3a_modules_present)}
                for w in welle_results
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"json written: {args.json}")

    # Exit code.
    drift = sum(1 for r in pair_results if r.status == "DRIFT")
    missing = sum(
        1 for r in pair_results
        if r.status in ("missing-runtime", "missing-protocol", "missing-both")
    )
    welle_incomplete = sum(
        1 for w in welle_results if w.overall_status == "incomplete-runtime"
    )

    if args.enforce:
        if allowlist_malformed:
            print("error: allowlist malformed in enforce mode", file=sys.stderr)
            return 1
        if drift > 0:
            print(f"error: {drift} un-allowlisted drift item(s) in enforce mode",
                  file=sys.stderr)
            return 1
        if missing > 0 and protocol_root is not None:
            # In enforce mode with a protocol root, missing-on-either-side
            # is a hard fail. Without a protocol root the synthesized
            # missing-protocol rows are expected, so we do NOT fail.
            print(f"error: {missing} pair(s) missing on one side", file=sys.stderr)
            return 1
        if welle_incomplete > 0:
            print(f"error: {welle_incomplete} welle(s) incomplete in enforce mode",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
