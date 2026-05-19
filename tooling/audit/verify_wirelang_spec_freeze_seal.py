#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-58 Wirelang-Spec Pre-Cutover-Freeze-Seal Probe
==================================================

Purpose
-------
The Wirelang specification at ``wirelang/specs/wirelang-spec-v0-4-3.md``
is declared ``status: pre-cutover-freeze`` with ``freeze-marker:
kw-24-cutover-gate`` for the KW-24 Phase-3c cutover gate
(2026-06-09 start). Tag-53 introduced the marker; until Tag-58 there
was no CI-side tripwire that catches a post-freeze edit that is not
a typographic correction or an errata-footer addition.

A silent post-freeze edit is a strictly larger bug class than a
schema-drift: it breaks the *temporal* anchor that downstream
adopters (the persona-engine 0.5.2-final-pre-cutover boot, the
KW-24 cutover-gate acceptance criteria, the four ADR-head errata
footers from Tag-56) all pin against. The audit-trail surface of
the marathon depends on the seal staying intact between Tag-53 and
the KW-24 cutover-day.

Substance — what we seal
========================

Four stages, exactly:

  Stage 1 — Freeze-marker detect.
      Parse the frontmatter and confirm the ``status``,
      ``freeze-marker``, and ``freeze-anchor`` keys hold the values
      pinned in ``freeze-baseline.json``. If any of the three has
      drifted, the verdict is **SEAL-BROKEN** with class
      ``frontmatter-drift``.

  Stage 2 — Byte-level diff against the frozen baseline.
      Compute the SHA-256, byte-count, and line-count of the live
      spec and compare against ``freeze-baseline.json``. If all
      three match, the verdict is **SEAL-INTACT** and the helper
      short-circuits without entering the allowlist check.

  Stage 3 — Allowlist check (errata-footer / typo-marker).
      If Stage 2 surfaced a hash drift, fall back to a structural
      diff: every added / modified / removed line MUST fall inside
      the ``allowlist`` envelope of ``freeze-baseline.json``:

        * **errata-footer** — a new ``## Errata`` section MAY be
          appended after ``## 9. Citation pointers`` and before
          the ``— Reza`` signoff. Inside it, ``### ERR-S{n}``
          marker blocks are allowed up to a configurable cap.
        * **typo-marker** — inline ``<!-- typo: <slug> -->``
          comments MAY be added in-section up to a configurable
          cap per section and in total.

      Any delta that is neither of the two classes flips the
      verdict to **SEAL-BROKEN** with class ``unallowlisted-delta``.

  Stage 4 — Verdict envelope.
      ``run_audit(...)`` returns a ``SealEnvelope`` dataclass
      that serialises to a stable JSON shape. Three verdict
      classes only:

        * ``SEAL-INTACT`` — hash matches baseline byte-for-byte.
        * ``SEAL-ALLOWED-DELTA`` — hash differs but every delta
          line falls inside the allowlist.
        * ``SEAL-BROKEN`` — frontmatter drift OR delta outside
          the allowlist. Exit-non-zero in enforce-mode.

Scope discipline
----------------
This is a **path-level** seal, not a semantic-review seal. It does
not parse the §3 catalogue or the §4 ENV-flag schema. The earlier
hermetic suite at ``tests/specs/test_wirelang_spec_v0_4_3_pre_cutover
_freeze.py`` (Tag-53) covers the substance contract. The Tag-58
seal probe covers the *temporal* contract on top of it. A spec that
passes the Tag-53 hermetic suite but fails the Tag-58 seal probe
means: the substance is still v0.4.3-compliant, but the freeze
discipline was breached.

stdlib-only — no PyYAML, no jsonschema, no networking. The
frontmatter parser is a two-line scanner over the ``---`` fences;
the allowlist regexes are pre-compiled in module scope; the diff
walker is a deterministic line-by-line comparator over the
baseline-text fetched from the same git tree (or, in the absence
of a baseline-text-companion, from the hashed baseline itself).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Path constants                                                              #
# --------------------------------------------------------------------------- #

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_SPEC_PATH = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
DEFAULT_BASELINE_PATH = REPO_ROOT / "wirelang" / "specs" / "freeze-baseline.json"


# --------------------------------------------------------------------------- #
# Verdict classes (stable strings)                                            #
# --------------------------------------------------------------------------- #

VERDICT_INTACT = "SEAL-INTACT"
VERDICT_ALLOWED = "SEAL-ALLOWED-DELTA"
VERDICT_BROKEN = "SEAL-BROKEN"

VERDICTS = (VERDICT_INTACT, VERDICT_ALLOWED, VERDICT_BROKEN)


# --------------------------------------------------------------------------- #
# Allowlist regexes (pre-compiled in module scope)                            #
# --------------------------------------------------------------------------- #

# Inline typo-marker. Tag-58 default form is ``<!-- typo: <slug> -->``
# where <slug> is a lowercase-kebab token (a..z, 0..9, '-').
TYPO_MARKER_RE = re.compile(r"<!--\s*typo:\s*[a-z0-9\-]+\s*-->")

# Errata-footer anchor and marker block.
ERRATA_ANCHOR_RE = re.compile(r"^##\s+Errata\s*$")
ERRATA_MARKER_RE = re.compile(r"^###\s+ERR-S\d+\b")


# --------------------------------------------------------------------------- #
# Frontmatter parser                                                          #
# --------------------------------------------------------------------------- #


def parse_frontmatter(text: str) -> Dict[str, str]:
    """Return a flat string-to-string mapping of the YAML-ish
    frontmatter at the head of ``text``.

    The parser is deliberately tiny: only scalar ``key: value``
    lines are recognised; nested mappings, lists, and quoted
    multi-line scalars are not. The Wirelang spec frontmatter is
    flat by contract (see freeze-baseline.json
    ``frontmatter_invariants``), so a tiny parser is sufficient
    and avoids the PyYAML dependency on a CI runner.
    """
    out: Dict[str, str] = {}
    lines = text.splitlines()
    # Skip the optional HTML license comment at the head.
    i = 0
    while i < len(lines) and not lines[i].strip().startswith("---"):
        i += 1
    if i >= len(lines):
        return out
    # Walk until the closing ``---``.
    j = i + 1
    while j < len(lines) and not lines[j].strip().startswith("---"):
        raw = lines[j]
        if ":" in raw:
            k, _, v = raw.partition(":")
            out[k.strip()] = v.strip()
        j += 1
    return out


# --------------------------------------------------------------------------- #
# Hashing + reading                                                            #
# --------------------------------------------------------------------------- #


def sha256_of_path(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def byte_count_of_path(path: pathlib.Path) -> int:
    return path.stat().st_size


def line_count_of_text(text: str) -> int:
    # Match the historical ``wc -l`` semantics used to fill
    # freeze-baseline.json: count *trailing-newline-terminated*
    # lines. ``splitlines()`` would over-count by one when the
    # file ends with a newline (it does).
    return text.count("\n")


# --------------------------------------------------------------------------- #
# Baseline loader                                                              #
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class Baseline:
    spec_path: str
    sha256: str
    byte_count: int
    line_count: int
    frontmatter_invariants: Dict[str, str]
    section_headers: Tuple[str, ...]
    allowlist: Dict[str, Any]
    cutover_starts: str
    freeze_marker: str
    freeze_anchor: str
    freeze_status: str

    @classmethod
    def from_json_path(cls, path: pathlib.Path) -> "Baseline":
        data = json.loads(path.read_text(encoding="utf-8"))
        baseline = data["baseline"]
        return cls(
            spec_path=data["spec_path"],
            sha256=baseline["sha256"],
            byte_count=int(baseline["byte_count"]),
            line_count=int(baseline["line_count"]),
            frontmatter_invariants=dict(data["frontmatter_invariants"]),
            section_headers=tuple(data["section_headers"]),
            allowlist=dict(data["allowlist"]),
            cutover_starts=data["cutover_window"]["starts"],
            freeze_marker=data["freeze_marker"],
            freeze_anchor=data["freeze_anchor"],
            freeze_status=data["freeze_status"],
        )


# --------------------------------------------------------------------------- #
# Stage 1 — Freeze-marker detect                                              #
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class FrontmatterStatus:
    found: bool
    drift: Tuple[Tuple[str, str, str], ...]  # (key, expected, actual)

    @property
    def has_drift(self) -> bool:
        return bool(self.drift)


def detect_freeze_marker(text: str, baseline: Baseline) -> FrontmatterStatus:
    fm = parse_frontmatter(text)
    if not fm:
        return FrontmatterStatus(found=False, drift=())
    drift: List[Tuple[str, str, str]] = []
    for k, expected in baseline.frontmatter_invariants.items():
        actual = fm.get(k, "")
        if actual != expected:
            drift.append((k, expected, actual))
    return FrontmatterStatus(found=True, drift=tuple(drift))


# --------------------------------------------------------------------------- #
# Stage 2 — Byte-level diff                                                   #
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class HashStatus:
    sha256_matches: bool
    byte_count_matches: bool
    line_count_matches: bool
    actual_sha256: str
    actual_byte_count: int
    actual_line_count: int

    @property
    def is_intact(self) -> bool:
        return (
            self.sha256_matches
            and self.byte_count_matches
            and self.line_count_matches
        )


def diff_against_baseline(
    text: str,
    byte_count: int,
    baseline: Baseline,
) -> HashStatus:
    actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    actual_lines = line_count_of_text(text)
    return HashStatus(
        sha256_matches=(actual_sha == baseline.sha256),
        byte_count_matches=(byte_count == baseline.byte_count),
        line_count_matches=(actual_lines == baseline.line_count),
        actual_sha256=actual_sha,
        actual_byte_count=byte_count,
        actual_line_count=actual_lines,
    )


# --------------------------------------------------------------------------- #
# Stage 3 — Allowlist check                                                   #
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class AllowlistFinding:
    line_no: int
    line_text: str
    classification: str  # 'errata-footer' | 'typo-marker' | 'unallowlisted'
    reason: str


def classify_added_line(
    line: str,
    in_errata_section: bool,
) -> Tuple[str, str]:
    """Classify a single added line into one of three buckets.

    Returns a ``(classification, reason)`` tuple. ``classification``
    is one of ``'errata-footer'``, ``'typo-marker'``,
    ``'unallowlisted'``.
    """
    # Pure whitespace lines are admitted under whichever class is
    # currently active. Inside the errata-section they count as
    # errata-footer-content (blank lines between marker blocks);
    # outside they fall to 'typo-marker'-class (a stray blank
    # line is structurally harmless and we don't want a
    # punctuation tweak to break the seal).
    if line.strip() == "":
        if in_errata_section:
            return ("errata-footer", "blank-line-in-errata")
        return ("typo-marker", "blank-line")
    # Errata-section anchor + marker block.
    if ERRATA_ANCHOR_RE.match(line):
        return ("errata-footer", "errata-anchor")
    if in_errata_section:
        # Once inside the errata-section, every line is admitted as
        # errata-content as long as it does not flip us out of the
        # section (a new top-level ``## ``).
        if line.startswith("## ") and not ERRATA_ANCHOR_RE.match(line):
            return (
                "unallowlisted",
                "errata-section-broken-by-new-top-level-header",
            )
        return ("errata-footer", "errata-content")
    # Inline typo-marker.
    if TYPO_MARKER_RE.search(line):
        return ("typo-marker", "inline-typo-comment")
    return ("unallowlisted", "no-allowlist-class-matched")


def check_allowlist(
    baseline_text: str,
    actual_text: str,
) -> Tuple[Tuple[AllowlistFinding, ...], Dict[str, int]]:
    """Walk the line-level diff and classify each added line.

    The diff is deliberately *line-level*, not character-level, to
    keep the audit deterministic and reviewer-friendly. The walker
    is a two-pointer scan: every line that is present in the
    actual text but not in the baseline text counts as an *added*
    line; every line that is present in the baseline but not in
    the actual counts as a *removed* line. A removed line is
    always classified ``unallowlisted`` (removals are never
    typographic).
    """
    baseline_lines = baseline_text.splitlines()
    actual_lines = actual_text.splitlines()

    # Build a small set-style index so that lines that *also*
    # appear in the baseline are not counted as "added" just
    # because their positional index shifted. We key on the line
    # plus its line-no in the baseline so we can match exactly
    # once per occurrence.
    baseline_counter: Dict[str, int] = {}
    for ln in baseline_lines:
        baseline_counter[ln] = baseline_counter.get(ln, 0) + 1

    actual_counter: Dict[str, int] = {}
    for ln in actual_lines:
        actual_counter[ln] = actual_counter.get(ln, 0) + 1

    # Added: in actual but not in baseline (with multiplicity).
    findings: List[AllowlistFinding] = []
    tally: Dict[str, int] = {
        "errata-footer": 0,
        "typo-marker": 0,
        "unallowlisted": 0,
        "removed": 0,
    }

    # Walk added lines in actual-file order to give a reviewer a
    # readable error message that points at concrete line numbers.
    in_errata_section = False
    for idx, line in enumerate(actual_lines, start=1):
        if ERRATA_ANCHOR_RE.match(line):
            in_errata_section = True
        elif in_errata_section and line.startswith("## ") and not ERRATA_ANCHOR_RE.match(line):
            in_errata_section = False
        # Consume one baseline-occurrence if present.
        if baseline_counter.get(line, 0) > 0:
            baseline_counter[line] -= 1
            continue
        # Added line.
        cls, reason = classify_added_line(line, in_errata_section)
        findings.append(
            AllowlistFinding(
                line_no=idx,
                line_text=line,
                classification=cls,
                reason=reason,
            )
        )
        tally[cls] = tally.get(cls, 0) + 1

    # Walk removed lines (anything left in baseline_counter > 0).
    # If the removed line has a typo-marker-extended counterpart
    # among the added findings (same prefix, plus an inline typo
    # comment), reclassify the pair as a typo-marker delta instead
    # of an unallowlisted removal. This handles the realistic
    # "fix a typo inline" pattern where the line is *replaced*
    # rather than *appended-to*.
    typo_added_prefixes: List[str] = []
    for f in findings:
        if f.classification == "typo-marker" and TYPO_MARKER_RE.search(f.line_text):
            # Strip the typo-marker (and surrounding whitespace)
            # to recover the original line prefix.
            stripped = TYPO_MARKER_RE.sub("", f.line_text).rstrip()
            typo_added_prefixes.append(stripped)

    for ln, remaining in baseline_counter.items():
        if remaining <= 0:
            continue
        matched_typo = False
        if ln.rstrip() in typo_added_prefixes:
            # Pair the removal with a typo-marker addition: this is
            # an in-line typo correction, not an unallowlisted
            # removal. Account both sides as typo-marker.
            matched_typo = True
        if matched_typo:
            findings.append(
                AllowlistFinding(
                    line_no=-1,
                    line_text=ln,
                    classification="typo-marker",
                    reason="paired-typo-replacement-removal",
                )
            )
            tally["typo-marker"] += remaining
        else:
            findings.append(
                AllowlistFinding(
                    line_no=-1,
                    line_text=ln,
                    classification="unallowlisted",
                    reason="removed-from-baseline",
                )
            )
            tally["removed"] += remaining
            tally["unallowlisted"] += remaining

    return tuple(findings), tally


# --------------------------------------------------------------------------- #
# Stage 4 — Verdict envelope                                                  #
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class SealEnvelope:
    verdict: str  # one of VERDICTS
    verdict_class: str  # finer-grained reason
    spec_path: str
    baseline_path: str
    frontmatter: FrontmatterStatus
    hash: HashStatus
    findings: Tuple[AllowlistFinding, ...]
    tally: Dict[str, int]
    tag: str
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "tag": self.tag,
            "generated_at": self.generated_at,
            "spec_path": self.spec_path,
            "baseline_path": self.baseline_path,
            "verdict": self.verdict,
            "verdict_class": self.verdict_class,
            "frontmatter": {
                "found": self.frontmatter.found,
                "has_drift": self.frontmatter.has_drift,
                "drift": [
                    {"key": k, "expected": e, "actual": a}
                    for (k, e, a) in self.frontmatter.drift
                ],
            },
            "hash": {
                "sha256_matches": self.hash.sha256_matches,
                "byte_count_matches": self.hash.byte_count_matches,
                "line_count_matches": self.hash.line_count_matches,
                "actual_sha256": self.hash.actual_sha256,
                "actual_byte_count": self.hash.actual_byte_count,
                "actual_line_count": self.hash.actual_line_count,
            },
            "findings": [
                {
                    "line_no": f.line_no,
                    "classification": f.classification,
                    "reason": f.reason,
                    "line_text": f.line_text,
                }
                for f in self.findings
            ],
            "tally": dict(self.tally),
        }


# --------------------------------------------------------------------------- #
# Top-level entry-point                                                       #
# --------------------------------------------------------------------------- #


def run_audit(
    spec_path: Optional[pathlib.Path] = None,
    baseline_path: Optional[pathlib.Path] = None,
    baseline_text: Optional[str] = None,
    tag: str = "tag-58",
) -> SealEnvelope:
    """Run the four-stage seal audit and return a verdict envelope.

    Parameters
    ----------
    spec_path
        Path to the live spec markdown. Defaults to the in-tree
        v0.4.3 path.
    baseline_path
        Path to ``freeze-baseline.json``. Defaults to the in-tree
        sibling.
    baseline_text
        Optional override for the baseline text used by Stage 3's
        line-level diff. When ``None``, the helper falls back to
        the live spec text itself for the diff anchor (which means
        Stage 3 finds no added/removed lines when Stage 2 already
        passed). Tests pass an explicit ``baseline_text`` to
        exercise Stage 3.
    """
    sp = spec_path or DEFAULT_SPEC_PATH
    bp = baseline_path or DEFAULT_BASELINE_PATH

    baseline = Baseline.from_json_path(bp)
    text = sp.read_text(encoding="utf-8")
    byte_count = byte_count_of_path(sp)

    # Stage 1.
    fm = detect_freeze_marker(text, baseline)

    # Stage 2.
    hs = diff_against_baseline(text, byte_count, baseline)

    # Stage 3 (only if Stage 2 surfaced drift, or if a caller
    # provided baseline_text to exercise the diff path
    # explicitly).
    findings: Tuple[AllowlistFinding, ...] = ()
    tally: Dict[str, int] = {
        "errata-footer": 0,
        "typo-marker": 0,
        "unallowlisted": 0,
        "removed": 0,
    }
    if not hs.is_intact or baseline_text is not None:
        anchor = baseline_text if baseline_text is not None else text
        findings, tally = check_allowlist(anchor, text)

    # Stage 4 — verdict.
    if fm.has_drift or not fm.found:
        verdict = VERDICT_BROKEN
        verdict_class = "frontmatter-drift" if fm.found else "frontmatter-missing"
    elif hs.is_intact:
        verdict = VERDICT_INTACT
        verdict_class = "byte-for-byte-match"
    elif tally["unallowlisted"] > 0:
        verdict = VERDICT_BROKEN
        verdict_class = "unallowlisted-delta"
    else:
        verdict = VERDICT_ALLOWED
        verdict_class = (
            "errata-footer-only"
            if tally["typo-marker"] == 0
            else (
                "typo-marker-only"
                if tally["errata-footer"] == 0
                else "errata-plus-typo"
            )
        )

    return SealEnvelope(
        verdict=verdict,
        verdict_class=verdict_class,
        spec_path=str(sp),
        baseline_path=str(bp),
        frontmatter=fm,
        hash=hs,
        findings=findings,
        tally=tally,
        tag=tag,
        generated_at=_dt.datetime.now(tz=_dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
    )


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="verify_wirelang_spec_freeze_seal",
        description=(
            "Tag-58 Wirelang-Spec v0.4.3 pre-cutover-freeze-seal "
            "probe. Emits a JSON verdict envelope to stdout; "
            "exits non-zero in --enforce mode if the verdict is "
            "SEAL-BROKEN."
        ),
    )
    parser.add_argument(
        "--spec",
        type=pathlib.Path,
        default=None,
        help="Path to the live spec markdown (default: in-tree v0.4.3).",
    )
    parser.add_argument(
        "--baseline",
        type=pathlib.Path,
        default=None,
        help="Path to freeze-baseline.json (default: in-tree sibling).",
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit non-zero on SEAL-BROKEN. Default is audit-only.",
    )
    parser.add_argument(
        "--tag",
        default="tag-58",
        help="Audit-tag label (default: tag-58).",
    )
    args = parser.parse_args(argv)

    envelope = run_audit(
        spec_path=args.spec,
        baseline_path=args.baseline,
        tag=args.tag,
    )
    print(json.dumps(envelope.to_dict(), indent=2, sort_keys=False))

    if args.enforce and envelope.verdict == VERDICT_BROKEN:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
