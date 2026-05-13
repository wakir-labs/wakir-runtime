# `wat/anchor/external_verifier/` — 4-Pole Cross-Library Verifier

Materialised form of the Position-Paper §L4-References annex
(`agents-workspaces/comms/outbox/2026-05-12-position-paper-pilot-vollentwurf.md`).
Third-party auditors checking a Wakir Audit Trail anchor can run
this module against any `.ots` receipt produced by the WAT pipeline
without operating any Wakir-controlled code beyond this directory
and the upstream OpenTimestamps CLI.

## Why four poles

A single library doing all four roles (OTS-receipt parsing,
Bitcoin-block-header lookup, proof-tree walk, hash comparison) is
exactly the single-implementation drift surface the audit trail is
meant to defeat. Four independent code paths converging on the same
verdict is the cross-library witness: a tampered receipt or a buggy
implementation would have to fool four independently-maintained
verifiers in the same direction, which is the threat model worth
designing against.

| # | Pole | Code path | Operator |
|---|------|-----------|----------|
| 1 | `pole_python_stdlib`     | offline OTS-receipt structural parse (Python stdlib; pluggable `pyopentimestamps` reader) | operator-host |
| 2 | `pole_ots_cli`           | shells out to upstream `ots` CLI                                                            | OpenTimestamps reference (Peter Todd et al.) |
| 3 | `pole_mempool_space`     | HTTPS GET `mempool.space/api/block-height/<H>`                                              | mempool.space team |
| 4 | `pole_esplora_blockstream` | HTTPS GET `blockstream.info/api/block-height/<H>`                                         | Blockstream |

Pole 1 stands in for the "python-bitcoinlib axis" named in the
Position-Paper annex. Wakir runtime does not declare a hard
dependency on `python-bitcoinlib` or `pyopentimestamps` (boring-
tech bias: zero extra audit surface on the brand-proof verifier).
Operators who want the full proof-tree walk inject their preferred
reader via the `proof_reader` override on the public API; the
default body verifies receipt structure and recorded block heights.

## Quorum

Default quorum is **3-of-4**: a single transient pole failure
(typical: a 503 from one HTTP pole) does not flip the verdict. An
operator wanting a stricter contract can request `--pols all`.

| Policy        | Quorum threshold  | Use case |
|---------------|-------------------|----------|
| `3-of-4`      | three poles `ok`  | default; tolerates one transient |
| `all`         | every pole `ok`   | strict audit; production CI |
| `2-of-4`      | two poles `ok`    | archive debugging; never default |

## Public API

```python
from wat.anchor.external_verifier import verify_wat_anchor, QuorumPolicy

result = verify_wat_anchor(
    anchor_hash="d16216b92bac7653828301b0b8b5595028a636eaf1bfd0f10d9b9a5fbd1b1894",
    ots_proof_path="/path/to/root.bin.ots",
    quorum_policy=QuorumPolicy.THREE_OF_FOUR,
    pole_overrides={
        "pole_mempool_space": {
            "expected_block_height": 948183,
            "expected_block_hash": "<canonical block hash>",
        },
        "pole_esplora_blockstream": {
            "expected_block_height": 948183,
            "expected_block_hash": "<canonical block hash>",
        },
    },
)
print(result.quorum)         # True / False
print(result.pole_results)   # {name: PoleResult, ...}
```

Every pole returns a `PoleResult` with:

* `ok: bool` — independently verified
* `verdict: str` — `"verified" | "failed" | "unavailable"`
* `witness: dict` — observed evidence (heights, hashes, snippets)
* `note: str` — diagnostic on non-success

`unavailable` is not a fail vote under the default 3-of-4 policy;
under `all` it is.

## CLI quickstart

```sh
wat-verify --anchor <hash> --ots-proof <file>
wat-verify --anchor <hash> --ots-proof <file> --pols all
wat-verify --anchor <hash> --ots-proof <file> \
           --expected-block-height 948183 \
           --expected-block-hash <hex>
wat-verify --anchor <hash> --ots-proof <file> \
           --skip-pole pole_mempool_space \
           --skip-pole pole_esplora_blockstream
```

Output: JSON to stdout. Exit codes: `0` (quorum reached), `1` (audit
failure: quorum not reached), `2` (CLI usage error).

When `--expected-block-height` is omitted, the two HTTP poles are
trimmed automatically and the quorum runs against the two offline
poles; this is the brand-proof rerun mode for operators who do not
want to touch the public network at all.

## Test injection

Every pole exposes a per-call seam for hermetic testing:

* `pole_python_stdlib` — `proof_reader` callable.
* `pole_ots_cli` — `ots_runner` callable returning a `CompletedProcess`-shape.
* `pole_mempool_space` / `pole_esplora_blockstream` — `transport`
  callable returning an `HttpResponse(status, body)`.

The test suite under `tests/wat/external_verifier/` runs the full
4-pole aggregator entirely offline using these injection points.

## Failure semantics, by example

| Pole 1 | Pole 2 | Pole 3 | Pole 4 | Default 3-of-4 | `all` |
|--------|--------|--------|--------|----------------|-------|
| ok     | ok     | ok     | ok     | verified       | verified |
| ok     | ok     | ok     | unavailable | verified  | failed |
| ok     | ok     | unavailable | unavailable | failed | failed |
| ok     | ok     | failed | ok     | verified       | failed |
| ok     | failed | failed | failed | failed         | failed |

A pole that returns `failed` under the strict-mode policy always
fails quorum; only `unavailable` is treated as a non-vote under the
default policy.

## Licensing

This sub-package ships under **Apache-2.0**, distinct from the rest
of `wat/` which is BUSL-1.1. Brand-proof verifiers are part of the
external-trust contract and must be redistributable by auditors
without licence friction.

## Linkage to Position-Paper §L4

This module is the executable form of the §L4-References annex.
Substance changes here update the annex; the Position-Paper text
states "four poles, 3-of-4 default quorum, operator-independent
HTTP poles, sandbox-safe injection seams" — those four claims live
as code-paths in this directory and as the `tests/wat/external_verifier/`
test suite.
