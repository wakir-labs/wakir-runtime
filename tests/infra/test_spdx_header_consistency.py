# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""SPDX header consistency for Phase-2-Federation BSL sub-trees.

Asserts that every substance file in the four BSL sub-trees activated
under ADR-0059 (2026-05-13) carries the canonical
``SPDX-License-Identifier: BUSL-1.1`` marker, and that the
Brand-Proof external verifier carve-out (ADR-0023b) remains
Apache-2.0.

Henrik-Audit (2026-05-13) surfaced the BSL-coverage drift in
~68 files across:

* ``wirelang/federation/`` plus the V-908 Resolver, the operator
  marker-stack-reduce CLI, and the live NATS-JetStream adapter,
* ``infra/spire/federation/`` (excluding the provisioner sibling
  unit that ships its own BSL header since PR #36),
* ``infra/spire/agent/``.

Tests (the "Test-Files folgen Subjekt-Lizenz" rule of ADR-0059)
are also required to carry ``BUSL-1.1`` when they exercise a BSL
subject.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Sub-Baum 1: wirelang/federation/ plus sibling-units that are part of
# the Federation-Server runtime surface (V-908 Resolver, operator CLI,
# live NATS adapter — see wirelang/federation/LICENSE-BSL.md for the
# canonical scope statement).
WIRELANG_FED_BSL_SOURCES: tuple[str, ...] = (
    "wirelang/federation/__init__.py",
    "wirelang/federation/capability_attenuation_chain_verifier.py",
    "wirelang/federation/caveat_override_export.py",
    "wirelang/federation/cross_org_attenuation_verifier.py",
    "wirelang/federation/marker_composition.py",
    "wirelang/federation/marker_stack_kv.py",
    "wirelang/federation/multi_org_attestation_live_tail_replicator.py",
    "wirelang/federation/multi_org_attestation_nats_kv_backend.py",
    "wirelang/federation/multi_org_substrate.py",
    "wirelang/federation/n2_evaluator.py",
    "wirelang/federation/n3_chain_walker.py",
    "wirelang/federation/route_registry_nats_kv_backend.py",
    "wirelang/federation/sequence_number_ledger_kv.py",
    "wirelang/federation/spiffe_cross_trust_domain_bridge.py",
    "wirelang/federation/unrevoke_audit_marker_cross_org_export.py",
    "wirelang/identity/federation_resolver.py",
    "wirelang/cli/marker_stack_reduce.py",
    "wirelang/adapters/real_nats_adapter/adapter.py",
)

# Sub-Baum 2: infra/spire/federation/ (excluding the provisioner
# sibling, which carries its own BSL header since PR #36).
SPIRE_FED_BSL_SOURCES: tuple[str, ...] = (
    "infra/spire/federation/bin/spire_fed_bundle.py",
    "infra/spire/federation/bin/spire_fed_bundle_rotator.py",
    "infra/spire/federation/bin/spire_fed_health.py",
    "infra/spire/federation/bin/spire_fed_metrics.py",
    "infra/spire/federation/quadlet/wakir-spire-server-federation.container",
    "infra/spire/federation/quadlet/wakir-spire-server-federation-data.volume",
    "infra/spire/federation/quadlet/wakir-spire-server-federation-sockets.volume",
    "infra/spire/federation/quadlet/wakir-spire-server-federation-bundles.volume",
    "infra/spire/federation/quadlet/wakir-federation.network",
    "infra/spire/federation/compose/spire-federation.yaml",
    "infra/spire/federation/config/spire-server-wakir.conf",
    "infra/spire/federation/config/spire-server-partner.conf",
    "infra/spire/federation/proxmox/build-bundle.sh",
    "infra/spire/federation/proxmox/resolve-image-pins.sh",
    "infra/spire/federation/wakir-pilot-bootstrap.sh",
)

# Sub-Baum 3: infra/spire/agent/.
SPIRE_AGENT_BSL_SOURCES: tuple[str, ...] = (
    "infra/spire/agent/bin/spire_agent_fed_attest.py",
    "infra/spire/agent/bin/spire_agent_fed_reload.py",
    "infra/spire/agent/quadlet/wakir-spire-agent-federation.container",
    "infra/spire/agent/quadlet/wakir-spire-agent-federation-data.volume",
    "infra/spire/agent/quadlet/wakir-spire-agent-federation-sockets.volume",
    "infra/spire/agent/compose/spire-agent-federation.yaml",
    "infra/spire/agent/config/spire-agent-wakir.conf",
    "infra/spire/agent/config/spire-agent-partner.conf",
)

# Sub-Baum 4: Federation-Substanz-adjacent operator tooling.
# The proxmox-bringup-smoke binary self-verifies the live Federation-
# Server substrate (SPIRE-Server + SPIRE-Agent + NATS-KV marker-
# stack-bucket). It was re-licensed Apache-2.0 -> BSL 1.1 in
# Sprint-9 Tag-6 alongside the parser-hardening + e2e-vm-workflow
# fixes (Pilot-VM bring-up #2, 2026-05-14).
OPERATOR_TOOLING_BSL_SOURCES: tuple[str, ...] = (
    "bin/proxmox-bringup-smoke",
)

# Tests that exercise BSL subjects — these must inherit the subject
# licence per ADR-0059 §"Test-Files folgen Subjekt-Lizenz".
BSL_TEST_SOURCES: tuple[str, ...] = (
    # wirelang/federation/ tests
    "wirelang/tests/test_federation_capability_attenuation_chain_verifier.py",
    "wirelang/tests/test_federation_caveat_override_event_export_schema.py",
    "wirelang/tests/test_federation_caveat_override_export.py",
    "wirelang/tests/test_federation_marker_composition.py",
    "wirelang/tests/test_federation_marker_stack_kv.py",
    "wirelang/tests/test_federation_multi_org_attestation_live_tail_replicator.py",
    "wirelang/tests/test_federation_multi_org_attestation_nats_kv_backend.py",
    "wirelang/tests/test_federation_n2_evaluator.py",
    "wirelang/tests/test_federation_n3_chain_walker.py",
    "wirelang/tests/test_federation_resolver.py",
    "wirelang/tests/test_federation_route_registry_nats_kv_backend.py",
    "wirelang/tests/test_federation_sequence_number_ledger_kv.py",
    "wirelang/tests/test_federation_spiffe_cross_trust_domain_bridge.py",
    "wirelang/tests/test_federation_unrevoke_audit_marker_cross_org_export.py",
    # infra/spire/federation/ tests
    "infra/spire/federation/tests/test_federation_compose.py",
    "infra/spire/federation/tests/test_federation_quadlet.py",
    "infra/spire/federation/tests/test_image_pin_digest_form.py",
    "infra/spire/federation/tests/test_spire_fed_bundle_cli.py",
    "infra/spire/federation/tests/test_spire_fed_bundle_rotator.py",
    "infra/spire/federation/tests/test_spire_fed_health.py",
    "infra/spire/federation/tests/test_spire_fed_metrics.py",
    # infra/spire/agent/ tests
    "infra/spire/agent/tests/test_compose_spire_agent_federation.py",
    "infra/spire/agent/tests/test_quadlet_spire_agent_federation.py",
    "infra/spire/agent/tests/test_spire_agent_fed_attest_cli.py",
    "infra/spire/agent/tests/test_spire_agent_federation_config.py",
    "infra/spire/agent/tests/test_spire_agent_fed_reload.py",
    # WAT-Bridge tests (subject = WAT BSL via Phase-1a)
    "tests/wat/test_bridge_audit_wat_integration.py",
    "tests/wat/test_bridge_audit_writer_consistency.py",
    "tests/wat/test_bridge_audit_writer.py",
    "tests/wat/test_aggregator_side_signing_e2e.py",
    # Orchestrator tests against BSL Federation subjects
    "tests/orchestrator/test_nats_kv_bucket_provision.py",
    "tests/orchestrator/test_nats_kv_bucket_provision_multi_family.py",
    "tests/orchestrator/test_proxmox_bringup_smoke.py",
    "tests/orchestrator/test_proxmox_bringup_smoke_retry.py",
    "tests/orchestrator/test_proxmox_bringup_smoke_parser_hardening.py",
    "tests/orchestrator/test_multi_org_onboarding_recipe.py",
    "tests/orchestrator/test_check_federation_evaluator_health.py",
    # Infra tests against pilot-bootstrap / pin form (BSL subjects)
    "tests/infra/test_pilot_bootstrap.py",
    "tests/infra/test_python_image_pin_form.py",
    # E2E VM acceptance-gate workflow YAML (BSL subject: Federation-
    # Server live-substrate verification surface).
    "tests/infra/test_e2e_vm_workflow_yaml_validation.py",
    # Federation-Health-CLI
    "scripts/check-federation-evaluator-health.py",
    # Provisioner-Tests (subject = wakir-provisioner BSL)
    "infra/spire/federation/provisioner/tests/test_containerfile.py",
    "infra/spire/federation/provisioner/tests/test_requirements_hash_form.py",
)

# Brand-Proof carve-out per ADR-0023b — must remain Apache-2.0.
BRAND_PROOF_APACHE_SOURCES: tuple[str, ...] = (
    "wat/anchor/external_verifier",  # directory glob
)


def _read_head(path: Path, bytes_: int = 4096) -> str:
    with path.open("rb") as fh:
        return fh.read(bytes_).decode("utf-8", errors="replace")


@pytest.mark.parametrize(
    "rel",
    WIRELANG_FED_BSL_SOURCES
    + SPIRE_FED_BSL_SOURCES
    + SPIRE_AGENT_BSL_SOURCES
    + OPERATOR_TOOLING_BSL_SOURCES,
)
def test_substance_file_carries_busl_header(rel: str) -> None:
    """Every BSL substance file must carry ``SPDX-License-Identifier: BUSL-1.1``."""
    path = REPO_ROOT / rel
    assert path.exists(), f"{rel} not found at repo root {REPO_ROOT}"
    head = _read_head(path)
    assert "SPDX-License-Identifier: BUSL-1.1" in head, (
        f"{rel} is missing the BUSL-1.1 SPDX marker. "
        f"ADR-0059 requires every Federation-Server substance file to be BSL."
    )
    assert "SPDX-License-Identifier: Apache-2.0" not in head, (
        f"{rel} still carries an Apache-2.0 SPDX marker alongside BUSL-1.1. "
        f"Remove the Apache marker — the file is BSL, not dual-licensed."
    )


@pytest.mark.parametrize("rel", BSL_TEST_SOURCES)
def test_bsl_subject_test_carries_busl_header(rel: str) -> None:
    """Every test that exercises a BSL subject must carry BUSL-1.1.

    Per ADR-0059 §"Test-Files folgen Subjekt-Lizenz".
    """
    path = REPO_ROOT / rel
    assert path.exists(), f"{rel} not found at repo root {REPO_ROOT}"
    head = _read_head(path)
    assert "SPDX-License-Identifier: BUSL-1.1" in head, (
        f"{rel} exercises a BSL subject and must carry BUSL-1.1 itself. "
        f"See ADR-0059 §Test-Files folgen Subjekt-Lizenz."
    )


def test_brand_proof_verifier_remains_apache() -> None:
    """Brand-Proof verifier surface must remain Apache-2.0 (ADR-0023b)."""
    verifier_dir = REPO_ROOT / "wat" / "anchor" / "external_verifier"
    if not verifier_dir.exists():
        pytest.skip("Brand-Proof verifier directory not present in tree")
    py_files = list(verifier_dir.rglob("*.py"))
    assert py_files, (
        f"No Python files found under {verifier_dir}. Brand-Proof verifier "
        f"surface should not be empty — investigate."
    )
    for path in py_files:
        head = _read_head(path)
        assert "SPDX-License-Identifier: Apache-2.0" in head, (
            f"{path.relative_to(REPO_ROOT)} should be Apache-2.0 per ADR-0023b "
            f"(Brand-Proof-redistributable carve-out), but its SPDX header is "
            f"different. Do not relicense the Brand-Proof verifier."
        )
        assert "SPDX-License-Identifier: BUSL-1.1" not in head, (
            f"{path.relative_to(REPO_ROOT)} carries a BUSL-1.1 marker — the "
            f"Brand-Proof verifier must stay Apache-2.0 (ADR-0023b)."
        )


def test_bsl_unit_license_files_exist() -> None:
    """Each BSL sub-tree must ship its own LICENSE-BSL.md."""
    expected: tuple[str, ...] = (
        "wat/LICENSE-BSL.md",
        "infra/spire/federation/provisioner/LICENSE-BSL.md",
        "wirelang/federation/LICENSE-BSL.md",
        "infra/spire/federation/LICENSE-BSL.md",
        "infra/spire/agent/LICENSE-BSL.md",
    )
    missing = [rel for rel in expected if not (REPO_ROOT / rel).exists()]
    assert not missing, (
        f"Missing LICENSE-BSL.md files for BSL sub-trees: {missing}. "
        f"Every BSL unit must ship its own license file with the canonical "
        f"Change-Date / Change-License / Additional-Use-Grant fields."
    )


def test_change_date_consistency_phase_2_units() -> None:
    """All Phase-2-Federation BSL units share Change Date 2030-05-13.

    The WAT-Phase-1a unit has its own Change Date (separate first-published
    date) and is therefore *not* required to match. The provisioner unit was
    published on 2026-05-13 the same day as the Phase-2-Federation
    activation and shares the date by happenstance.
    """
    phase_2_units: tuple[str, ...] = (
        "infra/spire/federation/provisioner/LICENSE-BSL.md",
        "wirelang/federation/LICENSE-BSL.md",
        "infra/spire/federation/LICENSE-BSL.md",
        "infra/spire/agent/LICENSE-BSL.md",
    )
    for rel in phase_2_units:
        path = REPO_ROOT / rel
        text = path.read_text()
        assert "2030-05-13" in text, (
            f"{rel} does not state the canonical Phase-2-Federation Change "
            f"Date 2030-05-13. ADR-0059 fixed this date for all Phase-2 BSL "
            f"units activated on 2026-05-13."
        )
