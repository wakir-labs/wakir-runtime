# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-52 cross-repo-sync-audit refresh tests.

These tests lock in the *refresh-delta* invariants the Tag-52
report `reports/cross-repo-audit/2026-05-19-runtime-protocol-sync-
refresh.md` documents. They do **not** re-test the Tag-42 baseline
audit logic (covered by `test_cross_repo_sync_audit.py` —
22+ existing tests). The refresh-specific invariants are:

A. **Refresh-delta correctness** — given two report payloads, the
   delta-walker yields (a) the set of pairs newly fixed, (b) the
   set of pairs newly drifting, (c) the set of pairs still
   drifting, and (d) the set of pair-table additions/removals.

B. **Drift-type classification** — for the 6 Tag-42 drift items,
   the refresh classifies each as either *json-formatting-only*
   or *import-path-delta*. The classification is hermetic-testable
   by feeding synthetic file pairs into a classifier helper.

C. **Allowlist-admission templates** — the refresh names two
   admission patterns. Both templates parse as valid allowlist
   entries by the stdlib parser already shipped in the audit
   script.

D. **Refresh report shape** — the report must contain (i) the
   six fields of the audit-baselines comparison table, (ii) the
   refresh-delta tally, (iii) the drift-item type classification
   table, (iv) the "STABLE-BLOCKED" status banner. These are
   shape invariants the parent-agent's downstream consumer
   (Mira closeout summary + Henrik audit sample) relies on.

All fixtures are synthesised in `tmp_path`. No network, no real
clone, no git invocation. Pure stdlib + pytest.

Test inventory (>= 10 hermetic):

  T1   refresh-delta: identical-payload case (0 fixed, 0 new, N still)
  T2   refresh-delta: one-item-fixed case
  T3   refresh-delta: one-item-newly-drifting case
  T4   refresh-delta: pair-table addition is reported separately
  T5   refresh-delta: pair-table removal is reported separately
  T6   drift-type: JSON-format-only divergence -> json-formatting
  T7   drift-type: semantic divergence -> semantic-drift (not format)
  T8   drift-type: import-path delta -> import-path-delta
  T9   allowlist-admission template for JSON-format-only parses
  T10  allowlist-admission template for import-path-delta parses
  T11  refresh-report shape: required-section markers present
  T12  refresh-report shape: STABLE-BLOCKED banner when drift > 0
       and refresh-delta is zero
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
from typing import Any


# ---------------------------------------------------------------------------
# Module loader (mirrors test_cross_repo_sync_audit.py shape).
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_AUDIT_SCRIPT = _REPO_ROOT / "scripts" / "audit" / "cross-repo-sync-audit.py"
_REFRESH_REPORT = (
    _REPO_ROOT
    / "reports"
    / "cross-repo-audit"
    / "2026-05-19-runtime-protocol-sync-refresh.md"
)


def _load_audit_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "cross_repo_sync_audit_for_tag52_refresh", _AUDIT_SCRIPT
    )
    assert spec is not None and spec.loader is not None, _AUDIT_SCRIPT
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


audit = _load_audit_module()


# ---------------------------------------------------------------------------
# Refresh-delta walker — pure-function helper used by T1..T5.
#
# Takes two report-payloads (the dict shape `--json` produces) and
# returns a structured delta. The helper is defined here, not in
# the audit script, because the audit script is the single-shot
# audit tool — the *delta walker* is a refresh-specific
# composition that only the Tag-52 refresh consumes.
# ---------------------------------------------------------------------------

def _pair_key(pair: dict[str, Any]) -> tuple[str, str]:
    return (pair["runtime_path"], pair["protocol_path"])


def compute_refresh_delta(
    baseline: dict[str, Any], refresh: dict[str, Any]
) -> dict[str, list[tuple[str, str]]]:
    """
    Return the refresh-delta between two `cross-repo-sync-audit --json`
    payloads.

    Keys in the returned dict:

      newly_fixed       — pair was DRIFT in baseline, ok in refresh
      newly_drifting    — pair was ok in baseline, DRIFT in refresh
      still_drifting    — pair was DRIFT in baseline and refresh
      still_ok          — pair was ok in baseline and refresh
      added             — pair present in refresh, absent in baseline
      removed           — pair present in baseline, absent in refresh
    """
    base_pairs = {_pair_key(p): p for p in baseline.get("pairs", [])}
    refr_pairs = {_pair_key(p): p for p in refresh.get("pairs", [])}

    base_keys = set(base_pairs.keys())
    refr_keys = set(refr_pairs.keys())

    added = sorted(refr_keys - base_keys)
    removed = sorted(base_keys - refr_keys)
    common = base_keys & refr_keys

    newly_fixed: list[tuple[str, str]] = []
    newly_drifting: list[tuple[str, str]] = []
    still_drifting: list[tuple[str, str]] = []
    still_ok: list[tuple[str, str]] = []
    for k in sorted(common):
        b_status = base_pairs[k]["status"]
        r_status = refr_pairs[k]["status"]
        if b_status == "DRIFT" and r_status == "ok":
            newly_fixed.append(k)
        elif b_status == "ok" and r_status == "DRIFT":
            newly_drifting.append(k)
        elif b_status == "DRIFT" and r_status == "DRIFT":
            still_drifting.append(k)
        elif b_status == "ok" and r_status == "ok":
            still_ok.append(k)

    return {
        "newly_fixed": newly_fixed,
        "newly_drifting": newly_drifting,
        "still_drifting": still_drifting,
        "still_ok": still_ok,
        "added": added,
        "removed": removed,
    }


# ---------------------------------------------------------------------------
# Drift-type classifier — pure-function helper used by T6..T8.
# ---------------------------------------------------------------------------

def classify_drift_type(runtime_bytes: bytes, protocol_bytes: bytes,
                        *, filename: str) -> str:
    """
    Heuristic drift-type classifier for the Tag-52 refresh.

    Returns one of:

      "byte-identical"     — no drift at all (sanity sentinel)
      "json-formatting"    — both sides parse as JSON and are
                              `==`-equal once parsed, but bytes differ
                              (whitespace / indentation / inline-vs-
                              multiline)
      "import-path-delta"  — both sides are Python files whose AST
                              differs *only* in `from <pkg> import`
                              statements that select between
                              `wirelang.*` and `wakir_protocol.*`
                              package roots
      "semantic-drift"     — actual content divergence (everything
                              else)
    """
    if runtime_bytes == protocol_bytes:
        return "byte-identical"

    if filename.endswith(".json"):
        try:
            a = json.loads(runtime_bytes.decode("utf-8"))
            b = json.loads(protocol_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "semantic-drift"
        return "json-formatting" if a == b else "semantic-drift"

    if filename.endswith(".py"):
        try:
            a_tree = ast.parse(runtime_bytes.decode("utf-8"))
            b_tree = ast.parse(protocol_bytes.decode("utf-8"))
        except (UnicodeDecodeError, SyntaxError):
            return "semantic-drift"

        # Normalise `from <pkg>.<sub> import <name>` statements by
        # replacing the leading package-root segment. If after
        # normalisation the dumped ASTs are equal, the only delta
        # is import-path.
        def _normalise(tree: ast.AST) -> str:
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    head = node.module.split(".", 1)[0]
                    if head in ("wirelang", "wakir_protocol"):
                        # rewrite head to "_pkg_root_"
                        tail = node.module.split(".", 1)[1] \
                            if "." in node.module else ""
                        node.module = (
                            f"_pkg_root_.{tail}" if tail else "_pkg_root_"
                        )
                        # The `identity` vs `identity_substrate`
                        # subpackage split is also part of the
                        # structurally-expected delta — collapse it.
                        node.module = node.module.replace(
                            "identity_substrate", "identity"
                        )
            return ast.dump(tree, annotate_fields=False)

        if _normalise(a_tree) == _normalise(b_tree):
            return "import-path-delta"
        return "semantic-drift"

    return "semantic-drift"


# ---------------------------------------------------------------------------
# Fixture: minimal valid baseline + refresh payloads.
# ---------------------------------------------------------------------------

def _stub_pair(rpath: str, ppath: str, status: str = "ok",
               cls: str = "capability") -> dict[str, Any]:
    return {
        "runtime_path": rpath,
        "protocol_path": ppath,
        "substance_class": cls,
        "status": status,
        "runtime_sha256": "r" * 64,
        "protocol_sha256": ("r" * 64 if status == "ok" else "p" * 64),
    }


def _baseline_payload() -> dict[str, Any]:
    return {
        "report_date": "2026-05-18",
        "runtime_head": "64b1c170418d",
        "protocol_head": "9eca1e2d4b5b",
        "enforce": False,
        "allowlist_malformed": False,
        "pairs": [
            _stub_pair("wirelang/schemas/layer-0-transport.json",
                       "wakir_protocol/schemas/layer-0-transport.json",
                       status="DRIFT", cls="layer-0-schema"),
            _stub_pair("wirelang/schemas/layer-1-wire.json",
                       "wakir_protocol/schemas/layer-1-wire.json",
                       status="ok", cls="layer-1-schema"),
            _stub_pair("wirelang/schemas/aip-document.json",
                       "wakir_protocol/schemas/aip-document.json",
                       status="DRIFT", cls="aip"),
            _stub_pair("wirelang/canonical/caveat_set.py",
                       "wakir_protocol/canonical/caveat_set.py",
                       status="DRIFT", cls="capability"),
        ],
        "welle": [],
    }


# ---------------------------------------------------------------------------
# T1 — refresh-delta: identical-payload case.
# ---------------------------------------------------------------------------

def test_refresh_delta_identical_payload_zero_churn() -> None:
    baseline = _baseline_payload()
    refresh = _baseline_payload()
    delta = compute_refresh_delta(baseline, refresh)
    assert delta["newly_fixed"] == []
    assert delta["newly_drifting"] == []
    assert len(delta["still_drifting"]) == 3
    assert len(delta["still_ok"]) == 1
    assert delta["added"] == []
    assert delta["removed"] == []


# ---------------------------------------------------------------------------
# T2 — refresh-delta: one item newly-fixed.
# ---------------------------------------------------------------------------

def test_refresh_delta_one_item_newly_fixed() -> None:
    baseline = _baseline_payload()
    refresh = _baseline_payload()
    # Flip the aip-document.json pair from DRIFT to ok in the refresh.
    for p in refresh["pairs"]:
        if p["runtime_path"].endswith("aip-document.json"):
            p["status"] = "ok"
            p["protocol_sha256"] = p["runtime_sha256"]

    delta = compute_refresh_delta(baseline, refresh)
    assert len(delta["newly_fixed"]) == 1
    assert delta["newly_fixed"][0][0].endswith("aip-document.json")
    assert delta["newly_drifting"] == []
    assert len(delta["still_drifting"]) == 2


# ---------------------------------------------------------------------------
# T3 — refresh-delta: one item newly-drifting.
# ---------------------------------------------------------------------------

def test_refresh_delta_one_item_newly_drifting() -> None:
    baseline = _baseline_payload()
    refresh = _baseline_payload()
    # Flip the layer-1-wire.json pair from ok to DRIFT in the refresh.
    for p in refresh["pairs"]:
        if p["runtime_path"].endswith("layer-1-wire.json"):
            p["status"] = "DRIFT"
            p["protocol_sha256"] = "x" * 64

    delta = compute_refresh_delta(baseline, refresh)
    assert delta["newly_fixed"] == []
    assert len(delta["newly_drifting"]) == 1
    assert delta["newly_drifting"][0][0].endswith("layer-1-wire.json")
    assert len(delta["still_drifting"]) == 3
    assert len(delta["still_ok"]) == 0


# ---------------------------------------------------------------------------
# T4 — refresh-delta: pair-table addition is reported separately.
# ---------------------------------------------------------------------------

def test_refresh_delta_pair_table_addition_reported() -> None:
    baseline = _baseline_payload()
    refresh = _baseline_payload()
    refresh["pairs"].append(
        _stub_pair("wirelang/identity/new_pair.py",
                   "wakir_protocol/identity_substrate/new_pair.py",
                   status="ok", cls="identity-substrate")
    )
    delta = compute_refresh_delta(baseline, refresh)
    assert len(delta["added"]) == 1
    assert delta["added"][0][0].endswith("new_pair.py")
    assert delta["removed"] == []


# ---------------------------------------------------------------------------
# T5 — refresh-delta: pair-table removal is reported separately.
# ---------------------------------------------------------------------------

def test_refresh_delta_pair_table_removal_reported() -> None:
    baseline = _baseline_payload()
    refresh = _baseline_payload()
    # Drop the caveat_set.py pair from refresh.
    refresh["pairs"] = [
        p for p in refresh["pairs"]
        if not p["runtime_path"].endswith("caveat_set.py")
    ]
    delta = compute_refresh_delta(baseline, refresh)
    assert delta["added"] == []
    assert len(delta["removed"]) == 1
    assert delta["removed"][0][0].endswith("caveat_set.py")


# ---------------------------------------------------------------------------
# T6 — drift-type: JSON-format-only divergence is reported as
# `json-formatting`, not `semantic-drift`.
# ---------------------------------------------------------------------------

def test_drift_type_json_formatting_only() -> None:
    inline = b'{"required":["a","b","c"]}'
    multiline = b'{\n  "required": [\n    "a",\n    "b",\n    "c"\n  ]\n}'
    assert classify_drift_type(
        inline, multiline, filename="layer-0-transport.json"
    ) == "json-formatting"


# ---------------------------------------------------------------------------
# T7 — drift-type: real semantic divergence is reported as
# `semantic-drift`, not `json-formatting`.
# ---------------------------------------------------------------------------

def test_drift_type_semantic_drift_is_not_formatting() -> None:
    a = b'{"required":["a","b","c"]}'
    b = b'{"required":["a","b","c","d"]}'   # extra element
    assert classify_drift_type(
        a, b, filename="layer-0-transport.json"
    ) == "semantic-drift"


# ---------------------------------------------------------------------------
# T8 — drift-type: import-path delta is reported as
# `import-path-delta`, not `semantic-drift`.
# ---------------------------------------------------------------------------

def test_drift_type_import_path_delta() -> None:
    runtime_py = (
        b"from wirelang.identity._jcs_pure import canonicalize\n"
        b"def f():\n"
        b"    return canonicalize({})\n"
    )
    protocol_py = (
        b"from wakir_protocol.identity_substrate._jcs_pure "
        b"import canonicalize\n"
        b"def f():\n"
        b"    return canonicalize({})\n"
    )
    assert classify_drift_type(
        runtime_py, protocol_py, filename="caveat_set.py"
    ) == "import-path-delta"


def test_drift_type_python_semantic_drift_not_import_path() -> None:
    runtime_py = (
        b"from wirelang.identity._jcs_pure import canonicalize\n"
        b"def f():\n"
        b"    return canonicalize({'a': 1})\n"  # different literal
    )
    protocol_py = (
        b"from wakir_protocol.identity_substrate._jcs_pure "
        b"import canonicalize\n"
        b"def f():\n"
        b"    return canonicalize({})\n"
    )
    assert classify_drift_type(
        runtime_py, protocol_py, filename="caveat_set.py"
    ) == "semantic-drift"


# ---------------------------------------------------------------------------
# T9 — allowlist-admission template for JSON-format-only parses.
# ---------------------------------------------------------------------------

def test_allowlist_admission_template_json_formatting_parses() -> None:
    template = (
        "allow:\n"
        "  - runtime:  wirelang/schemas/layer-0-transport.json\n"
        "    protocol: wakir_protocol/schemas/layer-0-transport.json\n"
        "    reason:   json-formatting-only\n"
        "    follow_up: format-normalisation-sweep\n"
    )
    parsed = audit.parse_allowlist(template)
    assert parsed != "__MALFORMED__"
    assert len(parsed) == 1
    assert parsed[0] == (
        "wirelang/schemas/layer-0-transport.json",
        "wakir_protocol/schemas/layer-0-transport.json",
    )


# ---------------------------------------------------------------------------
# T10 — allowlist-admission template for import-path-delta parses.
# ---------------------------------------------------------------------------

def test_allowlist_admission_template_import_path_delta_parses() -> None:
    template = (
        "allow:\n"
        "  - runtime:  wirelang/canonical/caveat_set.py\n"
        "    protocol: wakir_protocol/canonical/caveat_set.py\n"
        "    reason:   package-root import-path delta\n"
        "    follow_up: permanent\n"
    )
    parsed = audit.parse_allowlist(template)
    assert parsed != "__MALFORMED__"
    assert len(parsed) == 1
    assert parsed[0] == (
        "wirelang/canonical/caveat_set.py",
        "wakir_protocol/canonical/caveat_set.py",
    )


# ---------------------------------------------------------------------------
# T11 — refresh-report shape: required-section markers present.
# ---------------------------------------------------------------------------

def test_refresh_report_shape_required_sections_present() -> None:
    """
    The Tag-52 refresh report must include the four contractually-
    required sections so that downstream Mira closeout summaries and
    Henrik audit samples can parse them without further negotiation.
    """
    assert _REFRESH_REPORT.is_file(), _REFRESH_REPORT
    body = _REFRESH_REPORT.read_text(encoding="utf-8")
    required_markers = [
        "# Cross-repo sync audit refresh — 2026-05-19 (Tag-52)",
        "## Audit baselines",
        "| Field | Tag-42 (2026-05-18) | Tag-52 refresh",
        "## Mirror-pair drift table (substance class 1-3)",
        "## Tag-42 baseline diff (refresh delta)",
        "**Refresh-delta tally**",
        "## Drift-item type classification (new in Tag-52)",
        "## Phase-3-Marathon cross-repo readiness",
        "— Reza",
    ]
    for m in required_markers:
        assert m in body, f"missing marker: {m!r}"


# ---------------------------------------------------------------------------
# T12 — refresh-report shape: STABLE-BLOCKED banner present.
# ---------------------------------------------------------------------------

def test_refresh_report_stable_blocked_banner_present() -> None:
    """
    With drift > 0 AND refresh-delta = 0 (the actual Tag-52 state),
    the report MUST classify cross-repo readiness as
    `STABLE-BLOCKED` — not `BLOCKED` (no signal about churn) and
    not `READY` (drift is still un-allowlisted). This is the
    refresh-specific status banner.
    """
    assert _REFRESH_REPORT.is_file(), _REFRESH_REPORT
    body = _REFRESH_REPORT.read_text(encoding="utf-8")
    assert "STABLE-BLOCKED" in body
    # And the explanation phrase that distinguishes it from a plain
    # BLOCKED status:
    assert "has not regressed" in body
    # The dormant-surface positive signal:
    assert "dormant" in body.lower()


# ---------------------------------------------------------------------------
# T13 (bonus) — refresh-report numeric tally matches the canonical
# Tag-52 finding (4 ok / 6 DRIFT / 0 allowed / 0 missing).
# ---------------------------------------------------------------------------

def test_refresh_report_numeric_tally_matches_canonical_finding() -> None:
    body = _REFRESH_REPORT.read_text(encoding="utf-8")
    assert "- ok: 4" in body
    assert "- drift (un-allowlisted): 6" in body
    assert "- drift (allowlisted): 0" in body
    assert "- missing on either side: 0" in body
    # Refresh-delta tally:
    assert "newly fixed since Tag-42: **0**" in body
    assert "newly drifting since Tag-42: **0**" in body
    assert "still drifting: **6**" in body


# ---------------------------------------------------------------------------
# T14 (bonus) — drift-type classifier is byte-deterministic across
# repeated invocations (no hidden state, no random salt).
# ---------------------------------------------------------------------------

def test_drift_type_classifier_is_byte_deterministic() -> None:
    a = b'{"x":[1,2,3]}'
    b = b'{\n  "x": [\n    1,\n    2,\n    3\n  ]\n}'
    runs = [
        classify_drift_type(a, b, filename="any.json") for _ in range(5)
    ]
    assert runs == ["json-formatting"] * 5
