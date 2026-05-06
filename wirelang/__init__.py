# SPDX-License-Identifier: Apache-2.0
"""Wakir Wirelang package marker.

This file exists so that ``wirelang.identity`` (and future Python
sub-packages) can be imported by the test suite without requiring an
installed wheel. The package itself ships no top-level public API at
this stage; consumers should import from explicit sub-packages, e.g.::

    from wirelang.identity import generate_persona_did_document
"""
