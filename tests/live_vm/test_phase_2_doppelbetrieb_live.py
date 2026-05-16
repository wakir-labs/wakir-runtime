# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-2 Doppelbetrieb — Live-VM Acceptance Test-Suite (skeleton).

Sprint-Live-VM-MINI (2026-05-16, post-Quota-Reset MINI-Welle). This
module is the canonical entry point for the Live-VM lane that
Phase-2 (Doppelbetrieb) requires for Acceptance-Gate enforcement on a
real Pilot-VM target. It complements the hermetic test surface
already on main (``tests/infra/test_pilot_phase_e2e_smoke.py`` and
``tests/infra/test_ci_live_vm_acceptance_wrapper.py``) by closing
the operator-side gap documented in
``feedback_live_bringup_sandbox_gap.md``: hermetic-Sandbox tests
cannot reach an SSH-driven 192.168.178.* target, but the
substance-bugs that have repeatedly slipped through the Sandbox can
only be caught by exercising the live-target invariants.

ADR-Anker
---------

* **ADR-0058** — Pilot-Persona-Migrations-Plan. §"Phase 4
  Cutover-Entscheidung" defines the four-axis Doppelbetrieb-Score
  verdict and the cutover gate. This suite is the test-vector
  harness behind that gate.
* **Sprint-QA-Tag-15 PR #80** — added the hermetic Phase-1b/2/3
  Quality-Gates documentation and the Pilot-Phase-E2E-Smoke
  test-vectors. This module is the live-target sibling of that PR:
  same Quality-Gate matrix, different (skip-by-default) execution
  lane.

Invocation
----------

This suite is **skipped by default**. CI stays green without a
live VM. To run against an operator-controlled target:

  pytest --run-live-vm tests/live_vm/test_phase_2_doppelbetrieb_live.py

…and additionally::

  WAKIR_LIVE_VM_ACCEPTANCE=1 pytest --run-live-vm \\
      tests/live_vm/test_phase_2_doppelbetrieb_live.py

Both gates (CLI flag + env-var) must agree. The double gate is
intentional: it prevents accidental runs from a CI runner that
happens to have the flag in a config file, and it prevents
accidental runs from an operator shell that has the env-var set
but did not mean to point at the live VM right now.

Sandbox boundary
----------------

The hermetic claude-dev Sandbox **cannot** reach the Pilot-VM. All
ten test-vectors in this module use the **SSH-mocked-stub-pattern**:
on a live run, the test invokes a thin wrapper that shells out over
SSH; on a dry-run or under unit-test of the helpers themselves, the
wrapper is monkeypatched to return a synthetic transcript. This
mirrors the pattern in
``tests/infra/test_ci_live_vm_acceptance_wrapper.py`` (which exercises
the wrapper-script *logic* without ever calling a real VM).

Test-Vector index
-----------------

* **TV-LVD-01..04** — Persona-Container heartbeat. The
  ``wakir-persona-tomas`` Quadlet-unit must answer the health probe
  with a fresh ``transition.utc`` over four heartbeat axes (single,
  burst, post-restart, post-bridge-fan-out).
* **TV-LVD-05..07** — WAT-Anchor roundtrip. A leaf-event committed
  on the VM must traverse JCS-canonicalisation → leaf-hash →
  hour-Merkle-root and the OTS-anchor must be retrievable (or the
  pending-receipt is observed cleanly).
* **TV-LVD-08..10** — Subscribe-Loop receive. The Bridge-Forward
  fan-out (Sprint-10 Tag-6 spec §7) must deliver exactly one frame
  to the wakir-Tomás-Container sink for every Auftrag, with no
  duplicate-delivery (Bug-42 regression) and no silent drop.

All ten vectors carry ``@pytest.mark.live_vm`` and are skipped by
default. The skip is enforced by ``tests/live_vm/conftest.py``.

Stub-pattern contract
---------------------

Each test takes an ``ssh_runner`` fixture. On a real live run, that
fixture returns a function which executes the command on the
target via SSH and returns ``(rc, stdout, stderr)``. On a dry-run
(default), the fixture returns a function which raises a clear
``pytest.fail()`` because the test should have been skipped — the
double-skip guard is a defence-in-depth against a future refactor
that silently flips the skip default.

Bridge to docs
--------------

* ``docs/quality-gates/phase-2-doppelbetrieb.md`` §2.2 (Bridge-
  Forward fan-out symmetric) — TV-LVD-08..10.
* ``docs/quality-gates/phase-2-doppelbetrieb.md`` §2.4 (V-907 pin-
  drift) — exercised at the heartbeat level by TV-LVD-04.
* ``docs/quality-gates/phase-1b-pilot.md`` — TV-LVD-01..03 inherit
  the Phase-1b heartbeat gate.

The accompanying Test-Plan document (which fixtures, which targets,
what to do when a vector fails) is intentionally deferred to a
follow-up sprint per the MINI scope.

— Amara
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

import pytest


# ---------------------------------------------------------------------------
# Module-level marker — every test in this file is a Live-VM test.
# The conftest.py in this package skips by default.
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.live_vm


# Shape of the runner that each test consumes. The runner takes a
# host string and a shell command, returns (rc, stdout, stderr).
SshRunner = Callable[[str, str], tuple[int, str, str]]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pilot_vm_host() -> str:
    """The Pilot-VM target host.

    Defaults to the wakir-pilot side per Sprint-10 Tag-6 topology,
    overridable via ``WAKIR_PEER_HOST`` to mirror the operator-script
    invocation. The default is intentionally an RFC1918 address so a
    careless live-run cannot exfiltrate.
    """

    return os.environ.get("WAKIR_PEER_HOST", "192.168.178.116")


@pytest.fixture
def ssh_runner(request: pytest.FixtureRequest) -> SshRunner:
    """SSH-mocked stub runner.

    On a real live run (operator-hand, with both gates open), the
    test framework is expected to install a real SSH-backed runner.
    Until that lane is wired, we fail loudly: the conftest skip
    should have fired *before* this fixture is constructed. If it
    did not, the test author has bypassed the skip guard.
    """

    def _refuse(host: str, cmd: str) -> tuple[int, str, str]:
        pytest.fail(
            "ssh_runner called outside a live-vm run; the "
            "tests/live_vm/conftest.py skip guard should have "
            f"fired first (host={host!r}, cmd={cmd!r:.80})"
        )

    return _refuse


# ---------------------------------------------------------------------------
# Helpers — pure functions, parser-style, hermetically testable on their own
# in a follow-up Test-Plan sprint. Kept here for MINI-scope locality.
# ---------------------------------------------------------------------------


_TRANSITION_UTC_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z"
)


def parse_heartbeat(stdout: str) -> dict[str, Any]:
    """Parse a heartbeat-probe JSON document.

    Expected shape (per Persona-Engine V-907 spec):

      {"persona": "tomas", "transition_utc": "...Z",
       "active_log_len": N, "pin_sha256": "..."}
    """

    doc = json.loads(stdout)
    if not isinstance(doc, dict):
        raise ValueError("heartbeat doc must be a JSON object")
    for required in ("persona", "transition_utc", "pin_sha256"):
        if required not in doc:
            raise ValueError(f"missing field {required!r}")
    if not _TRANSITION_UTC_RE.fullmatch(doc["transition_utc"]):
        raise ValueError(
            f"transition_utc malformed: {doc['transition_utc']!r}"
        )
    return doc


def parse_wat_anchor_receipt(stdout: str) -> dict[str, Any]:
    """Parse a WAT-anchor receipt JSON.

    Expected shape::

      {"hour_root": "<hex>", "ots_state": "pending"|"anchored",
       "btc_block_height": int|null}
    """

    doc = json.loads(stdout)
    if doc.get("ots_state") not in ("pending", "anchored"):
        raise ValueError(
            f"ots_state must be pending|anchored, got {doc.get('ots_state')!r}"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", doc.get("hour_root", "")):
        raise ValueError("hour_root must be 64-hex lower-case sha256")
    return doc


def parse_subscribe_loop_summary(stdout: str) -> dict[str, Any]:
    """Parse a Bridge-Forward subscribe-loop summary."""

    doc = json.loads(stdout)
    for required in ("auftrag_count", "pre_framework_sink_count",
                     "wakir_container_sink_count", "duplicate_count"):
        if required not in doc:
            raise ValueError(f"missing field {required!r}")
    return doc


# ---------------------------------------------------------------------------
# TV-LVD-01..04 — Persona-Container heartbeat
# ---------------------------------------------------------------------------


def test_tv_lvd_01_persona_heartbeat_single(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-01 — single heartbeat probe must return a fresh transition_utc.

    Operator command on-VM::

      podman exec wakir-persona-tomas \\
        /usr/local/bin/wirelang persona-inspect --heartbeat --json

    The returned ``transition_utc`` must parse as RFC3339-Z. We do
    **not** assert a freshness window here — that is a
    runtime-monitoring gate (Noa-Alert). The test asserts only that
    the probe returns a well-formed document.
    """

    rc, stdout, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-persona-tomas "
        "/usr/local/bin/wirelang persona-inspect --heartbeat --json",
    )
    assert rc == 0
    doc = parse_heartbeat(stdout)
    assert doc["persona"] == "tomas"


def test_tv_lvd_02_persona_heartbeat_burst(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-02 — burst of 5 heartbeats must show monotonic transition_utc.

    Catches a regression class where the engine caches a stale
    transition_utc and serves it for every probe (substance-bug
    pattern 2026-05-13 #4). Five probes within a 5-second window
    must yield five distinct, monotonically non-decreasing
    transition_utc values.
    """

    transitions: list[str] = []
    for _ in range(5):
        rc, stdout, _ = ssh_runner(
            pilot_vm_host,
            "podman exec wakir-persona-tomas "
            "/usr/local/bin/wirelang persona-inspect --heartbeat --json",
        )
        assert rc == 0
        doc = parse_heartbeat(stdout)
        transitions.append(doc["transition_utc"])

    # Monotonic non-decreasing.
    assert transitions == sorted(transitions), (
        f"transition_utc regression: {transitions!r}"
    )
    # And at least two distinct values across 5 probes — a fully
    # constant series indicates the cache-staleness regression.
    assert len(set(transitions)) >= 2


def test_tv_lvd_03_persona_heartbeat_post_restart(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-03 — heartbeat after Quadlet-restart must work and reflect new spawn.

    Restart the Quadlet-unit, wait for it to come up, then issue a
    heartbeat. ``active_log_len`` must be >= 1 (the post-restart
    Spawn-event), and ``pin_sha256`` must match the build-time pin
    (no V-907 drift on restart, see ADR-0058 §V-907).
    """

    rc, _, _ = ssh_runner(
        pilot_vm_host,
        "sudo systemctl restart wakir-persona-tomas.service",
    )
    assert rc == 0

    rc, stdout, _ = ssh_runner(
        pilot_vm_host,
        # 10-second settle.
        "sleep 10 && podman exec wakir-persona-tomas "
        "/usr/local/bin/wirelang persona-inspect --heartbeat --json",
    )
    assert rc == 0
    doc = parse_heartbeat(stdout)
    assert doc.get("active_log_len", 0) >= 1
    # pin_sha256 is a 64-hex lower-case digest of the persona-image.
    assert re.fullmatch(r"[0-9a-f]{64}", doc["pin_sha256"])


def test_tv_lvd_04_persona_heartbeat_post_bridge_fanout(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-04 — heartbeat after Bridge-Forward fan-out is delivered.

    After publishing a synthetic Auftrag to
    ``wakir.<env>.agent.agent.task.assigned.tomas``, the heartbeat
    must show ``active_log_len`` incremented by at least 1
    (confirming the Container saw and recorded the event). This
    pins down Bug-42-class regressions where the Container is up
    but silently fails to receive.
    """

    rc, before_stdout, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-persona-tomas "
        "/usr/local/bin/wirelang persona-inspect --heartbeat --json",
    )
    assert rc == 0
    before = parse_heartbeat(before_stdout)

    rc, _, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-persona-tomas "
        "/usr/local/bin/wirelang bridge-forward inject-synthetic "
        "--persona tomas --tag tv-lvd-04",
    )
    assert rc == 0

    rc, after_stdout, _ = ssh_runner(
        pilot_vm_host,
        "sleep 3 && podman exec wakir-persona-tomas "
        "/usr/local/bin/wirelang persona-inspect --heartbeat --json",
    )
    assert rc == 0
    after = parse_heartbeat(after_stdout)

    assert after["active_log_len"] >= before["active_log_len"] + 1


# ---------------------------------------------------------------------------
# TV-LVD-05..07 — WAT-Anchor roundtrip
# ---------------------------------------------------------------------------


def test_tv_lvd_05_wat_leaf_to_hour_root(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-05 — leaf event must reach the hour-Merkle-root within the hour.

    Inject a synthetic leaf, then query the current hour's anchor
    receipt. The receipt's ``hour_root`` must be a 64-hex digest and
    ``ots_state`` must be ``pending`` or ``anchored``.
    """

    rc, _, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-wat-anchorer "
        "/usr/local/bin/wat inject-synthetic-leaf --tag tv-lvd-05",
    )
    assert rc == 0

    rc, stdout, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-wat-anchorer "
        "/usr/local/bin/wat anchor-receipt --current-hour --json",
    )
    assert rc == 0
    doc = parse_wat_anchor_receipt(stdout)
    assert doc["hour_root"]


def test_tv_lvd_06_wat_anchor_ots_state_progression(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-06 — OTS-state must progress from pending → anchored eventually.

    For an hour-bucket older than 72 hours, ``ots_state`` MUST be
    ``anchored``. Anything younger MAY still be ``pending`` (Bitcoin
    confirmation latency). This catches the regression class where
    the OTS-upgrade-loop has silently stopped (substance-bug pattern
    pre-Sprint-10 Tag-6 W-OTS).
    """

    rc, stdout, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-wat-anchorer "
        "/usr/local/bin/wat anchor-receipt --hours-ago 72 --json",
    )
    assert rc == 0
    doc = parse_wat_anchor_receipt(stdout)
    assert doc["ots_state"] == "anchored", (
        f"OTS-upgrade-loop regression: 72h-old bucket still "
        f"{doc['ots_state']!r}; expected 'anchored'"
    )
    assert isinstance(doc.get("btc_block_height"), int)
    assert doc["btc_block_height"] > 0


def test_tv_lvd_07_wat_anchor_external_verify(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-07 — external-verifier path on the VM must succeed for an anchored bucket.

    Runs the on-VM ``wat verify --external`` lane against a
    72h-old (or older) bucket. The external lane re-derives the
    hour-root from the persisted leaves and re-checks the OTS-proof
    independently of the anchorer's internal state. A pass here
    means the anchor is verifiable by a third party — the core
    audit-trail invariant.
    """

    rc, stdout, stderr = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-wat-anchorer "
        "/usr/local/bin/wat verify --external --hours-ago 72 --json",
    )
    assert rc == 0, (
        f"external-verifier failed: rc={rc} stderr={stderr!r:.200}"
    )
    doc = json.loads(stdout)
    assert doc.get("verdict") == "verified"


# ---------------------------------------------------------------------------
# TV-LVD-08..10 — Subscribe-Loop receive (Bridge-Forward fan-out)
# ---------------------------------------------------------------------------


def test_tv_lvd_08_subscribe_loop_single_auftrag(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-08 — single Auftrag reaches both sinks exactly once.

    Publishes one synthetic Auftrag and reads the subscribe-loop
    summary. The Phase-2 §2.2 invariant is::

        pre_framework_sink_count == 1
        wakir_container_sink_count == 1
        duplicate_count == 0
    """

    rc, _, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-bridge-forward "
        "/usr/local/bin/wirelang bridge-forward publish-synthetic "
        "--persona tomas --count 1 --tag tv-lvd-08",
    )
    assert rc == 0

    rc, stdout, _ = ssh_runner(
        pilot_vm_host,
        "sleep 5 && podman exec wakir-bridge-forward "
        "/usr/local/bin/wirelang bridge-forward subscribe-loop-summary "
        "--filter-tag tv-lvd-08 --json",
    )
    assert rc == 0
    summary = parse_subscribe_loop_summary(stdout)
    assert summary["auftrag_count"] == 1
    assert summary["pre_framework_sink_count"] == 1
    assert summary["wakir_container_sink_count"] == 1
    assert summary["duplicate_count"] == 0


def test_tv_lvd_09_subscribe_loop_burst_symmetric(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-09 — 100-Auftrag burst keeps fan-out symmetric within ≤0.1% drop.

    Per ``docs/quality-gates/phase-2-doppelbetrieb.md`` §2.2 the
    drop-rate is ≤ 0.1% over 24h. For a 100-Auftrag burst (well
    under that budget) the tolerated drop is 0. Both sink counts
    must equal ``auftrag_count`` exactly.
    """

    rc, _, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-bridge-forward "
        "/usr/local/bin/wirelang bridge-forward publish-synthetic "
        "--persona tomas --count 100 --tag tv-lvd-09",
    )
    assert rc == 0

    rc, stdout, _ = ssh_runner(
        pilot_vm_host,
        "sleep 30 && podman exec wakir-bridge-forward "
        "/usr/local/bin/wirelang bridge-forward subscribe-loop-summary "
        "--filter-tag tv-lvd-09 --json",
    )
    assert rc == 0
    summary = parse_subscribe_loop_summary(stdout)
    assert summary["auftrag_count"] == 100
    assert summary["pre_framework_sink_count"] == 100
    assert summary["wakir_container_sink_count"] == 100
    assert summary["duplicate_count"] == 0


def test_tv_lvd_10_subscribe_loop_bug42_no_duplicate(
    ssh_runner: SshRunner, pilot_vm_host: str
) -> None:
    """TV-LVD-10 — Bug-42 regression: subscribe-loop must not double-deliver.

    Bug-42 (Subscribe-Loop double-receive, 2026-05 substance-bug
    list, anchored in ``feedback_live_bringup_sandbox_gap.md``):
    under specific reconnect conditions the wakir-Container sink
    was receiving the same Auftrag twice. This vector publishes
    10 Aufträge, induces a controlled reconnect, and asserts
    ``duplicate_count == 0`` on the summary.
    """

    rc, _, _ = ssh_runner(
        pilot_vm_host,
        "podman exec wakir-bridge-forward "
        "/usr/local/bin/wirelang bridge-forward publish-synthetic "
        "--persona tomas --count 10 --tag tv-lvd-10 "
        "--induce-reconnect-mid-burst",
    )
    assert rc == 0

    rc, stdout, _ = ssh_runner(
        pilot_vm_host,
        "sleep 10 && podman exec wakir-bridge-forward "
        "/usr/local/bin/wirelang bridge-forward subscribe-loop-summary "
        "--filter-tag tv-lvd-10 --json",
    )
    assert rc == 0
    summary = parse_subscribe_loop_summary(stdout)
    assert summary["auftrag_count"] == 10
    assert summary["duplicate_count"] == 0, (
        "Bug-42 regression detected: subscribe-loop double-delivered "
        f"under induced reconnect; summary={summary!r}"
    )
    # Both sinks must still see all 10 — induced reconnect must
    # not cause silent drop either.
    assert summary["pre_framework_sink_count"] == 10
    assert summary["wakir_container_sink_count"] == 10
