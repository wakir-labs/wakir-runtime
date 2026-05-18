# SPDX-License-Identifier: Apache-2.0
"""Tag-49 hermetic Cross-Lang-Pin-Coverage refresh for
`persona-engine-federation-resolver` post Spec v0.4.1.

Tag-48 PR #308 added `persona-engine-federation-resolver` as Row 16
to the wirelang-spec-v0-4-1.md §3.1 catalogue. Tag-49 verifies the
Cross-Lang-Pin-Coverage promise is intact:

- Python sibling exists and exposes the documented constants /
  authority surface.
- Rust crate exists with non-trivial source and the same constants.
- Cross-lang fixture file exists, schema-version matches, and the
  five pinned vectors are structurally well-formed.
- The V-907-pin-pack lists federation-resolver with consistent
  python_authority, selector_env, and binary_env wiring.

This suite is purely a static-pass over the working copy: no NATS,
no engine boot, no Rust build, no network. The actual byte-parity
(fixture-vs-Rust, fixture-vs-Python) is enforced by
`tests/identity/test_federation_resolver_cross_lang_parity.py`
(Python, 26 cases) and
`wirelang-rust/crates/persona-engine-federation-resolver/tests/`
(Rust, 21 cases combined unit+integration). Tag-49 keeps the
boundary between "byte-parity enforced" and "wiring-pin enforced"
explicit by separating into two suites.

Drift discovery (DRIFT-S4 candidate, not patched in Tag-49):
-----------------------------------------------------------

A separate, larger drift between Spec v0.4.0/v0.4.1 §4.1 (the nine
ENV-flag engine components, named `WAKIR_PE_*_BACKEND`, components
#1-#9 = v907_verify, svid_workload_identity, bridge_audit_writer,
state_backing, lifecycle_state_machine, subscribe_loop,
recovery_workflow, canonical_form, anchor_emitter) and the
pin-pack-0.5.0-pre-cutover.yaml §boot_wired_crates (nine wired
crates named `WAKIR_*_BACKEND` without the `_PE_` infix, with
federation-resolver in slot #9 in place of canonical_form) is
beyond the Tag-49 cross-lang-pin scope. This is recorded as a
DRIFT-S4 candidate in the Tag-49 done report for CEO triage and is
NOT reconciled here. The Tag-49 cross-lang-pin promise
(Python+Rust byte-parity for federation-resolver) is independent
of this naming-and-counting drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PY_SIBLING = (
    REPO_ROOT / "wirelang" / "identity" / "federation_resolver_canonical.py"
)
RUST_CRATE_DIR = (
    REPO_ROOT
    / "wirelang-rust"
    / "crates"
    / "persona-engine-federation-resolver"
)
RUST_LIB = RUST_CRATE_DIR / "src" / "lib.rs"
RUST_FIXTURE_TEST = (
    RUST_CRATE_DIR / "tests" / "federation_resolver_cross_lang_fixture_test.rs"
)
FIXTURE_FILE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "federation-resolver-cross-lang"
    / "fixtures.json"
)
PY_PARITY_TEST = (
    REPO_ROOT
    / "tests"
    / "identity"
    / "test_federation_resolver_cross_lang_parity.py"
)
PIN_PACK_PATH = (
    REPO_ROOT / "infra" / "persona-engine" / "pin-pack-0.5.0-pre-cutover.yaml"
)
SPEC_V041 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-1.md"

EXPECTED_SCHEMA = "wakir.federation.resolver-snapshot/1"
EXPECTED_FIXTURE_NAMES = (
    "f01-empty-resolver",
    "f02-single-org-multi-cluster",
    "f03-multi-org-disjoint",
    "f04-key-rotation-history",
    "f05-expired-mapping",
)
EXPECTED_CONSTANTS = {
    "FEDERATION_RESOLVER_SCHEMA": EXPECTED_SCHEMA,
    "HASH_PREFIX": "sha256:",
    "SHA256_HEX_LEN": "64",
    "PUBLIC_KEY_HEX_LEN": "64",
    "DEFAULT_ALG": "Ed25519",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_t01_python_sibling_exists_and_nontrivial() -> None:
    """Python authority module exists with >=100 LoC (substance floor)."""
    assert PY_SIBLING.is_file(), f"Python sibling missing: {PY_SIBLING}"
    loc = sum(1 for _ in PY_SIBLING.read_text().splitlines())
    assert loc >= 100, (
        f"Python sibling has only {loc} LoC; Tag-49 contract requires "
        f">=100 LoC for federation_resolver_canonical.py (it is the "
        f"Python authority for the byte-stable snapshot surface)."
    )


def test_t02_rust_crate_exists_and_nontrivial() -> None:
    """Rust crate exists with Cargo.toml and lib.rs >=100 LoC."""
    assert (RUST_CRATE_DIR / "Cargo.toml").is_file(), (
        f"Rust crate Cargo.toml missing: {RUST_CRATE_DIR / 'Cargo.toml'}"
    )
    assert RUST_LIB.is_file(), f"Rust crate lib.rs missing: {RUST_LIB}"
    loc = sum(1 for _ in RUST_LIB.read_text().splitlines())
    assert loc >= 100, (
        f"Rust crate lib.rs has only {loc} LoC; Tag-49 contract requires "
        f">=100 LoC for persona-engine-federation-resolver/src/lib.rs."
    )


def test_t03_python_constants_match_pinned_values() -> None:
    """All five documented constants are present in Python sibling
    with the byte-exact pinned values."""
    py_src = PY_SIBLING.read_text()
    for const_name, const_value in EXPECTED_CONSTANTS.items():
        # Accept both `NAME = "value"` (str) and `NAME = value` (int)
        candidates = (
            f'{const_name} = "{const_value}"',
            f"{const_name} = {const_value}",
        )
        assert any(c in py_src for c in candidates), (
            f"Python constant {const_name} not pinned to expected "
            f"value {const_value!r}; checked patterns: {candidates}"
        )


def test_t04_rust_constants_match_pinned_values() -> None:
    """All five documented constants are present in Rust crate
    with the byte-exact pinned values (`pub const` declarations)."""
    rust_src = RUST_LIB.read_text()
    expected_rust = {
        "FEDERATION_RESOLVER_SCHEMA": (
            f'pub const FEDERATION_RESOLVER_SCHEMA: &str = "{EXPECTED_SCHEMA}";'
        ),
        "HASH_PREFIX": 'pub const HASH_PREFIX: &str = "sha256:";',
        "SHA256_HEX_LEN": "pub const SHA256_HEX_LEN: usize = 64;",
        "PUBLIC_KEY_HEX_LEN": "pub const PUBLIC_KEY_HEX_LEN: usize = 64;",
        "DEFAULT_ALG": 'pub const DEFAULT_ALG: &str = "Ed25519";',
    }
    for const_name, decl in expected_rust.items():
        assert decl in rust_src, (
            f"Rust constant {const_name} not pinned with expected "
            f"declaration: {decl!r}"
        )


def test_t05_fixture_file_present_and_loadable() -> None:
    """Cross-lang fixture file exists, parses as JSON, and has the
    pinned schema_version + fixed_now_utc."""
    assert FIXTURE_FILE.is_file(), f"Fixture file missing: {FIXTURE_FILE}"
    data = json.loads(FIXTURE_FILE.read_text())
    assert data["schema_version"] == EXPECTED_SCHEMA, (
        f"Fixture schema_version drift: got {data['schema_version']!r}, "
        f"expected {EXPECTED_SCHEMA!r}"
    )
    assert data["fixed_now_utc"] == "2026-05-17T00:00:00Z", (
        f"Fixture fixed_now_utc drift: got {data['fixed_now_utc']!r}"
    )


def test_t06_fixture_file_has_five_named_vectors() -> None:
    """Fixture file contains exactly the five pinned named vectors
    in the canonical order."""
    data = json.loads(FIXTURE_FILE.read_text())
    actual_names = tuple(f["name"] for f in data["fixtures"])
    assert actual_names == EXPECTED_FIXTURE_NAMES, (
        f"Fixture vector name drift: got {actual_names}, "
        f"expected {EXPECTED_FIXTURE_NAMES}"
    )


def test_t07_each_fixture_has_required_expected_keys() -> None:
    """Each of the five fixtures pins all four expected byte-parity
    keys: snapshot_jcs_bytes_b64, snapshot_jcs_bytes_len,
    snapshot_sha256_hex, snapshot_hash_prefixed."""
    data = json.loads(FIXTURE_FILE.read_text())
    required = {
        "snapshot_jcs_bytes_b64",
        "snapshot_jcs_bytes_len",
        "snapshot_sha256_hex",
        "snapshot_hash_prefixed",
    }
    for fix in data["fixtures"]:
        missing = required - set(fix["expected"].keys())
        assert not missing, (
            f"Fixture {fix['name']!r} missing expected keys: {missing}"
        )
        # Sanity: sha256_hex prefix matches snapshot_hash_prefixed
        assert (
            fix["expected"]["snapshot_hash_prefixed"]
            == "sha256:" + fix["expected"]["snapshot_sha256_hex"]
        ), (
            f"Fixture {fix['name']!r} has hash-prefix vs hex drift: "
            f"{fix['expected']['snapshot_hash_prefixed']!r} vs "
            f"{fix['expected']['snapshot_sha256_hex']!r}"
        )


def test_t08_each_fixture_has_resolve_probe() -> None:
    """Every fixture carries a resolve_probe block with the four
    required keys."""
    data = json.loads(FIXTURE_FILE.read_text())
    required_probe_keys = {"org_id", "cluster_id", "now_utc", "expected_match"}
    for fix in data["fixtures"]:
        assert "resolve_probe" in fix, (
            f"Fixture {fix['name']!r} missing resolve_probe block"
        )
        missing = required_probe_keys - set(fix["resolve_probe"].keys())
        assert not missing, (
            f"Fixture {fix['name']!r} resolve_probe missing keys: "
            f"{missing}"
        )


def test_t09_pin_pack_lists_federation_resolver_with_consistent_wiring() -> None:
    """V-907 pin-pack lists persona-engine-federation-resolver in
    boot_wired_crates with the documented python_authority,
    selector_env, binary_env, and fixtures path."""
    pin_pack = yaml.safe_load(PIN_PACK_PATH.read_text())
    wired = pin_pack.get("boot_wired_crates", [])
    fr = next(
        (
            c
            for c in wired
            if c["name"] == "persona-engine-federation-resolver"
        ),
        None,
    )
    assert fr is not None, (
        "persona-engine-federation-resolver not present in pin-pack "
        "boot_wired_crates list"
    )
    assert (
        fr["python_authority"] == "wirelang.identity.federation_resolver_canonical"
    ), (
        f"Pin-pack python_authority drift: got {fr['python_authority']!r}"
    )
    assert fr["selector_env"] == "WAKIR_FEDERATION_RESOLVER_BACKEND", (
        f"Pin-pack selector_env drift: got {fr['selector_env']!r}"
    )
    assert fr["binary_env"] == "WAKIR_RUST_FEDERATION_RESOLVER_BIN", (
        f"Pin-pack binary_env drift: got {fr['binary_env']!r}"
    )
    assert (
        fr["fixtures"]
        == "tests/fixtures/federation-resolver-cross-lang/fixtures.json"
    ), f"Pin-pack fixtures path drift: got {fr['fixtures']!r}"


def test_t10_pin_pack_python_authority_path_resolves_to_actual_file() -> None:
    """The python_authority dotted module name in the pin-pack
    corresponds to a real file under the working copy."""
    pin_pack = yaml.safe_load(PIN_PACK_PATH.read_text())
    fr = next(
        c
        for c in pin_pack["boot_wired_crates"]
        if c["name"] == "persona-engine-federation-resolver"
    )
    dotted = fr["python_authority"]
    # "wirelang.identity.federation_resolver_canonical" ->
    # "wirelang/identity/federation_resolver_canonical.py"
    rel = Path(*dotted.split(".")).with_suffix(".py")
    abs_path = REPO_ROOT / rel
    assert abs_path.is_file(), (
        f"Pin-pack python_authority {dotted!r} resolves to {abs_path}, "
        f"but no such file exists"
    )


def test_t11_pin_pack_fixtures_path_matches_actual_file() -> None:
    """The fixtures path in the pin-pack actually exists at that
    relative path."""
    pin_pack = yaml.safe_load(PIN_PACK_PATH.read_text())
    fr = next(
        c
        for c in pin_pack["boot_wired_crates"]
        if c["name"] == "persona-engine-federation-resolver"
    )
    abs_fixture = REPO_ROOT / fr["fixtures"]
    assert abs_fixture.is_file(), (
        f"Pin-pack fixtures path {fr['fixtures']!r} resolves to "
        f"{abs_fixture}, but no such file exists"
    )
    assert abs_fixture.resolve() == FIXTURE_FILE.resolve(), (
        f"Pin-pack fixtures path resolves to {abs_fixture}, "
        f"expected {FIXTURE_FILE}"
    )


def test_t12_spec_v041_row_16_acknowledges_federation_resolver() -> None:
    """Spec v0.4.1 §3.1.16 (Row 16) documents the federation-resolver
    with the canonical classification text."""
    spec_text = SPEC_V041.read_text()
    assert "3.1.16" in spec_text, "Spec v0.4.1 missing §3.1.16 header"
    assert "persona-engine-federation-resolver" in spec_text, (
        "Spec v0.4.1 does not mention persona-engine-federation-resolver"
    )
    assert "Off-Welle (boot)" in spec_text, (
        "Spec v0.4.1 missing Off-Welle (boot) Welle classification "
        "for row 16"
    )


def test_t13_python_parity_test_suite_references_fixture_file() -> None:
    """The Python parity test suite reads exactly the canonical
    fixtures.json file (no shadow copy)."""
    assert PY_PARITY_TEST.is_file(), (
        f"Python parity test missing: {PY_PARITY_TEST}"
    )
    src = PY_PARITY_TEST.read_text()
    assert "federation-resolver-cross-lang" in src and "fixtures.json" in src, (
        "Python parity test does not reference the canonical "
        "federation-resolver-cross-lang/fixtures.json path"
    )


def test_t14_rust_parity_test_suite_references_fixture_file() -> None:
    """The Rust parity test suite reads exactly the canonical
    fixtures.json file (no shadow copy)."""
    assert RUST_FIXTURE_TEST.is_file(), (
        f"Rust parity test missing: {RUST_FIXTURE_TEST}"
    )
    src = RUST_FIXTURE_TEST.read_text()
    assert "federation-resolver-cross-lang" in src and "fixtures.json" in src, (
        "Rust parity test does not reference the canonical "
        "federation-resolver-cross-lang/fixtures.json path"
    )


def test_t15_fixture_file_pin_date_consistent_with_tag_24() -> None:
    """The fixture file's documented pin-date is 2026-05-17
    (Tag-24 mini-welle), as cited by the Python sibling docstring."""
    assert "2026-05-17" in FIXTURE_FILE.read_text(), (
        "Fixture file does not document Tag-24 pin date 2026-05-17 "
        "in its _comment field; pin lineage cannot be verified."
    )


def test_t16_all_five_fixtures_pinned_sha256_hex_is_64_lowercase_hex() -> None:
    """Every fixture's snapshot_sha256_hex value is a 64-char
    lower-case hex string (well-formed SHA-256 hex pin)."""
    data = json.loads(FIXTURE_FILE.read_text())
    for fix in data["fixtures"]:
        h = fix["expected"]["snapshot_sha256_hex"]
        assert isinstance(h, str) and len(h) == 64, (
            f"Fixture {fix['name']!r} sha256 hex has wrong length: "
            f"{len(h)} (expected 64)"
        )
        assert all(c in "0123456789abcdef" for c in h), (
            f"Fixture {fix['name']!r} sha256 hex contains non-lower-hex "
            f"chars: {h!r}"
        )
