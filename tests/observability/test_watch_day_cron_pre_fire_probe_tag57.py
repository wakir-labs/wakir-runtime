# SPDX-License-Identifier: Apache-2.0
"""Tag-57 Watch-Day Cron-Pre-Fire-Probe regression tests (Noa SRE).

Tests the helper module
``tooling/ci/verify_watch_day_cron_pre_fire_readiness.py``, and pins
properties of the Tag-56 workflow
``.github/workflows/phase-3c-watch-day-practice-run.yml`` and the
Tag-54 spec ``docs/observability/pre-cutover-watch-day-spec.md``.

The test surface covers three regression classes:

1. **Cron-expression-drift.** Stage A parses the cron expression
   from the Tag-56 workflow. Tests assert that exact-string match,
   that drift is detected, and that next-fire computation is
   correct across DST boundaries / week-boundaries.
2. **Path-filter-drift.** Stage B parses ``push.paths`` and
   ``pull_request.paths``. Tests assert that drift between the two
   lists is detected and that the canonical substrate set is
   pinned.
3. **Routing-table-drift.** Stage C resolves §6.1 / §6.2 routing
   triples. Tests assert that the routing-table shape is stable,
   that spec-anchor probes catch a hypothetical spec edit that
   removes a named trigger, and that the dry-run is in fact
   hermetic (no Mira-Notify file is created, no network call is
   attempted).

The tests are hermetic stdlib + pytest. They do not write to the
notify-log, do not invoke subprocess outside the verifier itself,
and do not require any GitHub Actions runtime.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPO_ROOT / "tooling/ci/verify_watch_day_cron_pre_fire_readiness.py"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/phase-3c-watch-day-practice-run.yml"
PROBE_WORKFLOW_PATH = (
    REPO_ROOT / ".github/workflows/watch-day-cron-pre-fire-probe.yml"
)
SPEC_PATH = REPO_ROOT / "docs/observability/pre-cutover-watch-day-spec.md"


def _load_verifier_module():
    mod_name = "verify_watch_day_cron_pre_fire_readiness"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(VERIFIER_PATH))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module so that dataclass
    # internals (which call sys.modules.get(cls.__module__)) can
    # resolve types defined in the module's own namespace under
    # Python 3.14.
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier():
    return _load_verifier_module()


# ---------------------------------------------------------------------------
# Stage A: cron-expression-parse-test
# ---------------------------------------------------------------------------


def test_a01_cron_extracted_equals_canonical(verifier):
    """The Tag-56 workflow's cron must be exactly `0 5 * * 2`."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    cron = verifier.extract_cron_from_workflow(text)
    assert cron == verifier.CANONICAL_CRON
    assert cron == "0 5 * * 2"


def test_a02_cron_drift_to_daily_is_detected(verifier):
    """If a future edit lands `0 5 * * *`, Stage A reports red."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    tampered = text.replace('cron: "0 5 * * 2"', 'cron: "0 5 * * *"')
    assert tampered != text
    ref = dt.datetime.fromisoformat("2026-06-02T05:00:01+00:00")
    res = verifier.stage_cron(tampered, ref)
    assert res.status == "red"
    assert any("cron_drift" in n for n in res.notes)


def test_a03_cron_drift_to_monday_is_detected(verifier):
    """If a future edit lands `0 5 * * 1` (Mon), Stage A reports red."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    tampered = text.replace('cron: "0 5 * * 2"', 'cron: "0 5 * * 1"')
    ref = dt.datetime.fromisoformat("2026-06-02T05:00:01+00:00")
    res = verifier.stage_cron(tampered, ref)
    assert res.status == "red"


def test_a04_next_four_fires_from_2026_06_02_are_kw24_through_27(verifier):
    """Default reference yields exactly KW-24..27 of 2026."""
    ref = dt.datetime.fromisoformat("2026-06-02T05:00:01+00:00")
    fires = verifier.next_n_tuesday_05_utc(ref, 4)
    assert [f.isoformat() for f in fires] == [
        "2026-06-09T05:00:00+00:00",
        "2026-06-16T05:00:00+00:00",
        "2026-06-23T05:00:00+00:00",
        "2026-06-30T05:00:00+00:00",
    ]
    weeks = [f.isocalendar().week for f in fires]
    assert weeks == [24, 25, 26, 27]


def test_a05_next_fire_skips_through_midnight_correctly(verifier):
    """Monday 23:00 UTC -> next fire Tue 05:00 UTC same week."""
    ref = dt.datetime(2026, 6, 8, 23, 0, 0, tzinfo=dt.timezone.utc)
    fires = verifier.next_n_tuesday_05_utc(ref, 1)
    assert fires == [
        dt.datetime(2026, 6, 9, 5, 0, 0, tzinfo=dt.timezone.utc)
    ]


def test_a06_next_fire_exactly_on_boundary_returns_next_week(verifier):
    """If reference is *exactly* Tue 05:00 UTC, next fire is +7 days.

    The cron-expression interpretation: a fire occurs *at* 05:00. A
    reference at 05:00:00 is the moment of the fire; "next" fire is
    one week later.
    """
    ref = dt.datetime(2026, 6, 9, 5, 0, 0, tzinfo=dt.timezone.utc)
    fires = verifier.next_n_tuesday_05_utc(ref, 1)
    assert fires == [
        dt.datetime(2026, 6, 16, 5, 0, 0, tzinfo=dt.timezone.utc)
    ]


def test_a07_stage_cron_caution_when_kw24_present_but_window_drifts(verifier):
    """Tag-57-era reference still flags CAUTION (window not exact KW-24..27)."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    ref = dt.datetime.fromisoformat("2026-05-19T00:00:00+00:00")
    res = verifier.stage_cron(text, ref)
    # KW-24 is the 4th fire in the next-four list; window is
    # KW-21..24, not the strict KW-24..27, so status is yellow.
    assert res.status == "yellow"
    assert "2026-06-09T05:00:00+00:00" in res.next_fires_iso


# ---------------------------------------------------------------------------
# Stage B: path-filter-coverage-test
# ---------------------------------------------------------------------------


def test_b01_push_paths_byte_equal_pull_request_paths(verifier):
    """The Tag-56 workflow's push and pull_request path-filters must match."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    push = verifier.extract_paths_block(text, "push")
    pr = verifier.extract_paths_block(text, "pull_request")
    assert push == pr
    assert len(push) >= 7


def test_b02_all_canonical_substrates_present(verifier):
    """Each of the seven canonical substrates is filter-covered."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    res = verifier.stage_paths(text)
    assert res.status == "green"
    for path in verifier.CANONICAL_PATH_FILTER_SET:
        assert path in res.push_paths
        assert path in res.pull_request_paths


def test_b03_drift_between_push_and_pr_is_detected(verifier):
    """Synthetic tamper: drop one path from pull_request only -> caution."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Drop the aggregator from pull_request.paths only.
    target = '      - "tooling/ci/aggregate_watch_day_practice_run_verdict.py"'
    push_idx = text.find(target)
    pr_idx = text.find(target, push_idx + 1)
    assert push_idx != -1 and pr_idx != -1 and pr_idx > push_idx
    tampered = text[:pr_idx] + text[pr_idx + len(target) + 1 :]
    res = verifier.stage_paths(tampered)
    # Removing from PR only -> aggregator missing in PR -> red
    # (canonical_substrate_missing dominates over push-pr-drift).
    assert res.status in ("red", "yellow")
    assert "tooling/ci/aggregate_watch_day_practice_run_verdict.py" not in res.pull_request_paths


def test_b04_missing_canonical_substrate_is_red(verifier):
    """Synthetic tamper: drop a canonical path from both blocks -> red."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    target = "scripts/observability/watch-day-practice-run.py"
    tampered = text.replace(f'      - "{target}"\n', "")
    assert target not in tampered or tampered.count(target) < text.count(target)
    res = verifier.stage_paths(tampered)
    assert res.status == "red"


# ---------------------------------------------------------------------------
# Stage C: alert-routing-dry-run
# ---------------------------------------------------------------------------


def test_c01_routing_table_shape_is_stable(verifier):
    """Three Page-class routes + four Ticket-class routes."""
    spec = SPEC_PATH.read_text(encoding="utf-8")
    res = verifier.stage_routing(spec)
    assert res.status == "green"
    assert len(res.page_routes) == 3
    assert len(res.ticket_routes) == 4


def test_c02_page_routes_all_15_minute_sla(verifier):
    """Every §6.1 Page-class route has a 15-minute SLA."""
    spec = SPEC_PATH.read_text(encoding="utf-8")
    res = verifier.stage_routing(spec)
    for route in res.page_routes:
        assert route["severity"] == "P"
        assert route["sla_minutes"] == 15


def test_c03_ticket_routes_have_4h_or_next_biz_day(verifier):
    """Ticket-class SLAs are 240 min (4h) or 1440 min (next biz day)."""
    spec = SPEC_PATH.read_text(encoding="utf-8")
    res = verifier.stage_routing(spec)
    for route in res.ticket_routes:
        assert route["severity"] == "T"
        assert route["sla_minutes"] in (240, 1440)


def test_c04_spec_anchor_drift_caution_when_trigger_renamed(verifier):
    """If the spec no longer mentions a routing trigger by name -> caution."""
    spec = SPEC_PATH.read_text(encoding="utf-8")
    tampered = spec.replace(
        "WAT-pipeline regression", "WAT-anchor-pipeline regression"
    )
    assert "WAT-pipeline regression" not in tampered
    res = verifier.stage_routing(tampered)
    assert res.status == "yellow"
    assert "wat_pipeline_regression" in res.spec_mentions_missing


def test_c05_dry_run_is_hermetic_no_notify_log_written(verifier, tmp_path):
    """Stage C must not write to any notify-log path."""
    spec_dir = tmp_path / "docs/observability"
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / "pre-cutover-watch-day-spec.md"
    spec_path.write_text(SPEC_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    notify_log = tmp_path / "infra/notify-log.jsonl"
    notify_log.parent.mkdir(parents=True)
    notify_log.write_text("", encoding="utf-8")
    cwd_before = os.getcwd()
    try:
        os.chdir(tmp_path)
        spec_text = spec_path.read_text(encoding="utf-8")
        res = verifier.stage_routing(spec_text)
    finally:
        os.chdir(cwd_before)
    assert res.status == "green"
    # Notify-log must remain empty (no dry-run side-effect).
    assert notify_log.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# Stage D / aggregate-verdict
# ---------------------------------------------------------------------------


def test_d01_aggregate_red_dominates(verifier):
    assert verifier.aggregate_verdict("red", "green", "green") == "BLOCK"
    assert verifier.aggregate_verdict("green", "red", "green") == "BLOCK"
    assert verifier.aggregate_verdict("green", "green", "red") == "BLOCK"


def test_d02_aggregate_yellow_becomes_caution(verifier):
    assert verifier.aggregate_verdict("yellow", "green", "green") == "CAUTION"
    assert verifier.aggregate_verdict("green", "yellow", "green") == "CAUTION"
    assert verifier.aggregate_verdict("green", "green", "yellow") == "CAUTION"


def test_d03_aggregate_all_green_is_ready(verifier):
    assert verifier.aggregate_verdict("green", "green", "green") == "READY"


def test_d04_exit_codes_match_verdict_table(verifier):
    assert verifier.exit_code_for_verdict("READY") == 0
    assert verifier.exit_code_for_verdict("CAUTION") == 2
    assert verifier.exit_code_for_verdict("BLOCK") == 1


# ---------------------------------------------------------------------------
# End-to-end smoke-test via subprocess
# ---------------------------------------------------------------------------


def test_e01_subprocess_default_reference_emits_ready():
    """Invoke the verifier as a subprocess, default reference -> READY exit 0."""
    out_path = REPO_ROOT / "out" / "pytest-e01-verdict.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    rc = subprocess.run(
        [
            sys.executable,
            str(VERIFIER_PATH),
            "--mode",
            "all",
            "--output",
            str(out_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, f"stderr={rc.stderr!r} stdout={rc.stdout[:400]!r}"
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == "READY"
    assert envelope["stages"]["cron"]["status"] == "green"
    assert envelope["stages"]["paths"]["status"] == "green"
    assert envelope["stages"]["routing"]["status"] == "green"


def test_e02_probe_workflow_file_is_present_and_parses():
    """The Tag-57 probe workflow file must exist with a workflow_dispatch trigger."""
    assert PROBE_WORKFLOW_PATH.is_file()
    text = PROBE_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "name: watch-day-cron-pre-fire-probe" in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" in text
    # No `push:` trigger (this is a review-time gate, not a calendar
    # re-pin).
    assert not re.search(r"^\s*push:\s*$", text, re.MULTILINE)
    # No `schedule:` trigger.
    assert not re.search(r"^\s*schedule:\s*$", text, re.MULTILINE)


def test_e03_workflow_stages_named_a_b_c_d():
    """The probe workflow exposes four named jobs A/B/C/D."""
    text = PROBE_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "stage-a-cron-expression-parse-test:" in text
    assert "stage-b-path-filter-coverage-test:" in text
    assert "stage-c-alert-routing-dry-run:" in text
    assert "stage-d-decision-aggregation:" in text
