# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
# REUSE-IgnoreStart
"""Tag-62 wakir-protocol Cross-Review-Zone-3 hand-off plan-doc tests.

These tests pin the runtime-side plan-doc that prepares the
Operator-Hand mirror PR against `wakir-labs/wakir-protocol`. They
verify the plan-doc is internally consistent, references the right
seed files, the right protocol paths, the right PR anchors, and
the right sandbox-boundary discipline.

Invariants under test
---------------------

1. Plan-doc exists at the canonical path under docs/operations/.
2. All 8 sections §1..§8 are present, in order, with non-empty
   bodies.
3. §2 source-state cites all 8 seed files (4 Tag-59 + 4 Tag-61)
   at their canonical runtime-side paths, AND those files
   actually exist on runtime `main`.
4. §3 target-state cites all 8 protocol-side canonical paths with
   the literal runtime->protocol mapping.
5. §4 recipe contains a `gh pr create` step targeting
   `wakir-labs/wakir-protocol` with the expected branch slug.
6. §5 verification cites `--post-resync` (runtime projection) and
   real protocol-side measurement, and gates the ENFORCE-Flip on
   both.
7. §6 failure-modes covers Path-Drift, License-Header-Drift, and
   Conflict explicitly with Symptom/Recovery/Owner triples.
8. §7 sandbox-boundary delimits Sandbox-Scope vs.
   Out-of-Sandbox-Scope and mentions
   Operator-Hand-Sandbox-Gap.
9. §8 cross-anchor cites runtime PRs #376, #382, #388 and
   ADR-0062 + ADR-0023a.
10. The verify helper exits 0 on the current plan-doc.
11. The plan-doc signs off as "-- Reza".
12. The plan-doc carries the Apache-2.0 SPDX banner (the doc
    itself follows the protocol-side SPDX posture).
13. The protocol-side `wakir_protocol/` paths in §3 are not
    accidentally present in the runtime tree (i.e. the plan does
    not pre-populate protocol-side state inside runtime).

Discipline
----------

stdlib + pytest only. No network. No protocol-side credentials.
The plan-doc and the verify helper are both within Sandbox-Scope;
this test pins them.

-- Reza
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "wakir-protocol-cross-review-zone-3-handoff-plan.md"
)
VERIFY_HELPER = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "verify_protocol_handoff_plan_doc.py"
)
SEED_PREFIX = REPO_ROOT / "wirelang" / "specs" / "protocol-mirror-seed"

REQUIRED_SECTIONS = ["§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8"]
REQUIRED_RECIPE_STAGES = ["§4.1", "§4.2", "§4.3", "§4.4", "§4.5", "§4.6"]
REQUIRED_VERIFICATION_STAGES = ["§5.1", "§5.2", "§5.3"]

EXPECTED_TAG59_SEEDS = [
    "wirelang/specs/protocol-mirror-seed/docs/observability/pre-mortem-failure-mode-notify-catalog.md",
    "wirelang/specs/protocol-mirror-seed/dashboards/phase-3-marathon-alerts.yaml",
    "wirelang/specs/protocol-mirror-seed/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
    "wirelang/specs/protocol-mirror-seed/scripts/observability/alert-rule-to-mira-notify-bridge.py",
]

EXPECTED_TAG61_SEEDS = [
    "wirelang/specs/protocol-mirror-seed/schemas/layer-0-transport.json",
    "wirelang/specs/protocol-mirror-seed/schemas/layer-1-wire.json",
    "wirelang/specs/protocol-mirror-seed/schemas/layer-2-semantic.json",
    "wirelang/specs/protocol-mirror-seed/schemas/aip-document.json",
]

ALL_SEEDS = EXPECTED_TAG59_SEEDS + EXPECTED_TAG61_SEEDS

EXPECTED_PROTOCOL_PATHS = [
    "wakir_protocol/docs/observability/pre-mortem-failure-mode-notify-catalog.md",
    "wakir_protocol/dashboards/phase-3-marathon-alerts.yaml",
    "wakir_protocol/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
    "wakir_protocol/scripts/observability/alert-rule-to-mira-notify-bridge.py",
    "wakir_protocol/schemas/layer-0-transport.json",
    "wakir_protocol/schemas/layer-1-wire.json",
    "wakir_protocol/schemas/layer-2-semantic.json",
    "wakir_protocol/schemas/aip-document.json",
]

REQUIRED_FAILURE_MODES = ["Path-Drift", "License-Header-Drift", "Conflict"]
ANCHOR_PRS = ["#376", "#382", "#388"]
EXPECTED_BRANCH_SLUG = "reza/tag-62-cross-review-zone-3-handoff"


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.exists(), f"plan-doc not found at {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sections(doc_text: str) -> dict[str, str]:
    """Split the doc into a {marker: body} map."""
    result: dict[str, str] = {}
    positions: list[tuple[str, int]] = []
    for marker in REQUIRED_SECTIONS:
        idx = doc_text.find(f"## {marker}")
        positions.append((marker, idx))
    positions.append(("__end__", len(doc_text)))
    for i in range(len(REQUIRED_SECTIONS)):
        marker, start = positions[i]
        _, end = positions[i + 1]
        result[marker] = doc_text[start:end]
    return result


# ---------------------------------------------------------------------------
# Test 1: existence + structure.
# ---------------------------------------------------------------------------


def test_plan_doc_exists() -> None:
    assert DOC_PATH.exists(), (
        f"plan-doc expected at {DOC_PATH} "
        "(Tag-62 Cross-Review-Zone-3 hand-off plan)"
    )


def test_all_eight_sections_present_in_order(doc_text: str) -> None:
    last_idx = -1
    for marker in REQUIRED_SECTIONS:
        idx = doc_text.find(f"## {marker}")
        assert idx >= 0, f"missing section header for {marker}"
        assert idx > last_idx, (
            f"section {marker} appears out of order (idx={idx} <= {last_idx})"
        )
        last_idx = idx


def test_every_section_body_nonempty(sections: dict[str, str]) -> None:
    for marker, body in sections.items():
        # Strip the heading line; what remains must have substance.
        rest = body.split("\n", 1)[1] if "\n" in body else ""
        content_lines = [ln for ln in rest.splitlines() if ln.strip()]
        assert len(content_lines) >= 3, (
            f"section {marker} body too thin "
            f"(got {len(content_lines)} non-empty lines, need >=3)"
        )


# ---------------------------------------------------------------------------
# Test 2: §2 source-state (runtime seed files).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed_path", ALL_SEEDS)
def test_source_state_lists_seed_path(sections: dict[str, str], seed_path: str) -> None:
    """Each of the 8 seed paths appears in §2."""
    assert seed_path in sections["§2"], (
        f"§2 source-state must cite seed path '{seed_path}'"
    )


@pytest.mark.parametrize("seed_path", ALL_SEEDS)
def test_seed_path_exists_on_runtime(seed_path: str) -> None:
    """Each cited seed file actually exists on runtime main."""
    abs_path = REPO_ROOT / seed_path
    assert abs_path.is_file(), (
        f"seed file '{seed_path}' missing on runtime main "
        "(plan-doc claims it is the source-of-truth)"
    )


def test_source_state_anchors_tag59_and_tag61_prs(sections: dict[str, str]) -> None:
    """§2 must cite PR #376 (Tag-59) and PR #388 (Tag-61)."""
    assert "#376" in sections["§2"], "§2 must anchor to Tag-59 PR #376"
    assert "#388" in sections["§2"], "§2 must anchor to Tag-61 PR #388"


def test_source_state_declares_apache_spdx(sections: dict[str, str]) -> None:
    # REUSE-IgnoreStart
    assert "Apache-2.0" in sections["§2"], (
        "§2 must declare Apache-2.0 SPDX posture for the seed tree"
    )
    # REUSE-IgnoreEnd


# ---------------------------------------------------------------------------
# Test 3: §3 target-state (protocol-side canonical paths).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("protocol_path", EXPECTED_PROTOCOL_PATHS)
def test_target_state_lists_protocol_path(
    sections: dict[str, str], protocol_path: str
) -> None:
    """Each of the 8 protocol-side canonical paths appears in §3."""
    assert protocol_path in sections["§3"], (
        f"§3 target-state must cite protocol path '{protocol_path}'"
    )


def test_target_state_apache_banner_discipline(sections: dict[str, str]) -> None:
    # REUSE-IgnoreStart
    assert "Apache-2.0" in sections["§3"], (
        "§3 must reference Apache-2.0 SPDX banner discipline"
    )
    # REUSE-IgnoreEnd


def test_protocol_paths_not_present_on_runtime() -> None:
    """The protocol-side paths must NOT exist under the runtime tree
    (the plan does not pre-populate protocol state in runtime)."""
    for protocol_path in EXPECTED_PROTOCOL_PATHS:
        runtime_collision = REPO_ROOT / protocol_path
        assert not runtime_collision.exists(), (
            f"protocol-side path '{protocol_path}' must not exist on "
            "runtime side (sandbox-boundary violation)"
        )


# ---------------------------------------------------------------------------
# Test 4: §4 Operator-Hand recipe.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", REQUIRED_RECIPE_STAGES)
def test_recipe_stage_heading_present(sections: dict[str, str], stage: str) -> None:
    assert f"### {stage}" in sections["§4"], (
        f"§4 recipe missing sub-section '### {stage}'"
    )


def test_recipe_no_empty_stage(sections: dict[str, str]) -> None:
    """No recipe stage body is empty (>=2 non-empty non-heading lines)."""
    section4 = sections["§4"]
    for stage in REQUIRED_RECIPE_STAGES:
        heading = f"### {stage}"
        idx = section4.find(heading)
        rest = section4[idx + len(heading):]
        next_heading_idx = rest.find("\n### ")
        next_section_idx = rest.find("\n## ")
        candidates = [i for i in (next_heading_idx, next_section_idx) if i >= 0]
        end = min(candidates) if candidates else len(rest)
        body = rest[:end].strip()
        non_empty = [
            ln for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert len(non_empty) >= 2, (
            f"§4 recipe stage '{stage}' body too thin "
            f"(got {len(non_empty)}, need >=2)"
        )


def test_recipe_gh_pr_create_targets_wakir_protocol(sections: dict[str, str]) -> None:
    assert "gh pr create" in sections["§4"], (
        "§4 recipe must include 'gh pr create'"
    )
    assert "wakir-labs/wakir-protocol" in sections["§4"], (
        "§4 recipe must target 'wakir-labs/wakir-protocol'"
    )


def test_recipe_branch_slug(sections: dict[str, str]) -> None:
    assert EXPECTED_BRANCH_SLUG in sections["§4"], (
        f"§4 recipe must use branch slug '{EXPECTED_BRANCH_SLUG}'"
    )


def test_recipe_has_merge_step(sections: dict[str, str]) -> None:
    assert "gh pr merge" in sections["§4"], (
        "§4 recipe must include 'gh pr merge' step"
    )


# ---------------------------------------------------------------------------
# Test 5: §5 Verification.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", REQUIRED_VERIFICATION_STAGES)
def test_verification_stage_heading_present(
    sections: dict[str, str], stage: str
) -> None:
    assert f"### {stage}" in sections["§5"], (
        f"§5 verification missing sub-section '### {stage}'"
    )


def test_verification_cites_post_resync_flag(sections: dict[str, str]) -> None:
    assert "--post-resync" in sections["§5"], (
        "§5 verification must cite '--post-resync' flag (runtime projection)"
    )


def test_verification_cites_real_protocol_measurement(sections: dict[str, str]) -> None:
    """§5 must distinguish runtime projection from real measurement."""
    assert "real" in sections["§5"].lower() or "actual" in sections["§5"].lower(), (
        "§5 must explicitly distinguish runtime projection from "
        "real/actual protocol-side measurement"
    )


def test_verification_enforces_score_92_threshold(sections: dict[str, str]) -> None:
    assert "92" in sections["§5"], "§5 must cite the score 92 (ENFORCE-READY threshold)"
    assert "ENFORCE-READY" in sections["§5"], (
        "§5 must cite ENFORCE-READY verdict"
    )
    assert "ENFORCE-Flip" in sections["§5"], (
        "§5 must reference ENFORCE-Flip trigger"
    )


# ---------------------------------------------------------------------------
# Test 6: §6 Failure-modes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", REQUIRED_FAILURE_MODES)
def test_failure_mode_present(sections: dict[str, str], mode: str) -> None:
    assert mode in sections["§6"], f"§6 failure-modes missing '{mode}'"


@pytest.mark.parametrize("mode", REQUIRED_FAILURE_MODES)
def test_failure_mode_has_symptom_recovery_owner(
    sections: dict[str, str], mode: str
) -> None:
    section6 = sections["§6"]
    idx = section6.find(mode)
    rest = section6[idx:]
    next_block = rest.find("\n### ", 5)
    next_section = rest.find("\n## ", 5)
    candidates = [i for i in (next_block, next_section) if i >= 0]
    end = min(candidates) if candidates else len(rest)
    body = rest[:end]
    for kw in ("Symptom", "Recovery", "Owner"):
        assert kw in body, f"§6 '{mode}' block missing '{kw}'"


# ---------------------------------------------------------------------------
# Test 7: §7 Sandbox-Boundary.
# ---------------------------------------------------------------------------


def test_sandbox_scope_delimited(sections: dict[str, str]) -> None:
    assert "Sandbox-Scope" in sections["§7"], (
        "§7 must declare Sandbox-Scope"
    )
    assert "Out-of-Sandbox-Scope" in sections["§7"], (
        "§7 must declare Out-of-Sandbox-Scope"
    )


def test_sandbox_mentions_operator_hand_gap(sections: dict[str, str]) -> None:
    assert "Operator-Hand-Sandbox-Gap" in sections["§7"], (
        "§7 must mention Operator-Hand-Sandbox-Gap"
    )


def test_sandbox_anchors_adr_0023a(sections: dict[str, str]) -> None:
    assert "ADR-0023a" in sections["§7"], (
        "§7 must anchor to ADR-0023a"
    )


# ---------------------------------------------------------------------------
# Test 8: §8 Cross-anchor.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pr_number", ANCHOR_PRS)
def test_cross_anchor_pr_present(sections: dict[str, str], pr_number: str) -> None:
    assert pr_number in sections["§8"], (
        f"§8 cross-anchor must cite PR {pr_number}"
    )


def test_cross_anchor_adr_0062(sections: dict[str, str]) -> None:
    assert "ADR-0062" in sections["§8"], (
        "§8 cross-anchor must reference ADR-0062"
    )


def test_cross_anchor_zone_3(sections: dict[str, str]) -> None:
    assert "Cross-Review-Zone-3" in sections["§8"], (
        "§8 cross-anchor must reference Cross-Review-Zone-3"
    )


# ---------------------------------------------------------------------------
# Test 9: signature + SPDX.
# ---------------------------------------------------------------------------


def test_signature_reza(doc_text: str) -> None:
    assert re.search(r"^-- Reza\s*$", doc_text, re.MULTILINE), (
        "doc must end with '-- Reza' signature line"
    )


def test_doc_apache_spdx_banner(doc_text: str) -> None:
    # REUSE-IgnoreStart
    assert "SPDX-License-Identifier: Apache-2.0" in doc_text, (
        "plan-doc itself must carry Apache-2.0 SPDX banner "
        "(matches protocol-side licensing posture)"
    )
    # REUSE-IgnoreEnd


# ---------------------------------------------------------------------------
# Test 10: helper script runs green.
# ---------------------------------------------------------------------------


def test_verify_helper_exists() -> None:
    assert VERIFY_HELPER.exists(), (
        f"verify helper expected at {VERIFY_HELPER}"
    )


def test_verify_helper_runs_green() -> None:
    """The verify helper exits 0 against the current plan-doc."""
    result = subprocess.run(
        [sys.executable, str(VERIFY_HELPER)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"verify helper exited {result.returncode}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert "OK" in result.stdout, (
        f"verify helper stdout must contain 'OK'; got: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Test 11: verify helper module surface (importable for unit tests).
# ---------------------------------------------------------------------------


def _load_verify_module():
    module_name = "verify_protocol_handoff_plan_doc_tag62"
    spec = importlib.util.spec_from_file_location(module_name, VERIFY_HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_helper_exports_required_constants() -> None:
    """The helper exposes the expected constants for downstream re-use."""
    mod = _load_verify_module()
    assert mod.REQUIRED_SECTIONS == REQUIRED_SECTIONS
    assert set(mod.ALL_SEEDS) == set(ALL_SEEDS)
    assert set(mod.EXPECTED_PROTOCOL_PATHS) == set(EXPECTED_PROTOCOL_PATHS)
    assert set(mod.REQUIRED_FAILURE_MODES) == set(REQUIRED_FAILURE_MODES)
    assert mod.EXPECTED_BRANCH_SLUG == EXPECTED_BRANCH_SLUG


def test_verify_helper_fails_on_missing_doc(tmp_path: Path, monkeypatch) -> None:
    """The verify helper fails cleanly when the doc is missing."""
    mod = _load_verify_module()
    # Point the helper at a non-existent file.
    bogus = tmp_path / "absent-plan-doc.md"
    with pytest.raises(SystemExit) as excinfo:
        mod.load_doc(bogus)
    assert excinfo.value.code == 1


def test_verify_helper_fails_on_empty_recipe(tmp_path: Path) -> None:
    """The helper rejects a doc whose §4 recipe stage is empty."""
    mod = _load_verify_module()
    # Build a synthetic doc that is structurally legal except for an
    # empty §4.1 body.
    synth = "\n\n".join(
        [
            "# Synthetic",
            "## §1 Scope",
            "Scope body line one.\nScope body line two.\nScope body line three.",
            "## §2 Source",
            "Source body content.",
            "## §3 Target",
            "Target body content.",
            "## §4 Recipe",
            "### §4.1\n\n### §4.2\nbody",
            "## §5 Verify",
            "Verify body --post-resync 92 ENFORCE-READY ENFORCE-Flip real.",
            "## §6 Failure",
            "Failure body.",
            "## §7 Sandbox",
            "Sandbox body.",
            "## §8 Anchor",
            "Anchor body.",
            "-- Reza",
        ]
    )
    synth_path = tmp_path / "synthetic-plan.md"
    synth_path.write_text(synth, encoding="utf-8")
    sections = {
        "§4": synth.split("## §4")[1].split("## §5")[0],
    }
    with pytest.raises(SystemExit) as excinfo:
        mod.check_recipe_stages_nonempty(sections["§4"])
    assert excinfo.value.code == 1


# REUSE-IgnoreEnd
