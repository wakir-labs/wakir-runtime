// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-lifecycle-state-machine` binary entry-point.
//!
//! Thin operator-CLI wrapper around the [`persona_engine_fsm`]
//! library. Subcommands:
//!
//! - `info`                        — print operator-discovery banner
//!   (spec wire-strings of the six states, count of valid
//!   transitions, env-var bindings).
//! - `states`                      — print the six lifecycle-state
//!   wire-strings, one per line, in spec order (PR #65 §3.3).
//! - `transitions`                 — print the nine valid transitions
//!   as `from -> to` lines, in `VALID_TRANSITIONS` order.
//! - `can <from> <to>`             — exit 0 if the transition is
//!   valid per spec §3.3, exit 1 otherwise. Stdout prints either
//!   `valid` or `invalid` for operator legibility.
//! - `trace-hash <jcs-file>`       — read a JCS-canonical
//!   LifecycleTrace blob from `<jcs-file>`, parse it via serde_json
//!   into the canonical `LifecycleTrace` struct, compute and print
//!   the `"sha256:<64hex>"` SHA-256 of the JCS bytes via
//!   [`trace_hash_prefixed`]. Exit 0 on success, 1 on parse or
//!   compute failure, 3 if the file is missing. Note: the input
//!   file must already be a JCS-canonical `LifecycleTrace` blob;
//!   this CLI does NOT canonicalise arbitrary JSON input.
//! - `--version`                   — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help`      — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success (or `can` returns valid)
//!   1  — runtime error (parse / hash / IO) OR `can` returns invalid
//!   3  — input file not found
//!  64  — usage error (unknown subcommand or bad argument shape)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. Wire-string outputs match the Python
//! reference byte-for-byte. The binary is a static-link-friendly
//! thin shim for the Container-Image-Build-Pipeline (Tag-32 Mini-
//! Welle, ADR-0066 Welle-5 `lifecycle_state_machine` pre-cutover
//! image).
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-5 `lifecycle_state_machine` — image-
//!   build pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-lifecycle-state-machine.yml`
//!   workflow publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.

use persona_engine_fsm::canonical::{trace_hash_prefixed, LifecycleTrace};
use persona_engine_fsm::{is_valid_transition, FsmState, STATES, VALID_TRANSITIONS};

use std::process::ExitCode;

const USAGE: &str = "\
usage:
    wakir-persona-engine-lifecycle-state-machine info
    wakir-persona-engine-lifecycle-state-machine states
    wakir-persona-engine-lifecycle-state-machine transitions
    wakir-persona-engine-lifecycle-state-machine can <from> <to>
    wakir-persona-engine-lifecycle-state-machine trace-hash <jcs-file>
    wakir-persona-engine-lifecycle-state-machine --version
    wakir-persona-engine-lifecycle-state-machine --help

Operator-CLI for the persona-engine lifecycle state-machine (spec
§3.3, six states + nine transitions). Read-only utility surface:
state inventory, transition-validity check, canonical-trace digest
emission. Does not mutate any persona state.
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
        "states" => run_states(),
        "transitions" => run_transitions(),
        "can" => run_can(argv),
        "trace-hash" => run_trace_hash(argv),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            println!(
                "wakir-persona-engine-lifecycle-state-machine {}",
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
    println!("spec_anchor=persona-engine-format-spec/§3.3");
    println!("state_count={}", STATES.len());
    println!("transition_count={}", VALID_TRANSITIONS.len());
    println!("python_authority=wirelang.persona_engine.lifecycle_state_machine");
    println!("env_switch=WAKIR_FSM_BACKEND");
    println!("env_switch_value=rust");
    println!("env_binary_override=WAKIR_RUST_FSM_BIN");
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

fn run_states() -> Result<u8, u8> {
    for s in STATES {
        println!("{}", s.as_wire_str());
    }
    Ok(0)
}

fn run_transitions() -> Result<u8, u8> {
    for t in VALID_TRANSITIONS {
        println!("{} -> {}", t.from.as_wire_str(), t.to.as_wire_str());
    }
    Ok(0)
}

fn run_can(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 4 {
        eprintln!("error: `can` takes exactly two arguments <from> <to>");
        eprintln!("{USAGE}");
        return Err(64);
    }
    let from = match parse_state(&argv[2]) {
        Some(s) => s,
        None => {
            eprintln!("error: unknown state: {}", argv[2]);
            return Err(64);
        }
    };
    let to = match parse_state(&argv[3]) {
        Some(s) => s,
        None => {
            eprintln!("error: unknown state: {}", argv[3]);
            return Err(64);
        }
    };
    if is_valid_transition(from, to) {
        println!("valid");
        Ok(0)
    } else {
        println!("invalid");
        Err(1)
    }
}

fn run_trace_hash(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 3 {
        eprintln!("error: `trace-hash` takes exactly one argument <jcs-file>");
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
    let trace: LifecycleTrace = match serde_json::from_slice(&blob) {
        Ok(t) => t,
        Err(err) => {
            eprintln!("error: trace parse failed: {err}");
            return Err(1);
        }
    };
    let hash = trace_hash_prefixed(&trace);
    println!("{hash}");
    Ok(0)
}

fn parse_state(s: &str) -> Option<FsmState> {
    for spec_state in STATES {
        if spec_state.as_wire_str() == s {
            return Some(*spec_state);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_with_no_args_exits_64() {
        let argv = vec!["wakir-persona-engine-lifecycle-state-machine".into()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_with_unknown_subcommand_exits_64() {
        let argv = vec![
            "wakir-persona-engine-lifecycle-state-machine".into(),
            "mutate".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_help_exits_0() {
        let argv = vec![
            "wakir-persona-engine-lifecycle-state-machine".into(),
            "--help".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_version_exits_0() {
        let argv = vec![
            "wakir-persona-engine-lifecycle-state-machine".into(),
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
    fn run_states_exits_0() {
        let result = run_states();
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_transitions_exits_0() {
        let result = run_transitions();
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_can_unknown_state_exits_64() {
        let argv = vec![
            "wakir-persona-engine-lifecycle-state-machine".into(),
            "can".into(),
            "not-a-state".into(),
            "running".into(),
        ];
        let result = run_can(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_can_wrong_argc_exits_64() {
        let argv = vec![
            "wakir-persona-engine-lifecycle-state-machine".into(),
            "can".into(),
            "running".into(),
        ];
        let result = run_can(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_trace_hash_missing_file_exits_3() {
        let argv = vec![
            "wakir-persona-engine-lifecycle-state-machine".into(),
            "trace-hash".into(),
            "/nonexistent/path/to/trace.jcs".into(),
        ];
        let result = run_trace_hash(&argv);
        assert!(matches!(result, Err(3)));
    }

    #[test]
    fn parse_state_round_trip_all_states() {
        for s in STATES {
            let wire = s.as_wire_str();
            let parsed = parse_state(wire);
            assert_eq!(parsed, Some(*s), "round-trip failure for {wire}");
        }
    }
}
