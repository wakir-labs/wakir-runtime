//! Operator-side pin-pack derivation example.
//!
//! Prints the V-907 persona-hash for each of the 13 active personae.
//! Intended for the Sprint-Pengine-7 Tag-1 outbox report and as the
//! seed of the operator-side pin-pack registry (§5.2 of the spec).
use persona_engine_format::{
    jcs_canonicalise_wakir_persona_v1, map_claude_native_to_wakir_v1, wakir_persona_hash,
};
use std::collections::BTreeMap;

const PERSONA_FIXTURES: &[(&str, &str)] = &[
    ("mira", include_str!("../tests/fixtures/claude-agents/mira.md")),
    ("cto", include_str!("../tests/fixtures/claude-agents/cto.md")),
    ("hr", include_str!("../tests/fixtures/claude-agents/hr.md")),
    ("cfo", include_str!("../tests/fixtures/claude-agents/cfo.md")),
    ("comms", include_str!("../tests/fixtures/claude-agents/comms.md")),
    ("internal-audit", include_str!("../tests/fixtures/claude-agents/internal-audit.md")),
    ("dev-engineering", include_str!("../tests/fixtures/claude-agents/dev-engineering.md")),
    ("reza", include_str!("../tests/fixtures/claude-agents/reza.md")),
    ("kai", include_str!("../tests/fixtures/claude-agents/kai.md")),
    ("pengine", include_str!("../tests/fixtures/claude-agents/pengine.md")),
    ("frontend", include_str!("../tests/fixtures/claude-agents/frontend.md")),
    ("qa", include_str!("../tests/fixtures/claude-agents/qa.md")),
    ("sre", include_str!("../tests/fixtures/claude-agents/sre.md")),
];

fn main() {
    let mut out = BTreeMap::new();
    for (slug, text) in PERSONA_FIXTURES {
        let doc = map_claude_native_to_wakir_v1(text).expect("map");
        let hash = wakir_persona_hash(&doc).expect("hash");
        let bytes = jcs_canonicalise_wakir_persona_v1(&doc).expect("jcs");
        out.insert(slug.to_string(), (hash, bytes.len()));
    }
    println!("| Persona | V-907 Persona-Hash | JCS bytes |");
    println!("|---|---|---|");
    for (slug, (hash, len)) in &out {
        println!("| `{slug}` | `{hash}` | {len} |");
    }
}
