"""RepoSentry layered configuration: defaults < file < environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class RepoSentryConfig(BaseModel):
    """Immutable, layered runtime configuration with strict secret isolation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    # General options
    environment: str = Field(default="production")
    log_level: str = Field(default="INFO")
    timeout_seconds: int = Field(default=30, ge=1, le=600)

    # Ingest limits
    max_file_size_bytes: int = Field(default=1_048_576, ge=1024)  # 1MB default
    max_total_size_bytes: int = Field(default=52_428_800, ge=1024)  # 50MB default
    max_file_count: int = Field(default=10_000, ge=1)
    max_compression_ratio: float = Field(default=100.0, ge=1.0)

    # Analysis options
    dominant_threshold: float = Field(default=0.75, ge=0.5, le=1.0)
    enable_llm_judge: bool = Field(default=False)

    # Secrets (strictly excluded from serialization and dumps; NEVER load from file)
    llm_api_key: SecretStr | None = Field(default=None, exclude=True)

    def __repr__(self) -> str:
        fields = []
        for k, v in self.__dict__.items():
            if isinstance(v, SecretStr):
                fields.append(f"{k}=**********")
            else:
                fields.append(f"{k}={v!r}")
        return f"RepoSentryConfig({', '.join(fields)})"

    def __str__(self) -> str:
        return self.__repr__()

    @classmethod
    def load(
        cls,
        config_path: str | Path | None = None,
        env_prefix: str = "REPOSENTRY_",
    ) -> RepoSentryConfig:
        """Layer configuration: defaults < file < environment.

        Secrets (e.g. LLM_API_KEY) are NEVER loaded from file and must come only from env.
        """
        data: dict[str, Any] = {}

        # 1. File layer
        if config_path:
            p = Path(config_path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                    if not isinstance(file_data, dict):
                        raise ValueError(f"Config file at {p} must contain a JSON object.")
                    # Explicit rule: secrets NEVER loaded from file
                    if "llm_api_key" in file_data:
                        raise ValueError(
                            "Security violation: 'llm_api_key' cannot be loaded from a file. "
                            "Secrets must come only from environment variables."
                        )
                    data.update(file_data)

        # 2. Environment layer
        env_mapping: dict[str, tuple[str, type]] = {
            f"{env_prefix}ENVIRONMENT": ("environment", str),
            f"{env_prefix}LOG_LEVEL": ("log_level", str),
            f"{env_prefix}TIMEOUT_SECONDS": ("timeout_seconds", int),
            f"{env_prefix}MAX_FILE_SIZE_BYTES": ("max_file_size_bytes", int),
            f"{env_prefix}MAX_TOTAL_SIZE_BYTES": ("max_total_size_bytes", int),
            f"{env_prefix}MAX_FILE_COUNT": ("max_file_count", int),
            f"{env_prefix}MAX_COMPRESSION_RATIO": ("max_compression_ratio", float),
            f"{env_prefix}DOMINANT_THRESHOLD": ("dominant_threshold", float),
            f"{env_prefix}ENABLE_LLM_JUDGE": ("enable_llm_judge", bool),
            f"{env_prefix}LLM_API_KEY": ("llm_api_key", SecretStr),
        }

        for env_key, (attr_name, attr_type) in env_mapping.items():
            if env_key in os.environ:
                raw_val = os.environ[env_key]
                if attr_type is SecretStr:
                    val: Any = SecretStr(raw_val.strip())
                elif attr_type is bool:
                    val = raw_val.strip().lower() in ("1", "true", "yes")
                elif attr_type is int:
                    val = int(raw_val.strip())
                elif attr_type is float:
                    val = float(raw_val.strip())
                else:
                    val = raw_val.strip()
                data[attr_name] = val

        return cls(**data)

    def require_secret(self, secret_name: str) -> str:
        """Require a secret value or raise a sanitized error that never echoes sensitive content."""
        val = getattr(self, secret_name, None)
        if val is None:
            raise RuntimeError(
                f"Required secret '{secret_name}' is not configured in environment."
            )
        if isinstance(val, SecretStr):
            secret_str = val.get_secret_value()
            if not secret_str.strip():
                raise RuntimeError(
                    f"Required secret '{secret_name}' is configured but empty."
                )
            return secret_str
        raw_str = str(val).strip()
        if not raw_str:
            raise RuntimeError(
                f"Required secret '{secret_name}' is configured but empty."
            )
        return raw_str
