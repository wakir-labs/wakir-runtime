# TV-W-3 Federation-Resolver-Roundtrip Fixtures

Phase-1b Tag-17 (2026-05-07).

This directory holds the hermetic golden fixture and the replay
bundle for the TV-W-3 vector specified in
[`wirelang/specs/wirelang-tv-strategy.md`](../../../specs/wirelang-tv-strategy.md)
Annex A.3.

## Files

| File | Role |
|---|---|
| `pin-pack.json` | Golden hermetic-trace pin-pack (top-level `pin_pack_sha256` is the audit anchor). |
| `replay/captured-at.txt` | ISO-8601 UTC timestamp of replay bundle generation (freshness anchor per spec §3.4 A5). |
| `replay/dns/_wakir-ftd.wakir.dev.txt` | Replayed DNS TXT-record payload (`v=1; sha256=<64-hex>`). |
| `replay/https/ftd-wakir.dev.json` | Replayed signed FTD-doc body bytes (JCS-canonical). |
| `replay/https/aip-tv-w-3-issuer-1-0.json` | Replayed signed AIP-doc body bytes (JCS-canonical). |

## Regenerate

```
python -m wirelang.tests._tv_w_3_pin_pack_builder \
    [--out wirelang/tests/fixtures/tv-w-3/pin-pack.json] \
    [--write-replay] \
    [--seed-hex 000102030405060708090a0b0c0d0e0f]
```

`--check` prints the pin-pack hash without writing any file. The
generator is deterministic given the BIP-32 test-vector-1 seed; an
external auditor can reproduce
`a4bc3df2c5716f79efabe407d3824dcc5e3ae645654c190ab6fc2b6ee4349213`
from a clean checkout.

## Cross-vector anchor

The biscuit-root pubkey
`c8efd3cbfb88ae70d094f1b68da5587a65b5bc05d1aedaa7f03832fbf64ab63c`
is the TV-W-1 persona-(1, 0) Ed25519 sub-key. Both
[`tv-w-1/pin-pack.json`](../tv-w-1/pin-pack.json) and the TV-W-3
trace pin this byte-string; a drift in either pin surfaces during
`pytest wirelang/tests/test_tv_w_1_identity_roundtrip.py` (forward
anchor) or `pytest wirelang/tests/test_tv_w_3_federation_roundtrip.py`
(reverse anchor).

## Live-mode

Set `WIRELANG_LIVE_FEDERATION=1` to enable the
`TestLiveFederation` class. The live test resolves
`_wakir-ftd.wakir.dev` via DoH and asserts the published TXT record
hashes back to the hermetic `dns_anchor_hash`. Mirrors
`OTS_INTEGRATION_TEST=1` on the WAT side.
