<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Cross-Substrate Parity Runbook — 3-Way Inventory Pflicht

**Status:** Live (Tag-32 Mini-Welle, ADR-0066 Welle-3 Mitigation).
**Owner:** Kai (DevOps), Cross-Review Zone C (Tomás).
**Anchor-ADR:** ADR-0066 Welle-3 Mitigation, ADR-0065
Phase-3c Cutover-Sequenz.
**Gate:** `.github/workflows/cross-substrate-parity-gate.yml`
(Workflow-name: `cross-substrate-parity-gate`, job-display:
`cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)`).

---

## 1. Was ist die 3-Way-Inventory-Pflicht?

Der Phase-3b Rust-CLI Inventory wird in **drei** Substraten getragen.
Eine Drift zwischen ihnen ist die schlimmste Failure-Mode-Klasse
für Phase-3c Cutover, weil sie eine partielle Migration als
erfolgreiche disguised.

Die drei Substrate:

1. **Cosign-Policy** — `policies/cosign-policy-phase-3b.yaml`
   - Declarative Image-Verification-Substrate.
   - 9 Einträge unter `binaries[].name`.
2. **Quadlet-Installer** — `quadlet/wakir-rust-cli.container`
   - Host-Installations-Substrat (Container kopiert Binaries nach
     `/opt/wakir/bin/` auf den Host).
   - 9 Einträge im `Exec=`-Install-Loop als
     `wakir-persona-engine-<name>`.
3. **Backend-Switch Resolver** —
   `wirelang/persona_engine/rust_backend_switch.py`
   - Python-side Subprocess-Bridge-Resolver. Wählt zur Boot-Zeit
     pro Backend-Komponente Rust-Binary oder Python-Fallback.
   - 9 `DEFAULT_RUST_<NAME>_BIN`-Konstanten für die kanonischen 9
     Binaries.

**Kanonische 11-Binary-Inventory** (Phase-3b carrier-image set;
ursprünglich 9 bei Tag-31, auf 11 erweitert bei Tag-45 mit den
Phase-3a-Foundation 14 + 15 Closeout-Modulen `bridge-audit-replay`
und `migrate-version`):

| # | Component | Binary-Basename |
|---|-----------|-----------------|
| 1 | recovery | `wakir-persona-engine-recovery` |
| 2 | state-backing | `wakir-persona-engine-state-backing` |
| 3 | fsm | `wakir-persona-engine-fsm` |
| 4 | v907-verify | `wakir-persona-engine-v907-verify` |
| 5 | bridge-diff | `wakir-persona-engine-bridge-diff` |
| 6 | subscribe-loop | `wakir-persona-engine-subscribe-loop` |
| 7 | anchor-emitter | `wakir-persona-engine-anchor-emitter` |
| 8 | svid-workload-identity | `wakir-persona-engine-svid-workload-identity` |
| 9 | bridge-audit-writer | `wakir-persona-engine-bridge-audit-writer` |
| 10 | bridge-audit-replay | `wakir-persona-engine-bridge-audit-replay` (Tag-45) |
| 11 | migrate-version | `wakir-persona-engine-migrate-version` (Tag-45) |

---

## 2. Bekannte Divergenz (resolver-known-extras)

Der Backend-Switch-Resolver trägt **einen** zusätzlichen Eintrag
über die kanonischen 9 hinaus:

| Component | Binary-Basename | Grund der Divergenz |
|-----------|-----------------|----------------------|
| federation-resolver | `wakir-persona-engine-federation-resolver` | ADR-0066 §Welle-Sequenz: Welle-2-Scaffold; noch kein Image-Build, daher noch keine Cosign-Policy / Quadlet-Installer Entry. Wird mit Welle-N-Promotion lock-step in alle drei Substrate gehoben. |

Diese Divergenz ist explizit in der Test-Datei
`tests/infra/test_cross_substrate_parity_3way.py` als
`RESOLVER_KNOWN_EXTRAS` deklariert. Jeder andere extra Eintrag im
Resolver (oder jede Drift zwischen Cosign ↔ Quadlet) ist ein
**Hard-Fail** des CI-Gates.

---

## 3. CI-Gate-Verhalten

Der Workflow `cross-substrate-parity-gate.yml` triggert auf
Änderungen an einem der drei Substrate. Job:

- **Display-Name:** `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)`
- **Required-Status:** Initial **advisory** (analog zum
  hash-derivate-gate Pattern). Mira-Hand-Folge nach erstem grünen
  main-Run: Pflicht-Aktivierung als Required-Check in Branch-
  Protection (Operator-Hand, GitHub-Repo-Settings).
- **Test-Substrat:** `tests/infra/test_cross_substrate_parity_3way.py`
  (5 + 1 = 6 Tests, hermetic, kein Live-Network).

Bei einer Drift schlägt der Test 1 (`test_three_way_inventory_agreement`)
fehl und zeigt die Drift-Diagnose:

```
Resolver-Phase-3b inventory drift:
  expected ['anchor-emitter', 'bridge-audit-writer', ...]
  got      ['anchor-emitter', 'bridge-audit-writer', 'new-backend', ...]
  missing  []
  extra    ['new-backend']
```

---

## 4. Operator-Recipe: Welle-N Inventory-Erweiterung

Wenn eine neue Welle-N ein 10. (oder weiteres) Phase-3b-Binary
einführen will, gilt die **3-Way-Lock-Step-Pflicht**:

1. **Cosign-Policy:** Eintrag unter `binaries:` in
   `policies/cosign-policy-phase-3b.yaml` ergänzen
   (Name, expected_image_digest-Placeholder, env-switch,
   in_image_path).
2. **Quadlet-Installer:** Eintrag im `Exec=`-Loop und im
   leading-comment-Block in `quadlet/wakir-rust-cli.container`
   ergänzen.
3. **Backend-Switch-Resolver:** Eintrag als
   `DEFAULT_RUST_<NAME>_BIN`-Konstante in
   `wirelang/persona_engine/rust_backend_switch.py` ergänzen
   (sowie ENV-Var-Konstanten, Resolver-Funktion, Tests).
4. **Test-Tupel:** `EXPECTED_BINARIES_9` in
   `tests/infra/test_cross_substrate_parity_3way.py` **und**
   `EXPECTED_BINARIES` in `tests/infra/test_cosign_policy_phase_3b.py`
   in lock-step erweitern.
5. **Runbook:** Diesen Runbook-Tabellenabschnitt §1 erweitern.
6. **Tuple-Name:** Wenn der Inventory-Count != 9 wird, das Tupel
   in beiden Test-Files umbenennen (`EXPECTED_BINARIES_<N>`) und
   in Welle-N-Mini-Welle-Notiz dokumentieren.

Wenn alle 6 Schritte in einer Mini-Welle in **einer** PR landen,
bleibt der CI-Gate grün. Wenn auch nur einer fehlt, schlägt der
Gate fehl — das ist gewünscht.

---

## 5. Operator-Recipe: Resolver-only-Scaffold (Welle-N+1 Vorgriff)

Eine Welle-N-Vorbereitung kann es notwendig machen, einen
Resolver-Backend zu landen, **bevor** das Image-Build / die
Cosign-Policy / der Quadlet-Installer-Entry landet. Beispiel:
`federation-resolver` als Welle-2-Scaffold (ADR-0066 §Welle-Sequenz).

In diesem Fall:

1. Resolver-Konstante `DEFAULT_RUST_<NAME>_BIN` in
   `rust_backend_switch.py` landen.
2. In `tests/infra/test_cross_substrate_parity_3way.py`:
   `RESOLVER_KNOWN_EXTRAS` um den neuen Component-Slug ergänzen
   (Pattern: `("federation-resolver", "<next-extra>")`).
3. In diesem Runbook §2-Tabelle eine neue Zeile mit dem Grund
   der Divergenz dokumentieren (welche Welle, ADR-Anchor).
4. Wenn die Welle dann live geht, in derselben Mini-Welle:
   - Resolver-Konstante bleibt (oder wird auf neue Konfiguration
     gebogen).
   - `RESOLVER_KNOWN_EXTRAS`-Entry entfernen.
   - Cosign + Quadlet + Test-Tupel + Runbook §1 ergänzen.

Diese Sequenz hält die Drift dokumentiert statt versteckt.

---

## 6. Sandbox-Boundary

Der CI-Gate läuft komplett hermetic. Keine
`cosign verify` / `crane manifest` / `skopeo inspect`-Aufrufe gegen
`ghcr.io` aus der Sandbox heraus. Live-Verifikation der
Image-Digests ist **Operator-Hand** (per
`docs/operations/cosign-policy-phase-3b.md` §3).

Anchor: `feedback_sandbox_host_trennung.md` — claude-dev darf
keinen Host-Container-Socket-Zugriff haben; Live-Smoke-Tests sind
Operator-Hand.

---

## 7. Wartungs-Anker

- **Cross-Review Zone C** — Tomás (Matrix-Lead): jede Änderung an
  diesem Runbook ODER an der 3-Way-Parity-Test-Datei ODER an dem
  Workflow muss in Zone C cross-reviewed werden (Container-Image-
  Pipeline × OTS-Anchoring-Konsens-Domain).
- **Mira-Hand-Folge:** Nach erstem grünen main-Run unter
  `cross-substrate-parity-gate.yml` muss Mira den Job als
  Required-Status-Check in Branch-Protection aktivieren (GitHub
  Repo-Settings → Branches → main → Required status checks). Der
  Job-Display-Name `cross-substrate parity (cosign ↔ quadlet ↔
  backend-switch)` ist exakt der zu aktivierende String (per
  `feedback_branch_protection_check_names.md`).
- **Audit-Log:** Drift-Vorfälle werden im
  `activity-log.md` als `cross-substrate-parity-drift`-Vorfall
  protokolliert. Henrik (Internal Audit) auditiert die Vorfälle
  im regulären Sample.

---

*Erstellt: Tag-32 Mini-Welle (ADR-0066 Welle-3 Mitigation).*
*Sibling-Runbooks:*
- *`docs/operations/cosign-policy-phase-3b.md` — Cosign-Policy
  Operator-Hand-Recipe.*
- *`docs/operations/cross-repo-drift-runbook.md` — Cross-Repo
  Drift-Operator-Recipe.*

— Kai
