# SPDX-License-Identifier: Apache-2.0
"""Tests for the Datalog-caveat JSON Schema (Phase-1a vocabulary).

The schema validates the *array of caveats* that goes inside
``authority_block.caveats`` and ``append_blocks[*].caveats`` of a
Layer-3 capability token. Schema-level validation is the syntactic
gate; Biscuit-Datalog evaluation does the runtime semantic check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

WIRELANG_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = WIRELANG_ROOT / "schemas" / "datalog-caveat.json"


@pytest.fixture(scope="module")
def datalog_caveat_validator() -> Draft202012Validator:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


def test_positive_empty_array_is_valid(datalog_caveat_validator) -> None:
    """A token with no caveats is structurally valid; semantic
    'must have at least one caveat' is a verifier policy decision."""
    datalog_caveat_validator.validate([])


def test_positive_simple_action_caveat(datalog_caveat_validator) -> None:
    datalog_caveat_validator.validate([
        'action("treasury.read.balance")',
    ])


def test_positive_validity_window_with_time_variable(
    datalog_caveat_validator,
) -> None:
    datalog_caveat_validator.validate([
        "time($t), $t < 2026-12-31T23:59:59Z",
    ])


def test_positive_full_phase_1a_caveat_set(datalog_caveat_validator) -> None:
    """A full set of Phase-1a caveats co-existing in one token."""
    datalog_caveat_validator.validate([
        "time($t), $t > 2026-05-06T00:00:00Z, $t < 2026-05-13T00:00:00Z",
        'audience("did:web:wakir.dev:personas:treasury-agent")',
        'agent_did("did:web:wakir.dev:personas:cfo-agent")',
        'operation("read_balance")',
        "action_count_max(10)",
        "read_only(true)",
        'env("prod")',
        "rate_limit(100)",
        "attenuation_depth_max(2)",
        'wat_anchor("anchor-2026-05-06-w19")',
    ])


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def test_negative_unknown_predicate_rejected(datalog_caveat_validator) -> None:
    """`drop_database` is obviously not in our vocabulary."""
    errors = list(
        datalog_caveat_validator.iter_errors([
            'drop_database("treasury")',
        ])
    )
    assert errors, "unknown predicate should not validate"


def test_negative_predicate_close_to_real_but_misspelled(
    datalog_caveat_validator,
) -> None:
    """`actions` (with trailing s) is NOT registered; must fail."""
    errors = list(
        datalog_caveat_validator.iter_errors([
            'actions("treasury.read.balance")',
        ])
    )
    assert errors


def test_negative_caveat_without_call_syntax(
    datalog_caveat_validator,
) -> None:
    """A bare predicate name without parens is invalid."""
    errors = list(
        datalog_caveat_validator.iter_errors([
            "read_only",
        ])
    )
    assert errors


def test_negative_non_string_caveat_entry(datalog_caveat_validator) -> None:
    """Caveat entries must be strings, not nested objects."""
    errors = list(
        datalog_caveat_validator.iter_errors([
            {"action": "treasury.read.balance"},
        ])
    )
    assert errors


def test_positive_example_caveat_set_file_validates(
    datalog_caveat_validator,
) -> None:
    """The committed reference example file must validate."""
    example_path = WIRELANG_ROOT / "examples" / "datalog-caveat-set-example.json"
    if not example_path.exists():
        pytest.skip("example file not present")
    with example_path.open("r", encoding="utf-8") as fh:
        caveats = json.load(fh)
    datalog_caveat_validator.validate(caveats)


def test_positive_all_20_predicates_each_validate_alone(
    datalog_caveat_validator,
) -> None:
    """Each of the 20 registered predicates validates as a singleton.

    This is a regression guard: if the JSON-Schema pattern drifts out
    of sync with the vocabulary spec, this test fails.
    """
    samples = [
        'action("treasury.read.balance")',
        'env("prod")',
        "time($t)",
        'audience("did:web:wakir.dev:personas:treasury-agent")',
        'operation("submit_tx")',
        "action_count_max(10)",
        "read_only(true)",
        'attests("4f9c8a3b1e7d2c0a9f8b6e5d4c3b2a190806e9d1")',
        'wat_anchor("anchor-2026-05-06-w19")',
        "rate_limit(100)",
        'agent_did("did:web:wakir.dev:personas:cfo-agent")',
        'parent_token("c1b2d3e4f50617283940a1b2c3d4e5f60718293a")',
        'nonce("a3f1b2c3d4e5f60718293a4b5c6d7e8f")',
        "spawn_counter_max(8)",
        "attenuation_depth_max(3)",
        "tee_required(true)",
        'allowed_methods("GET,HEAD")',
        'geo_region("EU")',
        "not_before(2026-05-06T00:00:00Z)",
        "not_after(2026-05-13T00:00:00Z)",
    ]
    for c in samples:
        datalog_caveat_validator.validate([c])


def test_negative_predicate_with_internal_paren_imbalance(
    datalog_caveat_validator,
) -> None:
    """A caveat with imbalanced parentheses is rejected by the pattern."""
    errors = list(
        datalog_caveat_validator.iter_errors([
            'action("treasury.read.balance"',  # missing closing paren
        ])
    )
    assert errors


def test_negative_array_of_array(datalog_caveat_validator) -> None:
    """Caveat entries are atomic strings, not nested arrays."""
    errors = list(
        datalog_caveat_validator.iter_errors([
            ['action("treasury.read.balance")'],
        ])
    )
    assert errors
