# Phase-2 Live-VM Acceptance Test-Plan

| Field | Value |
|---|---|
| Owner | Amara Osei (QA) |
| Date drafted | 2026-05-16 |
| Sprint | Sprint-Live-VM-Test-Plan-Doku-MINI (Folge zu Sprint-Live-VM-MINI) |
| Baseline-PR | wakir-runtime PR #108 (Phase-2 Doppelbetrieb Live-VM Test-Suite skeleton) |
| Companion-PR | wakir-runtime PR #76 (CI-Live-VM-Acceptance-Wrapper, Kai) |
| ADR-Anker | ADR-0058 (Pilot-Persona-Migrations-Plan), feedback_live_bringup_sandbox_gap, feedback_sandbox_host_trennung |
| Quality-Gate-Anker | `docs/quality-gates/phase-2-doppelbetrieb.md` (Phase-2-Acceptance-Gates §2.1–§2.5) |
| Cross-Review (Zone M) | Tomás (WAT-CLI on-VM), Selin (persona-inspect on-VM), Reza (bridge-forward subcommand semantics), Kai (CI-Wrapper coupling), Noa (heartbeat-freshness SLI overlap) |
| Cross-Review (Zone N) | Henrik (Audit-evidence harvest from the live-target lane) |

## 0. Why this document exists

`tests/live_vm/test_phase_2_doppelbetrieb_live.py` (PR #108) is the
skeleton harness for the Live-VM lane that Phase-2 Doppelbetrieb
needs for Acceptance-Gate enforcement. The skeleton documents
*what* each TV-LVD vector asserts. This Test-Plan is the operator-
facing companion: it documents

* the **pre-conditions** an operator must satisfy before invoking
  the suite,
* which TV-LVD vectors are **Operator-Hand-only** vs. which are
  **CI-triggerable** through the Kai CI-Wrapper (PR #76),
* the **Acceptance-Gate mapping** (§2.1–§2.5 of
  `docs/quality-gates/phase-2-doppelbetrieb.md`) each TV-LVD vector
  feeds, and
* the **pre-existing Live-VM failure-pattern** catalogue (GHCR
  cosign-auth, skopeo-image-pin, etc.) that an operator must
  distinguish from a real Phase-2 regression.

It is **not** an on-VM runbook. The on-VM execution lane is owned by
Tomás (`scripts/federation-live-vm-acceptance.sh`) and Kai
(`scripts/ci-live-vm-acceptance-wrapper.sh`). This document is the
**QA-side** contract: what evidence the Live-VM lane is expected to
produce so the Phase-2 Acceptance-Gate is enforceable.

## 1. Pre-conditions

The Live-VM suite is skipped by default by
`tests/live_vm/conftest.py` (see PR #108). To actually exercise it,
the operator must establish every one of the following pre-conditions.
Any one of them missing should produce an explicit `skip` reason
rather than a silent pass.

### 1.1 SSH-key access to the Pilot-VM target

* **Default target host:** `192.168.178.116` (wakir-pilot side per
  Sprint-10 Tag-6 dogfood-LAN topology), override via
  `WAKIR_PEER_HOST`.
* **Required:** the operator-host (or CI runner) has a private-key
  whose public-key is installed in the target user's
  `~/.ssh/authorized_keys`.
* **Required:** the target user has `sudo`-NOPASSWD for the on-VM
  acceptance lane (the on-VM `federation-live-vm-acceptance.sh`
  needs root for `systemctl` / `podman exec` against root-Quadlets).
* **Sandbox boundary:** the claude-dev Sandbox **cannot** reach
  `192.168.178.*`. The Sandbox-side checks for this Test-Plan are
  limited to verifying that the skip-by-default guard fires. Every
  real run is Operator-Hand or a CI runner with explicit SSH
  credentials to the target — never claude-dev itself.

### 1.2 wakir-pilot + wakir-orbit reachability

Phase-2 Doppelbetrieb assumes the **bilateral federation** topology
is up:

* **wakir-pilot side:** federation-mode active, bundle-endpoint
  listener bound on `:8443`, persona-tomas Quadlet running.
* **wakir-orbit side:** federation-mode active, bundle-endpoint
  listener bound on `:8443`, peer-trust-bundle imported.
* **Required reachability:** TCP/8443 between the two sides
  (verified by Kai's `WAKIR_BILATERAL_PRECHECK=1` step in
  `wakir-pilot-bootstrap.sh`, PR #76).

If only one side is up, the Persona-Container heartbeat vectors
(TV-LVD-01..04) may still run, but the Bridge-Forward fan-out
vectors (TV-LVD-08..10) MUST be skipped — they assume the bilateral
sink topology.

### 1.3 Double-Gate: both `--run-live-vm` AND `WAKIR_LIVE_VM_ACCEPTANCE=1`

The skeleton's `conftest.py` enforces a **double-gate**: both the
pytest CLI flag `--run-live-vm` AND the environment variable
`WAKIR_LIVE_VM_ACCEPTANCE=1` must be set. Either alone produces a
skip with an explicit reason.

* **Why double-gate.** Belt-and-braces against (a) a CI runner that
  happens to carry the flag in a config file but should not actually
  point at the live VM and (b) an operator shell that has the env-var
  set but did not mean to run the live lane right now.
* **Operator invocation (Mira-Hand):**

  ```
  WAKIR_LIVE_VM_ACCEPTANCE=1 pytest --run-live-vm \
      tests/live_vm/test_phase_2_doppelbetrieb_live.py
  ```

* **CI invocation (via Kai-Wrapper):** the wrapper sets the env-var
  internally on the on-VM side and passes the flag through. The CI
  runner side itself does not need to set the env-var — the
  wrapper-script is the gate.

### 1.4 SSH-runner fixture installed

The skeleton `ssh_runner` fixture (PR #108) is a **refusal stub**: it
raises `pytest.fail()` if invoked outside a live run. A real run
requires the operator-side test framework to install a real
SSH-backed runner. Sprint-Live-VM-Folge (post-MINI) will land this
runner; this Test-Plan is written assuming it exists.

### 1.5 On-VM CLI subcommand availability

The TV-LVD vectors invoke three on-VM CLI surfaces that are
**substance-bestätigung-pending** as of this Test-Plan draft (see
§5 Cross-Review-Pflicht):

* `wirelang persona-inspect --heartbeat --json` (TV-LVD-01..04)
* `wirelang bridge-forward inject-synthetic` /
  `publish-synthetic` / `subscribe-loop-summary --json`
  (TV-LVD-04, TV-LVD-08..10)
* `wat inject-synthetic-leaf` / `anchor-receipt --json` /
  `verify --external --json` (TV-LVD-05..07)

Sub-command **existence-confirmation** is on Tomás (wat-CLI),
Selin (persona-engine-CLI) and Reza (bridge-forward CLI / schema).
If any of these subcommands is named differently or carries
different flag-semantics on the substrate at run-time, the
corresponding TV-LVD vector MUST be marked `xfail` with the
substance-bug-ID until the CLI-shape lands; it MUST NOT be silently
skipped.

## 2. Operator-Hand vs. CI-triggerable matrix

The ten TV-LVD vectors are not all equally automation-safe. Some
need a human to be on the keyboard ready to intervene; some are
mechanical enough to run on a CI cadence without supervision.

| Vector | Lane | Why this lane | Cadence (target) |
|---|---|---|---|
| **TV-LVD-01** Persona heartbeat single | CI-triggerable | Read-only probe, no state mutation. Idempotent. | Continuous (per Wrapper-Run, at least weekly per §2.1) |
| **TV-LVD-02** Persona heartbeat burst (5×) | CI-triggerable | Read-only, bounded loop. Cache-staleness regression is mechanical to detect. | Continuous |
| **TV-LVD-03** Persona heartbeat post-restart | **Operator-Hand** | `systemctl restart` mutates VM state. A wedged restart blocks unrelated Engineering-traffic on the Pilot-VM. | On-demand (post-deploy, post-substrate-update) |
| **TV-LVD-04** Heartbeat post-bridge-fanout | CI-triggerable | `bridge-forward inject-synthetic` is by-design idempotent and tagged; clean test-data hygiene. | Continuous |
| **TV-LVD-05** WAT leaf → hour-root | CI-triggerable | Injects a tagged synthetic leaf into the audit-trail. This is by-design (the WAT-test-vector lane writes test-leaves; Henrik filters by tag in sample-audit). | Continuous |
| **TV-LVD-06** OTS state progression (72h-old) | CI-triggerable | Read-only against historical hour-bucket. Needs ≥72h Pilot-VM uptime — schedule it weekly so the 72h-window is always populated. | Weekly (Phase-2 §2.1 cadence) |
| **TV-LVD-07** External-verifier roundtrip | CI-triggerable | Read-only, expensive (re-derives hour-root from persisted leaves). Run after TV-LVD-06 in the same Wrapper-Run. | Weekly |
| **TV-LVD-08** Subscribe-loop single auftrag | CI-triggerable | Bounded, tagged, idempotent. | Continuous |
| **TV-LVD-09** Subscribe-loop 100-burst symmetric | CI-triggerable | 100-burst is well under the §2.2 drop-rate budget (≤0.1% over 24h). | Continuous |
| **TV-LVD-10** Bug-42 induced-reconnect | **Operator-Hand** | `--induce-reconnect-mid-burst` deliberately disturbs the subscribe-loop and could leak into unrelated traffic if the test-tag filter has a regression. Wants a human to watch the run. | On-demand (post-engine-update, regression-on-suspicion) |

**Lane discipline.** The CI-triggerable lane is invoked through Kai's
`scripts/ci-live-vm-acceptance-wrapper.sh` (PR #76). The
Operator-Hand lane is invoked directly via the `WAKIR_LIVE_VM_ACCEPTANCE=1`
+ `--run-live-vm` double-gate at an operator shell, optionally
deselecting CI-triggerable vectors with `-k 'tv_lvd_03 or tv_lvd_10'`.

**Mixed-lane safety.** Nothing forbids a CI-triggerable run from also
exercising the Operator-Hand vectors — they are gated by lane choice,
not by hard separation. But the default CI-Wrapper invocation MUST
deselect the Operator-Hand vectors (`-m 'live_vm and not operator_only'`,
once that marker lands in the suite). The Wrapper-Run summary-JSON
records which lane it ran in.

## 3. Acceptance-Gate mapping

Each TV-LVD vector feeds exactly one or more Phase-2 Acceptance-Gates
in `docs/quality-gates/phase-2-doppelbetrieb.md`. This table is the
contract: if a Gate is dropped from §1 of that document, the
corresponding TV-LVD vector(s) should be re-classified or retired in
a follow-up; conversely if a new Gate lands, a new TV-LVD vector is
required.

| TV-LVD | Phase-2 Gate (§ in `phase-2-doppelbetrieb.md`) | What the vector proves about the Gate |
|---|---|---|
| TV-LVD-01 | §2.1 (All Phase-1b gates remain green) + §2.4 (V-907 pin-drift) | Persona-Container responds, baseline alive-signal that every other Gate depends on. |
| TV-LVD-02 | §2.1 (Phase-1b gates inherit) | Heartbeat-cache-staleness regression class is detected (substance-bug pattern 2026-05-13 #4). |
| TV-LVD-03 | §2.4 (V-907 pin-drift over 28d) + §2.1 | Restart-roundtrip preserves the build-time pin; `EXIT_V907_HASH_DRIFT` does not fire. |
| TV-LVD-04 | §2.2 (Bridge-Forward fan-out symmetric) — receive-side | Container actually consumes a published auftrag — the Bug-42-class silent-drop is detected at the receive-end. |
| TV-LVD-05 | §2.1 (Phase-1b WAT-roundtrip inherits) | Leaf → hour-Merkle-root pipeline is live; OTS-state is observable. |
| TV-LVD-06 | §2.1 (Phase-1b OTS-upgrade-loop) + Henrik-Audit §4 evidence-A | OTS-upgrade-loop has not silently stopped; 72h-old buckets are anchored. |
| TV-LVD-07 | §2.1 (Phase-1b external-verifier) + Henrik-Audit §4 evidence-B | Audit-trail is verifiable by a third party. **Core audit-trail invariant for Zone-N.** |
| TV-LVD-08 | §2.2 (Bridge-Forward fan-out symmetric, single) | Per-auftrag exactly-once on both sinks. |
| TV-LVD-09 | §2.2 (Bridge-Forward fan-out symmetric, burst) | Drop-rate budget at 100-burst is 0 (well inside the ≤0.1%-over-24h budget). |
| TV-LVD-10 | §2.2 (Bridge-Forward fan-out symmetric, no-duplicate) | Bug-42-class double-delivery under induced reconnect is detected. |

**Henrik-Audit-Sample evidence harvest.** The TV-LVD outputs (pytest
JUnit-XML + summary-JSON from the CI-Wrapper) are the evidence-source
for the Phase-2 Audit-Sample §4.A (continuous CI-Live-VM-Acceptance-
Gate runs) and §4.B (external-verifier-driver runs against the
substrate). The mapping above is the Zone-N contract: Henrik reads
the TV-LVD-IDs in the summary-JSON and confirms they cover the §1
Gates without claiming evidence the Gate does not actually demand.

## 4. Pre-existing Live-VM failure-pattern catalogue

These are failure modes the Live-VM lane has surfaced **on the
substrate**, not regressions introduced by the TV-LVD suite. An
operator (or a future automated triage) MUST distinguish a
pre-existing failure (substrate-known-issue) from a Phase-2
regression (the TV-LVD suite is doing its job and caught something
new). If a TV-LVD vector fails with a transcript matching one of
these patterns, the verdict is **substrate-pre-existing**, not
Phase-2-regression — file against the corresponding open bug, do
not block the Acceptance-Gate verdict on this vector pending
substrate-fix.

### 4.1 Cosign + GHCR auth (cosign keyless sign-push → 401)

* **Pattern.** Build + buildah-push step completes; the next
  `cosign sign` step fails with `401 UNAUTHORIZED` against the
  GHCR signature-blob endpoint.
* **Root cause.** `cosign sign` pushes the signature artefact as
  an OCI blob to the **same OCI registry as the image** (GHCR).
  The earlier `Login to GHCR` step credentials are not picked up by
  cosign's blob-push code-path — cosign needs its own login step.
* **Reference.** `docs/ci-cosign-ghcr-auth.md` (full root-cause +
  fix-recipe).
* **Affects.** Substrate-build chain on the Pilot-VM, not the
  TV-LVD-suite directly. But TV-LVD-01..04 can fail at fixture-time
  if the persona-tomas Quadlet cannot pull its image because the
  pin's signature is missing — that failure-transcript is
  **substrate-pre-existing**, not a Phase-2 regression.
* **Disposition.** Re-run after substrate-image-rebuild with the
  Cosign-login-step fix; if it persists, file under existing
  `ci-cosign-ghcr-auth` issue.

### 4.2 skopeo image-pin resolution drift

* **Pattern.** `skopeo inspect docker://ghcr.io/<owner>/<image>:<tag>`
  returns a digest that does not match the digest baked into the
  Quadlet-pin; persona-tomas refuses to spawn with
  `EXIT_V907_HASH_DRIFT` (TV-LVD-03 failure-mode).
* **Root cause classes.**
  (a) Upstream-tag was force-overwritten (GHCR allows tag-mutability
  for public-registry images by default).
  (b) Multi-arch manifest-list vs. platform-specific digest:
  the Quadlet-pin is platform-specific (`linux/amd64`) but the
  bringup script resolved against the manifest-list head.
* **Reference.** `docs/ci-image-pin-resolution.md`,
  `docs/spire-agent-phase-2-2.md` (skopeo-inspect recipe), Kai
  Resolver-Trust-Mode-Selector (`WAKIR_RESOLVER_TRUST_MODE`, PR #76).
* **Affects.** TV-LVD-03 (post-restart heartbeat). A
  `pin_sha256`-mismatch in the heartbeat doc is *also* the symptom of
  a real V-907 drift event — the operator distinguishes by comparing
  the on-VM-recorded pre-restart `pin_sha256` (logged by the
  Quadlet-unit on startup) with the post-restart value: if the
  Quadlet was re-pulled in between, the pre-existing pattern applies.
* **Disposition.** Re-pin the Quadlet-unit to a fresh digest with
  `WAKIR_RESOLVER_TRUST_MODE=cosign-strict` (PR #76); if persistent,
  file under existing `ci-image-pin-resolution` issue.

### 4.3 Bug-30/31/32 SPIRE-malformed-configuration regression

* **Pattern.** SPIRE-Server log on the Pilot-VM contains
  `malformed configuration`; the on-VM acceptance script exits 3
  with `bootstrap-substance failure (Bug-30/31/32 regression)`.
  TV-LVD-01..10 all fail at fixture-time because the
  persona-tomas Quadlet has no SPIRE-Agent SVID and refuses to
  start.
* **Root cause.** Bootstrap-substance-bug class fixed in Sprint-Tag-6/7;
  regression-guard in `federation-live-vm-acceptance.sh` line ~180
  (`grep 'malformed configuration'`).
* **Affects.** Entire TV-LVD-suite is unrunnable until substrate-fix.
* **Disposition.** Substrate-stop. The TV-LVD-suite emits a single
  collection-time skip with reason `substrate-pre-existing:
  bootstrap-substance failure`. Do NOT mark Phase-2 Acceptance-Gate
  failed; mark Acceptance-Gate **pending substrate**.

### 4.4 Peer-VM unreachable (`192.168.178.<peer>:8443`)

* **Pattern.** `federation-live-vm-acceptance.sh` line ~189 emits
  `WARN: peer ${WAKIR_PEER_HOST}:8443 not reachable`. The local
  side's federation-mode still verifies, but TV-LVD-08..10
  (Bridge-Forward fan-out) fail at fixture-time because the
  bilateral sink topology is incomplete.
* **Root cause.** Either (a) the peer VM is intentionally offline
  (Operator-decision; cf. `feedback_sandbox_host_trennung`) or
  (b) network/firewall regression between the two LAN hosts.
* **Affects.** TV-LVD-08..10 only. TV-LVD-01..07 still run.
* **Disposition.** Skip the affected vectors with a
  collection-time `pytest.skip` carrying the WARN-string. Do NOT
  fail; the bilateral-down state is operator-known and tracked
  outside Phase-2 Acceptance-Gate per §1.2 of this Test-Plan.

### 4.5 Bug-35-class podman-run-vs-Quadlet drift

* **Pattern.** Persona-tomas Container is up under
  `podman run` (Mira-Hand workaround), but the Quadlet-unit
  `wakir-persona-tomas.service` is `inactive`. TV-LVD-03
  (post-restart) fails because `systemctl restart` operates on the
  inactive Quadlet, not the running `podman run` container.
* **Root cause.** Production-install path was Mira-Hand-`podman
  run` workaround since Bug-35; Kai PR #76 ships
  `scripts/install-persona-tomas-quadlet.sh` to replace the
  workaround with a Quadlet-installed unit.
* **Affects.** TV-LVD-03 only. TV-LVD-01/02/04 still work against
  the `podman run` container if the `wakir-persona-tomas` name
  resolves to it; TV-LVD-05..10 are unaffected (different
  containers).
* **Disposition.** Run `install-persona-tomas-quadlet.sh` to
  promote the workaround to a Quadlet; re-run TV-LVD-03.

### 4.6 Sandbox-host-collision (defence-in-depth, should never fire)

* **Pattern.** The TV-LVD-suite is invoked from inside the
  claude-dev Sandbox and somehow gets past the conftest skip-guard.
  Per `feedback_sandbox_host_trennung`, claude-dev has no
  host-podman-socket access and cannot reach
  `192.168.178.*`. The `ssh_runner` refusal-stub fires.
* **Root cause.** A future refactor accidentally flipped the
  skip-default. **This is a test-harness bug, not a substrate
  failure.**
* **Affects.** Entire TV-LVD-suite would emit
  `pytest.fail("ssh_runner called outside a live-vm run")`.
* **Disposition.** Treat as a P0 against the suite itself, not the
  substrate. Fix the conftest skip-guard. Do not file a substrate
  bug.

## 5. Cross-Review-Pflicht — substance-bestätigung items

The TV-LVD suite assumes three on-VM CLI surfaces exist with the
exact subcommand shape encoded in PR #108. These shapes are
**unconfirmed against the live substrate** as of this Test-Plan
draft. The owners listed below are responsible for confirming or
flagging the CLI-shape; until that confirmation lands, the affected
vectors carry an implicit `xfail-on-CLI-mismatch` disposition (§1.5).

### 5.1 `wirelang persona-inspect` (TV-LVD-01..04)

* **Owner:** Selin (Persona-Engine).
* **Assumed subcommand:** `wirelang persona-inspect --heartbeat --json`.
* **Assumed output schema:**

  ```json
  {"persona": "tomas",
   "transition_utc": "<RFC3339-Z>",
   "active_log_len": <int>,
   "pin_sha256": "<64-hex>"}
  ```

* **Selin to confirm:** Subcommand exists; flags `--heartbeat` +
  `--json` are accepted; output schema matches; the engine
  caches/serves a fresh `transition_utc` per probe (not a stale
  cached value, see TV-LVD-02 regression class).
* **If schema differs:** TV-LVD-01..04 fixtures' `parse_heartbeat`
  helper must be adapted. The schema-change is a Phase-2 contract
  change and should land via a follow-up PR against this Test-Plan +
  the suite, not silently.

### 5.2 `wat anchor-receipt` / `wat verify --external` (TV-LVD-05..07)

* **Owner:** Tomás (WAT-substrate).
* **Assumed subcommands:**
  * `wat inject-synthetic-leaf --tag <tag>` (TV-LVD-05).
  * `wat anchor-receipt --current-hour --json` (TV-LVD-05).
  * `wat anchor-receipt --hours-ago 72 --json` (TV-LVD-06).
  * `wat verify --external --hours-ago 72 --json` (TV-LVD-07).
* **Assumed output schemata:**
  * Anchor-receipt:
    `{"hour_root": "<64-hex>", "ots_state": "pending"|"anchored",
     "btc_block_height": <int>|null}`.
  * Verify-external:
    `{"verdict": "verified"|"failed", ...}` (verdict-key is
    load-bearing; rest is informational).
* **Tomás to confirm:** Subcommand-set exists on the on-VM `wat`
  binary; `--hours-ago N` is supported; `inject-synthetic-leaf` is
  by-design (not gated behind a debug-build flag).
* **If `inject-synthetic-leaf` is debug-only:** TV-LVD-05 must be
  promoted to Operator-Hand-only (debug-build provisioning is
  not automation-safe), and the §2 matrix updated.

### 5.3 `wirelang bridge-forward` subcommands (TV-LVD-04, TV-LVD-08..10)

* **Owner:** Reza (Wirelang-schema) — primary; Selin (subscribe-loop)
  — co-owner.
* **Assumed subcommands:**
  * `wirelang bridge-forward inject-synthetic --persona <p> --tag <t>`
    (TV-LVD-04).
  * `wirelang bridge-forward publish-synthetic --persona <p>
    --count <N> --tag <t>` (TV-LVD-08, TV-LVD-09).
  * `wirelang bridge-forward publish-synthetic --persona <p>
    --count <N> --tag <t> --induce-reconnect-mid-burst`
    (TV-LVD-10).
  * `wirelang bridge-forward subscribe-loop-summary --filter-tag <t>
    --json` (TV-LVD-08..10).
* **Assumed summary-output schema:**

  ```json
  {"auftrag_count": <int>,
   "pre_framework_sink_count": <int>,
   "wakir_container_sink_count": <int>,
   "duplicate_count": <int>}
  ```

* **Reza/Selin to confirm:** Subcommands exist; `--filter-tag` filters
  the summary against a single test-run cleanly; `--induce-reconnect-
  mid-burst` is implemented and bounded (the reconnect must be
  scoped to the test's tagged Aufträge — not a process-wide NATS
  reconnect that disturbs unrelated traffic).
* **If `--induce-reconnect-mid-burst` is not bounded to tag-scope:**
  TV-LVD-10 stays Operator-Hand-only (already so per §2). The
  affected-blast-radius of an unbounded reconnect is the entire
  Pilot-VM subscribe-loop fleet; Operator-Hand-only is the right
  default until the bound is confirmed.

### 5.4 Cross-review cadence

* Zone-M wöchentlich via Tomás (Engineering-Lead, ADR-0045-Matrix-
  Lead-Hut): the three CLI-substance-bestätigung items are agenda-
  items at the next Zone-M review.
* Zone-N quarterly with Henrik: the Acceptance-Gate-Mapping (§3) is
  the Zone-N contract for Phase-2 Audit-Sample evidence harvest.
  Confirm that the TV-LVD-to-Gate mapping is total (every §1 Gate
  has at least one TV-LVD feeding it) and audit-readable (Henrik
  can derive the §4-A/B evidence from the Wrapper-Run summary-JSON
  without consulting the test source).

## 6. Out of scope (deferred)

The following items are **deliberately deferred** beyond this
MINI-scope Test-Plan:

* **Real SSH-runner-fixture implementation.** The skeleton refusal-
  stub stands. A follow-up sprint lands the real
  `paramiko` / `fabric` / `subprocess + ssh-binary` runner.
* **Coverage thresholds for the live-target lane.** Coverage is
  measured at the hermetic-test layer
  (`docs/quality-gates/phase-2-doppelbetrieb.md` §2). The live-target
  lane is acceptance-binary (pass/fail per Gate), not coverage-
  measured.
* **Doppelbetrieb-Score-CLI integration into the suite.** The CLI
  runs separately on a 6h cadence per
  `docs/quality-gates/phase-2-doppelbetrieb.md` §2.3 and produces
  its own JSON-rollup; the TV-LVD-suite does not duplicate that
  measurement.
* **Phase-3-Production lane.** Phase-3 production-traffic SLOs
  (`docs/quality-gates/phase-3-production.md`) need a separate
  test-plan once Phase-2 is closed. This document covers Phase-2
  only.

## 7. Sign-off

This Test-Plan is **draft pending Zone-M and Zone-N cross-review**.

* **Zone-M (Tomás + Selin + Reza + Kai + Noa):** confirm §1.5 / §5
  CLI-substance items.
* **Zone-N (Henrik):** confirm §3 Acceptance-Gate-Mapping is the
  evidence-contract for Phase-2 Audit-Sample §4-A/§4-B.

On sign-off, this document becomes the **canonical operator
companion** to PR #108. Until sign-off, the TV-LVD suite stays
skipped-by-default and the Phase-2 Acceptance-Gate enforcement lane
runs against the hermetic surface only.

— Amara
