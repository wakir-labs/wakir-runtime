#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Verify the Tag-61 Branch-Protection Required-Check Wiring Doc Addendum.

Hermetic, stdlib-only. Extends verify_branch_protection_required_checks_doc.py
to the Tag-61 Addendum doc. Parses the addendum and asserts:
 - All 6 required sections (§1..§6) are present with the expected
   heading prefix (Tag-59-compatible numbering kept).
 - §1 Addendum-Tabelle has exactly 2 new rows (the 2 Tag-60 PRs).
 - §1 Gesamt-Pool-Bilanz table has exactly 7 rows (5 Tag-59 + 2 Tag-61).
 - Each new row carries a non-empty display-name in backticks plus
   a workflow-file reference under `.github/workflows/`.
 - New display-names are unique vs. the Tag-59 5-name set.
 - §4 Aktivierungs-Reihenfolge table has exactly 7 rows with
   risk-level entries; the 2 Tag-61 checks appear with explicit
   risk-level.
 - §6 Sandbox-Boundary table is non-empty and references both
   `Mira-Sandbox` and `Operator-Hand` columns.

Exit code 0 on pass, 1 on failure with a structured report on stderr.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable


DOC_DEFAULT = (
    "docs/operations/branch-protection-required-checks-tag61-addendum.md"
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "§1 — Erweiterung der Required-Check-Tabelle (Tag-61 Addendum)",
    "§2 — Operator-Hand-Aktivierungs-Recipe (Delta zur Tag-59-§2)",
    "§3 — Pre-Aktivierungs-Verifikations-Checklist (Delta-Notiz)",
    "§4 — Aktivierungs-Reihenfolge mit Risk-Map (Tag-61-Erweiterung)",
    "§5 — Post-Aktivierungs-Smoke (Delta-Notiz)",
    "§6 — Sandbox-Boundary (Tag-61-Delta)",
)

# Tag-61-Delta: exactly 2 new Required-Check rows.
EXPECTED_NEW_ROW_COUNT = 2
# Pool total after Tag-61: 5 (Tag-59) + 2 (Tag-61) = 7.
EXPECTED_POOL_TOTAL = 7
# Activation-order table also has 7 rows post-Tag-61.
EXPECTED_ORDER_ROW_COUNT = 7

# Tag-59 baseline display-names (must not duplicate).
TAG59_DISPLAY_NAMES: frozenset[str] = frozenset(
    {
        "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
        "pyramide layer-dependency DAG verify (6 layers, 16 edges)",
        "verify-containerfile-base-image-digest-pins",
        "wirelang spec v0.4.3 freeze-seal probe",
        "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)",
    }
)

# Tag-61 new display-names (must appear in §1 Addendum row + §4 order).
TAG61_NEW_DISPLAY_NAMES: tuple[str, ...] = (
    "pyramide cross-run stability pin (5 fixtures, 3 runs each)",
    "g1-g2 operator-recipe smoke-validation",
)

TAG61_NEW_WORKFLOW_FILES: tuple[str, ...] = (
    ".github/workflows/pyramide-cross-run-stability-pin-gate.yml",
    ".github/workflows/g1-g2-operator-recipe-smoke-validation.yml",
)

VALID_RISK_LEVELS: frozenset[str] = frozenset(
    {"low", "low-medium", "medium", "medium-high", "high"}
)


class Finding:
    """Single verification finding. Plain class for importlib-import compat."""

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
    """Split markdown by top-level `## ` headings."""
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
    """Extract all markdown tables in a section.

    Returns a list of tables; each table is a list of rows; each row
    a list of cell strings. Header and alignment rows are EXCLUDED
    (data rows only).
    """
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


def extract_backtick(s: str) -> str | None:
    m = re.search(r"`([^`]+)`", s)
    return m.group(1) if m else None


def verify(doc_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not doc_path.exists():
        return [Finding("error", "doc-existence", f"missing: {doc_path}")]

    text = doc_path.read_text(encoding="utf-8")
    if not text.strip():
        return [Finding("error", "doc-emptiness", "doc file is empty")]

    # Frontmatter sanity (predecessor field).
    if 'predecessor:' not in text:
        findings.append(
            Finding(
                "error",
                "frontmatter-predecessor",
                "missing `predecessor:` field referencing Tag-59 doc",
            )
        )
    if "branch-protection-required-checks-tag59.md" not in text:
        findings.append(
            Finding(
                "error",
                "frontmatter-predecessor-target",
                "predecessor field does not target Tag-59 doc",
            )
        )

    sections = split_sections(text)

    # 1. Required sections present.
    for req in REQUIRED_SECTIONS:
        if req not in sections:
            findings.append(
                Finding("error", req, "section heading missing")
            )

    # 2. §1 — Tag-61 Addendum table + Gesamt-Pool-Bilanz.
    s1 = sections.get(REQUIRED_SECTIONS[0])
    if s1 is not None:
        tables = parse_all_tables(s1)
        # First table: new Tag-61 rows (2 rows expected).
        if not tables:
            findings.append(
                Finding(
                    "error",
                    "§1-addendum-table",
                    "no markdown table found in §1",
                )
            )
        else:
            new_rows = tables[0]
            if len(new_rows) != EXPECTED_NEW_ROW_COUNT:
                findings.append(
                    Finding(
                        "error",
                        "§1-new-row-count",
                        f"expected {EXPECTED_NEW_ROW_COUNT} new rows, "
                        f"got {len(new_rows)}",
                    )
                )
            display_names: list[str] = []
            for idx, row in enumerate(new_rows, start=6):
                if len(row) < 6:
                    findings.append(
                        Finding(
                            "error",
                            f"§1-row-{idx}-cell-count",
                            f"row has < 6 cells (got {len(row)})",
                        )
                    )
                    continue
                dn = extract_backtick(row[1])
                if not dn:
                    findings.append(
                        Finding(
                            "error",
                            f"§1-row-{idx}-display-name",
                            "display-name not in backticks or empty",
                        )
                    )
                    continue
                display_names.append(dn)
                if dn in TAG59_DISPLAY_NAMES:
                    findings.append(
                        Finding(
                            "error",
                            f"§1-row-{idx}-tag59-collision",
                            f"display-name {dn!r} duplicates Tag-59 pool",
                        )
                    )
                wf = extract_backtick(row[2])
                if not wf or not wf.startswith(".github/workflows/"):
                    findings.append(
                        Finding(
                            "error",
                            f"§1-row-{idx}-workflow",
                            "workflow-file ref missing or not under "
                            ".github/workflows/",
                        )
                    )
                if not row[5].strip():
                    findings.append(
                        Finding(
                            "error",
                            f"§1-row-{idx}-status",
                            "status cell empty",
                        )
                    )
            # 3. Tag-61 expected display-names must all be in new rows.
            for expected in TAG61_NEW_DISPLAY_NAMES:
                if expected not in display_names:
                    findings.append(
                        Finding(
                            "error",
                            "§1-tag61-expected-displayname",
                            f"missing expected new display-name: "
                            f"{expected!r}",
                        )
                    )
            # 4. Tag-61 new rows must have unique display-names.
            if len(display_names) != len(set(display_names)):
                findings.append(
                    Finding(
                        "error",
                        "§1-new-displayname-uniqueness",
                        "duplicate display-names in new rows",
                    )
                )

            # 5. Second table in §1 should be Gesamt-Pool-Bilanz with 7 rows.
            if len(tables) >= 2:
                pool_rows = tables[1]
                if len(pool_rows) != EXPECTED_POOL_TOTAL:
                    findings.append(
                        Finding(
                            "error",
                            "§1-pool-total-row-count",
                            f"Gesamt-Pool-Bilanz expected "
                            f"{EXPECTED_POOL_TOTAL} rows, "
                            f"got {len(pool_rows)}",
                        )
                    )
            else:
                findings.append(
                    Finding(
                        "error",
                        "§1-pool-total-table",
                        "Gesamt-Pool-Bilanz table missing in §1",
                    )
                )

    # 6. §4 — Aktivierungs-Reihenfolge table with 7 rows and risk-levels.
    s4 = sections.get(REQUIRED_SECTIONS[3])
    if s4 is not None:
        order_tables = parse_all_tables(s4)
        if not order_tables:
            findings.append(
                Finding(
                    "error",
                    "§4-order-table",
                    "no markdown table found in §4",
                )
            )
        else:
            order_rows = order_tables[0]
            if len(order_rows) != EXPECTED_ORDER_ROW_COUNT:
                findings.append(
                    Finding(
                        "error",
                        "§4-order-row-count",
                        f"activation-order table expected "
                        f"{EXPECTED_ORDER_ROW_COUNT} rows, "
                        f"got {len(order_rows)}",
                    )
                )
            # Check each row has a recognized risk-level token in cell[3].
            for idx, row in enumerate(order_rows, start=1):
                if len(row) < 4:
                    continue
                risk_cell = row[3].lower()
                if not any(rl in risk_cell for rl in VALID_RISK_LEVELS):
                    findings.append(
                        Finding(
                            "error",
                            f"§4-order-row-{idx}-risk",
                            f"no recognized risk-level token in "
                            f"{row[3]!r}",
                        )
                    )
            # All Tag-61 new display-names must appear in §4 order.
            joined = "\n".join("|".join(r) for r in order_rows)
            for expected in TAG61_NEW_DISPLAY_NAMES:
                if expected not in joined:
                    findings.append(
                        Finding(
                            "error",
                            "§4-tag61-presence",
                            f"new check {expected!r} not in §4 order table",
                        )
                    )

    # 7. §6 Sandbox-Boundary table has Mira-Sandbox + Operator-Hand cols.
    s6 = sections.get(REQUIRED_SECTIONS[5], "")
    if "Mira-Sandbox" not in s6 or "Operator-Hand" not in s6:
        findings.append(
            Finding(
                "error",
                "§6-sandbox-boundary",
                "Sandbox-Boundary section missing Mira-Sandbox/"
                "Operator-Hand axis",
            )
        )
    if "|" not in s6:
        findings.append(
            Finding(
                "error",
                "§6-sandbox-boundary-table",
                "no markdown table found in §6",
            )
        )
    if "ADR-0020" not in s6:
        findings.append(
            Finding(
                "error",
                "§6-adr-reference",
                "ADR-0020 reference missing in §6",
            )
        )

    return findings


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doc",
        type=Path,
        default=Path(DOC_DEFAULT),
        help="Path to the Tag-61 addendum doc",
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
        f"OK: {args.doc} passes Tag-61-addendum wiring-doc verification"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
