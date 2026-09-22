# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic vectors for the ADR-0076 acceptance-window judge.

``scripts/acceptance/substrate_acceptance_window.py`` turns a series of
probe samples into the three assurances (Z1..Z3), the anchor assurance
(Z4), the two falsifications (F1, F2), the mandatory negative control
and a coverage statement. This module drives all of them.

What is being defended here
---------------------------

Two properties, and they are the ones the CEO's assignment names:

* **Not-evidence is not green.** Every vector that removes a
  *measurement* must come out ``UNKNOWN`` (exit 2), and every vector
  that breaks the *substrate* must come out ``FAIL`` (exit 1). A vector
  pair exists for each assurance so that the two cannot be conflated by
  a later edit: TV-ACC-W-30..35.
* **The verdict is computed, not read.** A sample that carries a
  verdict-shaped field is refused outright (TV-ACC-W-41), and no code
  path in the judge consults one.

Mutation control: TV-ACC-W-01 asserts that the baseline series is
actually ``PASS``. Without it every red vector below would be
unattributable -- a suite in which everything is red proves only that
something is red.

Negative control on the negative control: TV-ACC-W-24 is the TV-PROV-6
lesson made structural. A negative-control episode during which the
probe itself stopped measuring must come out ``UNKNOWN``, not be
accepted as the required red. A control that removes the state it is
meant to test has not tested it.

Everything is hermetic: samples are dicts, no substrate, no podman, no
network, no clock.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
JUDGE = REPO_ROOT / "scripts" / "acceptance" / "substrate_acceptance_window.py"

SCHEMA = "wakir-runtime/substrate-acceptance-sample@1"

HOUR = 3600
DAY = 24 * HOUR
T0 = 1790000000  # arbitrary, fixed; the judge has no clock of its own

ROOT_ID = "EE7185A994C1FDE23C85B8E8D10D70451EBEE92A"


def signer_id(n: int) -> str:
    """A distinct signing-intermediate identity per rotation generation."""
    return f"{n:040X}"


def sample(
    i: int,
    *,
    side: str = "orbit",
    marker: str | None = None,
    signer_gen: int | None = None,
    chain_authority: str | None = ROOT_ID,
    bundle_ids: list[str] | None = None,
    not_after: int | None = None,
    agent_mtime: int | None = None,
    anchor_ids: list[str] | None = None,
    anchor_mtime: int | None = None,
    svid_status: str = "ok",
    bundle_status: str = "ok",
    agent_data_status: str = "ok",
    anchor_status: str = "ok",
    unmeasured: list | None = None,
) -> dict:
    """One synthetic hourly sample, index ``i`` hours into the window."""
    t = T0 + i * HOUR
    gen = i // 24 if signer_gen is None else signer_gen
    return {
        "schema": SCHEMA,
        "side": side,
        "observed_at_epoch": t,
        "observed_at": f"t+{i:03d}h",
        "marker": marker,
        "svid_status": svid_status,
        "svid_not_before_epoch": t - 60 if svid_status == "ok" else None,
        "svid_not_after_epoch": (
            (t + HOUR if not_after is None else not_after) if svid_status == "ok" else None
        ),
        "svid_chain_len": 2 if svid_status == "ok" else None,
        "svid_chain_authority_id": chain_authority if svid_status == "ok" else None,
        "svid_leaf_authority_id": signer_id(gen) if svid_status == "ok" else None,
        "svid_chain_ids": None,
        "agent_cached_bundle_authority_ids": None,
        "bundle_status": bundle_status,
        "bundle_authority_ids": (
            ([ROOT_ID] if bundle_ids is None else bundle_ids) if bundle_status == "ok" else None
        ),
        "bundle_jwt_kids": None,
        "agent_data_status": agent_data_status,
        "agent_data_mtime_epoch": (
            (t - 120 if agent_mtime is None else agent_mtime) if agent_data_status == "ok" else None
        ),
        "anchor_status": anchor_status,
        "anchor_size_bytes": 716 if anchor_status == "ok" else 0,
        "anchor_mtime_epoch": (
            (t - 300 if anchor_mtime is None else anchor_mtime) if anchor_status == "ok" else None
        ),
        "anchor_authority_ids": (
            ([ROOT_ID] if anchor_ids is None else anchor_ids) if anchor_status == "ok" else None
        ),
        "unmeasured": unmeasured or [],
    }


#: A seven-day series that should pass: hourly samples, the signing
#: intermediate rotates once a day (``ca_ttl = 24h``, ADR-0076 keeps it
#: there on purpose), the expiry moves every hour, the state file moves
#: every hour, and the anchor is re-staged every hour.
#:
#: The two mandated episodes are in it, because a window without them
#: does not pass either: the cold-agent counter-probe (F2, Auflage 2 of
#: the board decision) and the negative control.
def baseline(hours: int = 7 * 24 + 8) -> list[dict]:
    out: list[dict] = []
    # hours 0..168: the standing window
    for i in range(hours):
        out.append(sample(i))
    return out


def with_cold_agent(series: list[dict], stop_h: int = 100, hours_down: int = 26) -> list[dict]:
    """Mark a cold-agent episode: the agent is down and serves nothing."""
    out = []
    frozen_mtime = None
    for s in series:
        i = (s["observed_at_epoch"] - T0) // HOUR
        if i == stop_h:
            s = dict(s, marker="cold-agent-stop")
            frozen_mtime = s["agent_data_mtime_epoch"]
        elif stop_h < i < stop_h + hours_down:
            s = sample(i, svid_status="target_bad_workload_api_no_response",
                       agent_mtime=frozen_mtime)
        elif i == stop_h + hours_down:
            s = sample(i, marker="cold-agent-start", agent_mtime=frozen_mtime)
        out.append(s)
    return out


def with_negative_control(series: list[dict], start_h: int = 150, hours: int = 2) -> list[dict]:
    """Mark a negative control: the ``bundles`` volume is emptied."""
    out = []
    for s in series:
        i = (s["observed_at_epoch"] - T0) // HOUR
        if i == start_h:
            s = sample(i, marker="negative-control-start", anchor_status="target_bad_anchor_absent")
        elif start_h < i < start_h + hours:
            s = sample(i, anchor_status="target_bad_anchor_absent")
        elif i == start_h + hours:
            s = sample(i, marker="negative-control-end", anchor_status="target_bad_anchor_absent")
        out.append(s)
    return out


def full_window() -> list[dict]:
    return with_negative_control(with_cold_agent(baseline()))


def run(tmp_path: Path, series: list[dict], *, extra: list[str] | None = None, raw: str | None = None):
    log = tmp_path / "samples.ndjson"
    if raw is not None:
        log.write_text(raw, encoding="utf-8")
    else:
        log.write_text("".join(json.dumps(s) + "\n" for s in series), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(JUDGE), "--samples", str(log), "--json", *(extra or [])],
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"verdict": None, "stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, payload


def state_of(payload: dict, prefix: str) -> str:
    for j in payload["judgements"]:
        if j["name"].startswith(prefix):
            return j["state"]
    raise AssertionError(f"no judgement named {prefix!r} in {[j['name'] for j in payload['judgements']]}")


# --------------------------------------------------------- mutation control


def test_tv_acc_w_01_baseline_window_passes(tmp_path):
    """TV-ACC-W-01 (mutation control). The healthy window is green.

    Every red vector below is attributable only because this one is
    green. A suite in which everything fails has measured nothing.
    """
    rc, payload = run(tmp_path, full_window())
    assert payload["verdict"] == "PASS", json.dumps(payload, indent=2)
    assert rc == 0


def test_tv_acc_w_02_every_judgement_reports_a_state(tmp_path):
    """TV-ACC-W-02. All eight judgements are present and each is one of three states."""
    _, payload = run(tmp_path, full_window())
    names = [j["name"] for j in payload["judgements"]]
    assert len(names) == 8, names
    for j in payload["judgements"]:
        assert j["state"] in {"PASS", "FAIL", "UNKNOWN"}


# ------------------------------------------------------------ Z1 red / grey


def test_tv_acc_w_10_z1_pruned_root_is_fail(tmp_path):
    """TV-ACC-W-10. The SVID chains to an authority the server no longer holds.

    This is the May state with the diagnosis attached: the agent was
    alive against a root that had been pruned a day after it was minted.
    """
    series = full_window()
    series[40] = sample(40, chain_authority="AA" * 20)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z1") == "FAIL"
    assert payload["verdict"] == "FAIL"
    assert rc == 1


def test_tv_acc_w_11_z1_unmeasured_is_unknown_not_pass(tmp_path):
    """TV-ACC-W-11. A sample the probe could not take is UNKNOWN, never PASS."""
    series = full_window()
    series[40] = sample(
        40, svid_status="unmeasured", unmeasured=[{"field": "svid", "reason": "podman_absent"}]
    )
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z1") == "UNKNOWN"
    assert payload["verdict"] == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_12_z1_unknown_status_word_is_unknown(tmp_path):
    """TV-ACC-W-12. A status this reader does not know is UNKNOWN, not PASS and not FAIL.

    The vocabulary is closed on purpose. If the probe grows a fifth
    answer, the reader must stop rather than guess which of the four it
    resembles -- guessing at an unknown shape is how a reader ends up
    reporting a default as a measurement.
    """
    series = full_window()
    series[40] = dict(sample(40), svid_status="probably_fine")
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z1") == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_13_no_svid_served_is_fail_not_unknown(tmp_path):
    """TV-ACC-W-13. The Workload API answering with nothing is measured, and bad."""
    series = full_window()
    series[40] = sample(40, svid_status="target_bad_no_svid_in_response")
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z1") == "FAIL"
    assert rc == 1


# ------------------------------------------------------------ Z2, the core


def test_tv_acc_w_20_frozen_expiry_is_fail(tmp_path):
    """TV-ACC-W-20. A credential that never moves is a cache.

    This is the assurance ADR-0076 rests on. A substrate that is up,
    healthy-looking and serving the same certificate for a week is the
    exact thing seven days of green were unable to tell apart in May.
    """
    series = [sample(i, not_after=T0 + HOUR) for i in range(7 * 24 + 8)]
    series = with_negative_control(with_cold_agent(series))
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z2") == "FAIL"
    assert rc == 1


def test_tv_acc_w_21_stall_beyond_tolerance_is_fail(tmp_path):
    """TV-ACC-W-21. A stall longer than TTL + one sampling interval is red."""
    series = full_window()
    frozen = series[30]["svid_not_after_epoch"]
    for i in range(30, 40):
        series[i] = sample(i, not_after=frozen)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z2") == "FAIL"
    assert rc == 1


def test_tv_acc_w_22_expiry_going_backwards_is_fail(tmp_path):
    """TV-ACC-W-22. An expiry that moves backwards is a replaced-by-older identity."""
    series = full_window()
    series[40] = sample(40, not_after=T0)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z2") == "FAIL"
    assert rc == 1


def test_tv_acc_w_23_one_renewal_per_ttl_is_pass(tmp_path):
    """TV-ACC-W-23. Renewal at the documented cadence is not red.

    Guards the tolerance from the other side: a check that fires on
    healthy behaviour gets switched off, and then it is a check that
    does not run.
    """
    _, payload = run(tmp_path, full_window())
    assert state_of(payload, "Z2") == "PASS"


def test_tv_acc_w_24_z2_unmeasured_is_unknown(tmp_path):
    """TV-ACC-W-24. A missing expiry is UNKNOWN, not a pass and not a stall."""
    series = full_window()
    for i in range(20, 60):
        series[i] = dict(sample(i), svid_not_after_epoch=None)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z2") == "UNKNOWN"
    assert rc == 2


# ---------------------------------------------------------------------- Z3


def test_tv_acc_w_30_static_state_file_is_fail(tmp_path):
    """TV-ACC-W-30. The number that stood still for four months, standing still."""
    series = [sample(i, agent_mtime=T0) for i in range(7 * 24 + 8)]
    series = with_negative_control(with_cold_agent(series))
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z3") == "FAIL"
    assert rc == 1


def test_tv_acc_w_31_absent_state_file_is_fail(tmp_path):
    """TV-ACC-W-31. No state file at all is measured, and bad."""
    series = full_window()
    series[40] = sample(40, agent_data_status="target_bad_agent_data_absent")
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z3") == "FAIL"
    assert rc == 1


def test_tv_acc_w_32_unmeasured_state_file_is_unknown(tmp_path):
    """TV-ACC-W-32. The pair to TV-ACC-W-31: not measured is not bad."""
    series = full_window()
    for i in range(20, 60):
        series[i] = sample(
            i,
            agent_data_status="unmeasured",
            unmeasured=[{"field": "agent_data_mtime", "reason": "agent_data_volume_absent"}],
        )
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z3") == "UNKNOWN"
    assert rc == 2


# ---------------------------------------------------- Z4, the staged anchor


def test_tv_acc_w_40_missing_anchor_is_fail(tmp_path):
    """TV-ACC-W-40. The prescribed negative control, applied to the whole window.

    ADR-0076: *"Ein Lauf mit geleertem bundles-Volume muss rot werden."*
    This is that run. It is red because of Z4 and only because of Z4 --
    Z1, Z2 and Z3 stay green throughout, since a running agent keeps
    serving from its cache when the anchor is deleted. That is the
    reason Z4 exists at all.
    """
    series = [sample(i, anchor_status="target_bad_anchor_absent") for i in range(7 * 24 + 8)]
    series = with_cold_agent(series)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z4") == "FAIL"
    assert payload["verdict"] == "FAIL"
    assert rc == 1


def test_tv_acc_w_41_anchor_disjoint_from_bundle_is_fail(tmp_path):
    """TV-ACC-W-41. A staged file at the right path holding the wrong authorities.

    ADR-0076 context (c): the in-tree bundle CLIs produce well-formed
    JWKS that are *"NOT cryptographically valid SPIRE-CA-keys"*. Wired
    into the staging path they would give a file, a green existence
    check and a cold agent that still cannot bootstrap. Existence is
    not the assurance; overlap with the authorities the server actually
    holds is.
    """
    series = full_window()
    for i in range(20, 60):
        series[i] = sample(i, anchor_ids=["BB" * 20])
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z4") == "FAIL"
    assert rc == 1


def test_tv_acc_w_42_stale_restaging_timer_is_fail(tmp_path):
    """TV-ACC-W-42. The re-staging timer stopped and nobody would have noticed.

    ADR-0076 names this risk in as many words: *"Der Re-Staging-Timer
    wird eine weitere stille Pflicht. Er muss Teil der Sonde aus der
    Abnahme sein, sonst wiederholt sich die Klasse."*
    """
    series = full_window()
    for i in range(20, 60):
        series[i] = sample(i, anchor_mtime=T0)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z4") == "FAIL"
    assert rc == 1


def test_tv_acc_w_43_unmeasured_anchor_is_unknown(tmp_path):
    """TV-ACC-W-43. The pair to TV-ACC-W-40."""
    series = full_window()
    for i in range(20, 60):
        series[i] = sample(
            i,
            anchor_status="unmeasured",
            unmeasured=[{"field": "anchor", "reason": "bundles_volume_absent"}],
        )
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z4") == "UNKNOWN"
    assert rc == 2


# ---------------------------------------------------------------------- F1


def test_tv_acc_w_50_too_few_rotations_is_fail(tmp_path):
    """TV-ACC-W-50. Seven days in which nothing happened is not a passed window.

    ADR-0076 F1: *"sieben Tage ohne beobachtete Rotation sind kein
    bestandenes Fenster."* The window is not a waiting period; it is six
    executions of the operation that killed the substrate, watched.
    """
    series = [sample(i, signer_gen=0) for i in range(7 * 24 + 8)]
    series = with_negative_control(with_cold_agent(series))
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "F1") == "FAIL"
    assert rc == 1


def test_tv_acc_w_51_rotation_not_survived_is_fail(tmp_path):
    """TV-ACC-W-51. A rotation happened and the SVID after it does not chain to the bundle."""
    series = full_window()
    series[48] = sample(48, signer_gen=99, chain_authority="CC" * 20)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "F1") == "FAIL"
    assert rc == 1


def test_tv_acc_w_52_rotation_count_is_reported(tmp_path):
    """TV-ACC-W-52. The counter is visible, and the bundle-set counter next to it.

    Under ``UpstreamAuthority "disk"`` the root stands still by design,
    so the bundle-set transition count is expected to read 0 and is
    reported rather than gated on. Gating on it would demand an event
    the chosen configuration forbids.
    """
    _, payload = run(tmp_path, full_window())
    f1 = next(j for j in payload["judgements"] if j["name"].startswith("F1"))
    assert f1["observations"]["signing_authority_rotations"] >= 6
    assert f1["observations"]["bundle_authority_set_transitions"] == 0
    assert f1["state"] == "PASS"


# ---------------------------------------------------------------------- F2


def test_tv_acc_w_60_no_cold_agent_probe_is_unknown(tmp_path):
    """TV-ACC-W-60. A window without the counter-probe is not a passed window.

    Board decision, Auflage 2: the cold-agent probe stays in even though
    it turns the substrate red once. Leaving it out is not a way to get
    a greener window, it is a way to get no window.
    """
    rc, payload = run(tmp_path, with_negative_control(baseline()))
    assert state_of(payload, "F2") == "UNKNOWN"
    assert payload["verdict"] == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_61_restart_inside_the_overlap_is_fail(tmp_path):
    """TV-ACC-W-61. A restart inside the CA overlap tests nothing."""
    series = with_negative_control(with_cold_agent(baseline(), hours_down=2))
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "F2") == "FAIL"
    assert rc == 1


def test_tv_acc_w_62_returning_with_the_old_credential_is_fail(tmp_path):
    """TV-ACC-W-62. Coming back is not enough; coming back with a *new* credential is.

    An agent that restarts and re-serves the certificate it had before
    has demonstrated a cache, not a bootstrap.
    """
    series = with_negative_control(with_cold_agent(baseline()))
    stale = series[100]["svid_not_after_epoch"]
    for i in range(126, 132):
        series[i] = dict(series[i], svid_not_after_epoch=stale)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "F2") == "FAIL"
    assert rc == 1


def test_tv_acc_w_63_volume_touched_while_down_is_fail(tmp_path):
    """TV-ACC-W-63. The one hand-on-the-volume the judge can actually see.

    ADR-0076 requires the restart to happen *"ohne jedes Anfassen der
    Volumes"*. Whether anything else on the node was touched is not
    knowable from the samples and is an operator obligation in the test
    plan, not an assertion here. The agent's own state file moving while
    the agent is stopped, however, is measurable, and it means somebody
    helped.
    """
    series = with_negative_control(with_cold_agent(baseline()))
    idx = next(i for i, s in enumerate(series) if s["marker"] == "cold-agent-start")
    series[idx] = dict(series[idx], agent_data_mtime_epoch=series[idx]["observed_at_epoch"])
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "F2") == "FAIL"
    assert rc == 1


def test_tv_acc_w_64_cold_agent_episode_does_not_redden_the_standing_assurances(tmp_path):
    """TV-ACC-W-64. The deliberate outage is judged by F2 and excluded from Z1..Z4.

    Otherwise the window could only pass by skipping the falsification
    the board insisted on -- abnahme and expectation would contradict
    each other, which is exactly the conflict ADR-0076 A3 raises.
    """
    _, payload = run(tmp_path, full_window())
    for prefix in ("Z1", "Z2", "Z3", "Z4"):
        assert state_of(payload, prefix) == "PASS"
    assert state_of(payload, "F2") == "PASS"


# --------------------------------------------------- the negative control


def test_tv_acc_w_70_missing_negative_control_is_unknown(tmp_path):
    """TV-ACC-W-70. No negative control, no green.

    ADR-0076: *"Wird er das nicht, ist auch das grüne Ergebnis nichts
    wert."* Not performing it is the same position as performing it and
    watching it stay green.
    """
    rc, payload = run(tmp_path, with_cold_agent(baseline()))
    assert state_of(payload, "NC") == "UNKNOWN"
    assert payload["verdict"] == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_71_negative_control_that_stays_green_fails_the_window(tmp_path):
    """TV-ACC-W-71. The control was run, the anchor was not actually removed, the window falls.

    This is the vector that makes the mechanism worth having. A control
    that comes out green says the instrument cannot detect the thing it
    was built to detect, and therefore the green window says nothing
    either.
    """
    series = with_cold_agent(baseline())
    out = []
    for s in series:
        i = (s["observed_at_epoch"] - T0) // HOUR
        if i == 150:
            s = sample(i, marker="negative-control-start")
        elif i == 152:
            s = sample(i, marker="negative-control-end")
        out.append(s)
    rc, payload = run(tmp_path, out)
    assert state_of(payload, "NC") == "FAIL"
    assert payload["verdict"] == "FAIL"
    assert rc == 1


def test_tv_acc_w_72_negative_control_that_killed_the_probe_is_unknown(tmp_path):
    """TV-ACC-W-72. The TV-PROV-6 lesson, in the control itself.

    If the probe stopped measuring during the control, the slice is not
    green -- but it is not the required red either. Accepting "not
    green" as "red" would mean a control that took out its own
    instrument counted as a successful control. The rule from
    2026-09-22 applies to the control as much as to anything else: a
    negative control must not remove the state it is supposed to test.
    """
    series = with_cold_agent(baseline())
    out = []
    for s in series:
        i = (s["observed_at_epoch"] - T0) // HOUR
        if 150 <= i <= 152:
            s = sample(
                i,
                marker=(
                    "negative-control-start"
                    if i == 150
                    else "negative-control-end" if i == 152 else None
                ),
                svid_status="unmeasured",
                bundle_status="unmeasured",
                agent_data_status="unmeasured",
                anchor_status="unmeasured",
                unmeasured=[{"field": "tooling", "reason": "missing_tool_openssl"}],
            )
        out.append(s)
    rc, payload = run(tmp_path, out)
    assert state_of(payload, "NC") == "UNKNOWN"
    assert payload["verdict"] == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_73_negative_control_does_not_redden_the_window(tmp_path):
    """TV-ACC-W-73. A control that did its job leaves the window green."""
    _, payload = run(tmp_path, full_window())
    assert state_of(payload, "NC") == "PASS"
    assert payload["verdict"] == "PASS"


# ------------------------------------------------------------- the reader


def test_tv_acc_w_80_sample_carrying_a_verdict_is_refused(tmp_path):
    """TV-ACC-W-80. The judgement is computed here; a sample with an opinion is not read.

    The defect class this house found twice on 2026-09-22 -- reading a
    conclusion off a field written by the thing under observation --
    made structural rather than commented on.
    """
    series = full_window()
    series[40] = dict(sample(40), verdict="green")
    rc, payload = run(tmp_path, series)
    assert rc == 2
    assert "sample_carries_a_verdict" in json.dumps(payload)


def test_tv_acc_w_81_unknown_schema_is_refused(tmp_path):
    """TV-ACC-W-81. A record shape the reader does not understand is not re-interpreted."""
    series = full_window()
    series[40] = dict(sample(40), schema="wakir-runtime/substrate-acceptance-sample@99")
    rc, payload = run(tmp_path, series)
    assert rc == 2
    assert "schema" in json.dumps(payload)


def test_tv_acc_w_82_unparseable_line_is_not_skipped(tmp_path):
    """TV-ACC-W-82. A hole stepped over silently is indistinguishable from no hole."""
    good = "".join(json.dumps(s) + "\n" for s in full_window())
    rc, payload = run(tmp_path, [], raw=good + "{this is not json}\n")
    assert rc == 2
    assert "not JSON" in json.dumps(payload)


def test_tv_acc_w_83_two_sides_in_one_log_is_refused(tmp_path):
    """TV-ACC-W-83. A window is a statement about one substrate."""
    series = full_window() + [sample(200, side="wakir")]
    rc, payload = run(tmp_path, series)
    assert rc == 2
    assert "more than one side" in json.dumps(payload)


def test_tv_acc_w_84_empty_log_is_unknown_not_pass(tmp_path):
    """TV-ACC-W-84. No samples at all is the strongest form of not-evidence."""
    rc, payload = run(tmp_path, [])
    assert rc == 2
    assert payload["verdict"] == "UNKNOWN"


# ------------------------------------------------------------- coverage


def test_tv_acc_w_90_short_window_is_unknown(tmp_path):
    """TV-ACC-W-90. A window that is not over yet does not pass early.

    The series is otherwise the green one; only the required length is
    raised. Everything else stays PASS, which is the point: coverage is
    an independent reason to withhold a verdict, not a side effect of
    some other assurance going grey.
    """
    rc, payload = run(tmp_path, full_window(), extra=["--window-seconds", str(14 * DAY)])
    assert state_of(payload, "C ") == "UNKNOWN"
    assert state_of(payload, "Z2") == "PASS"
    assert payload["verdict"] == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_91_unexplained_gap_is_unknown(tmp_path):
    """TV-ACC-W-91. A stretch nobody watched is a stretch nothing is claimed about."""
    series = [s for s in full_window() if not (60 <= (s["observed_at_epoch"] - T0) // HOUR <= 70)]
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "C ") == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_92_open_episode_is_unknown(tmp_path):
    """TV-ACC-W-92. An exclusion that was opened and never closed swallows the rest of the series.

    It has to be loud, because the quiet version of this bug excludes
    everything after it and reports PASS on an empty set.
    """
    series = full_window()
    idx = next(i for i, s in enumerate(series) if s["marker"] == "cold-agent-start")
    series[idx] = dict(series[idx], marker=None)
    rc, payload = run(tmp_path, series)
    assert payload["verdict"] == "UNKNOWN"
    assert "never closed" in json.dumps(payload)
    assert rc == 2


def test_tv_acc_w_93_fail_outranks_unknown(tmp_path):
    """TV-ACC-W-93. A gap must not mask a measured defect.

    The fold is deliberately conservative in this direction: if part of
    the series is missing and the part that exists shows a real failure,
    the failure is the answer.
    """
    series = full_window()
    series[40] = sample(40, chain_authority="AA" * 20)          # measured and bad
    series[41] = sample(41, svid_status="unmeasured")            # not measured
    rc, payload = run(tmp_path, series)
    assert payload["verdict"] == "FAIL"
    assert rc == 1


def test_tv_acc_w_94_reader_refuses_a_missing_log(tmp_path):
    """TV-ACC-W-94. The judge that cannot read its own input exits 2, never 0."""
    proc = subprocess.run(
        [sys.executable, str(JUDGE), "--samples", str(tmp_path / "nope.ndjson"), "--json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2


# ----------------------------------------------- the non-evidence surfaces


NON_EVIDENCE_TOKENS = (
    "podman inspect",
    "RestartCount",
    ".State.Health",
    "healthcheck",
    "podman logs",
    "journalctl",
    "podman ps",
)


def test_tv_acc_w_95_judge_reads_none_of_the_forbidden_surfaces():
    """TV-ACC-W-95. ADR-0076's non-evidence list, enforced instead of quoted.

    Podman health state, container uptime and server logs are excluded
    by the decision because all three were true and worthless for 127
    days. A prohibition that lives only in a comment is the same class
    of instrument as a healthcheck that never runs.
    """
    text = JUDGE.read_text(encoding="utf-8")
    body = text.split('"""', 2)[-1]
    for token in NON_EVIDENCE_TOKENS:
        assert token not in body, f"{JUDGE.name} refers to non-evidence surface {token!r}"


@pytest.mark.parametrize("prefix", ["Z1", "Z2", "Z3", "Z4", "F1", "F2", "NC", "C "])
def test_tv_acc_w_96_every_assurance_has_a_red_and_a_grey_path(tmp_path, prefix):
    """TV-ACC-W-96. Each assurance can reach all three states.

    Not a tautology check: an assurance that can only ever be PASS or
    UNKNOWN cannot fail, and one that can only be PASS or FAIL has
    collapsed the very distinction this harness is for.
    """
    source = JUDGE.read_text(encoding="utf-8")
    assert "violations.append" in source
    assert "gaps.append" in source
    _, payload = run(tmp_path, full_window())
    assert state_of(payload, prefix) == "PASS"


def test_tv_acc_w_97_ok_status_with_a_missing_value_is_unknown(tmp_path):
    """TV-ACC-W-97. A source that reported ``ok`` and then handed over nothing.

    The narrow case ``require_measured`` exists for: the status says the
    source answered, and the field it should have filled is null. That
    is a probe bug, not a substrate finding, and it has to come out
    UNKNOWN rather than crash or pass. Without this vector the one line
    that separates "not measured" from "measured and bad" is only
    exercised through Z2.
    """
    series = full_window()
    for i in range(20, 60):
        series[i] = dict(sample(i), svid_chain_authority_id=None)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z1") == "UNKNOWN"
    assert payload["verdict"] == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_98_ok_anchor_with_a_missing_authority_list_is_unknown(tmp_path):
    """TV-ACC-W-98. The same narrow case on the anchor assurance."""
    series = full_window()
    for i in range(20, 60):
        series[i] = dict(sample(i), anchor_authority_ids=None)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z4") == "UNKNOWN"
    assert rc == 2


def test_tv_acc_w_99_ok_agent_data_with_a_missing_mtime_is_unknown(tmp_path):
    """TV-ACC-W-99. And on Z3, so all four assurances carry the pair."""
    series = full_window()
    for i in range(20, 60):
        series[i] = dict(sample(i), agent_data_mtime_epoch=None)
    rc, payload = run(tmp_path, series)
    assert state_of(payload, "Z3") == "UNKNOWN"
    assert rc == 2
