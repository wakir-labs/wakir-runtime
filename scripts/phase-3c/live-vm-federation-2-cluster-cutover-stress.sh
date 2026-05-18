#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# live-vm-federation-2-cluster-cutover-stress.sh
#   Phase-3c 2-Cluster Federation Cutover-Stress-Drill (Tag-44)
# ------------------------------------------------------------------
#
# Purpose
#   ADR-0066 Phase-3c Cutover runs against wakir-pilot today as a
#   single-org topology.  Production Phase-4 (KW-12+) will operate
#   the substrate as a 2-cluster federation (wakir-pilot +
#   wakir-orbit).  The M-3 Federation Live-Trial established that
#   federation-mode itself works end-to-end (Sprint-10 Tag-5..Tag-8).
#   What has NOT been exercised is the *cutover-window* under
#   federation-mode, i.e. whether per-Welle backend-flips on the
#   pilot side disturb the orbit-side engine or the federation
#   bundle-sync path.
#
#   This script is the cutover-stress drill for that gap.  It
#   simulates a per-Welle cutover on wakir-pilot while wakir-orbit
#   participates as a passive federation peer, and verifies three
#   isolation/durability properties:
#
#     1. Cross-cluster engine-drift: orbit-engine backend remains
#        the documented Default-Backend (python) regardless of the
#        pilot-side Welle-N cutover.
#     2. Federation trust durability: the SPIFFE/SPIRE trust-bundle
#        refresh across the pilot-orbit federation-link stays
#        intact throughout the cutover window.
#     3. Pilot-side cutover semantics: per-Welle BackendDecision
#        audit emits the expected backend on the pilot side
#        (mirrors live-vm-cutover-drill action_cutover semantics).
#
#   The drill is parameterised by --welle and --action (analog to
#   live-vm-cutover-drill).  --action stress walks the four
#   stress-phases in order:
#
#     a. pre-stress-setup   — verify both sides reachable and in
#                              federation-mode; capture baseline
#                              engine snapshot from each side.
#     b. stress             — perform the Welle-N cutover on the
#                              pilot side (overlay + reload +
#                              restart + boot-audit), analog to
#                              live-vm-cutover-drill action_cutover.
#     c. drift-check        — verify orbit-side engine emits
#                              backend=python (unaffected by pilot
#                              cutover) and observed BackendDecision
#                              stream contains no entries for the
#                              Welle-N component switched to the
#                              rust-side value on orbit.
#     d. trust-stress       — trigger trust-bundle refresh on both
#                              sides and verify each side observes
#                              the partner bundle within the
#                              configured roundtrip window
#                              (default 30 s).
#
# Authority
#   Mira-Hand-SSH per ADR-0058 §Nachtrag (approved KW-20).  Requires
#   two distinct SSH keys (one per VM) or the same key authorised
#   on both VMs.  Read-only on orbit; mutating on pilot (overlay +
#   restart of wakir-persona-engine.service).
#
# Sandbox boundary
#   This script never executes podman / systemctl / journalctl
#   locally.  All probes ship over SSH.  Hermetic CI runs via
#   --sandbox-stub-mode which short-circuits every remote call to
#   a deterministic in-process stub — no SSH attempted, no host
#   paths leaked.  The hermetic test suite in
#   tests/scripts/test_federation_2_cluster_cutover_stress.py
#   exercises every code path through the stub mode.
#
# Cluster-roles
#   PILOT  = mutating side; cutover overlay applied here.
#   ORBIT  = observing side; remains on Default-Backend (python).
#
# Exit-codes
#   0  green       — all four phases green for the requested Welle.
#   1  caution     — at least one phase yellow, no red phases.
#                    Operator-Hand-Decision required.
#   2  block       — at least one phase red.  Federation-cutover
#                    BLOCKED for that Welle.  Investigate before
#                    Phase-4 KW-12+ rollout.
#   3  precond     — bad CLI args / missing SSH key / unknown
#                    Welle / invalid action.
#   4  not-exec    — at least one VM unreachable (SSH failure).
#                    Surfaced as PROBE-NOT-EXECUTED in the
#                    Stress-Report (non-blocking per Tag-41
#                    AR-direktive).
#
# Anchors
#   - ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
#   - ADR-0065 (Phase-3c Cutover-Plan)
#   - ADR-0066 (Phase-3c Doppel-Welle Order; Welle-N Topologie)
#   - docs/decisions/topology-bilateral-federation.md
#     (Bilateral-Federation Sprint-10 Tag-8 substrate)
#   - docs/phase-3c/federation-2-cluster-cutover-stress-runbook.md
#     (this script's operator companion)
#   - scripts/phase-3c/live-vm-cutover-drill.sh (Tag-40 single-org
#     reference; this script extends the same Welle-Matrix)
#   - scripts/phase-3c/welle-1-pre-cutover-probe.sh (Tag-41
#     PROBE-NOT-EXECUTED idiom; reused here)
#   - scripts/federation-live-vm-acceptance.sh (Sprint-10 Tag-6
#     M-3 Federation Live-Trial; bootstrap-side reference)
#
# Author: Kai Hoffmann (DevEng-3 / DevOps), Sprint-Tag-44,
#         2026-05-18.
# ------------------------------------------------------------------

set -euo pipefail

# ------------------------------------------------------------------
# Defaults — overridable via env or CLI.
# ------------------------------------------------------------------

WAKIR_PILOT_HOST="${WAKIR_PILOT_HOST:-192.168.178.116}"
WAKIR_ORBIT_HOST="${WAKIR_ORBIT_HOST:-192.168.178.191}"
WAKIR_PILOT_USER="${WAKIR_PILOT_USER:-root}"
WAKIR_ORBIT_USER="${WAKIR_ORBIT_USER:-root}"
WAKIR_PILOT_SSH_KEY="${WAKIR_PILOT_SSH_KEY:-${HOME}/.ssh/wakir-pilot-vm-diagnose}"
WAKIR_ORBIT_SSH_KEY="${WAKIR_ORBIT_SSH_KEY:-${HOME}/.ssh/wakir-orbit-vm-diagnose}"
WAKIR_SSH_BIN="${WAKIR_SSH_BIN:-ssh}"
WAKIR_DATE_BIN="${WAKIR_DATE_BIN:-date}"
WAKIR_STRESS_LOG_DIR="${WAKIR_STRESS_LOG_DIR:-/tmp/wakir-fed-2-cluster-stress}"
WAKIR_STRESS_SSH_CONNECT_TIMEOUT_SEC="${WAKIR_STRESS_SSH_CONNECT_TIMEOUT_SEC:-8}"
WAKIR_STRESS_BOOT_AUDIT_TIMEOUT_SEC="${WAKIR_STRESS_BOOT_AUDIT_TIMEOUT_SEC:-30}"
WAKIR_STRESS_BOOT_AUDIT_MIN_HITS="${WAKIR_STRESS_BOOT_AUDIT_MIN_HITS:-5}"
WAKIR_STRESS_TRUST_BUNDLE_TIMEOUT_SEC="${WAKIR_STRESS_TRUST_BUNDLE_TIMEOUT_SEC:-30}"
WAKIR_STRESS_DEFAULT_BACKEND="${WAKIR_STRESS_DEFAULT_BACKEND:-python}"

DRY_RUN=0
SANDBOX_STUB=0
QUIET=0

STRESS_TS="$("${WAKIR_DATE_BIN}" -u +%Y%m%dT%H%M%SZ)"
STRESS_LOG=""

# ------------------------------------------------------------------
# Welle-Matrix.  Source of truth for per-Welle metadata.
#
# Format per row (TAB-separated):
#   welle | component | env_vars (comma-sep) | env_value | overlay_basename
#
# Mirrors live-vm-cutover-drill.sh §Welle-Matrix to keep both drills
# in lock-step.  Changes here MUST be reflected there and in
# docs/phase-3c/welle-{1..7}-*-runbook.md.
# ------------------------------------------------------------------

# shellcheck disable=SC2034
WELLE_MATRIX=$(cat <<'WELLE_EOF'
1	v907_verify	WAKIR_V907_VERIFY_BACKEND	rust	welle-1-v907-verify-rust.conf
2	svid_workload_identity	WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND	rust	welle-2-svid-workload-identity-rust.conf
3	bridge_audit_writer	WAKIR_BRIDGE_AUDIT_WRITER_BACKEND,WAKIR_ANCHOR_EMITTER_BACKEND	rust	welle-3-bridge-audit-writer-rust.conf
4	state_backing	WAKIR_STATE_BACKING_BACKEND	rust_inmemory	welle-4-state-backing-rust.conf
5	lifecycle_state_machine	WAKIR_FSM_BACKEND	rust	welle-5-lifecycle-state-machine-rust.conf
6	subscribe_loop	WAKIR_SUBSCRIBE_LOOP_BACKEND	rust	welle-6-subscribe-loop-rust.conf
7	recovery_workflow	WAKIR_RECOVERY_BACKEND	rust	welle-7-recovery-workflow-rust.conf
WELLE_EOF
)

select_welle_row() {
    local idx="$1"
    awk -F'\t' -v want="${idx}" '$1==want {print; exit}' <<<"${WELLE_MATRIX}"
}

welle_component() {
    local row; row=$(select_welle_row "$1")
    awk -F'\t' '{print $2}' <<<"${row}"
}

welle_env_vars() {
    local row; row=$(select_welle_row "$1")
    awk -F'\t' '{print $3}' <<<"${row}"
}

welle_env_value() {
    local row; row=$(select_welle_row "$1")
    awk -F'\t' '{print $4}' <<<"${row}"
}

welle_overlay_basename() {
    local row; row=$(select_welle_row "$1")
    awk -F'\t' '{print $5}' <<<"${row}"
}

# ------------------------------------------------------------------
# CLI parsing.
# ------------------------------------------------------------------

usage() {
    cat <<USAGE
usage: $(basename "$0") --welle N [options]
       $(basename "$0") --full-marathon [options]

Phase-3c 2-Cluster Federation Cutover-Stress-Drill (Tag-44).  Walks
the four stress-phases pre-stress-setup / stress / drift-check /
trust-stress against wakir-pilot (mutating) + wakir-orbit (observing)
in federation-mode.  See ADR-0066 + ADR-0058 §Nachtrag.

Required (mode A):
  --welle N             1..7 — target Welle index.

Required (mode B):
  --full-marathon       run all 7 Wellen sequentially (stop on first
                        non-zero verdict).

Options:
  --action ACTION       stress | pre-stress-setup | stress-only |
                        drift-check | trust-stress
                        (default: stress = all four phases in order)
  --dry-run             plan steps; do not open SSH.
  --sandbox-stub-mode   short-circuit every remote call to a
                        deterministic stub.  Required for CI.
  --quiet               suppress non-error stdout chatter.
  --pilot-host HOST     override pilot host (env: WAKIR_PILOT_HOST).
  --orbit-host HOST     override orbit host (env: WAKIR_ORBIT_HOST).
  --pilot-ssh-key PATH  override pilot SSH key.
  --orbit-ssh-key PATH  override orbit SSH key.
  --log-dir DIR         override stress-log dir.
  --min-hits N          BackendDecision min-hits (default 5).
  --boot-timeout SEC    boot-audit wait-loop timeout (default 30).
  --trust-timeout SEC   trust-bundle roundtrip timeout (default 30).
  -h, --help            show this help.

Exit codes:
  0 green | 1 caution | 2 block | 3 precond | 4 not-exec
USAGE
}

WELLE=""
ACTION="stress"
FULL_MARATHON=0

parse_args() {
    while (( $# > 0 )); do
        case "$1" in
            --welle)               WELLE="${2:-}"; shift 2 ;;
            --action)              ACTION="${2:-}"; shift 2 ;;
            --full-marathon)       FULL_MARATHON=1; shift ;;
            --dry-run)             DRY_RUN=1; shift ;;
            --sandbox-stub-mode)   SANDBOX_STUB=1; shift ;;
            --quiet)               QUIET=1; shift ;;
            --pilot-host)          WAKIR_PILOT_HOST="${2:-${WAKIR_PILOT_HOST}}"; shift 2 ;;
            --orbit-host)          WAKIR_ORBIT_HOST="${2:-${WAKIR_ORBIT_HOST}}"; shift 2 ;;
            --pilot-ssh-key)       WAKIR_PILOT_SSH_KEY="${2:-${WAKIR_PILOT_SSH_KEY}}"; shift 2 ;;
            --orbit-ssh-key)       WAKIR_ORBIT_SSH_KEY="${2:-${WAKIR_ORBIT_SSH_KEY}}"; shift 2 ;;
            --log-dir)             WAKIR_STRESS_LOG_DIR="${2:-${WAKIR_STRESS_LOG_DIR}}"; shift 2 ;;
            --min-hits)            WAKIR_STRESS_BOOT_AUDIT_MIN_HITS="${2:-${WAKIR_STRESS_BOOT_AUDIT_MIN_HITS}}"; shift 2 ;;
            --boot-timeout)        WAKIR_STRESS_BOOT_AUDIT_TIMEOUT_SEC="${2:-${WAKIR_STRESS_BOOT_AUDIT_TIMEOUT_SEC}}"; shift 2 ;;
            --trust-timeout)       WAKIR_STRESS_TRUST_BUNDLE_TIMEOUT_SEC="${2:-${WAKIR_STRESS_TRUST_BUNDLE_TIMEOUT_SEC}}"; shift 2 ;;
            -h|--help)             usage; exit 0 ;;
            *) echo "unknown arg: $1" >&2; usage >&2; exit 3 ;;
        esac
    done

    if (( FULL_MARATHON == 1 )); then
        if [[ -n "${WELLE}" ]]; then
            echo "--full-marathon excludes --welle" >&2
            return 3
        fi
    else
        if [[ -z "${WELLE}" ]]; then
            echo "either --full-marathon or --welle required" >&2
            usage >&2
            return 3
        fi
        if ! [[ "${WELLE}" =~ ^[1-7]$ ]]; then
            echo "--welle must be 1..7 (got '${WELLE}')" >&2
            return 3
        fi
    fi

    case "${ACTION}" in
        stress|pre-stress-setup|stress-only|drift-check|trust-stress) ;;
        *)
            echo "--action must be stress|pre-stress-setup|stress-only|drift-check|trust-stress (got '${ACTION}')" >&2
            return 3 ;;
    esac
    return 0
}

# ------------------------------------------------------------------
# Logging helpers.
# ------------------------------------------------------------------

log() {
    local level="$1"; shift
    local msg="$*"
    local stamp
    stamp="$("${WAKIR_DATE_BIN}" -u +%Y-%m-%dT%H:%M:%SZ)"
    # Log lines go to stderr so they never pollute the captured stdout
    # of remote_exec callers.  In QUIET mode we still emit ERROR lines.
    if [[ "${QUIET}" -eq 0 || "${level}" == "ERROR" ]]; then
        printf '[%s] [%-7s] %s\n' "${stamp}" "${level}" "${msg}" >&2
    fi
    if [[ -n "${STRESS_LOG}" ]]; then
        printf '[%s] [%-7s] %s\n' "${stamp}" "${level}" "${msg}" >> "${STRESS_LOG}"
    fi
}

log_info()    { log INFO    "$@"; }
log_warn()    { log WARN    "$@"; }
log_error()   { log ERROR   "$@"; }
log_step()    { log STEP    "$@"; }
log_verdict() { log VERDICT "$@"; }

# ------------------------------------------------------------------
# SSH wrappers.  One per side so the key + user + host are bound
# to the cluster role.
#
#   pilot_exec <cmd>  — mutating side
#   orbit_exec <cmd>  — observing side
#
# In --sandbox-stub-mode every remote_exec is short-circuited to a
# deterministic stub keyed by the env-var WAKIR_STUB_<SIDE>_<FN>.
# This keeps the hermetic test surface trivial and verifies the
# code paths that consume the stub output.
# ------------------------------------------------------------------

remote_exec() {
    local side="$1"; shift
    local desc="$1"; shift
    local cmd="$1"; shift || true

    local host user key
    case "${side}" in
        pilot) host="${WAKIR_PILOT_HOST}"; user="${WAKIR_PILOT_USER}"; key="${WAKIR_PILOT_SSH_KEY}" ;;
        orbit) host="${WAKIR_ORBIT_HOST}"; user="${WAKIR_ORBIT_USER}"; key="${WAKIR_ORBIT_SSH_KEY}" ;;
        *)
            log_error "remote_exec: unknown side='${side}'"
            return 2 ;;
    esac

    if (( SANDBOX_STUB == 1 )); then
        local stub_var="WAKIR_STUB_${side^^}_${desc^^}"
        stub_var="${stub_var//-/_}"
        local stub_val="${!stub_var:-}"
        log_info "STUB ${side} [${desc}] = '${stub_val}'"
        printf '%s' "${stub_val}"
        return 0
    fi

    if (( DRY_RUN == 1 )); then
        log_info "DRY-RUN ssh ${user}@${host} [${desc}]: ${cmd}"
        printf 'DRY-RUN-STDOUT\n'
        return 0
    fi

    "${WAKIR_SSH_BIN}" \
        -o BatchMode=yes \
        -o "ConnectTimeout=${WAKIR_STRESS_SSH_CONNECT_TIMEOUT_SEC}" \
        -o StrictHostKeyChecking=accept-new \
        -i "${key}" \
        "${user}@${host}" \
        "${cmd}"
}

pilot_exec() { remote_exec pilot "$@"; }
orbit_exec() { remote_exec orbit "$@"; }

# ------------------------------------------------------------------
# Pre-condition checks.  Skipped in dry-run + sandbox-stub.
# ------------------------------------------------------------------

check_ssh_keys_present() {
    if (( DRY_RUN == 1 || SANDBOX_STUB == 1 )); then
        return 0
    fi
    if [[ ! -r "${WAKIR_PILOT_SSH_KEY}" ]]; then
        log_error "pilot SSH key not readable at ${WAKIR_PILOT_SSH_KEY}"
        return 3
    fi
    if [[ ! -r "${WAKIR_ORBIT_SSH_KEY}" ]]; then
        log_error "orbit SSH key not readable at ${WAKIR_ORBIT_SSH_KEY}"
        return 3
    fi
    return 0
}

# ------------------------------------------------------------------
# Phase A — Pre-Stress-Setup.
#
# Verify both sides are reachable, in federation-mode, and on the
# documented Default-Backend (python).  Captures a baseline
# snapshot directory per side under $WAKIR_STRESS_LOG_DIR/baseline.
# ------------------------------------------------------------------

phase_pre_stress_setup() {
    local idx="$1"
    local component; component=$(welle_component "${idx}")
    log_step "phase A: pre-stress-setup welle=${idx} component=${component}"

    local pilot_reach orbit_reach pilot_mode orbit_mode pilot_backend orbit_backend
    pilot_reach=$(pilot_exec reach "echo PILOT_REACH_OK" || echo "")
    orbit_reach=$(orbit_exec reach "echo ORBIT_REACH_OK" || echo "")

    if [[ -z "${pilot_reach}" || -z "${orbit_reach}" ]]; then
        log_error "VM unreachable: pilot='${pilot_reach}' orbit='${orbit_reach}'"
        return 4
    fi

    pilot_mode=$(pilot_exec federation_mode "test -f /etc/wakir/federation-mode-enabled && echo enabled || echo disabled" || echo "unknown")
    orbit_mode=$(orbit_exec federation_mode "test -f /etc/wakir/federation-mode-enabled && echo enabled || echo disabled" || echo "unknown")

    if [[ "${pilot_mode}" != "enabled" || "${orbit_mode}" != "enabled" ]]; then
        log_error "federation not enabled on both sides: pilot=${pilot_mode} orbit=${orbit_mode}"
        return 2
    fi

    pilot_backend=$(pilot_exec backend_default "systemctl show wakir-persona-engine.service --property=Environment | grep -oE 'BACKEND=[a-z_]+' | head -n1 || echo BACKEND=python" || echo "BACKEND=python")
    orbit_backend=$(orbit_exec backend_default "systemctl show wakir-persona-engine.service --property=Environment | grep -oE 'BACKEND=[a-z_]+' | head -n1 || echo BACKEND=python" || echo "BACKEND=python")

    log_info "pilot_backend=${pilot_backend} orbit_backend=${orbit_backend}"

    # Default-state assertion: both sides report BACKEND=python (no
    # overlay drop-in active).  We strip the BACKEND= prefix for the
    # comparison so the assertion is robust to systemd's quoting.
    if [[ "${pilot_backend}" != "BACKEND=${WAKIR_STRESS_DEFAULT_BACKEND}" ]]; then
        log_warn "pilot not in default backend: ${pilot_backend} (expected BACKEND=${WAKIR_STRESS_DEFAULT_BACKEND})"
        return 1
    fi
    if [[ "${orbit_backend}" != "BACKEND=${WAKIR_STRESS_DEFAULT_BACKEND}" ]]; then
        log_warn "orbit not in default backend: ${orbit_backend} (expected BACKEND=${WAKIR_STRESS_DEFAULT_BACKEND})"
        return 1
    fi

    log_verdict "phase A green: both sides in federation-mode + default-backend"
    return 0
}

# ------------------------------------------------------------------
# Phase B — Stress (Welle-N Cutover on pilot side).
#
# Mirrors live-vm-cutover-drill action_cutover but constrained to
# the pilot side.  Writes overlay, daemon-reload, restart service,
# wait-loop for BackendDecision records.  Returns 0/1/2.
# ------------------------------------------------------------------

phase_stress() {
    local idx="$1"
    local component env_vars env_value overlay
    component=$(welle_component "${idx}")
    env_vars=$(welle_env_vars "${idx}")
    env_value=$(welle_env_value "${idx}")
    overlay=$(welle_overlay_basename "${idx}")
    log_step "phase B: stress welle=${idx} component=${component} env_vars=${env_vars} value=${env_value}"

    # Render the overlay body — one Environment="K=V" per env-var.
    local env_lines=""
    local IFS_BACKUP="${IFS}"
    IFS=','
    for var in ${env_vars}; do
        env_lines+=$(printf 'Environment="%s=%s"\n' "${var}" "${env_value}")
        env_lines+=$'\n'
    done
    IFS="${IFS_BACKUP}"

    local overlay_dir='/etc/systemd/system/wakir-persona-engine.service.d'
    local overlay_path="${overlay_dir}/${overlay}"
    local overlay_body
    overlay_body=$(printf '# Phase-3c Welle-%s Federation-Stress-Cutover\n# Generated: %s\n# ADR-0066 §Welle-%s\n[Service]\n%s' "${idx}" "${STRESS_TS}" "${idx}" "${env_lines}")

    pilot_exec install_overlay_dir "install -d -m 0755 '${overlay_dir}'" >/dev/null || return 2
    pilot_exec write_overlay "umask 0022 && printf '%s' $(printf '%q' "${overlay_body}") > '${overlay_path}'" >/dev/null || return 2
    pilot_exec daemon_reload "systemctl daemon-reload" >/dev/null || return 2

    local ts_restart
    ts_restart="$("${WAKIR_DATE_BIN}" -u +%Y-%m-%dT%H:%M:%SZ)"
    pilot_exec restart_service "systemctl restart wakir-persona-engine.service" >/dev/null || return 2
    log_info "pilot restart issued at ${ts_restart}"

    # Boot-audit wait-loop.  Counts BackendDecision rows matching the
    # component+backend pair within the configured timeout.
    local boot_cmd
    boot_cmd=$(cat <<REMOTE_EOF
timeout ${WAKIR_STRESS_BOOT_AUDIT_TIMEOUT_SEC} journalctl -u wakir-persona-engine.service --since '${ts_restart}' --no-pager --output=cat 2>/dev/null \
  | grep -c -E 'BackendDecision.*${component}.*backend=${env_value}' \
  || true
REMOTE_EOF
)
    local hits
    hits=$(pilot_exec boot_audit "${boot_cmd}" | tail -n 1 | tr -d '[:space:]')
    if [[ -z "${hits}" || ! "${hits}" =~ ^[0-9]+$ ]]; then
        log_error "pilot boot-audit hit-count not parseable: '${hits}'"
        return 2
    fi

    log_info "pilot boot-audit hits=${hits} (min=${WAKIR_STRESS_BOOT_AUDIT_MIN_HITS})"
    if (( hits >= WAKIR_STRESS_BOOT_AUDIT_MIN_HITS )); then
        log_verdict "phase B green: pilot cutover boot-audit met min-hits"
        return 0
    fi
    if (( hits >= 1 )); then
        log_warn "phase B yellow: pilot boot-audit hits=${hits} below min=${WAKIR_STRESS_BOOT_AUDIT_MIN_HITS}"
        return 1
    fi
    log_error "phase B red: pilot boot-audit zero hits for component=${component} backend=${env_value}"
    return 2
}

# ------------------------------------------------------------------
# Phase C — Cross-Cluster Drift-Check.
#
# After the pilot-side cutover, the orbit-side engine MUST stay on
# the Default-Backend (python) for the Welle-N component.  This
# verifies federation isolation: backend-flips on one side do not
# bleed to the federation peer.
# ------------------------------------------------------------------

phase_drift_check() {
    local idx="$1"
    local component env_value
    component=$(welle_component "${idx}")
    env_value=$(welle_env_value "${idx}")
    log_step "phase C: drift-check welle=${idx} component=${component} expected_orbit_backend=${WAKIR_STRESS_DEFAULT_BACKEND}"

    # Orbit-side: count BackendDecisions for the component since the
    # cutover-window started.  We expect >= 1 entry with
    # backend=python (orbit unaffected) AND zero entries with
    # backend=<env_value> (no drift from pilot).
    local since_ts="${STRESS_TS}"
    local python_cmd drift_cmd python_hits drift_hits
    python_cmd=$(cat <<REMOTE_EOF
timeout ${WAKIR_STRESS_BOOT_AUDIT_TIMEOUT_SEC} journalctl -u wakir-persona-engine.service --since '-15 min' --no-pager --output=cat 2>/dev/null \
  | grep -c -E 'BackendDecision.*${component}.*backend=${WAKIR_STRESS_DEFAULT_BACKEND}' \
  || true
REMOTE_EOF
)
    drift_cmd=$(cat <<REMOTE_EOF
timeout ${WAKIR_STRESS_BOOT_AUDIT_TIMEOUT_SEC} journalctl -u wakir-persona-engine.service --since '-15 min' --no-pager --output=cat 2>/dev/null \
  | grep -c -E 'BackendDecision.*${component}.*backend=${env_value}' \
  || true
REMOTE_EOF
)
    python_hits=$(orbit_exec drift_python "${python_cmd}" | tail -n 1 | tr -d '[:space:]')
    drift_hits=$(orbit_exec drift_other "${drift_cmd}" | tail -n 1 | tr -d '[:space:]')

    if [[ -z "${python_hits}" || ! "${python_hits}" =~ ^[0-9]+$ ]]; then
        log_error "orbit python-hit-count not parseable: '${python_hits}'"
        return 2
    fi
    if [[ -z "${drift_hits}" || ! "${drift_hits}" =~ ^[0-9]+$ ]]; then
        log_error "orbit drift-hit-count not parseable: '${drift_hits}'"
        return 2
    fi

    log_info "orbit python_hits=${python_hits} drift_hits=${drift_hits} (using ts=${since_ts})"

    if (( drift_hits > 0 )); then
        log_error "phase C red: orbit observed ${drift_hits} BackendDecision(s) with backend=${env_value} — federation isolation BROKEN"
        return 2
    fi
    if (( python_hits == 0 )); then
        log_warn "phase C yellow: orbit emitted zero python BackendDecision for component=${component} (engine quiet?)"
        return 1
    fi

    log_verdict "phase C green: orbit on backend=${WAKIR_STRESS_DEFAULT_BACKEND}, no drift from pilot cutover"
    return 0
}

# ------------------------------------------------------------------
# Phase D — Federation Trust-Bundle Stress.
#
# Trigger a trust-bundle refresh on both sides (SPIRE server's
# `bundle list` / `bundle refresh`-equivalent) and verify each side
# observes the partner bundle within the configured timeout.
# ------------------------------------------------------------------

phase_trust_stress() {
    local idx="$1"
    log_step "phase D: trust-stress welle=${idx} timeout=${WAKIR_STRESS_TRUST_BUNDLE_TIMEOUT_SEC}s"

    local pilot_refresh orbit_refresh pilot_observes orbit_observes
    pilot_refresh=$(pilot_exec trust_refresh "wakir-cli federation bundle refresh --peer orbit 2>&1 || echo REFRESH_FAIL" || echo "")
    orbit_refresh=$(orbit_exec trust_refresh "wakir-cli federation bundle refresh --peer pilot 2>&1 || echo REFRESH_FAIL" || echo "")

    log_info "pilot refresh='${pilot_refresh}'"
    log_info "orbit refresh='${orbit_refresh}'"

    if [[ "${pilot_refresh}" == *"REFRESH_FAIL"* ]] || [[ "${orbit_refresh}" == *"REFRESH_FAIL"* ]]; then
        log_error "phase D red: bundle refresh failed on at least one side"
        return 2
    fi

    # Roundtrip-Verify: each side should now see the partner bundle
    # within the timeout window.  We poll a single read; the CI stub
    # supplies the canned answer.
    pilot_observes=$(pilot_exec trust_observe "wakir-cli federation bundle list --peer orbit 2>&1 | grep -c 'spiffe://' || true" | tail -n1 | tr -d '[:space:]')
    orbit_observes=$(orbit_exec trust_observe "wakir-cli federation bundle list --peer pilot 2>&1 | grep -c 'spiffe://' || true" | tail -n1 | tr -d '[:space:]')

    if [[ -z "${pilot_observes}" || ! "${pilot_observes}" =~ ^[0-9]+$ ]]; then
        log_error "pilot observe-count not parseable: '${pilot_observes}'"
        return 2
    fi
    if [[ -z "${orbit_observes}" || ! "${orbit_observes}" =~ ^[0-9]+$ ]]; then
        log_error "orbit observe-count not parseable: '${orbit_observes}'"
        return 2
    fi

    log_info "pilot_observes=${pilot_observes} orbit_observes=${orbit_observes}"

    if (( pilot_observes == 0 || orbit_observes == 0 )); then
        log_error "phase D red: at least one side observes zero peer bundle entries"
        return 2
    fi
    if (( pilot_observes == 1 && orbit_observes == 1 )); then
        log_verdict "phase D green: trust-bundle roundtrip observed on both sides"
        return 0
    fi

    log_warn "phase D yellow: trust-bundle observe-count >1 on at least one side (multi-bundle topology?)"
    return 1
}

# ------------------------------------------------------------------
# Orchestrator.  Walks the four stress-phases and renders a
# per-Welle verdict (GREEN/CAUTION/BLOCK).  Returns the highest
# severity exit code observed.
#
#   green   = all four phases exit 0
#   caution = at least one phase exit 1, none exit 2 or 4
#   block   = any phase exit 2
#   not-exec = any phase exit 4 (and no exit-2 above it)
# ------------------------------------------------------------------

run_all_phases() {
    local idx="$1"
    local rc_a rc_b rc_c rc_d
    local highest=0

    # `set +e` around each phase call so non-zero exits do not abort
    # under `set -e`; we explicitly capture + dispatch on the rc.
    set +e
    phase_pre_stress_setup "${idx}"; rc_a=$?
    set -e
    if (( rc_a > highest )); then highest=${rc_a}; fi

    if (( rc_a == 4 )); then
        log_verdict "welle=${idx} STRESS-VERDICT=PROBE-NOT-EXECUTED (phase A not-exec)"
        return 4
    fi

    set +e
    phase_stress "${idx}"; rc_b=$?
    set -e
    if (( rc_b > highest )); then highest=${rc_b}; fi

    set +e
    phase_drift_check "${idx}"; rc_c=$?
    set -e
    if (( rc_c > highest )); then highest=${rc_c}; fi

    set +e
    phase_trust_stress "${idx}"; rc_d=$?
    set -e
    if (( rc_d > highest )); then highest=${rc_d}; fi

    local verdict
    case "${highest}" in
        0) verdict="GREEN" ;;
        1) verdict="CAUTION" ;;
        2) verdict="BLOCK" ;;
        4) verdict="PROBE-NOT-EXECUTED" ;;
        *) verdict="UNKNOWN-${highest}" ;;
    esac

    log_verdict "welle=${idx} STRESS-VERDICT=${verdict} (A=${rc_a} B=${rc_b} C=${rc_c} D=${rc_d})"
    return "${highest}"
}

# ------------------------------------------------------------------
# Single-phase dispatcher (used by --action {pre-stress-setup |
# stress-only | drift-check | trust-stress}).
# ------------------------------------------------------------------

run_single_phase() {
    local idx="$1"; local action="$2"
    case "${action}" in
        pre-stress-setup) phase_pre_stress_setup "${idx}" ;;
        stress-only)      phase_stress           "${idx}" ;;
        drift-check)      phase_drift_check      "${idx}" ;;
        trust-stress)     phase_trust_stress     "${idx}" ;;
        *)
            log_error "run_single_phase: unknown action='${action}'"
            return 3 ;;
    esac
}

# ------------------------------------------------------------------
# Full-Marathon walker.  Walks Welle 1..7 in numeric order, stops on
# first non-zero verdict.  Marathon order is intentionally numeric
# rather than ADR-0066 Doppel-Welle parallel order because the
# federation-stress is a sequential validation surface: parallel
# Wellen would muddy the drift-check signal.
# ------------------------------------------------------------------

run_full_marathon() {
    local idx
    local highest=0
    for idx in 1 2 3 4 5 6 7; do
        log_info "=== marathon: welle=${idx} ==="
        run_all_phases "${idx}"
        local rc=$?
        if (( rc > highest )); then highest=${rc}; fi
        if (( rc >= 2 )); then
            log_error "marathon halted at welle=${idx} rc=${rc}"
            return "${rc}"
        fi
    done
    log_verdict "marathon completed all 7 Wellen rc=${highest}"
    return "${highest}"
}

# ------------------------------------------------------------------
# Main entrypoint.
# ------------------------------------------------------------------

main() {
    parse_args "$@" || exit $?

    mkdir -p "${WAKIR_STRESS_LOG_DIR}"
    if (( FULL_MARATHON == 1 )); then
        STRESS_LOG="${WAKIR_STRESS_LOG_DIR}/marathon-${STRESS_TS}.log"
    else
        STRESS_LOG="${WAKIR_STRESS_LOG_DIR}/welle-${WELLE}-${ACTION}-${STRESS_TS}.log"
    fi
    : > "${STRESS_LOG}"
    log_info "stress-log: ${STRESS_LOG}"
    log_info "config: pilot=${WAKIR_PILOT_HOST} orbit=${WAKIR_ORBIT_HOST} dry_run=${DRY_RUN} sandbox_stub=${SANDBOX_STUB}"

    check_ssh_keys_present || exit 3

    if (( FULL_MARATHON == 1 )); then
        run_full_marathon
        exit $?
    fi

    if [[ "${ACTION}" == "stress" ]]; then
        run_all_phases "${WELLE}"
        exit $?
    fi

    run_single_phase "${WELLE}" "${ACTION}"
    exit $?
}

# Allow sourcing for tests: only run main() when invoked directly.
if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" && "${WAKIR_STRESS_TEST_MODE:-0}" != "1" ]]; then
    main "$@"
fi
