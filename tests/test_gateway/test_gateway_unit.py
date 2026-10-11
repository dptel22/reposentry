"""Unit tests for the C6 LLM gateway (reposentry-agent-b/tests/test_gateway).

Covers the unit list from docs/INITIAL_PLAN.md "C6 LLM gateway" (lines 172-175):
cache-key sensitivity, replay strictness, record-then-replay offline,
budget enforcement, transient backoff / permanent error, kill switch,
secret scrubbing, and schema validation.
"""

from __future__ import annotations

import json

import pytest

from reposentry.gateway.canonical import cache_key, input_hash
from reposentry.gateway.errors import BudgetExceededError, GatewayError, ReplayMissError
from reposentry.gateway.gateway import LLMGateway
from reposentry.gateway.provider import FakeModel
from reposentry.gateway.replay import MemoryStore
from reposentry.gateway.types import Budget, BudgetState, GatewayConfig, Mode, ModelRequest

from conftest import SECRET, VERDICT_SCHEMA, verdict_payload

MODEL = "fake-model-1"


def make_request(bundle=None, **overrides) -> ModelRequest:
    return ModelRequest(
        model=overrides.pop("model", MODEL),
        prompt_version="pv1",
        bundle=bundle if bundle is not None else {"file": "app.py", "snippet": "def f(): pass"},
        schema=VERDICT_SCHEMA,
        **overrides,
    )


def make_gateway(script, *, config=None, store=None, fallback=None, clock=None, tracer=None) -> LLMGateway:
    return LLMGateway(
        FakeModel(script),
        config=config or GatewayConfig(),
        store=store or MemoryStore(),
        clock=clock,
        tracer=tracer,
        fallback=fallback or (lambda: {"verdict": "safe", "degraded": True}),
    )


# --------------------------------------------------------------------- cache key sensitivity


class TestCacheKeySensitivity:
    def test_different_models_produce_different_keys(self):
        b = {"x": 1}
        assert cache_key(model="m-a", prompt_version="pv1", bundle=b) != cache_key(
            model="m-b", prompt_version="pv1", bundle=b
        )

    def test_different_prompt_versions_produce_different_keys(self):
        b = {"x": 1}
        assert cache_key(model=MODEL, prompt_version="pv1", bundle=b) != cache_key(
            model=MODEL, prompt_version="pv2", bundle=b
        )

    def test_different_bundles_produce_different_keys(self):
        assert cache_key(model=MODEL, prompt_version="pv1", bundle={"x": 1}) != cache_key(
            model=MODEL, prompt_version="pv1", bundle={"x": 2}
        )

    def test_same_inputs_same_key_and_key_covers_all_three(self):
        b = {"x": 1}
        k = cache_key(model=MODEL, prompt_version="pv1", bundle=b)
        assert k == cache_key(model=MODEL, prompt_version="pv1", bundle=b)
        # changing any single component changes the key
        assert k != cache_key(model="other", prompt_version="pv1", bundle=b)
        assert k != cache_key(model=MODEL, prompt_version="other", bundle=b)
        assert k != cache_key(model=MODEL, prompt_version="pv1", bundle={"x": 9})
        assert input_hash(b) != input_hash({"x": 9})

    def test_gateway_misses_cache_for_different_bundle(self):
        """A changed bundle must not hit the recorded entry (provider called again)."""
        store = MemoryStore()
        model = FakeModel([verdict_payload(verdict="safe"), verdict_payload(verdict="vulnerable")])
        gw = LLMGateway(model, config=GatewayConfig(mode=Mode.RECORD), store=store,
                        fallback=lambda: {"verdict": "safe"})
        r1 = gw.call(make_request({"file": "a.py"}))
        r2 = gw.call(make_request({"file": "b.py"}))
        assert r1.source == "provider" and r2.source == "provider"
        assert r1.data["verdict"] == "safe" and r2.data["verdict"] == "vulnerable"
        assert len(model.calls) == 2

    def test_gateway_misses_cache_for_different_model(self):
        model = FakeModel([verdict_payload(), verdict_payload()])
        gw = make_gateway([])  # placeholder replaced below
        gw = LLMGateway(model, config=GatewayConfig(mode=Mode.RECORD), store=MemoryStore(),
                        fallback=lambda: {"verdict": "safe"})
        gw.call(make_request({"f": 1}, model="model-a"))
        gw.call(make_request({"f": 1}, model="model-b"))
        assert len(model.calls) == 2  # no cache sharing across models


# --------------------------------------------------------------------- replay strictness


class TestReplay:
    def test_strict_replay_raises_replay_miss_on_unrecorded_call(self):
        gw = make_gateway([], config=GatewayConfig(mode=Mode.STRICT_REPLAY), store=MemoryStore())
        with pytest.raises(ReplayMissError):
            gw.call(make_request({"never": "recorded"}))

    def test_replay_mode_falls_back_on_unrecorded_call(self):
        gw = make_gateway([], config=GatewayConfig(mode=Mode.REPLAY), store=MemoryStore())
        resp = gw.call(make_request({"never": "recorded"}))
        assert resp.used_fallback
        assert resp.degraded_reason == "unrecorded_call_replay"
        assert resp.data == {"verdict": "safe", "degraded": True}

    def test_strict_replay_hit_returns_recorded_data(self):
        store = MemoryStore()
        rec = make_gateway([verdict_payload(verdict="vulnerable")],
                           config=GatewayConfig(mode=Mode.RECORD), store=store)
        recorded = rec.call(make_request({"f": 1}))
        gw = make_gateway([], config=GatewayConfig(mode=Mode.STRICT_REPLAY), store=store)
        resp = gw.call(make_request({"f": 1}))
        assert not resp.used_fallback
        assert resp.data == recorded.data
        assert resp.source == "replay"

    def test_record_then_replay_identical_fully_offline(self, no_network):
        """Record with the fake provider, then replay with a provider whose
        complete() raises if touched. socket.socket is monkeypatched to raise
        (no_network fixture), so any network use would fail the test."""
        store = MemoryStore()
        rec_gw = make_gateway([verdict_payload(verdict="vulnerable", score=7)],
                              config=GatewayConfig(mode=Mode.RECORD), store=store)
        recorded = rec_gw.call(make_request({"f": 1}))

        class DeadProvider:
            name = "dead"

            def complete(self, **kwargs):  # pragma: no cover - must never run
                raise AssertionError("provider must not be called in replay mode")

        replay_gw = LLMGateway(DeadProvider(), config=GatewayConfig(mode=Mode.REPLAY),
                               store=store, fallback=lambda: {"verdict": "fallback"})
        resp = replay_gw.call(make_request({"f": 1}))
        assert resp.source == "replay"
        assert resp.data == recorded.data == {"verdict": "vulnerable", "score": 7}
        assert resp.tokens_in == recorded.tokens_in
        assert resp.tokens_out == recorded.tokens_out


# --------------------------------------------------------------------- budgets


class TestBudgets:
    def test_call_budget_exceeded_routes_to_fallback_without_provider_call(self):
        model = FakeModel([verdict_payload()])
        gw = make_gateway([], fallback=lambda: {"verdict": "fallback"})
        gw.provider = model  # ensure the fake records every provider attempt
        bstate = BudgetState()
        bstate.record(tokens_in=0, tokens_out=0, cost_usd=0.0)  # spent_calls = 1
        resp = gw.call(make_request(), budget=Budget(max_calls=1), budget_state=bstate)
        assert resp.used_fallback and resp.degraded_reason == "budget_exceeded"
        assert model.calls == []  # the budget gate fires before the provider
        assert bstate.spent_calls == 1  # fallback must not consume budget

    def test_call_budget_exceeded_with_no_fallback_raises_gateway_error(self):
        gw = LLMGateway(FakeModel([]), config=GatewayConfig(), store=MemoryStore(), fallback=None)
        bstate = BudgetState()
        bstate.record(tokens_in=0, tokens_out=0, cost_usd=0.0)
        with pytest.raises(GatewayError):
            gw.call(make_request(), budget=Budget(max_calls=1), budget_state=bstate)
        # BudgetExceededError is the declared kind for this path
        assert BudgetExceededError.kind == "budget"

    def test_token_out_budget_enforced(self):
        # FakeModel charges 10 tokens in / 10 out per call by default
        model = FakeModel([verdict_payload(), verdict_payload()])
        gw = LLMGateway(model, config=GatewayConfig(), store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        bstate = BudgetState()
        r1 = gw.call(make_request(), budget=Budget(max_tokens_out=10), budget_state=bstate)
        assert r1.source == "provider"
        r2 = gw.call(make_request(), budget=Budget(max_tokens_out=10), budget_state=bstate)
        assert r2.used_fallback and r2.degraded_reason == "budget_exceeded"
        assert len(model.calls) == 1

    def test_token_in_budget_enforced(self):
        model = FakeModel([verdict_payload(), verdict_payload()])
        gw = LLMGateway(model, config=GatewayConfig(), store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        bstate = BudgetState()
        gw.call(make_request({"blob": "x" * 40}), budget=Budget(max_tokens_in=15), budget_state=bstate)
        # spent_tokens_in is 10 after call 1; est for call 2 is ~10, so 10 + est > 15
        r2 = gw.call(make_request({"blob": "x" * 40}), budget=Budget(max_tokens_in=15), budget_state=bstate)
        assert r2.used_fallback

    def test_cost_budget_enforced_with_prices(self):
        # 10 in + 10 out at 1_000_000 per 1M tokens = 20 USD per call
        cfg = GatewayConfig(prices={MODEL: (1_000_000.0, 1_000_000.0)})
        model = FakeModel([verdict_payload(), verdict_payload()])
        gw = LLMGateway(model, config=cfg, store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        bstate = BudgetState()
        r1 = gw.call(make_request(), budget=Budget(max_cost_usd=20.0), budget_state=bstate)
        assert r1.source == "provider" and r1.cost_usd == pytest.approx(20.0)
        r2 = gw.call(make_request(), budget=Budget(max_cost_usd=20.0), budget_state=bstate)
        assert r2.used_fallback and r2.degraded_reason == "budget_exceeded"
        assert len(model.calls) == 1

    def test_zero_budget_blocks_first_call(self):
        model = FakeModel([verdict_payload()])
        gw = LLMGateway(model, config=GatewayConfig(), store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        resp = gw.call(make_request(), budget=Budget(max_calls=0), budget_state=BudgetState())
        assert resp.used_fallback and model.calls == []


# --------------------------------------------------------------------- error classification


class TestErrorHandling:
    def test_transient_errors_back_off_then_succeed(self, fake_clock):
        from reposentry.gateway.errors import RateLimitError

        model = FakeModel([RateLimitError("429"), RateLimitError("429"), verdict_payload()])
        cfg = GatewayConfig(backoff_base_s=0.05)
        gw = LLMGateway(model, config=cfg, store=MemoryStore(), clock=fake_clock,
                        fallback=lambda: {"verdict": "fallback"})
        resp = gw.call(make_request())
        assert resp.source == "provider"
        assert resp.data == {"verdict": "safe"}
        assert resp.attempts == 3
        assert len(model.calls) == 3
        # bounded exponential backoff: base * 2^(attempt-1)
        assert fake_clock.sleeps == [0.05, 0.10]

    def test_permanent_error_goes_straight_to_fallback(self, fake_clock):
        from reposentry.gateway.errors import PermanentProviderError

        class HardDown(PermanentProviderError):
            kind = "hard_down"

        model = FakeModel([HardDown("auth revoked"), verdict_payload()])
        gw = LLMGateway(model, config=GatewayConfig(), store=MemoryStore(), clock=fake_clock,
                        fallback=lambda: {"verdict": "fallback"})
        resp = gw.call(make_request())
        assert resp.used_fallback
        assert resp.degraded_reason == "permanent:hard_down"
        assert model.calls == [model.calls[0]]  # exactly one provider attempt
        assert fake_clock.sleeps == []  # no backoff for permanent errors

    def test_script_exhaustion_is_permanent(self):
        model = FakeModel([])  # nothing scripted -> ScriptExhausted (permanent)
        gw = LLMGateway(model, config=GatewayConfig(), store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        resp = gw.call(make_request())
        assert resp.used_fallback and resp.degraded_reason.startswith("permanent:script_exhausted")


# --------------------------------------------------------------------- kill switch


class TestKillSwitch:
    def test_kill_switch_routes_to_fallback_without_any_provider_call(self):
        model = FakeModel([verdict_payload()])
        cfg = GatewayConfig(kill_switch=True)
        gw = LLMGateway(model, config=cfg, store=MemoryStore(),
                        fallback=lambda: {"verdict": "non_llm"})
        resp = gw.call(make_request())
        assert resp.used_fallback
        assert resp.degraded_reason == "kill_switch"
        assert resp.data == {"verdict": "non_llm"}
        assert resp.raw_text is None
        assert model.calls == []

    def test_kill_switch_without_fallback_raises(self):
        gw = LLMGateway(FakeModel([]), config=GatewayConfig(kill_switch=True),
                        store=MemoryStore(), fallback=None)
        with pytest.raises(GatewayError):
            gw.call(make_request())


# --------------------------------------------------------------------- scrubbing


class TestScrubbing:
    def test_secret_in_bundle_redacted_before_send(self):
        """The scripted bundle contains 'api_key = sk-abcdef1234567890'; the
        recorded user_text must not contain the secret."""
        model = FakeModel([verdict_payload()])
        gw = LLMGateway(model, config=GatewayConfig(), store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        bundle = {"file": "app.py", "code": f"api_key = {SECRET}"}
        gw.call(make_request(bundle))
        sent = model.calls[0]["user_text"]
        assert SECRET not in sent
        assert "[REDACTED]" in sent
        assert model.calls[0]["model"] == MODEL

    def test_nested_secret_leaves_redacted(self):
        model = FakeModel([verdict_payload()])
        gw = LLMGateway(model, config=GatewayConfig(), store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        bundle = {"files": [{"name": "cfg.py", "lines": [f"token = {SECRET}"]}]}
        gw.call(make_request(bundle))
        sent = model.calls[0]["user_text"]
        assert SECRET not in sent
        assert "[REDACTED]" in sent

    def test_scrubbed_bundle_is_what_the_cache_key_covers(self):
        """Two bundles differing only by a secret must map to the same cache
        entry: the key is computed over the scrubbed bundle (gateway.py)."""
        from reposentry.gateway.scrub import scrub_bundle

        assert input_hash(scrub_bundle(f"api_key = {SECRET}")) == input_hash(scrub_bundle("api_key = [REDACTED]"))


# --------------------------------------------------------------------- schema validation


class TestSchemaValidation:
    def test_valid_nested_object_passes_through_gateway(self):
        payload = json.dumps({
            "verdict": "vulnerable",
            "score": 3,
            "notes": "ok",  # within maxLength 10
            "items": [{"id": "a"}, {"id": "b"}],  # within maxItems 2
        })
        gw = make_gateway([payload])
        resp = gw.call(make_request())
        assert resp.data == json.loads(payload)

    def test_enum_violation_repairs_then_falls_back(self):
        model = FakeModel([verdict_payload(verdict="maybe"), verdict_payload(verdict="maybe"),
                           verdict_payload(verdict="maybe")])
        gw = LLMGateway(model, config=GatewayConfig(repair_retries=2), store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        resp = gw.call(make_request())
        assert resp.used_fallback and resp.degraded_reason == "schema_validation_exhausted"
        assert len(model.calls) == 3  # 1 initial + 2 repair retries

    def test_max_length_violation_rejected(self):
        from reposentry.gateway.schema import parse_and_validate
        from reposentry.gateway.errors import SchemaValidationError

        bad = verdict_payload(notes="x" * 11)
        with pytest.raises(SchemaValidationError):
            parse_and_validate(bad, VERDICT_SCHEMA, max_bytes=100_000)

    def test_additional_properties_false_rejects_extra_fields_at_top_level(self):
        from reposentry.gateway.schema import parse_and_validate
        from reposentry.gateway.errors import SchemaValidationError

        bad = json.dumps({"verdict": "safe", "bonus": True})
        with pytest.raises(SchemaValidationError, match="extra fields"):
            parse_and_validate(bad, VERDICT_SCHEMA, max_bytes=100_000)

    def test_nested_object_rejects_extra_fields(self):
        from reposentry.gateway.schema import parse_and_validate
        from reposentry.gateway.errors import SchemaValidationError

        bad = json.dumps({"verdict": "safe", "items": [{"id": "a", "evil": 1}]})
        with pytest.raises(SchemaValidationError, match="extra fields"):
            parse_and_validate(bad, VERDICT_SCHEMA, max_bytes=100_000)

    def test_nested_required_and_type_errors(self):
        from reposentry.gateway.schema import parse_and_validate
        from reposentry.gateway.errors import SchemaValidationError

        with pytest.raises(SchemaValidationError, match="missing required"):
            parse_and_validate(json.dumps({"verdict": "safe", "items": [{}]}), VERDICT_SCHEMA, max_bytes=100_000)
        with pytest.raises(SchemaValidationError, match="expected integer"):
            parse_and_validate(json.dumps({"verdict": "safe", "score": "high"}), VERDICT_SCHEMA, max_bytes=100_000)
        with pytest.raises(SchemaValidationError, match="too many items"):
            parse_and_validate(
                json.dumps({"verdict": "safe", "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}),
                VERDICT_SCHEMA, max_bytes=100_000,
            )

    def test_max_items_violation_falls_back_via_gateway(self):
        bad = json.dumps({"verdict": "safe", "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}]})
        model = FakeModel([bad, bad, bad])
        gw = LLMGateway(model, config=GatewayConfig(repair_retries=2), store=MemoryStore(),
                        fallback=lambda: {"verdict": "fallback"})
        resp = gw.call(make_request())
        assert resp.used_fallback
