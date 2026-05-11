// SPDX-License-Identifier: Apache-2.0
//! Operator CLI for the persona self-migration converter + validator
//! (Rust pendant of `wirelang.persona.cli`).
//!
//! Phase-1c Sprint-5 Tag-1 implementation. Thin shim around
//! [`persona_migration_resolver::migrate_persona`] for ad-hoc operator
//! use, CI-pipeline integration, and the wakir-runtime self-migration
//! shell scripts ADR-0036 anticipates.
//!
//! Sprint-6 Tag-2 added the `validate` subcommand: thin shim over
//! [`persona_validator::validate_persona`] that emits the
//! `PersonaValidationReport` as canonical-subset JSON on stdout and
//! maps `is_valid` to exit-code 0 / 1.
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
//!
//! wakir-persona validate <persona-file>
//!                        [--quiet]
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
use persona_validator::{validate_persona, ValidatorInput};
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

/// Alias for the validator failure path. Conceptually distinct from a
/// migration chain failure but mapped to the same code so a single
/// `$?` check in a shell pipeline branches the same way. Sprint-6
/// Tag-2 addition; mirrors Python `EXIT_VALIDATION_FAILED`.
pub const EXIT_VALIDATION_FAILED: i32 = EXIT_MIGRATION_ERROR;

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
    /// Validate a persona-definition file (read-only, no migration).
    ///
    /// Sprint-6 Tag-2 addition; mirrors Python `validate` subcommand
    /// byte-for-byte on stdout (canonical-subset
    /// `PersonaValidationReport` JSON).
    #[command(
        about = "Validate a persona-definition file (read-only, no migration).",
        long_about = "Run the read-only persona-validator on a persona-definition file and emit the canonical-subset PersonaValidationReport on stdout as JSON. Exit code 0 if is_valid, 1 if not. See wirelang/persona/persona_validator.py for the report schema (persona-validation-v1)."
    )]
    Validate(ValidateArgs),
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

/// Arguments for the `validate` subcommand.
///
/// Sprint-6 Tag-2 addition. Deliberately narrower than [`MigrateArgs`]:
/// the validator is read-only, so there is no `--target`,
/// `--expect-hash`, or `--emit-hash` knob. Only `--quiet` is shared
/// with `migrate` for stderr-progress-line suppression.
#[derive(Debug, Parser)]
pub struct ValidateArgs {
    /// Filesystem path to a UTF-8 markdown persona-definition.
    pub persona_file: PathBuf,

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
// `validate` subcommand handler (Sprint-6 Tag-2)
// ---------------------------------------------------------------------

/// Serialise a [`persona_validator::ValidationReport`] canonical-value
/// for stdout.
///
/// Same posture as [`serialise_canonical_subset`]: sort keys, two-space
/// indent, terminate with `\n`, and re-escape non-ASCII characters
/// inside string literals to match Python `json.dumps(...,
/// ensure_ascii=True)`. Public so the test pack can call it on
/// hand-built report dicts.
pub fn serialise_validation_report(report: &Value) -> String {
    // Posture is verbatim identical to `serialise_canonical_subset`;
    // keep them as distinct entry points to document the two different
    // callers (migrate vs validate) and allow them to diverge later
    // without touching the migrate path.
    let sorted = sort_keys_recursive(report);
    let raw = serde_json::to_string_pretty(&sorted)
        .expect("serde_json::to_string_pretty cannot fail on a Value tree");
    let mut s = ascii_escape_non_ascii_in_strings(&raw);
    s.push('\n');
    s
}

/// Execute the `validate` subcommand against the given arguments.
///
/// Mirrors Python `_run_validate(args) -> int` exactly. Returns a
/// fully-captured [`CliOutcome`]. Pure function: only IO is reading
/// the persona-file via [`std::fs::read_to_string`].
pub fn run_validate(args: &ValidateArgs) -> CliOutcome {
    let mut outcome = CliOutcome::default();

    if !args.persona_file.exists() {
        outcome.stderr = format!(
            "wakir-persona: persona-file not found: {}\n",
            args.persona_file.display()
        );
        outcome.exit_code = EXIT_INPUT_NOT_FOUND;
        return outcome;
    }

    let text = match fs::read_to_string(&args.persona_file) {
        Ok(s) => s,
        Err(e) => {
            outcome.stderr = format!(
                "wakir-persona: persona-file vanished mid-run: {}: {e}\n",
                args.persona_file.display()
            );
            outcome.exit_code = EXIT_INPUT_NOT_FOUND;
            return outcome;
        }
    };

    // validate_persona is infallible (errors are accumulated into the
    // report); no error branch beyond the IO above.
    let report = validate_persona(ValidatorInput::MarkdownText(&text));
    let canonical = report.to_canonical_value();
    outcome.stdout = serialise_validation_report(&canonical);

    if !args.quiet {
        // Verdict-first progress line mirrors the Python pendant
        // exactly: "valid" or "invalid: N error(s)".
        let verdict = if report.is_valid {
            "valid".to_string()
        } else {
            format!("invalid: {} error(s)", report.errors.len())
        };
        outcome.stderr.push_str(&format!(
            "wakir-persona: validated {} -> {}\n",
            args.persona_file.display(),
            verdict
        ));
    }

    outcome.exit_code = if report.is_valid {
        0
    } else {
        EXIT_VALIDATION_FAILED
    };
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
            Command::Validate(args) => run_validate(&args),
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

// ---------------------------------------------------------------------
// `--target persona-v2` operator-CLI test pack (Phase-1b Sprint-5 Tag-2).
//
// Rust mirror of `wirelang/tests/test_persona_migration_cli_v2_target.py`
// (7 Python tests). Covers the `wakir-persona migrate --target persona-v2`
// surface that Sprint-3 Tag-3 wired into the CLI's `--target` choices via
// `PERSONA_SCHEMA_VERSION_LIST`. Each Rust test is paired 1:1 with a
// Python test so that a future regression in either tree fails the
// matching test on the other side.
//
// Pairing:
//
// | Python test                                                | Rust test                                                  |
// |------------------------------------------------------------|-----------------------------------------------------------|
// | test_build_parser_accepts_target_persona_v2                | vt1_parser_accepts_target_persona_v2                       |
// | test_cli_v9_to_v2_single_step_emits_v2_canonical_subset    | vt2_cli_v9_to_v2_single_step_emits_v2_canonical_subset     |
// | test_cli_v9_to_v2_emit_hash_matches_v9_migrated_to_v2_pin  | vt3_cli_v9_to_v2_emit_hash_matches_v9_migrated_to_v2_pin   |
// | test_cli_v8_to_v2_multi_step_chain_emits_v2_canonical_*    | vt4_cli_v8_to_v2_multi_step_chain_emits_v2_canonical_*     |
// | test_cli_v8_to_v2_chain_expect_hash_passes                 | vt5_cli_v8_to_v2_chain_expect_hash_passes                  |
// | test_cli_target_persona_v0_from_v9_input_rejects_with_*    | vt6_cli_target_persona_v0_from_v9_input_rejects_with_*     |
// |  (no Python counterpart — Rust-only extra: V9 single-step  | vt7_cli_v9_to_v2_chain_expect_hash_passes                  |
// |   expect-hash; matches the Python single-step contract     |   (paired with vt3 via expect-hash form; mirrors the      |
// |   that vt3 exercises via emit-hash. Added so the bare-hex  |   Python emit-hash anchor as an expect-hash anchor)        |
// |   expect-hash form has v2-target coverage.)                |                                                            |
//
// Cross-check Rust ↔ Python: each test's behaviour is byte-identical to
// the Python test on stdout (JSON shape + schema_version field) and
// load-bearing-identical on stderr (marker substrings + exit codes;
// progress-line wording is irrelevant — all vt2..vt7 run under `--quiet`
// where stderr is silent or carries only the pin / drift marker).
// ---------------------------------------------------------------------

#[cfg(test)]
mod v2_target_tests {
    use super::*;
    use persona_migration_resolver::{
        PERSONA_HASH_PIN_V8_MIGRATED_TO_V2, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
    };
    use std::path::PathBuf;

    // Repeat the fixture-resolver here instead of pulling it from the
    // sibling `tests` mod: Rust's mod-private items are not visible to
    // sibling test modules. This is a 12-LoC mirror, not a new contract.
    fn fixture(name: &str) -> PathBuf {
        let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
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
    // vt1 / Parser surface: --target persona-v2 must be an accepted
    //       choice after Tag-3's PERSONA_SCHEMA_VERSION_LIST extension.
    //
    // Mirror of Python `test_build_parser_accepts_target_persona_v2`.
    // Regression guard for the resolver's PERSONA_SCHEMA_VERSION_LIST
    // tuple: if a future refactor narrows the list back to
    // ("persona-v0", "persona-v1"), `validate_target("persona-v2")`
    // rejects and clap's parse fails with EXIT_USAGE_ERROR — both
    // assertions trip.
    // -------------------------------------------------------------------

    #[test]
    fn vt1_parser_accepts_target_persona_v2() {
        // Direct call on the public validator.
        assert_eq!(
            validate_target("persona-v2"),
            Ok("persona-v2".to_string()),
            "validate_target must accept persona-v2 after Tag-3 list extension"
        );

        // Full clap parse path: argv shape mirrors the Python invocation
        // `["migrate", str(V9_FIXTURE), "--target", "persona-v2"]`. Cli
        // is a derive-Parser; we use try_parse_from so a clap regression
        // (e.g. unknown subcommand) surfaces as `Err` rather than a
        // process exit at test-time.
        let path = v9_fixture();
        let path_str = path.to_string_lossy().into_owned();
        let cli = Cli::try_parse_from([
            "wakir-persona",
            "migrate",
            &path_str,
            "--target",
            "persona-v2",
        ])
        .expect("clap should parse --target persona-v2");
        match cli.command {
            Command::Migrate(args) => {
                assert_eq!(args.target, "persona-v2");
                assert_eq!(args.persona_file, path);
            }
            other => panic!("expected Command::Migrate, got {other:?}"),
        }
    }

    // -------------------------------------------------------------------
    // vt2 / Single-step CLI path: v9 -> v2 (V1ToV2Step alone).
    //
    // Mirror of Python `test_cli_v9_to_v2_single_step_emits_v2_canonical_subset`.
    // stdout JSON carries schema_version=persona-v2; stderr is silent
    // under --quiet without --emit-hash.
    // -------------------------------------------------------------------

    #[test]
    fn vt2_cli_v9_to_v2_single_step_emits_v2_canonical_subset() {
        let outcome = run_in_process(
            "v9 -> v2 single-step",
            v9_fixture(),
            &["--target", "persona-v2", "--quiet"],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let payload: Value =
            serde_json::from_str(&outcome.stdout).expect("stdout is JSON-decodable");
        assert_eq!(
            payload["schema_version"], "persona-v2",
            "schema_version must be lifted to persona-v2"
        );
        assert_eq!(
            outcome.stderr, "",
            "--quiet without --emit-hash must yield empty stderr"
        );
    }

    // -------------------------------------------------------------------
    // vt3 / --emit-hash on the v9 -> v2 single-step path surfaces the
    //       V9-migrated-to-V2 pin (PERSONA_HASH_PIN_V9_MIGRATED_TO_V2).
    //
    // Mirror of Python `test_cli_v9_to_v2_emit_hash_matches_v9_migrated_to_v2_pin`.
    // Pinned-anchor assertion: a CLI-dispatch regression (e.g.
    // accidentally re-hashing the v1 intermediate instead of the v2
    // endpoint) trips this assertion rather than silently emitting the
    // wrong pin.
    // -------------------------------------------------------------------

    #[test]
    fn vt3_cli_v9_to_v2_emit_hash_matches_v9_migrated_to_v2_pin() {
        let outcome = run_in_process(
            "v9 -> v2 emit-hash",
            v9_fixture(),
            &["--target", "persona-v2", "--quiet", "--emit-hash"],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let nonempty: Vec<&str> = outcome
            .stderr
            .lines()
            .filter(|l| !l.trim().is_empty())
            .collect();
        assert_eq!(
            nonempty,
            vec![PERSONA_HASH_PIN_V9_MIGRATED_TO_V2],
            "emit-hash stderr must be exactly the V9-migrated-to-V2 pin"
        );
    }

    // -------------------------------------------------------------------
    // vt4 / Multi-step CLI path: v8 -> v0 -> v1 -> v2 (M-1 direct
    //       anchor through the operator surface).
    //
    // Mirror of Python `test_cli_v8_to_v2_multi_step_chain_emits_v2_canonical_subset`.
    // The resolver builds [V0ToV1Step(), V1ToV2Step()] automatically
    // when the source is v0 (v8 fixture's recorded schema_version) and
    // the target is v2. stdout JSON carries schema_version=persona-v2.
    // -------------------------------------------------------------------

    #[test]
    fn vt4_cli_v8_to_v2_multi_step_chain_emits_v2_canonical_subset() {
        let outcome = run_in_process(
            "v8 -> chain -> v2",
            v8_fixture(),
            &["--target", "persona-v2", "--quiet"],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let payload: Value =
            serde_json::from_str(&outcome.stdout).expect("stdout is JSON-decodable");
        assert_eq!(
            payload["schema_version"], "persona-v2",
            "schema_version must be lifted to persona-v2 through the chain"
        );
    }

    // -------------------------------------------------------------------
    // vt5 / --expect-hash against PERSONA_HASH_PIN_V8_MIGRATED_TO_V2 on
    //       the v8 -> chain -> v2 path passes (M-1 direct anchor via
    //       operator surface).
    //
    // Mirror of Python `test_cli_v8_to_v2_chain_expect_hash_passes`.
    // Full sha256:<64hex> form (bare-hex form is exercised by t8b on
    // the v1 surface; here we keep parity with the Python file which
    // also uses full form on this v2-target test).
    //
    // By construction PERSONA_HASH_PIN_V8_MIGRATED_TO_V2 ==
    // PERSONA_HASH_PIN_V9_MIGRATED_TO_V2 (v8 and v9 share every
    // canonical-subset key except schema_version, and the chain
    // endpoint sets v2 either way); we anchor on the V8 alias here.
    // -------------------------------------------------------------------

    #[test]
    fn vt5_cli_v8_to_v2_chain_expect_hash_passes() {
        let outcome = run_in_process(
            "v8 -> chain -> v2 expect-hash",
            v8_fixture(),
            &[
                "--target",
                "persona-v2",
                "--quiet",
                "--expect-hash",
                PERSONA_HASH_PIN_V8_MIGRATED_TO_V2,
            ],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        // --quiet without --emit-hash: stderr silent.
        assert_eq!(
            outcome.stderr, "",
            "--quiet without --emit-hash must yield empty stderr on happy path"
        );
    }

    // -------------------------------------------------------------------
    // vt6 / Negative path: --target persona-v0 with a v9 input is
    //       rejected at resolver time with exit code 1.
    //
    // Mirror of Python `test_cli_target_persona_v0_from_v9_input_rejects_with_exit_1`.
    // Forward-only chain (Default-Lock A-2 additive-only): persona-v0
    // is in PERSONA_SCHEMA_VERSION_LIST so clap accepts it, but no
    // inverse migration step is registered, so the resolver raises
    // PersonaMigrationError and the CLI maps that to EXIT_MIGRATION_ERROR
    // = 1.
    // -------------------------------------------------------------------

    #[test]
    fn vt6_cli_target_persona_v0_from_v9_input_rejects_with_exit_1() {
        let outcome = run_in_process(
            "v9 -> v0 forward-only-reject",
            v9_fixture(),
            &["--target", "persona-v0", "--quiet"],
        );
        assert_eq!(
            outcome.exit_code, EXIT_MIGRATION_ERROR,
            "stderr: {}",
            outcome.stderr
        );
        assert!(
            outcome.stderr.contains("migration failed"),
            "expected 'migration failed' marker; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // vt7 / --expect-hash against PERSONA_HASH_PIN_V9_MIGRATED_TO_V2 on
    //       the v9 -> v2 single-step path passes.
    //
    // Companion to vt5: that test pins the v8 -> chain -> v2 endpoint
    // via PERSONA_HASH_PIN_V8_MIGRATED_TO_V2; this test pins the v9 ->
    // v2 single-step path via PERSONA_HASH_PIN_V9_MIGRATED_TO_V2 (which
    // is the same byte-blob by construction, but reached via a
    // different dispatch path — single V1ToV2Step alone, no V0ToV1Step
    // upfront). Catches a regression where the single-step path
    // accidentally drops or duplicates a step.
    //
    // This is an additive Rust-side anchor not present 1:1 in the
    // Python file (the Python file exercises the single-step path via
    // emit-hash in test_cli_v9_to_v2_emit_hash_matches_*, see vt3
    // above); we add the expect-hash form here for symmetry with vt5.
    // The Python single-step expect-hash form is implicitly covered
    // because the Python emit-hash test asserts byte-equality with the
    // same pin constant.
    // -------------------------------------------------------------------

    #[test]
    fn vt7_cli_v9_to_v2_chain_expect_hash_passes() {
        let outcome = run_in_process(
            "v9 -> v2 single-step expect-hash",
            v9_fixture(),
            &[
                "--target",
                "persona-v2",
                "--quiet",
                "--expect-hash",
                PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
            ],
        );
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        assert_eq!(
            outcome.stderr, "",
            "--quiet without --emit-hash must yield empty stderr on happy path"
        );
    }
}

// ---------------------------------------------------------------------
// `validate` subcommand test pack (Phase-1b Sprint-6 Tag-2).
//
// Rust mirror of `wirelang/tests/test_persona_validator_cli.py`. Pairs
// 1:1 with the Python tests so that a regression on either side fails
// the matching test on the other side.
//
// Pairing:
//
// | Python test                                              | Rust test                                                |
// |----------------------------------------------------------|----------------------------------------------------------|
// | test_build_parser_accepts_validate_subcommand            | va1_parser_accepts_validate_subcommand                   |
// | test_build_parser_validate_subcommand_quiet_flag_parses  | va2_parser_validate_subcommand_quiet_flag                |
// | test_build_parser_validate_subcommand_rejects_unknown_*  | va3_parser_validate_subcommand_rejects_unknown_flag      |
// | test_validate_v9_returns_exit_code_0_and_valid_report    | va4_validate_v9_returns_exit_0_and_valid_report          |
// | test_validate_v9_stdout_sorted_and_newline_terminated    | va5_validate_v9_stdout_sorted_and_newline_terminated     |
// | test_validate_v8_returns_exit_code_1_and_invalid_report  | va6_validate_v8_returns_exit_1_and_invalid_report        |
// | test_validate_v9_progress_line_when_not_quiet            | va7_validate_v9_progress_line_when_not_quiet             |
// | test_validate_v8_progress_line_carries_invalid_count     | va8_validate_v8_progress_line_carries_invalid_count      |
// | test_validate_missing_file_returns_exit_code_3           | va9_validate_missing_file_returns_exit_3                 |
// | test_validate_v9_stdout_byte_identical_to_frozen_fixture | va10_validate_v9_stdout_byte_identical_to_python_cli     |
// | test_validate_v8_stdout_byte_identical_to_frozen_fixture | va11_validate_v8_stdout_byte_identical_to_python_cli     |
// | test_validate_v9_idempotent_stdout                       | va12_validate_v9_idempotent_stdout                       |
// | test_validate_v8_idempotent_stdout                       | va13_validate_v8_idempotent_stdout                       |
// | test_migrate_subcommand_still_works_after_validate_added | va14_migrate_subcommand_still_works_after_validate_added |
//
// Cross-check Rust ↔ Python: stdout shape is asserted byte-identical
// via `include_str!` on the same frozen fixtures the Python CLI tests
// load (`v8-validated.expected.json`, `v9-validated.expected.json`).
// ---------------------------------------------------------------------

#[cfg(test)]
mod validate_tests {
    use super::*;
    use std::path::PathBuf;

    fn fixture(name: &str) -> PathBuf {
        let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
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

    /// Helper that runs the in-process CLI against a fixture file via
    /// the `validate` subcommand. Mirror of [`run_in_process`] (which
    /// targets `migrate`).
    fn run_validate_in_process(persona_file: PathBuf, extra: &[&str]) -> CliOutcome {
        let path_str = persona_file.to_string_lossy().into_owned();
        let mut argv: Vec<&str> = vec!["wakir-persona", "validate", &path_str];
        argv.extend_from_slice(extra);
        run(&argv)
    }

    // -------------------------------------------------------------------
    // va1 / Parser accepts the `validate` subcommand.
    // -------------------------------------------------------------------

    #[test]
    fn va1_parser_accepts_validate_subcommand() {
        let path = v9_fixture();
        let path_str = path.to_string_lossy().into_owned();
        let cli = Cli::try_parse_from(["wakir-persona", "validate", &path_str])
            .expect("clap should parse `validate <file>`");
        match cli.command {
            Command::Validate(args) => {
                assert_eq!(args.persona_file, path);
                assert!(!args.quiet, "default --quiet must be false");
            }
            _ => panic!("expected Command::Validate"),
        }
    }

    // -------------------------------------------------------------------
    // va2 / `--quiet` flag parses on the validate subcommand.
    // -------------------------------------------------------------------

    #[test]
    fn va2_parser_validate_subcommand_quiet_flag() {
        let path = v9_fixture();
        let path_str = path.to_string_lossy().into_owned();
        let cli = Cli::try_parse_from(["wakir-persona", "validate", &path_str, "--quiet"])
            .expect("clap should parse `validate <file> --quiet`");
        match cli.command {
            Command::Validate(args) => {
                assert!(args.quiet, "--quiet must flip the flag to true");
            }
            _ => panic!("expected Command::Validate"),
        }
    }

    // -------------------------------------------------------------------
    // va3 / Validate subcommand rejects unknown flags (e.g. --target
    //       which belongs to migrate).
    // -------------------------------------------------------------------

    #[test]
    fn va3_parser_validate_subcommand_rejects_unknown_flag() {
        let path = v9_fixture();
        let outcome = run(&[
            "wakir-persona",
            "validate",
            &path.to_string_lossy(),
            "--target",
            "persona-v2",
        ]);
        assert_eq!(outcome.exit_code, EXIT_USAGE_ERROR);
        assert!(
            outcome.stderr.contains("--target") || outcome.stderr.contains("unexpected"),
            "stderr should flag the unknown flag; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // va4 / V9 happy path: is_valid=true, exit 0.
    // -------------------------------------------------------------------

    #[test]
    fn va4_validate_v9_returns_exit_0_and_valid_report() {
        let outcome = run_validate_in_process(v9_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let payload: Value = serde_json::from_str(&outcome.stdout).expect("stdout is JSON");
        assert_eq!(payload["is_valid"], true);
        assert_eq!(payload["schema_version"], "persona-v1");
        assert_eq!(payload["schema_supported"], true);
        assert_eq!(payload["report_schema_version"], "persona-validation-v1");
        assert!(payload["errors"]
            .as_array()
            .expect("errors is array")
            .is_empty());
        assert_eq!(outcome.stderr, "", "--quiet must yield empty stderr");
    }

    // -------------------------------------------------------------------
    // va5 / stdout has lexical key order and terminates with `\n`.
    // -------------------------------------------------------------------

    #[test]
    fn va5_validate_v9_stdout_sorted_and_newline_terminated() {
        let outcome = run_validate_in_process(v9_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, 0);
        assert!(
            outcome.stdout.ends_with('\n'),
            "stdout must end with newline"
        );
        // "errors" must precede "is_valid" in the rendered JSON.
        let errors_pos = outcome.stdout.find("\"errors\"").expect("errors key");
        let is_valid_pos = outcome.stdout.find("\"is_valid\"").expect("is_valid key");
        assert!(
            errors_pos < is_valid_pos,
            "expected sorted key order; got errors@{errors_pos} is_valid@{is_valid_pos}"
        );
    }

    // -------------------------------------------------------------------
    // va6 / V8 failure path: is_valid=false, exit 1.
    // -------------------------------------------------------------------

    #[test]
    fn va6_validate_v8_returns_exit_1_and_invalid_report() {
        let outcome = run_validate_in_process(v8_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, EXIT_VALIDATION_FAILED);
        assert_eq!(outcome.exit_code, 1);
        let payload: Value = serde_json::from_str(&outcome.stdout).expect("stdout is JSON");
        assert_eq!(payload["is_valid"], false);
        assert_eq!(payload["schema_version"], "persona-v0");
        assert_eq!(payload["schema_supported"], false);
        let errs = payload["errors"].as_array().expect("errors is array");
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0]["code"], "schema-version-unsupported");
        assert_eq!(errs[0]["detail"], "persona-v0");
        assert_eq!(outcome.stderr, "", "--quiet must yield empty stderr");
    }

    // -------------------------------------------------------------------
    // va7 / Progress line on stderr when not --quiet (V9 = valid).
    // -------------------------------------------------------------------

    #[test]
    fn va7_validate_v9_progress_line_when_not_quiet() {
        let outcome = run_validate_in_process(v9_fixture(), &[]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        assert!(
            outcome.stderr.contains("wakir-persona: validated"),
            "missing progress marker; got: {}",
            outcome.stderr
        );
        assert!(
            outcome.stderr.contains("-> valid"),
            "missing 'valid' verdict; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // va8 / Progress line carries the invalid count (V8 = invalid).
    // -------------------------------------------------------------------

    #[test]
    fn va8_validate_v8_progress_line_carries_invalid_count() {
        let outcome = run_validate_in_process(v8_fixture(), &[]);
        assert_eq!(outcome.exit_code, EXIT_VALIDATION_FAILED);
        assert!(
            outcome.stderr.contains("wakir-persona: validated"),
            "missing progress marker; got: {}",
            outcome.stderr
        );
        assert!(
            outcome.stderr.contains("-> invalid: 1 error(s)"),
            "missing invalid-count verdict; got: {}",
            outcome.stderr
        );
    }

    // -------------------------------------------------------------------
    // va9 / Missing persona-file returns exit 3.
    // -------------------------------------------------------------------

    #[test]
    fn va9_validate_missing_file_returns_exit_3() {
        let outcome = run(&[
            "wakir-persona",
            "validate",
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
    // va10 / V9 stdout byte-identical to the Python-frozen fixture.
    //
    // The fixture was generated on 2026-05-11 (Sprint-6 Tag-2 Box) by
    // `python -m wirelang.persona.cli validate v9-persona-framework-
    // native.md --quiet > v9-validated.expected.json`. A drift on
    // either side breaks this anchor.
    // -------------------------------------------------------------------

    #[test]
    fn va10_validate_v9_stdout_byte_identical_to_python_cli() {
        let outcome = run_validate_in_process(v9_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let expected = include_str!("../tests/fixtures/v9-validated.expected.json");
        assert_eq!(
            outcome.stdout, expected,
            "stdout drifted from Python CLI byte-fingerprint (v9 validate)"
        );
    }

    // -------------------------------------------------------------------
    // va11 / V8 stdout byte-identical to the Python-frozen fixture.
    // -------------------------------------------------------------------

    #[test]
    fn va11_validate_v8_stdout_byte_identical_to_python_cli() {
        let outcome = run_validate_in_process(v8_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, EXIT_VALIDATION_FAILED);
        let expected = include_str!("../tests/fixtures/v8-validated.expected.json");
        assert_eq!(
            outcome.stdout, expected,
            "stdout drifted from Python CLI byte-fingerprint (v8 validate)"
        );
    }

    // -------------------------------------------------------------------
    // va12 / V9 idempotence: two invocations yield byte-identical stdout.
    // -------------------------------------------------------------------

    #[test]
    fn va12_validate_v9_idempotent_stdout() {
        let first = run_validate_in_process(v9_fixture(), &["--quiet"]);
        let second = run_validate_in_process(v9_fixture(), &["--quiet"]);
        assert_eq!(first.exit_code, 0);
        assert_eq!(second.exit_code, 0);
        assert_eq!(first.stdout, second.stdout, "validate must be idempotent");
    }

    // -------------------------------------------------------------------
    // va13 / V8 idempotence (failure-path).
    // -------------------------------------------------------------------

    #[test]
    fn va13_validate_v8_idempotent_stdout() {
        let first = run_validate_in_process(v8_fixture(), &["--quiet"]);
        let second = run_validate_in_process(v8_fixture(), &["--quiet"]);
        assert_eq!(first.exit_code, EXIT_VALIDATION_FAILED);
        assert_eq!(second.exit_code, EXIT_VALIDATION_FAILED);
        assert_eq!(
            first.stdout, second.stdout,
            "validate must be idempotent on failure path too"
        );
    }

    // -------------------------------------------------------------------
    // va14 / Backward compatibility: migrate subcommand still works
    //        after the validate subcommand was added.
    // -------------------------------------------------------------------

    #[test]
    fn va14_migrate_subcommand_still_works_after_validate_added() {
        let outcome = run_in_process("v8->v1 backcompat", v8_fixture(), &["--quiet"]);
        assert_eq!(outcome.exit_code, 0, "stderr: {}", outcome.stderr);
        let payload: Value = serde_json::from_str(&outcome.stdout).expect("stdout is JSON");
        assert_eq!(payload["schema_version"], "persona-v1");
    }

    // -------------------------------------------------------------------
    // va15 / Determinism stress: 10-iteration loop, all byte-identical.
    //        Mirror of Crate-7 t15 anchor pattern for the CLI surface.
    //        Rust-only addition (no Python counterpart needed because
    //        Python uses the same validator core).
    // -------------------------------------------------------------------

    #[test]
    fn va15_validate_v9_stdout_determinism_stress_10_iter() {
        let first = run_validate_in_process(v9_fixture(), &["--quiet"]);
        assert_eq!(first.exit_code, 0);
        for i in 0..10 {
            let later = run_validate_in_process(v9_fixture(), &["--quiet"]);
            assert_eq!(
                later.stdout, first.stdout,
                "iteration {i} drifted from baseline"
            );
            assert_eq!(later.exit_code, 0);
        }
    }
}
