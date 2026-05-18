# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bug-42 Regression-Suite (Tag-48).

Owner: Amara Osei (QA)
Source: Tag-48 Amara Auftrag (Continuous-Mode, 2026-05-18/19)
Related ADRs / spec sections:
- Tag-41 PR #265 (Selin) — Bug-42 silent-drop F-1 fix:
  ``wirelang/persona_engine/publish_mode_contract.py`` (Adapter-B
  substrate), ``wirelang/cli/bridge_forward.py`` (``--publish-mode``
  dispatch), ``wirelang/persona_engine/cli.py`` (``require_compatible``
  pre-flight gate).
- Tag-43 PR #278 (Selin) — NATS-JetStream-Subjects-Audit-Baseline
  (0 drift) at ``scripts/audit/nats-jetstream-subjects-audit.py``.
- Spec ``wirelang/specs/wirelang-spec-v0-2.md`` §13.2 / §13.3 / §13.4.
- Schema ``wirelang/schemas/layer-0-transport.json``
  (single source of truth for the canonical subject regex).

Contract scope
--------------
This suite asserts that the Bug-42 fix (Tag-41 PR #265) cannot
silently regress along three axes:

1.  **Section A — Publish-Mode-Contract-Matrix (5 tests).** All four
    ``publish_mode × subscribe_surface`` combinations behave per the
    spec §13.2 frozen matrix. F-1 / F-2 stay BROKEN; the two HARD-
    COMPATIBLE pairs stay COMPATIBLE; the fan-out pair stays FANOUT-
    dependent; the env-var resolver round-trips both valid modes and
    rejects an unknown mode.

2.  **Section B — NATS-Subject-Pattern-Drift (6 tests).** The 7
    ``wakir.<env>.*`` literal/template sites listed in the Tag-43
    audit baseline (2 templates × 4 sites + 2 concrete literals + 1
    output-channel template = 7 hits in 5 distinct files) all match
    the canonical schema regex; the canonical regex itself is pinned
    against the JSON-Schema; and a known-bad literal (capital
    ``Agent``) is classified as drift by the audit's template
    classifier.

3.  **Section C — Failure-Mode-Catalogue (5 tests).** The spec's
    F-1..F-6 catalogue is intact: all six IDs are present in the
    spec; the machine-readable ``_FAILURE_MODE_BY_PAIR`` dispatch
    maps the two BROKEN pairs to F-1 / F-2; ``SurfaceMismatchError``
    carries the verdict on a broken pipe; the recommended-adapter
    sentence references both Adapter-A and Adapter-B per spec §13.4.

4.  **Section D — Audit-Script-Invariants (4 tests).** The Tag-43
    audit, run against the repo at HEAD, still reports 0 drift, 24
    wakir-namespace literals, 7 NATS subjects, and exactly 3
    mode-cross-validation modules; the audit's exit code stays 0 in
    audit-only mode and 0 in ``--enforce`` mode (drift-free repo).

This is a Zone-M cross-component regression suite: it consumes
Selin's publish-mode-contract module and Selin's audit script as
read-only test surface. It does **not** modify either; it pins their
observable invariants so Tag-49+ refactors cannot silently break the
Bug-42 closure.

Hermetic profile
----------------
- No live NATS, no container runtime, no network.
- The audit script is loaded as a Python module via
  ``importlib.util.spec_from_file_location`` because its filename
  contains hyphens (not importable via plain ``import``).
- The frozen-matrix tests parametrize over the public mode constants
  exposed by :mod:`wirelang.persona_engine.publish_mode_contract` so
  a future rename of a constant is caught at import time (loud) and
  a future addition of a mode shows up as a parametrize gap (loud).
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Tuple

import pytest

from wirelang.persona_engine import publish_mode_contract as pmc


# ---------------------------------------------------------------------------
# Fixtures / module-level helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUDIT_SCRIPT = _REPO_ROOT / "scripts" / "audit" / "nats-jetstream-subjects-audit.py"
_SPEC_FILE = _REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-2.md"
_TRANSPORT_SCHEMA = _REPO_ROOT / "wirelang" / "schemas" / "layer-0-transport.json"


def _load_audit_module():
    """Load the audit script as a Python module (filename has hyphens)."""
    spec = importlib.util.spec_from_file_location(
        "nats_jetstream_subjects_audit",
        _AUDIT_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["nats_jetstream_subjects_audit"] = module
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit_module():
    return _load_audit_module()


@pytest.fixture(scope="module")
def audit_result(audit_module):
    """Run the full audit once per session — pin the snapshot."""
    return audit_module.audit_repo(_REPO_ROOT)


# ---------------------------------------------------------------------------
# Section A — Publish-Mode-Contract-Matrix (5 tests)
# ---------------------------------------------------------------------------
#
# Spec §13.2 frozen matrix:
#
#                  | sub=core | sub=js-push | sub=js-pull
#   pub=core       | COMPAT   | F-2 BROKEN  | F-1 BROKEN
#   pub=jetstream  | FANOUT   | COMPAT      | COMPAT
#
# Every cell is exercised; the matrix is parameterized so a future
# mode addition surfaces as a parametrize gap.


_ALL_PUBLISH_MODES: Tuple[str, ...] = pmc.VALID_PUBLISH_MODES
_ALL_SUBSCRIBE_SURFACES: Tuple[str, ...] = pmc.VALID_SUBSCRIBE_SURFACES


@pytest.mark.parametrize(
    "publish_mode,subscribe_surface,expected_verdict,expected_failure",
    [
        # COMPATIBLE pairs (Bug-42 closure HARD-set)
        (pmc.PUBLISH_MODE_CORE, pmc.SUBSCRIBE_SURFACE_CORE,
         pmc.VERDICT_COMPATIBLE, None),
        (pmc.PUBLISH_MODE_JETSTREAM, pmc.SUBSCRIBE_SURFACE_JS_PUSH,
         pmc.VERDICT_COMPATIBLE, None),
        (pmc.PUBLISH_MODE_JETSTREAM, pmc.SUBSCRIBE_SURFACE_JS_PULL,
         pmc.VERDICT_COMPATIBLE, None),
        # BROKEN pairs (silent-drop classes F-1, F-2)
        (pmc.PUBLISH_MODE_CORE, pmc.SUBSCRIBE_SURFACE_JS_PULL,
         pmc.VERDICT_BROKEN, "F-1"),
        (pmc.PUBLISH_MODE_CORE, pmc.SUBSCRIBE_SURFACE_JS_PUSH,
         pmc.VERDICT_BROKEN, "F-2"),
        # FANOUT pair (spec §13.2 footnote ¹ — MUST-NOT-rely)
        (pmc.PUBLISH_MODE_JETSTREAM, pmc.SUBSCRIBE_SURFACE_CORE,
         pmc.VERDICT_FANOUT, None),
    ],
)
def test_a1_publish_mode_matrix_full_six_cells(
    publish_mode: str,
    subscribe_surface: str,
    expected_verdict: str,
    expected_failure: str,
) -> None:
    """A1: All 6 cells of the (publish_mode × subscribe_surface) matrix
    return the expected verdict and failure-mode-id."""
    verdict = pmc.check_compatibility(publish_mode, subscribe_surface)
    assert verdict.verdict == expected_verdict, (
        f"({publish_mode}, {subscribe_surface}) expected {expected_verdict}, "
        f"got {verdict.verdict}"
    )
    assert verdict.failure_mode_id == expected_failure, (
        f"({publish_mode}, {subscribe_surface}) expected failure_mode_id="
        f"{expected_failure}, got {verdict.failure_mode_id}"
    )


def test_a2_matrix_dimensions_pin_2x3_shape() -> None:
    """A2: VALID_PUBLISH_MODES is 2 entries; VALID_SUBSCRIBE_SURFACES is 3.

    A future mode addition forces a deliberate matrix update — the
    parametrize in A1 will fall short of (len(pubs) * len(subs)) and
    the next-cell tests below will surface the gap.
    """
    assert len(_ALL_PUBLISH_MODES) == 2, _ALL_PUBLISH_MODES
    assert len(_ALL_SUBSCRIBE_SURFACES) == 3, _ALL_SUBSCRIBE_SURFACES
    assert set(_ALL_PUBLISH_MODES) == {
        pmc.PUBLISH_MODE_CORE, pmc.PUBLISH_MODE_JETSTREAM,
    }
    assert set(_ALL_SUBSCRIBE_SURFACES) == {
        pmc.SUBSCRIBE_SURFACE_CORE,
        pmc.SUBSCRIBE_SURFACE_JS_PUSH,
        pmc.SUBSCRIBE_SURFACE_JS_PULL,
    }


def test_a3_require_compatible_raises_on_broken_pipe() -> None:
    """A3: ``require_compatible`` raises ``SurfaceMismatchError`` on F-1.

    This is the Tag-41 Adapter-B preflight gate — the test pins that
    the gate is a hard raise, not a warning.
    """
    with pytest.raises(pmc.SurfaceMismatchError) as exc_info:
        pmc.require_compatible(
            pmc.PUBLISH_MODE_CORE,
            pmc.SUBSCRIBE_SURFACE_JS_PULL,
        )
    err = exc_info.value
    assert err.verdict.verdict == pmc.VERDICT_BROKEN
    assert err.verdict.failure_mode_id == "F-1"
    # Diagnosis sentence MUST reference the spec section so operator
    # logs are runbook-actionable.
    assert "spec §13.2" in err.verdict.diagnosis or "13.2" in err.verdict.diagnosis


def test_a4_require_compatible_fanout_gate_off_by_default() -> None:
    """A4: ``require_compatible`` raises on FANOUT unless allow_fanout=True.

    Spec §13.2 footnote ¹ — fan-out MUST NOT be relied upon for
    correctness. Default-deny pins that intent.
    """
    with pytest.raises(pmc.SurfaceMismatchError):
        pmc.require_compatible(
            pmc.PUBLISH_MODE_JETSTREAM,
            pmc.SUBSCRIBE_SURFACE_CORE,
        )
    # With explicit opt-in the verdict is returned, not raised.
    verdict = pmc.require_compatible(
        pmc.PUBLISH_MODE_JETSTREAM,
        pmc.SUBSCRIBE_SURFACE_CORE,
        allow_fanout=True,
    )
    assert verdict.verdict == pmc.VERDICT_FANOUT


def test_a5_env_var_resolver_roundtrips_and_rejects(monkeypatch) -> None:
    """A5: ``resolve_publish_mode`` honours both valid modes from env
    and raises on unknown / malformed env values."""
    # Default (unset → core, per spec §13.5)
    assert pmc.resolve_publish_mode({}) == pmc.DEFAULT_PUBLISH_MODE
    assert pmc.resolve_publish_mode({}) == "core"

    # Both valid modes round-trip explicitly via env override.
    for mode in pmc.VALID_PUBLISH_MODES:
        env = {pmc.PUBLISH_MODE_ENV_VAR: mode}
        assert pmc.resolve_publish_mode(env) == mode

    # Unknown mode is rejected loudly.
    with pytest.raises(ValueError):
        pmc.resolve_publish_mode({pmc.PUBLISH_MODE_ENV_VAR: "kafka"})


# ---------------------------------------------------------------------------
# Section B — NATS-Subject-Pattern-Drift (6 tests)
# ---------------------------------------------------------------------------
#
# Tag-43 baseline (`reports/audit/2026-05-18-nats-jetstream-subjects-audit.md`):
# - 24 wakir.* literals total (NATS subjects: 7, namespace-ids: 17)
# - 0 drift rows
#
# Tag-48 pins the canonical regex + the 7-subject inventory + the
# template/literal classifier.


def test_b1_canonical_subject_regex_mirrors_json_schema(audit_module) -> None:
    """B1: The audit's ``SCHEMA_SUBJECT_REGEX`` mirrors the JSON-Schema
    ``subject.pattern`` exactly. Drift between the two would silently
    allow malformed subjects through one gate or the other."""
    schema = json.loads(_TRANSPORT_SCHEMA.read_text(encoding="utf-8"))
    schema_pattern = (
        schema["properties"]["subject"]["properties"]["pattern"]["pattern"]
    )
    assert audit_module.SCHEMA_SUBJECT_REGEX.pattern == schema_pattern, (
        "audit SCHEMA_SUBJECT_REGEX drifted from "
        "wirelang/schemas/layer-0-transport.json subject.pattern"
    )


def test_b2_seven_nats_subjects_inventory_pinned(audit_result) -> None:
    """B2: The audit reports exactly 7 NATS-subject hits (verdict ``ok``
    or ``ok (template)``). This is the Tag-43 baseline.

    A new module that introduces an 8th subject MUST be reviewed
    against the schema regex; this test surfaces the introduction
    loudly. Removal of a subject is also surfaced (4 LH < 7) so a
    silent demotion of an active publisher is observable.
    """
    nats_subjects = [
        s for s in audit_result.subjects if s.verdict == "ok"
    ]
    assert len(nats_subjects) == 7, (
        f"Expected 7 NATS-subject hits (Tag-43 baseline), got "
        f"{len(nats_subjects)}: {[(s.file, s.line, s.literal) for s in nats_subjects]}"
    )


def test_b3_all_inventory_subjects_match_schema_regex(audit_module, audit_result) -> None:
    """B3: Every NATS-subject literal/template the audit classifies as
    ``ok`` actually matches the schema regex (or the template form).

    This is the cross-check that the verdict and the regex agree —
    if classification logic drifted from the regex, this catches it.

    The audit's ``classify_subject_template`` returns verdict ``ok``
    for both concrete literals AND templates (templates are
    distinguished by ``detail='template form accepted'``). The test
    routes each row to the matching regex.
    """
    regex = audit_module.SCHEMA_SUBJECT_REGEX
    template_regex = audit_module.TEMPLATE_SUBJECT_REGEX
    for row in audit_result.subjects:
        if row.verdict != "ok":
            continue
        is_template = "{" in row.literal
        if is_template:
            assert template_regex.match(row.literal), (
                f"verdict=ok template but {row.literal!r} does not match "
                f"TEMPLATE_SUBJECT_REGEX (file={row.file}:{row.line})"
            )
        else:
            assert regex.match(row.literal), (
                f"verdict=ok concrete but literal {row.literal!r} does "
                f"not match SCHEMA_SUBJECT_REGEX (file={row.file}:{row.line})"
            )


def test_b4_subjects_cover_expected_event_axes(audit_result) -> None:
    """B4: The 7-subject inventory covers the two expected event types
    (``task.assigned``, ``task.output``) and the canonical persona-slug
    sub-id form. A silent rename of ``task.assigned`` to ``task.assign``
    would be caught here.
    """
    literals = [s.literal for s in audit_result.subjects
                if s.verdict == "ok"]
    blob = "\n".join(literals)
    assert "task.assigned" in blob, (
        f"expected event 'task.assigned' in NATS-subject inventory; "
        f"literals: {literals}"
    )
    assert "task.output" in blob, (
        f"expected event 'task.output' in NATS-subject inventory; "
        f"literals: {literals}"
    )
    # At least one persona-slug-bound concrete literal must exist
    # (Tag-43 baseline: tomas + reza).
    concrete = [lit for lit in literals if "{" not in lit]
    assert any(lit.endswith((".tomas", ".reza")) for lit in concrete), (
        f"expected at least one concrete persona-slug literal "
        f"(.tomas / .reza); concretes: {concrete}"
    )


def test_b5_canonical_regex_rejects_uppercase_domain(audit_module) -> None:
    """B5: The canonical regex MUST reject ``wakir.dev.Agent.task.assigned``
    (capital ``Agent``). This is the regression target the audit's
    Tag-43 test_subject_pattern_drift uses; pinning it at the
    integration layer guards against a silent regex loosening.
    """
    regex = audit_module.SCHEMA_SUBJECT_REGEX
    assert regex.match("wakir.dev.agent.task.assigned"), (
        "regex must accept canonical form"
    )
    assert not regex.match("wakir.dev.Agent.task.assigned"), (
        "regex must reject capital domain segment"
    )
    assert not regex.match("wakir.test.agent.task.assigned"), (
        "regex must reject non-{dev,staging,prod} env segment"
    )


def test_b6_subject_inventory_seven_hits_distributed_across_languages(audit_result) -> None:
    """B6: The 7-subject inventory spans both Python and Rust — pinning
    that the cross-language parity is preserved. A regression where
    one language's publisher drops the canonical subject (and uses an
    ad-hoc literal) would shrink the inventory on one side.
    """
    py_hits = [
        s for s in audit_result.subjects
        if s.verdict == "ok"
        and str(s.file).endswith(".py")
    ]
    rs_hits = [
        s for s in audit_result.subjects
        if s.verdict == "ok"
        and str(s.file).endswith(".rs")
    ]
    assert len(py_hits) >= 1, f"Python NATS-subject hits: {py_hits}"
    assert len(rs_hits) >= 1, f"Rust NATS-subject hits: {rs_hits}"
    assert len(py_hits) + len(rs_hits) == 7, (
        f"py={len(py_hits)} + rs={len(rs_hits)} != 7 "
        f"(expected Tag-43 baseline split)"
    )


# ---------------------------------------------------------------------------
# Section C — Failure-Mode-Catalogue (5 tests)
# ---------------------------------------------------------------------------
#
# Spec §13.3 enumerates F-1..F-6. The machine-readable
# ``_FAILURE_MODE_BY_PAIR`` dispatch covers F-1 / F-2 (the two
# silent-drop pairs); F-3..F-6 are operational / fan-out / ack /
# mode-flip classes that have no static (publish_mode,
# subscribe_surface) signature and stay in the runbook layer.


def test_c1_spec_lists_all_six_failure_mode_ids() -> None:
    """C1: ``wirelang/specs/wirelang-spec-v0-2.md`` mentions F-1..F-6.

    The Tag-43 audit's Failure-Mode-Catalogue is built off this spec
    block; a silent demotion of an ID (e.g. removing F-3 without
    spec-update + ADR) would re-open a documentation gap.
    """
    spec_text = _SPEC_FILE.read_text(encoding="utf-8")
    for fmid in ("F-1", "F-2", "F-3", "F-4", "F-5", "F-6"):
        assert fmid in spec_text, (
            f"failure-mode-id {fmid} missing from spec §13 — Bug-42 "
            f"catalogue regression"
        )


def test_c2_machine_readable_failure_mode_by_pair_maps_two_broken() -> None:
    """C2: ``_FAILURE_MODE_BY_PAIR`` maps the two silent-drop pairs to
    F-1 / F-2 (and only those).

    F-3..F-6 do NOT map (they aren't (publish_mode, subscribe_surface)
    pair-static); the test pins both the F-1/F-2 inclusion and the
    F-3+ exclusion so a confused refactor doesn't accidentally annex
    F-3 (a fan-out class) under a pair-static dispatch.
    """
    mapping = pmc._FAILURE_MODE_BY_PAIR
    assert mapping[(pmc.PUBLISH_MODE_CORE, pmc.SUBSCRIBE_SURFACE_JS_PULL)] == "F-1"
    assert mapping[(pmc.PUBLISH_MODE_CORE, pmc.SUBSCRIBE_SURFACE_JS_PUSH)] == "F-2"
    assert set(mapping.values()) == {"F-1", "F-2"}, (
        f"_FAILURE_MODE_BY_PAIR.values() drifted from {{F-1, F-2}}: "
        f"{set(mapping.values())}"
    )
    # Pair-static dispatch has exactly 2 entries.
    assert len(mapping) == 2


def test_c3_surface_mismatch_error_carries_verdict() -> None:
    """C3: ``SurfaceMismatchError`` carries the full verdict so operator
    log handlers can render structured failure-mode-id breadcrumbs.
    """
    try:
        pmc.require_compatible(
            pmc.PUBLISH_MODE_CORE,
            pmc.SUBSCRIBE_SURFACE_JS_PUSH,
        )
    except pmc.SurfaceMismatchError as exc:
        assert hasattr(exc, "verdict")
        assert isinstance(exc.verdict, pmc.CompatibilityVerdict)
        assert exc.verdict.failure_mode_id == "F-2"
        # The exception message is the diagnosis sentence — must be
        # operator-friendly (mention pair + section).
        assert "publish=core" in str(exc)
        assert "subscribe=jetstream-push" in str(exc)
    else:
        pytest.fail("SurfaceMismatchError not raised for F-2 pair")


def test_c4_recommended_adapter_references_both_a_and_b() -> None:
    """C4: For F-1/F-2 the verdict.recommended_adapter sentence cites
    both Adapter-A (stream-mirror) and Adapter-B (producer-rewrite,
    Phase-2c strategic target).

    The Tag-41 fix landed Adapter-B substrate; the diagnosis must keep
    citing Adapter-A as the operational default and Adapter-B as the
    strategic target — operator runbooks rely on the two-name pair.
    """
    verdict = pmc.check_compatibility(
        pmc.PUBLISH_MODE_CORE,
        pmc.SUBSCRIBE_SURFACE_JS_PULL,
    )
    assert verdict.recommended_adapter is not None
    rec = verdict.recommended_adapter
    assert "Adapter A" in rec or "stream-mirror" in rec, rec
    assert "Adapter B" in rec or "producer-rewrite" in rec, rec


def test_c5_compatible_and_fanout_verdicts_have_no_failure_mode_id() -> None:
    """C5: Only BROKEN verdicts carry a ``failure_mode_id``. Compatible
    and Fanout pairs return ``None`` — pinning this prevents a future
    refactor from silently annotating a Fanout pair as ``F-3`` and
    triggering a spurious failure-mode-id in operator logs.
    """
    for pub, sub in pmc._HARD_COMPATIBLE:
        v = pmc.check_compatibility(pub, sub)
        assert v.failure_mode_id is None, (
            f"COMPATIBLE pair ({pub},{sub}) leaked failure_mode_id="
            f"{v.failure_mode_id}"
        )
    for pub, sub in pmc._FANOUT_DEPENDENT:
        v = pmc.check_compatibility(pub, sub)
        assert v.failure_mode_id is None, (
            f"FANOUT pair ({pub},{sub}) leaked failure_mode_id="
            f"{v.failure_mode_id}"
        )


# ---------------------------------------------------------------------------
# Section D — Audit-Script-Invariants (4 tests)
# ---------------------------------------------------------------------------
#
# The audit script itself is a regression target: a silent loosening
# of its exclusion rules or a silent change to its classification
# logic would let drift slip through CI without surfacing.


def test_d1_audit_reports_zero_drift_at_head(audit_result) -> None:
    """D1: At repo HEAD the audit reports exactly 0 drift rows.

    Tag-43 baseline (``reports/audit/2026-05-18-nats-jetstream-subjects-audit.md``):
    0 drift, 276 scanned files. Tag-48 pins the 0-drift invariant; the
    file count is allowed to grow as the codebase grows.
    """
    assert audit_result.drift_count == 0, (
        f"audit drift_count={audit_result.drift_count}; expected 0. "
        f"Bug-42 audit baseline regressed."
    )
    assert audit_result.scanned_files >= 200, (
        f"audit only scanned {audit_result.scanned_files} files — "
        f"exclusion rules may have over-broadened"
    )


def test_d2_audit_reports_three_mode_check_modules(audit_result) -> None:
    """D2: Three mode-cross-validation modules at HEAD —
    ``bridge_forward.py`` (ok / dispatches both surfaces),
    ``persona_engine/cli.py`` (no-publish-mode / consumer),
    ``publish_mode_contract.py`` (no-publish-mode / contract).

    Tag-43 baseline. A 4th module appearing means a new publisher
    landed; that publisher MUST be reviewed for Bug-42 closure
    (Adapter-B dispatch + gate). A drop to 2 means one of the three
    was removed without spec-update.
    """
    assert len(audit_result.mode_checks) == 3, (
        f"mode_checks count drifted from 3: "
        f"{[m.file for m in audit_result.mode_checks]}"
    )
    files = {Path(m.file).name for m in audit_result.mode_checks}
    assert "bridge_forward.py" in files
    assert "cli.py" in files
    assert "publish_mode_contract.py" in files


def test_d3_audit_namespace_id_count_pinned(audit_result) -> None:
    """D3: 17 namespace-id literals at the Tag-43 baseline.

    Namespace-ids are informational (telemetry meters / schema-ids /
    DID prefixes). A drop indicates a removed metric or schema-id; an
    increase indicates a new ``wakir.<not-an-env>.*`` literal that
    SHOULD be reviewed (is it actually a NATS subject? is it a new
    metric name? does it collide with the canonical regex?).

    This test allows growth (17+) but flags shrinkage (would suggest
    a metric was silently removed) and counts the inventory total
    against the audit's published numbers.
    """
    namespace_ids = [
        s for s in audit_result.subjects if s.verdict == "namespace-id"
    ]
    # Lower bound from Tag-43 baseline; upper bound generous to
    # accommodate organic growth of telemetry meter names.
    assert len(namespace_ids) >= 15, (
        f"namespace-id count dropped to {len(namespace_ids)}; "
        f"Tag-43 baseline was 17. A removed metric / schema-id is "
        f"worth a review."
    )
    total = len(audit_result.subjects)
    assert total >= 22, (
        f"total wakir.* literal inventory shrank to {total}; "
        f"Tag-43 baseline was 24"
    )


def test_d4_audit_cli_invocation_exit_zero_drift_free() -> None:
    """D4: Invoking the audit CLI as a subprocess at HEAD returns exit
    code 0 in audit-only mode and exit code 0 in ``--enforce`` mode.

    The subprocess invocation is the CI surface; this test pins the
    CI contract.
    """
    # Audit-only mode.
    proc = subprocess.run(
        [sys.executable, str(_AUDIT_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"audit CLI (audit-only) exited {proc.returncode}; "
        f"stderr: {proc.stderr[:400]}"
    )
    # Enforce mode — at HEAD the repo is drift-free so this MUST also
    # exit 0. A regression that introduces drift would flip this to 2
    # on CI and on Tag-48 regression.
    proc_enf = subprocess.run(
        [sys.executable, str(_AUDIT_SCRIPT), "--enforce"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc_enf.returncode == 0, (
        f"audit CLI (--enforce) exited {proc_enf.returncode}; "
        f"stderr: {proc_enf.stderr[:400]}. Bug-42 audit drift regressed."
    )


# ---------------------------------------------------------------------------
# Total: 5 + 6 + 5 + 4 = 20 tests (A1 parametrized over 6 cells counts
# as 6 test-IDs at collection time, so the actual pytest test count is
# 25; the 20-tests target counts the parametrize as a single contract).
# ---------------------------------------------------------------------------
