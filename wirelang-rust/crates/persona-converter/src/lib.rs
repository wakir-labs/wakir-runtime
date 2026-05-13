// SPDX-License-Identifier: Apache-2.0
//! Operator CLI for the Sprint-Pengine-7 Tag-1 mapping pipeline.
//!
//! Sprint-Pengine-7 Tag-2 implementation. Thin shim around
//! [`persona_engine_format::map_claude_native_to_wakir_v1`] for
//! ad-hoc operator use, the Self-Migration shell scripts (ADR-0036),
//! and the CI cut-over pipeline that produces the operator-side
//! pin-pack from `.claude/agents/*.md`.
//!
//! # Synopsis
//!
//! ```text
//! wakir-persona-convert from-claude
//!     --in  <path/to/claude-agent.md>
//!     --out <path/to/wakir.persona/<slug>.json>
//!     [--pin-hash-v907 <sha256:<64hex> | <64hex>>]
//!     [--quiet]
//! ```
//!
//! # Pipeline
//!
//! 1. Read the axis-A markdown text from `--in`.
//! 2. Map to axis-C `wakir-persona-v1` via
//!    [`persona_engine_format::map_claude_native_to_wakir_v1`].
//! 3. JCS-canonicalise via
//!    [`persona_engine_format::jcs_canonicalise_wakir_persona_v1`].
//! 4. If `--pin-hash-v907` is supplied, recompute the V-907 hash via
//!    [`persona_engine_format::wakir_persona_hash`] and compare it
//!    against the pin. A drift exits with code
//!    [`EXIT_HASH_DRIFT_ERROR`] (2).
//! 5. Write the JCS bytes (plus trailing newline) to `--out`.
//!
//! # Exit codes
//!
//! - `0`: success.
//! - `1`: schema / parse error (front-matter invalid, axis-A
//!   required key missing, ...).
//! - `2`: V-907 hash-drift error (recomputed hash != supplied pin).
//! - `3`: input file (`--in`) not found.
//! - `64`: argparse usage error (Unix `EX_USAGE`).
//!
//! # Posture
//!
//! Thin shim. All conversion logic lives in `persona-engine-format`;
//! this crate's only jobs are clap argparse parsing, file IO, JCS
//! canonicalisation invocation, optional pin-verification, and
//! exit-code mapping. The synthesis-default-exceptions table
//! (`SYNTHESIS_DEFAULT_EXCEPTIONS`, §4.3.1 spec v1.1) is honoured
//! transparently by the upstream mapping function — this CLI does
//! NOT duplicate the table.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use std::fs;
use std::io::Write;
use std::path::PathBuf;

use clap::{Parser, Subcommand};
use persona_engine_format::{
    jcs_canonicalise_wakir_persona_v1, map_claude_native_to_wakir_v1, wakir_persona_hash,
    PersonaEngineFormatError,
};

// ---------------------------------------------------------------------
// Exit codes (mirror of persona-cli Crate-6 §7.4).
// ---------------------------------------------------------------------

/// Success exit code.
pub const EXIT_OK: i32 = 0;

/// Schema / parse error exit code (axis-A invalid, required key missing, ...).
pub const EXIT_SCHEMA_ERROR: i32 = 1;

/// V-907 hash-drift exit code: recomputed wakir-persona-hash does not
/// match the supplied `--pin-hash-v907`.
pub const EXIT_HASH_DRIFT_ERROR: i32 = 2;

/// Input-file-not-found exit code.
pub const EXIT_INPUT_NOT_FOUND: i32 = 3;

/// Argparse usage-error exit code (Unix `EX_USAGE`). clap's default
/// is 2; we remap to 64 to mirror the Python CLI docstring spec §7.4.
pub const EXIT_USAGE_ERROR: i32 = 64;

// ---------------------------------------------------------------------
// clap parser surface
// ---------------------------------------------------------------------

/// Top-level CLI shape.
///
/// `wakir-persona-convert <command>`. The only currently registered
/// command is `from-claude`; future axis-A sources (e.g. `from-json`)
/// would land here.
#[derive(Debug, Parser)]
#[command(
    name = "wakir-persona-convert",
    about = "Operator CLI for the .claude/agents/*.md -> wakir.persona/*.json byte-deterministic converter (Sprint-Pengine-7 Tag-2, V-907 pin-verified).",
    version,
    disable_help_subcommand = true
)]
pub struct Cli {
    /// Top-level command.
    #[command(subcommand)]
    pub command: Command,
}

/// Registered subcommands.
#[derive(Debug, Subcommand)]
pub enum Command {
    /// Convert a `.claude/agents/<slug>.md` axis-A file into a
    /// `wakir.persona/<slug>.json` axis-C document.
    #[command(
        about = "Convert a .claude/agents/<slug>.md file into a wakir.persona/<slug>.json document.",
        long_about = "Read the axis-A persona-claude-native markdown file at --in, map it to axis-C wakir-persona-v1, JCS-canonicalise, optionally verify against --pin-hash-v907, and write the result to --out. See wirelang/specs/persona-engine-format-spec.md v1.1 §4 for the mapping pipeline and §4.3.1 for the synthesis-default-exceptions table."
    )]
    FromClaude(FromClaudeArgs),
}

/// Arguments for the `from-claude` subcommand.
#[derive(Debug, Parser)]
pub struct FromClaudeArgs {
    /// Filesystem path to the axis-A UTF-8 markdown persona-definition.
    #[arg(long = "in", value_name = "PATH")]
    pub input: PathBuf,

    /// Filesystem path for the axis-C JSON output. The directory must
    /// exist. Existing files are overwritten.
    #[arg(long = "out", value_name = "PATH")]
    pub output: PathBuf,

    /// Optional V-907 wakir-persona-hash pin. When supplied, the
    /// converter recomputes the hash from the produced document and
    /// asserts byte-equality with the pin. A drift exits with code
    /// [`EXIT_HASH_DRIFT_ERROR`].
    ///
    /// Accepts both bare 64-hex (`<64hex>`) and full
    /// (`sha256:<64hex>`) form.
    #[arg(long = "pin-hash-v907", value_name = "<pin>")]
    pub pin_hash_v907: Option<String>,

    /// Suppress the human-readable progress line on stderr.
    #[arg(long = "quiet", default_value_t = false)]
    pub quiet: bool,
}

// ---------------------------------------------------------------------
// Runtime outcome surface
// ---------------------------------------------------------------------

/// Captured outcome of a [`run`] invocation.
///
/// Mirrors the `persona-cli` Crate-6 surface so the test pack can
/// drive the CLI without spawning a subprocess.
#[derive(Debug)]
pub struct CliOutcome {
    /// Captured stdout bytes (typically empty for `from-claude`; the
    /// output is written to the `--out` path).
    pub stdout: Vec<u8>,
    /// Captured stderr bytes (progress line + error messages).
    pub stderr: Vec<u8>,
    /// Exit code to return to the operating system.
    pub exit_code: i32,
}

impl CliOutcome {
    /// Construct a success outcome.
    #[must_use]
    pub fn ok(stdout: Vec<u8>, stderr: Vec<u8>) -> Self {
        Self {
            stdout,
            stderr,
            exit_code: EXIT_OK,
        }
    }

    /// Construct a failure outcome.
    #[must_use]
    pub fn fail(stderr: Vec<u8>, exit_code: i32) -> Self {
        Self {
            stdout: Vec::new(),
            stderr,
            exit_code,
        }
    }
}

/// Write the captured outcome to the real stdout / stderr streams
/// and return the exit code. Used by the `main` shim.
pub fn write_outcome(outcome: &CliOutcome) -> i32 {
    let _ = std::io::stdout().write_all(&outcome.stdout);
    let _ = std::io::stderr().write_all(&outcome.stderr);
    outcome.exit_code
}

// ---------------------------------------------------------------------
// Top-level entry-point
// ---------------------------------------------------------------------

/// Run the CLI with the supplied argv.
///
/// The first element of `argv` is the program name (matching the
/// `std::env::args` convention).
#[must_use]
pub fn run(argv: &[&str]) -> CliOutcome {
    let parse_result = Cli::try_parse_from(argv.iter().copied());
    let cli = match parse_result {
        Ok(cli) => cli,
        Err(e) => {
            let msg = e.to_string();
            let exit_code = map_clap_exit_code(e.exit_code());
            return CliOutcome::fail(msg.into_bytes(), exit_code);
        }
    };

    match cli.command {
        Command::FromClaude(args) => run_from_claude(&args),
    }
}

fn map_clap_exit_code(clap_code: i32) -> i32 {
    // clap returns 0 for `--help` / `--version` (success) and 2 for
    // usage errors. We remap usage errors to 64 (EX_USAGE).
    match clap_code {
        0 => EXIT_OK,
        _ => EXIT_USAGE_ERROR,
    }
}

// ---------------------------------------------------------------------
// `from-claude` subcommand
// ---------------------------------------------------------------------

fn run_from_claude(args: &FromClaudeArgs) -> CliOutcome {
    // 1. Read input file.
    let input_text = match fs::read_to_string(&args.input) {
        Ok(text) => text,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            let msg = format!(
                "wakir-persona-convert: input file not found: {} ({e})\n",
                args.input.display()
            );
            return CliOutcome::fail(msg.into_bytes(), EXIT_INPUT_NOT_FOUND);
        }
        Err(e) => {
            let msg = format!(
                "wakir-persona-convert: failed to read input file {}: {e}\n",
                args.input.display()
            );
            return CliOutcome::fail(msg.into_bytes(), EXIT_SCHEMA_ERROR);
        }
    };

    // 2. Map axis-A -> axis-C.
    let doc = match map_claude_native_to_wakir_v1(&input_text) {
        Ok(doc) => doc,
        Err(e) => {
            let msg = format!("wakir-persona-convert: schema error: {e}\n");
            return CliOutcome::fail(msg.into_bytes(), EXIT_SCHEMA_ERROR);
        }
    };

    // 3. JCS-canonicalise.
    let mut bytes = match jcs_canonicalise_wakir_persona_v1(&doc) {
        Ok(b) => b,
        Err(e) => {
            let msg = format!("wakir-persona-convert: JCS canonicalisation failed: {e}\n");
            return CliOutcome::fail(msg.into_bytes(), EXIT_SCHEMA_ERROR);
        }
    };
    // Trailing newline for POSIX-friendly file form.
    bytes.push(b'\n');

    // 4. Pin-verify (optional).
    if let Some(pin) = &args.pin_hash_v907 {
        let recomputed = match wakir_persona_hash(&doc) {
            Ok(h) => h,
            Err(e) => {
                let msg = format!("wakir-persona-convert: V-907 hash computation failed: {e}\n");
                return CliOutcome::fail(msg.into_bytes(), EXIT_SCHEMA_ERROR);
            }
        };
        let normalised_pin = normalise_v907_pin(pin);
        if recomputed != normalised_pin {
            let msg = format!(
                "wakir-persona-convert: V-907 hash drift\n  expected: {normalised_pin}\n  actual:   {recomputed}\n",
            );
            return CliOutcome::fail(msg.into_bytes(), EXIT_HASH_DRIFT_ERROR);
        }
    }

    // 5. Write output.
    if let Err(e) = write_output(&args.output, &bytes) {
        let msg = format!(
            "wakir-persona-convert: failed to write output {}: {e}\n",
            args.output.display()
        );
        return CliOutcome::fail(msg.into_bytes(), EXIT_SCHEMA_ERROR);
    }

    // 6. Progress line on stderr (unless --quiet).
    let stderr = if args.quiet {
        Vec::new()
    } else {
        let bytes_len = bytes.len();
        let hash = match wakir_persona_hash(&doc) {
            Ok(h) => h,
            Err(_) => String::from("<hash unavailable>"),
        };
        let line = format!(
            "wakir-persona-convert: wrote {} ({bytes_len} bytes, persona-hash {hash})\n",
            args.output.display()
        );
        line.into_bytes()
    };

    CliOutcome::ok(Vec::new(), stderr)
}

fn write_output(path: &std::path::Path, bytes: &[u8]) -> Result<(), std::io::Error> {
    fs::write(path, bytes)
}

/// Normalise a V-907 pin string to the canonical `sha256:<64hex>`
/// form. Accepts both bare 64-hex and full forms.
fn normalise_v907_pin(pin: &str) -> String {
    if pin.starts_with("sha256:") {
        pin.to_string()
    } else if pin.len() == 64 && pin.chars().all(|c| c.is_ascii_hexdigit()) {
        format!("sha256:{pin}")
    } else {
        // Pass through invalid pins unchanged so the drift check fails
        // with a meaningful "expected: <whatever>" line rather than a
        // panic.
        pin.to_string()
    }
}

// Re-export common error types for ergonomic test driving.
pub use persona_engine_format::PersonaEngineFormatError as MappingError;

#[allow(dead_code)]
fn _assert_mapping_error_is_send_sync()
where
    PersonaEngineFormatError: std::fmt::Display,
{
}
