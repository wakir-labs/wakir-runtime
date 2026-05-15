# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Sprint-Tag-8 Bug-39 Option-A substrate:
bilateral-federation-handshake-precheck (`step_15_bilateral_precheck`)
in `infra/spire/federation/wakir-pilot-bootstrap.sh`, and the Option-B
decision-note at `docs/decisions/topology-bilateral-federation.md`.

Anlass — AR-Direktive 2026-05-15 23:35 CEST. Bug-39 surfaced from
Tag-13/14 Live-VM-Acceptance: the Cross-VM-Federation 8/8 smoke
requires BOTH peer VMs to be in federation-mode, but the Pilot
topology is asymmetric (wakir-pilot single-org, wakir-orbit
federation). Two options ship in this PR as substrate:

* Option A — Pilot-Symmetric (step_15 precheck, gated on
  WAKIR_BILATERAL_PRECHECK=1).
* Option B — Sprint-12+ Production-Setup-Item (decision-note).

Test-Vector index
-----------------

* ``TV-B39-A-01`` Bootstrap env-var default ``WAKIR_BILATERAL_PRECHECK=0``
  declared in the script (Option-B is the default).
* ``TV-B39-A-02`` ``step_15_bilateral_precheck`` function defined.
* ``TV-B39-A-03`` step_15 is no-op when WAKIR_BILATERAL_PRECHECK!=1.
* ``TV-B39-A-04`` step_15 rejects single-org-mode (the precheck only
  makes sense AFTER the flip).
* ``TV-B39-A-05`` step_15 rejects missing peer-side or peer-host.
* ``TV-B39-A-06`` step_15 invokes the TCP/8443 reachability probe
  against the peer.
* ``TV-B39-A-07`` step_15 records the persona re-spawn-window (or
  warns if unset).
* ``TV-B39-A-08`` step_15 is wired into main() AFTER step_8_smoke.
* ``TV-B39-B-09`` Decision-note exists at
  docs/decisions/topology-bilateral-federation.md.
* ``TV-B39-B-10`` Decision-note declares both options A and B,
  explicit Cons + Pros sections, and references the
  WAKIR_BILATERAL_PRECHECK runtime selector.
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
_DECISION_NOTE = (
    _REPO_ROOT / "docs" / "decisions" / "topology-bilateral-federation.md"
)


@pytest.fixture(scope="module")
def bootstrap_source() -> str:
    assert _BOOTSTRAP.is_file()
    return _BOOTSTRAP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def decision_note_text() -> str:
    assert _DECISION_NOTE.is_file(), f"decision note not found: {_DECISION_NOTE}"
    return _DECISION_NOTE.read_text(encoding="utf-8")


# TV-B39-A-01 -----------------------------------------------------------------


def test_default_bilateral_precheck_off(bootstrap_source: str) -> None:
    """Option-B is the default; existing bring-ups must remain byte-
    stable in their behaviour."""
    assert ': "${WAKIR_BILATERAL_PRECHECK:=0}"' in bootstrap_source, (
        "WAKIR_BILATERAL_PRECHECK must default to 0 (Option-B)"
    )


# TV-B39-A-02 -----------------------------------------------------------------


def test_step_15_function_defined(bootstrap_source: str) -> None:
    assert "step_15_bilateral_precheck()" in bootstrap_source, (
        "step_15_bilateral_precheck function must be defined"
    )


# TV-B39-A-03 -----------------------------------------------------------------


def test_step_15_noop_when_disabled(bootstrap_source: str) -> None:
    """The no-op short-circuit check must be the first thing in the
    function body."""
    # Find the function body.
    start = bootstrap_source.find("step_15_bilateral_precheck()")
    end = bootstrap_source.find("\n}", start)
    body = bootstrap_source[start:end]
    # First non-comment instruction must be the WAKIR_BILATERAL_PRECHECK
    # check returning 0.
    assert 'WAKIR_BILATERAL_PRECHECK:-0}" != "1"' in body, (
        "First step_15 instruction must be the WAKIR_BILATERAL_PRECHECK gate"
    )
    assert "return 0" in body[: body.find("log_step")], (
        "step_15 must return 0 silently when not enabled"
    )


# TV-B39-A-04 -----------------------------------------------------------------


def test_step_15_rejects_single_org(bootstrap_source: str) -> None:
    """The precheck only makes sense AFTER the operator has flipped
    this side to federation-mode; running it in single-org-mode is a
    hard error."""
    start = bootstrap_source.find("step_15_bilateral_precheck()")
    end = bootstrap_source.find("\n}", start)
    body = bootstrap_source[start:end]
    assert 'WAKIR_PILOT_MODE" != "federation"' in body, (
        "step_15 must reject single-org-mode"
    )


# TV-B39-A-05 -----------------------------------------------------------------


def test_step_15_requires_peer_vars(bootstrap_source: str) -> None:
    start = bootstrap_source.find("step_15_bilateral_precheck()")
    end = bootstrap_source.find("\n}", start)
    body = bootstrap_source[start:end]
    assert "WAKIR_PEER_SIDE" in body and "WAKIR_PEER_HOST" in body, (
        "step_15 must require both WAKIR_PEER_SIDE and WAKIR_PEER_HOST"
    )


# TV-B39-A-06 -----------------------------------------------------------------


def test_step_15_tcp_8443_probe(bootstrap_source: str) -> None:
    start = bootstrap_source.find("step_15_bilateral_precheck()")
    end = bootstrap_source.find("\n}", start)
    body = bootstrap_source[start:end]
    # The probe uses /dev/tcp/<host>/8443.
    assert "/dev/tcp/" in body and ":8443" in body, (
        "step_15 must probe peer TCP 8443 reachability"
    )


# TV-B39-A-07 -----------------------------------------------------------------


def test_step_15_respawn_window(bootstrap_source: str) -> None:
    """Records the persona re-spawn-window declaration so the bring-
    up log captures the operational invariant."""
    start = bootstrap_source.find("step_15_bilateral_precheck()")
    end = bootstrap_source.find("\n}", start)
    body = bootstrap_source[start:end]
    assert "WAKIR_PERSONA_RESPAWN_WINDOW" in body, (
        "step_15 must check WAKIR_PERSONA_RESPAWN_WINDOW"
    )


# TV-B39-A-08 -----------------------------------------------------------------


def test_step_15_wired_after_step_8(bootstrap_source: str) -> None:
    """step_15 must run AFTER step_8_smoke in main()."""
    main_start = bootstrap_source.find("main() {")
    main_end = bootstrap_source.find("\n}", main_start)
    main_body = bootstrap_source[main_start:main_end]
    s8_idx = main_body.find('"step_8_smoke"')
    s15_idx = main_body.find("step_15_bilateral_precheck")
    assert s8_idx > 0 and s15_idx > 0, (
        "step_8_smoke and step_15_bilateral_precheck must both be in main()"
    )
    assert s15_idx > s8_idx, (
        "step_15_bilateral_precheck must be wired AFTER step_8_smoke in main()"
    )


# TV-B39-B-09 -----------------------------------------------------------------


def test_decision_note_exists() -> None:
    assert _DECISION_NOTE.is_file(), (
        f"Option-B decision-note missing: {_DECISION_NOTE}"
    )


# TV-B39-B-10 -----------------------------------------------------------------


def test_decision_note_content(decision_note_text: str) -> None:
    """The decision-note must declare both options, give Pros/Cons for
    each, and reference the runtime selector env-var."""
    assert "Option A" in decision_note_text, "Decision-note must declare Option A"
    assert "Option B" in decision_note_text, "Decision-note must declare Option B"
    assert "Pros" in decision_note_text and "Cons" in decision_note_text, (
        "Decision-note must give Pros + Cons for each option"
    )
    assert "WAKIR_BILATERAL_PRECHECK" in decision_note_text, (
        "Decision-note must reference the runtime selector env-var"
    )
    # AR decision-points section.
    assert "AR" in decision_note_text and "Decision-points" in decision_note_text, (
        "Decision-note must include AR/Mira decision-points section"
    )
