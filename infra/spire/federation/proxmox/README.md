<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Proxmox-Pilot-Bundle (Phase-2 Sprint-9 Tag-1)

Status: Operator-Hand-Companion zu `PROXMOX_BRING_UP_RECIPE.md`.

## Inhalt

| Datei | Rolle |
|---|---|
| `resolve-image-pins.sh` | Image-Digest-Placeholder-Resolution (Cross-Review Zone-C). |
| `proxmox-bundle-v1.0.tar.gz` | Zusammengestelltes Quadlet-Unit-Bundle fuer den VM-Bring-up. |
| `proxmox-bundle-v1.0.sha256` | Hash der Bundle-Datei. |
| `build-bundle.sh` | Reproduzierbares Bundle-Build-Skript (laeuft auf einem Repo-Klon). |

## Bundle-Inhalt

Das Tarball enthaelt das `wakir-runtime` Repo (oder einen Subset
dessen), genug fuer Schritte 2-6 in `PROXMOX_BRING_UP_RECIPE.md`:

- `wakir-runtime/quadlet/` — Phase-1b-Substrate-Quadlets (NATS,
  SPIRE-Server-Single-Side, SPIRE-Agent-Single-Side, NATS-KV-
  Bucket-Init).
- `wakir-runtime/infra/spire/federation/quadlet/` — Federation-
  Server-Substrate-Quadlets.
- `wakir-runtime/infra/spire/federation/config/` — SPIRE-Server-
  Federation HCL-Configs.
- `wakir-runtime/infra/spire/agent/quadlet/` — Federation-Agent-
  Quadlets.
- `wakir-runtime/infra/spire/agent/config/` — SPIRE-Agent
  HCL-Configs.
- `wakir-runtime/bin/` — Provisioner-Module + Smoke-Test-Skript.
- `wakir-runtime/wirelang/federation/marker_stack_kv.py` —
  Bucket-Config-Single-Source-of-Truth.
- `wakir-runtime/infra/spire/federation/PROXMOX_BRING_UP_RECIPE.md`
  — der Operator-Pfad.

## Reproduzierbarkeit

`build-bundle.sh` baut das Tarball deterministisch aus einem sauberen
Repo-Klon. Ausgabe-Hash ist stabil ueber wiederholte Builds (mtime
auf 1970-01-01 normalisiert, no-uid/gid-encoding).
