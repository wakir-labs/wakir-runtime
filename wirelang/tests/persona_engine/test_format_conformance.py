# SPDX-License-Identifier: BUSL-1.1
"""Tests verifying persona-engine-format-spec v1.3 conformance.

Cross-checks against the existing JSON-Schema
``wirelang/schemas/wakir-persona-v1.json`` (spec §3.8) and against
the spec-declared constants in §3.3, §3.7.4, §3.7.5.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirelang.persona_engine.lifecycle_state_machine import (
    STATES,
    VALID_TRANSITIONS,
)
from wirelang.persona_engine.recovery_workflow import (
    RECOVERY_BUDGET_SECONDS,
    RECOVERY_WORKFLOW_PHASE_ORDER,
    RecoveryFailureMode,
    RecoveryTrigger,
)
from wirelang.persona_engine.despawn_clean import (
    DESPAWN_CLEAN_PHASE_ORDER,
    DespawnPhase,
)


SPEC_PATH = (
    Path(__file__).resolve().parents[3]
    / "wirelang"
    / "specs"
    / "persona-engine-format-spec.md"
)


def _spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


# -------------------- spec section anchors present --------------------


def test_spec_file_exists():
    assert SPEC_PATH.is_file()


def test_spec_carries_section_33_state_machine():
    text = _spec_text()
    assert "### 3.3 `spawn_lifecycle`" in text


def test_spec_carries_section_374_recovery_workflow():
    text = _spec_text()
    assert "#### 3.7.4 `recovery_workflow`" in text


def test_spec_carries_section_375_state_backing():
    text = _spec_text()
    assert "#### 3.7.5 `PersonaStateBacking`" in text


# -------------------- spec constants match code --------------------


def test_six_states_mentioned_in_spec_33():
    text = _spec_text()
    for s in STATES:
        assert f'"{s}"' in text or f"`{s}`" in text


def test_nine_transitions_present_in_spec_33():
    text = _spec_text()
    section = text.split("### 3.3 `spawn_lifecycle`")[1].split("### 3.4")[0]
    # All nine pairs appear as JSON literals in the spec.
    for from_s, to_s in VALID_TRANSITIONS:
        pair = f'["{from_s}", "{to_s}"]'
        assert pair in section, f"missing transition {pair} in spec §3.3"


def test_recovery_phase_order_in_spec_3742():
    text = _spec_text()
    # R1..R4 listed in canonical order somewhere in §3.7.4.2.
    section = text.split("§3.7.4.2")[1].split("§3.7.4.3")[0]
    for phase in RECOVERY_WORKFLOW_PHASE_ORDER:
        assert f"| {phase} |" in section, f"missing phase {phase}"


def test_recovery_trigger_enum_in_spec_3741():
    text = _spec_text()
    for t in RecoveryTrigger:
        assert t.value in text, f"missing trigger {t.value} in spec"


def test_recovery_failure_modes_in_spec_3745():
    text = _spec_text()
    # Five §3.7.4.5 modes plus the BUDGET_EXCEEDED from §3.7.4.4.
    for mode in RecoveryFailureMode:
        assert mode.value in text, f"missing failure mode {mode.value}"


def test_despawn_phase_order_in_spec_3711():
    text = _spec_text()
    section = text.split("§3.7.1.1")[1].split("§3.7.1.2")[0]
    for phase in DespawnPhase:
        assert phase.value in section, f"missing phase {phase.value}"


def test_recovery_budget_30_in_spec_3722_invariant_4():
    text = _spec_text()
    # Spec §3.7.2.2 invariant 4: ``recovery_budget_seconds: 30``.
    assert "recovery_budget_seconds: 30" in text or "30s" in text


# -------------------- json-schema cross-check --------------------


SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "wirelang"
    / "schemas"
    / "wakir-persona-v1.json"
)


def test_wakir_persona_v1_schema_file_present():
    assert SCHEMA_PATH.is_file()


def test_schema_carries_spawn_lifecycle_field():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # The schema is strict: spawn_lifecycle must be in properties.
    assert "spawn_lifecycle" in schema.get("properties", {}), (
        "schema must carry spawn_lifecycle per spec §3.3"
    )


def test_schema_carries_state_persistence_field():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "state_persistence" in schema.get("properties", {})


def test_schema_carries_container_bridge_field():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "container_bridge" in schema.get("properties", {})


# -------------------- engine version field surface --------------------


def test_engine_version_format_semver_pilot():
    from wirelang.persona_engine import __version__

    parts = __version__.split("-")
    assert len(parts) == 2
    assert parts[1] == "rc1"
    semver = parts[0]
    assert semver.count(".") == 2
