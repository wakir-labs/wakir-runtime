# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Reader for the repo-provenance record.
#
# Why this file exists
# --------------------
#
# The acceptance lanes are the only means this repository has of
# producing live evidence. Until 2026-09-22 they could only ever
# measure one tree -- step 4 of the bootstrap ended with
# ``reset --hard origin/<branch>`` unconditionally, so anything placed
# on the node was gone before the steps under test ran. A change could
# not be measured on the substrate before it was merged.
#
# Step 4 can now be told to pin a ref or to leave the checkout alone.
# That makes the lane able to measure a change before it is merged, and
# it makes a second thing necessary: an acceptance report you cannot
# tell apart from a canonical one is worse than the old state, because
# in the old state you at least knew it was always the branch.
#
# So step 4 measures the tree it ends up with and writes a record; this
# file reads it back and turns it into one of five states. Exactly one
# of them may be quoted as acceptance evidence.
#
#   canonical        HEAD is the origin/<branch> tip, that reference was
#                    refreshed during the run that wrote the record, and
#                    the worktree is clean. Evidence.
#   non-canonical    the tree was measured and is not the branch tip.
#                    The record says why. Not evidence.
#   unmeasured       the comparison did not happen -- most often because
#                    the comparison reference could not be refreshed, so
#                    HEAD would have been compared against a file of
#                    unknown age. A different statement from
#                    non-canonical, and it must not be collapsed into
#                    it. Not evidence.
#   missing          no record -- an older bootstrap on the node, or a
#                    resume that skipped step 4. Not evidence: the tree
#                    is unknown, and unknown is not canonical.
#   stale            a record from a different run. Not evidence, for
#                    the same reason -- it describes some other tree.
#   schema-mismatch  a record this reader does not understand. Not
#                    evidence. Records written before schema @2 land
#                    here on purpose: their `canonical=yes` did not
#                    carry the freshness guarantee, so re-interpreting
#                    one as if it did would be the defect @2 exists to
#                    close.
#
# One writer (bootstrap step 4), one reader (this file). The key set
# they share is pinned by tests/infra/test_acceptance_run_provenance.py
# so the two cannot drift apart into a reader that silently finds
# nothing and calls it missing.
#
# Usage:
#
#   source "${WAKIR_REPO_ROOT}/scripts/lib/repo-provenance.sh"
#   run_id=$(wakir_provenance_new_run_id)
#   WAKIR_PROVENANCE_RUN_ID="$run_id" bash "$bootstrap"
#   wakir_provenance_load "$run_id" || true
#   log "$(wakir_provenance_tree_line)"
#   if wakir_provenance_is_evidence; then ... else exit "$WAKIR_PROVENANCE_NOT_EVIDENCE_RC"; fi
#
# Sandbox boundary: none. This file is pure shell over a local file and
# is driven directly by the hermetic test surface.

# Schema this reader understands. A record that says anything else is
# not interpreted -- guessing at an unknown shape is how a reader ends
# up reporting a default as a measurement.
WAKIR_PROVENANCE_SCHEMA_EXPECTED="wakir-runtime/repo-provenance@2"

# The exit code a lane uses when its run is not acceptance evidence.
# Deliberately not 0 and deliberately not one of the lanes' failure
# codes: "the checks passed but this run does not count" is a third
# outcome, and collapsing it into either of the other two is what this
# whole mechanism exists to prevent.
WAKIR_PROVENANCE_NOT_EVIDENCE_RC=10

wakir_provenance_file() {
  printf '%s' "${WAKIR_REPO_PROVENANCE_FILE:-/var/lib/wakir/bootstrap/repo-provenance.env}"
}

# A nonce for one lane run. The bootstrap writes it into the record and
# this reader requires it back, so a record left by an earlier run
# cannot be read as a statement about this one.
wakir_provenance_new_run_id() {
  printf 'run-%s-%s-%s' \
    "$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || echo unknown)" \
    "$$" \
    "${RANDOM:-0}"
}

# Load the record and classify it. Sets WAKIR_PROVENANCE_STATUS plus the
# WAKIR_PROVENANCE_* fields in the caller's shell. Returns 0 only for a
# record that may be quoted as evidence.
wakir_provenance_load() {
  local expect_run_id="${1:-}"
  local f line key val

  WAKIR_PROVENANCE_STATUS="unknown"
  WAKIR_PROVENANCE_SCHEMA=""
  WAKIR_PROVENANCE_RUN_ID=""
  WAKIR_PROVENANCE_WRITTEN_UTC=""
  WAKIR_PROVENANCE_REPO_ROOT=""
  WAKIR_PROVENANCE_BRANCH=""
  WAKIR_PROVENANCE_REF_MODE=""
  WAKIR_PROVENANCE_REQUESTED_REF=""
  WAKIR_PROVENANCE_HEAD=""
  WAKIR_PROVENANCE_REMOTE_TIP=""
  WAKIR_PROVENANCE_REMOTE_TIP_FRESH=""
  WAKIR_PROVENANCE_WORKTREE=""
  WAKIR_PROVENANCE_CANONICAL=""
  WAKIR_PROVENANCE_REASON=""

  f=$(wakir_provenance_file)

  if [[ ! -r "$f" ]]; then
    WAKIR_PROVENANCE_STATUS="missing"
    WAKIR_PROVENANCE_REASON="no provenance record at ${f}; step 4 of the bootstrap did not write one"
    return 1
  fi

  # Parsed, not sourced. The record is data about a measurement; it does
  # not get to execute in the lane's shell.
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    case "$key" in
      WAKIR_PROVENANCE_SCHEMA|WAKIR_PROVENANCE_RUN_ID|\
WAKIR_PROVENANCE_WRITTEN_UTC|WAKIR_PROVENANCE_REPO_ROOT|\
WAKIR_PROVENANCE_BRANCH|WAKIR_PROVENANCE_REF_MODE|\
WAKIR_PROVENANCE_REQUESTED_REF|WAKIR_PROVENANCE_HEAD|\
WAKIR_PROVENANCE_REMOTE_TIP|WAKIR_PROVENANCE_REMOTE_TIP_FRESH|\
WAKIR_PROVENANCE_WORKTREE|\
WAKIR_PROVENANCE_CANONICAL|WAKIR_PROVENANCE_REASON)
        printf -v "$key" '%s' "$val"
        ;;
      *) : ;;
    esac
  done <"$f"

  if [[ "$WAKIR_PROVENANCE_SCHEMA" != "$WAKIR_PROVENANCE_SCHEMA_EXPECTED" ]]; then
    WAKIR_PROVENANCE_STATUS="schema-mismatch"
    WAKIR_PROVENANCE_REASON="record schema '${WAKIR_PROVENANCE_SCHEMA:-(none)}' is not '${WAKIR_PROVENANCE_SCHEMA_EXPECTED}'"
    return 1
  fi

  if [[ -n "$expect_run_id" && "$WAKIR_PROVENANCE_RUN_ID" != "$expect_run_id" ]]; then
    WAKIR_PROVENANCE_STATUS="stale"
    WAKIR_PROVENANCE_REASON="record belongs to run '${WAKIR_PROVENANCE_RUN_ID:-(none)}', not to this one; it describes some other tree"
    return 1
  fi

  if [[ "$WAKIR_PROVENANCE_CANONICAL" == "yes" ]]; then
    WAKIR_PROVENANCE_STATUS="canonical"
    return 0
  fi

  if [[ "$WAKIR_PROVENANCE_CANONICAL" == "unmeasured" ]]; then
    WAKIR_PROVENANCE_STATUS="unmeasured"
    return 1
  fi

  WAKIR_PROVENANCE_STATUS="non-canonical"
  return 1
}

# Returns 0 only when the loaded record may be quoted as acceptance
# evidence. Call wakir_provenance_load first.
wakir_provenance_is_evidence() {
  [[ "${WAKIR_PROVENANCE_STATUS:-unknown}" == "canonical" ]]
}

# One line, for the run's own output. It is printed whatever the
# outcome: the requirement is not that a deviation be possible, it is
# that a report never leaves the reader guessing which tree produced it.
wakir_provenance_tree_line() {
  case "${WAKIR_PROVENANCE_STATUS:-unknown}" in
    canonical)
      printf 'tree: %s — canonical %s tip, clean worktree (ref-mode=%s)' \
        "$WAKIR_PROVENANCE_HEAD" \
        "$WAKIR_PROVENANCE_BRANCH" \
        "$WAKIR_PROVENANCE_REF_MODE"
      ;;
    unmeasured)
      printf 'tree: %s — NOT MEASURED (ref-mode=%s, requested=%s): %s' \
        "$WAKIR_PROVENANCE_HEAD" \
        "$WAKIR_PROVENANCE_REF_MODE" \
        "$WAKIR_PROVENANCE_REQUESTED_REF" \
        "$WAKIR_PROVENANCE_REASON"
      ;;
    non-canonical)
      printf 'tree: %s — NOT the canonical %s tip (ref-mode=%s, requested=%s): %s' \
        "$WAKIR_PROVENANCE_HEAD" \
        "$WAKIR_PROVENANCE_BRANCH" \
        "$WAKIR_PROVENANCE_REF_MODE" \
        "$WAKIR_PROVENANCE_REQUESTED_REF" \
        "$WAKIR_PROVENANCE_REASON"
      ;;
    *)
      printf 'tree: UNKNOWN (%s): %s' \
        "${WAKIR_PROVENANCE_STATUS:-unknown}" \
        "${WAKIR_PROVENANCE_REASON:-no reason recorded}"
      ;;
  esac
}
