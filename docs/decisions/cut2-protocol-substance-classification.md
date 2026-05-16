# Cut-2 Protocol-Substance-Klassifikation

**Datum:** 2026-05-16
**Trigger:** ADR-0062 Phase-2 Cut-2 (`wakir-protocol` Apache-2.0 + CC-BY-4.0)
**Autor:** Tomás Reinhart (Dev-Engineering, Matrix-Lead)
**ADR-Anker:** ADR-0034 §3.3, ADR-0062 "Cut 2", ADR-0061 (License-Hygiene Phase-1)

## Zweck

Inventar der Wirelang/Capability-Token/Identity-Substrate-Substanz in
`wakir-labs/wakir-runtime` mit Klassifikation **Protocol-Layer** (Apache-2.0
bzw. CC-BY-4.0, Konsolidation nach `wakir-protocol`) vs.
**Runtime-Internal-Implementation** (BUSL-1.1, bleibt in wakir-runtime).

Cut-2-Konsolidations-Modus ist **Kopie** in wakir-protocol mit
Re-Strukturierung des Package-Layouts (`wakir_protocol/`-Namespace).
Cross-Repo-Import-Adaption in wakir-runtime (`wirelang.* → wakir_protocol.*`)
ist Folge-Sprint (Reza-Hand pro ADR-0062 §Cut-2-Folgeartefakte) — analog
Cut-1-Pattern.

## Klassifikations-Kriterien

- **Protocol-Layer (Apache-2.0):** Spec-Anker, Reference-Parser-Logik,
  Schema-Validatoren, Standards-Adoption-Substrate (AIP, Biscuit,
  DID-Methode, BIP32-HD). Adopter müssen diese ohne Wakir-Runtime
  reproduzieren können.
- **Protocol-Spec (CC-BY-4.0):** Prosa-Spec-Dokumente in `wirelang/specs/`.
  File-level SPDX, getrennt von Code.
- **Runtime-Internal-Implementation (BUSL-1.1):** Multi-Org-Federation-
  Substrate, Persona-Engine-Orchestrator, KV-State-Backings, Marker-Stack-
  Reducer mit Cross-Org-Semantik. Bleibt in wakir-runtime.

## Inventar-Tabelle

### A) `wirelang/canonical/` — JCS-Canonical-Form (Apache → wakir-protocol)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/canonical/caveat_set.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/canonical/caveat_set.py` |
| `wirelang/canonical/__init__.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/canonical/__init__.py` |

### B) `wirelang/identity/` — Identity-Substrate (Apache → wakir-protocol, selektiv)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/identity/aip_document.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/aip_document.py` |
| `wirelang/identity/aip_document_transport_fetch.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/aip_document_transport_fetch.py` |
| `wirelang/identity/aip_https_backend.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/aip_https_backend.py` |
| `wirelang/identity/aip_signature_verification_cache.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/aip_signature_verification_cache.py` |
| `wirelang/identity/aip_signing.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/aip_signing.py` |
| `wirelang/identity/did_document.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/did_document.py` |
| `wirelang/identity/did_document_signing.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/did_document_signing.py` |
| `wirelang/identity/dns_anchor.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/dns_anchor.py` |
| `wirelang/identity/ftd_verifier.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/ftd_verifier.py` |
| `wirelang/identity/_jcs_pure.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/_jcs_pure.py` |
| `wirelang/identity/key_derivation.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/key_derivation.py` |
| `wirelang/identity/kid_resolver.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/kid_resolver.py` |
| `wirelang/identity/recovery_drill.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/recovery_drill.py` |
| `wirelang/identity/_schema_pure.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/_schema_pure.py` |
| `wirelang/identity/shamir_split.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/shamir_split.py` |
| `wirelang/identity/verify_bridge.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/verify_bridge.py` |
| `wirelang/identity/__init__.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/identity_substrate/__init__.py` (re-export adapter) |
| `wirelang/identity/federation_resolver.py` | BUSL-1.1 | BUSL-1.1 | Runtime-Internal | bleibt in wakir-runtime |

### C) `wirelang/schemas/` — JSON-Schemas + Schema-Registry-Adapters

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/schemas/*.json` (16 files) | (description-Feld) | Apache-2.0 (top-level `x-spdx-license-identifier`) | Protocol-Layer | `wakir_protocol/schemas/*.json` mit Refactor: SPDX-Property statt description-string (externe Audit-Empfehlung #6) |
| `wirelang/schemas/__init__.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/schemas/__init__.py` |
| `wirelang/schemas/entry_signing.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/schemas/entry_signing.py` |
| `wirelang/schemas/capability_policy_nats_kv_backend.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer (Adapter-Interface) | `wakir_protocol/schemas/capability_policy_nats_kv_backend.py` |
| `wirelang/schemas/capability_policy_replication.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/schemas/capability_policy_replication.py` |
| `wirelang/schemas/publisher_cli.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer (CLI) | `wakir_protocol/schemas/publisher_cli.py` |
| `wirelang/schemas/registered_by_capability.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/schemas/registered_by_capability.py` |
| `wirelang/schemas/registry_nats_kv_backend.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/schemas/registry_nats_kv_backend.py` |
| `wirelang/schemas/replication.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/schemas/replication.py` |

### D) `wirelang/builder/` — Frame-Builder (Layer-1)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/builder/frame_builder.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/wirelang/frame_builder.py` |
| `wirelang/builder/__init__.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/wirelang/__init__.py` (mit re-exports) |

### E) `wirelang/persona/` — Persona-Spec-Layer (selektiv Apache)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/persona/persona_canonical_form.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer (Spec-Anker JCS) | `wakir_protocol/persona/persona_canonical_form.py` |
| `wirelang/persona/persona_hash.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer (Spec-Anker) | `wakir_protocol/persona/persona_hash.py` |
| `wirelang/persona/persona_migration.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/persona/persona_migration.py` |
| `wirelang/persona/persona_validator.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/persona/persona_validator.py` |
| `wirelang/persona/cli.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer (Persona-Validator-CLI) | `wakir_protocol/persona/cli.py` |
| `wirelang/persona/__init__.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/persona/__init__.py` |
| `wirelang/persona/_internal/` (private interna) | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/persona/_internal/` |
| `wirelang/persona/persona_state_kv.py` | BUSL-1.1 | BUSL-1.1 | Runtime-Internal | bleibt |
| `wirelang/persona/persona_state_kv_constants.py` | BUSL-1.1 | BUSL-1.1 | Runtime-Internal | bleibt |
| `wirelang/persona/recovery_drill_anchor.py` | BUSL-1.1 | BUSL-1.1 | Runtime-Internal | bleibt |

### F) `wirelang/nats/` — NATS-Subject-Mapping (Layer-0 Spec)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/nats/subject_mapping.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer (Layer-0-Spec) | `wakir_protocol/wirelang/nats_subject_mapping.py` |
| `wirelang/nats/__init__.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | (merged into `wakir_protocol/wirelang/__init__.py`) |

### G) `wirelang/cli/` — CLI-Tools (selektiv)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/cli/bridge_forward.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer (Layer-1 publisher) | `wakir_protocol/cli/bridge_forward.py` |
| `wirelang/cli/doppelbetrieb_aggregate.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/cli/doppelbetrieb_aggregate.py` |
| `wirelang/cli/doppelbetrieb_score.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/cli/doppelbetrieb_score.py` |
| `wirelang/cli/mira_dispatch.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/cli/mira_dispatch.py` |
| `wirelang/cli/__init__.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/cli/__init__.py` |
| `wirelang/cli/marker_stack_emit.py` | BUSL-1.1 | BUSL-1.1 | Runtime-Internal | bleibt |
| `wirelang/cli/marker_stack_reduce.py` | BUSL-1.1 | BUSL-1.1 | Runtime-Internal | bleibt |

### H) `wirelang/adapters/` — SPIFFE-Workload-API-Adapter (Layer-0-Interface)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/adapters/spiffe_workload_api.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer (Stub+Interface) | `wakir_protocol/adapters/spiffe_workload_api.py` |
| `wirelang/adapters/real_spiffe_workload_api.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/adapters/real_spiffe_workload_api.py` |
| `wirelang/adapters/__init__.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer | `wakir_protocol/adapters/__init__.py` |
| `wirelang/adapters/real_nats_adapter/` | (mixed) | Apache-2.0 (Stub-Anteil) | Protocol-Layer | `wakir_protocol/adapters/real_nats_adapter/` |

### I) `wirelang/specs/` — Prose-Spec-Dokumente (CC-BY-4.0)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/specs/wirelang-spec-v0-2.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/wirelang-spec-v0-2.md` |
| `wirelang/specs/identity-substrate.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/identity-substrate-spec.md` |
| `wirelang/specs/layer-0-2-overview.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/layer-0-2-overview.md` |
| `wirelang/specs/layer-3-capability-token.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/layer-3-capability-token-spec.md` |
| `wirelang/specs/datalog-caveat-vocabulary.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/datalog-caveat-vocabulary.md` |
| `wirelang/specs/datalog-caveat-vocabulary-phase-2.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/datalog-caveat-vocabulary-phase-2.md` |
| `wirelang/specs/nats-subject-mapping-v1.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/nats-subject-mapping-v1.md` |
| `wirelang/specs/persona-engine-format-spec.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/persona-engine-format-spec.md` |
| `wirelang/specs/persona-hash-spec.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/persona-hash-spec.md` |
| `wirelang/specs/persona-schema-v10-migration-vorbereitung.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/persona-schema-v10-migration.md` |
| `wirelang/specs/recovery-drill-leaf-projection.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/recovery-drill-leaf-projection.md` |
| `wirelang/specs/schema-registry-spec.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/schema-registry-spec.md` |
| `wirelang/specs/self-migration-konverter-spec.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/self-migration-konverter-spec.md` |
| `wirelang/specs/wat-leaf-projection.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/wat-leaf-projection.md` |
| `wirelang/specs/wirelang-tv-strategy.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/wirelang-tv-strategy.md` |
| `wirelang/specs/bridge-forward-pipe-v1.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/bridge-forward-pipe-v1.md` |
| `wirelang/specs/datalog-caveat-vocabulary-phase-2-skizze.md` | (file-level) | CC-BY-4.0 | Protocol-Spec | `docs/datalog-caveat-vocabulary-phase-2-skizze.md` |

### J) `wirelang/examples/` — Example-JSON-Vectors

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/examples/*.json` (6 files) | n/a (JSON) | Apache-2.0 | Protocol-Layer (Test-Vectors) | `wakir_protocol/examples/*.json` |

### K) Federation + Persona-Engine — Runtime-Internal (BUSL bleibt)

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Bleibt |
|---|---|---|---|---|
| `wirelang/federation/**` (17 files) | BUSL-1.1 | BUSL-1.1 | Runtime-Internal (Multi-Org-Federation, Phase-3) | wakir-runtime |
| `wirelang/persona_engine/**` (17 files) | BUSL-1.1 | BUSL-1.1 | Runtime-Internal (Persona-Engine-Orchestrator) | wakir-runtime |

### L) Tests — Selektive Migration

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Ziel |
|---|---|---|---|---|
| `wirelang/tests/test_identity_*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_identity_*.py` |
| `wirelang/tests/test_aip_*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_aip_*.py` |
| `wirelang/tests/test_did_*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_did_*.py` |
| `wirelang/tests/test_schema_registry_*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_schema_registry_*.py` |
| `wirelang/tests/test_frame_builder.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_frame_builder.py` |
| `wirelang/tests/test_layer_*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_layer_*.py` |
| `wirelang/tests/test_persona_canonical_form_jcs.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_persona_canonical_form_jcs.py` |
| `wirelang/tests/test_persona_hash.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_persona_hash.py` |
| `wirelang/tests/test_persona_migration*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_persona_migration*.py` |
| `wirelang/tests/test_persona_validator*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_persona_validator*.py` |
| `wirelang/tests/test_nats_subject_mapping.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_nats_subject_mapping.py` |
| `wirelang/tests/test_datalog_*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_datalog_*.py` |
| `wirelang/tests/test_recovery_drill.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_recovery_drill.py` |
| `wirelang/tests/test_shamir_split.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_shamir_split.py` |
| `wirelang/tests/test_bip32_full_vectors.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_bip32_full_vectors.py` |
| `wirelang/tests/test_slip0010_*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests | `tests/test_slip0010_*.py` |
| `wirelang/tests/test_tv_w_*.py` | Apache-2.0 | Apache-2.0 | Protocol-Layer-Tests (Spec-Test-Vectors) | `tests/test_tv_w_*.py` |
| `wirelang/tests/fixtures/tv-w-{1,2,3}/` | n/a | Apache-2.0 (test-vectors) | Protocol-Layer-Test-Fixtures | `tests/fixtures/tv-w-{1,2,3}/` |
| `wirelang/tests/test_federation_*.py` | (mixed) | (BUSL-Side bleibt) | Runtime-Internal-Tests | wakir-runtime |
| `wirelang/tests/test_multi_org_substrate.py` | BUSL-1.1 | BUSL-1.1 | Runtime-Internal-Tests | wakir-runtime |
| `wirelang/tests/persona_engine/` | BUSL-1.1 | BUSL-1.1 | Runtime-Internal-Tests | wakir-runtime |

## Cut-2 Migration-Mode

**Kopie, nicht Move.** wakir-runtime behält Apache-Files für die
Übergangs-Zeit. Cross-Repo-Import-Adaption (wirelang.* → wakir_protocol.*)
in wakir-runtime ist Folge-Sprint (Reza-Hand).

**Rationale:** Single-Welle-Move würde Federation- und Persona-Engine-Tests
(BUSL-Internal, hängen am Apache-Substrat) breaken. Cut-1-Pattern war
gleich. Adapter-Welle als Cut-2-Folge-Item.

## Re-Strukturierung: Package-Layout `wakir_protocol/`

```
wakir_protocol/
├── __init__.py
├── canonical/           # ex wirelang/canonical/
├── identity_substrate/  # ex wirelang/identity/ (Apache-Files ohne federation_resolver)
├── persona/             # ex wirelang/persona/ (Apache-Files ohne state_kv/recovery_anchor)
├── schemas/             # ex wirelang/schemas/ (Apache, JSON-Schemas refactored)
├── adapters/            # ex wirelang/adapters/
├── cli/                 # ex wirelang/cli/ (Apache-Files ohne marker_stack_*)
├── examples/            # ex wirelang/examples/
└── wirelang/            # ex wirelang/builder/ + wirelang/nats/ konsolidiert
    ├── __init__.py
    ├── frame_builder.py
    └── nats_subject_mapping.py
```

## Cross-Repo-Imports (für Folge-Sprint)

Reza-Hand-Adapter-Welle nach Cut-2-Stabilisation:

- `from wirelang.canonical import caveat_set` → `from wakir_protocol.canonical import caveat_set`
- `from wirelang.identity import aip_document` → `from wakir_protocol.identity_substrate import aip_document`
- `from wirelang.schemas import ...` → `from wakir_protocol.schemas import ...`
- `from wirelang.persona import persona_validator` → `from wakir_protocol.persona import persona_validator`
- `from wirelang.builder import frame_builder` → `from wakir_protocol.wirelang import frame_builder`
- `from wirelang.nats import subject_mapping` → `from wakir_protocol.wirelang import nats_subject_mapping`

Runtime-Internal Imports unverändert:
- `wirelang.federation.*` bleibt (BUSL)
- `wirelang.persona_engine.*` bleibt (BUSL)
- `wirelang.identity.federation_resolver` bleibt (BUSL)
- `wirelang.persona.persona_state_kv*` bleibt (BUSL)
- `wirelang.cli.marker_stack_*` bleibt (BUSL)

## JSON-Schema-Refactor (externe Audit-Empfehlung #6)

Aktuelle Pattern (description-Feld mit SPDX-Text) → REUSE-False-Positive.

**Soll-Pattern:**
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.wakirlabs.com/...",
  "x-spdx-license-identifier": "Apache-2.0",
  "x-spdx-file-copyright-text": "2026 Callandor GmbH and contributors",
  "title": "...",
  "description": "(SPDX entfernt, nur fachlicher Inhalt)",
  ...
}
```

Cut-2 Implementation: Migrations-Script `tools/refactor_schema_spdx.py` (im
wakir-protocol-Repo, optional in Cut-2-Tag-2 wenn Bedarf besteht), aktuell
manueller Refactor pro Schema-File beim Kopier-Schritt.

## Acceptance-Gates (Cut-2-Tag-1)

- [ ] Repo `wakir-labs/wakir-protocol` existiert public, Apache-2.0-
      LICENSE, CC-BY-4.0 für `docs/`.
- [ ] NOTICE-File, REUSE.toml mit Apache-2.0-Default + CC-BY-4.0-docs/.
- [ ] `pyproject.toml` mit `wakir-protocol@0.1.0`.
- [ ] Initial-Commit-Push erfolgreich.
- [ ] `pip install -e .` clean.
- [ ] `pytest tests/` grün, minimum 15 Test-Vektoren.
- [ ] wakir-runtime-Tests laufen weiter grün (Kopie, kein Move).
- [ ] Klassifikations-Doc committed in wakir-runtime/docs/decisions/.

## Cut-2-Folge-Items (außerhalb Cut-2-Tag-1)

- Reza-Hand: Cross-Repo-Import-Adaption (`wirelang.* → wakir_protocol.*`).
- Kai-Hand: GitHub-Actions-Workflow (CI pytest, REUSE-Lint, semver-tag-on-merge).
- Júlia-Hand: README + Marketing-Stub-Page wakirlabs.com `/protocol/`.
- Mira-Hand: PyPI-Package-Publish (initial `wakir-protocol@0.1.0`).

— Tomás

---

## Anhang A — Cut-2-Folge-Sprint-Befund (Reza-Hand, 2026-05-16)

**Trigger:** Cross-Repo-Import-Adaption-Sprint pro ADR-0062
§Cut-2-Folge-Items.

### A.1 Audit-Ergebnis Cross-Repo-Imports

Sichtung des wakir-runtime-Trees nach Python-Imports aus dem
konsolidierten Apache-Substrat (`wirelang.*`, `capability_token.*`,
`identity_substrate.*`) ergibt:

- **240+ `from wirelang.* import …`-Stellen** über 121 distinct
  Files, davon:
  - 119 Files innerhalb des `wirelang/`-Sub-Trees selbst (gemischter
    Apache + BUSL Subtree, Klassifikations-Tabellen A-L oben).
  - 2 Files unter `tests/infra/` (`test_doppelbetrieb_bridge_smoke.py`,
    `test_pilot_phase_e2e_smoke.py`), beide SPDX-`BUSL-1.1` und mit
    starkem BSL-Subtree-Bezug (Imports aus
    `wirelang.persona_engine.*`, das BUSL-1.1 ist und in
    wakir-runtime bleibt).
- **0 `from capability_token.* import …`-Stellen** —
  Capability-Token-Substrat existiert nur als
  `wakir_protocol.identity_substrate` / `wakir_protocol.canonical`
  Namespace, nicht als Top-Level-Package in wakir-runtime.
- **0 `from identity_substrate.* import …`-Stellen** — analog.
- **0 Apache-Top-Level-Python-Files mit `wirelang.*`-Imports**
  (`tooling/` ist JS-only, `scripts/` ist standalone-Python ohne
  wirelang-Abhängigkeit).

**Konsequenz für die Adapter-Welle:** Da keine Apache-Top-Level-
Python-Files `wirelang.*` importieren, gibt es keine substantielle
Import-Umstellung auf `wakir_protocol.*`. Die im Folge-Sprint-
Auftrag vorgesehene zweistufige Behandlung (BUSL-Subtree behält
`wirelang.*` mit Kommentar; Apache-Top-Level stellt um) reduziert
sich auf die erste Stufe.

### A.2 Behandlung des BUSL-Subtree-Anteils

Konsolidations-Hinweise wurden zu den 9 Apache-Hub-`__init__.py`-
Files unter `wirelang/` hinzugefügt (statt 240 Inline-Kommentaren
auf jeder Import-Stelle):

| Hub-File | Wakir-protocol-Ziel |
|---|---|
| `wirelang/__init__.py` | (Package-marker mit Top-Level-Hinweis) |
| `wirelang/canonical/__init__.py` | `wakir_protocol.canonical` |
| `wirelang/identity/__init__.py` | `wakir_protocol.identity_substrate` (minus `federation_resolver`) |
| `wirelang/persona/__init__.py` | `wakir_protocol.persona` (minus `persona_state_kv*`, `recovery_drill_anchor`) |
| `wirelang/schemas/__init__.py` | `wakir_protocol.schemas` |
| `wirelang/cli/__init__.py` | `wakir_protocol.cli` (minus `marker_stack_*`) |
| `wirelang/adapters/__init__.py` | `wakir_protocol.adapters` (Stub-Tier) |
| `wirelang/builder/__init__.py` | `wakir_protocol.wirelang` |
| `wirelang/nats/__init__.py` | `wakir_protocol.wirelang` |

Jeder Kommentar nennt explizit:
- Den ADR-Anker (ADR-0062 Cut-2, 2026-05-16).
- Den `wakir_protocol`-Ziel-Namespace.
- Die BUSL-Inseln, die NICHT in `wakir-protocol` mirroren.
- Die Empfehlung an externe Adopter: `wakir-protocol` direkt
  installieren statt aus wakir-runtime importieren.

### A.3 Klassifikations-Validation (SPDX-Header-Konsistenz-Audit)

Vollständiger SPDX-Header-Audit aller 215 Python-Files unter
`wirelang/` gegen die Klassifikations-Tabellen A-L:

- 132 Apache-2.0 + 83 BUSL-1.1 (100% Coverage, keine Files ohne
  SPDX-Header).
- **Kein einziger Widerspruch** zwischen tatsächlichem SPDX-Header
  und Klassifikations-Doc-Soll-SPDX.
- Insbesondere `wirelang/adapters/real_nats_adapter/` ist korrekt
  mixed: `__init__.py` Apache-2.0 (Stub-Tier-Re-Exports),
  `adapter.py`/`connect_retry.py` BUSL-1.1 (Live-Tier). Das
  entspricht Tabelle H ("mixed | Apache-2.0 (Stub-Anteil)") exakt.
- BUSL-Test-Files in `wirelang/tests/`
  (`test_federation_*.py`, `test_multi_org_substrate.py`,
  `test_spire_fed_bundle_live_https_fetcher.py`,
  `test_persona_state_kv_constants_parity.py`,
  `test_nats_connect_race_resilience.py`,
  `persona_engine/`) sind konsistent BUSL-1.1 und testen
  BUSL-Internal-Code.

**Befund:** Keine widersprüchliche SPDX/Klassifikations-Kombination
gefunden. Keine Mira-Hand-Folge-Patches benötigt.

### A.4 README-Status

`README.md §"Protocol-layer split (ADR-0062 Cut-2)"` wurde im
Source-PR #93 bereits gepflegt und nennt:
- den `wakir-protocol`-Repo,
- den Klassifikations-Doc-Link,
- das `[protocol]`-Extra (`pip install 'wakir-runtime[protocol]'`).

Da die Adapter-Welle keine substanzielle Import-Umstellung an
Top-Level-Code bewirkt hat, ist kein README-Folge-Eingriff in
diesem PR nötig. Reza notiert das ausdrücklich, damit Mira den
Status sieht.

### A.5 Tests post-Adaption

Smoke-Test lokal mit `pytest tests/wirelang/` und
`pytest wirelang/tests/` weiter grün — der Doc-String-Kommentar in
den 9 Hub-`__init__.py`-Files ändert keine Import-Mechanik. Volle
Test-Suite ist im PR-Body protokolliert.

— Reza
