# SPDX-License-Identifier: Apache-2.0
"""Schema-compliance tests for Wirelang Layer 1 (CloudEvents 1.0 + Wakir extensions)."""

from __future__ import annotations

import copy


def _base_frame() -> dict:
    return {
        "specversion": "1.0",
        "type": "wakir.task.assigned",
        "source": "did:web:wakir.dev:audit-trail-agent",
        "id": "01HK4P8X3W2N5Q9V0R6T7S8YZA",
        "time": "2026-05-06T11:35:00.000Z",
        "datacontenttype": "application/wirelang+json",
        "wirelangversion": "0.1.0",
        "schemaid": "wakir.task.assigned",
        "schemaversion": "0.1.0",
        "actorrole": "audit-specialist",
    }


# ---- positive cases ----


def test_positive_minimum_required_only(layer_1_validator):
    frame = _base_frame()
    frame.pop("time")
    frame.pop("datacontenttype")
    assert layer_1_validator.is_valid(frame)


def test_positive_full_extensions(layer_1_validator):
    frame = _base_frame()
    h = "0" * 64
    frame.update(
        {
            "caprefs": [f"sha256:{h}"],
            "attestationref": f"sha256:{h}",
            "personahash": f"sha256:{h}",
            "imagedigest": f"sha256:{h}",
            "agentid": "audit-trail-agent-001",
            "personapin": f"sha256:{h}",
            "dataschemaref": "https://wakir.dev/wirelang/schema/task.assigned/0.1.0",
        }
    )
    assert layer_1_validator.is_valid(frame)


def test_positive_meta_event_type(layer_1_validator):
    frame = _base_frame()
    frame["type"] = "wakir.meta.capability.issued"
    frame["schemaid"] = "wakir.meta.capability.issued"
    assert layer_1_validator.is_valid(frame)


def test_positive_loaded_example_domain(layer_1_validator, example_domain_event):
    assert layer_1_validator.is_valid(example_domain_event)


def test_positive_loaded_example_meta(layer_1_validator, example_meta_event):
    assert layer_1_validator.is_valid(example_meta_event)


# ---- negative cases ----


def test_negative_specversion_wrong(layer_1_validator):
    frame = _base_frame()
    frame["specversion"] = "0.3"
    assert not layer_1_validator.is_valid(frame)


def test_negative_source_not_did_web(layer_1_validator):
    frame = _base_frame()
    frame["source"] = "https://wakir.dev/audit-trail-agent"
    assert not layer_1_validator.is_valid(frame)


def test_negative_type_missing_wakir_prefix(layer_1_validator):
    frame = _base_frame()
    frame["type"] = "task.assigned"
    assert not layer_1_validator.is_valid(frame)


def test_negative_capref_wrong_hash_format(layer_1_validator):
    frame = _base_frame()
    frame["caprefs"] = ["md5:abcdef"]
    assert not layer_1_validator.is_valid(frame)


def test_negative_actorrole_capitalised(layer_1_validator):
    """actorrole MUST be lowercase per pseudonymisation discipline."""
    frame = _base_frame()
    frame["actorrole"] = "Audit-Specialist"
    assert not layer_1_validator.is_valid(frame)


def test_negative_missing_required_wirelangversion(layer_1_validator):
    frame = _base_frame()
    frame.pop("wirelangversion")
    assert not layer_1_validator.is_valid(frame)
