<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Self-Migration Converter Spec (Phase-1b Sprint-2)

| Field | Value |
|---|---|
| Spec ID | ADR-0036 / V-907 (Pillar-3 consumer) |
| Module | `wirelang/persona/persona_migration.py` |
| Step registry | `wirelang/persona/_internal/migration_steps.py` |
| CLI entry-point | `wakir-persona migrate ...` (`wirelang/persona/cli.py`) |
| Companion spec | `wirelang/specs/persona-hash-spec.md` (V-907) |
| Phase | 1b (Python bootstrap; Phase-1c Rust re-write follows ADR) |
| Format ratification | engine-default mock + Default-Lock A-1/A-2/A-3 (ratified 2026-05-07 ~10:00 CEST by ceo-slot via the engine-side inbox decision file). |
| Cross-review zones | K (WAT-bridge — Phase-2 P2-01 only), L (identity-substrate — I-15 loader pending), HR (A-2 marker pending until ADR-0029-Annex KW 23). |

## 1. Purpose

The self-migration converter answers a single Wakir-Orga question from
ADR-0036:

> When a persona-definition was authored against schema-version `v_n`
> and the engine has moved on to `v_{n+1}`, *who* migrates the
> definition forward, *when*, and on what byte-deterministic
> guarantee?

The converter is the answer. It walks an explicit linear chain of
`MigrationStep` objects from a source schema-version to a target
schema-version, returning a canonical-subset dict that
`compute_persona_hash_from_canonical` will hash to the pin of the
equivalent native target-version fixture. Migration is one direction:
a definition crosses the `v_n -> v_{n+1}` boundary once, in code, and
never silently.

The converter is the **third-pillar bridge** of the V-907
audit-pin pillars: AIP-document hash, capability-token hash, and
persona-hash form the WAT frame's audit surface; the converter is
what keeps the persona-hash pillar usable across schema-version
shifts without losing pin-stability.

## 2. Scope and non-goals

### 2.1 In scope

- Multi-step linear migration chains (`v_n -> v_{n+1} -> ... -> v_m`)
  resolved at call-time from a flat registered-steps tuple.
- Three input shapes: parsed front-matter `dict`, raw markdown `str`
  (must start with the `---` fence), and filesystem `Path`.
- Optional caller-supplied post-migration hash pin for byte-equality
  enforcement (`expected_post_migration_hash`, accepts both bare
  64-hex form and full `sha256:<64hex>` form).
- Defensive error surface: front-matter parse failures from
  `persona_canonical_form` are re-wrapped as `PersonaMigrationError`
  with the original exception chained via `__cause__`.
- Operator CLI wrapper `wakir-persona migrate` for ad-hoc use and
  CI-pipeline integration; emits canonical-subset JSON on stdout and
  the post-migration hash on stderr.

### 2.2 Out of scope (Phase-1b)

- **Markdown-body migration.** The body is out-of-hash by V-907
  design (`persona-hash-spec.md` §1). If a future canonical subset
  pulls body fragments in, the body-reader extends
  `persona_canonical_form`, not this module.
- **Branching DAG.** The Phase-1b registry is a linear chain; the
  resolver carries a 32-step cycle-detection guard, not a feature
  for parallel branches. Branching is a Phase-2 item (P2-02).
- **Migration-audit-trail in WAT-leaf-slot.** The converter emits
  pre/post hash pairs on demand; the pairing into a WAT frame is
  Cross-Review Zone K (P2-01), wat-eng-slot owns. No WAT-frame
  is produced from this module.
- **Schema-Registry-loader integration (I-15).** The converter
  currently consumes JSON-Schema files directly from
  `wirelang/schemas/persona-v_n.json`. Once the identity-eng-slot
  ships I-15, the converter's pre/post validation calls switch to
  `SchemaRegistry.validate(d, "persona-v_n")` (Cross-Review Zone L).
- **Inverse migration `v_{n+1} -> v_n`.** Migration is intentionally
  not invertible (Tag-4-Skizze §2.2 Regel B2 / §4.4 marker M-3). A
  Default-Wert-Auffuell-Step at `v_n -> v_{n+1}` loses
  "absent vs. default-explicit" information; the inverse is not a
  safe reconstruction.

## 3. Default-Lock posture (A-1 / A-2 / A-3)

The converter operates entirely within the Default-Lock that
ratified the V-907 mock canonical subset:

| Lock | Statement | Converter consequence |
|---|---|---|
| **A-1** | The mock canonical subset is the input shape (Tag-2 baseline). | Steps consume and emit canonical-subset dicts; raw markdown is parsed once at the public-API boundary by `_coerce_to_dict`. |
| **A-2** | semver-major-only, additiv-only, linear chain. | Every registered step is additive on the v-next side; key removal is forbidden. The resolver assumes linear progression and surfaces unreachable-target as `PersonaMigrationError`. |
| **A-3** | front-matter is in-hash, markdown body is out-of-hash. | Steps never read or edit the body. The body passes through the converter untouched (it is not even materialised inside the chain). |

A-2 in particular is the load-bearing assumption for the resolver:
field removal would invalidate the linear-walk algorithm, since a
v_{n+1} reader would no longer be a superset of v_n. Removing this
constraint is a Phase-2 change.

## 4. Determinism guarantees (V-907 pin-pillar)

The converter is byte-deterministic by construction. Tag-4-Skizze §2.3
identified three classes of determinism risk; the implementation
neutralises each:

| Risk class | Mechanism | Mitigation site |
|---|---|---|
| **D-1: Dict-key order** | Python `dict` insertion order vs. JCS canonical order. | Output is always projected through `compute_persona_hash_from_canonical` (or the operator hashes the JCS form externally); steps return raw dicts but the consumer hashes via JCS. The converter never persists a non-JCS dict to disk. |
| **D-2: Default-value inference** | JSON-Schema default-fill order is not deterministic across JSON-Schema implementations. | Every step writes default values **explicitly** in code (`out["schema_version"] = self.target_version`, never `validator.fill_defaults(out)`). Step bodies are pure Python dict edits. |
| **D-3: String encoding** | Unicode-normalisation drift (NFC vs. NFD) shifts the JCS bytes. | Strings pass through `rfc8785` JCS, which preserves the input form; canonical dicts are required to be NFC at the source-fixture level. The converter does not introduce non-ASCII strings on its own. |

The optional caller-pin path (`expected_post_migration_hash`)
turns "byte-deterministic by construction" into a runtime check: the
converter re-hashes the migrated canonical subset and raises
`PersonaMigrationDeterminismError` on drift.

## 5. Public API surface

```python
from wirelang.persona import (
    PERSONA_SCHEMA_VERSION_LATEST,    # "persona-v1"
    PERSONA_SCHEMA_VERSION_LIST,      # ("persona-v0", "persona-v1")
    PersonaMigrationDeterminismError,
    PersonaMigrationError,
    migrate_persona,
)
```

### 5.1 `migrate_persona`

```python
def migrate_persona(
    definition: dict | str | Path,
    *,
    target_schema_version: str = PERSONA_SCHEMA_VERSION_LATEST,
    expected_post_migration_hash: str | None = None,
) -> dict: ...
```

- **Returns** a canonical-subset dict at `target_schema_version`,
  consumable by `compute_persona_hash_from_canonical`.
- **Raises** `PersonaMigrationError` on unknown source/target
  versions, no path between them, suspected cycle, malformed raw
  markdown, missing/malformed front-matter, or non-string
  `schema_version`.
- **Raises** `PersonaMigrationDeterminismError` when an
  `expected_post_migration_hash` is supplied and disagrees with the
  freshly-computed hash.
- **Raises** `TypeError` for inputs that are not `dict | str | Path`.
- **Raises** `FileNotFoundError` for `Path` inputs that do not exist.

### 5.2 Errors

| Class | Inherits | Meaning |
|---|---|---|
| `PersonaMigrationError` | `ValueError` | Chain not resolvable (unknown version, no path, cycle, malformed input). |
| `PersonaMigrationDeterminismError` | `RuntimeError` | Caller-pin disagreement after a successful chain run. |

Front-matter parse failures from `persona_canonical_form` are
**re-wrapped** as `PersonaMigrationError`; the original exception is
available via `__cause__` for forensic inspection. This keeps
call-sites at single-class import.

## 6. Step registry contract

A `MigrationStep` is a `runtime_checkable` Protocol:

```python
class MigrationStep(Protocol):
    source_version: str
    target_version: str
    def apply(self, definition_dict: dict) -> dict: ...
```

Concrete step requirements (audit-grade):

1. **Pure.** No filesystem reads, no network, no time, no random.
2. **Non-mutating on input.** `apply(d)` deep-copies before editing.
3. **Deterministic.** Two calls with byte-identical input produce
   byte-identical output.
4. **Source-version-strict.** `apply` raises `ValueError` if
   `definition_dict["schema_version"] != self.source_version`.
5. **No JSON-Schema default inference.** All injected defaults are
   written explicitly (D-2 mitigation).

The active registry as of Sprint-2 Tag-3 carries one entry,
`V0ToV1Step`, which performs only the schema-version lift
(Tag-4-Skizze §3.2 R1-R4). Future entries append in linear order.

## 7. Operator CLI (`wakir-persona migrate`)

The CLI is a thin wrapper around `migrate_persona` for ad-hoc
operator use, CI integration, and the wakir-runtime
self-migration shell scripts that ADR-0036 anticipates.

### 7.1 Synopsis

```
wakir-persona migrate <persona-file>
                      [--target persona-v1]
                      [--expect-hash <pin>]
                      [--emit-hash]
                      [--quiet]
```

### 7.2 Inputs

- **`<persona-file>`** — filesystem path to a UTF-8 markdown
  persona-definition. The CLI does not accept `-` (stdin) in this
  cut; pipe via a temporary file if needed.

### 7.3 Outputs

- **stdout** — JSON serialisation of the migrated canonical-subset
  dict (sorted keys, two-space indent, terminating newline). Suitable
  for `| jq` and for piping into `compute_persona_hash_from_canonical`
  in a downstream step.
- **stderr** — when `--emit-hash` is set, the post-migration
  persona-hash on a single line in `sha256:<64hex>` form. Otherwise
  silent unless `--quiet` is unset and a progress line is emitted.

### 7.4 Exit codes

| Code | Condition |
|---|---|
| `0` | Migration completed; if `--expect-hash` supplied, the pin matched. |
| `1` | `PersonaMigrationError` (chain not resolvable, malformed input, ...). |
| `2` | `PersonaMigrationDeterminismError` (`--expect-hash` mismatch). |
| `3` | `FileNotFoundError` on the `<persona-file>` argument. |
| `64` | argparse usage error (mirrors Unix `EX_USAGE`). |

### 7.5 Examples

Migrate an old `persona-v0` file to the engine-current version and
print the canonical subset:

```
$ wakir-persona migrate /path/to/legacy-persona.md
{
  "description": "...",
  "identity_pinned": { ... },
  "name": "...",
  "schema_version": "persona-v1",
  "tools": [...]
}
```

Emit the post-migration hash on stderr (suitable for shell capture):

```
$ wakir-persona migrate /path/to/legacy-persona.md --emit-hash 2>hash.txt 1>out.json
$ cat hash.txt
sha256:0f29889420...1d793
```

Hard-pin the expected target hash and fail the run on drift:

```
$ wakir-persona migrate /path/to/legacy-persona.md \
    --expect-hash sha256:0f29889420...1d793 --quiet
$ echo $?
0
```

## 8. Test posture

The Sprint-2 implementation ships with three test files:

| File | Coverage | Test count (Sprint-2 Tag-3) |
|---|---|---|
| `tests/test_persona_migration.py` | Public-API happy paths (S2-T1-01, S2-T1-02). | 6 |
| `tests/test_persona_migration_edge_cases.py` | Defensive belt: degraded front-matter, malformed inputs, immutability, cycle-guard (S2-T1-03). | 19 |
| `tests/test_persona_migration_roundtrip.py` | Cross-version round-trip + idempotence + input-shape-equivalence (S2-T1-04). | 9 |
| `tests/test_persona_migration_cli.py` | Operator CLI (Sprint-2 Tag-3, S2-T1-06). | (see test file) |

The existing fixtures `wirelang/tests/fixtures/persona_definitions/v8-persona-pre-framework.md`
and `v9-persona-framework-native.md` form the Sprint-2 round-trip
anchor: a successful `v8 -> v1` migration must reproduce the
`PERSONA_HASH_PIN_V9` constant byte-for-byte.

## 9. Cross-review zones (status as of Sprint-2 Tag-3)

| Zone | Partner | Status | Trigger |
|---|---|---|---|
| **K** (WAT-Hash V-907) | wat-eng-slot | tracking only | Phase-2 item P2-01 (migration-audit-trail in WAT-leaf-slot). No converter-side change required for Sprint-2. |
| **L** (Identity-Substrate) | identity-eng-slot | I-15 schema-registry loader pending | Once I-15 lands, swap direct `wirelang/schemas/persona-v_n.json` reads for `SchemaRegistry.validate`. |
| **J** (Container-Bridge) | container-ops-slot | not initiated | Phase-1b Sprint-3 or later. |
| **HR** (Persona-Definition format) | hr-slot | A-2 marker pending until ADR-0029-Annex deadline KW 23 (2026-06-02). | If HR ratifies a `persona-v2` shape, a `V1ToV2Step` is added to the registry; the resolver chains v0 inputs through `[V0ToV1Step(), V1ToV2Step()]` automatically. |

A re-pin sweep on HR ratification is mechanical: re-run the chain on
each fixture, record the new pin in `_internal/pin_pack_constants.py`,
re-run the test pack. No public-API change is anticipated.

## 10. Phase-1c carry-over

The Phase-1c Rust re-write of `persona_hash.py` is scheduled (Tag-8
sketch). The converter follows the same posture: `persona_migration.rs`
is a candidate Phase-1c module, with the registry encoded as a Rust
trait-object slice. The byte-deterministic guarantee is unchanged —
JCS plus explicit defaults — so the Python and Rust implementations
must agree byte-for-byte on the canonical-subset output for every
fixture in the test pack.

The CLI wrapper is intentionally Python-only in Phase-1b; if the
Rust core ships with a binary entry-point, the operator CLI may
either become a thin Python shim over the Rust binary or migrate
entirely.

## 11. References

- `wirelang/specs/persona-hash-spec.md` — V-907 hash function and
  canonical-subset definition.
- `wirelang/persona/persona_migration.py` — implementation.
- `wirelang/persona/_internal/migration_steps.py` — step registry.
- `wirelang/persona/cli.py` — operator CLI wrapper (Sprint-2 Tag-3).
- ADR-0036 — Self-Migration der Wakir-Orga auf wakir-runtime.
- ADR-0029 (and pending Annex KW 23) — HR Persona-Definition
  format ratification.
- RFC 8785 — JSON Canonicalization Scheme (JCS).
