// SPDX-License-Identifier: Apache-2.0
//! Operator CLI for the Bridge-Audit-Replay-Engine.
//!
//! Sprint-Tag-14 Mini-Welle (Bridge-Audit-Roundtrip-E2E).
//!
//! The CLI is the wire-end of the cross-language roundtrip used in
//! `tests/integration/test_bridge_audit_roundtrip_e2e.py`:
//!
//! 1. Python emits a sequence of `EngineeringOutputEvent` envelopes
//!    via `BridgeAuditWriter` and serialises them as JSONL
//!    (one JCS-canonical envelope per line) to a temp file.
//! 2. This CLI reads the JSONL, deserialises into `AuditRecord`s,
//!    runs `ReplayEngine::replay_stream` against an expected
//!    trajectory (loaded from a second JSONL file or, in the
//!    self-replay smoke mode, against the same stream).
//! 3. The CLI emits a JSON report on stdout (see `CliReport`) and
//!    exits 0 on success / 1 on divergence / 2 on usage error.
//!
//! Wire format
//! -----------
//!
//! Each input line is a JCS-canonical JSON object with the same key
//! shape as `AuditRecord::to_envelope()`. The CLI re-canonicalises
//! per record before hashing, so caller-side whitespace drift is
//! safely ignored (the hashes still match the Python pendant).
//!
//! Determinism
//! -----------
//!
//! Like the engine itself, the CLI is deterministic: same input
//! files -> bit-identical stdout report (modulo `serde_json` Map
//! ordering, which we pin by explicit field-ordering in `CliReport`
//! via the `preserve_order` workspace feature).
//!
//! Out of scope
//! ------------
//!
//! - No network / NATS / file-mutating side effects.
//! - No persona-engine re-execution; "replay" here is the record-
//!   sequence-level oracle, not a live engine run.

use std::env;
use std::fs;
use std::io::{self, Read};
use std::path::PathBuf;
use std::process::ExitCode;

use serde::{Deserialize, Serialize};

use persona_engine_bridge_audit_replay::{
    stream_hash, AuditRecord, ExpectedTrajectory, ReplayEngine,
};

// ---------------------------------------------------------------------------
// Wire-format DTO
// ---------------------------------------------------------------------------

/// On-the-wire envelope shape (matches Python `record_envelope()` output
/// + Rust `AuditRecord::to_envelope()`). Decoded from each JSONL line.
#[derive(Debug, Deserialize)]
struct WireRecord {
    org_id: String,
    persona_id: String,
    session_id: String,
    step_index: u32,
    output_kind: String,
    output_payload_sha256: String,
    engine_version: String,
    v907_pin: String,
    ts_utc: String,
    // Tolerated-but-ignored fields (the canonical envelope carries
    // `schema` and `event_kind` as constants; we accept them on the
    // wire for round-trip-friendliness but do not re-validate them
    // here — the AuditRecord builder re-stamps the constants).
    //
    // Reading these fields would be redundant work; we keep the
    // `#[serde(default)]` parser tolerance but mark them allow-dead
    // so the rustc dead-code lint stays clean. Removing them would
    // break tolerance against caller envelopes that include the
    // schema constants.
    #[serde(default)]
    #[allow(dead_code)]
    schema: Option<String>,
    #[serde(default)]
    #[allow(dead_code)]
    event_kind: Option<String>,
}

impl From<WireRecord> for AuditRecord {
    fn from(w: WireRecord) -> Self {
        AuditRecord {
            org_id: w.org_id,
            persona_id: w.persona_id,
            session_id: w.session_id,
            step_index: w.step_index,
            output_kind: w.output_kind,
            output_payload_sha256: w.output_payload_sha256,
            engine_version: w.engine_version,
            v907_pin: w.v907_pin,
            ts_utc: w.ts_utc,
        }
    }
}

// ---------------------------------------------------------------------------
// CLI report DTO
// ---------------------------------------------------------------------------

/// Per-divergence DTO emitted in the CLI's JSON report.
#[derive(Debug, Serialize)]
struct CliDivergence {
    step_index: usize,
    kind: &'static str,
    expected_hash: Option<String>,
    actual_hash: Option<String>,
    field_diff_paths: Vec<String>,
}

/// Top-level CLI JSON report (stdout on every invocation).
#[derive(Debug, Serialize)]
struct CliReport {
    success: bool,
    actual_record_count: usize,
    expected_record_count: usize,
    stream_hash_actual: String,
    stream_hash_expected: String,
    time_to_divergence_steps: Option<usize>,
    divergence_count: usize,
    divergences: Vec<CliDivergence>,
}

// ---------------------------------------------------------------------------
// Argument parsing (minimal, no `clap` dependency for hermetic-test surface)
// ---------------------------------------------------------------------------

#[derive(Debug)]
struct Args {
    /// Path to the actual-stream JSONL. `-` reads from stdin.
    actual: String,
    /// Path to the expected-trajectory JSONL. Optional; when absent,
    /// the CLI compares the actual stream against itself (self-replay
    /// — useful as a smoke-test that the input parses + hashes
    /// deterministically).
    expected: Option<String>,
}

fn parse_args(argv: &[String]) -> Result<Args, String> {
    // Layout: replay_cli --actual <path> [--expected <path>]
    let mut actual: Option<String> = None;
    let mut expected: Option<String> = None;
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "--actual" => {
                i += 1;
                actual = Some(
                    argv.get(i)
                        .ok_or_else(|| "missing value for --actual".to_string())?
                        .clone(),
                );
            }
            "--expected" => {
                i += 1;
                expected = Some(
                    argv.get(i)
                        .ok_or_else(|| "missing value for --expected".to_string())?
                        .clone(),
                );
            }
            "--help" | "-h" => {
                return Err(usage());
            }
            other => return Err(format!("unknown argument: {other}\n\n{}", usage())),
        }
        i += 1;
    }
    let actual = actual.ok_or_else(|| format!("--actual is required\n\n{}", usage()))?;
    Ok(Args { actual, expected })
}

fn usage() -> String {
    "Usage: replay_cli --actual <path-or-dash> [--expected <path>]\n\
     \n\
     Reads JSONL-encoded EngineeringOutputEvent envelopes (one per\n\
     line) and replays them against an expected trajectory.\n\
     \n\
     Without --expected, the CLI does a self-replay (proves the\n\
     input parses and hashes deterministically).\n\
     \n\
     Stdout: JSON CliReport (single object, sort_keys=False).\n\
     Exit codes:\n\
       0  success (no divergence)\n\
       1  divergence detected\n\
       2  usage / parse error"
        .to_string()
}

// ---------------------------------------------------------------------------
// IO helpers
// ---------------------------------------------------------------------------

fn read_input(path: &str) -> io::Result<Vec<u8>> {
    if path == "-" {
        let mut buf = Vec::with_capacity(4096);
        io::stdin().read_to_end(&mut buf)?;
        Ok(buf)
    } else {
        fs::read(PathBuf::from(path))
    }
}

fn parse_jsonl(bytes: &[u8]) -> Result<Vec<AuditRecord>, String> {
    let mut out: Vec<AuditRecord> = Vec::new();
    for (line_no, raw) in bytes.split(|&b| b == b'\n').enumerate() {
        if raw.iter().all(|c| c.is_ascii_whitespace()) {
            continue;
        }
        let line_str = std::str::from_utf8(raw)
            .map_err(|e| format!("line {}: invalid UTF-8: {e}", line_no + 1))?;
        let wire: WireRecord = serde_json::from_str(line_str)
            .map_err(|e| format!("line {}: invalid JSONL record: {e}", line_no + 1))?;
        out.push(wire.into());
    }
    Ok(out)
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn run() -> Result<(CliReport, i32), String> {
    let argv: Vec<String> = env::args().collect();
    let args = parse_args(&argv)?;

    let actual_bytes = read_input(&args.actual).map_err(|e| format!("read actual: {e}"))?;
    let actual_records = parse_jsonl(&actual_bytes)?;

    let expected_records = match args.expected.as_deref() {
        Some(p) => {
            let bytes = read_input(p).map_err(|e| format!("read expected: {e}"))?;
            parse_jsonl(&bytes)?
        }
        None => actual_records.clone(),
    };

    let engine = ReplayEngine::new();
    let trajectory = ExpectedTrajectory::from_records(&expected_records);
    let report = engine
        .replay_stream(&actual_records, &trajectory)
        .map_err(|e| format!("replay: {e}"))?;

    // Sanity-recompute stream-hash via the public helper so the CLI
    // output stays a single source of truth even if the engine grows
    // a more-detailed report later.
    let _ = stream_hash(&actual_records).map_err(|e| format!("stream-hash actual: {e}"))?;

    let divergences: Vec<CliDivergence> = report
        .divergences
        .iter()
        .map(|d| CliDivergence {
            step_index: d.step_index,
            kind: d.kind.as_str(),
            expected_hash: d.expected_hash.clone(),
            actual_hash: d.actual_hash.clone(),
            field_diff_paths: d.field_diffs.iter().map(|f| f.path.clone()).collect(),
        })
        .collect();

    let exit_code = if report.success { 0 } else { 1 };
    let cli_report = CliReport {
        success: report.success,
        actual_record_count: report.actual_record_count,
        expected_record_count: report.expected_record_count,
        stream_hash_actual: report.stream_hash_actual,
        stream_hash_expected: report.stream_hash_expected,
        time_to_divergence_steps: report.time_to_divergence_steps,
        divergence_count: divergences.len(),
        divergences,
    };
    Ok((cli_report, exit_code))
}

fn main() -> ExitCode {
    match run() {
        Ok((report, exit_code)) => {
            // Pretty-print is opt-in; tests parse the JSON regardless.
            // We emit compact JSON for hermetic-test stability.
            let s = serde_json::to_string(&report).expect("serialise CliReport");
            println!("{s}");
            ExitCode::from(exit_code as u8)
        }
        Err(msg) => {
            eprintln!("replay_cli: {msg}");
            ExitCode::from(2)
        }
    }
}

// ---------------------------------------------------------------------------
// Tests (inline; no external fixtures required)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn sample_envelope_line(step: u32) -> String {
        let env = serde_json::json!({
            "engine_version": "0.2.0-pilot",
            "event_kind": "engineering_output",
            "org_id": "wakir-labs",
            "output_kind": "tool_call",
            "output_payload_sha256": format!("sha256:{}", "a".repeat(64)),
            "persona_id": "mira",
            "schema": "wakir.persona.engineering-output/1",
            "session_id": "sess-001",
            "step_index": step,
            "ts_utc": format!("2026-05-17T10:00:0{step}Z"),
            "v907_pin": format!("sha256:{}", "b".repeat(64)),
        });
        // serde_json -> String (compact). Same shape Python emits.
        serde_json::to_string(&env).expect("serialise wire envelope")
    }

    #[test]
    fn parse_jsonl_skips_blank_lines() {
        let mut input = String::new();
        input.push_str(&sample_envelope_line(0));
        input.push_str("\n\n\n");
        input.push_str(&sample_envelope_line(1));
        input.push('\n');
        let recs = parse_jsonl(input.as_bytes()).expect("parse");
        assert_eq!(recs.len(), 2);
        assert_eq!(recs[0].step_index, 0);
        assert_eq!(recs[1].step_index, 1);
    }

    #[test]
    fn parse_jsonl_rejects_malformed_line_with_line_number() {
        let mut input = String::new();
        input.push_str(&sample_envelope_line(0));
        input.push('\n');
        input.push_str("not-json\n");
        let err = parse_jsonl(input.as_bytes()).expect_err("must fail");
        assert!(err.contains("line 2"), "error should pin line number, got: {err}");
    }

    #[test]
    fn args_actual_required() {
        let argv = vec!["replay_cli".to_string()];
        let err = parse_args(&argv).expect_err("must fail without --actual");
        assert!(err.contains("--actual is required"));
    }

    #[test]
    fn args_actual_and_expected_pair() {
        let argv = vec![
            "replay_cli".to_string(),
            "--actual".to_string(),
            "a.jsonl".to_string(),
            "--expected".to_string(),
            "e.jsonl".to_string(),
        ];
        let a = parse_args(&argv).expect("parse");
        assert_eq!(a.actual, "a.jsonl");
        assert_eq!(a.expected.as_deref(), Some("e.jsonl"));
    }

    #[test]
    fn cli_report_serialises_to_json_object() {
        // Make sure the report shape stays a single top-level JSON object.
        let r = CliReport {
            success: true,
            actual_record_count: 0,
            expected_record_count: 0,
            stream_hash_actual: "sha256:0".to_string(),
            stream_hash_expected: "sha256:0".to_string(),
            time_to_divergence_steps: None,
            divergence_count: 0,
            divergences: vec![],
        };
        let s = serde_json::to_string(&r).expect("serialise");
        let v: Value = serde_json::from_str(&s).expect("re-parse");
        assert!(v.is_object());
        assert_eq!(v.get("success").unwrap().as_bool(), Some(true));
    }
}
