"""Cumulative model-facing ablation adapters with explicit component seams."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class ArmConfig:
    name: str
    use_judge: bool = False
    use_retrieval: bool = False
    use_verifier: bool = False
    use_agent: bool = False
    allow_hypotheses: bool = False

    def __post_init__(self) -> None:
        if self.use_retrieval and not self.use_judge:
            raise ValueError("retrieval arm must feed the judge")
        if self.use_verifier and not self.use_judge:
            raise ValueError("verifier arm requires model-authored citations")
        if self.use_agent and not self.use_judge:
            raise ValueError("agent arm must return through the judge verdict contract")
        if self.allow_hypotheses != self.use_agent:
            raise ValueError("only the bounded agent arm may propose candidates")


_ARMS = {
    "A": ArmConfig("A"),
    "B": ArmConfig("B", use_judge=True),
    "C": ArmConfig("C", use_judge=True, use_retrieval=True),
    "D": ArmConfig("D", use_judge=True, use_retrieval=True, use_verifier=True),
    "E": ArmConfig("E", use_judge=True, use_retrieval=True, use_verifier=True,
                    use_agent=True, allow_hypotheses=True),
}


def get_arm(name: str) -> ArmConfig:
    try:
        return _ARMS[name.upper()]
    except (AttributeError, KeyError) as exc:
        raise ValueError(f"unknown ablation arm: {name!r}") from exc


@dataclass(frozen=True)
class ArmCallbacks:
    judge: Callable[[Mapping[str, Any], Sequence[Any]], Any] | None = None
    retrieve: Callable[[Mapping[str, Any]], Sequence[Any]] | None = None
    verify: Callable[[Any], Any] | None = None
    agent: Callable[[Mapping[str, Any], Sequence[Any]], Any] | None = None


@dataclass(frozen=True)
class ArmExecution:
    candidate_id: str
    retrieval: tuple[Any, ...] = ()
    judgment: Any = None
    verification: Any = None


@dataclass(frozen=True)
class ArmRun:
    config: ArmConfig
    executions: tuple[ArmExecution, ...]
    proposed_hypotheses: tuple[Any, ...] = ()


class ArmAdapter:
    """Run one fixed component configuration over deterministic candidate order."""

    def __init__(self, config: ArmConfig) -> None:
        self.config = config

    def run(self, candidates: Sequence[Mapping[str, Any]], callbacks: ArmCallbacks) -> ArmRun:
        if self.config.use_judge and not self.config.use_agent and callbacks.judge is None:
            raise ValueError(f"arm {self.config.name} requires a judge callback")
        if self.config.use_retrieval and callbacks.retrieve is None:
            raise ValueError(f"arm {self.config.name} requires a retrieval callback")
        if self.config.use_verifier and callbacks.verify is None:
            raise ValueError(f"arm {self.config.name} requires a verifier callback")
        if self.config.use_agent and callbacks.agent is None:
            raise ValueError(f"arm {self.config.name} requires an agent callback")

        candidate_ids = [_candidate_id(candidate) for candidate in candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate IDs must be unique within an arm run")
        ordered = sorted(candidates, key=_candidate_id)
        executions = []
        hypotheses = []
        for candidate in ordered:
            candidate_id = _candidate_id(candidate)
            retrieved = tuple(callbacks.retrieve(candidate)) if self.config.use_retrieval else ()
            judgment = None
            verification = None
            if self.config.use_agent:
                judgment = callbacks.agent(candidate, retrieved)  # type: ignore[misc]
                if self.config.allow_hypotheses:
                    hypotheses.extend(_hypotheses(judgment))
            elif self.config.use_judge:
                judgment = callbacks.judge(candidate, retrieved)  # type: ignore[misc]
            if self.config.use_verifier:
                verification = callbacks.verify(judgment)  # type: ignore[misc]
            executions.append(ArmExecution(candidate_id, retrieved, judgment, verification))
        return ArmRun(self.config, tuple(executions), tuple(hypotheses))


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    explicit = candidate.get("id")
    if explicit is not None:
        return str(explicit)
    try:
        canonical = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate without an ID must be JSON serializable") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _hypotheses(judgment: Any) -> tuple[Any, ...]:
    if isinstance(judgment, Mapping):
        hypotheses = judgment.get("hypotheses", ())
    else:
        hypotheses = getattr(judgment, "hypotheses", ())
    return tuple(item for item in hypotheses if getattr(item, "label", item.get("label") if isinstance(item, Mapping) else None) == "hypothesis")

