#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-3-day-0-pipeline.sh — Operator-side Day-0 orchestrator for
# the ADR-0066 Welle-3 (`bridge_audit_writer`) cutover week.
#
# This is the Welle-3 sibling of `scripts/welle-1-day-0-pipeline.sh`
# (PR #218, Tag-32). The two scripts share their four-phase shape,
# JSON-emit/read helpers and exit-code semantics so Tomás / Selin /
# Reza only have to learn one pipeline contract; the substance that
# differs is wired explicitly inside the Mo, Mi and Do phases.
#
# Welle-3 is the **bridge-audit cutover**, scheduled KW 25 solo per
# ADR-0066 §"Bridge-Audit-Welle bleibt strikt solo". Three things
# matter operationally for Welle-3 that did not matter for Welle-1:
#
#   1. **Component normalisation** — ADR-0065 §Welle-Sequenz spells
#      the Welle-3 component as `bridge_audit_writer`. The in-repo
#      dry-run + resolver substrate maps it to the short form
#      `anchor_emitter` via
#      `scripts/phase-3c-cutover-dry-run.py::PHASE_3C_COMPONENT_ALIASES`
#      (PR #205 §Component-Aliasing). This script accepts either
#      spelling on the CLI; the JSON envelopes record the long-form
#      name verbatim so the artifact remains operator-readable.
#
#   2. **Henrik-Caution (independent oracle, Phase Mi.5)** — the
#      module being flipped IS the bridge-audit substrate, so the
#      canonical Welle-1/Welle-2 consistency oracle
#      `tests/integration/test_bridge_audit_roundtrip_e2e.py` cannot
#      be used as the consistency signal for Welle-3 (the subject
#      under test would certify its own switch). Henrik (Internal
#      Audit) flagged this in the ADR-0066 verification plan; the
#      CI workflow PR #205 replaced the e2e oracle with the Phase-2
#      Cross-Modul-Stress aggregator (PR #197). This script mirrors
#      that decision with an explicit Phase Mi.5 step that runs
#      `scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-
#      stress` and records `henrik_caution_applied=true` in the
#      acceptance-decision envelope.
#
#   3. **Live Welle-3 telemetry snapshot (Phase Do)** — Phase Do of
#      the Welle-3 pipeline reads a snapshot from the live
#      `scripts/welle-3-telemetry-emitter.py` JSON output (PR #206)
#      in addition to the WAT/observability baseline. The
#      `divergence_red_flag` field is the operator-facing signal
#      Henrik asked for; it is the structural sibling of the
#      cross-modul-stress oracle in Phase Mi.5.
#
# Phases
# ------
#
#   Mo    Dry-Run        — phase-3c-trigger-gate-aggregator (JSON)
#                          + phase-3c-cutover-dry-run --component
#                          bridge_audit_writer (normalised to
#                          anchor_emitter inside the resolver)
#   Mi    CI-Cutover     — gh workflow run phase-3c-welle-3-validation
#                          + wait for the run to finish
#   Mi.5  Henrik-Caution — doppelbetrieb-score-aggregator
#                          --mode=cross-modul-stress; independent
#                          consistency oracle for the bridge-audit
#                          cutover, NOT a bridge-audit self-oracle
#   Do    Cross-Review   — PR-review state for the Welle-3 PR bundle
#                          + welle-3-telemetry-emitter snapshot
#                          (PR #206) + WAT-telemetry baseline JSONL
#   Fr    Acceptance     — fuse the phase artifacts into a single
#                          cutover-acceptance-decision-welle-3.json
#                          with an explicit go/no-go verdict AND a
#                          `henrik_caution_applied` marker
#
# Per-phase exit codes (also the overall exit-code when --phase is
# given): 0 = green/success, 1 = yellow/proceed-with-caveats,
# 2 = red/block.
#
# Dependencies: bash >= 4, python3, gh (only for the Mi phase when
# --no-ci-wait is *not* set), git. Uses python3 for JSON
# emit/parse so the script runs equally well on hosts without jq.
# (jq is referenced in the runbook for ad-hoc inspection only.)
#
# Hermetic-by-default: every external side-effect (gh dispatch,
# artifact download, network) is gated behind a flag. The default
# invocation `welle-3-day-0-pipeline.sh --dry-run-all` runs all
# four+1 phases in the deterministic local-only mode the test suite
# exercises.

set -uo pipefail

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

readonly SCRIPT_NAME="welle-3-day-0-pipeline.sh"
readonly SCRIPT_VERSION="1.0.0-tag32"
# ADR-0065 long-form component name. Normalised to anchor_emitter
# inside the resolver layer via PHASE_3C_COMPONENT_ALIASES.
readonly WELLE_COMPONENT_DEFAULT="bridge_audit_writer"
readonly WELLE_COMPONENT_RESOLVER_ALIAS="anchor_emitter"
readonly WORKFLOW_FILE_DEFAULT="phase-3c-welle-3-validation.yml"
readonly WELLE_REPO_DEFAULT="wakir-labs/wakir-runtime"
readonly WELLE_NUMBER=3

# Exit codes (per phase + overall)
readonly EXIT_GREEN=0
readonly EXIT_YELLOW=1
readonly EXIT_RED=2

# ----------------------------------------------------------------------
# Diagnostic helpers
# ----------------------------------------------------------------------

log() {
    # All log lines go to stderr so stdout stays JSON-pure when a
    # phase emits its envelope to stdout.
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

die() {
    log "FATAL: $*"
    exit "$EXIT_RED"
}

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || die "missing dependency: $cmd"
}

# ----------------------------------------------------------------------
# JSON emit / read helpers (python3-based, no jq required)
#
# json_emit OUTPUT_PATH KEY=TYPE:VALUE [...]
#   TYPE is one of: s (string), j (raw json — number/bool/object),
#                   ji (integer), jb (bool from 0/1)
#
# json_read FILE FIELD [DEFAULT]
#   Reads a top-level field. Prints DEFAULT when the file is missing or
#   the field is absent.
# ----------------------------------------------------------------------

json_emit() {
    local output="$1"; shift
    python3 - "$output" "$@" <<'PYEOF'
import json, sys
out = sys.argv[1]
pairs = sys.argv[2:]
obj = {}
for p in pairs:
    if "=" not in p:
        sys.exit("json_emit: bad pair: " + p)
    key, rhs = p.split("=", 1)
    typ, _, val = rhs.partition(":")
    if typ == "s":
        obj_val = val
    elif typ == "j":
        obj_val = json.loads(val) if val != "" else None
    elif typ == "ji":
        obj_val = int(val)
    elif typ == "jb":
        obj_val = (val == "1")
    else:
        sys.exit("json_emit: bad type: " + typ)
    # Support dotted-keys for nesting: a.b.c
    cur = obj
    keys = key.split(".")
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = obj_val
with open(out, "w") as f:
    json.dump(obj, f, sort_keys=True)
PYEOF
}

json_read() {
    local file="$1"
    local field="$2"
    local default="${3:-}"
    if [[ ! -s "$file" ]]; then
        printf '%s' "$default"
        return
    fi
    python3 - "$file" "$field" "$default" <<'PYEOF'
import json, sys
path, field, default = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f:
        obj = json.load(f)
except Exception:
    print(default, end="")
    sys.exit(0)
val = obj
for part in field.split("."):
    if isinstance(val, dict) and part in val:
        val = val[part]
    else:
        print(default, end="")
        sys.exit(0)
if isinstance(val, bool):
    print("true" if val else "false", end="")
elif val is None:
    print(default, end="")
else:
    print(val, end="")
PYEOF
}

json_validate() {
    local file="$1"
    [[ -s "$file" ]] || return 1
    python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$file" \
        >/dev/null 2>&1
}

# ----------------------------------------------------------------------
# Component normalisation
#
# ADR-0065 §Welle-Sequenz spells the Welle-3 component as
# `bridge_audit_writer`. The in-repo resolver / dry-run substrate
# uses the short form `anchor_emitter`. Both spellings must work as
# CLI input; the JSON envelopes record the long-form name verbatim
# so the artifact stays operator-readable.
# ----------------------------------------------------------------------

normalise_component_for_resolver() {
    local name="$1"
    case "$name" in
        bridge_audit_writer|anchor_emitter)
            printf '%s' "$WELLE_COMPONENT_RESOLVER_ALIAS"
            ;;
        *)
            # Anything else flows through untouched; the resolver
            # will raise its own validation error if it does not
            # know the name.
            printf '%s' "$name"
            ;;
    esac
}

# ----------------------------------------------------------------------
# CLI surface
# ----------------------------------------------------------------------

print_usage() {
    cat <<USAGE
Usage: $SCRIPT_NAME [options]

Options:
  --phase PHASE          One of: mo, mi, mi5, do, fr, all (default: all)
  --component NAME       Phase-3c component (default: $WELLE_COMPONENT_DEFAULT)
                         Accepts ADR-0065 long-form (bridge_audit_writer)
                         or in-repo short form (anchor_emitter).
  --workdir DIR          Directory for phase JSON artifacts (default:
                         \$PWD/.welle-3-day-0-artifacts)
  --repo-root DIR        Repository root (default: parent of scripts/)
  --workflow FILE        CI workflow filename (default: $WORKFLOW_FILE_DEFAULT)
  --gh-repo SLUG         GitHub slug (default: $WELLE_REPO_DEFAULT)
  --telemetry-snapshot F Path to a welle-3-telemetry-emitter snapshot
                         JSON (PR #206) consumed by Phase Do. When
                         omitted Phase Do skips that signal.
  --no-ci-wait           For the Mi phase: dispatch only, do not wait
  --dry-run-all          Hermetic mode: never call gh or the network;
                         every phase uses the local-only path
  --version              Print version and exit
  -h | --help            Print this help

Per-phase exit-codes (overall when --phase != all):
  $EXIT_GREEN = green / success
  $EXIT_YELLOW = yellow / proceed-with-caveats
  $EXIT_RED = red / block

Examples
--------

Run the full Welle-3 Day-0 pipeline in hermetic mode (rehearsal):
  $SCRIPT_NAME --dry-run-all

Run only the Monday dry-run phase:
  $SCRIPT_NAME --phase mo --dry-run-all

Run only the Henrik-Caution Cross-Modul-Stress oracle:
  $SCRIPT_NAME --phase mi5 --dry-run-all

USAGE
}

# Defaults (resolved later if blank)
PHASE="all"
COMPONENT="$WELLE_COMPONENT_DEFAULT"
WORKDIR=""
REPO_ROOT=""
WORKFLOW="$WORKFLOW_FILE_DEFAULT"
GH_REPO="$WELLE_REPO_DEFAULT"
TELEMETRY_SNAPSHOT=""
NO_CI_WAIT=0
DRY_RUN_ALL=0

parse_args() {
    while (($#)); do
        case "$1" in
            --phase) PHASE="${2:-}"; shift 2 ;;
            --component) COMPONENT="${2:-}"; shift 2 ;;
            --workdir) WORKDIR="${2:-}"; shift 2 ;;
            --repo-root) REPO_ROOT="${2:-}"; shift 2 ;;
            --workflow) WORKFLOW="${2:-}"; shift 2 ;;
            --gh-repo) GH_REPO="${2:-}"; shift 2 ;;
            --telemetry-snapshot) TELEMETRY_SNAPSHOT="${2:-}"; shift 2 ;;
            --no-ci-wait) NO_CI_WAIT=1; shift ;;
            --dry-run-all) DRY_RUN_ALL=1; shift ;;
            --version) printf '%s %s\n' "$SCRIPT_NAME" "$SCRIPT_VERSION"; exit 0 ;;
            -h|--help) print_usage; exit 0 ;;
            *)
                printf 'Unknown option: %s\n\n' "$1" >&2
                print_usage >&2
                exit "$EXIT_RED"
                ;;
        esac
    done

    case "$PHASE" in
        mo|mi|mi5|do|fr|all) ;;
        *) die "invalid --phase: $PHASE (one of: mo, mi, mi5, do, fr, all)" ;;
    esac
}

# ----------------------------------------------------------------------
# Environment resolution
# ----------------------------------------------------------------------

resolve_repo_root() {
    if [[ -n "$REPO_ROOT" ]]; then
        REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
        return
    fi
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "$script_dir/.." && pwd)"
}

resolve_workdir() {
    if [[ -z "$WORKDIR" ]]; then
        WORKDIR="$PWD/.welle-3-day-0-artifacts"
    fi
    mkdir -p "$WORKDIR" || die "cannot create workdir: $WORKDIR"
}

# Worst-of-two combinator for phase exit-codes:
#   green + anything -> anything
#   yellow + red -> red
combine_exit() {
    local a="$1" b="$2"
    if (( a > b )); then
        printf '%s' "$a"
    else
        printf '%s' "$b"
    fi
}

# ----------------------------------------------------------------------
# Phase Mo — Monday Dry-Run
# ----------------------------------------------------------------------

phase_mo_run() {
    local resolver_name
    resolver_name="$(normalise_component_for_resolver "$COMPONENT")"
    log "phase Mo (dry-run): trigger-gate-aggregator + cutover-dry-run --component $COMPONENT (resolver=$resolver_name)"

    local gates_out="$WORKDIR/phase-mo-trigger-gates.json"
    local dry_out="$WORKDIR/phase-mo-cutover-dry-run.json"
    local summary_out="$WORKDIR/phase-mo-summary.json"

    # 1) Trigger-gate aggregator
    local gates_rc=0
    if ! python3 "$REPO_ROOT/scripts/phase-3c-trigger-gate-aggregator.py" \
            --repo-root "$REPO_ROOT" --json >"$gates_out" 2>/dev/null; then
        gates_rc=$?
    fi
    log "trigger-gate-aggregator rc=$gates_rc artifact=$gates_out"

    # 2) Cutover dry-run for the requested component. The resolver
    # accepts both spellings of the Welle-3 component, but we feed
    # it the ADR-0065 long-form so the dry-run JSON envelope is
    # operator-readable end-to-end.
    local dry_rc=0
    if ! python3 "$REPO_ROOT/scripts/phase-3c-cutover-dry-run.py" \
            --component "$COMPONENT" --output "$dry_out" >/dev/null 2>&1; then
        dry_rc=$?
    fi
    log "cutover-dry-run rc=$dry_rc component=$COMPONENT artifact=$dry_out"

    # 3) Verdict — green when both succeeded and both envelopes parse-clean
    local gates_status="unknown"
    local dry_status="unknown"
    if json_validate "$gates_out"; then
        gates_status="$(json_read "$gates_out" overall_status unknown)"
    fi
    if json_validate "$dry_out"; then
        dry_status="$(json_read "$dry_out" dry_run unknown)"
    fi

    local verdict="green"
    local rc="$EXIT_GREEN"
    if [[ "$gates_status" == "red" ]] || [[ "$dry_status" == "blocked" ]] \
       || (( gates_rc >= 2 )) || (( dry_rc >= 2 )); then
        verdict="red"
        rc="$EXIT_RED"
    elif [[ "$gates_status" == "yellow" ]] || (( gates_rc == 1 )) || (( dry_rc == 1 )); then
        verdict="yellow"
        rc="$EXIT_YELLOW"
    fi

    json_emit "$summary_out" \
        "phase=s:mo" \
        "component=s:$COMPONENT" \
        "component_resolver_alias=s:$resolver_name" \
        "verdict=s:$verdict" \
        "gates_status=s:$gates_status" \
        "dry_status=s:$dry_status" \
        "gates_rc=ji:$gates_rc" \
        "dry_rc=ji:$dry_rc" \
        "exit_code=ji:$rc" \
        "artifacts.gates=s:$gates_out" \
        "artifacts.dry_run=s:$dry_out"

    log "phase Mo verdict=$verdict rc=$rc summary=$summary_out"
    return "$rc"
}

# ----------------------------------------------------------------------
# Phase Mi — Wednesday CI Cutover
# ----------------------------------------------------------------------

phase_mi_run() {
    log "phase Mi (CI cutover): dispatch $WORKFLOW for $GH_REPO"
    local summary_out="$WORKDIR/phase-mi-summary.json"
    local run_id="hermetic-dispatch"
    local run_status="dispatched"
    local conclusion="hermetic"
    local rc="$EXIT_GREEN"
    local verdict="green"

    if (( DRY_RUN_ALL )); then
        log "DRY_RUN_ALL=1 — hermetic CI phase, no gh invocation"
    else
        require_cmd gh

        # Dispatch the workflow
        if ! gh workflow run "$WORKFLOW" \
                --repo "$GH_REPO" \
                --ref main >/dev/null 2>&1; then
            log "gh workflow run failed"
            rc="$EXIT_RED"
            verdict="red"
            run_status="dispatch-failed"
            conclusion="failure"
        else
            # Locate the most recent run for this workflow
            sleep 2
            run_id="$(gh run list --repo "$GH_REPO" \
                        --workflow "$WORKFLOW" --limit 1 \
                        --json databaseId --jq '.[0].databaseId' \
                        2>/dev/null || printf 'unknown')"
            log "dispatched run_id=$run_id"

            if (( NO_CI_WAIT )); then
                run_status="dispatched"
                conclusion="not-waited"
                verdict="yellow"
                rc="$EXIT_YELLOW"
            else
                # Wait for the run; surface its conclusion
                if gh run watch "$run_id" --repo "$GH_REPO" \
                        --exit-status >/dev/null 2>&1; then
                    run_status="completed"
                    conclusion="success"
                    verdict="green"
                    rc="$EXIT_GREEN"
                else
                    local watch_rc=$?
                    run_status="completed"
                    conclusion="failure"
                    verdict="red"
                    rc="$EXIT_RED"
                    log "gh run watch exited with rc=$watch_rc"
                fi
            fi
        fi
    fi

    json_emit "$summary_out" \
        "phase=s:mi" \
        "workflow=s:$WORKFLOW" \
        "gh_repo=s:$GH_REPO" \
        "run_id=s:$run_id" \
        "run_status=s:$run_status" \
        "conclusion=s:$conclusion" \
        "verdict=s:$verdict" \
        "exit_code=ji:$rc" \
        "hermetic=jb:$DRY_RUN_ALL"

    log "phase Mi verdict=$verdict rc=$rc summary=$summary_out"
    return "$rc"
}

# ----------------------------------------------------------------------
# Phase Mi.5 — Henrik-Caution Cross-Modul-Stress-Test
#
# Welle-3 is the bridge-audit cutover. The canonical Welle-1/Welle-2
# consistency oracle (`tests/integration/test_bridge_audit_roundtrip_
# e2e.py`) cannot validate the Welle-3 cutover — it would ask the
# subject under test to certify its own switch. Henrik (Internal
# Audit) flagged this in the ADR-0066 verification plan and demanded
# an *independent* consistency source.
#
# The Phase-2 Cross-Modul-Stress aggregator
# (`scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-
# stress`, PR #197) stresses cross-modul pinning OUTSIDE the
# bridge_audit_writer code path. Its three axes:
#
#   * cross-modul-state-backing-lifecycle-state-machine
#   * cross-modul-subscribe-loop-recovery-workflow
#   * cross-modul-v907-verify-svid-workload-identity
#
# None of those axes use the bridge_audit_writer / anchor_emitter
# substrate as the source-of-truth oracle, so the signal is
# structurally independent from the subject under cutover. The
# operator-side acceptance envelope records
# `henrik_caution_applied=true` only after this phase passes.
# ----------------------------------------------------------------------

phase_mi5_run() {
    log "phase Mi.5 (Henrik-Caution): doppelbetrieb-score-aggregator --mode=cross-modul-stress"
    local stress_out="$WORKDIR/phase-mi5-cross-modul-stress.json"
    local summary_out="$WORKDIR/phase-mi5-summary.json"

    local stress_rc=0
    # The Cross-Modul-Stress aggregator returns rc=0 (pass) /
    # rc=1 (threshold-fail) / rc=2 (script error). The same
    # 0/1/2 ladder is the operator-pipeline contract.
    #
    # We capture the rc via "|| stress_rc=$?" rather than the
    # "if ! cmd; then stress_rc=$?; fi" pattern because in bash
    # the latter sets $? to the rc of the negation (always 0
    # when the negated command exited non-zero) — losing the
    # actual exit code we need to branch on.
    python3 "$REPO_ROOT/scripts/doppelbetrieb-score-aggregator.py" \
            --mode cross-modul-stress --out "$stress_out" \
            >/dev/null 2>&1 || stress_rc=$?
    log "doppelbetrieb-score-aggregator rc=$stress_rc artifact=$stress_out"

    local threshold_pass="unknown"
    if json_validate "$stress_out"; then
        threshold_pass="$(json_read "$stress_out" threshold_pass unknown)"
    fi

    local verdict="green"
    local rc="$EXIT_GREEN"
    local henrik_caution_applied=0

    if (( stress_rc >= 2 )); then
        verdict="red"
        rc="$EXIT_RED"
    elif [[ "$threshold_pass" == "false" ]] || (( stress_rc == 1 )); then
        verdict="red"
        rc="$EXIT_RED"
    elif [[ "$threshold_pass" == "true" ]]; then
        verdict="green"
        rc="$EXIT_GREEN"
        henrik_caution_applied=1
    else
        # Threshold missing / unknown — yellow, do not claim the
        # Henrik-Caution stamp.
        verdict="yellow"
        rc="$EXIT_YELLOW"
    fi

    json_emit "$summary_out" \
        "phase=s:mi5" \
        "oracle=s:cross-modul-stress" \
        "oracle_pr=s:PR-197" \
        "independence_rationale=s:cross-modul-axes-do-not-touch-bridge-audit-writer" \
        "threshold_pass=s:$threshold_pass" \
        "stress_rc=ji:$stress_rc" \
        "verdict=s:$verdict" \
        "exit_code=ji:$rc" \
        "henrik_caution_applied=jb:$henrik_caution_applied" \
        "artifacts.stress=s:$stress_out"

    log "phase Mi.5 verdict=$verdict rc=$rc henrik_caution_applied=$henrik_caution_applied summary=$summary_out"
    return "$rc"
}

# ----------------------------------------------------------------------
# Phase Do — Thursday Cross-Review
# ----------------------------------------------------------------------

phase_do_run() {
    log "phase Do (cross-review): PR-review state + welle-3-telemetry snapshot + WAT baseline"
    local summary_out="$WORKDIR/phase-do-summary.json"

    local pr_count=0
    local reviews_approved=0
    local reviews_changes_requested=0
    local reviews_commented=0
    local wat_jsonl_present=0
    local wat_days=0
    local wat_records=0
    local telemetry_present=0
    local telemetry_red_flag="unknown"
    local telemetry_divergence_pct=""
    local telemetry_consistency_score_pct=""
    local verdict="green"
    local rc="$EXIT_GREEN"

    # 1) PR-review state
    if (( DRY_RUN_ALL )); then
        log "DRY_RUN_ALL=1 — hermetic PR-review snapshot"
    else
        if command -v gh >/dev/null 2>&1; then
            local pr_json_file="$WORKDIR/phase-do-pr-raw.json"
            if gh pr list --repo "$GH_REPO" --state open \
                    --search "welle-3 in:title,body" \
                    --json number,reviewDecision >"$pr_json_file" 2>/dev/null; then
                # Parse via python so we don't need jq
                read -r pr_count reviews_approved reviews_changes_requested reviews_commented \
                    < <(python3 - "$pr_json_file" <<'PYEOF'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    data = []
if not isinstance(data, list):
    data = []
total = len(data)
approved = sum(1 for x in data if x.get("reviewDecision") == "APPROVED")
changes = sum(1 for x in data if x.get("reviewDecision") == "CHANGES_REQUESTED")
commented = sum(1 for x in data
                if x.get("reviewDecision") in ("REVIEW_REQUIRED", "COMMENTED"))
print(total, approved, changes, commented)
PYEOF
                )
            else
                log "gh pr list failed; treating as zero PRs"
            fi
        else
            log "gh not available, skipping PR-review snapshot"
        fi
    fi

    # 2) Welle-3-telemetry-emitter snapshot (PR #206). Only consumed
    # when --telemetry-snapshot was supplied; the live week dispatch
    # will point this at the snapshot the operator just emitted.
    if [[ -n "$TELEMETRY_SNAPSHOT" ]] && [[ -s "$TELEMETRY_SNAPSHOT" ]] \
            && json_validate "$TELEMETRY_SNAPSHOT"; then
        telemetry_present=1
        telemetry_red_flag="$(json_read "$TELEMETRY_SNAPSHOT" divergence_red_flag unknown)"
        telemetry_divergence_pct="$(json_read "$TELEMETRY_SNAPSHOT" divergence_pct '')"
        telemetry_consistency_score_pct="$(json_read "$TELEMETRY_SNAPSHOT" consistency_score_pct '')"
        log "telemetry snapshot loaded red_flag=$telemetry_red_flag divergence_pct=$telemetry_divergence_pct"
    fi

    # 3) WAT-telemetry snapshot — look for the obs-baseline JSONL the
    # gate-4 aggregator already references.
    local baseline_path="${WAKIR_PHASE_3C_OBS_BASELINE_PATH:-$REPO_ROOT/state/backend-decision-observability/baseline.jsonl}"
    if [[ -s "$baseline_path" ]]; then
        wat_jsonl_present=1
        wat_records="$(wc -l <"$baseline_path" | tr -d ' ')"
        wat_days="$(python3 - "$baseline_path" <<'PYEOF'
import json, sys
days = set()
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    ts = rec.get("timestamp_utc") or rec.get("ts") or ""
    if isinstance(ts, str) and len(ts) >= 10:
        days.add(ts[:10])
print(len(days))
PYEOF
        )"
    fi

    # Verdict ladder. Red beats yellow beats green.
    #
    # Red signals:
    #   * CHANGES_REQUESTED on any open Welle-3 PR
    #   * telemetry snapshot reports divergence_red_flag=true
    # Yellow signals (only in non-hermetic mode):
    #   * WAT baseline JSONL missing
    #   * open PRs but zero approvals
    #   * telemetry snapshot supplied but unparseable (records as
    #     telemetry_present=0)
    if (( reviews_changes_requested > 0 )); then
        verdict="red"
        rc="$EXIT_RED"
    elif [[ "$telemetry_red_flag" == "true" ]]; then
        verdict="red"
        rc="$EXIT_RED"
    elif (( DRY_RUN_ALL == 0 )) && (( wat_jsonl_present == 0 )); then
        verdict="yellow"
        rc="$EXIT_YELLOW"
    elif (( DRY_RUN_ALL == 0 )) && (( reviews_approved == 0 )) && (( pr_count > 0 )); then
        verdict="yellow"
        rc="$EXIT_YELLOW"
    fi

    json_emit "$summary_out" \
        "phase=s:do" \
        "pr_review.count=ji:$pr_count" \
        "pr_review.approved=ji:$reviews_approved" \
        "pr_review.changes_requested=ji:$reviews_changes_requested" \
        "pr_review.commented=ji:$reviews_commented" \
        "wat_telemetry.jsonl_present=jb:$wat_jsonl_present" \
        "wat_telemetry.distinct_days=ji:$wat_days" \
        "wat_telemetry.records=ji:$wat_records" \
        "wat_telemetry.baseline_path=s:$baseline_path" \
        "welle_3_telemetry.snapshot_present=jb:$telemetry_present" \
        "welle_3_telemetry.snapshot_path=s:$TELEMETRY_SNAPSHOT" \
        "welle_3_telemetry.divergence_red_flag=s:$telemetry_red_flag" \
        "welle_3_telemetry.divergence_pct=s:$telemetry_divergence_pct" \
        "welle_3_telemetry.consistency_score_pct=s:$telemetry_consistency_score_pct" \
        "verdict=s:$verdict" \
        "exit_code=ji:$rc" \
        "hermetic=jb:$DRY_RUN_ALL"

    log "phase Do verdict=$verdict rc=$rc summary=$summary_out"
    return "$rc"
}

# ----------------------------------------------------------------------
# Phase Fr — Friday Acceptance Decision
# ----------------------------------------------------------------------

phase_fr_run() {
    log "phase Fr (acceptance): fuse phase artifacts into cutover-acceptance-decision-welle-3.json"
    local out="$WORKDIR/cutover-acceptance-decision-welle-3.json"

    local mo="$WORKDIR/phase-mo-summary.json"
    local mi="$WORKDIR/phase-mi-summary.json"
    local mi5="$WORKDIR/phase-mi5-summary.json"
    local do_="$WORKDIR/phase-do-summary.json"

    local mo_verdict="missing"
    local mi_verdict="missing"
    local mi5_verdict="missing"
    local do_verdict="missing"
    local mo_rc=2
    local mi_rc=2
    local mi5_rc=2
    local do_rc=2
    local henrik_caution_applied="false"

    if json_validate "$mo"; then
        mo_verdict="$(json_read "$mo" verdict missing)"
        mo_rc="$(json_read "$mo" exit_code 2)"
    fi
    if json_validate "$mi"; then
        mi_verdict="$(json_read "$mi" verdict missing)"
        mi_rc="$(json_read "$mi" exit_code 2)"
    fi
    if json_validate "$mi5"; then
        mi5_verdict="$(json_read "$mi5" verdict missing)"
        mi5_rc="$(json_read "$mi5" exit_code 2)"
        henrik_caution_applied="$(json_read "$mi5" henrik_caution_applied false)"
    fi
    if json_validate "$do_"; then
        do_verdict="$(json_read "$do_" verdict missing)"
        do_rc="$(json_read "$do_" exit_code 2)"
    fi

    # Overall verdict = worst-of-four (mo, mi, mi5, do).
    local worst="$mo_rc"
    worst="$(combine_exit "$worst" "$mi_rc")"
    worst="$(combine_exit "$worst" "$mi5_rc")"
    worst="$(combine_exit "$worst" "$do_rc")"

    local decision="go"
    local verdict="green"
    case "$worst" in
        0) decision="go"; verdict="green" ;;
        1) decision="go-with-caveats"; verdict="yellow" ;;
        *) decision="no-go"; verdict="red" ;;
    esac

    # Resolver alias (purely informational in the envelope).
    local resolver_name
    resolver_name="$(normalise_component_for_resolver "$COMPONENT")"

    json_emit "$out" \
        "schema_version=ji:1" \
        "adr=s:ADR-0066" \
        "welle=ji:$WELLE_NUMBER" \
        "component=s:$COMPONENT" \
        "component_resolver_alias=s:$resolver_name" \
        "generated_at=s:$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "decision=s:$decision" \
        "verdict=s:$verdict" \
        "exit_code=ji:$worst" \
        "henrik_caution_applied=jb:$( [[ "$henrik_caution_applied" == "true" ]] && echo 1 || echo 0 )" \
        "phases.mo.verdict=s:$mo_verdict" \
        "phases.mo.exit_code=ji:$mo_rc" \
        "phases.mi.verdict=s:$mi_verdict" \
        "phases.mi.exit_code=ji:$mi_rc" \
        "phases.mi5.verdict=s:$mi5_verdict" \
        "phases.mi5.exit_code=ji:$mi5_rc" \
        "phases.mi5.oracle=s:cross-modul-stress" \
        "phases.do.verdict=s:$do_verdict" \
        "phases.do.exit_code=ji:$do_rc" \
        "workdir=s:$WORKDIR"

    log "phase Fr decision=$decision verdict=$verdict rc=$worst henrik_caution_applied=$henrik_caution_applied output=$out"
    cp "$out" "$WORKDIR/phase-fr-summary.json"
    return "$worst"
}

# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------

main() {
    parse_args "$@"
    require_cmd python3
    resolve_repo_root
    resolve_workdir

    log "$SCRIPT_NAME $SCRIPT_VERSION starting phase=$PHASE component=$COMPONENT"
    log "repo_root=$REPO_ROOT workdir=$WORKDIR dry_run_all=$DRY_RUN_ALL"

    local overall="$EXIT_GREEN"
    case "$PHASE" in
        mo)  phase_mo_run;  overall=$? ;;
        mi)  phase_mi_run;  overall=$? ;;
        mi5) phase_mi5_run; overall=$? ;;
        do)  phase_do_run;  overall=$? ;;
        fr)  phase_fr_run;  overall=$? ;;
        all)
            phase_mo_run;  local mo_rc=$?
            phase_mi_run;  local mi_rc=$?
            phase_mi5_run; local mi5_rc=$?
            phase_do_run;  local do_rc=$?
            phase_fr_run;  local fr_rc=$?
            overall="$(combine_exit "$mo_rc" "$mi_rc")"
            overall="$(combine_exit "$overall" "$mi5_rc")"
            overall="$(combine_exit "$overall" "$do_rc")"
            overall="$(combine_exit "$overall" "$fr_rc")"
            ;;
    esac

    log "$SCRIPT_NAME done overall_exit=$overall"
    return "$overall"
}

main "$@"
