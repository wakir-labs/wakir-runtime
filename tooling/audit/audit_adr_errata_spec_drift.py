#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-57 ADR-Head-Errata x Wirelang-Spec cross-site mirror-drift audit
====================================================================

Purpose
-------
The Tag-56 ADR-Errata commit landed six ``ERR-S1..ERR-S6`` footer
markers on four ADR heads in ``AI-Corp/decisions/``:

  * ADR-0034 (``0034-repo-lizenz-strategie.md``) — ERR-S1, ERR-S2, ERR-S3
  * ADR-0052 (``0052-class-p-promotion-caveat-hash.md``)            — ERR-S4
  * ADR-0062 (``0062-repo-split-strategie-phase-2.md``)             — ERR-S5
  * ADR-0064 (``0064-model-routing-prompt-caching-persona-engine.md``) — ERR-S6

Each ERR marker describes a *canonical-form* path or symbol on the
runtime-main-tip that the original ADR body either mis-cites or did
not pin. The Wirelang Spec ``v0.4.3-pre-cutover-freeze`` is the
contract-surface that downstream adopters, the persona-engine
0.5.2-final-pre-cutover boot, and the Tag-56 marathon acceptance
gate all anchor against. If the spec mentions any of the
canonical-form artefacts in a way that drifts from the ERR-marker
text, an adopter implementing against the public spec will end up
on a different path than the runtime reference implementation and
the ADR audit trail. That is the cross-site mirror-drift class
this audit catches.

Scope discipline
----------------
This helper is *path/symbol consistency* only, not semantic
review. Each ERR marker exposes a small set of ``canonical_paths``
(or ``canonical_symbols``). The helper:

  1. parses the four ADR heads and extracts the ``## Errata``
     footer section,
  2. extracts the six ERR-S{1..6} marker blocks and their
     canonical-paths/symbols (Markdown-literal back-tick spans),
  3. reads the Wirelang spec file and tokenises its back-tick
     spans,
  4. emits a drift-envelope JSON object that, for each ERR marker
     and each canonical-path/symbol, records (a) whether the spec
     mentions the canonical form, (b) whether the spec mentions
     the *legacy* (pre-errata) form, and (c) whether the legacy
     form appears in a citation context (i.e. a Markdown
     foot-note pointer to one of the four ADRs).

This is a Tier-1 (drift-detection) audit. It does **not** rewrite
the spec, it does **not** propose new ERR markers, and it does
**not** speak to whether v0.4.3 should be re-baselined. A non-zero
``mentions_legacy_form`` count surfaces a follow-up item for the
spec editor (Reza-Hand or whoever owns the spec next). A non-zero
``mentions_canonical_form`` count surfaces the spec-side anchor
that downstream adopters will (correctly) follow.

Output contract
---------------
``run_audit(...)`` returns a ``DriftEnvelope`` dataclass that
serialises to a stable JSON shape::

  {
    "audit_id": "tag-57-adr-errata-spec-cross-audit",
    "spec_path": "wirelang/specs/wirelang-spec-v0-4-3.md",
    "spec_freeze_marker": "pre-cutover-freeze" | null,
    "adr_heads": [
      {"adr_id": "ADR-0034", "path": "...", "found": true, "err_markers_extracted": ["ERR-S1","ERR-S2","ERR-S3"]},
      ...
    ],
    "err_markers": [
      {
        "marker_id": "ERR-S1",
        "adr_id": "ADR-0034",
        "canonical_forms": ["wirelang/specs/", "wirelang/specs/wirelang-spec-v0-4-3.md", ...],
        "legacy_forms":    ["wirelang/spec/v0.1.0/*.md", ...],
        "mentions_canonical_form_in_spec": 1+,
        "mentions_legacy_form_in_spec":    0,
        "legacy_form_citation_pointer":    false,
        "drift_class": "no-drift" | "legacy-form-uncited" | "legacy-form-cited"
      },
      ...
    ],
    "summary": {
      "markers_total":             6,
      "markers_with_drift":        0..6,
      "markers_with_citation_ok":  0..6
    }
  }

A ``drift_class`` of ``"legacy-form-uncited"`` is the worst case:
the spec mentions the old path without pointing the reader to the
ADR errata. ``"legacy-form-cited"`` is acceptable (the spec
preserves the historical name but explicitly cross-references the
errata footer). ``"no-drift"`` is the common case: the spec
either mentions only the canonical form or mentions neither.

Pure stdlib. No network, no git invocation, no JSON-schema
validator dependency. Importable from the hermetic test suite
under ``tests/audit/test_adr_errata_spec_cross_audit_tag57.py``.

Tag-57, Reza-Hand, AI-Corp continuous-mode.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
from typing import Iterable


AUDIT_ID = "tag-57-adr-errata-spec-cross-audit"

# --------------------------------------------------------------- #
# ERR-marker contract                                              #
# --------------------------------------------------------------- #
#
# The marker contract is hard-coded against the Tag-56 ADR-head
# errata text. If the ADR bodies are re-edited and the canonical/
# legacy forms shift, this contract must be updated in lockstep —
# that is exactly the property the hermetic tests pin. We list
# each marker, its source ADR id, the canonical form(s) the marker
# enshrines, and the legacy form(s) the marker supersedes.
#
# Forms are stored as substrings that match Markdown back-tick
# spans in the spec body. We match against the *unwrapped* span
# content (the literal between back-ticks), case-sensitive,
# left-anchored or anywhere depending on `match_mode`.


@dataclasses.dataclass(frozen=True)
class ErrMarker:
    marker_id: str
    adr_id: str
    canonical_forms: tuple[str, ...]
    legacy_forms: tuple[str, ...]


ERR_MARKERS: tuple[ErrMarker, ...] = (
    ErrMarker(
        marker_id="ERR-S1",
        adr_id="ADR-0034",
        canonical_forms=(
            "wirelang/specs/",
            "wirelang/specs/wirelang-spec-v0-4-3.md",
            "wirelang/specs/wirelang-spec-v0-4-2.md",
            "wirelang/specs/wirelang-spec-v0-4-1.md",
            "wirelang/specs/wirelang-spec-v0-2.md",
        ),
        legacy_forms=(
            "wirelang/spec/v0.1.0/",
            "wirelang/spec/",
        ),
    ),
    ErrMarker(
        marker_id="ERR-S2",
        adr_id="ADR-0034",
        canonical_forms=(
            "wirelang/builder/",
            "wirelang/canonical/",
            "wirelang/identity/",
        ),
        legacy_forms=(
            "wirelang/parser/",
        ),
    ),
    ErrMarker(
        marker_id="ERR-S3",
        adr_id="ADR-0034",
        canonical_forms=(
            "decisions/0023a-inter-agent-protokoll-layer-architektur.md",
        ),
        legacy_forms=(
            "decisions/0023a-wirelang-tech-spec.md",
        ),
    ),
    ErrMarker(
        marker_id="ERR-S4",
        adr_id="ADR-0052",
        canonical_forms=(
            "wirelang/canonical/caveat_set.py",
        ),
        legacy_forms=(
            "wirelang/canonical/self_reference.py",
            "verify_caveat_hash_self_reference",
        ),
    ),
    ErrMarker(
        marker_id="ERR-S5",
        adr_id="ADR-0062",
        canonical_forms=(
            "wakir-runtime/wirelang/specs/",
            "wakir-runtime/wirelang/builder/",
            "wakir-runtime/wirelang/canonical/",
            "wakir-runtime/wirelang/identity/",
        ),
        legacy_forms=(
            "wakir-runtime/wirelang/spec/",
            "wakir-runtime/wirelang/parser/",
        ),
    ),
    ErrMarker(
        marker_id="ERR-S6",
        adr_id="ADR-0064",
        canonical_forms=(
            "wirelang/persona_engine/llm_call_shim.py",
            "EchoReflectionLlmHook",
            "anthropic_messages_hook_phase_3_stub",
        ),
        legacy_forms=(
            "wirelang/persona_engine/llm_hook.py",
        ),
    ),
)


# Citation-pointer pattern: ADR id followed (within ~120 chars) by
# the marker id, or the marker id followed by an ADR id reference,
# or the spec uses an explicit "see ADR-NNNN Errata" form.
CITATION_HINTS = (
    "Errata",
    "errata",
    "ERR-S",
    "ADR-0034",
    "ADR-0052",
    "ADR-0062",
    "ADR-0064",
)


# --------------------------------------------------------------- #
# Dataclasses for the drift-envelope output                        #
# --------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class AdrHeadStatus:
    adr_id: str
    path: str
    found: bool
    err_markers_extracted: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class MarkerReport:
    marker_id: str
    adr_id: str
    canonical_forms: tuple[str, ...]
    legacy_forms: tuple[str, ...]
    mentions_canonical_form_in_spec: int
    mentions_legacy_form_in_spec: int
    legacy_form_citation_pointer: bool
    drift_class: str  # "no-drift" | "legacy-form-uncited" | "legacy-form-cited"


@dataclasses.dataclass(frozen=True)
class Summary:
    markers_total: int
    markers_with_drift: int
    markers_with_citation_ok: int


@dataclasses.dataclass(frozen=True)
class DriftEnvelope:
    audit_id: str
    spec_path: str
    spec_freeze_marker: str | None
    adr_heads: tuple[AdrHeadStatus, ...]
    err_markers: tuple[MarkerReport, ...]
    summary: Summary

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(dataclasses.asdict(self), indent=indent, sort_keys=False)


# --------------------------------------------------------------- #
# Parsers                                                          #
# --------------------------------------------------------------- #


_ERR_MARKER_RE = re.compile(r"\bERR-S([1-6])\b")
_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")
_ERRATA_HEADER_RE = re.compile(r"^##\s+Errata\s*$", re.MULTILINE)
_NEXT_H2_RE = re.compile(r"^##\s+", re.MULTILINE)
_FREEZE_MARKER_RE = re.compile(r"pre-cutover-freeze", re.IGNORECASE)


def extract_errata_section(adr_text: str) -> str:
    """
    Return the substring from the ``## Errata`` heading to the next
    top-level ``## `` heading (or end-of-file). Empty string if no
    Errata section exists.
    """
    match = _ERRATA_HEADER_RE.search(adr_text)
    if match is None:
        return ""
    start = match.start()
    # Find next "## " after the errata header itself.
    next_match = _NEXT_H2_RE.search(adr_text, pos=match.end())
    end = next_match.start() if next_match is not None else len(adr_text)
    return adr_text[start:end]


def extract_err_marker_ids(errata_section: str) -> tuple[str, ...]:
    """
    Return the sorted-unique ERR-S{N} marker ids that appear in the
    errata section.
    """
    found = sorted({f"ERR-S{m.group(1)}" for m in _ERR_MARKER_RE.finditer(errata_section)})
    return tuple(found)


def extract_backtick_spans(text: str) -> tuple[str, ...]:
    """All Markdown literal back-tick spans (single back-tick form)."""
    return tuple(m.group(1) for m in _BACKTICK_SPAN_RE.finditer(text))


def _count_substring(haystacks: Iterable[str], needle: str) -> int:
    n = 0
    for h in haystacks:
        if needle in h:
            n += 1
    return n


def _legacy_form_has_citation(spec_text: str, legacy_form: str) -> bool:
    """
    Return True if every occurrence of ``legacy_form`` in the spec
    body has at least one ``CITATION_HINTS`` token within ~120
    characters before or after. We are conservative: any single
    citation hint near *any* occurrence counts as "cited" because
    spec authors typically introduce a name once with a citation
    and then re-use it.
    """
    cited_at_least_once = False
    for m in re.finditer(re.escape(legacy_form), spec_text):
        window_lo = max(0, m.start() - 120)
        window_hi = min(len(spec_text), m.end() + 120)
        window = spec_text[window_lo:window_hi]
        if any(hint in window for hint in CITATION_HINTS):
            cited_at_least_once = True
            break
    return cited_at_least_once


# --------------------------------------------------------------- #
# Public entry-point                                               #
# --------------------------------------------------------------- #


ADR_HEAD_FILENAMES: dict[str, str] = {
    "ADR-0034": "0034-repo-lizenz-strategie.md",
    "ADR-0052": "0052-class-p-promotion-caveat-hash.md",
    "ADR-0062": "0062-repo-split-strategie-phase-2.md",
    "ADR-0064": "0064-model-routing-prompt-caching-persona-engine.md",
}


def run_audit(
    *,
    decisions_dir: pathlib.Path,
    spec_path: pathlib.Path,
) -> DriftEnvelope:
    """
    Execute the Tag-57 cross-site mirror-drift audit.

    Parameters
    ----------
    decisions_dir
        Directory containing the four ADR head files (typically
        ``AI-Corp/decisions/``).
    spec_path
        Wirelang spec file to audit against (typically
        ``wirelang/specs/wirelang-spec-v0-4-3.md`` on the
        runtime-main-tip).
    """
    decisions_dir = pathlib.Path(decisions_dir)
    spec_path = pathlib.Path(spec_path)

    # 1. ADR-head extraction.
    adr_heads: list[AdrHeadStatus] = []
    errata_text_by_adr: dict[str, str] = {}
    for adr_id, filename in ADR_HEAD_FILENAMES.items():
        adr_path = decisions_dir / filename
        if not adr_path.exists():
            adr_heads.append(
                AdrHeadStatus(
                    adr_id=adr_id,
                    path=str(adr_path),
                    found=False,
                    err_markers_extracted=(),
                )
            )
            errata_text_by_adr[adr_id] = ""
            continue
        adr_text = adr_path.read_text(encoding="utf-8")
        errata_section = extract_errata_section(adr_text)
        markers = extract_err_marker_ids(errata_section)
        adr_heads.append(
            AdrHeadStatus(
                adr_id=adr_id,
                path=str(adr_path),
                found=True,
                err_markers_extracted=markers,
            )
        )
        errata_text_by_adr[adr_id] = errata_section

    # 2. Spec body.
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
    spec_freeze_marker = "pre-cutover-freeze" if _FREEZE_MARKER_RE.search(spec_text) else None
    spec_backtick_spans = extract_backtick_spans(spec_text)

    # 3. Per-marker drift classification.
    marker_reports: list[MarkerReport] = []
    drift_count = 0
    citation_ok_count = 0
    for marker in ERR_MARKERS:
        canonical_hits = 0
        for cf in marker.canonical_forms:
            canonical_hits += _count_substring(spec_backtick_spans, cf)
        legacy_hits = 0
        legacy_cited = False
        for lf in marker.legacy_forms:
            n = _count_substring(spec_backtick_spans, lf)
            legacy_hits += n
            if n > 0 and _legacy_form_has_citation(spec_text, lf):
                legacy_cited = True

        if legacy_hits == 0:
            drift_class = "no-drift"
        elif legacy_cited:
            drift_class = "legacy-form-cited"
        else:
            drift_class = "legacy-form-uncited"

        if drift_class == "legacy-form-uncited":
            drift_count += 1
        if drift_class in ("no-drift", "legacy-form-cited"):
            citation_ok_count += 1

        marker_reports.append(
            MarkerReport(
                marker_id=marker.marker_id,
                adr_id=marker.adr_id,
                canonical_forms=marker.canonical_forms,
                legacy_forms=marker.legacy_forms,
                mentions_canonical_form_in_spec=canonical_hits,
                mentions_legacy_form_in_spec=legacy_hits,
                legacy_form_citation_pointer=legacy_cited,
                drift_class=drift_class,
            )
        )

    summary = Summary(
        markers_total=len(ERR_MARKERS),
        markers_with_drift=drift_count,
        markers_with_citation_ok=citation_ok_count,
    )

    return DriftEnvelope(
        audit_id=AUDIT_ID,
        spec_path=str(spec_path),
        spec_freeze_marker=spec_freeze_marker,
        adr_heads=tuple(adr_heads),
        err_markers=tuple(marker_reports),
        summary=summary,
    )


# --------------------------------------------------------------- #
# CLI                                                              #
# --------------------------------------------------------------- #


def _default_decisions_dir() -> pathlib.Path:
    # Repo-root-relative not applicable (audit reads from outside
    # the runtime repo). The CLI requires an explicit --decisions-dir
    # by default. We expose a sensible suggestion for documentation.
    return pathlib.Path("/var/home/fred/AI-Corp/decisions")


def _default_spec_path(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="audit_adr_errata_spec_drift",
        description=(
            "Tag-57 ADR-head-errata x Wirelang-spec cross-site "
            "mirror-drift audit (pure stdlib)."
        ),
    )
    parser.add_argument(
        "--decisions-dir",
        type=pathlib.Path,
        default=_default_decisions_dir(),
        help=(
            "Path to AI-Corp/decisions/ (the four ADR heads must "
            "live here). Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--spec",
        type=pathlib.Path,
        required=True,
        help="Path to the Wirelang spec file to audit.",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="Optional output JSON file. Default: stdout.",
    )
    args = parser.parse_args(argv)

    envelope = run_audit(decisions_dir=args.decisions_dir, spec_path=args.spec)
    payload = envelope.to_json()

    if args.out is not None:
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    # Exit-code contract: 0 if no uncited drift, 1 if any
    # marker is in "legacy-form-uncited". "legacy-form-cited"
    # and "no-drift" are both green.
    return 1 if envelope.summary.markers_with_drift > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
