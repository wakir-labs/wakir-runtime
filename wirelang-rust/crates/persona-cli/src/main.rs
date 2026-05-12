// SPDX-License-Identifier: Apache-2.0
//! `wakir-persona` binary entry-point.
//!
//! Thin wrapper around [`persona_cli::run`]. All logic lives in the
//! library crate so the test pack can drive it without spawning a
//! subprocess. The binary's only jobs are:
//!
//! 1. Collect `argv` from the process environment.
//! 2. Call [`persona_cli::run`] with the captured argv.
//! 3. Write the captured stdout / stderr to the real streams.
//! 4. Exit with the captured exit code.
//!
//! See `lib.rs` for the public surface and the exit-code mapping.

use std::process::ExitCode;

use persona_cli::{run, write_outcome};

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().collect();
    let argv_refs: Vec<&str> = argv.iter().map(String::as_str).collect();
    let outcome = run(&argv_refs);
    let code = write_outcome(&outcome);
    // `ExitCode::from` only takes u8, so clamp the i32 exit code into
    // u8 range (Unix exit codes are 8-bit anyway; values >255 wrap
    // mod 256 in the kernel). Our exit codes are 0-3 + 64; all fit.
    ExitCode::from(code.clamp(0, 255) as u8)
}
