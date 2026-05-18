// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-recovery` binary entry-point.
//!
//! Tag-33 Mini-Welle (ADR-0066 Welle-7 `recovery_workflow` pre-cutover
//! image, parallel to ADR-0066 Welle-1 V907-verify, Welle-2 SVID-
//! workload-identity, Welle-3 bridge-audit-writer, Welle-4 state-
//! backing, Welle-5 lifecycle-state-machine and Welle-6 subscribe-loop
//! image-builds).
//!
//! Thin operator-CLI wrapper around the
//! [`persona_engine_recovery`] library. Two payload subcommands
//! plus the standard `--help` / `--version` surface:
//!
//! - `info` — print the canonical R1..R4 phase-order constant, the
//!   30-second total recovery budget, the per-phase soft-cap seconds
//!   and the canonical recovery-outcome schema string. Always exits 0.
//!   Format is machine-parseable (one `key=value` pair per line).
//! - `soft-cap PHASE` — print the soft-cap seconds for a given phase
//!   (R1..R4) using the library's [`phase_soft_cap_sec`] lookup. Exits
//!   64 if the phase label is unknown.
//! - `--version`              — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help` — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success: `info` / `soft-cap` / `--help` / `--version`
//!   1  — internal error (reserved for future I/O-bound subcommands)
//!  64  — usage error (unknown subcommand, missing argument, unknown
//!         phase label)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No clap, no anyhow, no env_logger — the
//! binary is a static-link-friendly thin shim for the Container-
//! Image-Build-Pipeline (Tag-33 Mini-Welle, ADR-0066 Welle-7 image-
//! build). Parity with the prior six Phase-3b Rust-CLI operator
//! binaries (recovery is the lex-first entry in the cosign-policy
//! 13-binary inventory).
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-7 `recovery_workflow` — image-build
//!   pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-recovery-workflow.yml` workflow
//!   publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.
//! - persona-engine-format-spec §3.7.4 — R1..R4 recovery-workflow
//!   contract.

use std::process::ExitCode;

use persona_engine_recovery::{
    phase_soft_cap_sec, RECOVERY_BUDGET_SECONDS,
    RECOVERY_OUTCOME_SCHEMA, RECOVERY_WORKFLOW_PHASE_ORDER,
};

const USAGE: &str = "\
usage:
    wakir-persona-engine-recovery info
    wakir-persona-engine-recovery soft-cap PHASE
    wakir-persona-engine-recovery --version
    wakir-persona-engine-recovery --help

Print the canonical R1..R4 recovery-workflow spec constants (phase
order, 30s total budget, per-phase soft-caps, canonical outcome
schema), or look up the soft-cap seconds for a given phase label.
Output is machine-parseable (key=value lines).
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
        "soft-cap" => run_soft_cap(argv),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            println!(
                "wakir-persona-engine-recovery {}",
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
    // Operator-discovery banner — prints the canonical R1..R4 phase-
    // order, the 30s total budget, per-phase soft-cap seconds and the
    // canonical recovery-outcome schema string.
    println!(
        "phase_order={}",
        RECOVERY_WORKFLOW_PHASE_ORDER.join(",")
    );
    println!("recovery_budget_seconds={RECOVERY_BUDGET_SECONDS}");
    for phase in RECOVERY_WORKFLOW_PHASE_ORDER.iter() {
        if let Some(cap) = phase_soft_cap_sec(phase) {
            println!("soft_cap_sec_{phase}={cap}");
        }
    }
    println!("recovery_outcome_schema={RECOVERY_OUTCOME_SCHEMA}");
    println!(
        "python_authority=wirelang.persona_engine.recovery_workflow"
    );
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

fn run_soft_cap(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 3 {
        eprintln!(
            "error: `soft-cap` takes exactly one argument: PHASE"
        );
        eprintln!("{USAGE}");
        return Err(64);
    }
    let phase = &argv[2];
    match phase_soft_cap_sec(phase) {
        Some(cap) => {
            println!("{cap}");
            Ok(0)
        }
        None => {
            eprintln!(
                "error: unknown PHASE {:?} (expected one of: {})",
                phase,
                RECOVERY_WORKFLOW_PHASE_ORDER.join(", ")
            );
            Err(64)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_with_no_args_exits_64() {
        let argv = vec!["wakir-persona-engine-recovery".into()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_with_unknown_subcommand_exits_64() {
        let argv = vec![
            "wakir-persona-engine-recovery".into(),
            "fetch".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_help_exits_0() {
        let argv = vec![
            "wakir-persona-engine-recovery".into(),
            "--help".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_version_exits_0() {
        let argv = vec![
            "wakir-persona-engine-recovery".into(),
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
    fn run_soft_cap_known_phase_exits_0() {
        let argv = vec![
            "wakir-persona-engine-recovery".into(),
            "soft-cap".into(),
            "R2".into(),
        ];
        let result = run_soft_cap(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_soft_cap_unknown_phase_exits_64() {
        let argv = vec![
            "wakir-persona-engine-recovery".into(),
            "soft-cap".into(),
            "R99".into(),
        ];
        let result = run_soft_cap(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_soft_cap_missing_arg_exits_64() {
        let argv = vec![
            "wakir-persona-engine-recovery".into(),
            "soft-cap".into(),
        ];
        let result = run_soft_cap(&argv);
        assert!(matches!(result, Err(64)));
    }
}
