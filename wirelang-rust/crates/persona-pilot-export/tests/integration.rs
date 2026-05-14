// SPDX-License-Identifier: Apache-2.0
//! Integration tests for `persona-pilot-export` (ADR-0058 Schritt 8 CLI).
//!
//! Test inventory (T-PPE-01..12):
//! - T-PPE-01..02 — `normalise_pin` accepts/rejects forms.
//! - T-PPE-03 — empty workspace produces a manifest with file_count = 0.
//! - T-PPE-04 — workspace with one file produces a one-entry manifest
//!   with correct sha256 + size.
//! - T-PPE-05 — manifest entries sort by path (determinism).
//! - T-PPE-06 — `compute_workspace_state_hash` is byte-stable across
//!   two runs.
//! - T-PPE-07 — end-to-end `run_export` with a small persona-def fixture
//!   produces a bundle of the expected shape.
//! - T-PPE-08 — `run_export` with `--pin-hash-v907` matching succeeds.
//! - T-PPE-09 — `run_export` with mismatching pin returns `HashDrift`.
//! - T-PPE-10 — `run_export` with missing `--persona-def` returns
//!   `InputNotFound`.
//! - T-PPE-11 — `bundle_to_jcs_bytes` is byte-deterministic across two runs.
//! - T-PPE-12 — round-trip: parse the JCS bytes back; PartialEq holds.

use std::fs;
use std::path::PathBuf;

use persona_pilot_export::{
    build_workspace_manifest, bundle_to_jcs_bytes, compute_workspace_state_hash, run_export, Cli,
    PilotExportError, PILOT_EXPORT_SCHEMA_VERSION,
};

// ---------------------------------------------------------------------
// Test fixture: minimal axis-A persona-definition for tomas-pilot
// rehearsal. Mirrors the .claude/agents/<slug>.md front-matter shape.
// ---------------------------------------------------------------------

const FIXTURE_PERSONA_DEF: &str = "---\nname: tomas\ndescription: Dev-Engineering + Matrix-Lead\ntools: [Read, Write, Edit, Bash]\n---\n\n# Tomás Reinhart — Pilot-Fixture\n\nFixture for the pilot-export rehearsal. Body is dropped from V-907 hash.\n";

fn write_persona_def(dir: &std::path::Path, body: &str) -> PathBuf {
    let p = dir.join("tomas.md");
    fs::write(&p, body).unwrap();
    p
}

fn make_cli(
    persona_def: PathBuf,
    workspace_dir: PathBuf,
    out: PathBuf,
    pin: Option<String>,
) -> Cli {
    Cli {
        persona_def,
        workspace_dir,
        out,
        exported_at_utc: "2026-05-14T16:30:00Z".into(),
        pin_hash_v907: pin,
        active_spawn_memory: None,
        quiet: true,
    }
}

// ---------------------------------------------------------------------
// T-PPE-01..02 — pin normalisation
// ---------------------------------------------------------------------

#[test]
fn t_ppe_01_pin_normalisation_accepts_valid_forms() {
    // Internal helper isn't pub; we exercise it indirectly via run_export
    // with a mismatching pin (a known-invalid hash) — but we also pin the
    // canonical accepted form via a successful run in T-PPE-08. This test
    // is the negative anchor: a non-hex string fails as SchemaError
    // (invalid pin) BEFORE the hash-drift check fires.
    let tmp = tempfile::tempdir().unwrap();
    let pd = write_persona_def(tmp.path(), FIXTURE_PERSONA_DEF);
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    let out = tmp.path().join("export.json");
    let cli = make_cli(pd, ws, out, Some("not-a-hex-string".into()));
    let err = run_export(&cli).unwrap_err();
    match err {
        PilotExportError::SchemaError(m) => {
            assert!(
                m.contains("--pin-hash-v907"),
                "schema error mentions the pin flag: {m}"
            );
        }
        other => panic!("expected SchemaError, got {other:?}"),
    }
}

#[test]
fn t_ppe_02_pin_normalisation_uppercase_hex_normalises() {
    // sha256:<64hex> is canonicalised to lowercase; an UPPERCASE-hex pin
    // matching the lowercase computed hash MUST succeed (T-PPE-08 pattern).
    let tmp = tempfile::tempdir().unwrap();
    let pd = write_persona_def(tmp.path(), FIXTURE_PERSONA_DEF);
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    let out = tmp.path().join("export.json");
    // First run without pin to obtain the canonical hash.
    let cli_no_pin = make_cli(pd.clone(), ws.clone(), out.clone(), None);
    let bundle = run_export(&cli_no_pin).expect("no-pin run ok");
    let canonical = bundle.v907_persona_hash.clone();
    let uppercase_hex = canonical
        .strip_prefix("sha256:")
        .expect("hash has prefix")
        .to_ascii_uppercase();
    // Re-run with UPPERCASE-hex pin — MUST succeed.
    let cli_upper = make_cli(pd, ws, out, Some(format!("SHA256:{uppercase_hex}")));
    run_export(&cli_upper).expect("uppercase pin succeeds (case-folded)");
}

// ---------------------------------------------------------------------
// T-PPE-03..05 — workspace manifest semantics
// ---------------------------------------------------------------------

#[test]
fn t_ppe_03_empty_workspace_zero_files() {
    let tmp = tempfile::tempdir().unwrap();
    let ws = tmp.path().join("empty-ws");
    fs::create_dir_all(&ws).unwrap();
    let m = build_workspace_manifest(&ws).expect("manifest ok");
    assert_eq!(m.file_count, 0);
    assert_eq!(m.total_size_bytes, 0);
    assert!(m.entries.is_empty());
}

#[test]
fn t_ppe_04_one_file_workspace_manifest_correct() {
    let tmp = tempfile::tempdir().unwrap();
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    fs::write(ws.join("CLAUDE.md"), b"hello-world").unwrap();
    let m = build_workspace_manifest(&ws).unwrap();
    assert_eq!(m.file_count, 1);
    assert_eq!(m.total_size_bytes, 11);
    assert_eq!(m.entries.len(), 1);
    assert_eq!(m.entries[0].path, "CLAUDE.md");
    // sha256("hello-world") canonical hex (verified via `echo -n hello-world | sha256sum`).
    assert_eq!(
        m.entries[0].sha256, "afa27b44d43b02a9fea41d13cedc2e4016cfcf87c5dbf990e593669aa8ce286d",
        "sha256 of 'hello-world' is canonical"
    );
}

#[test]
fn t_ppe_05_manifest_entries_sorted_by_path() {
    let tmp = tempfile::tempdir().unwrap();
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    // Create files in non-lex order; recursion will iter them in OS-defined
    // order. The sort step guarantees lex output regardless.
    fs::write(ws.join("z.txt"), b"z").unwrap();
    fs::write(ws.join("a.txt"), b"a").unwrap();
    fs::write(ws.join("m.txt"), b"m").unwrap();
    fs::create_dir_all(ws.join("sub")).unwrap();
    fs::write(ws.join("sub").join("b.txt"), b"b").unwrap();

    let m = build_workspace_manifest(&ws).unwrap();
    let paths: Vec<&str> = m.entries.iter().map(|e| e.path.as_str()).collect();
    assert_eq!(paths, vec!["a.txt", "m.txt", "sub/b.txt", "z.txt"]);
}

// ---------------------------------------------------------------------
// T-PPE-06 — workspace_state_hash is deterministic
// ---------------------------------------------------------------------

#[test]
fn t_ppe_06_workspace_state_hash_byte_stable() {
    let tmp = tempfile::tempdir().unwrap();
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    fs::write(ws.join("a"), b"x").unwrap();
    fs::write(ws.join("b"), b"y").unwrap();

    let m1 = build_workspace_manifest(&ws).unwrap();
    let m2 = build_workspace_manifest(&ws).unwrap();
    assert_eq!(m1, m2, "manifest is byte-stable across runs");

    let h1 = compute_workspace_state_hash(&m1).unwrap();
    let h2 = compute_workspace_state_hash(&m2).unwrap();
    assert_eq!(h1, h2);
    assert!(h1.starts_with("sha256:"));
    assert_eq!(h1.len(), "sha256:".len() + 64);
}

// ---------------------------------------------------------------------
// T-PPE-07..10 — end-to-end run_export semantics
// ---------------------------------------------------------------------

#[test]
fn t_ppe_07_end_to_end_run_export_shape() {
    let tmp = tempfile::tempdir().unwrap();
    let pd = write_persona_def(tmp.path(), FIXTURE_PERSONA_DEF);
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    fs::write(ws.join("conversations.md"), b"session-protokoll").unwrap();
    let out = tmp.path().join("export.json");
    let cli = make_cli(pd, ws, out, None);
    let bundle = run_export(&cli).expect("export ok");

    assert_eq!(bundle.schema_version, PILOT_EXPORT_SCHEMA_VERSION);
    assert_eq!(bundle.persona_id, "tomas");
    assert_eq!(bundle.exported_at_utc, "2026-05-14T16:30:00Z");
    assert!(bundle.v907_persona_hash.starts_with("sha256:"));
    assert_eq!(bundle.v907_persona_hash.len(), "sha256:".len() + 64);
    assert!(bundle.workspace_state_hash.starts_with("sha256:"));
    assert_eq!(bundle.workspace_manifest.file_count, 1);
    assert_eq!(
        bundle.workspace_manifest.entries[0].path,
        "conversations.md"
    );
    assert_eq!(bundle.active_spawn_memory, serde_json::Value::Null);
    // wakir_persona_v1.persona_id must equal bundle.persona_id (consistency).
    assert_eq!(
        bundle
            .wakir_persona_v1
            .get("persona_id")
            .and_then(|v| v.as_str()),
        Some("tomas")
    );
}

#[test]
fn t_ppe_08_pin_match_succeeds() {
    let tmp = tempfile::tempdir().unwrap();
    let pd = write_persona_def(tmp.path(), FIXTURE_PERSONA_DEF);
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    let out = tmp.path().join("export.json");
    // First obtain the hash, then re-run with the pin.
    let cli1 = make_cli(pd.clone(), ws.clone(), out.clone(), None);
    let bundle1 = run_export(&cli1).expect("no-pin run ok");
    let pin = bundle1.v907_persona_hash.clone();
    let cli2 = make_cli(pd, ws, out, Some(pin));
    let bundle2 = run_export(&cli2).expect("pin-matching run ok");
    assert_eq!(bundle1.v907_persona_hash, bundle2.v907_persona_hash);
}

#[test]
fn t_ppe_09_pin_mismatch_returns_hash_drift() {
    let tmp = tempfile::tempdir().unwrap();
    let pd = write_persona_def(tmp.path(), FIXTURE_PERSONA_DEF);
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    let out = tmp.path().join("export.json");
    // 64-hex pin that will not match the computed hash.
    let bad_pin =
        "sha256:0000000000000000000000000000000000000000000000000000000000000000".to_string();
    let cli = make_cli(pd, ws, out, Some(bad_pin.clone()));
    let err = run_export(&cli).unwrap_err();
    let exit_code = err.to_exit_code();
    match &err {
        PilotExportError::HashDrift { computed, supplied } => {
            assert!(computed.starts_with("sha256:"));
            assert_eq!(supplied, &bad_pin);
        }
        other => panic!("expected HashDrift, got {other:?}"),
    }
    assert_eq!(exit_code, 2);
}

#[test]
fn t_ppe_10_missing_persona_def_returns_input_not_found() {
    let tmp = tempfile::tempdir().unwrap();
    let pd = tmp.path().join("does-not-exist.md");
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    let out = tmp.path().join("export.json");
    let cli = make_cli(pd, ws, out, None);
    let err = run_export(&cli).unwrap_err();
    let exit_code = err.to_exit_code();
    match &err {
        PilotExportError::InputNotFound { which, path } => {
            assert_eq!(*which, "persona-def");
            assert_eq!(path.file_name().unwrap(), "does-not-exist.md");
        }
        other => panic!("expected InputNotFound, got {other:?}"),
    }
    assert_eq!(exit_code, 3);
}

// ---------------------------------------------------------------------
// T-PPE-11..12 — JCS bytes byte-determinism + round-trip
// ---------------------------------------------------------------------

#[test]
fn t_ppe_11_bundle_jcs_bytes_byte_deterministic() {
    let tmp = tempfile::tempdir().unwrap();
    let pd = write_persona_def(tmp.path(), FIXTURE_PERSONA_DEF);
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    fs::write(ws.join("conversations.md"), b"x").unwrap();
    let out = tmp.path().join("export.json");
    let cli = make_cli(pd, ws, out, None);

    let bundle_a = run_export(&cli).unwrap();
    let bundle_b = run_export(&cli).unwrap();
    let bytes_a = bundle_to_jcs_bytes(&bundle_a).unwrap();
    let bytes_b = bundle_to_jcs_bytes(&bundle_b).unwrap();
    assert_eq!(
        bytes_a, bytes_b,
        "JCS bytes byte-deterministic across two runs"
    );
    // Trailing newline.
    assert_eq!(*bytes_a.last().unwrap(), b'\n');
}

#[test]
fn t_ppe_12_bundle_round_trip_parses_back_equal() {
    let tmp = tempfile::tempdir().unwrap();
    let pd = write_persona_def(tmp.path(), FIXTURE_PERSONA_DEF);
    let ws = tmp.path().join("ws");
    fs::create_dir_all(&ws).unwrap();
    fs::write(ws.join("file.txt"), b"abc").unwrap();
    let out = tmp.path().join("export.json");
    let cli = make_cli(pd, ws, out, None);
    let bundle = run_export(&cli).unwrap();
    let bytes = bundle_to_jcs_bytes(&bundle).unwrap();
    // Strip trailing newline before parse.
    let bytes_no_nl = &bytes[..bytes.len() - 1];
    let parsed: persona_pilot_export::PilotExportBundle =
        serde_json::from_slice(bytes_no_nl).expect("round-trip parse");
    assert_eq!(parsed, bundle, "round-trip PartialEq holds");
}
