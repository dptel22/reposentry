"""Unit and security tests for RepoSentry layered configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reposentry.config.settings import RepoSentryConfig


def test_config_defaults() -> None:
    cfg = RepoSentryConfig()
    assert cfg.environment == "production"
    assert cfg.log_level == "INFO"
    assert cfg.timeout_seconds == 30
    assert cfg.enable_llm_judge is False
    assert cfg.llm_api_key is None


def test_config_load_from_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({
            "environment": "staging",
            "timeout_seconds": 60,
            "dominant_threshold": 0.80,
        }),
        encoding="utf-8",
    )
    cfg = RepoSentryConfig.load(config_path=config_file)
    assert cfg.environment == "staging"
    assert cfg.timeout_seconds == 60
    assert cfg.dominant_threshold == 0.80
    assert cfg.log_level == "INFO"  # default preserved


def test_config_precedence_env_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({
            "environment": "staging",
            "timeout_seconds": 60,
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("REPOSENTRY_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("REPOSENTRY_ENVIRONMENT", "test")

    cfg = RepoSentryConfig.load(config_path=config_file)
    assert cfg.environment == "test"
    assert cfg.timeout_seconds == 120


def test_secret_in_config_file_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "insecure_config.json"
    config_file.write_text(
        json.dumps({
            "llm_api_key": "sk-secret-token",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Security violation: 'llm_api_key' cannot be loaded from a file"):
        RepoSentryConfig.load(config_path=config_file)


def test_missing_secret_error_does_not_echo_value() -> None:
    cfg = RepoSentryConfig()
    with pytest.raises(RuntimeError) as exc_info:
        cfg.require_secret("llm_api_key")
    msg = str(exc_info.value)
    assert "Required secret 'llm_api_key' is not configured" in msg
    assert "None" not in msg
