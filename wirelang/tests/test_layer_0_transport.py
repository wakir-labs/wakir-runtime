# SPDX-License-Identifier: Apache-2.0
"""Schema-compliance tests for Wirelang Layer 0 (NATS+JetStream transport).

Five positive and five negative cases per ADR-0009 invariant-test discipline.
"""

from __future__ import annotations

import copy

import pytest


# ---- positive cases ----


def _base_binding() -> dict:
    return {
        "binding": "nats-jetstream-1.0",
        "subject": {
            "pattern": "wakir.dev.agent.task.assigned",
            "env": "dev",
            "domain": "agent",
            "event_type": "task.assigned",
        },
        "stream": {
            "name": "WAKIR_AGENT_TASK",
            "subjects": ["wakir.dev.agent.task.>"],
            "retention_days": 7,
            "storage": "file",
        },
        "delivery": {
            "semantics": "at-least-once",
            "ordering": "per-stream-fifo",
        },
    }


def test_positive_minimal_required(layer_0_validator):
    binding = {
        "binding": "nats-jetstream-1.0",
        "subject": {
            "pattern": "wakir.prod.wat.audit.anchor.created",
            "env": "prod",
            "domain": "wat",
            "event_type": "audit.anchor.created",
        },
        "delivery": {
            "semantics": "at-least-once",
            "ordering": "per-stream-fifo",
        },
    }
    assert layer_0_validator.is_valid(binding)


def test_positive_full_with_stream_and_permissions(layer_0_validator):
    binding = _base_binding()
    binding["permissions"] = {
        "publish": ["wakir.dev.agent.task.>"],
        "subscribe": ["wakir.dev.agent.task.>"],
    }
    assert layer_0_validator.is_valid(binding)


def test_positive_with_sub_id(layer_0_validator):
    binding = _base_binding()
    binding["subject"]["sub_id"] = "audit-trail-agent"
    binding["subject"]["pattern"] = "wakir.dev.agent.task.assigned.audit-trail-agent"
    assert layer_0_validator.is_valid(binding)


def test_positive_wat_long_retention(layer_0_validator):
    binding = _base_binding()
    binding["subject"]["domain"] = "wat"
    binding["subject"]["pattern"] = "wakir.dev.wat.audit.anchor.created"
    binding["subject"]["event_type"] = "audit.anchor.created"
    binding["stream"]["name"] = "WAKIR_WAT_ANCHOR"
    binding["stream"]["subjects"] = ["wakir.dev.wat.audit.>"]
    binding["stream"]["retention_days"] = 14
    assert layer_0_validator.is_valid(binding)


def test_positive_staging_env(layer_0_validator):
    binding = _base_binding()
    binding["subject"]["env"] = "staging"
    binding["subject"]["pattern"] = "wakir.staging.agent.task.assigned"
    assert layer_0_validator.is_valid(binding)


# ---- negative cases ----


def test_negative_unknown_binding_id(layer_0_validator):
    binding = _base_binding()
    binding["binding"] = "kafka-1.0"
    assert not layer_0_validator.is_valid(binding)


def test_negative_subject_env_invalid(layer_0_validator):
    binding = _base_binding()
    binding["subject"]["env"] = "production"
    binding["subject"]["pattern"] = "wakir.production.agent.task.assigned"
    assert not layer_0_validator.is_valid(binding)


def test_negative_subject_pattern_missing_wakir_prefix(layer_0_validator):
    binding = _base_binding()
    binding["subject"]["pattern"] = "wakirX.dev.agent.task.assigned"
    assert not layer_0_validator.is_valid(binding)


def test_negative_delivery_semantics_unsupported(layer_0_validator):
    binding = _base_binding()
    binding["delivery"]["semantics"] = "exactly-once"
    assert not layer_0_validator.is_valid(binding)


def test_negative_retention_out_of_range(layer_0_validator):
    binding = _base_binding()
    binding["stream"]["retention_days"] = 0
    assert not layer_0_validator.is_valid(binding)


def test_negative_extra_top_level_property(layer_0_validator):
    """additionalProperties:false on the root object should reject unknowns."""
    binding = _base_binding()
    binding["unknown_field"] = True
    assert not layer_0_validator.is_valid(binding)
