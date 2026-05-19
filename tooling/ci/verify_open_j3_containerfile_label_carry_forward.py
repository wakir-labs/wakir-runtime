#!/usr/bin/env python3
"""
Tag-64 OPEN-J3 Containerfile-Label Carry-Forward verifier.

Verifies the §9 OPEN-J3 carry-forward append to the Tag-58
Strict-Flip-Readiness-Map plus the underlying Containerfile.real
LABEL-substrate is still in the intentional-carry-forward state
(`0.5.2-final-pre-cutover` LABEL, ADR-0061-LABEL-Konvention satisfied
with 7 OCI-image LABELs, no premature `0.5.3` refresh).

Decision-Pfad: carry-forward (siehe inbox/2026-05-19-kai-tag-64-j3-label-done.md).
Pre-Cutover-Cleanup ist explizit ausgeschlossen — Tag-62-Release-Notes
§1 Out-of-Scope + Tag-63-Audit §D6 Domain-Boundary.

Exit 0 on green carry-forward, exit 1 on substrate-drift.
stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "operations" / "strict-flip-readiness-map-tag58.md"
CONTAINERFILE_PATH = REPO_ROOT / "infra" / "persona-engine" / "Containerfile.real"
AUDIT_PATH = (
    REPO_ROOT
    / "reports"
    / "audit"
    / "persona-engine-0-5-3-production-readiness-2026-05-19.md"
)

EXPECTED_CARRY_FORWARD_LABEL = (
    'LABEL org.opencontainers.image.version="0.5.2-final-pre-cutover"'
)
FORBIDDEN_PREMATURE_LABEL = 'LABEL org.opencontainers.image.version="0.5.3"'

REQUIRED_OCI_LABEL_KEYS = [
    "org.opencontainers.image.title",
    "org.opencontainers.image.description",
    "org.opencontainers.image.version",
    "org.opencontainers.image.licenses",
    "org.opencontainers.image.source",
    "org.opencontainers.image.url",
    "org.opencontainers.image.documentation",
]

REQUIRED_SECTION9_SUBSECTIONS = ["§9.1", "§9.2", "§9.3", "§9.4", "§9.5"]
REQUIRED_J3_SUB_T_STEPS = ["J3-A", "J3-B", "J3-C", "J3-D", "J3-E", "J3-F", "J3-G"]


def fail(msg: str) -> None:
    sys.stderr.write(f"verify_open_j3_carry_forward: FAIL: {msg}\n")
    sys.exit(1)


def load(path: Path) -> str:
    if not path.exists():
        fail(f"required file missing: {path}")
    return path.read_text(encoding="utf-8")


def check_doc_section9_present() -> None:
    doc = load(DOC_PATH)
    if "## §9 — OPEN-J3 Containerfile-Label Carry-Forward" not in doc:
        fail("§9 OPEN-J3 carry-forward header missing in tag58-map")
    for sub in REQUIRED_SECTION9_SUBSECTIONS:
        if f"### {sub}" not in doc:
            fail(f"§9 subsection {sub} missing")
    for sub_t in REQUIRED_J3_SUB_T_STEPS:
        if f"| {sub_t} |" not in doc:
            fail(f"§9.3 J3-sub-sequence row {sub_t} missing")
    if "Tag-64-Append" not in doc:
        fail("§9 must self-identify as Tag-64-Append")
    if "intentional-carry-forward" not in doc:
        fail("§9 must use the verbatim 'intentional-carry-forward' status")


def check_containerfile_label_substrate() -> None:
    cf = load(CONTAINERFILE_PATH)
    if EXPECTED_CARRY_FORWARD_LABEL not in cf:
        fail(
            f"Containerfile.real does not carry the expected carry-forward "
            f"label: {EXPECTED_CARRY_FORWARD_LABEL}"
        )
    if FORBIDDEN_PREMATURE_LABEL in cf:
        fail(
            "Containerfile.real has been prematurely refreshed to '0.5.3' "
            "before the KW-24 cutover-image-build sub-sequence. This "
            "violates the intentional-carry-forward contract documented "
            "in §9 of the Strict-Flip-Readiness-Map."
        )
    for key in REQUIRED_OCI_LABEL_KEYS:
        if f'LABEL {key}=' not in cf:
            fail(f"Containerfile.real missing required OCI LABEL key: {key}")
    # ADR-0061 LABEL-Konvention: at least the 7 OCI keys present, no duplicates.
    label_pattern = re.compile(r"^LABEL\s+([\w\.\-]+)=", re.MULTILINE)
    found = label_pattern.findall(cf)
    duplicates = {k for k in found if found.count(k) > 1}
    if duplicates:
        fail(f"Containerfile.real has duplicate LABEL keys: {sorted(duplicates)}")


def check_audit_alignment() -> None:
    audit = load(AUDIT_PATH)
    if "OPEN-J3" not in audit:
        fail("Tag-63 audit report does not mention OPEN-J3 (substrate drift)")
    if "intentional carry-forward" not in audit and "intentional-carry-forward" not in audit:
        fail(
            "Tag-63 audit report missing the 'intentional carry-forward' "
            "marker for OPEN-J3"
        )
    if "MATCH-WITH-1-INTENTIONAL-CARRY-FORWARD" not in audit:
        fail(
            "Tag-63 audit §3.6 verdict 'MATCH-WITH-1-INTENTIONAL-CARRY-"
            "FORWARD' missing — audit-doc-substrate may have drifted"
        )


def check_scope_split_anchor() -> None:
    doc = load(DOC_PATH)
    s9_idx = doc.find("## §9 — OPEN-J3")
    if s9_idx < 0:
        fail("§9 missing (re-check)")
    s9 = doc[s9_idx:]
    for anchor in (
        "Tag-62-Release-Notes",
        "Out of scope",
        "Domain-Boundary",
        "Byte-Stability",
        "0.5.2-final-pre-cutover",
        "0.5.3",
    ):
        if anchor not in s9:
            fail(f"§9 missing scope-split-anchor: {anchor}")


def main() -> int:
    check_doc_section9_present()
    check_containerfile_label_substrate()
    check_audit_alignment()
    check_scope_split_anchor()
    print(
        "verify_open_j3_carry_forward: OK "
        "(§9 + 5 subsections + 7 J3-sub-T + carry-forward label intact + "
        "7 OCI LABELs + audit alignment + scope-split-anchors)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
