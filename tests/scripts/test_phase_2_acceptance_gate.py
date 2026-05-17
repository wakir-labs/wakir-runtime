# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for the Phase-2 Acceptance Gate workflow contract — Tag-22 Mini-Welle.

Where ``test_doppelbetrieb_score_aggregator.py`` exercises the
aggregator *library* (per-axis evaluators, envelope assembly, CLI
plumbing), this test module exercises the **gate contract** the
`phase-2-acceptance-gate.yml` workflow depends on:

* The `--threshold N` flag actually gates pass/fail at the CLI exit-
  code boundary.
* Missing axes are not silently dropped; the rollup always lists
  every axis from ``AXIS_ORDER``.
* Malformed inputs (broken fixture file) surface as a non-zero CLI
  exit code, not a corrupt rollup.
* The workflow YAML stays in sync with the aggregator surface (job
  name, CLI invocation, artifact path) — drift here breaks the
  daily ops signal.

The tests use the aggregator's library seams (``build_envelope``
with synthetic ``AxisResult``s, plus subprocess-driven CLI runs
with injected fixture paths) so they are hermetic, do not touch
the network, and do not actually run the Phase-2-gate pytest suite
inside this test module (that lane is covered by
``test_doppelbetrieb_score_aggregator.py`` and by the
``phase-2-validation-gate.yml`` workflow).

Test inventory (6 cases)
------------------------

1. test_threshold_pass_at_or_above_floor
2. test_threshold_fail_below_floor
3. test_missing_axis_marked_failed_in_envelope
4. test_malformed_federation_frame_fixture_rejected
5. test_workflow_yaml_references_aggregator_cli_surface
6. test_workflow_yaml_job_name_matches_ops_doc
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader (script lives under scripts/ with a hyphenated filename)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = REPO_ROOT / "scripts" / "doppelbetrieb-score-aggregator.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "phase-2-acceptance-gate.yml"
OPS_DOC_PATH = REPO_ROOT / "docs" / "operations" / "phase-2-acceptance-gate.md"


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "doppelbetrieb_score_aggregator_phase_2_gate", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


aggregator = _load_aggregator()


def _all_pass_axes():
    """Synthetic AxisResults — one per AXIS_ORDER entry, all pass.
    Tag-29 (ADR-0066): 11 axes total (8 Tag-15 + 3 Cross-Modul).
    """
    return [
        aggregator.AxisResult(label=label, pass_=True, weight=1)
        for label in aggregator.AXIS_ORDER
    ]


# ---------------------------------------------------------------------------
# 1. Threshold pass at or above the floor
# ---------------------------------------------------------------------------


def test_threshold_pass_at_or_above_floor():
    """The CI gate uses ``--threshold 9`` (Tag-29). With ten axes
    passing (one short of the 11/11 strict default), the rollup MUST
    report ``threshold_pass=True`` and ``total_score=10``. Anything
    else breaks the 9/11 ops contract documented in
    ``docs/operations/phase-2-acceptance-gate.md``.
    """
    axes = _all_pass_axes()
    assert len(axes) == 11, "Tag-29 axis-count drift"
    # Flip one axis to fail to simulate the typical "anchor-emitter
    # env-not-set on CI" scenario (the daily gate accepts that miss).
    axes[-1] = aggregator.AxisResult(
        label=axes[-1].label,
        pass_=False,
        weight=1,
        details={"both_envs_rust": False},
    )
    envelope = aggregator.build_envelope(axes, threshold=9, ts_utc="2026-05-17T02:00:00Z")
    assert envelope["total_score"] == 10
    assert envelope["threshold"] == 9
    assert envelope["threshold_pass"] is True
    # The strict 11/11 floor MUST fail this same envelope.
    strict = aggregator.build_envelope(axes, threshold=11, ts_utc="2026-05-17T02:00:00Z")
    assert strict["total_score"] == 10
    assert strict["threshold"] == 11
    assert strict["threshold_pass"] is False


# ---------------------------------------------------------------------------
# 2. Threshold fail below the floor
# ---------------------------------------------------------------------------


def test_threshold_fail_below_floor():
    """With only eight axes passing (three concurrent regressions —
    the post-Tag-29 escalation contract), the 9/11 CI gate MUST
    fail. The aggregator's CLI exit code MUST be 1 (threshold-fail),
    not 0.
    """
    axes = _all_pass_axes()
    # Fail axes 8, 9, 10 (last three) — drops total_score to 8.
    for i in (-1, -2, -3):
        old = axes[i]
        axes[i] = aggregator.AxisResult(
            label=old.label, pass_=False, weight=old.weight
        )
    envelope = aggregator.build_envelope(axes, threshold=9)
    assert envelope["total_score"] == 8
    assert envelope["threshold"] == 9
    assert envelope["threshold_pass"] is False
    # Sanity-check: relaxing to threshold=8 flips it green again.
    relaxed = aggregator.build_envelope(axes, threshold=8)
    assert relaxed["threshold_pass"] is True


# ---------------------------------------------------------------------------
# 3. Missing axis handled (not silently dropped)
# ---------------------------------------------------------------------------


def test_missing_axis_marked_failed_in_envelope():
    """If the aggregator is fed an incomplete axis-set (e.g. the
    cross-lang evaluator crashed and returned no result), the
    envelope MUST still list every AXIS_ORDER entry; the missing
    ones MUST appear as ``pass=false`` with
    ``details.reason=='axis-missing'``. Silent-drop would let a
    regression hide behind a partial rollup.
    """
    # Provide only the first five axes; omit the last six (post-Tag-29).
    partial = [
        aggregator.AxisResult(label=label, pass_=True, weight=1)
        for label in aggregator.AXIS_ORDER[:5]
    ]
    envelope = aggregator.build_envelope(partial, threshold=11)
    # All eleven axes present.
    assert set(envelope["axes"].keys()) == set(aggregator.AXIS_ORDER)
    # Each missing axis flagged correctly.
    for label in aggregator.AXIS_ORDER[5:]:
        axis = envelope["axes"][label]
        assert axis["pass"] is False, f"missing axis {label} should be False"
        assert axis["details"]["reason"] == "axis-missing"
    # total_score reflects only the five that did pass.
    assert envelope["total_score"] == 5
    assert envelope["threshold_pass"] is False


# ---------------------------------------------------------------------------
# 4. Malformed fixture rejected
# ---------------------------------------------------------------------------


def test_malformed_federation_frame_fixture_rejected(tmp_path):
    """The federation-frame fixture-loader MUST raise ValueError when
    the JSON is structurally wrong (missing the ``fixtures`` list).
    The aggregator surfaces this as an exception that bubbles into a
    non-zero CLI exit code; we test the bubble-up path here directly
    against ``_count_federation_frame_pins`` so the loader is locked
    against silently returning 0 (which would corrupt the pin-count
    axis and could hide regressions behind a "passing" 0-count).
    """
    bad_fixture = tmp_path / "broken.json"
    # Top-level object missing the "fixtures" list — should raise.
    bad_fixture.write_text(json.dumps({"not_fixtures": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'fixtures' list"):
        aggregator._count_federation_frame_pins(bad_fixture)
    # And: JSON-parse error (truncated content) MUST also raise —
    # the loader does not swallow it into a 0-count.
    truncated = tmp_path / "truncated.json"
    truncated.write_text("{not-json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        aggregator._count_federation_frame_pins(truncated)
    # Valid empty fixtures list returns 0 (legal — drives the per-
    # contract count check elsewhere, not an exception path).
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"fixtures": []}), encoding="utf-8")
    assert aggregator._count_federation_frame_pins(empty) == 0


# ---------------------------------------------------------------------------
# 5. Workflow YAML still references the aggregator CLI surface
# ---------------------------------------------------------------------------


def test_workflow_yaml_references_aggregator_cli_surface():
    """The workflow YAML MUST keep its invocation in sync with the
    aggregator CLI surface. If the script is renamed, or the
    ``--mode=full`` / ``--threshold`` / ``--out`` flags drift, the
    daily gate silently breaks (or worse: stops running but stays
    "green" because GitHub treats a non-running job as N/A). We pin
    the contract here.
    """
    assert WORKFLOW_PATH.exists(), f"workflow missing at {WORKFLOW_PATH}"
    body = WORKFLOW_PATH.read_text(encoding="utf-8")
    # CLI invocation pins. Tag-29 makes the mode dispatch-input-driven
    # (default ``full``, alternatives ``cross-modul-stress`` and
    # ``cross-lang-only``), so we only require that the ``--mode=``
    # flag is wired to the resolved mode-output, plus the default is
    # mentioned in the dispatch-input definition.
    assert "scripts/doppelbetrieb-score-aggregator.py" in body
    assert "--mode=" in body, "aggregator invocation must pass --mode="
    assert (
        'default: "full"' in body
        or "default: full" in body
    ), "workflow_dispatch mode input must default to 'full'"
    assert "--threshold" in body
    assert "--out " in body or "--out=" in body or "--out\n" in body
    # The aggregator entry-point file exists.
    assert AGGREGATOR_PATH.exists()
    # The trigger surface is the documented one: schedule + push +
    # workflow_dispatch (no pull_request).
    assert "schedule:" in body
    assert "workflow_dispatch" in body
    assert "branches:\n      - main" in body
    # `pull_request` MUST NOT appear in the `on:` trigger block.
    # (It may appear in header comments — those are docs, not triggers.
    # We slice off the header comment block before scanning.)
    body_after_name = body.split("\nname:", 1)[1] if "\nname:" in body else body
    on_block_start = body_after_name.find("\non:")
    jobs_block_start = body_after_name.find("\njobs:")
    assert on_block_start != -1 and jobs_block_start != -1
    on_block = body_after_name[on_block_start:jobs_block_start]
    assert "pull_request" not in on_block, (
        "phase-2-acceptance-gate MUST NOT trigger on pull_request; "
        "the per-PR lane is phase-2-validation-gate.yml"
    )


# ---------------------------------------------------------------------------
# 6. Workflow job-name matches the ops-doc table
# ---------------------------------------------------------------------------


def test_workflow_yaml_job_name_matches_ops_doc():
    """The required-check-display-name discipline
    (``feedback_branch_protection_check_names.md``) says we pin the
    job-display-name, not the workflow name. The ops-doc references
    a specific job-name; this test guards the cross-reference so a
    rename is caught here.
    """
    assert WORKFLOW_PATH.exists(), f"workflow missing at {WORKFLOW_PATH}"
    body = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Job display name pinned in the workflow.
    assert "name: Phase-2 Acceptance Gate (Doppelbetrieb-Score)" in body
    # And referenced in the ops doc.
    assert OPS_DOC_PATH.exists(), f"ops doc missing at {OPS_DOC_PATH}"
    doc = OPS_DOC_PATH.read_text(encoding="utf-8")
    assert "phase-2-acceptance-gate.yml" in doc
    assert "phase-2-validation-gate" in doc, (
        "ops doc MUST contrast the two phase-2 gate lanes"
    )
    assert "scripts/doppelbetrieb-score-aggregator.py" in doc


# ---------------------------------------------------------------------------
# Bonus: smoke-test the CLI path through subprocess
# ---------------------------------------------------------------------------


def test_cli_smoke_with_explicit_threshold(tmp_path, monkeypatch):
    """Drive the CLI's mode=cross-lang-only path through subprocess
    (cheaper than mode=full) and confirm the output JSON conforms to
    the schema. Locks the round-trip from argparse → build_envelope →
    JSON-on-disk that the workflow's "Upload rollup artifact" step
    depends on.
    """
    out_path = tmp_path / "rollup.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(AGGREGATOR_PATH),
            "--mode=cross-lang-only",
            "--threshold",
            "1",
            "--out",
            str(out_path),
            "--ts-utc",
            "2026-05-17T02:00:00Z",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    # Three acceptable outcomes:
    #   rc=0 — pin-counts match, envelope written, threshold-pass
    #   rc=1 — pin-counts drifted but envelope still written, threshold-fail
    #   rc=2 — environment-missing (e.g. wirelang not installed in
    #          the test runner's site-packages). The CLI's contract
    #          is that rc=2 writes an error to stderr and does NOT
    #          produce a partial rollup.
    assert proc.returncode in (0, 1, 2), (
        f"unexpected rc {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    if proc.returncode == 2:
        # Environment-error path: stderr MUST carry the standard
        # prefix and no rollup is produced.
        assert "[doppelbetrieb-score-aggregator] ERROR" in proc.stderr
        assert not out_path.exists() or out_path.read_text() == "", (
            "rc=2 MUST NOT leave a partial rollup behind"
        )
        return
    # rc 0/1 path: envelope MUST be written and conform to schema.
    assert out_path.exists(), "aggregator did not write --out"
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == aggregator.SCHEMA
    assert payload["ts_utc"] == "2026-05-17T02:00:00Z"
    assert payload["threshold"] == 1
    # Cross-lang-only mode emits one axis; the envelope still lists
    # all eleven AXIS_ORDER entries (the other ten default to
    # axis-missing).
    assert set(payload["axes"].keys()) == set(aggregator.AXIS_ORDER)
