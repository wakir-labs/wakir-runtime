// SPDX-License-Identifier: Apache-2.0
//! Operator CLI for the ADR-0058 Pilot-Persona Migration Schritt 8.
//!
//! Produces a deterministic state-export bundle from the Claude-Code-
//! Sandbox-side persona artefacts (persona-definition plus workspace
//! state plus active-spawn-memory) into a Wakir-Runtime-format JSON
//! document ready to be ingested by the wakir-runtime persona-engine
//! spawn pipeline (Schritt 9, Operator-Hand on the Pilot-VM).
//!
//! # Synopsis
//!
//! ```text
//! wakir-persona-pilot-export
//!     --persona-def    <path/to/.claude/agents/<slug>.md>
//!     --workspace-dir  <path/to/agents-workspaces/<slug>/>
//!     --out            <path/to/exports/<slug>.pilot-export.json>
//!     [--pin-hash-v907 <sha256:<64hex> | <64hex>>]
//!     [--active-spawn-memory <path/to/active-spawn-memory.json>]
//!     [--quiet]
//! ```
//!
//! # Pipeline
//!
//! 1. Read `--persona-def` markdown and map it to `wakir-persona-v1`
//!    via the byte-deterministic Sprint-Pengine-7 Tag-1 converter
//!    ([`persona_engine_format::map_claude_native_to_wakir_v1`]).
//! 2. Compute the V-907 persona-hash on the resulting document.
//! 3. Walk `--workspace-dir` (read-only) and produce a manifest of
//!    `(relative_path, sha256, size_bytes)` triples sorted by path.
//!    The manifest's own sha256 becomes the `workspace_state_hash`.
//! 4. Read optional `--active-spawn-memory` JSON (operator-supplied
//!    snapshot of in-flight spawn state, or `null` if not active).
//! 5. Assemble the `PilotExportBundle` (see schema below); JCS-canonicalise
//!    it; verify the V-907 pin if `--pin-hash-v907` was supplied; write
//!    the bytes plus trailing newline to `--out`.
//!
//! # PilotExportBundle JSON shape
//!
//! ```json
//! {
//!   "schema_version": "wakir-pilot-export-v1",
//!   "persona_id": "tomas",
//!   "exported_at_utc": "<operator-supplied, RFC 3339 UTC, second-precision>",
//!   "v907_persona_hash": "sha256:<64hex>",
//!   "workspace_state_hash": "sha256:<64hex>",
//!   "wakir_persona_v1": { ... },                  // §3 of persona-engine-format-spec
//!   "workspace_manifest": {                       // operator-readable
//!     "file_count": <usize>,
//!     "total_size_bytes": <u64>,
//!     "entries": [
//!       { "path": "<relative>", "sha256": "<hex>", "size_bytes": <u64> }
//!     ]
//!   },
//!   "active_spawn_memory": null | { ... }         // operator-supplied JSON
//! }
//! ```
//!
//! The bundle is the read-only export artefact that the operator
//! transfers (out-of-band scp or USB) to the Pilot-VM; the Pilot-VM
//! spawn-side (Schritt 9) consumes the bundle and reconstitutes the
//! Tomás-Persona context.
//!
//! # Exit codes
//!
//! - `0`: success.
//! - `1`: schema / parse error (front-matter invalid, workspace walk
//!   IO failure, ...).
//! - `2`: V-907 persona-hash drift (recomputed != pin).
//! - `3`: input file or directory not found.
//! - `64`: argparse usage error.
//!
//! # Sandbox boundary (ADR-0051)
//!
//! This CLI runs on the **operator's Claude-Code-Sandbox side** and is
//! purely read-only over the AI-Corp tree + write-only to the operator-
//! supplied `--out` path. It does **NOT** touch the Pilot-VM, SPIRE,
//! or NATS-KV — those are operator-hand surfaces (Schritt 9 recipe at
//! `infra/migration-pilot/TOMAS_SPAWN_RECIPE.md`).

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use clap::Parser;
use persona_engine_format::{
    map_claude_native_to_wakir_v1, wakir_persona_hash, PersonaEngineFormatError,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

// ---------------------------------------------------------------------
// Exit codes (mirror of persona-converter §7.4)
// ---------------------------------------------------------------------

/// Success exit code.
pub const EXIT_OK: i32 = 0;
/// Schema / parse / IO error exit code.
pub const EXIT_SCHEMA_ERROR: i32 = 1;
/// V-907 hash-drift exit code.
pub const EXIT_HASH_DRIFT_ERROR: i32 = 2;
/// Input-not-found exit code.
pub const EXIT_INPUT_NOT_FOUND: i32 = 3;
/// Argparse usage-error exit code (Unix `EX_USAGE`).
pub const EXIT_USAGE_ERROR: i32 = 64;

/// Schema-version string of the export bundle.
pub const PILOT_EXPORT_SCHEMA_VERSION: &str = "wakir-pilot-export-v1";

// ---------------------------------------------------------------------
// clap argparse
// ---------------------------------------------------------------------

/// CLI shape.
#[derive(Debug, Parser)]
#[command(
    name = "wakir-persona-pilot-export",
    about = "ADR-0058 Pilot-Persona Migration Schritt 8: produce a deterministic state-export bundle (persona-definition + workspace-state + active-spawn-memory) for the wakir-runtime spawn pipeline (Schritt 9).",
    long_about = "Operator CLI that walks the Claude-Code-Sandbox-side persona artefacts and produces a JCS-canonicalised JSON bundle ready for transfer to the Pilot-VM. Pipeline: (1) convert .claude/agents/<slug>.md to wakir-persona-v1 via the Sprint-Pengine-7 Tag-1 byte-deterministic converter; (2) compute the V-907 persona-hash; (3) walk the workspace directory (read-only) and produce a sha256-anchored manifest; (4) optionally embed an operator-supplied active-spawn-memory snapshot; (5) write the JCS bytes to --out. Anchors: ADR-0058 §Persona-Engine-Format-Specs, persona-engine-format-spec.md §3, ADR-0036 Self-Migration-Konverter.",
    version
)]
pub struct Cli {
    /// Path to the `.claude/agents/<slug>.md` axis-A persona definition.
    #[arg(long, value_name = "PATH")]
    pub persona_def: PathBuf,

    /// Path to the persona's workspace directory (read-only walk).
    #[arg(long, value_name = "DIR")]
    pub workspace_dir: PathBuf,

    /// Path to write the JCS-canonicalised export bundle JSON.
    #[arg(long, value_name = "PATH")]
    pub out: PathBuf,

    /// UTC export timestamp (RFC 3339, second precision). Operator-supplied
    /// to keep the CLI byte-deterministic and side-effect-free.
    #[arg(long, value_name = "RFC3339")]
    pub exported_at_utc: String,

    /// Optional V-907 persona-hash pin. If supplied, the recomputed hash
    /// MUST match (else exit 2).
    #[arg(long, value_name = "HASH")]
    pub pin_hash_v907: Option<String>,

    /// Optional path to a JSON file containing the operator-supplied
    /// active-spawn-memory snapshot. Embedded as-is into the bundle.
    /// Absent → bundle records `"active_spawn_memory": null`.
    #[arg(long, value_name = "PATH")]
    pub active_spawn_memory: Option<PathBuf>,

    /// Suppress informational stderr output (errors still printed).
    #[arg(long)]
    pub quiet: bool,
}

// ---------------------------------------------------------------------
// Bundle data types
// ---------------------------------------------------------------------

/// One row of the workspace manifest.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkspaceManifestEntry {
    /// Relative path from the workspace directory root.
    pub path: String,
    /// Hex-encoded sha256 over the file bytes.
    pub sha256: String,
    /// File size in bytes.
    pub size_bytes: u64,
}

/// The operator-readable workspace manifest section of the bundle.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkspaceManifest {
    /// Number of files traversed.
    pub file_count: usize,
    /// Sum of file sizes.
    pub total_size_bytes: u64,
    /// Entries sorted by `path` for determinism.
    pub entries: Vec<WorkspaceManifestEntry>,
}

/// The pilot-export bundle envelope.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PilotExportBundle {
    /// Schema-version literal `wakir-pilot-export-v1`.
    pub schema_version: String,
    /// Persona slug (matches `wakir_persona_v1.persona_id`).
    pub persona_id: String,
    /// Operator-supplied UTC timestamp (RFC 3339, second precision).
    pub exported_at_utc: String,
    /// V-907 persona-hash (`sha256:<64hex>`).
    pub v907_persona_hash: String,
    /// Workspace-state hash (`sha256:<64hex>` over the JCS-canonicalised manifest).
    pub workspace_state_hash: String,
    /// Embedded wakir-persona-v1 document (§3 of persona-engine-format-spec).
    pub wakir_persona_v1: serde_json::Value,
    /// Workspace manifest (file paths, sha256, sizes).
    pub workspace_manifest: WorkspaceManifest,
    /// Active-spawn-memory snapshot (operator-supplied) or `null`.
    pub active_spawn_memory: serde_json::Value,
}

// ---------------------------------------------------------------------
// Error surface
// ---------------------------------------------------------------------

/// CLI error class. Each variant maps to one exit code in `to_exit_code`.
#[derive(Debug)]
pub enum PilotExportError {
    /// Input file or directory not found.
    InputNotFound {
        /// Which argument triggered the error.
        which: &'static str,
        /// The missing path.
        path: PathBuf,
    },
    /// Persona-definition / schema / IO / parse failure.
    SchemaError(String),
    /// V-907 persona-hash drift between recomputed and supplied pin.
    HashDrift {
        /// The hash the engine recomputed.
        computed: String,
        /// The pin the operator supplied.
        supplied: String,
    },
}

impl std::fmt::Display for PilotExportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InputNotFound { which, path } => write!(
                f,
                "PilotExportError::InputNotFound: --{which} path not found: {}",
                path.display()
            ),
            Self::SchemaError(m) => write!(f, "PilotExportError::SchemaError: {m}"),
            Self::HashDrift { computed, supplied } => write!(
                f,
                "PilotExportError::HashDrift: V-907 recomputed hash {computed} does NOT match --pin-hash-v907 {supplied}"
            ),
        }
    }
}

impl std::error::Error for PilotExportError {}

impl PilotExportError {
    /// Map an error to its exit code.
    pub fn to_exit_code(&self) -> i32 {
        match self {
            Self::InputNotFound { .. } => EXIT_INPUT_NOT_FOUND,
            Self::SchemaError(_) => EXIT_SCHEMA_ERROR,
            Self::HashDrift { .. } => EXIT_HASH_DRIFT_ERROR,
        }
    }
}

impl From<PersonaEngineFormatError> for PilotExportError {
    fn from(e: PersonaEngineFormatError) -> Self {
        Self::SchemaError(format!("persona-engine-format: {e}"))
    }
}

// ---------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------

/// Walk `workspace_dir` (read-only), producing a sorted, deterministic
/// manifest. Symlinks are NOT followed; hidden files (`.`-prefixed) ARE
/// included (audit-trail completeness).
pub fn build_workspace_manifest(
    workspace_dir: &Path,
) -> Result<WorkspaceManifest, PilotExportError> {
    if !workspace_dir.exists() {
        return Err(PilotExportError::InputNotFound {
            which: "workspace-dir",
            path: workspace_dir.to_owned(),
        });
    }
    if !workspace_dir.is_dir() {
        return Err(PilotExportError::SchemaError(format!(
            "--workspace-dir {} is not a directory",
            workspace_dir.display()
        )));
    }

    let mut entries: Vec<WorkspaceManifestEntry> = Vec::new();
    walk_dir(workspace_dir, workspace_dir, &mut entries)?;

    // Sort by `path` for determinism. The recursion order of `walk_dir`
    // is filesystem-iteration-order, which is not guaranteed stable
    // across platforms / re-runs; the sort gives us byte-determinism.
    entries.sort_by(|a, b| a.path.cmp(&b.path));

    let file_count = entries.len();
    let total_size_bytes = entries.iter().map(|e| e.size_bytes).sum();

    Ok(WorkspaceManifest {
        file_count,
        total_size_bytes,
        entries,
    })
}

fn walk_dir(
    root: &Path,
    cursor: &Path,
    entries: &mut Vec<WorkspaceManifestEntry>,
) -> Result<(), PilotExportError> {
    let read = fs::read_dir(cursor).map_err(|e| {
        PilotExportError::SchemaError(format!("read_dir({}): {e}", cursor.display()))
    })?;
    for child in read {
        let child = child.map_err(|e| {
            PilotExportError::SchemaError(format!("read_dir entry under {}: {e}", cursor.display()))
        })?;
        let ft = child.file_type().map_err(|e| {
            PilotExportError::SchemaError(format!("file_type({:?}): {e}", child.path()))
        })?;
        if ft.is_symlink() {
            // Symlinks are NOT followed; record as zero-byte entry with
            // a `.symlink` suffix tag in path. Operator forensics surface.
            let path = child.path();
            let rel = path.strip_prefix(root).map_err(|_| {
                PilotExportError::SchemaError(format!("strip_prefix({})", path.display()))
            })?;
            entries.push(WorkspaceManifestEntry {
                path: format!("{}#symlink", rel.to_string_lossy()),
                sha256: "0000000000000000000000000000000000000000000000000000000000000000".into(),
                size_bytes: 0,
            });
            continue;
        }
        if ft.is_dir() {
            walk_dir(root, &child.path(), entries)?;
            continue;
        }
        if !ft.is_file() {
            continue;
        }
        let path = child.path();
        let rel = path.strip_prefix(root).map_err(|_| {
            PilotExportError::SchemaError(format!("strip_prefix({})", path.display()))
        })?;
        let bytes = fs::read(&path)
            .map_err(|e| PilotExportError::SchemaError(format!("read({}): {e}", path.display())))?;
        let mut hasher = Sha256::new();
        hasher.update(&bytes);
        let digest = hasher.finalize();
        entries.push(WorkspaceManifestEntry {
            path: rel.to_string_lossy().to_string(),
            sha256: hex::encode(digest),
            size_bytes: bytes.len() as u64,
        });
    }
    Ok(())
}

/// Compute the sha256 over a JCS-canonicalised manifest. The result is
/// the `workspace_state_hash` field of the bundle.
pub fn compute_workspace_state_hash(
    manifest: &WorkspaceManifest,
) -> Result<String, PilotExportError> {
    let value = serde_json::to_value(manifest)
        .map_err(|e| PilotExportError::SchemaError(format!("serde_json::to_value: {e}")))?;
    let jcs = serde_jcs::to_vec(&value)
        .map_err(|e| PilotExportError::SchemaError(format!("serde_jcs::to_vec: {e}")))?;
    let mut hasher = Sha256::new();
    hasher.update(&jcs);
    Ok(format!("sha256:{}", hex::encode(hasher.finalize())))
}

/// Normalise a pin to `sha256:<64hex>` form (accepts either pre-fixed
/// or bare 64-hex).
fn normalise_pin(s: &str) -> Option<String> {
    let lower = s.to_ascii_lowercase();
    if let Some(rest) = lower.strip_prefix("sha256:") {
        if rest.len() == 64 && rest.chars().all(|c| c.is_ascii_hexdigit()) {
            return Some(lower);
        }
        return None;
    }
    if lower.len() == 64 && lower.chars().all(|c| c.is_ascii_hexdigit()) {
        return Some(format!("sha256:{lower}"));
    }
    None
}

/// Run the export pipeline end-to-end. Returns the produced bundle (for
/// in-process testing) and writes the JCS bytes to disk.
pub fn run_export(args: &Cli) -> Result<PilotExportBundle, PilotExportError> {
    // (1) Persona-definition read + map.
    if !args.persona_def.exists() {
        return Err(PilotExportError::InputNotFound {
            which: "persona-def",
            path: args.persona_def.clone(),
        });
    }
    let pd_bytes = fs::read(&args.persona_def).map_err(|e| {
        PilotExportError::SchemaError(format!("read({}): {e}", args.persona_def.display()))
    })?;
    let pd_text = std::str::from_utf8(&pd_bytes).map_err(|e| {
        PilotExportError::SchemaError(format!(
            "persona-def is not UTF-8 ({}): {e}",
            args.persona_def.display()
        ))
    })?;
    let wakir_v1 = map_claude_native_to_wakir_v1(pd_text)?;
    let v907_hash = wakir_persona_hash(&wakir_v1)?;
    let persona_id = wakir_v1
        .get("persona_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| {
            PilotExportError::SchemaError(
                "wakir-persona-v1 is missing persona_id field".to_string(),
            )
        })?
        .to_owned();

    // (2) V-907 pin verification if supplied.
    if let Some(pin) = args.pin_hash_v907.as_ref() {
        let normalised = normalise_pin(pin).ok_or_else(|| {
            PilotExportError::SchemaError(format!(
                "--pin-hash-v907 is not a valid sha256:<64hex> or bare 64-hex form: {pin}"
            ))
        })?;
        if normalised != v907_hash {
            return Err(PilotExportError::HashDrift {
                computed: v907_hash,
                supplied: normalised,
            });
        }
    }

    // (3) Workspace manifest.
    let manifest = build_workspace_manifest(&args.workspace_dir)?;
    let workspace_state_hash = compute_workspace_state_hash(&manifest)?;

    // (4) Active-spawn-memory (optional).
    let active_spawn_memory = match args.active_spawn_memory.as_ref() {
        None => serde_json::Value::Null,
        Some(p) => {
            if !p.exists() {
                return Err(PilotExportError::InputNotFound {
                    which: "active-spawn-memory",
                    path: p.clone(),
                });
            }
            let bytes = fs::read(p).map_err(|e| {
                PilotExportError::SchemaError(format!("read({}): {e}", p.display()))
            })?;
            serde_json::from_slice::<serde_json::Value>(&bytes).map_err(|e| {
                PilotExportError::SchemaError(format!(
                    "active-spawn-memory parse error ({}): {e}",
                    p.display()
                ))
            })?
        }
    };

    // (5) Assemble bundle.
    let bundle = PilotExportBundle {
        schema_version: PILOT_EXPORT_SCHEMA_VERSION.to_string(),
        persona_id,
        exported_at_utc: args.exported_at_utc.clone(),
        v907_persona_hash: v907_hash,
        workspace_state_hash,
        wakir_persona_v1: wakir_v1,
        workspace_manifest: manifest,
        active_spawn_memory,
    };

    Ok(bundle)
}

/// Serialise the bundle to JCS bytes (with trailing newline).
pub fn bundle_to_jcs_bytes(bundle: &PilotExportBundle) -> Result<Vec<u8>, PilotExportError> {
    let value = serde_json::to_value(bundle)
        .map_err(|e| PilotExportError::SchemaError(format!("serde_json::to_value: {e}")))?;
    let mut bytes = serde_jcs::to_vec(&value)
        .map_err(|e| PilotExportError::SchemaError(format!("serde_jcs::to_vec: {e}")))?;
    bytes.push(b'\n');
    Ok(bytes)
}

/// Write the JCS bytes to `out`. Creates parent directories if needed.
pub fn write_bundle(out: &Path, bytes: &[u8]) -> Result<(), PilotExportError> {
    if let Some(parent) = out.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent).map_err(|e| {
                PilotExportError::SchemaError(format!("create_dir_all({}): {e}", parent.display()))
            })?;
        }
    }
    let mut file = fs::File::create(out).map_err(|e| {
        PilotExportError::SchemaError(format!("File::create({}): {e}", out.display()))
    })?;
    file.write_all(bytes)
        .map_err(|e| PilotExportError::SchemaError(format!("write_all({}): {e}", out.display())))?;
    Ok(())
}

/// CLI entrypoint helper consumed by `src/main.rs`.
pub fn run_cli(args: &Cli) -> Result<(), PilotExportError> {
    let bundle = run_export(args)?;
    let bytes = bundle_to_jcs_bytes(&bundle)?;
    write_bundle(&args.out, &bytes)?;
    if !args.quiet {
        // operator-readable summary on stderr.
        eprintln!(
            "wakir-persona-pilot-export OK persona_id={} v907={} workspace_state_hash={} files={} bytes={}",
            bundle.persona_id,
            bundle.v907_persona_hash,
            bundle.workspace_state_hash,
            bundle.workspace_manifest.file_count,
            bundle.workspace_manifest.total_size_bytes,
        );
    }
    Ok(())
}
