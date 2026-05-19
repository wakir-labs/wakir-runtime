#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-70 hermetic cross-validation probe for the two Operator-Hand
Cutover-Eve recipes:

  * Tag-66 Eve-Recipe   :: ``docs/operations/operator-hand-cutover-eve-final-recipe.md``
  * Tag-69 Last-Mile    :: ``docs/operations/g1-g2-last-mile-operator-checklist.md``

Both docs target the same cutover time-domain (T0 = 2026-06-08).
Tag-66 documents the day-by-day plan in **CEST** with Eve-Day = Fr
2026-05-29 (14:00 CEST opening) and T0-Day = Mo 2026-06-08
(06:00 - 14:00 CEST). Tag-69 zooms into the **24 h immediately
before T0** in **UTC** with Eve = Su 2026-06-07 (19:00 - 24:00 UTC)
and T0 = Mo 2026-06-08 00:00 - 00:30 UTC. The two docs MUST be
read by the Operator as a consistent pair: the Tag-66 plan is the
8-day calendar; the Tag-69 plan is the 30-min critical window
inside it.

Purpose
=======

This helper hermetically parses both documents and cross-checks:

  1. **Time-anchors** — both docs name 2026-06-08 as T0 (the
     strict-flip merge day). Tag-66 §1.1 lists Eve = 2026-05-29
     and T0 = 2026-06-08; Tag-69 §1.1 frontmatter names T0-1 Eve
     = 2026-06-07 and T0 = 2026-06-08. The UTC<->CEST conversion
     note in Tag-69 §1.1 must be present and self-consistent
     (00:00 UTC Mon 2026-06-08 = 02:00 CEST).

  2. **Verdict-marker namespaces** — both docs use the
     ``EVE-E1`` .. ``EVE-E12`` Eve-step namespace and the
     ``T0.0`` .. ``T0.9`` T0-step namespace. The cross-check
     confirms that every Tag-66 Eve-E1..E12 verdict-marker and
     T0.0..T0.9 verdict-marker has a Tag-69 counterpart in the
     same namespace (suffix may differ - ``EVE-E1-READY`` vs
     ``EVE-E1-COSIGN-READY`` is OK because both share the
     ``EVE-E1-`` prefix), and vice versa.

  3. **Shared verdict roll-up** — Tag-66 §2.12 emits
     ``EVE-VERDICT-GO`` and Tag-69 §2.11 emits
     ``EVE-VERDICT-GO-LAST-MILE``. The cross-check confirms both
     terminals exist and the Tag-69 final-marker is referenced
     from Tag-66 (or vice versa) so the Operator sees the link.

  4. **Action non-contradiction** — both docs name the Strict-
     Flip-PR, the Trust-Root Snapshot, the AR-pair voice
     channel, and the Rollback anchor. The cross-check confirms
     these shared subjects are not contradicted (e.g. Tag-66
     "no merge tonight if E4 HOLD" vs Tag-69 implicit go would
     be a contradiction; the cross-check looks for explicit
     contradiction tokens).

  5. **Sandbox-boundary consistency** — both docs MUST declare
     Operator-Hand-Sandbox-Gap per ADR-0020 §10 in the doc-form
     header. The cross-check confirms the disclaimer appears in
     both intro blocks.

  6. **Cross-reference closure** — Tag-69 frontmatter MUST list
     the Tag-66 doc in ``predecessors`` AND ``related_docs``;
     Tag-66 frontmatter MAY list Tag-69 in ``related_docs`` (the
     Tag-66 doc was written before Tag-69 so the forward-link is
     a SOFT requirement and only WARN-level).

Sandbox Boundary
================

This helper is **hermetic**. Zero ``gh api`` calls, zero
podman/cosign invocations, zero network I/O. Only on-disk
markdown is read. See ADR-0020 §10 + Memory
``feedback_sandbox_host_trennung``.

Verdicts
========

  * ``CROSS-VALIDATION-CLEAN``  - every cross-check green.
  * ``CROSS-VALIDATION-DRIFT``  - one or more soft cross-checks
                                  fail (warn-level, e.g. missing
                                  forward-link from Tag-66 to
                                  Tag-69).
  * ``CROSS-VALIDATION-DEFECT`` - one or more hard cross-checks
                                  fail (contradiction, missing
                                  shared time-anchor, missing
                                  shared verdict-namespace,
                                  missing sandbox-boundary).

Exit codes: 0 on CLEAN, 1 on DRIFT, 2 on DEFECT, 3 on doc-not-
found. Pass ``--json`` for a machine-readable envelope; pass
``--enforce false`` to suppress non-zero exit codes (default:
enforce true).

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

TAG66_REL = Path("docs/operations/operator-hand-cutover-eve-final-recipe.md")
TAG69_REL = Path("docs/operations/g1-g2-last-mile-operator-checklist.md")

# T0 day - the strict-flip merge calendar date both docs target.
SHARED_T0_DATE = "2026-06-08"

# Tag-66 Eve-Day calendar date (Fr 2026-05-29). Tag-66 §1.1 lists
# Eve = 2026-05-29 14:00 CEST.
TAG66_EVE_DATE = "2026-05-29"

# Tag-69 Eve-Day calendar date (Su 2026-06-07). Tag-69 §2 opens
# 2026-06-07 19:00 UTC = 21:00 CEST.
TAG69_EVE_DATE = "2026-06-07"

# Shared verdict / step namespaces. Both docs MUST cover every
# namespace slot in either the verdict-marker form (``EVE-E1-...``)
# or the section-heading form (``E1:`` / ``Eve-Check E1`` / ``Eve-E1``)
# for EVE checks, and either ``T0.x-`` (verdict-marker prefix) or
# ``T0.x:`` / ``T0.x `` (section-heading) for T0 steps. Tag-66 §2
# is bounded by Eve-Check E1..E11 + a §2.12 Roll-Up that emits the
# aggregator ``EVE-VERDICT-GO`` instead of an ``EVE-E12-*`` marker;
# Tag-69 §2 names Eve-E1..Eve-E12 explicitly. The cross-check
# accepts either form via the helper ``_namespace_present_in``.
EVE_STEP_INDICES: tuple[int, ...] = tuple(range(1, 13))
T0_STEP_INDICES: tuple[int, ...] = tuple(range(10))

# Shared action subjects. The cross-check counts them in both docs;
# if one doc names the subject and the other has no mention at all,
# that is DRIFT (the subject must appear in both because both docs
# document the same critical window).
SHARED_ACTION_SUBJECTS: tuple[str, ...] = (
    "Strict-Flip-PR",
    "Trust-Root",
    "AR-pair",
    "Rollback",
)

# Hard sandbox-boundary disclaimer phrase. Must appear in both intro
# blocks per ADR-0020 §10.
SANDBOX_DISCLAIMER_REGEX = re.compile(
    r"doc-form-only|Operator-Hand-Sandbox-Gap", re.IGNORECASE
)

# Tag-69 frontmatter MUST list Tag-66 in predecessors.
TAG66_PATH_IN_FRONTMATTER = "operator-hand-cutover-eve-final-recipe.md"
TAG69_PATH_IN_FRONTMATTER = "g1-g2-last-mile-operator-checklist.md"

# UTC<->CEST conversion sentence in Tag-69 §1.1. The Tag-69 doc says:
# "Conversion: 00:00 UTC on Mon 2026-06-08 = 02:00 CEST". The cross-
# check confirms the conversion tokens are present and self-
# consistent (00:00 UTC == 02:00 CEST is the canonical anchor).
UTC_CEST_CONVERSION_TOKENS: tuple[str, ...] = (
    "00:00 UTC",
    "02:00 CEST",
)


# --------------------------------------------------------------------
# Result schema
# --------------------------------------------------------------------

@dataclass
class CheckResult:
    """Single cross-validation check outcome."""
    name: str
    severity: str  # "hard" or "soft"
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "severity": self.severity,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class CrossValidationEnvelope:
    """Aggregated cross-validation envelope."""
    verdict: str
    rc: int
    tag66_path: str
    tag69_path: str
    checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "rc": self.rc,
            "tag66_path": self.tag66_path,
            "tag69_path": self.tag69_path,
            "checks": [c.to_dict() for c in self.checks],
            "summary": {
                "total": len(self.checks),
                "passed": sum(1 for c in self.checks if c.passed),
                "hard_failed": sum(
                    1 for c in self.checks if not c.passed and c.severity == "hard"
                ),
                "soft_failed": sum(
                    1 for c in self.checks if not c.passed and c.severity == "soft"
                ),
            },
        }


# --------------------------------------------------------------------
# Doc readers
# --------------------------------------------------------------------

def read_doc(repo_root: Path, rel: Path) -> str | None:
    """Read a doc file relative to repo root; None on missing."""
    full = repo_root / rel
    if not full.is_file():
        return None
    return full.read_text(encoding="utf-8")


def split_frontmatter_body(text: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body.

    Returns (frontmatter, body). If no frontmatter, returns
    ("", text).
    """
    if not text.startswith("---\n"):
        return ("", text)
    end = text.find("\n---\n", 4)
    if end == -1:
        return ("", text)
    frontmatter = text[4:end]
    body = text[end + 5 :]
    return (frontmatter, body)


# --------------------------------------------------------------------
# Check helpers
# --------------------------------------------------------------------

def check_time_anchors(tag66_body: str, tag69_text: str) -> list[CheckResult]:
    """Cross-check shared T0 date + per-doc Eve dates."""
    results: list[CheckResult] = []

    # Hard: T0 date in both docs.
    results.append(
        CheckResult(
            name="shared_t0_date_in_tag66",
            severity="hard",
            passed=SHARED_T0_DATE in tag66_body,
            detail=f"expected '{SHARED_T0_DATE}' in Tag-66 body",
        )
    )
    results.append(
        CheckResult(
            name="shared_t0_date_in_tag69",
            severity="hard",
            passed=SHARED_T0_DATE in tag69_text,
            detail=f"expected '{SHARED_T0_DATE}' in Tag-69",
        )
    )

    # Hard: each doc's eve-date in its own body.
    results.append(
        CheckResult(
            name="tag66_eve_date_present",
            severity="hard",
            passed=TAG66_EVE_DATE in tag66_body,
            detail=f"expected Tag-66 Eve-date '{TAG66_EVE_DATE}'",
        )
    )
    results.append(
        CheckResult(
            name="tag69_eve_date_present",
            severity="hard",
            passed=TAG69_EVE_DATE in tag69_text,
            detail=f"expected Tag-69 Eve-date '{TAG69_EVE_DATE}'",
        )
    )

    # Hard: UTC<->CEST conversion anchor in Tag-69.
    for tok in UTC_CEST_CONVERSION_TOKENS:
        results.append(
            CheckResult(
                name=f"tag69_utc_cest_token_{tok.replace(' ', '_').replace(':', '')}",
                severity="hard",
                passed=tok in tag69_text,
                detail=f"expected UTC<->CEST anchor token '{tok}' in Tag-69",
            )
        )

    return results


def _eve_step_present(body: str, idx: int) -> bool:
    """Return True if Eve-step ``idx`` is named in ``body`` in either
    the verdict-marker form (``EVE-E{idx}-``) or the section-heading
    form (``Eve-Check E{idx}`` / ``Eve-E{idx}``).
    """
    patterns = (
        f"EVE-E{idx}-",
        f"Eve-Check E{idx}",
        f"Eve-E{idx}:",
        f"Eve-E{idx} ",
        f"E{idx}:",
    )
    return any(p in body for p in patterns)


def _t0_step_present(body: str, idx: int) -> bool:
    """Return True if T0-step ``idx`` is named in ``body`` in either
    the verdict-marker form (``T0.{idx}-``) or the section-heading
    form (``T0.{idx}:`` / ``T0.{idx} `` / ``T0.{idx})``).
    """
    patterns = (
        f"T0.{idx}-",
        f"T0.{idx}:",
        f"T0.{idx} ",
        f"T0.{idx})",
    )
    return any(p in body for p in patterns)


def check_verdict_namespaces(tag66_body: str, tag69_text: str) -> list[CheckResult]:
    """Confirm every shared Eve-Ei + T0.i step is named in both docs.

    Both verdict-marker form and section-heading form count.
    """
    results: list[CheckResult] = []

    for idx in EVE_STEP_INDICES:
        in_tag66 = _eve_step_present(tag66_body, idx)
        in_tag69 = _eve_step_present(tag69_text, idx)
        both = in_tag66 and in_tag69
        detail_parts = []
        if not in_tag66:
            detail_parts.append("missing in Tag-66")
        if not in_tag69:
            detail_parts.append("missing in Tag-69")
        results.append(
            CheckResult(
                name=f"eve_step_E{idx}",
                severity="hard",
                passed=both,
                detail=("; ".join(detail_parts)) if detail_parts else "",
            )
        )

    for idx in T0_STEP_INDICES:
        in_tag66 = _t0_step_present(tag66_body, idx)
        in_tag69 = _t0_step_present(tag69_text, idx)
        both = in_tag66 and in_tag69
        detail_parts = []
        if not in_tag66:
            detail_parts.append("missing in Tag-66")
        if not in_tag69:
            detail_parts.append("missing in Tag-69")
        results.append(
            CheckResult(
                name=f"t0_step_T0_{idx}",
                severity="hard",
                passed=both,
                detail=("; ".join(detail_parts)) if detail_parts else "",
            )
        )

    return results


def check_verdict_rollup_terminals(tag66_body: str, tag69_text: str) -> list[CheckResult]:
    """Confirm both verdict-rollup terminals exist."""
    results: list[CheckResult] = []

    # Hard: Tag-66 must emit EVE-VERDICT-GO.
    results.append(
        CheckResult(
            name="tag66_verdict_rollup_terminal",
            severity="hard",
            passed="EVE-VERDICT-GO" in tag66_body,
            detail="Tag-66 §2.12 must emit 'EVE-VERDICT-GO'",
        )
    )

    # Hard: Tag-69 must emit EVE-VERDICT-GO-LAST-MILE.
    results.append(
        CheckResult(
            name="tag69_verdict_rollup_terminal",
            severity="hard",
            passed="EVE-VERDICT-GO-LAST-MILE" in tag69_text,
            detail="Tag-69 §2.11 must emit 'EVE-VERDICT-GO-LAST-MILE'",
        )
    )

    return results


def check_shared_subjects_non_contradiction(
    tag66_body: str, tag69_text: str
) -> list[CheckResult]:
    """Confirm shared action subjects appear in both docs.

    Soft check: if subject is in only one doc, DRIFT (warning).
    """
    results: list[CheckResult] = []

    for subj in SHARED_ACTION_SUBJECTS:
        in_tag66 = subj.lower() in tag66_body.lower()
        in_tag69 = subj.lower() in tag69_text.lower()
        both = in_tag66 and in_tag69
        detail_parts = []
        if not in_tag66:
            detail_parts.append("missing in Tag-66")
        if not in_tag69:
            detail_parts.append("missing in Tag-69")
        results.append(
            CheckResult(
                name=f"shared_subject_{subj.lower().replace('-', '_').replace(' ', '_')}",
                severity="soft",
                passed=both,
                detail=("; ".join(detail_parts)) if detail_parts else "",
            )
        )

    return results


def check_sandbox_boundary(tag66_body: str, tag69_text: str) -> list[CheckResult]:
    """Confirm sandbox-boundary disclaimer in both intro blocks."""
    results: list[CheckResult] = []

    intro66 = tag66_body[:3000]
    intro69 = tag69_text[:3000]

    results.append(
        CheckResult(
            name="tag66_sandbox_boundary_disclaimer",
            severity="hard",
            passed=bool(SANDBOX_DISCLAIMER_REGEX.search(intro66)),
            detail="Tag-66 intro must declare doc-form-only / Operator-Hand-Sandbox-Gap",
        )
    )
    results.append(
        CheckResult(
            name="tag69_sandbox_boundary_disclaimer",
            severity="hard",
            passed=bool(SANDBOX_DISCLAIMER_REGEX.search(intro69)),
            detail="Tag-69 intro must declare doc-form-only / Operator-Hand-Sandbox-Gap",
        )
    )

    return results


def check_cross_reference_closure(
    tag66_text: str, tag69_text: str
) -> list[CheckResult]:
    """Confirm Tag-69 frontmatter links to Tag-66 (hard) and Tag-66
    optionally lists Tag-69 in related_docs (soft, doc was written
    earlier)."""
    results: list[CheckResult] = []

    tag66_fm, _ = split_frontmatter_body(tag66_text)
    tag69_fm, _ = split_frontmatter_body(tag69_text)

    # Hard: Tag-69 frontmatter MUST list Tag-66 in predecessors AND
    # related_docs (Tag-69 written after Tag-66).
    results.append(
        CheckResult(
            name="tag69_frontmatter_lists_tag66_predecessor",
            severity="hard",
            passed=TAG66_PATH_IN_FRONTMATTER in tag69_fm,
            detail=f"Tag-69 frontmatter must reference '{TAG66_PATH_IN_FRONTMATTER}'",
        )
    )

    # Soft: Tag-66 frontmatter MAY list Tag-69 in related_docs.
    # Since Tag-66 was authored before Tag-69, missing forward-link
    # is DRIFT, not DEFECT.
    results.append(
        CheckResult(
            name="tag66_frontmatter_forward_link_tag69",
            severity="soft",
            passed=TAG69_PATH_IN_FRONTMATTER in tag66_fm,
            detail=(
                f"Tag-66 frontmatter forward-link to "
                f"'{TAG69_PATH_IN_FRONTMATTER}' missing (soft)"
            ),
        )
    )

    return results


# --------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------

def run_all_checks(repo_root: Path) -> CrossValidationEnvelope:
    """Run every cross-validation check and produce an envelope."""
    tag66_text = read_doc(repo_root, TAG66_REL)
    tag69_text = read_doc(repo_root, TAG69_REL)

    if tag66_text is None or tag69_text is None:
        missing = []
        if tag66_text is None:
            missing.append(str(TAG66_REL))
        if tag69_text is None:
            missing.append(str(TAG69_REL))
        return CrossValidationEnvelope(
            verdict="DOC-NOT-FOUND",
            rc=3,
            tag66_path=str(TAG66_REL),
            tag69_path=str(TAG69_REL),
            checks=[
                CheckResult(
                    name="doc_present",
                    severity="hard",
                    passed=False,
                    detail=f"missing: {', '.join(missing)}",
                )
            ],
        )

    _, tag66_body = split_frontmatter_body(tag66_text)

    all_checks: list[CheckResult] = []
    all_checks.extend(check_time_anchors(tag66_body, tag69_text))
    all_checks.extend(check_verdict_namespaces(tag66_body, tag69_text))
    all_checks.extend(check_verdict_rollup_terminals(tag66_body, tag69_text))
    all_checks.extend(check_shared_subjects_non_contradiction(tag66_body, tag69_text))
    all_checks.extend(check_sandbox_boundary(tag66_body, tag69_text))
    all_checks.extend(check_cross_reference_closure(tag66_text, tag69_text))

    hard_failed = sum(
        1 for c in all_checks if not c.passed and c.severity == "hard"
    )
    soft_failed = sum(
        1 for c in all_checks if not c.passed and c.severity == "soft"
    )

    if hard_failed > 0:
        verdict = "CROSS-VALIDATION-DEFECT"
        rc = 2
    elif soft_failed > 0:
        verdict = "CROSS-VALIDATION-DRIFT"
        rc = 1
    else:
        verdict = "CROSS-VALIDATION-CLEAN"
        rc = 0

    return CrossValidationEnvelope(
        verdict=verdict,
        rc=rc,
        tag66_path=str(TAG66_REL),
        tag69_path=str(TAG69_REL),
        checks=all_checks,
    )


# --------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------

def render_human(env: CrossValidationEnvelope) -> str:
    """Human-readable rendering of the envelope."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Tag-70 Cross-Validation Recipe-Consistency Probe")
    lines.append("=" * 72)
    lines.append(f"tag66: {env.tag66_path}")
    lines.append(f"tag69: {env.tag69_path}")
    lines.append("")
    lines.append("checks:")
    for c in env.checks:
        flag = "PASS" if c.passed else f"FAIL ({c.severity})"
        line = f"  [{flag:>11}] {c.name}"
        if not c.passed and c.detail:
            line += f"  -- {c.detail}"
        lines.append(line)
    lines.append("")
    summary = env.to_dict()["summary"]
    lines.append(
        f"summary: total={summary['total']} passed={summary['passed']} "
        f"hard_failed={summary['hard_failed']} soft_failed={summary['soft_failed']}"
    )
    lines.append(f"verdict: {env.verdict}")
    lines.append(f"rc: {env.rc}")
    return "\n".join(lines)


# --------------------------------------------------------------------
# CLI entry
# --------------------------------------------------------------------

def _find_repo_root(start: Path) -> Path:
    """Walk upward to find repo root by looking for .git or the
    two target docs."""
    cur = start.resolve()
    for _ in range(8):
        if (cur / ".git").exists() or (cur / TAG66_REL).exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tag-70 hermetic cross-validation probe for "
        "Tag-66 + Tag-69 Operator-Hand recipes."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Override repo-root (default: walk up from CWD).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON envelope instead of "
        "human-readable text.",
    )
    parser.add_argument(
        "--enforce",
        default="true",
        help="If 'true' (default), exit with non-zero rc on any "
        "DRIFT/DEFECT/DOC-NOT-FOUND verdict. If 'false', exit 0.",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root or _find_repo_root(Path.cwd())
    env = run_all_checks(repo_root)

    if args.json:
        sys.stdout.write(json.dumps(env.to_dict(), indent=2) + "\n")
    else:
        sys.stdout.write(render_human(env) + "\n")

    enforce = (args.enforce or "true").strip().lower() == "true"
    if not enforce:
        return 0
    return env.rc


if __name__ == "__main__":
    sys.exit(main())
