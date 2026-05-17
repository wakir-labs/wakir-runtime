// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-subscribe-loop` binary entry-point.
//!
//! Thin operator-CLI wrapper around the
//! [`persona_engine_subscribe_loop`] library. Subcommands:
//!
//! - `info`                                  — print operator-
//!   discovery banner (accepted inbound schema, outbound output
//!   schema, env-var bindings).
//! - `subject <env> <persona-slug>`          — emit the canonical
//!   `agent.task.assigned` subscribe-subject for the supplied
//!   environment + persona-slug. Validates `<env>` against
//!   `dev|staging|prod` and `<persona-slug>` against
//!   `[a-z][a-z0-9_-]*` (parity with the Python `build_subscribe_subject`).
//!   Exit 0 on success, 64 on validation failure.
//! - `ack-hash <jcs-file>`                   — read a JCS-canonical
//!   `SubscribeAckRecord` blob and emit its
//!   `"sha256:<64hex>"` payload digest. Since `SubscribeAckRecord`
//!   intentionally does NOT implement `serde::Deserialize` (the
//!   canonical-serialisation contract is one-way: build-via-helper
//!   then `serialize_ack`), the binary hashes the raw bytes directly.
//!   This is the correct semantics for the cross-substrate-parity
//!   smoke: any byte that differs at the wire boundary changes the
//!   digest. Exit 0 on success, 1 on IO failure, 3 if the file is
//!   missing.
//! - `--version`                             — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help`                — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success
//!   1  — runtime error (parse / hash / IO)
//!   3  — input file not found
//!  64  — usage error (unknown subcommand or bad argument shape /
//!        env / persona-slug validation failure)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No live async-nats connect. The binary is
//! a static-link-friendly thin shim for the Container-Image-Build-
//! Pipeline (Tag-32 Mini-Welle, ADR-0066 Welle-6 `subscribe_loop`
//! pre-cutover image).
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-6 `subscribe_loop` — image-build
//!   pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-subscribe-loop.yml` workflow
//!   publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.

use persona_engine_subscribe_loop::ack_record::sha256_hex;
use persona_engine_subscribe_loop::{
    build_subscribe_subject, ACCEPTED_INBOUND_SCHEMA, OUTBOUND_OUTPUT_SCHEMA,
    SUBSCRIBE_SUBJECT_TEMPLATE,
};

use std::process::ExitCode;

const USAGE: &str = "\
usage:
    wakir-persona-engine-subscribe-loop info
    wakir-persona-engine-subscribe-loop subject <env> <persona-slug>
    wakir-persona-engine-subscribe-loop ack-hash <jcs-file>
    wakir-persona-engine-subscribe-loop --version
    wakir-persona-engine-subscribe-loop --help

Operator-CLI for the persona-engine NATS-JetStream subscribe-loop
substrate. Read-only utility surface: subject canonicalisation and
ack-record digest emission. Does not open a NATS connection.
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
        "subject" => run_subject(argv),
        "ack-hash" => run_ack_hash(argv),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            println!(
                "wakir-persona-engine-subscribe-loop {}",
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
    println!("accepted_inbound_schema={ACCEPTED_INBOUND_SCHEMA}");
    println!("outbound_output_schema={OUTBOUND_OUTPUT_SCHEMA}");
    println!("subscribe_subject_template={SUBSCRIBE_SUBJECT_TEMPLATE}");
    println!("python_authority=wirelang.persona_engine.nats_subscribe_loop");
    println!("env_switch=WAKIR_SUBSCRIBE_LOOP_BACKEND");
    println!("env_switch_value=rust");
    println!("env_binary_override=WAKIR_RUST_SUBSCRIBE_LOOP_BIN");
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

fn run_subject(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 4 {
        eprintln!(
            "error: `subject` takes exactly two arguments \
             <env> <persona-slug>"
        );
        eprintln!("{USAGE}");
        return Err(64);
    }
    let env = &argv[2];
    let slug = &argv[3];
    match build_subscribe_subject(env, slug) {
        Ok(subject) => {
            println!("{subject}");
            Ok(0)
        }
        Err(msg) => {
            eprintln!("error: {msg}");
            Err(64)
        }
    }
}

fn run_ack_hash(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 3 {
        eprintln!("error: `ack-hash` takes exactly one argument <jcs-file>");
        eprintln!("{USAGE}");
        return Err(64);
    }
    let path = &argv[2];
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
    // SubscribeAckRecord does not implement serde::Deserialize by
    // design (one-way canonical-serialisation contract). Hash the
    // raw bytes directly; this matches the cross-substrate-parity
    // requirement for a JCS-canonical input blob.
    let hex_digest = sha256_hex(&blob);
    println!("sha256:{hex_digest}");
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_with_no_args_exits_64() {
        let argv = vec!["wakir-persona-engine-subscribe-loop".into()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_with_unknown_subcommand_exits_64() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "consume".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_help_exits_0() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "--help".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_version_exits_0() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
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
    fn run_subject_happy_path() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "subject".into(),
            "dev".into(),
            "selin".into(),
        ];
        let result = run_subject(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_subject_bad_env_exits_64() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "subject".into(),
            "qa".into(), // not one of dev|staging|prod
            "selin".into(),
        ];
        let result = run_subject(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_subject_bad_slug_exits_64() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "subject".into(),
            "dev".into(),
            "BadSlug".into(), // capital not allowed
        ];
        let result = run_subject(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_subject_wrong_argc_exits_64() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "subject".into(),
            "dev".into(),
        ];
        let result = run_subject(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_ack_hash_missing_file_exits_3() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "ack-hash".into(),
            "/nonexistent/path/to/ack.jcs".into(),
        ];
        let result = run_ack_hash(&argv);
        assert!(matches!(result, Err(3)));
    }

    #[test]
    fn run_ack_hash_wrong_argc_exits_64() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "ack-hash".into(),
        ];
        let result = run_ack_hash(&argv);
        assert!(matches!(result, Err(64)));
    }
}
