# SPDX-FileCopyrightText: 2026 Wakir Labs
# SPDX-License-Identifier: Apache-2.0
"""Tag-72 Signaturzeile-Drift-Fix tests (Noa-Tag-71-Side-Finding).

Background
----------
Tag-58 strict-flip-readiness-map.md uses an append-only authorship
footer. Tag-64 appended `+ Tag-64-Append`. Tag-68 appended
`+ Tag-68-Append`. test_17 in test_open_j3_containerfile_label_tag64.py
hardcoded the literal substring `Tag-58 Original, Tag-64-Append
2026-05-19`, which the Tag-68 append broke. Tag-72 fixes the test
to substring-tolerant matching and adds a Tag-72-Signaturzeile-Fix
marker to the footer so the append-chain is self-documenting.

This suite locks the Tag-72 contract:

1. Footer carries Tag-58 Original anchor.
2. Footer references the Tag-64-Append wave.
3. Footer references the Tag-68-Append wave.
4. Footer references the Tag-72-Signaturzeile-Fix marker.
5. Footer carries the canonical date stamp 2026-05-19.
6. Footer is prefixed with the em-dash + Kai signature.
7. Footer is the last non-empty content line in the doc body.
8. test_17 in the Tag-64 file is substring-tolerant (no rigid sequence).
9. The Tag-72-Append-Format-Regel is documented in an HTML comment.
10. The append-format-regel chain mentions Tag-58 / Tag-64 / Tag-68 / Tag-72.
11. The full Tag-64 test_open_j3 suite still passes (regression guard).
12. The doc still owns the §9 OPEN-J3 header (no accidental deletion).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "operations" / "strict-flip-readiness-map-tag58.md"
TAG64_TEST_PATH = (
    REPO_ROOT
    / "tests"
    / "observability"
    / "test_open_j3_containerfile_label_tag64.py"
)


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tag64_test_src() -> str:
    return TAG64_TEST_PATH.read_text(encoding="utf-8")


def test_01_doc_footer_has_tag58_original_anchor(doc_text: str) -> None:
    assert "Tag-58 Original" in doc_text, (
        "Footer must keep the Tag-58 Original authorship anchor"
    )


def test_02_doc_footer_has_tag64_append_marker(doc_text: str) -> None:
    assert "Tag-64-Append" in doc_text, (
        "Footer must reflect the Tag-64-Append authorship wave"
    )


def test_03_doc_footer_has_tag68_append_marker(doc_text: str) -> None:
    assert "Tag-68-Append" in doc_text, (
        "Footer must reflect the Tag-68-Append authorship wave"
    )


def test_04_doc_footer_has_tag72_signaturzeile_fix_marker(doc_text: str) -> None:
    assert "Tag-72-Signaturzeile-Fix" in doc_text, (
        "Footer must reflect the Tag-72 Signaturzeile-Drift-Fix marker"
    )


def test_05_doc_footer_has_canonical_date_stamp(doc_text: str) -> None:
    assert "2026-05-19" in doc_text, (
        "Footer must carry the canonical 2026-05-19 append-date"
    )


def test_06_doc_footer_signed_by_kai_with_em_dash(doc_text: str) -> None:
    # Em-dash + Kai prefix is the strict-flip authorship convention.
    assert re.search(r"—\s+Kai\s+\(Tag-58 Original", doc_text), (
        "Footer must start with em-dash + Kai signature followed by Tag-58 anchor"
    )


def test_07_doc_footer_is_last_non_empty_signature_line(doc_text: str) -> None:
    # The signature line must come after the §10.7 Tag-68-Verdict.
    lines = [ln for ln in doc_text.splitlines() if ln.strip()]
    # Scan from the end for the signature line.
    sig_line_idx = None
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].startswith("— Kai"):
            sig_line_idx = idx
            break
    assert sig_line_idx is not None, "No '— Kai' signature line found"
    # After the signature, only the HTML-comment block may follow.
    tail = "\n".join(lines[sig_line_idx + 1 :])
    # If anything follows, it must be the HTML comment metadata only.
    if tail.strip():
        assert tail.lstrip().startswith("<!--") or "-->" in tail, (
            f"Content after signature must be HTML metadata only, got: {tail!r}"
        )


def test_08_tag64_test_17_is_substring_tolerant(tag64_test_src: str) -> None:
    # The Tag-72 fix replaced the rigid literal with three substring asserts.
    assert (
        'assert "Tag-58 Original" in doc_text' in tag64_test_src
    ), "test_17 must use substring-tolerant Tag-58 Original assertion"
    assert (
        'assert "Tag-64-Append" in doc_text' in tag64_test_src
    ), "test_17 must use substring-tolerant Tag-64-Append assertion"
    assert (
        'assert "2026-05-19" in doc_text' in tag64_test_src
    ), "test_17 must use substring-tolerant 2026-05-19 date assertion"


def test_09_tag64_test_17_no_longer_uses_rigid_sequence(
    tag64_test_src: str,
) -> None:
    # The pre-Tag-72 rigid sequence must be gone from the assertion line.
    # We allow it to appear in the explanatory comment but not as a
    # raw `assert "<literal>" in doc_text` statement.
    rigid = 'assert "Tag-58 Original, Tag-64-Append 2026-05-19" in doc_text'
    assert rigid not in tag64_test_src, (
        "test_17 must not pin the rigid literal sequence anymore"
    )


def test_10_doc_documents_tag72_append_format_regel(doc_text: str) -> None:
    # The footer block must explain the append-format-regel for future waves.
    assert "Tag-72 Signaturzeile-Drift-Fix" in doc_text, (
        "Doc must document the Tag-72 Signaturzeile-Drift-Fix in metadata"
    )
    assert "Append-Format-Regel" in doc_text, (
        "Doc must spell out the Append-Format-Regel"
    )


def test_11_append_format_regel_lists_all_waves(doc_text: str) -> None:
    # The HTML comment metadata must list the append-chain waves.
    # Locate the HTML comment block at the doc tail.
    start = doc_text.rfind("<!--")
    end = doc_text.rfind("-->")
    assert start != -1 and end != -1 and end > start, (
        "Doc must carry a trailing HTML comment with Tag-72 metadata"
    )
    block = doc_text[start:end]
    for wave in ["Tag-58", "Tag-64", "Tag-68", "Tag-72"]:
        assert wave in block, (
            f"Append-Format-Regel metadata must reference {wave}"
        )


def test_12_section9_open_j3_header_still_present(doc_text: str) -> None:
    # Regression guard: the Tag-64 OPEN-J3 header must remain intact.
    assert "## §9 — OPEN-J3 Containerfile-Label Carry-Forward" in doc_text, (
        "Tag-64 OPEN-J3 §9 header must not have been accidentally removed"
    )


def test_13_tag64_test_suite_full_pass() -> None:
    # Regression guard: run the full Tag-64 test_open_j3 suite.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "--no-header",
            "-q",
            str(TAG64_TEST_PATH),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        "Tag-64 OPEN-J3 test suite must remain fully green after Tag-72 fix.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_14_doc_frontmatter_owner_kai(doc_text: str) -> None:
    # Owner-of-record must stay Kai across append-waves.
    assert 'owner: "kai"' in doc_text, "Doc owner must remain Kai"
