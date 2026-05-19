# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-66 Watch-Day Operator-Trigger Audit-Trail verifier tests (Noa SRE).

Pins the substance contract of
``tooling/ci/verify_watch_day_operator_trigger_audit_trail.py`` and
its co-substrates:

  * the canonical audit-marker schema + required-key-set,
  * the audit_marker_tag pattern + four marker classes,
  * the per-envelope green/yellow/red classification,
  * the cross-substrate marker-reference check,
  * the four-stage aggregate verdict mapping,
  * the CLI subcommand surface (stdlib-only, hermetic),
  * the workflow file's path-filter list + status-check name.

Hermetic: pytest + stdlib + python 3.11. No subprocess except the
inline integration test that drives the helper end-to-end (calls
out to the helper's own subprocess Tag-62 invocation; if Tag-62
helper is missing the test skips).

Author: Noa Bergstroem (SRE)
Anchor: Tag-66 Marathon-Continuous-Mode Pre-KW-24 Watch-Day
        Operator-Trigger Audit-Trail Verifier.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "verify_watch_day_operator_trigger_audit_trail.py"
)
WORKFLOW = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "watch-day-operator-trigger-audit-trail-verify.yml"
)
MARKER_CATALOG_MD = (
    REPO_ROOT
    / "docs"
    / "observability"
    / "watch-day-operator-trigger-audit-trail-marker-catalog.md"
)
TAG62_HELPER = (
    REPO_ROOT / "tooling" / "ci" / "simulate_watch_day_operator_trigger.py"
)


def _import_helper():
    mod_name = "verify_watch_day_operator_trigger_audit_trail"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, HELPER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec_module so dataclass(__module__) can resolve
    # the module via sys.modules during type-annotation introspection
    # (python 3.14 dataclasses strictness).
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# T01 - helper script exists, importable, has CLI entry.
# ---------------------------------------------------------------------------
def test_t01_helper_exists_and_importable():
    assert HELPER.is_file(), f"helper missing: {HELPER}"
    mod = _import_helper()
    assert hasattr(mod, "main")
    assert hasattr(mod, "build_parser")
    assert hasattr(mod, "AUDIT_MARKER_CATALOG")
    assert hasattr(mod, "AUDIT_MARKER_TAG_PATTERN")
    assert hasattr(mod, "synthesize_audit_trail_envelope")


# ---------------------------------------------------------------------------
# T02 - canonical verdict constants single-sourced (no string drift).
# ---------------------------------------------------------------------------
def test_t02_canonical_verdict_constants():
    mod = _import_helper()
    assert mod.VERDICT_INTACT == "AUDIT-TRAIL-INTACT"
    assert mod.VERDICT_DRIFT == "AUDIT-TRAIL-DRIFT"
    assert mod.VERDICT_DEFECT == "AUDIT-TRAIL-DEFECT"
    assert mod.STAGE_GREEN == "green"
    assert mod.STAGE_YELLOW == "yellow"
    assert mod.STAGE_RED == "red"
    # Exit code contract: 0=OK, 1=ERROR, 2=CAUTION.
    assert mod.EXIT_OK == 0
    assert mod.EXIT_ERROR == 1
    assert mod.EXIT_CAUTION == 2


# ---------------------------------------------------------------------------
# T03 - audit-marker-tag pattern matches canonical examples + rejects junk.
# ---------------------------------------------------------------------------
def test_t03_audit_marker_tag_pattern():
    mod = _import_helper()
    pat = mod.AUDIT_MARKER_TAG_PATTERN
    # Positive cases: one per source class.
    assert pat.match("watch-day-operator-20260609-3bc7794")
    assert pat.match("watch-day-ar-20260609-7a9b00e")
    assert pat.match("watch-day-cron-20260609-3bc7794")
    assert pat.match("watch-day-replay-20260612-deadbeef0")
    # Negative cases: wrong source, malformed date, wrong prefix.
    assert not pat.match("watch-day-foo-20260609-3bc7794")
    assert not pat.match("watch-day-operator-2026-06-09-3bc7794")
    assert not pat.match("operator-20260609-3bc7794")
    assert not pat.match("watch-day-operator-20260609")
    assert not pat.match("")


# ---------------------------------------------------------------------------
# T04 - AUDIT_MARKER_CATALOG enumerates the four canonical classes.
# ---------------------------------------------------------------------------
def test_t04_marker_catalog_has_four_canonical_classes():
    mod = _import_helper()
    sources = {m.source for m in mod.AUDIT_MARKER_CATALOG}
    assert sources == {"operator", "ar", "cron", "replay"}
    # Each class has the required fields.
    for m in mod.AUDIT_MARKER_CATALOG:
        assert m.name and isinstance(m.name, str)
        assert m.source and isinstance(m.source, str)
        assert m.description and isinstance(m.description, str)
        assert m.expected_event in {"workflow_dispatch", "schedule"}
    # The cron class is the only one whose expected_event is "schedule".
    by_source = {m.source: m for m in mod.AUDIT_MARKER_CATALOG}
    assert by_source["cron"].expected_event == "schedule"
    assert by_source["operator"].expected_event == "workflow_dispatch"
    assert by_source["ar"].expected_event == "workflow_dispatch"
    assert by_source["replay"].expected_event == "workflow_dispatch"


# ---------------------------------------------------------------------------
# T05 - synthesize_audit_trail_envelope produces a Tag-66-conformant
#       envelope (all required keys, all shapes valid).
# ---------------------------------------------------------------------------
def test_t05_synthesize_envelope_is_conformant():
    mod = _import_helper()
    env = mod.synthesize_audit_trail_envelope()
    for k in mod.AUDIT_MARKER_REQUIRED_KEYS:
        assert k in env, f"missing key: {k}"
    assert env["event"] == "workflow_dispatch"
    assert env["workflow"] == "phase-3c-watch-day-practice-run.yml"
    assert env["ref"] == "refs/heads/main"
    assert isinstance(env["inputs"], dict) and env["inputs"].get("diagnostic") == "true"
    assert env["actor"] and isinstance(env["actor"], str)
    assert mod.DISPATCHED_AT_PATTERN.match(env["dispatched_at"])
    assert mod.AUDIT_MARKER_TAG_PATTERN.match(env["audit_marker_tag"])
    assert mod.UUID_PATTERN.match(env["trigger_sequence_id"])


# ---------------------------------------------------------------------------
# T06 - _shape_envelope: complete envelope is green.
# ---------------------------------------------------------------------------
def test_t06_shape_envelope_green():
    mod = _import_helper()
    env = mod.synthesize_audit_trail_envelope()
    status, notes = mod._shape_envelope(env)
    assert status == mod.STAGE_GREEN, f"expected green, got {status}: {notes}"


# ---------------------------------------------------------------------------
# T07 - _shape_envelope: legacy Tag-62 envelope (missing audit overlay)
#       is yellow, not red.
# ---------------------------------------------------------------------------
def test_t07_shape_envelope_legacy_is_yellow():
    mod = _import_helper()
    legacy = {
        "event": "workflow_dispatch",
        "workflow": "phase-3c-watch-day-practice-run.yml",
        "ref": "refs/heads/main",
        "inputs": {"diagnostic": "true"},
        # No actor, dispatched_at, audit_marker_tag, trigger_sequence_id.
    }
    status, notes = mod._shape_envelope(legacy)
    assert status == mod.STAGE_YELLOW
    assert any("audit-keys-missing" in n for n in notes)


# ---------------------------------------------------------------------------
# T08 - _shape_envelope: missing base key (no event) is red.
# ---------------------------------------------------------------------------
def test_t08_shape_envelope_missing_base_is_red():
    mod = _import_helper()
    broken = {
        "workflow": "phase-3c-watch-day-practice-run.yml",
        "ref": "refs/heads/main",
        "inputs": {"diagnostic": "true"},
    }
    status, notes = mod._shape_envelope(broken)
    assert status == mod.STAGE_RED
    assert any("missing-base-keys" in n for n in notes)


# ---------------------------------------------------------------------------
# T09 - _shape_envelope: malformed audit_marker_tag is red.
# ---------------------------------------------------------------------------
def test_t09_shape_envelope_malformed_tag_is_red():
    mod = _import_helper()
    env = mod.synthesize_audit_trail_envelope()
    env["audit_marker_tag"] = "garbage-tag-format"
    status, notes = mod._shape_envelope(env)
    assert status == mod.STAGE_RED
    assert any("audit-marker-tag-malformed" in n for n in notes)


# ---------------------------------------------------------------------------
# T10 - _shape_envelope: malformed trigger_sequence_id is red.
# ---------------------------------------------------------------------------
def test_t10_shape_envelope_malformed_sequence_id_is_red():
    mod = _import_helper()
    env = mod.synthesize_audit_trail_envelope()
    env["trigger_sequence_id"] = "not-a-uuid"
    status, notes = mod._shape_envelope(env)
    assert status == mod.STAGE_RED
    assert any("trigger-sequence-id-malformed" in n for n in notes)


# ---------------------------------------------------------------------------
# T11 - _classify_marker_tag: operator-source green, cron-source yellow.
# ---------------------------------------------------------------------------
def test_t11_classify_marker_tag_operator_green_cron_yellow():
    mod = _import_helper()
    st_op, src_op, _ = mod._classify_marker_tag(
        "watch-day-operator-20260609-3bc7794"
    )
    assert st_op == mod.STAGE_GREEN
    assert src_op == "operator"

    st_cron, src_cron, notes_cron = mod._classify_marker_tag(
        "watch-day-cron-20260609-3bc7794"
    )
    # cron expected_event = schedule, but verifier targets workflow_dispatch.
    assert st_cron == mod.STAGE_YELLOW
    assert src_cron == "cron"
    assert any("source-event-mismatch" in n for n in notes_cron)


# ---------------------------------------------------------------------------
# T12 - _classify_marker_tag: malformed tag is red.
# ---------------------------------------------------------------------------
def test_t12_classify_marker_tag_malformed_is_red():
    mod = _import_helper()
    st, src, notes = mod._classify_marker_tag("totally-bogus")
    assert st == mod.STAGE_RED
    assert src is None
    assert any("tag-malformed" in n for n in notes)


# ---------------------------------------------------------------------------
# T13 - aggregate_verdict logic: 3-green = INTACT, 1-yellow = DRIFT,
#       any-red or 2+yellow = DEFECT.
# ---------------------------------------------------------------------------
def test_t13_aggregate_verdict_logic():
    mod = _import_helper()
    assert mod.aggregate_verdict("green", "green", "green") == "AUDIT-TRAIL-INTACT"
    assert mod.aggregate_verdict("yellow", "green", "green") == "AUDIT-TRAIL-DRIFT"
    assert mod.aggregate_verdict("green", "yellow", "green") == "AUDIT-TRAIL-DRIFT"
    assert mod.aggregate_verdict("yellow", "yellow", "green") == "AUDIT-TRAIL-DEFECT"
    assert mod.aggregate_verdict("red", "green", "green") == "AUDIT-TRAIL-DEFECT"
    assert mod.aggregate_verdict("yellow", "yellow", "yellow") == "AUDIT-TRAIL-DEFECT"
    # Invalid stage status returns DEFECT.
    assert mod.aggregate_verdict("blue", "green", "green") == "AUDIT-TRAIL-DEFECT"


# ---------------------------------------------------------------------------
# T14 - stage_cross_substrate_marker_reference: every catalog class
#       resolves to >=1 substrate (canonical state = green).
# ---------------------------------------------------------------------------
def test_t14_cross_substrate_marker_reference_green():
    mod = _import_helper()
    result = mod.stage_cross_substrate_marker_reference(REPO_ROOT)
    assert result.status == mod.STAGE_GREEN, (
        f"expected green, got {result.status}; notes={result.notes}; "
        f"orphans={result.details.get('orphans')}"
    )
    # Sanity: the marker-catalog markdown is one of the substrates.
    assert any(
        "watch-day-operator-trigger-audit-trail-marker-catalog.md" in p
        for p in mod.DOWNSTREAM_SUBSTRATES
    )


# ---------------------------------------------------------------------------
# T15 - stage_marker_tag_catalog_conformance: synthesized envelope
#       produces green stage-2.
# ---------------------------------------------------------------------------
def test_t15_marker_tag_catalog_conformance_green(tmp_path):
    mod = _import_helper()
    # Build a stage-1-shaped details dict directly.
    env = mod.synthesize_audit_trail_envelope()
    details = {
        "envelopes": [
            {
                "index": 0,
                "status": "green",
                "audit_marker_tag": env["audit_marker_tag"],
                "actor": env["actor"],
                "notes": [],
            }
        ]
    }
    result = mod.stage_marker_tag_catalog_conformance(details)
    assert result.status == mod.STAGE_GREEN
    assert result.details["tags"][0]["matched_source"] == "operator"


# ---------------------------------------------------------------------------
# T16 - End-to-end CLI: full mode on canonical state returns INTACT.
# ---------------------------------------------------------------------------
def test_t16_cli_full_canonical_intact(tmp_path):
    if not TAG62_HELPER.is_file():
        pytest.skip("Tag-62 helper missing; full-mode integration unavailable")
    out_dir = tmp_path / "tag66-out"
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "full",
            "--scratch-dir",
            str(out_dir),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"expected rc=0 INTACT, got {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    verdict_file = out_dir / "watch-day-operator-trigger-audit-trail-verdict.json"
    assert verdict_file.is_file()
    payload = json.loads(verdict_file.read_text(encoding="utf-8"))
    assert payload["verdict"] == "AUDIT-TRAIL-INTACT"
    assert payload["stages"]["stage_1_trigger_event_schema_audit"] == "green"
    assert payload["stages"]["stage_2_marker_tag_catalog_conformance"] == "green"
    assert payload["stages"]["stage_3_cross_substrate_marker_reference"] == "green"


# ---------------------------------------------------------------------------
# T17 - End-to-end CLI: aggregate-mode with mixed inputs returns expected.
# ---------------------------------------------------------------------------
def test_t17_cli_aggregate_subcommand(tmp_path):
    out = tmp_path / "verdict.json"
    # green/green/green -> INTACT (rc=0)
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "aggregate",
            "--stage-1",
            "green",
            "--stage-2",
            "green",
            "--stage-3",
            "green",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    payload = json.loads(out.read_text())
    assert payload["verdict"] == "AUDIT-TRAIL-INTACT"

    # green/yellow/green -> DRIFT (rc=2)
    proc2 = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "aggregate",
            "--stage-1",
            "green",
            "--stage-2",
            "yellow",
            "--stage-3",
            "green",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc2.returncode == 2
    payload2 = json.loads(out.read_text())
    assert payload2["verdict"] == "AUDIT-TRAIL-DRIFT"

    # red/green/green -> DEFECT (rc=1)
    proc3 = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "aggregate",
            "--stage-1",
            "red",
            "--stage-2",
            "green",
            "--stage-3",
            "green",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc3.returncode == 1
    payload3 = json.loads(out.read_text())
    assert payload3["verdict"] == "AUDIT-TRAIL-DEFECT"


# ---------------------------------------------------------------------------
# T18 - Stage-1 with fixture-array of mixed envelopes aggregates correctly.
# ---------------------------------------------------------------------------
def test_t18_stage1_fixture_array(tmp_path):
    mod = _import_helper()
    # One green, one yellow (missing audit-only), one green.
    green1 = mod.synthesize_audit_trail_envelope(
        actor="mira-hand-operator",
        sequence_id=str(uuid.uuid4()),
    )
    legacy_yellow = {
        "event": "workflow_dispatch",
        "workflow": "phase-3c-watch-day-practice-run.yml",
        "ref": "refs/heads/main",
        "inputs": {"diagnostic": "true"},
    }
    green2 = mod.synthesize_audit_trail_envelope(
        actor="mira-hand-operator-backup",
        sequence_id=str(uuid.uuid4()),
    )
    fixture = tmp_path / "envelopes.json"
    fixture.write_text(json.dumps([green1, legacy_yellow, green2]))
    out_dir = tmp_path / "out"
    result = mod.stage_trigger_event_schema_audit(
        REPO_ROOT, out_dir, fixture=fixture
    )
    # Mixed green+yellow with no red: aggregate yellow.
    assert result.status == mod.STAGE_YELLOW
    statuses = [e["status"] for e in result.details["envelopes"]]
    assert statuses.count("green") == 2
    assert statuses.count("yellow") == 1
    assert statuses.count("red") == 0


# ---------------------------------------------------------------------------
# T19 - Workflow file present, parses as YAML, has all four stage jobs.
# ---------------------------------------------------------------------------
def test_t19_workflow_file_shape():
    import yaml  # PyYAML is in dev-deps (pytest infra)

    assert WORKFLOW.is_file()
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert data["name"] == "watch-day-operator-trigger-audit-trail-verify"
    # `on:` is parsed as boolean True by PyYAML (YAML 1.1 quirk).
    on_key = True if True in data else "on"
    triggers = data[on_key]
    assert "workflow_dispatch" in triggers
    assert "pull_request" in triggers
    # Path-filters include the canonical surface.
    paths = triggers["pull_request"]["paths"]
    assert (
        ".github/workflows/watch-day-operator-trigger-audit-trail-verify.yml"
        in paths
    )
    assert (
        "tooling/ci/verify_watch_day_operator_trigger_audit_trail.py" in paths
    )
    assert (
        "docs/observability/watch-day-operator-trigger-audit-trail-marker-catalog.md"
        in paths
    )
    # All four stage jobs present.
    jobs = data["jobs"]
    assert "stage-1-trigger-event-schema-audit" in jobs
    assert "stage-2-marker-tag-catalog-conformance" in jobs
    assert "stage-3-cross-substrate-marker-reference" in jobs
    assert "stage-4-aggregate-verdict" in jobs
    # Stage 4 depends on stages 1-3.
    assert set(jobs["stage-4-aggregate-verdict"]["needs"]) == {
        "stage-1-trigger-event-schema-audit",
        "stage-2-marker-tag-catalog-conformance",
        "stage-3-cross-substrate-marker-reference",
    }


# ---------------------------------------------------------------------------
# T20 - Marker-catalog markdown exists + enumerates all four classes.
# ---------------------------------------------------------------------------
def test_t20_marker_catalog_markdown_enumerates_four_classes():
    assert MARKER_CATALOG_MD.is_file()
    text = MARKER_CATALOG_MD.read_text(encoding="utf-8")
    assert "operator-hand-dispatch" in text
    assert "ar-hand-override" in text
    assert "scheduled-cron" in text
    assert "replay-driver" in text
    # The canonical pattern is documented.
    assert "watch-day-<source>-<YYYYMMDD>-<short-hash>" in text
    # The canonical workflow file name is referenced.
    assert "phase-3c-watch-day-practice-run.yml" in text


# ---------------------------------------------------------------------------
# T21 - Verifier-catalog vs. markdown-catalog single-source consistency:
#       every class in the python catalog appears (by name) in the markdown.
# ---------------------------------------------------------------------------
def test_t21_catalog_python_markdown_drift_check():
    mod = _import_helper()
    md_text = MARKER_CATALOG_MD.read_text(encoding="utf-8")
    for marker in mod.AUDIT_MARKER_CATALOG:
        assert marker.name in md_text, (
            f"marker {marker.name!r} not referenced in catalog markdown"
        )


# ---------------------------------------------------------------------------
# T22 - Stage-1 envelope JSON shape (schema_version, tag, stage, details).
# ---------------------------------------------------------------------------
def test_t22_stage_envelope_serialised_shape(tmp_path):
    mod = _import_helper()
    out_dir = tmp_path / "out"
    result = mod.stage_trigger_event_schema_audit(REPO_ROOT, out_dir)
    out_file = tmp_path / "stage-1.json"
    mod.emit_stage_envelope("stage_1_trigger_event_schema_audit", result, out_file)
    payload = json.loads(out_file.read_text())
    assert payload["schema_version"] == 1
    assert payload["tag"] == 66
    assert payload["tool"] == "verify-watch-day-operator-trigger-audit-trail"
    assert payload["stage"] == "stage_1_trigger_event_schema_audit"
    assert payload["status"] in {"green", "yellow", "red"}
    assert "envelopes" in payload["details"]


# ---------------------------------------------------------------------------
# T23 - Verdict envelope JSON shape (schema_version, tag, verdict, stages).
# ---------------------------------------------------------------------------
def test_t23_verdict_envelope_serialised_shape(tmp_path):
    mod = _import_helper()
    out_file = tmp_path / "verdict.json"
    mod.emit_verdict_envelope(
        "AUDIT-TRAIL-INTACT", "green", "green", "green", out_file
    )
    payload = json.loads(out_file.read_text())
    assert payload["schema_version"] == 1
    assert payload["tag"] == 66
    assert payload["verdict"] == "AUDIT-TRAIL-INTACT"
    stages = payload["stages"]
    assert stages["stage_1_trigger_event_schema_audit"] == "green"
    assert stages["stage_2_marker_tag_catalog_conformance"] == "green"
    assert stages["stage_3_cross_substrate_marker_reference"] == "green"


# ---------------------------------------------------------------------------
# T24 - Helper SPDX banner is Apache-2.0 (license-clear-zone).
# ---------------------------------------------------------------------------
# REUSE-IgnoreStart
def test_t24_helper_spdx_banner_apache():
    head = HELPER.read_text(encoding="utf-8").splitlines()[:5]
    joined = "\n".join(head)
    assert "SPDX-License-Identifier: Apache-2.0" in joined
# REUSE-IgnoreEnd
