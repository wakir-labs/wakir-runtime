# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-61 6-Layer Acceptance-
Pyramide Cross-Layer Dependency-DAG Drift-Allowlist mechanic
(extension of ``tooling/ci/verify_layer_dependency_dag.py`` and
``.github/workflows/pyramide-layer-dependency-verify-gate.yml``,
plus the new file ``tooling/ci/layer-dag-drift-allowlist.json``).

Auftrag-Anker
-------------

Tag-61 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
extend the Tag-58 Layer-DAG-Verify-Gate with an Allowlist-mechanic
analogue to the ADR-Errata CI-pin-skip pattern (Tag-59 audit-pin-
gate). Legitimate cross-layer imports that the DAG-spec does NOT
yet declare should NOT block CI - they should be explicitly
allowlisted with (edge, reason, follow_up). Verdict-vocabulary
extension:

  - DAG-CONSISTENT       : declared == observed (exit 0)
  - DAG-DRIFT-ALLOWED    : residual extras all allowlisted (exit 0)
  - DAG-DRIFT-BLOCKED    : residual extras OR missing remain (exit 2)

Missing edges remain non-allowlistable (those are spec-bugs).

Scope (allowlist load + verdict split + workflow shape)
-------------------------------------------------------

This module verifies three surfaces:

* The Tag-61 helper additions:
  - ``load_allowlist()`` returns (entries, errors) and validates
    each entry shape (from_layer/to_layer in 1..6, no self-edges,
    non-empty reason + follow_up, no duplicate edges)
  - ``verify()`` accepts an ``allowlist_path`` kwarg, defaults to
    repo-root/tooling/ci/layer-dag-drift-allowlist.json
  - DAG-DRIFT-ALLOWED is emitted when residual extras are fully
    covered (exit 0)
  - DAG-DRIFT-BLOCKED is emitted when residual extras OR missing
    edges remain (exit 2)
  - Stale allowlist entries (allowlist edge not observed) are
    surfaced as notes, not blocking
  - Missing edges are NEVER allowlistable
  - Malformed allowlist surfaces as DAG-PARSE-ERROR (exit 1)
  - CLI accepts --allowlist-path
  - VerifyResult.to_json() includes the new fields

* The Tag-61 allowlist file:
  - JSON-parses, has ``_schema`` + ``entries`` keys
  - Initial state is empty (entries == [])
  - ``_schema`` carries owner, tag, follow-up requirement docs

* The Tag-61 workflow YAML additions:
  - path-filter includes the allowlist file and the Tag-61 suite
  - Stage 2 passes --allowlist-path to the helper

Hermetic-tests
--------------

Auftrag minimum: >= 12 hermetic tests. This module ships >= 18.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "verify_layer_dependency_dag.py"
ALLOWLIST_PATH = REPO_ROOT / "tooling" / "ci" / "layer-dag-drift-allowlist.json"
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "pyramide-layer-dependency-verify-gate.yml"
)


@pytest.fixture(scope="module")
def helper_module():
    """Load the verifier helper as an importable module without
    requiring tooling/ to be on sys.path. Mirrors the Tag-58
    fixture; see that file for the ``@dataclass`` + ``sys.modules``
    rationale on Python 3.13+."""
    assert HELPER_PATH.is_file(), f"helper missing: {HELPER_PATH}"
    mod_name = "verify_layer_dependency_dag_under_test_tag61"
    spec = importlib.util.spec_from_file_location(mod_name, HELPER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


def _write_allowlist(
    path: Path,
    entries: List[Dict[str, object]],
    *,
    schema_obj: Dict[str, object] | None = None,
    raw_doc: object | None = None,
) -> Path:
    """Write a synthetic allowlist file. If ``raw_doc`` is provided
    (not None) it is used verbatim - the ``entries`` arg is then
    ignored. Otherwise build a well-formed schema envelope around
    ``entries``."""
    if raw_doc is not None:
        path.write_text(
            raw_doc if isinstance(raw_doc, str) else json.dumps(raw_doc),
            encoding="utf-8",
        )
        return path
    doc: Dict[str, object] = {
        "_schema": schema_obj
        or {
            "version": 1,
            "description": "synthetic test allowlist",
            "owner": "Amara Osei (QA) - test fixture",
            "tag": "Tag-61-test",
        },
        "entries": entries,
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------
# Section A - Allowlist file shape (the in-repo Tag-61 file)
# ---------------------------------------------------------------


def test_allowlist_file_exists_and_parses():
    """``tooling/ci/layer-dag-drift-allowlist.json`` must exist
    and be valid JSON in the Tag-61 substrate snapshot."""
    assert ALLOWLIST_PATH.is_file(), (
        f"Tag-61 allowlist file missing at {ALLOWLIST_PATH}"
    )
    doc = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "allowlist top-level must be a JSON object"
    assert "_schema" in doc, "allowlist must have a _schema key"
    assert "entries" in doc, "allowlist must have an entries key"
    assert isinstance(doc["entries"], list), "entries must be a list"


def test_allowlist_initial_state_is_empty():
    """By design the Tag-61 initial allowlist ships empty (no
    legitimate drift edges known at activation time). Future PRs
    that need an allowance must edit this file with a tracked
    follow-up reference - it must not silently accumulate."""
    doc = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert doc["entries"] == [], (
        f"Tag-61 initial allowlist must ship empty; got "
        f"{len(doc['entries'])} entries"
    )


def test_allowlist_schema_carries_required_metadata():
    """The ``_schema`` block must declare version, description,
    owner, tag, and the entry_schema sub-block so the file is
    self-describing for future operators."""
    doc = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    schema = doc["_schema"]
    assert isinstance(schema.get("version"), int)
    assert isinstance(schema.get("description"), str) and schema["description"]
    assert isinstance(schema.get("owner"), str) and "Amara" in schema["owner"]
    assert schema.get("tag") == "Tag-61"
    assert isinstance(schema.get("entry_schema"), dict)
    sub = schema["entry_schema"]
    for required_key in ("from_layer", "to_layer", "reason", "follow_up"):
        assert required_key in sub, (
            f"entry_schema must document {required_key!r}; got {list(sub)}"
        )


# ---------------------------------------------------------------
# Section B - load_allowlist() validator
# ---------------------------------------------------------------


def test_load_allowlist_missing_file_is_empty(helper_module, tmp_path):
    """A missing allowlist file is documented as an empty allowlist,
    NOT a parse error. (Tag-61 default-on, empty-by-default.)"""
    missing = tmp_path / "no-such-allowlist.json"
    assert not missing.exists()
    entries, errors = helper_module.load_allowlist(missing)
    assert entries == []
    assert errors == []


def test_load_allowlist_empty_entries_returns_empty(helper_module, tmp_path):
    """A well-formed file with ``entries: []`` returns empty + no
    errors (the initial Tag-61 state)."""
    p = _write_allowlist(tmp_path / "empty.json", entries=[])
    entries, errors = helper_module.load_allowlist(p)
    assert entries == []
    assert errors == []


def test_load_allowlist_valid_entry_parses(helper_module, tmp_path):
    """A well-formed entry with from_layer/to_layer/reason/follow_up
    becomes a single AllowlistEntry."""
    p = _write_allowlist(
        tmp_path / "ok.json",
        entries=[
            {
                "from_layer": 4,
                "to_layer": 2,
                "reason": "L4 needs L2 fixtures for negative-companion path",
                "follow_up": "ADR-9999 (synthetic test)",
            }
        ],
    )
    entries, errors = helper_module.load_allowlist(p)
    assert errors == []
    assert len(entries) == 1
    e = entries[0]
    assert e.from_layer == 4
    assert e.to_layer == 2
    assert "negative-companion" in e.reason
    assert "ADR-9999" in e.follow_up


def test_load_allowlist_rejects_self_edge(helper_module, tmp_path):
    """A self-edge L3 -> L3 must surface as an error and be dropped."""
    p = _write_allowlist(
        tmp_path / "self-edge.json",
        entries=[
            {
                "from_layer": 3,
                "to_layer": 3,
                "reason": "x",
                "follow_up": "ADR-x",
            }
        ],
    )
    entries, errors = helper_module.load_allowlist(p)
    assert entries == []
    assert any("self-edge" in e for e in errors), (
        f"expected self-edge error; got {errors}"
    )


def test_load_allowlist_rejects_out_of_range_layer(helper_module, tmp_path):
    """Layer ids must be in 1..6. 7 must be rejected."""
    p = _write_allowlist(
        tmp_path / "oor.json",
        entries=[
            {
                "from_layer": 7,
                "to_layer": 1,
                "reason": "x",
                "follow_up": "ADR-x",
            }
        ],
    )
    entries, errors = helper_module.load_allowlist(p)
    assert entries == []
    assert any("from_layer" in e for e in errors), (
        f"expected from_layer error; got {errors}"
    )


def test_load_allowlist_rejects_missing_follow_up(helper_module, tmp_path):
    """Missing follow_up is an error - every allowance must track
    a permanent-fix reference."""
    p = _write_allowlist(
        tmp_path / "no-followup.json",
        entries=[
            {
                "from_layer": 4,
                "to_layer": 2,
                "reason": "legitimate cross-import",
                # follow_up missing
            }
        ],
    )
    entries, errors = helper_module.load_allowlist(p)
    assert entries == []
    assert any("follow_up" in e for e in errors), (
        f"expected follow_up error; got {errors}"
    )


def test_load_allowlist_rejects_empty_reason(helper_module, tmp_path):
    """Whitespace-only reason is rejected."""
    p = _write_allowlist(
        tmp_path / "empty-reason.json",
        entries=[
            {
                "from_layer": 4,
                "to_layer": 2,
                "reason": "   ",
                "follow_up": "ADR-x",
            }
        ],
    )
    entries, errors = helper_module.load_allowlist(p)
    assert entries == []
    assert any("reason" in e for e in errors)


def test_load_allowlist_rejects_duplicate_edges(helper_module, tmp_path):
    """Two entries for the same (from, to) is an error - one reason
    + one follow-up per edge keeps the audit-trail singular."""
    p = _write_allowlist(
        tmp_path / "dup.json",
        entries=[
            {
                "from_layer": 4,
                "to_layer": 2,
                "reason": "first reason",
                "follow_up": "ADR-1",
            },
            {
                "from_layer": 4,
                "to_layer": 2,
                "reason": "second reason",
                "follow_up": "ADR-2",
            },
        ],
    )
    entries, errors = helper_module.load_allowlist(p)
    # First entry kept; second flagged as duplicate
    assert len(entries) == 1
    assert any("duplicate" in e.lower() for e in errors), (
        f"expected duplicate-edge error; got {errors}"
    )


def test_load_allowlist_malformed_json_yields_error(helper_module, tmp_path):
    """Top-level invalid JSON is a parse error, not a silent
    empty-list."""
    p = tmp_path / "bad.json"
    p.write_text("{ this is not valid JSON", encoding="utf-8")
    entries, errors = helper_module.load_allowlist(p)
    assert entries == []
    assert errors, "expected non-empty errors for malformed JSON"
    assert "JSON parse failure" in errors[0]


def test_load_allowlist_top_level_array_is_error(helper_module, tmp_path):
    """The top-level must be an object - a bare JSON array is
    rejected."""
    p = tmp_path / "arr.json"
    p.write_text("[]", encoding="utf-8")
    entries, errors = helper_module.load_allowlist(p)
    assert entries == []
    assert errors
    assert "top-level" in errors[0]


def test_load_allowlist_entries_not_a_list_is_error(helper_module, tmp_path):
    """``entries`` must be a list."""
    p = _write_allowlist(
        tmp_path / "wrong-shape.json",
        entries=[],
        raw_doc={"_schema": {"version": 1}, "entries": "not a list"},
    )
    entries, errors = helper_module.load_allowlist(p)
    assert entries == []
    assert any("not a list" in e for e in errors)


# ---------------------------------------------------------------
# Section C - verify() integration with allowlist
# ---------------------------------------------------------------


def test_verify_consistent_emits_consistent_with_empty_allowlist(
    helper_module, tmp_path
):
    """Default (empty) allowlist + the canonical repo substrate
    yields DAG-CONSISTENT (the Tag-58 baseline is preserved)."""
    # Empty allowlist file
    empty = _write_allowlist(tmp_path / "empty.json", entries=[])
    result = helper_module.verify(
        REPO_ROOT, strict=False, allowlist_path=empty
    )
    assert result.verdict == "DAG-CONSISTENT", (
        f"unexpected verdict {result.verdict!r}; notes={result.notes}"
    )
    assert result.exit_code == 0
    assert result.allowlisted_extras == []
    assert result.stale_allowlist_entries == []


def test_verify_strict_blocks_when_no_allowlist_coverage(
    helper_module, tmp_path
):
    """Under --strict, the (1, 2) soft-cite becomes a residual
    extra. With an empty allowlist that residual blocks - verdict
    DAG-DRIFT-BLOCKED, exit 2."""
    empty = _write_allowlist(tmp_path / "empty.json", entries=[])
    result = helper_module.verify(
        REPO_ROOT, strict=True, allowlist_path=empty
    )
    assert result.verdict == "DAG-DRIFT-BLOCKED"
    assert result.exit_code == 2
    assert (1, 2) in result.extra_edges
    assert result.allowlisted_extras == []


def test_verify_strict_allows_when_allowlist_covers_soft_cite(
    helper_module, tmp_path
):
    """Under --strict + allowlist that covers (1, 2), the soft-
    cite is no longer blocking; verdict downgrades to DAG-DRIFT-
    ALLOWED with exit 0."""
    al = _write_allowlist(
        tmp_path / "covers-1-2.json",
        entries=[
            {
                "from_layer": 1,
                "to_layer": 2,
                "reason": (
                    "L2 docstring cites L1 (Tag-40 anchor) for context; "
                    "non-topology citation."
                ),
                "follow_up": (
                    "ADR-0066 §4.1 spec-update to declare (1, 2) as a "
                    "soft-cite-strict-pass edge"
                ),
            }
        ],
    )
    result = helper_module.verify(
        REPO_ROOT, strict=True, allowlist_path=al
    )
    assert result.verdict == "DAG-DRIFT-ALLOWED", (
        f"unexpected verdict {result.verdict!r}; "
        f"extras={result.extra_edges}, allowlisted="
        f"{result.allowlisted_extras}, notes={result.notes}"
    )
    assert result.exit_code == 0
    assert (1, 2) in result.allowlisted_extras
    assert result.extra_edges == [], (
        f"residual extras must be empty when fully allowlisted; "
        f"got {result.extra_edges}"
    )


def test_verify_allowlist_does_not_excuse_missing_edges(
    helper_module, tmp_path
):
    """Missing edges (declared-but-not-observed) MUST never be
    allowlistable - they are SPEC bugs, not legitimate drift. We
    verify this by patching ``_aggregate_observed_edges`` on a
    fresh helper instance to drop one observed edge (L1, 3) so
    that the declared source-cited edge (1, 3) becomes missing.
    Then we attempt to allowlist (1, 3) and confirm it does not
    rescue the verdict from BLOCKED."""
    mod_name = "verify_layer_dependency_dag_under_test_tag61_isolated_missing"
    spec = importlib.util.spec_from_file_location(mod_name, HELPER_PATH)
    assert spec is not None and spec.loader is not None
    iso = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = iso
    try:
        spec.loader.exec_module(iso)
        # Drop (1, 3) from the observed-edge-set. This simulates a
        # substrate where L3 no longer cites L1's filename, which
        # would make the declared (1, 3) edge missing.
        original_aggregator = iso._aggregate_observed_edges

        def patched_aggregator(refs):
            edges = original_aggregator(refs)
            return {e for e in edges if e != (1, 3)}

        iso._aggregate_observed_edges = patched_aggregator
        # Try to allowlist (1, 3). The allowlist is extras-only;
        # missing edges should NOT be rescuable.
        al = _write_allowlist(
            tmp_path / "tries-to-rescue-missing.json",
            entries=[
                {
                    "from_layer": 1,
                    "to_layer": 3,
                    "reason": "trying to silence a missing-edge bug",
                    "follow_up": "ADR-fake",
                }
            ],
        )
        result = iso.verify(
            REPO_ROOT, strict=False, allowlist_path=al
        )
    finally:
        sys.modules.pop(mod_name, None)
    # The missing edge must remain blocking even though the
    # allowlist mentions it - allowlist is extras-only.
    assert result.verdict == "DAG-DRIFT-BLOCKED", (
        f"missing edges must not be allowlistable; got "
        f"verdict={result.verdict!r} missing={result.missing_edges}"
    )
    assert result.exit_code == 2
    assert (1, 3) in result.missing_edges


def test_verify_surfaces_stale_allowlist_entries(helper_module, tmp_path):
    """An allowlist entry whose edge is not actually observed in
    the substrate is surfaced as a stale-allowlist-entry note but
    NOT blocking. (Operator-hygiene: prune stale entries when the
    underlying cross-import is refactored away.)"""
    # (3, 3) is invalid (self-edge), so we use a plausible-but-
    # unobserved edge. The substrate at main-tip does not cite
    # L4 from L1 textually (the (1, 4) direction is L1->L4 declared,
    # not L4->L1). Allowlist L4->L1 (which is neither declared nor
    # observed) - it should be stale.
    al = _write_allowlist(
        tmp_path / "stale.json",
        entries=[
            {
                "from_layer": 4,
                "to_layer": 1,
                "reason": "no longer observed; refactor cleaned this up",
                "follow_up": "issue-stub-1234",
            }
        ],
    )
    result = helper_module.verify(
        REPO_ROOT, strict=False, allowlist_path=al
    )
    # Substrate is still DAG-CONSISTENT because the stale entry
    # neither rescues a missing edge nor matches an observed extra.
    assert result.verdict == "DAG-CONSISTENT"
    assert (4, 1) in result.stale_allowlist_entries


def test_verify_malformed_allowlist_is_parse_error(helper_module, tmp_path):
    """A malformed allowlist file surfaces as DAG-PARSE-ERROR
    (exit 1), not a silent pass-through."""
    p = tmp_path / "bad.json"
    p.write_text("not valid json {", encoding="utf-8")
    result = helper_module.verify(
        REPO_ROOT, strict=False, allowlist_path=p
    )
    assert result.verdict == "DAG-PARSE-ERROR"
    assert result.exit_code == 1
    assert any("allowlist" in pe for pe in result.parse_errors)


def test_verify_default_allowlist_path_resolves_to_repo_file(helper_module):
    """When allowlist_path is None, the helper resolves to
    {repo_root}/tooling/ci/layer-dag-drift-allowlist.json. Confirm
    the constant exposes that relative path."""
    assert helper_module.DEFAULT_ALLOWLIST_RELPATH == (
        "tooling/ci/layer-dag-drift-allowlist.json"
    )
    # And verify() with no allowlist_path arg still loads the in-
    # repo allowlist successfully (empty initial entries).
    result = helper_module.verify(REPO_ROOT, strict=False)
    assert result.verdict == "DAG-CONSISTENT"


def test_verify_result_to_json_includes_tag61_fields(helper_module, tmp_path):
    """VerifyResult.to_json() must include the new Tag-61 fields
    so the workflow Step-Summary renderer can consume them."""
    al = _write_allowlist(tmp_path / "empty.json", entries=[])
    result = helper_module.verify(
        REPO_ROOT, strict=False, allowlist_path=al
    )
    envelope = json.loads(result.to_json())
    for required_key in (
        "verdict",
        "exit_code",
        "declared_edges",
        "observed_edges",
        "missing_edges",
        "extra_edges",
        "allowlisted_extras",
        "stale_allowlist_entries",
        "soft_cites_skipped",
        "notes",
    ):
        assert required_key in envelope, (
            f"envelope missing key {required_key!r}; "
            f"got {sorted(envelope)}"
        )


# ---------------------------------------------------------------
# Section D - CLI surface
# ---------------------------------------------------------------


def test_cli_accepts_allowlist_path_flag(helper_module, tmp_path):
    """The CLI argparser exposes ``--allowlist-path`` as a flag."""
    parser = helper_module._build_argparser()
    args = parser.parse_args(
        ["--repo-root", str(REPO_ROOT),
         "--allowlist-path", str(ALLOWLIST_PATH)]
    )
    assert args.allowlist_path == ALLOWLIST_PATH


def test_cli_end_to_end_with_in_repo_allowlist():
    """End-to-end: invoke the helper as a subprocess against the
    real repo with the real allowlist - verdict must be
    DAG-CONSISTENT and exit 0."""
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--repo-root", str(REPO_ROOT),
            "--allowlist-path", str(ALLOWLIST_PATH),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"non-zero exit {result.returncode}; "
        f"stdout={result.stdout[:500]}; stderr={result.stderr[:500]}"
    )
    envelope = json.loads(result.stdout)
    assert envelope["verdict"] == "DAG-CONSISTENT"
    assert envelope["allowlisted_extras"] == []


# ---------------------------------------------------------------
# Section E - Workflow YAML shape (Tag-61 additions)
# ---------------------------------------------------------------


def test_workflow_path_filter_includes_allowlist_file():
    """The Tag-61 path-filter must include the new allowlist file
    so edits to the allowlist re-fire the gate."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "tooling/ci/layer-dag-drift-allowlist.json" in text, (
        "workflow path-filter must list the allowlist file"
    )
    # Both push and pull_request branches must list it.
    push_matches = re.findall(
        r"layer-dag-drift-allowlist\.json", text
    )
    assert len(push_matches) >= 2, (
        f"allowlist file must appear in both push and pull_request "
        f"path-filters; got {len(push_matches)} occurrences"
    )


def test_workflow_path_filter_includes_tag61_test_suite():
    """The Tag-61 path-filter must include the Tag-61 test-file
    so edits to the suite re-fire the gate."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "tests/ci/test_layer_dag_drift_allowlist_tag61.py" in text, (
        "workflow path-filter must list the Tag-61 test-suite"
    )


def test_workflow_stage_2_passes_allowlist_flag():
    """Workflow Stage 2 must invoke the helper with
    ``--allowlist-path tooling/ci/layer-dag-drift-allowlist.json``
    so the live verify uses the in-repo allowlist."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "--allowlist-path" in text, (
        "workflow must pass --allowlist-path to helper"
    )
    assert "tooling/ci/layer-dag-drift-allowlist.json" in text


def test_workflow_runs_both_tag58_and_tag61_test_suites():
    """Stage 1 must execute both test-suites so a regression in
    either fails the gate."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "test_layer_dependency_dag_verify_tag58.py" in text
    assert "test_layer_dag_drift_allowlist_tag61.py" in text


# ---------------------------------------------------------------
# Section F - Cross-Review marker compliance
# ---------------------------------------------------------------


def test_helper_docstring_references_allowlist_pattern():
    """The helper module-docstring must explain the Tag-61
    DAG-DRIFT-ALLOWED verdict and the allowlist file format so
    future operators can read it standalone."""
    text = HELPER_PATH.read_text(encoding="utf-8")
    assert "DAG-DRIFT-ALLOWED" in text
    assert "DAG-DRIFT-BLOCKED" in text
    assert "follow_up" in text or "follow-up" in text


def test_allowlist_schema_lists_cross_review_markers():
    """The allowlist _schema must mention Zone-M (Engineering
    cross-review via Tomás) and Zone-N (Henrik audit boundary)
    so the file is self-explanatory about who validates entries."""
    doc = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    markers = doc["_schema"].get("cross_review_markers", [])
    assert isinstance(markers, list) and markers
    combined = " ".join(markers)
    assert "Zone-M" in combined
    assert "Zone-N" in combined
    assert "Henrik" in combined or "Audit" in combined
