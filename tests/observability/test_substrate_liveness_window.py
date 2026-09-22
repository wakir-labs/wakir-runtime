# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/substrate-liveness-window.py``.

The window is the half of the substrate melder that notices silence. The
probe on the node produces a verdict; this evaluator, on a runner that
never touches the private network, asks whether every expected node has
a fresh, authentic, green heartbeat.

What is under test, and why each case earns its place:

* the happy path, so the failure paths mean something;
* ``red`` and ``stale`` and ``missing`` — the three shapes of "not yes";
* **``unmeasurable`` counts as red.** Wired, not commented. A probe that
  could not measure is not a sign of life;
* **a forged heartbeat cannot silence the alarm.** Without the signature
  check, anyone who learned the topic could post ``green`` and switch
  the watchdog off from outside. Two tests: a forgery cannot supply a
  missing node, and a forgery cannot outrank a genuine red;
* **a replayed old message cannot present itself as fresh** — recency is
  decided by the probe's own timestamp, not by the broker's;
* the evaluator's own blindness (no key, no topic, no expectation, an
  unreachable broker) exits 2, never 0;
* an empty ``--expect`` list is refused rather than defaulted, because a
  window that expects nothing is green forever — which is the defect,
  not the configuration.

Plus the drill: the frozen May state of the live nodes, replayed through
the whole chain, must come out red while everything else about those
nodes still looks like operation.

Nothing here touches the network: the broker is replaced by stdin or a
file in every case.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOW = REPO_ROOT / "scripts" / "observability" / "substrate-liveness-window.py"

KEY = "test-key-not-a-real-secret"
OTHER_KEY = "the-key-an-attacker-would-not-have"

NOW = 1790065485  # 2026-09-22T08:24:45Z, the hour the live nodes were measured

# ---------------------------------------------------------------------
# Recorded, not invented.
#
# These two lines are the verbatim output of
# scripts/observability/substrate-liveness-probe.sh executed against the
# two live federation nodes on 2026-09-22 08:24:45 UTC, read-only, piped
# over stdin so that nothing was installed. They are the substrate's own
# words about itself on the day the outage was found.
#
# There is deliberately no recorded *green* payload: no node has been
# green since May, so a green fixture would be a fabrication. The green
# cases below are synthesised and say so.
# ---------------------------------------------------------------------
RECORDED_NODE_A = {
    "schema": "wakir.substrate-liveness/v1",
    "node": "node-a",
    "observed_at_epoch": 1790065485,
    "observed_at": "2026-09-22T08:24:45Z",
    "verdict": "red",
    "reason": "bundle_expired",
    "svid_ttl_seconds": 3600,
    "grace_seconds": 3600,
    "state_max_age_seconds": 21600,
    "svid_not_after_epoch": 1778833955,
    "svid_expired_for_seconds": 11231530,
    "bundle_newest_not_after_epoch": 1778884579,
    "bundle_expired_for_seconds": 11180906,
    "bundle_cert_count": 3,
    "state_mtime_epoch": 1778830355,
    "state_age_seconds": 11235130,
}
RECORDED_NODE_B = {
    "schema": "wakir.substrate-liveness/v1",
    "node": "node-b",
    "observed_at_epoch": 1790065485,
    "observed_at": "2026-09-22T08:24:45Z",
    "verdict": "red",
    "reason": "bundle_expired",
    "svid_ttl_seconds": 3600,
    "grace_seconds": 3600,
    "state_max_age_seconds": 21600,
    "svid_not_after_epoch": 1778993959,
    "svid_expired_for_seconds": 11071526,
    "bundle_newest_not_after_epoch": 1779060452,
    "bundle_expired_for_seconds": 11005033,
    "bundle_cert_count": 4,
    "state_mtime_epoch": 1778990359,
    "state_age_seconds": 11075126,
}


def payload(node: str, verdict: str, observed_at_epoch: int, reason: str = "ok") -> dict:
    """A synthesised probe payload. Used for every case but the recorded two."""
    return {
        "schema": "wakir.substrate-liveness/v1",
        "node": node,
        "observed_at_epoch": observed_at_epoch,
        "observed_at": "synthesised",
        "verdict": verdict,
        "reason": reason,
        "svid_ttl_seconds": 3600,
        "grace_seconds": 3600,
        "state_max_age_seconds": 21600,
        "svid_not_after_epoch": observed_at_epoch + 1800,
        "svid_expired_for_seconds": 0,
        "bundle_newest_not_after_epoch": observed_at_epoch + 72000,
        "bundle_expired_for_seconds": 0,
        "bundle_cert_count": 3,
        "state_mtime_epoch": observed_at_epoch - 300,
        "state_age_seconds": 300,
    }


def wire(body: dict, key: str = KEY, *, prefix: str = "wakir-hb1") -> str:
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    mac = hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
    return f"{prefix} {mac} {base64.b64encode(raw).decode()}"


def run(
    lines: list[str] | None,
    expect: list[str],
    *,
    now: int = NOW,
    window: int = 7200,
    key: str | None = KEY,
    topic: str | None = "topic-for-tests",
    source: str = "-",
    extra: list[str] | None = None,
):
    env = dict(os.environ)
    for name in ("WAKIR_NTFY_TOPIC", "WAKIR_HEARTBEAT_HMAC_KEY"):
        env.pop(name, None)
    if key is not None:
        env["WAKIR_HEARTBEAT_HMAC_KEY"] = key
    if topic is not None:
        env["WAKIR_NTFY_TOPIC"] = topic

    argv = [sys.executable, str(WINDOW), "--source", source, "--now-epoch", str(now)]
    argv += ["--window-seconds", str(window)]
    for node in expect:
        argv += ["--expect", node]
    argv += extra or []

    proc = subprocess.run(
        argv,
        input="\n".join(lines or []),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc


def report_of(proc, tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


# --- the happy path ---------------------------------------------------


def test_every_expected_node_fresh_and_green_is_exit_zero(tmp_path):
    lines = [
        wire(payload("node-a", "green", NOW - 300)),
        wire(payload("node-b", "green", NOW - 200)),
    ]
    proc = run(lines, ["node-a", "node-b"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rep = report_of(proc, tmp_path)
    assert rep["verdict"] == "green"
    assert rep["failing_nodes"] == []
    assert rep["nodes"]["node-a"]["state"] == "ok"


# --- the three shapes of "not yes" ------------------------------------


def test_red_heartbeat_fails_the_window(tmp_path):
    lines = [
        wire(payload("node-a", "red", NOW - 60, reason="bundle_expired")),
        wire(payload("node-b", "green", NOW - 60)),
    ]
    proc = run(lines, ["node-a", "node-b"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 1
    rep = report_of(proc, tmp_path)
    assert rep["nodes"]["node-a"]["state"] == "red"
    assert rep["nodes"]["node-a"]["probe_reason"] == "bundle_expired"
    assert rep["failing_nodes"] == ["node-a"]


def test_stale_heartbeat_fails_even_when_it_was_green(tmp_path):
    """The node said green — three hours ago, into a two-hour window. A
    green that has stopped arriving is the exact shape of the incident."""
    lines = [wire(payload("node-a", "green", NOW - 3 * 3600))]
    proc = run(lines, ["node-a"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 1
    rep = report_of(proc, tmp_path)
    assert rep["nodes"]["node-a"]["state"] == "stale"
    assert rep["nodes"]["node-a"]["age_seconds"] == 3 * 3600


def test_missing_node_fails(tmp_path):
    lines = [wire(payload("node-a", "green", NOW - 60))]
    proc = run(lines, ["node-a", "node-b"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 1
    rep = report_of(proc, tmp_path)
    assert rep["nodes"]["node-b"]["state"] == "missing"
    assert rep["nodes"]["node-b"]["age_seconds"] is None


# --- the rule Mira asked to see wired, not commented ------------------


def test_unmeasurable_counts_as_red(tmp_path):
    """The probe could not do its job. That is not a sign of life.

    The counter-example is on the substrate: the SPIRE container
    healthchecks have returned `ExitCode 1, Output ""` every ten seconds
    since May and the container published `unhealthy` on the strength of
    it, while the same command run without the shell wrapper answers
    `Server is healthy.` An answer that was never computed must not be
    able to pass for one that was.
    """
    lines = [
        wire(payload("node-a", "unmeasurable", NOW - 60, reason="missing_tool_openssl")),
    ]
    proc = run(lines, ["node-a"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 1, proc.stdout
    rep = report_of(proc, tmp_path)
    assert rep["nodes"]["node-a"]["state"] == "unmeasurable"
    assert rep["verdict"] == "red"


def test_a_verdict_this_evaluator_does_not_know_counts_as_red(tmp_path):
    """Forward compatibility in the safe direction: a future probe word
    is not assumed to be good news."""
    lines = [wire(payload("node-a", "probably-fine-honestly", NOW - 60))]
    proc = run(lines, ["node-a"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 1
    assert report_of(proc, tmp_path)["nodes"]["node-a"]["state"] == "unmeasurable"


# --- forgery ----------------------------------------------------------


def test_forged_heartbeat_cannot_supply_a_missing_node(tmp_path):
    """Anyone who learns the topic can post to it. If that were enough to
    report green, the watchdog could be switched off from the outside."""
    lines = [wire(payload("node-a", "green", NOW - 60), key=OTHER_KEY)]
    proc = run(lines, ["node-a"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 1
    rep = report_of(proc, tmp_path)
    assert rep["nodes"]["node-a"]["state"] == "missing"
    assert rep["rejected_messages"] == 1


def test_forged_green_cannot_outrank_a_genuine_red(tmp_path):
    lines = [
        wire(payload("node-a", "red", NOW - 120, reason="bundle_expired")),
        wire(payload("node-a", "green", NOW - 10), key=OTHER_KEY),
    ]
    proc = run(lines, ["node-a"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 1
    rep = report_of(proc, tmp_path)
    assert rep["nodes"]["node-a"]["state"] == "red"
    assert rep["rejected_messages"] == 1


def test_malformed_and_wrong_version_messages_are_rejected(tmp_path):
    lines = [
        "not a heartbeat at all",
        wire(payload("node-a", "green", NOW - 60), prefix="wakir-hb0"),
        "wakir-hb1 deadbeef !!!not-base64!!!",
        wire(payload("node-a", "green", NOW - 30)),
    ]
    proc = run(lines, ["node-a"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 0, proc.stdout
    rep = report_of(proc, tmp_path)
    assert rep["rejected_messages"] == 3


def test_replayed_old_message_does_not_pass_for_fresh(tmp_path):
    """Recency is the probe's own timestamp, never the broker's arrival
    order. A captured message re-posted today must still read as old."""
    lines = [
        wire(payload("node-a", "green", NOW - 5 * 3600)),  # replayed last, still old
    ]
    proc = run(lines, ["node-a"], extra=["--json-out", str(tmp_path / "report.json")])
    assert proc.returncode == 1
    assert report_of(proc, tmp_path)["nodes"]["node-a"]["state"] == "stale"


# --- the evaluator's own blindness ------------------------------------


def test_no_hmac_key_is_unmeasurable_never_green():
    lines = [wire(payload("node-a", "green", NOW - 60))]
    proc = run(lines, ["node-a"], key=None)
    assert proc.returncode == 2
    assert "unmeasurable" in proc.stdout
    assert "HMAC" in proc.stdout


def test_no_topic_is_unmeasurable_when_the_broker_would_be_used():
    proc = run([], ["node-a"], topic=None, source="https://broker.invalid")
    assert proc.returncode == 2
    assert "WAKIR_NTFY_TOPIC" in proc.stdout


def test_empty_expectation_list_is_refused():
    """A window that expects no node is satisfied by silence — the defect
    itself, dressed as configuration."""
    proc = run([wire(payload("node-a", "green", NOW))], [])
    assert proc.returncode == 2
    assert "expects no node" in proc.stdout


def test_unreachable_broker_is_unmeasurable_not_green():
    """A broker we cannot reach is not evidence that the substrate is
    fine. It is not evidence that it is broken either."""
    proc = run(None, ["node-a"], source="http://127.0.0.1:9")
    assert proc.returncode == 2
    assert "unmeasurable" in proc.stdout


def test_unreadable_source_file_is_unmeasurable(tmp_path):
    proc = run(None, ["node-a"], source=str(tmp_path / "nope.jsonl"))
    assert proc.returncode == 2


# --- broker envelope parsing ------------------------------------------


def test_only_message_events_are_read(tmp_path):
    """ntfy's poll stream carries keepalives and open events too. A
    keepalive is not a heartbeat."""
    source = tmp_path / "stream.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps({"id": "1", "event": "open", "topic": "t"}),
                json.dumps({"id": "2", "event": "keepalive", "topic": "t"}),
                json.dumps(
                    {
                        "id": "3",
                        "event": "message",
                        "topic": "t",
                        "message": wire(payload("node-a", "green", NOW - 60)),
                    }
                ),
                "this line is not json at all",
            ]
        )
    )
    proc = run(
        None,
        ["node-a"],
        source=str(source),
        extra=[
            "--source-format",
            "stream",
            "--json-out",
            str(tmp_path / "report.json"),
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report_of(proc, tmp_path)["nodes"]["node-a"]["state"] == "ok"


# --- the drill --------------------------------------------------------


def test_drill_the_frozen_may_state_comes_out_red(tmp_path):
    """Level 3 of the fallback test, the evaluator half.

    The two recorded payloads are what the live nodes actually said on
    2026-09-22. The heartbeats are **fresh** — the emitter is running,
    the node is up, the containers read `Up`, the push arrives on time.
    Everything about this looks like operation except the one thing that
    matters.

    A window that passed this would be the four months again.
    """
    lines = [
        wire(RECORDED_NODE_A),
        wire(RECORDED_NODE_B),
    ]
    proc = run(
        lines,
        ["node-a", "node-b"],
        extra=["--json-out", str(tmp_path / "report.json")],
    )
    assert proc.returncode == 1, proc.stdout
    rep = report_of(proc, tmp_path)
    assert rep["verdict"] == "red"
    assert rep["failing_nodes"] == ["node-a", "node-b"]
    for node in ("node-a", "node-b"):
        assert rep["nodes"][node]["state"] == "red"
        assert rep["nodes"][node]["probe_reason"] == "bundle_expired"
        # the heartbeat itself was punctual — this is not a silence case
        assert rep["nodes"][node]["age_seconds"] == 0

    # Negative control on the same fixtures: had the window existed in
    # May, on the day of the bring-up it would have been green. The
    # instrument is not one that always says red.
    may = [
        wire(payload("node-a", "green", 1778830355)),
        wire(payload("node-b", "green", 1778830355)),
    ]
    ok = run(
        may,
        ["node-a", "node-b"],
        now=1778830355 + 600,
        extra=["--json-out", str(tmp_path / "report.json")],
    )
    assert ok.returncode == 0, ok.stdout


def test_report_carries_no_topology(tmp_path):
    """The report is printed into a CI log and pasted into issues."""
    lines = [wire(RECORDED_NODE_A), wire(payload("node-b", "green", NOW - 60))]
    proc = run(lines, ["node-a", "node-b"], extra=["--json-out", str(tmp_path / "report.json")])
    blob = proc.stdout + (tmp_path / "report.json").read_text()
    for needle in ("192.168.", "spiffe://", "join_token", "BEGIN CERTIFICATE"):
        assert needle not in blob, f"leaked {needle!r}"


@pytest.mark.parametrize("verdict,expected", [("green", 0), ("red", 1), ("unmeasurable", 1)])
def test_exit_code_is_the_gate(verdict, expected):
    """The consuming lane keys off the exit code alone, so the mapping is
    pinned here rather than left to the reader of the source."""
    proc = run([wire(payload("node-a", verdict, NOW - 60))], ["node-a"])
    assert proc.returncode == expected


# --- a node that is knowingly not reporting yet -----------------------
#
# Only one of the two federation nodes is being armed. The other is the
# untouched evidence for ADR-0076 and will be rebuilt with the bilateral
# root change, armed as part of that bring-up rather than by an
# intervention before it.
#
# The tempting form is a shorter --expect list. That is exactly the gap
# this instrument exists to close: a roster silently smaller than the
# installation is green on a silence nobody declared. So absence is
# declared, dated and justified instead of omitted.

ABSENCE_REASON = (
    "rebuilt with the bilateral root change per ADR-0076; armed as part of that "
    "bring-up rather than by an intervention before it"
)


def test_known_absent_node_does_not_fail_the_window_before_its_date(tmp_path):
    proc = run(
        [wire(payload("node-a", "green", NOW - 60))],
        ["node-a"],
        extra=[
            "--known-absent",
            f"node-b=2026-12-31={ABSENCE_REASON}",
            "--json-out",
            str(tmp_path / "report.json"),
        ],
    )
    assert proc.returncode == 0, proc.stdout
    rep = report_of(proc, tmp_path)
    assert rep["known_absent_nodes"]["node-b"]["state"] == "known-absent"
    assert rep["known_absent_nodes"]["node-b"]["absent_until"] == "2026-12-31"
    assert rep["failing_nodes"] == []
    # and it is visible, not merely tolerated
    assert "node-b" in proc.stdout


def test_known_absent_turns_red_on_its_date(tmp_path):
    """An absence without an end is a node quietly dropped from the
    roster. The date is what makes it a decision instead of a habit."""
    proc = run(
        [wire(payload("node-a", "green", NOW - 60))],
        ["node-a"],
        extra=[
            "--known-absent",
            f"node-b=2026-09-22={ABSENCE_REASON}",
            "--json-out",
            str(tmp_path / "report.json"),
        ],
    )
    assert proc.returncode == 1, proc.stdout
    rep = report_of(proc, tmp_path)
    assert rep["known_absent_nodes"]["node-b"]["state"] == "absence-expired"
    assert "node-b" in rep["failing_nodes"]


def test_absence_needs_a_reason_long_enough_to_be_one():
    proc = run(
        [wire(payload("node-a", "green", NOW - 60))],
        ["node-a"],
        extra=["--known-absent", "node-b=2026-12-31=later"],
    )
    assert proc.returncode == 2
    assert "shrug" in proc.stdout


def test_absence_needs_a_real_date():
    proc = run(
        [wire(payload("node-a", "green", NOW - 60))],
        ["node-a"],
        extra=["--known-absent", f"node-b=soon={ABSENCE_REASON}"],
    )
    assert proc.returncode == 2
    assert "not an ISO date" in proc.stdout


def test_malformed_absence_entry_is_unmeasurable_never_green():
    proc = run(
        [wire(payload("node-a", "green", NOW - 60))],
        ["node-a"],
        extra=["--known-absent", "node-b"],
    )
    assert proc.returncode == 2


def test_a_node_cannot_be_both_expected_and_absent():
    """A roster that contradicts itself has no answer to give, so it does
    not get to give the convenient one."""
    proc = run(
        [wire(payload("node-a", "green", NOW - 60))],
        ["node-a"],
        extra=["--known-absent", f"node-a=2026-12-31={ABSENCE_REASON}"],
    )
    assert proc.returncode == 2
    assert "contradicts itself" in proc.stdout


def test_a_roster_of_only_absent_nodes_is_still_refused():
    """Declaring every node absent would be the empty --expect list with
    extra steps: a window satisfied by silence."""
    proc = run(
        [],
        [],
        extra=["--known-absent", f"node-b=2026-12-31={ABSENCE_REASON}"],
    )
    assert proc.returncode == 2
    assert "expects no node" in proc.stdout


def test_an_absent_node_that_starts_reporting_is_flagged_not_failed(tmp_path):
    """Good news should not be red. The until-date already forces the
    roster to be revisited, and making a returning node fail as well
    would be the alert fatigue this instrument is meant to avoid."""
    proc = run(
        [
            wire(payload("node-a", "green", NOW - 60)),
            wire(payload("node-b", "green", NOW - 60)),
        ],
        ["node-a"],
        extra=[
            "--known-absent",
            f"node-b=2026-12-31={ABSENCE_REASON}",
            "--json-out",
            str(tmp_path / "report.json"),
        ],
    )
    assert proc.returncode == 0, proc.stdout
    rep = report_of(proc, tmp_path)
    assert rep["known_absent_nodes"]["node-b"]["unexpectedly_present"] is True
    assert "but it is reporting" in proc.stdout
    # and it is not counted as an unexpected label either — it is known,
    # just not expected to speak
    assert rep["unexpected_node_labels"] == []
