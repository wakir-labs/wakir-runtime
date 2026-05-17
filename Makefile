# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Top-level convenience Makefile.
#
# This file is intentionally minimal. It exists to surface one-shot
# operator commands that have been blessed for cross-repo demos and
# external-audit walk-throughs. Day-to-day development still runs
# through ``pytest`` / ``cargo`` / ``./scripts/...`` directly; the
# Makefile is a thin shortcut layer, not a build system.

.PHONY: help demo-proof

help:
	@echo "Wakir runtime — Makefile convenience targets"
	@echo ""
	@echo "  demo-proof   Run the one-command cross-repo proof demo"
	@echo "               (protocol event -> runtime bridge -> WAT"
	@echo "               manifest -> Merkle proof -> wakir-verify"
	@echo "               cross-check). Emits a JSON report on stdout."
	@echo "               Override DEMO_PROOF_WORKDIR / DEMO_PROOF_HOUR"
	@echo "               for reproducible runs (defaults: per-PID"
	@echo "               tmpdir, hour pinned to 2026-05-17T12)."
	@echo ""

demo-proof:
	@bash scripts/demo-proof.sh
