# SPDX-License-Identifier: Apache-2.0
"""Persona-validator test suite (Phase-1b Sprint-6 Tag-1).

Coverage map
------------

- **t1**: V9 fixture (canonical persona-v1) → ``is_valid=True``,
  ``schema_supported=True``, empty errors.
- **t2**: V8 fixture (schema persona-v0) → ``is_valid=False``,
  ``schema_supported=False``, single
  ``schema-version-unsupported`` error.
- **t3**: missing-fence Markdown → ``frontmatter-missing`` error.
- **t4**: malformed-YAML (scalar) → ``frontmatter-malformed`` error.
- **t5**: missing top-level key (``description`` dropped) →
  ``missing-top-level-key`` error with ``detail`` = key name.
- **t6**: identity_pinned-not-mapping → coded error.
- **t7**: identity_pinned-missing-key (``hierarchy`` dropped) → coded
  error with ``detail`` = key name.
- **t8**: tools-wrong-type (int) → coded error with ``detail`` = type
  name.
- **t9**: dict input (bypasses frontmatter parse) and Path input
  produce identical reports for the V9 fixture (parity).
- **t10**: report ``to_canonical_dict()`` produces a JCS-stable dict
  whose ``rfc8785.dumps`` bytes are deterministic across two runs;
  ``schema_version`` field carries the declared value verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import rfc8785

from wirelang.persona.persona_canonical_form import (
    parse_frontmatter,
    split_frontmatter,
)
from wirelang.persona.persona_validator import (
    PERSONA_VALIDATION_REPORT_SCHEMA_VERSION,
    PersonaValidationReport,
    VALIDATION_ERROR_CODES,
    ValidationError,
    validate_persona,
)


FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "persona_definitions"
)
V8_PATH = FIXTURE_DIR / "v8-persona-pre-framework.md"
V9_PATH = FIXTURE_DIR / "v9-persona-framework-native.md"


def _v9_dict() -> dict:
    """Parse V9 fixture into the frontmatter dict (bypassing validator)."""
    text = V9_PATH.read_text(encoding="utf-8")
    fm, _ = split_frontmatter(text)
    return parse_frontmatter(fm)


def test_t1_v9_fixture_is_valid() -> None:
    report = validate_persona(V9_PATH)
    assert report.is_valid is True
    assert report.schema_version == "persona-v1"
    assert report.schema_supported is True
    assert report.errors == ()
    assert (
        report.report_schema_version == PERSONA_VALIDATION_REPORT_SCHEMA_VERSION
    )


def test_t2_v8_fixture_is_invalid_schema_unsupported() -> None:
    report = validate_persona(V8_PATH)
    assert report.is_valid is False
    assert report.schema_version == "persona-v0"
    assert report.schema_supported is False
    assert len(report.errors) == 1
    err = report.errors[0]
    assert err.code == "schema-version-unsupported"
    assert err.detail == "persona-v0"
    assert "persona-v0" in err.message


def test_t3_missing_frontmatter_fence_classified() -> None:
    markdown = "no frontmatter at all\njust prose\n"
    report = validate_persona(markdown)
    assert report.is_valid is False
    assert report.schema_version == ""
    assert report.schema_supported is False
    assert len(report.errors) == 1
    assert report.errors[0].code == "frontmatter-missing"


def test_t4_malformed_yaml_scalar_classified() -> None:
    markdown = "---\njust-a-scalar\n---\nbody\n"
    report = validate_persona(markdown)
    assert report.is_valid is False
    assert len(report.errors) == 1
    assert report.errors[0].code == "frontmatter-malformed"


def test_t5_missing_top_level_key_classified() -> None:
    fm = _v9_dict()
    del fm["description"]
    report = validate_persona(fm)
    assert report.is_valid is False
    missing = [e for e in report.errors if e.code == "missing-top-level-key"]
    assert len(missing) == 1
    assert missing[0].detail == "description"


def test_t6_identity_pinned_not_mapping_classified() -> None:
    fm = _v9_dict()
    fm["identity_pinned"] = "not-a-mapping"
    report = validate_persona(fm)
    assert report.is_valid is False
    coded = [
        e for e in report.errors if e.code == "identity-pinned-not-mapping"
    ]
    assert len(coded) == 1
    assert coded[0].detail == "str"


def test_t7_identity_pinned_missing_key_classified() -> None:
    fm = _v9_dict()
    del fm["identity_pinned"]["hierarchy"]
    report = validate_persona(fm)
    assert report.is_valid is False
    coded = [
        e for e in report.errors if e.code == "identity-pinned-missing-key"
    ]
    assert len(coded) == 1
    assert coded[0].detail == "hierarchy"


def test_t8_tools_wrong_type_classified() -> None:
    fm = _v9_dict()
    fm["tools"] = 42  # neither list nor str
    report = validate_persona(fm)
    assert report.is_valid is False
    coded = [e for e in report.errors if e.code == "tools-wrong-type"]
    assert len(coded) == 1
    assert coded[0].detail == "int"


def test_t9_dict_and_path_inputs_produce_equivalent_reports() -> None:
    report_path = validate_persona(V9_PATH)
    report_dict = validate_persona(_v9_dict())
    assert report_path.is_valid is True
    assert report_dict.is_valid is True
    # The two reports must be equal at the canonical-dict level (JCS
    # bytes-identical) — the dict-input branch skips file IO and YAML
    # parse, but the validator side of the pipeline must converge.
    assert report_path.to_canonical_dict() == report_dict.to_canonical_dict()


def test_t10_report_to_canonical_dict_is_jcs_byte_stable() -> None:
    report = validate_persona(V9_PATH)
    canon = report.to_canonical_dict()
    bytes_run_1 = rfc8785.dumps(canon)
    bytes_run_2 = rfc8785.dumps(canon)
    # Determinism: same input dict → same JCS bytes (well-known
    # property; the additional anchor is that running through our
    # canonical-dict shape preserves it).
    assert bytes_run_1 == bytes_run_2
    # Field-level anchors: the JCS bytes must contain the literal
    # schema_version value and the report-schema-version sentinel.
    assert b'"schema_version":"persona-v1"' in bytes_run_1
    assert b'"report_schema_version":"persona-validation-v1"' in bytes_run_1
    assert b'"is_valid":true' in bytes_run_1
    assert b'"schema_supported":true' in bytes_run_1
    # And the errors array is empty for the V9 fixture.
    assert b'"errors":[]' in bytes_run_1


def test_t11_validation_error_codes_registry_is_closed_set() -> None:
    # The closed-set guarantee: every code that the validator emits
    # must appear in VALIDATION_ERROR_CODES. This is the cross-lang
    # contract that the Rust pendant enforces with an enum.
    expected = {
        "frontmatter-missing",
        "frontmatter-malformed",
        "missing-top-level-key",
        "identity-pinned-not-mapping",
        "identity-pinned-missing-key",
        "schema-version-unsupported",
        "tools-wrong-type",
    }
    assert set(VALIDATION_ERROR_CODES) == expected


def test_t12_does_not_raise_on_validation_failure() -> None:
    # Contract: validate_persona never raises on validation failure.
    # Only FileNotFoundError (missing Path) and pure bugs propagate.
    no_fence = "x"
    # Must not raise:
    validate_persona(no_fence)
    # FileNotFoundError DOES propagate for missing Path:
    with pytest.raises(FileNotFoundError):
        validate_persona(Path("/nonexistent/persona.md"))


def test_t13_canonical_dict_keys_are_lexicographically_sorted() -> None:
    # JCS resorts anyway, but having the intermediate dict already
    # sorted helps inspection and matches the canonical-form posture
    # of the other persona modules.
    report = validate_persona(V9_PATH)
    canon = report.to_canonical_dict()
    keys = list(canon.keys())
    assert keys == sorted(keys)


def test_t14_error_record_canonical_dict_keys_sorted() -> None:
    err = ValidationError(
        code="schema-version-unsupported",
        message="persona schema_version='persona-v0' is not supported",
        detail="persona-v0",
    )
    d = err.to_canonical_dict()
    keys = list(d.keys())
    assert keys == sorted(keys)
    assert d == {
        "code": "schema-version-unsupported",
        "detail": "persona-v0",
        "message": "persona schema_version='persona-v0' is not supported",
    }


def test_t15_report_is_frozen_dataclass() -> None:
    # Frozen-dataclass anchor: cannot mutate fields after construction
    # — the parity contract requires immutability so the canonical
    # dict shape is stable across the call.
    report = validate_persona(V9_PATH)
    with pytest.raises((AttributeError, Exception)):
        report.is_valid = False  # type: ignore[misc]
    assert isinstance(report, PersonaValidationReport)
