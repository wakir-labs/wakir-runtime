# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-9-Tag-7 bring-up-cleanup
substance-fixes (3 bugs from the live Pilot-VM bring-up 2026-05-14
~12:00 CEST, V2-Acceptance-Bring-up-3).

Context
-------

Bring-up-3 ran from-scratch out-of-box on the Pilot-VM and reached
6/6 smoke-pass, but only after the Operator applied 3 hand-patches
mid-bring-up. These three bugs were NOT caught by the Sprint-9-Tag-6
hermetic surface — the classic Live-Bring-up-Sandbox-Gap. This
module closes the gap so a future regression on any of the three
codepaths fails fast in CI.

Test-Vector index (Bug-numbered to continue the Tag-6 ladder)
-------------------------------------------------------------

  * ``TV-S9T7-16`` Resolver ``resolve_group_tagged`` runs WITHOUT
    Perl on the PATH. Live-Bring-up-3 crashed because FCOS does not
    ship Perl and the Tag-6 implementation called ``perl -ne`` /
    ``perl -pi -e``. The Tag-7 refactor uses Bash-native
    ``[[ =~ ]]`` + ``${BASH_REMATCH[@]}``.
  * ``TV-S9T7-16b`` Bootstrap ``step_1_preflight`` explicitly checks
    a CLI-tool inventory before proceeding so a missing tool fails
    fast at Step 1 rather than silently falling through at Step 5.
  * ``TV-S9T7-17`` ``wakir-nats-kv-bucket-init.container``'s
    ``Exec=`` does NOT carry a leading ``python3`` token (the
    image entrypoint is already ``python3``).
  * ``TV-S9T7-18`` Bootstrap ``step_7_bucket_init`` runs
    ``systemctl daemon-reload`` unconditionally BEFORE the
    ``systemctl start`` of the bucket-init unit.

Sandbox boundary
----------------

All tests parse source files or run the resolver against an isolated
fixture directory under ``tmp_path``. No live podman / NATS / systemd
interaction. Bug-16 stripped-PATH test rebuilds ``PATH`` to a
deliberate minimum-viable subset that EXCLUDES Perl and proves the
substitution still fires.

-- Tomás
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)
RESOLVER = (
    REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "proxmox"
    / "resolve-image-pins.sh"
)
BUCKET_INIT_QUADLET = (
    REPO_ROOT / "quadlet" / "wakir-nats-kv-bucket-init.container"
)


SHA256_A = "sha256:" + "a" * 64
SHA256_B = "sha256:" + "b" * 64
SHA256_C = "sha256:" + "c" * 64
SHA256_D = "sha256:" + "d" * 64


def _bootstrap_text() -> str:
    return BOOTSTRAP.read_text(encoding="utf-8")


def _strip_systemd_comments(text: str) -> str:
    """systemd unit-file parser strips ``;`` and ``#`` line-prefixed
    comments. We mirror that here to avoid false-positives when an
    in-file commentary mentions the token we're forbidding."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        out.append(line)
    return "\n".join(out)


def _build_resolver_skeleton(
    root: Path, provisioner_image_line: str
) -> None:
    """Build a minimal ``--root`` layout matching what the resolver
    expects on a real Pilot-VM."""
    (root / "quadlet").mkdir(parents=True, exist_ok=True)
    (root / "quadlet" / "wakir-spire-server.container").write_text(
        "[Container]\n"
        "Image=ghcr.io/spiffe/spire-server:1.14.6"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    (root / "infra/spire/federation/quadlet").mkdir(
        parents=True, exist_ok=True
    )
    (
        root
        / "infra/spire/federation/quadlet"
        / "wakir-spire-server-federation.container"
    ).write_text(
        "[Container]\n"
        "Image=ghcr.io/spiffe/spire-server:1.14.6"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    (root / "quadlet" / "wakir-spire-agent.container").write_text(
        "[Container]\n"
        "Image=ghcr.io/spiffe/spire-agent:1.14.6"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    (root / "infra/spire/agent/quadlet").mkdir(
        parents=True, exist_ok=True
    )
    (
        root
        / "infra/spire/agent/quadlet"
        / "wakir-spire-agent-federation.container"
    ).write_text(
        "[Container]\n"
        "Image=ghcr.io/spiffe/spire-agent:1.14.6"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    (root / "infra/spire/federation/provisioner").mkdir(
        parents=True, exist_ok=True
    )
    (
        root
        / "infra/spire/federation/provisioner"
        / "Containerfile"
    ).write_text(
        "FROM docker.io/library/python:3.13-slim"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).write_text(
        "[Container]\n"
        f"{provisioner_image_line}\n"
    )


def _build_perl_stripped_path(tmp_path: Path) -> str:
    """Return a PATH string containing every binary the resolver needs
    EXCEPT perl. We construct a sandbox bin/ directory that symlinks
    just the required executables; perl is deliberately omitted so
    a regression to the Tag-6 implementation would fail the test.

    Required: bash, sed, grep, mktemp, mv, chmod, stat, cat, rm,
    awk (for the help-text); cmp may be exercised through subprocess
    calls. We resolve each via shutil.which against the host PATH and
    fall back to ``/bin/<name>`` / ``/usr/bin/<name>``.
    """
    sandbox_bin = tmp_path / "perl_stripped_bin"
    sandbox_bin.mkdir(exist_ok=True)
    required = [
        "bash",
        "sed",
        "grep",
        "mktemp",
        "mv",
        "chmod",
        "stat",
        "cat",
        "rm",
        "awk",
        "head",
        "tr",
        "printf",
        "tee",
        "cp",
        "find",
        "sort",
        "uniq",
        "wc",
        "id",
        "env",
        "dirname",
        "basename",
        "tput",
        "cmp",
    ]
    for tool in required:
        src = shutil.which(tool)
        if src is None:
            for cand in (f"/usr/bin/{tool}", f"/bin/{tool}"):
                if Path(cand).exists():
                    src = cand
                    break
        if src is None:
            # Builtin or unavailable; skip — the test PATH falls back to
            # nothing for it, the resolver only needs the listed core set.
            continue
        target = sandbox_bin / tool
        if not target.exists():
            target.symlink_to(src)
    # Assert perl is NOT linked into the sandbox bin (the whole point).
    assert not (sandbox_bin / "perl").exists()
    return str(sandbox_bin)


# ---------------------------------------------------------------------------
# TV-S9T7-16 — Bug-16: resolver runs WITHOUT perl on PATH
# ---------------------------------------------------------------------------


def test_tv_s9t7_16_resolver_substitutes_without_perl_on_path(
    tmp_path: Path,
) -> None:
    """The resolver MUST substitute the wakir-provisioner placeholder
    when Perl is NOT on the PATH. Live-Bring-up-3 (2026-05-14) on
    Fedora-CoreOS crashed at Step 5 because FCOS does not ship Perl
    on the host PATH and the Tag-6 implementation called ``perl``
    directly. Tag-7's Bash-native refactor must close this gap.
    """
    root = tmp_path / "root"
    _build_resolver_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW",
    )
    stripped_path = _build_perl_stripped_path(tmp_path)
    env = {
        # Hard-replace the inherited PATH so the resolver cannot
        # accidentally find perl via the parent process environment.
        "PATH": stripped_path,
        # Pass through the bare minimum for bash startup; LANG keeps
        # the locale stable enough for awk/sed.
        "LANG": "C",
        "HOME": str(tmp_path),
    }
    # Sanity: confirm perl is unreachable through this PATH.
    sanity = subprocess.run(
        ["bash", "-c", "command -v perl || echo NOPERL"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "NOPERL" in sanity.stdout, (
        f"PATH-strip fixture leaked perl: {sanity.stdout!r}"
    )

    proc = subprocess.run(
        [
            "bash",
            str(RESOLVER),
            "--spire-server-digest", SHA256_A,
            "--spire-agent-digest", SHA256_B,
            "--python-digest", SHA256_C,
            "--wakir-provisioner-digest", SHA256_D,
            "--root", str(root),
            "--apply",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"resolver failed without perl on PATH: "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    # The placeholder is gone and the digest landed.
    quadlet_after = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    assert "DIGEST_PENDING_TOMAS_REVIEW" not in quadlet_after, (
        f"placeholder not substituted: {quadlet_after!r}"
    )
    assert (
        f"ghcr.io/wakir-labs/wakir-provisioner:0.1.2@{SHA256_D}"
        in quadlet_after
    ), quadlet_after
    # Anti-regression assertion: stderr must NOT carry the
    # "perl: command not found" diagnostic that exposed Bug-16.
    assert "perl: command not found" not in proc.stderr.lower(), (
        f"resolver still invokes perl somewhere: {proc.stderr!r}"
    )


def test_tv_s9t7_16_resolver_source_has_no_perl_invocation() -> None:
    """The resolver source MUST NOT contain a ``perl `` invocation.
    Defensive static check that catches a Tag-6 reversion at lint
    time (faster than the subprocess-based PATH-stripped test).
    """
    src = RESOLVER.read_text(encoding="utf-8")
    # We strip comment lines first so the "Sprint-9 Tag-7 Aenderung"
    # commentary which mentions Perl is not a false positive.
    code_lines = []
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    # Forbid any of: 'perl ', 'perl\t', 'perl -...', backtick / $()
    # subshell that invokes perl.
    forbidden_patterns = [
        r"\bperl\s+-",
        r"\bperl\s*\|",
        r"\$\(\s*perl\b",
        r"`\s*perl\b",
    ]
    for pat in forbidden_patterns:
        m = re.search(pat, code)
        assert m is None, (
            f"resolver source still calls perl ({pat!r}): {m!r}"
        )


# ---------------------------------------------------------------------------
# TV-S9T7-16b — Bug-16 follow-on: bootstrap step 1 CLI-deps check
# ---------------------------------------------------------------------------


def test_tv_s9t7_16b_bootstrap_step_1_checks_cli_deps() -> None:
    """``step_1_preflight`` MUST explicitly enumerate the CLI tools
    the resolver + bootstrap depend on and fail fast with an
    operator-actionable diagnostic when one is missing. Live-Bring-
    up-3 silent-fell-through because perl was missing and Step 1
    did not check the resolver's dependency set."""
    src = _bootstrap_text()
    # The function exists.
    assert "step_1_preflight()" in src
    # The CLI-required list mentions the core tools the resolver + bootstrap
    # exercise. We assert the strict-required minimum is present in the
    # script source (the list itself lives in the function body).
    must_have_in_list = [
        '"sed"',
        '"grep"',
        '"awk"',
        '"cmp"',
        '"install"',
        '"mktemp"',
        '"mv"',
        '"jq"',
    ]
    for tool in must_have_in_list:
        assert tool in src, (
            f"step_1_preflight is missing a CLI-deps check for {tool}"
        )
    # The check must announce a missing-tool error before the rest of
    # the pre-flight returns, NOT silently continue.
    assert "missing required CLI tool" in src, (
        "step_1_preflight does not log a fail-fast diagnostic for "
        "missing CLI tools"
    )
    # The check must run BEFORE step 2 (toolbox). We approximate this by
    # asserting the CLI-deps list appears in source order BEFORE the
    # toolbox-step function definition.
    cli_check_pos = src.find("missing required CLI tool")
    toolbox_pos = src.find("step_2_toolbox()")
    assert cli_check_pos != -1
    assert toolbox_pos != -1
    assert cli_check_pos < toolbox_pos, (
        "CLI-deps check must run inside step_1_preflight, before "
        "step_2_toolbox"
    )


def test_tv_s9t7_16b_bootstrap_bash_version_guard() -> None:
    """The Bash-native resolver requires Bash >= 5 (FCOS-standard).
    ``step_1_preflight`` MUST guard against an older Bash on the host
    so the operator gets a clear diagnostic instead of a silent
    capture-group miss."""
    src = _bootstrap_text()
    assert "BASH_VERSINFO" in src, (
        "step_1_preflight must guard against Bash < 5 (resolver's "
        "Bash-native codepath uses BASH_REMATCH)"
    )


# ---------------------------------------------------------------------------
# TV-S9T7-17 — Bug-17: bucket-init Quadlet Exec= without leading python3
# ---------------------------------------------------------------------------


def test_tv_s9t7_17_bucket_init_exec_does_not_double_python3() -> None:
    """The ``wakir-provisioner`` Containerfile sets
    ``ENTRYPOINT ["python3"]``. The Quadlet ``Exec=`` MUST therefore
    NOT prefix the script invocation with ``python3``, or the effective
    container argv becomes ``python3 python3 /opt/wakir/bin/...`` and
    the inner ``python3`` interprets the literal string ``python3`` as
    a script-path relative to the WorkingDir.
    """
    text = BUCKET_INIT_QUADLET.read_text(encoding="utf-8")
    body = _strip_systemd_comments(text)
    # Find the Exec= line.
    exec_lines = [
        line for line in body.splitlines()
        if line.startswith("Exec=")
    ]
    assert exec_lines, (
        "wakir-nats-kv-bucket-init.container has no Exec= directive"
    )
    first_exec = exec_lines[0]
    # The Exec value MUST start with the absolute script path, NOT
    # with the literal ``python3`` token.
    value = first_exec[len("Exec="):].lstrip()
    assert not value.startswith("python3"), (
        f"Bug-17 regression: Exec= still starts with python3 "
        f"(double-entrypoint anti-pattern): {first_exec!r}"
    )
    # And it MUST start with the canonical script path so the
    # entrypoint's python3 picks it up.
    assert value.startswith("/opt/wakir/bin/nats-kv-bucket-provision"), (
        f"Exec= does not invoke the canonical script path: "
        f"{first_exec!r}"
    )


def test_tv_s9t7_17_effective_argv_is_defense_in_depth_safe() -> None:
    """The Quadlet's effective argv MUST work regardless of whether
    the published wakir-provisioner image carries
    ``ENTRYPOINT ["python3"]`` or no entrypoint at all. The Tag-6
    Containerfile dropped the entrypoint as a defense-in-depth
    measure, but Live-Bring-up-3 (2026-05-14) proved that the
    published image at :0.1.2 still ships an entrypoint — the
    image-rebuild did not land before the Quadlet was rolled.

    Two-axis invariant:

    1. The Quadlet's ``Exec=`` value MUST NOT start with the literal
       ``python3`` token. If the image has an entrypoint, the
       effective argv would otherwise contain TWO ``python3`` tokens
       and the inner one is interpreted as a script path (Bug-17).

    2. The Quadlet's ``Exec=`` first argument MUST be the absolute
       path of an executable that has a ``#!/usr/bin/env python3``
       shebang. This way, when the image has no entrypoint, the
       kernel still invokes Python via the shebang.
    """
    # Axis 1: no leading python3 in Exec=.
    text = BUCKET_INIT_QUADLET.read_text(encoding="utf-8")
    body = _strip_systemd_comments(text)
    joined = []
    buf: list[str] = []
    for line in body.splitlines():
        if line.endswith("\\"):
            buf.append(line[:-1].rstrip())
            continue
        buf.append(line)
        joined.append(" ".join(buf))
        buf = []
    if buf:
        joined.append(" ".join(buf))
    exec_lines = [ln for ln in joined if ln.startswith("Exec=")]
    assert exec_lines
    exec_argv = exec_lines[0][len("Exec="):].split()
    assert exec_argv, "Exec= directive is empty"
    assert exec_argv[0] != "python3", (
        f"Bug-17 regression: Exec= leads with python3 token "
        f"(double-interpreter risk if image keeps entrypoint): "
        f"{exec_argv!r}"
    )
    # Axis 2: the first argv must reference the provisioner script
    # whose shebang carries python3. We resolve the host-path
    # equivalent of the container path. The Quadlet bind-mounts
    # /opt/wakir-runtime/bin -> /opt/wakir/bin, so the script
    # ``/opt/wakir/bin/nats-kv-bucket-provision`` corresponds to the
    # repo path ``bin/nats-kv-bucket-provision``.
    script_target = exec_argv[0]
    assert script_target == "/opt/wakir/bin/nats-kv-bucket-provision", (
        f"Exec= no longer points at the canonical provisioner script: "
        f"{script_target!r}"
    )
    host_path = REPO_ROOT / "bin" / "nats-kv-bucket-provision"
    assert host_path.is_file(), (
        f"the Quadlet-referenced provisioner script is missing from "
        f"the repo: {host_path}"
    )
    first_line = host_path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!"), (
        f"provisioner script is missing a shebang; without it the "
        f"defense-in-depth (no-entrypoint) path breaks: {first_line!r}"
    )
    assert "python3" in first_line, (
        f"provisioner script shebang must reference python3: "
        f"{first_line!r}"
    )
    # And it must be executable so the kernel can fire the shebang
    # when the image has no entrypoint.
    mode = host_path.stat().st_mode
    assert mode & 0o111, (
        f"provisioner script is not executable (mode={oct(mode)}); "
        f"defense-in-depth (no-entrypoint) path breaks"
    )


# ---------------------------------------------------------------------------
# TV-S9T7-18 — Bug-18: bootstrap step 7 daemon-reload before start
# ---------------------------------------------------------------------------


def test_tv_s9t7_18_step_7_daemon_reload_before_start() -> None:
    """``step_7_bucket_init`` MUST run ``systemctl daemon-reload``
    unconditionally AFTER the install (or no-install-needed) block
    and BEFORE the ``systemctl start`` of the bucket-init unit.
    Live-Bring-up-3 emitted ``The unit file ... changed on disk. Run
    'systemctl daemon-reload' to reload units.`` when the reload was
    scoped only to the cmp-mismatch branch.
    """
    src = _bootstrap_text()
    # Locate the step-7 body.
    m = re.search(
        r"step_7_bucket_init\(\)\s*\{(.*?)\n\}",
        src,
        flags=re.DOTALL,
    )
    assert m is not None, "step_7_bucket_init() body not found"
    body = m.group(1)

    # The body MUST contain a daemon-reload call.
    assert "daemon-reload" in body, (
        "step_7_bucket_init() is missing daemon-reload"
    )
    # The systemctl start must reference the bucket-init unit by name.
    start_marker = "start wakir-nats-kv-bucket-init.service"
    assert start_marker in body, (
        f"step_7_bucket_init() does not start the bucket-init unit "
        f"({start_marker!r})"
    )
    reload_pos = body.find("daemon-reload")
    start_pos = body.find(start_marker)
    assert reload_pos != -1 and start_pos != -1
    assert reload_pos < start_pos, (
        "Bug-18 regression: daemon-reload appears AFTER systemctl "
        "start; systemd will run the stale unit cache"
    )


def test_tv_s9t7_18_step_7_daemon_reload_outside_install_conditional() -> None:
    """The Bug-18 fix is structural: the daemon-reload must NOT live
    INSIDE the ``if ! cmp -s ... ; then`` install branch — otherwise a
    fresh-install vs re-run path divergence can skip the reload. We
    assert the daemon-reload sits OUTSIDE that conditional by checking
    the indentation depth in the source: install logic is one level
    deeper than the surrounding step body.
    """
    src = _bootstrap_text()
    m = re.search(
        r"step_7_bucket_init\(\)\s*\{(.*?)\n\}",
        src,
        flags=re.DOTALL,
    )
    assert m is not None
    body = m.group(1)
    # Find the daemon-reload line that immediately precedes the
    # systemctl start. Walk lines, find the first daemon-reload that
    # is followed (later in the body) by the start. Assert that line
    # is indented with the BASE indent (the step-body level), not
    # the nested install-branch level.
    lines = body.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if "start wakir-nats-kv-bucket-init.service" in line:
            start_idx = i
            break
    assert start_idx is not None
    # Look backwards for the daemon-reload that gates this start.
    reload_idx = None
    for i in range(start_idx - 1, -1, -1):
        if "daemon-reload" in lines[i]:
            reload_idx = i
            break
    assert reload_idx is not None, (
        "no daemon-reload precedes the systemctl start"
    )
    # The step body's base indent is 2 spaces (matches sibling
    # step_6_* in this script). Anything > 2 means the reload is
    # nested inside a conditional.
    reload_line = lines[reload_idx]
    leading_ws = len(reload_line) - len(reload_line.lstrip(" "))
    assert leading_ws <= 2, (
        f"Bug-18 regression: daemon-reload is indented {leading_ws} "
        f"spaces (nested inside install-branch). Expected base-level "
        f"indent (<=2): {reload_line!r}"
    )


def test_tv_s9t7_18_step_7_daemon_reload_mock_hook_present() -> None:
    """The test-injection hook ``WAKIR_BOOTSTRAP_SYSTEMCTL`` MUST be
    used for the daemon-reload call so that a hermetic test harness
    can swap it for a recording mock. Without the hook, a hermetic
    daemon-reload-was-called assertion is impossible."""
    src = _bootstrap_text()
    m = re.search(
        r"step_7_bucket_init\(\)\s*\{(.*?)\n\}",
        src,
        flags=re.DOTALL,
    )
    assert m is not None
    body = m.group(1)
    # The daemon-reload line in step 7 must go through the hook.
    daemon_reload_lines = [
        line for line in body.splitlines()
        if "daemon-reload" in line and "$" in line
    ]
    assert any(
        "WAKIR_BOOTSTRAP_SYSTEMCTL" in line
        for line in daemon_reload_lines
    ), (
        "step_7 daemon-reload must invoke "
        "$WAKIR_BOOTSTRAP_SYSTEMCTL for hermetic mockability"
    )
