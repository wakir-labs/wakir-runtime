# Anthropic Prompt-Caching — Phase-2a Implementation Annex

**Status:** delivered (Sprint-Pengine-14, 2026-05-16).
**Authoritative ADR:** ADR-0064 (Model-Routing + Prompt-Caching, approved
2026-05-16). This file is an *implementation annex* — it documents how
the Phase-2a §"Folgeartefakte" item 1 lands in the codebase. The ADR
remains the single source of truth for the architectural decision.

## What ships

`wirelang/persona_engine/anthropic_cache.py` — pure-Python substrate for
the Anthropic Messages API prompt-caching B.2 pattern. No `anthropic`
SDK import; no HTTP call. Provides:

1. **`resolve_cache_ttl_from_env()`** — reads
   `WAKIR_ANTHROPIC_CACHE_TTL_SECONDS` (default `300`), maps integer
   seconds to one of the two Anthropic-API TTL strings (`"5m"` or
   `"1h"`), and surfaces a `CacheTtlResolution` envelope that records
   the resolution provenance (`source=env|default`). `0` disables
   caching entirely.

2. **`derive_cache_affinity_key()`** — builds a Wakir-side telemetry key
   `anthropic:<model>:<persona_id>:<v907_pin>:ttl<seconds>` that pins
   the cache identity to (model, persona, V-907-pin, TTL-slot). The key
   is *not* sent to Anthropic — it is a log/metric label that lets
   operators cross-reference Anthropic-side cache hits with Wakir-side
   persona-pin changes. Pin-change automatically rotates the affinity
   key, mirroring the Anthropic-side cache-miss-on-prefix-change
   behaviour (the prefix tokens include the persona-def text whose
   hash is the V-907 pin).

3. **`build_anthropic_request_payload()`** — composes the Messages API
   request payload with the cache breakpoint on the **last text block
   of the `system` array** (the static prefix: system prompt +
   persona-def + tool descriptions). The per-task `messages` content
   carries no `cache_control` — it is intentionally cache-miss on every
   call. Exactly the B.2 pattern from ADR-0064.

4. **`parse_cache_telemetry()`** — parses the Anthropic response
   `usage` object into a `CacheTelemetry` dataclass with:
   - `cache_read_input_tokens` / `cache_creation_input_tokens` (the two
     fields documented at the Anthropic Messages API page,
     URL-200-stamped 2026-05-16);
   - `cache_hit_rate_input_only` (read / (read + creation + uncached));
   - per-slot breakdown (`ephemeral_5m_input_tokens` /
     `ephemeral_1h_input_tokens`) when the response carries the
     `cache_creation` sub-dict, else `None`.
   - `to_structured_log_line()` emits a `sort_keys=True` JSON object
     under the event tag `"anthropic_cache_telemetry"` — drop-in for
     the persona-engine structured-JSON log substrate.

5. **`anthropic_hook_supports_caching()`** — module-level constant
   `True`. A live `AnthropicMessagesHook` delegates its
   `supports_caching()` method to this. Provider-lock-in boundary
   (ADR-0064 §"Provider-Lock-In"): OpenAI / other-provider hooks
   return `False` from their own `supports_caching()`.

## LLM-Hook protocol extension

`LlmCallHook` (in `llm_call_shim.py`) gains a `supports_caching() -> bool`
method:

- `EchoReflectionLlmHook` returns `False` — the Phase-2-Stub does not
  call an LLM, so it has no prefix to cache.
- The future `AnthropicMessagesHook` (Phase-3) returns
  `anthropic_hook_supports_caching()` = `True` and the engine attaches
  the B.2 cache_control block to the request.

## V-907 pin / cache-key contract

ADR-0064 §"Risiken und Annahmen" raises the V-907-Pin-Verify + Cache-
Conflict risk: if a persona-def hash invalidates but the Anthropic
cache is still warm, the stale prefix could keep producing stale-pin
output. Mitigation: the cache key on the Anthropic side is derived
from the prefix tokens themselves, which include the persona-def text;
the hash of that text *is* the V-907 pin. A pin-change therefore
guarantees a prefix-change, which guarantees an Anthropic-side cache-
miss. The Wakir-side affinity key in `derive_cache_affinity_key()`
makes that contract visible to operators: a pin-change in the
structured log shows up as an affinity-key change paired with a
non-zero `cache_creation_input_tokens` on the next request.

## What does NOT ship in Phase-2a

- **Live Anthropic HTTP-POST integration.** Phase-3 carries that;
  Sprint-Pengine-14 only delivers the payload-builder + telemetry-
  parser substrate. The `anthropic_messages_hook_phase_3_stub()` in
  `llm_call_shim.py` still raises `AnthropicMessagesHookNotImplemented`
  — the Phase-3 hook will replace that factory.
- **Prometheus textfile-gauge writer.** The optional bonus item in
  the Sprint-Pengine-14 auftrag was deferred to the SRE Phase-2b
  follow-up (Noa, ADR-0064 §"Folgeartefakte" Phase-2a item 2). The
  structured-JSON log line from `CacheTelemetry.to_structured_log_line()`
  is the substrate Noa's textfile-gauge writer will scrape.
- **Tool-array breakpoint.** `build_anthropic_request_payload()`
  passes `tools` through verbatim with no auto-decoration. A tool-
  array breakpoint is composable by callers but Phase-2a defaults to
  the system-tail-only breakpoint (the operator-stable surface).

## Test coverage

`wirelang/tests/persona_engine/test_anthropic_cache.py` — 29 hermetic
test vectors covering the six items listed in the Sprint-Pengine-14
auftrag plus 8 defence-in-depth vectors (model-scoping, persona-
scoping, malformed env, empty-prefix guard, frozen-dataclass
discipline, etc.). All pure-stdlib; no `anthropic` SDK; no network.

## Cross-references

- ADR-0064 (Model-Routing + Prompt-Caching, approved 2026-05-16).
- ADR-0063 (Persona-Engine-Sprach-Revision, approved 2026-05-16) —
  the Phase-2a caching substrate must be stable *before* the Phase-3
  Rust-Re-Write so that the Rust-engine inherits a working caching
  contract rather than re-deriving it.
- ADR-0035 §C (Sprach-pro-Komponente, approved 2026-05-06) — Phase-2a
  ships in Python (Pilot-Substrat-Pragma); the Rust port follows in
  Phase-3a (Reza-Hauptlast).
- Anthropic Messages API Prompt-Caching documentation
  (`https://docs.claude.com/en/docs/build-with-claude/prompt-caching`,
  HTTP-200-stamped 2026-05-16 13:17 CEST, redirects to canonical
  `platform.claude.com/docs/...` host).
