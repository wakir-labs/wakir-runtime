# SPDX-License-Identifier: Apache-2.0
"""V-907 persona-hash test suite (Phase-1b Sprint-1 Tag-2).

Coverage map
------------

1. **9-vector pin pack** — every fixture under
   ``wirelang/tests/fixtures/persona_definitions/`` reproduces the
   frozen hex pin in
   :mod:`wirelang.persona._internal.pin_pack_constants`.
2. **In-hash / out-of-hash boundary** — body-only edit (v5) yields
   the v1 pin; front-matter and identity_pinned edits (v4, v6) do not.
3. **Mutation classes M-1 / M-2 / M-3 / M-4** — exhaustive coverage
   per the V-907 spec.
4. **Schema rejection** — schema_version=persona-v0 (v8) raises
   PersonaSchemaUnsupportedError; the self-migration target (v9)
   hashes cleanly.
5. **Caller-pin verification** — happy path + drift path.
6. **V-908 federation sentinel** — the empty-string sentinel is the
   correct value for a frame that does not pin a persona reference.
7. **JSON-Schema conformance** — every accepted fixture's canonical
   subset validates against ``wirelang/schemas/persona-v1.json``.
8. **Roundtrip determinism** — running the hash twice on the same
   input is idempotent (also covers the parser side).
9. **Malformed-input error mapping** — missing fence, malformed YAML,
   missing required keys, malformed identity_pinned all surface as
   PersonaDefinitionInvalidError (single error class for callers).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
import rfc8785

from wirelang.persona import (
    PERSONA_EMPTY_REF_SENTINEL,
    PERSONA_HASH_HEX_LENGTH,
    PERSONA_HASH_PREFIX,
    PersonaDefinitionInvalidError,
    PersonaHashMismatchError,
    PersonaSchemaUnsupportedError,
    compute_persona_hash,
    compute_persona_hash_from_canonical,
)
from wirelang.persona._internal.pin_pack_constants import (
    PERSONA_HASH_PIN_V1,
    PERSONA_HASH_PIN_V2,
    PERSONA_HASH_PIN_V3,
    PERSONA_HASH_PIN_V4,
    PERSONA_HASH_PIN_V5,
    PERSONA_HASH_PIN_V6,
    PERSONA_HASH_PIN_V9,
)
from wirelang.persona.persona_canonical_form import (
    extract_canonical_subset,
    parse_frontmatter,
    read_canonical_subset,
    split_frontmatter,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "persona_definitions"
)
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "persona-v1.json"
)


def _fixture(name: str) -> Path:
    return FIXTURE_DIR / name


@pytest.fixture(scope="module")
def schema_validator() -> jsonschema.Draft202012Validator:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    return jsonschema.Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# 1. Constants surface
# ---------------------------------------------------------------------------


def test_persona_hash_prefix_is_sha256_colon() -> None:
    assert PERSONA_HASH_PREFIX == "sha256:"


def test_persona_hash_hex_length_is_64() -> None:
    assert PERSONA_HASH_HEX_LENGTH == 64


def test_persona_empty_ref_sentinel_is_empty_string() -> None:
    assert PERSONA_EMPTY_REF_SENTINEL == ""


# ---------------------------------------------------------------------------
# 2. Pin-pack regression: every fixture reproduces its frozen hex pin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name,expected_pin",
    [
        ("v1-persona-ceo.md", PERSONA_HASH_PIN_V1),
        ("v2-persona-wat-eng.md", PERSONA_HASH_PIN_V2),
        ("v3-persona-identity-eng.md", PERSONA_HASH_PIN_V3),
        ("v4-persona-ceo-frontmatter-edit.md", PERSONA_HASH_PIN_V4),
        ("v5-persona-ceo-body-edit.md", PERSONA_HASH_PIN_V5),
        ("v6-persona-ceo-cross-review-edit.md", PERSONA_HASH_PIN_V6),
        ("v9-persona-framework-native.md", PERSONA_HASH_PIN_V9),
    ],
    ids=["v1", "v2", "v3", "v4", "v5", "v6", "v9"],
)
def test_pin_pack_regression(fixture_name: str, expected_pin: str) -> None:
    assert compute_persona_hash(_fixture(fixture_name)) == expected_pin


# ---------------------------------------------------------------------------
# 3. In-hash / out-of-hash boundary — the audit-pillar pillar test
# ---------------------------------------------------------------------------


def test_v5_body_edit_does_not_change_hash() -> None:
    """Mutation M-3: body-only edit MUST NOT shift the persona-hash."""
    h_v1 = compute_persona_hash(_fixture("v1-persona-ceo.md"))
    h_v5 = compute_persona_hash(_fixture("v5-persona-ceo-body-edit.md"))
    assert h_v1 == h_v5, "out-of-hash boundary violated by body edit"


def test_v4_frontmatter_edit_does_change_hash() -> None:
    """Mutation M-1: in-hash front-matter edit MUST shift the hash."""
    h_v1 = compute_persona_hash(_fixture("v1-persona-ceo.md"))
    h_v4 = compute_persona_hash(_fixture("v4-persona-ceo-frontmatter-edit.md"))
    assert h_v1 != h_v4


def test_v6_identity_pinned_edit_does_change_hash() -> None:
    """Mutation M-2: in-hash identity_pinned edit MUST shift the hash."""
    h_v1 = compute_persona_hash(_fixture("v1-persona-ceo.md"))
    h_v6 = compute_persona_hash(_fixture("v6-persona-ceo-cross-review-edit.md"))
    assert h_v1 != h_v6


# ---------------------------------------------------------------------------
# 4. Mutation class M-4: spot-mutation in the hex tail
# ---------------------------------------------------------------------------


def test_m4_hex_tail_bit_flip_breaks_caller_pin() -> None:
    """Flipping a single hex char in the caller-pin must trip the verifier."""
    base = compute_persona_hash(_fixture("v1-persona-ceo.md"))
    # Flip the last hex character (deterministic bit-flip).
    flipped_hex = base[-1]
    replacement = "0" if flipped_hex != "0" else "1"
    tampered = base[:-1] + replacement
    with pytest.raises(PersonaHashMismatchError):
        compute_persona_hash(
            _fixture("v1-persona-ceo.md"), expected_jcs_sha256=tampered
        )


# ---------------------------------------------------------------------------
# 5. Schema-version rejection (self-migration source) and acceptance (target)
# ---------------------------------------------------------------------------


def test_v8_pre_framework_is_rejected() -> None:
    with pytest.raises(PersonaSchemaUnsupportedError):
        compute_persona_hash(_fixture("v8-persona-pre-framework.md"))


def test_v9_framework_native_hashes_cleanly() -> None:
    h = compute_persona_hash(_fixture("v9-persona-framework-native.md"))
    assert h == PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------------------
# 6. Caller-pin happy path + drift path + accept-both-forms
# ---------------------------------------------------------------------------


def test_caller_pin_happy_path_full_form() -> None:
    h = compute_persona_hash(
        _fixture("v1-persona-ceo.md"),
        expected_jcs_sha256=PERSONA_HASH_PIN_V1,
    )
    assert h == PERSONA_HASH_PIN_V1


def test_caller_pin_happy_path_bare_hex_form() -> None:
    bare_hex = PERSONA_HASH_PIN_V1[len(PERSONA_HASH_PREFIX):]
    h = compute_persona_hash(
        _fixture("v1-persona-ceo.md"), expected_jcs_sha256=bare_hex
    )
    assert h == PERSONA_HASH_PIN_V1


def test_caller_pin_drift_raises() -> None:
    bogus = (
        "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    )
    with pytest.raises(PersonaHashMismatchError):
        compute_persona_hash(
            _fixture("v1-persona-ceo.md"), expected_jcs_sha256=bogus
        )


# ---------------------------------------------------------------------------
# 7. V-908 federation sentinel — the empty-string convention
# ---------------------------------------------------------------------------


def test_empty_ref_sentinel_is_distinct_from_any_real_hash() -> None:
    """An empty persona_refs[0] entry must NOT collide with a real hash."""
    real_hash = compute_persona_hash(_fixture("v1-persona-ceo.md"))
    assert PERSONA_EMPTY_REF_SENTINEL != real_hash
    assert PERSONA_EMPTY_REF_SENTINEL == ""


# ---------------------------------------------------------------------------
# 8. Schema conformance — every accepted fixture validates against persona-v1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    [
        "v1-persona-ceo.md",
        "v2-persona-wat-eng.md",
        "v3-persona-identity-eng.md",
        "v4-persona-ceo-frontmatter-edit.md",
        "v5-persona-ceo-body-edit.md",
        "v6-persona-ceo-cross-review-edit.md",
        "v9-persona-framework-native.md",
    ],
)
def test_canonical_subset_validates_against_schema(
    fixture_name: str, schema_validator: jsonschema.Draft202012Validator
) -> None:
    text = _fixture(fixture_name).read_text(encoding="utf-8")
    canonical = read_canonical_subset(text)
    schema_validator.validate(canonical)


# ---------------------------------------------------------------------------
# 9. Roundtrip determinism — same input yields same output
# ---------------------------------------------------------------------------


def test_compute_persona_hash_is_deterministic() -> None:
    p = _fixture("v1-persona-ceo.md")
    a = compute_persona_hash(p)
    b = compute_persona_hash(p)
    assert a == b


def test_canonical_form_is_jcs_byte_stable() -> None:
    """The canonical-subset dict + JCS must round-trip byte-stably."""
    text = _fixture("v1-persona-ceo.md").read_text(encoding="utf-8")
    canonical_a = read_canonical_subset(text)
    canonical_b = read_canonical_subset(text)
    assert rfc8785.dumps(canonical_a) == rfc8785.dumps(canonical_b)


# ---------------------------------------------------------------------------
# 10. Malformed-input error mapping
# ---------------------------------------------------------------------------


def test_missing_frontmatter_fence_raises_invalid(tmp_path: Path) -> None:
    p = tmp_path / "no-frontmatter.md"
    p.write_text("# just a body, no fences\n", encoding="utf-8")
    with pytest.raises(PersonaDefinitionInvalidError):
        compute_persona_hash(p)


def test_unterminated_frontmatter_raises_invalid(tmp_path: Path) -> None:
    p = tmp_path / "open-fence.md"
    p.write_text("---\nname: x\nschema_version: persona-v1\n", encoding="utf-8")
    with pytest.raises(PersonaDefinitionInvalidError):
        compute_persona_hash(p)


def test_empty_frontmatter_raises_invalid(tmp_path: Path) -> None:
    p = tmp_path / "empty-fm.md"
    p.write_text("---\n---\n# body\n", encoding="utf-8")
    with pytest.raises(PersonaDefinitionInvalidError):
        compute_persona_hash(p)


def test_missing_required_key_raises_invalid(tmp_path: Path) -> None:
    p = tmp_path / "no-identity-pinned.md"
    p.write_text(
        "---\n"
        "name: x\n"
        "description: y\n"
        "tools: [Read]\n"
        "schema_version: persona-v1\n"
        "---\n"
        "# body\n",
        encoding="utf-8",
    )
    with pytest.raises(PersonaDefinitionInvalidError):
        compute_persona_hash(p)


def test_scalar_frontmatter_raises_invalid(tmp_path: Path) -> None:
    p = tmp_path / "scalar-fm.md"
    p.write_text("---\n42\n---\n# body\n", encoding="utf-8")
    with pytest.raises(PersonaDefinitionInvalidError):
        compute_persona_hash(p)


# ---------------------------------------------------------------------------
# 11. Forward-compat: unknown front-matter keys are ignored, hash unchanged
# ---------------------------------------------------------------------------


def test_unknown_frontmatter_keys_are_ignored(tmp_path: Path) -> None:
    """Adding an unknown top-level key must NOT alter the persona-hash.

    Forward-compat posture: HR can introduce new fields in a later
    schema revision without forcing a re-pin sweep, *as long as* the
    new field is documented as out-of-canonical-subset. A future
    strict-mode flag will trip on unknown keys, but that is opt-in.
    """
    base_text = _fixture("v1-persona-ceo.md").read_text(encoding="utf-8")
    fm, body = split_frontmatter(base_text)
    augmented = (
        "---\n"
        + fm
        + "extra_unknown_key: ignored-by-extractor\n"
        + "---\n"
        + body
    )
    p = tmp_path / "augmented.md"
    p.write_text(augmented, encoding="utf-8")
    h_aug = compute_persona_hash(p)
    h_base = compute_persona_hash(_fixture("v1-persona-ceo.md"))
    assert h_aug == h_base


# ---------------------------------------------------------------------------
# 12. compute_persona_hash_from_canonical — direct in-memory path
# ---------------------------------------------------------------------------


def test_in_memory_canonical_matches_file_hash() -> None:
    text = _fixture("v1-persona-ceo.md").read_text(encoding="utf-8")
    canonical = read_canonical_subset(text)
    file_hash = compute_persona_hash(_fixture("v1-persona-ceo.md"))
    mem_hash = compute_persona_hash_from_canonical(canonical)
    assert file_hash == mem_hash


def test_jcs_byte_check_against_canonical() -> None:
    """Cross-check that the hash equals sha256(rfc8785.dumps(subset))."""
    text = _fixture("v2-persona-wat-eng.md").read_text(encoding="utf-8")
    canonical = read_canonical_subset(text)
    expected_hex = hashlib.sha256(rfc8785.dumps(canonical)).hexdigest()
    expected_full = PERSONA_HASH_PREFIX + expected_hex
    assert compute_persona_hash(_fixture("v2-persona-wat-eng.md")) == (
        expected_full
    )


# ---------------------------------------------------------------------------
# 13. Format invariants — full-length and prefix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    [
        "v1-persona-ceo.md",
        "v2-persona-wat-eng.md",
        "v3-persona-identity-eng.md",
        "v9-persona-framework-native.md",
    ],
)
def test_returned_hash_has_expected_format(fixture_name: str) -> None:
    h = compute_persona_hash(_fixture(fixture_name))
    assert h.startswith(PERSONA_HASH_PREFIX)
    tail = h[len(PERSONA_HASH_PREFIX):]
    assert len(tail) == PERSONA_HASH_HEX_LENGTH
    int(tail, 16)  # well-formed hex
