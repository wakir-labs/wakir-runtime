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
