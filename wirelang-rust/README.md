# wirelang-rust — Phase-1c Rust workspace (scaffolding)

Status: **Phase-1c preparation, not yet replacing Python.**

This Cargo workspace is the Rust pendant of the `wirelang/persona/`
Python tree. It exists to anchor Phase-1c (ADR-0035 Errata 1, approved
2026-05-07 12:55 CEST) one byte at a time:

1. `persona-hash` (this scaffold) — V-907 hash primitive.
2. *(future)* `persona-canonical-form` — YAML front-matter + canonical
   subset extractor.
3. *(future)* `persona-migration` — V0->V1 step + linear-chain walker.
4. *(future)* `persona-cli` — Rust pendant for `wakir-persona migrate`.

## Determinism contract

Every Rust crate in this tree must produce **byte-identical** output
to the corresponding Python module for the V-907 9-vector pin pack:

- `wirelang/persona/_internal/pin_pack_constants.py::PERSONA_HASH_PIN_V{1..9}`

The Python tree is the temporary source of truth; the Rust tree must
match before any consumer is migrated. The cross-check ground-truth
JSON for V9 lives at
`crates/persona-hash/tests/fixtures/v9-ground-truth.json`. Future
boxes will add V1..V6+V8-migrated.

## Build / test (when toolchain is available)

```sh
cd wirelang-rust
cargo test --workspace
```

Requires a Rust toolchain (>= 1.85) AND a system C linker (`cc`/`ld`).
A user-local rustup install is sufficient for `rustc`/`cargo` but not
for the linker; on Fedora that means `dnf install gcc` (sudo).

## Layering

This crate is **library-only**. CLI and YAML-parsing layers come in
follow-up boxes. The split mirrors Python's
`persona_canonical_form.py -> persona_hash.py -> persona_migration.py
-> cli.py` order; we migrate in that order to keep the V-907 anchor
stable through the transition.
