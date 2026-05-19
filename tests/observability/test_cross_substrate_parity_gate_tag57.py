# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-57 Cross-Substrate Parity Gate green-on-PR closeout.

Audit anchor
------------
Selin Tag-56 Persona-Engine 0.5.2-final production-readiness audit
(``reports/audit/persona-engine-0-5-2-production-readiness-2026-05-19.md``)
left OPEN-J1 open:

> OPEN-J1: Cross-substrate-parity-gate green on PR (Kai Zone-J)

Two distinct contracts are co-housed under the
``cross-substrate-parity-gate`` workflow umbrella, and Tag-57 closes
the gap between them so OPEN-J1 can flip to GREEN-on-PR:

1. **9-Binary Phase-3b Cosign/Quadlet/Resolver Parity** (pre-Tag-57,
   already enforced by
   ``tests/infra/test_cross_substrate_parity_3way.py``). This is the
   image-side substrate parity: every binary the Cosign-policy
   signs must be installed by the Quadlet container AND known to
   the Python resolver.

2. **10-BackendDecision Manifest × Pin-Pack × engine.py-Resolver
   Parity** (Tag-57 addition, Selin-anchored). This is the
   record-side substrate parity: every BackendDecision record the
   manifest enumerates must (a) appear in the Pin-Pack
   ``boot_wired_crates`` block, (b) be resolved by exactly one
   ``resolve_*_backend()`` call in ``engine.py``, and (c) live in
   the canonical boot-order indices used by the resilience
   suite.

This test file is the **green-on-PR hermetic guarantee** for
contract (2). It does not duplicate contract (1) — that remains in
``tests/infra/test_cross_substrate_parity_3way.py``. It does enforce
the workflow-level wiring (path-triggers, job-name, required-status-
check name) so the gate cannot silently drop the new parity
guarantee.

Hermetic discipline
-------------------
Pure file inspection. No subprocess, no network, no Rust build, no
engine boot, no NATS. Encodes assertions about workflow YAML,
manifest Markdown, pin-pack YAML, engine.py Python source, and the
Tag-57 runbook update.

Test inventory (≥ 10)
---------------------
1.  test_01_workflow_file_exists
2.  test_02_workflow_job_display_name_is_required_status_check_name
3.  test_03_workflow_triggers_on_manifest_change
4.  test_04_workflow_triggers_on_pin_pack_change
5.  test_05_workflow_triggers_on_engine_py_change
6.  test_06_workflow_runs_10_decision_manifest_parity_stage
7.  test_07_manifest_lists_ten_backend_decisions
8.  test_08_pin_pack_wired_crates_count_matches_manifest
9.  test_09_engine_py_imports_all_ten_resolvers
10. test_10_canonical_boot_order_consistent_three_witnesses
11. test_11_runbook_documents_open_j1_closeout
12. test_12_required_status_check_doc_present
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="PyYAML required for cross-substrate parity gate tests.",
)

# ---------------------------------------------------------------------------
# Paths anchored from the repo root (this file lives at
# tests/observability/, so repo_root = parents[2]).
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "cross-substrate-parity-gate.yml"
MANIFEST = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.2-final-pre-cutover.md"
)
PIN_PACK = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.2-final-pre-cutover.yaml"
)
ENGINE_PY = REPO_ROOT / "wirelang" / "persona_engine" / "engine.py"
RUNBOOK = REPO_ROOT / "docs" / "operations" / "cross-substrate-parity-runbook.md"

# The canonical 10-BackendDecision order, byte-stable vs.
# 0.5.1/0.5.2 manifest §1. The first-token-of-each-record matches
# the names in ``test_10_decision_resilience.py:DECISION_ORDER``.
CANONICAL_BOOT_ORDER: tuple[str, ...] = (
    "recovery-workflow",
    "state-backing",
    "lifecycle-fsm",
    "v907-verify",
    "bridge-diff",
    "subscribe-loop",
    "anchor-emitter",
    "svid-workload-identity",
    "federation-resolver",
    "bridge-audit-writer",
)

# The ten resolver entry-point function names imported by
# ``wirelang.persona_engine.engine`` at boot. One-to-one with
# ``CANONICAL_BOOT_ORDER``.
CANONICAL_RESOLVERS: tuple[str, ...] = (
    "resolve_recovery_backend",
    "resolve_state_backing_backend",
    "resolve_fsm_backend",
    "resolve_v907_verify_backend",
    "resolve_bridge_diff_backend",
    "resolve_subscribe_loop_backend",
    "resolve_anchor_emitter_backend",
    "resolve_svid_workload_identity_backend",
    "resolve_federation_resolver_backend",
    "resolve_bridge_audit_writer_backend",
)

# The required-status-check display name that Mira-Hand must
# activate under Settings → Branches → main → Required status
# checks. Per ``feedback_branch_protection_check_names.md`` this
# string must exactly match the workflow ``job.name`` field.
REQUIRED_STATUS_CHECK_NAME = (
    "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    return yaml.safe_load(workflow_text)


@pytest.fixture(scope="module")
def manifest_text() -> str:
    return MANIFEST.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pin_pack() -> dict:
    return yaml.safe_load(PIN_PACK.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def engine_py_text() -> str:
    return ENGINE_PY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def runbook_text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Workflow-Wiring tests (workflow exists, job name pin, path triggers)
# ---------------------------------------------------------------------------


def test_01_workflow_file_exists() -> None:
    """The cross-substrate-parity-gate workflow file must exist."""
    assert WORKFLOW.is_file(), f"Workflow missing: {WORKFLOW}"


def test_02_workflow_job_display_name_is_required_status_check_name(
    workflow_yaml: dict,
) -> None:
    """job.name must equal the canonical required-status-check name.

    Per ``feedback_branch_protection_check_names.md``: branch-
    protection required-status-checks reference the **job display
    name**, not the workflow name. Drift here makes the gate appear
    perpetually pending.
    """
    jobs = workflow_yaml.get("jobs", {})
    assert "cross-substrate-parity-gate" in jobs
    job = jobs["cross-substrate-parity-gate"]
    assert job.get("name") == REQUIRED_STATUS_CHECK_NAME, (
        f"Job display name drift. Expected exactly:\n"
        f"  {REQUIRED_STATUS_CHECK_NAME!r}\n"
        f"Got:\n"
        f"  {job.get('name')!r}\n"
        f"Branch-protection required-status-check would fail to match."
    )


def test_03_workflow_triggers_on_manifest_change(workflow_yaml: dict) -> None:
    """A change to the 0.5.2-final manifest must trigger the gate.

    Tag-57 widening: previously the workflow only triggered on the
    9-Binary substrate paths. Without the manifest in the path
    list, Selin-style PRs that only touch the manifest would not
    run the gate, and OPEN-J1 could not turn green on those PRs.
    """
    on = workflow_yaml.get("on", workflow_yaml.get(True, {}))
    pr_paths = on.get("pull_request", {}).get("paths", [])
    manifest_rel = "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md"
    assert manifest_rel in pr_paths, (
        f"Workflow pull_request.paths must include the 0.5.2-final "
        f"manifest. Missing: {manifest_rel!r}"
    )


def test_04_workflow_triggers_on_pin_pack_change(workflow_yaml: dict) -> None:
    """A change to the 0.5.2-final pin-pack must trigger the gate."""
    on = workflow_yaml.get("on", workflow_yaml.get(True, {}))
    pr_paths = on.get("pull_request", {}).get("paths", [])
    pin_rel = "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml"
    assert pin_rel in pr_paths, (
        f"Workflow pull_request.paths must include the 0.5.2-final "
        f"pin-pack. Missing: {pin_rel!r}"
    )


def test_05_workflow_triggers_on_engine_py_change(workflow_yaml: dict) -> None:
    """A change to ``engine.py`` (the resolver call-site) must trigger.

    ``engine.py`` is the third substrate-witness for the 10-
    BackendDecision boot fan-out (per the Tag-56 audit §6 matrix).
    A silent edit there must run the gate.
    """
    on = workflow_yaml.get("on", workflow_yaml.get(True, {}))
    pr_paths = on.get("pull_request", {}).get("paths", [])
    engine_rel = "wirelang/persona_engine/engine.py"
    assert engine_rel in pr_paths, (
        f"Workflow pull_request.paths must include engine.py "
        f"(third substrate-witness). Missing: {engine_rel!r}"
    )


def test_06_workflow_runs_10_decision_manifest_parity_stage(
    workflow_text: str,
) -> None:
    """The workflow must run the 10-BackendDecision parity stage.

    The Tag-57 widening adds a second pytest invocation that runs
    ``test_manifest_0_5_2_final_pre_cutover.py`` (Selin's manifest
    integrity suite) as a stage of the gate. Without this stage,
    the gate is silent on manifest-side drift even when triggered.
    """
    assert "test_manifest_0_5_2_final_pre_cutover.py" in workflow_text, (
        "Workflow must invoke the 10-BackendDecision manifest-parity "
        "stage (test_manifest_0_5_2_final_pre_cutover.py)."
    )


# ---------------------------------------------------------------------------
# 10-BackendDecision triple-witness tests (manifest, pin-pack, engine.py)
# ---------------------------------------------------------------------------


def test_07_manifest_lists_ten_backend_decisions(manifest_text: str) -> None:
    """Manifest §1 lists exactly the canonical 10 BackendDecision names."""
    for canonical in CANONICAL_BOOT_ORDER:
        assert canonical in manifest_text, (
            f"Manifest §1 missing canonical BackendDecision name "
            f"{canonical!r}. 10-decision boot fan-out broken."
        )


def test_08_pin_pack_wired_crates_count_matches_manifest(pin_pack: dict) -> None:
    """Pin-pack ``boot_wired_crates`` must contain exactly 10 entries."""
    wired = pin_pack.get("boot_wired_crates", [])
    assert len(wired) == 10, (
        f"Pin-pack boot_wired_crates count drift: expected 10 "
        f"(byte-stable vs. 0.5.1), got {len(wired)}."
    )
    # Verify the record index goes 1..10 in order, matching the
    # canonical manifest §1 boot order.
    records = [entry.get("record") for entry in wired]
    assert records == list(range(1, 11)), (
        f"Pin-pack record indices not [1..10] in order: {records}"
    )


def test_09_engine_py_imports_all_ten_resolvers(engine_py_text: str) -> None:
    """engine.py must import all ten canonical resolver entry points."""
    for resolver in CANONICAL_RESOLVERS:
        assert resolver in engine_py_text, (
            f"engine.py missing resolver call-site {resolver!r}. "
            f"10-BackendDecision boot fan-out broken at the third "
            f"substrate-witness."
        )


def test_10_canonical_boot_order_consistent_three_witnesses(
    manifest_text: str,
    pin_pack: dict,
    engine_py_text: str,
) -> None:
    """All three witnesses must agree on the canonical 10-record set.

    This is the heart of the OPEN-J1 contract: any silent drift
    where one substrate adds/removes/renames a BackendDecision
    record without the others must fail loud.
    """
    wired_names = [entry.get("name", "") for entry in pin_pack.get("boot_wired_crates", [])]

    # Map crate names back to canonical short names. The pin-pack
    # uses ``persona-engine-recovery``, ``persona-engine-state-backing``,
    # ``persona-engine-fsm``, etc. We strip the ``persona-engine-``
    # prefix and tolerate the ``fsm`` ↔ ``lifecycle-fsm`` and the
    # remaining short-name normalisations.
    short_names_from_pin_pack = [
        n.replace("persona-engine-", "") for n in wired_names
    ]
    pin_pack_aliases = {
        "recovery": "recovery-workflow",
        "fsm": "lifecycle-fsm",
    }
    normalised_pin_pack = [
        pin_pack_aliases.get(n, n) for n in short_names_from_pin_pack
    ]

    assert normalised_pin_pack == list(CANONICAL_BOOT_ORDER), (
        f"Pin-pack canonical boot order drift.\n"
        f"  Expected: {list(CANONICAL_BOOT_ORDER)}\n"
        f"  Got:      {normalised_pin_pack}"
    )

    # Every canonical name must appear in manifest §1 AND engine.py.
    for canonical_name, resolver in zip(CANONICAL_BOOT_ORDER, CANONICAL_RESOLVERS):
        assert canonical_name in manifest_text, (
            f"Manifest witness missing {canonical_name!r}"
        )
        assert resolver in engine_py_text, (
            f"engine.py witness missing resolver {resolver!r} for "
            f"{canonical_name!r}"
        )


# ---------------------------------------------------------------------------
# Runbook + branch-protection documentation tests
# ---------------------------------------------------------------------------


def test_11_runbook_documents_open_j1_closeout(runbook_text: str) -> None:
    """Tag-57 runbook addendum must document the OPEN-J1 closeout."""
    # Either a section header or an explicit mention of OPEN-J1
    # plus Tag-57 must appear in the runbook so a future operator
    # can trace the green-on-PR contract.
    assert "OPEN-J1" in runbook_text, (
        "Runbook must reference OPEN-J1 to anchor Tag-57 closeout."
    )
    assert "Tag-57" in runbook_text, (
        "Runbook must reference Tag-57 to anchor the green-on-PR "
        "widening (10-BackendDecision-parity stage + path triggers)."
    )


def test_12_required_status_check_doc_present(runbook_text: str) -> None:
    """Runbook must spell out the exact required-status-check name.

    Sandbox-Gap-Marker: Mira-Hand activates branch-protection in
    Settings → Branches → main → Required status checks. The
    runbook must spell the exact string so the activation step
    cannot drift from the workflow's job display name (cf.
    ``feedback_branch_protection_check_names.md``).
    """
    assert REQUIRED_STATUS_CHECK_NAME in runbook_text, (
        f"Runbook must spell the exact required-status-check name "
        f"verbatim: {REQUIRED_STATUS_CHECK_NAME!r}"
    )
