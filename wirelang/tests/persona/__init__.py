# SPDX-License-Identifier: Apache-2.0
"""Persona-CLI hermetic test sub-package.

Houses test packs for ``wirelang.persona.cli`` subcommands that
were introduced after and need a sub-package to avoid
collision with sibling tests at ``wirelang/tests/`` top level.

First inhabitant: ``test_persona_inspect_cli.py`` for the
``inspect-heartbeat`` subcommand (-Wirelang-Persona-Inspect-
CLI-MINI, the QA zone PR #116 §5 + ADR-0058).
"""
