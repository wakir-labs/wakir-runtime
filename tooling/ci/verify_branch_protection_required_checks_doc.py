#!/usr/bin/env python3
"""Verify the Tag-59 Branch-Protection Required-Check Wiring Doc.

Hermetic, stdlib-only. Parses the doc and asserts:
 - All 6 required sections (§1..§6) are present with the expected
   heading prefix.
 - §1 status table has exactly 5 rows (the 5 pending checks).
 - Each §1 row carries a non-empty display-name in backticks plus
   a workflow-file reference under `.github/workflows/`.
 - Display-names are unique (no accidental duplicate entry).
 - Sandbox-Boundary table in §6 is non-empty and references both
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
    "docs/operations/branch-protection-required-checks-tag59.md"
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "§1 — Status pro Required-Check",
    "§2 — Operator-Hand-Aktivierungs-Recipe",
    "§3 — Pre-Aktivierungs-Verifikations-Checklist",
    "§4 — Aktivierungs-Reihenfolge mit Risk-Map",
    "§5 — Post-Aktivierungs-Smoke",
    "§6 — Sandbox-Boundary",
)

EXPECTED_CHECK_COUNT = 5


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


def parse_status_table(section_text: str) -> list[dict[str, str]]:
    """Extract markdown table rows from §1 status section.

    Returns one dict per data row (header + alignment row skipped).
    Keys: ``num``, ``display_name``, ``workflow``, ``source_pr``,
    ``first_main_run``, ``status``.
    """
    rows: list[dict[str, str]] = []
    in_table = False
    seen_header = False
    for raw in section_text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            in_table = False
            continue
        in_table = True
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Alignment row e.g. |---|---| --- skip.
        if all(set(c) <= {"-", ":"} for c in cells if c):
            continue
        if not seen_header:
            seen_header = True
            continue
        if len(cells) < 6:
            continue
        rows.append(
            {
                "num": cells[0],
                "display_name": cells[1],
                "workflow": cells[2],
                "source_pr": cells[3],
                "first_main_run": cells[4],
                "status": cells[5],
            }
        )
    return rows


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

    sections = split_sections(text)

    # 1. Required sections present.
    for req in REQUIRED_SECTIONS:
        if req not in sections:
            findings.append(
                Finding("error", req, "section heading missing")
            )

    # 2. §1 table integrity.
    s1 = sections.get(REQUIRED_SECTIONS[0])
    if s1 is None:
        return findings
    rows = parse_status_table(s1)
    if len(rows) != EXPECTED_CHECK_COUNT:
        findings.append(
            Finding(
                "error",
                "§1-row-count",
                f"expected {EXPECTED_CHECK_COUNT} rows, got {len(rows)}",
            )
        )

    display_names: list[str] = []
    for idx, row in enumerate(rows, start=1):
        dn = extract_backtick(row["display_name"])
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
        wf = extract_backtick(row["workflow"])
        if not wf or not wf.startswith(".github/workflows/"):
            findings.append(
                Finding(
                    "error",
                    f"§1-row-{idx}-workflow",
                    "workflow-file ref missing or not under .github/workflows/",
                )
            )
        if not row["status"].strip():
            findings.append(
                Finding(
                    "error",
                    f"§1-row-{idx}-status",
                    "status cell empty",
                )
            )

    # 3. Display-name uniqueness.
    if len(display_names) != len(set(display_names)):
        dupes = sorted(
            {n for n in display_names if display_names.count(n) > 1}
        )
        findings.append(
            Finding(
                "error",
                "§1-display-name-unique",
                f"duplicate display-names: {dupes}",
            )
        )

    # 4. §6 Sandbox-Boundary table has Mira-Sandbox + Operator-Hand cols.
    s6 = sections.get(REQUIRED_SECTIONS[5], "")
    if "Mira-Sandbox" not in s6 or "Operator-Hand" not in s6:
        findings.append(
            Finding(
                "error",
                "§6-sandbox-boundary",
                "Sandbox-Boundary section missing Mira-Sandbox/Operator-Hand axis",
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

    return findings


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doc",
        type=Path,
        default=Path(DOC_DEFAULT),
        help="Path to the wiring doc",
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
    print(f"OK: {args.doc} passes wiring-doc verification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
