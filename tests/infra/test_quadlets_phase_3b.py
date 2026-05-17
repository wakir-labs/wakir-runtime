# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic format invariants for the Tag-22 Phase-3b Rust-CLI
installer Quadlet bundle (retry after Tag-21 quota-hit; identical
bytes-shape as the aborted Tag-21 draft).

Sibling tests
-------------
  * ``tests/infra/test_cosign_policy_phase_3b.py`` — Cosign-Policy
    (carrier image + 4-binary inventory).
  * ``tests/infra/test_persona_tomas_quadlet_validate.py`` — production
    Quadlet for the Tomás-Persona pilot (carrier image consumer).
  * ``tests/infra/test_quadlet_selinux_relabel.py`` — global
    SELinux-relabel discipline (every ``Volume=`` carries ``:Z``/``:z``).

This test surface validates the SHAPE of the Tag-22 deliverables:

  - ``quadlet/wakir-rust-cli.container``
  - ``quadlet/wakir-rust-cli-bin.volume``

NOT covered here (intentional sandbox boundary)
-----------------------------------------------
  * NO ``podman`` invocation against the host.
  * NO ``systemctl`` invocation.
  * NO live container start.
  * NO carrier-image pull from ghcr.io.

Live verification lives in
``docs/operations/quadlets-phase-3b-rust-cli.md`` §4 and is
Operator-Hand per ``feedback_sandbox_host_trennung.md`` +
ADR-0051 Mira-Sandbox-vs-Host-Operations-Trennung.

Test-Vector index
-----------------
  * ``TV-T22-Q-01`` Quadlet files present at the expected repo paths.
  * ``TV-T22-Q-02`` Container Quadlet declares the canonical sections
    (``[Unit]``, ``[Container]``, ``[Service]``, ``[Install]``).
  * ``TV-T22-Q-03`` All five Phase-3b binaries listed in the
    installer Exec= shell loop (recovery, state-backing, fsm,
    v907-verify, bridge-diff).
  * ``TV-T22-Q-04`` Image= line matches the Cosign-Policy
    carrier_image entry byte-for-byte (registry + repository +
    tag + placeholder digest slot).
  * ``TV-T22-Q-05`` SELinux relabel-private flag (``:Z``) and the
    uid-remap flag (``:U``) both present on the host-bin Volume=
    directive.
  * ``TV-T22-Q-06`` Restart=on-failure NOT used (oneshot install
    path uses ``Restart=no`` + ``Type=oneshot``).
  * ``TV-T22-Q-07`` Volume Quadlet declares the canonical sections
    (``[Unit]``, ``[Volume]``, ``[Install]``).
  * ``TV-T22-Q-08`` Operator-recipe documentation file present
    and references the Quadlet bundle.

-- Kai
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
QUADLET_CONTAINER = REPO_ROOT / "quadlet" / "wakir-rust-cli.container"
QUADLET_VOLUME = REPO_ROOT / "quadlet" / "wakir-rust-cli-bin.volume"
COSIGN_POLICY = REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
OPERATIONS_DOC = (
    REPO_ROOT / "docs" / "operations" / "quadlets-phase-3b-rust-cli.md"
)
RUST_SWITCH_MODULE = (
    REPO_ROOT / "wirelang" / "persona_engine" / "rust_backend_switch.py"
)

EXPECTED_BINARIES_FIVE = (
    "wakir-persona-engine-recovery",
    "wakir-persona-engine-state-backing",
    "wakir-persona-engine-fsm",
    "wakir-persona-engine-v907-verify",
    "wakir-persona-engine-bridge-diff",
)

# Canonical placeholder + canonical resolved-digest form (mirrors the
# Cosign-Policy + persona-tomas Quadlet convention).
PLACEHOLDER_DIGEST = "sha256:DIGEST_PENDING_KAI_CROSS_REVIEW"
CANONICAL_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
PLACEHOLDER_OR_CANONICAL_RE = re.compile(
    r"^(?:sha256:DIGEST_PENDING_KAI_CROSS_REVIEW|sha256:[a-f0-9]{64})$"
)

EXPECTED_CARRIER_IMAGE_REGISTRY = "ghcr.io"
EXPECTED_CARRIER_IMAGE_REPO = "wakir-labs/wakir-persona-engine"
EXPECTED_CARRIER_IMAGE_TAG = "0.5.0-pilot"


@pytest.fixture(scope="module")
def container_text() -> str:
    """Read the Tag-22 installer Quadlet (container unit) once
    per test-module."""
    assert QUADLET_CONTAINER.exists(), (
        f"Tag-22 container Quadlet missing at {QUADLET_CONTAINER}"
    )
    return QUADLET_CONTAINER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def volume_text() -> str:
    """Read the Tag-22 host-bin Quadlet (volume unit) once per
    test-module."""
    assert QUADLET_VOLUME.exists(), (
        f"Tag-22 volume Quadlet missing at {QUADLET_VOLUME}"
    )
    return QUADLET_VOLUME.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TV-T22-Q-01 — Quadlet files present at the expected repo paths.
# ---------------------------------------------------------------------------
def test_quadlet_files_present() -> None:
    """Both unit files exist and are non-empty.

    A future refactor that moves one of these files (e.g. into
    ``infra/quadlets/``) MUST update this test alongside the move
    so the production install path stays single-sourced.
    """
    assert QUADLET_CONTAINER.is_file(), (
        f"container Quadlet missing at {QUADLET_CONTAINER}"
    )
    assert QUADLET_VOLUME.is_file(), (
        f"volume Quadlet missing at {QUADLET_VOLUME}"
    )
    # Non-empty: a zero-byte file would silently pass a downstream
    # ``podman quadlet --dryrun`` because the generator skips empty
    # units. Catch that here.
    assert QUADLET_CONTAINER.stat().st_size > 0, (
        f"container Quadlet is zero bytes: {QUADLET_CONTAINER}"
    )
    assert QUADLET_VOLUME.stat().st_size > 0, (
        f"volume Quadlet is zero bytes: {QUADLET_VOLUME}"
    )


# ---------------------------------------------------------------------------
# TV-T22-Q-02 — Container Quadlet declares the canonical sections.
# ---------------------------------------------------------------------------
def test_container_section_invariants(container_text: str) -> None:
    """Quadlet container units MUST carry the four canonical
    section headers in topological order: ``[Unit]``,
    ``[Container]``, ``[Service]``, ``[Install]``.

    Drift-guard: a future refactor that drops ``[Install]`` would
    leave the unit invisible to ``systemctl enable``; this test
    pins the section inventory.
    """
    required_sections = ("[Unit]", "[Container]", "[Service]", "[Install]")
    for section in required_sections:
        assert section in container_text, (
            f"container Quadlet missing required section: {section}"
        )

    # Ordering: each section header must appear AFTER the previous
    # one's offset (topological ordering matters for systemd-quadlet
    # generator parsing).
    offsets = [container_text.index(section) for section in required_sections]
    assert offsets == sorted(offsets), (
        f"container Quadlet section order drift: got offsets {offsets} "
        f"for sections {required_sections}"
    )


# ---------------------------------------------------------------------------
# TV-T22-Q-03 — All five Phase-3b binaries listed in Exec= loop.
# ---------------------------------------------------------------------------
def test_all_five_binaries_listed(container_text: str) -> None:
    """The installer Exec= shell loop MUST iterate over all five
    Phase-3b Rust-CLI binary names (recovery, state-backing, fsm,
    v907-verify, bridge-diff).

    Drift-guard: dropping a binary from the loop would silently
    leave the corresponding ``WAKIR_*_BACKEND=rust`` switch
    falling back to Python on Pilot-VM hosts that consume the
    installer (the host-side ``/opt/wakir/bin/<missing>`` would
    not be populated). This test red is a hard-stop.
    """
    # Find the Exec= line (single-line in our Quadlet form).
    exec_lines = [
        line for line in container_text.splitlines()
        if line.startswith("Exec=")
    ]
    assert len(exec_lines) == 1, (
        f"container Quadlet must declare exactly one Exec= line, "
        f"got {len(exec_lines)}: {exec_lines}"
    )
    exec_line = exec_lines[0]

    for binary in EXPECTED_BINARIES_FIVE:
        assert binary in exec_line, (
            f"Phase-3b binary {binary!r} missing from Exec= shell loop"
        )

    # And the bridge-diff binary specifically — Tag-20 PR #175 wired
    # the switch; the Tag-22 Quadlet MUST install the binary even
    # though the Cosign-Policy inventory has not yet been extended
    # (tracked as a Tag-23+ follow-up).
    assert "wakir-persona-engine-bridge-diff" in exec_line, (
        "Tag-20 bridge-diff binary missing from Tag-22 installer "
        "Exec= loop — see docs/operations/quadlets-phase-3b-rust-cli.md §2"
    )


# ---------------------------------------------------------------------------
# TV-T22-Q-04 — Image= line matches Cosign-Policy carrier_image.
# ---------------------------------------------------------------------------
def test_image_pin_matches_cosign_policy(container_text: str) -> None:
    """The Quadlet ``Image=`` directive MUST match the Cosign-Policy
    ``carrier_image`` entry byte-for-byte on registry + repository +
    tag + digest slot.

    Drift-guard: a future bump of the carrier-image tag in either
    file without updating the other would break the ``resolve-
    image-pins-ci.yml`` workflow's single-source-of-truth contract.
    This test pins both files in lock-step.
    """
    # Find the Image= line.
    image_lines = [
        line for line in container_text.splitlines()
        if line.startswith("Image=")
    ]
    assert len(image_lines) == 1, (
        f"container Quadlet must declare exactly one Image= line, "
        f"got {len(image_lines)}"
    )
    image_value = image_lines[0][len("Image="):].strip()

    # Form: <registry>/<repo>:<tag>@<digest>
    image_re = re.compile(
        r"^"
        r"(?P<registry>[^/]+)"
        r"/"
        r"(?P<repo>[^:]+)"
        r":"
        r"(?P<tag>[^@]+)"
        r"@"
        r"(?P<digest>sha256:[A-Za-z0-9_]+)"
        r"$"
    )
    match = image_re.match(image_value)
    assert match is not None, (
        f"Image= directive does not match canonical "
        f"<registry>/<repo>:<tag>@sha256:<digest> form: {image_value!r}"
    )
    assert match.group("registry") == EXPECTED_CARRIER_IMAGE_REGISTRY, (
        f"Image= registry drift: {match.group('registry')!r}"
    )
    assert match.group("repo") == EXPECTED_CARRIER_IMAGE_REPO, (
        f"Image= repository drift: {match.group('repo')!r}"
    )
    assert match.group("tag") == EXPECTED_CARRIER_IMAGE_TAG, (
        f"Image= tag drift: expected {EXPECTED_CARRIER_IMAGE_TAG!r}, "
        f"got {match.group('tag')!r}"
    )
    digest_slot = match.group("digest")
    assert PLACEHOLDER_OR_CANONICAL_RE.match(digest_slot), (
        f"Image= digest slot is neither the canonical "
        f"DIGEST_PENDING_KAI_CROSS_REVIEW placeholder nor a "
        f"sha256:<64-hex> canonical form: {digest_slot!r}"
    )

    # Cross-file parity: the Cosign-Policy declares the same image
    # tag + digest-slot form. We do a substring check (a full YAML
    # parse lives in test_cosign_policy_phase_3b.py).
    assert COSIGN_POLICY.is_file(), (
        f"Cosign-Policy missing at {COSIGN_POLICY}"
    )
    policy_text = COSIGN_POLICY.read_text(encoding="utf-8")
    assert f"expected_tag: {EXPECTED_CARRIER_IMAGE_TAG}" in policy_text, (
        "Cosign-Policy carrier_image.expected_tag does not match the "
        "Tag-22 Quadlet Image= tag — Zone-C parity violation"
    )
    assert EXPECTED_CARRIER_IMAGE_REPO in policy_text, (
        "Cosign-Policy carrier_image.repository does not match the "
        "Tag-22 Quadlet Image= repository — Zone-C parity violation"
    )


# ---------------------------------------------------------------------------
# TV-T22-Q-05 — SELinux + uid-remap flags present on host-bin Volume.
# ---------------------------------------------------------------------------
def test_selinux_and_uid_remap_flags(container_text: str) -> None:
    """The host-bin Volume= directive MUST carry both ``:Z`` (SELinux
    relabel-private; Sprint-9-Tag-8 Bug-20 substance-fix) and ``:U``
    (named-volume uid:1000 remap; parity with SPIRE-Agent + NATS
    named volumes).

    Drift-guard: dropping ``:Z`` causes EACCES on first write on
    FCOS enforcing-mode hosts (Bug-20 root cause); dropping ``:U``
    causes the install step to fail because the container runs as
    uid:1000 but the empty volume is initialised root-owned. Both
    flags are mandatory.
    """
    # Find the host-bin Volume= directive specifically.
    volume_lines = [
        line for line in container_text.splitlines()
        if line.startswith("Volume=") and "wakir-rust-cli-bin" in line
    ]
    assert len(volume_lines) == 1, (
        f"container Quadlet must declare exactly one wakir-rust-cli-bin "
        f"Volume= directive, got {len(volume_lines)}: {volume_lines}"
    )
    volume_line = volume_lines[0]

    # Extract options (the part after the second ``:``).
    # Format: Volume=<source>:<target>:<options>
    parts = volume_line[len("Volume="):].split(":")
    assert len(parts) >= 3, (
        f"Volume= directive missing options field "
        f"(expected <src>:<dst>:<opts>): {volume_line!r}"
    )
    options = parts[-1]
    options_set = {opt.strip() for opt in options.split(",")}

    assert "Z" in options_set, (
        f"host-bin Volume= missing :Z SELinux relabel-private flag "
        f"(Sprint-9-Tag-8 Bug-20 discipline): {volume_line!r}"
    )
    assert "U" in options_set, (
        f"host-bin Volume= missing :U uid-remap flag "
        f"(named-volume parity with SPIRE-Agent + NATS): "
        f"{volume_line!r}"
    )


# ---------------------------------------------------------------------------
# TV-T22-Q-06 — oneshot install path uses Type=oneshot + Restart=no.
# ---------------------------------------------------------------------------
def test_oneshot_restart_posture(container_text: str) -> None:
    """The installer is a oneshot — ``Type=oneshot`` and
    ``Restart=no`` MUST both be declared. ``Restart=on-failure``
    (the sibling persona-tomas posture) is the WRONG posture for
    an installer: a failed install should be operator-visible,
    not auto-masked by a restart loop.

    Drift-guard: a future refactor that copies the persona-tomas
    Service section over without thinking would silently flip
    this to ``Restart=on-failure``. This test reds that change.
    """
    assert "Type=oneshot" in container_text, (
        "container Quadlet missing Type=oneshot — installer must be "
        "oneshot, not long-running"
    )
    assert "Restart=no" in container_text, (
        "container Quadlet missing Restart=no — installer failure "
        "must be operator-visible, not auto-masked by restart loop"
    )
    # And the opposite must NOT be present.
    assert "Restart=on-failure" not in container_text, (
        "container Quadlet declares Restart=on-failure — wrong "
        "posture for a oneshot installer"
    )
    assert "Restart=always" not in container_text, (
        "container Quadlet declares Restart=always — wrong posture "
        "for a oneshot installer"
    )


# ---------------------------------------------------------------------------
# TV-T22-Q-07 — Volume Quadlet declares the canonical sections.
# ---------------------------------------------------------------------------
def test_volume_section_invariants(volume_text: str) -> None:
    """Quadlet volume units MUST carry the three canonical section
    headers in topological order: ``[Unit]``, ``[Volume]``,
    ``[Install]``.

    Drift-guard: parity with the sibling
    ``wakir-persona-tomas-workspace.volume`` shape.
    """
    required_sections = ("[Unit]", "[Volume]", "[Install]")
    for section in required_sections:
        assert section in volume_text, (
            f"volume Quadlet missing required section: {section}"
        )

    offsets = [volume_text.index(section) for section in required_sections]
    assert offsets == sorted(offsets), (
        f"volume Quadlet section order drift: got offsets {offsets} "
        f"for sections {required_sections}"
    )


# ---------------------------------------------------------------------------
# TV-T22-Q-08 — Operator-recipe documentation file present.
# ---------------------------------------------------------------------------
def test_operations_doc_present_and_references_quadlets() -> None:
    """The operator-recipe documentation file MUST exist and
    explicitly reference both Quadlet unit files by name. The
    Quadlet README MUST link back to the operations doc.

    Drift-guard: a future PR that adds a third Quadlet unit
    (e.g. a timer) MUST update this doc; if the doc goes missing
    entirely (someone moves it / renames it without updating
    callers) this test reds.
    """
    assert OPERATIONS_DOC.is_file(), (
        f"operations doc missing at {OPERATIONS_DOC}"
    )
    doc_text = OPERATIONS_DOC.read_text(encoding="utf-8")
    assert "wakir-rust-cli.container" in doc_text, (
        "operations doc does not reference wakir-rust-cli.container"
    )
    assert "wakir-rust-cli-bin.volume" in doc_text, (
        "operations doc does not reference wakir-rust-cli-bin.volume"
    )
    # All five binaries enumerated by name in the doc (operator-
    # reading-substrate, not just the Exec= loop).
    for binary in EXPECTED_BINARIES_FIVE:
        assert binary in doc_text, (
            f"operations doc does not enumerate binary {binary!r}"
        )

    # Cross-link from Quadlet README.
    quadlet_readme = REPO_ROOT / "quadlet" / "README.md"
    assert quadlet_readme.is_file(), (
        f"quadlet/README.md missing at {quadlet_readme}"
    )
    readme_text = quadlet_readme.read_text(encoding="utf-8")
    assert "wakir-rust-cli.container" in readme_text, (
        "quadlet/README.md does not reference the Tag-22 installer "
        "Quadlet — inventory drift"
    )
    assert "quadlets-phase-3b-rust-cli.md" in readme_text, (
        "quadlet/README.md does not link to the Tag-22 operations doc"
    )


# ---------------------------------------------------------------------------
# TV-T22-Q-09 — In-image paths match rust_backend_switch.py defaults.
# ---------------------------------------------------------------------------
def test_in_image_paths_match_switch_defaults(container_text: str) -> None:
    """The installer Exec= loop MUST install binaries at the same
    canonical in-image paths that the
    ``DEFAULT_RUST_*_BIN`` constants in
    ``wirelang/persona_engine/rust_backend_switch.py`` declare.

    The host-side install location is ``/host-bin/`` inside the
    container (Volume= mount-target), which the named-volume
    surfaces at ``/opt/wakir/bin/`` on the host. The source paths
    inside the carrier image are ``/opt/wakir/bin/<binary>`` per
    the persona-engine Containerfile.real install layout.

    Drift-guard: if Selin renames a crate's binary output name
    (e.g. ``wakir-persona-engine-recovery`` -> ``persona-engine-
    recovery``) the switch defaults move and this Quadlet's source
    paths must move in lock-step.
    """
    assert RUST_SWITCH_MODULE.is_file(), (
        f"rust_backend_switch.py missing at {RUST_SWITCH_MODULE}"
    )
    switch_text = RUST_SWITCH_MODULE.read_text(encoding="utf-8")

    for binary in EXPECTED_BINARIES_FIVE:
        canonical_path = f"/opt/wakir/bin/{binary}"
        assert canonical_path in switch_text, (
            f"rust_backend_switch.py default does NOT declare "
            f"{canonical_path!r} — switch / Quadlet path drift"
        )
        assert canonical_path in container_text, (
            f"installer Quadlet Exec= does NOT reference the "
            f"in-image source path {canonical_path!r}"
        )
