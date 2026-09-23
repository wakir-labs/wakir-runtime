<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# ADR-0076 — Seven-Day Acceptance Window: Test Plan

| Field | Value |
|---|---|
| Owner | QA engineering |
| Date drafted | 2026-09-22 |
| Decision | `decisions/0076-trust-anker-spire-upstream-ca.md` (approved 2026-09-22) |
| Specification | CTO decision paper §6, `agents-workspaces/cto/outbox/2026-09-22-trust-anker-entscheid.md` |
| Implements | Umsetzungsschnitt step 8 |
| Depends on | umsetzungsschnitt steps 0–4 (reachability, `UpstreamAuthority`, root material, anchor staging, re-staging timer) — deployment ownership |
| Status | built and hermetically proven; **not armed**. The window starts after the bilateral cutover, which is operator hand |

---

## 0. What this plan is answering

*Smoke 6/6* on 2026-05-15 was correct and worthless. It could not tell a
working substrate from a freshly filled cache, because at the moment of
the measurement the two are identical. The substrate then stopped
attesting within about 48 hours and stayed dead for 127 days while every
cheap signal stayed green.

The distinction is not in any state. It is only in **movement**: does the
agent renew its credential, against an authority the server currently
holds. That is measurable only over time, and only if somebody writes
down what was true each hour and computes the answer afterwards.

Two rules run through everything below.

**Not-evidence is not green.** Every judgement has three outcomes, never
two. A measurement that did not happen ends as `UNKNOWN` and exit 2. It
is not a pass, and it may not be quoted as one.

**The verdict is computed, never read.** The sample record carries
measurements and no opinion. A record that grows a verdict-shaped field
is refused outright.

---

## 1. The instrument

Two pieces, split along the line where the node ends.

| Piece | Where it runs | What it does |
|---|---|---|
| `scripts/acceptance/substrate-acceptance-probe.sh` | on the node, hourly, as root | takes one sample, appends one NDJSON line, judges nothing |
| `scripts/acceptance/substrate_acceptance_window.py` | off the node | reads the series, computes every judgement, prints the verdict |

The split is forced, not stylistic. Both live VMs run Fedora CoreOS with
**no python3 at all** (measured 2026-09-22), so anything that runs on the
node is bash over `openssl`, `od`, `dd`, `stat`, `base64`, `date`, `sed`,
`grep`, `tr`, `sort`. And a per-run verdict would have to answer from one
sample a question only the series can answer — which is how May's
evidence was produced.

Deployment: `scripts/systemd/wakir-substrate-acceptance-probe@.service`
and the matching `.timer`, instanced per side. Installed and enabled by
operator hand at the start of the window, stopped at the end. It is
deliberately not wired into the bootstrap: the window is a dated
measurement, not a standing service.

### 1.1 What the sample contains

Per side, per hour, with a timestamp:

1. **the current X509-SVID** — `spire-agent api fetch x509 -output json`
   inside the agent container. Recorded: not-before, not-after, chain
   length, the Subject Key Identifiers along the chain, the authority
   the chain terminates at, and the authority that signed the leaf.
2. **the server's current authority set** — `spire-server bundle show
   -format spiffe` inside the server container, reduced to the Subject
   Key Identifier of each X.509 authority.
3. **the mtime of `agent-data.json`** in the agent data volume.
4. **the staged bootstrap anchor** in the bundles volume: presence,
   size, mtime, and the authority set inside it.

Item 4 is not in §6.1. See §3.

### 1.2 Why key identifiers and not `kid`

The SPIFFE bundle format defines `x5c` for `use=x509-svid` entries and
does not define `kid` for them
(`standards/SPIFFE_Trust_Domain_and_Bundle.md` §4.2, retrieved
2026-09-22). The identifier that exists on both sides of the comparison
is therefore the certificate's Subject Key Identifier — and an SVID names
exactly that value in its issuer's Authority Key Identifier. That is what
makes Z1 a set-membership test between comparable identifiers rather than
a name match.

### 1.3 Why the top of the chain and not the leaf's issuer

Under `UpstreamAuthority "disk"` the chain the Workload API hands over is
leaf + intermediate, and the bundle holds the long-lived root. The leaf's
own issuer is the intermediate and is legitimately **absent** from the
bundle. A probe that compared the leaf's issuer against the bundle would
read red every hour on a perfectly healthy substrate. The comparison is
made on the authority the **top of the chain** names. Under a self-signed
server the chain is the leaf alone and the two readings coincide; both
topologies carry a test vector (TV-ACC-P-01, TV-ACC-P-02).

### 1.4 What never leaves the node

The sample log is read off the node to be judged, so it carries no
hostname, no address, no SPIFFE ID and no certificate. The side is an
opaque label; identities are key identifiers. The SVID **private key** is
in the Workload API response (`x509_svid_key`) and is extracted nowhere,
logged nowhere and written nowhere — which is also why `-output json` is
used rather than `-write`, since `-write` puts `svid.0.key` into a volume
that persona containers mount. TV-ACC-P-10 asserts this with a canary.

---

## 2. The three assurances

| | Statement | Red when | Grey when |
|---|---|---|---|
| **Z1** | the authority the SVID chain terminates at is an element of the **current** server bundle | it is not, or no SVID was served, or the server produced no authority set | the chain authority or the bundle set was not measured |
| **Z2** | the SVID expiry **moves**, at least once per `default_x509_svid_ttl` window | it stalls beyond the tolerance, moves backwards, or never moves across a series long enough to require it | fewer than two expiries were measured, or the series is shorter than the tolerance |
| **Z3** | the mtime of `agent-data.json` moves in the window | it never moves across a series longer than the floor, or moves backwards, or the file is gone | fewer than two mtimes were measured, or the series is shorter than the floor |

Z2 is the load-bearing one. A cache does not move.

**The tolerance is stated rather than hidden.** The probe samples hourly
and `default_x509_svid_ttl` is one hour, so the sampling interval and the
measured quantity are the same order of magnitude. The series can
establish *that* the expiry moves; it cannot count how many times it moved
between two samples. Z2's default stall tolerance is therefore TTL + one
sampling interval, and `--z2-max-stall-seconds` says so on the command
line.

Z3's floor is six hours (`--z3-min-span-seconds`, the same figure the
substrate-liveness probe uses for state staleness). SPIRE documents no
write cadence for `agent-data.json`, so a short quiet stretch is a gap in
the evidence, not a defect in the agent. Below the floor the absence of a
write is `UNKNOWN`; above it, it is the finding.

---

## 3. Z4 — the staged anchor, and why it was added

**This is an addition to §6.2 of the decision paper. It is flagged here
for the CTO and the CEO rather than slipped in.**

Two lines of ADR-0076 require it.

*"Der Re-Staging-Timer wird eine weitere stille Pflicht. Er muss Teil der
Sonde aus der Abnahme sein, sonst wiederholt sich die Klasse."*

*"Negativkontrolle, verpflichtend: Ein Lauf mit geleertem
`bundles`-Volume muss rot werden."*

The second one is the harder argument. **Z1, Z2 and Z3 cannot see an
emptied `bundles` volume.** A running agent keeps renewing from the
bundle it has cached in its own data volume; deleting the staged anchor
changes nothing it does, for as long as it keeps running. That is not a
hypothetical — it is precisely the state both nodes were in from May
onwards, and the reason the failure took four months to surface. Without
a fourth assurance the mandated negative control would come out green,
and by the decision's own logic the green window would be worth nothing
with it.

Z4 states: the anchor exists, is non-empty, parses as a bundle, holds at
least one X.509 authority that the server **also** currently holds, and
is rewritten at a cadence below `--anchor-restage-max-seconds`
(default 2 h, against a 24 h `ca_ttl` and a proposed 30 min timer).

The overlap requirement is the part that matters. ADR-0076 context (c)
records that the in-tree bundle CLIs produce well-formed JWKS which are
*"NOT cryptographically valid SPIRE-CA-keys"*. Wired into the staging
path they would give a file at the right path, a green existence check,
and a cold agent that still cannot bootstrap. Existence is not the
assurance; overlap with the authorities the server actually holds is
(TV-ACC-W-41, TV-ACC-P-23).

**Both sets are X.509 sets, and that is not a detail.** The
identity-substrate review measured a bundle holding exactly one
`jwt-svid` key and no X.509 authority: well-formed, genuine
server-issued key material, and it puts a real SPIRE v1.14.6 agent into
a retry loop with *"no certificates found in trust bundle"*. Such an
anchor **shares its JWT key with the server's key set**. If the overlap
were computed over all JWKS keys it would be satisfied, and Z4 would
read green over a substrate whose agent cannot start.

The sets are therefore built only from entries that declare
`"use": "x509-svid"`, via their `x5c`. The JWT key ids are recorded
beside them (`bundle_jwt_kids`) and take part in no comparison. An `x5c`
found on an entry that does not declare itself an X.509 authority is
ignored: the agent selects by `use`, and a measurement more generous
than its consumer is a measurement of something else
(TV-ACC-P-70, TV-ACC-P-71, TV-ACC-W-76).

The same gap exists at the writing end, in the staging step's own
validity check, and is being closed there in parallel. It is worth
having at both ends: the staging step decides what to write, this
decides whether what is there is an anchor, and those are two different
questions about the same file.

---

## 4. The falsifications

### F1 — six survived rotations

`ca_ttl` stays at 24 h by decision, so the operation that killed the
substrate runs six times inside the window, under observation. Seven days
without an observed rotation is not a passed window.

**What rotates, and what the harness counts.** Under `UpstreamAuthority
"disk"` the *root* stands still for years by design; the *signing
intermediate* turns over once per `ca_ttl`. The rotation is therefore
visible in the authority that signed the **leaf** and invisible in the
bundle set. The harness counts transitions of the leaf's signing
authority and gates on that. It also counts and reports transitions of
the bundle authority set, and does **not** gate on them: under the chosen
configuration that counter is expected to read zero, and gating on it
would demand an event the design forbids.

*This is a reading of the decision, not a quotation of it.* ADR-0076 says
"Wurzel-Rotationen"; the CTO decision paper §6.3 says "rotiert damit
weiterhin täglich der signierende Intermediate, während die Wurzel
steht." The harness follows the second. **If the board meant root
rotations, the window can never pass and the count has to be
renegotiated.** Flagged, not decided here.

"Survived" is not a synonym for "happened": each transition must be
followed by a sample in which the chain still terminates inside the
current bundle.

The count is only a finding once the series is long enough to contain it
(`--rotation-period-seconds` × `--min-rotations`). Below that it is a
gap, because demanding six rotations from a log that cannot hold six
would be a judgement about the length of the log.

### F2 — the cold-agent counter-probe

Stop the agent. Wait longer than the CA overlap. Start it again **without
touching any volume**. It has to come back — and "come back" means a
*new* credential: an agent that restarts and re-serves the certificate it
had before has demonstrated a cache, not a bootstrap.

Board decision, Auflage 2: it stays in the window even though it turns
the substrate red once.

The judge therefore **excludes** the marked cold-agent episode from
Z1–Z4 and F1, and judges it separately under F2. Folding the deliberate
outage into the standing assurances would mean the window could only pass
if the falsification the board insisted on were skipped — which is
exactly the conflict ADR-0076 A3 raises, resolved in favour of the
falsification.

F2 fails when: the agent was down for less than the CA overlap; it served
no SVID afterwards; the post-restart expiry is no later than the
pre-stop one; the post-restart chain does not terminate in the current
bundle; **or the agent's state file changed while the agent was
stopped**. The last one is the only part of "without touching any volume"
that is measurable from the samples. Everything else about that clause is
an operator obligation (§6), stated as such and not asserted as if it
had been measured.

---

## 5. The mandatory negative control

*"Ein Lauf mit geleertem `bundles`-Volume muss rot werden. Wird er das
nicht, ist auch das grüne Ergebnis nichts wert."*

Implemented as a marked episode inside the window, with three outcomes
and not two:

| The marked slice | Verdict | Because |
|---|---|---|
| no sample ever saw the anchor missing | `UNKNOWN` | the control was **not carried out**. Almost always the re-staging timer was left running (§6.4) |
| fewer than two samples saw it missing | `UNKNOWN` | the restore cadence undid the control mid-way; it measured the timer, not the assurance |
| two or more saw it missing, and the anchor assurance over the slice **fails** | `PASS` | the instrument detects what it was built to detect |
| two or more saw it missing, and the anchor assurance does **not** fail | `FAIL` | a check that cannot fail has not passed either, and the green window falls with it |

The first two rows are a correction, not a nicety. Before the DevOps
cross-review of PR #562 both of them came out `FAIL` with the reason
*"the negative control did not go red"* — a sentence that was wrong
twice: nobody had performed the control, and the finding was about the
procedure, not about the instrument. Either way the window does not
pass; the difference is whether the operator reading it on day seven is
pointed at the timer or at the harness. Keeping "not measured" apart
from "measured and bad" is the rule this whole plan runs on, and it has
to hold for the control as much as for anything it controls.

A window with no control episode at all is `UNKNOWN` — not performing
the control is the same position as performing it and watching it stay
green.

**The control must not remove the state it tests.** This is the TV-PROV-6
lesson from 2026-09-22 (a negative control that deleted the stale
remote-tracking ref whose *presence* created the condition it was
checking). Here the equivalent shape is a control run during which the
probe itself stopped working: the anchor then reads `unmeasured`, the
slice reads `UNKNOWN`, and one could be tempted to accept "not green" as
"red". It is not accepted. The slice must contain at least one sample in
which the other three sources were still measured, so the red is
attributable to the emptied volume and not to a fallen-over probe
(TV-ACC-W-72, TV-ACC-P-52).

---

## 6. Operator procedure

All of this is operator hand. Nothing here is run from the sandbox.

### 6.0 Step 0 — check that the instrument can measure, before opening the window

**Do not skip this.** An instrument that measures for seven days without
anyone having checked once that it measures is the class of instrument
this whole decision was written against.

Three preconditions have to hold, none of them visible from the harness,
two of them **false on a freshly bootstrapped node**:

1. **`WAKIR_PILOT_MODE=federation`.** The bootstrap stages the anchor and
   installs the re-staging timer only in this mode; the default is
   `single-org`. Under `single-org` the anchor is never written, the
   agent boots with `insecure_bootstrap = true`, and the `bundles`
   volume still exists because the server mounts it — so the mountpoint
   resolves, Z4 reads a clean `target_bad_anchor_absent`, and the window
   is **red for all 168 samples** for a reason that has nothing to do
   with trust.
2. **A registration entry the probe can actually see.** `spire-agent api
   fetch x509` returns *workload* SVIDs, not the agent's own. Without an
   entry that matches the calling context a real SPIRE v1.14.6 answers
   `PermissionDenied: no identity issued`; the probe records
   `target_bad_no_identity_issued_to_the_probe` and Z1, Z2 and F1 are
   red for a week — out of "nobody is registered", not out of "the
   substrate does not trust". **The bootstrap creates no entries.** The
   entry has to be made by hand, and it has to name the agent as it
   actually is:

   ```bash
   # the parent id is the agent's REAL id; read it, do not assume it.
   # Under join_token attestation it looks like
   #   spiffe://<trust-domain>/spire/agent/join_token/<uuid>
   # and NOT like the x509pop form the bring-up recipe still prints.
   podman exec wakir-spire-server-federation-<side> \
       /opt/spire/bin/spire-server agent list

   podman exec wakir-spire-server-federation-<side> \
       /opt/spire/bin/spire-server entry create \
       -parentID  "spiffe://<trust-domain>/spire/agent/join_token/<uuid>" \
       -spiffeID  "spiffe://<trust-domain>/acceptance-probe" \
       -selector  unix:uid:1000
   ```

   `unix:uid:1000` is the right selector because the agent config
   enables `WorkloadAttestor "unix"` and the agent container runs as
   uid 1000, which is the identity `podman exec` presents. If the entry
   is created with a shorter `-ttl` than the server default, pass the
   same figure to the judge as `--svid-ttl-seconds`, or Z2's stall
   tolerance is looser than the credential it is watching.

3. **The re-staging timer is enabled.** Otherwise the anchor is staged
   once at bring-up and never again, and Z4 goes red after two hours —
   correctly.

**Then the dry run, and its acceptance criterion:**

```bash
WAKIR_ACC_LOG=/tmp/step0.ndjson substrate-acceptance-probe.sh   # no --mark
```

The window may be opened only if **all** of these hold:

| | Criterion |
|---|---|
| a | exit code **0** |
| b | `svid_status`, `bundle_status`, `agent_data_status` and `anchor_status` are **all `ok`** |
| c | `unmeasured` is empty |
| d | `svid_chain_len` is noted. After the bilateral cutover it must read **2** (leaf + intermediate). A **1** there means Z1's chain-top assumption does not hold on this node, and that has to be settled **before** the window, not on day seven |

Throw the dry-run log away afterwards; it is not part of the window.

### 6.1 Open the window

`substrate-acceptance-probe.sh --mark window-start`, then
`systemctl enable --now wakir-substrate-acceptance-probe@<side>.timer`.

### 6.2 Let it run for seven days

Both sides.

### 6.3 The cold-agent counter-probe, once, somewhere in the middle

- `systemctl stop wakir-spire-agent-<side>.service`
- **then** `substrate-acceptance-probe.sh --mark cold-agent-stop` — in
  this order, so a write during shutdown is not misread as a hand on the
  volume
- wait **longer than `ca_ttl`**, i.e. more than 24 h
- **touch nothing.** No volume, no config, no file. The judge can see the
  agent's own state file move and nothing else; the rest of this line is
  held by the operator, not by the instrument
- `systemctl start wakir-spire-agent-<side>.service`
- `substrate-acceptance-probe.sh --mark cold-agent-start`

### 6.4 The negative control, once, near the end

**The re-staging timer has to be stopped first.** It restores the anchor
on a cadence far below the probe's — half an hour against an hour — so a
control run against a live timer gets the anchor back before a single
sample can see it gone. The marked episode then contains no absent
anchor at all, and the run is `UNKNOWN` with
`samples_with_anchor_absent: 0`: the control was not carried out. Same
outcome, differently caused, if the timer is left running and exactly one
sample catches the gap.

```bash
systemctl stop  wakir-spire-bootstrap-anchor-restage-<side>.timer   # FIRST
substrate-acceptance-probe.sh --mark negative-control-start
rm "$(podman volume inspect --format '{{.Mountpoint}}' \
        wakir-spire-server-federation-<side>-bundles)/bootstrap.jwks"

# ... at least two sampling intervals. Touch nothing else. ...
# Only the anchor goes. The agent keeps running, the server keeps
# running, the probe keeps running: the control proves that Z4 sees an
# emptied volume, and it proves nothing if it also takes out the
# measurement.

systemctl start wakir-spire-bootstrap-anchor-restage-<side>.timer
systemctl start wakir-spire-bootstrap-anchor-restage-<side>.service   # re-stage now
substrate-acceptance-probe.sh --mark negative-control-end
```

**Whoever stops the timer has to start it again.** Forgetting it makes
the standing Z4 correctly red two hours later — the right behaviour, and
it should surprise nobody.

**Acceptance criterion for the control, checked immediately and not on
day seven:**

```bash
python3 scripts/acceptance/substrate_acceptance_window.py \
    --samples samples-<side>.ndjson --json
```

The `NC` judgement must report **`samples_with_anchor_absent` ≥ 2**. The
overall verdict will still be `UNKNOWN` at this point — the window is not
over — but that one number says whether the control happened. It costs a
minute here and a whole window if it is left to the end.

### 6.5 Close the window

`--mark window-end`, stop the timer.

### 6.6 Judge, per side

```bash
python3 scripts/acceptance/substrate_acceptance_window.py \
    --samples samples-<side>.ndjson --json
```

Exit 0 is the only outcome that may be quoted as acceptance evidence.
Exit 1 and exit 2 are both "not evidence"; the difference between them is
for the person reading the report, not for the gate.

---

## 7. What does not count as evidence

From ADR-0076, and enforced rather than quoted — `tests/infra/` greps
both files for these surfaces and fails if one appears
(TV-ACC-P-40, TV-ACC-W-95):

- **podman health state.** Measured 2026-09-22: the healthcheck is
  executed as `CMD-SHELL` against an image with no shell, so it has
  published `unhealthy` since May while the same command run directly
  answers "Server is healthy." The label is not merely meaningless, it is
  the inversion of the truth.
- **container `Up` state and `RestartCount`.** Both were true and
  worthless for four months.
- **a single smoke run on bring-up day.** That was the May evidence.
- **server logs alone.** The server was busy and error-free for 127 days,
  rotating its CA cleanly, with no consumer.

A prohibition that lives only in a comment is the same class of
instrument as a healthcheck that never runs.

---

## 8. What this harness cannot catch

Stated here because a test plan that only lists what it covers is the
document version of the same problem.

1. **It has never run on a node.** Everything below `tests/infra/` is
   hermetic: minted certificates, injected fixtures, an injected clock,
   no podman, no network. The first real run is a first run, with
   everything this house has learned about first runs.
2. **It cannot see a hand on the volumes** during the cold-agent probe,
   beyond `agent-data.json` moving while the agent is stopped. Restoring
   a bundle cache, editing a config, re-running the bootstrap — none of
   that is visible in the samples.
3. **It cannot count renewals.** Hourly sampling against a one-hour TTL
   establishes movement, not frequency. An agent renewing once every 59
   minutes and one renewing four times an hour look the same.
4. **It cannot prove the SVID is usable.** Z1 is a set-membership test on
   key identifiers, not a cryptographic path validation. An SVID whose
   chain names an authority in the bundle but fails signature
   verification would pass Z1. The Workload API itself verifies the
   chain against the agent's cached bundle before handing it over, so
   this is a narrow gap — but it is a gap, and closing it would mean
   moving certificate material off the node.
5. **It says nothing about the federation peer.** Both assurances are
   made per side. Whether the two sides trust each other after the
   bilateral cutover is a different measurement and is not in this
   window.
6. **The sample log is not tamper-evident.** It is root-written on the
   node, unsigned, not anchored. Against an operator editing it by hand,
   nothing protects it. For Zone-N purposes: this is QA evidence, not an
   audit trail. A tamper-evident variant is a separate decision (WAT
   anchor), not a QA one.
7. **Nobody is told.** The window is watched because a person looks at
   it, not because the system reports. That is the Melder question
   (ADR-0076 "was diese Entscheidung nicht löst", point 2) and it is a
   different strand. Past day 8, this instrument says nothing at all.
8. **A green window is a statement about seven days.** It is not a
   statement about the eighth, and the thing that went wrong in May went
   wrong on roughly day two.
9. **The probe cannot see the agent's own credential.** `spire-agent api
   fetch x509` returns *workload* SVIDs, which is what ADR-0076 §6.1
   prescribes, and it therefore needs a registration entry that matches
   the calling context (§6.0). Everything Z1, Z2 and F1 say is a
   statement about *an identity issued to the probe*, not about the
   agent's own SVID. The two move together on a healthy substrate, and
   a missing entry is caught by step 0 rather than by a week of red —
   but they are not the same quantity, and the harness measures the one
   the decision names.

   There **is** a source for the other one: the agent's persisted SVID
   in `agent-data.json`, which the substrate-liveness probe already
   parses, and which needs no entry at all. Adding it would change what
   §6.1 measures, so it is named here and not built. If the entry turns
   out not to be creatable before the window opens, that is the change
   to make — in the decision, not quietly in this file.

---

## 9. The seam with the bootstrap

The harness consumes one contract and owns none of it: the staged
bootstrap anchor, written by `infra/spire/federation/wakir-pilot-bootstrap.sh`
into the `bundles` volume and refreshed by a timer beside it (ADR-0076
umsetzungsschnitt steps 3 and 4).

Four assumptions stood here when the harness was written. All four have
since been answered by the owner of the staging step, against the code
and in one case against a measurement:

| # | Assumption | Answer | Consequence here |
|---|---|---|---|
| A | the anchor's file name is `bootstrap.jwks` | **correct** — fixed in the stager, and the agent config points `trust_bundle_path` at it | no override needed; `WAKIR_ACC_ANCHOR_NAME` stays available |
| B | the volume is `wakir-spire-server-federation-<side>-bundles` | **correct** — the `.volume` unit sets `VolumeName=` explicitly, so Podman does not prefix it with `systemd-` | no override needed |
| C | the content is the output of `spire-server bundle show -format spiffe`, byte-identical | **correct**, and the admin socket is the SPIRE default, which the stager uses too | no override needed |
| D | **the re-staging timer touches the file on every run, even when the content is unchanged** | **correct, and measured**: three runs against byte-identical output gave three increasing mtimes | Z4's freshness half stands as built |

D was the one that could have produced a false red on a healthy
substrate — and it is now more than a promise: the staging step carries
its own invariant with a mutation control, so the obvious optimisation
("only write when it changed") turns that test red instead of turning
this window red two hours into the week. That is the right place for it.
A guarantee that only exists in the consumer's head is the arrangement
this house has already paid four months for.

Nothing under `infra/spire/` is read or written by this change, and
TV-ACC-P-41 asserts it.

---

## 10. Test vectors

| Module | Vectors |
|---|---|
| `tests/infra/test_substrate_acceptance_probe.py` | TV-ACC-P-01..03 (both trust topologies, rotation visibility), -10 (key hygiene), -20..28 (target-bad versus could-not-measure, one pair per source), -30..36 (record contract, markers, no SPIFFE ID), -40..42 (forbidden surfaces, the `infra/spire` seam, RFC1918 and home paths), -50..52 (probe and judge end to end, including the mandated negative control), -60..62 (the podman code path the fixtures bypass, driven through a stub, including the pair "container absent" = finding versus "podman absent" = not measured), -70..72 (the X.509 scoping of both authority sets, and a refusal named as a refusal) |
| `tests/infra/test_substrate_acceptance_window.py` | TV-ACC-W-01..02 (mutation control), -10..13 (Z1), -20..24 (Z2), -30..32 (Z3), -40..43 (Z4), -50..52 (F1), -60..64 (F2), -70..76 (the negative control: never carried out, undone by the restore cadence, the count the operator checks in §6.4, the control that killed its own instrument, and the JWT-only anchor), -80..84 (the reader: verdict-carrying samples, schema, unparseable lines, two sides, empty log), -90..99 (coverage, open episodes, FAIL over UNKNOWN, the narrow `require_measured` path on all four assurances) |

Both modules run in `lane-hermetic-invariants` and are required.
