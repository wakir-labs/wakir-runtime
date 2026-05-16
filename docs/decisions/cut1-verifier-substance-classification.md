# Cut-1 Verifier-Substance-Klassifikation

**Datum:** 2026-05-16
**Trigger:** ADR-0062 Phase-2 Cut-1 (`wakir-verify` Apache-2.0)
**Autor:** Tomás Reinhart (Dev-Engineering, Matrix-Lead)
**ADR-Anker:** ADR-0034 §3.1, ADR-0062 "Cut 1", ADR-0061 (License-Hygiene Phase-1)

## Zweck

Inventar der Verifier-Substanz in `wakir-labs/wakir-runtime` mit
Klassifikation **Brand-Beweis-Werkzeug** (Apache-2.0, Migration nach
`wakir-verify`) vs. **Hosted-Service-Substrat** (BUSL-1.1, bleibt in
wakir-runtime). Re-Klassifikationen sind Mira-Hand-autorisiert via
ADR-0062 §"Cut 1 Source-Origin"-Erweiterung in Verbindung mit
ADR-0034 §3.1.

## Klassifikations-Kriterien

- **Brand-Beweis-Werkzeug (Apache-2.0):** verifiziert Audit-Trails
  stand-alone, kein hosted-service-Bezug, offline-fähig,
  Trust-Anchor-Substrat das Adopter ohne Wakir-Runtime
  reproduzieren können müssen.
- **Hosted-Service-Substrat (BUSL-1.1):** Multi-Tenant-Worker,
  anchor-pipeline-Server-Side, Operator-Convenience, läuft gegen
  Wakir-Runtime-Manifest-Store.

## Inventar-Tabelle

| Pfad | Aktueller SPDX | Soll-SPDX | Klassifikation | Begründung |
|---|---|---|---|---|
| `wat/anchor/external_verifier/__init__.py` | Apache-2.0 | Apache-2.0 | Brand-Beweis | 4-Pol-External-Verifier, offline gegen Bitcoin-Anchor + OTS-Receipt. Adopter-MVP. Migration nach `wakir_verify/`. |
| `wat/anchor/external_verifier/aggregator.py` | Apache-2.0 | Apache-2.0 | Brand-Beweis | 4-Pol-Quorum-Aggregator (n-von-m). Migration nach `wakir_verify/aggregator.py`. |
| `wat/anchor/external_verifier/cli.py` | Apache-2.0 | Apache-2.0 | Brand-Beweis | CLI-Entry `wat-verify` → wird zu `wakir-verify`. Migration nach `wakir_verify/cli.py`. |
| `wat/anchor/external_verifier/poles.py` | Apache-2.0 | Apache-2.0 | Brand-Beweis | 4 Pol-Implementations (Python-Stdlib, OTS-CLI, Mempool.space, Esplora). Migration nach `wakir_verify/poles.py`. |
| `wat/anchor/external_verifier/types.py` | Apache-2.0 | Apache-2.0 | Brand-Beweis | PoleResult-Datacls. Migration nach `wakir_verify/types.py`. |
| `wat/merkle/aggregator.py` | BUSL-1.1 | **Apache-2.0** | Brand-Beweis (Read-Half) | Re-Klassifikation: Merkle-Tree-Read-Half (Bitcoin-Pattern duplicate-and-pair) ist offline verifizierbarer Trust-Anchor, kein hosted-service. Write-Half bleibt in wakir-runtime hosted-pipeline. Migration nach `wakir_verify/merkle_proof.py`. |
| `wat/merkle/__init__.py` | BUSL-1.1 | **Apache-2.0** | Brand-Beweis | Re-Klassifikation: Modul-Surface für Read-Half. Migration nach `wakir_verify/merkle_proof.py` (konsolidiert). |
| `wat/verify/__init__.py` | BUSL-1.1 | BUSL-1.1 | Hosted-Service | Server-side WAT-Manifest-Verifikations-Modul. Bleibt in wakir-runtime. |
| `wat/verify/cli.py` | BUSL-1.1 | BUSL-1.1 | Hosted-Service | Docstring explizit: *"operator-facing convenience verifier (BSL 1.1) that runs against the local manifest store. The public, offline brand-proof verifier ships separately under `wakir_verify/` in Apache-2.0 form"*. Bleibt. |
| `wat/verify/manifest_v2.py` | BUSL-1.1 | BUSL-1.1 | Hosted-Service | 2566 LOC, abhängig von `wat.identity.manifest_signing` (BUSL) + `wat.merkle.aggregator` (Re-Klassifikation auf Apache wäre möglich, aber Substanz ist primär Schema-Validator gegen hosted-Manifest-Store). Cut-1: bleibt. Cut-2 Kandidat falls Brand-Beweis-Bedarf wächst. |
| `tests/wat/external_verifier/*` | Apache-2.0 | Apache-2.0 | Brand-Beweis | Test-Suite zum External-Verifier. Migration mit Substanz. |
| `tests/wat/external_verifier/witness_captures/*` | Apache-2.0 | Apache-2.0 | Brand-Beweis | Test-Vectors (echte Bitcoin-Block-Witness-Captures). Migration mit. |

## Migrations-Plan (Cut-1 0.1.0)

Apache-Substanz konsolidiert nach `wakir-labs/wakir-verify`:

```
wakir_verify/
  __init__.py        # Modul-Surface, SPDX Apache-2.0
  cli.py             # ex wat/anchor/external_verifier/cli.py
  aggregator.py      # ex wat/anchor/external_verifier/aggregator.py
  poles.py           # ex wat/anchor/external_verifier/poles.py
  types.py           # ex wat/anchor/external_verifier/types.py
  merkle_proof.py    # ex wat/merkle/aggregator.py + __init__.py (konsolidiert, BUSL→Apache)
  manifest.py        # MVP-Standalone-Manifest-Reader (neue Datei, minimaler v1-Envelope-Parser)
  ots_verify.py      # Convenience-Wrapper um aggregator+poles für OTS-CLI-Flow
  bitcoin_header.py  # MVP-Bitcoin-Block-Header-Decoder (neue Datei, stdlib-only)
  format.py          # Output-Format JSON/Text (ex Anteile aus external_verifier/cli.py)

tests/
  test_aggregator.py
  test_cli.py
  test_cli_text_mode.py
  test_multi_pol_determinismus.py
  test_poles.py
  test_property_hypothesis.py
  test_python_bitcoinlib_drift.py
  test_witness_captures.py
  test_manifest.py        # neu, MVP-coverage
  test_merkle_proof.py    # neu, MVP-coverage
  fixtures/               # ex tests/wat/external_verifier/fixtures.py + witness_captures/
```

Cross-Repo-Import-Adaption: `wakir-runtime`-Code, der bisher
`wat.anchor.external_verifier.*` importiert hat, wird in einem
Folge-Sprint auf `wakir_verify.*` umgestellt (Reza-Hand pro
ADR-0062 §Cut-1-Folgeartefakte). Dieses File dokumentiert nur die
Substanz-Klassifikation, nicht die Adapter-Welle.

## Risiken

- **Cross-Repo-Dependency-Drift:** Tests in `wakir-runtime` die
  bisher `from wat.anchor.external_verifier import ...` nutzten,
  laufen weiter, weil Source-Code bleibt parallel im wakir-runtime
  noch eine Welle. Removal-Welle ist Cut-1-Folgesprint nach Adopter-
  Feedback (~1 Woche).

- **Merkle-Read-Half-Re-Klassifikation BUSL→Apache:** partial-
  irreversibel per ADR-0034 §1.1. Apache-Snapshot des Codes wird
  dauerhaft. Aber: Read-Half ist konzeptionell offline-verifizierbar
  und gehört per Brand-Aussage 1 (*"Methodik überprüfbar via Repo-
  Commits + OTS-Stamps"*) public.

- **Initial 0.1.0 Scope:** Nur Apache-Bereits-Klassifizierte +
  Merkle-Read-Half. Weitergehende v2-Manifest-Schema-Validierung
  bleibt Cut-2-Kandidat — vermeidet 2566-LOC-Migration-Risk im
  Initial-Cut.

## Verweise

- ADR-0034 §3.1 — Tier-1-Apache-Klassifikation `wakir-verify` CLI
- ADR-0061 — License-Hygiene-Welle Phase-1
- ADR-0062 — Cut-1 Phase-2-Repo-Split-Strategie
