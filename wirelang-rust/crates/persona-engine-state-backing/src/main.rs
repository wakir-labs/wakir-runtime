// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-state-backing` binary entry-point.
//!
//! Thin operator-CLI wrapper around the
//! [`persona_engine_state_backing`] library. Subcommands:
//!
//! - `info`                   — print operator-discovery banner
//!   (default key prefix, offset key width, env-var binding hints).
//! - `snapshot-hash <persona-id> <jcs-file>` — read a JCS-canonical
//!   PersonaStateSnapshot blob from `<jcs-file>`, parse it via
//!   [`snapshot_from_jcs_bytes`], compute and print the
//!   `"sha256:<64hex>"` payload digest via
//!   [`snapshot_payload_sha256`]. Exit 0 on success, 1 on parse or
//!   compute failure, 3 if the file is missing.
//! - `offset-key <offset>`    — print the canonical zero-padded
//!   offset key for the given non-negative integer offset (mirrors
//!   the Python `state_backing.offset_key(offset)` helper). Exit 0
//!   on success, 64 on parse error (negative or non-integer).
//! - `--version`              — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help` — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success
//!   1  — runtime error (parse / hash / IO)
//!   3  — input file not found
//!  64  — usage error (unknown subcommand or bad argument shape)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No clap, no anyhow, no env_logger — the
//! binary is a static-link-friendly thin shim for the Container-
//! Image-Build-Pipeline (Tag-32 Mini-Welle, ADR-0066 Welle-4
//! `state_backing` pre-cutover image). The binary intentionally
//! does NOT open a live NATS-KV socket; the `InMemoryStateBacking`
//! is also NOT exposed via the CLI in this skeleton (the live
//! socket binding belongs to the Phase-3a live-binding follow-up).
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-4 `state_backing` — image-build
//!   pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-state-backing.yml`
//!   workflow publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.

use persona_engine_state_backing::{
    offset_key, snapshot_from_jcs_bytes, snapshot_payload_sha256, LATEST_KEY, NEXT_OFFSET_KEY,
    OFFSET_KEY_WIDTH, PINNED_KEY, STATE_PACK_KEY_PREFIX,
};

use std::process::ExitCode;

const USAGE: &str = "\
usage:
    wakir-persona-engine-state-backing info
    wakir-persona-engine-state-backing snapshot-hash <persona-id> <jcs-file>
    wakir-persona-engine-state-backing offset-key <offset>
    wakir-persona-engine-state-backing --version
    wakir-persona-engine-state-backing --help

Operator-CLI for the persona-engine NATS-KV Persona-State-Backing
substrate. Read-only utility surface: snapshot digest computation
and canonical offset-key emission. Does not open a NATS-KV socket.
";

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().collect();
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
        "info" => run_info(),
        "snapshot-hash" => run_snapshot_hash(argv),
        "offset-key" => run_offset_key(argv),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            println!(
                "wakir-persona-engine-state-backing {}",
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

fn run_info() -> Result<u8, u8> {
    println!("state_pack_key_prefix={STATE_PACK_KEY_PREFIX}");
    println!("offset_key_width={OFFSET_KEY_WIDTH}");
    println!("pinned_key={PINNED_KEY}");
    println!("next_offset_key={NEXT_OFFSET_KEY}");
    println!("latest_key={LATEST_KEY}");
    println!("python_authority=wirelang.persona_engine.state_backing");
    println!("env_switch=WAKIR_STATE_BACKING_BACKEND");
    println!("env_switch_values=rust_inmemory|rust_natskv");
    println!("env_binary_override=WAKIR_RUST_STATE_BACKING_BIN");
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

fn run_snapshot_hash(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 4 {
        eprintln!(
            "error: `snapshot-hash` takes exactly two arguments \
             <persona-id> <jcs-file>"
        );
        eprintln!("{USAGE}");
        return Err(64);
    }
    let persona_id = &argv[2];
    let path = &argv[3];
    // persona_id is currently advisory in the digest computation
    // (the JCS bytes are self-describing), but we keep it in the
    // CLI surface for parity with the Python `payload_sha256` log
    // record shape and future audit-stream emission.
    let _ = persona_id;
    let blob = match std::fs::read(path) {
        Ok(b) => b,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            eprintln!("error: jcs-file not found: {path}");
            return Err(3);
        }
        Err(err) => {
            eprintln!("error: failed to read {path}: {err}");
            return Err(1);
        }
    };
    let snap = match snapshot_from_jcs_bytes(&blob) {
        Ok(s) => s,
        Err(err) => {
            eprintln!("error: snapshot_from_jcs_bytes failed: {err}");
            return Err(1);
        }
    };
    let digest = snapshot_payload_sha256(&snap);
    println!("{digest}");
    Ok(0)
}

fn run_offset_key(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 3 {
        eprintln!("error: `offset-key` takes exactly one argument <offset>");
        eprintln!("{USAGE}");
        return Err(64);
    }
    let raw = &argv[2];
    let offset: u64 = match raw.parse() {
        Ok(v) => v,
        Err(_) => {
            eprintln!("error: offset must be a non-negative integer: {raw}");
            return Err(64);
        }
    };
    println!("{}", offset_key(offset));
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_with_no_args_exits_64() {
        let argv = vec!["wakir-persona-engine-state-backing".into()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_with_unknown_subcommand_exits_64() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "live-bind".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_help_exits_0() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "--help".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_version_exits_0() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "--version".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_info_exits_0() {
        let result = run_info();
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_offset_key_happy_path() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "offset-key".into(),
            "42".into(),
        ];
        let result = run_offset_key(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_offset_key_negative_exits_64() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "offset-key".into(),
            "-1".into(),
        ];
        let result = run_offset_key(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_offset_key_wrong_argc_exits_64() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "offset-key".into(),
        ];
        let result = run_offset_key(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_snapshot_hash_missing_file_exits_3() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "snapshot-hash".into(),
            "persona:test".into(),
            "/nonexistent/path/to/snapshot.jcs".into(),
        ];
        let result = run_snapshot_hash(&argv);
        assert!(matches!(result, Err(3)));
    }

    #[test]
    fn run_snapshot_hash_wrong_argc_exits_64() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "snapshot-hash".into(),
            "persona:test".into(),
        ];
        let result = run_snapshot_hash(&argv);
        assert!(matches!(result, Err(64)));
    }
}
