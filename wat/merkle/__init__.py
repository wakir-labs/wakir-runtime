# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Re-classified BUSL-1.1 -> Apache-2.0 per ADR-0062 Cut-1
# substance-classification (see
# `docs/decisions/cut1-verifier-substance-classification.md`,
# Merkle-Read-Half row). Rationale: the Merkle read-half is offline
# verifiable via the Bitcoin-pattern duplicate-and-pair construction
# and is a brand-proof anchor surface that adopters must be able to
# reproduce without any Wakir-controlled hosted state. The full
# Apache-2.0 source snapshot is consolidated upstream in
# `wakir-labs/wakir-verify` under `wakir_verify/merkle_proof.py`.

"""Merkle tree construction for hourly WAT aggregation (read-half)."""
