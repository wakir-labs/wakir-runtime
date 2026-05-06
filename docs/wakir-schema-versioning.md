# Wakir Schema Versioning Convention (Phase-1a)

**Status:** Phase-1a Tag-15 baseline. Owner: wirelang-eng
(Wirelang / Capability-Token-Layer / Identity-Substrate-Owner).
This convention covers the seven Wirelang schemas indexed in
[`wirelang-schema-inventory.md`](./wirelang-schema-inventory.md).
WAT-manifest-spec versioning remains under wat-eng's
(Matrix-Lead) owner-right and is **not** covered here
(Cross-Review-Zone-3 boundary).

## Rule: SemVer in `$id`

Every Wakir-owned JSON Schema declares an `$id` of the form

```
https://wakir.dev/wirelang/schema/<slug>/<MAJOR>.<MINOR>.<PATCH>
```

The `<slug>/<MAJOR>.<MINOR>.<PATCH>` segment is the
**immutable identifier**: a published schema body is **never**
edited in place. To change a schema, publish a new file with a
new `$id` and let the registry index both old and new during the
overlap window.

## Bump Decisions

| Bump  | Examples                                                                             | Consumer impact                                  |
|-------|--------------------------------------------------------------------------------------|--------------------------------------------------|
| MAJOR | required field added, removed, renamed; type changed; allowed-values set narrowed    | breaking; opt-in by consumers                    |
| MINOR | optional field added (and `additionalProperties: false` widened to allow it); new optional `$defs` exposed | non-breaking; consumers may ignore the new field |
| PATCH | `description`, `title`, `$comment`, error-message-only changes; spelling fixes       | none structural                                  |

The PATCH-on-description rule means a documentation cleanup can
be shipped without a MINOR bump, **only if** every byte of
schema-effective content stays identical.

### Edge cases

- **Tightening `additionalProperties` from `true` to `false`** is
  MAJOR (consumers that previously sent extra keys break).
- **Loosening `required` to optional** is MAJOR for *producers*
  of strict tools that infer types, but practically MINOR for
  most validators; default is **MAJOR** unless an explicit
  ADR-style note loosens that.
- **Adding an entry to a `enum`** is MINOR.
- **Removing an entry from a `enum`** is MAJOR.

## Overlap Window (Lese-SLA)

When a MAJOR bump publishes `<slug>/2.0.0`, the previous
`<slug>/1.x.y` body remains in the registry **for at least 90
days** so consumers can migrate without a hard cliff. Phase-1a
ships only `0.1.0`s; the 90-day window starts the day a `1.0.0`
or later is first published. A shorter window is acceptable
**only** with explicit CEO-approval (ADR-style note).

## File Layout During Overlap

During the overlap window, two files coexist in
`wirelang/schemas/`:

```
wirelang/schemas/aip-document.json          # current (e.g. 2.0.0)
wirelang/schemas/aip-document-1.x.json      # legacy (e.g. 1.3.0), retained
```

The legacy file's `$id` retains its old SemVer. Both files are
indexed by the registry; consumers select by `$id`. After the
overlap window, the legacy file is deleted in a single commit
that explicitly cites the publication date of the MAJOR bump.

## Producer Side: How a Bump Lands

1. Author writes the new schema body to a new file. The new
   file's `$id` carries the new SemVer.
2. Author **does not edit the previous file**. The previous
   file remains byte-for-byte identical.
3. Author updates `docs/wirelang-schema-inventory.md` to list
   both versions side-by-side during the overlap window.
4. Author updates Wirelang Python consumers
   (`wirelang/identity/*.py`, `wirelang/builder/*.py`) to point
   at the new `$id`. Tests pin the new `$id` string.
5. Cross-review: any MAJOR bump triggers a Cross-Review-Zone-3
   sync-memo to wat-eng (Matrix-Lead). MINOR/PATCH bumps do not
   require a memo but **do** require a regular Tag-N outbox
   entry.

## Consumer Side: How a Consumer Migrates

A consumer that currently calls
`get_schema("https://wakir.dev/wirelang/schema/aip-document/0.1.0")`
migrates by:

1. Updating the `$id` literal in code (or in a single constant
   defined per consumer module).
2. Re-running tests; structural breakages surface immediately
   under JSON-Schema validation.
3. Filing a short PR-description that names the old `$id`, the
   new `$id`, and which fields the migration touched.

## Consumer Obligation: Registry-Lookup Only (Tag-16)

**Effective Phase-1a Tag-16, every Wirelang-internal consumer of
a Wakir schema MUST go through the registry API.** Direct
file-path opens of `wirelang/schemas/*.json` are no longer the
supported pattern.

### Required pattern

```python
from wirelang.schemas import get_schema

# Define the schema $id once per module (or once per fixture).
_AIP_DOCUMENT_ID = "https://wakir.dev/wirelang/schema/aip-document/0.1.0"

schema = get_schema(_AIP_DOCUMENT_ID)
```

### Forbidden pattern

```python
# Do not do this in Wirelang-internal code.
from pathlib import Path
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "aip-document.json"
with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
    schema = json.load(fh)
```

### Why

- **Backend portability.** Phase-1b may move schema storage
  behind a NATS-KV or HTTP-fetch backend. Consumers that already
  go through `get_schema($id)` migrate transparently; consumers
  on direct file-path access break.
- **Version pinning.** A `$id` string carries the SemVer in plain
  text. A file-path string carries only the slug. Consumers on
  `$id` cannot accidentally drift onto a future MAJOR bump's
  file when the legacy file is renamed.
- **Audit-trail.** Every `get_schema` call is greppable; direct
  `json.load(SCHEMA_DIR / ...)` calls are not.

### Out-of-scope (still allowed on direct path)

The registry indexes **schemas only**. Test fixtures, example
frames, and golden vectors stay on direct file-path access — they
are illustrative payloads, not registry-indexed artefacts. The
Tag-16 migration left the example-frame fixtures
(`frame-domain-event-example.json`, etc.) untouched on purpose.

### Phase-1b Onboarding Hook

When a Phase-1b consumer onboards (Container-Bridge under
container-bridge-eng, Persona-Engine under persona-engine-eng),
it MUST onboard directly on `get_schema($id)` from day one.
**Onboarding via direct
file-path access is not a supported migration step.** This is
a hard rule, not a recommendation: a Phase-1b consumer that
shows up with a `Path(...) / "schemas" / ...` import in its
review carries a blocking comment.

### Lint Hook (Tag-17, wired as pytest-AST test)

Effective Phase-1a Tag-17, the Consumer Obligation is enforced
mechanically by
[`wirelang/tests/test_no_direct_schema_imports.py`](../wirelang/tests/test_no_direct_schema_imports.py).
The test walks every `.py` file under `wirelang/`, parses the AST,
and fails if any non-allowlisted module contains a string literal
of the form `wirelang/schemas/<slug>.json` (or
`schemas/<slug>.json` reaching a file-opening API).

**Allowlist** (intentional, audit-justified):

| Module                          | Why it is allowed                     |
|---------------------------------|---------------------------------------|
| `wirelang/schemas/registry.py`  | builds the index by scanning the dir |
| `wirelang/schemas/__init__.py`  | re-exports the registry API          |
| `wirelang/tests/test_no_direct_schema_imports.py` | constructs forbidden literals as test fixtures |

**What the test catches:**

* a freshly introduced `Path("wirelang/schemas/...json")` literal
  in any code path under `wirelang/` (positive test;
  breach-probe-verified on Tag-17);
* a literal split across an f-string concatenation chunk that
  re-assembles the forbidden path;
* a same-style literal inside a `JoinedStr` (f-string).

**What the test deliberately does not catch:**

* docstring narrative references like
  `"validates against wirelang/schemas/aip-document.json"`
  (stripped before scanning);
* example-frame paths like `examples/frame-domain-event-example.json`
  (different directory, not registry-indexed);
* test-vector paths like `fixtures/vector-1.json` (out of scope per
  the "Out-of-scope" section above);
* DID document paths like `.well-known/did/treasury-issuer/v1.json`
  (different directory, different ownership).

If a future contributor reasons that they need a new direct-load
exemption, the path is: edit the `_ALLOWLIST_RELATIVE` constant in
the test file in the same commit that introduces the new code,
with a one-line comment justifying the exemption. Reviewers
(wirelang-eng or wat-eng / Matrix-Lead under Zone 3) decide
whether to accept the exemption or push back.

**Pre-commit-Hook (Phase-1b candidate, not Tag-17):** the same
AST scan can be re-packaged as a pre-commit hook so violations
fail before push, not only at CI time. A Tag-17 sketch lives in
the Tag-17 outbox §3 (KW-21+ work item; pytest-AST already
provides the CI gate, pre-commit would be a usability uplift, not
a correctness uplift).

## Phase-1a Baseline

All seven Wirelang schemas currently sit at `0.1.0`. The
explicit `0.x.y` major-zero range signals **pre-1.0 vocabulary**
- breaking changes within `0.x` are still allowed without the
overlap-window obligation, but every such change still requires
the **producer-side workflow** (steps 1-5 above) to land cleanly
in the registry.

The first `1.0.0` triggers the full overlap-window discipline.
Phase-1a Tag-15 does not target a `1.0.0`; that decision belongs
to Phase-1b or later.

## Cross-Review Notes

- **wat-eng (Zone 3, WAT-Manifest-Spec):** if WAT-Manifest-Spec
  adopts a different versioning convention, the two
  conventions can coexist; both reference distinct `$id`
  spaces. A unified convention is desirable but **not** required
  for Phase-1a. The "Consumer Obligation" section above applies
  to **Wirelang-internal** consumers; WAT consumers of the
  WAT-Manifest schema follow wat-eng's convention.
- **persona-engine-eng (Zone L, Persona-Engine):** when
  persona-definition schemas land in Phase-1b, they will follow
  this convention. The Persona-Engine onboards directly on
  `get_schema($id)` from day one (see "Phase-1b Onboarding Hook"
  above).
- **container-bridge-eng (Zone J, Container-Bridge):** Phase-1b
  container-bridge schemas will follow this convention if they
  are Wakir-owned. The Container-Bridge onboards directly on
  `get_schema($id)` from day one (see "Phase-1b Onboarding Hook"
  above).

— wirelang-eng
