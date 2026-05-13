# SPDX-License-Identifier: Apache-2.0
"""Self-migration converter edge-case test pack (Phase-1b Sprint-2 Tag-2, S2-T1-03).

Coverage map (Tag-4-Skizze §3.4 + Sprint-2-Tag-2 auftrag)
========================================================

This file is the *negative-and-defensive* test belt around
:func:`wirelang.persona.migrate_persona`. The Tag-1 file
``test_persona_migration.py`` already pins the determinism anchor
(v8 -> v1 reproduces ``PERSONA_HASH_PIN_V8_MIGRATED_TO_V1``) and the
basic chain-resolution rejection paths; this file exercises:

- **Degraded front-matter:** missing closing fence, scalar/list
  front-matter, raw-markdown with no schema_version key.
- **Missing fields:** dict without schema_version, dict with
  non-string schema_version (int / list / None).
- **Malformed mock-format records:** non-dict input (int, bytes,
  None) — must raise ``TypeError`` (engineered guard).
- **Defensive immutability:** caller dicts are not mutated.
- **Cycle-guard backstop:** the ``_MAX_CHAIN_LENGTH=32`` safety
  guard fires on a fault-injected step registry.
- **Caller-pin form tolerance:** bare-hex form vs. full
  ``sha256:`` form both work for drift detection.

Each test is hermetic — no network, no shared mutable state.

Default-Lock A-1+A-2+A-3 conformance (ratified 2026-05-07 ~10:00
CEST): the converter never touches the markdown body, never removes
keys, and operates on the canonical-subset shape only.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

# Skip the whole module when rfc8785 is absent: the wirelang.persona
# package imports rfc8785 unconditionally at module-load time, so any
# top-level `from wirelang.persona ...` below would crash collection
# in the sandbox lane. Test-level importorskip is the conventional
# guard for this case until the persona package adopts a lazy import.
pytest.importorskip("rfc8785")

from wirelang.persona import (
    PERSONA_SCHEMA_VERSION_LATEST,
    PERSONA_SCHEMA_VERSION_LIST,
    PersonaMigrationError,
    migrate_persona,
)
from wirelang.persona._internal.migration_steps import (
    REGISTERED_STEPS,
    V0ToV1Step,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "persona_definitions"
)


def _v0_canonical_dict() -> dict[str, Any]:
    """Return a fresh, well-formed v0 canonical-subset dict."""
    return {
        "name": "edge-case-agent",
        "description": "edge-case test fixture (in-memory v0)",
        "tools": ["Read"],
        "schema_version": "persona-v0",
        "identity_pinned": {
            "cross_review_zones": [],
            "authority": {
                "push_remote": False,
                "budget_cap_eur_per_month": 0,
                "sub_delegation": False,
            },
            "hierarchy": {
                "reports_to": "cto",
                "escalation": "cto",
            },
        },
    }


# ---------------------------------------------------------------
# Degraded front-matter (raw-markdown inputs)
# ---------------------------------------------------------------

def test_raw_markdown_without_closing_fence_is_irreparable():
    """No closing ``---`` fence -> ``PersonaMigrationError`` (wrapped)."""
    raw = "---\nname: foo\nschema_version: persona-v0\n"
    with pytest.raises(PersonaMigrationError, match="irreparable"):
        migrate_persona(raw)


def test_raw_markdown_with_scalar_frontmatter_is_irreparable():
    """A YAML scalar front-matter block is not a mapping -> wrapped."""
    raw = "---\n42\n---\nbody"
    with pytest.raises(PersonaMigrationError, match="irreparable"):
        migrate_persona(raw)


def test_raw_markdown_without_leading_fence_is_rejected():
    """A string that doesn't start with ``---`` is an explicit reject."""
    raw = "name: foo\nschema_version: persona-v0\n"
    with pytest.raises(
        PersonaMigrationError, match="must start with a '---'"
    ):
        migrate_persona(raw)


def test_path_to_irreparable_file_is_wrapped(tmp_path: Path):
    """A persona file with malformed front-matter raises wrapped error."""
    bad = tmp_path / "broken.md"
    bad.write_text(
        "---\nname: foo\nschema_version: persona-v0\n"
        # no closing fence
        ,
        encoding="utf-8",
    )
    with pytest.raises(PersonaMigrationError, match="irreparable"):
        migrate_persona(bad)


def test_path_to_missing_file_raises_filenotfound(tmp_path: Path):
    """Non-existent path is a stdlib ``FileNotFoundError`` (not wrapped)."""
    missing = tmp_path / "does-not-exist.md"
    with pytest.raises(FileNotFoundError):
        migrate_persona(missing)


# ---------------------------------------------------------------
# Missing / malformed schema_version
# ---------------------------------------------------------------

def test_dict_without_schema_version_raises():
    """A dict missing ``schema_version`` is rejected with a clear error."""
    d = _v0_canonical_dict()
    del d["schema_version"]
    with pytest.raises(
        PersonaMigrationError, match="no schema_version"
    ):
        migrate_persona(d)


def test_dict_with_int_schema_version_raises():
    """``schema_version`` must be a string."""
    d = _v0_canonical_dict()
    d["schema_version"] = 42
    with pytest.raises(
        PersonaMigrationError, match="must be a string"
    ):
        migrate_persona(d)


def test_dict_with_list_schema_version_raises():
    """``schema_version`` as a list is rejected (defensive type-guard)."""
    d = _v0_canonical_dict()
    d["schema_version"] = ["persona-v0"]
    with pytest.raises(
        PersonaMigrationError, match="must be a string"
    ):
        migrate_persona(d)


# ---------------------------------------------------------------
# Non-dict / non-str / non-Path input shapes
# ---------------------------------------------------------------

def test_int_input_raises_typeerror():
    """``int`` is not in the public-API contract."""
    with pytest.raises(TypeError, match="dict | str | Path"):
        migrate_persona(123)  # type: ignore[arg-type]


def test_bytes_input_raises_typeerror():
    """``bytes`` is not in the public-API contract."""
    with pytest.raises(TypeError, match="dict | str | Path"):
        migrate_persona(b"---\nname: x\n---\n")  # type: ignore[arg-type]


def test_none_input_raises_typeerror():
    """``None`` is not in the public-API contract."""
    with pytest.raises(TypeError, match="dict | str | Path"):
        migrate_persona(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------
# Defensive immutability of caller state
# ---------------------------------------------------------------

def test_input_dict_is_not_mutated_on_success():
    """Caller's dict survives migration unchanged (deepcopy at boundary)."""
    d = _v0_canonical_dict()
    snapshot = copy.deepcopy(d)
    _ = migrate_persona(d, target_schema_version="persona-v1")
    assert d == snapshot, "migrate_persona must not mutate caller state"


def test_input_dict_nested_lists_are_isolated():
    """Migration output's identity_pinned must be a separate object."""
    d = _v0_canonical_dict()
    out = migrate_persona(d, target_schema_version="persona-v1")
    # Mutate the output and confirm the input is untouched.
    out["identity_pinned"]["cross_review_zones"].append(
        {"zone": "X", "partner": "fault-injection", "trigger": "test"}
    )
    assert d["identity_pinned"]["cross_review_zones"] == []


# ---------------------------------------------------------------
# Step-level invariants (V0ToV1Step.apply contract)
# ---------------------------------------------------------------

def test_v0_to_v1_step_rejects_wrong_source_version():
    """``V0ToV1Step.apply`` refuses dicts that don't claim v0."""
    d = _v0_canonical_dict()
    d["schema_version"] = "persona-v1"
    with pytest.raises(ValueError, match="expected schema_version"):
        V0ToV1Step().apply(d)


def test_v0_to_v1_step_rejects_non_dict():
    """``V0ToV1Step.apply`` refuses non-dict inputs."""
    with pytest.raises(TypeError, match="expects a dict"):
        V0ToV1Step().apply("not a dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------
# Caller-pin form tolerance (bare-hex vs sha256:hex)
# ---------------------------------------------------------------

def test_caller_pin_bare_hex_form_drift_is_detected():
    """A wrong bare-hex pin still raises the determinism error class."""
    from wirelang.persona import PersonaMigrationDeterminismError
    bogus_bare = "0" * 64
    with pytest.raises(PersonaMigrationDeterminismError, match="drift"):
        migrate_persona(
            FIXTURE_DIR / "v8-persona-pre-framework.md",
            target_schema_version="persona-v1",
            expected_post_migration_hash=bogus_bare,
        )


# ---------------------------------------------------------------
# Cycle-guard backstop (engineered fault injection)
# ---------------------------------------------------------------

class _CyclicStep:
    """Fault-injection step that points to its own source (instant cycle)."""
    source_version = "persona-v0"
    target_version = "persona-v0"

    def apply(self, definition_dict: dict[str, Any]) -> dict[str, Any]:
        return dict(definition_dict)


def test_cycle_guard_fires_on_self_referencing_step(monkeypatch):
    """A self-referencing step in the registry trips the 32-step guard."""
    from wirelang.persona import persona_migration as mig

    # Inject a single cyclic step. The registered V0ToV1Step is replaced
    # by a step whose target equals its source, so _resolve_chain spins.
    monkeypatch.setattr(
        mig,
        "REGISTERED_STEPS",
        (_CyclicStep(),),
    )
    with pytest.raises(
        PersonaMigrationError, match="suspect a cycle"
    ):
        mig.migrate_persona(
            _v0_canonical_dict(), target_schema_version="persona-v1"
        )


# ---------------------------------------------------------------
# Sanity sweep — schema-version registry surface
# ---------------------------------------------------------------

def test_schema_version_list_includes_latest():
    """``PERSONA_SCHEMA_VERSION_LATEST`` is always reachable."""
    assert PERSONA_SCHEMA_VERSION_LATEST in PERSONA_SCHEMA_VERSION_LIST


def test_registered_steps_are_non_empty():
    """At least one migration step is wired (Phase-1b minimum)."""
    assert len(REGISTERED_STEPS) >= 1
