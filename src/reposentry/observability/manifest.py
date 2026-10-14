from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class RunManifest:
    run_id: str
    versions: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def record_version(self, name: str, version: str) -> None:
        self.versions[name] = version

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "versions": dict(sorted(self.versions.items())),
            "extra": dict(self.extra),
        }

    @classmethod
    def default(
        cls,
        run_id: str,
        *,
        gateway_version: str = "c6-v0",
        verifier_version: str = "c8-v0",
        prompt_versions: Mapping[str, str] | None = None,
        model: str = "none",
        ruleset: str = "none",
        toolset: str = "none",
        seed: str = "0",
    ) -> RunManifest:
        m = cls(run_id=run_id)
        m.record_version("gateway", gateway_version)
        m.record_version("verifier", verifier_version)
        m.record_version("model", model)
        m.record_version("ruleset", ruleset)
        m.record_version("toolset", toolset)
        m.record_version("seed", seed)
        if prompt_versions:
            for k, v in prompt_versions.items():
                m.record_version(f"prompt.{k}", v)
        return m
