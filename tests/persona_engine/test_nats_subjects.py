# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for :mod:`wirelang.persona_engine.nats_subjects`.

These tests close the Tag-14 Python-Side-Sync loop:

- Each typed-builder function round-trips to the expected canonical
  subject string.
- Each invalid-input class raises :class:`SubjectError` with the
  correct ``kind`` and ``field`` attributes (parity with the Rust
  ``SubjectError`` discriminant tags).
- The 8 pin-pack fixtures are bit-identical between Rust and Python
  (the Rust strings are scraped out of
  ``wirelang-rust/crates/persona-engine-nats-subjects/src/lib.rs``
  if the file is in-tree; otherwise the Python-local constants are
  used as the contract pin).
- The SHA-256 over the ``\\n``-joined pin pack matches the pin
  published in the Rust crate's ``test_pin_pack_cross_lang_sha256``
  test (the test in this file owns the byte-identity assertion from
  the Python side; the Rust side asserts the same digest constant).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from wirelang.persona_engine import nats_subjects as subj
from wirelang.persona_engine.nats_subjects import (
    ALL_FIXTURES,
    FIXTURE_ANCHOR_SUBMITTED,
    FIXTURE_AUDIT_IDENTITY_ROTATE,
    FIXTURE_AUDIT_POLICY_VIOLATION,
    FIXTURE_FEDERATION_FRAME,
    FIXTURE_LIFECYCLE_DESPAWNED,
    FIXTURE_LIFECYCLE_SPAWNED,
    FIXTURE_RECOVERY_REPLAY,
    FIXTURE_RECOVERY_VERIFY,
    MAX_TOKEN_LEN,
    RESERVED_WORDS,
    SubjectError,
)

# ---------------------------------------------------------------------------
# Cross-language pin digest (parity contract)
# ---------------------------------------------------------------------------

# This digest is computed once over the canonical ``"\n"``-joined
# pin-pack and pinned here. The Rust-side test
# ``test_pin_pack_cross_lang_sha256`` pins the same hex string. Any
# change to the pin set (add / remove / reorder) requires a synced
# update on both sides — that is the whole point of the parity test.
#
# Hash derivation:
#   sha256("\n".join([
#       "persona.lifecycle.reza-2026-05-17.spawned",
#       "persona.lifecycle.reza-2026-05-17.despawned",
#       "persona.federation.cluster-eu-1.reza-2026-05-17.frame",
#       "persona.audit.identity-rotate.run-0001",
#       "persona.audit.policy-violation.run-0002",
#       "persona.anchor.batch-2026-05-17.submitted",
#       "persona.recovery.replay.run-0003",
#       "persona.recovery.verify.run-0003",
#   ]).encode("utf-8"))
PIN_PACK_SHA256_HEX = (
    "57a28150010f8a42f46b83a8c83d9939cfe27f3ae9133716a86b8d0886994976"
)


# ---------------------------------------------------------------------------
# 1. Typed-builder round-trip (5 tests, one per subject class)
# ---------------------------------------------------------------------------


def test_persona_lifecycle_subject_roundtrip() -> None:
    assert (
        subj.persona_lifecycle_subject("reza-2026-05-17", "spawned")
        == "persona.lifecycle.reza-2026-05-17.spawned"
    )


def test_persona_federation_subject_roundtrip() -> None:
    assert (
        subj.persona_federation_subject("cluster-eu-1", "reza-2026-05-17")
        == "persona.federation.cluster-eu-1.reza-2026-05-17.frame"
    )


def test_persona_audit_subject_roundtrip() -> None:
    assert (
        subj.persona_audit_subject("identity-rotate", "run-0001")
        == "persona.audit.identity-rotate.run-0001"
    )


def test_persona_anchor_subject_roundtrip() -> None:
    assert (
        subj.persona_anchor_subject("batch-2026-05-17")
        == "persona.anchor.batch-2026-05-17.submitted"
    )


def test_persona_recovery_subject_roundtrip() -> None:
    assert (
        subj.persona_recovery_subject("replay", "run-0003")
        == "persona.recovery.replay.run-0003"
    )


# ---------------------------------------------------------------------------
# 2. Invalid-input rejection (6 tests, one per SubjectError variant + edges)
# ---------------------------------------------------------------------------


def test_reject_token_with_dot_is_invalid_char() -> None:
    with pytest.raises(SubjectError) as exc_info:
        subj.persona_lifecycle_subject("foo.bar", "spawned")
    err = exc_info.value
    assert err.kind == "InvalidChar"
    assert err.field == "id"
    assert err.character == "."
    # Position must be after the first character (we accept the first
    # ASCII letter ``f`` and trip on the ``.`` at index 3).
    assert err.position == 3


def test_reject_empty_token_is_empty_token() -> None:
    with pytest.raises(SubjectError) as exc_info:
        subj.persona_audit_subject("", "run-1")
    err = exc_info.value
    assert err.kind == "EmptyToken"
    assert err.field == "kind"


def test_reject_reserved_word_star_is_reserved_word() -> None:
    with pytest.raises(SubjectError) as exc_info:
        subj.persona_lifecycle_subject("*", "spawned")
    err = exc_info.value
    assert err.kind == "ReservedWord"
    assert err.field == "id"
    assert err.value == "*"


def test_reject_reserved_word_gt_is_reserved_word() -> None:
    with pytest.raises(SubjectError) as exc_info:
        subj.persona_lifecycle_subject(">", "spawned")
    err = exc_info.value
    assert err.kind == "ReservedWord"
    assert err.field == "id"


def test_reject_token_too_long_reports_actual_and_max() -> None:
    long = "a" * (MAX_TOKEN_LEN + 1)
    with pytest.raises(SubjectError) as exc_info:
        subj.persona_lifecycle_subject(long, "spawned")
    err = exc_info.value
    assert err.kind == "TokenTooLong"
    assert err.field == "id"
    assert err.actual == MAX_TOKEN_LEN + 1
    assert err.max == MAX_TOKEN_LEN


def test_reject_leading_digit_is_leading_digit_variant() -> None:
    with pytest.raises(SubjectError) as exc_info:
        subj.persona_lifecycle_subject("9abc", "spawned")
    err = exc_info.value
    assert err.kind == "LeadingDigit"
    assert err.field == "id"
    assert err.value == "9abc"


# ---------------------------------------------------------------------------
# 3. Wildcard-subscribe-pattern builders (5 tests)
# ---------------------------------------------------------------------------


def test_lifecycle_wildcard_all_events_emits_star_terminal() -> None:
    assert (
        subj.lifecycle_wildcard_all_events("reza-2026-05-17")
        == "persona.lifecycle.reza-2026-05-17.*"
    )


def test_lifecycle_wildcard_all_emits_gt_terminal() -> None:
    assert subj.lifecycle_wildcard_all() == "persona.lifecycle.>"


def test_federation_wildcard_by_cluster() -> None:
    assert (
        subj.federation_wildcard_by_cluster("cluster-eu-1")
        == "persona.federation.cluster-eu-1.>"
    )


def test_persona_root_wildcard() -> None:
    assert subj.persona_root_wildcard() == "persona.>"


def test_audit_wildcard_by_kind() -> None:
    assert (
        subj.audit_wildcard_by_kind("identity-rotate")
        == "persona.audit.identity-rotate.*"
    )


# ---------------------------------------------------------------------------
# 4. Pin-pack integrity (3 tests)
# ---------------------------------------------------------------------------


def test_pin_pack_count_is_exactly_eight() -> None:
    assert len(ALL_FIXTURES) == 8, "Cross-Lang pin-pack MUST have exactly 8 fixtures"


def test_pin_pack_each_fixture_reproducible_by_builder() -> None:
    # If the builder output drifts from the constant, the parity
    # contract with Rust silently breaks. We re-derive each fixture
    # and compare.
    assert FIXTURE_LIFECYCLE_SPAWNED == subj.persona_lifecycle_subject(
        "reza-2026-05-17", "spawned"
    )
    assert FIXTURE_LIFECYCLE_DESPAWNED == subj.persona_lifecycle_subject(
        "reza-2026-05-17", "despawned"
    )
    assert FIXTURE_FEDERATION_FRAME == subj.persona_federation_subject(
        "cluster-eu-1", "reza-2026-05-17"
    )
    assert FIXTURE_AUDIT_IDENTITY_ROTATE == subj.persona_audit_subject(
        "identity-rotate", "run-0001"
    )
    assert FIXTURE_AUDIT_POLICY_VIOLATION == subj.persona_audit_subject(
        "policy-violation", "run-0002"
    )
    assert FIXTURE_ANCHOR_SUBMITTED == subj.persona_anchor_subject(
        "batch-2026-05-17"
    )
    assert FIXTURE_RECOVERY_REPLAY == subj.persona_recovery_subject(
        "replay", "run-0003"
    )
    assert FIXTURE_RECOVERY_VERIFY == subj.persona_recovery_subject(
        "verify", "run-0003"
    )


def test_pin_pack_no_duplicates() -> None:
    assert len(set(ALL_FIXTURES)) == len(
        ALL_FIXTURES
    ), "Pin-pack contains duplicate subject"


# ---------------------------------------------------------------------------
# 5. Cross-language SHA-256 parity (1 test, the core invariant)
# ---------------------------------------------------------------------------


def test_pin_pack_cross_lang_sha256_matches_pinned_digest() -> None:
    # Compute the SHA-256 over the canonical ``\n``-joined pin-pack
    # and assert it equals the pinned hex digest. The same digest is
    # asserted on the Rust side in
    # ``test_pin_pack_cross_lang_sha256``.
    digest = subj.pin_pack_sha256_hex()
    assert (
        digest == PIN_PACK_SHA256_HEX
    ), f"pin-pack digest drift: got {digest}, pinned {PIN_PACK_SHA256_HEX}"

    # Also sanity-check the hashlib path independently of the helper.
    payload = "\n".join(ALL_FIXTURES).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == PIN_PACK_SHA256_HEX


# ---------------------------------------------------------------------------
# 6. Cross-language source-of-truth scrape (1 test, defensive)
# ---------------------------------------------------------------------------


def _rust_crate_lib_path() -> Path:
    """Return the in-tree path to the Rust crate's ``lib.rs``.

    Returns the absolute path even if the file does not exist; the
    caller decides whether to skip the test.
    """

    here = Path(__file__).resolve()
    # tests/persona_engine/ -> repo-root
    repo_root = here.parents[2]
    return (
        repo_root
        / "wirelang-rust"
        / "crates"
        / "persona-engine-nats-subjects"
        / "src"
        / "lib.rs"
    )


def test_pin_pack_matches_rust_source_constants_when_available() -> None:
    rust_lib = _rust_crate_lib_path()
    if not rust_lib.is_file():
        pytest.skip(
            f"Rust crate lib.rs not in-tree at {rust_lib}; "
            "the cross-lang SHA-256 parity test above is the contract pin."
        )
    rust_src = rust_lib.read_text(encoding="utf-8")

    # Each Python fixture constant must appear as a literal string in
    # the Rust source (the Rust crate defines them as
    # ``pub const FIXTURE_* : &str = "..."``). We grep for the literal
    # rather than parse Rust syntax: any drift triggers a clear-failure.
    for name, value in [
        ("FIXTURE_LIFECYCLE_SPAWNED", FIXTURE_LIFECYCLE_SPAWNED),
        ("FIXTURE_LIFECYCLE_DESPAWNED", FIXTURE_LIFECYCLE_DESPAWNED),
        ("FIXTURE_FEDERATION_FRAME", FIXTURE_FEDERATION_FRAME),
        ("FIXTURE_AUDIT_IDENTITY_ROTATE", FIXTURE_AUDIT_IDENTITY_ROTATE),
        ("FIXTURE_AUDIT_POLICY_VIOLATION", FIXTURE_AUDIT_POLICY_VIOLATION),
        ("FIXTURE_ANCHOR_SUBMITTED", FIXTURE_ANCHOR_SUBMITTED),
        ("FIXTURE_RECOVERY_REPLAY", FIXTURE_RECOVERY_REPLAY),
        ("FIXTURE_RECOVERY_VERIFY", FIXTURE_RECOVERY_VERIFY),
    ]:
        # Each constant must be present as a string literal in the
        # Rust source. We bind to the constant name to make the
        # diagnostic readable when a drift occurs.
        pattern = re.compile(
            rf'pub const {re.escape(name)}\s*:\s*&str\s*=\s*\n?\s*"{re.escape(value)}"\s*;',
            re.MULTILINE,
        )
        assert pattern.search(rust_src), (
            f"Rust crate is missing or has drifted constant {name} "
            f"= {value!r} (searched in {rust_lib})"
        )


# ---------------------------------------------------------------------------
# 7. Token-validation API surface (2 tests, defensive)
# ---------------------------------------------------------------------------


def test_is_valid_token_examples_match_rust_truth_table() -> None:
    # Mirror the Rust ``test_is_valid_token_examples`` truth table.
    assert subj.is_valid_token("reza")
    assert subj.is_valid_token("reza-2026-05-17")
    assert subj.is_valid_token("a")
    assert subj.is_valid_token("a_b-c")
    assert not subj.is_valid_token("")
    assert not subj.is_valid_token("*")
    assert not subj.is_valid_token(">")
    assert not subj.is_valid_token("9abc")
    assert not subj.is_valid_token("a.b")
    assert not subj.is_valid_token("a b")


def test_reserved_words_constant_is_exhaustive() -> None:
    # The Rust crate exports the same three reserved words; the order
    # is part of the cross-language contract for any future structural
    # consumer (e.g. a config-file dumper).
    assert RESERVED_WORDS == (">", "*", "")
