# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/substrate-liveness-probe.sh``.

The probe answers one question about a SPIRE agent: *when did it last
hold a valid credential?* It exists because every cheaper signal was
measured on the live substrate on 2026-09-22 and found to be true and
worthless — the container read ``Up``, ``RestartCount`` read ``0``, and
the workload-API socket file was present, while the agent had not
attested since May.

Contract under test:

* an unexpired SVID and bundle with a fresh state file  -> green, exit 0
* an SVID expired beyond the grace window               -> red, exit 1
* an SVID expired but still inside the grace window     -> green
* an expired trust bundle outranks an expired SVID as a
  reason, because it is the condition the agent cannot
  recover from on its own                               -> red/bundle_expired
* a valid SVID with a stale state file                  -> red/state_stale
* a missing state file                                  -> red/state_missing
* an undecodable SVID, or no way to find the state file -> exit 2,
  verdict ``unmeasurable`` — *never* exit 0
* the payload carries no hostname, no IP, no SPIFFE ID

Plus the regression test that gives the probe its reason to exist:
the exact state measured on the live node on 2026-09-22 must come out
red, with the expiry age in the right order of magnitude. A probe that
was never run against its own originating incident is a check that
checks nothing.

Everything is hermetic: certificates are minted in-process with
``cryptography``, ``now`` is injected through ``WAKIR_NOW_EPOCH``, the
state file path is injected through ``WAKIR_AGENT_DATA_FILE`` so the
probe never calls podman, and no network is touched.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "scripts" / "observability" / "substrate-liveness-probe.sh"

UTC = dt.timezone.utc

# Measured read-only on the live nodes, 2026-09-22 ~08:19 UTC.
# Source: this PR's measurement run; cross-checked against
# agents-workspaces/mira/ar-hand/inbox/2026-09-21-live-vm-lauf-korrigiert.md
PILOT_SVID_NOT_AFTER = dt.datetime(2026, 5, 15, 8, 32, 35, tzinfo=UTC)
PILOT_SVID_NOT_BEFORE = dt.datetime(2026, 5, 15, 7, 32, 25, tzinfo=UTC)
PILOT_BUNDLE_NEWEST_NOT_AFTER = dt.datetime(2026, 5, 14, 22, 36, 19, tzinfo=UTC)
PILOT_STATE_MTIME_EPOCH = 1778830355  # 2026-05-15 07:32:35 UTC
MEASUREMENT_EPOCH = 1790065140  # 2026-09-22 08:19:00 UTC


def _mint(not_before: dt.datetime, not_after: dt.datetime, cn: str) -> str:
    """Mint a self-signed cert and return it base64(PEM), as SPIRE stores it."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before.replace(tzinfo=None))
        .not_valid_after(not_after.replace(tzinfo=None))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    return base64.b64encode(pem).decode("ascii")


def _write_state(
    tmp_path: Path,
    *,
    svid_not_after: dt.datetime,
    bundle_not_afters: list[dt.datetime],
    mtime_epoch: int,
    svid_not_before: dt.datetime | None = None,
    svid_override: str | None = None,
) -> Path:
    svid_not_before = svid_not_before or (svid_not_after - dt.timedelta(hours=1))
    svid = svid_override or _mint(svid_not_before, svid_not_after, "agent-svid")
    state = {
        "svid": [svid],
        "bundle": [
            _mint(na - dt.timedelta(days=1), na, f"bundle-{i}")
            for i, na in enumerate(bundle_not_afters)
        ],
        "reattestable": False,
        "bootstrap_use": 0,
        "bootstrap_start_time": "0001-01-01T00:00:00Z",
        "connection_attempts": 0,
    }
    path = tmp_path / "agent-data.json"
    path.write_text(json.dumps(state))
    os.utime(path, (mtime_epoch, mtime_epoch))
    return path


def _run(state_file: Path | None, now_epoch: int, **env_extra: str):
    env = dict(os.environ)
    env.pop("WAKIR_SIDE", None)
    env.pop("WAKIR_AGENT_DATA_FILE", None)
    if state_file is not None:
        env["WAKIR_AGENT_DATA_FILE"] = str(state_file)
    env["WAKIR_NOW_EPOCH"] = str(now_epoch)
    env["WAKIR_NODE_LABEL"] = env_extra.pop("WAKIR_NODE_LABEL", "node-a")
    env.update(env_extra)
    proc = subprocess.run(
        ["bash", str(PROBE)], env=env, capture_output=True, text=True, timeout=120
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, payload, proc.stderr


def _healthy(tmp_path: Path, now: dt.datetime) -> Path:
    return _write_state(
        tmp_path,
        svid_not_after=now + dt.timedelta(minutes=45),
        bundle_not_afters=[now + dt.timedelta(hours=20)],
        mtime_epoch=int(now.timestamp()) - 600,
    )


def test_probe_runs_where_it_is_needed():
    """The probe runs on Fedora CoreOS, which has **no python3 at all**
    (measured 2026-09-22 on both nodes) and where this dev sandbox's
    missing ``jq`` would equally be fatal. A liveness probe that cannot
    run on the host whose liveness is in question is the defect it was
    built to answer, one level down.

    Checked structurally, not by review: no executable line may invoke
    python or jq.
    """
    source = PROBE.read_text()
    assert source.splitlines()[0] == "#!/usr/bin/env bash"
    code = [
        line
        for line in source.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for banned in ("python", "jq "):
        offenders = [line for line in code if banned in line]
        assert not offenders, f"probe invokes {banned!r}: {offenders}"


def test_healthy_substrate_is_green(tmp_path):
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _healthy(tmp_path, now)
    rc, out, _ = _run(state, int(now.timestamp()))
    assert rc == 0
    assert out["verdict"] == "green"
    assert out["reason"] == "ok"
    assert out["svid_expired_for_seconds"] == 0
    assert out["bundle_expired_for_seconds"] == 0
    assert out["bundle_cert_count"] == 1


def test_svid_expired_beyond_grace_is_red(tmp_path):
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _write_state(
        tmp_path,
        svid_not_after=now - dt.timedelta(hours=3),
        bundle_not_afters=[now + dt.timedelta(hours=20)],
        mtime_epoch=int(now.timestamp()) - 600,
    )
    rc, out, _ = _run(state, int(now.timestamp()))
    assert rc == 1
    assert out["verdict"] == "red"
    assert out["reason"] == "svid_expired"
    assert out["svid_expired_for_seconds"] == pytest.approx(3 * 3600, abs=5)


def test_svid_expired_inside_grace_stays_green(tmp_path):
    """Negative control against alert fatigue: one missed rotation plus a
    restart must not page anyone. The grace window is one full TTL."""
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _write_state(
        tmp_path,
        svid_not_after=now - dt.timedelta(minutes=50),
        bundle_not_afters=[now + dt.timedelta(hours=20)],
        mtime_epoch=int(now.timestamp()) - 600,
    )
    rc, out, _ = _run(state, int(now.timestamp()))
    assert rc == 0, out
    assert out["verdict"] == "green"
    assert out["svid_expired_for_seconds"] == pytest.approx(50 * 60, abs=5)


def test_expired_bundle_outranks_expired_svid(tmp_path):
    """Both expired: the bundle is the reason, because that is the one the
    agent cannot recover from without an operator."""
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _write_state(
        tmp_path,
        svid_not_after=now - dt.timedelta(hours=5),
        bundle_not_afters=[now - dt.timedelta(hours=9)],
        mtime_epoch=int(now.timestamp()) - 600,
    )
    rc, out, _ = _run(state, int(now.timestamp()))
    assert rc == 1
    assert out["reason"] == "bundle_expired"
    assert out["bundle_expired_for_seconds"] == pytest.approx(9 * 3600, abs=5)


def test_newest_bundle_cert_wins(tmp_path):
    """A bundle holding an expired root next to a valid one is not expired.
    Measured reality: the live nodes carry 3 and 4 certs respectively."""
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _write_state(
        tmp_path,
        svid_not_after=now + dt.timedelta(minutes=30),
        bundle_not_afters=[
            now - dt.timedelta(days=4),
            now - dt.timedelta(days=2),
            now + dt.timedelta(hours=18),
        ],
        mtime_epoch=int(now.timestamp()) - 600,
    )
    rc, out, _ = _run(state, int(now.timestamp()))
    assert rc == 0, out
    assert out["bundle_cert_count"] == 3
    assert out["bundle_expired_for_seconds"] == 0


def test_stale_state_file_with_valid_svid_is_red(tmp_path):
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _write_state(
        tmp_path,
        svid_not_after=now + dt.timedelta(minutes=45),
        bundle_not_afters=[now + dt.timedelta(hours=20)],
        mtime_epoch=int(now.timestamp()) - 9 * 3600,
    )
    rc, out, _ = _run(state, int(now.timestamp()))
    assert rc == 1
    assert out["reason"] == "state_stale"
    assert out["state_age_seconds"] == pytest.approx(9 * 3600, abs=5)


def test_missing_state_file_is_red_not_unmeasurable(tmp_path):
    """An agent data dir without a state file is not an unknown — it is an
    agent that has never successfully attested."""
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    rc, out, _ = _run(tmp_path / "does-not-exist.json", int(now.timestamp()))
    assert rc == 1
    assert out["reason"] == "state_missing"


def test_undecodable_svid_is_unmeasurable_never_green(tmp_path):
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _write_state(
        tmp_path,
        svid_not_after=now + dt.timedelta(minutes=45),
        bundle_not_afters=[now + dt.timedelta(hours=20)],
        mtime_epoch=int(now.timestamp()) - 600,
        svid_override=base64.b64encode(b"not a certificate").decode("ascii"),
    )
    rc, out, _ = _run(state, int(now.timestamp()))
    assert rc == 2
    assert out["verdict"] == "unmeasurable"
    assert out["reason"] == "svid_undecodable"


def test_probe_that_cannot_run_is_distinguishable_from_a_bad_verdict(tmp_path):
    """A probe that never started must not look like a probe that found
    something, and must not look like a probe that found nothing wrong.

    The counter-example is on the substrate itself, measured 2026-09-22
    08:32 UTC: the SPIRE containers carry
    ``["CMD-SHELL", ".../spire-server healthcheck"]``, podman runs that
    through ``/bin/sh -c``, and the SPIRE image has no ``/bin/sh``. Every
    probe since May returned ``ExitCode 1, Output ""`` — and the container
    has published ``unhealthy`` on the strength of it, while the same
    command run directly answers ``Server is healthy.``

    Empty output is not a finding. This probe's answer to that is a
    payload with a reason code and exit 2, in every case where it could
    not do its job.
    """
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _healthy(tmp_path, now)

    bash = shutil.which("bash")
    assert bash, "no bash to test with"

    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = dict(os.environ)
    env["PATH"] = str(empty_bin)
    env["WAKIR_AGENT_DATA_FILE"] = str(state)
    env["WAKIR_NOW_EPOCH"] = str(int(now.timestamp()))
    env["WAKIR_NODE_LABEL"] = "node-a"
    proc = subprocess.run(
        [bash, str(PROBE)], env=env, capture_output=True, text=True, timeout=120
    )

    assert proc.returncode == 2, proc.stdout
    assert proc.stdout.strip(), "a probe that cannot run must still answer"
    out = json.loads(proc.stdout)
    assert out["verdict"] == "unmeasurable"
    assert out["reason"].startswith("missing_tool_"), out["reason"]
    # and it must not have invented a measurement it never took
    assert out["svid_not_after_epoch"] is None
    assert out["bundle_newest_not_after_epoch"] is None


def test_pretty_printed_state_file_parses_identically(tmp_path):
    """SPIRE writes the file compact. The reader must not depend on that,
    because a reader that depends on formatting fails quietly — and quiet
    failure is the thing being fixed here."""
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    compact = _healthy(tmp_path, now)
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(json.loads(compact.read_text()), indent=4))
    os.utime(pretty, (int(now.timestamp()) - 600, int(now.timestamp()) - 600))

    rc_a, out_a, _ = _run(compact, int(now.timestamp()))
    rc_b, out_b, _ = _run(pretty, int(now.timestamp()))
    assert rc_a == rc_b == 0, (out_a, out_b)
    assert out_a["svid_not_after_epoch"] == out_b["svid_not_after_epoch"]
    assert out_a["bundle_newest_not_after_epoch"] == out_b["bundle_newest_not_after_epoch"]


def test_state_file_of_the_wrong_shape_is_unmeasurable_never_green(tmp_path):
    """A file that is not an agent state file must not read as healthy."""
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    path = tmp_path / "agent-data.json"
    path.write_text('{"hello": "world"}')
    os.utime(path, (int(now.timestamp()), int(now.timestamp())))
    rc, out, _ = _run(path, int(now.timestamp()))
    assert rc == 2
    assert out["verdict"] == "unmeasurable"
    assert out["reason"] == "state_unparseable"


def test_no_path_and_no_side_is_unmeasurable_never_green():
    """The probe must not silently fall back to a default when it does not
    know what to look at."""
    env = dict(os.environ)
    env.pop("WAKIR_SIDE", None)
    env.pop("WAKIR_AGENT_DATA_FILE", None)
    env["WAKIR_NOW_EPOCH"] = str(MEASUREMENT_EPOCH)
    proc = subprocess.run(
        ["bash", str(PROBE)], env=env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["verdict"] == "unmeasurable"


def test_payload_discloses_no_topology(tmp_path):
    """The payload travels over a push channel. Confidentiality directive:
    no addresses, no operator hostnames, no SPIFFE ID — the SAN of the real
    SVID embeds a join-token UUID."""
    now = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
    state = _healthy(tmp_path, now)
    rc, out, _ = _run(state, int(now.timestamp()), WAKIR_NODE_LABEL="node-b")
    assert rc == 0
    blob = json.dumps(out)
    forbidden = ["192.168.", "spiffe://", "join_token", "BEGIN CERTIFICATE"]
    nodename = os.uname().nodename
    if len(nodename) >= 4:
        forbidden.append(nodename)
    for needle in forbidden:
        assert needle not in blob, f"payload leaked {needle!r}: {blob}"
    assert out["node"] == "node-b"
    assert set(out) == {
        "schema",
        "node",
        "observed_at_epoch",
        "observed_at",
        "verdict",
        "reason",
        "svid_ttl_seconds",
        "grace_seconds",
        "state_max_age_seconds",
        "svid_not_after_epoch",
        "svid_expired_for_seconds",
        "bundle_newest_not_after_epoch",
        "bundle_expired_for_seconds",
        "bundle_cert_count",
        "state_mtime_epoch",
        "state_age_seconds",
    }


def test_regression_the_incident_this_probe_exists_for(tmp_path):
    """The 2026-09-21/22 finding, replayed.

    A node whose agent last attested on 2026-05-15 and whose cached trust
    bundle expired on 2026-05-14, evaluated at the moment the Operator-Hand
    run measured it. Everything else about that node looked like operation:
    the container was ``Up``, ``RestartCount`` was ``0``, the socket file
    existed. The probe must call it red on the very first sample, and the
    reason must be the bundle, because that is the one nothing recovers from
    by itself.
    """
    state = _write_state(
        tmp_path,
        svid_not_after=PILOT_SVID_NOT_AFTER,
        svid_not_before=PILOT_SVID_NOT_BEFORE,
        bundle_not_afters=[
            PILOT_BUNDLE_NEWEST_NOT_AFTER - dt.timedelta(days=2),
            PILOT_BUNDLE_NEWEST_NOT_AFTER - dt.timedelta(days=1),
            PILOT_BUNDLE_NEWEST_NOT_AFTER,
        ],
        mtime_epoch=PILOT_STATE_MTIME_EPOCH,
    )
    rc, out, _ = _run(state, MEASUREMENT_EPOCH)

    assert rc == 1, out
    assert out["verdict"] == "red"
    assert out["reason"] == "bundle_expired"

    days_svid = out["svid_expired_for_seconds"] / 86400
    days_bundle = out["bundle_expired_for_seconds"] / 86400
    days_state = out["state_age_seconds"] / 86400
    assert 129 < days_svid < 131, days_svid
    assert 130 < days_bundle < 132, days_bundle
    assert 129 < days_state < 131, days_state

    # And the negative half of the same replay: the *day of the bring-up*
    # would have been green. "6/6 PASS on 2026-05-15" was not wrong, it was
    # early. The probe is what turns that into a statement with a shelf life.
    green_epoch = int(dt.datetime(2026, 5, 15, 8, 0, 0, tzinfo=UTC).timestamp())
    state_fresh = _write_state(
        tmp_path / "fresh",
        svid_not_after=PILOT_SVID_NOT_AFTER,
        svid_not_before=PILOT_SVID_NOT_BEFORE,
        bundle_not_afters=[dt.datetime(2026, 5, 16, 8, 0, 0, tzinfo=UTC)],
        mtime_epoch=PILOT_STATE_MTIME_EPOCH,
    )
    rc2, out2, _ = _run(state_fresh, green_epoch)
    assert rc2 == 0, out2
    assert out2["verdict"] == "green"


@pytest.fixture(autouse=True)
def _mkdir_fresh(tmp_path):
    (tmp_path / "fresh").mkdir(exist_ok=True)
    yield
