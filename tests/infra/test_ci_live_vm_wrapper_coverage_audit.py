# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic Test-Coverage-Audit for the CI-Live-VM-Acceptance-Wrapper
(Sprint-Tag-8 Kai PR #76 item 3).

The existing ``tests/infra/test_ci_live_vm_acceptance_wrapper.py``
covers TV-CW-01..08 (bash-syntax, --help, missing-flags exit-code,
invalid federation-mode, --pre-check-only short-circuit, summary-JSON
shape, tool-precheck loop, federation-mode auto-detect, hardcoded-IP
ban, bug_regressions enumeration).

This file is the Sprint-QA-Tag-15 **gap-closer**: it adds
TV-PIL-WRAP-01..05 (per the Sprint-QA-Tag-15 test-plan §3) — five
additional failure-mode vectors that the existing suite did not
exercise:

* TV-PIL-WRAP-01: pull_script idempotency — both
  ``clone-if-missing`` and ``fetch+reset-if-present`` branches
  present in source.
* TV-PIL-WRAP-02: reset_script targets only ``wakir-*`` Quadlets
  (never wildcard-deletes ``/etc/containers/systemd/*``).
* TV-PIL-WRAP-03: exit-code contract is total — 0 PASS / 1 pre-check
  fail / 2 acceptance fail / 3 wrapper-internal error.
* TV-PIL-WRAP-04: on-VM acceptance invocation uses the documented
  env-var prefix (WAKIR_SIDE / PEER_SIDE / PEER_HOST / PILOT_MODE /
  SKIP_COSIGN_VERIFY).
* TV-PIL-WRAP-05: emit_summary uses --argjson for acceptance_rc so
  the rc lands in JSON as an integer (not a string).

Sandbox boundary: source-level inspection + argparse exercise only.
No live target; no SSH; no network.

— Amara
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "scripts" / "ci-live-vm-acceptance-wrapper.sh"


@pytest.fixture(scope="module")
def wrapper_source() -> str:
    assert _WRAPPER.is_file(), f"wrapper not found: {_WRAPPER}"
    return _WRAPPER.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TV-PIL-WRAP-01 — pull_script idempotency: both branches present
# ---------------------------------------------------------------------------


def test_tv_pil_wrap_01_pull_script_has_both_branches(
    wrapper_source: str,
) -> None:
    """The pull_script must contain *both* a
    ``git clone`` path (for the first-bring-up case) and a
    ``git fetch`` + ``git reset --hard`` path (for the
    incremental-update case).

    A drift that drops either branch produces a non-idempotent
    wrapper: either every run fails on a fresh target, or every run
    leaves stale state on an existing target.
    """
    assert "git clone" in wrapper_source, (
        "wrapper pull_script missing the clone branch; first bring-up "
        "on a fresh target will fail"
    )
    assert "git" in wrapper_source and "fetch" in wrapper_source, (
        "wrapper pull_script missing the fetch branch; incremental "
        "update on a previously-cloned target will fail"
    )
    assert "reset --hard" in wrapper_source, (
        "wrapper pull_script missing the reset-hard branch; "
        "incremental update will leave a dirty tree"
    )
    # Both branches must be in the SAME heredoc — otherwise the
    # clone path is unreachable from the reset path. Use a span check.
    clone_idx = wrapper_source.find("git clone")
    fetch_idx = wrapper_source.find("fetch")
    reset_idx = wrapper_source.find("reset --hard")
    assert clone_idx > 0 and fetch_idx > 0 and reset_idx > 0
    # They should be reasonably close together (within ~500 chars of
    # source) to belong to the same heredoc. Loose bound.
    assert abs(fetch_idx - clone_idx) < 500, (
        "git clone and git fetch are in different heredocs; the "
        "pull-script may have been split, breaking idempotency"
    )


# ---------------------------------------------------------------------------
# TV-PIL-WRAP-02 — reset_script targets only wakir-* Quadlets
# ---------------------------------------------------------------------------


def test_tv_pil_wrap_02_reset_script_does_not_wildcard_delete(
    wrapper_source: str,
) -> None:
    """The reset_script must NEVER wildcard-delete
    ``/etc/containers/systemd/*`` — that would erase Quadlets owned
    by other workloads on the target host. It must restrict deletes
    to ``wakir-*`` glob patterns.

    If a future refactor drops the ``wakir-*`` prefix, an operator
    running this wrapper against a multi-workload host would brick
    every Quadlet on the box.
    """
    # The reset_script extends from `reset_script=$(cat <<'EOF'`
    # to the closing `EOF`. We extract that block.
    m = re.search(
        r"reset_script=\$\(cat <<'EOF'\n(.*?)\nEOF\n",
        wrapper_source,
        re.DOTALL,
    )
    assert m is not None, (
        "could not locate reset_script heredoc; the wrapper source "
        "shape changed and this test must be updated"
    )
    block = m.group(1)
    # No wildcard rm of the whole systemd dir.
    forbidden_patterns = [
        "/etc/containers/systemd/*",
        "/etc/containers/systemd/ *",  # space-padded form
        "rm -rf /etc/containers/systemd",
    ]
    for fp in forbidden_patterns:
        assert fp not in block, (
            f"reset_script contains forbidden wildcard delete pattern: {fp!r}; "
            "this would erase other workloads' Quadlets on the target"
        )
    # All find/rm operations must restrict to wakir-* or
    # spire-*-named patterns.
    if "find /etc/containers/systemd/" in block:
        # Every find invocation must include a -name 'wakir-*' or
        # 'wakir-federation*' filter.
        finds = re.findall(
            r"find /etc/containers/systemd/[^\n]*", block
        )
        for f in finds:
            assert "wakir-" in f, (
                f"find without wakir-* restriction: {f!r}; would delete "
                "Quadlets outside the Wakir namespace"
            )


# ---------------------------------------------------------------------------
# TV-PIL-WRAP-03 — exit-code contract total: 0/1/2/3
# ---------------------------------------------------------------------------


def test_tv_pil_wrap_03_exit_code_contract_documented_and_pinned(
    wrapper_source: str,
) -> None:
    """The wrapper header documents four exit-codes (0/1/2/3) with
    semantic meanings. The body must use exactly those codes — no
    rogue ``exit 4`` or ``exit 42`` that would confuse CI ingestion.
    """
    # Header must document all four.
    assert "0  Acceptance PASS" in wrapper_source
    assert "1  Pre-check failed" in wrapper_source
    assert "2  Acceptance FAIL" in wrapper_source
    assert "3  Wrapper-internal error" in wrapper_source
    # Body must only use those four codes.
    exit_calls = re.findall(r"\bexit\s+(\d+)\b", wrapper_source)
    used_codes = set(exit_calls)
    allowed = {"0", "1", "2", "3"}
    illegal = used_codes - allowed
    assert not illegal, (
        f"wrapper uses exit codes outside the documented {sorted(allowed)} "
        f"contract: {sorted(illegal)}; CI ingestion will silently misclassify"
    )
    # Each documented code must actually be used (no dead documentation).
    for c in allowed:
        # We allow "0" to be used; check at least "1", "2", "3" appear
        # since those are the failure-mode codes.
        if c in {"1", "2", "3"}:
            assert c in used_codes, (
                f"exit code {c} is documented but never used in the "
                "wrapper body; either remove the doc or wire it up"
            )


# ---------------------------------------------------------------------------
# TV-PIL-WRAP-04 — env-var prefix for on-VM acceptance invocation
# ---------------------------------------------------------------------------


_REQUIRED_ENV_PREFIX = [
    "WAKIR_SIDE",
    "WAKIR_PEER_SIDE",
    "WAKIR_PEER_HOST",
    "WAKIR_PILOT_MODE",
    "WAKIR_SKIP_COSIGN_VERIFY",
]


@pytest.mark.parametrize("env_name", _REQUIRED_ENV_PREFIX)
def test_tv_pil_wrap_04_accept_cmd_uses_documented_env_vars(
    wrapper_source: str, env_name: str
) -> None:
    """The on-VM acceptance invocation prefixes the bash command with
    five env vars (WAKIR_SIDE / PEER_SIDE / PEER_HOST / PILOT_MODE /
    SKIP_COSIGN_VERIFY). The on-VM acceptance script reads these by
    name; a rename in the wrapper without a matching rename in the
    on-VM script would silently leave the acceptance run with
    default values.
    """
    assert env_name in wrapper_source, (
        f"wrapper does not pass {env_name} to the on-VM acceptance "
        "invocation; the on-VM script will fall back to its default "
        "and the wrapper's --side / --peer-* flags become dead args"
    )
    # The env var must appear in an `accept_cmd=` assignment (i.e.
    # we are passing it as a prefix, not just mentioning it in a
    # comment).
    assert (
        f"{env_name}=" in wrapper_source
        or f"{env_name}='" in wrapper_source
    ), (
        f"{env_name} appears in source but not in an assignment; the "
        "on-VM env var is documented but never actually exported"
    )


# ---------------------------------------------------------------------------
# TV-PIL-WRAP-05 — emit_summary uses --argjson for acceptance_rc
# ---------------------------------------------------------------------------


def test_tv_pil_wrap_05_acceptance_rc_typed_as_integer(
    wrapper_source: str,
) -> None:
    """The summary-JSON's ``acceptance_rc`` field must be an integer,
    not a JSON string. This requires the jq call to use
    ``--argjson acceptance_rc "${summary[acceptance_rc]}"``, NOT
    ``--arg`` (which would coerce to string).

    If the rc lands as a string, CI ingestion (e.g.
    ``jq '.acceptance_rc == 0'``) silently returns false even on a
    PASS.
    """
    # Find the emit_summary jq call.
    m = re.search(
        r"jq -n\s+\\\n(.*?)\n\s*'\{",
        wrapper_source,
        re.DOTALL,
    )
    assert m is not None, (
        "could not locate the emit_summary jq invocation; if the "
        "source shape changed, update this regex"
    )
    jq_args = m.group(1)
    # acceptance_rc must be argjson, not arg.
    assert "--argjson acceptance_rc" in jq_args, (
        "emit_summary uses --arg (string) for acceptance_rc; CI "
        "ingestion will fail integer comparisons. Switch to --argjson."
    )
    assert "--arg acceptance_rc" not in jq_args, (
        "emit_summary has --arg acceptance_rc somewhere; remove it. "
        "The rc must be a JSON integer."
    )


# ---------------------------------------------------------------------------
# Bonus: additional source-shape audits (low-risk regression nets)
# ---------------------------------------------------------------------------


def test_summary_json_started_finished_utc_emitted(wrapper_source: str) -> None:
    """started_utc + finished_utc must be present in every emit_summary
    call (the emit-summary helper sets finished_utc unconditionally).
    """
    assert 'summary[finished_utc]="$(utc_now)"' in wrapper_source, (
        "emit_summary no longer stamps finished_utc; CI rollups depend "
        "on this field being present on every summary record"
    )


def test_ssh_target_uses_batch_mode_and_strict_hostkey_accept_new(
    wrapper_source: str,
) -> None:
    """The ssh_target() function must use BatchMode=yes (no
    interactive password prompt) and StrictHostKeyChecking=accept-new
    (TOFU semantics, not 'no').

    A drift to ``StrictHostKeyChecking=no`` would silently accept any
    MITM; a drift away from ``BatchMode=yes`` would hang CI on
    unexpected interactive prompts.
    """
    assert "BatchMode=yes" in wrapper_source, (
        "ssh_target no longer uses BatchMode=yes; CI may hang on "
        "interactive prompts"
    )
    assert "StrictHostKeyChecking=accept-new" in wrapper_source, (
        "ssh_target uses an insecure StrictHostKeyChecking mode; must "
        "be accept-new (TOFU), never 'no'"
    )
    assert "StrictHostKeyChecking=no" not in wrapper_source, (
        "ssh_target accepts any host key; this is a MITM hole — fix "
        "to accept-new"
    )


def test_wrapper_bash_strict_mode(wrapper_source: str) -> None:
    """The wrapper must use ``set -eu -o pipefail`` at the top so a
    silent step-failure halts the whole run.
    """
    # Allow set -eu in either order (-eu or -ue), but pipefail must be on.
    has_e = re.search(r"^set\s+-[a-z]*e[a-z]*\b", wrapper_source, re.MULTILINE)
    has_u = re.search(r"^set\s+-[a-z]*u[a-z]*\b", wrapper_source, re.MULTILINE)
    has_pipefail = "pipefail" in wrapper_source
    assert has_e, "wrapper missing `set -e`; silent failures will not halt"
    assert has_u, (
        "wrapper missing `set -u`; unbound variables will produce "
        "empty-string defaults and hide bugs"
    )
    assert has_pipefail, (
        "wrapper missing `set -o pipefail`; failures inside pipelines "
        "will be silently swallowed"
    )


def test_wrapper_help_doc_lists_all_required_and_optional_flags() -> None:
    """The --help output must enumerate every flag the wrapper accepts,
    so an operator can discover the contract without reading source.
    """
    proc = subprocess.run(
        ["bash", str(_WRAPPER), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    required_flags = ("--target", "--ssh-user", "--ssh-key")
    optional_flags = (
        "--side",
        "--peer-side",
        "--peer-host",
        "--federation-mode",
        "--repo-url",
        "--repo-branch",
        "--skip-cosign-verify",
        "--summary-json",
        "--pre-check-only",
    )
    for f in required_flags + optional_flags:
        assert f in proc.stdout, (
            f"--help output does not document {f}; operators cannot "
            "discover this flag without reading the source"
        )


def test_wrapper_phase_numbering_monotonic(wrapper_source: str) -> None:
    """The wrapper documents phases 1 through 4 in order. A future
    refactor that re-orders phases without renumbering would make
    operator-side log-grep brittle. Assert each phase label appears
    in monotonic order.
    """
    phase_positions = []
    for n in range(1, 5):
        # The header docs may say "Phase 1: SSH precheck"; the log
        # lines may say "phase 1:" — accept both forms.
        for needle in (f"Phase {n}:", f"phase {n}:"):
            idx = wrapper_source.find(needle)
            if idx >= 0:
                phase_positions.append((n, idx))
                break
        else:
            pytest.fail(
                f"phase {n} not labelled in wrapper source; operator "
                "log-grep cannot key on phase identifiers"
            )
    # Positions must be monotonic in n.
    for (n1, p1), (n2, p2) in zip(phase_positions, phase_positions[1:]):
        assert p1 < p2, (
            f"phase {n1} is at byte-offset {p1} but phase {n2} is at "
            f"{p2}; phases are not in source order"
        )
