#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Welle-N State-File Conventions Verifier -- Tag-67 (Amara / Pre-Cutover-T0 pin).

This helper enforces the canonical schema of the
``state/welle-N-*.json`` family as pinned by
``docs/quality-gates/welle-n-state-file-conventions.md`` (Tag-67).

It is a **stdlib-only** Python module (no third-party dependencies)
intended to be shellable from any producer-workflow as well as from
the Tag-67 conformance test-suite.

Usage (CLI)
-----------

::

    python3 tooling/ci/verify_welle_state_file_conventions.py \\
        state/welle-1.json [more files...]

    python3 tooling/ci/verify_welle_state_file_conventions.py \\
        --rollup state/welle-3.json

    python3 tooling/ci/verify_welle_state_file_conventions.py \\
        --sign-off state/welle-3-sign-off.json

    python3 tooling/ci/verify_welle_state_file_conventions.py \\
        --validation state/welle-3-validation-last-verdict.json

Exit-code: 0 if all OK, 1 if any conformance violation.

Sandbox-Boundary
----------------

This module is hermetic: it reads files, never writes, never makes
network calls. Per Mira's Sandbox-vs-Host-Operations Trennung,
``*-live.json`` state-files (operator-emitted on the host) are
schema-checked here but file-existence is NOT required at sandbox-
verification-time.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Sequence

# ---------------------------------------------------------------------------
# Canonical schema-pin constants (Tag-67 v1)
# ---------------------------------------------------------------------------

SCHEMA_VERSION_PIN = "tag-67-v1"
PHASE_LITERAL = "phase-3-marathon"

KW_ANCHOR_RE = re.compile(r"^KW-2[2-7]$")
ISO_TS_RE = re.compile(
    r"^$|^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$"
)
ISO_TS_NONEMPTY_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OTS_ANCHOR_RE = re.compile(r"^$|^[0-9a-f]{64}$")

ROLLUP_STATUS_ENUM = {"pending", "in-progress", "signed-off", "rolled-back"}
SIGN_OFF_STATUS_ENUM = {"pending", "signed-off", "rolled-back"}
DRIFT_VERDICT_ENUM = {"green", "caution", "blocker"}
VALIDATION_VERDICT_ENUM = {"green", "yellow", "red"}
AGGREGATOR_VERDICT_ENUM = {"CLEAR", "CAUTION", "BLOCK"}
PRE_AUDITOR_DECISION_ENUM = {"designated", "pending", "not-required"}

ROLLUP_REQUIRED_FIELDS = (
    "welle_number",
    "schema_version",
    "phase",
    "kw_cutover_anchor",
    "cutover_iso",
    "signoff_iso",
    "status",
    "rollup_links",
    "audit_trail_anchor",
)
ROLLUP_LINK_KEYS = (
    "sign_off",
    "validation_last_verdict",
    "hot_spot_trend_dir",
    "pre_auditor_decision",
)
SIGN_OFF_REQUIRED_FIELDS = (
    "welle_number",
    "status",
    "ac_1_5_green",
    "ac_4_consensus_personas",
    "cross_welle_drift_assert",
)
VALIDATION_REQUIRED_FIELDS = (
    "welle_number",
    "verdict",
    "verdict_iso",
    "checks",
    "schema_version",
)


@dataclass
class Violation:
    """One schema-pin violation."""

    file: str
    field: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - trivial format
        return f"{self.file}: {self.field}: {self.detail}"


@dataclass
class Report:
    """Aggregate verifier outcome."""

    violations: List[Violation] = field(default_factory=list)
    files_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.violations

    def add(self, file: str, field_name: str, detail: str) -> None:
        self.violations.append(Violation(file=file, field=field_name, detail=detail))

    def merge(self, other: "Report") -> None:
        self.violations.extend(other.violations)
        self.files_checked += other.files_checked


# ---------------------------------------------------------------------------
# Detector: pick the right validator for a given filename.
# ---------------------------------------------------------------------------


ROLLUP_RE = re.compile(r"(?:^|/)state/welle-([1-7])\.json$")
SIGN_OFF_RE = re.compile(r"(?:^|/)state/welle-([1-7])-sign-off\.json$")
VALIDATION_RE = re.compile(
    r"(?:^|/)state/welle-([1-7])-validation-last-verdict\.json$"
)
HOT_SPOT_DAY_RE = re.compile(
    r"(?:^|/)state/welle-([3-7])-hot-spot-trend/(\d{4}-\d{2}-\d{2})\.json$"
)
PRE_AUDITOR_RE = re.compile(
    r"(?:^|/)state/welle-([3-7])-pre-auditor-decision\.json$"
)


def detect_kind(path: str) -> str:
    """Return the schema-kind for ``path``.

    Returns one of: ``"rollup"``, ``"sign-off"``, ``"validation"``,
    ``"hot-spot-day"``, ``"pre-auditor"``, ``"unknown"``.
    """
    p = path.replace("\\", "/")
    if ROLLUP_RE.search(p):
        return "rollup"
    if SIGN_OFF_RE.search(p):
        return "sign-off"
    if VALIDATION_RE.search(p):
        return "validation"
    if HOT_SPOT_DAY_RE.search(p):
        return "hot-spot-day"
    if PRE_AUDITOR_RE.search(p):
        return "pre-auditor"
    return "unknown"


def welle_number_from_path(path: str) -> int | None:
    """Extract the welle ordinal from ``path`` or return ``None``."""
    p = path.replace("\\", "/")
    for rx in (ROLLUP_RE, SIGN_OFF_RE, VALIDATION_RE, HOT_SPOT_DAY_RE, PRE_AUDITOR_RE):
        m = rx.search(p)
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_json(path: Path) -> Any:
    """Load JSON from ``path``; raises on any error."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Per-kind validators -- each appends Violation rows to a Report.
# ---------------------------------------------------------------------------


def _check_required(
    report: Report, file: str, doc: Mapping[str, Any], fields: Iterable[str]
) -> None:
    for f in fields:
        if f not in doc:
            report.add(file, f, "required field missing")


def validate_rollup(file: str, doc: Any, report: Report) -> None:
    """Validate a ``state/welle-N.json`` rollup file."""
    if not isinstance(doc, dict):
        report.add(file, "<root>", "rollup file must be a JSON object")
        return

    _check_required(report, file, doc, ROLLUP_REQUIRED_FIELDS)

    path_welle = welle_number_from_path(file)
    welle_no = doc.get("welle_number")
    if not isinstance(welle_no, int):
        report.add(file, "welle_number", "must be an integer")
    elif welle_no < 1 or welle_no > 7:
        report.add(file, "welle_number", "must be in 1..7")
    elif path_welle is not None and welle_no != path_welle:
        report.add(
            file,
            "welle_number",
            f"mismatch: filename welle-{path_welle} but field={welle_no}",
        )

    if doc.get("schema_version") != SCHEMA_VERSION_PIN:
        report.add(
            file,
            "schema_version",
            f'must equal "{SCHEMA_VERSION_PIN}"',
        )

    if doc.get("phase") != PHASE_LITERAL:
        report.add(
            file,
            "phase",
            f'must equal "{PHASE_LITERAL}"',
        )

    kw = doc.get("kw_cutover_anchor")
    if not isinstance(kw, str) or not KW_ANCHOR_RE.match(kw):
        report.add(file, "kw_cutover_anchor", "must match ^KW-2[2-7]$")

    for ts_field in ("cutover_iso", "signoff_iso"):
        v = doc.get(ts_field)
        if not isinstance(v, str) or not ISO_TS_RE.match(v):
            report.add(file, ts_field, "must be empty or ISO-8601 with timezone")

    status = doc.get("status")
    if status not in ROLLUP_STATUS_ENUM:
        report.add(
            file,
            "status",
            f"must be one of {sorted(ROLLUP_STATUS_ENUM)}",
        )

    links = doc.get("rollup_links")
    if not isinstance(links, dict):
        report.add(file, "rollup_links", "must be a JSON object")
    else:
        for key in ROLLUP_LINK_KEYS:
            if key not in links:
                report.add(file, f"rollup_links.{key}", "required key missing")
                continue
            val = links[key]
            if not isinstance(val, str) or not val.startswith(
                f"state/welle-{welle_no}-"
            ) and not val.startswith(f"state/welle-{welle_no}.json"):
                report.add(
                    file,
                    f"rollup_links.{key}",
                    f'must start with "state/welle-{welle_no}-"',
                )
        # Specific shape per key.
        sign_off_link = links.get("sign_off")
        if isinstance(sign_off_link, str) and not sign_off_link.endswith(
            "-sign-off.json"
        ):
            report.add(
                file,
                "rollup_links.sign_off",
                'must end with "-sign-off.json"',
            )
        val_link = links.get("validation_last_verdict")
        if isinstance(val_link, str) and not val_link.endswith(
            "-validation-last-verdict.json"
        ):
            report.add(
                file,
                "rollup_links.validation_last_verdict",
                'must end with "-validation-last-verdict.json"',
            )
        trend_link = links.get("hot_spot_trend_dir")
        if isinstance(trend_link, str) and not trend_link.endswith(
            "-hot-spot-trend/"
        ):
            report.add(
                file,
                "rollup_links.hot_spot_trend_dir",
                'must end with "-hot-spot-trend/"',
            )
        pa_link = links.get("pre_auditor_decision")
        if isinstance(pa_link, str) and not pa_link.endswith(
            "-pre-auditor-decision.json"
        ):
            report.add(
                file,
                "rollup_links.pre_auditor_decision",
                'must end with "-pre-auditor-decision.json"',
            )

    anchor = doc.get("audit_trail_anchor")
    if not isinstance(anchor, str) or not OTS_ANCHOR_RE.match(anchor):
        report.add(
            file,
            "audit_trail_anchor",
            "must be empty or 64-hex OTS-anchor",
        )


def validate_sign_off(file: str, doc: Any, report: Report) -> None:
    """Validate a ``state/welle-N-sign-off.json`` file."""
    if not isinstance(doc, dict):
        report.add(file, "<root>", "sign-off file must be a JSON object")
        return

    _check_required(report, file, doc, SIGN_OFF_REQUIRED_FIELDS)

    path_welle = welle_number_from_path(file)
    welle_no = doc.get("welle_number")
    if not isinstance(welle_no, int):
        report.add(file, "welle_number", "must be an integer")
    elif welle_no < 1 or welle_no > 7:
        report.add(file, "welle_number", "must be in 1..7")
    elif path_welle is not None and welle_no != path_welle:
        report.add(
            file,
            "welle_number",
            f"mismatch: filename welle-{path_welle} but field={welle_no}",
        )

    if doc.get("status") not in SIGN_OFF_STATUS_ENUM:
        report.add(
            file,
            "status",
            f"must be one of {sorted(SIGN_OFF_STATUS_ENUM)}",
        )

    if not isinstance(doc.get("ac_1_5_green"), bool):
        report.add(file, "ac_1_5_green", "must be a boolean")

    consensus = doc.get("ac_4_consensus_personas")
    if not isinstance(consensus, list) or not all(
        isinstance(p, str) for p in consensus
    ):
        report.add(
            file,
            "ac_4_consensus_personas",
            "must be a list of persona-slug strings",
        )

    if doc.get("cross_welle_drift_assert") not in DRIFT_VERDICT_ENUM:
        report.add(
            file,
            "cross_welle_drift_assert",
            f"must be one of {sorted(DRIFT_VERDICT_ENUM)}",
        )

    for ts_field in ("cutover_iso", "signoff_iso"):
        if ts_field in doc:
            v = doc[ts_field]
            if not isinstance(v, str) or not ISO_TS_RE.match(v):
                report.add(
                    file,
                    ts_field,
                    "must be empty or ISO-8601 with timezone",
                )


def validate_validation(file: str, doc: Any, report: Report) -> None:
    """Validate a ``state/welle-N-validation-last-verdict.json`` file."""
    if not isinstance(doc, dict):
        report.add(file, "<root>", "validation file must be a JSON object")
        return

    _check_required(report, file, doc, VALIDATION_REQUIRED_FIELDS)

    path_welle = welle_number_from_path(file)
    welle_no = doc.get("welle_number")
    if not isinstance(welle_no, int):
        report.add(file, "welle_number", "must be an integer")
    elif welle_no < 1 or welle_no > 7:
        report.add(file, "welle_number", "must be in 1..7")
    elif path_welle is not None and welle_no != path_welle:
        report.add(
            file,
            "welle_number",
            f"mismatch: filename welle-{path_welle} but field={welle_no}",
        )

    if doc.get("verdict") not in VALIDATION_VERDICT_ENUM:
        report.add(
            file,
            "verdict",
            f"must be one of {sorted(VALIDATION_VERDICT_ENUM)}",
        )

    v_iso = doc.get("verdict_iso")
    if not isinstance(v_iso, str) or not ISO_TS_NONEMPTY_RE.match(v_iso):
        report.add(
            file,
            "verdict_iso",
            "must be non-empty ISO-8601 with timezone",
        )

    checks = doc.get("checks")
    if not isinstance(checks, list):
        report.add(file, "checks", "must be a JSON array")
    else:
        for i, ck in enumerate(checks):
            if not isinstance(ck, dict):
                report.add(file, f"checks[{i}]", "must be a JSON object")
                continue
            for ck_key in ("name", "verdict", "evidence_ref"):
                if ck_key not in ck:
                    report.add(
                        file,
                        f"checks[{i}].{ck_key}",
                        "required field missing",
                    )
            if ck.get("verdict") not in VALIDATION_VERDICT_ENUM:
                report.add(
                    file,
                    f"checks[{i}].verdict",
                    f"must be one of {sorted(VALIDATION_VERDICT_ENUM)}",
                )

    if doc.get("schema_version") != SCHEMA_VERSION_PIN:
        report.add(
            file,
            "schema_version",
            f'must equal "{SCHEMA_VERSION_PIN}"',
        )


def validate_hot_spot_day(file: str, doc: Any, report: Report) -> None:
    """Validate a ``state/welle-N-hot-spot-trend/<date>.json`` file."""
    if not isinstance(doc, dict):
        report.add(file, "<root>", "hot-spot-day file must be a JSON object")
        return

    for f in ("welle_number", "date", "aggregator_verdict", "checks", "schema_version"):
        if f not in doc:
            report.add(file, f, "required field missing")

    path_welle = welle_number_from_path(file)
    welle_no = doc.get("welle_number")
    if isinstance(welle_no, int) and path_welle is not None and welle_no != path_welle:
        report.add(
            file,
            "welle_number",
            f"mismatch: filename welle-{path_welle} but field={welle_no}",
        )
    if isinstance(welle_no, int) and (welle_no < 3 or welle_no > 7):
        report.add(file, "welle_number", "hot-spot-trend only defined for welle 3..7")

    date_v = doc.get("date")
    if not isinstance(date_v, str) or not DATE_RE.match(date_v):
        report.add(file, "date", "must be YYYY-MM-DD")

    if doc.get("aggregator_verdict") not in AGGREGATOR_VERDICT_ENUM:
        report.add(
            file,
            "aggregator_verdict",
            f"must be one of {sorted(AGGREGATOR_VERDICT_ENUM)}",
        )

    checks = doc.get("checks")
    if not isinstance(checks, dict):
        report.add(file, "checks", "must be a JSON object of check->verdict")
    else:
        for k, v in checks.items():
            if v not in VALIDATION_VERDICT_ENUM:
                report.add(
                    file,
                    f"checks.{k}",
                    f"must be one of {sorted(VALIDATION_VERDICT_ENUM)}",
                )

    if doc.get("schema_version") != SCHEMA_VERSION_PIN:
        report.add(
            file,
            "schema_version",
            f'must equal "{SCHEMA_VERSION_PIN}"',
        )


def validate_pre_auditor(file: str, doc: Any, report: Report) -> None:
    """Validate a ``state/welle-N-pre-auditor-decision.json`` file."""
    if not isinstance(doc, dict):
        report.add(file, "<root>", "pre-auditor file must be a JSON object")
        return

    for f in (
        "welle_number",
        "decision",
        "pre_auditor_slug",
        "designation_iso",
        "rationale_doc",
        "schema_version",
    ):
        if f not in doc:
            report.add(file, f, "required field missing")

    path_welle = welle_number_from_path(file)
    welle_no = doc.get("welle_number")
    if isinstance(welle_no, int) and path_welle is not None and welle_no != path_welle:
        report.add(
            file,
            "welle_number",
            f"mismatch: filename welle-{path_welle} but field={welle_no}",
        )
    if isinstance(welle_no, int) and (welle_no < 3 or welle_no > 7):
        report.add(
            file,
            "welle_number",
            "pre-auditor-decision only defined for welle 3..7",
        )

    if doc.get("decision") not in PRE_AUDITOR_DECISION_ENUM:
        report.add(
            file,
            "decision",
            f"must be one of {sorted(PRE_AUDITOR_DECISION_ENUM)}",
        )

    if not isinstance(doc.get("pre_auditor_slug"), str):
        report.add(file, "pre_auditor_slug", "must be a string (may be empty)")

    iso_v = doc.get("designation_iso")
    if not isinstance(iso_v, str) or not ISO_TS_RE.match(iso_v):
        report.add(
            file,
            "designation_iso",
            "must be empty or ISO-8601 with timezone",
        )

    if not isinstance(doc.get("rationale_doc"), str):
        report.add(file, "rationale_doc", "must be a string (may be empty)")

    if doc.get("schema_version") != SCHEMA_VERSION_PIN:
        report.add(
            file,
            "schema_version",
            f'must equal "{SCHEMA_VERSION_PIN}"',
        )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


KIND_DISPATCH = {
    "rollup": validate_rollup,
    "sign-off": validate_sign_off,
    "validation": validate_validation,
    "hot-spot-day": validate_hot_spot_day,
    "pre-auditor": validate_pre_auditor,
}


def verify_file(path: str | Path, kind_override: str | None = None) -> Report:
    """Verify a single state-file path.

    Parameters
    ----------
    path:
        Filesystem path.
    kind_override:
        If given, force the schema-kind instead of detecting from the path.
    """
    rpt = Report()
    rpt.files_checked = 1
    pth = Path(path)
    file_str = str(path)

    if not pth.exists():
        rpt.add(file_str, "<file>", "does not exist")
        return rpt

    try:
        doc = load_json(pth)
    except json.JSONDecodeError as exc:
        rpt.add(file_str, "<json>", f"invalid JSON: {exc}")
        return rpt

    kind = kind_override or detect_kind(file_str)
    validator = KIND_DISPATCH.get(kind)
    if validator is None:
        rpt.add(
            file_str,
            "<kind>",
            f"path does not match any known welle-state-file kind: {file_str}",
        )
        return rpt
    validator(file_str, doc, rpt)
    return rpt


def verify_many(paths: Sequence[str | Path]) -> Report:
    """Verify a sequence of paths and return an aggregate Report."""
    agg = Report()
    for p in paths:
        agg.merge(verify_file(p))
    return agg


def verify_doc(file_label: str, doc: Any, kind: str) -> Report:
    """Validate an already-loaded JSON document (test helper).

    Useful from test-suites that build fixtures in-memory without
    touching disk.
    """
    rpt = Report()
    rpt.files_checked = 1
    validator = KIND_DISPATCH.get(kind)
    if validator is None:
        rpt.add(file_label, "<kind>", f"unknown kind: {kind}")
        return rpt
    validator(file_label, doc, rpt)
    return rpt


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verify_welle_state_file_conventions",
        description=(
            "Verify state/welle-N-*.json files against the Tag-67 schema-pin."
        ),
    )
    p.add_argument(
        "files",
        nargs="*",
        help="state-file paths to verify (kind detected from filename)",
    )
    p.add_argument(
        "--rollup",
        action="append",
        default=[],
        help="force kind=rollup for the given path (can repeat)",
    )
    p.add_argument(
        "--sign-off",
        action="append",
        default=[],
        help="force kind=sign-off for the given path (can repeat)",
    )
    p.add_argument(
        "--validation",
        action="append",
        default=[],
        help="force kind=validation for the given path (can repeat)",
    )
    p.add_argument(
        "--hot-spot-day",
        action="append",
        default=[],
        help="force kind=hot-spot-day for the given path (can repeat)",
    )
    p.add_argument(
        "--pre-auditor",
        action="append",
        default=[],
        help="force kind=pre-auditor for the given path (can repeat)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    agg = Report()
    for f in args.files:
        agg.merge(verify_file(f))
    for f in args.rollup:
        agg.merge(verify_file(f, kind_override="rollup"))
    for f in args.sign_off:
        agg.merge(verify_file(f, kind_override="sign-off"))
    for f in args.validation:
        agg.merge(verify_file(f, kind_override="validation"))
    for f in args.hot_spot_day:
        agg.merge(verify_file(f, kind_override="hot-spot-day"))
    for f in args.pre_auditor:
        agg.merge(verify_file(f, kind_override="pre-auditor"))

    if agg.files_checked == 0:
        print(
            "verify_welle_state_file_conventions: no files supplied",
            file=sys.stderr,
        )
        return 2

    if agg.ok:
        print(
            f"verify_welle_state_file_conventions: OK ({agg.files_checked} files)"
        )
        return 0

    print(
        "verify_welle_state_file_conventions: VIOLATIONS",
        file=sys.stderr,
    )
    for v in agg.violations:
        print(f"  - {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
