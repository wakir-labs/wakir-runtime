<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors
REUSE-IgnoreStart
-->

# Pre-Commit REUSE-Lint Hook — Operator Runbook

**ADR-Anker:** ADR-0061 (License-Hygiene Gate) Tag-32 EXT-AUDIT-FOLGE.
**Audit-Anlass:** Kai-PR #211 (LICENSING-Audit) fixed 11 Invalid-SPDX-
Headers in Tests, brauchte drei Rebase-Iterationen wegen paralleler
Merges. Pre-Commit-Hook spiegelt die `license-gate.yml`-Invarianten
client-seitig vor `git commit`.

## Zweck

Der Pre-Commit-Hook fängt License-Hygiene-Drift bereits am
Entwickler-Rechner ab — bevor der Server-side `license-gate.yml`
einen PR-Run rot machen muss. Drei Verteidigungs-Schichten:

1. **`reuse lint`** (Upstream `fsfe/reuse-tool`) — vollständiger
   REUSE-3.0-Compliance-Check.
2. **`spdx-header-check`** — fehlende SPDX-Header in
   **neu hinzugefügten** Substance-Dateien (`.py`, `.rs`, `.sh`,
   `.toml`, `.yml`, `.yaml`, `.md`).
3. **`reuse-toml-annotation-drift`** — `REUSE.toml`-interne
   Konsistenz (gültiges TOML, alle `[[annotations]]`-Pfade
   matchen mindestens eine Datei auf Platte).

## Installation (einmalig pro Clone)

```bash
# 1) pre-commit selbst installieren (PyPI).
pip install pre-commit

# 2) Hook in die `.git/hooks/`-Pipeline einhängen.
pre-commit install

# 3) Sanity-Check: alle Hooks gegen Tree-Snapshot.
pre-commit run --all-files
```

Die `pre-commit`-Binary verdrahtet `.git/hooks/pre-commit` so, dass
jeder zukünftige `git commit` automatisch die in
`.pre-commit-config.yaml` deklarierten Hooks ausführt.

## Erwartetes Hook-Verhalten

### Layer 1 — `reuse lint`

Läuft mit `pass_filenames: false` über den gesamten Tree (so wie
der Server-side Gate). Bricht den Commit ab bei:

- Datei ohne `SPDX-License-Identifier:`.
- Datei ohne `SPDX-FileCopyrightText:` (oder REUSE-toml-Annotation,
  die das abdeckt).
- Lizenz in einem Header genannt, aber kein Volltext unter
  `LICENSES/`.

**Bemerkung:** Während der Welle (vor Reza-Merge der `LICENSES/`-
Volltexte) kann dieser Hook RED sein. Das ist erwartet und
spiegelt das Server-side-Verhalten 1:1.

### Layer 2 — `spdx-header-check`

Läuft **nur über neu hinzugefügte** Substance-Dateien (Status `A`
im Index). Modifizierte Dateien werden bewusst ignoriert — Legacy-
Churn soll keine Entwickler-Flow-Friction erzeugen. Den vollen
Tree-Invariante deckt der Server-side Gate ab.

Bricht den Commit ab, wenn eine neu hinzugefügte
`.py`/`.rs`/`.sh`/`.toml`/`.yml`/`.yaml`/`.md`-Datei keinen
`SPDX-License-Identifier:`-Marker in den ersten 4 KiB hat.

**Ausgenommen** (Skip-Prefixes):

- `LICENSES/` — Upstream-Volltext-Lizenz-Dateien.
- `meta/timestamps/` — OTS-Attestation-Blobs.
- `.github/ISSUE_TEMPLATE/` — GitHub-spezifische Template-
  Frontmatter ohne SPDX-Konvention.
- `vendor/` — vendored-Dependencies.

### Layer 3 — `reuse-toml-annotation-drift`

Läuft nur, wenn `REUSE.toml` selbst gestaged ist. Bricht den
Commit ab bei:

- Ungültigem TOML.
- `[[annotations]]`-Block mit `path = "..."`, der **kein einzige
  Datei** auf Platte matcht. Typischer Auslöser: ein Rename oder
  Delete, der vergessen hat die REUSE-Annotation nachzuziehen.

## Bypass — `--no-verify`

```bash
git commit --no-verify  # NICHT EMPFOHLEN
```

`--no-verify` umgeht alle Pre-Commit-Hooks. Das ist **explizit nicht
empfohlen** für License-Hygiene-Items:

- Der Server-side `license-gate.yml` läuft trotzdem im PR und
  blockt den Merge.
- Mit Branch-Protection (ADR-0061 Schritt 8 Required-Status-Check)
  ist `--no-verify` an `main` praktisch wirkungslos.

**Legitime `--no-verify`-Fälle:** ausschließlich der Initial-Commit
beim Repo-Bootstrap oder eine Rescue-Recovery nach einem
mid-rebase-Crash. Beides ist nicht der Entwickler-Default-Pfad.

## Drift-Prevention-Pattern — Lessons Learned aus PR #211

Kai-PR #211 musste dreimal rebased werden, weil **andere** PRs
während des Audits frische SPDX-Drift in den Tree gespült haben
(neue Test-Dateien ohne Header). Der Pre-Commit-Hook unterbindet
genau dieses Muster:

| Bug-Klasse | PR #211 Manuelle Audit | Pre-Commit-Hook |
|---|---|---|
| Neue `.py`-Datei ohne SPDX | Per-Commit-Audit nötig | Hook blockt sofort |
| `REUSE.toml`-Rename-Drift | Audit-Tool meldet zu spät | Hook blockt sofort |
| Stale `[[annotations]]` | Manueller Cross-Check nötig | Hook blockt sofort |

## Troubleshooting

### `pre-commit: command not found`

`pre-commit` ist nicht im aktiven Python-Environment installiert.
Lösung:

```bash
pip install pre-commit
which pre-commit  # sollte einen Pfad im Venv ausgeben.
```

### `reuse lint` schlägt fehl mit "Missing licenses: N"

Beabsichtigtes Welle-Verhalten bis `LICENSES/Apache-2.0.txt` +
`BUSL-1.1.txt` + `CC-BY-4.0.txt` gemerged sind. Workaround
während der Welle:

```bash
# Lokales Skip nur des Layer-1-Hooks (für Welle-interne Commits).
SKIP=reuse pre-commit run
```

`SKIP=` ist die offiziell unterstützte Form, einen einzelnen
Hook für einen einzelnen Commit zu überspringen, ohne den globalen
`--no-verify`-Hammer zu nehmen.

### `spdx-header-check` meldet Datei, die meiner Meinung nach modifiziert (nicht added) ist

Das Hook ruft `git diff --cached --name-status --diff-filter=A`
intern. Wenn deine Datei doch als `A` durchläuft, ist sie für
den Index ein neuer Pfad (z. B. nach einem Rename ohne
`-M`-Heuristik). Lösung: Header einfügen, dann commiten.

## Persona-Workspace-Hinweis

Pre-Commit-Hooks laufen im Persona-Workspace genauso wie im
Operator-Workspace. Bei Cross-Repo-Worktrees (z. B.
`/var/home/fred/AI-Corp/.worktree-*`) ist `pre-commit install`
per Worktree zu wiederholen, weil `.git/hooks/` worktree-spezifisch
gemanagt wird (siehe `.git`-File im Worktree → tatsächlicher
hook-Pfad in `<repo>/.git/worktrees/<name>/hooks/`).

## Eskalationspfad

| Anlass | Ansprechpartner |
|---|---|
| Hook bricht False-Positive | Tomás (Matrix-Lead-Funktion) |
| `REUSE.toml`-Annotation-Drift | Kai (Substrate-Owner) |
| BSL-Subtree-Header-Drift | Reza (Federation-BSL-Owner) |
| `license-gate.yml`-Server-side-Bruch | Mira (CEO) per CTO-Pfad |

## Acceptance-Kriterien

- [x] `.pre-commit-config.yaml` existiert im Repo-Root.
- [x] `scripts/pre-commit-spdx-header-check.py` ist ausführbar.
- [x] `scripts/pre-commit-reuse-toml-drift-check.py` ist ausführbar.
- [x] `docs/operations/pre-commit-reuse-lint-runbook.md` (dieses
      Dokument) existiert.
- [x] `tests/infra/test_pre_commit_reuse_lint.py` deckt die fünf
      Acceptance-Vektoren ab (hook-config-shape,
      hook-trigger-conditions, SPDX-Drift-Detection,
      REUSE.toml-Annotation-Check, runbook-presence).

— Tomás

<!-- REUSE-IgnoreEnd -->

