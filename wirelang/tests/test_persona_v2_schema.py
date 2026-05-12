# SPDX-License-Identifier: Apache-2.0
"""persona-v2 (V10) schema validation tests (Phase-1b Sprint-3 Tag-2).

Coverage map
------------

The schema-file ``wirelang/schemas/persona-v2.json`` is authored from
``wirelang/specs/persona-schema-v10-migration-vorbereitung.md`` §2
(Sprint-3 Tag-1 sketch). These tests pin the field-spec at JSON-Schema
level and lock the additive-only Default-Lock A-2 contract:

1. **Positive** — minimal v2 input (v1-shape with schema_version lifted)
   validates.
2. **Positive** — full v2 input (every additive top-level + nested
   identity_pinned field present) validates.
3. **Positive** — reserved-fields-present-but-empty validates (Sprint-3
   Tag-1 §2.1.3 reservation discipline).
4. **Negative** — schema_version != "persona-v2" rejected (the const
   discriminator that distinguishes v2 from v1).
5. **Negative** — unknown additionalProperty at top-level rejected
   (additionalProperties:false enforces the reserved-list boundary).
6. **Negative** — unknown additionalProperty inside identity_pinned
   rejected (additive fields are explicit; no general escape hatch).

The Sprint-3 Tag-N implementation box adds the Cross-Version-Roundtrip
test pack (~16 tests, 4 classes, per Sprint-3 Tag-1 sketch §4); this
file covers schema-conformance only.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "persona-v2.json"
)


@pytest.fixture(scope="module")
def schema_validator() -> jsonschema.Draft202012Validator:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _minimal_v2_doc() -> dict:
    """Minimal valid persona-v2 doc: v1 required-set with v2 schema_version."""
    return {
        "name": "pengine",
        "description": "Persona-engine engineer (test fixture).",
        "tools": ["Read", "Bash"],
        "schema_version": "persona-v2",
        "identity_pinned": {
            "cross_review_zones": [
                {
                    "zone": "K",
                    "partner": "wat-eng-slot",
                    "trigger": "v-907 implementation",
                }
            ],
            "authority": {
                "push_remote": False,
                "budget_cap_eur_per_month": 10,
                "sub_delegation": False,
            },
            "hierarchy": {
                "reports_to": "ceo-slot",
                "escalation": "ceo-slot",
            },
        },
    }


# ---------------------------------------------------------------------------
# Positive tests
# ---------------------------------------------------------------------------


def test_v2_minimal_doc_validates(
    schema_validator: jsonschema.Draft202012Validator,
) -> None:
    """A v2 doc with only v1-required fields and schema_version=persona-v2
    validates. This is the lifted-v9-input shape per V1ToV2Step (§3)."""
    doc = _minimal_v2_doc()
    errors = list(schema_validator.iter_errors(doc))
    assert errors == [], f"unexpected errors: {[e.message for e in errors]}"


def test_v2_full_additive_doc_validates(
    schema_validator: jsonschema.Draft202012Validator,
) -> None:
    """A v2 doc that exercises every additive field (top-level + nested)
    validates. Locks §2.1.1 + §2.1.2 of the Sprint-3 Tag-1 sketch."""
    doc = _minimal_v2_doc()
    doc["model_pin"] = {"family": "claude", "version": "opus-4-7"}
    doc["spawn_constraints"] = {"max_concurrent": 1}
    doc["identity_pinned"]["identity_doc_ref"] = (
        "https://wakir.dev/identity/pengine/v1"
    )
    doc["identity_pinned"]["persona_owner_role"] = "hr-slot"
    doc["identity_pinned"]["governance_revision"] = 1
    errors = list(schema_validator.iter_errors(doc))
    assert errors == [], f"unexpected errors: {[e.message for e in errors]}"


def test_v2_reserved_fields_present_but_empty_validates(
    schema_validator: jsonschema.Draft202012Validator,
) -> None:
    """Reserved fields (recovery_drill, wat_bridge_overrides,
    container_bridge_spec) carry no semantics yet but the schema admits
    them so that a future reader does not parse-fail. Locks §2.1.3."""
    doc = _minimal_v2_doc()
    doc["recovery_drill"] = {}
    doc["wat_bridge_overrides"] = {}
    doc["container_bridge_spec"] = {}
    errors = list(schema_validator.iter_errors(doc))
    assert errors == [], f"unexpected errors: {[e.message for e in errors]}"


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------


def test_v2_rejects_wrong_schema_version_const(
    schema_validator: jsonschema.Draft202012Validator,
) -> None:
    """schema_version is a const "persona-v2"; v1 inputs (or anything
    else) are rejected by this validator. The const is the discriminator
    that lets a multiplexer route a doc to the right schema."""
    doc = _minimal_v2_doc()
    doc["schema_version"] = "persona-v1"
    errors = list(schema_validator.iter_errors(doc))
    assert errors, "expected schema_version mismatch to be rejected"
    assert any("schema_version" in str(e.path) or "const" in e.message.lower()
               for e in errors)


def test_v2_rejects_unknown_top_level_field(
    schema_validator: jsonschema.Draft202012Validator,
) -> None:
    """additionalProperties:false at top-level enforces the field
    allow-list. Unknown keys (not in the additive set, not reserved)
    are rejected. Locks the Default-Lock A-2 boundary: no escape hatch."""
    doc = _minimal_v2_doc()
    doc["arbitrary_unknown_field"] = "should_fail"
    errors = list(schema_validator.iter_errors(doc))
    assert errors, "expected unknown top-level field to be rejected"


def test_v2_rejects_unknown_field_in_identity_pinned(
    schema_validator: jsonschema.Draft202012Validator,
) -> None:
    """identity_pinned has additionalProperties:false; unknown keys
    inside the nested object are rejected. The three additive v2 keys
    (identity_doc_ref, persona_owner_role, governance_revision) are
    explicit; nothing else is admitted."""
    doc = _minimal_v2_doc()
    doc["identity_pinned"]["arbitrary_unknown_nested"] = "should_fail"
    errors = list(schema_validator.iter_errors(doc))
    assert errors, "expected unknown identity_pinned field to be rejected"
