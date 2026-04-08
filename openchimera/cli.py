"""Shim exposing the OpenChimera CLI entry-point under the ``openchimera`` namespace.

Usage::

    from openchimera import cli
    sys.exit(cli.main())
"""
from __future__ import annotations

from run import main  # noqa: F401

__all__ = ["main"]
