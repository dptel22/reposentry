"""Unit tests for C0 contracts: round-trip serialization, strict schema, canonical json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from reposentry.contracts.models import (
    SCHEMA_VERSION,
    Coverage,
    Evidence,
    Finding,
    FindingCategory,
    FrameworkType,
    GuardMechanismType,
    GuardSignature,
    IngestedFileRecord,
    LineRange,
    Route,
    RunManifest,
    Score,
    SeverityLevel,
    Symbol,
    SymbolKind,
    TraceEvent,
    Verdict,
    VerdictStatus,
    canonical_json,
    compute_content_hash,
)

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "contracts_v0"


def test_line_range_round_trip() -> None:
    lr = LineRange(start_line=10, end_line=25, start_col=4, end_col=12)
    dumped = lr.model_dump(mode="json")
    reloaded = LineRange.model_validate(dumped)
    assert lr == reloaded
    assert reloaded.start_line == 10
    assert reloaded.end_line == 25


def test_schema_version_mismatch_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        LineRange(schema_version="9.9.9", start_line=1, end_line=5)
    assert "Schema version mismatch" in str(exc_info.value)


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        LineRange.model_validate({"start_line": 1, "end_line": 5, "unknown_field": "disallowed"})
    assert "extra_forbidden" in str(exc_info.value) or "Extra inputs are not permitted" in str(exc_info.value)


def test_canonical_json_stability() -> None:
    dict_a = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
    dict_b = {"a": 2, "m": {"a": 4, "b": 3}, "z": 1}
    assert canonical_json(dict_a) == canonical_json(dict_b)
    assert compute_content_hash(dict_a) == compute_content_hash(dict_b)


def test_validate_all_fixture_files() -> None:
    assert FIXTURES_DIR.exists(), f"Fixtures dir {FIXTURES_DIR} does not exist"

    # Route fixture
    with open(FIXTURES_DIR / "route.json", "r", encoding="utf-8") as f:
        route_data = json.load(f)
    route = Route.model_validate(route_data)
    assert route.handler_name == "get_user_profile"
    assert route.framework == FrameworkType.FASTAPI
    assert "GET" in route.http_methods

    # Symbol fixture
    with open(FIXTURES_DIR / "symbol.json", "r", encoding="utf-8") as f:
        symbol = Symbol.model_validate(json.load(f))
    assert symbol.kind == SymbolKind.FUNCTION
    assert symbol.name == "get_user_profile"

    # GuardSignature fixture
    with open(FIXTURES_DIR / "guard_signature.json", "r", encoding="utf-8") as f:
        guard = GuardSignature.model_validate(json.load(f))
    assert guard.mechanism_type == GuardMechanismType.AUTH_CHECK
    assert guard.confidence == 0.95

    # Evidence fixture
    with open(FIXTURES_DIR / "evidence.json", "r", encoding="utf-8") as f:
        evidence = Evidence.model_validate(json.load(f))
    assert evidence.evidence_id == "ev-883a9f1b"

    # Finding fixture
    with open(FIXTURES_DIR / "finding.json", "r", encoding="utf-8") as f:
        finding = Finding.model_validate(json.load(f))
    assert finding.category == FindingCategory.A
    assert len(finding.evidence) == 1

    # Verdict fixture
    with open(FIXTURES_DIR / "verdict.json", "r", encoding="utf-8") as f:
        verdict = Verdict.model_validate(json.load(f))
    assert verdict.status == VerdictStatus.CONFIRMED

    # Score fixture
    with open(FIXTURES_DIR / "score.json", "r", encoding="utf-8") as f:
        score = Score.model_validate(json.load(f))
    assert score.overall_score == 76.5

    # Coverage fixture
    with open(FIXTURES_DIR / "coverage.json", "r", encoding="utf-8") as f:
        cov = Coverage.model_validate(json.load(f))
    assert cov.scanned_files == 42
    assert cov.total_files == 45

    # RunManifest fixture
    with open(FIXTURES_DIR / "run_manifest.json", "r", encoding="utf-8") as f:
        manifest = RunManifest.model_validate(json.load(f))
    assert manifest.total_files == 2
    assert len(manifest.files) == 2

    # TraceEvent fixture
    with open(FIXTURES_DIR / "trace_event.json", "r", encoding="utf-8") as f:
        trace = TraceEvent.model_validate(json.load(f))
    assert trace.stage == "C2_PARSE"
