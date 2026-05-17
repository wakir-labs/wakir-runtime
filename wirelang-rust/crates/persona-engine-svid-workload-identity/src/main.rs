// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-engine-svid-workload-identity` binary entry-point.
//!
//! Thin operator-CLI wrapper around the
//! [`persona_engine_svid_workload_identity`] library. Three
//! subcommands:
//!
//! - `probe [--socket PATH]`  — socket-presence probe of the SPIFFE
//!   Workload-API Unix domain socket. Defaults to
//!   [`DEFAULT_WORKLOAD_API_SOCKET_PATH`]
//!   (`/run/spire/agent-sockets/api.sock`). Prints a one-line
//!   summary to stdout and exits with the
//!   [`ProbeOutcome::exit_code`] of the result.
//! - `info`                   — print the default socket path + the
//!   Quadlet bind-mount contract reference. Always exits 0.
//! - `--version`              — `CARGO_PKG_VERSION` build-time string.
//! - `--help` / `-h` / `help` — usage banner.
//!
//! Exit codes
//! ----------
//!
//!   0  — success: probe reachable, or `info` / `--help` / `--version`
//!   1  — internal error (unexpected I/O failure unrelated to probe)
//!   2  — probe: socket path missing
//!   3  — probe: socket present but `connect()` failed
//!  64  — usage error (unknown subcommand or bad argument shape)
//!
//! Posture
//! -------
//!
//! Zero new dependencies. No clap, no anyhow, no env_logger — the
//! binary is a static-link-friendly thin shim for the Container-
//! Image-Build-Pipeline (Tag-29 Mini-Welle, ADR-0066 Welle-2 image-
//! build).
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-2 `svid_workload_identity` — image-
//!   build pre-cutover. This binary is the artefact the
//!   `.github/workflows/build-rust-cli-svid-workload-identity.yml`
//!   workflow publishes.
//! - ADR-0060 — Cosign-Policy on Pilot-Container-Images.

use persona_engine_svid_workload_identity::{
    probe_workload_api_socket, ProbeOutcome, DEFAULT_WORKLOAD_API_SOCKET_PATH,
};

use std::process::ExitCode;

const USAGE: &str = "\
usage:
    wakir-persona-engine-svid-workload-identity probe [--socket PATH]
    wakir-persona-engine-svid-workload-identity info
    wakir-persona-engine-svid-workload-identity --version
    wakir-persona-engine-svid-workload-identity --help

Probe the SPIFFE Workload-API Unix domain socket for presence +
reachability, or print operator info about the default socket path.
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
        "probe" => run_probe(argv),
        "info" => run_info(),
        "--help" | "-h" | "help" => {
            print!("{USAGE}");
            Ok(0)
        }
        "--version" => {
            // CARGO_PKG_VERSION is set by Cargo at build time.
            println!(
                "wakir-persona-engine-svid-workload-identity {}",
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

fn run_probe(argv: &[String]) -> Result<u8, u8> {
    // Parse optional --socket PATH. The single supported form is
    // ``probe`` (defaults to DEFAULT_WORKLOAD_API_SOCKET_PATH) or
    // ``probe --socket PATH``. Any other shape is a usage error.
    let socket_path: String = match argv.len() {
        2 => DEFAULT_WORKLOAD_API_SOCKET_PATH.to_string(),
        4 if argv[2] == "--socket" => argv[3].clone(),
        _ => {
            eprintln!(
                "error: `probe` takes either no arguments or `--socket PATH`"
            );
            eprintln!("{USAGE}");
            return Err(64);
        }
    };

    let outcome = probe_workload_api_socket(&socket_path);
    // One-line summary on stdout for Reachable, stderr for failures
    // (mirrors persona-cli convention: success-path on stdout,
    // failure-path summary on stderr).
    match &outcome {
        ProbeOutcome::Reachable => {
            println!("{}", outcome.summary(&socket_path));
        }
        ProbeOutcome::SocketMissing | ProbeOutcome::ConnectFailed(_) => {
            eprintln!("{}", outcome.summary(&socket_path));
        }
    }
    let code = outcome.exit_code();
    if code == 0 {
        Ok(0)
    } else {
        Err(code)
    }
}

fn run_info() -> Result<u8, u8> {
    // Operator-discovery banner — prints the default socket path +
    // the Quadlet bind-mount contract reference. The format is
    // intentionally machine-parseable (one `key=value` pair per
    // line) so a future operator script can grep without a JSON
    // dependency.
    println!("default_socket_path={DEFAULT_WORKLOAD_API_SOCKET_PATH}");
    println!("quadlet_volume=wakir-spire-agent-sockets.volume");
    println!("quadlet_mount_target=/run/spire/agent-sockets");
    println!("python_authority=wirelang.persona_engine.svid_workload_identity");
    println!(
        "version={}",
        env!("CARGO_PKG_VERSION")
    );
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_with_no_args_exits_64() {
        let argv = vec!["wakir-persona-engine-svid-workload-identity".into()];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_with_unknown_subcommand_exits_64() {
        let argv = vec![
            "wakir-persona-engine-svid-workload-identity".into(),
            "fetch".into(), // future subcommand, not implemented yet
        ];
        let result = run(&argv);
        assert!(matches!(result, Err(64)));
    }

    #[test]
    fn run_help_exits_0() {
        let argv = vec![
            "wakir-persona-engine-svid-workload-identity".into(),
            "--help".into(),
        ];
        let result = run(&argv);
        assert!(matches!(result, Ok(0)));
    }

    #[test]
    fn run_version_exits_0() {
        let argv = vec![
            "wakir-persona-engine-svid-workload-identity".into(),
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
    fn run_probe_missing_socket_exits_2() {
        let argv = vec![
            "wakir-persona-engine-svid-workload-identity".into(),
            "probe".into(),
            "--socket".into(),
            "/nonexistent/path/to/spire/agent/socket.sock".into(),
        ];
        let result = run_probe(&argv);
        assert!(matches!(result, Err(2)));
    }

    #[test]
    fn run_probe_with_bad_args_exits_64() {
        let argv = vec![
            "wakir-persona-engine-svid-workload-identity".into(),
            "probe".into(),
            "--bogus".into(),
        ];
        let result = run_probe(&argv);
        assert!(matches!(result, Err(64)));
    }
}
