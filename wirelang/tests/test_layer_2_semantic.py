# SPDX-License-Identifier: Apache-2.0
"""Schema-compliance tests for Wirelang Layer 2 (Semantic frame envelope)."""

from __future__ import annotations

import copy


def _base_domain_envelope() -> dict:
    return {
        "frame_class": "domain-event",
        "schema_id": "wakir.task.assigned",
        "schema_version": "0.1.0",
        "validafter": "2026-05-06T00:00:00Z",
        "validuntil": None,
    }


def _base_meta_envelope() -> dict:
    return {
        "frame_class": "meta-event",
        "schema_id": "wakir.meta.capability.issued",
        "schema_version": "0.1.0",
        "validafter": "2026-05-06T00:00:00Z",
        "validuntil": None,
    }


# ---- positive cases ----


def test_positive_minimal_domain_event(layer_2_validator):
    assert layer_2_validator.is_valid(_base_domain_envelope())


def test_positive_minimal_meta_event(layer_2_validator):
    assert layer_2_validator.is_valid(_base_meta_envelope())


def test_positive_with_vocabulary_anchor(layer_2_validator):
    env = _base_domain_envelope()
    env["vocabulary"] = {
        "id": "wakir.core",
        "version": "0.1.0",
        "anchor_url": "https://wakir.dev/wirelang/vocab/0.1.0.json",
    }
    assert layer_2_validator.is_valid(env)


def test_positive_with_overlap_window(layer_2_validator):
    env = _base_domain_envelope()
    env["schema_version"] = "0.2.0"
    env["validafter"] = "2026-08-01T00:00:00Z"
    env["supersedes"] = "0.1.0"
    env["overlap_with"] = [{"version": "0.1.0", "until": "2026-09-01T00:00:00Z"}]
    assert layer_2_validator.is_valid(env)


def test_positive_with_ots_anchor_path(layer_2_validator):
    env = _base_meta_envelope()
    env["ots_anchor_path"] = (
        "meta/timestamps/wirelang-schema/wakir.meta.capability.issued-0.1.0.ots"
    )
    assert layer_2_validator.is_valid(env)


# ---- negative cases ----


def test_negative_meta_event_with_domain_schema_id(layer_2_validator):
    """Meta events MUST use the wakir.meta.* prefix."""
    env = _base_meta_envelope()
    env["schema_id"] = "wakir.task.assigned"
    assert not layer_2_validator.is_valid(env)


def test_negative_domain_event_with_meta_prefix(layer_2_validator):
    """Domain events MUST NOT use the wakir.meta.* prefix."""
    env = _base_domain_envelope()
    env["schema_id"] = "wakir.meta.capability.issued"
    assert not layer_2_validator.is_valid(env)


def test_negative_unknown_frame_class(layer_2_validator):
    env = _base_domain_envelope()
    env["frame_class"] = "side-effect"
    assert not layer_2_validator.is_valid(env)


def test_negative_schema_version_not_semver(layer_2_validator):
    env = _base_domain_envelope()
    env["schema_version"] = "1.0"
    assert not layer_2_validator.is_valid(env)


def test_negative_ots_anchor_wrong_path(layer_2_validator):
    """ots_anchor_path must live under meta/timestamps/wirelang-(schema|vocab)/."""
    env = _base_domain_envelope()
    env["ots_anchor_path"] = "meta/timestamps/wat/2026-05-06/12.ots"
    assert not layer_2_validator.is_valid(env)


def test_negative_extra_property(layer_2_validator):
    env = _base_domain_envelope()
    env["unknown"] = True
    assert not layer_2_validator.is_valid(env)
