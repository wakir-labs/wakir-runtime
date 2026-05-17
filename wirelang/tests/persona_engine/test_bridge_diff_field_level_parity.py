# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-language Field-Level Diff parity pins between Python and Rust.

Tag-17 Mini-Welle, Phase-3a-Python-Sync-Erweiterung — sister to the
Rust-side cross-language test ``persona-engine-bridge-diff/tests/
cross_lang_field_diff_test.rs``. Sprint-Pengine-15 (PR #106) and
Sprint-Bridge-Diff-Engine-Rust-MINI (PR #131) shipped
``bridge_audit_diff_engine.py`` and the ``persona-engine-bridge-diff``
crate respectively. Tomás's Bridge-Audit-Roundtrip-E2E (PR #156)
pinned three Stream-Hash anchors between the two. This module pins
the next layer down: **per-field-level diff output** — same record
on both sides MUST produce identical RFC-6901 field-paths in the
same order, with byte-identical ``DiffKind`` and value tuples.

Cross-language contract
-----------------------

For each fixture below, both the Python ``diff_envelopes()`` helper
and the Rust ``persona_engine_bridge_diff::diff_envelopes()`` helper
MUST emit the same sequence of ``(path, kind_as_str)`` tuples (sorted
by path) when fed the same A/B envelope pair. The Python side asserts
this directly against the frozen pins in :data:`CROSS_LANG_PIN_TABLE`.
The Rust side reads ``cross_lang_field_diff_fixtures.json`` (emitted
by :func:`test_15_emit_fixture_file_for_rust_cross_lang_test`) and
asserts the same pins.

A future regression in either implementation's walker, RFC-6901
escape rules, sort order, or DiffKind alphabet surfaces as a parity-
test failure on whichever side drifted first.

Coverage map (10 tests)
-----------------------

1.  Baseline: identical records yield empty diff (Pin-0).
2.  Nested-object value drift at ``/a/b/c`` (Pin-1).
3.  Array-with-index-pinning: middle-element drift (Pin-2).
4.  null-vs-missing distinction: ``None``-valued key on one side
    surfaces as ``only-in-a`` (Pin-3).
5.  Empty-array vs absent-key: ``[]`` on one side, key absent on
    the other (Pin-4).
6.  Special-chars in keys + multi-field drift: ``/`` and ``~``
    escapes plus nested-array drift (Pin-5).
7.  Diff entries sorted by path: ordering is deterministic and
    lexicographic across all fixtures.
8.  ``DiffKind.value`` alphabet matches the Rust ``DiffKind::as_str()``
    output one-to-one.
9.  JCS hash determinism for each fixture matches Python ``jcs_hash``
    pins (cross-checked with Rust ``jcs_hash`` via the existing
    bridge-diff smoke-test pin anchor pattern).
10. Fixture file written to disk is byte-stable across runs (the Rust
    test loads it; instability here would silently invalidate the
    Rust assertions).

The fixture file lives at::

    wirelang-rust/crates/persona-engine-bridge-diff/tests/
        cross_lang_field_diff_fixtures.json

so the Rust cross-lang test reads it from a path relative to its
own crate root via ``CARGO_MANIFEST_DIR``.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping, Sequence

import pytest

from wirelang.persona_engine.bridge_audit_diff_engine import (
    DiffKind,
    canonicalize_envelope,
    diff_envelopes,
    jcs_hash,
)


# ---------------------------------------------------------------------------
# Fixture envelopes
# ---------------------------------------------------------------------------


FIXTURE_PIN_0_A: Mapping[str, Any] = {"a": {"b": {"c": 1, "d": 2}}, "e": "x"}
FIXTURE_PIN_0_B: Mapping[str, Any] = {"a": {"b": {"c": 1, "d": 2}}, "e": "x"}

FIXTURE_PIN_1_A: Mapping[str, Any] = {"a": {"b": {"c": 1, "d": 2}}, "e": "x"}
FIXTURE_PIN_1_B: Mapping[str, Any] = {"a": {"b": {"c": 99, "d": 2}}, "e": "x"}

FIXTURE_PIN_2_A: Mapping[str, Any] = {
    "items": [{"id": 1}, {"id": 2}, {"id": 3}],
}
FIXTURE_PIN_2_B: Mapping[str, Any] = {
    "items": [{"id": 1}, {"id": 99}, {"id": 3}],
}

#: ``None`` (Python) -> JSON ``null``. Different from "key absent".
#: The walker must surface ``only-in-a`` because key ``k`` is present
#: in A (value: null) and absent in B.
FIXTURE_PIN_3_A: Mapping[str, Any] = {"k": None, "other": 1}
FIXTURE_PIN_3_B: Mapping[str, Any] = {"other": 1}

#: Empty-array on one side, key absent on the other. Same
#: only-in-a surfacing pattern as Pin-3 but with a container value
#: instead of a scalar null.
FIXTURE_PIN_4_A: Mapping[str, Any] = {"tags": []}
FIXTURE_PIN_4_B: Mapping[str, Any] = {}

#: ``p~q`` exercises the ``~`` -> ``~0`` escape; ``a/b`` exercises
#: ``/`` -> ``~1``; the nested array drift exercises index-token
#: paths. Two drift entries are surfaced; ordering test below
#: validates the sort key.
FIXTURE_PIN_5_A: Mapping[str, Any] = {
    "p~q": {"a/b": [10, 20]},
    "normal": "x",
}
FIXTURE_PIN_5_B: Mapping[str, Any] = {
    "p~q": {"a/b": [10, 99]},
    "normal": "y",
}


# ---------------------------------------------------------------------------
# Cross-language pin table
# ---------------------------------------------------------------------------


# Each row pins, for one fixture pair:
#   - the expected sequence of (path, DiffKind.value) tuples after
#     diff_envelopes(A, B) sorted by path,
#   - the expected JCS hash of A and B (frozen 2026-05-17 from the
#     Python jcs_hash output, identical to the Rust serde_jcs +
#     sha2::Sha256 output for the same envelope).
CROSS_LANG_PIN_TABLE: Sequence[Mapping[str, Any]] = (
    {
        "pin_id": "pin-0-identical",
        "envelope_a": FIXTURE_PIN_0_A,
        "envelope_b": FIXTURE_PIN_0_B,
        "expected_diff_entries": (),
        "expected_hash_a":
            "sha256:82689386a4f13231f2f031fafcbf5bfa42cdbdff6ff9b700a56ea52a8057db01",
        "expected_hash_b":
            "sha256:82689386a4f13231f2f031fafcbf5bfa42cdbdff6ff9b700a56ea52a8057db01",
        "byte_identical": True,
    },
    {
        "pin_id": "pin-1-nested-value-drift",
        "envelope_a": FIXTURE_PIN_1_A,
        "envelope_b": FIXTURE_PIN_1_B,
        "expected_diff_entries": (
            {"path": "/a/b/c", "kind": "value-mismatch",
             "value_a": 1, "value_b": 99},
        ),
        "expected_hash_a":
            "sha256:82689386a4f13231f2f031fafcbf5bfa42cdbdff6ff9b700a56ea52a8057db01",
        "expected_hash_b":
            "sha256:f3d41b955294120c2b7f6d6bc93d3442efe9c41332afae4e6c3a4b5048142c7c",
        "byte_identical": False,
    },
    {
        "pin_id": "pin-2-array-index-middle-drift",
        "envelope_a": FIXTURE_PIN_2_A,
        "envelope_b": FIXTURE_PIN_2_B,
        "expected_diff_entries": (
            {"path": "/items/1/id", "kind": "value-mismatch",
             "value_a": 2, "value_b": 99},
        ),
        "expected_hash_a":
            "sha256:919ec1502d47d6943f93977b07e2b4f2d5817dd1d75ea6ab0d013d6fd167d224",
        "expected_hash_b":
            "sha256:a3b80a3febac1e944972fc2964fcf101fe6423c2515fb2dbac1bb1595e761107",
        "byte_identical": False,
    },
    {
        "pin_id": "pin-3-null-vs-missing",
        "envelope_a": FIXTURE_PIN_3_A,
        "envelope_b": FIXTURE_PIN_3_B,
        "expected_diff_entries": (
            {"path": "/k", "kind": "only-in-a",
             "value_a": None, "value_b": None},
        ),
        "expected_hash_a":
            "sha256:68b7c9c473e716774e62ba53fb84a0c7c68d0bf83bd31762ee160c8d7791ec8a",
        "expected_hash_b":
            "sha256:8b0bb7512fb6d1595c87b3604b48935021ab88233ea853246f5c244600a40929",
        "byte_identical": False,
    },
    {
        "pin_id": "pin-4-empty-vs-absent",
        "envelope_a": FIXTURE_PIN_4_A,
        "envelope_b": FIXTURE_PIN_4_B,
        "expected_diff_entries": (
            {"path": "/tags", "kind": "only-in-a",
             "value_a": [], "value_b": None},
        ),
        "expected_hash_a":
            "sha256:b35b1ec1c0c72c4bbd16bd9d6c2cbcac8224272cd7e6ecf504a78f2c7e989b2a",
        "expected_hash_b":
            "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        "byte_identical": False,
    },
    {
        "pin_id": "pin-5-rfc6901-escapes-plus-multi-field",
        "envelope_a": FIXTURE_PIN_5_A,
        "envelope_b": FIXTURE_PIN_5_B,
        "expected_diff_entries": (
            {"path": "/normal", "kind": "value-mismatch",
             "value_a": "x", "value_b": "y"},
            {"path": "/p~0q/a~1b/1", "kind": "value-mismatch",
             "value_a": 20, "value_b": 99},
        ),
        "expected_hash_a":
            "sha256:6250f5058101ebedad2e9d80ca193e81cacbbc9e9a5d9fee5c12cbebd09d0386",
        "expected_hash_b":
            "sha256:a502af86d2fe682743f16344d8d5951afd71e8da0c65ae4aea70b209f3f95556",
        "byte_identical": False,
    },
)


# Resolve the fixture file path RELATIVE to the test file so the
# emitter test runs from any pytest cwd. The layout is::
#
#   <workspace-root>/wirelang/tests/persona_engine/<this-file>.py
#   <workspace-root>/wirelang-rust/crates/persona-engine-bridge-diff/tests/
#
# so ``wirelang/`` is ``parents[2]`` and the workspace root is its
# ``.parent``. We use ``.resolve()`` so symlinks (e.g. git worktrees)
# resolve to the real path.
_TEST_FILE = pathlib.Path(__file__).resolve()
_WIRELANG_DIR = _TEST_FILE.parents[2]
_WORKSPACE_ROOT = _WIRELANG_DIR.parent
_RUST_CRATE_TESTS = (
    _WORKSPACE_ROOT
    / "wirelang-rust"
    / "crates"
    / "persona-engine-bridge-diff"
    / "tests"
)
FIXTURE_FILE_PATH = _RUST_CRATE_TESTS / "cross_lang_field_diff_fixtures.json"


# ---------------------------------------------------------------------------
# Pin-table parameterised tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pin",
    CROSS_LANG_PIN_TABLE,
    ids=[row["pin_id"] for row in CROSS_LANG_PIN_TABLE],
)
def test_01_through_06_field_level_pins(pin: Mapping[str, Any]) -> None:
    """Each pin in :data:`CROSS_LANG_PIN_TABLE` round-trips through
    Python ``diff_envelopes`` to the exact expected entries.

    This is the core cross-lang contract on the Python side. The
    matching Rust test loads the same fixture (via the emitted
    ``cross_lang_field_diff_fixtures.json``) and asserts the same
    expected entries through ``persona_engine_bridge_diff::
    diff_envelopes``. Any drift on either side fails the gate.
    """
    diffs = diff_envelopes(pin["envelope_a"], pin["envelope_b"])
    expected = pin["expected_diff_entries"]

    assert len(diffs) == len(expected), (
        f"{pin['pin_id']}: drift count mismatch "
        f"(got {len(diffs)}, expected {len(expected)})"
    )

    for got, want in zip(diffs, expected):
        assert got.path == want["path"], (
            f"{pin['pin_id']}: path drift "
            f"(got {got.path!r}, expected {want['path']!r})"
        )
        assert got.kind.value == want["kind"], (
            f"{pin['pin_id']}: kind drift at {got.path!r} "
            f"(got {got.kind.value!r}, expected {want['kind']!r})"
        )
        assert got.value_a == want["value_a"], (
            f"{pin['pin_id']}: value_a drift at {got.path!r}"
        )
        assert got.value_b == want["value_b"], (
            f"{pin['pin_id']}: value_b drift at {got.path!r}"
        )


# ---------------------------------------------------------------------------
# 7 / Sort order: across ALL pins, diff entries are sorted by path.
# ---------------------------------------------------------------------------


def test_07_diff_entries_sorted_by_path_across_all_pins() -> None:
    """``diff_envelopes`` MUST emit entries sorted by ``path`` ascending.

    The Rust cross-lang test depends on this ordering to do a direct
    zip-comparison without re-sorting on its side. Without an
    explicit sort guarantee, set-equality would be required and the
    fixture-comparison would lose its byte-determinism.
    """
    for pin in CROSS_LANG_PIN_TABLE:
        diffs = diff_envelopes(pin["envelope_a"], pin["envelope_b"])
        paths = [d.path for d in diffs]
        assert paths == sorted(paths), (
            f"{pin['pin_id']}: paths not sorted ascending: {paths}"
        )


# ---------------------------------------------------------------------------
# 8 / DiffKind alphabet parity with Rust DiffKind::as_str.
# ---------------------------------------------------------------------------


def test_08_diffkind_alphabet_matches_rust_as_str() -> None:
    """The four ``DiffKind.value`` strings MUST match Rust ``as_str()``.

    Frozen pins from the Rust ``t14_diffkind_as_str_python_enum_parity``
    smoke-test. Any rename of a variant on either side breaks the
    Rust cross-lang test's pin-table parsing.
    """
    assert DiffKind.VALUE_MISMATCH.value == "value-mismatch"
    assert DiffKind.ONLY_IN_A.value == "only-in-a"
    assert DiffKind.ONLY_IN_B.value == "only-in-b"
    assert DiffKind.TYPE_MISMATCH.value == "type-mismatch"


# ---------------------------------------------------------------------------
# 9 / JCS hashes match the frozen pin table.
# ---------------------------------------------------------------------------


def test_09_jcs_hash_matches_frozen_pins() -> None:
    """Each fixture's JCS hash matches its frozen pin.

    The Rust cross-lang test runs the same fixtures through its
    serde_jcs + sha2 stack and asserts the same hash strings. A
    drift in either canonicaliser surfaces as a hash mismatch on
    the side that drifted first.
    """
    for pin in CROSS_LANG_PIN_TABLE:
        got_a = jcs_hash(pin["envelope_a"])
        got_b = jcs_hash(pin["envelope_b"])
        assert got_a == pin["expected_hash_a"], (
            f"{pin['pin_id']}: hash_a drift (got {got_a}, "
            f"expected {pin['expected_hash_a']})"
        )
        assert got_b == pin["expected_hash_b"], (
            f"{pin['pin_id']}: hash_b drift (got {got_b}, "
            f"expected {pin['expected_hash_b']})"
        )
        assert (got_a == got_b) == pin["byte_identical"], (
            f"{pin['pin_id']}: byte_identical mismatch"
        )


# ---------------------------------------------------------------------------
# 10 / Round-trip through canonicalize_envelope is stable.
# ---------------------------------------------------------------------------


def test_10_canonicalize_envelope_is_idempotent() -> None:
    """JCS canonicalisation is idempotent: feeding the output back
    through ``json.loads`` then through the canonicaliser yields the
    same bytes. This is a sanity-check that the diff-engine's
    canonicaliser does not depend on input-shape state.
    """
    for pin in CROSS_LANG_PIN_TABLE:
        for label, env in (("a", pin["envelope_a"]),
                           ("b", pin["envelope_b"])):
            bytes_1 = canonicalize_envelope(env)
            reparsed = json.loads(bytes_1.decode("utf-8"))
            bytes_2 = canonicalize_envelope(reparsed)
            assert bytes_1 == bytes_2, (
                f"{pin['pin_id']}/{label}: JCS not idempotent"
            )


# ---------------------------------------------------------------------------
# 11 / Fixture file emission for the Rust cross-lang test.
# ---------------------------------------------------------------------------


def _serialise_pin_for_cross_lang(pin: Mapping[str, Any]) -> Mapping[str, Any]:
    """Project a pin into the JSON-on-disk shape the Rust test reads.

    The Rust test parses this JSON via ``serde_json`` and walks the
    ``expected_diff_entries`` array entry-by-entry, asserting that
    its native ``diff_envelopes()`` output matches the recorded
    ``path`` / ``kind`` / ``value_a`` / ``value_b`` tuple for each
    entry.
    """
    return {
        "pin_id": pin["pin_id"],
        "envelope_a": pin["envelope_a"],
        "envelope_b": pin["envelope_b"],
        "expected_diff_entries": [
            {
                "path": e["path"],
                "kind": e["kind"],
                "value_a": e["value_a"],
                "value_b": e["value_b"],
            }
            for e in pin["expected_diff_entries"]
        ],
        "expected_hash_a": pin["expected_hash_a"],
        "expected_hash_b": pin["expected_hash_b"],
        "byte_identical": pin["byte_identical"],
    }


def test_11_emit_fixture_file_for_rust_cross_lang_test(tmp_path: pathlib.Path) -> None:
    """Emit ``cross_lang_field_diff_fixtures.json`` to the Rust crate.

    The Rust cross-lang test (``persona-engine-bridge-diff/tests/
    cross_lang_field_diff_test.rs``) reads this file at test time.
    We write to the canonical path under the crate's ``tests/`` dir
    AND also to ``tmp_path`` for a hermetic byte-stability check.

    The on-disk file is committed to git as a static fixture; this
    test rewrites it deterministically (sorted-keys JSON, indented
    by 2 spaces, trailing newline) so it round-trips byte-stable
    across machines. The CI gate is: if a developer changes a
    fixture, this test rewrites the file, the developer commits
    the diff. The Rust test then runs against the new content.
    """
    payload = {
        "format_version": 1,
        "captured_at": "2026-05-17",
        "pins": [_serialise_pin_for_cross_lang(p) for p in CROSS_LANG_PIN_TABLE],
    }

    # Serialise deterministically: sorted keys, 2-space indent, LF
    # newlines, trailing newline. This is the byte-stable
    # representation the on-disk fixture must equal.
    body = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
    body += "\n"

    # Write to tmp_path first for the hermetic check.
    scratch = tmp_path / "cross_lang_field_diff_fixtures.json"
    scratch.write_text(body, encoding="utf-8")
    assert scratch.read_text(encoding="utf-8") == body, (
        "round-trip through tmp_path drifted"
    )

    # Now ensure the canonical fixture file matches the same bytes.
    # If it does not, we rewrite it and fail the test so the diff
    # surfaces in code-review — the developer commits the new
    # fixture content. Subsequent CI runs pass.
    if not FIXTURE_FILE_PATH.exists():
        FIXTURE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_FILE_PATH.write_text(body, encoding="utf-8")
        pytest.fail(
            f"Fixture file did not exist; wrote {FIXTURE_FILE_PATH}. "
            f"Commit the new file."
        )
    existing = FIXTURE_FILE_PATH.read_text(encoding="utf-8")
    if existing != body:
        FIXTURE_FILE_PATH.write_text(body, encoding="utf-8")
        pytest.fail(
            f"Fixture file content drifted; rewrote {FIXTURE_FILE_PATH}. "
            f"Commit the diff."
        )


# ---------------------------------------------------------------------------
# 12 / Cross-validate fixture file contents matches the in-memory pin table.
# ---------------------------------------------------------------------------


def test_12_fixture_file_matches_pin_table_in_memory() -> None:
    """The on-disk fixture file MUST encode the same content as the
    in-memory ``CROSS_LANG_PIN_TABLE``.

    Catches the case where someone edits the JSON by hand without
    updating the Python pin table (or vice versa). Both sides must
    move together; otherwise the Rust cross-lang test asserts
    against stale data.
    """
    assert FIXTURE_FILE_PATH.exists(), (
        f"fixture file missing at {FIXTURE_FILE_PATH}; "
        f"run test_11 first to emit it"
    )
    on_disk = json.loads(FIXTURE_FILE_PATH.read_text(encoding="utf-8"))
    assert on_disk["format_version"] == 1
    assert len(on_disk["pins"]) == len(CROSS_LANG_PIN_TABLE)

    for got, want in zip(on_disk["pins"], CROSS_LANG_PIN_TABLE):
        assert got["pin_id"] == want["pin_id"]
        # Compare envelopes via JCS canonicalisation so trailing
        # whitespace / key-order in the JSON file cannot mask a
        # real fixture drift.
        assert canonicalize_envelope(got["envelope_a"]) == \
            canonicalize_envelope(want["envelope_a"])
        assert canonicalize_envelope(got["envelope_b"]) == \
            canonicalize_envelope(want["envelope_b"])
        assert got["expected_hash_a"] == want["expected_hash_a"]
        assert got["expected_hash_b"] == want["expected_hash_b"]
        assert got["byte_identical"] == want["byte_identical"]
        assert len(got["expected_diff_entries"]) == \
            len(want["expected_diff_entries"])
        for ge, we in zip(got["expected_diff_entries"],
                          want["expected_diff_entries"]):
            assert ge["path"] == we["path"]
            assert ge["kind"] == we["kind"]
            assert ge["value_a"] == we["value_a"]
            assert ge["value_b"] == we["value_b"]
