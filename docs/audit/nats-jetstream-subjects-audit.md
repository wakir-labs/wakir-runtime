<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# NATS-JetStream Subjects + Publish-Mode Audit (Tag-43)

**Owner:** Selin Çelik (Persona-Engine Engineer)
**Companion script:** [`scripts/audit/nats-jetstream-subjects-audit.py`](../../scripts/audit/nats-jetstream-subjects-audit.py)
**Hermetic tests:** [`tests/audit/test_nats_jetstream_subjects_audit.py`](../../tests/audit/test_nats_jetstream_subjects_audit.py)
**First report:** [`reports/audit/2026-05-18-nats-jetstream-subjects-audit.md`](../../reports/audit/2026-05-18-nats-jetstream-subjects-audit.md)
**Related ADRs / spec sections:** Bug-42 Failure-Mode-Catalogue (`wirelang/specs/wirelang-spec-v0-2.md` §13.2 / §13.3 / §13.4), Tag-41 PR #265 (publish/subscribe surface compatibility contract).

---

## 1. Why this audit exists

PR #265 (Tag-41) closed the Bug-42 *silent-drop F-1* class for the
Bridge-Forward-Pipe by:

1. Encoding the publish/subscribe surface-compatibility matrix in
   `wirelang/persona_engine/publish_mode_contract.py`.
2. Adding a `--publish-mode {core,jetstream}` switch and the
   `js.publish` dispatch path to `wirelang/cli/bridge_forward.py`.
3. Installing a `require_compatible(...)` pre-flight gate on the
   subscriber side (`wirelang/persona_engine/cli.py`).

That fix lives on three files. Tag-43 asks the next question: *Are
all other NATS publish / subscribe call sites in the codebase
configured analogously?* A silent regression — a new module that
calls `nc.publish` without honouring `--publish-mode jetstream`, or
a new subscriber that imports the contract but forgets the gate —
would re-introduce the same Bug-42 class without surfacing in any
existing test.

The audit is a **static**, **stdlib-only**, **hermetic-testable**
pass over the working tree. It does not run NATS. It does not
import `nats-py`. It is a deterministic grep + parse + classify
pipeline.

---

## 2. Audit charter (four classes)

### 2.1 Inventory-Scan

Every Python (`*.py`) and Rust (`*.rs`) source file under the repo
root is scanned for one of the publish/subscribe call sigils:

| Sigil               | Kind                  |
|---------------------|-----------------------|
| `nc.publish(...)`   | `publish-core`        |
| `js.publish(...)`   | `publish-jetstream`   |
| `nc.subscribe(...)` | `subscribe-core`      |
| `js.subscribe(...)` | `subscribe-jetstream` |
| `SubscribeAsync(`   | `subscribe-polyglot`  |

Each hit becomes an inventory row `(file, line, kind, snippet)`.
Docstring-embedded sigils are stripped before classification so
documentation literals do not pollute the inventory. Comment lines
(`#` for Python, `//` for Rust) are skipped.

### 2.2 Mode-Cross-Validation (Bug-42 Adapter-B)

For every module that *both* references the publish-mode
discriminator (one of `PUBLISH_MODE_JETSTREAM`,
`PUBLISH_MODE_CORE`, `resolve_publish_mode_from_env`,
`--publish-mode`, `WAKIR_NATS_PUBLISH_MODE`) and contains a
publish call, the audit verifies that the dispatch is well-formed:

| Verdict             | Meaning                                                                 |
|---------------------|-------------------------------------------------------------------------|
| `ok`                | Module dispatches both `nc.publish` and `js.publish` with the guard.    |
| `ok` (jetstream)    | Module is JetStream-only publisher with mode guard (Phase-3 end state). |
| `adapter-incomplete`| Module references the mode but only calls `nc.publish` — Bug-42-class.  |
| `no-publish-mode`   | Module references the mode discriminator but has no publish call.       |

### 2.3 Subject-Pattern-Drift Check

Every string literal that starts with `wakir.` is parsed and
classified against the canonical subject form
`wakir.<env>.<domain>.<event>[.<sub_id>]` (single source of truth:
`wirelang/schemas/layer-0-transport.json`, mirrored in
`wirelang/nats/subject_mapping.py::SCHEMA_SUBJECT_REGEX`).

| Verdict          | Meaning                                                                        |
|------------------|--------------------------------------------------------------------------------|
| `ok`             | Concrete literal matches the schema regex.                                     |
| `ok` (template)  | Template literal matches `wakir.{env}.<domain>.<event>[.<sub_id>]`.            |
| `regex-drift`    | Concrete literal starts with `wakir.<env>.` but fails the schema regex.        |
| `template-drift` | Template literal uses unknown placeholder(s) or wrong root.                    |
| `namespace-id`   | Literal uses `wakir.*` namespace but is *not* a NATS subject (metric / schema-id / DID prefix). |

The `namespace-id` verdict is intentional: many `wakir.*` literals
in the codebase are telemetry meter names
(`wakir.persona_engine.subscribe_lag_seconds`), schema-ids
(`wakir.bridge.forward-frame/1`) or DID prefixes (`wakir.dev`) —
not NATS subjects. The audit must surface them so reviewers can
spot a *future* mistake (a literal that is meant to be a subject
but is misclassified by the heuristic) but must not count them as
drift.

The distinguishing rule: a NATS subject literal starts with
`wakir.<env>.` where `<env>` is one of `dev` / `staging` / `prod`.
Anything else is a namespace-id.

### 2.4 Adapter-Config-Audit (require_compatible gate)

The `require_compatible(...)` gate (spec §13.2) is the
**subscriber's** responsibility: a subscriber must refuse silent-
drop pairs before binding the JetStream consumer. A pure-publisher
module that resolves the publish-mode but never subscribes does
not need the gate — the matching gate fires on its subscriber
counterpart.

| Verdict                 | Meaning                                                                          |
|-------------------------|----------------------------------------------------------------------------------|
| `ok`                    | Module imports contract, calls `require_compatible`, and dispatches NATS.        |
| `preflight-gate-missing`| Subscriber imports contract but does not call `require_compatible` — Bug-42-class. |
| `publisher-no-gate`     | Publisher imports contract and resolves mode but has no subscribe call (info).   |
| `no-contract-import`    | Module has NATS calls but does not import the contract (info).                   |
| `data-only`             | Contract-importing module with no NATS call (test/helper).                       |

Only `preflight-gate-missing` counts as drift.

---

## 3. Exclusion rules

The audit deliberately skips the following paths so test fixtures
do not pollute the inventory:

- Any path containing `/tests/`, `/test/`, `/fixtures/`,
  `/.git/`, `/.venv/`, `/venv/`, `/__pycache__/`, `/target/`,
  `/node_modules/`, `/.worktree-`.
- Any file named `conftest.py`.
- The audit script itself (`nats-jetstream-subjects-audit.py`,
  which contains documentation sigils).

If a future test directory needs to participate in the audit (very
unlikely — the audit is about production substrate), edit
`_EXCLUDED_DIR_TOKENS` / `_EXCLUDED_FILE_NAMES` in the script and
update this table.

---

## 4. CLI usage

```bash
# Print the report to stdout (default audit-only mode).
python3 scripts/audit/nats-jetstream-subjects-audit.py

# Write the report to the canonical reports/audit/ location.
python3 scripts/audit/nats-jetstream-subjects-audit.py \
    --report reports/audit/$(date +%F)-nats-jetstream-subjects-audit.md

# Enforce mode — exit non-zero if any drift row is present.
python3 scripts/audit/nats-jetstream-subjects-audit.py --enforce

# Deterministic timestamp for snapshot tests.
python3 scripts/audit/nats-jetstream-subjects-audit.py \
    --utc-date 2026-05-18T00:00:00Z
```

Exit codes:

| Exit code | Meaning                                                             |
|-----------|---------------------------------------------------------------------|
| 0         | Audit completed; either drift-free or audit-only mode.              |
| 2         | `--enforce` set AND at least one drift row detected.                |
| Other     | CLI usage error (argparse) or unexpected I/O failure.               |

---

## 5. CI integration

The audit ships with a CI workflow
(`.github/workflows/nats-jetstream-subjects-audit.yml`) that runs
on every push / PR touching `wirelang/`, `scripts/`,
`scripts/audit/nats-jetstream-subjects-audit.py`, the docs file,
or the test file. The workflow runs in **audit-only** mode for
the introduction cut (the same posture as Reza's
`cross-repo-drift-audit` workflow at Tag-42 introduction) and
publishes the Markdown report as a job-summary block. Flipping
the workflow to `--enforce` happens after the first drift-free
report has been observed for two consecutive merge-trains.

---

## 6. Test coverage (14 hermetic tests)

`tests/audit/test_nats_jetstream_subjects_audit.py` covers:

1. `classify_call` returns the expected sigil for each surface.
2. `classify_call` skips comment lines.
3. `classify_subject_template` distinguishes `ok` / `regex-drift`
   / `template-drift` / `namespace-id`.
4. `scan_calls` skips docstring sigils.
5. `scan_subjects` reports line numbers and de-dups same-line
   repeats.
6. `audit_repo` over a clean fixture reports zero drift.
7. `audit_repo` over a drifted fixture surfaces the regex-drift
   literal.
8. `cross_validate_modes` flags adapter-incomplete modules.
9. `adapter_config_audit` flags subscriber preflight-gate-missing.
10. `adapter_config_audit` treats publisher-no-gate as
    informational.
11. `render_report` is deterministic (SHA-256 match).
12. CLI `--enforce` exit codes are correct on clean and drifted
    fixtures.
13. CLI `--report` writes the file matching the in-process render.
14. The audit's `SCHEMA_SUBJECT_REGEX` mirror matches every
    canonical subject example from
    `tests/test_nats_subject_mapping.py`.

Run them with:

```bash
python3 -m pytest tests/audit/test_nats_jetstream_subjects_audit.py -v
```

---

## 7. Audit boundary — what this script does NOT do

- **No live JetStream probe.** The complementary live-config audit
  lives in Tomás' `cross-substrate-parity-gate` workflow.
- **No git history scan.** The audit is a working-tree snapshot.
- **No nats-py import.** stdlib-only; runs on a bare Python 3.11+.
- **No network.** The audit never opens a socket.

The combination of (a) this static audit, (b) Tomás' live-config
parity gate, and (c) the existing `require_compatible` pre-flight
guard is the Bug-42 compound defence.

---

## 8. Cross-Review references

- Reza Tag-42: `scripts/audit/cross-repo-sync-audit.py` —
  pattern template (stdlib-only, hermetic-testable, audit-only
  vs enforce-mode).
- Tomás Tag-41: PR #265 substrate
  (`wirelang/persona_engine/publish_mode_contract.py`) — the
  Bug-42 compatibility matrix that this audit enforces structurally.
- Kai Container-Bridge — when the audit gains a CI workflow,
  the workflow's required-status-check name must be coordinated
  with branch-protection (Zone J).

— Selin
