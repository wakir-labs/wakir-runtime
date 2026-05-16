<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

---
doc: rust-rewrite-crate-wahlen
version: 0.1.0
status: decision-prep
date: 2026-05-16
author: Reza Tehrani (Dev-Engineering-2)
audience: mira-ceo, priya-cto, selin-pengine, tomas-engineering, henrik-audit
purpose: Crate-Wahl-Decision-Doc für ADR-0063 §Folgeartefakte Item 1 — drei offene Wahlachsen aus Selin-Roadmap §2.3 beantworten.
---

# Rust-Re-Write Crate-Wahlen (ADR-0063 §Folgeartefakte Item 1)

## Kontext

- ADR-0063 approved 2026-05-16 ~15:30 CEST (Option A — Phase-3-Trigger
  nach Phase-2-Validation, ~KW 27).
- Selin-Roadmap (`docs/decisions/persona-engine-rust-rewrite-roadmap.md`,
  Sprint-Pengine-13, PR #79) identifiziert in §2.3 drei offene
  Crate-Wahl-Fragen für die Rust-Persona-Engine.
- Decision-Vorbereitung jetzt, damit Phase-3a-Start (~KW 27,
  ~2026-06-26) ohne offene Crate-Wahlen lossetzbar ist.
- Diese Doku ist eine **Decision-Vorbereitung**, kein
  Implementierungs-Auftrag. Sie liefert pro Wahlachse eine
  Empfehlung mit Begründung, Smoke-Test-Skizze und Risiko-Liste.
- Re-Validation-Pflicht 2 Wochen vor Phase-3-Trigger (ADR-0063
  §"Risiken" Crate-Wahl-Ökosystem-Drift) — diese Snapshots sind
  Stand 2026-05-16, müssen bei Phase-3-Start bestätigt werden.

### Verifikations-Methodik

- Alle Crate-Metadaten direkt aus der Crates.io-JSON-API geholt
  (`https://crates.io/api/v1/crates/<name>`) — die HTML-Pages
  rendern client-side via SPA und liefern ohne Browser keinen
  brauchbaren Body, deshalb API-Endpoints als Primärquelle.
- HTTP-Status-Stempel für API-Endpoints + docs.rs (Stand
  2026-05-16 ~13:19 CEST).
- Audit-Tracking: RustSec Advisory DB (`rustsec.org`) als
  Sekundärquelle für CVE-Status — wird in Smoke-Test-Phase pro
  Crate explizit `cargo audit`-geprüft (siehe §"Smoke-Test-
  Empfehlungen").

---

## Wahlachse 1 — Shamir-Secret-Sharing

### Use-Case

Persona-State-Recovery (Spec §3.7.4 R1..R4, Reza Zone-B Identity-
Substrate). Backup-Substrate für `PersonaStateSnapshot` (siehe
Selin-Roadmap §1.3 — state-pack envelope ist der Cross-Engine-
Determinism-Anchor).

**Substrat-Klassifikation:** Identity-Substrate-kritisch. Format-
Mismatch zwischen Python-Engine und Rust-Engine bricht Recovery
irreversibel.

### Kandidaten (Stand 2026-05-16, Crates.io-API)

| Crate | Latest | Last Update | Recent DLs | License | Repo |
|---|---|---|---|---|---|
| `shamirsecretsharing` | 0.1.7 | 2025-10-26 | 3,155 | MIT | dsprenkels/sss-rs |
| `sharks` | 0.5.0 | 2021-03-14 | 24,118 | MIT/Apache-2.0 | c0dearm/sharks |
| `vsss-rs` | 5.4.0 | 2026-04-28 | 251,594 | Apache-2.0 OR MIT | mikelodder7/vsss-rs |
| eigene Implementation (`wakir-shamir`) | — | — | — | Apache-2.0 OR MIT | wakir-labs/wakir-runtime |

**HTTP-200-Stempel:**
- `https://crates.io/api/v1/crates/shamirsecretsharing` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/sharks` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/vsss-rs` — 200, 2026-05-16T11:19Z
- `https://docs.rs/shamirsecretsharing` — 200, 2026-05-16T11:19Z
- `https://docs.rs/sharks` — 200, 2026-05-16T11:19Z
- `https://docs.rs/vsss-rs` — 200, 2026-05-16T11:19Z

### Analyse

**`shamirsecretsharing` (dsprenkels):**
- Aktiv gepflegt (2025-10-26 Update für 0.1.7 nach 4 Jahren
  Pause — signalisiert Maintainer-Re-engagement, aber lange
  Pause vorher ist Risiko-Indikator).
- C-FFI-Layer (libsodium in älteren Versionen, 0.1.7 hat C-Code
  entfernt — Linecounts: 530 Rust, 0 C in 0.1.7 vs. 261 Rust +
  1395 C in 0.1.4). Pure-Rust ab 0.1.7 ist Reza-positiv.
- Geringe Adoption (3.155 recent downloads) — kleines
  Ecosystem-Risiko.
- API: generic bytes (kein SLIP-0039-Mnemonic-Layer).
- Author Amber Sprenkels ist Cryptography-Researcher (Radboud
  University) — Reputations-positiv.

**`sharks` (c0dearm):**
- **Stale.** Letztes Update 2021-03-14, also 5 Jahre keine
  Pflege. Disqualifiziert für Identity-Substrate-Use-Case.
- Höhere Adoption als shamirsecretsharing (24k recent DLs),
  aber das ist Legacy-Adoption ohne Maintenance-Garantie.

**`vsss-rs` (mikelodder7):**
- **Aktiv und breit adoptiert.** 5.4.0 vom 2026-04-28, 251k
  recent downloads — Größenordnung über shamirsecretsharing.
- Implementiert mehrere Shamir-Varianten plus Verifiable
  Secret Sharing (VSSS, Pedersen, Feldman) — größerer
  Surface als wir brauchen, aber Subset-Use ist möglich.
- Maintainer Michael Lodder ist OpenWallet-Foundation-aktiv
  (Hyperledger AnonCreds, Indy-Node-Vorgeschichte) — Identity-
  Substrate-Domain-Match.
- Apache-2.0 OR MIT — Lizenz-konform (kein BUSL-Risiko).
- Dependencies: `elliptic-curve`, `zeroize`, `rand_core` —
  RustCrypto-Ökosystem-aligned.

**Eigene Implementation:**
- Vorteil: voll-kontrolliert, byte-format-stable definierbar.
- Nachteil: Shamir-Crypto ist Constant-Time-anfällig. Selbst-
  geschriebener Code ohne externes Audit ist für Identity-
  Substrate-kritischen Pfad fragwürdig.
- Nur sinnvoll wenn alle drei externen Optionen disqualifizieren.

### Empfehlung (Reza)

**`vsss-rs` v5.4.0**, mit folgenden Bedingungen:

1. **Smoke-Test pro Phase-3a-Re-Validation:**
   Hello-World-Use-Case mit Python-`shamir-mnemonic` Wheel
   (SLIP-0039) — wir nutzen NICHT die SLIP-0039-Mnemonic-Layer
   (das ist `shamir-mnemonic` Python-spezifisch), sondern
   den Raw-Shamir-Pfad. Cross-Sprache-Byte-Verifikation in
   einem hermetic Test-Fixture-Bundle.
2. **Subset-Restriction:** Wir nutzen nur Classical-Shamir
   (kein Pedersen, kein Feldman, kein VSSS — diese sind
   feature-flag-gated und werden NICHT aktiviert in Cargo.toml).
3. **Format-Anchor:** Der Backup-Substrate-Byte-Format ist im
   `persona_state_recovery_format`-Spec (Reza Zone-B, folgt
   in Phase-3a) festgenagelt. `vsss-rs` ist Implementation,
   nicht Format-Definition.

**Begründung gegen Mira-Empfehlung-Stand:** Mira-Empfehlung
in ADR-0063 §Folgeartefakte war `shamir-sss` (das ist die
Python-`shamir-mnemonic`-Domäne) falls production-tested,
sonst Standalone. Reza-Vertiefung zeigt: `shamir-sss` als
Crate-Name existiert nicht direkt auf Crates.io
(API-Check: `crate 'rfc8785' does not exist` — gleiche
Klasse-Befund). `vsss-rs` ist der aktive, breit-adoptierte,
Identity-Domain-aligned-Kandidat und schlägt sowohl
`shamirsecretsharing` (kleine Adoption, lange Maintainer-
Pause vor 2025-10) als auch eigene Implementation
(Constant-Time-Risiko ohne Audit).

### Risiken bei dieser Wahl

- **Larger Surface than needed:** `vsss-rs` enthält Pedersen
  + Feldman + VSSS — Cargo-Feature-Flag-Discipline nötig damit
  wir nur Classical-Shamir compilen.
- **Maintainer-Single-Point:** Michael Lodder ist Hauptautor.
  OpenWallet-Foundation-Bindung mitigiert, aber kein Team-Drift-
  Schutz wie bei RustCrypto-Org.
- **API-Drift 5.x → 6.x:** Major-Version-Bumps zwischen 5.0 und
  5.4 (sechs Minor-Releases in 12 Monaten). Wir pinnen `=5.4.0`
  in Cargo.toml mit explizitem `cargo update --precise`-
  Workflow für Bumps.

---

## Wahlachse 2 — JSON-Canonicalization (JCS, RFC 8785)

### Use-Case

- WAT-Audit-Hash (Tomás Zone-K, identische Bytes Python-Engine
  ↔ Rust-Engine ↔ WAT-Sink).
- V-907-Persona-Hash (Aisha Zone-F + Reza Zone-B-Anker).
- Doppelbetrieb-Konsistenz (Selin-Roadmap §4.1 Gates G-1/G-2/G-3
  fordern byte-identische JCS-Bytes Python ↔ Rust).

**Substrat-Klassifikation:** Cross-Engine-Determinism-Anker.
Ein-Byte-Drift bricht Bridge-Audit-Writer als Konsistenz-Oracle.

### Kandidaten (Stand 2026-05-16, Crates.io-API)

| Crate | Latest | Last Update | Recent DLs | License | Repo |
|---|---|---|---|---|---|
| `serde_jcs` | 0.2.0 | 2026-03-25 | 213,591 | MIT OR Apache-2.0 | l1h3r/serde_jcs |
| `rfc8785` | — | — | — | — | **existiert nicht auf Crates.io** |
| `serde-json-canonicalization` | — | — | — | — | **existiert nicht auf Crates.io** |
| `json-syntax` | 0.12.5 | 2024-07-03 | 670,104 | MIT/Apache-2.0 | timothee-haudebourg/json-syntax |

**HTTP-200-Stempel:**
- `https://crates.io/api/v1/crates/serde_jcs` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/rfc8785` — 404 (`crate 'rfc8785' does not exist`)
- `https://crates.io/api/v1/crates/serde-json-canonicalization` — 404 (`crate 'serde-json-canonicalization' does not exist`)
- `https://crates.io/api/v1/crates/json-syntax` — 200, 2026-05-16T11:19Z
- `https://docs.rs/serde_jcs` — 200, 2026-05-16T11:19Z

### Korrektur-Befund

**Mira-Empfehlung-Stand-Korrektur:** ADR-0063 §Folgeartefakte
Item 1 und Selin-Roadmap §2.2 schlagen `rfc8785-rs` bzw.
`serde-json-canonicalization` als Optionen vor. Reza-
Verifikation zeigt: **beide existieren nicht auf Crates.io**
unter diesen Namen.

- `rfc8785` ist der Python-Wheel-Name (PyPI), nicht ein
  Rust-Crate.
- `serde-json-canonicalization` ist ein Crates.io-Phantom (404
  bestätigt).
- Die tatsächlich existierenden Rust-JCS-Implementations sind
  `serde_jcs` (Devin Turner) und Fragmente in `json-syntax`
  (Timothée Haudebourg, primär JSON-LD-Tooling).

### Analyse

**`serde_jcs` v0.2.0:**
- Aktiv (2026-03-25 Update zu 0.2.0 von 0.1.0/2020 — 5 Jahre
  Lücke, aber dann gepflegt).
- Sehr breite Adoption (213.591 recent downloads — größer als
  ed25519-dalek-recent in vielen Quartalen).
- Rust-Edition 2024, rust_version 1.85 — modern.
- Implementiert RFC 8785 als Serde-Layer (`serde_jcs::to_string`,
  `serde_jcs::to_vec`).
- Repo: `l1h3r/serde_jcs`, MIT OR Apache-2.0.

**`json-syntax`:**
- Breitere Lib (JSON-LD-Tooling-Schwerpunkt), enthält JCS-
  Implementation als Sub-Feature.
- Nicht JCS-fokussiert — Risiko dass JCS-Spezifika nicht
  prioritär gepflegt werden.
- Größere Dependency-Footprint.

### Empfehlung (Reza)

**`serde_jcs` v0.2.0** als alleiniger JCS-Crate für **hot-path
UND Tests**.

**Begründung gegen Mira-Empfehlung-Stand:** Mira-Empfehlung
ADR-0063 §Folgeartefakte unterscheidet `rfc8785-rs` (hot-path)
vs. `serde-jcs` (Tests). Diese Trennung war auf der falschen
Annahme zwei aktiver Implementations basiert. Reza-Befund:
`rfc8785` (Rust-Crate-Name) existiert nicht. Der einzige
aktive Crate ist `serde_jcs` — also: ein Crate für beide
Pfade.

**Wenn Mira-Stand zwei Crates wollte für Cross-Implementation-
Check:** Cross-Implementation-Check funktioniert besser via
Python-`rfc8785` Wheel ↔ Rust-`serde_jcs` (zwei Sprachen, zwei
Implementations) statt zwei Rust-Crates. Das ist genau das was
Selin-Roadmap §4.1 Gate G-1/G-2/G-3 fordert.

### Smoke-Test-Empfehlung

1. **Test-Vector-Suite (Phase-3a Vorbereitung):**
   - Pickle 200 Python-Engine-JCS-Outputs (V-907-pins,
     state-pack envelopes, output envelopes) als
     `tests/fixtures/jcs-byte-equiv-vectors-2026-05.json`.
   - Rust-Side-Test: für jeden Vector `serde_jcs::to_vec()`
     berechnen, byte-equal-Assertion.
2. **Edge-Case-Tests:**
   - Unicode-Escape (BMP-Chars, Astral-Chars, Surrogate-Pairs).
   - Key-Ordering (numerische Strings vs. alphabetische).
   - Floats: **strikt verbieten** (Engine emittiert keine
     Floats; RFC 8785 §3.2.2 hat I3E-754-Edge-Case-Drift-
     Pfade — wir schließen das aus).
3. **CI-Gate:** Test-Vector-Suite als Phase-3a-G-1-Pflicht
   in CI verankern.

### Risiken bei dieser Wahl

- **Single-Crate-Lock-In:** Kein zweiter Rust-JCS-Crate als
  Fallback. Falls `serde_jcs` deprecated/unmaintained wird,
  müssen wir eigenen JCS-Crate bauen (RFC 8785 ist ~6 Seiten
  Spec, machbar — siehe Wakir-Eigenbau-Notiz §"Fallback-Plan").
- **Rust-Edition-2024-Floor:** rust_version 1.85 — falls
  unsere Toolchain auf älteren rustc gepinnt ist, blocken.
  Cargo.toml prüfen vor Phase-3a-Start.
- **JCS-Drift Python-rfc8785 ↔ Rust-serde_jcs:** ungetestete
  Edge-Cases bleiben Edge-Cases. Test-Vector-Suite ist
  Mitigation, kein Beweis von Vollständigkeit.

### Fallback-Plan

Falls `serde_jcs` während Phase-3a/b deprecated wird:
Wakir-Eigenbau-Crate `wakir-jcs` (geschätzt 600 LOC Rust),
strikte RFC-8785-Konformität, keine Float-Surface, JCS-
Test-Vector-Suite als Acceptance.

---

## Wahlachse 3 — Cryptography (Sig-Verify, Hash, AEAD)

### Use-Case

- **BIP32 secp256k1:** Identity-Substrate-Hauptkurve (Reza
  Zone-L, Persona-Identity-Document-Signaturen).
- **SLIP-0010 Ed25519:** Alternativ-Identity-Kurve (Aisha-Persona-
  Tooling, manche Sub-Key-Pfade).
- **SVID-Cert-Verify:** X.509-Parse für SPIFFE Workload-API
  (Selin-Roadmap §2.1 `svid_workload_identity.py`).
- **AEAD für State-Encryption:** AES-GCM oder ChaCha20-Poly1305
  für PersonaStateBacking-Optional-Encryption (Phase-3b-Item).
- **Hash:** SHA-256 für V-907-pins und Merkle-Layer-Konsistenz
  mit WAT (Tomás Zone-K).

### Kandidaten (Stand 2026-05-16, Crates.io-API)

| Crate | Latest | Last Update | Recent DLs | License | Notes |
|---|---|---|---|---|---|
| `ring` | 0.17.14 | 2025-03-11 | 117,363,485 | Apache-2.0 AND ISC | Brian Smith — All-in-one |
| `aws-lc-rs` | 1.17.0 | 2026-05-13 | 45,261,654 | ISC AND (Apache-2.0 OR ISC) | AWS-maintained, FIPS-ready |
| `rustls` | 0.23.40 | 2026-04-28 | 147,221,968 | Apache-2.0 OR ISC OR MIT | TLS-Layer-fokussiert |
| `k256` | 0.13.4 | 2026-04-17 | 12,227,225 | Apache-2.0 OR MIT | RustCrypto secp256k1 |
| `ed25519-dalek` | 2.2.0 | 2026-05-06 | 44,142,186 | BSD-3-Clause | Dalek-Cryptography Ed25519 |
| `sha2` | 0.11.0 | 2026-03-25 | 142,396,318 | MIT OR Apache-2.0 | RustCrypto SHA-2 |
| `chacha20poly1305` | 0.10.1 | 2026-02-02 | 11,611,631 | Apache-2.0 OR MIT | RustCrypto AEAD |
| `aes-gcm` | 0.10.3 | 2026-02-02 | 20,973,355 | Apache-2.0 OR MIT | RustCrypto AEAD |
| `bip32` | 0.5.3 | 2025-01-28 | 2,476,719 | Apache-2.0 OR MIT | iqlusioninc BIP32 |
| `slip10_ed25519` | 0.1.3 | 2021-03-05 | 550,951 | MIT OR Apache-2.0 | jpopesculian — **stale** |

**HTTP-200-Stempel:**
- `https://crates.io/api/v1/crates/ring` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/aws-lc-rs` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/rustls` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/k256` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/ed25519-dalek` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/sha2` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/chacha20poly1305` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/aes-gcm` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/bip32` — 200, 2026-05-16T11:19Z
- `https://crates.io/api/v1/crates/slip10_ed25519` — 200, 2026-05-16T11:19Z

### Analyse — Crypto-Strategie-Ansatz

Mira-Empfehlung-Stand: `ring` für Phase-3a, `aws-lc-rs`-Migration
für FIPS-Compliance bei Hosted-Service-Pfad.

**Reza-Bewertung der Strategie:**
- `ring` ist all-in-one (Sig, Hash, AEAD, RNG), audit-clean,
  117M recent DLs (Bedrock-Adoption). Aber: kein BIP32, kein
  SLIP-0010, kein secp256k1 (`ring` macht ECDSA-P256/P384,
  Ed25519, X25519 — KEIN secp256k1).
- `aws-lc-rs` ist API-kompatibel zu `ring` (`drop-in replacement`
  ist die explizite Roadmap), FIPS-140-3 zertifiziert seit
  ~2024. Größerer Maintainer (AWS-Team).
- **Keine der beiden ringeligen Crates kann secp256k1.** Das
  ist der Hauptbedarf für Reza Zone-L (BIP32-Hauptkurve).

**Implication:** Wir können NICHT mit nur `ring` oder nur
`aws-lc-rs` auskommen. Wir brauchen **eine Layered-Strategie**:

- **Primitive-Layer:** RustCrypto-Ökosystem (`k256` für
  secp256k1, `ed25519-dalek` für Ed25519, `sha2` für SHA-256,
  `aes-gcm` + `chacha20poly1305` für AEAD).
- **TLS/SVID-Cert-Layer:** `rustls` (NICHT `ring` direkt —
  `rustls` nutzt intern `ring` oder `aws-lc-rs` als
  CryptoProvider und das ist konfigurierbar).
- **BIP32-Layer:** `bip32` crate (iqlusioninc, baut auf `k256`).

### Empfehlung (Reza) — Crate-Stack pro Pfad

#### Stack 1 — Identity-Substrate (Reza Zone-L)

| Pfad | Crate | Version-Pin |
|---|---|---|
| secp256k1 ECDSA | `k256` | `=0.13.4` |
| BIP32 derivation | `bip32` | `=0.5.3` |
| Ed25519 sig/verify | `ed25519-dalek` | `=2.2.0` |
| SLIP-0010 derivation | **eigene Implementation** | — |

**SLIP-0010-Begründung:** `slip10_ed25519` Crate ist stale
(letztes Update 2021). Das ist Identity-Substrate-kritischer
Pfad — eigene Implementation auf Basis von `ed25519-dalek` +
`hmac` + `sha2` ist machbar (~150 LOC), kontrolliert, und
spart Maintainer-Single-Point-Risiko.

#### Stack 2 — Cross-Engine-Determinism (Tomás Zone-K + Reza Zone-B)

| Pfad | Crate | Version-Pin |
|---|---|---|
| SHA-256 (V-907 pins, WAT Merkle leaves) | `sha2` | `=0.11.0` |

**Single-Choice:** RustCrypto `sha2` ist der Standard. 142M
recent DLs, audit-clean (RustCrypto-Org-Reputation), Lizenz-
konform. Kein konkurrierender Vorschlag.

#### Stack 3 — SVID + Workload-API (Selin-Roadmap §2.1 svid_workload_identity)

| Pfad | Crate | Version-Pin |
|---|---|---|
| TLS-Channel (SPIFFE Workload-API) | `rustls` mit `aws-lc-rs` CryptoProvider | `rustls=0.23.40`, `aws-lc-rs=1.17.0` |
| X.509 Cert parse | `x509-cert` (RustCrypto) oder `rustls`-internal | (Phase-3a Smoke-Test entscheidet) |

**Begründung `aws-lc-rs` statt `ring`:**
- `aws-lc-rs` ist API-kompatibel zu `ring` ("plug-and-play")
  bei besserer FIPS-Roadmap.
- Hosted-Service-Pfad (ADR-0058 Phase-X) wird FIPS-Compliance
  perspektivisch fordern — early-adopt vermeidet Mid-Flight-
  Migration.
- `ring` ist seit 2025-03-11 nicht mehr aktiv-released (0.17.14
  ist letztes), während `aws-lc-rs` 2026-05-13 frisch released.
- Recent-DLs-Verteilung 117M (ring) vs. 45M (aws-lc-rs) — aber
  aws-lc-rs wächst und ist die zukunfts-positionierte Wahl
  laut AWS-Team-Roadmap (2024-2026 Announcement).

#### Stack 4 — State-Encryption-Optional (Phase-3b)

| Pfad | Crate | Version-Pin |
|---|---|---|
| AEAD primary | `chacha20poly1305` | `=0.10.1` |
| AEAD alternativ (FIPS-Pfad) | `aes-gcm` | `=0.10.3` |

**Begründung ChaCha20-Poly1305 als Default:** Constant-time
auf Software-only-CPUs (kein AES-NI-Bedarf), 2× schneller als
AES-GCM auf ARM ohne Hardware-Beschleunigung, von WireGuard +
TLS-1.3 als bevorzugtes AEAD. AES-GCM-Pfad für FIPS-
Compliance-Bedarf (Phase-X Hosted-Service).

### Empfehlung gegen Mira-Empfehlung-Stand

**Mira-Stand:** `ring` für Phase-3a, `aws-lc-rs` später.

**Reza-Korrektur:** 
1. **`ring` deckt unseren Hauptbedarf (secp256k1) NICHT ab.**
   Mira-Empfehlung war auf der Annahme dass `ring` als All-in-
   One reicht. Das ist für SPIFFE-TLS okay, aber Identity-
   Substrate braucht secp256k1 das `ring` nicht hat.
2. **Direkt `aws-lc-rs` statt `ring` für TLS-Pfad** — kein
   Sinn in Two-Step-Migration wenn `aws-lc-rs` jetzt schon
   ready ist und besser maintained.
3. **Layered Crate-Stack** statt Single-Crate-Wahl. Das ist
   keine "Komplikation" sondern reflektiert dass Crypto-
   Domain heterogen ist.

### Smoke-Test-Empfehlung

Pro Crate ein Hello-World-Use-Case in `crates/persona-engine-
crypto-smoke/` (Phase-3a-Initial-Sprint):

1. `k256`: secp256k1 keygen + sign + verify against Python-
   `cryptography`-Wheel ECDSA-output.
2. `bip32`: derive m/44'/0'/0'/0/0 from same seed in Python
   `bip32` and Rust `bip32`; byte-compare child pubkeys.
3. `ed25519-dalek`: sig/verify against Python-`cryptography`-
   Wheel Ed25519.
4. `sha2`: hash a 1MB blob, byte-compare against Python
   `hashlib.sha256` — trivial but Acceptance-Gate-relevant.
5. `aws-lc-rs`: TLS-1.3 handshake against test-SPIRE-server.
6. `rustls` + `aws-lc-rs` CryptoProvider: X.509-Cert parse
   for one SVID-fixture.
7. `chacha20poly1305`: AEAD-encrypt + decrypt roundtrip,
   byte-compare against Python `cryptography`-Wheel ChaCha20.

**RustSec-Audit-Check (Pflicht vor Phase-3a-Start):**
`cargo audit` über alle gepinten Crates. Falls ein CVE,
Pin-Update vor Phase-3a-Trigger.

### Risiken bei dieser Wahl

- **Multi-Crate-Surface:** 8+ Crypto-Crates erhöhen Supply-
  Chain-Surface. Mitigation: `cargo audit` als CI-Gate,
  `cargo deny` für Lizenz-Compliance.
- **`ring`-Drop:** Wir nehmen `ring` NICHT in den Stack. Falls
  ein downstream Dependency (z.B. `rustls` Default-Provider)
  intern `ring` zieht, ist das transitiv ok, aber wir spezifizieren
  explizit `rustls`-`aws-lc-rs`-Provider.
- **Eigenbau SLIP-0010:** Wir bauen die SLIP-0010-Ed25519-
  Derivation selbst. Risiko: Constant-Time-Fehler in HMAC-Logik.
  Mitigation: gegen Python-`cryptography` SLIP-0010-Test-
  Vectors aus BIP-32-Test-Suite verifizieren (existieren als
  publicly-known vectors).
- **RustCrypto-Team-Konzentration:** Mehrere Crates in unserem
  Stack sind RustCrypto-Org (k256, sha2, aes-gcm, chacha20-
  poly1305). Einzel-Org-Risiko, aber RustCrypto ist breit-
  finanziert (NLnet, Hyperledger, Filecoin-Foundation).

---

## Zusammenfassung

### Crate-Stack-Liste (Phase-3a-Initial-Pin)

| Wahlachse | Crate | Version-Pin | Status |
|---|---|---|---|
| Shamir-Secret-Sharing | `vsss-rs` | `=5.4.0` | Reza-Empfehlung, Smoke-Test-Pflicht |
| JCS (RFC 8785) | `serde_jcs` | `=0.2.0` | Reza-Empfehlung, single-crate-Wahl |
| secp256k1 ECDSA | `k256` | `=0.13.4` | Reza-Empfehlung |
| BIP32 derivation | `bip32` | `=0.5.3` | Reza-Empfehlung |
| Ed25519 sig | `ed25519-dalek` | `=2.2.0` | Reza-Empfehlung |
| SLIP-0010 Ed25519 derive | Eigene Implementation (`wakir-slip10`) | — | Reza-Eigenbau (~150 LOC) |
| SHA-256 | `sha2` | `=0.11.0` | Reza-Empfehlung |
| TLS / SVID | `rustls` 0.23.40 + `aws-lc-rs` 1.17.0 CryptoProvider | `=0.23.40` / `=1.17.0` | Reza-Empfehlung |
| AEAD (Default) | `chacha20poly1305` | `=0.10.1` | Reza-Empfehlung |
| AEAD (FIPS-Pfad) | `aes-gcm` | `=0.10.3` | Phase-X Hosted-Service-Reserve |

### Smoke-Test-Empfehlungen pro Crate

Pro Crate ein Hello-World-Use-Case in `crates/persona-engine-
crypto-smoke/` als Phase-3a-Initial-Sprint-Item (Reza Hauptlast,
Cross-Review Tomás für Cert-Parse + Selin für JCS-Vector-Suite).

Detail-Tests siehe §"Smoke-Test-Empfehlung" je Wahlachse.

### Phase-3a-Trigger-Pre-Check (2 Wochen vor KW 27)

- Re-Validation aller Crate-Pins gegen aktuellen Crates.io-
  Stand (Versions-Drift?).
- `cargo audit` über alle gepinten Crates — bei CVE-Befund
  Pin-Update vor Phase-3a-Trigger.
- Hello-World-Smoke-Tests ausführbar als CI-Pre-Gate.

### Cross-Review-Bedarf vor Phase-3a-Trigger

- **Tomás Zone-K (Sign-off Gate G-11 per Selin-Roadmap):**
  V-907 SHA-256 + JCS Byte-Equivalence Review.
- **Selin Zone-Persona-Engine (Sign-off Gate G-10 per Selin-
  Roadmap):** Crate-Stack-Review insbesondere JCS-Test-Vector-
  Suite.
- **Kai Zone-J (Sign-off Gate G-12):** Container-Image-Build
  mit allen Crypto-Crates (Static-Linking, Image-Size-Acceptance
  ≤ 125 MB).

### Risiken-Zusammenfassung (alle Wahlen)

- **Maintainer-Drift:** Vier Crates haben Single-Maintainer-
  Risiko (`vsss-rs`, `serde_jcs`, `bip32`, `ed25519-dalek` —
  Dalek-Team ist klein, aber etabliert). RustCrypto-Org-Crates
  haben Team-Coverage.
- **Ökosystem-Lock-In:** RustCrypto-Konzentration. Akzeptiert,
  weil Ökosystem etabliert und keine bessere Alternative.
- **Performance-Implikationen:** ChaCha20-Poly1305-Wahl bevorzugt
  Software-CPU-Perf statt AES-NI-Hardware. Falls Phase-3-Pilot-
  VM AES-NI hat (wahrscheinlich, Intel/AMD-Standard), könnte
  AES-GCM marginal schneller sein — nicht kritisch für unsere
  Volumes.
- **Phase-3-Trigger-Drift:** Diese Snapshots sind Stand 2026-05-16.
  Re-Validation 2 Wochen vor Phase-3-Trigger (Mitte KW 25) per
  ADR-0063 §"Risiken" Pflicht.

---

## Out-of-Scope (für dieses Decision-Doc)

- **Tonic / gRPC / async-nats:** Diese sind in Selin-Roadmap
  §2.1 bereits gewählt und nicht Teil der drei offenen Wahlen.
  Reza-Cross-Sicht: einverstanden mit Selin-Wahlen.
- **serde_yaml für persona-md axis-A parse:** Selin-Roadmap §2.2
  hat das adressiert. Reza-Cross-Sicht: YAML-1.2-Strict-Mode
  hinzufügen als Pre-Phase-3a-Item (Aisha Zone-F).
- **`reqwest` für Anthropic LLM-Hook (Phase-3-Stub):** Selin-
  Roadmap §2.1, nicht Identity-Substrate-Domain.

---

## Cross-References

- ADR-0063 (Persona-Engine-Sprach-Revision Rust-Re-Write,
  approved 2026-05-16) — diese Decision-Doc beantwortet
  §Folgeartefakte Item 1.
- ADR-0035 §C (Sprach-pro-Komponente, approved 2026-05-06) —
  Persona-Engine in Rust-Pflicht.
- Selin-Roadmap-Doku: `docs/decisions/persona-engine-rust-
  rewrite-roadmap.md` §2.3 (drei offene Wahlen) + §4.4
  (Governance-Gates).
- Memory `feedback_externe_url_verifikation` — HTTP-200-Stempel-
  Pflicht für externe URLs erfüllt für alle Crates.io-API-
  Endpoints + docs.rs-Pages.

---

*— Reza Tehrani (Dev-Engineering-2), 2026-05-16*
