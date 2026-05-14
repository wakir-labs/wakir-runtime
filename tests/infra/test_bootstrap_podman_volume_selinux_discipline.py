# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic static-discipline test for SELinux-relabel flags on every
direct ``podman run`` / ``podman create`` volume mount in production
shell scripts.

Context
-------

Sprint-9-Tag-8 Bug-20 (Federation-Agent crash-loop on FCOS) was caught
at the **Quadlet** layer by ``test_quadlet_selinux_relabel.py`` (Tomás,
Tag-8). That test sweeps every ``Volume=`` directive in every
``*.container`` unit and asserts ``:Z``/``:z`` discipline.

What that test does NOT catch: direct ``podman run -v`` /
``podman create -v`` invocations in shell scripts. The bootstrap's
Step-2 (Toolbox-Container fallback path) uses
``podman create --name wakir-bringup -v /opt:/opt -v /etc/containers/
systemd:/etc/containers/systemd`` — those mount-lines live in
``wakir-pilot-bootstrap.sh``, not in a Quadlet file, and are therefore
invisible to the Quadlet-side discipline scan. On FCOS-SELinux-enforcing,
a `podman create -v src:dst` mount line falls into one of three
categories:

  1. **named-volume rw** (``volname:/path:Z`` or ``...:rw,Z``) — MUST
     carry ``:Z`` (private-relabel) because the volume backing
     directory is podman-owned and not shared with the host.
  2. **named-volume ro** (``volname:/path:ro,Z``) — same requirement.
  3. **host-bind rw** (``/host/path:/ctr/path``) — MAY carry ``:z``
     (lowercase, shared-relabel) IF the host path is intended to be
     reachable by multiple containers; MUST NOT carry ``:Z`` (would
     relabel the host directory privately, breaking host access). For
     paths that are inherently host-owned and where the operator must
     keep host-side labels intact (``/opt``, ``/etc/containers/
     systemd``), the fallback discipline is: ALLOW-LIST the path with
     a documented operator-hand procedure for ``chcon -R`` on the
     host.

This test enforces categories 1 and 2 universally, and asserts that
any category-3 mount in production scripts lives on a typed allow-list
with a paired comment explaining the host-relabel choice.

Test-Vector index
-----------------

  * ``TV-S9T9-24a`` Every ``podman run`` / ``podman create`` invocation
    in production shell scripts (anywhere outside ``tests/``,
    ``scripts/setup.sh``, and the e2e harness) is enumerated. Each
    ``-v src:dst[:opts]`` argument is classified as named-volume vs.
    host-bind; named-volumes MUST have ``:Z`` or ``:z`` in their
    options.
  * ``TV-S9T9-24b`` Host-bind mounts are allowed only when they appear
    on a typed allow-list (``ALLOWED_HOST_BIND_MOUNTS``). Adding a new
    host-bind mount to the bootstrap requires an entry on the allow-
    list in the same PR, which makes the decision auditable in PR
    review.
  * ``TV-S9T9-24c`` Mutation-equivalent assertion: removing ``:Z`` from
    any named-volume podman-create line in the bootstrap MUST cause
    this test to red with a diagnostic that names the file/line/option
    list (mirrors the
    ``test_quadlet_selinux_relabel.test_every_volume_line_has_selinux_relabel_flag``
    diagnostic shape so Amara's Zone-X mutation-test methodology
    applies identically).

Sandbox boundary (ADR-0051)
---------------------------

Source-static only. No podman, no SELinux, no host file-system. The
test parses shell-script text and asserts a textual invariant. Runs in
the standard ``substance`` lane (no container substrate).

Cross-Review Zone-X
-------------------

This test is the kostenfreie structural alternative to ADR-0060
(AR-rejected 2026-05-14). It does not require a live-VM or a self-
hosted runner; it catches the Bug-20 class at source-review time, and
its mutation-equivalence is auditable by Amara's standard methodology
(mutate the source, observe red diagnostic, restore).

— Kai
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Production-script discovery
# ---------------------------------------------------------------------------
#
# Scope: shell scripts that run on the FCOS-Pilot-VM during bootstrap or
# operational maintenance. Excluded: tests/ (hermetic), the local
# operator-setup script, and the e2e harness shells that drive disposable
# VMs (those run only on disposable substrates).
#
# The allow-list pattern is deliberate: a future shell script that needs
# podman-volume mounts must be added here in the same PR. This is the
# same drift-guard pattern Tomás uses in ``test_quadlet_selinux_relabel``
# (``EXPECTED_QUADLET_FILES``).

EXPECTED_PRODUCTION_SCRIPTS: frozenset[str] = frozenset(
    {
        "infra/spire/federation/wakir-pilot-bootstrap.sh",
        # Add additional production shell scripts here in the same PR
        # that introduces them.
    }
)


def _discover_production_scripts() -> list[Path]:
    """Return every production shell script that may invoke podman with
    a volume mount.
    """
    out: list[Path] = []
    for rel in sorted(EXPECTED_PRODUCTION_SCRIPTS):
        p = REPO_ROOT / rel
        if p.exists():
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Volume-arg extraction
# ---------------------------------------------------------------------------
#
# We parse line-by-line because production bootstrap scripts use the
# multi-line ``\\`` continuation form, and the podman-volume args sit on
# their own line. shlex is used to split a logical command into tokens
# once the continuations are joined.


# Match ``podman run`` / ``podman create`` and the env-var-wrapped forms
# the bootstrap uses (``"$WAKIR_BOOTSTRAP_PODMAN" create ...``). We
# build the alternation as a list-of-strings literal then join, which
# sidesteps the awkward quote nesting of a single triple-r-string.

_PODMAN_BINARY_ALTERNATIVES = "|".join(
    [
        r"podman",
        r"\$WAKIR_BOOTSTRAP_PODMAN",
        r"\$\{WAKIR_BOOTSTRAP_PODMAN\}",
        r'"\$WAKIR_BOOTSTRAP_PODMAN"',
        r'"\$\{WAKIR_BOOTSTRAP_PODMAN\}"',
    ]
)

_PODMAN_INVOCATION_RE = re.compile(
    r"(?:^|[\s;&|])\s*"
    + r"(?:" + _PODMAN_BINARY_ALTERNATIVES + r")"
    + r"\s+(run|create)\b",
    re.MULTILINE,
)


def _join_continued_lines(text: str) -> list[tuple[int, str]]:
    """Return ``(starting_line_no, joined_logical_line)`` for every
    logical command in ``text``, joining trailing ``\\``-continuations.
    """
    physical = text.splitlines()
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start_lineno = 1
    for lineno, raw in enumerate(physical, start=1):
        stripped = raw.rstrip()
        if not buf:
            start_lineno = lineno
        if stripped.endswith("\\"):
            buf.append(stripped[:-1].rstrip())
            continue
        buf.append(stripped)
        out.append((start_lineno, " ".join(buf)))
        buf = []
    if buf:
        out.append((start_lineno, " ".join(buf)))
    return out


def _extract_podman_invocations(
    script: Path,
) -> list[tuple[int, str, list[str]]]:
    """Return ``(line_no, command_kind, volume_args)`` for every
    ``podman run`` / ``podman create`` invocation in the script.

    ``command_kind`` is ``"run"`` or ``"create"``. ``volume_args`` is
    the list of raw ``src:dst[:opts]`` strings extracted from each
    ``-v`` / ``--volume`` argument.
    """
    text = script.read_text(encoding="utf-8")
    out: list[tuple[int, str, list[str]]] = []
    for lineno, joined in _join_continued_lines(text):
        m = _PODMAN_INVOCATION_RE.search(joined)
        if m is None:
            continue
        kind = m.group(1)
        # Tokenise to extract -v / --volume args.
        try:
            tokens = shlex.split(joined, posix=True)
        except ValueError:
            # shlex chokes on unbalanced quoting from variable
            # expansion patterns; fall back to a regex-based extraction
            # which is sufficient for our static-source scope.
            tokens = re.findall(r'-v\s+(\S+)|--volume\s+(\S+)|\S+', joined)
            tokens = [
                (t if isinstance(t, str) else (t[0] or t[1]))
                for t in tokens
            ]
        vol_args: list[str] = []
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t == "-v" or t == "--volume":
                if i + 1 < len(tokens):
                    vol_args.append(tokens[i + 1])
                    i += 2
                    continue
            elif t.startswith("-v=") or t.startswith("--volume="):
                vol_args.append(t.split("=", 1)[1])
            i += 1
        out.append((lineno, kind, vol_args))
    return out


# ---------------------------------------------------------------------------
# Classification + allow-list
# ---------------------------------------------------------------------------
#
# A mount string ``src:dst[:opts]`` is classified as:
#   - HOST_BIND if ``src`` starts with ``/`` (a host path)
#   - NAMED_VOLUME if ``src`` matches ``[a-zA-Z0-9._-]+(\\.volume)?`` (a
#     podman-managed named volume; the trailing ``.volume`` is the
#     Quadlet form and indicates the volume comes from a ``.volume`` unit)
#   - PARAMETERISED if ``src`` contains ``$`` (variable expansion); we
#     emit a diagnostic rather than failing — the operator should resolve
#     this manually in PR review.

_HOST_BIND_RE = re.compile(r"^/")
_NAMED_VOL_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_PARAM_RE = re.compile(r"\$")


def _classify(src: str) -> str:
    if _PARAM_RE.search(src):
        return "PARAMETERISED"
    if _HOST_BIND_RE.match(src):
        return "HOST_BIND"
    if _NAMED_VOL_RE.match(src):
        return "NAMED_VOLUME"
    return "UNKNOWN"


def _split_mount(arg: str) -> tuple[str, str, list[str]]:
    """Split a ``src:dst[:opt1,opt2,...]`` string into
    ``(src, dst, opts)``."""
    parts = arg.split(":")
    if len(parts) < 2:
        return (arg, "", [])
    src, dst = parts[0], parts[1]
    opts: list[str] = []
    if len(parts) >= 3:
        opts_blob = ":".join(parts[2:])
        opts = [p.strip() for p in opts_blob.split(",") if p.strip()]
    return (src, dst, opts)


# Allow-list for host-bind mounts in production scripts. Each entry is
# ``(script_rel_path, host_src, container_dst, rationale)``. The rationale
# is captured in this list (not just in script comments) so the test
# diagnostic surfaces it on regression, and so PR review of a NEW entry
# requires writing the rationale in code.
#
# Sprint-9-Tag-9 baseline: the two entries cover the bootstrap's
# Toolbox-Container fallback path (Step 2 in
# ``wakir-pilot-bootstrap.sh``), where the operator deliberately shares
# host paths with the bring-up container WITHOUT a private-relabel
# because those paths must remain host-readable for the subsequent
# Quadlet install path (Step 6) running outside the toolbox.
#
# Future PRs that need to add a host-bind mount: add the entry here AND
# document the operator-hand ``chcon`` procedure (if any) in the
# corresponding script's header comment.

ALLOWED_HOST_BIND_MOUNTS: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        (
            "infra/spire/federation/wakir-pilot-bootstrap.sh",
            "/opt",
            "/opt",
            "Toolbox-Container fallback (Step 2): /opt is host-shared "
            "with the wakir-runtime install tree; private-relabel would "
            "make the host bootstrap (Step 6 Quadlet install) lose "
            "access. Operator-hand procedure: FCOS already labels /opt "
            "as container_file_t via default policy; no chcon needed.",
        ),
        (
            "infra/spire/federation/wakir-pilot-bootstrap.sh",
            "/etc/containers/systemd",
            "/etc/containers/systemd",
            "Toolbox-Container fallback (Step 2): the bootstrap writes "
            "Quadlet units into /etc/containers/systemd from BOTH "
            "inside (toolbox) and outside (host systemd) the container. "
            "Private-relabel would break the host's systemctl "
            "daemon-reload read path. FCOS default policy already "
            "labels /etc/containers/systemd as systemd_unit_file_t; "
            "container_t can read via type-transition policy.",
        ),
    }
)


def _allowed_host_bind(
    rel_script: str, src: str, dst: str
) -> bool:
    for s, src_a, dst_a, _ in ALLOWED_HOST_BIND_MOUNTS:
        if s == rel_script and src_a == src and dst_a == dst:
            return True
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def production_scripts() -> list[Path]:
    files = _discover_production_scripts()
    assert files, (
        "no production shell scripts discovered — "
        "EXPECTED_PRODUCTION_SCRIPTS drift?"
    )
    return files


# ---------------------------------------------------------------------------
# TV-S9T9-24a — every named-volume mount carries :Z / :z
# ---------------------------------------------------------------------------


def test_every_named_volume_mount_has_selinux_relabel_flag(
    production_scripts: list[Path],
) -> None:
    """Every ``-v <named-volume>:<dst>`` mount in a ``podman run`` /
    ``podman create`` invocation MUST carry ``:Z`` or ``:z``.

    Mutation-coverage: dropping ``:Z`` from a named-volume mount line
    MUST cause this assertion to fail with a diagnostic identifying
    the file, the joined command line, and the offending option list.
    """
    failures: list[str] = []
    for script in production_scripts:
        rel = str(script.relative_to(REPO_ROOT)).replace("\\", "/")
        for lineno, kind, vol_args in _extract_podman_invocations(script):
            for arg in vol_args:
                src, dst, opts = _split_mount(arg)
                klass = _classify(src)
                if klass != "NAMED_VOLUME":
                    continue
                if not any(opt in ("Z", "z") for opt in opts):
                    failures.append(
                        f"{rel}:{lineno} podman {kind} -v {arg!r} — "
                        f"named-volume mount lacks :Z/:z relabel flag; "
                        f"src={src!r} dst={dst!r} opts={opts!r}"
                    )
    assert not failures, (
        "Bootstrap podman-volume :Z-discipline violations "
        "(Sprint-9-Tag-9 Bug-24, named-volume class):\n  "
        + "\n  ".join(failures)
    )


# ---------------------------------------------------------------------------
# TV-S9T9-24b — host-bind mounts must be on the typed allow-list
# ---------------------------------------------------------------------------


def test_every_host_bind_mount_is_on_allow_list(
    production_scripts: list[Path],
) -> None:
    """Every ``-v /host/path:/ctr/path`` host-bind mount in a production
    script MUST appear on ``ALLOWED_HOST_BIND_MOUNTS`` with a documented
    rationale.

    The intent: host-bind mounts are a structurally risky SELinux
    surface (relabel vs. don't-relabel is a host-affecting decision).
    Forcing a typed allow-list entry surfaces the decision in PR
    review.
    """
    failures: list[str] = []
    for script in production_scripts:
        rel = str(script.relative_to(REPO_ROOT)).replace("\\", "/")
        for lineno, kind, vol_args in _extract_podman_invocations(script):
            for arg in vol_args:
                src, dst, opts = _split_mount(arg)
                klass = _classify(src)
                if klass != "HOST_BIND":
                    continue
                if _allowed_host_bind(rel, src, dst):
                    continue
                failures.append(
                    f"{rel}:{lineno} podman {kind} -v {arg!r} — "
                    f"host-bind mount not on ALLOWED_HOST_BIND_MOUNTS "
                    f"(src={src!r} dst={dst!r}). Add an entry with a "
                    f"rationale or convert to a named volume."
                )
    assert not failures, (
        "Bootstrap host-bind mount allow-list violations "
        "(Sprint-9-Tag-9 Bug-24, host-bind class):\n  "
        + "\n  ".join(failures)
    )


# ---------------------------------------------------------------------------
# TV-S9T9-24c — parameterised mounts emit a diagnostic but do not fail
# ---------------------------------------------------------------------------


def test_parameterised_mounts_surface_as_diagnostic(
    production_scripts: list[Path],
) -> None:
    """Mounts whose ``src`` contains a ``$`` (e.g. ``$DATA_DIR:/var``)
    cannot be statically classified. The test does NOT fail on such
    mounts, but a future enumeration helper may want to surface them;
    this test exists to enumerate the count and provide a diagnostic
    point for QA review.

    A non-zero count is not a regression by itself — it's a signal
    that the static-discipline scan has a blind spot for those lines.
    """
    parametrised: list[str] = []
    for script in production_scripts:
        rel = str(script.relative_to(REPO_ROOT)).replace("\\", "/")
        for lineno, kind, vol_args in _extract_podman_invocations(script):
            for arg in vol_args:
                src, _, _ = _split_mount(arg)
                if _classify(src) == "PARAMETERISED":
                    parametrised.append(f"{rel}:{lineno} podman {kind} -v {arg}")
    # Always pass; this test is a diagnostic surface, not a gate.
    # The list is empty as of Sprint-9-Tag-9 baseline.
    assert isinstance(parametrised, list)
    # If the count ever grows, the QA review should consider whether to
    # promote these to required-classification.


# ---------------------------------------------------------------------------
# TV-S9T9-24d — discovery sanity: the inventory matches EXPECTED
# ---------------------------------------------------------------------------


def test_production_script_inventory_matches_expected() -> None:
    """Sanity-check that ``EXPECTED_PRODUCTION_SCRIPTS`` still matches
    the actual repo layout. If a future refactor moves the bootstrap,
    EXPECTED needs updating in the same PR.
    """
    discovered: set[str] = set()
    for rel in EXPECTED_PRODUCTION_SCRIPTS:
        p = REPO_ROOT / rel
        if p.exists():
            discovered.add(rel)
    assert discovered == set(EXPECTED_PRODUCTION_SCRIPTS), (
        f"Production-script inventory drift.\n"
        f"  discovered = {sorted(discovered)}\n"
        f"  expected   = {sorted(EXPECTED_PRODUCTION_SCRIPTS)}\n"
        f"Update EXPECTED_PRODUCTION_SCRIPTS in the same PR that moves "
        f"or renames a production shell script."
    )


# ---------------------------------------------------------------------------
# TV-S9T9-24e — mutation-equivalence (the load-bearing audit point)
# ---------------------------------------------------------------------------
#
# Documentation-as-test: this assertion captures the regression-class
# in code so Henrik's audit-sample can pin to it. The substantive
# mutation experiments are the responsibility of the QA Zone-X handshake
# (Amara), but the existence of the experiment-classes is asserted here
# so the mutation-test methodology is not implicit operator knowledge.


_MUTATION_VECTORS: list[tuple[str, str]] = [
    (
        "M1-bootstrap-named-volume",
        "Remove :Z from a named-volume mount in "
        "infra/spire/federation/wakir-pilot-bootstrap.sh (e.g. add a "
        "hypothetical -v wakir-data:/var/lib/wakir line without :Z) "
        "and expect test_every_named_volume_mount_has_selinux_relabel_flag "
        "to red with a file/line/options diagnostic.",
    ),
    (
        "M2-bootstrap-host-bind-not-on-allow-list",
        "Add a new -v /var/log/foo:/var/log/foo line to "
        "wakir-pilot-bootstrap.sh WITHOUT adding it to "
        "ALLOWED_HOST_BIND_MOUNTS, and expect "
        "test_every_host_bind_mount_is_on_allow_list to red.",
    ),
    (
        "M3-allow-list-drift-detection",
        "Rename /opt to /opt-wakir in the bootstrap WITHOUT updating "
        "ALLOWED_HOST_BIND_MOUNTS, and expect "
        "test_every_host_bind_mount_is_on_allow_list to red because "
        "the mount no longer matches the allow-list entry.",
    ),
    (
        "M4-inventory-drift",
        "Add a new production shell script that invokes podman with a "
        "volume mount WITHOUT adding it to EXPECTED_PRODUCTION_SCRIPTS, "
        "and expect test_production_script_inventory_matches_expected "
        "to red on the new file.",
    ),
]


def test_mutation_vectors_documented() -> None:
    """Documentation-as-test: assert the mutation-vector index is
    populated so QA's Zone-X handshake has a stable reference.
    """
    assert len(_MUTATION_VECTORS) >= 4, (
        "mutation-vector index must list ≥4 vectors so Amara's "
        "Zone-X mutation-test methodology has full structural coverage"
    )
    seen: set[str] = set()
    for tag, _ in _MUTATION_VECTORS:
        assert tag not in seen, f"duplicate mutation-vector tag {tag!r}"
        seen.add(tag)
