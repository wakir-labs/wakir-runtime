# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Sprint-10 Tag-8 Bug-38 substance fix.

Anlass — Live-VM-Acceptance against wakir-orbit 2026-05-15 ~21:45
CEST (Mira-Hand, Kai-Tag-7 Bug-36+37 deployment). Bootstrap-re-run
PASS and the smoke 6/6 PASS, but
``scripts/federation-live-vm-acceptance.sh`` Phase-2 FAILed at
``wakir-spire-server.service is not active`` because the script
hard-coded the single-org unit names. The two federation-substance
smoke checks (federation-bundle-sync-reachable +
federation-cross-trust-domain-verify) SKIPped because the script did
NOT export WAKIR_FEDERATION_MODE=enabled nor pass --peer-side.

Bug-38 — TWO sub-bugs in one cleanup PR:

* **Bug-38a — Acceptance-Script Service-Naming-Drift.** Phase 2 of
  ``scripts/federation-live-vm-acceptance.sh`` checked
  ``wakir-spire-server.service`` / ``wakir-spire-agent.service``,
  which only exist in single-org-mode. In federation-mode the Quadlet
  unit names are side-suffixed:
  ``wakir-spire-server-federation-${WAKIR_SIDE}.service`` and
  ``wakir-spire-agent-${WAKIR_SIDE}.service`` (mirror of the smoke
  CLI L325/326 convention). The acceptance script now uses
  ``WAKIR_SIDE`` to resolve the federation unit names; agent-unit
  check is added as Bug-37 substance-acceptance.

* **Bug-38b — Smoke federation-mode-gate not activated.** The smoke
  CLI gates the two Sprint-10 Tag-1 substance checks
  (federation-bundle-sync-reachable, federation-cross-trust-domain-
  verify) on ``WAKIR_FEDERATION_MODE=enabled`` env-var AND
  ``--peer-side`` CLI-arg. Neither was passed by the acceptance
  script's Phase-3, nor by ``step_8_smoke()`` in the bootstrap when
  running ``WAKIR_PILOT_MODE=federation``. Both checks always
  SKIPped, which defeated the purpose of running the smoke inside a
  federation-mode acceptance lane. Bootstrap step-8 now auto-forwards
  ``WAKIR_FEDERATION_MODE=enabled`` + ``--peer-side $WAKIR_PEER_SIDE``
  in federation-mode (single-org behaviour unchanged). The
  acceptance script's Phase-3 does the same.

Sandbox boundary
----------------

Source-file inspection only. No podman, no systemctl, no live VM —
see ``feedback_sandbox_host_trennung.md``. The Live-VM acceptance
lane that exercises this cleanup remains
``scripts/federation-live-vm-acceptance.sh`` (Operator-Hand on the
Pilot-VM, re-run after merge per the Tag-8 brief).

Test-Vector index
-----------------

Bug-38a acceptance-script service-naming (5 vectors):

* ``TV-BUG-38A-01`` Phase-2 server-unit is side-suffixed.
* ``TV-BUG-38A-02`` Phase-2 agent-unit is side-suffixed and actually
  checked (Bug-37 substance-acceptance — agent must not restart-loop
  on join-token misconfiguration).
* ``TV-BUG-38A-03`` Hard-coded single-org unit names (no side suffix)
  have been removed from Phase-2.
* ``TV-BUG-38A-04`` Phase-2 ``journalctl -u ...`` log-scan also
  targets the side-suffixed server unit.
* ``TV-BUG-38A-05`` The acceptance script is ``bash -n``-clean.

Bug-38b smoke-federation-mode-gate (5 vectors):

* ``TV-BUG-38B-01`` Acceptance-script Phase-3 exports
  ``WAKIR_FEDERATION_MODE=enabled``.
* ``TV-BUG-38B-02`` Acceptance-script Phase-3 passes ``--peer-side``.
* ``TV-BUG-38B-03`` Bootstrap ``step_8_smoke()`` auto-forwards
  ``WAKIR_FEDERATION_MODE=enabled`` in federation-mode.
* ``TV-BUG-38B-04`` Bootstrap ``step_8_smoke()`` auto-forwards
  ``--peer-side $WAKIR_PEER_SIDE`` in federation-mode.
* ``TV-BUG-38B-05`` Bootstrap ``step_8_smoke()`` does NOT pass either
  in single-org mode (backwards compat invariant).

Bug-38 documentation anchor (1 vector):

* ``TV-BUG-38-DOC-01`` The acceptance script header + summary block
  document the Sprint-10 Tag-8 Bug-38 lineage.

-- Tomás
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ACCEPTANCE = _REPO_ROOT / "scripts" / "federation-live-vm-acceptance.sh"
_BOOTSTRAP = _REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"


@pytest.fixture(scope="module")
def acceptance_source() -> str:
    assert _ACCEPTANCE.is_file(), (
        f"acceptance script not found: {_ACCEPTANCE}"
    )
    return _ACCEPTANCE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bootstrap_source() -> str:
    assert _BOOTSTRAP.is_file(), (
        f"bootstrap script not found: {_BOOTSTRAP}"
    )
    return _BOOTSTRAP.read_text(encoding="utf-8")


def _extract_acceptance_phase_2(source: str) -> str:
    """Body of Phase 2 (between the Phase-2 banner and the Phase-3
    banner)."""
    start = source.find("# --- Phase 2:")
    assert start > 0, "Phase 2 banner not found"
    end = source.find("# --- Phase 3:", start)
    assert end > start, "Phase 3 banner not found"
    return source[start:end]


def _extract_acceptance_phase_3(source: str) -> str:
    """Body of Phase 3 (between Phase-3 banner and Acceptance-summary
    banner)."""
    start = source.find("# --- Phase 3:")
    assert start > 0, "Phase 3 banner not found"
    end = source.find("# --- Acceptance summary", start)
    assert end > start, "Acceptance-summary banner not found"
    return source[start:end]


def _extract_step_8_smoke(source: str) -> str:
    """Body of ``step_8_smoke()`` in the bootstrap (from the function
    header through the closing brace at column 0)."""
    start = source.find("step_8_smoke()")
    assert start > 0, "step_8_smoke() function not found"
    after = source[start:]
    m = re.search(r"\n\}\s*\n", after)
    assert m, "step_8_smoke() closing brace not found"
    return after[: m.end()]


# ---------------------------------------------------------------------------
# TV-BUG-38A-05 + bootstrap syntax invariant.
# ---------------------------------------------------------------------------


def test_acceptance_script_bash_syntax_clean() -> None:
    """``bash -n`` must accept the acceptance script after the Bug-38a
    edits."""
    rc = subprocess.run(
        ["bash", "-n", str(_ACCEPTANCE)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, f"bash -n failed: stderr={rc.stderr!r}"


def test_bootstrap_bash_syntax_clean_tag8() -> None:
    """``bash -n`` must accept the bootstrap after the Bug-38b edits."""
    rc = subprocess.run(
        ["bash", "-n", str(_BOOTSTRAP)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, f"bash -n failed: stderr={rc.stderr!r}"


# ---------------------------------------------------------------------------
# TV-BUG-38A-01: Phase-2 server-unit is side-suffixed.
# ---------------------------------------------------------------------------


def test_phase_2_server_unit_is_side_suffixed(acceptance_source: str) -> None:
    """The Tag-6 hard-coded ``wakir-spire-server.service`` (no side
    suffix) does not exist in federation-mode. Phase-2 must resolve
    the federation-mode unit name via WAKIR_SIDE."""
    phase_2 = _extract_acceptance_phase_2(acceptance_source)
    assert "wakir-spire-server-federation-${WAKIR_SIDE}.service" in phase_2, (
        "Phase 2 must reference the side-suffixed federation server-unit "
        "name (mirror of the smoke CLI L325 convention)."
    )


# ---------------------------------------------------------------------------
# TV-BUG-38A-02: Phase-2 agent-unit is side-suffixed and checked.
# ---------------------------------------------------------------------------


def test_phase_2_agent_unit_is_side_suffixed_and_checked(
    acceptance_source: str,
) -> None:
    """Bug-37 substance-acceptance: the agent unit must be active too.
    Tag-6's acceptance script never checked the agent unit at all."""
    phase_2 = _extract_acceptance_phase_2(acceptance_source)
    assert "wakir-spire-agent-${WAKIR_SIDE}.service" in phase_2, (
        "Phase 2 must reference the side-suffixed federation agent-unit "
        "name (Bug-37 substance-acceptance surface)."
    )
    # Must actually be passed to systemctl is-active.
    assert re.search(
        r'systemctl is-active --quiet "\$agent_unit"', phase_2
    ), (
        "Phase 2 must call systemctl is-active on the agent unit, not "
        "just reference the name in a comment."
    )


# ---------------------------------------------------------------------------
# TV-BUG-38A-03: Hard-coded single-org unit names removed from Phase-2.
# ---------------------------------------------------------------------------


def _strip_shell_comments(body: str) -> str:
    """Return only the executable shell lines from a bash body.

    Drops full-line comments (lines whose first non-whitespace char is
    ``#``). Inline ``#`` comments after code stay — they are uncommon
    in this codebase and conservatively counted. The goal is to keep
    rationale-comments from triggering false-positives in invariant
    checks that target executable shell tokens.
    """
    out_lines = []
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def test_phase_2_no_hardcoded_single_org_unit_names(
    acceptance_source: str,
) -> None:
    """The Tag-6 bare ``wakir-spire-server.service`` /
    ``wakir-spire-agent.service`` literals MUST NOT appear in
    EXECUTABLE shell lines of Phase 2 any more — those only exist
    in single-org-mode. Rationale comments that quote the literals
    for context are allowed."""
    phase_2_code = _strip_shell_comments(
        _extract_acceptance_phase_2(acceptance_source)
    )
    bad_server = re.search(r"\bwakir-spire-server\.service\b", phase_2_code)
    assert bad_server is None, (
        "Phase 2 still references the bare ``wakir-spire-server.service`` "
        "literal in an executable shell line — use ``$server_unit`` "
        "(side-suffixed) instead."
    )
    bad_agent = re.search(r"\bwakir-spire-agent\.service\b", phase_2_code)
    assert bad_agent is None, (
        "Phase 2 still references the bare ``wakir-spire-agent.service`` "
        "literal in an executable shell line — use ``$agent_unit`` "
        "(side-suffixed) instead."
    )


# ---------------------------------------------------------------------------
# TV-BUG-38A-04: journalctl log-scan targets the side-suffixed unit.
# ---------------------------------------------------------------------------


def test_phase_2_journalctl_uses_side_suffixed_unit(
    acceptance_source: str,
) -> None:
    """The Bug-30..32 regression-surface log scan must point at the
    side-suffixed unit. Otherwise ``journalctl -u
    wakir-spire-server.service`` returns empty on a federation-mode
    VM and silently misses a real regression."""
    phase_2 = _extract_acceptance_phase_2(acceptance_source)
    assert re.search(r'journalctl -u "\$server_unit"', phase_2), (
        "Phase 2's ``journalctl`` invocations must use the resolved "
        "``$server_unit`` variable, not the bare single-org literal."
    )


# ---------------------------------------------------------------------------
# TV-BUG-38B-01: Acceptance-script Phase-3 exports
# WAKIR_FEDERATION_MODE=enabled.
# ---------------------------------------------------------------------------


def test_phase_3_exports_federation_mode_env(
    acceptance_source: str,
) -> None:
    """Without WAKIR_FEDERATION_MODE=enabled the smoke CLI SKIPs both
    Sprint-10 Tag-1 federation-substance checks."""
    phase_3 = _extract_acceptance_phase_3(acceptance_source)
    assert "WAKIR_FEDERATION_MODE=enabled" in phase_3, (
        "Phase 3 must export WAKIR_FEDERATION_MODE=enabled so the "
        "federation-bundle-sync-reachable + federation-cross-trust-"
        "domain-verify checks actually run."
    )


# ---------------------------------------------------------------------------
# TV-BUG-38B-02: Acceptance-script Phase-3 passes --peer-side.
# ---------------------------------------------------------------------------


def test_phase_3_passes_peer_side(acceptance_source: str) -> None:
    """The two federation-substance checks ALSO require ``--peer-side``
    on the smoke CLI."""
    phase_3 = _extract_acceptance_phase_3(acceptance_source)
    assert "--peer-side" in phase_3, (
        "Phase 3 must pass --peer-side to the smoke invocation."
    )
    assert '"$WAKIR_PEER_SIDE"' in phase_3, (
        "Phase 3 must thread the WAKIR_PEER_SIDE env-var into the "
        "--peer-side flag."
    )


# ---------------------------------------------------------------------------
# TV-BUG-38B-03 + TV-BUG-38B-04: Bootstrap step_8_smoke auto-forwards
# in federation-mode.
# ---------------------------------------------------------------------------


def test_step_8_forwards_fed_mode_env(bootstrap_source: str) -> None:
    """When WAKIR_PILOT_MODE=federation and WAKIR_PEER_SIDE is set,
    step_8_smoke must export WAKIR_FEDERATION_MODE=enabled."""
    step_8 = _extract_step_8_smoke(bootstrap_source)
    assert "WAKIR_FEDERATION_MODE=enabled" in step_8, (
        "step_8_smoke must export WAKIR_FEDERATION_MODE=enabled in "
        "federation-mode."
    )
    assert re.search(r'WAKIR_PILOT_MODE"\s*==\s*"federation"', step_8), (
        "step_8_smoke must guard the WAKIR_FEDERATION_MODE=enabled "
        "export with a check on WAKIR_PILOT_MODE."
    )


def test_step_8_forwards_peer_side_flag(bootstrap_source: str) -> None:
    """step_8_smoke must forward --peer-side $WAKIR_PEER_SIDE to the
    smoke binary in federation-mode."""
    step_8 = _extract_step_8_smoke(bootstrap_source)
    assert "--peer-side" in step_8, (
        "step_8_smoke must pass --peer-side to the smoke binary in "
        "federation-mode."
    )
    assert '"$WAKIR_PEER_SIDE"' in step_8, (
        "step_8_smoke must thread WAKIR_PEER_SIDE into the --peer-side "
        "CLI argument."
    )


# ---------------------------------------------------------------------------
# TV-BUG-38B-05: Single-org backwards-compat invariant.
# ---------------------------------------------------------------------------


def test_step_8_single_org_backwards_compat(bootstrap_source: str) -> None:
    """In single-org mode (WAKIR_PILOT_MODE != federation), step_8_smoke
    must NOT pass --peer-side and must NOT export
    WAKIR_FEDERATION_MODE=enabled in EXECUTABLE shell lines — both
    were absent in the Sprint-9 baseline. Rationale comments that
    mention the tokens for context are allowed."""
    step_8 = _extract_step_8_smoke(bootstrap_source)
    guard_idx = step_8.find('WAKIR_PILOT_MODE"')
    assert guard_idx > 0, "federation-mode guard not found in step_8_smoke"
    fi_idx = step_8.find("\n  fi", guard_idx)
    assert fi_idx > guard_idx, "closing fi of federation-mode guard not found"
    guarded_block = step_8[guard_idx:fi_idx]
    assert "--peer-side" in guarded_block, (
        "--peer-side must live INSIDE the federation-mode guard."
    )
    assert "WAKIR_FEDERATION_MODE=enabled" in guarded_block, (
        "WAKIR_FEDERATION_MODE=enabled must live INSIDE the "
        "federation-mode guard."
    )
    outside_code = _strip_shell_comments(
        step_8[:guard_idx] + step_8[fi_idx:]
    )
    assert "--peer-side" not in outside_code, (
        "--peer-side must not appear in the single-org unconditional "
        "smoke invocation path (executable shell lines)."
    )
    assert "WAKIR_FEDERATION_MODE=enabled" not in outside_code, (
        "WAKIR_FEDERATION_MODE=enabled must not appear in the single-"
        "org unconditional smoke invocation path (executable shell lines)."
    )


# ---------------------------------------------------------------------------
# TV-BUG-38-DOC-01: Header / summary documentation anchor.
# ---------------------------------------------------------------------------


def test_acceptance_script_documents_bug_38_lineage(
    acceptance_source: str,
) -> None:
    """A future operator inspecting the acceptance script must see the
    Bug-38 cleanup mentioned in the header AND the summary block —
    otherwise the cleanup rationale is invisible without git-log
    archaeology."""
    header = "\n".join(acceptance_source.splitlines()[:60])
    assert "Bug-38" in header or "Tag-8" in header, (
        "Acceptance script header must reference the Sprint-10 Tag-8 "
        "Bug-38 cleanup for trace-back."
    )
    assert "Bug-38" in acceptance_source, (
        "Acceptance summary block should call out Bug-38 in the "
        "regression-tested list."
    )
