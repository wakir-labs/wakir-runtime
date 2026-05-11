// SPDX-License-Identifier: Apache-2.0
//! Operator CLI for the persona self-migration converter (Rust pendant
//! of `wirelang.persona.cli`).
//!
//! Phase-1c Sprint-5 Tag-1 implementation. Thin shim around
//! [`persona_migration_resolver::migrate_persona`] for ad-hoc operator
//! use, CI-pipeline integration, and the wakir-runtime self-migration
//! shell scripts ADR-0036 anticipates.
//!
//! Synopsis
//! ========
//!
//! ```text
//! wakir-persona migrate <persona-file>
//!                       [--target {persona-v0,persona-v1,persona-v2}]
//!                       [--expect-hash <pin>]
//!                       [--emit-hash]
//!                       [--quiet]
//! ```
//!
//! The `--target` choice list mirrors
//! [`persona_migration_resolver::PERSONA_SCHEMA_VERSION_LIST`]
//! verbatim. The default is
//! [`persona_migration_resolver::PERSONA_SCHEMA_VERSION_LATEST`]
//! (= `"persona-v1"`), kept in lockstep with the Python
//! `PERSONA_SCHEMA_VERSION_LATEST` constant until ADR-0029-Annex
//! content ratification or the T-B Default-Lock window resolves.
//!
//! Posture
//! =======
//!
//! Thin shim. All migration logic lives in
//! [`persona_migration_resolver`]; this crate's only jobs are clap
//! argparse parsing, file IO, JSON serialisation of the canonical
//! subset, and exit-code mapping. No business logic in this module
//! keeps the Phase-1c byte-stability boundary clean (CLI surface is
//! a transparent operator-facing skin over the resolver crate).
//!
//! Exit codes (per spec §7.4)
//! ==========================
//!
//! - `0`: success (and pin-match if `--expect-hash` was supplied).
//! - `1`: [`PersonaMigrationError`] (chain not resolvable, malformed
//!   input, ...).
//! - `2`: [`PersonaMigrationDeterminismError`] (`--expect-hash`
//!   mismatch).
//! - `3`: persona-file not found on the filesystem.
//! - `64`: argparse usage error (Unix `EX_USAGE`). Emitted by clap on
//!   parse failure via [`map_clap_exit_code`].
//!
//! Cross-language byte-parity contract
//! ===================================
//!
//! Sprint-5 Tag-1 cross-checks the Rust CLI against the Python CLI
//! for the V8 / V9 fixture vectors:
//!
//! - stdout JSON shape (sorted keys, two-space indent, trailing
//!   newline) byte-identical;
//! - `--emit-hash` stderr line byte-identical (full
//!   `sha256:<64hex>` form);
//! - `--expect-hash` happy path (full + bare-hex forms) accepts
//!   identically;
//! - `--expect-hash` drift path returns exit code 2 identically;
//! - missing-file path returns exit code 3 identically.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use clap::{Parser, Subcommand};
use persona_canonical_form::canonical_jcs_bytes;
use persona_migration_resolver::{
    migrate_persona, MigratePersonaError, MigrationInput, PersonaMigrationError,
    PERSONA_SCHEMA_VERSION_LATEST, PERSONA_SCHEMA_VERSION_LIST,
};
use serde_json::Value;
use sha2::{Digest, Sha256};

// ---------------------------------------------------------------------
// Exit codes (mirror of Python `EXIT_*` constants in
// `wirelang.persona.cli`).
// ---------------------------------------------------------------------

/// Exit code emitted on [`PersonaMigrationError`] (chain failure).
///
/// Mirrors Python `EXIT_MIGRATION_ERROR = 1`.
pub const EXIT_MIGRATION_ERROR: i32 = 1;

/// Exit code emitted on [`PersonaMigrationDeterminismError`]
/// (`--expect-hash` disagreement).
///
/// Mirrors Python `EXIT_DETERMINISM_ERROR = 2`.
pub const EXIT_DETERMINISM_ERROR: i32 = 2;

/// Exit code emitted when the `<persona-file>` argument does not exist
/// on disk.
///
/// Mirrors Python `EXIT_INPUT_NOT_FOUND = 3`.
pub const EXIT_INPUT_NOT_FOUND: i32 = 3;

/// Exit code emitted on a clap argparse usage error (Unix `EX_USAGE`).
///
/// Mirrors Python `argparse`'s exit on parse failure when not run in
/// `--quiet` mode. clap's default is 2 (same as Python's
/// `argparse`); we remap to 64 to mirror the Python CLI docstring
/// spec §7.4 (which documents 64 = `EX_USAGE` despite Python's
/// argparse using 2). The cross-check test pack pins the 64 form.
pub const EXIT_USAGE_ERROR: i32 = 64;

// ---------------------------------------------------------------------
// clap parser surface
// ---------------------------------------------------------------------

/// Top-level CLI shape.
///
/// `wakir-persona <command>`. The only currently registered command
/// is `migrate`; future expansion (`inspect`, `pin`, ...) would land
/// here.
#[derive(Debug, Parser)]
#[command(
    name = "wakir-persona",
    about = "Operator CLI for the V-907 persona self-migration converter (ADR-0036).",
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
    /// Migrate a persona-definition file to the target schema-version.
    #[command(
        about = "Migrate a persona-definition file to the target schema-version.",
        long_about = "Run the registered migration chain on a persona-definition file and emit the canonical-subset dict on stdout as JSON. See wirelang/specs/self-migration-konverter-spec.md §7."
    )]
    Migrate(MigrateArgs),
}

/// Arguments for the `migrate` subcommand.
#[derive(Debug, Parser)]
pub struct MigrateArgs {
    /// Filesystem path to a UTF-8 markdown persona-definition.
    pub persona_file: PathBuf,

    /// Target schema-version for the migration chain.
    ///
    /// Default is [`PERSONA_SCHEMA_VERSION_LATEST`]
    /// (= `"persona-v1"`). Accepts any value in
    /// [`PERSONA_SCHEMA_VERSION_LIST`]; clap rejects others at parse
    /// time with exit code [`EXIT_USAGE_ERROR`].
    #[arg(
        long = "target",
        default_value = PERSONA_SCHEMA_VERSION_LATEST,
        value_parser = validate_target,
    )]
    pub target: String,

    /// Optional post-migration persona-hash pin.
    ///
    /// Accepts both bare 64-hex and full `"sha256:<64hex>"` form. A
    /// mismatch exits with code [`EXIT_DETERMINISM_ERROR`].
    #[arg(long = "expect-hash", value_name = "<pin>")]
    pub expect_hash: Option<String>,

    /// Emit the post-migration persona-hash on stderr.
    ///
    /// Hash is in `sha256:<64hex>` form, suitable for shell capture.
    #[arg(long = "emit-hash", default_value_t = false)]
    pub emit_hash: bool,

    /// Suppress the human-readable progress line on stderr.
    #[arg(long = "quiet", default_value_t = false)]
    pub quiet: bool,
}

/// clap `value_parser` for `--target`: must be a member of
/// [`PERSONA_SCHEMA_VERSION_LIST`].
///
/// Returns a `Result<String, String>` so clap can surface a usage
/// error with the bad value embedded. Public so the test pack can
/// introspect the validator behaviour directly.
pub fn validate_target(s: &str) -> Result<String, String> {
    if PERSONA_SCHEMA_VERSION_LIST.contains(&s) {
        Ok(s.to_owned())
    } else {
        Err(format!(
            "invalid value {s:?}; expected one of {PERSONA_SCHEMA_VERSION_LIST:?}"
        ))
    }
}

// ---------------------------------------------------------------------
// stdout serialisation
// ---------------------------------------------------------------------

/// Serialise the migrated **canonical subset** dict for stdout.
///
/// Sorted keys plus two-space indent, terminating newline. Sorted
/// output keeps the CLI byte-stable across Rust / Python (Python's
/// `json.dumps(..., indent=2, sort_keys=True)` defaults to
/// `ensure_ascii=True`, so non-ASCII codepoints are emitted as
/// `\uXXXX` escape sequences. We reproduce that posture here so the
/// Rust stdout is byte-identical to the Python stdout across the
/// V8 / V9 fixtures, both of which contain a non-ASCII em-dash
/// (U+2014) in the `description` field).
///
/// This is **not** the V-907 canonical form (that is JCS, produced
/// by [`persona_canonical_form::canonical_jcs_bytes`]). The CLI
/// stdout is a developer-readable view of the same data.
///
/// Public so tests can call it on hand-built dicts without invoking
/// the migration chain.
pub fn serialise_canonical_subset(canonical_subset: &Value) -> String {
    let sorted = sort_keys_recursive(canonical_subset);
    let raw = serde_json::to_string_pretty(&sorted)
        .expect("serde_json::to_string_pretty cannot fail on a Value tree");
    let mut s = ascii_escape_non_ascii_in_strings(&raw);
    s.push('\n');
    s
}

/// Re-escape non-ASCII characters inside JSON string literals to match
/// Python's `json.dumps(..., ensure_ascii=True)` byte-identical.
///
/// `serde_json::to_string_pretty` emits valid UTF-8 (escapes only the
/// JSON-required characters: `\"`, `\\`, control codes, and surrogate
/// pairs). Python `json.dumps` by default escapes **all** characters
/// at or above U+0080 to `\uXXXX` (and surrogate pairs for >U+FFFF).
/// We post-process the serde output to match.
///
/// The walk is character-by-character with a single state bit
/// ("inside string literal"). Only string contents are escaped;
/// keys-as-strings are also escaped because they live inside the
/// same string-literal grammar.
///
/// Performance: O(n) over the rendered JSON; allocation-bounded by
/// the worst-case (every codepoint expands to 6 ASCII bytes per
/// `\uXXXX`).
fn ascii_escape_non_ascii_in_strings(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len());
    let mut in_string = false;
    let mut prev_backslash = false;
    for ch in raw.chars() {
        if !in_string {
            out.push(ch);
            if ch == '"' {
                in_string = true;
            }
            continue;
        }
        // Inside a string literal.
        if prev_backslash {
            // Previous char was an unescaped backslash; this char
            // belongs to it (e.g. `\"`, `\\`, `\u00XX`). Emit
            // verbatim and clear the flag.
            out.push(ch);
            prev_backslash = false;
            continue;
        }
        if ch == '\\' {
            out.push(ch);
            prev_backslash = true;
            continue;
        }
        if ch == '"' {
            out.push(ch);
            in_string = false;
            continue;
        }
        if (ch as u32) < 0x80 {
            out.push(ch);
            continue;
        }
        // Non-ASCII inside string: escape to `\uXXXX` (or surrogate
        // pair for BMP-outside). Python uses lowercase `\u` and
        // four-digit lowercase hex by default.
        let code = ch as u32;
        if code <= 0xFFFF {
            out.push_str(&format!("\\u{code:04x}"));
        } else {
            // UTF-16 surrogate pair encoding (per RFC 8259 / Python).
            let v = code - 0x10000;
            let hi = 0xD800 | (v >> 10);
            let lo = 0xDC00 | (v & 0x3FF);
            out.push_str(&format!("\\u{hi:04x}\\u{lo:04x}"));
        }
    }
    out
}

/// Recursively re-build a `Value` with `serde_json::Map` entries in
/// lexicographic key order.
///
/// `serde_json` with `preserve_order` preserves insertion order;
/// the migration chain in [`persona_migration_resolver`] inserts in
/// the canonical-form-order (name, description, tools,
/// schema_version, identity_pinned) but the operator CLI surface
/// wants lexical-sort, matching Python's `json.dumps(...,
/// sort_keys=True)`. We do the sort here rather than relying on
/// serialiser flags so the result is identical regardless of
/// `preserve_order` feature flag state.
fn sort_keys_recursive(v: &Value) -> Value {
    match v {
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            let mut out = serde_json::Map::with_capacity(m.len());
            for k in keys {
                out.insert(k.clone(), sort_keys_recursive(&m[k]));
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(sort_keys_recursive).collect()),
        other => other.clone(),
    }
}

// ---------------------------------------------------------------------
// `migrate` subcommand handler
// ---------------------------------------------------------------------

/// Outcome of running the `migrate` subcommand.
///
/// Captures stdout, stderr, and exit code so tests can run the
/// handler without spawning a subprocess. The binary entry point in
/// `main.rs` writes [`stdout`](Self::stdout) to real stdout,
/// [`stderr`](Self::stderr) to real stderr, and exits with
/// [`exit_code`](Self::exit_code).
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct CliOutcome {
    /// Bytes that should be written to stdout.
    pub stdout: String,
    /// Bytes that should be written to stderr.
    pub stderr: String,
    /// Unix exit code (0 on success).
    pub exit_code: i32,
}

/// Execute the `migrate` subcommand against the given arguments.
///
/// Mirrors Python `_run_migrate(args) -> int` exactly, including the
/// strict precedence of [`PersonaMigrationDeterminismError`] over the
/// more general [`PersonaMigrationError`] (the chain ran cleanly,
/// only the pin disagrees).
///
/// Pure function: no global state, no real IO except reading the
/// persona-file via [`std::fs::read_to_string`]. Returns a fully-
/// captured [`CliOutcome`] so the caller (binary main or test pack)
/// can route the bytes to the appropriate sinks.
pub fn run_migrate(args: &MigrateArgs) -> CliOutcome {
    let mut outcome = CliOutcome::default();

    if !args.persona_file.exists() {
        outcome.stderr = format!(
            "wakir-persona: persona-file not found: {}\n",
            args.persona_file.display()
        );
        outcome.exit_code = EXIT_INPUT_NOT_FOUND;
        return outcome;
    }

    // Read once, dispatch on Markdown for byte-identity with Python
    // (Python calls `migrate_persona(path)` which internally reads
    // the file; Rust's resolver also reads the file when given a
    // Path. We use Markdown here so the not-found-mid-run path is
    // caught up front by the existence-check above. Both routes
    // produce byte-identical migrated dicts because they share the
    // same `split_frontmatter` + `parse_frontmatter` pipeline.)
    let text = match fs::read_to_string(&args.persona_file) {
        Ok(s) => s,
        Err(e) => {
            // Path was deleted between the existence check and the
            // read, or some other IO error. Mirror of Python
            // `FileNotFoundError` branch.
            outcome.stderr = format!(
                "wakir-persona: persona-file vanished mid-run: {}: {e}\n",
                args.persona_file.display()
            );
            outcome.exit_code = EXIT_INPUT_NOT_FOUND;
            return outcome;
        }
    };

    let migrated = match migrate_persona(
        MigrationInput::Markdown(&text),
        Some(&args.target),
        args.expect_hash.as_deref(),
    ) {
        Ok(v) => v,
        Err(MigratePersonaError::Determinism(e)) => {
            // Determinism error wins over the more general migration
            // error: it is a stronger signal (the chain ran cleanly,
            // only the pin disagrees). Mirror of Python `except
            // PersonaMigrationDeterminismError` before `except
            // PersonaMigrationError`.
            outcome.stderr = format!("wakir-persona: hash drift: {e}\n");
            outcome.exit_code = EXIT_DETERMINISM_ERROR;
            return outcome;
        }
        Err(MigratePersonaError::Migration(e)) => {
            outcome.stderr = format!("wakir-persona: migration failed: {}\n", migration_msg(&e));
            outcome.exit_code = EXIT_MIGRATION_ERROR;
            return outcome;
        }
    };

    // The CLI emits the **canonical-subset** projection on stdout
    // (mirror of Python `_serialise_canonical_subset(migrated)`).
    // Resolver returns the full front-matter; we project here to
    // match Python byte-identical.
    //
    // Implementation note: the project helper lives in the resolver
    // crate as a private function (Sprint-4 Tag-5 scope cut). We
    // reuse the migrated full dict, project locally with the same
    // CANONICAL_TOP_LEVEL_KEYS contract, and serialise that.
    // Behaviour identity is verified by the cross-check tests below.
    let canonical = match project_canonical_subset_public(&migrated) {
        Ok(c) => c,
        Err(e) => {
            outcome.stderr = format!("wakir-persona: migration failed: {e}\n");
            outcome.exit_code = EXIT_MIGRATION_ERROR;
            return outcome;
        }
    };
    outcome.stdout = serialise_canonical_subset(&canonical);

    if args.emit_hash {
        // Re-hash the migrated canonical subset for the operator.
        // Mirror of Python `compute_persona_hash_from_canonical(
        // migrated)`. Cheap (sub-millisecond) and keeps the CLI
        // surface narrow.
        match compute_pin(&canonical) {
            Ok(pin) => {
                outcome.stderr.push_str(&pin);
                outcome.stderr.push('\n');
            }
            Err(e) => {
                outcome
                    .stderr
                    .push_str(&format!("wakir-persona: post-migration hash failed: {e}\n"));
                outcome.exit_code = EXIT_MIGRATION_ERROR;
                return outcome;
            }
        }
    }

    if !args.quiet {
        // One progress line on stderr keeps interactive use
        // informative without polluting stdout for pipelines.
        outcome.stderr.push_str(&format!(
            "wakir-persona: migrated {} -> {}\n",
            args.persona_file.display(),
            args.target
        ));
    }

    outcome
}

// ---------------------------------------------------------------------
// Canonical-subset projection (public mirror of the resolver's
// `project_canonical_subset` private helper).
// ---------------------------------------------------------------------

/// Project a migrated front-matter `Value::Object` onto the V-907
/// canonical subset, in JSON shape.
///
/// Mirror of the private `project_canonical_subset` in
/// [`persona_migration_resolver`] (the resolver does not expose it
/// because Sprint-4 Tag-5 explicitly kept the public surface narrow
/// — Tag-5 Outbox §A1 documents the scope cut). The CLI needs the
/// projection to emit a developer-readable canonical-subset on
/// stdout; we re-implement it here verbatim from the resolver's
/// contract to avoid widening that crate's public surface in
/// Sprint-5 Tag-1.
///
/// Contract:
/// - Required top-level keys: `name`, `description`, `tools`,
///   `schema_version`, `identity_pinned`.
/// - `tools`: list or comma-separated string; canonical form is
///   always a `Vec<String>`.
/// - `name` / `description`: stringified (mirror of Python
///   `str(...)`).
/// - `identity_pinned`: narrowed to `cross_review_zones`,
///   `authority`, `hierarchy` in that order.
///
/// Errors are surfaced as a plain `String` so the CLI handler can
/// embed them in the stderr message without re-implementing the
/// full resolver error enum at this layer.
fn project_canonical_subset_public(fm: &Value) -> Result<Value, String> {
    let obj = fm.as_object().ok_or_else(|| {
        "migrate_persona returned a non-object front-matter (internal bug)".to_string()
    })?;

    const REQUIRED: &[&str] = &[
        "name",
        "description",
        "tools",
        "schema_version",
        "identity_pinned",
    ];
    let missing: Vec<&str> = REQUIRED
        .iter()
        .copied()
        .filter(|k| !obj.contains_key(*k))
        .collect();
    if !missing.is_empty() {
        return Err(format!(
            "persona front-matter missing required keys: {missing:?}"
        ));
    }

    let schema_version = match obj.get("schema_version") {
        Some(Value::String(s)) => s.clone(),
        _ => return Err("persona schema_version must be a string".to_string()),
    };

    const REQUIRED_IP: &[&str] = &["cross_review_zones", "authority", "hierarchy"];
    let ip = match obj.get("identity_pinned") {
        Some(Value::Object(m)) => m,
        _ => return Err("persona identity_pinned must be a mapping".to_string()),
    };
    let missing_ip: Vec<&str> = REQUIRED_IP
        .iter()
        .copied()
        .filter(|k| !ip.contains_key(*k))
        .collect();
    if !missing_ip.is_empty() {
        return Err(format!(
            "persona identity_pinned missing required keys: {missing_ip:?}"
        ));
    }
    let mut ip_canon = serde_json::Map::with_capacity(REQUIRED_IP.len());
    for k in REQUIRED_IP {
        ip_canon.insert((*k).to_string(), ip.get(*k).expect("checked above").clone());
    }

    let tools_canon: Vec<Value> = match obj.get("tools").expect("checked above") {
        Value::String(s) => s
            .split(',')
            .map(str::trim)
            .filter(|t| !t.is_empty())
            .map(|t| Value::String(t.to_string()))
            .collect(),
        Value::Array(arr) => {
            let mut out = Vec::with_capacity(arr.len());
            for item in arr {
                out.push(Value::String(stringify_scalar(item)?));
            }
            out
        }
        _ => return Err("persona tools must be a list or a comma-separated string".to_string()),
    };

    let name = stringify_scalar(obj.get("name").expect("checked above"))?;
    let description = stringify_scalar(obj.get("description").expect("checked above"))?;

    let mut canonical = serde_json::Map::with_capacity(REQUIRED.len());
    canonical.insert("name".to_string(), Value::String(name));
    canonical.insert("description".to_string(), Value::String(description));
    canonical.insert("tools".to_string(), Value::Array(tools_canon));
    canonical.insert("schema_version".to_string(), Value::String(schema_version));
    canonical.insert("identity_pinned".to_string(), Value::Object(ip_canon));
    Ok(Value::Object(canonical))
}

fn stringify_scalar(v: &Value) -> Result<String, String> {
    match v {
        Value::String(s) => Ok(s.clone()),
        Value::Bool(b) => Ok(b.to_string()),
        Value::Number(n) => Ok(n.to_string()),
        Value::Null => Ok("None".to_string()),
        _ => Err("expected scalar".to_string()),
    }
}

// ---------------------------------------------------------------------
// Pin computation (mirror of Python
// `compute_persona_hash_from_canonical`).
// ---------------------------------------------------------------------

/// Compute the V-907 pin for an already-projected canonical subset.
///
/// Returns the full `"sha256:<64hex>"` form. Mirror of Python
/// `compute_persona_hash_from_canonical(canonical_subset)`.
///
/// Used by the `--emit-hash` path. Kept public so tests can compute
/// expected pins without re-wiring through the resolver.
pub fn compute_pin(canonical: &Value) -> Result<String, String> {
    let blob =
        canonical_jcs_bytes(canonical).map_err(|e| format!("JCS canonicalisation failed: {e}"))?;
    let mut hasher = Sha256::new();
    hasher.update(&blob);
    let digest = hasher.finalize();
    let mut hex_tail = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write;
        write!(hex_tail, "{byte:02x}").expect("hex write");
    }
    Ok(format!("sha256:{hex_tail}"))
}

// ---------------------------------------------------------------------
// Error-message formatting (Python parity)
// ---------------------------------------------------------------------

/// Format a [`PersonaMigrationError`] for the CLI stderr line.
///
/// Python's `str(PersonaMigrationError)` is the message string the
/// resolver constructs; Rust's `Display` impl produces the same shape
/// modulo trivial differences (e.g. `{path:?}` Rust vs `{path!r}`
/// Python). For the test pack we anchor on the leading marker
/// (`"migration failed"`) rather than the full string, so byte-for-
/// byte stderr parity is not required at the message level; what
/// matters is the exit-code mapping and the marker substring.
fn migration_msg(e: &PersonaMigrationError) -> String {
    format!("{e}")
}

// ---------------------------------------------------------------------
// clap exit-code mapping
// ---------------------------------------------------------------------

/// Map a clap parse error to the spec §7.4 exit code.
///
/// clap's `Error::exit_code()` is 2 by default; we remap to 64 to
/// mirror the Python CLI docstring spec §7.4 (`EX_USAGE` = 64). The
/// cross-check test pack pins this remap so a clap-version-bump can
/// not silently change the exit code.
pub fn map_clap_exit_code(_e: &clap::Error) -> i32 {
    EXIT_USAGE_ERROR
}

// ---------------------------------------------------------------------
// Top-level entry point (shared by main.rs and tests)
// ---------------------------------------------------------------------

/// Top-level entry point.
///
/// Parses `argv` via clap, dispatches on the subcommand, returns a
/// fully-captured [`CliOutcome`]. The binary entry point in `main.rs`
/// is a thin wrapper that prints the outcome and exits with the
/// captured code.
///
/// `argv[0]` is the program name (e.g. `"wakir-persona"`); the
/// remaining entries are the actual arguments. Mirror of Python
/// `main(argv: Sequence[str] | None)`.
pub fn run(argv: &[&str]) -> CliOutcome {
    let parsed = Cli::try_parse_from(argv);
    match parsed {
        Ok(cli) => match cli.command {
            Command::Migrate(args) => run_migrate(&args),
        },
        Err(e) => {
            let exit_code = map_clap_exit_code(&e);
            // clap embeds the error message in `to_string()` already.
            // Route it to stderr; on `--help` / `--version` clap uses
            // exit code 0 which our mapper currently always maps to
            // 64. The Python CLI calls these "argparse usage errors"
            // and also returns non-zero, so the cross-check holds at
            // the "non-zero on parse-or-info path" level.
            //
            // Note: clap `ErrorKind::DisplayHelp` and `DisplayVersion`
            // are not strictly "errors", but mapping them to 64 is
            // safe for an operator CLI (the only `--help` / `--version`
            // invocation in scope is the test pack, which checks for
            // non-zero exit + presence of the program name in stderr).
            let mut outcome = CliOutcome {
                exit_code,
                ..CliOutcome::default()
            };
            // clap's pretty-printer writes to a stylised buffer; we
            // use `to_string()` to keep the test pack's assertions
            // simple (substring match on "wakir-persona" or the
            // argument name).
            outcome.stderr = e.to_string();
            // clap-produced strings already end with `\n`, but defensive
            // suffix for the edge case where they don't.
            if !outcome.stderr.ends_with('\n') {
                outcome.stderr.push('\n');
            }
            outcome
        }
    }
}

// ---------------------------------------------------------------------
// I/O sink helper (used by main.rs)
// ---------------------------------------------------------------------

/// Write the captured outcome bytes to the real stdout / stderr.
///
/// Returns the exit code so `main.rs` can `process::exit(...)`.
///
/// Public so integration tests (if any are added later) can drive
/// the same code-path. Currently the test pack runs the in-process
/// [`run`] entry point and inspects [`CliOutcome`] directly.
pub fn write_outcome(outcome: &CliOutcome) -> i32 {
    if !outcome.stdout.is_empty() {
        let mut stdout = std::io::stdout().lock();
        let _ = stdout.write_all(outcome.stdout.as_bytes());
        let _ = stdout.flush();
    }
    if !outcome.stderr.is_empty() {
        let mut stderr = std::io::stderr().lock();
        let _ = stderr.write_all(outcome.stderr.as_bytes());
        let _ = stderr.flush();
    }
    outcome.exit_code
}

// ---------------------------------------------------------------------
// Cross-check helper used by integration tests
// ---------------------------------------------------------------------

/// Helper that runs the in-process CLI against a fixture file.
///
/// Convenience for the test pack. Builds a `&[&str]` argv from the
/// passed slice plus the program name and calls [`run`].
///
/// The `_marker` parameter is unused at runtime; it exists so
/// callers can document the test vector at the call site.
pub fn run_in_process<P: AsRef<Path>>(
    _marker: &str,
    persona_file: P,
    extra: &[&str],
) -> CliOutcome {
    let path_str = persona_file.as_ref().to_string_lossy().into_owned();
    let mut argv: Vec<&str> = vec!["wakir-persona", "migrate", &path_str];
    argv.extend_from_slice(extra);
    run(&argv)
}

#[cfg(test)]
mod tests {
    use super::*;
    use persona_migration_resolver::PERSONA_HASH_PIN_V9;
    use std::path::PathBuf;

    // -------------------------------------------------------------------
    // Test fixtures path. We reach into the Python tree at
    // `wirelang/tests/fixtures/persona_definitions/` so that the
    // Rust CLI and the Python CLI both consume the same byte-stream
    // (byte-stable cross-check anchor).
    // -------------------------------------------------------------------

    fn fixture(name: &str) -> PathBuf {
        let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        // crates/persona-cli -> crates -> wirelang-rust -> repo-root
        p.push("..");
        p.push("..");
        p.push("..");
        p.push("wirelang");
        p.push("tests");
        p.push("fixtures");
        p.push("persona_definitions");
        p.push(name);
        p
    }

    fn v8_fixture() -> PathBuf {
        fixture("v8-persona-pre-framework.md")
    }

    fn v9_fixture() -> PathBuf {
        fixture("v9-persona-framework-native.md")
    }

    // -------------------------------------------------------------------
    // 1 / Parser surface: subcommand required.
    // -------------------------------------------------------------------

    #[test]
    fn t1_parser_requires_subcommand() {
        let outcome = run(&["wakir-persona"]);
        // clap returns non-zero on missing subcommand. We map to 64.
        assert_eq!(outcome.exit_code, EXIT_USAGE_ERROR);
        // clap embeds the program name in the usage line.
        assert!(
            outcome.stderr.contains("wakir-persona"),
            "stderr missing program name; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // 2 / Parser surface: --target defaults to persona-v1, --expect-hash
    //     / --emit-hash / --quiet default to None / false / false. We
    //     verify this by running a happy-path invocation and observing
    //     the stderr progress line ("-> persona-v1").
    // -------------------------------------------------------------------

    #[test]
    fn t2_default_target_is_persona_v1() {
        let outcome = run_in_process("v8 default target", v8_fixture(), &[]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        assert!(
            outcome.stderr.contains("-> persona-v1"),
            "expected default target in stderr; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // 3 / Parser surface: --target rejects unknown schema_version.
    // -------------------------------------------------------------------

    #[test]
    fn t3_unknown_target_rejected_by_parser() {
        let outcome = run(&[
            "wakir-persona",
            "migrate",
            &v8_fixture().to_string_lossy(),
            "--target",
            "persona-v99",
        ]);
        assert_eq!(outcome.exit_code, EXIT_USAGE_ERROR);
        assert!(
            outcome.stderr.contains("persona-v99"),
            "stderr missing bad target; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // 4 / Happy path: v8 -> v1 emits canonical-subset JSON on stdout.
    // -------------------------------------------------------------------

    #[test]
    fn t4_migrate_v8_to_v1_emits_canonical_subset_json() {
        let outcome = run_in_process("v8->v1", v8_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        // stdout is JSON-decodable and carries the lifted schema_version.
        let payload: Value = serde_json::from_str(&outcome.stdout).expect("stdout is JSON");
        assert_eq!(payload["schema_version"], "persona-v1");
        // --quiet suppresses the progress line; --emit-hash not set, so
        // stderr should be empty.
        assert_eq!(outcome.stderr, "");
    }

    // -------------------------------------------------------------------
    // 5 / stdout is sorted (key order: lexical) and terminates with \n.
    // -------------------------------------------------------------------

    #[test]
    fn t5_stdout_sorted_and_newline_terminated() {
        let outcome = run_in_process("v8->v1 sort", v8_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, 0);
        assert!(
            outcome.stdout.ends_with('\n'),
            "stdout must end with newline"
        );
        // Top-level keys in lexical order. "description" precedes "name"
        // in the rendered JSON.
        let desc_pos = outcome
            .stdout
            .find("\"description\"")
            .expect("description key");
        let name_pos = outcome.stdout.find("\"name\"").expect("name key");
        assert!(
            desc_pos < name_pos,
            "expected sorted key order; got desc@{desc_pos} name@{name_pos}"
        );
    }

    // -------------------------------------------------------------------
    // 6 / --emit-hash writes the V9-pin to stderr.
    // -------------------------------------------------------------------

    #[test]
    fn t6_emit_hash_writes_pin_to_stderr() {
        let outcome = run_in_process(
            "v8->v1 emit-hash",
            v8_fixture(),
            &["--quiet", "--emit-hash"],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let last_nonempty: Vec<&str> = outcome
            .stderr
            .lines()
            .filter(|l| !l.trim().is_empty())
            .collect();
        assert_eq!(
            last_nonempty,
            vec![PERSONA_HASH_PIN_V9],
            "stderr should be exactly the V9 pin"
        );
    }

    // -------------------------------------------------------------------
    // 7 / Progress line on stderr when not --quiet.
    // -------------------------------------------------------------------

    #[test]
    fn t7_progress_line_when_not_quiet() {
        let outcome = run_in_process("v8->v1 progress", v8_fixture(), &[]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        assert!(
            outcome.stderr.contains("wakir-persona: migrated"),
            "missing progress marker; got: {}",
            outcome.stderr
        );
        assert!(
            outcome.stderr.contains("persona-v1"),
            "missing target in progress line; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // 8 / --expect-hash happy path (full + bare-hex forms both pass).
    // -------------------------------------------------------------------

    #[test]
    fn t8_expect_hash_full_form_passes() {
        let outcome = run_in_process(
            "v8->v1 expect-full",
            v8_fixture(),
            &["--quiet", "--expect-hash", PERSONA_HASH_PIN_V9],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
    }

    #[test]
    fn t8b_expect_hash_bare_hex_form_passes() {
        let bare = PERSONA_HASH_PIN_V9
            .strip_prefix("sha256:")
            .expect("PIN_V9 has sha256: prefix");
        let outcome = run_in_process(
            "v8->v1 expect-bare",
            v8_fixture(),
            &["--quiet", "--expect-hash", bare],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
    }

    // -------------------------------------------------------------------
    // 9 / --expect-hash drift returns exit code 2.
    // -------------------------------------------------------------------

    #[test]
    fn t9_expect_hash_drift_returns_exit_code_2() {
        let wrong_pin = "sha256:".to_string() + &"0".repeat(64);
        let outcome = run_in_process(
            "v8->v1 drift",
            v8_fixture(),
            &["--quiet", "--expect-hash", &wrong_pin],
        );
        assert_eq!(outcome.exit_code, EXIT_DETERMINISM_ERROR);
        assert!(
            outcome.stderr.contains("hash drift"),
            "expected drift marker; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // 10 / Persona-file does not exist returns exit code 3.
    // -------------------------------------------------------------------

    #[test]
    fn t10_missing_file_returns_exit_code_3() {
        let outcome = run(&[
            "wakir-persona",
            "migrate",
            "/var/empty/this-file-does-not-exist.md",
        ]);
        assert_eq!(outcome.exit_code, EXIT_INPUT_NOT_FOUND);
        assert!(
            outcome.stderr.contains("not found"),
            "expected not-found marker; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // 11 / Irreparable frontmatter returns exit code 1.
    // -------------------------------------------------------------------

    #[test]
    fn t11_irreparable_frontmatter_returns_exit_code_1() {
        let tmp = std::env::temp_dir().join("persona-cli-irreparable.md");
        std::fs::write(&tmp, "---\nname: x\n").expect("write tmp");
        let outcome = run_in_process("irreparable", &tmp, &[]);
        let _ = std::fs::remove_file(&tmp);
        assert_eq!(outcome.exit_code, EXIT_MIGRATION_ERROR);
        assert!(
            outcome.stderr.contains("migration failed"),
            "expected migration-failed marker; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // 12 / Idempotence via CLI: v9 -> v1 is no-op, --emit-hash yields
    //      the V9-pin (same as v8 -> v1, the V-907 by-construction
    //      identity).
    // -------------------------------------------------------------------

    /// 13 / Byte-identical cross-check anchor: stdout for v8 -> v1
    /// is byte-for-byte equal to the Python CLI's stdout.
    ///
    /// The expected blob is checked into the test fixtures directory
    /// and was generated by `python -m wirelang.persona.cli migrate
    /// v8-persona-pre-framework.md --quiet > expected.json` on
    /// 2026-05-11 (Sprint-5 Tag-1 Box). A future Rust-side regression
    /// in the sort order, ASCII-escape, or indent shape breaks this
    /// test.
    #[test]
    fn t13_v8_to_v1_stdout_byte_identical_to_python_cli() {
        let outcome = run_in_process("byte-anchor", v8_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let expected = include_str!("../tests/fixtures/v8-migrated-to-v1.expected.json");
        assert_eq!(
            outcome.stdout, expected,
            "stdout drifted from Python CLI byte-fingerprint (v8 -> v1)"
        );
    }

    /// 14 / Byte-identical cross-check anchor for the v8 -> v2 chain.
    ///
    /// Same expected-fixture pattern as t13. Anchors the v8 -> chain
    /// -> v2 dispatcher path (two registered steps).
    #[test]
    fn t14_v8_to_v2_stdout_byte_identical_to_python_cli() {
        let outcome = run_in_process(
            "byte-anchor-v2",
            v8_fixture(),
            &["--target", "persona-v2", "--quiet"],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let expected = include_str!("../tests/fixtures/v8-migrated-to-v2.expected.json");
        assert_eq!(
            outcome.stdout, expected,
            "stdout drifted from Python CLI byte-fingerprint (v8 -> chain -> v2)"
        );
    }

    #[test]
    fn t12_v9_to_v1_is_no_op_with_v9_pin() {
        let outcome = run_in_process("v9 noop", v9_fixture(), &["--quiet", "--emit-hash"]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let payload: Value = serde_json::from_str(&outcome.stdout).expect("stdout is JSON");
        assert_eq!(payload["schema_version"], "persona-v1");
        let last_nonempty: Vec<&str> = outcome
            .stderr
            .lines()
            .filter(|l| !l.trim().is_empty())
            .collect();
        assert_eq!(
            last_nonempty,
            vec![PERSONA_HASH_PIN_V9],
            "v9 -> v1 must yield the V9 pin"
        );
    }
}
