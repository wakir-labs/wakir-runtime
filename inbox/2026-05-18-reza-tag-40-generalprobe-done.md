# Reza Tag-40 — Cross-Welle-Cutover-Generalprobe DONE

**From:** Reza Tehrani (Dev-Engineering-2)
**To:** Mira Kessler (CEO) / Tomás Reinhart (Matrix-Lead) / Priya Nakamura (CTO)
**Date:** 2026-05-18 19:37 CEST
**Status:** Substanz fertig, ready for Mira-Hand-Push.

---

## Auftrag

Cross-Welle-Cutover-Generalprobe (Tag-40) — Phase-3c marathon
dress-rehearsal sequencing all 7 Welle-N-Cutover-Smokes in
ADR-0066-Reihenfolge (KW-24..KW-27), exit-code-aggregation
+ cross-welle A1..A7 drift-aggregation, JSON-Marathon-Verdict.

## Liefer-Inventar

| Pfad | LoC | Inhalt |
|---|---|---|
| `scripts/phase-3c/cross-welle-cutover-generalprobe.py` | 930 | Orchestrator-Script (stdlib-only, hermetisch) |
| `tests/phase_3c/test_cross_welle_generalprobe.py` | 587 | 16 hermetic Tests (4 über Auftrag-Minimum 12) |
| `docs/phase-3c/cross-welle-generalprobe.md` | 282 | Operator-Runbook, ADR-0066-Plan-Tabelle, Marathon-Verdict-Semantik, CI-Integration-Note |

**Worktree:** `/var/home/fred/AI-Corp/.worktree-reza-tag40-generalprobe-runtime`
**Branch:** `reza/tag40-generalprobe`
**Baseline:** `cc186fa` (Tag-39 Welle-6+7 Cutover-Smokes)
**Net-new files:** 3 (kein bestehender Code modifiziert)

## Substanz-Funktionalität

### 1. ADR-0066-Plan (pinned als `PLAN` Tuple)

| KW | Welles | Mode |
|---|---|---|
| KW-24 | 1 + 2 | parallel |
| KW-25 | 3 | solo |
| KW-26 | 4 + 5 | parallel |
| KW-27 | 6 + 7 | parallel |

Plan-Integrität durch `test_plan_constants_match_adr_0066_kw24_kw27`
gepinnt — jede Abweichung bricht den Test.

### 2. Dispatch-Mechanik

- **Parallel-Sub-Sequenzen:** `ThreadPoolExecutor(max_workers=len(welles))`
  spawnt einen Subprocess pro Welle, joint, sortiert Ergebnisse nach Welle-ID.
- **Solo-Sub-Sequenzen:** inline sequential.
- **Short-circuit on ROLLBACK:** Wenn KW-24 ein ROLLBACK emittiert,
  werden KW-25..KW-27 nicht dispatcht (Evidenz wäre operator-
  irrelevant für das Cutover-Go-No-Go-Gate).
- **Hermeticity:** Orchestrator mutiert `os.environ` nie; jeder
  Subprocess bekommt eine frisch gebaute env-map mit
  `PYTHONPATH=<repo-root>:$PYTHONPATH` damit die Welle-Smokes
  `wirelang.persona_engine.rust_backend_switch` importieren können.

### 3. Marathon-Verdict (drei Achsen)

- **Marathon-Exit:** worst-band-wins (`max(welle.exit_code)` mit
  `EXIT_ROLLBACK > EXIT_CAUTION > EXIT_GREEN`).
- **Cross-Welle-Drift-Aggregator:** A1..A7 family-by-family
  Aggregation über alle dispatchten Welles. Pro Family:
  `passed_in / failed_in / skipped_in / family_verdict`
  (RED/AMBER/GREEN). Welle-spezifische A7-Keys
  (`A7_cross_modul_drift_welle_5_fsm` etc.) sind explizit gemappt
  damit Drift-Symmetrie zwischen Parallel-Pairs lesbar bleibt.
- **Overall-Drift-Verdict:** worst family-verdict (RED > AMBER > GREEN).
  Orthogonal zum Marathon-Exit — eine Welle kann CAUTION sein
  und gleichzeitig eine RED-Family triggern wenn eine andere
  Welle dort blocker-failt.

### 4. CLI-Surface

```
--dry-run             plan-only, no smokes invoked
--from-welle N        resume mid-marathon (1..7)
--up-to-welle N       partial run (1..7)
--out-dir PATH        per-welle envelope dir
--output PATH         marathon envelope file (default: stdout)
--smoke-arg=ARG       repeatable passthrough (e.g. --smoke-arg=--boots-per-phase=2)
--sequential          force sequential within parallel sub-sequences
--now TS              hermetic timestamp override
```

Exit-Code: `0/1/2 = GREEN / CAUTION / ROLLBACK_RECOMMENDED`.

## Tests (16, exceeds Minimum 12)

1.  `test_module_loads_and_exports_public_surface` — public-surface pin.
2.  `test_plan_constants_match_adr_0066_kw24_kw27` — ADR-0066 calendar pin.
3.  `test_filter_plan_full_default_returns_all_four_sub_sequences`
4.  `test_filter_plan_partial_up_to_welle_3_drops_kw26_kw27`
5.  `test_filter_plan_partial_from_welle_4_drops_kw24_kw25`
6.  `test_filter_plan_partial_single_welle_degrades_parallel_to_solo`
7.  `test_filter_plan_invalid_range_raises`
8.  `test_expected_assert_families_union_grows_with_welle_set`
9.  `test_aggregate_exit_worst_band_wins`
10. `test_aggregate_drift_green_path_all_pass`
11. `test_aggregate_drift_red_on_blocker_fail`
12. `test_aggregate_drift_amber_on_caution_only_fail`
13. `test_run_generalprobe_green_path_dispatches_all_welles`
14. `test_run_generalprobe_dry_run_skips_dispatch`
15. `test_run_generalprobe_short_circuits_on_rollback`
16. `test_main_cli_writes_envelope_and_returns_exit_code`

Alle 16 Tests grün:
```
============================== 16 passed in 0.16s ==============================
```

Tests injizieren einen mock `smoke_runner` — kein realer
Subprocess-Spawn, kein FS-Zugriff außerhalb `tmp_path`.
Stdlib-only.

## End-to-End-Sanity-Run

Realer Marathon-Run gegen alle 7 Welle-Smokes auf cc186fa-Baseline:

```
$ python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py \
    --out-dir /tmp/gp-test-full --output /tmp/gp-marathon-full.json
EXIT=1
marathon_band: CAUTION
drift_verdict: AMBER
```

Die CAUTION ist **Substanz, nicht Defekt**: Welles 3-7 haben A3
(latency tolerance) und A4 (decision-count drift) caution-asserts
in der hermetischen Sandbox. Das ist genau das Signal, das die
Per-Welle-Smokes designed sind zu emittieren, und der
Generalprobe propagiert es korrekt nach oben. Drift-Verdict ist
AMBER (nicht RED), weil keine blocker-severity-Family failt.

Partial-Run KW-24 (welles 1+2) mit `--boots-per-phase=2`:
```
EXIT=0
marathon_band: GREEN
drift_verdict: GREEN
```

## Regression-Check

`PYTHONPATH=. pytest tests/phase_3c/` → **143 passed in 0.53s**
(127 existing + 16 new). Keine Phase-3c-Regression.

Bei `tests/workflows/` gibt es 2 pre-existing failures auf der
cc186fa-Baseline
(`test_cross_modul_stress_step_only_on_welle_4_and_5`,
`test_decision_envelope_schema_per_welle`) — von Reza unter
`git stash` verifiziert, sind nicht durch diesen PR verursacht.
Wenn das Mira's Sicht stört, kann ich eine separate Notiz an
Priya senden.

## Disziplin-Selbstcheck

- [x] Worktree `cc186fa` (Auftrag-pin) — fetched, branch sauber.
- [x] Stdlib-only Orchestrator + Tests.
- [x] Hermetisch: keine NATS / Rust-Binary / Anthropic-SDK
  Aufrufe; smoke_runner-Seam für Tests.
- [x] Tri-State-Exit-Contract 0/1/2 mit existing Per-Welle-Smokes
  konsistent.
- [x] ADR-0065/0066-Pfade in Docs verifiziert (filename-slug
  `0066-phase-3c-beschleunigung-option-a-plus.md`, nicht der
  prosafreundliche slug aus dem Auftrag).
- [x] Zeitstempel-Verifikation (P5): alle Datum-Einträge via
  `date`.
- [x] SPDX-Header auf Script + Test (parity mit existing
  Phase-3c-Schwestern).
- [x] Cross-Review-Zonen unverändert (Generalprobe konsumiert
  Welle-Smokes, mutiert sie nicht — kein WAT × Wirelang
  Frame-Format-Eingriff).

## Bekannte offene Punkte

1. **CI-Workflow für die Generalprobe** ist im Doc beschrieben
   (`phase-3c-cross-welle-generalprobe` als Required-Status-Check)
   aber **nicht** als `.github/workflows/*.yml` File ausgeliefert.
   Begründung: der Auftrag spricht von "6+ Required-Status-Checks
   grün" (also: existing checks bleiben grün), nicht von "neuen
   Check anlegen". Ein separater Tag-40-Follow-up oder
   Tomás-Hand-PR kann den Workflow nachziehen sobald
   Branch-Protection-Konsens mit Aisha-Protokoll vorliegt.

2. **A7-Family-Key-Mapping** habe ich live aus den envelope-JSONs
   ausgelesen, nicht aus den Per-Welle-Smoke-Quellen geparst. Das
   ist robust gegen Welle-Smoke-Code-Refactor solange die
   envelope-keys stabil bleiben. Wenn jemand einen Welle-Smoke
   refactor't und A7-Key umbenennt, schlägt der
   `_family_a7_for_welle`-Test gegen die fallback "missing"-Logik
   an — das ist die intended drift-detection.

## Next-Step-Empfehlung an Mira

- Push als Tag-40-PR `reza/tag40-generalprobe` (Continuous-Mode-
  authorisiert per AR-Direktive); PR-Body kann diesen Bericht
  als Substanz-Anhang verwenden.
- Nach Merge: optional Tomás-Hand-PR für den `phase-3c-cross-
  welle-generalprobe.yml` Workflow + Branch-Protection-Update
  (separat, nicht in diesem Tag-40-PR).
- KW-24-Go-No-Go-Generalprobe-Run kann nun reproduzierbar von
  jedem Operator triggert werden.

— Reza
