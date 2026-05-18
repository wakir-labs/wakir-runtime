// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-subscribe-loop` binary entry-point.
//!
//! Tag-33 Mini-Welle (ADR-0066 Welle-6 `subscribe_loop` pre-cutover
//! image, parallel to ADR-0066 Welle-1 V907-verify, Welle-2 SVID-
//! workload-identity, Welle-3 bridge-audit-writer, Welle-4 state-
//! backing and Welle-5 lifecycle-state-machine image-builds).
//!
//! Thin operator-CLI wrapper around the
//! [`persona_engine_subscribe_loop`] library. Two payload
//! subcommands plus the standard `--help` / `--version` surface:
//!
//! - `info` — print the canonical schema strings
//!   (inbound `wakir.agent.task-assigned/1`, outbound
//!   `wakir.agent.task-output/1`, ack-record
//!   `wakir.persona-engine.subscribe-ack/1`), the NATS-subject
//!   template and the five valid outcome strings. Always exits 0.
//!   Format is machine-parseable (one `key=value` pair per line).
//! - `build-subject ENV PERSONA_SLUG` — render the NATS-JetStream
//!   subject string for a given env + persona-slug pair via the
//!   library's [`build_subscribe_subject`] formatter. The output is
//!   byte-identical to the Python pendant
//!   `wirelang.persona_engine.subscribe_loop.build_subscribe_subject`
//!   for the same arguments.
//! - `--version`              — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help` — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success: `info` / `build-subject` / `--help` / `--version`
//!   1  — internal error (reserved for future I/O-bound subcommands)
//!  64  — usage error (unknown subcommand, missing argument,
//!         malformed env / persona-slug shape)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No clap, no anyhow, no env_logger — the
//! binary is a static-link-friendly thin shim for the Container-
//! Image-Build-Pipeline (Tag-33 Mini-Welle, ADR-0066 Welle-6 image-
//! build). Parity with the `wakir-persona-engine-state-backing` and
//! `wakir-persona-engine-fsm` operator-CLI surface.
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-6 `subscribe_loop` — image-build
//!   pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-subscribe-loop.yml` workflow
//!   publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.

use std::process::ExitCode;

use persona_engine_subscribe_loop::ack_record::{
    ACK_RECORD_SCHEMA, OUTCOME_EMPTY_PAYLOAD, OUTCOME_MALFORMED,
    OUTCOME_PERSONA_MISMATCH, OUTCOME_PROCESSED, OUTCOME_REJECTED,
    VALID_OUTCOMES,
};
use persona_engine_subscribe_loop::{
    build_subscribe_subject, ACCEPTED_INBOUND_SCHEMA,
    OUTBOUND_OUTPUT_SCHEMA, SUBSCRIBE_SUBJECT_TEMPLATE,
};

const USAGE: &str = "\
usage:
    wakir-persona-engine-subscribe-loop info
    wakir-persona-engine-subscribe-loop build-subject ENV PERSONA_SLUG
    wakir-persona-engine-subscribe-loop --version
    wakir-persona-engine-subscribe-loop --help

Print the canonical NATS-JetStream subscribe-loop schema constants
(inbound + outbound + ack-record schemas, subject template, valid
outcomes), or render the subject string for a given (env, persona-slug)
pair. Output is machine-parseable (key=value lines).
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
        "build-subject" => run_build_subject(argv),
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
    // Operator-discovery banner — prints the canonical schema strings,
    // the subject template and the five valid outcome strings.
    println!("accepted_inbound_schema={ACCEPTED_INBOUND_SCHEMA}");
    println!("outbound_output_schema={OUTBOUND_OUTPUT_SCHEMA}");
    println!("ack_record_schema={ACK_RECORD_SCHEMA}");
    println!("subject_template={SUBSCRIBE_SUBJECT_TEMPLATE}");
    println!("outcome_processed={OUTCOME_PROCESSED}");
    println!("outcome_malformed={OUTCOME_MALFORMED}");
    println!("outcome_persona_mismatch={OUTCOME_PERSONA_MISMATCH}");
    println!("outcome_rejected={OUTCOME_REJECTED}");
    println!("outcome_empty_payload={OUTCOME_EMPTY_PAYLOAD}");
    println!("valid_outcomes={}", VALID_OUTCOMES.join(","));
    println!(
        "python_authority=wirelang.persona_engine.subscribe_loop"
    );
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

fn run_build_subject(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 4 {
        eprintln!(
            "error: `build-subject` takes exactly two arguments: \
             ENV PERSONA_SLUG"
        );
        eprintln!("{USAGE}");
        return Err(64);
    }
    let env_name = &argv[2];
    let persona_slug = &argv[3];
    match build_subscribe_subject(env_name, persona_slug) {
        Ok(subject) => {
            println!("{subject}");
            Ok(0)
        }
        Err(err) => {
            eprintln!("error: {err}");
            Err(64)
        }
    }
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
            "fetch".into(),
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
    fn run_build_subject_renders_subject() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "build-subject".into(),
            "dev".into(),
            "selin".into(),
        ];
        let result = run_build_subject(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_build_subject_with_bad_args_exits_64() {
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "build-subject".into(),
        ];
        let result = run_build_subject(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_build_subject_with_invalid_persona_slug_exits_64() {
        // Empty persona-slug is rejected by build_subscribe_subject.
        let argv = vec![
            "wakir-persona-engine-subscribe-loop".into(),
            "build-subject".into(),
            "dev".into(),
            "".into(),
        ];
        let result = run_build_subject(&argv);
        assert!(matches!(result, Err(64)));
    }
}
