<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors -->

# Runbook — the expectation window, and who notices the silence

**Owner:** SRE
**Substrate:**
`scripts/observability/substrate-heartbeat-emit.sh` (node side),
`scripts/observability/substrate-liveness-window.py` (evaluator side)
**Probe:** `scripts/observability/substrate-liveness-probe.sh`, documented
in `docs/observability/substrate-liveness-probe.md`
**Lane:** lives in the private repository, not here — see §6
**Introduced:** 2026-09-22

---

## 1. The shape of the thing

```
  private network                    |  public internet
                                     |
  [node]  probe  -> verdict          |
          emit   -> sign (HMAC)      |
                 -> POST  ------------->  message topic
                                     |         |
                                     |         |  poll every 2 h
                                     |         v
                                     |   expectation window  (scheduled lane)
                                     |         |
                                     |         |  exit != 0
                                     |         v
                                     |   receiver  ->  one de-duplicated issue
```

Nothing crosses right-to-left. The evaluator never touches the private
network, holds no route into it, and needs no credential for it. That is
not an aesthetic preference: three named live-evidence lanes died
because they tried to reach in from outside, and a melder built the same
way would have been the fourth.

## 2. What each half refuses to do

**The emitter sends bad news too.** Green, red and `unmeasurable` all go
on the wire and all exit 0. If it suppressed anything, silence would
carry two meanings — "all well" and "badly broken" — and that ambiguity
is the incident in one word.

**The evaluator treats `unmeasurable` as red.** Wired, not commented. A
probe that could not do its job is not a sign of life. The same rule
applies to the evaluator itself: no key, no topic, an unreachable broker
or an empty `--expect` list all exit 2, never 0.

**An empty expectation list is refused.** A window that expects no node
is satisfied by silence, which is the defect dressed as configuration.

**A forged heartbeat cannot silence the alarm.** Anyone who learns the
topic can post to it, so every message carries HMAC-SHA256 over the exact
probe bytes and anything that does not verify is discarded before its
contents are read. Two tests pin it: a forgery cannot supply a missing
node, and a forgery cannot outrank a genuine red.

**Recency is the probe's own timestamp**, never the broker's arrival
order, so a captured message re-posted today still reads as old.

## 3. Numbers, and where each comes from

| Knob | Value | Derivation |
|---|---|---|
| Probe cadence on the node | 15 min | The measured quantity moves on the hour scale (`default_x509_svid_ttl = "1h"`, read from the live server config). A one-minute cadence is fifteen times the load for no extra resolution. |
| Probe grace (`red` threshold) | 1 h = 1× TTL | SPIRE renews at roughly half the TTL, so red means two consecutive renewal windows were missed — not one hiccup, not one restart. |
| Probe state staleness | 6 h | **Derived, not observed.** See §7. |
| Expectation window | **2 h** | Eight consecutive missed pushes. One lost push — reboot, network blip, a scheduled run GitHub dropped — must not fire. Eight in a row is not chance. |
| Broker lookback | 4× window | Wider than the window on purpose, so a message that arrived *just* outside is seen and judged `stale` rather than not seen at all. Those two are the same verdict but not the same report, and the report is what somebody reads at 9am. |
| Lane cron | every 2 h at :17 | GitHub documents that `schedule` "can be delayed during periods of high loads … some queued jobs may be dropped", and names the start of every hour as a high-load time. :17 is not :00. |

### Why a dropped scheduled run is survivable

A dropped run means the window is not evaluated, so detection is delayed
by up to one cron interval. It does not produce a false green: the
verdict is computed from timestamps inside the heartbeats, not from the
fact that the job ran. The failure direction is *later*, not *wrong*.

## 4. The first state is red, and that is correct

Until the secrets exist and the emitter is deployed, the lane fails with
`unmeasurable: WAKIR_HEARTBEAT_HMAC_KEY is unset or empty`, and the
receiver opens one issue saying so.

That is the intended first state, not a rollout defect. "The melder is
not armed" is a true and actionable statement, it is visible in exactly
the place the real alarm will appear, and the issue closes by itself on
the first green evaluation. The alternative — shipping the lane inert
until somebody remembers to switch it on — is the failure mode this
whole instrument exists to prevent.

## 5. Arming checklist

Each step is owned, and the lane stays red until all of them are done.

1. **Move the pinned runtime SHA** in the lane workflow to the merge
   commit of the runtime pull request. Until then it points at an
   unmerged branch commit. *(SRE)*
2. **Generate the shared key** — 32 bytes, `openssl rand -hex 32`. Place
   it on each node as a file readable only by the emitter's user, and as
   the `WAKIR_HEARTBEAT_HMAC_KEY` secret in the private repository.
   *(Kai — secrets are his domain, Zone H)*
3. **Choose a heartbeat topic** distinct from the alert topic, and set it
   as `WAKIR_NTFY_HEARTBEAT_TOPIC`. Nobody subscribes to it
   interactively: it is polled by the lane. A topic that pushes
   ninety-six notifications a day to a phone is a topic that gets muted.
   *(Kai)*
4. **Install probe, emitter and a 15-minute timer** on each node. The
   emitter needs `WAKIR_SIDE`, `WAKIR_NODE_LABEL`, `WAKIR_NTFY_TOPIC` and
   `WAKIR_HMAC_KEY_FILE`. The node label is an opaque pseudonym and must
   not be the hostname. *(Kai deploys, SRE specifies — Zone H)*
5. **Confirm the expected labels** in the lane match the labels the nodes
   actually send. A mismatch reads as `missing`, which is red — the safe
   direction, but an avoidable morning. *(SRE)*

## 6. Where the lane lives, and why not here

The lane and its issues live in the **private** repository. The
confidentiality directive is about operational statements: "our identity
substrate is not attesting" is a live fact about a running system and
does not belong in a public issue, even with no address in it.

The *tools* are here, in the open, and that is deliberate — they are a
method, not a state. Publishing how we measure discloses nothing;
publishing what we measured would.

Two consequences worth stating:

* The private lane references this repository's composite receiver
  action by SHA rather than copying it. One receiver, one behaviour,
  one place to fix it.
* The receiver's issue body links
  `docs/operations/scheduled-workflow-failure-receiver.md`, a path that
  exists here and not in the private repository. Cosmetic, and named
  here so it is not rediscovered as a bug.

There is one measured reason the private repository is also the
*technically* better host: GitHub disables scheduled workflows after 60
days of inactivity **in public repositories**. A watchdog lane in a repo
nobody commits to would have switched itself off after two months —
which is precisely the failure it was built to catch.

## 7. What is derived rather than observed

The 6-hour state-staleness threshold on the probe is computed from the
measured SVID TTL. It is **not** calibrated against a healthy agent,
because no node has attested since May and therefore no healthy baseline
exists to calibrate against.

**Calibration is owed at the seven-day acceptance run from Strang B**,
and it is recorded — not remembered — in
`docs/observability/substrate-liveness-drill-evidence.json`.

## 8. The fallback drill (level 3), and why it is dated

The test that matters is not "stop the timer and see if anyone notices".
That simulates an *absent* melder. The incident had a **running** melder
and a dead substrate.

**The drill:**

1. Leave everything running. Probe, timer, emitter, containers — all
   normal, node `Up`, heartbeats arriving on time.
2. Point the probe at the frozen May state by setting
   `WAKIR_AGENT_DATA_FILE` to the node's own
   `agent-data.json` — the file is still there on both nodes and *is*
   the originating state, so nothing has to be fabricated.
3. Expect: the heartbeat still arrives and is still punctual, the
   verdict inside it is `red`, the window fails, and the receiver opens
   exactly **one** issue.
4. Restore the environment variable. Expect the issue to close on the
   next green evaluation.

A drill that comes out green did not prove the melder works. It proved
it does not.

The evaluator half of this runs hermetically on every CI pass
(`test_drill_the_frozen_may_state_comes_out_red`, using the two payloads
the live nodes actually emitted on 2026-09-22). The live half is the
procedure above.

**Why it carries a date.** A drill run once, on the day somebody is
proud of the thing, proves it worked that day. That sentence is the May
bilanz: *6/6 PASS* on 2026-05-15 was true and meaningless by 2026-05-17.
So the obligation lives in the evidence file, the dates are compared
against the calendar by
`tests/observability/test_substrate_liveness_drill_obligation.py`, and
a lapse turns a required lane red:

* the seven-day window must start by `activate_by`, otherwise "we have
  not started yet" would be a permanently green answer;
* the first drill is due **eight days** after the window starts;
* it recurs every `recheck_interval_days`, because a fallback test that
  is never repeated decays into documentation of a thing that used to
  work.

## 9. Limits, stated rather than discovered later

* **Nobody is woken up.** The receiver produces an issue. The realistic
  latency is "until somebody reads the issue list" — hours, worst case a
  day or two. For this failure that is enough: the target was never
  *minutes*, it was **not months**. It stops being enough the day the
  substrate carries a pilot customer, and that is a different decision
  with different costs, to be taken before the customer, not after the
  incident.
* **"The cron did not fire at all" is still unwatched.** Same limit the
  receiver names in its own runbook. The named fallback is an external
  dead-man's switch; it was deliberately not built in parallel.
* **The evidence file has no renewal-diff check.** ADR-0075's mechanism
  for lane exemptions diffs the file against the pull-request base so a
  date cannot be quietly moved instead of renewed. This file has no such
  half; a moved date is caught by review, not by tooling. If the file
  outlives the pilot, build it.
* **The emitter is specified here and deployed by Kai** (Zone H). None
  of it is installed on either node today; `systemctl list-timers` shows
  zero Wakir timers on both, measured 2026-09-22.

— Noa
