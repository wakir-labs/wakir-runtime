# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic vectors for the ADR-0076 acceptance sampler.

``scripts/acceptance/substrate-acceptance-probe.sh`` takes one sample
per hour on a substrate node: the current X509-SVID and the authority
its chain terminates at, the authority set the SPIRE server currently
holds, the mtime of ``agent-data.json``, and the staged bootstrap
anchor in the ``bundles`` volume.

Contract under test
-------------------

* the two trust topologies ADR-0076 spans -- a self-signed server
  (chain = leaf) and ``UpstreamAuthority "disk"`` (chain = leaf +
  intermediate, root in the bundle) -- both yield a chain authority that
  is comparable with the bundle authority set (TV-ACC-P-01, -02). The
  second is the one the decision moves to, and the one where naive
  "issuer of the leaf" matching would read red on a healthy substrate;
* the SVID private key the Workload API hands over reaches neither the
  record nor the log (TV-ACC-P-10);
* every failure is classified as either *the target answered badly* or
  *this probe could not measure*, never merged (TV-ACC-P-20..27), and
  only the second one changes the exit code to 2;
* the record carries measurements and no verdict (TV-ACC-P-30), and its
  key set is the one the judge reads (TV-ACC-P-31);
* none of the surfaces ADR-0076 rules out as evidence -- podman health,
  container uptime, server logs -- is read (TV-ACC-P-40);
* nothing under ``infra/spire/`` is touched (TV-ACC-P-41): the staged
  anchor is a contract with the bootstrap's staging step, consumed here and
  owned there.

Everything is hermetic. Certificates are minted in-process, the four
source overrides make the probe read fixtures instead of calling
podman, and ``WAKIR_ACC_NOW_EPOCH`` supplies the clock. The probe is
never run against a substrate by this module.
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
PROBE = REPO_ROOT / "scripts" / "acceptance" / "substrate-acceptance-probe.sh"
JUDGE = REPO_ROOT / "scripts" / "acceptance" / "substrate_acceptance_window.py"

UTC = dt.timezone.utc
NOW_EPOCH = 1790000000

#: A base64 blob that is recognisable in any output it should not be in.
KEY_CANARY = base64.b64encode(b"WAKIR-ACCEPTANCE-PRIVATE-KEY-CANARY" * 4).decode()

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None or shutil.which("od") is None,
    reason="the probe is a shell script over openssl/od; both are required to drive it",
)


# ------------------------------------------------------------- minting


def _mint(cn: str, *, issuer=None, issuer_key=None, ca: bool, days: int = 1, not_after_epoch=None):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(UTC).replace(tzinfo=None)
    if not_after_epoch is None:
        end = now + dt.timedelta(days=days)
        begin = now - dt.timedelta(minutes=1)
    else:
        # The SVID expiry is the one measurement the whole acceptance
        # turns on, so in the end-to-end vector it has to advance with
        # the simulated clock rather than with the wall clock of the
        # test runner. A fixture whose expiry never moves would make a
        # healthy substrate look like a cache -- which is the right
        # verdict about that fixture and the wrong one about the code.
        end = dt.datetime.fromtimestamp(not_after_epoch, UTC).replace(tzinfo=None)
        begin = end - dt.timedelta(hours=1)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer.subject if issuer is not None else name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(begin)
        .not_valid_after(end)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
    )
    signing_key = issuer_key if issuer_key is not None else key
    signing_pub = issuer.public_key() if issuer is not None else key.public_key()
    builder = builder.add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(signing_pub), critical=False
    )
    cert = builder.sign(signing_key, hashes.SHA256())
    return cert, key


def _ski(cert) -> str:
    ext = cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
    return ext.value.digest.hex().upper()


def _b64der(cert) -> str:
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()


def _jwks(*certs) -> str:
    keys = [
        {"kty": "EC", "crv": "P-256", "x": "aa", "y": "bb", "use": "x509-svid", "x5c": [_b64der(c)]}
        for c in certs
    ]
    keys.append({"kty": "EC", "crv": "P-256", "x": "cc", "y": "dd", "use": "jwt-svid", "kid": "jwt-1"})
    return json.dumps({"keys": keys, "spiffe_refresh_hint": 300})


def _workload_response(chain: list, bundle_cert) -> str:
    der = b"".join(c.public_bytes(serialization.Encoding.DER) for c in chain)
    return json.dumps(
        {
            "svids": [
                {
                    "spiffe_id": "spiffe://wakir.test/workload/probe",
                    "x509_svid": base64.b64encode(der).decode(),
                    "x509_svid_key": KEY_CANARY,
                    "bundle": _b64der(bundle_cert),
                    "hint": "",
                }
            ],
            "crl": [],
            "federated_bundles": {},
        }
    )


# ------------------------------------------------------------- fixtures


@pytest.fixture
def upstream(tmp_path):
    """``UpstreamAuthority "disk"``: root in the bundle, intermediate in the chain."""
    root, root_key = _mint("upstream-root", ca=True, days=1800)
    inter, inter_key = _mint("spire-x509-ca", issuer=root, issuer_key=root_key, ca=True)
    leaf, _ = _mint("svid", issuer=inter, issuer_key=inter_key, ca=False)
    files = {
        "svid": tmp_path / "wl.json",
        "bundle": tmp_path / "bundle.jwks",
        "agent": tmp_path / "agent-data.json",
        "anchor": tmp_path / "bootstrap.jwks",
        "log": tmp_path / "samples.ndjson",
    }
    files["svid"].write_text(_workload_response([leaf, inter], root))
    files["bundle"].write_text(_jwks(root))
    files["anchor"].write_text(_jwks(root))
    files["agent"].write_text('{"svid":[],"bundle":[]}')
    return {"root": root, "inter": inter, "leaf": leaf, "files": files}


def run_probe(files, *, env=None, args=()):
    e = dict(os.environ)
    e.update(
        {
            "WAKIR_ACC_SIDE": "orbit",
            "WAKIR_ACC_LOG": str(files["log"]),
            "WAKIR_ACC_NOW_EPOCH": str(NOW_EPOCH),
            "WAKIR_ACC_SVID_JSON_FILE": str(files["svid"]),
            "WAKIR_ACC_BUNDLE_JWKS_FILE": str(files["bundle"]),
            "WAKIR_ACC_AGENT_DATA_FILE": str(files["agent"]),
            "WAKIR_ACC_ANCHOR_FILE": str(files["anchor"]),
        }
    )
    e.update(env or {})
    proc = subprocess.run(
        ["bash", str(PROBE), *args], capture_output=True, text=True, env=e
    )
    try:
        record = json.loads(proc.stdout)
    except json.JSONDecodeError:
        record = None
    return proc, record


# --------------------------------------------------------- the topologies


def test_tv_acc_p_01_upstream_topology_chain_authority_is_the_bundle_root(upstream):
    """TV-ACC-P-01. Leaf + intermediate, root in the bundle: Z1 is satisfiable.

    This is the topology ADR-0076 decides on, and the one where the
    obvious implementation is wrong. The leaf's own issuer is the
    rotating intermediate and is legitimately *not* in the bundle; only
    the top of the chain names an authority the server holds. A probe
    that compared the leaf's issuer would read red on a healthy
    substrate every hour of the window.
    """
    proc, rec = run_probe(upstream["files"])
    assert proc.returncode == 0, proc.stderr
    assert rec["svid_status"] == "ok"
    assert rec["svid_chain_len"] == 2
    assert rec["svid_chain_authority_id"] == _ski(upstream["root"])
    assert rec["svid_leaf_authority_id"] == _ski(upstream["inter"])
    assert rec["bundle_authority_ids"] == [_ski(upstream["root"])]
    assert rec["svid_chain_authority_id"] in rec["bundle_authority_ids"]


def test_tv_acc_p_02_self_signed_topology_collapses_to_one_identity(tmp_path):
    """TV-ACC-P-02. No upstream: chain is the leaf alone, and both readings coincide.

    The pre-ADR-0076 substrate. Kept as a vector because the harness has
    to be able to measure the state it is meant to move away from --
    otherwise the first sample after the cutover would be its first run
    ever against anything.
    """
    root, root_key = _mint("self-signed-ca", ca=True)
    leaf, _ = _mint("svid", issuer=root, issuer_key=root_key, ca=False)
    files = {
        "svid": tmp_path / "wl.json",
        "bundle": tmp_path / "b.jwks",
        "agent": tmp_path / "a.json",
        "anchor": tmp_path / "anchor.jwks",
        "log": tmp_path / "s.ndjson",
    }
    files["svid"].write_text(_workload_response([leaf], root))
    files["bundle"].write_text(_jwks(root))
    files["anchor"].write_text(_jwks(root))
    files["agent"].write_text("{}")
    proc, rec = run_probe(files)
    assert proc.returncode == 0, proc.stderr
    assert rec["svid_chain_len"] == 1
    assert rec["svid_chain_authority_id"] == rec["svid_leaf_authority_id"] == _ski(root)
    assert rec["svid_chain_authority_id"] in rec["bundle_authority_ids"]


def test_tv_acc_p_03_rotated_intermediate_changes_only_the_leaf_authority(upstream, tmp_path):
    """TV-ACC-P-03. What F1 counts, and what it must not count.

    ``ca_ttl`` stays at 24 h by ADR-0076, so the signing intermediate
    rotates daily while the upstream root stands still for years. The
    rotation is therefore visible in ``svid_leaf_authority_id`` and
    invisible in the bundle set. A rotation counter fed from the bundle
    set would read zero for the whole window and the falsification would
    be unreachable.
    """
    root, root_key = upstream["root"], None
    # re-mint a second intermediate under the same root
    root2, root2_key = _mint("upstream-root", ca=True, days=1800)
    inter_b, inter_b_key = _mint("spire-x509-ca-2", issuer=root2, issuer_key=root2_key, ca=True)
    leaf_b, _ = _mint("svid", issuer=inter_b, issuer_key=inter_b_key, ca=False)
    files = dict(upstream["files"])
    files["svid"] = tmp_path / "wl2.json"
    files["bundle"] = tmp_path / "b2.jwks"
    files["anchor"] = tmp_path / "anchor2.jwks"
    files["log"] = tmp_path / "s2.ndjson"
    files["svid"].write_text(_workload_response([leaf_b, inter_b], root2))
    files["bundle"].write_text(_jwks(root2))
    files["anchor"].write_text(_jwks(root2))
    _, rec_b = run_probe(files)
    _, rec_a = run_probe(upstream["files"])
    assert rec_a["svid_leaf_authority_id"] != rec_b["svid_leaf_authority_id"]
    assert rec_a["svid_chain_authority_id"] != rec_b["svid_chain_authority_id"]  # distinct roots here
    assert rec_b["svid_chain_authority_id"] in rec_b["bundle_authority_ids"]


# ----------------------------------------------------------- key hygiene


def test_tv_acc_p_10_the_private_key_reaches_neither_record_nor_log(upstream):
    """TV-ACC-P-10. The Workload API hands over the SVID private key. It stops here.

    ``spire-agent api fetch x509`` has two output modes and both carry
    the key: ``-write`` puts ``svid.0.key`` on a filesystem, and
    ``-output json`` carries it in ``x509_svid_key``. The probe uses the
    JSON form precisely so that nothing is written, and extracts only
    the two certificate fields. The canary in the fixture is the
    assertion that this stays true.
    """
    proc, rec = run_probe(upstream["files"])
    assert KEY_CANARY not in proc.stdout
    assert KEY_CANARY not in proc.stderr
    assert KEY_CANARY not in json.dumps(rec)
    assert KEY_CANARY not in upstream["files"]["log"].read_text()


# -------------------------------- target-bad versus could-not-be-measured


def test_tv_acc_p_20_absent_anchor_is_target_bad_and_exit_zero(upstream):
    """TV-ACC-P-20. The negative control's state at the probe: measured, and bad.

    An emptied ``bundles`` volume is not a failure of the probe. The
    probe measured, found nothing staged, and said so; the exit code
    stays 0 because the measurement succeeded. It is the judge that
    turns this into a red window, and TV-ACC-W-40 is the other half.
    """
    upstream["files"]["anchor"].unlink()
    proc, rec = run_probe(upstream["files"])
    assert rec["anchor_status"] == "target_bad_anchor_absent"
    assert rec["unmeasured"] == []
    assert proc.returncode == 0


def test_tv_acc_p_21_empty_anchor_is_target_bad(upstream):
    """TV-ACC-P-21. A zero-byte file at the right path is not an anchor."""
    upstream["files"]["anchor"].write_text("")
    _, rec = run_probe(upstream["files"])
    assert rec["anchor_status"] == "target_bad_anchor_empty"


def test_tv_acc_p_22_anchor_that_is_not_a_bundle_is_target_bad(upstream):
    """TV-ACC-P-22. Present, non-empty, and not a bundle."""
    upstream["files"]["anchor"].write_text("this is not a JWKS\n")
    _, rec = run_probe(upstream["files"])
    assert rec["anchor_status"] == "target_bad_anchor_not_a_jwks"


def test_tv_acc_p_23_anchor_with_no_x509_authority_is_target_bad(upstream):
    """TV-ACC-P-23. A parseable JWKS carrying no X.509 authority.

    The shape the in-tree fixture CLIs produce (ADR-0076 context (c)):
    well-formed JSON at the right path, and nothing a cold agent could
    bootstrap from. Parsing is necessary and nowhere near sufficient.
    """
    upstream["files"]["anchor"].write_text(
        json.dumps({"keys": [{"kty": "EC", "use": "jwt-svid", "kid": "only-a-jwt-key"}]})
    )
    _, rec = run_probe(upstream["files"])
    assert rec["anchor_status"] == "target_bad_anchor_holds_no_x509_authority"
    assert rec["anchor_authority_ids"] == []


def test_tv_acc_p_24_workload_api_silence_is_target_bad(upstream):
    """TV-ACC-P-24. The Workload API answered with nothing."""
    upstream["files"]["svid"].write_text("")
    _, rec = run_probe(upstream["files"])
    assert rec["svid_status"] == "target_bad_workload_api_no_response"
    assert rec["svid_not_after_epoch"] is None


def test_tv_acc_p_25_response_without_an_svid_is_target_bad(upstream):
    """TV-ACC-P-25. Served, and empty. SPIRE's own wording is "contains no svids"."""
    upstream["files"]["svid"].write_text(json.dumps({"svids": [], "crl": []}))
    _, rec = run_probe(upstream["files"])
    assert rec["svid_status"] == "target_bad_no_svid_in_response"


def test_tv_acc_p_26_absent_agent_state_file_is_target_bad(upstream):
    """TV-ACC-P-26. No ``agent-data.json`` at all."""
    upstream["files"]["agent"].unlink()
    _, rec = run_probe(upstream["files"])
    assert rec["agent_data_status"] == "target_bad_agent_data_absent"


def test_tv_acc_p_27_unreachable_source_is_unmeasured_and_exit_two(upstream):
    """TV-ACC-P-27. The other half of TV-ACC-P-20: not measured is not a pass.

    The record says which field and why; the exit code is 2, not 0. Two
    different words for two different things, all the way down: the
    assignment's first standing requirement.
    """
    proc, rec = run_probe(upstream["files"], env={"WAKIR_ACC_SVID_JSON_FILE": "/nonexistent/source"})
    assert rec["svid_status"] == "unmeasured"
    assert {"field": "svid", "reason": "svid_source_unreadable"} in rec["unmeasured"]
    assert proc.returncode == 2


def test_tv_acc_p_28_bundle_without_x509_authority_is_target_bad(upstream):
    """TV-ACC-P-28. The server answered and holds no X.509 authority."""
    upstream["files"]["bundle"].write_text(
        json.dumps({"keys": [{"kty": "EC", "use": "jwt-svid", "kid": "j"}]})
    )
    _, rec = run_probe(upstream["files"])
    assert rec["bundle_status"] == "target_bad_bundle_holds_no_x509_authority"


# ------------------------------------------------------------ the record


def test_tv_acc_p_30_the_record_carries_no_verdict(upstream):
    """TV-ACC-P-30. The sampler does not form opinions.

    The judge refuses a record that carries a verdict-shaped field
    (TV-ACC-W-80). This is the producer side of the same rule: reading a
    conclusion off a field written by the thing under observation is the
    defect class found twice in this house on 2026-09-22, and the answer
    is structural rather than a third comment about it.
    """
    _, rec = run_probe(upstream["files"])
    forbidden = {"verdict", "status", "ok", "healthy", "pass", "z1", "z2", "z3", "z4", "f1", "f2", "result"}
    assert forbidden.isdisjoint(rec), sorted(forbidden & set(rec))


def test_tv_acc_p_31_the_judge_reads_what_the_probe_writes(upstream, tmp_path):
    """TV-ACC-P-31. One writer, one reader, pinned against drift.

    A reader that silently finds nothing and calls it "missing" is the
    same failure as no reader. The key set is therefore asserted across
    the seam rather than trusted to survive two separate edits.
    """
    run_probe(upstream["files"])
    run_probe(upstream["files"], env={"WAKIR_ACC_NOW_EPOCH": str(NOW_EPOCH + 3600)})
    proc = subprocess.run(
        [
            "python3",
            str(JUDGE),
            "--samples",
            str(upstream["files"]["log"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout)
    # Two samples an hour apart cannot establish a seven-day window --
    # the point here is that the reader parsed them at all, and that too
    # little evidence comes out UNKNOWN rather than PASS.
    assert payload["verdict"] == "UNKNOWN"
    assert proc.returncode == 2
    assert payload["samples"] == 2


def test_tv_acc_p_32_two_runs_append_two_lines(upstream):
    """TV-ACC-P-32. The log is a series, not a latest-value file."""
    run_probe(upstream["files"])
    run_probe(upstream["files"], env={"WAKIR_ACC_NOW_EPOCH": str(NOW_EPOCH + 3600)})
    lines = [l for l in upstream["files"]["log"].read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["observed_at_epoch"] != json.loads(lines[1])["observed_at_epoch"]


def test_tv_acc_p_33_a_known_marker_is_recorded(upstream):
    """TV-ACC-P-33. The falsification episodes are marked in the same series they interrupt."""
    _, rec = run_probe(upstream["files"], args=("--mark", "cold-agent-stop"))
    assert rec["marker"] == "cold-agent-stop"


def test_tv_acc_p_34_an_unknown_marker_is_refused_and_nothing_is_recorded(upstream):
    """TV-ACC-P-34. A marker the judge cannot interpret would carve the window on a boundary nobody meant.

    Refused at the source, with exit 3 and an empty log, rather than
    written and silently ignored downstream.
    """
    proc, _ = run_probe(upstream["files"], args=("--mark", "cold-agent-pause"))
    assert proc.returncode == 3
    assert not upstream["files"]["log"].exists() or upstream["files"]["log"].read_text() == ""


def test_tv_acc_p_35_a_sample_without_a_side_is_refused(upstream):
    """TV-ACC-P-35. A sample that does not say which substrate it describes is not a sample."""
    proc, _ = run_probe(upstream["files"], env={"WAKIR_ACC_SIDE": ""})
    assert proc.returncode == 3


def test_tv_acc_p_36_the_record_carries_no_spiffe_id(upstream):
    """TV-ACC-P-36. The SPIFFE ID stays on the node.

    On this substrate the agent's own SPIFFE ID embeds the join-token
    UUID. The sample log is read off the node to be judged, so nothing
    that identifies a node, an address or a credential subject goes into
    it: the side is an opaque label and the identities are key
    identifiers.
    """
    _, rec = run_probe(upstream["files"])
    blob = json.dumps(rec)
    assert "spiffe://" not in blob
    assert "spiffe_id" not in rec


# ------------------------------------------------- what must not be read


NON_EVIDENCE_TOKENS = (
    "podman inspect",
    "RestartCount",
    "State.Health",
    "podman logs",
    "journalctl",
    "podman ps",
    "podman healthcheck",
)


def test_tv_acc_p_40_the_probe_reads_none_of_the_forbidden_surfaces():
    """TV-ACC-P-40. ADR-0076's non-evidence list, enforced on the source.

    Podman health state was measured on 2026-09-22 to be the *inverse*
    of the truth on this substrate -- the wrapper exits 1 with empty
    output because the image has no shell, while the same check run
    directly answers "healthy". Container uptime was true for four
    months of not attesting. Server logs were error-free for 127 days of
    rotating a CA nobody consumed. All three are excluded by the
    decision; a prohibition that lives only in a comment is the same
    class of instrument as a healthcheck that never runs.
    """
    body = PROBE.read_text(encoding="utf-8")
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    for token in NON_EVIDENCE_TOKENS:
        assert token not in code, f"the probe reads the non-evidence surface {token!r}"


def test_tv_acc_p_41_the_harness_does_not_reach_into_the_bootstrap_it_observes():
    """TV-ACC-P-41. The seam with bootstrap step 3 is a read, not an edit.

    The staged anchor is written by
    ``infra/spire/federation/wakir-pilot-bootstrap.sh`` and refreshed by
    a timer beside it. This harness consumes that contract and owns none
    of it; both the volume and the file name are env-overridable so the
    contract can move without a change here. Two boxes were open in
    parallel when this was written, which is the practical reason the
    assertion exists rather than an intention.
    """
    for path in (PROBE, JUDGE):
        body = path.read_text(encoding="utf-8")
        code = "\n".join(
            l for l in body.splitlines() if not l.lstrip().startswith("#")
        )
        assert "infra/spire" not in code, f"{path.name} refers to infra/spire outside a comment"


def test_tv_acc_p_42_no_private_address_and_no_operator_path():
    """TV-ACC-P-42. No LAN addresses, no operator home paths in the harness.

    The rule that was public for four months because nothing ran it
    (#559). Here it runs on the two files this change adds.
    """
    import re

    rfc1918 = re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
    )
    for path in (PROBE, JUDGE):
        text = path.read_text(encoding="utf-8")
        assert not rfc1918.search(text), f"{path.name} carries a private address"
        assert "/home/" not in text, f"{path.name} carries an operator home path"


# ------------------------------------------- probe and judge, end to end


def _compressed_window(tmp_path, *, stage_anchor: bool, steps: int = 20, step_s: int = 3600):
    """Drive the real probe over a compressed but complete window.

    Same shape as the seven-day window, with the clock arguments scaled
    so the vector runs in seconds: the signing intermediate rotates every
    two samples instead of every 24, and the judge is told so. What is
    *not* scaled is anything the harness itself decides -- the episodes,
    the exclusions, the negative control and the three-valued verdict all
    run exactly as they will on the node.

    This is the only vector in which the probe and the judge meet. Both
    are otherwise tested against fixtures, and two halves that each work
    against a fixture of the other is how a seam drifts apart.
    """
    root, root_key = _mint("upstream-root", ca=True, days=1800)
    files = {
        "svid": tmp_path / "wl.json",
        "bundle": tmp_path / "bundle.jwks",
        "agent": tmp_path / "agent-data.json",
        "anchor": tmp_path / "bootstrap.jwks",
        "log": tmp_path / "samples.ndjson",
    }
    files["bundle"].write_text(_jwks(root))
    if stage_anchor:
        files["anchor"].write_text(_jwks(root))
    files["agent"].write_text('{"svid":[],"bundle":[]}')

    stop_at, start_at = 8, 10
    nc_start, nc_end = 16, 18
    frozen_agent_mtime = None

    for i in range(steps):
        now = NOW_EPOCH + i * step_s
        marker = None
        if i == stop_at:
            marker = "cold-agent-stop"
        elif i == start_at:
            marker = "cold-agent-start"
        elif i == nc_start:
            marker = "negative-control-start"
        elif i == nc_end:
            marker = "negative-control-end"

        agent_down = stop_at < i < start_at
        inter, inter_key = _mint(
            f"spire-x509-ca-{i // 2}", issuer=root, issuer_key=root_key, ca=True
        )
        # Deterministic per generation: re-minting inside the loop would
        # make every sample a rotation. The generation seed is the index
        # pair, so two consecutive samples share one intermediate.
        if i % 2 == 1 and hasattr(_compressed_window, "_last"):
            inter, inter_key = _compressed_window._last
        _compressed_window._last = (inter, inter_key)

        if agent_down:
            files["svid"].write_text(json.dumps({"svids": [], "crl": []}))
        else:
            leaf, _ = _mint(
                "svid",
                issuer=inter,
                issuer_key=inter_key,
                ca=False,
                not_after_epoch=now + step_s,
            )
            files["svid"].write_text(_workload_response([leaf, inter], root))

        if stop_at <= i <= start_at:
            if frozen_agent_mtime is None:
                frozen_agent_mtime = now - 120
            agent_mtime = frozen_agent_mtime
        else:
            agent_mtime = now - 120
        os.utime(files["agent"], (agent_mtime, agent_mtime))

        if nc_start <= i <= nc_end:
            files["anchor"].unlink(missing_ok=True)
        elif stage_anchor:
            files["anchor"].write_text(_jwks(root))
            os.utime(files["anchor"], (now - 300, now - 300))

        args = ("--mark", marker) if marker else ()
        run_probe(files, env={"WAKIR_ACC_NOW_EPOCH": str(now)}, args=args)

    if hasattr(_compressed_window, "_last"):
        del _compressed_window._last
    return files


JUDGE_ARGS_COMPRESSED = [
    "--window-seconds", str(19 * 3600),
    "--rotation-period-seconds", "7200",
    "--ca-overlap-seconds", "3600",
]


def _judge(files, extra=()):
    proc = subprocess.run(
        [
            "python3",
            str(JUDGE),
            "--samples",
            str(files["log"]),
            "--json",
            *JUDGE_ARGS_COMPRESSED,
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode, json.loads(proc.stdout)


def _state(payload, prefix):
    return next(j["state"] for j in payload["judgements"] if j["name"].startswith(prefix))


def test_tv_acc_p_50_a_staged_window_passes_end_to_end(tmp_path):
    """TV-ACC-P-50 (mutation control for TV-ACC-P-51). A staged anchor gives a green window.

    Twenty real probe runs, a real cold-agent episode, a real negative
    control, judged by the real judge. This is the vector that makes the
    red one below attributable: without it, TV-ACC-P-51's red could be
    anything from the anchor to a broken fixture.
    """
    files = _compressed_window(tmp_path, stage_anchor=True)
    rc, payload = _judge(files)
    assert payload["verdict"] == "PASS", json.dumps(payload, indent=2)
    assert rc == 0


def test_tv_acc_p_51_an_emptied_bundles_volume_makes_the_window_red(tmp_path):
    """TV-ACC-P-51. The negative control ADR-0076 makes mandatory, end to end.

    *"Ein Lauf mit geleertem bundles-Volume muss rot werden. Wird er das
    nicht, ist auch das grüne Ergebnis nichts wert."*

    The whole run is identical to TV-ACC-P-50 except that nothing is ever
    staged. The agent keeps attesting throughout -- Z1, Z2 and Z3 stay
    green, exactly as they did for the four months nobody noticed -- and
    the window is red on the anchor alone. That asymmetry is the reason
    the anchor assurance exists: without it this mandated control would
    come out green and take the meaning of every green window with it.
    """
    files = _compressed_window(tmp_path, stage_anchor=False)
    rc, payload = _judge(files)
    assert _state(payload, "Z4") == "FAIL"
    assert payload["verdict"] == "FAIL"
    assert rc == 1
    for prefix in ("Z1", "Z2", "Z3"):
        assert _state(payload, prefix) == "PASS", (
            f"{prefix} went {_state(payload, prefix)}: the point of this vector is that the standing "
            "assurances do not notice an emptied bundles volume"
        )


def test_tv_acc_p_52_the_negative_control_does_not_remove_what_it_tests(tmp_path):
    """TV-ACC-P-52. The TV-PROV-6 rule, checked on this harness's own control.

    The control empties the anchor and leaves everything else running.
    If it had also stopped the probe, the slice would be UNKNOWN and the
    control would have proved nothing; the judge refuses that shape
    (TV-ACC-W-72). Here the positive form is asserted: during the marked
    episode the other three sources are still being measured, so the red
    is attributable to the emptied volume and to nothing else.
    """
    files = _compressed_window(tmp_path, stage_anchor=True)
    lines = [json.loads(l) for l in files["log"].read_text().splitlines() if l.strip()]
    start = next(i for i, s in enumerate(lines) if s["marker"] == "negative-control-start")
    end = next(i for i, s in enumerate(lines) if s["marker"] == "negative-control-end")
    episode = lines[start : end + 1]
    assert episode, "the control produced no samples at all"
    for s in episode:
        assert s["anchor_status"] == "target_bad_anchor_absent"
        assert s["svid_status"] == "ok"
        assert s["bundle_status"] == "ok"
        assert s["agent_data_status"] == "ok"
        assert s["unmeasured"] == []


# ------------------------------------------------- the podman code path


def _podman_stub(tmp_path: Path, *, exec_rc: int, exec_out: str = "", volume_out: str = "") -> Path:
    """A stand-in for podman, so the branch the fixtures bypass is reachable.

    The four ``*_FILE`` overrides make the probe hermetic by skipping
    podman entirely -- which leaves the code that actually runs on the
    node unexercised. A branch no test can reach is a branch nobody has
    read, and this harness exists because of a check that had never run.
    """
    stub = tmp_path / "podman-stub"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "volume" ]]; then\n'
        f"  printf '%s' {json.dumps(volume_out)}\n"
        f"  exit {0 if volume_out else 125}\n"
        "fi\n"
        f"printf '%s' {json.dumps(exec_out)}\n"
        f"exit {exec_rc}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def test_tv_acc_p_60_absent_container_is_named_as_such(tmp_path, upstream):
    """TV-ACC-P-60. Podman's 125 is "there is nothing to exec into".

    Still a finding about the substrate -- during an acceptance window an
    absent agent is the finding, not an excuse -- but a different
    sentence from "the container is there and the API said nothing". The
    person reading a red window needs the difference, and the verdict
    does not change either way.
    """
    stub = _podman_stub(tmp_path, exec_rc=125)
    files = dict(upstream["files"])
    files["log"] = tmp_path / "stub.ndjson"
    env = {
        "WAKIR_ACC_PODMAN_BIN": str(stub),
        "WAKIR_ACC_SVID_JSON_FILE": "",
        "WAKIR_ACC_BUNDLE_JWKS_FILE": "",
    }
    proc, rec = run_probe(files, env=env)
    assert rec["svid_status"] == "target_bad_agent_container_unavailable"
    assert rec["bundle_status"] == "target_bad_server_container_unavailable"
    assert rec["unmeasured"] == []
    assert proc.returncode == 0


def test_tv_acc_p_61_absent_podman_is_unmeasured_not_a_finding(tmp_path, upstream):
    """TV-ACC-P-61. No podman at all is the probe's problem, not the substrate's.

    The pair to TV-ACC-P-60, and the one that must not be a finding: a
    probe that cannot run has not discovered anything about the thing it
    could not look at.
    """
    files = dict(upstream["files"])
    files["log"] = tmp_path / "nopodman.ndjson"
    env = {
        "WAKIR_ACC_PODMAN_BIN": str(tmp_path / "definitely-not-here"),
        "WAKIR_ACC_SVID_JSON_FILE": "",
        "WAKIR_ACC_BUNDLE_JWKS_FILE": "",
        "WAKIR_ACC_AGENT_DATA_FILE": "",
        "WAKIR_ACC_ANCHOR_FILE": "",
    }
    proc, rec = run_probe(files, env=env)
    assert rec["svid_status"] == "unmeasured"
    assert rec["bundle_status"] == "unmeasured"
    assert rec["agent_data_status"] == "unmeasured"
    assert rec["anchor_status"] == "unmeasured"
    assert {e["reason"] for e in rec["unmeasured"]} == {"podman_absent"}
    assert proc.returncode == 2


def test_tv_acc_p_62_the_podman_path_reads_the_same_values(tmp_path, upstream):
    """TV-ACC-P-62. The fixture path and the podman path produce the same record.

    Otherwise the whole hermetic suite above would be testing a branch
    that the node never takes.
    """
    response = upstream["files"]["svid"].read_text()
    stub = _podman_stub(tmp_path, exec_rc=0, exec_out=response)
    files = dict(upstream["files"])
    files["log"] = tmp_path / "parity-a.ndjson"
    _, via_stub = run_probe(
        files,
        env={"WAKIR_ACC_PODMAN_BIN": str(stub), "WAKIR_ACC_SVID_JSON_FILE": ""},
    )
    files["log"] = tmp_path / "parity-b.ndjson"
    _, via_fixture = run_probe(files)
    for key in (
        "svid_status",
        "svid_not_after_epoch",
        "svid_chain_len",
        "svid_chain_authority_id",
        "svid_leaf_authority_id",
    ):
        assert via_stub[key] == via_fixture[key], key
