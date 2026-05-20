# AR-Authorisation Request — OTS Live-Emit Activation

**Status:** REQUEST (Mira-Hand) — pending AR-Sign-off + Filename-Rename
**Date filed:** 2026-05-20 ~03:30 CEST
**Filed by:** Mira Kessler (CEO)
**Decision target:** Aufsichtsrat (Fred)

## Purpose

Authorise the live-OTS-anchor activation for the Phase-3c-Welle-1..7
cutover marathon. Toggle `WAKIR_OTS_LIVE_EMIT=1` on the network-attached
Operator-Host to enable actual OpenTimestamps Calendar emission for
Welle-N audit-anchor markers.

## Scope

- **Operator-Host only.** `WAKIR_OTS_LIVE_EMIT=1` is exported in the
  Operator's shell session that runs the live-stamp commands.
- **Sandbox stays audit-only.** Helpers under `tooling/ots/` refuse the
  flag by construction (Sandbox-Boundary recital, ADR-0023a §6.1).
- **Per-Welle Trigger.** Each of the 7 Welle-Cutover-Days emits the
  Welle-N audit-anchor marker plus its `.ots` calendar proof during
  the cutover sequence (recipe §5).
- **Post-Welle-7.** Phase-3-COMPLETE-Marker bundle stamp (recipe §6
  marker-chain-verification) closes the marathon.

## Pre-Conditions (verified Mira-Hand 2026-05-20 ~03:25 CEST)

- ✅ §2.1 Pre-Activation-Probe green: 3 manifests (0.5.0-pre-cutover,
  0.5.1-pre-cutover, 0.5.2-final-pre-cutover) all `PROBE-READY` per
  emit_manifest_hash_ots_marker.py output.
- ✅ ADR-0071 Pre-Auditor-Designation Mira-Proxy AR-approved 2026-05-20.
- ✅ ADR-0070 V2-Daily-Update-Workflow AR-approved 2026-05-20.
- ✅ Branch-Protection 14 Required-Status-Checks aktiviert (Tag-80 Item 4
  Mira-Hand-B 2026-05-20 ~03:15 CEST).
- ⏳ §2.2 Phase-3-COMPLETE-Marker existence — DEFERRED. Welle-1..7
  markers werden erst AT Cutover-Day emittiert; Phase-3-COMPLETE-Marker
  post-Welle-7. Recipe ist designed für Eve-of-Cutover; current state
  ist Pre-Eve-Prepared.
- ⏳ Item 1 G1+G2 Cosign-Quadlet-Wiring — AR-Operator-Hand pending.

## Rollback Path

See `docs/operations/ots-live-stamping-operator-setup.md` §7. Toggle
back: `unset WAKIR_OTS_LIVE_EMIT` on Operator-Host. Existing `.ots`
calendar receipts remain (cannot be unstamped); next emit reverts to
audit-only-stub.

## Audit-Trail Disposition

- Henrik Voss (Internal Audit, Zone-N) audit-sample-priority post-
  Welle-7 includes live-stamp markers + `.ots` proof files (per ADR-0071
  Pre-Auditor-Mira-Proxy + ADR-0070 V2-Workflow Henrik §11.5 Roh-
  Material-Listing).
- Marker-SHA-256 + `.ots` file references logged in activity-log per
  recipe §5.3.

## Sandbox-Boundary Recital

This authorisation does NOT permit Sandbox-internal helpers to emit
live-OTS calls. Sandbox helpers refuse `WAKIR_OTS_LIVE_EMIT=1` by
construction. The flag is **host-side only** — exported in the
Operator's shell session, never inside Mira-Sandbox or Engineering-
Spawn-Subagent contexts.

## AR-Sign-off (AR-Hand block — leave empty until AR signs)

```
Signed: ____________________
Date:   ____________________
Cutover-target-date: ____________________  (per ADR-0066-symbolisch
                                            oder neue AR-Trigger-Date)
```

## Mira-Hand Notes

- Recipe-Original ADR-0066-Datum 2026-06-08 wurde in AR-Sichtung
  Tag-79 (2026-05-20 ~02:30 CEST) als symbolisch deklariert. Actual
  Cutover-T0 ist AR-Hand-getriggert nach Operator-Setup-Done.
- Diese Request kann als Vorab-Authorisierung dienen — AR signs jetzt,
  Operator-Toggle erfolgt zum Cutover-Eve (wann auch immer AR den
  Cutover-Trigger setzt).
- Filename-Convention post-Sign-off: `<YYYY-MM-DD>-ots-live-emit-
  activation-authorisation.md` mit dem AR-Sign-off-Datum.

— Mira Kessler, CEO
