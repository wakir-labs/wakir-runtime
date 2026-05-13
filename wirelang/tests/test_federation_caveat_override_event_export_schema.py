# SPDX-License-Identifier: Apache-2.0
"""Tests for the OTS-anchored caveat-override-event-export
schema-registry entry (Phase-2 Sprint-9 Tag-2).

This test module verifies the **Teil B** substance of Sprint-9
Tag-2: the JSON-Schema-Registry entry
``wakir.federation.caveat-override-event-export/1`` and its
OTS-anchor pre-submission manifest. Tests:

- T-COXSR-01: schema file parses as JSON Schema (Draft 2020-12);
  envelopes produced by the Sprint-9 Tag-1
  :class:`~wirelang.federation.caveat_override_export.ExportedCaveatOverrideEvent`
  pseudonymisation pipeline validate against it.
- T-COXSR-02: defence-in-depth — envelopes carrying raw narrative
  fields (override_reason / original_caveat_set / narrowed_caveat_set)
  FAIL schema validation. This is a wire-level boundary check;
  the runtime
  :class:`~wirelang.federation.caveat_override_export.CaveatOverrideExportRawNarrativeLeakError`
  gate is defence-in-depth one layer up.
- T-COXSR-03: anchor-manifest fixture is well-formed and
  cross-references the live schema digest byte-for-byte.
- T-COXSR-04: schema-digest fixture (schema.sha256.bin) round-trips
  with a live recompute of sha256(schema-file-bytes).
- T-COXSR-05: cross-reference contract — the anchor-manifest's
  cross-reference paths point at files that exist in the
  repository tree.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "wirelang"
    / "schemas"
    / "caveat-override-event-export.json"
)
FIXTURE_DIR = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "schema-registry"
    / "caveat-override-event-export-v1"
)
ANCHOR_MANIFEST_PATH = FIXTURE_DIR / "anchor-manifest.json"
SCHEMA_DIGEST_PATH = FIXTURE_DIR / "schema.sha256.bin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_schema() -> dict:
    with open(SCHEMA_PATH, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def _load_manifest() -> dict:
    with open(ANCHOR_MANIFEST_PATH, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def _well_formed_envelope() -> dict:
    """A pseudonymised envelope that MUST validate against the
    schema. Mirrors the Sprint-9 Tag-1 exporter output shape.
    """
    return {
        "schema": "wakir.federation.caveat-override-event-export/1",
        "route_id": "route-x",
        "sequence_number": 1,
        "event_at": "2026-05-13T09:00:00Z",
        "exported_at": "2026-05-13T09:00:05Z",
        "override_event_id": "a" * 64,
        "original_caveat_chain_hash": "b" * 64,
        "narrowed_caveat_chain_hash": "c" * 64,
        "narrowing_class": "SUBSET_PROPER",
        "reason_class": "POLICY_TIGHTENING",
        "override_reason_hash": "d" * 64,
        "cross_org_witnesses": [
            {
                "peer_org": "org-b",
                "peer_trust_domain": "wakir.dev",
                "observed_at": "2026-05-13T09:00:02Z",
            }
        ],
        "audit_trace": [
            {
                "wat_anchor_manifest_id": "manifest-2026-05-13T09",
                "event_kind": "CAVEAT_OVERRIDE",
                "event_at": "2026-05-13T09:00:01Z",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_coxsr_01_schema_validates_well_formed_envelope() -> None:
    """T-COXSR-01: the schema file parses as JSON Schema and a
    well-formed envelope (mirroring the Sprint-9 Tag-1 exporter
    output shape) validates against it.
    """
    schema = _load_schema()
    # Schema must declare $id and $schema; basic sanity.
    assert (
        schema["$id"]
        == "https://wakir.dev/wirelang/schema/caveat-override-event-export/1"
    )
    assert schema["$schema"].startswith("https://json-schema.org/")
    # Validator construction confirms the schema itself is valid.
    validator = jsonschema.Draft202012Validator(schema)
    validator.check_schema(schema)
    # Well-formed envelope passes.
    validator.validate(_well_formed_envelope())


def test_coxsr_02_raw_narrative_fields_rejected_by_schema() -> None:
    """T-COXSR-02: an envelope carrying any of the three raw
    narrative fields FAILS schema validation. This is the
    wire-level defence-in-depth boundary against accidental
    cross-org narrative leak.
    """
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    for forbidden_field, forbidden_value in (
        ("override_reason", "OPERATOR FREE-FORM NARRATIVE"),
        (
            "original_caveat_set",
            [["predicate-a", ["arg-1"]]],
        ),
        (
            "narrowed_caveat_set",
            [["predicate-b", ["arg-2"]]],
        ),
    ):
        envelope = _well_formed_envelope()
        envelope[forbidden_field] = forbidden_value
        errors = list(validator.iter_errors(envelope))
        assert errors, (
            f"schema must reject {forbidden_field!r} at the wire "
            f"boundary; got no errors"
        )


def test_coxsr_03_anchor_manifest_well_formed() -> None:
    """T-COXSR-03: the OTS-anchor manifest fixture is well-formed
    and cross-references the live schema digest byte-for-byte.
    """
    manifest = _load_manifest()
    assert (
        manifest["schema_registry_id"]
        == "wakir.federation.caveat-override-event-export/1"
    )
    # schema_file_sha256 must match a recompute of the live schema
    # file (i.e. the manifest is not stale).
    with open(SCHEMA_PATH, "rb") as fh:
        live_digest = hashlib.sha256(fh.read()).hexdigest()
    assert manifest["schema_file_sha256"] == live_digest, (
        f"anchor manifest schema_file_sha256={manifest['schema_file_sha256']} "
        f"does not match live recompute={live_digest}; manifest is stale"
    )
    # Bytes count must also match.
    assert manifest["schema_file_bytes"] == SCHEMA_PATH.stat().st_size
    # State machine sanity.
    assert manifest["anchor_state"] in (
        "PRE_SUBMISSION",
        "PENDING",
        "FINALISED",
    )
    assert manifest["anchor_kind"] == "wakir.schema-registry.ots-anchor/1"
    assert manifest["anchor_digest_algorithm"] == "sha256"
    # Verifier contract is non-empty.
    assert isinstance(manifest["verifier_contract"], list)
    assert len(manifest["verifier_contract"]) >= 3


def test_coxsr_04_schema_digest_fixture_round_trips() -> None:
    """T-COXSR-04: the schema-digest fixture (schema.sha256.bin)
    is byte-for-byte equal to sha256(schema-file-bytes), and the
    anchor-manifest hex spelling matches the binary digest hex.
    """
    with open(SCHEMA_PATH, "rb") as fh:
        live_digest = hashlib.sha256(fh.read()).digest()
    assert SCHEMA_DIGEST_PATH.exists(), (
        f"schema-digest fixture missing: {SCHEMA_DIGEST_PATH}"
    )
    with open(SCHEMA_DIGEST_PATH, "rb") as fh:
        on_disk = fh.read()
    assert on_disk == live_digest, (
        "schema.sha256.bin fixture is stale; re-derive from the "
        "live schema file"
    )
    assert len(on_disk) == 32
    manifest = _load_manifest()
    assert manifest["schema_file_sha256"] == live_digest.hex()


def test_coxsr_05_cross_reference_paths_exist() -> None:
    """T-COXSR-05: the cross-reference paths declared in the
    anchor-manifest point at files that exist in the repository
    tree. (Spec / module / tests cross-link integrity.)
    """
    manifest = _load_manifest()
    cross_ref = manifest["cross_reference"]
    # Module + tests cross-reference paths must exist on disk.
    module_path = REPO_ROOT / cross_ref["module"]
    assert module_path.exists(), f"module path missing: {module_path}"
    tests_path = REPO_ROOT / cross_ref["tests"]
    assert tests_path.exists(), f"tests path missing: {tests_path}"
    # The spec section path is a section reference inside the spec
    # file; just verify the spec file itself exists.
    spec_section = cross_ref["spec_section"]
    spec_file = spec_section.split(" ")[0]
    spec_path = REPO_ROOT / spec_file
    assert spec_path.exists(), f"spec path missing: {spec_path}"
