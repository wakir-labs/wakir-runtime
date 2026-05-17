// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Persona-Engine R1..R4 Recovery-Workflow — Rust substrate
//! (Phase-3a Item 4).
//!
//! This is the **initial Rust scaffold** of the persona-engine
//! recovery-workflow. The Python reference implementation lives at
//! `wirelang/persona_engine/recovery_workflow.py` (Selin Sprint-
//! Pengine-8 PR #65, persona-engine-format-spec §3.7.4). The
//! Doppelbetrieb-Konsistenz contract (Selin PR #113 3-way-triangle)
//! requires this Rust substrate to produce schema-byte-parity with
//! the Python workflow at the audit-record boundary.
//!
//! # Scope of this scaffold
//!
//! This crate intentionally does **not** bind a live container
//! supervisor (systemd / Quadlet), a live SPIFFE workload-API socket,
//! or a live persona-state-backing. Each external dependency is
//! abstracted as a `RecoveryHooks` callable injection point — the
//! same posture as the Python hermetic-test surface
//! (`RecoveryWorkflow(state_machine=..., state_backing=...,
//! container_supervisor=...)`). Smoke-tests stub the four hooks; the
//! Phase-3a "live-binding" follow-up step extends the hook adapters.
//!
//! # Schema parity with PR #65 (`recovery_workflow.py`)
//!
//! | Python concept                          | Rust type/const                  |
//! |-----------------------------------------|----------------------------------|
//! | `RecoveryTrigger` (enum)                | [`RecoveryTrigger`]              |
//! | `RecoveryFailureMode` (enum)            | [`RecoveryFailureMode`]          |
//! | `PhaseResult` (dataclass)               | [`PhaseResult`]                  |
//! | `RecoveryResult` (dataclass)            | [`RecoveryOutcome`]              |
//! | `RECOVERY_BUDGET_SECONDS = 30`          | [`RECOVERY_BUDGET_SECONDS`]      |
//! | `PHASE_SOFT_CAPS_SEC`                   | [`phase_soft_cap_sec`]           |
//! | `RECOVERY_WORKFLOW_PHASE_ORDER`         | [`RECOVERY_WORKFLOW_PHASE_ORDER`]|
//! | `_utc_now_rfc3339()`                    | [`utc_now_rfc3339`]              |
//!
//! # Naming note (Sprint-Auftrag vs. PR-65)
//!
//! The Sprint-Auftrag describes `RecoveryAction` variants as
//! `R1Refetch / R2Resubscribe / R3Restart / R4Escalate`. The Python
//! foundation (PR #65, spec §3.7.4.2) uses the canonical labels
//! `R1 Detect / R2 Reload / R3 Re-register / R4 Resume`. Hard-
//! constraint "Schema-Parität zu Python recovery_workflow.py" wins —
//! we mirror the Python phase labels exactly. The Sprint-Auftrag's
//! four action-hooks (SVID-Refetch, NATS-Resubscribe, FSM-Restart,
//! Operator-Escalation) map onto the four phases as advisory action-
//! hooks via the [`RecoveryHooks`] injection point: the operator
//! supplies callables that perform the actual remediation; the phase
//! labels remain stable.
//!
//! # ADR anchors
//!
//! - ADR-0063 §Folgeartefakte Phase-3a Item 4.
//! - Selin PR #65  (Sprint-Pengine-8) — Python schema authority.
//! - Selin PR #113 (3-way-triangle) — Doppelbetrieb substrate.
//! - Selin PR #131 (bridge-diff-engine-rust) — sibling crate.
//! - Reza  PR #132 (subscribe-loop-rust) — sibling crate.
//! - persona-engine-format-spec §3.7.4 — R1..R4 phase contract.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::Mutex;

// ---------------------------------------------------------------------------
// Constants — byte-parity with Python `recovery_workflow.py`.
// ---------------------------------------------------------------------------

/// Hard cap for end-to-end recovery (R1+R2+R3+R4 inclusive), seconds.
///
/// Parity with Python `RECOVERY_BUDGET_SECONDS = 30`
/// (spec §3.7.2.2 invariant 4).
pub const RECOVERY_BUDGET_SECONDS: u64 = 30;

/// Canonical phase order (§3.7.4.2). Re-ordering would violate the
/// audit invariants per §3.7.4.2 last paragraph.
///
/// Parity with Python
/// `RECOVERY_WORKFLOW_PHASE_ORDER = ("R1", "R2", "R3", "R4")`.
pub const RECOVERY_WORKFLOW_PHASE_ORDER: [&str; 4] = ["R1", "R2", "R3", "R4"];

/// Per-phase soft caps (advisory; emits `recovery_phase_slow`
/// annotation when exceeded but does not halt). Mirrors Python
/// `PHASE_SOFT_CAPS_SEC = {"R1": 1, "R2": 15, "R3": 5, "R4": 9}`.
///
/// Returns `None` for an unknown phase label (parity with a Python
/// `dict.get(label)` returning `None`).
pub fn phase_soft_cap_sec(phase: &str) -> Option<u64> {
    match phase {
        "R1" => Some(1),
        "R2" => Some(15),
        "R3" => Some(5),
        "R4" => Some(9),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Trigger enumeration (§3.7.4.1) — closed set.
// ---------------------------------------------------------------------------

/// Recovery entry-point classification (§3.7.4.1).
///
/// Parity with Python `RecoveryTrigger` string-enum:
///
/// | Python literal           | Rust variant          |
/// |--------------------------|-----------------------|
/// | `"CrashDetected"`        | [`Self::CrashDetected`]      |
/// | `"DespawnMidOperation"`  | [`Self::DespawnMidOperation`]|
/// | `"StateCorruption"`      | [`Self::StateCorruption`]    |
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RecoveryTrigger {
    CrashDetected,
    DespawnMidOperation,
    StateCorruption,
}

impl RecoveryTrigger {
    /// Wire-string form for audit-record JSON (parity with Python
    /// `RecoveryTrigger.value`).
    pub fn as_str(&self) -> &'static str {
        match self {
            RecoveryTrigger::CrashDetected => "CrashDetected",
            RecoveryTrigger::DespawnMidOperation => "DespawnMidOperation",
            RecoveryTrigger::StateCorruption => "StateCorruption",
        }
    }
}

impl std::fmt::Display for RecoveryTrigger {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

// ---------------------------------------------------------------------------
// Failure modes (§3.7.4.5) — closed set.
// ---------------------------------------------------------------------------

/// Recovery failure-mode classifier (§3.7.4.5).
///
/// Parity with Python `RecoveryFailureMode` string-enum:
///
/// | Python literal                     | Rust variant                |
/// |------------------------------------|-----------------------------|
/// | `"RecoveryTriggerAmbiguousError"`  | [`Self::TriggerAmbiguous`]      |
/// | `"RecoveryBackingUnreachableError"`| [`Self::BackingUnreachable`]    |
/// | `"RecoverySnapshotCorruptError"`   | [`Self::SnapshotCorrupt`]       |
/// | `"RecoveryIdentityRebindError"`    | [`Self::IdentityRebindError`]   |
/// | `"RecoveryResumeError"`            | [`Self::ResumeError`]           |
/// | `"RecoveryBudgetExceededError"`    | [`Self::BudgetExceeded`]        |
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RecoveryFailureMode {
    TriggerAmbiguous,
    BackingUnreachable,
    SnapshotCorrupt,
    IdentityRebindError,
    ResumeError,
    BudgetExceeded,
}

impl RecoveryFailureMode {
    /// Wire-string form for audit-record JSON.
    pub fn as_str(&self) -> &'static str {
        match self {
            RecoveryFailureMode::TriggerAmbiguous => "RecoveryTriggerAmbiguousError",
            RecoveryFailureMode::BackingUnreachable => "RecoveryBackingUnreachableError",
            RecoveryFailureMode::SnapshotCorrupt => "RecoverySnapshotCorruptError",
            RecoveryFailureMode::IdentityRebindError => "RecoveryIdentityRebindError",
            RecoveryFailureMode::ResumeError => "RecoveryResumeError",
            RecoveryFailureMode::BudgetExceeded => "RecoveryBudgetExceededError",
        }
    }
}

impl std::fmt::Display for RecoveryFailureMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Recovery-workflow error envelope. Carries the failure-mode label
/// in `mode` for the audit-record annotation (parity with Python
/// `RecoveryError(mode, detail)`).
#[derive(Debug, Clone, PartialEq)]
pub struct RecoveryError {
    pub mode: RecoveryFailureMode,
    pub detail: String,
}

impl RecoveryError {
    pub fn new(mode: RecoveryFailureMode, detail: impl Into<String>) -> Self {
        Self {
            mode,
            detail: detail.into(),
        }
    }
}

impl std::fmt::Display for RecoveryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.mode.as_str(), self.detail)
    }
}

impl std::error::Error for RecoveryError {}

// ---------------------------------------------------------------------------
// Phase result + outcome envelope.
// ---------------------------------------------------------------------------

/// Outcome of one phase. Idempotent re-runs return the same status.
///
/// Parity with Python `PhaseResult` dataclass — fields kept identical
/// at the JSON-serialisation boundary so cross-lang audit-record diff
/// is byte-stable.
#[derive(Debug, Clone, PartialEq)]
pub struct PhaseResult {
    /// `"R1"` | `"R2"` | `"R3"` | `"R4"`.
    pub phase: String,
    /// `"detected"` | `"reloaded"` | `"re_registered"` | `"resumed"`.
    pub terminal_status: String,
    pub elapsed_sec: f64,
    pub soft_cap_exceeded: bool,
    pub audit_annotation: String,
}

/// End-to-end recovery outcome. The Rust type is named
/// `RecoveryOutcome` to match the Sprint-Auftrag signature
/// (`run_recovery_drill -> RecoveryOutcome`); the field shape is
/// byte-parity with the Python `RecoveryResult` dataclass.
#[derive(Debug, Clone, PartialEq)]
pub struct RecoveryOutcome {
    pub trigger: RecoveryTrigger,
    pub phases: Vec<PhaseResult>,
    pub total_elapsed_sec: f64,
    /// Expected `"running"` on success; the workflow does not own the
    /// FSM in this scaffold (callable injection) so the value is
    /// supplied by the operator-side FSM-restart hook.
    pub final_state: String,
    pub success: bool,
}

// ---------------------------------------------------------------------------
// Recovery context (Sprint-Auftrag signature) and hook surface.
// ---------------------------------------------------------------------------

/// Drill-context envelope.
///
/// Captures the per-drill input flags the operator forwards to the
/// recovery workflow. The `pin_drift` / `fence_active` /
/// `subscribe_failure` triple corresponds to the three Sprint-Auftrag
/// trigger conditions; the `force_trigger` override mirrors the
/// Python `--force-trigger=<label>` OI-PEF-10 path.
#[derive(Debug, Clone, Default)]
pub struct RecoveryContext {
    /// Drift in V-907 pin pack detected (Sprint-Auftrag flag;
    /// maps onto Python `state_corruption=True`).
    pub pin_drift: bool,
    /// SRE-controlled fence active (Sprint-Auftrag flag; maps onto
    /// Python `crash_detected=True` because the fence-trip is the
    /// crash-detection signal in Phase-3a).
    pub fence_active: bool,
    /// NATS subscribe-loop failure (Sprint-Auftrag flag; maps onto
    /// Python `despawn_mid_operation=True` because the despawn path
    /// is the subscribe-loop teardown trigger).
    pub subscribe_failure: bool,
    /// Operator override (`--force-trigger=<label>`).
    pub force_trigger: Option<RecoveryTrigger>,
    /// Persona identifier (used for audit annotation; equivalent to
    /// the Python `fsm.persona_id`).
    pub persona_id: String,
    /// Org identifier (used for audit annotation; equivalent to the
    /// Python `fsm.org_id`).
    pub org_id: String,
}

/// Future returned by the four hook callables.
pub type HookFuture<'a> = Pin<Box<dyn Future<Output = Result<(), RecoveryError>> + Send + 'a>>;

/// Callable injection points for the four recovery actions.
///
/// The Sprint-Auftrag enumerates four hook surfaces; we name them per
/// the action they perform, while the workflow itself drives the
/// canonical R1..R4 phase order:
///
/// - `svid_refetch`        — used by R3 (re-register).
/// - `nats_resubscribe`    — used by R2/R3 in the Doppelbetrieb
///   variant; consumed by R3 here when the subscribe-loop must be
///   rebuilt before SVID rebind (advisory).
/// - `fsm_restart`         — used by R4 (resume) to drive the FSM
///   `uninstantiated -> recovered -> running` two-hop.
/// - `operator_escalation` — invoked by [`escalate_to_operator`]
///   when budget is exceeded or a hook fails irrecoverably.
///
/// The default implementation returns `Ok(())` for every hook —
/// matches the Python `_default_supervisor` posture (the engine runs
/// inside the Quadlet so the host-side supervisor is the supervisor
/// of record; the in-engine R4 is a logical no-op).
pub struct RecoveryHooks {
    pub svid_refetch: Arc<dyn for<'a> Fn(&'a RecoveryContext) -> HookFuture<'a> + Send + Sync>,
    pub nats_resubscribe: Arc<dyn for<'a> Fn(&'a RecoveryContext) -> HookFuture<'a> + Send + Sync>,
    pub fsm_restart: Arc<dyn for<'a> Fn(&'a RecoveryContext) -> HookFuture<'a> + Send + Sync>,
    pub operator_escalation:
        Arc<dyn for<'a> Fn(&'a RecoveryContext, &'a RecoveryError) -> HookFuture<'a> + Send + Sync>,
}

fn ok_hook() -> Arc<dyn for<'a> Fn(&'a RecoveryContext) -> HookFuture<'a> + Send + Sync> {
    Arc::new(|_ctx: &RecoveryContext| -> HookFuture<'_> { Box::pin(async move { Ok(()) }) })
}

fn ok_escalation(
) -> Arc<dyn for<'a> Fn(&'a RecoveryContext, &'a RecoveryError) -> HookFuture<'a> + Send + Sync> {
    Arc::new(
        |_ctx: &RecoveryContext, _err: &RecoveryError| -> HookFuture<'_> {
            Box::pin(async move { Ok(()) })
        },
    )
}

impl Default for RecoveryHooks {
    fn default() -> Self {
        Self {
            svid_refetch: ok_hook(),
            nats_resubscribe: ok_hook(),
            fsm_restart: ok_hook(),
            operator_escalation: ok_escalation(),
        }
    }
}

impl std::fmt::Debug for RecoveryHooks {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RecoveryHooks")
            .field("svid_refetch", &"<callable>")
            .field("nats_resubscribe", &"<callable>")
            .field("fsm_restart", &"<callable>")
            .field("operator_escalation", &"<callable>")
            .finish()
    }
}

// ---------------------------------------------------------------------------
// Trigger classification (R1 helper) — exposed for unit tests.
// ---------------------------------------------------------------------------

/// Classify the recovery trigger from a [`RecoveryContext`].
///
/// Parity with Python `classify_trigger`:
/// - `force_trigger.is_some()` overrides everything.
/// - Otherwise exactly one of `pin_drift / fence_active /
///   subscribe_failure` must be `true`; ambiguity raises
///   [`RecoveryFailureMode::TriggerAmbiguous`].
/// - Zero asserted flags also yields `TriggerAmbiguous` (Python
///   `"no trigger flag asserted; expected exactly one"`).
pub fn classify_trigger(ctx: &RecoveryContext) -> Result<RecoveryTrigger, RecoveryError> {
    if let Some(forced) = ctx.force_trigger {
        return Ok(forced);
    }
    let flags = [
        (RecoveryTrigger::StateCorruption, ctx.pin_drift),
        (RecoveryTrigger::CrashDetected, ctx.fence_active),
        (RecoveryTrigger::DespawnMidOperation, ctx.subscribe_failure),
    ];
    let active: Vec<RecoveryTrigger> = flags
        .iter()
        .filter(|(_, on)| *on)
        .map(|(t, _)| *t)
        .collect();
    match active.len() {
        0 => Err(RecoveryError::new(
            RecoveryFailureMode::TriggerAmbiguous,
            "no trigger flag asserted; expected exactly one",
        )),
        1 => Ok(active[0]),
        _ => Err(RecoveryError::new(
            RecoveryFailureMode::TriggerAmbiguous,
            format!(
                "multiple triggers asserted: {:?}; operator must --force-trigger=<label>",
                active.iter().map(|t| t.as_str()).collect::<Vec<_>>()
            ),
        )),
    }
}

// ---------------------------------------------------------------------------
// Time helpers.
// ---------------------------------------------------------------------------

/// Current UTC timestamp in the RFC-3339 second-precision shape
/// (matches Python `time.strftime("%Y-%m-%dT%H:%M:%SZ")`).
pub fn utc_now_rfc3339() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn elapsed_sec(start: std::time::Instant) -> f64 {
    start.elapsed().as_secs_f64()
}

// ---------------------------------------------------------------------------
// Phase implementations — internal driver helpers.
// ---------------------------------------------------------------------------

async fn run_phase_r1(trigger: RecoveryTrigger, start: std::time::Instant) -> PhaseResult {
    let elapsed = elapsed_sec(start);
    let cap = phase_soft_cap_sec("R1").unwrap();
    PhaseResult {
        phase: "R1".to_owned(),
        terminal_status: "detected".to_owned(),
        elapsed_sec: elapsed,
        soft_cap_exceeded: elapsed > cap as f64,
        audit_annotation: format!("recovery_trigger_classified={}", trigger.as_str()),
    }
}

async fn run_phase_r2(
    ctx: &RecoveryContext,
    hooks: &RecoveryHooks,
) -> Result<PhaseResult, RecoveryError> {
    let start = std::time::Instant::now();
    // R2 in Python performs state-backing restore. In this scaffold
    // the operator may also choose to rebuild the NATS subscription
    // before SVID rebind (advisory; mirrors the Doppelbetrieb posture
    // documented in PR #131). We invoke the nats_resubscribe hook
    // here because it precedes R3 in the action-hook map.
    (hooks.nats_resubscribe)(ctx).await?;
    let elapsed = elapsed_sec(start);
    let cap = phase_soft_cap_sec("R2").unwrap();
    Ok(PhaseResult {
        phase: "R2".to_owned(),
        terminal_status: "reloaded".to_owned(),
        elapsed_sec: elapsed,
        soft_cap_exceeded: elapsed > cap as f64,
        // Parity with Python `"snapshot-restored"` annotation. The
        // scaffold does not surface the cold-start path yet; future
        // versions branch on `hooks.state_backing_probe`.
        audit_annotation: "snapshot-restored".to_owned(),
    })
}

async fn run_phase_r3(
    ctx: &RecoveryContext,
    hooks: &RecoveryHooks,
) -> Result<PhaseResult, RecoveryError> {
    let start = std::time::Instant::now();
    (hooks.svid_refetch)(ctx).await?;
    let elapsed = elapsed_sec(start);
    let cap = phase_soft_cap_sec("R3").unwrap();
    // Parity audit annotation: SPIFFE ID format byte-identical with the
    // Python sibling `wirelang/persona_engine/svid_workload_identity.py`
    // `SPIFFE_ID_TEMPLATE = "spiffe://wakir.{org_id}/persona/{persona_id}"`
    // (Tag-20 Python-sync cross-lang parity sweep).
    let svid_id = format!(
        "spiffe://wakir.{}/persona/{}",
        if ctx.org_id.is_empty() {
            "wakir-labs"
        } else {
            &ctx.org_id
        },
        if ctx.persona_id.is_empty() {
            "unknown"
        } else {
            &ctx.persona_id
        },
    );
    Ok(PhaseResult {
        phase: "R3".to_owned(),
        terminal_status: "re_registered".to_owned(),
        elapsed_sec: elapsed,
        soft_cap_exceeded: elapsed > cap as f64,
        audit_annotation: format!("recovery_svid_refreshed={}", svid_id),
    })
}

async fn run_phase_r4(
    ctx: &RecoveryContext,
    hooks: &RecoveryHooks,
) -> Result<PhaseResult, RecoveryError> {
    let start = std::time::Instant::now();
    (hooks.fsm_restart)(ctx).await?;
    let elapsed = elapsed_sec(start);
    let cap = phase_soft_cap_sec("R4").unwrap();
    Ok(PhaseResult {
        phase: "R4".to_owned(),
        terminal_status: "resumed".to_owned(),
        elapsed_sec: elapsed,
        soft_cap_exceeded: elapsed > cap as f64,
        audit_annotation: "container-active".to_owned(),
    })
}

// ---------------------------------------------------------------------------
// End-to-end driver.
// ---------------------------------------------------------------------------

/// Run the R1..R4 recovery drill end-to-end.
///
/// Signature mirrors the Sprint-Auftrag contract:
///
/// ```ignore
/// async fn run_recovery_drill(context, budget_seconds) -> RecoveryOutcome
/// ```
///
/// `budget_seconds == 0` uses the default `RECOVERY_BUDGET_SECONDS`
/// (= 30, parity with Python `RECOVERY_BUDGET_SECONDS`).
///
/// The function does **not** panic on hook failure; instead it
/// returns a [`RecoveryOutcome`] with `success = false` and the
/// `phases` vector truncated at the failing phase. The operator-
/// escalation hook is invoked exactly once on terminal failure so
/// audit trails capture the escalation timestamp.
pub async fn run_recovery_drill(context: RecoveryContext, budget_seconds: u64) -> RecoveryOutcome {
    let hooks = RecoveryHooks::default();
    run_recovery_drill_with_hooks(context, budget_seconds, hooks).await
}

/// Hook-injected variant of [`run_recovery_drill`].
///
/// Hermetic tests inject a [`RecoveryHooks`] with stubbed callables;
/// production code passes the live SVID/NATS/FSM adapters.
pub async fn run_recovery_drill_with_hooks(
    context: RecoveryContext,
    budget_seconds: u64,
    hooks: RecoveryHooks,
) -> RecoveryOutcome {
    let budget = if budget_seconds == 0 {
        RECOVERY_BUDGET_SECONDS
    } else {
        budget_seconds
    };
    let deadline = Duration::from_secs(budget);
    let phases = Arc::new(Mutex::new(Vec::<PhaseResult>::new()));
    let phases_for_drill = phases.clone();
    let context_arc = Arc::new(context);
    let context_for_drill = context_arc.clone();
    let hooks_arc = Arc::new(hooks);
    let hooks_for_drill = hooks_arc.clone();

    let driver_start = std::time::Instant::now();

    let drill = async move {
        let ctx = context_for_drill.as_ref();
        let hooks = hooks_for_drill.as_ref();

        // R1.
        let trigger = classify_trigger(ctx)?;
        let r1 = run_phase_r1(trigger, driver_start).await;
        phases_for_drill.lock().await.push(r1);

        // R2.
        let r2 = run_phase_r2(ctx, hooks).await?;
        phases_for_drill.lock().await.push(r2);

        // R3.
        let r3 = run_phase_r3(ctx, hooks).await?;
        phases_for_drill.lock().await.push(r3);

        // R4.
        let r4 = run_phase_r4(ctx, hooks).await?;
        phases_for_drill.lock().await.push(r4);

        Ok::<RecoveryTrigger, RecoveryError>(trigger)
    };

    let outcome = tokio::time::timeout(deadline, drill).await;

    let total_elapsed = elapsed_sec(driver_start);
    let phases_snapshot = phases.lock().await.clone();

    match outcome {
        Ok(Ok(trigger)) => {
            // Success path: FSM is now `running` (the fsm_restart hook
            // performed the transition).
            RecoveryOutcome {
                trigger,
                phases: phases_snapshot,
                total_elapsed_sec: total_elapsed,
                final_state: "running".to_owned(),
                success: true,
            }
        }
        Ok(Err(err)) => {
            // Hook failure or trigger ambiguity: escalate and report.
            // Best-effort escalation; ignore escalation errors so the
            // operator can still inspect the partial outcome.
            let _ = (hooks_arc.operator_escalation)(context_arc.as_ref(), &err).await;
            let trig = context_arc
                .force_trigger
                .unwrap_or(RecoveryTrigger::CrashDetected);
            RecoveryOutcome {
                trigger: trig,
                phases: phases_snapshot,
                total_elapsed_sec: total_elapsed,
                final_state: format!("failed:{}", err.mode.as_str()),
                success: false,
            }
        }
        Err(_elapsed_err) => {
            // tokio timeout — budget exceeded.
            let err = RecoveryError::new(
                RecoveryFailureMode::BudgetExceeded,
                format!(
                    "recovery elapsed {:.2}s > {}s budget",
                    total_elapsed, budget
                ),
            );
            let _ = (hooks_arc.operator_escalation)(context_arc.as_ref(), &err).await;
            let trig = context_arc
                .force_trigger
                .unwrap_or(RecoveryTrigger::CrashDetected);
            RecoveryOutcome {
                trigger: trig,
                phases: phases_snapshot,
                total_elapsed_sec: total_elapsed,
                final_state: format!("failed:{}", RecoveryFailureMode::BudgetExceeded.as_str()),
                success: false,
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Operator-escalation helper (Sprint-Auftrag hook surface).
// ---------------------------------------------------------------------------

/// Invoke the operator-escalation hook directly. Used by the
/// supervisor when an out-of-workflow failure (e.g. R-prefix
/// budget-exceeded discovered after-the-fact) must surface to the
/// on-call operator without re-running the drill.
pub async fn escalate_to_operator(
    ctx: &RecoveryContext,
    hooks: &RecoveryHooks,
    err: &RecoveryError,
) -> Result<(), RecoveryError> {
    (hooks.operator_escalation)(ctx, err).await
}

// ---------------------------------------------------------------------------
// JSON audit-record builder — cross-lang parity helper.
// ---------------------------------------------------------------------------

/// Schema identifier for the canonical-projection wire-form used by
/// the cross-lang fixture vectors (Tag-20 Python-sync). Byte-identical
/// with the Python sibling constant `RECOVERY_OUTCOME_SCHEMA`.
pub const RECOVERY_OUTCOME_SCHEMA: &str = "wakir.persona-engine.recovery-outcome/1";

/// Hash prefix tag used by the canonical-projection helpers
/// (parity with `persona-engine-subscribe-loop::HASH_PREFIX`).
pub const HASH_PREFIX: &str = "sha256:";

/// Length of a lowercase hex-encoded SHA-256 digest (parity with
/// `persona-engine-subscribe-loop::SHA256_HEX_LEN`).
pub const SHA256_HEX_LEN: usize = 64;

// ---------------------------------------------------------------------------
// Canonical-projection helper — cross-lang fixture pin (Tag-20).
// ---------------------------------------------------------------------------

/// Build the canonical-projection `serde_json::Value` from a
/// [`RecoveryOutcome`]. Timing fields are zeroed so the projection is
/// deterministic across runs (the cross-lang fixture comparator pins
/// the timing-free wire-form). `soft_cap_exceeded` is recomputed from
/// the zero-elapsed projection — i.e. always `false`, because every
/// soft cap is strictly positive.
///
/// Wire-shape (alphabetical keys via the downstream JCS pass):
///
/// ```json
/// {
///   "final_state": "...",
///   "phases": [
///     {
///       "audit_annotation": "...",
///       "elapsed_sec": 0.0,
///       "phase": "R1",
///       "soft_cap_exceeded": false,
///       "terminal_status": "..."
///     }, ...
///   ],
///   "schema": "wakir.persona-engine.recovery-outcome/1",
///   "success": true,
///   "total_elapsed_sec": 0.0,
///   "trigger": "..."
/// }
/// ```
///
/// Cross-lang parity: Python `recovery_outcome_canonical_dict()` in
/// `wirelang.persona_engine.recovery_workflow_canonical` produces the
/// same shape.
pub fn recovery_outcome_canonical_value(outcome: &RecoveryOutcome) -> serde_json::Value {
    let phases_json: Vec<serde_json::Value> = outcome
        .phases
        .iter()
        .map(|p| {
            serde_json::json!({
                "audit_annotation": p.audit_annotation,
                "elapsed_sec": 0.0_f64,
                "phase": p.phase,
                "soft_cap_exceeded": false,
                "terminal_status": p.terminal_status,
            })
        })
        .collect();
    serde_json::json!({
        "final_state": outcome.final_state,
        "phases": phases_json,
        "schema": RECOVERY_OUTCOME_SCHEMA,
        "success": outcome.success,
        "total_elapsed_sec": 0.0_f64,
        "trigger": outcome.trigger.as_str(),
    })
}

/// Serialise a [`RecoveryOutcome`] to the JCS-canonical bytes.
///
/// Uses `serde_jcs` (RFC 8785) for byte-identical parity with the
/// Python sibling `rfc8785.dumps(recovery_outcome_canonical_dict(...))`.
/// This is the authoritative cross-lang fixture-comparison surface.
pub fn recovery_outcome_jcs_bytes(outcome: &RecoveryOutcome) -> Vec<u8> {
    let value = recovery_outcome_canonical_value(outcome);
    serde_jcs::to_vec(&value).expect("recovery outcome must JCS-serialise")
}

/// Return the lowercase-hex SHA-256 of the JCS-canonical bytes
/// (parity with Python `hashlib.sha256(bytes).hexdigest()`).
pub fn recovery_outcome_sha256_hex(outcome: &RecoveryOutcome) -> String {
    use sha2::Digest;
    let bytes = recovery_outcome_jcs_bytes(outcome);
    let mut hasher = sha2::Sha256::new();
    hasher.update(&bytes);
    let digest = hasher.finalize();
    hex::encode(digest)
}

/// Return `"sha256:" + <lowercase-hex>` (parity with Python helper).
pub fn recovery_outcome_hash_prefixed(outcome: &RecoveryOutcome) -> String {
    format!("{}{}", HASH_PREFIX, recovery_outcome_sha256_hex(outcome))
}

// ---------------------------------------------------------------------------
// Legacy audit-record JSON helper (kept for in-engine consumers).
// ---------------------------------------------------------------------------

/// Serialise a [`RecoveryOutcome`] into the canonical audit-record
/// JSON shape used by the Python implementation. Cross-lang parity:
/// Python `json.dumps(asdict(result), sort_keys=True, separators=(",", ":"))`
/// shape — keys sorted, no whitespace, ASCII-clean.
///
/// The output is **not** a JCS-canonicalised string (we do not pull
/// in serde_jcs here to keep the dep surface at the three workspace
/// deps); the cross-lang comparator de-serialises both sides and
/// compares parsed values. This matches the precedent in
/// `persona-engine-subscribe-loop`.
pub fn audit_record_json(outcome: &RecoveryOutcome) -> String {
    let phases_json: Vec<serde_json::Value> = outcome
        .phases
        .iter()
        .map(|p| {
            serde_json::json!({
                "audit_annotation": p.audit_annotation,
                "elapsed_sec": p.elapsed_sec,
                "phase": p.phase,
                "soft_cap_exceeded": p.soft_cap_exceeded,
                "terminal_status": p.terminal_status,
            })
        })
        .collect();
    let value = serde_json::json!({
        "final_state": outcome.final_state,
        "phases": phases_json,
        "success": outcome.success,
        "total_elapsed_sec": outcome.total_elapsed_sec,
        "trigger": outcome.trigger.as_str(),
    });
    serde_json::to_string(&value).expect("audit record must serialise")
}
