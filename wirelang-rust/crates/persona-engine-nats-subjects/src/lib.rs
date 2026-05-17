// SPDX-License-Identifier: Apache-2.0
//
// persona-engine-nats-subjects — Typed Subject-Hierarchy für die
// Persona-Engine NATS-Topology.
//
// Phase-3a Modul 10 (2026-05-17, Tag-12 Mini-Welle).
//
// Subject-Familie:
//
//   persona.lifecycle.{id}.{event}
//   persona.federation.{cluster}.{id}.frame
//   persona.audit.{kind}.{id}
//   persona.anchor.{batch}.submitted
//   persona.recovery.{step}.{id}
//
// Wildcard-Tokens:
//
//   `*` : exactly one token at this position
//   `>` : tail-wildcard (terminal, matches one or more tokens)
//
// Cross-Lang-Pin-Posture:
//
//   8 Pin-Fixtures (siehe `pins`-Modul) sind Rust-canonical. Wenn
//   `wirelang/persona_engine/nats_subjects.py` später emergiert,
//   MUSS dieser Python-Side byte-identisch zu den Rust-Pins liefern.
//   Bis dahin: Rust ist die einzige Quelle der Wahrheit.

#![deny(missing_docs)]
#![deny(unsafe_code)]

//! Typed NATS-Subject-Builders für die Persona-Engine.
//!
//! Diese Crate liefert (a) Typed-Builder-Funktionen für die fünf
//! Persona-Engine-Subject-Klassen und (b) Wildcard-Pattern-Builders
//! für Subscribe-Side-Operatoren. Alle Funktionen validieren ihre
//! Token-Inputs gegen die [`is_valid_token`]-Regel und reservierte
//! Wörter (`>`, `*`, leerer String, Tokens mit `.`).
//!
//! Beispiel:
//!
//! ```
//! use persona_engine_nats_subjects as subjects;
//!
//! let s = subjects::lifecycle_subject("reza-2026-05-17", "spawned").unwrap();
//! assert_eq!(s, "persona.lifecycle.reza-2026-05-17.spawned");
//!
//! let pat = subjects::lifecycle_wildcard_all_events("reza-2026-05-17").unwrap();
//! assert_eq!(pat, "persona.lifecycle.reza-2026-05-17.*");
//!
//! let pat = subjects::lifecycle_wildcard_all().unwrap();
//! assert_eq!(pat, "persona.lifecycle.>");
//! ```

use serde::Serialize;
use std::fmt;

/// Maximale Länge eines einzelnen NATS-Tokens (Persona-Engine-Policy).
///
/// NATS selbst limitiert einen ganzen Subject-String auf ~255 Bytes;
/// die Persona-Engine drückt die Per-Token-Grenze auf 64 ASCII-
/// Zeichen, damit zusammengesetzte Subjects nie über 255 hinaus
/// wachsen (5 Tokens × 64 = 320 ist theoretisch möglich, aber unsere
/// Schemata haben max 4 dynamische Tokens; 4 × 64 + Constanten < 255).
pub const MAX_TOKEN_LEN: usize = 64;

/// Geschützte (reservierte) Tokens — dürfen nicht als dynamische
/// Werte (`id`, `event`, `cluster`, `kind`, `batch`, `step`)
/// auftauchen, weil sie in NATS spezielle Bedeutung haben.
pub const RESERVED_WORDS: &[&str] = &[">", "*", ""];

/// Fehlerklassen für Subject-Validation.
///
/// Closed enum — neue Varianten werden bei Bedarf hinzugefügt, alte
/// werden nicht entfernt (Backward-Compat für Konsumenten, die auf
/// die Discriminant matchen).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "error", content = "detail")]
pub enum SubjectError {
    /// Token enthält ein Zeichen, das nicht in `[A-Za-z0-9_-]` liegt
    /// (insbesondere ein Punkt `.`, der NATS-Token-Separator).
    InvalidChar {
        /// Position (zero-based) im Token, an der das ungültige
        /// Zeichen steht.
        position: usize,
        /// Das tatsächlich gefundene Zeichen.
        character: char,
        /// Welches Token-Feld (z.B. `"id"`, `"event"`, `"cluster"`).
        field: &'static str,
    },
    /// Token ist länger als [`MAX_TOKEN_LEN`].
    TokenTooLong {
        /// Beobachtete Länge in Bytes.
        actual: usize,
        /// Erlaubter Maximalwert.
        max: usize,
        /// Welches Token-Feld.
        field: &'static str,
    },
    /// Token ist gleich einem [`RESERVED_WORDS`]-Eintrag.
    ReservedWord {
        /// Welches Token-Feld.
        field: &'static str,
        /// Der konkret gefundene reservierte Wert.
        value: String,
    },
    /// Token ist leer (Spezialfall von [`SubjectError::ReservedWord`],
    /// aber als eigene Variante exportiert, damit Caller "vergessene
    /// Inputs" von "absichtlich reserviertes Wildcard" unterscheiden
    /// können).
    EmptyToken {
        /// Welches Token-Feld.
        field: &'static str,
    },
    /// Token beginnt mit einer Ziffer. Wakir-Convention (analog zur
    /// `^[a-z][a-z0-9_-]*$`-Regel im Layer-0-Schema): Tokens müssen
    /// mit einem Buchstaben starten, damit sie als Identifier nutzbar
    /// bleiben (Stream-Namen, Consumer-Namen).
    LeadingDigit {
        /// Welches Token-Feld.
        field: &'static str,
        /// Der konkrete Wert (für Diagnose).
        value: String,
    },
}

impl fmt::Display for SubjectError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SubjectError::InvalidChar { position, character, field } => write!(
                f,
                "invalid character {:?} at position {} in token field {:?}",
                character, position, field
            ),
            SubjectError::TokenTooLong { actual, max, field } => write!(
                f,
                "token field {:?} is {} bytes (max {})",
                field, actual, max
            ),
            SubjectError::ReservedWord { field, value } => write!(
                f,
                "token field {:?} uses reserved word {:?}",
                field, value
            ),
            SubjectError::EmptyToken { field } => {
                write!(f, "token field {:?} is empty", field)
            }
            SubjectError::LeadingDigit { field, value } => write!(
                f,
                "token field {:?} starts with a digit (got {:?})",
                field, value
            ),
        }
    }
}

impl std::error::Error for SubjectError {}

// ---------------------------------------------------------------------------
// Token-Validation
// ---------------------------------------------------------------------------

/// Validiert ein einzelnes Token gegen die Persona-Engine-Regeln.
///
/// Regeln (ASCII-only, in dieser Reihenfolge angewendet):
/// 1. Nicht leer (sonst [`SubjectError::EmptyToken`]).
/// 2. Nicht in [`RESERVED_WORDS`] (sonst [`SubjectError::ReservedWord`]).
/// 3. Länge ≤ [`MAX_TOKEN_LEN`] (sonst [`SubjectError::TokenTooLong`]).
/// 4. Erstes Zeichen ein ASCII-Buchstabe `[A-Za-z]`
///    (sonst [`SubjectError::LeadingDigit`] — schließt auch andere
///    Nicht-Buchstaben mit ein, deren konkretes Zeichen-Failure
///    aber zuerst durch (5) als [`SubjectError::InvalidChar`]
///    aufschlägt; siehe Test `test_token_validation_order`).
/// 5. Alle Zeichen in `[A-Za-z0-9_-]` (sonst
///    [`SubjectError::InvalidChar`]).
pub fn validate_token(token: &str, field: &'static str) -> Result<(), SubjectError> {
    if token.is_empty() {
        return Err(SubjectError::EmptyToken { field });
    }
    // Reserved-word-Check kommt vor dem Length-Check, weil Reserved-
    // Words alle ≤ 1 Byte sind und ihre Diagnose informativer ist.
    if RESERVED_WORDS.contains(&token) {
        return Err(SubjectError::ReservedWord {
            field,
            value: token.to_owned(),
        });
    }
    if token.len() > MAX_TOKEN_LEN {
        return Err(SubjectError::TokenTooLong {
            actual: token.len(),
            max: MAX_TOKEN_LEN,
            field,
        });
    }
    // Char-Walk: erstes Zeichen MUSS Buchstabe sein; alle weiteren
    // dürfen [A-Za-z0-9_-] sein.
    for (position, ch) in token.chars().enumerate() {
        let allowed = if position == 0 {
            ch.is_ascii_alphabetic()
        } else {
            ch.is_ascii_alphanumeric() || ch == '-' || ch == '_'
        };
        if !allowed {
            // Sonderfall: erstes Zeichen ist Ziffer, aber sonst valide
            // → spezifischere `LeadingDigit`-Diagnose.
            if position == 0 && ch.is_ascii_digit() {
                return Err(SubjectError::LeadingDigit {
                    field,
                    value: token.to_owned(),
                });
            }
            return Err(SubjectError::InvalidChar {
                position,
                character: ch,
                field,
            });
        }
    }
    Ok(())
}

/// Heuristik-Helfer: ist `token` ein gültiges NATS-Token nach unseren
/// Regeln? Reine Bequemlichkeit für externe Konsumenten; intern wird
/// [`validate_token`] genutzt, weil es strukturierte Fehler liefert.
pub fn is_valid_token(token: &str) -> bool {
    validate_token(token, "token").is_ok()
}

// ---------------------------------------------------------------------------
// Typed Subject-Builders (concrete subjects)
// ---------------------------------------------------------------------------

/// Bau-Helfer: validiert beide Tokens und joint zu drei Konstant-
/// Segmenten.
fn build_two_token(
    root: &str,
    namespace: &str,
    tok1: &str,
    tok1_field: &'static str,
    tok2: &str,
    tok2_field: &'static str,
) -> Result<String, SubjectError> {
    validate_token(tok1, tok1_field)?;
    validate_token(tok2, tok2_field)?;
    Ok(format!("{}.{}.{}.{}", root, namespace, tok1, tok2))
}

/// `persona.lifecycle.{id}.{event}`
///
/// Verwendung: Lifecycle-Events einer einzelnen Persona-Instanz
/// (`spawned`, `ready`, `paused`, `despawned`, `crashed`, ...).
pub fn lifecycle_subject(id: &str, event: &str) -> Result<String, SubjectError> {
    build_two_token("persona", "lifecycle", id, "id", event, "event")
}

/// `persona.federation.{cluster}.{id}.frame`
///
/// Verwendung: Federation-Frames zwischen Persona-Engine-Clustern.
/// Das terminale Konstant-Token `frame` bleibt fix, damit Subscribers
/// per `persona.federation.*.*.frame` alle Federation-Frames eines
/// Multi-Cluster-Setups einsammeln können.
pub fn federation_subject(cluster: &str, id: &str) -> Result<String, SubjectError> {
    validate_token(cluster, "cluster")?;
    validate_token(id, "id")?;
    Ok(format!("persona.federation.{}.{}.frame", cluster, id))
}

/// `persona.audit.{kind}.{id}`
///
/// Verwendung: Audit-Trail-Events. `kind` kategorisiert den Audit-
/// Typ (z.B. `lifecycle-change`, `identity-rotate`, `policy-violation`),
/// `id` ist der Vorgangs-Identifier (Audit-Run-UUID o.ä.).
pub fn audit_subject(kind: &str, id: &str) -> Result<String, SubjectError> {
    build_two_token("persona", "audit", kind, "kind", id, "id")
}

/// `persona.anchor.{batch}.submitted`
///
/// Verwendung: OTS/V-907-Anchor-Submission-Events. `batch` ist der
/// Anchor-Batch-Identifier (z.B. Datums-Tag oder Hash-Prefix);
/// terminales Konstant-Token `submitted` markiert den Submit-
/// Lifecycle-Stand.
pub fn anchor_subject(batch: &str) -> Result<String, SubjectError> {
    validate_token(batch, "batch")?;
    Ok(format!("persona.anchor.{}.submitted", batch))
}

/// `persona.recovery.{step}.{id}`
///
/// Verwendung: Recovery-Protokoll-Events (Spawn-Replay, State-Rebuild,
/// Identity-Refetch). `step` benennt die Recovery-Phase (z.B.
/// `replay`, `rebuild`, `verify`), `id` identifiziert die Recovery-
/// Run-Instance.
pub fn recovery_subject(step: &str, id: &str) -> Result<String, SubjectError> {
    build_two_token("persona", "recovery", step, "step", id, "id")
}

// ---------------------------------------------------------------------------
// Wildcard-Subscribe-Pattern-Builders
// ---------------------------------------------------------------------------

/// `persona.lifecycle.{id}.*` — alle Events einer einzelnen Persona.
pub fn lifecycle_wildcard_all_events(id: &str) -> Result<String, SubjectError> {
    validate_token(id, "id")?;
    Ok(format!("persona.lifecycle.{}.*", id))
}

/// `persona.lifecycle.>` — alle Lifecycle-Events aller Personas.
pub fn lifecycle_wildcard_all() -> Result<String, SubjectError> {
    Ok("persona.lifecycle.>".to_owned())
}

/// `persona.federation.{cluster}.>` — alle Federation-Frames eines
/// Clusters.
pub fn federation_wildcard_by_cluster(cluster: &str) -> Result<String, SubjectError> {
    validate_token(cluster, "cluster")?;
    Ok(format!("persona.federation.{}.>", cluster))
}

/// `persona.federation.>` — alle Federation-Frames aller Cluster.
pub fn federation_wildcard_all() -> Result<String, SubjectError> {
    Ok("persona.federation.>".to_owned())
}

/// `persona.audit.{kind}.*` — alle Audit-Events eines Kinds.
pub fn audit_wildcard_by_kind(kind: &str) -> Result<String, SubjectError> {
    validate_token(kind, "kind")?;
    Ok(format!("persona.audit.{}.*", kind))
}

/// `persona.audit.>` — alle Audit-Events.
pub fn audit_wildcard_all() -> Result<String, SubjectError> {
    Ok("persona.audit.>".to_owned())
}

/// `persona.anchor.>` — alle Anchor-Events aller Batches.
pub fn anchor_wildcard_all() -> Result<String, SubjectError> {
    Ok("persona.anchor.>".to_owned())
}

/// `persona.recovery.{step}.*` — alle Recovery-Events eines Steps.
pub fn recovery_wildcard_by_step(step: &str) -> Result<String, SubjectError> {
    validate_token(step, "step")?;
    Ok(format!("persona.recovery.{}.*", step))
}

/// `persona.recovery.>` — alle Recovery-Events.
pub fn recovery_wildcard_all() -> Result<String, SubjectError> {
    Ok("persona.recovery.>".to_owned())
}

/// `persona.>` — root-wildcard (alle Persona-Engine-Subjects).
pub fn persona_root_wildcard() -> Result<String, SubjectError> {
    Ok("persona.>".to_owned())
}

// ---------------------------------------------------------------------------
// Cross-Lang Pin-Pack (Rust-canonical, Python-Sync-Folge)
// ---------------------------------------------------------------------------

/// Cross-Lang-Hash-Pin-Fixtures.
///
/// 8 fixed Subjects (eine pro Subject-Klasse × Variation), gepinnt
/// als Rust-canonical Strings. Python-Pendant
/// `wirelang/persona_engine/nats_subjects.py` ist eine Sync-Folge-
/// Aufgabe (Tag-N+1) — bis dahin gilt Rust als Single-Source-of-
/// Truth.
///
/// Hash-Verfahren des Pins: SHA-256 über die UTF-8-Bytes der
/// concat-Liste mit `\n`-Separator. Wenn Python diese Liste
/// byte-identisch erzeugt und denselben SHA-256 berechnet, ist die
/// Cross-Lang-Parität bewiesen.
pub mod pins {
    /// Lifecycle-Pin: spawn-event einer Test-Persona.
    pub const FIXTURE_LIFECYCLE_SPAWNED: &str =
        "persona.lifecycle.reza-2026-05-17.spawned";

    /// Lifecycle-Pin: despawn-event derselben Test-Persona.
    pub const FIXTURE_LIFECYCLE_DESPAWNED: &str =
        "persona.lifecycle.reza-2026-05-17.despawned";

    /// Federation-Pin: Frame im Default-Cluster.
    pub const FIXTURE_FEDERATION_FRAME: &str =
        "persona.federation.cluster-eu-1.reza-2026-05-17.frame";

    /// Audit-Pin: Identity-Rotation-Audit.
    pub const FIXTURE_AUDIT_IDENTITY_ROTATE: &str =
        "persona.audit.identity-rotate.run-0001";

    /// Audit-Pin: Policy-Violation-Audit.
    pub const FIXTURE_AUDIT_POLICY_VIOLATION: &str =
        "persona.audit.policy-violation.run-0002";

    /// Anchor-Pin: Submit-Event eines Test-Batches.
    pub const FIXTURE_ANCHOR_SUBMITTED: &str =
        "persona.anchor.batch-2026-05-17.submitted";

    /// Recovery-Pin: Replay-Step einer Test-Recovery-Run.
    pub const FIXTURE_RECOVERY_REPLAY: &str =
        "persona.recovery.replay.run-0003";

    /// Recovery-Pin: Verify-Step derselben Recovery-Run.
    pub const FIXTURE_RECOVERY_VERIFY: &str =
        "persona.recovery.verify.run-0003";

    /// Vollständige Pin-Liste in stabiler Reihenfolge.
    ///
    /// Diese Reihenfolge ist Teil des Cross-Lang-Vertrags: Python
    /// MUSS dieselbe Reihenfolge emittieren, damit der `\n`-joined
    /// SHA-256 byte-identisch wird.
    pub const ALL_FIXTURES: &[&str] = &[
        FIXTURE_LIFECYCLE_SPAWNED,
        FIXTURE_LIFECYCLE_DESPAWNED,
        FIXTURE_FEDERATION_FRAME,
        FIXTURE_AUDIT_IDENTITY_ROTATE,
        FIXTURE_AUDIT_POLICY_VIOLATION,
        FIXTURE_ANCHOR_SUBMITTED,
        FIXTURE_RECOVERY_REPLAY,
        FIXTURE_RECOVERY_VERIFY,
    ];
}

// ---------------------------------------------------------------------------
// Inline-Unit-Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ---------- Round-trip pro Subject-Klasse (5 Tests) ----------

    #[test]
    fn test_lifecycle_subject_roundtrip() {
        let s = lifecycle_subject("reza-2026-05-17", "spawned").unwrap();
        assert_eq!(s, "persona.lifecycle.reza-2026-05-17.spawned");
    }

    #[test]
    fn test_federation_subject_roundtrip() {
        let s = federation_subject("cluster-eu-1", "reza-2026-05-17").unwrap();
        assert_eq!(s, "persona.federation.cluster-eu-1.reza-2026-05-17.frame");
    }

    #[test]
    fn test_audit_subject_roundtrip() {
        let s = audit_subject("identity-rotate", "run-0001").unwrap();
        assert_eq!(s, "persona.audit.identity-rotate.run-0001");
    }

    #[test]
    fn test_anchor_subject_roundtrip() {
        let s = anchor_subject("batch-2026-05-17").unwrap();
        assert_eq!(s, "persona.anchor.batch-2026-05-17.submitted");
    }

    #[test]
    fn test_recovery_subject_roundtrip() {
        let s = recovery_subject("replay", "run-0003").unwrap();
        assert_eq!(s, "persona.recovery.replay.run-0003");
    }

    // ---------- Invalid-Input-Rejection (6 Tests) ----------

    #[test]
    fn test_reject_token_with_dot() {
        // `.` ist NATS-Separator und darf nie innerhalb eines Tokens
        // auftauchen.
        let err = lifecycle_subject("foo.bar", "spawned").unwrap_err();
        match err {
            SubjectError::InvalidChar { character, field, .. } => {
                assert_eq!(character, '.');
                assert_eq!(field, "id");
            }
            other => panic!("unexpected error variant: {:?}", other),
        }
    }

    #[test]
    fn test_reject_empty_token() {
        let err = audit_subject("", "run-1").unwrap_err();
        assert!(matches!(err, SubjectError::EmptyToken { field: "kind" }));
    }

    #[test]
    fn test_reject_reserved_word_star() {
        let err = lifecycle_subject("*", "spawned").unwrap_err();
        match err {
            SubjectError::ReservedWord { field, value } => {
                assert_eq!(field, "id");
                assert_eq!(value, "*");
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn test_reject_reserved_word_gt() {
        let err = lifecycle_subject(">", "spawned").unwrap_err();
        assert!(matches!(err, SubjectError::ReservedWord { .. }));
    }

    #[test]
    fn test_reject_token_too_long() {
        let long = "a".repeat(MAX_TOKEN_LEN + 1);
        let err = lifecycle_subject(&long, "spawned").unwrap_err();
        match err {
            SubjectError::TokenTooLong { actual, max, field } => {
                assert_eq!(actual, MAX_TOKEN_LEN + 1);
                assert_eq!(max, MAX_TOKEN_LEN);
                assert_eq!(field, "id");
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn test_reject_leading_digit() {
        let err = lifecycle_subject("9abc", "spawned").unwrap_err();
        match err {
            SubjectError::LeadingDigit { field, value } => {
                assert_eq!(field, "id");
                assert_eq!(value, "9abc");
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    // ---------- Wildcard-Builders (4 Tests) ----------

    #[test]
    fn test_lifecycle_wildcard_all_events_with_id() {
        let p = lifecycle_wildcard_all_events("reza-2026-05-17").unwrap();
        assert_eq!(p, "persona.lifecycle.reza-2026-05-17.*");
    }

    #[test]
    fn test_lifecycle_wildcard_all_tail() {
        let p = lifecycle_wildcard_all().unwrap();
        assert_eq!(p, "persona.lifecycle.>");
    }

    #[test]
    fn test_federation_wildcard_by_cluster() {
        let p = federation_wildcard_by_cluster("cluster-eu-1").unwrap();
        assert_eq!(p, "persona.federation.cluster-eu-1.>");
    }

    #[test]
    fn test_persona_root_wildcard() {
        let p = persona_root_wildcard().unwrap();
        assert_eq!(p, "persona.>");
    }

    // ---------- Pin-Pack-Integrity (3 Tests) ----------

    #[test]
    fn test_pin_pack_count() {
        assert_eq!(
            pins::ALL_FIXTURES.len(),
            8,
            "Cross-Lang-Pin-Pack MUSS exakt 8 Fixtures haben"
        );
    }

    #[test]
    fn test_pin_pack_each_fixture_parses_as_builder_output() {
        // Jede Pin-Fixture muss durch die typed Builder reproduzierbar
        // sein — wenn das fehlschlägt, sind Pin-String und Builder
        // auseinandergedriftet.
        assert_eq!(
            pins::FIXTURE_LIFECYCLE_SPAWNED,
            lifecycle_subject("reza-2026-05-17", "spawned").unwrap()
        );
        assert_eq!(
            pins::FIXTURE_LIFECYCLE_DESPAWNED,
            lifecycle_subject("reza-2026-05-17", "despawned").unwrap()
        );
        assert_eq!(
            pins::FIXTURE_FEDERATION_FRAME,
            federation_subject("cluster-eu-1", "reza-2026-05-17").unwrap()
        );
        assert_eq!(
            pins::FIXTURE_AUDIT_IDENTITY_ROTATE,
            audit_subject("identity-rotate", "run-0001").unwrap()
        );
        assert_eq!(
            pins::FIXTURE_AUDIT_POLICY_VIOLATION,
            audit_subject("policy-violation", "run-0002").unwrap()
        );
        assert_eq!(
            pins::FIXTURE_ANCHOR_SUBMITTED,
            anchor_subject("batch-2026-05-17").unwrap()
        );
        assert_eq!(
            pins::FIXTURE_RECOVERY_REPLAY,
            recovery_subject("replay", "run-0003").unwrap()
        );
        assert_eq!(
            pins::FIXTURE_RECOVERY_VERIFY,
            recovery_subject("verify", "run-0003").unwrap()
        );
    }

    #[test]
    fn test_pin_pack_no_duplicates() {
        let mut sorted: Vec<&str> = pins::ALL_FIXTURES.to_vec();
        sorted.sort();
        sorted.dedup();
        assert_eq!(
            sorted.len(),
            pins::ALL_FIXTURES.len(),
            "Pin-Pack enthält Duplikate"
        );
    }

    // ---------- Token-Validation-Edge-Cases (4 Tests) ----------

    #[test]
    fn test_is_valid_token_examples() {
        assert!(is_valid_token("reza"));
        assert!(is_valid_token("reza-2026-05-17"));
        assert!(is_valid_token("a"));
        assert!(is_valid_token("a_b-c"));
        assert!(!is_valid_token(""));
        assert!(!is_valid_token("*"));
        assert!(!is_valid_token(">"));
        assert!(!is_valid_token("9abc"));
        assert!(!is_valid_token("a.b"));
        assert!(!is_valid_token("a b"));
    }

    #[test]
    fn test_token_validation_order_reserved_before_length() {
        // Reserved-Word-Check kommt VOR Length-Check, weil Reserved
        // Words alle ≤ 1 Byte sind. Hier prüfen wir, dass "*"
        // als ReservedWord rapportiert wird (nicht etwa als
        // "TokenTooLong" für eine 1-Byte-Eingabe — was logisch ohnehin
        // nicht greift, aber wir wollen den Pfad festschreiben).
        let err = validate_token("*", "x").unwrap_err();
        assert!(matches!(err, SubjectError::ReservedWord { .. }));
    }

    #[test]
    fn test_token_validation_order_leading_digit_specific() {
        // Pure-Digit-Token soll als LeadingDigit gemeldet werden
        // (spezifischer als InvalidChar).
        let err = validate_token("123", "x").unwrap_err();
        assert!(matches!(err, SubjectError::LeadingDigit { .. }));
    }

    #[test]
    fn test_token_validation_invalid_char_after_first() {
        // Erstes Zeichen Buchstabe (valide), zweites Zeichen `.`
        // (invalid) → InvalidChar an Position 1.
        let err = validate_token("a.b", "x").unwrap_err();
        match err {
            SubjectError::InvalidChar { position, character, .. } => {
                assert_eq!(position, 1);
                assert_eq!(character, '.');
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    // ---------- Error-Display (1 Test) ----------

    #[test]
    fn test_error_display_messages() {
        let err = SubjectError::EmptyToken { field: "id" };
        assert_eq!(err.to_string(), "token field \"id\" is empty");

        let err = SubjectError::ReservedWord {
            field: "id",
            value: "*".to_owned(),
        };
        assert_eq!(
            err.to_string(),
            "token field \"id\" uses reserved word \"*\""
        );
    }
}
