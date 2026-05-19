#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Verify the Tag-69 E2E-Smoke Required-Status-Check Promotion-Workflow-Doc.

Hermetic, stdlib-only. Companion to verify_branch_protection_required_
checks_doc_tag61.py (Tag-61) and inherits the same Finding-shape and
section/table-parsing primitives. Verifies the Tag-69
``docs/operations/e2e-smoke-required-check-promotion-workflow.md`` doc
along these surfaces:

* Frontmatter sanity: ``title``, ``status: "active"``, ``owner:
  "amara"``, ``tag: "tag-69"``, ``predecessor`` field pointing at the
  Tag-64-Companion doc, the required cross-anchor PRs (#389, #396,
  #404, #411, #416), and the required Cross-Review-Markers (Zone-M
  twice + Zone-N).
* Required sections §1..§7 present with verbatim headings.
* §2.1 Stability-Window-Confirmation-Capture recipe contains the
  three back-to-back ``gh workflow run`` calls and the
  ``STABILITY-WINDOW-CONFIRMED`` verdict gate.
* §3.2 PUT-payload contains exactly the 8-pool display-names verbatim,
  in the Tag-64-Companion-§4 risk-order, with the E2E-verdict at
  position #8.
* §3.2 PUT-payload has ``enforce_admins: true``.
* §4 Verification-Steps has exactly 4 sub-sections (§4.1..§4.4).
* §5 Rollback section contains the 7-pool rollback-PUT (E2E-verdict
  display-name absent from the rollback contexts-array) and the
  diagnostic-tree with exactly 3 failure-mode rows (A/B/C).
* §6 Cross-Anchor section references all three predecessor PRs by
  number (#389, #396, #404).
* §7 Sandbox-Boundary table mentions Mira-Sandbox + Operator-Hand
  axis (Tag-64-Companion §6 lineage).
* §7.1 Cross-Review-Markers calls out Zone-M × 2 + Zone-N.

Exit code 0 on pass, 1 on failure with a structured report on stderr.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable


DOC_DEFAULT = (
    "docs/operations/e2e-smoke-required-check-promotion-workflow.md"
)


REQUIRED_SECTIONS: tuple[str, ...] = (
    "§1 — Scope",
    "§2 — Stability-Window-Confirmed Prerequisite (Tag-65 Pattern)",
    "§3 — PUT branch-protection Recipe (Operator-Hand)",
    "§4 — Verification-Steps",
    "§5 — Rollback bei Post-Promotion-Defect",
    "§6 — Cross-Anchor zu Kai-#389 + Kai-#396 + Tomás-#404",
    "§7 — Sandbox-Boundary",
)


# The Tag-64-Companion §4 risk-order. §3.2 PUT-payload must include
# exactly these 8 display-names in this exact sequence.
EXPECTED_POOL_DISPLAY_NAMES: tuple[str, ...] = (
    "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
    "pyramide layer-dependency DAG verify (6 layers, 16 edges)",
    "verify-containerfile-base-image-digest-pins",
    "wirelang spec v0.4.3 freeze-seal probe",
    "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)",
    "pyramide cross-run stability pin (5 fixtures, 3 runs each)",
    "g1-g2 operator-recipe smoke-validation",
    "E2E verdict (READY / DRIFT / DEFECT)",
)


# §5.2 Rollback-PUT must contain exactly these 7 (the 8-pool minus
# the E2E-verdict).
EXPECTED_ROLLBACK_DISPLAY_NAMES: tuple[str, ...] = EXPECTED_POOL_DISPLAY_NAMES[:7]


# Required cross-anchor PR numbers in the frontmatter related_prs list
# and in §6.
REQUIRED_CROSS_ANCHOR_PRS: tuple[str, ...] = ("#389", "#396", "#404")


# Frontmatter sanity fields (key, expected-substring).
REQUIRED_FRONTMATTER_FIELDS: tuple[tuple[str, str], ...] = (
    ("status:", "active"),
    ("owner:", "amara"),
    ("tag:", "tag-69"),
    (
        "predecessor:",
        "branch-protection-required-checks-tag64-companion.md",
    ),
)


# Required Cross-Review-Markers: exactly two Zone-M entries and at
# least one Zone-N entry, each on its own list-item.
REQUIRED_CROSS_REVIEW_TOKENS: tuple[str, ...] = (
    "Zone-M: QA × Tomas",
    "Zone-M: QA × Kai",
    "Zone-N: QA × Henrik",
)


# §5.1 Diagnostic-Tree must have exactly 3 failure-mode rows (A/B/C).
EXPECTED_DIAGNOSTIC_ROW_COUNT = 3


# §4 must have exactly 4 sub-sections (§4.1..§4.4).
EXPECTED_VERIFICATION_SUBSECTION_COUNT = 4


class Finding:
    """Single verification finding."""

    __slots__ = ("severity", "section", "message")

    def __init__(self, severity: str, section: str, message: str) -> None:
        self.severity = severity
        self.section = section
        self.message = message

    def render(self) -> str:
        return f"[{self.severity.upper()}] {self.section}: {self.message}"

    def __repr__(self) -> str:  # for test diagnostics
        return self.render()


def split_sections(text: str) -> dict[str, str]:
    """Split markdown by top-level ``## `` headings."""
    out: dict[str, str] = {}
    current_heading: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                out[current_heading] = "\n".join(buf)
            current_heading = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if current_heading is not None:
        out[current_heading] = "\n".join(buf)
    return out


def parse_all_tables(section_text: str) -> list[list[list[str]]]:
    """Extract all markdown tables in a section (data rows only)."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    in_table = False
    seen_header = False
    for raw in section_text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            if in_table and current:
                tables.append(current)
                current = []
                seen_header = False
            in_table = False
            continue
        in_table = True
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Alignment row e.g. |---|---|---| skip.
        if all(set(c) <= {"-", ":"} for c in cells if c):
            continue
        if not seen_header:
            seen_header = True
            continue
        current.append(cells)
    if in_table and current:
        tables.append(current)
    return tables


def extract_json_payload_contexts(section_text: str) -> list[str] | None:
    """Extract the ``contexts`` array from the first ``gh api -X PUT``
    JSON heredoc payload in a section.

    Returns ``None`` if no parsable payload is found. The payload is
    treated as a literal text-scan (not parsed as JSON) so a syntax-
    error in the doc still produces a diagnostic-friendly result.
    """
    # Find the contexts: [ ... ] block.
    m = re.search(
        r'"contexts"\s*:\s*\[([^\]]*)\]',
        section_text,
        re.DOTALL,
    )
    if not m:
        return None
    inner = m.group(1)
    # Extract each "..."-quoted string preserving order.
    return re.findall(r'"([^"]+)"', inner)


def verify(doc_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not doc_path.exists():
        return [Finding("error", "doc-existence", f"missing: {doc_path}")]

    text = doc_path.read_text(encoding="utf-8")
    if not text.strip():
        return [Finding("error", "doc-emptiness", "doc file is empty")]

    # 1. Frontmatter sanity.
    for key, expected in REQUIRED_FRONTMATTER_FIELDS:
        # Look for the key followed by anything containing the expected
        # substring on the same line.
        pattern = re.compile(
            rf"^{re.escape(key)}.*{re.escape(expected)}.*$",
            re.MULTILINE,
        )
        if not pattern.search(text):
            findings.append(
                Finding(
                    "error",
                    "frontmatter",
                    f"missing or wrong field {key!r} (expected "
                    f"value containing {expected!r})",
                )
            )

    # 2. Cross-anchor PRs in related_prs frontmatter list.
    # Look only in the frontmatter region (between the first --- pair).
    # The doc may have a leading HTML SPDX comment before the frontmatter
    # opener, so we search for the first --- line anywhere (not anchored
    # to start-of-file).
    fm_match = re.search(
        r"(?:^|\n)---\s*\n(.*?)\n---\s*\n",
        text,
        re.DOTALL,
    )
    fm_block = fm_match.group(1) if fm_match else ""
    for pr in REQUIRED_CROSS_ANCHOR_PRS:
        if pr not in fm_block:
            findings.append(
                Finding(
                    "error",
                    "frontmatter-related-prs",
                    f"PR {pr} missing from related_prs list",
                )
            )

    # 3. Cross-Review-Markers in frontmatter.
    for token in REQUIRED_CROSS_REVIEW_TOKENS:
        if token not in fm_block:
            findings.append(
                Finding(
                    "error",
                    "frontmatter-cross-review-markers",
                    f"Cross-Review-Marker token missing: {token!r}",
                )
            )

    sections = split_sections(text)

    # 4. Required sections present.
    for req in REQUIRED_SECTIONS:
        if req not in sections:
            findings.append(
                Finding("error", req, "section heading missing")
            )

    # 5. §2 — Stability-Window-Confirmed prerequisite checks.
    s2 = sections.get(REQUIRED_SECTIONS[1], "")
    if "STABILITY-WINDOW-CONFIRMED" not in s2:
        findings.append(
            Finding(
                "error",
                "§2-stability-window-verdict",
                "verdict-string STABILITY-WINDOW-CONFIRMED missing",
            )
        )
    if "gh workflow run pre-cutover-final-acceptance-e2e-smoke" not in s2:
        findings.append(
            Finding(
                "error",
                "§2-workflow-dispatch-recipe",
                "workflow_dispatch recipe for the Tag-63 E2E-Smoke missing",
            )
        )
    if "aggregate_e2e_stability_window.py" not in s2:
        findings.append(
            Finding(
                "error",
                "§2-tag65-aggregator-ref",
                "Tag-65 aggregator-helper reference missing",
            )
        )
    if "24h" not in s2 and "24 h" not in s2 and "24-hour" not in s2:
        findings.append(
            Finding(
                "error",
                "§2-freshness-window",
                "24h freshness-window not explicitly documented",
            )
        )

    # 6. §3 — PUT-payload contains all 8 expected display-names in order.
    s3 = sections.get(REQUIRED_SECTIONS[2], "")
    payload = extract_json_payload_contexts(s3)
    if payload is None:
        findings.append(
            Finding(
                "error",
                "§3-put-payload",
                "no parseable PUT-payload contexts-array found in §3",
            )
        )
    else:
        if list(payload) != list(EXPECTED_POOL_DISPLAY_NAMES):
            findings.append(
                Finding(
                    "error",
                    "§3-put-payload-pool",
                    "PUT-payload contexts-array does not match the "
                    "Tag-64-Companion §4 risk-ordered 8-pool",
                )
            )
    if '"enforce_admins": true' not in s3:
        findings.append(
            Finding(
                "error",
                "§3-enforce-admins",
                'PUT-payload missing "enforce_admins": true',
            )
        )

    # 7. §4 — Verification-Steps has exactly 4 sub-sections.
    s4 = sections.get(REQUIRED_SECTIONS[3], "")
    subsection_pattern = re.compile(r"^### §4\.(\d+)", re.MULTILINE)
    found_subs = sorted({m.group(1) for m in subsection_pattern.finditer(s4)})
    if len(found_subs) != EXPECTED_VERIFICATION_SUBSECTION_COUNT:
        findings.append(
            Finding(
                "error",
                "§4-subsection-count",
                f"expected exactly {EXPECTED_VERIFICATION_SUBSECTION_COUNT} "
                f"§4.x sub-sections, got {len(found_subs)}",
            )
        )

    # 8. §5 — Rollback: 7-pool rollback-PUT + 3-row diagnostic-tree.
    s5 = sections.get(REQUIRED_SECTIONS[4], "")
    rollback_payload = extract_json_payload_contexts(s5)
    if rollback_payload is None:
        findings.append(
            Finding(
                "error",
                "§5-rollback-payload",
                "no parseable Rollback-PUT-payload contexts-array in §5",
            )
        )
    else:
        if list(rollback_payload) != list(EXPECTED_ROLLBACK_DISPLAY_NAMES):
            findings.append(
                Finding(
                    "error",
                    "§5-rollback-payload-7pool",
                    "Rollback-PUT-payload contexts-array does not match "
                    "the 7-pool (8-pool minus E2E-verdict)",
                )
            )
        if "E2E verdict (READY / DRIFT / DEFECT)" in rollback_payload:
            findings.append(
                Finding(
                    "error",
                    "§5-rollback-payload-no-e2e",
                    "Rollback-PUT-payload must NOT contain the E2E-verdict "
                    "display-name (that defeats rollback)",
                )
            )
    # Diagnostic-tree table.
    diag_tables = parse_all_tables(s5)
    if not diag_tables:
        findings.append(
            Finding(
                "error",
                "§5-diagnostic-tree-table",
                "no diagnostic-tree table found in §5",
            )
        )
    else:
        diag = diag_tables[0]
        if len(diag) != EXPECTED_DIAGNOSTIC_ROW_COUNT:
            findings.append(
                Finding(
                    "error",
                    "§5-diagnostic-tree-row-count",
                    f"expected {EXPECTED_DIAGNOSTIC_ROW_COUNT} diagnostic "
                    f"rows (A/B/C), got {len(diag)}",
                )
            )

    # 9. §6 — Cross-anchor section references all three predecessor PRs.
    s6 = sections.get(REQUIRED_SECTIONS[5], "")
    for pr in REQUIRED_CROSS_ANCHOR_PRS:
        if pr not in s6:
            findings.append(
                Finding(
                    "error",
                    "§6-cross-anchor-pr",
                    f"§6 does not reference {pr}",
                )
            )

    # 10. §7 — Sandbox-Boundary axis + Cross-Review-Markers §7.1.
    s7 = sections.get(REQUIRED_SECTIONS[6], "")
    if "Mira-Sandbox" not in s7 or "Operator-Hand" not in s7:
        findings.append(
            Finding(
                "error",
                "§7-sandbox-boundary-axis",
                "§7 missing Mira-Sandbox / Operator-Hand axis",
            )
        )
    if "|" not in s7:
        findings.append(
            Finding(
                "error",
                "§7-sandbox-boundary-table",
                "§7 has no markdown table",
            )
        )
    if "ADR-0020" not in s7:
        findings.append(
            Finding(
                "error",
                "§7-adr-0020-ref",
                "§7 missing ADR-0020 reference",
            )
        )
    if "Zone-M" not in s7 or "Zone-N" not in s7:
        findings.append(
            Finding(
                "error",
                "§7-cross-review-markers",
                "§7.1 missing Zone-M / Zone-N cross-review-markers",
            )
        )

    return findings


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doc",
        type=Path,
        default=Path(DOC_DEFAULT),
        help="Path to the Tag-69 promotion-workflow doc",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    findings = verify(args.doc)
    errors = [f for f in findings if f.severity == "error"]
    for f in findings:
        print(f.render(), file=sys.stderr)
    if errors:
        print(
            f"FAIL: {len(errors)} error(s) in {args.doc}",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK: {args.doc} passes Tag-69 E2E-Promotion-Workflow-Doc "
        f"verification"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
