// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Operator CLI for the persona-engine-anchor-submit-worker.
//
// Tag-16 Mini-Welle — Phase-3b production-wiring.
//
// Role
// ----
// The CLI is the wire-end of the Python <-> Rust bridge for the WAT
// anchor pipeline. The Python side (`wat/anchor/anchor_backend.py`)
// serialises one `AnchorEnvelope` as a single-line JSON object on
// stdin, the binary advances the submit-worker FSM by one `tick()`,
// then writes one JSON `BridgeResult` line to stdout and exits.
//
// Single-shot, single-envelope, no embedded loop. The Python caller
// owns the queue and the eligibility decision; this binary is the
// "one transport attempt + state transition" hop. This mirrors the
// `replay_cli` posture established by Tag-14 (PR #156).
//
// Transport selection
// -------------------
// `WAKIR_SUBMIT_WORKER_TRANSPORT` selects the `SubmitTransport`
// implementation:
//
//   - `ots_cli` (default): production transport. Shells out to
//     `ots stamp -m <min> --calendar <url> ... <root>` and translates
//     the exit-code / parsed-response into `TransportOutcome`.
//     The calendar URLs and `min_calendars` are supplied by the
//     Python caller as part of the input envelope (see `BridgeInput`).
//   - `mock_accept`: returns `TransportOutcome::Accepted` without
//     side-effects. For hermetic tests.
//   - `mock_retriable`: returns `TransportOutcome::Retriable(...)`.
//   - `mock_permanent`: returns `TransportOutcome::Permanent(...)`.
//
// Wire format
// -----------
// Stdin: one JSON object matching `BridgeInput` (see below).
// Stdout: one JSON object matching `BridgeOutput`.
//
// Exit codes
// ----------
//   0 - Success / Idle / Throttled / Retrying (the FSM advanced; the
//       Python caller inspects `BridgeOutput.result_kind`).
//   1 - Dead (terminal). Operator alert-worthy but not a CLI bug.
//   2 - Usage / input-decode error.
//   3 - Internal-config error (e.g. ots binary missing on PATH when
//       transport is `ots_cli`).
//
// Determinism
// -----------
// Single-envelope; clock and RNG are real (`SystemClock` + a
// real-RNG stub backed by the OS time-based seed for the jitter
// draw). The Python caller does not assert on the jitter value; it
// only consumes `next_delay_secs`.

use std::env;
use std::io::{self, Read, Write};
use std::process::ExitCode;
use std::sync::Arc;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use persona_engine_anchor_emitter::AnchorEnvelope;
use persona_engine_anchor_submit_worker::{
    Clock, InMemoryDeadLetterStore, NoopWriteBackSink, Rng, SubmitResult, SubmitTransport,
    SubmitWorker, SubmitWorkerConfig, SystemClock, TransportOutcome,
};

/// Environment variable selecting the transport implementation.
const ENV_TRANSPORT: &str = "WAKIR_SUBMIT_WORKER_TRANSPORT";
/// Default transport when `ENV_TRANSPORT` is unset.
const DEFAULT_TRANSPORT: &str = "ots_cli";

// ---------------------------------------------------------------------------
// Wire DTOs.
// ---------------------------------------------------------------------------

/// JSON shape consumed on stdin. Mirrors the AnchorEnvelope plus the
/// OTS-side parameters that the production transport needs.
#[derive(Debug, Deserialize)]
struct BridgeInput {
    /// Envelope `event_id`.
    event_id: String,
    /// RFC-3339 UTC timestamp.
    timestamp_utc: String,
    /// Persona identifier.
    persona_id: String,
    /// Hex (lower-case) of the 32-byte SHA-256 Merkle root being
    /// anchored. We accept the hex form on the wire because JSON does
    /// not carry raw bytes, and the Python side already has the hex.
    payload_root_hex: String,
    /// Calendar URLs to submit to. Only used by the `ots_cli`
    /// transport. Empty for mock transports.
    #[serde(default)]
    calendars: Vec<String>,
    /// Minimum calendars threshold. Only used by `ots_cli`.
    /// Defaults to 2 (matches `DEFAULT_MIN_CALENDARS` on the Python
    /// side).
    #[serde(default = "default_min_calendars")]
    min_calendars: u32,
    /// Filesystem path the OTS receipt will be persisted to. Only
    /// used by `ots_cli` — `mock_*` transports ignore this.
    #[serde(default)]
    target_dir: Option<String>,
}

fn default_min_calendars() -> u32 {
    2
}

/// JSON shape emitted on stdout. Mirrors `SubmitResult` but flattens
/// the enum into a tagged struct so the Python side can deserialise
/// with a stable shape regardless of which variant fired.
#[derive(Debug, Serialize)]
struct BridgeOutput {
    /// One of `success` / `throttled` / `retrying` / `dead` / `idle`.
    result_kind: String,
    /// Envelope `event_id` (echoed for caller correlation).
    event_id: String,
    /// Populated only when `result_kind == "retrying"`.
    attempt: Option<u32>,
    /// Populated only when `result_kind == "retrying"`. Seconds.
    next_delay_secs: Option<u64>,
    /// Populated only when `result_kind == "dead"`.
    terminal_error: Option<String>,
    /// Populated when the `ots_cli` transport actually invoked
    /// `ots stamp` and produced a receipt path. Echoed for the Python
    /// side so the legacy `AnchorReceipt.receipt_path` field stays
    /// populated.
    receipt_path: Option<String>,
}

// ---------------------------------------------------------------------------
// Transport implementations.
// ---------------------------------------------------------------------------

/// Production transport: invokes the `ots stamp` CLI for one envelope.
///
/// The submit-worker FSM owns the rate-limit / retry / dead-letter
/// discipline; this transport only implements one round-trip.
#[derive(Debug)]
struct OtsCliTransport {
    calendars: Vec<String>,
    min_calendars: u32,
    payload_root_hex: String,
    target_dir: Option<String>,
    /// Set by `submit()` so the calling main() can include it in the
    /// `BridgeOutput.receipt_path` field.
    receipt_path: std::sync::Mutex<Option<String>>,
}

impl OtsCliTransport {
    fn new(input: &BridgeInput) -> Self {
        Self {
            calendars: input.calendars.clone(),
            min_calendars: input.min_calendars,
            payload_root_hex: input.payload_root_hex.clone(),
            target_dir: input.target_dir.clone(),
            receipt_path: std::sync::Mutex::new(None),
        }
    }

    fn captured_receipt_path(&self) -> Option<String> {
        self.receipt_path.lock().unwrap().clone()
    }
}

#[async_trait]
impl SubmitTransport for OtsCliTransport {
    async fn submit(&self, _envelope: &AnchorEnvelope) -> TransportOutcome {
        // 1. Materialise the root as `root.bin` in the target dir.
        let target = match &self.target_dir {
            Some(p) => std::path::PathBuf::from(p),
            None => {
                return TransportOutcome::Permanent(
                    "ots_cli transport requires target_dir input".to_string(),
                )
            }
        };
        if let Err(e) = std::fs::create_dir_all(&target) {
            return TransportOutcome::Retriable(format!(
                "failed to create target_dir {}: {}",
                target.display(),
                e
            ));
        }

        let root_bytes = match hex::decode(&self.payload_root_hex) {
            Ok(b) => b,
            Err(e) => {
                return TransportOutcome::Permanent(format!(
                    "payload_root_hex decode failed: {}",
                    e
                ))
            }
        };
        if root_bytes.len() != 32 {
            return TransportOutcome::Permanent(format!(
                "payload_root expected 32 bytes, got {}",
                root_bytes.len()
            ));
        }
        let root_path = target.join("root.bin");
        if let Err(e) = std::fs::write(&root_path, &root_bytes) {
            return TransportOutcome::Retriable(format!(
                "failed to write root.bin: {}",
                e
            ));
        }

        // 2. Build the `ots stamp` argv.
        let ots_binary = match which_ots() {
            Some(p) => p,
            None => {
                return TransportOutcome::Permanent(
                    "ots binary not on PATH; install opentimestamps-client"
                        .to_string(),
                )
            }
        };
        let mut argv: Vec<String> = vec![
            "stamp".to_string(),
            "-m".to_string(),
            self.min_calendars.to_string(),
        ];
        for url in &self.calendars {
            argv.push("--calendar".to_string());
            argv.push(url.clone());
        }
        argv.push(root_path.display().to_string());

        // 3. Spawn synchronously inside a blocking task; the worker
        //    serialises calls and we are inside an `async fn`, so we
        //    don't want to block the runtime thread.
        let result = tokio::task::spawn_blocking(move || {
            std::process::Command::new(ots_binary)
                .args(&argv)
                .output()
        })
        .await;

        let output = match result {
            Ok(Ok(o)) => o,
            Ok(Err(e)) => {
                return TransportOutcome::Retriable(format!("ots spawn failed: {}", e))
            }
            Err(e) => {
                return TransportOutcome::Retriable(format!(
                    "ots blocking task join failed: {}",
                    e
                ))
            }
        };

        // 4. Translate exit code into outcome. 0 -> Accepted; non-zero
        //    where stderr looks transient -> Retriable; else Permanent.
        if output.status.success() {
            // Try to capture the receipt path the CLI produced. OTS
            // writes `<root>.ots` next to the root file by default.
            let receipt_candidate = root_path.with_extension("bin.ots");
            if receipt_candidate.exists() {
                *self.receipt_path.lock().unwrap() =
                    Some(receipt_candidate.display().to_string());
            }
            return TransportOutcome::Accepted;
        }
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let blob = format!("{}\n{}", stdout, stderr).to_lowercase();
        let transient = blob.contains("timeout")
            || blob.contains("refused")
            || blob.contains("temporarily")
            || blob.contains("503")
            || blob.contains("502")
            || blob.contains("504")
            || blob.contains("network");
        if transient {
            TransportOutcome::Retriable(format!(
                "ots stamp transient failure: exit={:?} stderr={}",
                output.status.code(),
                stderr.trim()
            ))
        } else {
            TransportOutcome::Permanent(format!(
                "ots stamp permanent failure: exit={:?} stderr={}",
                output.status.code(),
                stderr.trim()
            ))
        }
    }
}

fn which_ots() -> Option<std::path::PathBuf> {
    let path_var = env::var_os("PATH")?;
    for dir in env::split_paths(&path_var) {
        let candidate = dir.join("ots");
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Hermetic mock transport. Returns a fixed `TransportOutcome` per
/// `WAKIR_SUBMIT_WORKER_TRANSPORT` selection.
#[derive(Debug)]
struct MockTransport {
    outcome: TransportOutcome,
}

#[async_trait]
impl SubmitTransport for MockTransport {
    async fn submit(&self, _envelope: &AnchorEnvelope) -> TransportOutcome {
        self.outcome.clone()
    }
}

// ---------------------------------------------------------------------------
// Real-time RNG (jitter source).
// ---------------------------------------------------------------------------

/// Minimal RNG impl backed by a simple xorshift seeded from the system
/// time. The submit-worker's full-jitter backoff only needs an
/// integer-bounded draw; we deliberately do not pull `rand` for this.
#[derive(Debug)]
struct SystemRng {
    state: std::sync::Mutex<u64>,
}

impl SystemRng {
    fn new() -> Self {
        let seed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0x9E3779B97F4A7C15);
        Self {
            state: std::sync::Mutex::new(seed | 1), // non-zero
        }
    }
}

impl Rng for SystemRng {
    fn gen_range_secs(&self, upper_inclusive: u64) -> u64 {
        if upper_inclusive == 0 {
            return 0;
        }
        let mut s = self.state.lock().unwrap();
        let mut x = *s;
        // xorshift64.
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        *s = x;
        x % (upper_inclusive + 1)
    }
}

// ---------------------------------------------------------------------------
// main.
// ---------------------------------------------------------------------------

fn main() -> ExitCode {
    // 1. Read stdin (single JSON object).
    let mut buf = String::new();
    if let Err(e) = io::stdin().read_to_string(&mut buf) {
        eprintln!("submit_worker: failed to read stdin: {}", e);
        return ExitCode::from(2);
    }
    let input: BridgeInput = match serde_json::from_str(&buf) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("submit_worker: input JSON parse failed: {}", e);
            return ExitCode::from(2);
        }
    };

    // 2. Build the AnchorEnvelope. The submit-worker only uses
    //    event_id / persona_id internally; the payload bytes are a
    //    parity-marker (the actual root bytes travel via the transport
    //    fields).
    let envelope = AnchorEnvelope {
        event_id: input.event_id.clone(),
        timestamp_utc: input.timestamp_utc.clone(),
        persona_id: input.persona_id.clone(),
        payload_jcs_bytes: input.payload_root_hex.clone().into_bytes(),
    };

    // 3. Pick the transport.
    let transport_kind =
        env::var(ENV_TRANSPORT).unwrap_or_else(|_| DEFAULT_TRANSPORT.to_string());
    // Keep an Arc-clone of the OtsCliTransport so we can read the
    // receipt-path after `tick()` returns.
    let (transport, ots_handle): (Arc<dyn SubmitTransport>, Option<Arc<OtsCliTransport>>) =
        match transport_kind.as_str() {
            "ots_cli" => {
                if which_ots().is_none() {
                    eprintln!(
                        "submit_worker: ots binary not on PATH (transport=ots_cli); \
                         install opentimestamps-client or select a mock transport"
                    );
                    return ExitCode::from(3);
                }
                let inner = Arc::new(OtsCliTransport::new(&input));
                (inner.clone() as Arc<dyn SubmitTransport>, Some(inner))
            }
            "mock_accept" => (
                Arc::new(MockTransport {
                    outcome: TransportOutcome::Accepted,
                }),
                None,
            ),
            "mock_retriable" => (
                Arc::new(MockTransport {
                    outcome: TransportOutcome::Retriable(
                        "mock_retriable transport".to_string(),
                    ),
                }),
                None,
            ),
            "mock_permanent" => (
                Arc::new(MockTransport {
                    outcome: TransportOutcome::Permanent(
                        "mock_permanent transport".to_string(),
                    ),
                }),
                None,
            ),
            other => {
                eprintln!(
                    "submit_worker: unknown {}={:?}; expected one of \
                     ots_cli / mock_accept / mock_retriable / mock_permanent",
                    ENV_TRANSPORT, other
                );
                return ExitCode::from(2);
            }
        };

    // 4. Build the worker. Production config from env; single-shot
    //    semantics (we only call tick() once, so the queue is
    //    transient).
    let config = SubmitWorkerConfig::from_env();
    let dead_letter: Arc<dyn persona_engine_anchor_submit_worker::DeadLetterStore> =
        Arc::new(InMemoryDeadLetterStore::new());
    let writeback: Arc<dyn persona_engine_anchor_submit_worker::WriteBackSink> =
        Arc::new(NoopWriteBackSink);
    let clock: Arc<dyn Clock> = Arc::new(SystemClock);
    let rng: Arc<dyn Rng> = Arc::new(SystemRng::new());
    let worker = SubmitWorker::new(
        config,
        transport.clone(),
        dead_letter,
        writeback,
        clock,
        rng,
    );

    // 5. Run the tick on a single-threaded tokio runtime.
    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(r) => r,
        Err(e) => {
            eprintln!("submit_worker: tokio runtime build failed: {}", e);
            return ExitCode::from(3);
        }
    };
    let result = rt.block_on(async {
        worker.enqueue(envelope.clone()).await;
        worker.tick().await
    });

    // 6. Translate to BridgeOutput.
    let receipt_path = ots_handle.as_ref().and_then(|h| h.captured_receipt_path());
    let (output, exit) = match result {
        SubmitResult::Success { event_id } => (
            BridgeOutput {
                result_kind: "success".to_string(),
                event_id,
                attempt: None,
                next_delay_secs: None,
                terminal_error: None,
                receipt_path,
            },
            ExitCode::from(0),
        ),
        SubmitResult::Throttled { event_id } => (
            BridgeOutput {
                result_kind: "throttled".to_string(),
                event_id,
                attempt: None,
                next_delay_secs: None,
                terminal_error: None,
                receipt_path: None,
            },
            ExitCode::from(0),
        ),
        SubmitResult::Retrying {
            event_id,
            attempt,
            next_delay,
        } => (
            BridgeOutput {
                result_kind: "retrying".to_string(),
                event_id,
                attempt: Some(attempt),
                next_delay_secs: Some(next_delay.as_secs()),
                terminal_error: None,
                receipt_path: None,
            },
            ExitCode::from(0),
        ),
        SubmitResult::Dead {
            event_id,
            terminal_error,
        } => (
            BridgeOutput {
                result_kind: "dead".to_string(),
                event_id,
                attempt: None,
                next_delay_secs: None,
                terminal_error: Some(terminal_error),
                receipt_path: None,
            },
            ExitCode::from(1),
        ),
        SubmitResult::Idle => (
            BridgeOutput {
                result_kind: "idle".to_string(),
                event_id: envelope.event_id.clone(),
                attempt: None,
                next_delay_secs: None,
                terminal_error: None,
                receipt_path: None,
            },
            ExitCode::from(0),
        ),
    };

    let json = match serde_json::to_string(&output) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("submit_worker: output JSON encode failed: {}", e);
            return ExitCode::from(3);
        }
    };
    let mut stdout = io::stdout().lock();
    if let Err(e) = writeln!(stdout, "{}", json) {
        eprintln!("submit_worker: stdout write failed: {}", e);
        return ExitCode::from(3);
    }
    exit
}
