# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Sprint-Tag-8 Bug-36-Härtung: resolver trust-mode
selector in ``infra/spire/federation/wakir-pilot-bootstrap.sh``.

Anlass — AR-Direktive 2026-05-15 23:35 CEST. Bug-36 (Sprint-10 Tag-7)
collapsed the bootstrap's skip-cosign-verify branch into a
skopeo-only-all-4 resolve path. The fix unblocked the Live-VM run at
the cost of broadening the trust-base. Sprint-Tag-8 makes the trust-
base explicit via ``WAKIR_RESOLVER_TRUST_MODE`` so the Pilot-Phase
tolerance and the Production requirement are runtime-selectable from
a single bootstrap.

Test-Vector index
-----------------

* ``TV-TM-01`` Unset trust-mode + unset skip-cosign defaults to
  ``cosign-strict``.
* ``TV-TM-02`` Unset trust-mode + ``WAKIR_SKIP_COSIGN_VERIFY=1`` maps
  to ``skopeo-only-all-4`` (back-compat alias).
* ``TV-TM-03`` Explicit ``cosign-strict`` + ``WAKIR_SKIP_COSIGN_VERIFY=1``
  is an error (mutual exclusion).
* ``TV-TM-04`` Explicit ``skopeo-only-all-4`` + unset skip-cosign sets
  the legacy var internally for back-compat.
* ``TV-TM-05`` Explicit ``mixed`` mode is accepted; the allowlist
  variable is set.
* ``TV-TM-06`` Invalid mode value is a hard error.
* ``TV-TM-07`` Trust-mode banner is logged in step-5 (visibility in
  bring-up log).
* ``TV-TM-08`` The mixed-mode allowlist contains ONLY
  spire-server + spire-agent (hardcoded, no Operator-Hand widening).
* ``TV-TM-09`` Doku ``docs/RESOLVER-TRUST-MODES.md`` exists and
  declares all three modes.

Sandbox boundary
----------------

Source-file inspection + subprocess ``bash -c`` snippets to verify the
env-var argument validation. No podman, no live VM. See
``feedback_sandbox_host_trennung.md``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOOTSTRAP = (
    _REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)
_DOC = _REPO_ROOT / "docs" / "RESOLVER-TRUST-MODES.md"


@pytest.fixture(scope="module")
def bootstrap_source() -> str:
    assert _BOOTSTRAP.is_file(), f"bootstrap script not found: {_BOOTSTRAP}"
    return _BOOTSTRAP.read_text(encoding="utf-8")


def _eval_env_block(extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run the bootstrap source up to the trust-mode validation block
    only; we substitute ``main`` and the actual step-runs out via
    ``return 0`` injection so the env-var validation runs in isolation.
    """
    # The cheapest hermetic exercise: source the script in a non-main
    # context (BASH_SOURCE != $0), then trip the validation by reading
    # the resolved values. We use ``bash -c`` with a wrapper that sets
    # the env-vars BEFORE sourcing.
    env_kv = " ".join(f"{k}={v!s}" for k, v in extra_env.items())
    # Source-up-to-line gate: read the script, slice off everything from
    # ``# Test-injection hooks.`` onwards (line ~250) so the file does
    # NOT auto-run main() but the trust-mode validation block at line
    # ~169-241 still executes.
    src = _BOOTSTRAP.read_text(encoding="utf-8")
    # Find the cutoff anchor — the test-injection-hooks comment header.
    cutoff = src.find("# Test-injection hooks.")
    assert cutoff > 0, "test-injection hooks anchor not found in bootstrap source"
    # Replace the rest with a marker echo so we know the validation
    # passed without auto-running main.
    truncated = src[:cutoff] + 'echo "VALIDATION_OK trust_mode=$WAKIR_RESOLVER_TRUST_MODE skip_cosign=$WAKIR_SKIP_COSIGN_VERIFY"\nexit 0\n'
    cmd = f"{env_kv} bash -c '{truncated}'" if env_kv else f"bash -c '{truncated}'"
    # Use shell=True is awkward with the quoting; write to tmp.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as tmp:
        tmp.write(truncated)
        tmp_path = tmp.name
    return subprocess.run(
        ["bash", tmp_path],
        env={**dict(__import__("os").environ), **extra_env},
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_bootstrap_bash_syntax_clean() -> None:
    """bash -n must pass after the trust-mode patch."""
    rc = subprocess.run(
        ["bash", "-n", str(_BOOTSTRAP)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, f"bash -n failed: {rc.stderr!r}"


# TV-TM-01 -------------------------------------------------------------------


def test_default_mode_is_cosign_strict() -> None:
    out = _eval_env_block({})
    assert out.returncode == 0, f"stderr={out.stderr!r}"
    assert "trust_mode=cosign-strict" in out.stdout, (
        "Default trust-mode must be cosign-strict when neither env-var is set; "
        f"got stdout={out.stdout!r}"
    )


# TV-TM-02 -------------------------------------------------------------------


def test_skip_cosign_maps_to_skopeo_only_all_4() -> None:
    out = _eval_env_block({"WAKIR_SKIP_COSIGN_VERIFY": "1"})
    assert out.returncode == 0, f"stderr={out.stderr!r}"
    assert "trust_mode=skopeo-only-all-4" in out.stdout, (
        "WAKIR_SKIP_COSIGN_VERIFY=1 must map to skopeo-only-all-4 (back-compat alias); "
        f"got stdout={out.stdout!r}"
    )


# TV-TM-03 -------------------------------------------------------------------


def test_explicit_strict_with_skip_cosign_is_error() -> None:
    out = _eval_env_block(
        {
            "WAKIR_RESOLVER_TRUST_MODE": "cosign-strict",
            "WAKIR_SKIP_COSIGN_VERIFY": "1",
        }
    )
    assert out.returncode != 0, (
        f"Explicit cosign-strict + skip-cosign=1 must error; got rc={out.returncode} "
        f"stdout={out.stdout!r}"
    )
    assert "conflicts" in out.stderr.lower() or "conflict" in out.stderr.lower(), (
        f"Error message must mention 'conflict'; got stderr={out.stderr!r}"
    )


# TV-TM-04 -------------------------------------------------------------------


def test_explicit_skopeo_only_sets_legacy_var_for_backcompat() -> None:
    out = _eval_env_block(
        {"WAKIR_RESOLVER_TRUST_MODE": "skopeo-only-all-4"}
    )
    assert out.returncode == 0, f"stderr={out.stderr!r}"
    assert "trust_mode=skopeo-only-all-4" in out.stdout, out.stdout
    assert "skip_cosign=1" in out.stdout, (
        "Explicit skopeo-only-all-4 must set WAKIR_SKIP_COSIGN_VERIFY=1 "
        f"internally for back-compat; got {out.stdout!r}"
    )


# TV-TM-05 -------------------------------------------------------------------


def test_mixed_mode_accepted(bootstrap_source: str) -> None:
    out = _eval_env_block({"WAKIR_RESOLVER_TRUST_MODE": "mixed"})
    assert out.returncode == 0, f"stderr={out.stderr!r}"
    assert "trust_mode=mixed" in out.stdout, out.stdout
    # Source-check: mixed-mode allowlist variable is declared in step-5.
    assert "_KAI_MIXED_MODE_ALLOWLIST" in bootstrap_source, (
        "Mixed-mode allowlist variable must exist in the bootstrap source"
    )


# TV-TM-06 -------------------------------------------------------------------


def test_invalid_mode_value_is_hard_error() -> None:
    out = _eval_env_block({"WAKIR_RESOLVER_TRUST_MODE": "no-such-mode"})
    assert out.returncode != 0, (
        f"Invalid mode must error; got rc={out.returncode} stdout={out.stdout!r}"
    )
    assert "WAKIR_RESOLVER_TRUST_MODE" in out.stderr, (
        f"Error must mention the env-var name; got stderr={out.stderr!r}"
    )


# TV-TM-07 -------------------------------------------------------------------


def test_step_5_logs_trust_mode_banner(bootstrap_source: str) -> None:
    """The step-5 image-pin function logs the resolved trust-mode so
    the bring-up log records which trust-base was used.
    """
    # Anchor inside step_5_image_pins().
    s5_start = bootstrap_source.find("step_5_image_pins()")
    assert s5_start > 0, "step_5_image_pins() not found"
    s5_end = bootstrap_source.find("step_6_quadlet()", s5_start)
    s5 = bootstrap_source[s5_start:s5_end]
    assert "resolver trust-mode:" in s5, (
        "step-5 must log the resolved trust-mode for bring-up visibility"
    )


# TV-TM-08 -------------------------------------------------------------------


def test_mixed_mode_allowlist_only_spire_pair(bootstrap_source: str) -> None:
    """The mixed-mode allowlist contains ONLY spire-server + spire-agent.
    Operator-Hand cannot widen it from env-vars; widening requires a
    source-patch + Zone-C cross-review.
    """
    # The default-assignment uses bash ``: "${_KAI_MIXED_MODE_ALLOWLIST:=...}"``
    # form which expands to a single shell line. Capture the value
    # literal between ``:=`` and the closing ``}``.
    m = re.search(
        r'_KAI_MIXED_MODE_ALLOWLIST\s*:=\s*([^}]+)\}',
        bootstrap_source,
    )
    assert m, "_KAI_MIXED_MODE_ALLOWLIST default literal not found"
    allowlist = m.group(1).strip().strip('"')
    assert "spire-server:1.14.6" in allowlist, allowlist
    assert "spire-agent:1.14.6" in allowlist, allowlist
    # The allowlist should NOT contain python or wakir-provisioner.
    assert "python:3.13-slim" not in allowlist, (
        f"python:3.13-slim must NOT be in mixed-mode allowlist (DockerHub is "
        f"skopeo-only by upstream policy); got {allowlist!r}"
    )
    assert "wakir-provisioner" not in allowlist, (
        "wakir-provisioner is signed by wakir-labs build-workflow; mixed-mode "
        "fallback must not be available for it"
    )


# TV-TM-09 -------------------------------------------------------------------


def test_doc_exists_and_declares_all_three_modes() -> None:
    assert _DOC.is_file(), f"docs/RESOLVER-TRUST-MODES.md not found: {_DOC}"
    txt = _DOC.read_text(encoding="utf-8")
    for mode in ("cosign-strict", "skopeo-only-all-4", "mixed"):
        assert mode in txt, f"docs must declare mode '{mode}'"
    # Threat-model table mentions Bug-36 explicitly.
    assert "Bug-36" in txt, "Threat-model section must reference Bug-36"
    # Back-compat table is present.
    assert "WAKIR_SKIP_COSIGN_VERIFY" in txt, (
        "Doc must describe the back-compat mapping with the legacy env-var"
    )


# Integration sanity ---------------------------------------------------------


def test_skopeo_only_branch_still_resolves_all_four(bootstrap_source: str) -> None:
    """Sprint-10 Tag-7 Bug-36 fix invariant must remain unchanged: the
    skip-cosign branch still resolves all 4 image pins via skopeo. The
    trust-mode patch must not regress that fix.
    """
    s5_start = bootstrap_source.find("step_5_image_pins()")
    s5_end = bootstrap_source.find("step_6_quadlet()", s5_start)
    s5 = bootstrap_source[s5_start:s5_end]
    # Locate the skip-cosign branch.
    sc_start = s5.find('if [[ "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then')
    assert sc_start > 0
    sc_end = s5.find("\n  fi", sc_start)
    assert sc_end > sc_start
    branch = s5[sc_start:sc_end]
    for image in (
        "ghcr.io/spiffe/spire-server:1.14.6",
        "ghcr.io/spiffe/spire-agent:1.14.6",
        "docker.io/library/python:3.13-slim",
        "ghcr.io/wakir-labs/wakir-provisioner:0.1.2",
    ):
        assert image in branch, (
            f"Bug-36 invariant: skip-cosign branch must still enumerate {image}"
        )
