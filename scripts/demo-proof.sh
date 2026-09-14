#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# scripts/demo-proof.sh — one-command cross-repo proof demo.
#
# Drives the full evidence chain end-to-end:
#
#   protocol event  ->  runtime bridge  ->  WAT manifest
#                                 ->  Merkle inclusion proof
#                                 ->  wakir-verify cross-check
#
# Requirements: bash and python3. Nothing else. All JSON handling is
# done by ``scripts/demo_proof_helpers.py``; this file only orders the
# steps and applies the short-circuit rule.
#
# Output: one ``wakir-demo-proof/v1`` JSON object on stdout with one
# record per step (always all five, in fixed order) plus the three
# repo commit hashes the demo was driven against.
#
# Exit code:
#   0   no step failed (``ok`` and ``skipped`` steps both count as
#       non-failing — a fresh clone without wakir-verify installed
#       exits 0 with ``external_verify: skipped`` and a reason)
#   10  at least one step ``failed``; downstream steps are ``not_run``
#   2   python3 not found
#
# Per-step ``exit_code`` inside the report: 0 ok, 10 failed,
# 20 skipped, 30 not_run. The CI gate additionally requires
# ``external_verify == ok`` through the report validator.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HELPERS="${SCRIPT_DIR}/demo_proof_helpers.py"

# Working directory for demo artefacts. Defaults to a fresh tmpdir so
# parallel runs cannot stomp each other; tests override this so they
# can assert on the produced files. Portable mktemp form (no -t).
: "${DEMO_PROOF_WORKDIR:=$(mktemp -d "${TMPDIR:-/tmp}/wakir-demo-proof.XXXXXX")}"

# Hour slot used for the demo. Pinned rather than ``$(date)`` so the
# proof is byte-for-byte reproducible across runs.
: "${DEMO_PROOF_HOUR:=2026-05-17T12}"

# Online mode: when "1" *and* DEMO_PROOF_OTS_PROOF points at a real
# OpenTimestamps receipt, step 5 additionally shells out to the
# wakir-verify console script for the Bitcoin-anchor poles. Default
# "0" keeps the run hermetic (library-only cross-check, no network).
: "${DEMO_PROOF_VERIFY_ONLINE:=0}"
: "${DEMO_PROOF_OTS_PROOF:=}"
: "${DEMO_PROOF_VERIFY_CMD:=wakir-verify}"

# Spool-projection escape hatch. Default "0": step 3 reads the spool
# and nothing else, so a spool record that lost a B1 field fails the
# step instead of being silently reconstructed from
# event.envelope.json. Set to "1" for local work against a spool
# writer whose format has moved; the report then carries
# `envelope_projection_used=true` and the strict CI validator rejects
# it. Honoured in every mode — this is a deliberate operator choice,
# not a test hook.
: "${DEMO_PROOF_ALLOW_ENVELOPE_PROJECTION:=0}"

# Cross-repo commit-hash pins. Optional; recorded verbatim in the report.
: "${DEMO_PROOF_PROTOCOL_COMMIT:=}"
: "${DEMO_PROOF_VERIFY_COMMIT:=}"

# Test hooks. Only honoured when DEMO_PROOF_TEST_MODE=1; ignored
# otherwise so they cannot alter a production run by accident.
#   DEMO_PROOF_FAIL_STEP=<step function name>   force that step to fail
#   DEMO_PROOF_SIMULATE_NO_WAKIR_VERIFY=1       treat wakir_verify as absent
: "${DEMO_PROOF_TEST_MODE:=0}"
: "${DEMO_PROOF_FAIL_STEP:=}"
: "${DEMO_PROOF_SIMULATE_NO_WAKIR_VERIFY:=0}"
if [[ "${DEMO_PROOF_TEST_MODE}" != "1" ]]; then
    DEMO_PROOF_FAIL_STEP=""
    DEMO_PROOF_SIMULATE_NO_WAKIR_VERIFY="0"
fi

# Report and artefact paths (kept stable so the runbook can reference them).
DEMO_REPORT="${DEMO_PROOF_WORKDIR}/demo-report.json"
STEPS_FILE="${DEMO_PROOF_WORKDIR}/.steps.jsonl"
EVENT_PAYLOAD="${DEMO_PROOF_WORKDIR}/event.json"
EVENT_ENVELOPE="${DEMO_PROOF_WORKDIR}/event.envelope.json"
EVENT_PAYLOAD_HASH_FILE="${DEMO_PROOF_WORKDIR}/event.sha256"
BRIDGE_RESULT="${DEMO_PROOF_WORKDIR}/bridge-result.json"
SPOOL_ROOT="${DEMO_PROOF_WORKDIR}/spool"
ACTIVITY_LOG="${DEMO_PROOF_WORKDIR}/activity-log.md"
MANIFEST_INPUT="${DEMO_PROOF_WORKDIR}/manifest-input.jsonl"
MANIFEST_OUT="${DEMO_PROOF_WORKDIR}/${DEMO_PROOF_HOUR}/manifest.json"
PROJECTION_OUT="${DEMO_PROOF_WORKDIR}/manifest-projection.json"
PROOF_OUT="${DEMO_PROOF_WORKDIR}/proof.json"
VERIFY_RESULT="${DEMO_PROOF_WORKDIR}/verify-result.json"
VERIFY_CLI_RESULT="${DEMO_PROOF_WORKDIR}/verify-cli-result.json"

mkdir -p "${DEMO_PROOF_WORKDIR}" "$(dirname "${MANIFEST_OUT}")" "${SPOOL_ROOT}"
: > "${STEPS_FILE}"

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
    printf 'demo-proof: required command not found: python3\n' >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

helper() {
    python3 "${HELPERS}" "$@"
}

# emit_step <name> <status> <exit_code> [emit-step options...]
# Details are assembled and validated by the helper; see
# ``do_emit_step`` for the accepted options (--result-file, --pick,
# --kv, --int, --error-file, --details-json).
emit_step() {
    local name="$1" status="$2" code="$3"
    shift 3
    helper emit-step --steps-file "${STEPS_FILE}" \
        --name "${name}" --status "${status}" --code "${code}" "$@"
}

# fail_step <name> <stderr-capture> [extra emit-step options...]
fail_step() {
    local name="$1" err_file="$2"
    shift 2
    emit_step "${name}" "failed" 10 --error-file "${err_file}" "$@"
    return 10
}

# inject_fault <name> <step function>  — test-mode only (see above).
inject_fault() {
    local name="$1" fn="$2"
    if [[ -n "${DEMO_PROOF_FAIL_STEP}" && "${DEMO_PROOF_FAIL_STEP}" == "${fn}" ]]; then
        emit_step "${name}" "failed" 10 \
            --kv "error=fault injected via DEMO_PROOF_FAIL_STEP=${fn}" \
            --kv "fault_injected=true"
        return 10
    fi
    return 0
}

resolve_runtime_commit() {
    if git -C "${REPO_ROOT}" rev-parse --verify HEAD >/dev/null 2>&1; then
        git -C "${REPO_ROOT}" rev-parse HEAD
    else
        printf 'unknown'
    fi
}

RUNTIME_COMMIT="$(resolve_runtime_commit)"
PROTOCOL_COMMIT="${DEMO_PROOF_PROTOCOL_COMMIT:-unknown}"
VERIFY_COMMIT="${DEMO_PROOF_VERIFY_COMMIT:-unknown}"

# ---------------------------------------------------------------------------
# Step 1 — protocol event
# ---------------------------------------------------------------------------
#
# Materialise a B1-shape audit event matching the wakir-protocol
# Wirelang frame contract (event_id / time / payload_hash /
# capability_token_hash).

step1_protocol_event() {
    local name="protocol_event" err="${DEMO_PROOF_WORKDIR}/step1.err" rc=0
    inject_fault "${name}" "${FUNCNAME[0]}" || return $?

    helper build-event \
        --hour "${DEMO_PROOF_HOUR}" \
        --out "${EVENT_PAYLOAD}" \
        --hash-out "${EVENT_PAYLOAD_HASH_FILE}" \
        2>"${err}" || rc=$?
    if [[ "${rc}" -ne 0 ]]; then
        fail_step "${name}" "${err}"
        return 10
    fi

    emit_step "${name}" "ok" 0 \
        --result-file "${EVENT_ENVELOPE}" --pick "payload_path,payload_hash"
}

# ---------------------------------------------------------------------------
# Step 2 — runtime bridge
# ---------------------------------------------------------------------------
#
# Push the event through the bridge-audit-writer. The bridge fans an
# event out to both the WAT spool and the activity log; we exercise
# both sinks so the demo demonstrates the full atomicity contract.

step2_runtime_bridge() {
    local name="runtime_bridge" err="${DEMO_PROOF_WORKDIR}/step2.err" rc=0
    inject_fault "${name}" "${FUNCNAME[0]}" || return $?

    local payload_hash
    payload_hash="$(cat "${EVENT_PAYLOAD_HASH_FILE}")" || {
        emit_step "${name}" "failed" 10 --kv "error=payload hash from step 1 missing"
        return 10
    }

    helper run-bridge \
        --payload "${EVENT_PAYLOAD}" \
        --payload-hash "${payload_hash}" \
        --spool-root "${SPOOL_ROOT}" \
        --activity-log "${ACTIVITY_LOG}" \
        --event-time "${DEMO_PROOF_HOUR}:00:00Z" \
        --out "${BRIDGE_RESULT}" \
        2>"${err}" || rc=$?
    if [[ "${rc}" -ne 0 ]]; then
        if [[ -f "${BRIDGE_RESULT}" ]]; then
            fail_step "${name}" "${err}" \
                --result-file "${BRIDGE_RESULT}" --pick "status:bridge_status,error:bridge_error"
        else
            fail_step "${name}" "${err}"
        fi
        return 10
    fi

    emit_step "${name}" "ok" 0 \
        --result-file "${BRIDGE_RESULT}" \
        --pick "status:bridge_status,wat_spool_path:spool,activity_log_path:activity_log"
}

# ---------------------------------------------------------------------------
# Step 3 — Merkle manifest from spool
# ---------------------------------------------------------------------------

step3_merkle_manifest() {
    local name="merkle_manifest" err="${DEMO_PROOF_WORKDIR}/step3.err" rc=0
    inject_fault "${name}" "${FUNCNAME[0]}" || return $?

    # The spool is the input of this step. Filling an incomplete spool
    # record from event.envelope.json repairs exactly the drift the
    # step is meant to expose, so it is off unless the operator asks
    # for it — and then the report says so.
    local -a projection_opt=()
    if [[ "${DEMO_PROOF_ALLOW_ENVELOPE_PROJECTION}" == "1" ]]; then
        projection_opt=(--allow-envelope-projection)
    fi

    helper build-manifest \
        --spool-root "${SPOOL_ROOT}" \
        --hour "${DEMO_PROOF_HOUR}" \
        --aggregator-input "${MANIFEST_INPUT}" \
        --manifest-out "${MANIFEST_OUT}" \
        --projection-out "${PROJECTION_OUT}" \
        "${projection_opt[@]}" \
        2>"${err}" || rc=$?
    if [[ "${rc}" -ne 0 ]]; then
        fail_step "${name}" "${err}"
        return 10
    fi

    local projection_used="unknown"
    if [[ -f "${PROJECTION_OUT}" ]]; then
        projection_used="$(helper json-get "${PROJECTION_OUT}" envelope_projection_used)" \
            || projection_used="unknown"
    fi

    emit_step "${name}" "ok" 0 \
        --result-file "${MANIFEST_OUT}" --pick "merkle_root,event_count" \
        --kv "manifest_path=${MANIFEST_OUT}" \
        --kv "envelope_projection_used=${projection_used}"
}

# ---------------------------------------------------------------------------
# Step 4 — inclusion proof (wakir-inclusion-proof/v1)
# ---------------------------------------------------------------------------
#
# Builds the inclusion proof for the demo event — sibling hashes with
# side markers, so anyone can recompute the root with plain SHA-256 —
# and verifies it against the manifest's stored root using the
# in-tree Merkle implementation. Step 5 repeats the check through the
# external verifier's code.

step4_inclusion_proof() {
    local name="inclusion_proof" err="${DEMO_PROOF_WORKDIR}/step4.err" rc=0
    inject_fault "${name}" "${FUNCNAME[0]}" || return $?

    helper verify-proof \
        --manifest "${MANIFEST_OUT}" \
        --event "${EVENT_PAYLOAD}" \
        --out "${PROOF_OUT}" \
        2>"${err}" || rc=$?
    if [[ "${rc}" -ne 0 ]]; then
        if [[ -f "${PROOF_OUT}" ]]; then
            fail_step "${name}" "${err}" --kv "proof_path=${PROOF_OUT}" --details-json '{"verified": false}'
        else
            fail_step "${name}" "${err}"
        fi
        return 10
    fi

    emit_step "${name}" "ok" 0 \
        --result-file "${PROOF_OUT}" \
        --pick "schema,merkle_root,leaf_hash,leaf_index,leaf_count,siblings" \
        --kv "proof_path=${PROOF_OUT}" --details-json '{"verified": true}'
}

# ---------------------------------------------------------------------------
# Step 5 — wakir-verify cross-check
# ---------------------------------------------------------------------------
#
# Cross-repo leg through the wakir-verify *library*: the runtime-built
# manifest is loaded by ``wakir_verify.manifest``, its root re-derived
# by the verifier's own Merkle code, and the step-4 proof is checked
# with ``wakir_verify.merkle_proof``. No network. When the package is
# not importable the step is ``skipped`` with a reason — never
# silently dropped, never faked as ``ok``.
#
# Online mode (DEMO_PROOF_VERIFY_ONLINE=1 + DEMO_PROOF_OTS_PROOF) adds
# a console-script run for the Bitcoin-anchor poles on top of the
# library check. ONLINE=1 without a receipt is an explicit skip.

step5_external_verify() {
    local name="external_verify" err="${DEMO_PROOF_WORKDIR}/step5.err" rc=0
    inject_fault "${name}" "${FUNCNAME[0]}" || return $?

    if [[ "${DEMO_PROOF_VERIFY_ONLINE}" == "1" && -z "${DEMO_PROOF_OTS_PROOF}" ]]; then
        emit_step "${name}" "skipped" 20 \
            --kv "mode=online" \
            --kv "reason=DEMO_PROOF_VERIFY_ONLINE=1 but DEMO_PROOF_OTS_PROOF unset"
        return 20
    fi

    local -a simulate=()
    if [[ "${DEMO_PROOF_SIMULATE_NO_WAKIR_VERIFY}" == "1" ]]; then
        simulate=(--simulate-missing)
    fi

    helper external-verify \
        --manifest "${MANIFEST_OUT}" \
        --proof "${PROOF_OUT}" \
        --out "${VERIFY_RESULT}" \
        "${simulate[@]}" \
        2>"${err}" || rc=$?

    case "${rc}" in
        0)  ;;
        20)
            emit_step "${name}" "skipped" 20 \
                --result-file "${VERIFY_RESULT}" --pick "mode,reason,local_root_rederived"
            return 20
            ;;
        *)
            if [[ -f "${VERIFY_RESULT}" ]]; then
                fail_step "${name}" "${err}" --result-file "${VERIFY_RESULT}" \
                    --pick "mode,wakir_verify_version,manifest_consistent,root_match,leaf_present,proof_verified"
            else
                fail_step "${name}" "${err}"
            fi
            return 10
            ;;
    esac

    if [[ "${DEMO_PROOF_VERIFY_ONLINE}" != "1" ]]; then
        emit_step "${name}" "ok" 0 \
            --result-file "${VERIFY_RESULT}" \
            --pick "mode,wakir_verify_version,manifest_consistent,root_match,leaf_present,proof_verified,leaf_count" \
            --kv "verify_result_path=${VERIFY_RESULT}"
        return 0
    fi

    # Online: operator supplied a real OTS receipt; drive the console script.
    local anchor
    anchor="$(helper json-get "${MANIFEST_OUT}" merkle_root)" || {
        emit_step "${name}" "failed" 10 --kv "error=cannot read merkle_root from manifest"
        return 10
    }
    if ! command -v "${DEMO_PROOF_VERIFY_CMD}" >/dev/null 2>&1; then
        emit_step "${name}" "failed" 10 --kv "mode=library+online" \
            --kv "error=DEMO_PROOF_VERIFY_ONLINE=1 but ${DEMO_PROOF_VERIFY_CMD} not on PATH"
        return 10
    fi
    rc=0
    "${DEMO_PROOF_VERIFY_CMD}" \
        --anchor "${anchor}" \
        --ots-proof "${DEMO_PROOF_OTS_PROOF}" \
        --output-format json \
        >"${VERIFY_CLI_RESULT}" 2>"${err}" || rc=$?
    if [[ "${rc}" -ne 0 ]]; then
        fail_step "${name}" "${err}" --kv "mode=library+online" --kv "anchor=${anchor}"
        return 10
    fi
    emit_step "${name}" "ok" 0 \
        --result-file "${VERIFY_RESULT}" \
        --pick "wakir_verify_version,manifest_consistent,root_match,leaf_present,proof_verified" \
        --kv "mode=library+online" --kv "anchor=${anchor}" \
        --kv "verify_result_path=${VERIFY_RESULT}" \
        --kv "verify_cli_result_path=${VERIFY_CLI_RESULT}"
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

run_demo() {
    local step rc short_circuited=""
    for step in step1_protocol_event step2_runtime_bridge \
                step3_merkle_manifest step4_inclusion_proof \
                step5_external_verify; do
        rc=0
        "${step}" || rc=$?
        if [[ "${rc}" -eq 10 ]]; then
            # A hard failure short-circuits; downstream steps would only
            # produce noise on broken inputs. They are reported as not_run.
            short_circuited="${step}"
            break
        fi
    done

    local -a sc_opt=()
    if [[ -n "${short_circuited}" ]]; then
        sc_opt=(--short-circuited-after "${short_circuited}")
    fi
    helper assemble-report \
        --steps-file "${STEPS_FILE}" \
        --out "${DEMO_REPORT}" \
        --runtime-commit "${RUNTIME_COMMIT}" \
        --protocol-commit "${PROTOCOL_COMMIT}" \
        --verify-commit "${VERIFY_COMMIT}" \
        --workdir "${DEMO_PROOF_WORKDIR}" \
        --hour "${DEMO_PROOF_HOUR}" \
        "${sc_opt[@]}"

    cat "${DEMO_REPORT}"

    local exit_code
    exit_code="$(helper json-get "${DEMO_REPORT}" exit_code)"
    return "${exit_code}"
}

run_demo
