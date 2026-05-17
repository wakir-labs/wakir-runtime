// SPDX-License-Identifier: Apache-2.0
//! `wakir-v907-verify` binary entry-point.
//!
//! Thin operator-CLI wrapper around the [`persona_engine_v907_verify`]
//! library. Two subcommands:
//!
//! - `compute <persona-file>`         — read axis-A markdown bytes
//!   from `<persona-file>`, run [`compute_v907_pin`], print the
//!   resulting `"sha256:<64hex>"` pin on stdout, exit 0.
//! - `verify <persona-file> <expected>` — read axis-A markdown bytes,
//!   parse, run [`verify_v907_pin`] against `<expected>`, print
//!   `"OK <pin>"` on stdout on match (exit 0) or `"DRIFT computed=<pin> expected=<expected>"`
//!   on mismatch (exit 1).
//!
//! Exit codes
//! ----------
//!
//!   0  — success (compute) or pin match (verify)
//!   1  — pin drift (verify-only) or parse / hash-compute failure
//!   3  — persona-file not found
//!  64  — argparse usage error (mirrors Python `argparse`'s EX_USAGE
//!        + the persona-cli convention in `persona-cli`)
//!
//! Posture
//! -------
//!
//! Zero new dependencies beyond the workspace deps the library
//! already pulls in. No clap, no anyhow, no env_logger — the binary
//! is a static-link-friendly thin shim for the Container-Image-Build-
//! Pipeline (Tag-26 Mini-Welle, ADR-0065 Welle-1 `v907_verify`
//! pre-cutover image).
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0065 §Phase-3c Welle-1 `v907_verify` — first component to
//!   flip from Python-default to Rust-default. This binary is the
//!   container-image-shipped artefact.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images. The
//!   workflow `.github/workflows/build-rust-cli-v907-verify.yml`
//!   signs the published digest against the GitHub-Actions OIDC
//!   identity.

use std::process::ExitCode;

use persona_engine_v907_verify::{
    compute_v907_pin, parse_persona_def, verify_v907_pin, PersonaHashError,
};

const USAGE: &str = "\
usage:
    wakir-v907-verify compute <persona-file>
    wakir-v907-verify verify  <persona-file> <expected-pin>

Compute the V-907 pin for the axis-A markdown bytes at <persona-file>,
or verify against an expected `sha256:<64hex>` pin.
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
        "compute" => run_compute(argv),
        "verify" => run_verify(argv),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            // CARGO_PKG_VERSION is set by Cargo at build time.
            println!("wakir-v907-verify {}", env!("CARGO_PKG_VERSION"));
            Ok(0)
        }
        other => {
            eprintln!("error: unknown subcommand: {other}");
            eprintln!("{USAGE}");
            Err(64)
        }
    }
}

fn run_compute(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 3 {
        eprintln!("error: `compute` takes exactly one argument <persona-file>");
        eprintln!("{USAGE}");
        return Err(64);
    }
    let path = &argv[2];
    let md = read_persona_file(path)?;
    match compute_v907_pin(&md) {
        Ok(pin) => {
            println!("{pin}");
            Ok(0)
        }
        Err(err) => {
            eprintln!("error: compute_v907_pin failed: {}", err_message(&err));
            Err(1)
        }
    }
}

fn run_verify(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 4 {
        eprintln!("error: `verify` takes exactly two arguments <persona-file> <expected-pin>");
        eprintln!("{USAGE}");
        return Err(64);
    }
    let path = &argv[2];
    let expected = &argv[3];
    let md = read_persona_file(path)?;
    let def = match parse_persona_def(&md) {
        Ok(d) => d,
        Err(err) => {
            eprintln!("error: parse_persona_def failed: {}", err_message(&err));
            return Err(1);
        }
    };
    // Use a stable, file-derived persona_id for log/audit messages —
    // the verify path itself does not consume it semantically but the
    // library API signature requires it.
    let persona_id = std::path::Path::new(path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown");
    match verify_v907_pin(persona_id, &def, Some(expected)) {
        Ok(result) => {
            println!("OK {}", result.pin);
            Ok(0)
        }
        Err(PersonaHashError::Drift {
            computed, expected, ..
        }) => {
            println!("DRIFT computed={computed} expected={expected}");
            Err(1)
        }
        Err(err) => {
            eprintln!("error: verify_v907_pin failed: {}", err_message(&err));
            Err(1)
        }
    }
}

fn read_persona_file(path: &str) -> Result<String, u8> {
    match std::fs::read_to_string(path) {
        Ok(s) => Ok(s),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            eprintln!("error: persona-file not found: {path}");
            Err(3)
        }
        Err(err) => {
            eprintln!("error: failed to read {path}: {err}");
            Err(1)
        }
    }
}

fn err_message(err: &PersonaHashError) -> String {
    match err {
        PersonaHashError::Compute(m) => format!("compute: {m}"),
        PersonaHashError::Drift {
            persona_id,
            computed,
            expected,
        } => {
            format!("drift: persona_id={persona_id} computed={computed} expected={expected}")
        }
    }
}
