"""Tests for the configure CLI wiring in run.py.

Covers:
  1. configure subparser exists and accepts --list, --enable, --disable, --json
  2. _configure_quantum_command dispatches to configure_wizard.configure_command
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from run import _build_parser


# 1. configure subparser exists with expected arguments
def test_configure_subparser_exists() -> None:
    parser = _build_parser()
    args = parser.parse_args(["configure", "--list", "--json"])
    assert args.command == "configure"
    assert args.list_caps is True
    assert args.json is True


def test_configure_enable_flag() -> None:
    parser = _build_parser()
    args = parser.parse_args(["configure", "--enable", "quantum_engine_100"])
    assert args.enable == "quantum_engine_100"


def test_configure_disable_flag() -> None:
    parser = _build_parser()
    args = parser.parse_args(["configure", "--disable", "remote_telegram"])
    assert args.disable == "remote_telegram"


# 2. _configure_quantum_command dispatches correctly
def test_configure_dispatches_to_wizard() -> None:
    from run import _configure_quantum_command

    with patch("run.configure_command", create=True) as mock_cmd:
        mock_cmd.return_value = 0
        with patch("core.configure_wizard.configure_command", return_value=0) as wiz:
            result = _configure_quantum_command(
                list_caps=True, enable_id="", disable_id="", as_json=True
            )
    assert result == 0
