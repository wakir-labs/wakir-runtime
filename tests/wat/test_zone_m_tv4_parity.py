# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Zone-M TV-4 cross-component test-vector parity tests.

This test-suite is the QA-owned counterpart to
``tests/wat/test_external_verifier_parity.py``. Where the existing
parity tests pin the v1 schema-file against the 31-vector synthetic
conformance set owned by ``dev-engineering`` (Sprint-3 Tag-1 +
Sprint-6 Tag-1), this suite pins the **Zone-M cross-component
boundaries** that bind:

- WAT (``dev-engineering``) x Wirelang.identity.aip_signing
  (``reza``) -- the optional ``signature`` slot shape pin
  introduced by Sprint-5 Tag-1 (schema 0.2.0).
- WAT (``dev-engineering``) x Pengine capability-token producer
  (``pengine``) -- the ``capability_token_hash`` field-shape per
  event.
- WAT (``dev-engineering``) x Wirelang schema-version-enum
  (``reza``) -- the forward-compat reservation that the v1
  schema-file also accepts ``wakir-wat-manifest/v2`` as a
  ``version`` string (carrying v1-shape leaves).

The vector file lives under ``tests/fixtures/zone-m-tv4/`` (QA-owned
fixture path) rather than under
``tooling/external-verifier-ajv/test-vectors.json`` (Tomas-owned
substrate). This separation keeps the dev-engineering 31-vector
contract intact and gives QA an independent file to evolve as new
cross-component boundaries land in later sprints.

The parity check itself reuses the driver functions from
``scripts/external_verifier_validation.py`` so that the same three
reference validators (python-jsonschema, ajv, fastjsonschema) walk the
TV-4 vectors and must reach the same verdict on each. Skip conditions
mirror the Tomas suite (node + node_modules; fastjsonschema importable).

Sprint-6 Tag-2 closeout follow-up: Welle-27 QA box.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "external_verifier_validation.py"
AJV_TOOL_DIR = REPO_ROOT / "tooling" / "external-verifier-ajv"
TV4_VECTORS = (
    REPO_ROOT / "tests" / "fixtures" / "zone-m-tv4" / "zone-m-tv4-vectors.json"
)


def _import_validation_script():
    """Load the driver module without polluting ``sys.modules`` permanently."""
    spec = importlib.util.spec_from_file_location(
        "external_verifier_validation_script_zone_m", SCRIPT_PATH
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


# ---------------------------------------------------------------------------
# Vector-file shape pins (always run)
# ---------------------------------------------------------------------------


def test_tv4_vectors_file_present_and_well_formed():
    """Fail fast if the TV-4 vectors file disappears or is malformed."""
    assert TV4_VECTORS.exists(), f"TV-4 vectors file missing: {TV4_VECTORS}"
    vectors = json.loads(TV4_VECTORS.read_text(encoding="utf-8"))
    assert isinstance(vectors, list), "TV-4 vectors must be a JSON array"
    assert len(vectors) >= 6, (
        f"TV-4 vector count {len(vectors)} below Zone-M-coverage floor of 6 "
        "(box-task floor; raise on intentional expansion)"
    )
    for v in vectors:
        assert "name" in v, f"vector missing 'name': {v!r}"
        assert "expect" in v, f"vector {v.get('name')!r} missing 'expect'"
        assert v["expect"] in ("accept", "reject"), (
            f"vector {v['name']!r} expect must be 'accept' or 'reject'"
        )
        assert "manifest" in v, f"vector {v['name']!r} missing 'manifest'"
        assert "zone_m_axis" in v, (
            f"vector {v['name']!r} missing 'zone_m_axis' field "
            "(Zone-M cross-component-boundary annotation is mandatory)"
        )
        assert "boundary" in v, (
            f"vector {v['name']!r} missing 'boundary' field "
            "(human-readable boundary description is mandatory)"
        )


def test_tv4_vectors_cover_signature_slot_boundary():
    """At least one accept and three reject vectors must touch the signature slot.

    Pins the Sprint-5 Tag-1 / Sprint-6 Tag-1 signature slot as the
    primary Zone-M boundary surface. If a refactor accidentally drops
    all signature-slot vectors, this test catches it before the parity
    sweep silently degrades coverage.
    """
    vectors = json.loads(TV4_VECTORS.read_text(encoding="utf-8"))
    sig_accept = [
        v for v in vectors
        if v["expect"] == "accept" and "signature" in v["manifest"]
    ]
    sig_reject = [
        v for v in vectors
        if v["expect"] == "reject" and "signature" in v["manifest"]
    ]
    assert len(sig_accept) >= 1, (
        "Zone-M floor: at least one accept-vector must carry a signature "
        f"slot (got {len(sig_accept)})"
    )
    assert len(sig_reject) >= 3, (
        "Zone-M floor: at least three reject-vectors must touch the "
        f"signature slot (got {len(sig_reject)})"
    )


def test_tv4_vectors_cover_multi_capref_event():
    """At least one accept vector with two distinct capability_token_hash values.

    Pins the WAT x Pengine boundary: the v1 schema accepts events
    carrying distinct caprefs per event (a Pengine multi-token
    issuance pattern).
    """
    vectors = json.loads(TV4_VECTORS.read_text(encoding="utf-8"))
    multi_capref = []
    for v in vectors:
        if v["expect"] != "accept":
            continue
        events = v["manifest"].get("events", [])
        caprefs = {e.get("capability_token_hash") for e in events}
        if len(events) >= 2 and len(caprefs) >= 2:
            multi_capref.append(v)
    assert multi_capref, (
        "Zone-M floor: at least one accept-vector with >=2 events and "
        ">=2 distinct capability_token_hash values must be present"
    )


# ---------------------------------------------------------------------------
# Python-side parity (always runs)
# ---------------------------------------------------------------------------


def test_tv4_python_jsonschema_parity():
    """python-jsonschema verdict matches every TV-4 vector's ``expect``."""
    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(TV4_VECTORS.read_text(encoding="utf-8"))

    report = mod.run_python_validator(schema, vectors)
    mismatches = [r for r in report["results"] if not r["matched"]]
    assert not mismatches, (
        f"python-jsonschema disagreed on {len(mismatches)} TV-4 vectors: "
        + ", ".join(r["name"] for r in mismatches)
    )
    assert report["total"] == len(vectors)
    assert report["matched"] == len(vectors)


@pytest.mark.skipif(
    not _fastjsonschema_available(),
    reason="fastjsonschema not installed (Tomas-suite skip-mirror posture)",
)
def test_tv4_fastjsonschema_parity():
    """fastjsonschema verdict matches every TV-4 vector's ``expect``."""
    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(TV4_VECTORS.read_text(encoding="utf-8"))

    report = mod.run_fastjsonschema_validator(schema, vectors)
    assert report is not None
    mismatches = [r for r in report["results"] if not r["matched"]]
    assert not mismatches, (
        f"fastjsonschema disagreed on {len(mismatches)} TV-4 vectors: "
        + ", ".join(r["name"] for r in mismatches)
    )


@pytest.mark.skipif(
    not _fastjsonschema_available(),
    reason="fastjsonschema not installed (Tomas-suite skip-mirror posture)",
)
def test_tv4_python_and_fastjsonschema_agree_per_vector():
    """Per-vector verdict agreement between python-jsonschema and fastjsonschema."""
    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(TV4_VECTORS.read_text(encoding="utf-8"))

    py_report = mod.run_python_validator(schema, vectors)
    fjs_report = mod.run_fastjsonschema_validator(schema, vectors)
    assert fjs_report is not None

    py_by_name = {r["name"]: r["verdict"] for r in py_report["results"]}
    fjs_by_name = {r["name"]: r["verdict"] for r in fjs_report["results"]}

    disagreement = [
        name for name in py_by_name
        if py_by_name[name] != fjs_by_name.get(name)
    ]
    assert not disagreement, (
        "TV-4 python-vs-fastjsonschema disagreement on: "
        + ", ".join(disagreement)
    )


# ---------------------------------------------------------------------------
# Node-side parity (skipped when node / node_modules unavailable)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _node_available(),
    reason="node or node_modules unavailable (run npm install in tooling/external-verifier-ajv)",
)
def test_tv4_node_ajv_parity():
    """ajv verdict matches every TV-4 vector's ``expect``."""
    mod = _import_validation_script()
    report = mod.run_node_validator(TV4_VECTORS)
    assert report is not None, "node validator returned None despite availability"
    mismatches = [r for r in report["results"] if not r["matched"]]
    assert not mismatches, (
        f"ajv disagreed on {len(mismatches)} TV-4 vectors: "
        + ", ".join(r["name"] for r in mismatches)
    )


@pytest.mark.skipif(
    not (_node_available() and _fastjsonschema_available()),
    reason="three-way parity needs node + fastjsonschema",
)
def test_tv4_three_way_parity():
    """All three reference validators agree per TV-4 vector."""
    mod = _import_validation_script()
    schema = json.loads(mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    vectors = json.loads(TV4_VECTORS.read_text(encoding="utf-8"))

    py_report = mod.run_python_validator(schema, vectors)
    fjs_report = mod.run_fastjsonschema_validator(schema, vectors)
    node_report = mod.run_node_validator(TV4_VECTORS)
    assert fjs_report is not None
    assert node_report is not None

    py = {r["name"]: r["verdict"] for r in py_report["results"]}
    fjs = {r["name"]: r["verdict"] for r in fjs_report["results"]}
    nd = {r["name"]: r["verdict"] for r in node_report["results"]}

    disagreements = []
    for name in py:
        if not (py[name] == fjs.get(name) == nd.get(name)):
            disagreements.append(
                f"{name}: py={py[name]} fjs={fjs.get(name)} ajv={nd.get(name)}"
            )
    assert not disagreements, (
        "TV-4 three-way disagreement:\n  " + "\n  ".join(disagreements)
    )
