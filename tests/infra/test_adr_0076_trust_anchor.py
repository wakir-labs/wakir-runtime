# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for ADR-0076 -- the trust anchor of the
identity substrate (steps 1-6).

What ADR-0076 is about
----------------------

Measured on both pilot VMs 2026-09-22, lesend:

  * the agents' ``trust_bundle_path`` volume is empty and has been
    since it was created in May -- nothing ever wrote the bootstrap
    anchor;
  * the servers signed without an ``UpstreamAuthority``, minting a
    fresh self-signed root every ``ca_ttl`` (24h) and pruning the
    expired one, so a staged anchor could not have survived a day
    anyway;
  * the two ``spire-fed-bundle`` CLIs that look like the fix emit
    fixture JWKS whose keys are not SPIRE CA keys, and wiring them in
    would have produced a file at the right path, a green check, and
    an agent that still does not attest.

The last point is why this module leans on behaviour and negative
control rather than on presence assertions. A check that cannot fail
is the defect, not the guard against it.

Test-Vector index
-----------------

Configuration (static shape):

  * ``TV-0076-01``  the three federation server configs declare
    ``UpstreamAuthority "disk"``, and its paths are the paths the
    Quadlet actually mounts.
  * ``TV-0076-02``  ``ca_ttl`` is still ``24h`` everywhere, and the
    "production default is 30 days" claim is gone from the tree.
  * ``TV-0076-03``  no PEM private key material anywhere under
    ``infra/spire/`` -- the root is created on the node, never here.
  * ``TV-0076-04``  both federation agent configs carry
    ``rebootstrap_mode = "auto"``.
  * ``TV-0076-05``  the fixture CLIs say so, in the module docstring
    AND in the README, above the fold.
  * ``TV-0076-06``  the upstream-CA volume unit exists and the server
    template mounts it read-only.
  * ``TV-0076-07``  the re-staging timer fires strictly below
    ``ca_ttl``, and its service invokes the stager.

Behaviour -- the anchor stager:

  * ``TV-0076-10``  POSITIVE: a valid JWKS is staged, mode 0644,
    byte-identical to what the server returned.
  * ``TV-0076-11``  NEGATIVE CONTROL: empty output -> exit 2.
  * ``TV-0076-12``  NEGATIVE CONTROL: non-JSON output -> exit 2.
  * ``TV-0076-13``  NEGATIVE CONTROL: truncated JSON -> exit 2.
  * ``TV-0076-14``  NEGATIVE CONTROL: a JWKS with zero keys -> exit 2.
  * ``TV-0076-15``  NEGATIVE CONTROL: ``bundle show`` exits non-zero
    -> exit 2.
  * ``TV-0076-16``  every failure leaves the PREVIOUS anchor intact
    and no temp file behind. A stager that half-writes is worse than
    one that does not run.
  * ``TV-0076-17``  MUTATION CONTROL: with the key-count guard cut out
    of a copy of the script, TV-0076-14's vector goes green -- proof
    the vector tests the guard and not the scaffolding.
  * ``TV-0076-18``  the stager REWRITES on every run, including when
    the bundle document is byte-identical to the one already staged.
    ADR-0076 errata E3: the acceptance harness measures the re-staging
    cadence at the anchor's mtime, and under ``UpstreamAuthority
    "disk"`` the document is constant for the life of the root -- so a
    later "skip the rename when nothing changed" would stop the mtime
    on a HEALTHY substrate and produce a red window out of an
    optimisation. The property is load-bearing; this is where it is
    guarded rather than assumed.
  * ``TV-0076-19``  MUTATION CONTROL for TV-0076-18: a copy of the
    script with exactly that short-circuit spliced in must make
    TV-0076-18's assertion fail.

Behaviour -- the upstream CA root:

  * ``TV-0076-20``  POSITIVE: first run creates a self-signed EC P-256
    CA certificate with ``CA:TRUE``, key 0600, cert 0644, and the key
    belongs to the certificate.
  * ``TV-0076-21``  a second run does NOT regenerate. Rolling the root
    invalidates every SVID and bundle on both federation sides; a
    bootstrap that did it on a re-run would be a one-command outage of
    the peer.
  * ``TV-0076-22``  NEGATIVE CONTROL: half-present material (cert
    without key) aborts with rc 2 and does not regenerate over it.
  * ``TV-0076-23``  NEGATIVE CONTROL: an unparseable certificate
    aborts with rc 2.
  * ``TV-0076-24``  NEGATIVE CONTROL: a key that does not belong to
    the certificate is rejected. This is the failure that otherwise
    shows up hours later, at the first CSR, in a log nobody reads.
  * ``TV-0076-25``  the root's lifetime is multi-year, i.e. far longer
    than ``ca_ttl`` -- the entire point of the exercise.

Sandbox boundary
----------------

No podman, no systemd, no root, no live SPIRE. ``podman`` is a mock
script; ``WAKIR_STAGE_TARGET_DIR`` and the ``WAKIR_UPSTREAM_CA_CHOWN``
hook stand in for the parts that need uid 0. What this module
therefore does NOT establish, stated rather than left to be
discovered:

  * that SPIRE v1.14.6 accepts the emitted certificate as an
    ``UpstreamAuthority "disk"`` root -- that is a live-node
    measurement and belongs to the operator-hand cutover;
  * that the agent's SELinux context may read the staged anchor. The
    bundles volume carries ``Z`` on the server mount and ``ro,Z`` on
    the agent mount; two private relabels of one volume want a
    measurement on an enforcing node, and have not had one.

-- the engineering zone
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FED = REPO_ROOT / "infra" / "spire" / "federation"
AGENT = REPO_ROOT / "infra" / "spire" / "agent"
BOOTSTRAP = FED / "wakir-pilot-bootstrap.sh"
STAGER = FED / "bin" / "wakir-spire-stage-bootstrap-anchor"
SERVER_TPL = FED / "quadlet" / "wakir-spire-server-federation.container"
UPSTREAM_VOL = FED / "quadlet" / "wakir-spire-server-federation-upstream-ca.volume"
RESTAGE_SERVICE = FED / "quadlet" / "wakir-spire-bootstrap-anchor-restage.service"
RESTAGE_TIMER = FED / "quadlet" / "wakir-spire-bootstrap-anchor-restage.timer"

FEDERATION_SIDES = ("wakir", "orbit", "partner")

#: Where the Quadlet mounts the root material inside the container.
UPSTREAM_MOUNT = "/var/lib/spire/upstream-ca"

VALID_JWKS = (
    '{"keys":[{"kty":"EC","crv":"P-256",'
    '"x":"MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcAAA",'
    '"y":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",'
    '"use":"x509-svid"}]}\n'
)


def _server_conf(side: str) -> str:
    return (FED / "config" / f"spire-server-{side}.conf").read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """HCL structure only.

    These configs carry long rationale comments that quote option
    names. A structural assertion that reads them is asserting on
    prose, which is how a config can pass a check by talking about
    what it does not do.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _agent_conf(side: str) -> str:
    return (AGENT / "config" / f"spire-agent-{side}.conf").read_text(encoding="utf-8")


# =====================================================================
# Configuration shape
# =====================================================================


@pytest.mark.parametrize("side", FEDERATION_SIDES)
def test_tv_0076_01_upstream_authority_declared(side: str) -> None:
    """Step 1. The server must not be its own root any more."""
    text = _strip_comments(_server_conf(side))
    assert 'UpstreamAuthority "disk" {' in text, (
        f"spire-server-{side}.conf declares no UpstreamAuthority. Without "
        f"it the server mints a fresh self-signed root every ca_ttl and "
        f"prunes the old one -- which is the mechanism that made the "
        f"staged anchor worthless (ADR-0076)."
    )
    cert = re.search(r'cert_file_path\s*=\s*"([^"]+)"', text)
    key = re.search(r'key_file_path\s*=\s*"([^"]+)"', text)
    assert cert and key, f"spire-server-{side}.conf: UpstreamAuthority needs both paths"
    assert cert.group(1).startswith(UPSTREAM_MOUNT + "/"), (
        f"cert_file_path {cert.group(1)!r} is not under the mount the "
        f"Quadlet provides ({UPSTREAM_MOUNT}); the server would fail to "
        f"configure the plugin at start"
    )
    assert key.group(1).startswith(UPSTREAM_MOUNT + "/"), (
        f"key_file_path {key.group(1)!r} is not under {UPSTREAM_MOUNT}"
    )
    assert "bundle_file_path" not in text, (
        "bundle_file_path must stay unset for root-CA operation "
        "(plugin_server_upstreamauthority_disk.md, v1.14.6: 'When "
        "functioning as a root CA, the trust bundle is unused')"
    )


def test_tv_0076_02_ca_ttl_stays_24h_and_the_false_claim_is_gone() -> None:
    """``ca_ttl`` is the instrument, not the defect (ADR-0076 Beschluss).

    Raising it would defuse the acceptance window, which requires six
    observed rotations. And the comment that claimed we had shortened a
    30-day production default was wrong: 24h IS SPIRE's documented
    default. Both halves are asserted, because a corrected claim with a
    surviving copy is not corrected.
    """
    conf_dir = FED / "config"
    for path in sorted(conf_dir.glob("spire-server-*.conf")):
        raw = path.read_text(encoding="utf-8")
        text = _strip_comments(raw)
        assert re.search(r'^\s*ca_ttl\s*=\s*"24h"', text, re.MULTILINE), (
            f"{path.name}: ca_ttl must stay at 24h -- the acceptance window "
            f"needs the rotation it drives (ADR-0076 F1)"
        )
        assert "Production default is 30 days" not in raw, (
            f"{path.name} still claims SPIRE's ca_ttl default is 30 days. "
            f"It is 24h (doc/spire_server.md, v1.14.6). The claim is "
            f"checked on the RAW text including comments -- it only ever "
            f"lived in a comment."
        )


def test_tv_0076_03_no_private_key_material_in_the_tree() -> None:
    """The root is created on the node and never enters the repository.

    A private key in git is a published key. The ADR's risk section
    makes this an explicit condition of choosing the disk-backed root
    at all.
    """
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "infra" / "spire").rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----", text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"PEM private key blocks found under infra/spire/: {offenders}. "
        f"The upstream CA root is generated on the node into its own "
        f"volume and must never be committed (ADR-0076 risk section)."
    )


@pytest.mark.parametrize("side", ("wakir", "orbit"))
def test_tv_0076_04_rebootstrap_mode_auto(side: str) -> None:
    """Step 6. The default is ``never`` and it applied for 127 days."""
    text = _agent_conf(side)
    assert re.search(r'^\s*rebootstrap_mode\s*=\s*"auto"', text, re.MULTILINE), (
        f"spire-agent-{side}.conf must set rebootstrap_mode = \"auto\". "
        f"SPIRE's default is 'never': 'the agent will be prevented from "
        f"automated rebootstrapping, and manual recovery will be necessary "
        f"if trust is ever lost' (doc/spire_agent.md, v1.14.6)."
    )
    # And the honest half: it is inert until the NodeAttestor can
    # re-attest. A config that promises recovery it cannot deliver is
    # the same class of claim this ADR exists to clean up.
    assert "join_token" in text and "x509pop" in text, (
        f"spire-agent-{side}.conf sets rebootstrap_mode but does not name "
        f"why it is inert under join_token. Wave 2 (x509pop) is what makes "
        f"it real; the file has to say so or the next reader will believe "
        f"the switch does something."
    )


@pytest.mark.parametrize(
    "module",
    ("spire_fed_bundle.py", "spire_fed_bundle_rotator.py"),
)
def test_tv_0076_05a_fixture_clis_are_marked_in_their_docstring(module: str) -> None:
    """Step 5. The marking has to be the first thing a reader meets."""
    text = (FED / "bin" / module).read_text(encoding="utf-8")
    head = text[:2500]
    assert "FIXTURE ONLY" in head, (
        f"{module} does not carry the fixture-only banner near the top of "
        f"its docstring. It emits JWKS whose keys are not SPIRE CA keys; "
        f"wired into staging it produces a green check and a dead agent "
        f"(ADR-0076 context finding (c))."
    )
    assert "wakir-spire-stage-bootstrap-anchor" in head, (
        f"{module}'s banner must name the mechanism that IS the live path. "
        f"A prohibition without an alternative gets ignored."
    )


def test_tv_0076_05b_fixture_clis_are_marked_in_the_readme() -> None:
    text = (FED / "README.md").read_text(encoding="utf-8")
    assert text.count("Fixture only.") >= 4, (
        "the README's file table must mark all four fixture CLI entries "
        "(two wrappers, two modules) as fixture-only"
    )
    assert "are fixtures, not tools" in text, (
        "README §3 must carry the fixture warning above the CLI recipe -- "
        "the table entry alone is not where a reader in a hurry looks"
    )
    assert "### 3c." in text, (
        "README must document the live staging path (§3c); otherwise the "
        "fixture warning removes an option without offering one"
    )


def test_tv_0076_06_upstream_ca_volume_and_mount() -> None:
    """Step 2's substrate: its own volume, mounted read-only."""
    assert UPSTREAM_VOL.exists(), "upstream-CA volume unit missing"
    vol_text = UPSTREAM_VOL.read_text(encoding="utf-8")
    assert "VolumeName=wakir-spire-server-federation-<SIDE>-upstream-ca" in vol_text
    assert "<SIDE>" in vol_text, "placeholder must survive for per-side install"

    tpl = SERVER_TPL.read_text(encoding="utf-8")
    mount = re.search(
        r"^Volume=wakir-spire-server-federation-<SIDE>-upstream-ca\.volume:"
        r"([^:\s]+):([^\s]+)$",
        tpl,
        re.MULTILINE,
    )
    assert mount, "server Quadlet does not mount the upstream-CA volume"
    assert mount.group(1) == UPSTREAM_MOUNT, (
        f"upstream-CA mount target {mount.group(1)!r} must match the path "
        f"the server configs read ({UPSTREAM_MOUNT})"
    )
    opts = mount.group(2).split(",")
    assert "ro" in opts, (
        "the upstream-CA volume must be mounted read-only: the server has "
        "no business writing its own root, and rotating it is a bilateral "
        "maintenance-window operation"
    )
    assert "U" not in opts, (
        "no ``U`` on the upstream-CA mount -- the chown is the bootstrap's "
        "job and it verifies it; a 0600 private key's ownership must not "
        "be decided by a mount flag"
    )


def test_tv_0076_07_restage_timer_fires_below_ca_ttl() -> None:
    """Step 4. A cadence at or above ``ca_ttl`` is not a refresh."""
    assert RESTAGE_SERVICE.exists() and RESTAGE_TIMER.exists()
    timer = RESTAGE_TIMER.read_text(encoding="utf-8")
    m = re.search(r"^OnUnitActiveSec=(\d+)(min|h)$", timer, re.MULTILINE)
    assert m, "restage timer must declare an explicit OnUnitActiveSec"
    minutes = int(m.group(1)) * (60 if m.group(2) == "h" else 1)
    assert minutes < 24 * 60, (
        f"restage cadence {minutes} min is not below ca_ttl (1440 min); a "
        f"refresh that runs slower than the thing it refreshes reproduces "
        f"the May half-life"
    )
    assert minutes <= 120, (
        f"restage cadence {minutes} min leaves too little margin: the ADR "
        f"asks for 'deutlich unter ca_ttl', and missed ticks, reboots and "
        f"slow server starts all eat into it"
    )
    assert "Persistent=true" in timer, (
        "a tick missed while the VM was down must fire on next boot -- the "
        "stager is idempotent so a catch-up run is free"
    )

    service = RESTAGE_SERVICE.read_text(encoding="utf-8")
    assert re.search(r"^ExecStart=<STAGER_PATH> --side <SIDE>$", service, re.MULTILINE), (
        "the restage service must invoke the same stager the bootstrap "
        "installs -- two staging paths means the second one is untested"
    )
    assert "Type=oneshot" in service


# =====================================================================
# Behaviour: the anchor stager
# =====================================================================


@pytest.fixture()
def stage_env(tmp_path: Path):
    """A mock ``podman`` whose ``exec`` output the test controls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    out_file = tmp_path / "bundle-out"
    rc_file = tmp_path / "bundle-rc"
    rc_file.write_text("0\n")
    mock = bin_dir / "podman"
    mock.write_text(
        "#!/usr/bin/env bash\n"
        f'rc=$(cat "{rc_file}")\n'
        f'cat "{out_file}"\n'
        "exit $rc\n"
    )
    mock.chmod(0o755)
    vol = tmp_path / "bundles"
    vol.mkdir()

    def run(bundle_output: str, rc: int = 0, side: str = "wakir"):
        out_file.write_text(bundle_output)
        rc_file.write_text(f"{rc}\n")
        env = dict(os.environ)
        env.update(
            WAKIR_STAGE_PODMAN=str(mock),
            WAKIR_STAGE_TARGET_DIR=str(vol),
            WAKIR_STAGE_CHOWN="0",
        )
        return subprocess.run(
            ["bash", str(STAGER), "--side", side],
            capture_output=True,
            text=True,
            env=env,
        )

    run.volume = vol  # type: ignore[attr-defined]
    run.anchor = vol / "bootstrap.jwks"  # type: ignore[attr-defined]
    # Exposed so a mutation control can drive a modified copy of the
    # script against the same mock and the same volume.
    run.podman = mock  # type: ignore[attr-defined]
    return run


def test_tv_0076_10_stager_positive(stage_env) -> None:
    proc = stage_env(VALID_JWKS)
    assert proc.returncode == 0, proc.stderr
    anchor = stage_env.anchor
    assert anchor.exists(), "stager reported success without writing the anchor"
    assert anchor.read_text() == VALID_JWKS, (
        "the staged anchor must be byte-identical to what the server "
        "returned -- no re-encoding, no local crypto"
    )
    assert oct(anchor.stat().st_mode)[-3:] == "644"


@pytest.mark.parametrize(
    "case,payload,rc",
    [
        ("empty", "", 0),
        ("whitespace", "   \n\n", 0),
        ("not-json", "spire-server: command not found\n", 0),
        ("truncated", '{"keys":[{"kty":"EC"\n', 0),
        ("zero-keys", '{"keys":[]}\n', 0),
        ("keys-not-a-list", '{"keys":{"kty":"EC"}}\n', 0),
        ("exec-failed", "", 1),
    ],
    ids=[
        "TV-0076-11-empty",
        "TV-0076-11-whitespace",
        "TV-0076-12-not-json",
        "TV-0076-13-truncated",
        "TV-0076-14-zero-keys",
        "TV-0076-14-keys-not-a-list",
        "TV-0076-15-exec-failed",
    ],
)
def test_tv_0076_11_to_15_negative_controls(stage_env, case, payload, rc) -> None:
    """Each of these must be RED. A check that cannot fail is the bug."""
    proc = stage_env(payload, rc=rc)
    assert proc.returncode == 2, (
        f"case {case!r}: the stager exited {proc.returncode}, expected 2. "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "ERROR" in proc.stderr, f"case {case!r}: failure must be loud"
    assert not stage_env.anchor.exists(), (
        f"case {case!r}: the stager wrote an anchor from input it rejected"
    )


def test_tv_0076_16_failure_preserves_the_previous_anchor(stage_env) -> None:
    """The refresh path matters more than the first write.

    On the node this runs every 30 minutes against a live server. A
    transient failure that clobbered the good anchor would turn a
    hiccup into an outage at the next agent restart.
    """
    assert stage_env(VALID_JWKS).returncode == 0
    good = stage_env.anchor.read_bytes()

    for payload, rc in (("", 0), ("garbage\n", 0), ('{"keys":[]}\n', 0), ("", 1)):
        proc = stage_env(payload, rc=rc)
        assert proc.returncode == 2
        assert stage_env.anchor.read_bytes() == good, (
            "a failing run overwrote or truncated the previously staged anchor"
        )

    leftovers = [
        p.name
        for p in stage_env.volume.iterdir()
        if p.name != "bootstrap.jwks"
    ]
    assert not leftovers, (
        f"temp files left behind after failed runs: {leftovers}. The agent "
        f"reads this directory; litter here is the next diagnosis."
    )


def test_tv_0076_17_mutation_control(tmp_path: Path, stage_env) -> None:
    """Cut the key-count guard out and TV-0076-14 must go green.

    Without this, a zero-key document passing would look like a test
    doing its job, when it could equally be the scaffolding rejecting
    everything for an unrelated reason.
    """
    src = STAGER.read_text(encoding="utf-8")
    needle = '[[ "${key_count:-0}" -ge 1 ]] \\'
    assert src.count(needle) == 1, "guard text moved; update the mutation"
    mutated = src.replace(
        needle
        + '\n  || die "bundle document carries 0 keys -- an empty JWKS is not '
          'an anchor; anchor left untouched"',
        'true',
    )
    assert mutated != src, "mutation did not apply"
    # ...and the jq layer would still catch it, so drop that too: the
    # mutation has to isolate exactly one guard.
    mutated = mutated.replace(
        "if command -v jq >/dev/null 2>&1; then", "if false; then"
    )
    mutant = tmp_path / "mutant-stager"
    mutant.write_text(mutated)

    vol = tmp_path / "mutant-vol"
    vol.mkdir()
    bin_dir = tmp_path / "mutant-bin"
    bin_dir.mkdir()
    mock = bin_dir / "podman"
    mock.write_text('#!/usr/bin/env bash\nprintf \'{"keys":[]}\\n\'\n')
    mock.chmod(0o755)

    env = dict(os.environ)
    env.update(
        WAKIR_STAGE_PODMAN=str(mock),
        WAKIR_STAGE_TARGET_DIR=str(vol),
        WAKIR_STAGE_CHOWN="0",
    )
    proc = subprocess.run(
        ["bash", str(mutant), "--side", "wakir"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, (
        "with the key-count guard removed the zero-key document should be "
        "accepted -- if it still fails, TV-0076-14 is not measuring that "
        f"guard. stderr={proc.stderr!r}"
    )
    assert (vol / "bootstrap.jwks").exists()



def test_tv_0076_18_restage_rewrites_unchanged_content(stage_env) -> None:
    """The anchor is rewritten every run, unchanged content included.

    This is not an aesthetic preference about atomic writes. The
    seven-day acceptance harness (PR #562) measures whether the
    re-staging timer is alive by looking at the anchor's mtime, and
    under ``UpstreamAuthority "disk"`` there is nothing else it could
    look at: the published bundle is the long-lived root, so the
    document this script stages is byte-identical from one run to the
    next for years. A future "only write when the content changed"
    would therefore freeze the mtime permanently on a substrate that
    is perfectly healthy, and the window would go red because someone
    made the script faster.

    ADR-0076 errata E3 names the property as load-bearing. A property
    that is load-bearing and only written down in a header comment is
    the same instrument class this substrate spent four months paying
    for.

    The mtime is back-dated between the runs rather than compared
    against a sleep: timestamp granularity and inode reuse are both
    properties of whatever filesystem the runner happens to have, and
    neither of them is the property under test. What Z4 reads is "the
    file was written again", and back-dating measures exactly that on
    any filesystem.
    """
    assert stage_env(VALID_JWKS).returncode == 0
    first_bytes = stage_env.anchor.read_bytes()

    for _ in range(2):
        backdated = int(time.time()) - 3600
        os.utime(stage_env.anchor, (backdated, backdated))
        stale_ns = stage_env.anchor.stat().st_mtime_ns

        assert stage_env(VALID_JWKS).returncode == 0, "re-run of the stager failed"

        assert stage_env.anchor.read_bytes() == first_bytes, (
            "the re-run changed the staged bytes; the input was identical"
        )
        assert stage_env.anchor.stat().st_mtime_ns > stale_ns, (
            "the staged anchor's mtime did not move across a re-run with "
            "identical content. The acceptance window reads that mtime as "
            "'the re-staging timer is running'; if this assertion fails, a "
            "healthy node now reports a stopped timer (ADR-0076 errata E3)."
        )


def test_tv_0076_19_mutation_control_for_the_unconditional_write(
    tmp_path: Path, stage_env
) -> None:
    """Splice the plausible optimisation in; TV-0076-18 must go red.

    The optimisation is written here the way someone would actually
    write it -- compare what we just read against what is on disk,
    skip the rename when they match -- so the vector above is shown to
    be measuring the write and not the scaffolding.
    """
    src = STAGER.read_text(encoding="utf-8")
    needle = 'staged_tmp="${target_dir}/.${ANCHOR_NAME}.tmp.$$"'
    assert src.count(needle) == 1, "write block moved; update the mutation"
    short_circuit = textwrap.dedent(
        """\
        if cmp -s "$raw_file" "$anchor_path"; then
          note "unchanged -- nothing to do"
          exit 0
        fi
        """
    )
    mutated = src.replace(needle, short_circuit + needle)
    assert mutated != src, "mutation did not apply"
    mutant = tmp_path / "mutant-stager"
    mutant.write_text(mutated)

    # Prime the anchor with the real script, back-date it exactly as
    # TV-0076-18 does, then let the mutant run against the same
    # document.
    assert stage_env(VALID_JWKS).returncode == 0
    backdated = int(time.time()) - 3600
    os.utime(stage_env.anchor, (backdated, backdated))
    stale_ns = stage_env.anchor.stat().st_mtime_ns

    env = dict(os.environ)
    env.update(
        WAKIR_STAGE_PODMAN=str(stage_env.podman),
        WAKIR_STAGE_TARGET_DIR=str(stage_env.volume),
        WAKIR_STAGE_CHOWN="0",
    )
    proc = subprocess.run(
        ["bash", str(mutant), "--side", "wakir"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr

    assert stage_env.anchor.stat().st_mtime_ns == stale_ns, (
        "with the short-circuit spliced in the mtime still moved -- "
        "TV-0076-18 would then not be measuring the unconditional write"
    )

# =====================================================================
# Behaviour: the upstream CA root
# =====================================================================


@pytest.fixture()
def ca_env(tmp_path: Path):
    """Drive ``_ensure_upstream_ca_material`` out of the real bootstrap."""
    vol = tmp_path / "upstream-ca"
    vol.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock = bin_dir / "podman"
    mock.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "volume" && "$2" == "inspect" ]]; then\n'
        f'  printf \'%s\\n\' "{vol}"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    mock.chmod(0o755)

    def run(extra: str = "") -> subprocess.CompletedProcess:
        script = (
            "set -u\n"
            f'export WAKIR_BOOTSTRAP_PODMAN="{mock}"\n'
            'export WAKIR_TRUST_DOMAIN="wakir.test"\n'
            "export WAKIR_UPSTREAM_CA_CHOWN=0\n"
            f'source "{BOOTSTRAP}" >/dev/null 2>&1\n'
            "_ensure_upstream_ca_material wakir\n"
            "rc=$?\n"
            f"{extra}\n"
            "exit $rc\n"
        )
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True
        )

    run.vol = vol  # type: ignore[attr-defined]
    run.crt = vol / "root.crt"  # type: ignore[attr-defined]
    run.key = vol / "root.key"  # type: ignore[attr-defined]
    return run


def _openssl(*args: str) -> str:
    return subprocess.run(
        ["openssl", *args], capture_output=True, text=True
    ).stdout


def test_tv_0076_20_ca_root_shape(ca_env) -> None:
    proc = ca_env()
    assert proc.returncode == 0, proc.stderr
    crt, key = ca_env.crt, ca_env.key
    assert crt.exists() and key.exists()

    assert oct(key.stat().st_mode)[-3:] == "600", (
        "the root key must be 0600 -- it is the whole trust domain"
    )
    assert oct(crt.stat().st_mode)[-3:] == "644"

    text = _openssl("x509", "-in", str(crt), "-noout", "-text")
    assert "CA:TRUE" in text, "the root must be a CA certificate"
    assert "id-ecPublicKey" in text and "P-256" in text, (
        "ADR-0076 specifies EC P-256"
    )

    subject = _openssl("x509", "-in", str(crt), "-noout", "-subject")
    issuer = _openssl("x509", "-in", str(crt), "-noout", "-issuer")
    assert subject.split("=", 1)[1] == issuer.split("=", 1)[1], (
        "root-CA operation requires a self-signed certificate "
        "(plugin_server_upstreamauthority_disk.md, v1.14.6)"
    )

    cert_pub = _openssl("x509", "-in", str(crt), "-noout", "-pubkey")
    key_pub = _openssl("pkey", "-in", str(key), "-pubout")
    assert cert_pub and cert_pub == key_pub, (
        "the key must belong to the certificate"
    )
    assert crt.read_text().count("-----BEGIN CERTIFICATE-----") == 1, (
        "cert_file_path 'MUST contain exactly one certificate which is "
        "self-signed' for root-CA operation"
    )


def test_tv_0076_21_second_run_does_not_regenerate(ca_env) -> None:
    assert ca_env().returncode == 0
    first_crt = ca_env.crt.read_bytes()
    first_key = ca_env.key.read_bytes()

    proc = ca_env()
    assert proc.returncode == 0, proc.stderr
    assert ca_env.crt.read_bytes() == first_crt, (
        "a re-run rolled the CA root. That invalidates every SVID and every "
        "bundle copy on BOTH federation sides and is a bilateral "
        "maintenance-window operation (ADR-0076 §Migration) -- never a "
        "side effect of running the bootstrap again."
    )
    assert ca_env.key.read_bytes() == first_key
    assert "retained" in proc.stdout


def test_tv_0076_22_half_present_material_aborts(ca_env) -> None:
    assert ca_env().returncode == 0
    crt_before = ca_env.crt.read_bytes()
    ca_env.key.unlink()

    proc = ca_env()
    assert proc.returncode == 2, (
        "cert without key must abort, not silently regenerate: the "
        "'helpful' branch of that decision takes the peer down"
    )
    assert "half-present" in proc.stdout + proc.stderr
    assert ca_env.crt.read_bytes() == crt_before, (
        "the abort path must not touch the surviving half"
    )


def test_tv_0076_23_unparseable_certificate_aborts(ca_env) -> None:
    assert ca_env().returncode == 0
    ca_env.crt.write_text("-----BEGIN CERTIFICATE-----\nnot base64\n")
    proc = ca_env()
    assert proc.returncode == 2, (
        "a corrupt root certificate must stop the bring-up loudly rather "
        "than start a server that fails at its first CSR"
    )


def test_tv_0076_24_mismatched_key_is_rejected(ca_env, tmp_path: Path) -> None:
    """The check that earns its place.

    A cert next to somebody else's key yields a server that starts,
    logs nothing unusual, and fails hours later at the first CSR.
    """
    assert ca_env().returncode == 0
    foreign = tmp_path / "foreign.key"
    subprocess.run(
        [
            "openssl", "genpkey", "-algorithm", "EC",
            "-pkeyopt", "ec_paramgen_curve:P-256",
            "-out", str(foreign),
        ],
        check=True,
        capture_output=True,
    )
    script = (
        "set -u\n"
        f'source "{BOOTSTRAP}" >/dev/null 2>&1\n'
        f'_verify_upstream_ca_material "{ca_env.crt}" "{foreign}"\n'
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 2, (
        "a key that does not belong to the certificate must be rejected "
        f"before the server ever sees it. stdout={proc.stdout!r}"
    )

    # Positive counterpart, so the vector is not just 'everything fails'.
    ok = subprocess.run(
        [
            "bash", "-c",
            "set -u\n"
            f'source "{BOOTSTRAP}" >/dev/null 2>&1\n'
            f'_verify_upstream_ca_material "{ca_env.crt}" "{ca_env.key}"\n',
        ],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_tv_0076_25_root_outlives_ca_ttl_by_years(ca_env) -> None:
    """The point of the exercise: the root stands while the
    intermediate rotates."""
    assert ca_env().returncode == 0
    out = _openssl(
        "x509", "-in", str(ca_env.crt), "-noout", "-checkend", str(3 * 365 * 24 * 3600)
    )
    assert "will not expire" in out, (
        "the upstream root must outlive ca_ttl by years, not by days -- a "
        "short-lived root reproduces the defect with extra machinery. "
        f"openssl said: {out!r}"
    )
