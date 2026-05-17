// SPDX-License-Identifier: Apache-2.0
//! SPIFFE Workload-API probe — Rust pendant.
//!
//! Rust pendant of
//! `wirelang.persona_engine.svid_workload_identity.probe_workload_api_socket`
//! (Python). Mirrors the v0.2.0-pilot socket-presence probe semantics
//! preserved by Sprint-Pengine-9 (`connect()`-on-UDS, no protocol
//! exchange) — the boot-gate path that fails fast on a missing
//! SPIRE-Agent before the full gRPC `FetchX509SVID` RPC is attempted.
//!
//! Layer position
//! --------------
//!
//! Engine-side, Zone-L surface. The SPIRE-Agent listens on a Unix
//! domain socket bind-mounted into the persona-container at
//! `/run/spire/agent-sockets/api.sock` (Quadlet
//! `wakir-spire-agent-sockets.volume`). This crate is the Rust
//! pendant slot ADR-0066 Welle-2 cuts over to once shipping.
//!
//! Skeleton scope (Tag-29 Mini-Welle)
//! ----------------------------------
//!
//! This crate ships the **socket-presence probe** and the operator
//! info banner. The full Workload-API gRPC `FetchX509SVID` RPC is
//! intentionally out-of-scope for the image-build pipeline pre-
//! shipping — Tonic/grpcio substrate is substantially larger than
//! the probe surface and warrants its own Zone-L cross-review
//! pass. The CLI `probe` subcommand is sufficient to flip the
//! Welle-2 backend-decision from `binary_missing` to `binary_present`
//! and to give the boot-gate path a Rust pendant.
//!
//! Determinism contract
//! --------------------
//!
//! The probe is deterministic against socket-presence + connect()
//! result:
//!
//!   - socket path missing                  -> `ProbeOutcome::SocketMissing`
//!   - socket path present, connect() OK    -> `ProbeOutcome::Reachable`
//!   - socket path present, connect() fails -> `ProbeOutcome::ConnectFailed(io::Error)`
//!
//! The CLI maps these to exit codes 2 / 0 / 3 respectively (see
//! `src/main.rs`).
//!
//! Cross-references
//! ----------------
//!
//! - ADR-0066 §Phase-3c Welle-2 `svid_workload_identity` —
//!   Welle-2 pre-cutover image-build (Tag-29 Mini-Welle).
//! - `wirelang/persona_engine/svid_workload_identity.py` —
//!   Python authority; preserves the same `connect()`-on-UDS
//!   semantics in `probe_workload_api_socket`.
//! - Zone-L cross-review — Reza owns the SPIFFE-ID + cert
//!   semantics; the probe surface is shape-neutral wrt SPIFFE-ID.

use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

/// Default Workload-API Unix socket path inside the persona-container.
///
/// Matches the Quadlet
/// `Volume=wakir-spire-agent-sockets.volume:/run/spire/agent-sockets`
/// bind-mount target and the Python
/// `DEFAULT_WORKLOAD_API_SOCKET_PATH` constant byte-for-byte.
pub const DEFAULT_WORKLOAD_API_SOCKET_PATH: &str =
    "/run/spire/agent-sockets/api.sock";

/// Default connect-timeout for the probe. Matches the Python
/// `DEFAULT_PROBE_TIMEOUT_SECONDS = 2.0` constant. The probe is a
/// boot-gate path; 2 seconds is generous for a local UDS and short
/// enough that a missing peer fails fast.
pub const DEFAULT_PROBE_TIMEOUT: Duration = Duration::from_secs(2);

/// Outcome of a socket-presence probe.
///
/// The three variants map onto the three observable states of a
/// SPIRE-Agent UDS:
///
/// - `SocketMissing` — the path does not exist on the filesystem.
///   Usual cause: the SPIRE-Agent Quadlet did not start, or the
///   bind-mount is wrong.
/// - `Reachable` — `connect()` succeeded; the agent is accepting
///   connections. No protocol exchange is performed.
/// - `ConnectFailed` — the path exists but `connect()` failed.
///   Usual causes: permission denied, peer not listening, EACCES
///   from SELinux.
#[derive(Debug)]
pub enum ProbeOutcome {
    /// Socket path does not exist.
    SocketMissing,
    /// Socket exists and `connect()` succeeded.
    Reachable,
    /// Socket exists but `connect()` failed; the inner error is the
    /// underlying `io::Error`.
    ConnectFailed(std::io::Error),
}

impl ProbeOutcome {
    /// CLI exit-code mapping (parity with the Python authority's
    /// `__main__` exit-code contract).
    ///
    ///   - `Reachable`      -> 0
    ///   - `SocketMissing`  -> 2
    ///   - `ConnectFailed`  -> 3
    pub fn exit_code(&self) -> u8 {
        match self {
            ProbeOutcome::Reachable => 0,
            ProbeOutcome::SocketMissing => 2,
            ProbeOutcome::ConnectFailed(_) => 3,
        }
    }

    /// Operator-friendly one-line summary.
    pub fn summary(&self, socket_path: &str) -> String {
        match self {
            ProbeOutcome::Reachable => format!("OK reachable {socket_path}"),
            ProbeOutcome::SocketMissing => {
                format!("MISSING socket-not-found {socket_path}")
            }
            ProbeOutcome::ConnectFailed(err) => {
                format!("UNREACHABLE connect-failed {socket_path}: {err}")
            }
        }
    }
}

/// Probe a SPIFFE Workload-API socket for presence + reachability.
///
/// Performs a two-step check:
///
///   1. `Path::exists()` on the socket path. If absent, return
///      `ProbeOutcome::SocketMissing` immediately.
///   2. `UnixStream::connect()` against the socket path. On success,
///      return `ProbeOutcome::Reachable`; on `io::Error`, return
///      `ProbeOutcome::ConnectFailed(err)`.
///
/// The socket is NOT held open beyond the probe — the `UnixStream`
/// is dropped before the function returns, releasing the file
/// descriptor.
///
/// Mirrors Python `probe_workload_api_socket` byte-for-byte in the
/// observable-effect dimension (the side-effect on the SPIRE-Agent
/// is the same `accept()` enqueue + immediate close).
pub fn probe_workload_api_socket<P: AsRef<Path>>(socket_path: P) -> ProbeOutcome {
    let path = socket_path.as_ref();
    if !path.exists() {
        return ProbeOutcome::SocketMissing;
    }
    match UnixStream::connect(path) {
        Ok(_stream) => {
            // Stream dropped at end of scope; FD released.
            ProbeOutcome::Reachable
        }
        Err(err) => ProbeOutcome::ConnectFailed(err),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_socket_returns_socket_missing() {
        let outcome = probe_workload_api_socket(
            "/nonexistent/path/to/spire/agent/socket.sock",
        );
        assert!(matches!(outcome, ProbeOutcome::SocketMissing));
        assert_eq!(outcome.exit_code(), 2);
    }

    #[test]
    fn outcome_summary_contains_socket_path() {
        let outcome = ProbeOutcome::SocketMissing;
        let summary = outcome.summary("/tmp/x.sock");
        assert!(summary.contains("/tmp/x.sock"));
        assert!(summary.starts_with("MISSING"));
    }

    #[test]
    fn reachable_exit_code_is_zero() {
        assert_eq!(ProbeOutcome::Reachable.exit_code(), 0);
    }

    #[test]
    fn default_socket_path_matches_quadlet_contract() {
        assert_eq!(
            DEFAULT_WORKLOAD_API_SOCKET_PATH,
            "/run/spire/agent-sockets/api.sock"
        );
    }

    #[test]
    fn default_probe_timeout_is_two_seconds() {
        assert_eq!(DEFAULT_PROBE_TIMEOUT, Duration::from_secs(2));
    }
}
