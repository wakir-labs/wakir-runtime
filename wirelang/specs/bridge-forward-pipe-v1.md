# Bridge-Forward-Pipe — Doppelbetrieb-Auftrags-Mirror Spec (v1)

**Spec ID:** `wirelang/specs/bridge-forward-pipe-v1`
**Status:** Draft (Sprint-10 Tag-6 substrate-closer)
**Owner:** Tomás Reinhart (Dev-Engineering / Matrix-Lead Bridge-Audit)
**Cross-Review:** Kai (Zone-I federation-substrate), Reza (Zone-B Wirelang
schema), Selin (Zone-K persona-engine-bridge).
**Date:** 2026-05-15
**Anchor schemas:** `wirelang/schemas/layer-1-wire.json` v0.1.0 (envelope),
`wirelang/nats/subject_mapping.py` (`agent` domain).

SPDX-License-Identifier: Apache-2.0

---

## 1 / Scope and Problem

ADR-0058 §Pilot-Phase introduces a 4-week Doppelbetrieb-Vergleich: every
engineering Auftrag for the Tomás-Persona is meant to run **twice in
parallel** — once on the Pre-Framework Tomás-Spawn (Mira-Sandbox) and
once on the Wakir-Runtime Tomás-Container (Pilot-VM `wakir-pilot`). The
two outputs feed a 4-axis comparison (functional equivalence, latency,
cost, audit-trail completeness).

The Sprint-Pengine-8 substrate (PR #65, commit `4ca16ed`) wires the
**output-side**: the Wakir-Runtime Tomás-Container emits one
`engineering-output` envelope per tool-call to the Bridge-Audit-Writer.

**Gap (uncovered 2026-05-15 Schritt 9 Live-Bring-up):** the **input-side**
has no plumbing. When Mira invokes the Pre-Framework Tomás-Spawn via
``Agent(subagent_type=dev-engineering, prompt=...)``, the prompt goes
straight to the Sandbox. The Wakir-Runtime Tomás-Container subscribes
to nothing — it has no way to see the Auftrag and therefore cannot
mirror the work.

This spec defines the **Bridge-Forward-Pipe**: a NATS-publish that
mirrors every Mira-initiated engineering Auftrag onto a subject the
Wakir-Runtime persona-engine subscribes to. With the output-side
already wired, this closes the loop and unlocks the Doppelbetrieb-
Vergleich-4-Wochen-Clock.

---

## 2 / Subject Convention

The forward-pipe reuses the existing `agent` domain (§4 of
`nats-subject-mapping-v1.md`) and the `agent.task.assigned`
event-type (§5.5). The persona-slug `<sub_id>` scopes the subject
per persona for permission-grain (§7.3 W7).

### 2.1 Subject — Auftrag (Mira → Wakir-Runtime)

Canonical form:

```
wakir.<env>.agent.agent.task.assigned.<persona-slug>
```

Concrete instance for the Tomás-Pilot:

```
wakir.dev.agent.agent.task.assigned.tomas
```

Wildcards (per §7.2 W4, W5):

- Single-persona subscribe: `wakir.dev.agent.agent.task.assigned.tomas`
- All-persona subscribe (audit-side): `wakir.dev.agent.>`

### 2.2 Subject — Engineering-Output (existing; Bridge-Audit-Writer)

The Wakir-Runtime persona-engine already emits structured-log JSON via
the Bridge-Audit-Writer (`wirelang/persona_engine/bridge_audit_writer.py`).
The Sprint-9 Tag-1 forwarder chain (Selin OI-PEF-13) lifts those
emissions into the NATS-KV state-pack bucket. The natural
companion-subject (when the persona-engine publishes directly to
NATS instead of letting the forwarder chain transcribe) is:

```
wakir.dev.agent.agent.task.completed.<persona-slug>
```

The output-side wiring is OUT of scope for this spec — Selin OI-PEFR-3
async-engine-wrapper owns it (Sprint-Pengine-9). This spec covers ONLY
the input-side forward (Mira-publish).

---

## 3 / Payload Schema

The forward-pipe payload is a JCS-canonical JSON envelope on the
Layer-1 wire format. Schema anchor:
`wirelang/schemas/agent-task-assigned/0.1.0` (new schema, this spec).

### 3.1 Envelope shape

```json
{
  "schema": "wakir.agent.task-assigned/1",
  "event_kind": "agent.task.assigned",
  "org_id": "acme",
  "persona_id": "tomas",
  "auftrag_id": "<uuid-or-counter>",
  "ts_utc": "2026-05-15T16:55:00Z",
  "source": "mira-sandbox",
  "prompt_sha256": "sha256:<64hex>",
  "prompt_payload": "<auftrag text, UTF-8>",
  "metadata": {
    "sprint": "sprint-10",
    "tag": "tag-6",
    "subagent_type": "dev-engineering",
    "pilot_mode": "doppelbetrieb-shadow"
  }
}
```

### 3.2 Field semantics

| Field | Type | Required | Semantics |
|---|---|---|---|
| `schema` | string | yes | Schema-id literal, this spec's anchor. |
| `event_kind` | string | yes | Always `agent.task.assigned` for forward-pipe payloads. |
| `org_id` | string | yes | Pilot uses `acme`. Multi-org Phase-3a opens this slot. |
| `persona_id` | string | yes | Persona-slug, lowercase (e.g. `tomas`). |
| `auftrag_id` | string | yes | Operator-chosen ID; ULID/UUID/Sprint-tag-counter. Round-trip key. |
| `ts_utc` | RFC3339 string | yes | UTC, `Z` suffix, second-precision. |
| `source` | enum | yes | `mira-sandbox` (Pre-Framework-side) or `manual-cli` (operator-injected). |
| `prompt_sha256` | hex string | yes | `sha256:<64hex>` of UTF-8 prompt bytes. |
| `prompt_payload` | string | yes | The Auftrag text itself. UTF-8. |
| `metadata` | object | no | Free-form key/value; Wakir-Runtime side does NOT consume — pass-through for audit-trail. |

### 3.3 Size envelope

- `prompt_payload` MUST NOT exceed 256 KiB (NATS default max-payload is
  1 MiB on a Phase-2 cluster; we leave headroom for envelope + metadata).
- `auftrag_id` MUST be ≤ 64 octets.
- `metadata` MUST be ≤ 8 KiB JCS-serialised.

A publisher that exceeds the size envelope MUST emit a
`SizeLimitError` and refuse the publish. (The persona-engine cannot
chunk-reassemble at the subscribe-side and the audit-trail wants
event-atomicity.)

---

## 4 / Publisher (Mira-Side)

### 4.1 CLI surface

```
bin/wakir-bridge-forward
  --persona-slug tomas
  --auftrag-id   sprint-10-tag-6
  --prompt-file  /path/to/prompt.txt    # OR --prompt-stdin
  [--env         dev]                    # default: dev
  [--org-id      acme]                   # default: acme
  [--source      mira-sandbox]           # default: mira-sandbox
  [--nats-url    nats://wakir-nats:4222] # default: env WAKIR_NATS_URL
  [--metadata    key=value ...]
  [--dry-run]                            # print envelope, do not publish
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Publish acknowledged by NATS server. |
| 1 | Argument-error / pre-flight failure. |
| 2 | Size-envelope exceeded (§3.3). |
| 3 | NATS-publish failure (network, ack timeout, permission). |

### 4.2 Continuous-Mode invariant

The Bridge-Forward-CLI is **fire-and-forget** at the operator level:
publish-and-return. No subscribe-side ack required (the Wakir-Runtime
side's processing of the Auftrag is async; its output lands on the
companion engineering-output subject, picked up by the
Doppelbetrieb-Score-CLI).

If the NATS server is unreachable, the CLI fails fast (exit 3). The
operator (Mira-Hand) re-runs after the substrate is back up;
Continuous-Mode-disposition is "log and proceed", never block the
Pre-Framework Tomás-Spawn on a forward-pipe glitch.

---

## 5 / Subscriber (Wakir-Runtime-Side)

OUT of scope for this spec. The async-engine-wrapper (Selin OI-PEFR-3,
Sprint-Pengine-9) owns the subscribe-loop. The contract this spec
establishes:

- The persona-engine MUST subscribe to
  `wakir.<env>.agent.agent.task.assigned.<persona-slug>` where
  `<persona-slug>` is the value of `WAKIR_PERSONA_ID` and `<env>` is
  read from a new env-var `WAKIR_ENV` (default `dev`).
- The persona-engine MUST treat every received envelope as a spawn-
  step trigger. The engine MUST emit a corresponding
  `engineering-output` envelope (via Bridge-Audit-Writer) carrying the
  same `auftrag_id` in its metadata.
- The persona-engine MUST NOT retain `prompt_payload` beyond the
  spawn-session lifetime. The audit-trail keeps only the
  `prompt_sha256`.

---

## 6 / Doppelbetrieb-Score-CLI (Companion Tool)

The score-CLI compares two outputs (Pre-Framework + Wakir-Runtime) for
the same `auftrag_id` and emits a 4-axis Score-JSON for Mira-Hand
review (weekly Doppelbetrieb-Bilanz, ADR-0058 §Pilot-Phase Schritt 10).

### 6.1 CLI surface

```
bin/wakir-doppelbetrieb-score
  --auftrag-id   sprint-10-tag-6
  --preframework /path/to/preframework-output.txt
  --wakir        /path/to/wakir-runtime-output.txt
  [--out         /path/to/score.json]      # default: stdout
```

### 6.2 4-Axis Score Schema

```json
{
  "schema": "wakir.doppelbetrieb.score/1",
  "auftrag_id": "sprint-10-tag-6",
  "ts_utc": "2026-05-15T18:00:00Z",
  "preframework": {
    "byte_len": 5421,
    "sha256": "sha256:<64hex>",
    "line_count": 142
  },
  "wakir_runtime": {
    "byte_len": 5398,
    "sha256": "sha256:<64hex>",
    "line_count": 138
  },
  "axes": {
    "functional_equivalence": {
      "value": 0.95,
      "method": "line-overlap-coefficient",
      "note": "0.95 = 95% of preframework lines have a near-match in wakir output"
    },
    "byte_delta": {
      "value": 23,
      "method": "abs(preframework.byte_len - wakir.byte_len)"
    },
    "structural_equivalence": {
      "value": 1.0,
      "method": "code-block-count-match"
    },
    "spurious_divergence": {
      "value": 0,
      "method": "count of lines unique to wakir that don't appear anywhere in preframework"
    }
  },
  "verdict": "pass-with-drift"
}
```

### 6.3 Score-CLI Implementation Floor

The score-CLI is intentionally **simple** for v1:
- Line-overlap-coefficient (no embedding-based similarity, no LLM-grader).
- Pure-text comparison; no AST-parse for code blocks (just count
  triple-backtick fences).
- Verdict mapping:
  - `functional_equivalence >= 0.95` and `byte_delta < 1024` → `pass`
  - `functional_equivalence >= 0.80` → `pass-with-drift`
  - else → `fail`

Mira-Hand-Bilanz can override the verdict at the weekly review.

---

## 7 / Cross-Review Hooks

### 7.1 Zone-I (Kai — Federation-Substrate-Ops)

- **H-1.** Subject-pattern conforms to `agent`-domain reservations
  (§4 of nats-subject-mapping-v1.md).
- **H-2.** Account-permission grant: Mira's NATS-publish credential
  needs `publish=wakir.dev.agent.>` (or scoped per-persona-slug).
  Phase-1b token-auth: this is the operator-edit. Phase-2 JWT-SVID:
  the persona-engine's SVID gains a `caveats.publish` glob.

### 7.2 Zone-B (Reza — Wirelang Schema)

- **H-3.** New schema `wakir.agent.task-assigned/1` follows the
  layer-1-wire envelope shape. Reza-side may want to formalise the
  schema in `wirelang/schemas/agent-task-assigned.json` (out-of-scope
  for this PR; document the field-shape here, schema-formalisation
  in a follow-up).

### 7.3 Zone-K (Selin — Persona-Engine-Bridge)

- **H-4.** OI-PEFR-3 subscribe-loop contract (§5): the engine MUST
  subscribe to the canonical subject and MUST honour the
  `auftrag_id`-pass-through into engineering-output metadata.

---

## 8 / Open Items (Sprint-Tag-Folge)

- **OI-1.** Schema-formalisation (Reza Zone-B follow-up):
  `wirelang/schemas/agent-task-assigned.json` with full JCS-canonical
  pattern, additionalProperties: false on the metadata.
- **OI-2.** JWT-SVID caveat-grant for Mira-publish (Phase-2 transport):
  the trust-domain admin must issue a `publish=wakir.<env>.agent.>`
  caveat on Mira's SVID. Pre-Phase-2: the token-auth path
  (NATS_TOKEN env-var) is sufficient.
- **OI-3.** Multi-persona forward (Reza, Lena, Selin pilot-spawns):
  once additional personas pilot, this spec applies as-is — the
  subject hierarchy already supports `<persona-slug>` wildcards.

---

## 9 / Verification Stamp

- `date -u` 2026-05-15T17:30:00Z.
- Schema-regex compatibility check (`wirelang/nats/subject_mapping.py`
  RESERVED_DOMAINS): `agent` is present. RESERVED_EVENT_TYPES['agent']
  contains `agent.task.assigned`. Spec narrows; does not widen.
- Memory anchor `feedback_live_bringup_sandbox_gap.md` — this spec
  closes the input-side plumbing gap discovered in 2026-05-15 Schritt
  9 Live-Bring-up.

— Tomás
