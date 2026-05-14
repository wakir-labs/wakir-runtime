# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic static-discipline test for SELinux-relabel flags on every
``Volume=`` directive across the Quadlet inventory.

Context
-------

Sprint-9-Tag-8 Bug-20: SPIRE-Agent crash-looped on Bring-up-4 (AR Fred
2026-05-14 13:15 CEST) with::

    level=error msg="Failed to configure plugin"
      error="rpc error: code = FailedPrecondition desc =
             directory validation failed:
             open /var/lib/spire/agent/.probe: permission denied"
      plugin_name=disk plugin_type=KeyManager

Root cause: named-volume ``Volume=`` directives in three Quadlet units
were missing the ``:Z`` SELinux-relabel-private flag. On FCOS (SELinux
``enforcing``) Podman leaves the volume backing directory labeled
``root_t``, the container process runs as ``container_t``, and the
container gets EACCES on first write. Bind-mount entries on the same
unit DID carry ``:Z`` (proving the operator knew the flag), but named-
volume entries were forgotten.

The fix is local — append ``:Z`` to every named-volume rw mount and
``:ro,Z`` to every ro mount — and the only durable defense is a
static-source-discipline test that fails the build the moment a future
PR introduces a Volume= line without a relabel flag.

Test-Vector index
-----------------

  * ``TV-S9T8-20a`` Every ``^Volume=`` line across the Quadlet
    inventory carries ``:Z`` or ``:z`` somewhere in its option list
    (or ends in a tmpfs target — but ``Tmpfs=`` uses a separate
    directive so this branch is empty in practice).
  * ``TV-S9T8-20b`` Per-file allow-list: the three files explicitly
    named in the Bug-20 brief (single-org server/agent, federation
    server/agent, NATS) are individually re-asserted so a future
    refactor that splits one file does not silently drop a Volume
    line from the discipline scan.
  * ``TV-S9T8-20c`` Mutation-equivalent assertion (the QA Zone-X
    handshake): the test parses each Volume= line into a structured
    record (volume name, mount target, options) and asserts the
    relabel flag is set; removing ``:Z`` from any single line in
    source MUST cause this test to red.

Sandbox boundary
----------------

Source-static only. No podman, no SELinux, no host file-system. The
test parses Quadlet text and asserts a textual invariant.

-- Tomás
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# Canonical set of Quadlet units in this repo as of Sprint-9-Tag-8.
# The discovery glob below is the source of truth; this list is the
# expected-set against which discovery is sanity-checked so a future
# refactor that moves files breaks loudly rather than silently.
EXPECTED_QUADLET_FILES = {
    "quadlet/wakir-spire-server.container",
    "quadlet/wakir-spire-agent.container",
    "quadlet/wakir-nats.container",
    "quadlet/wakir-nats-kv-bucket-init.container",
    "infra/spire/federation/quadlet/wakir-spire-server-federation.container",
    "infra/spire/agent/quadlet/wakir-spire-agent-federation.container",
}


def _discover_quadlet_files() -> list[Path]:
    """Return every ``*.container`` file under the two Quadlet roots
    used by the pilot-bootstrap (top-level + SPIRE-federation sub-tree).
    """
    roots = [
        REPO_ROOT / "quadlet",
        REPO_ROOT / "infra" / "spire",
    ]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        found.extend(sorted(root.rglob("*.container")))
    return found


def _parse_volume_lines(path: Path) -> list[tuple[int, str]]:
    """Return ``(line_no, line)`` for every ``^Volume=`` line in the
    file (no leading whitespace allowed — Quadlet expects directives
    flush-left)."""
    out: list[tuple[int, str]] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        if raw.startswith("Volume="):
            out.append((lineno, raw))
    return out


def _volume_options(line: str) -> list[str]:
    """Extract the colon-separated mount-options trailing the second
    colon. Returns ``[]`` for ``src:dst`` (no options)."""
    # ``Volume=src:dst[:opt1,opt2,...]`` — Podman/Quadlet shape. The
    # first colon separates src from dst, the second from options.
    # Source path may contain colons only inside angle-bracket
    # placeholders (e.g. ``<HOST_PORT>``) which are stripped before
    # the bootstrap installs the file; the static text never has any.
    body = line.removeprefix("Volume=")
    parts = body.split(":")
    if len(parts) < 3:
        return []
    # parts[2:] is the options-tail; rejoin in case a future variant
    # introduces a colon-bearing option (none today).
    opts_blob = ":".join(parts[2:])
    return [p.strip() for p in opts_blob.split(",") if p.strip()]


@pytest.fixture(scope="module")
def quadlet_inventory() -> list[Path]:
    files = _discover_quadlet_files()
    assert files, "no Quadlet *.container files discovered — repo layout drift?"
    return files


# -- TV-S9T8-20a -------------------------------------------------------


def test_inventory_matches_expected_set(quadlet_inventory: list[Path]) -> None:
    """Sanity-check that the discovery glob still matches the brief.

    If a future refactor splits/renames a Quadlet file, EXPECTED needs
    updating in the same PR. This guard prevents silent drift between
    discovery and the per-file allow-list below.
    """
    found = {
        str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        for p in quadlet_inventory
    }
    assert found == EXPECTED_QUADLET_FILES, (
        f"Quadlet inventory drift.\n"
        f"  found    = {sorted(found)}\n"
        f"  expected = {sorted(EXPECTED_QUADLET_FILES)}"
    )


def test_every_volume_line_has_selinux_relabel_flag(
    quadlet_inventory: list[Path],
) -> None:
    """Every ``^Volume=`` line carries ``:Z`` (or ``:z``) in its
    option list.

    Mutation-coverage: removing ``:Z`` from any one Volume= line in
    source MUST cause this assertion to fail, with a diagnostic that
    points the operator at the exact file/line/option-list.
    """
    failures: list[str] = []
    for unit in quadlet_inventory:
        rel = unit.relative_to(REPO_ROOT)
        for lineno, line in _parse_volume_lines(unit):
            opts = _volume_options(line)
            if not any(opt in ("Z", "z") for opt in opts):
                failures.append(
                    f"{rel}:{lineno} missing :Z/:z relabel flag — "
                    f"options={opts!r}; line={line!r}"
                )
    assert not failures, (
        "Quadlet :Z-discipline violations (Sprint-9-Tag-8 Bug-20):\n  "
        + "\n  ".join(failures)
    )


# -- TV-S9T8-20b -------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    sorted(EXPECTED_QUADLET_FILES),
)
def test_each_expected_file_has_at_least_one_relabel_flagged_volume(
    rel_path: str,
) -> None:
    """Per-file allow-list: every unit listed in the brief has at
    least one Volume= line AND every Volume= line on that unit has a
    relabel flag.

    The parametrise-per-file shape gives a clear test-id per unit so
    a regression points at the unit name directly in the pytest
    output.
    """
    path = REPO_ROOT / rel_path
    assert path.exists(), f"{rel_path} missing"
    lines = _parse_volume_lines(path)
    assert lines, f"{rel_path}: no Volume= lines at all"
    bad: list[str] = []
    for lineno, line in lines:
        opts = _volume_options(line)
        if not any(opt in ("Z", "z") for opt in opts):
            bad.append(f"  L{lineno}: {line!r} (opts={opts!r})")
    assert not bad, (
        f"{rel_path}: Volume= lines without :Z/:z relabel flag:\n"
        + "\n".join(bad)
    )


# -- TV-S9T8-20c -------------------------------------------------------


def test_known_bug20_lines_have_relabel_flag() -> None:
    """Hard-coded line-checks for the exact Volume= directives called
    out in the Bug-20 brief.

    These targets are the regression triggers — if any one of them
    loses ``:Z``, this test names the file and the expected mount-
    target so the next operator can reproduce the failure without
    re-reading the original brief.
    """
    targets: list[tuple[str, str]] = [
        # Bug-20 primary (Federation agent — observed crash-loop):
        (
            "infra/spire/agent/quadlet/wakir-spire-agent-federation.container",
            "wakir-spire-agent-<SIDE>-data.volume:/var/lib/spire/agent",
        ),
        (
            "infra/spire/agent/quadlet/wakir-spire-agent-federation.container",
            "wakir-spire-server-federation-<SIDE>-bundles.volume:/var/lib/spire/bundles",
        ),
        (
            "infra/spire/agent/quadlet/wakir-spire-agent-federation.container",
            "wakir-spire-agent-<SIDE>-sockets.volume:/run/spire/agent-sockets",
        ),
        # Bug-20 secondary (Federation server — prophylactic):
        (
            "infra/spire/federation/quadlet/wakir-spire-server-federation.container",
            "wakir-spire-server-federation-<SIDE>-data.volume:/var/lib/spire/server",
        ),
        (
            "infra/spire/federation/quadlet/wakir-spire-server-federation.container",
            "wakir-spire-server-federation-<SIDE>-sockets.volume:/run/spire/sockets",
        ),
        (
            "infra/spire/federation/quadlet/wakir-spire-server-federation.container",
            "wakir-spire-server-federation-<SIDE>-bundles.volume:/var/lib/spire/bundles",
        ),
        # Bug-20 single-org variants:
        (
            "quadlet/wakir-spire-agent.container",
            "wakir-spire-agent-data.volume:/var/lib/spire/agent",
        ),
        (
            "quadlet/wakir-spire-agent.container",
            "wakir-spire-server-sockets.volume:/run/spire/sockets",
        ),
        (
            "quadlet/wakir-spire-agent.container",
            "wakir-spire-agent-sockets.volume:/run/spire/agent-sockets",
        ),
        (
            "quadlet/wakir-spire-server.container",
            "wakir-spire-server-data.volume:/var/lib/spire/server",
        ),
        (
            "quadlet/wakir-spire-server.container",
            "wakir-spire-server-sockets.volume:/run/spire/sockets",
        ),
        # Bug-20 cross-audit catch (NATS — found during Tomás sweep):
        (
            "quadlet/wakir-nats.container",
            "wakir-nats-jetstream-data.volume:/data/jetstream",
        ),
    ]
    missing: list[str] = []
    for rel, prefix in targets:
        path = REPO_ROOT / rel
        text = path.read_text()
        # Match the prefix and assert the next char-window contains :Z.
        pattern = re.compile(
            r"^Volume=" + re.escape(prefix) + r"(?::([^\r\n]*))?\s*$",
            re.MULTILINE,
        )
        match = pattern.search(text)
        if match is None:
            missing.append(
                f"{rel}: no Volume= line matching prefix {prefix!r}"
            )
            continue
        opts_blob = match.group(1) or ""
        opts = [p.strip() for p in opts_blob.split(",") if p.strip()]
        if not any(opt in ("Z", "z") for opt in opts):
            missing.append(
                f"{rel}: {prefix!r} present but options={opts!r} "
                "lack :Z/:z relabel flag"
            )
    assert not missing, (
        "Bug-20 known-target relabel-flag regressions:\n  "
        + "\n  ".join(missing)
    )
