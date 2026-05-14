// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-pilot-export` binary entry-point.
//!
//! Mirror of the persona-converter Crate-9 main.rs posture: parse argv,
//! delegate to [`persona_pilot_export::run_cli`], map the error to an
//! exit code and print to stderr.

use std::process::ExitCode;

use clap::Parser;
use persona_pilot_export::{run_cli, Cli, EXIT_OK, EXIT_USAGE_ERROR};

fn main() -> ExitCode {
    let cli = match Cli::try_parse() {
        Ok(c) => c,
        Err(e) => {
            // clap prints help / usage to stdout for help/version and to
            // stderr otherwise; we honour clap's stream and just remap
            // the exit code (clap default 2 -> 64 EX_USAGE).
            let _ = e.print();
            let code = if e.exit_code() == 0 {
                EXIT_OK
            } else {
                EXIT_USAGE_ERROR
            };
            return ExitCode::from(code.clamp(0, 255) as u8);
        }
    };

    match run_cli(&cli) {
        Ok(()) => ExitCode::from(EXIT_OK.clamp(0, 255) as u8),
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::from(e.to_exit_code().clamp(0, 255) as u8)
        }
    }
}
