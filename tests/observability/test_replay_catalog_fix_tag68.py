# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-68 Helper-Surface-Drift-Fix tests (Noa SRE).

Pins the substance contract of the Tag-67 Watch-Day Pre-Cutover
Live-Smoke helper-surface drift-fixes shipped under Tag-68:

  Stage 3 (Tag-67 PR #425 surfaced yellow): the Live-Smoke workflow
  probed a fixture at
  ``tests/fixtures/observability/watch_day_practice_run_pinned.json``
  which never existed in main. The Tag-61 multi-sample fixture-set
  lives at ``tests/observability/fixtures/watch-day-practice-run-
  sample-{green,caution,red}.json`` instead. Tag-68 updates the
  workflow to be multi-path-aware and to call the aggregator with
  the actual fixture-set + fixture-path it owns.

  Stage 5 (Tag-67 PR #425 surfaced yellow): the workflow invoked the
  Tag-66 Audit-Trail Verifier as ``--mode catalog``. The verifier's
  CLI surface is subcommand-style and had no ``catalog`` mode. Tag-68
  adds an explicit ``catalog`` subcommand (aliasing ``stage-3`` /
  cross-substrate marker-reference) and a ``--mode <name>`` flag-shim
  so both invocation styles resolve to the same code-path.

Side-effects fixed in the same Tag-68 pass (helper-surface drift
sweep): Stage 2 calls ``--mode all`` (not ``--mode pin``); Stage 4
uses the ``trigger`` subcommand (not ``--mode emit``) and reads the
envelope from ``payload['details']['envelope']``. Both are workflow-
only changes covered by the workflow-pin tests below.

Hermetic: pytest + stdlib + python 3.11. No subprocess except the
inline integration tests that drive the helper end-to-end.

Author: Noa Bergstroem (SRE)
Anchor: Tag-68 Marathon-Continuous-Mode Pre-KW-24 Helper-Surface-
        Drift-Fix.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TAG66_HELPER = (
    REPO_ROOT / "tooling" / "ci" / "verify_watch_day_operator_trigger_audit_trail.py"
)
PRACTICE_RUN_AGGREGATOR = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_watch_day_practice_run_verdict.py"
)
LIVE_SMOKE_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "watch-day-pre-cutover-live-smoke.yml"
)
CANONICAL_FIXTURES_DIR = REPO_ROOT / "tests" / "observability" / "fixtures"


def _import_tag66_helper():
    """Import the Tag-66 verifier helper as a module."""
    mod_name = "verify_watch_day_operator_trigger_audit_trail"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location(mod_name, TAG66_HELPER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# T01 -- Stage 5: 'catalog' subcommand resolves cleanly.
# ---------------------------------------------------------------------------


def test_t01_tag66_catalog_subcommand_registered():
    """The Tag-66 helper's argparse surface includes a ``catalog`` subcommand."""
    mod = _import_tag66_helper()
    parser = mod.build_parser()
    # Probe by parsing a single ``catalog`` argv. argparse rejects
    # unknown subcommands with SystemExit; resolving without exit
    # confirms registration.
    args = parser.parse_args(["catalog", "--repo-root", str(REPO_ROOT)])
    assert args.mode == "catalog"
    assert args.func.__name__ == "cmd_catalog"


# ---------------------------------------------------------------------------
# T02 -- Stage 5: ``--mode catalog`` flag-shim rewrites to subcommand.
# ---------------------------------------------------------------------------


def test_t02_tag66_mode_flag_shim_catalog():
    """The Tag-67 workflow's ``--mode catalog`` invocation rewrites cleanly."""
    mod = _import_tag66_helper()
    out = mod._rewrite_mode_flag(["--mode", "catalog", "--repo-root", "."])
    assert out == ["catalog", "--repo-root", "."]


# ---------------------------------------------------------------------------
# T03 -- Stage 5: ``--mode=catalog`` single-token form also rewrites.
# ---------------------------------------------------------------------------


def test_t03_tag66_mode_flag_shim_equals_form():
    """The shim also handles ``--mode=<name>`` (single-token form)."""
    mod = _import_tag66_helper()
    out = mod._rewrite_mode_flag(["--mode=catalog", "--repo-root", "."])
    assert out == ["catalog", "--repo-root", "."]


# ---------------------------------------------------------------------------
# T04 -- Stage 5: subprocess invocation with ``--mode catalog`` succeeds.
# ---------------------------------------------------------------------------


def test_t04_tag66_subprocess_mode_catalog_green():
    """Running the helper as the workflow does emits the catalog-conformance
    verdict and exits 0 (substrate green) on a clean tree."""
    proc = subprocess.run(
        [sys.executable, str(TAG66_HELPER), "--mode", "catalog", "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "stage_3_cross_substrate_marker_reference: green" in proc.stdout


# ---------------------------------------------------------------------------
# T05 -- Stage 5: ``catalog`` subcommand is a true alias of ``stage-3``.
# ---------------------------------------------------------------------------


def test_t05_tag66_catalog_aliases_stage3():
    """Both ``catalog`` and ``stage-3`` resolve to ``cmd_stage3`` semantics.

    The catalog alias shares the cross-substrate marker-reference
    logic; pin that the two CLI surfaces produce the same exit code
    and the same stdout marker on the same tree.
    """
    proc_catalog = subprocess.run(
        [sys.executable, str(TAG66_HELPER), "catalog", "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    proc_stage3 = subprocess.run(
        [sys.executable, str(TAG66_HELPER), "stage-3", "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc_catalog.returncode == proc_stage3.returncode
    # Both print the same status line.
    assert "stage_3_cross_substrate_marker_reference" in proc_catalog.stdout
    assert "stage_3_cross_substrate_marker_reference" in proc_stage3.stdout


# ---------------------------------------------------------------------------
# T06 -- Stage 5: existing subcommand surface is unchanged.
# ---------------------------------------------------------------------------


def test_t06_tag66_legacy_subcommands_still_resolve():
    """Tag-68 must not break the existing Tag-66 CLI surface."""
    mod = _import_tag66_helper()
    parser = mod.build_parser()
    for sub in ("stage-1", "stage-2", "stage-3", "aggregate", "full"):
        # stage-2 requires --stage-1-envelope to actually run, but
        # parse-time validation is what we want here.
        if sub == "stage-2":
            args = parser.parse_args([sub, "--stage-1-envelope", "/tmp/x.json"])
        elif sub == "aggregate":
            args = parser.parse_args([sub])
        else:
            args = parser.parse_args([sub])
        assert args.mode == sub


# ---------------------------------------------------------------------------
# T07 -- Stage 5: ``--mode`` flag-shim leaves unknown values alone.
# ---------------------------------------------------------------------------


def test_t07_tag66_mode_flag_shim_unknown_passthrough():
    """An unknown ``--mode`` value is NOT rewritten; argparse owns the error."""
    mod = _import_tag66_helper()
    out = mod._rewrite_mode_flag(["--mode", "bogus", "--repo-root", "."])
    assert out == ["--mode", "bogus", "--repo-root", "."]


# ---------------------------------------------------------------------------
# T08 -- Stage 3: canonical multi-sample fixtures exist at the expected path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", ["green", "caution", "red"])
def test_t08_stage3_canonical_fixtures_present(set_name: str):
    """Every Tag-61 fixture-set has a file at the canonical path."""
    fixture = CANONICAL_FIXTURES_DIR / f"watch-day-practice-run-sample-{set_name}.json"
    assert fixture.is_file(), f"fixture missing: {fixture}"
    # Sanity: parses as JSON with the practice-run schema shape.
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert "scenarios" in payload
    assert "overall_pass" in payload


# ---------------------------------------------------------------------------
# T09 -- Stage 3: replay-mode against the canonical green fixture returns
#                 REPLAY-STABLE (exit 0).
# ---------------------------------------------------------------------------


def test_t09_stage3_canonical_green_fixture_replay_stable(tmp_path: Path):
    """The Tag-68 Stage-3 fix path (canonical fixture + --fixture-set green)
    must produce REPLAY-STABLE in the practice-run aggregator."""
    fixture = CANONICAL_FIXTURES_DIR / "watch-day-practice-run-sample-green.json"
    output = tmp_path / "verdict.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(PRACTICE_RUN_AGGREGATOR),
            "--mode",
            "replay",
            "--fixture-set",
            "green",
            "--fixture-path",
            str(fixture),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["verdict"] == "REPLAY-STABLE"


# ---------------------------------------------------------------------------
# T10 -- Workflow pin: Stage 3 step calls the actual aggregator surface.
# ---------------------------------------------------------------------------


def test_t10_workflow_stage3_calls_canonical_fixture_path():
    """The Live-Smoke workflow's Stage 3 step probes the canonical
    multi-sample fixture path (Tag-68 fix), not just the legacy path."""
    text = LIVE_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    # Canonical directory pin (the path is composed in shell from
    # ``${canonical_dir}/watch-day-practice-run-sample-green.json``).
    assert "tests/observability/fixtures" in text, (
        "Stage 3 must reference the canonical Tag-61 fixture directory"
    )
    assert "watch-day-practice-run-sample-green.json" in text, (
        "Stage 3 must reference the canonical Tag-61 green-sample fixture"
    )
    assert "--fixture-set" in text, "Stage 3 must pass --fixture-set to the aggregator"


# ---------------------------------------------------------------------------
# T11 -- Workflow pin: Stage 5 step calls ``--mode catalog`` (preserved).
# ---------------------------------------------------------------------------


def test_t11_workflow_stage5_calls_mode_catalog():
    """Stage 5 invocation surface is preserved (workflow-side stays minimal;
    the helper grew the catalog mode under Tag-68)."""
    text = LIVE_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    assert "verify_watch_day_operator_trigger_audit_trail.py" in text
    assert "--mode catalog" in text


# ---------------------------------------------------------------------------
# T12 -- Workflow pin: Stage 5 yellow-fallback removed (Tag-68 hardening).
# ---------------------------------------------------------------------------


def test_t12_workflow_stage5_no_silent_yellow_fallback():
    """Pre-Tag-68 the workflow had a 'lacks catalog mode -> yellow' fallback.
    Tag-68 now owns the catalog mode; the fallback must promote a real
    helper failure to red, not silently yellow it."""
    text = LIVE_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    # The fallback comment must be replaced; the explicit red branch
    # for "helper exists but invocation failed" must be present.
    assert "lacks 'catalog' mode in this" not in text, (
        "Tag-68: the silent-yellow fallback comment is the pre-fix marker"
    )
    # Stage 5 must include a real red branch.
    stage5_block_start = text.find("Stage 5 - audit-trail-verify")
    stage5_block_end = text.find("Stage 6 -", stage5_block_start)
    assert stage5_block_start != -1 and stage5_block_end != -1
    stage5_block = text[stage5_block_start:stage5_block_end]
    assert "STAGE5_STATUS=red" in stage5_block


# ---------------------------------------------------------------------------
# T13 -- Workflow pin: Stage 2 calls ``--mode all`` (side-sweep fix).
# ---------------------------------------------------------------------------


def test_t13_workflow_stage2_uses_mode_all():
    """Stage 2 must call ``--mode all`` (the actual CLI surface), not the
    pre-Tag-68 ``--mode pin`` which never resolved."""
    text = LIVE_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    stage2_start = text.find("Stage 2 - cron-pre-fire-probe")
    stage2_end = text.find("Stage 3 -", stage2_start)
    assert stage2_start != -1 and stage2_end != -1
    stage2_block = text[stage2_start:stage2_end]
    assert "--mode all" in stage2_block
    assert "--mode pin" not in stage2_block


# ---------------------------------------------------------------------------
# T14 -- Workflow pin: Stage 4 reads envelope from details.envelope.
# ---------------------------------------------------------------------------


def test_t14_workflow_stage4_reads_nested_envelope():
    """Stage 4 must read the dispatch envelope from
    ``payload['details']['envelope']`` (Tag-68 fix; the simulator's
    output is wrapped, not flat)."""
    text = LIVE_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    stage4_start = text.find("Stage 4 - operator-trigger-integration")
    stage4_end = text.find("Stage 5 -", stage4_start)
    assert stage4_start != -1 and stage4_end != -1
    stage4_block = text[stage4_start:stage4_end]
    # The post-Tag-68 invocation uses the ``trigger`` subcommand, not
    # the broken ``--mode emit`` flag.
    assert "trigger --output" in stage4_block
    assert "--mode emit" not in stage4_block
    # The envelope extraction must walk into details.envelope.
    assert "details" in stage4_block and "envelope" in stage4_block


# ---------------------------------------------------------------------------
# T15 -- Substrate-inventory still pins the Tag-66 helper.
# ---------------------------------------------------------------------------


def test_t15_substrate_inventory_pins_tag66_helper():
    """The Tag-67 substrate-inventory must still reference the Tag-66
    helper after the Tag-68 helper change (Tag-68 is additive)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location(
        "aggregate_watch_day_pre_cutover_live_smoke",
        REPO_ROOT / "tooling" / "ci" / "aggregate_watch_day_pre_cutover_live_smoke.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    paths = {rel for _tag, _kind, rel in mod.SUBSTRATE_INVENTORY}
    assert "tooling/ci/verify_watch_day_operator_trigger_audit_trail.py" in paths


# ---------------------------------------------------------------------------
# T16 -- End-to-end: running all six Live-Smoke stages locally produces
#                    LIVE-SMOKE-INTACT.
# ---------------------------------------------------------------------------


def test_t16_end_to_end_live_smoke_intact(tmp_path: Path):
    """Drive all six stages locally with the post-Tag-68 invocation surfaces.
    Pin LIVE-SMOKE-INTACT as the aggregate verdict."""
    # Stage 1: synthetic all-green env.
    proc = subprocess.run(
        [
            sys.executable,
            str(PRACTICE_RUN_AGGREGATOR),
            "--mode",
            "aggregate",
            "--output",
            str(tmp_path / "s1.json"),
        ],
        env={
            "STEP1_STATUS": "green",
            "STEP2_STATUS": "green",
            "STEP3_STATUS": "green",
            "STEP4_STATUS": "green",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"stage1 failed: {proc.stderr}"

    # Stage 2: --mode all (post-Tag-68 surface).
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "ci" / "verify_watch_day_cron_pre_fire_readiness.py"),
            "--mode",
            "all",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"stage2 failed: {proc.stdout} {proc.stderr}"

    # Stage 3: canonical fixture + --fixture-set (post-Tag-68 surface).
    proc = subprocess.run(
        [
            sys.executable,
            str(PRACTICE_RUN_AGGREGATOR),
            "--mode",
            "replay",
            "--fixture-set",
            "green",
            "--fixture-path",
            str(
                CANONICAL_FIXTURES_DIR
                / "watch-day-practice-run-sample-green.json"
            ),
            "--output",
            str(tmp_path / "s3.json"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"stage3 failed: {proc.stdout} {proc.stderr}"

    # Stage 4: trigger subcommand + nested envelope read (post-Tag-68).
    stage4_out = tmp_path / "s4.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "ci" / "simulate_watch_day_operator_trigger.py"),
            "trigger",
            "--output",
            str(stage4_out),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode in (0, 2), f"stage4 failed: {proc.stderr}"
    payload = json.loads(stage4_out.read_text(encoding="utf-8"))
    envelope = payload.get("details", {}).get("envelope", {})
    assert {"event", "workflow", "ref", "inputs"}.issubset(envelope.keys())

    # Stage 5: --mode catalog (post-Tag-68 surface).
    proc = subprocess.run(
        [
            sys.executable,
            str(TAG66_HELPER),
            "--mode",
            "catalog",
            "--repo-root",
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"stage5 failed: {proc.stdout} {proc.stderr}"

    # Stage 6: substrate-coupling-map.
    proc = subprocess.run(
        [
            sys.executable,
            str(
                REPO_ROOT
                / "tooling"
                / "ci"
                / "aggregate_watch_day_pre_cutover_live_smoke.py"
            ),
            "pin-substrate",
            "--repo-root",
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"stage6 failed: {proc.stderr}"

    # Aggregate verdict.
    verdict_path = tmp_path / "verdict.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(
                REPO_ROOT
                / "tooling"
                / "ci"
                / "aggregate_watch_day_pre_cutover_live_smoke.py"
            ),
            "aggregate",
            "--output",
            str(verdict_path),
        ],
        env={
            "STAGE1_STATUS": "green",
            "STAGE2_STATUS": "green",
            "STAGE3_STATUS": "green",
            "STAGE4_STATUS": "green",
            "STAGE5_STATUS": "green",
            "STAGE6_STATUS": "green",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"aggregate failed: {proc.stdout} {proc.stderr}"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["verdict"] == "LIVE-SMOKE-INTACT"
    for stage in verdict["stages"]:
        assert stage["status"] == "green", f"stage {stage} not green"
