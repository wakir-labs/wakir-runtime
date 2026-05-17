// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-bridge-audit-writer` binary entry-point.
//!
//! Tag-31 Mini-Welle (ADR-0066 Welle-3 `bridge_audit_writer` pre-cutover
//! image, parallel to ADR-0066 Welle-1 V907-verify and Welle-2 SVID-
//! workload-identity image-builds).
//!
//! Thin operator-CLI wrapper around the [`AuditRecord`] envelope shape
//! exported by the [`persona_engine_bridge_audit_replay`] library.
//! Three subcommands:
//!
//! - `emit  --org-id ORG --persona-id PERSONA --session-id SID
//!         --step-index N --output-kind KIND --engine-version VER
//!         --v907-pin sha256:<64hex> [--ts-utc RFC3339]
//!         [--payload-file PATH | --payload-stdin]`
//!   — read payload bytes from `--payload-file` or stdin, hash them
//!   with SHA-256, build an `EngineeringOutputEvent` envelope and
//!   print it as a JCS-canonical UTF-8 JSON line on stdout. The
//!   envelope is byte-identical to the Python pendant's
//!   `wirelang.persona_engine.bridge_audit_writer.
//!   EngineeringOutputEvent.to_jcs_bytes()`.
//! - `info`                   — print the canonical schema string +
//!   the default Pre-Framework sink path template + the binary
//!   version. Always exits 0.
//! - `--version`              — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help` — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success: envelope emitted, or `info` / `--help` / `--version`
//!   1  — internal error (I/O failure on payload read, JCS error)
//!   2  — payload source missing (`--payload-file` path does not exist)
//!  64  — usage error (unknown subcommand, missing required flag, or
//!         malformed argument shape)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No `clap`, no `anyhow`, no `env_logger` — the
//! binary is a static-link-friendly thin shim for the Container-
//! Image-Build-Pipeline (Tag-31 Mini-Welle, ADR-0066 Welle-3 image-
//! build). Parity with the `wakir-persona-engine-svid-workload-identity`
//! and `wakir-persona-engine-v907-verify` operator-CLI surface.
//!
//! Wire-shape determinism contract
//! -------------------------------
//!
//! The emitted envelope is JCS-canonical (RFC 8785) UTF-8 bytes,
//! lexicographically-sorted keys, no whitespace. The Python pendant's
//! `EngineeringOutputEvent.to_jcs_bytes()` returns the same bytes for
//! the same input — this is the cross-language pin the
//! `persona-engine-bridge-audit-replay` test-suite enforces via the F1
//! / F2 / F3 fixture hashes. The Pre-Framework Markdown sink path is
//! NOT bound here — the CLI is the wakir-runtime-sink half of the
//! double-sink writer; the Pre-Framework sink is an Operator-Hand
//! Markdown append outside the supply-chain-signed binary surface.
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-3 `bridge_audit_writer` — image-build
//!   pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-bridge-audit-writer.yml`
//!   workflow publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.
//! - PR #131 (`persona-engine-bridge-diff`) — JCS / hash primitive
//!   reused via the lib crate's `AuditRecord::jcs_hash()`.
//! - PR #147 (`persona-engine-bridge-audit-replay`) — the library
//!   crate this binary lives in; the `AuditRecord::to_envelope()`
//!   wire shape is the single-source-of-truth.

use std::env;
use std::fs;
use std::io::{self, Read};
use std::process::ExitCode;

use persona_engine_bridge_audit_replay::AuditRecord;

use serde_json::Value;
use sha2::{Digest, Sha256};

const USAGE: &str = "\
usage:
    wakir-persona-engine-bridge-audit-writer emit \\
        --org-id ORG --persona-id PERSONA --session-id SID \\
        --step-index N --output-kind KIND \\
        --engine-version VER --v907-pin sha256:<64hex> \\
        [--ts-utc RFC3339] \\
        [--payload-file PATH | --payload-stdin]
    wakir-persona-engine-bridge-audit-writer info
    wakir-persona-engine-bridge-audit-writer --version
    wakir-persona-engine-bridge-audit-writer --help

Emit a single Bridge-Audit EngineeringOutputEvent envelope as a
JCS-canonical JSON line on stdout. Payload bytes are read from
--payload-file (path) or --payload-stdin (default), hashed with
SHA-256, and recorded as the envelope's output_payload_sha256 field.
Payload bytes themselves are NEVER written to stdout.

Subcommand `info` prints the schema identifier + default Pre-
Framework sink path template + version, one key=value pair per line.
";

fn main() -> ExitCode {
    let argv: Vec<String> = env::args().collect();
    match run(&argv) {
        Ok(code) => ExitCode::from(code),
        Err(code) => ExitCode::from(code),
    }
}

fn run(argv: &[String]) -> Result<u8, u8> {
    if argv.len() < 2 {
        eprintln!("{USAGE}");
        return Err(64);
    }
    match argv[1].as_str() {
        "emit" => run_emit(argv),
        "info" => run_info(),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            println!(
                "wakir-persona-engine-bridge-audit-writer {}",
                env!("CARGO_PKG_VERSION")
            );
            Ok(0)
        }
        other => {
            eprintln!("error: unknown subcommand: {other}");
            eprintln!("{USAGE}");
            Err(64)
        }
    }
}

// ---------------------------------------------------------------------------
// emit
// ---------------------------------------------------------------------------

#[derive(Debug, Default)]
struct EmitArgs {
    org_id: Option<String>,
    persona_id: Option<String>,
    session_id: Option<String>,
    step_index: Option<u32>,
    output_kind: Option<String>,
    engine_version: Option<String>,
    v907_pin: Option<String>,
    ts_utc: Option<String>,
    payload_file: Option<String>,
    payload_stdin: bool,
}

fn parse_emit_args(argv: &[String]) -> Result<EmitArgs, u8> {
    let mut out = EmitArgs::default();
    let mut i: usize = 2; // argv[0]=binary, argv[1]="emit"
    while i < argv.len() {
        let flag = argv[i].as_str();
        match flag {
            "--payload-stdin" => {
                out.payload_stdin = true;
                i += 1;
            }
            "--org-id"
            | "--persona-id"
            | "--session-id"
            | "--step-index"
            | "--output-kind"
            | "--engine-version"
            | "--v907-pin"
            | "--ts-utc"
            | "--payload-file" => {
                let val = argv.get(i + 1).ok_or_else(|| {
                    eprintln!("error: {flag} requires a value");
                    64u8
                })?;
                match flag {
                    "--org-id" => out.org_id = Some(val.clone()),
                    "--persona-id" => out.persona_id = Some(val.clone()),
                    "--session-id" => out.session_id = Some(val.clone()),
                    "--step-index" => {
                        let parsed: u32 = val.parse().map_err(|_| {
                            eprintln!(
                                "error: --step-index must be a non-negative \
                                 integer; got {val:?}"
                            );
                            64u8
                        })?;
                        out.step_index = Some(parsed);
                    }
                    "--output-kind" => out.output_kind = Some(val.clone()),
                    "--engine-version" => {
                        out.engine_version = Some(val.clone());
                    }
                    "--v907-pin" => out.v907_pin = Some(val.clone()),
                    "--ts-utc" => out.ts_utc = Some(val.clone()),
                    "--payload-file" => out.payload_file = Some(val.clone()),
                    _ => unreachable!(),
                }
                i += 2;
            }
            other => {
                eprintln!("error: unknown flag for `emit`: {other}");
                return Err(64);
            }
        }
    }
    Ok(out)
}

fn run_emit(argv: &[String]) -> Result<u8, u8> {
    let args = parse_emit_args(argv)?;

    // Required-flag check.
    let org_id = args.org_id.as_ref().ok_or_else(|| {
        eprintln!("error: --org-id is required");
        eprintln!("{USAGE}");
        64u8
    })?;
    let persona_id = args.persona_id.as_ref().ok_or_else(|| {
        eprintln!("error: --persona-id is required");
        64u8
    })?;
    let session_id = args.session_id.as_ref().ok_or_else(|| {
        eprintln!("error: --session-id is required");
        64u8
    })?;
    let step_index = args.step_index.ok_or_else(|| {
        eprintln!("error: --step-index is required");
        64u8
    })?;
    let output_kind = args.output_kind.as_ref().ok_or_else(|| {
        eprintln!("error: --output-kind is required");
        64u8
    })?;
    let engine_version = args.engine_version.as_ref().ok_or_else(|| {
        eprintln!("error: --engine-version is required");
        64u8
    })?;
    let v907_pin = args.v907_pin.as_ref().ok_or_else(|| {
        eprintln!("error: --v907-pin is required");
        64u8
    })?;

    // Substrate-fence: output_kind alphabet (mirrors Python writer).
    match output_kind.as_str() {
        "tool_call" | "reply" | "audit_annotation" => {}
        other => {
            eprintln!(
                "error: --output-kind must be one of tool_call|reply|\
                 audit_annotation; got {other:?}"
            );
            return Err(64);
        }
    }

    // Substrate-fence: v907_pin shape `sha256:<64hex>` (mirrors Python).
    if !is_valid_sha256_pin(v907_pin) {
        eprintln!(
            "error: --v907-pin must be `sha256:<64-lowercase-hex>`; \
             got {v907_pin:?}"
        );
        return Err(64);
    }

    // Conflict-check: --payload-file XOR --payload-stdin (default is stdin
    // if neither is given; treat both-set as a usage error).
    if args.payload_file.is_some() && args.payload_stdin {
        eprintln!(
            "error: --payload-file and --payload-stdin are mutually \
             exclusive"
        );
        return Err(64);
    }

    // Read payload bytes.
    let payload = read_payload(args.payload_file.as_deref())?;
    let payload_hash = format!("sha256:{}", hex_digest(&payload));

    // Build envelope.
    let ts_utc = args
        .ts_utc
        .as_ref()
        .map(|s| s.clone())
        .unwrap_or_else(default_ts_utc);

    let record = AuditRecord {
        org_id: org_id.clone(),
        persona_id: persona_id.clone(),
        session_id: session_id.clone(),
        step_index,
        output_kind: output_kind.clone(),
        output_payload_sha256: payload_hash,
        engine_version: engine_version.clone(),
        v907_pin: v907_pin.clone(),
        ts_utc,
    };

    // Emit JCS-canonical envelope on stdout (one line, newline-terminated;
    // mirrors the wakir-runtime sink shape in
    // `BridgeAuditWriter._write_wakir_runtime_sink`).
    let envelope: Value = record.to_envelope();
    let jcs_bytes = serde_jcs::to_vec(&envelope).map_err(|e| {
        eprintln!("error: JCS canonicalisation failed: {e}");
        1u8
    })?;
    // serde_jcs guarantees valid UTF-8; unwrap is safe.
    let line = String::from_utf8(jcs_bytes).map_err(|e| {
        eprintln!("error: JCS output not valid UTF-8: {e}");
        1u8
    })?;
    println!("{line}");
    Ok(0)
}

fn read_payload(payload_file: Option<&str>) -> Result<Vec<u8>, u8> {
    match payload_file {
        Some(path) => {
            // `--payload-file PATH` — open + read fully.
            let p = std::path::Path::new(path);
            if !p.exists() {
                eprintln!(
                    "error: --payload-file path not found: {path:?}"
                );
                return Err(2);
            }
            fs::read(p).map_err(|e| {
                eprintln!("error: failed to read payload-file {path:?}: {e}");
                1u8
            })
        }
        None => {
            // Default: drain stdin.
            let mut buf = Vec::new();
            io::stdin().read_to_end(&mut buf).map_err(|e| {
                eprintln!("error: failed to read payload from stdin: {e}");
                1u8
            })?;
            Ok(buf)
        }
    }
}

fn is_valid_sha256_pin(s: &str) -> bool {
    let prefix = "sha256:";
    if !s.starts_with(prefix) {
        return false;
    }
    let tail = &s[prefix.len()..];
    if tail.len() != 64 {
        return false;
    }
    tail.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}

fn hex_digest(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

fn default_ts_utc() -> String {
    // RFC-3339 UTC second-precision via a tiny date math routine. We
    // avoid the `chrono` / `time` substrate to keep the binary at zero
    // additional dependencies (parity with the V907-verify + SVID CLI
    // surface).
    //
    // The format matches the Python pendant's
    // `_utc_now_rfc3339()` (``%Y-%m-%dT%H:%M:%SZ``).
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format_rfc3339_utc_seconds(secs)
}

/// Convert UNIX seconds-since-epoch (UTC) into a
/// `YYYY-MM-DDTHH:MM:SSZ` RFC-3339 string.
///
/// Reimplemented locally to avoid pulling in `chrono` / `time` (zero-
/// dep posture). Civil-time conversion via Howard Hinnant's days-from-
/// civil algorithm (the same algorithm the C++23 `std::chrono` civil-
/// calendar uses).
fn format_rfc3339_utc_seconds(unix_secs: u64) -> String {
    let secs_in_day: u64 = 86_400;
    let days = (unix_secs / secs_in_day) as i64;
    let sod = (unix_secs % secs_in_day) as u32;
    let hh = sod / 3600;
    let mm = (sod % 3600) / 60;
    let ss = sod % 60;
    let (y, m, d) = civil_from_days(days);
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z", y, m, d, hh, mm, ss)
}

/// Howard Hinnant's `civil_from_days` (days-since-1970-01-01 to
/// year-month-day in the proleptic Gregorian calendar).
///
/// The internal `+719468` shifts the epoch from `1970-01-01` to
/// `0000-03-01` so the leap-year arithmetic works on a calendar that
/// starts at March (March-shifted years simplify the leap-day handling).
fn civil_from_days(z: i64) -> (i32, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y_full = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32; // [1, 12]
    let y = (y_full + if m <= 2 { 1 } else { 0 }) as i32;
    (y, m, d)
}

// ---------------------------------------------------------------------------
// info
// ---------------------------------------------------------------------------

fn run_info() -> Result<u8, u8> {
    // One `key=value` line per piece of operator-discoverable metadata.
    // Format mirrors the SVID-CLI `info` surface so a future shared
    // operator script can consume both with the same grep.
    println!(
        "engineering_output_schema=wakir.persona.engineering-output/1"
    );
    println!(
        "default_preframework_sink_template=\
         /var/lib/wakir/persona/{{persona_id}}/bridge-audit.md"
    );
    println!(
        "python_authority=wirelang.persona_engine.bridge_audit_writer"
    );
    println!(
        "library_crate=persona-engine-bridge-audit-replay"
    );
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn bin() -> String {
        "wakir-persona-engine-bridge-audit-writer".to_string()
    }

    #[test]
    fn run_with_no_args_exits_64() {
        let argv = vec![bin()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_with_unknown_subcommand_exits_64() {
        let argv = vec![bin(), "publish".into()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_help_exits_0() {
        let argv = vec![bin(), "--help".into()];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_version_exits_0() {
        let argv = vec![bin(), "--version".into()];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_info_exits_0() {
        let result = run_info();
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn emit_missing_required_flags_exits_64() {
        // Only --org-id, nothing else.
        let argv = vec![
            bin(),
            "emit".into(),
            "--org-id".into(),
            "acme".into(),
        ];
        let result = run_emit(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn emit_payload_file_missing_exits_2() {
        let argv = vec![
            bin(),
            "emit".into(),
            "--org-id".into(),
            "acme".into(),
            "--persona-id".into(),
            "tomas".into(),
            "--session-id".into(),
            "s1".into(),
            "--step-index".into(),
            "0".into(),
            "--output-kind".into(),
            "reply".into(),
            "--engine-version".into(),
            "0.2.0-pilot".into(),
            "--v907-pin".into(),
            format!("sha256:{}", "a".repeat(64)),
            "--payload-file".into(),
            "/nonexistent/payload.bin".into(),
        ];
        let result = run_emit(&argv);
        assert!(matches!(result, Err(2)));
    }

    #[test]
    fn emit_bad_output_kind_exits_64() {
        let argv = vec![
            bin(),
            "emit".into(),
            "--org-id".into(),
            "acme".into(),
            "--persona-id".into(),
            "tomas".into(),
            "--session-id".into(),
            "s1".into(),
            "--step-index".into(),
            "0".into(),
            "--output-kind".into(),
            "bogus".into(),
            "--engine-version".into(),
            "0.2.0-pilot".into(),
            "--v907-pin".into(),
            format!("sha256:{}", "a".repeat(64)),
            "--payload-stdin".into(),
        ];
        let result = run_emit(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn emit_bad_v907_pin_exits_64() {
        let argv = vec![
            bin(),
            "emit".into(),
            "--org-id".into(),
            "acme".into(),
            "--persona-id".into(),
            "tomas".into(),
            "--session-id".into(),
            "s1".into(),
            "--step-index".into(),
            "0".into(),
            "--output-kind".into(),
            "reply".into(),
            "--engine-version".into(),
            "0.2.0-pilot".into(),
            "--v907-pin".into(),
            "sha256:deadbeef".into(),
            "--payload-stdin".into(),
        ];
        let result = run_emit(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn is_valid_sha256_pin_accepts_canonical() {
        assert!(is_valid_sha256_pin(&format!(
            "sha256:{}",
            "0".repeat(64)
        )));
    }

    #[test]
    fn is_valid_sha256_pin_rejects_uppercase() {
        assert!(!is_valid_sha256_pin(&format!(
            "sha256:{}",
            "A".repeat(64)
        )));
    }

    #[test]
    fn is_valid_sha256_pin_rejects_short_tail() {
        assert!(!is_valid_sha256_pin("sha256:abc"));
    }

    #[test]
    fn hex_digest_matches_known_vector() {
        // SHA-256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        assert_eq!(
            hex_digest(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn format_rfc3339_epoch_zero() {
        assert_eq!(
            format_rfc3339_utc_seconds(0),
            "1970-01-01T00:00:00Z"
        );
    }

    #[test]
    fn format_rfc3339_known_anchor_2026_05_17() {
        // 2026-05-17T12:34:56Z corresponds to UNIX timestamp 1779021296.
        // Cross-checked via the workspace `date -u -d ...` recipe.
        let s = format_rfc3339_utc_seconds(1_779_021_296);
        assert_eq!(s, "2026-05-17T12:34:56Z");
    }
}
