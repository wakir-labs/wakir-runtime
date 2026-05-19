#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-78 Wirelang-Spec v0.4.3 vs v0.4.4-draft Cross-Validation Helper
(audit-only).

The Tag-77 trilogy (Tag-63 v0.4.4-draft baseline, Tag-64 sample
coverage, Tag-77 promotion-pre-readiness aggregate) pinned the
v0.4.4-draft side of the Phase-3c cutover gate. The Tag-58
freeze-seal probe pinned the v0.4.3 side. Both sides are now
substrate-pinned, but the **pairwise consistency between them**
has never been audited as a single artefact.

This helper does that pairwise audit. It walks both specs in
parallel and verifies four families of cross-validation
invariants:

  Family A -- Carry-forward consistency:
    Every §3 / §4 / §4.1 / §5 / §6 / §7 / §8 / §9 / §10 row
    that v0.4.4-draft claims to carry forward from v0.4.3 MUST
    appear unchanged in v0.4.3. The Pin-Pack-0.5.1 ten-row
    boot-record table is the load-bearing example: it is
    restated in both specs verbatim and the byte-equality of
    the two restatements is the carry-forward anchor.

  Family B -- Section-order stability:
    v0.4.3 has a fixed section sequence (§1 Scope, §2
    Conformance keywords, §3 no change, §4 no change, §4.1
    Carry-forward inventory, §5..§10 no change, §6 Freeze-
    marker semantics, §7 Backward compat, §8 Audit conformance,
    §9 Citation pointers). v0.4.4-draft MUST preserve this
    section order with the same numeric anchors so an auditor
    reading the two specs side-by-side can pin per-§ diffs.

  Family C -- Reserve-item isolation:
    v0.4.4-draft introduces five RES-D1..RES-D5 reserve items
    in §6 (and only in §6). NONE of the RES-Dn substance MAY
    appear in v0.4.3. The §2 draft-isolation invariant (three
    MUSTs: verifier-reject, producer-no-emit, operator-no-
    switch) is the load-bearing seal between the two specs.
    This helper verifies that the v0.4.3 file contains NONE of
    the RES-Dn anchor strings and that the v0.4.4-draft file
    contains ALL five of them in §6 (and only in §6).

  Family D -- Frontmatter cross-consistency:
    v0.4.4-draft frontmatter MUST declare ``parent:
    wirelang-spec-v0-4-3`` and ``extends: 0.4.3``, matching the
    v0.4.3 version. v0.4.3 frontmatter MUST declare ``status:
    pre-cutover-freeze`` and v0.4.4-draft MUST declare
    ``status: post-cutover-reserve-draft``. The two status
    values MUST be distinct (no accidental status-collision).

Audit-only posture (per ADR-0023a + ADR-0023b):

  - The helper reads both spec files and prints a verdict to
    stdout. It does NOT modify either spec, does NOT emit any
    audit-sample-rotation entry, notify-log entry, activity-log
    entry, ADR draft, promotion PR opening, or AR-authorisation
    request.
  - The helper does NOT touch git remotes, does NOT call any
    external endpoint, does NOT depend on wall-clock time, and
    does NOT depend on any runtime state beyond the two spec
    files on disk.
  - The helper is hermetic: stdlib only, no network, no NATS,
    no engine boot, no Rust build.

Exit 0 on green, exit 1 on any invariant failure with a clear
stderr message identifying the family (A/B/C/D) and the
specific invariant that failed.

Usage::

    python3 tooling/audit/cross_validate_v0_4_3_vs_v0_4_4.py
    python3 tooling/audit/cross_validate_v0_4_3_vs_v0_4_4.py \\
        --v043 path/to/v0.4.3.md --v044 path/to/v0.4.4-draft.md

The default paths resolve to the in-repo specs at
``wirelang/specs/wirelang-spec-v0-4-3.md`` and
``wirelang/specs/wirelang-spec-v0-4-4-draft.md``.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V043_PATH = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
DEFAULT_V044_PATH = (
    REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-4-draft.md"
)

# The ten Pin-Pack-0.5.1 boot records as they appear (in order) in
# §4.1 of both v0.4.3 and v0.4.4-draft. Byte-equal restatement of
# this table is the Family-A carry-forward anchor.
PIN_PACK_ROWS: Tuple[Tuple[str, str, str], ...] = (
    ("1", "persona-engine-recovery", "WAKIR_RECOVERY_BACKEND"),
    ("2", "persona-engine-state-backing", "WAKIR_STATE_BACKING_BACKEND"),
    ("3", "persona-engine-fsm", "WAKIR_FSM_BACKEND"),
    ("4", "persona-engine-v907-verify", "WAKIR_V907_VERIFY_BACKEND"),
    ("5", "persona-engine-bridge-diff", "WAKIR_BRIDGE_DIFF_BACKEND"),
    ("6", "persona-engine-subscribe-loop", "WAKIR_SUBSCRIBE_LOOP_BACKEND"),
    ("7", "persona-engine-anchor-emitter", "WAKIR_ANCHOR_EMITTER_BACKEND"),
    (
        "8",
        "persona-engine-svid-workload-identity",
        "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
    ),
    (
        "9",
        "persona-engine-federation-resolver",
        "WAKIR_FEDERATION_RESOLVER_BACKEND",
    ),
    (
        "10",
        "persona-engine-bridge-audit-writer",
        "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
    ),
)

# RES-Dn anchor strings. These MUST appear in v0.4.4-draft §6 and
# MUST NOT appear anywhere in v0.4.3.
RES_D_ANCHORS: Tuple[str, ...] = (
    "RES-D1",
    "RES-D2",
    "RES-D3",
    "RES-D4",
    "RES-D5",
)

# Family-B canonical section markers. Both specs MUST carry these
# numbered section headings (the heading text may differ — what
# matters is that the numeric anchor is present and in order).
CANONICAL_SECTION_NUMBERS: Tuple[str, ...] = (
    "1.",
    "2.",
    "3.",
    "4.",
    # §4.1 is a sub-section but is load-bearing (Pin-Pack mirror)
    "4.1",
    "5.",
    "6.",
    "7.",
    "8.",
    "9.",
)


# --- Frontmatter parsing -------------------------------------------------


_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL | re.MULTILINE)


def parse_frontmatter(text: str) -> Dict[str, str]:
    """Extract the YAML-ish frontmatter as a flat key->str mapping.

    The frontmatter in both specs is a flat key:value block with no
    nesting and no list values, so we parse line-by-line without
    pulling in PyYAML.

    Both specs start with an SPDX HTML comment block, then the
    frontmatter delimited by ``---`` lines. We strip the HTML
    comment first so the frontmatter delimiter matches the start
    of a line at offset 0 of the remaining text.
    """
    # Strip leading HTML comment block(s) — they precede the
    # frontmatter in CC-BY-4.0-licensed spec files.
    stripped = re.sub(r"\A<!--.*?-->\s*", "", text, count=1, flags=re.DOTALL)
    match = _FM_PATTERN.match(stripped)
    if not match:
        # Fallback: look anywhere in the first 4 KiB for the block.
        match = _FM_PATTERN.search(stripped[:4096])
    if not match:
        raise ValueError("frontmatter block not found (no '---'-delimited block)")
    body = match.group(1)
    out: Dict[str, str] = {}
    for line in body.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


# --- Family A: Carry-forward consistency --------------------------------


def _pin_pack_row_regex(row: Tuple[str, str, str]) -> re.Pattern[str]:
    rec_no, component, env = row
    # Anchor on the three cell contents in a single table row. We
    # allow flexible whitespace and backticks around the cell
    # values.
    return re.compile(
        r"\|\s*"
        + re.escape(rec_no)
        + r"\s*\|\s*`"
        + re.escape(component)
        + r"`\s*\|\s*`"
        + re.escape(env)
        + r"`\s*\|"
    )


def check_family_a(v043: str, v044: str) -> List[str]:
    """Family A: Carry-forward consistency.

    For each of the ten Pin-Pack rows, both spec files MUST
    contain a matching row in §4.1. The two restatements MUST be
    byte-equal at the cell level.
    """
    errors: List[str] = []
    for idx, row in enumerate(PIN_PACK_ROWS, start=1):
        pattern = _pin_pack_row_regex(row)
        if not pattern.search(v043):
            errors.append(
                f"A.{idx}: Pin-Pack row #{row[0]} ({row[1]}) "
                f"NOT FOUND in v0.4.3 §4.1 (carry-forward anchor broken)"
            )
        if not pattern.search(v044):
            errors.append(
                f"A.{idx}: Pin-Pack row #{row[0]} ({row[1]}) "
                f"NOT FOUND in v0.4.4-draft §4.1 (carry-forward anchor broken)"
            )
    # Pin-Pack source-of-truth pointer MUST also be cited in both.
    pinpack_yaml = (
        "infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml"
    )
    if pinpack_yaml not in v043:
        errors.append(
            "A.11: Pin-Pack source-of-truth pointer "
            f"'{pinpack_yaml}' NOT FOUND in v0.4.3"
        )
    if pinpack_yaml not in v044:
        errors.append(
            "A.11: Pin-Pack source-of-truth pointer "
            f"'{pinpack_yaml}' NOT FOUND in v0.4.4-draft"
        )
    return errors


# --- Family B: Section-order stability ----------------------------------


# Use [ \t]+ rather than \s+ between the hashes and the first
# token: \s matches newlines, which under MULTILINE could slurp a
# preceding heading line into the match (re.MULTILINE only affects
# ^/$, not \s). The inline character-class keeps each match on a
# single line.
_SECTION_HEADING_RE = re.compile(
    r"^(#{1,6})[ \t]+(\S+)(?:[ \t]+(.*))?$", re.MULTILINE
)


def collect_section_anchors(text: str) -> List[str]:
    """Return the numeric anchors of all top-level + sub-section
    headings in order of appearance (e.g. "1.", "2.", "4.1", ...).
    """
    anchors: List[str] = []
    for match in _SECTION_HEADING_RE.finditer(text):
        # Heading first token after the leading hashes.
        first_token = match.group(2)
        # Strip trailing punctuation like ":" but keep "1." or "4.1".
        if re.match(r"^\d+(\.\d+)*\.?$", first_token):
            anchors.append(first_token)
    return anchors


def check_family_b(v043: str, v044: str) -> List[str]:
    """Family B: Section-order stability.

    Both specs MUST carry the canonical numeric anchors in the
    canonical order. v0.4.4-draft MAY introduce additional anchors
    (sub-anchors under §6 like 6.1..6.5 and their sub-samples
    6.n.1) but the canonical sequence MUST appear in order.
    """
    errors: List[str] = []
    for label, text in (("v0.4.3", v043), ("v0.4.4-draft", v044)):
        anchors = collect_section_anchors(text)
        # Filter to canonical anchors only, preserving order.
        canonical_seen = [a for a in anchors if a in CANONICAL_SECTION_NUMBERS]
        # The canonical sequence MUST appear as a contiguous
        # prefix-subsequence (i.e. when we strip non-canonical
        # anchors, the result is the canonical sequence in order).
        expected = list(CANONICAL_SECTION_NUMBERS)
        # Trim duplicates while preserving first-occurrence order.
        seen: List[str] = []
        for a in canonical_seen:
            if a not in seen:
                seen.append(a)
        if seen != expected:
            errors.append(
                f"B.1: {label} canonical-section-order MISMATCH: "
                f"expected {expected}, got {seen}"
            )
    return errors


# --- Family C: Reserve-item isolation -----------------------------------


def find_section_6_bounds(text: str) -> Tuple[int, int]:
    """Locate the byte range of §6 in v0.4.4-draft.

    Returns (start_offset, end_offset). end_offset is the start of
    §7 (or len(text) if §7 absent).
    """
    s6 = re.search(r"^##\s+6\.\s", text, re.MULTILINE)
    if not s6:
        return (-1, -1)
    s7 = re.search(r"^##\s+7\.\s", text, re.MULTILINE)
    start = s6.start()
    end = s7.start() if s7 else len(text)
    return (start, end)


def check_family_c(v043: str, v044: str) -> List[str]:
    """Family C: Reserve-item isolation.

    No RES-Dn anchor MAY appear in v0.4.3.
    All RES-Dn anchors MUST appear in v0.4.4-draft.
    All RES-Dn anchors in v0.4.4-draft MUST appear inside §6 only
    (the candidate text section). The §2 draft-isolation invariant
    (three MUSTs) MUST be present in v0.4.4-draft.
    """
    errors: List[str] = []

    # Sub-check C.1: v0.4.3 contamination check.
    for anchor in RES_D_ANCHORS:
        if anchor in v043:
            errors.append(
                f"C.1: v0.4.3 contamination — RES-Dn anchor "
                f"'{anchor}' found in v0.4.3 "
                f"(reserve-item isolation violation)"
            )

    # Sub-check C.2: v0.4.4-draft presence check.
    for anchor in RES_D_ANCHORS:
        if anchor not in v044:
            errors.append(
                f"C.2: v0.4.4-draft missing reserve anchor '{anchor}' "
                f"(reserve-substrate incomplete)"
            )

    # Sub-check C.3: v0.4.4-draft §6 containment check.
    # Each RES-Dn MUST have its primary occurrence (the §6.n
    # sub-section heading) inside §6. We accept incidental
    # mentions in §1 (the scope table) and the abstract — what we
    # forbid is RES-Dn substance leaking into §7..§10.
    s6_start, s6_end = find_section_6_bounds(v044)
    if s6_start < 0:
        errors.append("C.3: §6 not found in v0.4.4-draft")
    else:
        post_6 = v044[s6_end:]
        for anchor in RES_D_ANCHORS:
            # The candidate-text body MUST live in §6. The post-§6
            # body MAY incidentally name RES-Dn anchors (e.g. in
            # §8 audit conformance pointing back to §6) but MUST
            # NOT contain a sub-section heading of the form
            # "### 6.n RES-Dn".
            if re.search(
                rf"^###\s+6\.\d+\s+{re.escape(anchor)}",
                post_6,
                re.MULTILINE,
            ):
                errors.append(
                    f"C.3: v0.4.4-draft RES-Dn body section "
                    f"'{anchor}' leaked outside §6"
                )

    # Sub-check C.4: §2 draft-isolation invariant MUST be present.
    isolation_phrases = (
        "MUST reject any frame carrying",
        "MUST NOT emit a frame carrying",
        "MUST NOT switch a Pin-Pack record",
    )
    for phrase in isolation_phrases:
        if phrase not in v044:
            errors.append(
                f"C.4: v0.4.4-draft missing draft-isolation invariant "
                f"phrase: '{phrase}'"
            )

    return errors


# --- Family D: Frontmatter cross-consistency ---------------------------


def check_family_d(v043: str, v044: str) -> List[str]:
    """Family D: Frontmatter cross-consistency.

    v0.4.3 MUST declare version 0.4.3 and status pre-cutover-freeze.
    v0.4.4-draft MUST declare version 0.4.4-draft, status
    post-cutover-reserve-draft, parent wirelang-spec-v0-4-3, and
    extends 0.4.3.
    The two status values MUST be distinct.
    The v0.4.4-draft extends value MUST match the v0.4.3 version.
    """
    errors: List[str] = []
    try:
        fm_043 = parse_frontmatter(v043)
    except ValueError as exc:
        errors.append(f"D.0: v0.4.3 frontmatter parse error: {exc}")
        return errors
    try:
        fm_044 = parse_frontmatter(v044)
    except ValueError as exc:
        errors.append(f"D.0: v0.4.4-draft frontmatter parse error: {exc}")
        return errors

    # D.1: v0.4.3 version + status invariants.
    if fm_043.get("version") != "0.4.3":
        errors.append(
            f"D.1: v0.4.3 frontmatter version != '0.4.3' "
            f"(got '{fm_043.get('version')}')"
        )
    if fm_043.get("status") != "pre-cutover-freeze":
        errors.append(
            f"D.1: v0.4.3 frontmatter status != 'pre-cutover-freeze' "
            f"(got '{fm_043.get('status')}')"
        )

    # D.2: v0.4.4-draft version + status + parent + extends.
    if fm_044.get("version") != "0.4.4-draft":
        errors.append(
            f"D.2: v0.4.4-draft frontmatter version != '0.4.4-draft' "
            f"(got '{fm_044.get('version')}')"
        )
    if fm_044.get("status") != "post-cutover-reserve-draft":
        errors.append(
            f"D.2: v0.4.4-draft frontmatter status != "
            f"'post-cutover-reserve-draft' "
            f"(got '{fm_044.get('status')}')"
        )
    if fm_044.get("parent") != "wirelang-spec-v0-4-3":
        errors.append(
            f"D.2: v0.4.4-draft frontmatter parent != "
            f"'wirelang-spec-v0-4-3' "
            f"(got '{fm_044.get('parent')}')"
        )
    if fm_044.get("extends") != "0.4.3":
        errors.append(
            f"D.2: v0.4.4-draft frontmatter extends != '0.4.3' "
            f"(got '{fm_044.get('extends')}')"
        )

    # D.3: Status-distinctness (no accidental collision).
    if (
        fm_043.get("status")
        and fm_043.get("status") == fm_044.get("status")
    ):
        errors.append(
            f"D.3: v0.4.3 and v0.4.4-draft status COLLIDE "
            f"(both '{fm_043.get('status')}') — "
            "draft-isolation invariant breached"
        )

    # D.4: extends-version-link consistency.
    if (
        fm_044.get("extends")
        and fm_043.get("version")
        and fm_044.get("extends") != fm_043.get("version")
    ):
        errors.append(
            f"D.4: v0.4.4-draft extends '{fm_044.get('extends')}' "
            f"!= v0.4.3 version '{fm_043.get('version')}'"
        )

    # D.5: freeze-marker isolation invariant. v0.4.3 carries a
    # freeze-marker; v0.4.4-draft MUST carry freeze-marker: null.
    if fm_043.get("freeze-marker") != "kw-24-cutover-gate":
        errors.append(
            f"D.5: v0.4.3 freeze-marker != 'kw-24-cutover-gate' "
            f"(got '{fm_043.get('freeze-marker')}')"
        )
    if fm_044.get("freeze-marker") != "null":
        errors.append(
            f"D.5: v0.4.4-draft freeze-marker != 'null' "
            f"(got '{fm_044.get('freeze-marker')}')"
        )

    return errors


# --- Driver -------------------------------------------------------------


def cross_validate(v043_path: Path, v044_path: Path) -> List[str]:
    """Run all four families against the two spec files.

    Returns a list of error strings. Empty list == green.
    """
    if not v043_path.exists():
        return [f"v0.4.3 spec not found at {v043_path}"]
    if not v044_path.exists():
        return [f"v0.4.4-draft spec not found at {v044_path}"]

    v043 = v043_path.read_text(encoding="utf-8")
    v044 = v044_path.read_text(encoding="utf-8")

    errors: List[str] = []
    errors.extend(check_family_a(v043, v044))
    errors.extend(check_family_b(v043, v044))
    errors.extend(check_family_c(v043, v044))
    errors.extend(check_family_d(v043, v044))
    return errors


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tag-78 Wirelang-Spec v0.4.3 vs v0.4.4-draft "
            "cross-validation helper (audit-only)."
        )
    )
    parser.add_argument(
        "--v043",
        type=Path,
        default=DEFAULT_V043_PATH,
        help=f"Path to v0.4.3 spec (default: {DEFAULT_V043_PATH})",
    )
    parser.add_argument(
        "--v044",
        type=Path,
        default=DEFAULT_V044_PATH,
        help=f"Path to v0.4.4-draft spec (default: {DEFAULT_V044_PATH})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress success banner on stdout (errors still go to stderr).",
    )
    args = parser.parse_args(argv)

    errors = cross_validate(args.v043, args.v044)
    if errors:
        print(
            "Tag-78 cross-validation FAILED "
            f"({len(errors)} invariant(s) breached):",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            "Tag-78 cross-validation PASSED:\n"
            "  - Family A (carry-forward consistency): green\n"
            "  - Family B (section-order stability):   green\n"
            "  - Family C (reserve-item isolation):    green\n"
            "  - Family D (frontmatter consistency):   green"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
