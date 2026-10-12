"""Tests for CLI safety: path validation, ANSI escape stripping, error handling."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from reposentry.cli.main import cli, sanitize_cli_output


def test_sanitize_cli_output_strips_ansi() -> None:
    ansi_string = "\x1B[31mRed Text\x1B[0m and \x1B[1mBold\x1B[0m"
    clean = sanitize_cli_output(ansi_string)
    assert clean == "Red Text and Bold"
    assert "\x1B" not in clean


def test_cli_rejects_nonexistent_path() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "nonexistent_dir_xyz123"])
    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_cli_rejects_reserved_device_target() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "CON"])
    assert result.exit_code != 0
    assert "Reserved Windows device name" in result.output


def test_cli_version_succeeds() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "reposentry 0.1.0" in result.output
