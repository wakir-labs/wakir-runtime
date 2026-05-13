// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona-convert` binary entry-point.
//!
//! Thin wrapper around [`persona_converter::run`]. Mirror of the
//! `persona-cli` Crate-6 main.rs posture.

use std::process::ExitCode;

use persona_converter::{run, write_outcome};

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().collect();
    let argv_refs: Vec<&str> = argv.iter().map(String::as_str).collect();
    let outcome = run(&argv_refs);
    let code = write_outcome(&outcome);
    ExitCode::from(code.clamp(0, 255) as u8)
}
