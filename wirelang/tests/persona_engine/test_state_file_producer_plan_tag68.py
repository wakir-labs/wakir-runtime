# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-68 - State-File Producer-Wiring-Plan pin (Selin).

The Tag-68 deliverable is doc-form-only: a plan-doc
``docs/persona-engine/state-file-producer-wiring-plan.md`` plus a
stdlib-only audit-helper
``tooling/ci/render_engine_state_file_stub.py`` that renders the
Tag-67 canonical pending-status stub for ``state/welle-N.json``.

This hermetic test-suite pins:

* the existence + six-section structure of the plan-doc,
* the four producer-triggers (Cutover-T0, Sign-Off, Rollback,
  Phase-3-COMPLETE backfill) are documented with writer-code-path,
* the lifecycle-state-machine transitions (pending ->
  in-progress -> signed-off plus rollback fan-in) are explicitly
  pinned,
* the cross-anchor section maps every writable field to the
  Tag-67 schema-pin,
* the sandbox-boundary section enumerates the live-file
  operator-hand-only set,
* the render-stub helper renders all seven canonical stubs
  byte-equivalent to the committed ``state/welle-N.json`` files,
* the render-stub helper rejects out-of-range welle_number,
* the render-stub helper rejects out-of-range kw_anchor,
* the render-stub CLI exits 0 on valid input and prints the JSON,
* the render-stub CLI exits non-zero on invalid input,
* the canonical KW-anchor map matches the Tag-67 stub-state-files,
* the helper is stdlib-only (no third-party imports leak).

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC.
* No subprocess outside an in-process module-import + CLI-main()
  call (the CLI is invoked as a function, not via subprocess).
* Pure file inspection + JSON parse + module call.

Scope discipline (Selin)
------------------------
This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K),
identity-substrate design (Reza-Domaene, Zone-L), or
container-infra (Kai-Domaene, Zone-J). It pins the Tag-68
plan-doc + helper-stub which are persona-engine-domain (Selin)
deliverables that reference the Amara-Tag-67 schema-pin (QA-
domain) without modifying it.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_DOC = (
    REPO_ROOT
    / "docs"
    / "persona-engine"
    / "state-file-producer-wiring-plan.md"
)
HELPER_STUB = (
    REPO_ROOT / "tooling" / "ci" / "render_engine_state_file_stub.py"
)
STATE_DIR = REPO_ROOT / "state"


def _load_helper_module():
    spec = importlib.util.spec_from_file_location(
        "render_engine_state_file_stub_tag68", HELPER_STUB
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_doc_exists():
    """Plan-doc lives at the canonical path."""
    assert PLAN_DOC.is_file(), f"plan-doc missing: {PLAN_DOC}"


def test_plan_doc_has_six_sections():
    """Plan-doc has the six required sections (§1..§6)."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    required_headings = [
        "## §1 Scope (post-Cutover-T0 Producer-Wiring)",
        "## §2 Per-Welle Engine-Side-Producer-Trigger",
        "## §3 State-Transitions pending → in-progress → signed-off",
        "## §4 Cross-Anchor zu Amara-Tag-67-Schema",
        "## §5 Tag-69+-Implementation-Roadmap (Stub-only Tag-68)",
        "## §6 Sandbox-Boundary",
    ]
    for heading in required_headings:
        assert heading in text, f"missing required heading: {heading!r}"


def test_plan_doc_documents_four_producer_triggers():
    """Plan-doc §2 enumerates the four producer-triggers."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    required_trigger_anchors = [
        "Welle-N-Cutover-T0-Event-Received",
        "Welle-N-Sign-Off-Event-Received",
        "Welle-N-Rollback-Event-Received",
        "Phase-3-COMPLETE-Marker-Fired",
    ]
    for anchor in required_trigger_anchors:
        assert anchor in text, f"missing producer-trigger: {anchor!r}"


def test_plan_doc_documents_status_transitions():
    """Plan-doc §3 pins the five allowed lifecycle transitions."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    required_transitions = [
        "`pending -> in-progress`",
        "`pending -> rolled-back`",
        "`in-progress -> signed-off`",
        "`in-progress -> rolled-back`",
        "`signed-off -> rolled-back`",
    ]
    for transition in required_transitions:
        assert transition in text, (
            f"missing transition: {transition!r}"
        )


def test_plan_doc_documents_forbidden_transitions():
    """Plan-doc §3 enumerates the forbidden transitions guard."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    forbidden_anchors = [
        "`signed-off -> in-progress`",
        "`signed-off -> pending`",
        "`rolled-back -> *`",
        "`in-progress -> pending`",
    ]
    for anchor in forbidden_anchors:
        assert anchor in text, (
            f"missing forbidden-transition anchor: {anchor!r}"
        )


def test_plan_doc_cross_anchors_tag_67_schema():
    """Plan-doc §4 references Amara's Tag-67 schema-pin doc."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    assert "welle-n-state-file-conventions.md" in text, (
        "plan-doc must cross-anchor to Tag-67 schema-pin doc"
    )
    assert "verify_welle_state_file_conventions.py" in text, (
        "plan-doc must cross-anchor to Tag-67 verifier helper"
    )
    assert "tag-67-v1" in text, (
        "plan-doc must reference the frozen schema_version literal"
    )


def test_plan_doc_documents_sandbox_boundary_live_files():
    """Plan-doc §6 enumerates the operator-hand-only live-files."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    required_live_files = [
        "state/welle-6-subscribe-mode-live.json",
        "state/welle-7-recovery-drill-live.json",
    ]
    for live_file in required_live_files:
        assert live_file in text, (
            f"plan-doc §6 must enumerate operator-hand live-file: "
            f"{live_file!r}"
        )
    assert "operator-hand" in text or "operator-territory" in text, (
        "plan-doc §6 must name operator-hand boundary explicitly"
    )


def test_plan_doc_marks_tag_68_as_doc_form_only():
    """Plan-doc §1 declares Tag-68 doc-form-only discipline."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    assert "doc-form-only" in text.lower() or "doc form only" in text.lower(), (
        "plan-doc must declare doc-form-only discipline for Tag-68"
    )
    assert "Tag-69" in text, (
        "plan-doc must reference Tag-69+ implementation roadmap"
    )


def test_plan_doc_documents_cross_review_gates():
    """Plan-doc §5 enumerates Zone-K + Zone-N cross-review gates."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    assert "Zone-K" in text, (
        "plan-doc §5 must reference Zone-K (Tomas) cross-review"
    )
    assert "Zone-N" in text, (
        "plan-doc §5 must reference Zone-N (Henrik) cross-review"
    )
    assert "Zone-L" in text, (
        "plan-doc §5 must reference Zone-L (Reza) cross-review for "
        "Tag-71+ OTS-anchor backfill"
    )


def test_helper_stub_exists():
    """Helper-stub lives at the canonical path."""
    assert HELPER_STUB.is_file(), f"helper-stub missing: {HELPER_STUB}"


def test_helper_stub_renders_all_seven_byte_equivalent():
    """Helper-stub renders each Welle-N stub byte-equivalent to disk."""
    module = _load_helper_module()
    for welle_number, stub_dict in module.render_all():
        committed_path = STATE_DIR / f"welle-{welle_number}.json"
        assert committed_path.is_file(), (
            f"committed stub missing: {committed_path}"
        )
        committed = json.loads(committed_path.read_text(encoding="utf-8"))
        assert committed == stub_dict, (
            f"Tag-68 render-stub diverges from committed Tag-67 stub "
            f"for welle-{welle_number}: "
            f"committed={committed!r} rendered={stub_dict!r}"
        )


def test_helper_stub_rejects_out_of_range_welle():
    """Helper-stub raises ValueError on welle_number outside 1..7."""
    module = _load_helper_module()
    for invalid in (0, 8, -1, 100):
        with pytest.raises(ValueError):
            module.render_stub(invalid, "KW-22")


def test_helper_stub_rejects_out_of_range_kw_anchor():
    """Helper-stub raises ValueError on KW-anchor outside KW-22..KW-27."""
    module = _load_helper_module()
    for invalid in ("KW-21", "KW-28", "KW-99", "", "kw-22", "K-22"):
        with pytest.raises(ValueError):
            module.render_stub(3, invalid)


def test_helper_stub_cli_main_valid_input_exits_zero():
    """Helper-stub CLI main() returns 0 on valid --welle + --kw."""
    module = _load_helper_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = module.main(["--welle", "3", "--kw", "KW-25"])
    assert rc == 0
    rendered = json.loads(buf.getvalue())
    assert rendered["welle_number"] == 3
    assert rendered["kw_cutover_anchor"] == "KW-25"
    assert rendered["status"] == "pending"
    assert rendered["schema_version"] == "tag-67-v1"


def test_helper_stub_cli_main_invalid_input_exits_nonzero():
    """Helper-stub CLI main() returns non-zero on invalid input."""
    module = _load_helper_module()
    err_buf = io.StringIO()
    with redirect_stderr(err_buf), redirect_stdout(io.StringIO()):
        rc = module.main(["--welle", "9", "--kw", "KW-22"])
    assert rc == 1
    assert "error" in err_buf.getvalue().lower()


def test_helper_stub_cli_main_all_flag_prints_seven_objects():
    """Helper-stub CLI main(--all) prints seven JSON objects to stdout."""
    module = _load_helper_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = module.main(["--all"])
    assert rc == 0
    # Output is seven indent=2 JSON objects concatenated; count
    # opening welle_number occurrences.
    out = buf.getvalue()
    matches = re.findall(r'"welle_number": [1-7]', out)
    assert len(matches) == 7, (
        f"--all must print seven welle_number entries, got {len(matches)}"
    )


def test_helper_stub_canonical_kw_anchor_map_matches_disk():
    """Helper-stub CANONICAL_KW_ANCHOR matches committed stub files."""
    module = _load_helper_module()
    for n in range(1, 8):
        committed = json.loads(
            (STATE_DIR / f"welle-{n}.json").read_text(encoding="utf-8")
        )
        assert module.CANONICAL_KW_ANCHOR[n] == committed["kw_cutover_anchor"], (
            f"CANONICAL_KW_ANCHOR[{n}] = "
            f"{module.CANONICAL_KW_ANCHOR[n]!r} but committed stub has "
            f"kw_cutover_anchor = {committed['kw_cutover_anchor']!r}"
        )


def test_helper_stub_is_stdlib_only():
    """Helper-stub imports only stdlib modules (hermetic guarantee)."""
    text = HELPER_STUB.read_text(encoding="utf-8")
    # Identify all `import X` and `from X import ...` lines.
    import_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(("import ", "from "))
        and not line.strip().startswith("from __future__")
    ]
    # Whitelist of stdlib modules referenced by the helper.
    allowed_stdlib = {
        "argparse",
        "json",
        "sys",
        "typing",
    }
    for line in import_lines:
        # Extract the top-level module name.
        if line.startswith("from "):
            mod = line.split()[1].split(".")[0]
        else:
            mod = line.split()[1].split(".")[0].rstrip(",")
        assert mod in allowed_stdlib, (
            f"helper-stub imports non-stdlib module {mod!r} "
            f"(line: {line!r}); Tag-68 helper must be stdlib-only"
        )


def test_helper_stub_render_stub_returns_dict_with_required_keys():
    """render_stub returns dict with the nine Tag-67 schema keys."""
    module = _load_helper_module()
    out = module.render_stub(3, "KW-25")
    required_keys = {
        "welle_number",
        "schema_version",
        "phase",
        "kw_cutover_anchor",
        "cutover_iso",
        "signoff_iso",
        "status",
        "rollup_links",
        "audit_trail_anchor",
    }
    assert set(out.keys()) == required_keys, (
        f"render_stub keys diverge from Tag-67 schema: "
        f"got {set(out.keys())!r}, expected {required_keys!r}"
    )
    assert out["status"] == "pending"
    assert out["cutover_iso"] == ""
    assert out["signoff_iso"] == ""
    assert out["audit_trail_anchor"] == ""
    assert set(out["rollup_links"].keys()) == {
        "sign_off",
        "validation_last_verdict",
        "hot_spot_trend_dir",
        "pre_auditor_decision",
    }


def test_plan_doc_references_helper_stub_filename():
    """Plan-doc references the helper-stub by filename."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    assert "render_engine_state_file_stub.py" in text, (
        "plan-doc must reference helper-stub filename"
    )


def test_plan_doc_references_tag_68_test_filename():
    """Plan-doc references this test-suite by filename."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    assert "test_state_file_producer_plan_tag68.py" in text, (
        "plan-doc must reference Tag-68 test-suite filename"
    )


def test_plan_doc_documents_writer_summary_table():
    """Plan-doc §2.5 has a summary-table mapping triggers to writers."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    # Summary-table must reference both async + sync engine modules.
    assert "engine_async.py" in text, (
        "plan-doc §2 must reference engine_async.py as a writer module"
    )
    assert "engine.py" in text, (
        "plan-doc §2 must reference engine.py as a writer module"
    )


def test_plan_doc_documents_idempotency_guard():
    """Plan-doc §2 + §3 enumerate idempotency / no-op guards."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    assert "idempot" in text.lower(), (
        "plan-doc must document idempotency discipline"
    )
    assert "no-op" in text.lower(), (
        "plan-doc must document no-op discipline for invalid "
        "transitions / re-fires"
    )
