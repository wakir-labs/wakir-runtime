# SPDX-License-Identifier: BUSL-1.1
"""Sprint-Pengine-9 Bug-Quadlet-Drift tests.

The Quadlet bind-mount paths must reference operator-staged
``/etc/wakir/persona/<slug>.{md,json}`` host paths, NOT
``/opt/wakir-runtime/...`` (which does not exist on the pilot host).
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUADLET_PATH = REPO_ROOT / "quadlet" / "wakir-persona-tomas.container"


def _quadlet_text() -> str:
    return QUADLET_PATH.read_text(encoding="utf-8")


def test_quadlet_file_exists():
    assert QUADLET_PATH.exists()


def _non_comment_lines(text: str) -> list[str]:
    """Return Quadlet lines excluding ``#``-comment lines.

    The Quadlet header documents prior bug-history (Bug-Quadlet-
    Drift) and intentionally mentions the deprecated
    ``/opt/wakir-runtime/...`` paths in comment prose so an
    operator reading the file understands the staging contract.
    The substantive-substrate tests must scope their negative
    assertions to non-comment lines so the documentation does
    not produce false positives.
    """
    return [
        ln for ln in text.splitlines()
        if not ln.lstrip().startswith("#")
    ]


def test_quadlet_does_not_bind_opt_wakir_runtime_claude_agents():
    """Bug-Quadlet-Drift: the prior bind-mount referenced
    ``/opt/wakir-runtime/.claude/agents/tomas.md`` which does not
    exist in the wakir-runtime checkout. The fix decouples the
    Quadlet from the repo topology by staging at ``/etc/wakir/
    persona/``."""
    substantive = "\n".join(_non_comment_lines(_quadlet_text()))
    assert "/opt/wakir-runtime/.claude/agents/tomas.md" not in substantive


def test_quadlet_does_not_bind_opt_wakir_runtime_wakir_persona():
    substantive = "\n".join(_non_comment_lines(_quadlet_text()))
    assert "/opt/wakir-runtime/wakir-persona/tomas.json" not in substantive


def test_quadlet_binds_etc_wakir_persona_md():
    text = _quadlet_text()
    assert "/etc/wakir/persona/tomas.md:/etc/wakir/persona/tomas.md:ro" in text


def test_quadlet_binds_etc_wakir_persona_json():
    text = _quadlet_text()
    assert "/etc/wakir/persona/tomas.json:/etc/wakir/persona/tomas.json:ro" in text


def test_quadlet_preserves_z_selinux_label():
    text = _quadlet_text()
    # The Z private-relabel flag is mandatory for the persona
    # definition bind-mounts on FCOS-enforced hosts. Quadlet
    # bind-mount option syntax uses comma-separated options after
    # the second colon (e.g. ``:ro,Z``), so accept either ``:Z``
    # or ``,Z`` as proof the flag is present.
    md_line = [
        ln for ln in text.splitlines()
        if "/etc/wakir/persona/tomas.md" in ln and "Volume=" in ln
    ]
    assert any((":Z" in ln) or (",Z" in ln) for ln in md_line)


def test_quadlet_preserves_spire_socket_bind():
    text = _quadlet_text()
    assert "wakir-spire-agent-sockets.volume:/run/spire/agent-sockets" in text


def test_quadlet_preserves_persona_state_bucket_env():
    text = _quadlet_text()
    assert "WAKIR_PERSONA_STATE_BUCKET=wakir-persona-state-acme-tomas" in text


def test_quadlet_preserves_persona_id_env():
    text = _quadlet_text()
    assert "WAKIR_PERSONA_ID=tomas" in text


def test_quadlet_preserves_org_id_env():
    text = _quadlet_text()
    assert "WAKIR_ORG_ID=acme" in text


def test_quadlet_preserves_image_tag_form():
    """The image-tag form is still ``0.1.0-pilot@sha256:DIGEST_PENDING_*``
    pending Cross-Review Zone-J digest resolution. Sprint-Pengine-9
    keeps the tag-form anchor so the resolve-image-pins-ci workflow
    fills it in idempotently."""
    text = _quadlet_text()
    assert "wakir-persona-engine:" in text
    assert "DIGEST_PENDING_" in text


def test_quadlet_documents_operator_hand_pre_step():
    """The fix narrative requires the operator to stage the persona
    files at ``/etc/wakir/persona/`` before starting the service.
    The Quadlet header comment must document the pre-step so the
    operator does not have to read this test file to learn the
    expected host layout."""
    text = _quadlet_text()
    assert "Operator-Hand pre-step" in text or "Operator-Hand-staged" in text \
        or "OPERATOR-HAND" in text or "Bug-Quadlet-Drift" in text


def test_quadlet_documents_naming_drift_followup():
    text = _quadlet_text()
    assert "Naming-Anchor" in text or "naming-drift" in text or "dev-engineering" in text


def test_quadlet_no_naked_wakir_runtime_substring_in_binds():
    """Defence in depth: no ``Volume=`` line may reference
    ``wakir-runtime`` as a host-path component. (The
    ``WORKDIR=/opt/wakir-runtime`` inside the container is
    different and lives inside the Containerfile, not the Quadlet.)"""
    text = _quadlet_text()
    for ln in text.splitlines():
        if ln.startswith("Volume="):
            assert "/opt/wakir-runtime/" not in ln, (
                f"Volume= line still references /opt/wakir-runtime/: {ln}"
            )
