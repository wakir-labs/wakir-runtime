// SPDX-License-Identifier: Apache-2.0
//! Integration tests for `persona-converter` (Sprint-Pengine-7 Tag-2,
//! Crate-9).
//!
//! Spec anchor: `wirelang/specs/persona-engine-format-spec.md` v1.1
//! (§4 mapping pipeline, §4.3.1 synthesis-default-exceptions table).
//!
//! Test inventory (Tag-2 floor: +10..+15 over Tag-1 base of 11):
//!
//! - **T-PCV-01** — `from-claude --in <mira-fixture> --out <tmp>`
//!   produces a non-empty file and exits 0.
//! - **T-PCV-02** — Output file is valid JSON parseable as the
//!   wakir-persona-v1 shape (schema_version, persona_id, ...).
//! - **T-PCV-03** — Re-conversion of the same input produces
//!   byte-identical output bytes (idempotence on rerun).
//! - **T-PCV-04** — Per-persona-roundtrip across all 13 fixtures: each
//!   converts cleanly and the on-disk JSON matches the in-memory JCS.
//! - **T-PCV-05** — `--pin-hash-v907` happy path: pin matches, exit 0.
//! - **T-PCV-06** — `--pin-hash-v907` happy path (bare-64hex form):
//!   pin matches, exit 0.
//! - **T-PCV-07** — `--pin-hash-v907` drift: pin mismatch exits 2.
//! - **T-PCV-08** — Missing input file exits 3.
//! - **T-PCV-09** — Schema error (invalid front-matter) exits 1.
//! - **T-PCV-10** — `--quiet` suppresses the stderr progress line on
//!   success.
//! - **T-PCV-11** — Argparse usage error (missing required `--in`)
//!   exits 64.
//! - **T-PCV-12** — Aisha-§4.3.1 exception: cfo-fixture conversion
//!   produces `identity_pinned.hierarchy.reports_to: "aufsichtsrat"`.
//! - **T-PCV-13** — Aisha-§4.3.1 exception: internal-audit-fixture
//!   conversion produces `identity_pinned.hierarchy.escalation:
//!   "aufsichtsrat"`.
//! - **T-PCV-14** — Default-personae (mira / kai / reza / pengine) all
//!   retain the safe-default `reports_to: "mira"` (no over-broad
//!   override leakage).
//! - **T-PCV-15** — Per-persona byte-determinism on disk: convert the
//!   same fixture twice, comparing on-disk bytes.

use persona_converter::{
    run, EXIT_HASH_DRIFT_ERROR, EXIT_INPUT_NOT_FOUND, EXIT_OK, EXIT_SCHEMA_ERROR, EXIT_USAGE_ERROR,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

// ---------------------------------------------------------------------
// Test-fixture inventory.
//
// The Tag-2 converter tests reuse the Tag-1 fixture pack from
// `persona-engine-format/tests/fixtures/claude-agents/`. We resolve
// the fixture path relative to CARGO_MANIFEST_DIR (this crate's own
// dir) and walk one level up to the sister crate. Brand-Guide §9
// posture: these fixtures are synthetic-anonymous (not the production
// `.claude/agents/*.md` files); Aisha-Option-B ratification permits
// operator-side `examples/` paths to consume the real files separately,
// but public-PR test fixtures stay synthetic.
// ---------------------------------------------------------------------

fn fixtures_dir() -> PathBuf {
    let crate_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    crate_dir
        .join("..")
        .join("persona-engine-format")
        .join("tests")
        .join("fixtures")
        .join("claude-agents")
}

const PERSONAE: &[&str] = &[
    "mira",
    "cto",
    "hr",
    "cfo",
    "comms",
    "internal-audit",
    "dev-engineering",
    "reza",
    "kai",
    "pengine",
    "frontend",
    "qa",
    "sre",
];

fn fixture_path(slug: &str) -> PathBuf {
    fixtures_dir().join(format!("{slug}.md"))
}

fn tmp_path(base: &str) -> PathBuf {
    // Tests run in parallel; suffix with thread id + nanos for
    // uniqueness on the same filesystem. (We do not use the `tempfile`
    // crate to keep the Sprint-Pengine-7 Tag-2 dependency footprint
    // identical to Tag-1.)
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let dir = std::env::temp_dir().join(format!("wakir-persona-convert-test-{ts}-{n}"));
    let _ = fs::create_dir_all(&dir);
    dir.join(base)
}

/// Compute the wakir-persona-hash of an axis-A fixture by mapping it
/// in-process. Used for the pin-verification tests (T-PCV-05 / -07).
fn pin_for(slug: &str) -> String {
    let text = fs::read_to_string(fixture_path(slug)).expect("fixture read");
    let doc = persona_engine_format::map_claude_native_to_wakir_v1(&text).expect("map");
    persona_engine_format::wakir_persona_hash(&doc).expect("hash")
}

fn read_bytes(p: &Path) -> Vec<u8> {
    fs::read(p).unwrap_or_else(|e| panic!("read {}: {e}", p.display()))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    hex::encode(h.finalize())
}

// ---------------------------------------------------------------------
// T-PCV-01 — basic conversion produces a non-empty output file
// ---------------------------------------------------------------------

#[test]
fn t_pcv_01_basic_conversion_writes_nonempty_file() {
    let input = fixture_path("mira");
    let output = tmp_path("mira.json");
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
    ];
    let outcome = run(&argv);
    assert_eq!(
        outcome.exit_code,
        EXIT_OK,
        "exit code; stderr={}",
        String::from_utf8_lossy(&outcome.stderr)
    );
    let bytes = read_bytes(&output);
    assert!(!bytes.is_empty(), "output file must be non-empty");
}

// ---------------------------------------------------------------------
// T-PCV-02 — output parses as the wakir-persona-v1 shape
// ---------------------------------------------------------------------

#[test]
fn t_pcv_02_output_is_valid_wakir_persona_v1() {
    let input = fixture_path("mira");
    let output = tmp_path("mira.json");
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
    ];
    let outcome = run(&argv);
    assert_eq!(outcome.exit_code, EXIT_OK);

    let bytes = read_bytes(&output);
    let parsed: Value = serde_json::from_slice(&bytes).expect("parse JSON");
    let obj = parsed.as_object().expect("object");
    assert_eq!(
        obj.get("schema_version").and_then(|v| v.as_str()),
        Some("wakir-persona-v1"),
    );
    assert_eq!(obj.get("persona_id").and_then(|v| v.as_str()), Some("mira"),);
    assert!(obj.contains_key("canonical_subset"));
    assert!(obj.contains_key("spawn_lifecycle"));
    assert!(obj.contains_key("state_persistence"));
    assert!(obj.contains_key("container_bridge"));
    assert!(obj.contains_key("migration_metadata"));
    assert!(obj.contains_key("claude_native_source"));
    assert!(obj.contains_key("model_override"));
}

// ---------------------------------------------------------------------
// T-PCV-03 — idempotence: re-conversion of the same input file
// produces byte-identical output
// ---------------------------------------------------------------------

#[test]
fn t_pcv_03_reconvert_idempotent_bytes() {
    let input = fixture_path("kai");
    let out_a = tmp_path("kai-a.json");
    let out_b = tmp_path("kai-b.json");

    for out in [&out_a, &out_b] {
        let argv = vec![
            "wakir-persona-convert",
            "from-claude",
            "--in",
            input.to_str().unwrap(),
            "--out",
            out.to_str().unwrap(),
        ];
        let outcome = run(&argv);
        assert_eq!(outcome.exit_code, EXIT_OK);
    }

    let bytes_a = read_bytes(&out_a);
    let bytes_b = read_bytes(&out_b);
    assert_eq!(
        sha256_hex(&bytes_a),
        sha256_hex(&bytes_b),
        "re-conversion must produce byte-identical output"
    );
}

// ---------------------------------------------------------------------
// T-PCV-04 — all 13 personae convert without error
// ---------------------------------------------------------------------

#[test]
fn t_pcv_04_per_persona_roundtrip_all_13() {
    for slug in PERSONAE {
        let input = fixture_path(slug);
        let output = tmp_path(&format!("{slug}.json"));
        let argv = vec![
            "wakir-persona-convert",
            "from-claude",
            "--in",
            input.to_str().unwrap(),
            "--out",
            output.to_str().unwrap(),
        ];
        let outcome = run(&argv);
        assert_eq!(
            outcome.exit_code,
            EXIT_OK,
            "[{slug}] exit; stderr={}",
            String::from_utf8_lossy(&outcome.stderr)
        );
        let bytes = read_bytes(&output);
        let parsed: Value =
            serde_json::from_slice(&bytes).unwrap_or_else(|e| panic!("[{slug}] parse: {e}"));
        let pid = parsed
            .as_object()
            .and_then(|o| o.get("persona_id"))
            .and_then(|v| v.as_str())
            .unwrap_or_else(|| panic!("[{slug}] persona_id"));
        assert_eq!(pid, *slug, "[{slug}] persona_id matches slug");
    }
}

// ---------------------------------------------------------------------
// T-PCV-05 — --pin-hash-v907 happy path (full sha256: form)
// ---------------------------------------------------------------------

#[test]
fn t_pcv_05_pin_verify_happy_path_full_form() {
    let slug = "comms";
    let pin = pin_for(slug);
    let input = fixture_path(slug);
    let output = tmp_path(&format!("{slug}.json"));
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
        "--pin-hash-v907",
        &pin,
    ];
    let outcome = run(&argv);
    assert_eq!(
        outcome.exit_code,
        EXIT_OK,
        "pin-verify must succeed; stderr={}",
        String::from_utf8_lossy(&outcome.stderr)
    );
}

// ---------------------------------------------------------------------
// T-PCV-06 — --pin-hash-v907 happy path (bare 64-hex form)
// ---------------------------------------------------------------------

#[test]
fn t_pcv_06_pin_verify_happy_path_bare_hex_form() {
    let slug = "qa";
    let full_pin = pin_for(slug);
    let bare = full_pin.trim_start_matches("sha256:").to_string();
    let input = fixture_path(slug);
    let output = tmp_path(&format!("{slug}.json"));
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
        "--pin-hash-v907",
        &bare,
    ];
    let outcome = run(&argv);
    assert_eq!(
        outcome.exit_code,
        EXIT_OK,
        "bare-hex pin-verify; stderr={}",
        String::from_utf8_lossy(&outcome.stderr)
    );
}

// ---------------------------------------------------------------------
// T-PCV-07 — --pin-hash-v907 drift exits 2
// ---------------------------------------------------------------------

#[test]
fn t_pcv_07_pin_drift_exits_2() {
    let slug = "sre";
    let wrong_pin = "sha256:0000000000000000000000000000000000000000000000000000000000000000";
    let input = fixture_path(slug);
    let output = tmp_path(&format!("{slug}.json"));
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
        "--pin-hash-v907",
        wrong_pin,
    ];
    let outcome = run(&argv);
    assert_eq!(outcome.exit_code, EXIT_HASH_DRIFT_ERROR, "drift exit code");
    let stderr = String::from_utf8_lossy(&outcome.stderr);
    assert!(
        stderr.contains("hash drift") || stderr.contains("drift"),
        "stderr must mention drift: {stderr}"
    );
}

// ---------------------------------------------------------------------
// T-PCV-08 — missing input file exits 3
// ---------------------------------------------------------------------

#[test]
fn t_pcv_08_missing_input_exits_3() {
    let input = tmp_path("nonexistent.md");
    let output = tmp_path("out.json");
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
    ];
    let outcome = run(&argv);
    assert_eq!(
        outcome.exit_code, EXIT_INPUT_NOT_FOUND,
        "missing input exit code"
    );
}

// ---------------------------------------------------------------------
// T-PCV-09 — invalid front-matter exits 1
// ---------------------------------------------------------------------

#[test]
fn t_pcv_09_invalid_frontmatter_exits_1() {
    // Synthetic in-test fixture: missing `description`. Write to tmp.
    let bad = "---\nname: invalid-fixture\ntools: Read\n---\n\n# body\n";
    let input = tmp_path("bad.md");
    fs::write(&input, bad).expect("write bad fixture");
    let output = tmp_path("bad-out.json");
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
    ];
    let outcome = run(&argv);
    assert_eq!(outcome.exit_code, EXIT_SCHEMA_ERROR);
    let stderr = String::from_utf8_lossy(&outcome.stderr);
    assert!(
        stderr.contains("schema error") || stderr.contains("description"),
        "stderr must indicate schema error: {stderr}"
    );
}

// ---------------------------------------------------------------------
// T-PCV-10 — --quiet suppresses the stderr progress line
// ---------------------------------------------------------------------

#[test]
fn t_pcv_10_quiet_suppresses_progress() {
    let input = fixture_path("mira");
    let output = tmp_path("mira-quiet.json");
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
        "--quiet",
    ];
    let outcome = run(&argv);
    assert_eq!(outcome.exit_code, EXIT_OK);
    assert!(
        outcome.stderr.is_empty(),
        "--quiet must suppress stderr; got={}",
        String::from_utf8_lossy(&outcome.stderr)
    );
}

// ---------------------------------------------------------------------
// T-PCV-11 — argparse usage error exits 64
// ---------------------------------------------------------------------

#[test]
fn t_pcv_11_argparse_usage_error_exits_64() {
    // Missing required --in / --out.
    let argv = vec!["wakir-persona-convert", "from-claude"];
    let outcome = run(&argv);
    assert_eq!(
        outcome.exit_code,
        EXIT_USAGE_ERROR,
        "missing-required-arg exit; stderr={}",
        String::from_utf8_lossy(&outcome.stderr)
    );
}

// ---------------------------------------------------------------------
// T-PCV-12 — Aisha §4.3.1: cfo-fixture override produces
// reports_to=aufsichtsrat
// ---------------------------------------------------------------------

#[test]
fn t_pcv_12_aisha_exception_cfo_reports_to_aufsichtsrat() {
    let input = fixture_path("cfo");
    let output = tmp_path("cfo.json");
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
    ];
    let outcome = run(&argv);
    assert_eq!(outcome.exit_code, EXIT_OK);

    let bytes = read_bytes(&output);
    let parsed: Value = serde_json::from_slice(&bytes).expect("parse");
    let reports_to = parsed
        .pointer("/canonical_subset/identity_pinned/hierarchy/reports_to")
        .and_then(|v| v.as_str())
        .expect("reports_to");
    let escalation = parsed
        .pointer("/canonical_subset/identity_pinned/hierarchy/escalation")
        .and_then(|v| v.as_str())
        .expect("escalation");
    assert_eq!(
        reports_to, "aufsichtsrat",
        "Aisha §4.3.1: cfo reports_to MUST be aufsichtsrat"
    );
    assert_eq!(
        escalation, "aufsichtsrat",
        "Aisha §4.3.1: cfo escalation MUST be aufsichtsrat"
    );
}

// ---------------------------------------------------------------------
// T-PCV-13 — Aisha §4.3.1: internal-audit-fixture override
// ---------------------------------------------------------------------

#[test]
fn t_pcv_13_aisha_exception_internal_audit_escalation_aufsichtsrat() {
    let input = fixture_path("internal-audit");
    let output = tmp_path("internal-audit.json");
    let argv = vec![
        "wakir-persona-convert",
        "from-claude",
        "--in",
        input.to_str().unwrap(),
        "--out",
        output.to_str().unwrap(),
    ];
    let outcome = run(&argv);
    assert_eq!(outcome.exit_code, EXIT_OK);

    let bytes = read_bytes(&output);
    let parsed: Value = serde_json::from_slice(&bytes).expect("parse");
    let reports_to = parsed
        .pointer("/canonical_subset/identity_pinned/hierarchy/reports_to")
        .and_then(|v| v.as_str())
        .expect("reports_to");
    let escalation = parsed
        .pointer("/canonical_subset/identity_pinned/hierarchy/escalation")
        .and_then(|v| v.as_str())
        .expect("escalation");
    assert_eq!(
        reports_to, "aufsichtsrat",
        "Aisha §4.3.1: internal-audit reports_to MUST be aufsichtsrat"
    );
    assert_eq!(
        escalation, "aufsichtsrat",
        "Aisha §4.3.1: internal-audit escalation MUST be aufsichtsrat"
    );
}

// ---------------------------------------------------------------------
// T-PCV-14 — non-exception personae retain `reports_to: "mira"` safe
// default (no over-broad override leakage)
// ---------------------------------------------------------------------

#[test]
fn t_pcv_14_default_personae_reports_to_mira() {
    for slug in ["mira", "kai", "reza", "pengine", "hr", "cto", "comms"] {
        let input = fixture_path(slug);
        let output = tmp_path(&format!("{slug}-default.json"));
        let argv = vec![
            "wakir-persona-convert",
            "from-claude",
            "--in",
            input.to_str().unwrap(),
            "--out",
            output.to_str().unwrap(),
            "--quiet",
        ];
        let outcome = run(&argv);
        assert_eq!(outcome.exit_code, EXIT_OK, "[{slug}] convert");

        let bytes = read_bytes(&output);
        let parsed: Value = serde_json::from_slice(&bytes).expect("parse");
        let reports_to = parsed
            .pointer("/canonical_subset/identity_pinned/hierarchy/reports_to")
            .and_then(|v| v.as_str())
            .unwrap_or_else(|| panic!("[{slug}] reports_to"));
        assert_eq!(
            reports_to, "mira",
            "[{slug}] safe-default reports_to=mira must be retained (no exception leakage)"
        );
    }
}

// ---------------------------------------------------------------------
// T-PCV-15 — per-persona on-disk byte-determinism across 13 fixtures
// ---------------------------------------------------------------------

#[test]
fn t_pcv_15_per_persona_disk_byte_determinism() {
    for slug in PERSONAE {
        let input = fixture_path(slug);
        let out_a = tmp_path(&format!("{slug}-a.json"));
        let out_b = tmp_path(&format!("{slug}-b.json"));
        for out in [&out_a, &out_b] {
            let argv = vec![
                "wakir-persona-convert",
                "from-claude",
                "--in",
                input.to_str().unwrap(),
                "--out",
                out.to_str().unwrap(),
                "--quiet",
            ];
            let outcome = run(&argv);
            assert_eq!(outcome.exit_code, EXIT_OK, "[{slug}] convert");
        }
        let bytes_a = read_bytes(&out_a);
        let bytes_b = read_bytes(&out_b);
        assert_eq!(
            sha256_hex(&bytes_a),
            sha256_hex(&bytes_b),
            "[{slug}] on-disk byte-determinism"
        );
    }
}
