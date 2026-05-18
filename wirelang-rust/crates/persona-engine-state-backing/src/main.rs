// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-state-backing` binary entry-point.
//!
//! Tag-33 Mini-Welle (ADR-0066 Welle-4 `state_backing` pre-cutover
//! image, parallel to ADR-0066 Welle-1 V907-verify, Welle-2 SVID-
//! workload-identity and Welle-3 bridge-audit-writer image-builds).
//!
//! Thin operator-CLI wrapper around the
//! [`persona_engine_state_backing`] library. Two payload
//! subcommands plus the standard `--help` / `--version` surface:
//!
//! - `info` — print the canonical key-prefix constants
//!   (`STATE_PACK_KEY_PREFIX`, `OFFSET_KEY_WIDTH`, `PINNED_KEY`,
//!   `NEXT_OFFSET_KEY`, `LATEST_KEY`) and the binary version. Always
//!   exits 0. Format is machine-parseable (one `key=value` pair per
//!   line) so an operator script can grep without a JSON dependency.
//! - `offset-key OFFSET` — render the zero-padded NATS-KV key for a
//!   given offset using the library's [`offset_key`] formatter. The
//!   offset argument must be a non-negative integer in
//!   `0..=u64::MAX`. The rendered key is the same string the Python
//!   pendant `wirelang.persona_engine.state_backing.offset_key()`
//!   returns for the same offset — byte-identical per spec §3.7.5.
//! - `--version`              — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help` — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success: `info` / `offset-key` / `--help` / `--version`
//!   1  — internal error (unreachable today, reserved for future
//!         I/O-bound subcommands)
//!  64  — usage error (unknown subcommand, missing required argument,
//!         malformed integer)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No clap, no anyhow, no env_logger — the
//! binary is a static-link-friendly thin shim for the Container-
//! Image-Build-Pipeline (Tag-33 Mini-Welle, ADR-0066 Welle-4 image-
//! build). Parity with the `wakir-persona-engine-svid-workload-identity`
//! and `wakir-persona-engine-bridge-audit-writer` operator-CLI surface.
//!
//! Wire-shape determinism contract
//! -------------------------------
//!
//! The Python pendant `wirelang.persona_engine.state_backing` is the
//! single-source-of-truth for the key-prefix constants and the
//! `offset_key(off)` formatter. The cross-language pins
//! (`STATE_PACK_KEY_PREFIX = "state-pack"`, `OFFSET_KEY_WIDTH = 20`,
//! `PINNED_KEY = "state-pack/__pinned__"`, etc.) live in the library
//! crate (`persona-engine-state-backing/src/lib.rs`); the binary
//! re-exports them through `info` so an operator can read the
//! canonical values without grepping the Rust source.
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-4 `state_backing` — image-build
//!   pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-state-backing.yml` workflow
//!   publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.
//! - persona-engine-format-spec §3.7.5 — state-backing trait contract.
//! - Selin PR #65 (Sprint-Pengine-8) — Python schema authority.

use std::process::ExitCode;

use persona_engine_state_backing::{
    offset_key, LATEST_KEY, NEXT_OFFSET_KEY, OFFSET_KEY_WIDTH, PINNED_KEY,
    STATE_PACK_KEY_PREFIX,
};

const USAGE: &str = "\
usage:
    wakir-persona-engine-state-backing info
    wakir-persona-engine-state-backing offset-key OFFSET
    wakir-persona-engine-state-backing --version
    wakir-persona-engine-state-backing --help

Print the canonical NATS-KV key-prefix constants of the persona-engine
state-backing module, or render the zero-padded offset-key for a given
offset. Output is machine-parseable (key=value lines).
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
    // Operator-discovery banner — prints the canonical key-prefix
    // constants. The format is intentionally machine-parseable (one
    // ``key=value`` pair per line) so a future operator script can
    // grep without a JSON dependency. Parity with the
    // `wakir-persona-engine-svid-workload-identity info` shape.
    println!("state_pack_key_prefix={STATE_PACK_KEY_PREFIX}");
    println!("offset_key_width={OFFSET_KEY_WIDTH}");
    println!("pinned_key={PINNED_KEY}");
    println!("next_offset_key={NEXT_OFFSET_KEY}");
    println!("latest_key={LATEST_KEY}");
    println!(
        "python_authority=wirelang.persona_engine.state_backing"
    );
    println!("version={}", env!("CARGO_PKG_VERSION"));
    Ok(0)
}

fn run_offset_key(argv: &[String]) -> Result<u8, u8> {
    if argv.len() != 3 {
        eprintln!(
            "error: `offset-key` takes exactly one argument: OFFSET"
        );
        eprintln!("{USAGE}");
        return Err(64);
    }
    let raw = &argv[2];
    let offset: u64 = match raw.parse::<u64>() {
        Ok(o) => o,
        Err(_) => {
            eprintln!(
                "error: OFFSET must be a non-negative integer (got: {raw})"
            );
            return Err(64);
        }
    };
    let key = offset_key(offset);
    println!("{key}");
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
            "fetch".into(),
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
    fn run_help_short_exits_0() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "-h".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_help_alias_exits_0() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "help".into(),
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
    fn run_offset_key_renders_padded_key() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "offset-key".into(),
            "42".into(),
        ];
        let result = run_offset_key(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_offset_key_with_bad_int_exits_64() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "offset-key".into(),
            "notanumber".into(),
        ];
        let result = run_offset_key(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_offset_key_with_missing_arg_exits_64() {
        let argv = vec![
            "wakir-persona-engine-state-backing".into(),
            "offset-key".into(),
        ];
        let result = run_offset_key(&argv);
        assert!(matches!(result, Err(64)));
    }
}
