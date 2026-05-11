# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-tool parity tests for the wakir-wat-manifest-v1 JSON-Schema.

This test wires the external-verifier validation script
(``scripts/external_verifier_validation.py``) into the pytest harness.
The script runs every test-vector through Python's ``jsonschema`` and
Node.js's ``ajv`` validator and asserts both reach the same verdict.

Skip conditions
---------------

The Node.js side is skipped (not failed) when:

- ``node`` is not on PATH, or
- ``tooling/external-verifier-ajv/node_modules`` does not exist (i.e.
  no one has run ``npm install`` in that directory yet).

Skipping rather than failing matches Sprint-3's posture: the
parity-check is **substrate** that external implementers can reach
for, not a CI gate. Once the Node.js side is wired into a CI job (a
follow-up Open-Item), the test gets ``--require-node`` semantics. For
now developers without Node still see the Python-side validation in
``tests/wat/test_manifest_v1_schema_smoke.py``.

Inline-imports the parity logic from the script rather than shelling
out to it; that way pytest collection is fast and per-vector failure
attribution lands on the right test name.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "external_verifier_validation.py"
AJV_TOOL_DIR = REPO_ROOT / "tooling" / "external-verifier-ajv"
DEFAULT_VECTORS = AJV_TOOL_DIR / "test-vectors.json"


def _import_validation_script():
    """Load the script as a module without polluting sys.modules permanently."""
    spec = importlib.util.spec_from_file_location(
        "external_verifier_validation_script", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot load script from {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _node_available() -> bool:
    if shutil.which("node") is None:
        return False
    if not (AJV_TOOL_DIR / "node_modules").exists():
        return False
    return True


def _fastjsonschema_available() -> bool:
    try:
        import fastjsonschema  # noqa: F401
    except ImportError:
        return False
    return True


# ===========================================================================
# Python-side parity (always runs)
# ===========================================================================


def test_python_validator_accepts_every_expected_accept():
    """Python ``jsonschema`` validator agrees with every ``expect=accept`` vector."""
    import json

    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(DEFAULT_VECTORS.read_text(encoding="utf-8"))

    report = mod.run_python_validator(schema, vectors)
    mismatches = [r for r in report["results"] if not r["matched"]]
    assert not mismatches, (
        f"python validator disagreed on {len(mismatches)} vectors: "
        + ", ".join(r["name"] for r in mismatches)
    )


def test_python_validator_total_count_matches_vectors():
    """Sanity: report total equals the test-vector array length.

    Catches an accidental vector-file edit that drops or duplicates an
    entry without updating the in-test expectation.
    """
    import json

    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(DEFAULT_VECTORS.read_text(encoding="utf-8"))

    report = mod.run_python_validator(schema, vectors)
    assert report["total"] == len(vectors)


# ===========================================================================
# Node.js-side parity (skipped if node unavailable)
# ===========================================================================


@pytest.mark.skipif(
    not _node_available(),
    reason=(
        "node and/or ajv node_modules unavailable; install via "
        "`cd tooling/external-verifier-ajv && npm install`"
    ),
)
def test_node_ajv_validator_accepts_every_expected_accept():
    """Node.js ``ajv`` validator agrees with every ``expect=accept`` vector."""
    mod = _import_validation_script()
    report = mod.run_node_validator(DEFAULT_VECTORS)
    assert report is not None, "node validator returned None despite gating"
    mismatches = [r for r in report["results"] if not r["matched"]]
    assert not mismatches, (
        f"ajv validator disagreed on {len(mismatches)} vectors: "
        + ", ".join(r["name"] for r in mismatches)
    )


@pytest.mark.skipif(
    not _node_available(),
    reason=(
        "node and/or ajv node_modules unavailable; install via "
        "`cd tooling/external-verifier-ajv && npm install`"
    ),
)
def test_python_and_node_verdicts_agree_per_vector():
    """Per-vector parity: python and node reach the same accept/reject verdict.

    The actual cross-tool-correctness contract. If python says accept
    and node says reject (or vice versa) on the *same* manifest under
    the *same* schema, the schema is ambiguous between implementations
    and the schema-correctness conversation needs to happen before the
    schema lands in any third-party hands.
    """
    import json

    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(DEFAULT_VECTORS.read_text(encoding="utf-8"))

    py_report = mod.run_python_validator(schema, vectors)
    node_report = mod.run_node_validator(DEFAULT_VECTORS)
    assert node_report is not None

    parity_ok, diffs = mod.compare_reports(py_report, node_report)
    assert parity_ok, "cross-tool parity violation:\n  " + "\n  ".join(diffs)


@pytest.mark.skipif(
    not _node_available(),
    reason="node and/or ajv node_modules unavailable",
)
def test_node_report_schema_id_matches_python():
    """Both validators report the same ``$id`` on the schema they loaded.

    Catches a misconfigured ``--schema`` flag in the Node.js wrapper
    (e.g. if a future PR moves the schema file but forgets to update
    the relative path in validate.js).
    """
    import json

    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(DEFAULT_VECTORS.read_text(encoding="utf-8"))

    py_report = mod.run_python_validator(schema, vectors)
    node_report = mod.run_node_validator(DEFAULT_VECTORS)
    assert node_report is not None

    assert py_report["schema_id"] == node_report["schema_id"], (
        f"schema $id drift between python ({py_report['schema_id']!r}) "
        f"and node ({node_report['schema_id']!r})"
    )


# ===========================================================================
# fastjsonschema third-pole parity (Sprint-6 Tag-1)
# ===========================================================================


@pytest.mark.skipif(
    not _fastjsonschema_available(),
    reason="fastjsonschema not installed; install via `pip install fastjsonschema`",
)
def test_fastjsonschema_validator_accepts_every_expected_accept():
    """fastjsonschema validator agrees with every declared expectation.

    fastjsonschema is the third Draft-2020-12 implementation in the
    parity set (alongside python-jsonschema and ajv). It compiles the
    schema to native Python code via a different code path than
    python-jsonschema's interpreter, so an implementation bug in one
    library that only ``jsonschema``+``ajv`` would not catch becomes
    visible here.
    """
    import json

    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(DEFAULT_VECTORS.read_text(encoding="utf-8"))

    report = mod.run_fastjsonschema_validator(schema, vectors)
    assert report is not None, "fastjsonschema validator returned None despite gating"
    mismatches = [r for r in report["results"] if not r["matched"]]
    assert not mismatches, (
        f"fastjsonschema validator disagreed on {len(mismatches)} vectors: "
        + ", ".join(r["name"] for r in mismatches)
    )


@pytest.mark.skipif(
    not _fastjsonschema_available(),
    reason="fastjsonschema not installed",
)
def test_python_and_fastjsonschema_verdicts_agree_per_vector():
    """Per-vector parity between python-jsonschema and fastjsonschema.

    Pure Python-side triangulation: both libraries claim Draft-2020-12
    compatibility but disagree on some corner cases historically. If
    parity holds here, schema-correctness has at least two independent
    Python-side witnesses, which is a meaningful adoption signal for
    external Python implementers picking either library.
    """
    import json

    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(DEFAULT_VECTORS.read_text(encoding="utf-8"))

    py_report = mod.run_python_validator(schema, vectors)
    fjs_report = mod.run_fastjsonschema_validator(schema, vectors)
    assert fjs_report is not None

    parity_ok, diffs = mod.compare_reports_multi([py_report, fjs_report])
    assert parity_ok, "python-vs-fastjsonschema parity violation:\n  " + "\n  ".join(diffs)


@pytest.mark.skipif(
    not (_node_available() and _fastjsonschema_available()),
    reason="full three-validator parity requires node + ajv + fastjsonschema",
)
def test_three_way_parity_python_node_fastjsonschema():
    """Full three-way parity check: python-jsonschema, ajv, fastjsonschema.

    This is the Sprint-6 substrate for external-verifier adoption: any
    third party picking one of the three libraries inherits a verdict-
    set that two other independent implementations agree with.
    """
    import json

    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(DEFAULT_VECTORS.read_text(encoding="utf-8"))

    py_report = mod.run_python_validator(schema, vectors)
    node_report = mod.run_node_validator(DEFAULT_VECTORS)
    fjs_report = mod.run_fastjsonschema_validator(schema, vectors)
    assert py_report is not None
    assert node_report is not None
    assert fjs_report is not None

    parity_ok, diffs = mod.compare_reports_multi(
        [py_report, node_report, fjs_report]
    )
    assert parity_ok, (
        "three-way parity violation:\n  " + "\n  ".join(diffs)
    )


def test_compare_reports_multi_handles_missing_validator():
    """compare_reports_multi gracefully handles a single-validator input.

    The N-way helper should report parity_ok=True with a single
    informational diff when only one validator participates (the
    degenerate case where node+fastjsonschema are both skipped).
    """
    mod = _import_validation_script()
    parity_ok, diffs = mod.compare_reports_multi(
        [
            {
                "tool": "python-jsonschema",
                "results": [
                    {"name": "v1-minimal", "verdict": "accept"},
                ],
            }
        ]
    )
    assert parity_ok is True
    assert any("fewer than 2 validators" in d for d in diffs)


def test_compare_reports_multi_detects_disagreement():
    """compare_reports_multi flags a verdict mismatch across validators."""
    mod = _import_validation_script()
    parity_ok, diffs = mod.compare_reports_multi(
        [
            {
                "tool": "python-jsonschema",
                "results": [{"name": "vec-a", "verdict": "accept"}],
            },
            {
                "tool": "python-fastjsonschema",
                "results": [{"name": "vec-a", "verdict": "reject"}],
            },
        ]
    )
    assert parity_ok is False
    assert any("vec-a" in d and "parity violation" in d for d in diffs)
