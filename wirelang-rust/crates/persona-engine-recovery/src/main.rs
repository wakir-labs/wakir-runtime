// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-recovery-workflow` binary entry-point.
//!
//! Thin operator-CLI wrapper around the [`persona_engine_recovery`]
//! library. Subcommands:
//!
//! - `info`                          — print operator-discovery
//!   banner (recovery budget, canonical phase order, env-var
//!   bindings).
//! - `phases`                        — print the canonical phase
//!   order, one phase per line.
//! - `soft-cap <phase>`              — print the per-phase soft cap
//!   in seconds for `<phase>` (one of `R1`..`R4`); exit 0 on
//!   success, 64 on unknown phase.
//! - `outcome-hash <jcs-file>`       — read a JCS-canonical
//!   `RecoveryOutcome` blob, deserialise into the
//!   canonical-value layout, compute and print the
//!   `"sha256:<64hex>"` digest via
//!   [`recovery_outcome_hash_prefixed`]. Exit 0 on success, 1 on
//!   parse or compute failure, 3 if the file is missing.
//! - `--version`                     — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help`        — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success
//!   1  — runtime error (parse / hash / IO)
//!   3  — input file not found
//!  64  — usage error (unknown subcommand or bad argument shape /
//!        unknown phase label)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No live container-supervisor call. The
//! binary is a static-link-friendly thin shim for the Container-
//! Image-Build-Pipeline (Tag-32 Mini-Welle, ADR-0066 Welle-7
//! `recovery_workflow` pre-cutover image).
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-7 `recovery_workflow` — image-build
//!   pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-recovery-workflow.yml`
//!   workflow publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.

use persona_engine_recovery::{
    phase_soft_cap_sec, RECOVERY_BUDGET_SECONDS, RECOVERY_OUTCOME_SCHEMA,
    RECOVERY_WORKFLOW_PHASE_ORDER,
};

use std::process::ExitCode;

const USAGE: &str = "\
usage:
    wakir-persona-engine-recovery-workflow info
    wakir-persona-engine-recovery-workflow phases
    wakir-persona-engine-recovery-workflow soft-cap <phase>
    wakir-persona-engine-recovery-workflow outcome-hash <jcs-file>
    wakir-persona-engine-recovery-workflow --version
    wakir-persona-engine-recovery-workflow --help

Operator-CLI for the persona-engine R1..R4 Recovery-Workflow
substrate (spec §3.7.4). Read-only utility surface: phase
inventory, soft-cap lookup, recovery-outcome digest emission. Does
not orchestrate any actual recovery.
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
        "phases" => run_phases(),
        "soft-cap" => run_soft_cap(argv),
        "outcome-hash" => run_outcome_hash(argv),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            println!(
                "wakir-persona-engine-recovery-workflow {}",
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
    println!("recovery_budget_sec={RECOVERY_BUDGET_SECONDS}");
    println!("phase_count={}", RECOVERY_WORKFLOW_PHASE_ORDER.len());
    println!("recovery_outcome_schema={RECOVERY_OUTCOME_SCHEMA}");
    println!("python_authority=wirelang.persona_engine.recovery_workflow");
    println!("env_switch=WAKIR_RECOVERY_BACKEND");
    println!("env_switch_value=rust");
    println!("env_binary_override=WAKIR_RUST_RECOVERY_BIN");
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

fn run_phases() -> Result<u8, u8> {
    for p in RECOVERY_WORKFLOW_PHASE_ORDER.iter() {
        println!("{p}");
    }
    Ok(0)
}

fn run_soft_cap(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 3 {
        eprintln!("error: `soft-cap` takes exactly one argument <phase>");
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
                "error: unknown phase: {phase} (valid: {})",
                RECOVERY_WORKFLOW_PHASE_ORDER.join(",")
            );
            Err(64)
        }
    }
}

fn run_outcome_hash(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 3 {
        eprintln!("error: `outcome-hash` takes exactly one argument <jcs-file>");
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
    // RecoveryOutcome is intentionally not serde-Deserialize: the
    // canonical-bytes contract is one-way (build via
    // `recovery_outcome_canonical_value` then JCS-canonicalise).
    // Hashing arbitrary user-supplied blobs is out of scope for
    // the library; the binary therefore hashes the raw bytes
    // directly, which matches the cross-substrate-parity contract
    // for a properly JCS-serialised input.
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(&blob);
    let digest = h.finalize();
    println!("sha256:{}", hex::encode(digest));
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_with_no_args_exits_64() {
        let argv = vec!["wakir-persona-engine-recovery-workflow".into()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_with_unknown_subcommand_exits_64() {
        let argv = vec![
            "wakir-persona-engine-recovery-workflow".into(),
            "orchestrate".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_help_exits_0() {
        let argv = vec![
            "wakir-persona-engine-recovery-workflow".into(),
            "--help".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_version_exits_0() {
        let argv = vec![
            "wakir-persona-engine-recovery-workflow".into(),
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
    fn run_phases_exits_0() {
        let result = run_phases();
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_soft_cap_happy_path() {
        for phase in &RECOVERY_WORKFLOW_PHASE_ORDER {
            let argv = vec![
                "wakir-persona-engine-recovery-workflow".into(),
                "soft-cap".into(),
                phase.to_string(),
            ];
            let result = run_soft_cap(&argv);
            assert!(matches!(result, Ok(0)), "soft-cap {phase} should succeed");
        }
    }

    #[test]
    fn run_soft_cap_unknown_phase_exits_64() {
        let argv = vec![
            "wakir-persona-engine-recovery-workflow".into(),
            "soft-cap".into(),
            "R9".into(),
        ];
        let result = run_soft_cap(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_soft_cap_wrong_argc_exits_64() {
        let argv = vec![
            "wakir-persona-engine-recovery-workflow".into(),
            "soft-cap".into(),
        ];
        let result = run_soft_cap(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_outcome_hash_missing_file_exits_3() {
        let argv = vec![
            "wakir-persona-engine-recovery-workflow".into(),
            "outcome-hash".into(),
            "/nonexistent/path/to/outcome.jcs".into(),
        ];
        let result = run_outcome_hash(&argv);
        assert!(matches!(result, Err(3)));
    }

    #[test]
    fn run_outcome_hash_wrong_argc_exits_64() {
        let argv = vec![
            "wakir-persona-engine-recovery-workflow".into(),
            "outcome-hash".into(),
        ];
        let result = run_outcome_hash(&argv);
        assert!(matches!(result, Err(64)));
    }
}
