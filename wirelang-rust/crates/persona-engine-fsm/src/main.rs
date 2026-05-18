// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-fsm` binary entry-point.
//!
//! Tag-33 Mini-Welle (ADR-0066 Welle-5 `lifecycle_state_machine`
//! pre-cutover image, parallel to ADR-0066 Welle-1 V907-verify,
//! Welle-2 SVID-workload-identity, Welle-3 bridge-audit-writer and
//! Welle-4 state-backing image-builds).
//!
//! Thin operator-CLI wrapper around the [`persona_engine_fsm`]
//! library. Two payload subcommands plus the standard `--help` /
//! `--version` surface:
//!
//! - `info` — print the canonical FSM substrate (six lifecycle
//!   states, nine valid transitions, lifecycle-trace schema string)
//!   plus the binary version. Always exits 0. Format is machine-
//!   parseable (one `key=value` pair per line) so an operator script
//!   can grep without a JSON dependency.
//! - `validate FROM TO` — exit 0 if `(from, to)` is in
//!   [`VALID_TRANSITIONS`], exit 3 if rejected, exit 64 on malformed
//!   state names. The wire-strings (`uninstantiated | spawning |
//!   running | despawning | recovered | migrated`) are the closed
//!   enumeration from persona-engine-format-spec §3.3.
//! - `--version`              — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help` — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success: `info` / `validate` accepted / `--help` / `--version`
//!   1  — internal error (reserved for future I/O-bound subcommands)
//!   3  — `validate`: transition rejected (edge not in VALID_TRANSITIONS)
//!  64  — usage error (unknown subcommand, missing argument, unknown
//!         state wire-string)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No clap, no anyhow, no env_logger — the
//! binary is a static-link-friendly thin shim for the Container-
//! Image-Build-Pipeline (Tag-33 Mini-Welle, ADR-0066 Welle-5 image-
//! build). Parity with the `wakir-persona-engine-state-backing` and
//! `wakir-persona-engine-bridge-audit-writer` operator-CLI surface.
//!
//! Wire-shape determinism contract
//! -------------------------------
//!
//! The Python pendant
//! `wirelang.persona_engine.lifecycle_state_machine` is the
//! single-source-of-truth for the state and transition wire-strings.
//! The cross-language pin tests (PR #65, spec §3.3) enforce that the
//! Rust [`STATES`] / [`VALID_TRANSITIONS`] arrays produce the same
//! wire-strings as the Python `STATES` / `VALID_TRANSITIONS` tuples
//! byte-for-byte.
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-5 `lifecycle_state_machine` — image-
//!   build pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-lifecycle-state-machine.yml`
//!   workflow publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.
//! - persona-engine-format-spec §3.3 — six-state, nine-transition
//!   envelope.

use std::process::ExitCode;

use persona_engine_fsm::canonical::LIFECYCLE_TRACE_SCHEMA;
use persona_engine_fsm::{
    is_valid_transition, FsmState, STATES, VALID_TRANSITIONS,
};

const USAGE: &str = "\
usage:
    wakir-persona-engine-fsm info
    wakir-persona-engine-fsm validate FROM TO
    wakir-persona-engine-fsm --version
    wakir-persona-engine-fsm --help

Print the canonical lifecycle states and transitions of the
persona-engine FSM module (spec §3.3, six states, nine transitions),
or validate whether a (FROM, TO) edge is a valid transition. Output is
machine-parseable (key=value lines).
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
        "validate" => run_validate(argv),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            println!(
                "wakir-persona-engine-fsm {}",
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
    // Operator-discovery banner — prints all six lifecycle states,
    // all nine valid transitions, the lifecycle-trace schema string
    // and the binary version. Format is intentionally machine-
    // parseable (one ``key=value`` pair per line).
    let states: Vec<&'static str> =
        STATES.iter().map(|s| s.as_wire_str()).collect();
    println!("states={}", states.join(","));
    println!("state_count={}", STATES.len());
    for (i, t) in VALID_TRANSITIONS.iter().enumerate() {
        println!(
            "transition_{}={}->{}",
            i,
            t.from.as_wire_str(),
            t.to.as_wire_str()
        );
    }
    println!("transition_count={}", VALID_TRANSITIONS.len());
    println!("lifecycle_trace_schema={LIFECYCLE_TRACE_SCHEMA}");
    println!(
        "python_authority=wirelang.persona_engine.lifecycle_state_machine"
    );
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

fn run_validate(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 4 {
        eprintln!(
            "error: `validate` takes exactly two arguments: FROM TO"
        );
        eprintln!("{USAGE}");
        return Err(64);
    }
    let from = match FsmState::from_wire_str(&argv[2]) {
        Ok(s) => s,
        Err(_) => {
            eprintln!(
                "error: unknown FROM state: {:?} (expected one of: {})",
                argv[2],
                STATES
                    .iter()
                    .map(|s| s.as_wire_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            );
            return Err(64);
        }
    };
    let to = match FsmState::from_wire_str(&argv[3]) {
        Ok(s) => s,
        Err(_) => {
            eprintln!(
                "error: unknown TO state: {:?} (expected one of: {})",
                argv[3],
                STATES
                    .iter()
                    .map(|s| s.as_wire_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            );
            return Err(64);
        }
    };
    if is_valid_transition(from, to) {
        println!(
            "valid={}->{}",
            from.as_wire_str(),
            to.as_wire_str()
        );
        Ok(0)
    } else {
        eprintln!(
            "rejected={}->{}",
            from.as_wire_str(),
            to.as_wire_str()
        );
        Err(3)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_with_no_args_exits_64() {
        let argv = vec!["wakir-persona-engine-fsm".into()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_with_unknown_subcommand_exits_64() {
        let argv = vec![
            "wakir-persona-engine-fsm".into(),
            "fetch".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_help_exits_0() {
        let argv = vec![
            "wakir-persona-engine-fsm".into(),
            "--help".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_version_exits_0() {
        let argv = vec![
            "wakir-persona-engine-fsm".into(),
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
    fn run_validate_accepted_transition_exits_0() {
        let argv = vec![
            "wakir-persona-engine-fsm".into(),
            "validate".into(),
            "uninstantiated".into(),
            "spawning".into(),
        ];
        let result = run_validate(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_validate_rejected_transition_exits_3() {
        // (running -> uninstantiated) is not in VALID_TRANSITIONS.
        let argv = vec![
            "wakir-persona-engine-fsm".into(),
            "validate".into(),
            "running".into(),
            "uninstantiated".into(),
        ];
        let result = run_validate(&argv);
        assert!(matches!(result, Err(3)));
    }

    #[test]
    fn run_validate_unknown_state_exits_64() {
        let argv = vec![
            "wakir-persona-engine-fsm".into(),
            "validate".into(),
            "bogus".into(),
            "running".into(),
        ];
        let result = run_validate(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_validate_missing_arg_exits_64() {
        let argv = vec![
            "wakir-persona-engine-fsm".into(),
            "validate".into(),
            "running".into(),
        ];
        let result = run_validate(&argv);
        assert!(matches!(result, Err(64)));
    }
}
