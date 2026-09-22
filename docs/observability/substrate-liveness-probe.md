<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors -->

# Substrate liveness probe — does this SPIRE agent still attest?

**Owner:** SRE
**Substrate:** `scripts/observability/substrate-liveness-probe.sh`
**Tests:** `tests/observability/test_substrate_liveness_probe.py`
**Introduced:** 2026-09-22
**Status:** probe merged; transport and receiver are an open decision
(see §6)

---

## 1. The finding this probe answers

On 2026-09-21/22 the first Operator-Hand live run measured two
federation nodes that had not attested since May. The agents had been
in a restart loop for about 127 days. Nothing reported it.

What makes this worth a dedicated instrument is not that it broke. It
is that every cheap signal a monitor would reasonably have used was
**true** the whole time. Measured read-only on both nodes,
2026-09-22 ~08:15 UTC:

| Signal | Reading | Worth |
|---|---|---|
| container state | `Up` | true for four months, agent never attested |
| container uptime | seconds — the unit is recreated constantly | looks like a fresh healthy start |
| `podman inspect .RestartCount` | `0` | systemd recreates the container, so podman never counts a restart |
| workload-API socket file present | yes, dated May | stale inode; nothing listening |
| server container health | `unhealthy`, `FailingStreak` 636 | correct, and read by nobody |
| persisted agent SVID `notAfter` | node A `2026-05-15T08:32:35Z`, node B `2026-05-17T04:59:19Z` | **unambiguous** |

The last row is the probe.

## 2. What it measures

`<agent data_dir>/agent-data.json` is the agent's persisted state.
Two fields are load-bearing:

* `.svid` — base64-wrapped PEM of the agent SVID. Its `notAfter` is
  the hard end of the last successful attestation. Measured
  `notBefore..notAfter` span is 1h00m10s, consistent with the server's
  measured `default_x509_svid_ttl = "1h"`.
* `.bundle` — the trust bundle as the agent cached it. The newest
  `notAfter` in it is the point past which the agent can no longer
  verify the server, i.e. the point of no return without an operator.

The file's **mtime** is read as an independent second opinion, not as
the primary signal. `keys.json` in the same directory was rewritten on
2026-09-21 by a bootstrap re-run while `agent-data.json` kept its May
timestamp. A watcher on the directory, or on the wrong file in it,
would have reported freshness.

Deliberately **not** read: container state, restart count, socket-file
existence — see the table above — and the SPIFFE ID in the SVID's SAN,
because it embeds the join-token UUID and must not leave the node.

## 3. Contract

One JSON object on stdout. Exit code:

| Exit | Verdict | Meaning |
|---|---|---|
| 0 | `green` | SVID and bundle valid, state file fresh |
| 1 | `red` | measured, and it is bad |
| 2 | `unmeasurable` | could not measure |

**Exit 2 is not exit 0.** A probe that cannot measure must not report
green. Missing tool, missing target, undecodable SVID and a state file
of the wrong shape all land on 2, each with its own `reason`.

Reason codes: `ok`, `bundle_expired`, `svid_expired`, `state_stale`,
`state_missing`, `bundle_absent`, `svid_absent`, `svid_undecodable`,
`state_unparseable`, `state_empty`, `state_unreadable`,
`state_mtime_unreadable`, `no_state_file_and_no_side`, `podman_absent`,
`agent_data_volume_absent`, `missing_tool_<tool>`.

`bundle_expired` outranks `svid_expired` when both hold: an expired
SVID can still be renewed, an expired cached bundle cannot be
recovered from by the agent alone.

## 4. Thresholds, and why these numbers

| Knob | Default | Derivation |
|---|---|---|
| `WAKIR_SVID_TTL_SECONDS` | 3600 | measured `default_x509_svid_ttl = "1h"` in the live server config |
| `WAKIR_GRACE_SECONDS` | 3600 | one full TTL. SPIRE renews at roughly half the TTL, so red means at least two consecutive renewal windows were missed — not one hiccup, not one restart. |
| `WAKIR_STATE_MAX_AGE_SECONDS` | 21600 (6 h) | six missed renewal windows on the second, independent signal. Loose enough that a maintenance restart does not fire it; far below anything that could hide a four-month outage. |

Both directions are under test. The negative control
(`test_svid_expired_inside_grace_stays_green`) asserts that an SVID
expired for 50 minutes stays green — alert fatigue is a reliability
risk, not a style question.

## 5. Running it

```bash
# On the substrate node, resolving the volume itself:
WAKIR_SIDE=<side> WAKIR_NODE_LABEL=node-a \
  bash scripts/observability/substrate-liveness-probe.sh

# Against an explicit state file (this is also what the tests do,
# and it is the mode in which podman is never invoked):
WAKIR_AGENT_DATA_FILE=/path/to/agent-data.json \
  bash scripts/observability/substrate-liveness-probe.sh
```

Dependencies: `bash`, `openssl`, `base64`, `stat`, `date`, `sed`, `tr`.
No `jq`, no `python`. Both nodes run Fedora CoreOS 44 and have **no
python3 at all** (measured 2026-09-22); the repo's existing systemd
health units invoke `/opt/wakir-runtime/.venv/bin/python3`, a path that
exists on neither node. A probe whose job is to notice that something
does not run must not itself be unable to run. The absence of `python`
and `jq` from the executable lines is asserted by a test, not by
review.

### Verification against the incident it exists for

`test_regression_the_incident_this_probe_exists_for` replays the exact
measured state of node A — SVID `notAfter 2026-05-15T08:32:35Z`,
newest bundle cert a day earlier, state mtime `1778830355` — evaluated
at the moment of the live measurement, and asserts `red` on the first
sample with the age in days in range. The same test asserts the other
half: on the day of the May bring-up that same state reads `green`.
The May report of *6/6 PASS* was not wrong, it was early. This probe
is what gives such a statement a shelf life.

The probe was additionally executed against both live nodes on
2026-09-22 08:24 UTC, piped over stdin so that nothing was installed
and nothing written:

| Node | Verdict | Reason | SVID expired for | Bundle certs |
|---|---|---|---|---|
| A | `red`, exit 1 | `bundle_expired` | 11 231 530 s ≈ 130.0 d | 3 |
| B | `red`, exit 1 | `bundle_expired` | 11 071 526 s ≈ 128.1 d | 4 |

## 6. What this is not

This probe **produces a verdict; it does not deliver it.** Transport,
dead-man's window, receiver and escalation latency are a separate
decision that is open at the time of writing and tracked outside this
repository.

Stated so it is not discovered later:

* A probe that nobody runs is exactly the class of defect it was
  written against. Until a timer runs it and something notices its
  silence, the probe changes nothing.
* The receiver in `docs/operations/scheduled-workflow-failure-receiver.md`
  covers scheduled GitHub-Actions lanes. It cannot reach a node on a
  private network and does not try to. This probe runs on the other
  side of that boundary; connecting the two is the open decision.
* The payload is designed to travel over a push channel: it carries no
  hostname, no address, no SPIFFE ID and no key material, and the node
  is identified only by a caller-supplied opaque label. A test asserts
  this and pins the exact field set, so a later field addition has to
  pass that assertion deliberately.

— Noa
