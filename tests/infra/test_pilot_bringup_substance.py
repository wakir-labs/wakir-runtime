# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""End-to-End Live-Bring-up Substanz-Test-Suite (Phase-2 Sprint-9 Tag-4).

Context
-------

On 2026-05-13 the AR-Operator-Hand ran the
``wakir-pilot-bootstrap.sh`` against a fresh Fedora-CoreOS Pilot-VM
(Proxmox host). The bootstrap blocked twice mid-flight and the Smoke-
Test ended at 1/6 PASS. The Mira-Bug-Bilanz
(``agents-workspaces/mira/outbox/2026-05-13-pilot-bringup-bug-bilanz.md``)
documented seven substance-bugs, NONE of which were caught by the
existing hermetic test surface (``tests/infra/test_pilot_bootstrap.py``
asserts script-shape; ``infra/spire/federation/tests/`` asserts
compose<->quadlet parity).

This suite adds substance-level negative tests that target each of the
seven bugs by inspecting the SOURCE templates and the bootstrap-script
LOGIC. Every test is hermetic — no VM, no podman, no systemd. Tests
that need a privileged container substrate live in the sibling module
``test_pilot_bringup_e2e_container.py``.

Test-Vector index
-----------------

  * ``TV-BRINGUP-01`` Volume-File-Naming-Consistency (Bug 2)
  * ``TV-BRINGUP-02`` Agent-Container Volume-Reference matches Server-
    Federation-Volume names (Bug 3)
  * ``TV-BRINGUP-03`` Agent-Container Requires-Service-Name matches the
    Server-Federation-Service name the bootstrap script generates
    (Bug 4)
  * ``TV-BRINGUP-04`` Phase-6-Idempotency: re-run preserves manual fixes
    OR generates correct substance from-scratch (Bug 5)
  * ``TV-BRINGUP-05`` Bucket-Init container has the dependency-substrate
    needed to import ``wirelang.federation.marker_stack_kv`` without
    pulling ``cryptography`` (Bug 6)
  * ``TV-BRINGUP-06`` SPIRE-Server-Service-Config-Substrate: server-conf
    bind-mount path that the bootstrap installs matches the
    generated unit's bind-mount expectation (Bug 7 — config-substrate-
    correctness; the actual ``active (running)`` check sits in the
    e2e-container suite where we can drive systemd)
  * ``TV-BRINGUP-07`` Bootstrap-Skript Resume-Hint has no ``bash bash``
    doubling (Bug 1, cosmetic but AR-visible)

Sandbox boundary
----------------

All tests read source files and parse them. No subprocess invocations
that could touch network, podman, or systemd. The companion CI lane
that DOES drive a privileged container lives in
``test_pilot_bringup_e2e_container.py``.

— Amara
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)
FED_QUADLET_DIR = REPO_ROOT / "infra" / "spire" / "federation" / "quadlet"
AGENT_QUADLET_DIR = REPO_ROOT / "infra" / "spire" / "agent" / "quadlet"
ROOT_QUADLET_DIR = REPO_ROOT / "quadlet"

SERVER_FED_TPL = FED_QUADLET_DIR / "wakir-spire-server-federation.container"
SERVER_FED_DATA_VOL = (
    FED_QUADLET_DIR / "wakir-spire-server-federation-data.volume"
)
SERVER_FED_SOCKETS_VOL = (
    FED_QUADLET_DIR / "wakir-spire-server-federation-sockets.volume"
)
SERVER_FED_BUNDLES_VOL = (
    FED_QUADLET_DIR / "wakir-spire-server-federation-bundles.volume"
)
AGENT_FED_TPL = AGENT_QUADLET_DIR / "wakir-spire-agent-federation.container"
AGENT_FED_DATA_VOL = (
    AGENT_QUADLET_DIR / "wakir-spire-agent-federation-data.volume"
)
AGENT_FED_SOCKETS_VOL = (
    AGENT_QUADLET_DIR / "wakir-spire-agent-federation-sockets.volume"
)
BUCKET_INIT_UNIT = ROOT_QUADLET_DIR / "wakir-nats-kv-bucket-init.container"
BUCKET_INIT_BIN = REPO_ROOT / "bin" / "nats-kv-bucket-provision"
WIRELANG_FED_INIT = REPO_ROOT / "wirelang" / "federation" / "__init__.py"
WIRELANG_MARKER_STACK = (
    REPO_ROOT / "wirelang" / "federation" / "marker_stack_kv.py"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sed_side(text: str, side: str) -> str:
    """Apply the SAME ``<SIDE>`` substitution the bootstrap uses on
    file content (Phase 6b–6d)."""
    return text.replace("<SIDE>", side)


def _bootstrap_text() -> str:
    return BOOTSTRAP.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TV-BRINGUP-01 — Volume-File-Naming-Consistency (Bug 2)
# ---------------------------------------------------------------------------
#
# After ``<SIDE>`` substitution on the SERVER-FEDERATION-CONTAINER, the
# Volume= directives reference a Quadlet-Unit-Filename of the shape
# ``wakir-spire-server-federation-<side>-data.volume``. The Quadlet
# generator resolves that string against installed filenames in
# ``/etc/containers/systemd``. The source template volume files are
# named WITHOUT the ``<side>`` middle segment
# (``wakir-spire-server-federation-data.volume``), so unless the
# bootstrap renames the file on install, the generator cannot find a
# match and the unit fails with "volume source not found".
#
# This vector asserts the bootstrap install logic produces a matching
# pair (container reference + installed filename) for at least one
# representative side.


@pytest.mark.parametrize("side", ["wakir", "partner"])
def test_tv_bringup_01_server_federation_volume_filename_resolves(
    side: str,
) -> None:
    """For each side, every ``Volume=...volume:...`` reference in the
    substituted server-federation-container MUST resolve to a Quadlet
    volume filename the bootstrap actually installs."""
    container_text = _sed_side(SERVER_FED_TPL.read_text(encoding="utf-8"), side)

    # Collect referenced .volume filenames (just the unit name, no path).
    referenced = set(
        re.findall(
            r"^Volume=([A-Za-z0-9._-]+\.volume):",
            container_text,
            re.MULTILINE,
        )
    )
    assert referenced, (
        f"server-federation-container for side={side!r} references no "
        f".volume units; the regression net cannot evaluate the Quadlet "
        f"resolution path"
    )

    # The bootstrap's Phase 6b installs every source .volume under
    # FED_QUADLET_DIR and AGENT_QUADLET_DIR, applying the SAME
    # filename-side-substitution as on file content.
    sources = (
        list(FED_QUADLET_DIR.glob("*.volume"))
        + list(AGENT_QUADLET_DIR.glob("*.volume"))
        + list(ROOT_QUADLET_DIR.glob("*.volume"))
    )
    installed = {p.name.replace("<SIDE>", side) for p in sources}

    missing = referenced - installed
    assert not missing, (
        f"server-federation-container for side={side!r} references "
        f"volume unit(s) the bootstrap does NOT install: {sorted(missing)}\n"
        f"  source filenames available (after <SIDE> sub): "
        f"{sorted(installed)}\n"
        f"This is Bug 2 from the 2026-05-13 Mira-Bug-Bilanz."
    )


def test_tv_bringup_01_bootstrap_installs_volumes_with_side_aware_filename() -> None:
    """Phase 6b of the bootstrap MUST apply the ``<SIDE>`` substitution
    to the volume filename (not just the file content). Otherwise the
    installed filename loses the ``-<side>-`` segment the container
    template requires."""
    text = _bootstrap_text()

    # Slice out Phase 6b roughly: from '6b. Volumes' to '6c.'
    m = re.search(r"# 6b\. Volumes.*?# 6c\.", text, re.DOTALL)
    assert m, "could not locate Phase 6b (Volumes) in the bootstrap script"
    phase_6b = m.group(0)

    # The substitution must happen on the FILENAME, not just on the
    # content. Pattern: a sed/sub on the basename inside the loop.
    # Acceptable forms:
    #   base=$(basename "$v" | sed ... -e "s/<SIDE>/${side}/g" ...)
    #   base=${base//<SIDE>/${side}}
    #   sed-rename via mv after install
    has_filename_sub = bool(
        re.search(
            r"basename .* sed.*<SIDE>",
            phase_6b,
            re.DOTALL,
        )
        or re.search(r"\$\{[A-Za-z_]+//<SIDE>/", phase_6b)
        or re.search(r'mv .*"<SIDE>".*"\${side}"', phase_6b)
    )

    # Stronger check: at least one source .volume must require the
    # ``-<SIDE>-`` segment in its filename to resolve. Today, the
    # server-federation-data/sockets/bundles volumes do NOT have <SIDE>
    # in their source filename, so the bootstrap MUST rename them on
    # install. If no filename substitution exists in Phase 6b, this is
    # Bug 2.
    if not has_filename_sub:
        # Fail with a clear pointer.
        pytest.fail(
            "Phase 6b of wakir-pilot-bootstrap.sh does NOT apply <SIDE>\n"
            "substitution to the installed volume FILENAME (only to the\n"
            "content). The server-federation-container resolves\n"
            "Volume=wakir-spire-server-federation-<side>-data.volume,\n"
            "which requires the installed file to be named with the\n"
            "``-<side>-`` segment in the filename, not just inside the\n"
            "[Volume] block.\n\n"
            "This is Bug 2 from the 2026-05-13 Mira-Bug-Bilanz."
        )


# ---------------------------------------------------------------------------
# TV-BRINGUP-02 — Agent-Container Volume-Reference matches Server-Federation
#                 -Volume names (Bug 3)
# ---------------------------------------------------------------------------
#
# The agent-federation-container template MUST reference the
# server-federation-bundles volume by the SAME name the server template
# declares. Mismatch (e.g. ``wakir-spire-server-<SIDE>-bundles`` vs
# ``wakir-spire-server-federation-<SIDE>-bundles``) means the agent
# cannot mount the bundles share at all.


@pytest.mark.parametrize("side", ["wakir", "partner"])
def test_tv_bringup_02_agent_references_existing_server_bundles_volume(
    side: str,
) -> None:
    agent_text = _sed_side(AGENT_FED_TPL.read_text(encoding="utf-8"), side)

    # Find every Volume= line that references a server-side volume.
    server_refs = re.findall(
        r"^Volume=(wakir-spire-server[A-Za-z0-9._-]*\.volume):",
        agent_text,
        re.MULTILINE,
    )
    assert server_refs, (
        f"agent-federation-container for side={side!r} declares no "
        f"server-side volume mount; bundle-share path missing"
    )

    # Source-side server volumes (after <SIDE> sub) the bootstrap WILL
    # install. The server-federation set lives under FED_QUADLET_DIR.
    server_sources = list(FED_QUADLET_DIR.glob("wakir-spire-server*.volume"))
    server_installed = {p.name.replace("<SIDE>", side) for p in server_sources}

    # If Phase 6b doesn't apply filename-substitution yet (Bug 2),
    # ``server_installed`` will only contain the source-shape names;
    # we accept either shape as "installed" for the cross-check so this
    # test cleanly isolates Bug 3 from Bug 2.
    raw_sources = {p.name for p in server_sources}
    candidates = server_installed | raw_sources

    missing = [ref for ref in server_refs if ref not in candidates]
    assert not missing, (
        f"agent-federation-container for side={side!r} references "
        f"server volume(s) that DO NOT exist as Quadlet unit files:\n"
        f"  missing: {missing}\n"
        f"  available (after <SIDE> sub OR raw): {sorted(candidates)}\n\n"
        f"This is Bug 3 from the 2026-05-13 Mira-Bug-Bilanz: the agent\n"
        f"template references ``wakir-spire-server-<SIDE>-bundles.volume``\n"
        f"but the server template declares it as\n"
        f"``wakir-spire-server-federation-<SIDE>-bundles.volume``."
    )


# ---------------------------------------------------------------------------
# TV-BRINGUP-03 — Agent-Container Requires-Service matches generated
#                 Server-Federation-Service name (Bug 4)
# ---------------------------------------------------------------------------
#
# The bootstrap Phase 6c writes the server unit file as
# ``wakir-spire-server-federation-${side}.container``, which systemd
# turns into ``wakir-spire-server-federation-${side}.service``. The
# agent's [Unit] block contains Requires=/After= lines that must point
# at that EXACT service name. The current agent template references
# ``wakir-spire-server-<SIDE>.service`` (no ``-federation-`` segment),
# so the agent cannot resolve its hard dependency.


@pytest.mark.parametrize("side", ["wakir", "partner"])
def test_tv_bringup_03_agent_requires_match_server_federation_service(
    side: str,
) -> None:
    agent_text = _sed_side(AGENT_FED_TPL.read_text(encoding="utf-8"), side)

    requires_lines = re.findall(
        r"^(?:Requires|After|Wants)=(.+)$", agent_text, re.MULTILINE
    )
    server_refs = []
    for line in requires_lines:
        for tok in line.split():
            if tok.startswith("wakir-spire-server") and tok.endswith(".service"):
                server_refs.append(tok)

    assert server_refs, (
        f"agent-federation-container for side={side!r} declares no "
        f"server-service dependency; agent will race the server unit"
    )

    # The bootstrap-installed server unit filename derives from the
    # server-federation-container source. Read its [Unit] target name
    # using the same install logic: file installed as
    # ``wakir-spire-server-federation-${side}.container`` → service
    # ``wakir-spire-server-federation-${side}.service``.
    expected_server_service = (
        f"wakir-spire-server-federation-{side}.service"
    )

    mismatched = [ref for ref in server_refs if ref != expected_server_service]
    assert not mismatched, (
        f"agent-federation-container for side={side!r} requires server "
        f"service(s) {mismatched!r} but the bootstrap installs the\n"
        f"server unit as {expected_server_service!r}.\n\n"
        f"This is Bug 4 from the 2026-05-13 Mira-Bug-Bilanz."
    )


# ---------------------------------------------------------------------------
# TV-BRINGUP-04 — Phase-6 Idempotency (Bug 5)
# ---------------------------------------------------------------------------
#
# Re-running the bootstrap with ``--resume-from 6`` must either:
#   (a) preserve operator-hand manual fixes on the installed Quadlet
#       files (i.e. detect "already fixed" content and skip), OR
#   (b) re-derive the correct substance from-scratch so any manual
#       fix becomes redundant (i.e. the source template substitution
#       produces a unit identical to what the operator hand-edited).
#
# In practice, option (b) is the desired path: every bug 2/3/4 fix
# upstream means the source template needs no manual-fix at all.
# This test asserts the bootstrap has SOME idempotency guard on
# Phase 6 — either a content-comparison or a structured "already
# installed" check.


def test_tv_bringup_04_phase_6_has_idempotency_guard() -> None:
    """Phase 6 INSTALL operations (6b volumes, 6c server, 6d agent, 6e
    NATS) must be content-idempotent: re-running should NOT overwrite
    a file whose content is already equal to the substituted source.
    The acceptable mechanism is ``cmp -s "$src" "$dst"`` before
    install (mirror of Phase 7's bucket-init pattern, which already
    has this guard).

    A weaker ``already present`` log marker on the START path (Phase
    6f) is necessary too, but it's not sufficient: an unconditional
    overwrite of the unit FILE before the start-guard runs still
    destroys operator-hand manual fixes.
    """
    text = _bootstrap_text()
    m = re.search(
        r"step_6_quadlet\(\) \{.*?^\}", text, re.DOTALL | re.MULTILINE
    )
    assert m, "step_6_quadlet function body not found in bootstrap"
    phase_6 = m.group(0)

    # Phase 6's INSTALL sub-steps (6b-6e) currently do:
    #   sed -e "s/<SIDE>/${side}/g" "$v" > "${dst}/${base}"
    # without any cmp-guard. Re-running overwrites unconditionally.
    has_install_idempotency = bool(
        re.search(
            r"(cmp -s|diff -q).*\$dst|cmp -s.*\$src",
            phase_6,
        )
    )

    assert has_install_idempotency, (
        "Phase 6 INSTALL path of wakir-pilot-bootstrap.sh has NO\n"
        "content-equality guard (no ``cmp -s`` / ``diff -q`` before\n"
        "the ``sed > $dst`` write). Re-running ``--resume-from 6``\n"
        "unconditionally overwrites the installed Quadlet files,\n"
        "destroying any operator-hand manual fix the operator applied\n"
        "to work around Bugs 2/3/4 in a previous run.\n\n"
        "Reference pattern: Phase 7 (bucket-init) already does\n"
        "``if ! cmp -s \"$src\" \"$dst\" 2>/dev/null; then install -m 644 ...``.\n"
        "Apply the same pattern to 6b/6c/6d/6e.\n\n"
        "This is Bug 5 from the 2026-05-13 Mira-Bug-Bilanz."
    )


def test_tv_bringup_04_phase_6_units_idempotent_on_active_units() -> None:
    """For the systemctl start invocations inside Phase 6, the script
    must guard ``systemctl start`` with ``is-active --quiet`` so a
    re-run does not bounce already-running units."""
    text = _bootstrap_text()
    m = re.search(
        r"step_6_quadlet\(\) \{.*?^\}", text, re.DOTALL | re.MULTILINE
    )
    assert m, "step_6_quadlet function body not found"
    phase_6 = m.group(0)
    assert "is-active --quiet" in phase_6, (
        "Phase 6 must use ``systemctl is-active --quiet`` to guard\n"
        "``systemctl start`` so re-runs don't bounce healthy units.\n"
        "This is the runtime half of Bug 5."
    )


# ---------------------------------------------------------------------------
# TV-BRINGUP-05 — Bucket-Init container dependency-substrate (Bug 6)
# ---------------------------------------------------------------------------
#
# The bucket-init Quadlet unit runs ``nats-kv-bucket-provision`` inside a
# ``python:3.13-slim`` container. The provisioner imports modules from
# the ``wirelang.federation`` package via the repo bind-mount. The
# Mira-Bug-Bilanz documents that this transitively pulls
# ``wirelang.identity.key_derivation`` -> ``cryptography``, which is
# not in the base image. There are three acceptable resolutions:
#
#   A) The base image already ships cryptography (Image= changes), OR
#   B) The container Exec runs `pip install cryptography ...` before
#      `python3 /opt/wakir/bin/nats-kv-bucket-provision`, OR
#   C) The provisioner script and the modules it imports have NO
#      transitive cryptography dependency at import time.
#
# Option C is the Mira-recommendation. This test asserts that EITHER
# the image-side resolution exists, OR the import surface of the
# provisioner is decoupled (heuristic: provisioner only imports
# ``wirelang.federation.marker_stack_kv`` constants, which the
# ``wirelang.federation.__init__`` exposes WITHOUT eagerly importing
# ``wirelang.identity``).


def test_tv_bringup_05_bucket_init_has_no_cryptography_dependency_path() -> None:
    """The provisioner the bucket-init container Exec invokes MUST be
    importable in an environment that has only the container's documented
    deps (``nats-py``, ``jsonschema``, ``rfc8785``) -- in particular,
    WITHOUT ``cryptography``. We assert this in two layers:

      Layer 1 (static): the Quadlet unit has either a cryptography-
        bearing image, an Exec-time ``pip install cryptography``, OR
        the provisioner's static import graph keeps clear of
        ``wirelang.identity``.
      Layer 2 (dynamic-cheap): if ``cryptography`` is importable in the
        test environment, simulate its absence by tracing transitive
        imports from the entry module and assert ``cryptography`` is
        not requested.
    """
    # Layer 1: static surface
    unit_text = BUCKET_INIT_UNIT.read_text(encoding="utf-8")
    exec_block = "\n".join(
        line for line in unit_text.splitlines() if line.startswith("Exec=")
    )
    image_line = next(
        (
            line
            for line in unit_text.splitlines()
            if line.startswith("Image=")
        ),
        "",
    )
    has_pip_install = "pip install" in exec_block and "cryptography" in exec_block
    has_pre_baked_image = (
        "python:3.13" in image_line and "slim" not in image_line
    )
    if has_pip_install or has_pre_baked_image:
        return  # Resolution A or B in place

    # Layer 2: dynamic import-graph trace.
    #
    # We import the SAME entry-point module the container would import
    # (``bin.nats_kv_bucket_provision``) under an import-hook that
    # records every requested module name. If ``cryptography`` shows up
    # in the requested set, Bug 6 is unresolved.
    import builtins
    import importlib
    import importlib.util
    import sys as _sys

    requested: set[str] = set()
    real_import = builtins.__import__

    def tracing_import(name, *args, **kw):  # type: ignore[no-untyped-def]
        requested.add(name.split(".", 1)[0])
        return real_import(name, *args, **kw)

    # Provisioner module path; load via spec to avoid namespace clobber.
    bin_module_path = REPO_ROOT / "bin" / "nats_kv_bucket_provision.py"
    if not bin_module_path.exists():
        pytest.skip("bin/nats_kv_bucket_provision.py not present")

    # Save and replace.
    builtins.__import__ = tracing_import  # type: ignore[assignment]
    # Drop any cached wirelang modules so the import-trace is real.
    for mod in [m for m in list(_sys.modules) if m.startswith("wirelang")]:
        del _sys.modules[mod]
    for mod in [
        m for m in list(_sys.modules) if m.startswith("cryptography")
    ]:
        del _sys.modules[mod]
    try:
        spec = importlib.util.spec_from_file_location(
            "_amara_test_provisioner", bin_module_path
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError as exc:
            # If cryptography itself is missing in this env, the import
            # raised -- that PROVES the bug. Mark the requested set so
            # the assertion below fires with a clear message.
            if "cryptography" in str(exc):
                requested.add("cryptography")
            else:
                raise
    finally:
        builtins.__import__ = real_import  # type: ignore[assignment]

    assert "cryptography" not in requested, (
        "Provisioner module ``bin/nats_kv_bucket_provision.py`` "
        "transitively imports ``cryptography`` (via "
        "``wirelang.federation`` -> ``wirelang.identity.key_derivation``). "
        "The bucket-init container's ``python:3.13-slim`` base image does "
        "not ship cryptography, so the container will crash on start with "
        "``ModuleNotFoundError: No module named 'cryptography'``.\n\n"
        "Resolution options (Mira-Bug-Bilanz, Bug 6): "
        "A) image with cryptography baked in; "
        "B) Exec-time pip install; "
        "C) decouple the provisioner from ``wirelang.identity`` "
        "(Mira-recommended).\n\n"
        f"Modules requested at import-time: {sorted(requested)}"
    )


# ---------------------------------------------------------------------------
# TV-BRINGUP-06 — SPIRE-Server config-substrate correctness (Bug 7)
# ---------------------------------------------------------------------------
#
# Bug 7 manifests as a crash-loop. Root cause may be config-path,
# trust-domain bootstrap, health-check timeout, or volume-permission.
# The substance-test here covers the config-path half (which IS
# inspectable hermetically); the runtime-check sits in the e2e-
# container suite.
#
# Specifically: Phase 6c installs the server-conf file at
# ``/etc/wakir/spire-federation/spire-server-${side}.conf``, and the
# container template MUST bind-mount that exact path.


@pytest.mark.parametrize("side", ["wakir", "partner"])
def test_tv_bringup_06_server_conf_path_matches_bootstrap_install(
    side: str,
) -> None:
    container_text = _sed_side(SERVER_FED_TPL.read_text(encoding="utf-8"), side)
    text = _bootstrap_text()

    # Find the host-side conf path the container expects to read.
    conf_mounts = re.findall(
        r"^Volume=(/etc/wakir/[^:]+\.conf):/etc/spire/server/server\.conf",
        container_text,
        re.MULTILINE,
    )
    assert conf_mounts, (
        f"server-federation-container for side={side!r} does NOT "
        f"bind-mount a host config path; the container will run with "
        f"no server.conf and crash on startup"
    )

    # Confirm the bootstrap installs the conf file at that same path.
    expected = conf_mounts[0]  # e.g. /etc/wakir/spire-federation/spire-server-wakir.conf
    # Bootstrap Phase 6c does:
    #   install -m 644 "$server_conf"
    #     "/etc/wakir/spire-federation/spire-server-${side}.conf"
    bootstrap_target_pattern = re.search(
        r'/etc/wakir/spire-federation/spire-server-\$\{side\}\.conf', text
    )
    assert bootstrap_target_pattern, (
        "bootstrap Phase 6c does NOT install spire-server-${side}.conf "
        "at /etc/wakir/spire-federation/; container will mount an "
        "empty file. This is the config-path half of Bug 7."
    )

    # Verify the expected path (after substitution) matches what
    # the bootstrap actually emits.
    expected_after_install = (
        f"/etc/wakir/spire-federation/spire-server-{side}.conf"
    )
    assert expected == expected_after_install, (
        f"container expects conf at {expected!r} but bootstrap installs "
        f"at {expected_after_install!r}; config-path mismatch is "
        f"Bug 7-substrate (server will crash-loop on missing conf)."
    )


def test_tv_bringup_06_server_health_start_period_is_generous_enough() -> None:
    """Initial CA generation on SPIRE-Server's first start can take
    20-40s on cold storage. ``HealthStartPeriod`` MUST be at least 30s
    so systemd does not mark the unit failed before the server is
    actually ready (this was one of the candidate root-causes for the
    crash-loop in Bug 7)."""
    text = SERVER_FED_TPL.read_text(encoding="utf-8")
    m = re.search(r"HealthStartPeriod=(\d+)s", text)
    assert m, "server-federation-container declares no HealthStartPeriod"
    period_seconds = int(m.group(1))
    assert period_seconds >= 30, (
        f"HealthStartPeriod={period_seconds}s is too short for cold "
        f"start CA-generation; raise to >= 30s (Bug 7 candidate)."
    )


# ---------------------------------------------------------------------------
# TV-BRINGUP-07 — Bootstrap Resume-Hint has no ``bash bash`` doubling (Bug 1)
# ---------------------------------------------------------------------------
#
# The fail_step helper emits a resume-hint. The hint must NOT contain
# the literal text "bash bash" — that means the script accidentally
# echoed both the interpreter ($PROG) and the literal ``bash`` keyword,
# producing user-visible nonsense.


def test_tv_bringup_07_resume_hint_no_bash_bash_doubling() -> None:
    """Bug 1 is RUNTIME-VISIBLE: when the script is invoked via
    ``curl ... | sudo bash``, ``$0`` (and therefore ``$PROG``) resolves
    to literally ``bash`` because the shell read the script from
    stdin. The resume-hint then prints ``sudo bash bash --resume-from N``.

    The fix is one of:
      (a) Detect the from-pipe invocation form (``BASH_SOURCE[0]`` empty
          or ``[[ -p /dev/stdin ]]``) and emit a curl-form resume hint, OR
      (b) Always emit an absolute-path resume hint that points at
          ``${WAKIR_REPO_ROOT}/infra/spire/federation/wakir-pilot-bootstrap.sh``.

    We assert at least one of these mechanisms is present in fail_step.
    """
    text = _bootstrap_text()
    m = re.search(
        r"fail_step\(\).*?^\}", text, re.DOTALL | re.MULTILINE
    )
    assert m, "fail_step helper not found in bootstrap"
    fail_step_body = m.group(0)

    # If the body still uses bare ``$PROG`` with no pipe-detection or
    # absolute-path fallback, the bug is present.
    uses_bare_prog = bool(re.search(r"sudo bash \$\{?PROG\}?", fail_step_body))
    has_pipe_detection = (
        "BASH_SOURCE" in fail_step_body
        or "/dev/stdin" in fail_step_body
        or "/dev/fd/" in fail_step_body
    )
    has_absolute_path_hint = (
        "WAKIR_REPO_ROOT" in fail_step_body
        or "/opt/wakir-runtime" in fail_step_body
    )

    if uses_bare_prog and not (has_pipe_detection or has_absolute_path_hint):
        pytest.fail(
            "fail_step resume-hint uses bare ``$PROG`` with no\n"
            "pipe-detection or absolute-path fallback. When invoked via\n"
            "``curl ... | sudo bash``, ``$PROG`` resolves to ``bash``,\n"
            "producing the user-visible ``sudo bash bash --resume-from N``\n"
            "nonsense.\n\n"
            "This is Bug 1 from the 2026-05-13 Mira-Bug-Bilanz."
        )


# ---------------------------------------------------------------------------
# Meta — coverage envelope
# ---------------------------------------------------------------------------


def test_substance_suite_covers_all_seven_bugs() -> None:
    """Inventory check: the seven test-vector groups exist as named
    test functions in this module. Future Bug-N additions land here so
    the Mira-Bug-Bilanz and the regression net stay synchronized."""
    module_src = Path(__file__).read_text(encoding="utf-8")
    expected_vectors = [
        "test_tv_bringup_01_server_federation_volume_filename_resolves",
        "test_tv_bringup_01_bootstrap_installs_volumes_with_side_aware_filename",
        "test_tv_bringup_02_agent_references_existing_server_bundles_volume",
        "test_tv_bringup_03_agent_requires_match_server_federation_service",
        "test_tv_bringup_04_phase_6_has_idempotency_guard",
        "test_tv_bringup_04_phase_6_units_idempotent_on_active_units",
        "test_tv_bringup_05_bucket_init_has_no_cryptography_dependency_path",
        "test_tv_bringup_06_server_conf_path_matches_bootstrap_install",
        "test_tv_bringup_06_server_health_start_period_is_generous_enough",
        "test_tv_bringup_07_resume_hint_no_bash_bash_doubling",
    ]
    for name in expected_vectors:
        assert f"def {name}(" in module_src, (
            f"expected TV function missing: {name}"
        )


# ---------------------------------------------------------------------------
# Source-shape sanity: every persona-touched file the tests inspect
# actually exists. Catches refactors that move the target.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "p",
    [
        BOOTSTRAP,
        SERVER_FED_TPL,
        SERVER_FED_DATA_VOL,
        SERVER_FED_SOCKETS_VOL,
        SERVER_FED_BUNDLES_VOL,
        AGENT_FED_TPL,
        AGENT_FED_DATA_VOL,
        AGENT_FED_SOCKETS_VOL,
        BUCKET_INIT_UNIT,
    ],
)
def test_source_targets_exist(p: Path) -> None:
    assert p.exists(), f"source target moved/missing: {p}"
