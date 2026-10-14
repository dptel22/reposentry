"""Framework-neutral liveness and readiness report helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class HealthReport:
    live: bool
    ready: bool
    checks: Mapping[str, bool]

    def as_dict(self) -> dict[str, object]:
        return {"live": self.live, "ready": self.ready, "checks": dict(sorted(self.checks.items()))}


def health_check() -> HealthReport:
    """Return process liveness; a running caller is live by definition."""
    return HealthReport(live=True, ready=True, checks={})


def readiness_check(checks: Mapping[str, bool]) -> HealthReport:
    """Report readiness from explicit dependency checks in stable key order."""
    normalized = {str(name): bool(ok) for name, ok in sorted(checks.items())}
    return HealthReport(live=True, ready=all(normalized.values()), checks=normalized)
