# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""A healthcheck that cannot start must not be able to publish a verdict.

The finding, measured read-only on the live node on 2026-09-22 08:32 UTC
and confirmed independently on both nodes:

    .Config.Healthcheck.Test = ["CMD-SHELL", ".../spire-server healthcheck"]
    podman exec <server> /bin/sh -c 'echo ok'
      -> crun: executable file `/bin/sh` not found
    podman exec <server> /opt/spire/bin/spire-server healthcheck
      -> Server is healthy.
    .State.Health.Log -> ExitCode 1, Output "", every 10 s, since May

Podman wraps a *string* ``HealthCmd`` in ``/bin/sh -c``. The SPIRE images
have no shell. So the probe never started, failed with empty output, and
the container published ``unhealthy`` on the strength of it — while the
same command run without the wrapper reported the server healthy. The
label was not merely uninformative, it was the inverse of the truth.

The semantics were then measured rather than cited, on the target podman
(5.8.1, on the live node, 2026-09-22 10:05 UTC), with a throwaway
container that was created, inspected and removed:

    --health-cmd "/opt/spire/bin/spire-server healthcheck"
      -> ["CMD-SHELL","/opt/spire/bin/spire-server healthcheck"]
    --health-cmd '["/opt/spire/bin/spire-server", "healthcheck"]'
      -> ["CMD","/opt/spire/bin/spire-server","healthcheck"]

and Quadlet was measured to pass the array through verbatim
(``/usr/libexec/podman/quadlet -dryrun``, podman 5.8.4).

The rule this test enforces
---------------------------

**A HealthCmd that does not need a shell must not ask for one.**

Not a list of blessed files — a list would have to be maintained by the
same attention that missed this for four months. The rule is mechanical:
if the command uses no shell feature, it must be in exec form. The one
string-form command in the tree, ``wakir-nats``, uses ``||`` and a
redirect, genuinely needs ``sh``, and its image has one — so it passes on
its merits rather than by exemption.

What this test does not check: that the binary named in the exec form
exists in the image. That is an image-content question and belongs to a
lane that pulls images; here it would be an assertion about something not
present. Named so it is not mistaken for covered.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Characters that only mean something to a shell. A command containing
#: none of these gains nothing from ``/bin/sh -c`` and loses the ability
#: to run in an image that has no shell.
SHELL_METACHARACTERS = ("|", "&", ";", "<", ">", "$", "`", "*", "?", "(", ")", "\n")


def quadlet_files() -> list[Path]:
    return sorted(REPO_ROOT.glob("**/*.container"))


def healthcmds() -> list[tuple[Path, int, str]]:
    found = []
    for path in quadlet_files():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if line.startswith("HealthCmd="):
                found.append((path, number, line[len("HealthCmd=") :].strip()))
    return found


def test_there_are_healthcmds_to_check():
    """A rule that matches nothing passes for the wrong reason."""
    assert healthcmds(), "no HealthCmd= lines found — the parser, not the tree, is wrong"


def test_no_healthcmd_asks_for_a_shell_it_does_not_need():
    offenders = []
    for path, number, value in healthcmds():
        if value.startswith("["):
            continue
        if any(char in value for char in SHELL_METACHARACTERS):
            continue
        offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {value}")

    assert not offenders, (
        "These HealthCmd values are plain commands written in string form. "
        "Podman runs a string HealthCmd through /bin/sh -c, so in an image "
        "without a shell the check never starts — it fails with empty output "
        "every interval, and the container publishes `unhealthy` as though "
        "that were a finding. Measured on the live substrate 2026-09-22.\n"
        "Write them as a JSON array instead:\n"
        '  HealthCmd=["/path/to/binary", "subcommand"]\n'
        "Offenders:\n  " + "\n  ".join(offenders)
    )


def test_every_exec_form_healthcmd_is_a_valid_list_of_strings():
    """A malformed array is silently treated as a string by podman, which
    would put the file back in the failure class it was moved out of."""
    for path, number, value in healthcmds():
        if not value.startswith("["):
            continue
        where = f"{path.relative_to(REPO_ROOT)}:{number}"
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            pytest.fail(f"{where}: not valid JSON ({exc}): {value}")
        assert isinstance(parsed, list) and parsed, f"{where}: must be a non-empty list"
        assert all(isinstance(part, str) for part in parsed), f"{where}: elements must be strings"
        assert parsed[0].startswith("/"), (
            f"{where}: first element should be an absolute path — exec form does not "
            "get the shell's PATH handling for free"
        )


def test_the_four_measured_broken_healthchecks_are_in_exec_form():
    """The regression this change exists for.

    These four quadlets target images measured on 2026-09-22 to have no
    ``/bin/sh``: ghcr.io/spiffe/spire-server and ghcr.io/spiffe/spire-agent.
    For them the string form is not a style question, it is a check that
    cannot run.
    """
    measured_shell_less = [
        "infra/spire/agent/quadlet/wakir-spire-agent-federation.container",
        "infra/spire/federation/quadlet/wakir-spire-server-federation.container",
        "quadlet/wakir-spire-agent.container",
        "quadlet/wakir-spire-server.container",
    ]
    by_path = {
        str(path.relative_to(REPO_ROOT)): value for path, _, value in healthcmds()
    }
    for rel in measured_shell_less:
        assert rel in by_path, f"{rel} has no HealthCmd any more — did it move?"
        assert by_path[rel].startswith("["), f"{rel}: back in string form"


def test_nats_keeps_its_shell_form_and_earns_it():
    """The negative control.

    ``wakir-nats`` is the one string-form HealthCmd left. It passes not by
    exemption but on its merits: its command uses ``||`` and a redirect, so
    it genuinely needs a shell, and its image was measured to have one
    (2026-09-22). A rule that had to list it as an exception would be a
    rule maintained by the same attention that missed the original defect.
    """
    nats = REPO_ROOT / "quadlet" / "wakir-nats.container"
    values = [value for path, _, value in healthcmds() if path == nats]
    assert values, "wakir-nats has no HealthCmd"
    value = values[0]
    assert not value.startswith("["), "wakir-nats was converted — it needs the shell"
    assert any(char in value for char in SHELL_METACHARACTERS)
