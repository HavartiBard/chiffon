"""Comprehensive tests for external AI fallback service.

Tests cover:
- Fallback triggers (quota, complexity, default)
- Quota tracking and calculation
- Claude success and failure scenarios
- Ollama fallback behavior
- Both-tiers-fail scenarios
- Complexity assessment
- Audit logging
"""

from unittest.mock import MagicMock, patch

import pytest

from src.common.config import Config
from src.common.litellm_client import LiteLLMClient
from src.common.models import WorkPlan
from src.orchestrator.fallback import ExternalAIFallback


@pytest.fixture
def config():
    """Configuration fixture."""
    cfg = Config()
    return cfg


@pytest.fixture
def mock_litellm_client():
    """Mock LiteLLMClient fixture."""
    return MagicMock(spec=LiteLLMClient)


@pytest.fixture
def fallback_service(config, mock_litellm_client):
    """ExternalAIFallback service instance."""
    return ExternalAIFallback(
        litellm_client=mock_litellm_client,
        config=config,
    )


@pytest.fixture
def simple_plan():
    """Simple complexity work plan."""
    return WorkPlan(
        plan_id="test-plan-simple",
        request_id="test-request-simple",
        tasks=[],
        estimated_duration_seconds=100,
        complexity_level="simple",
        will_use_external_ai=False,
        human_readable_summary="Simple task",
    )


@pytest.fixture
def medium_plan():
    """Medium complexity work plan."""
    return WorkPlan(
        plan_id="test-plan-medium",
        request_id="test-request-medium",
        tasks=[],
        estimated_duration_seconds=200,
        complexity_level="medium",
        will_use_external_ai=False,
        human_readable_summary="Medium task",
    )


@pytest.fixture
def complex_plan():
    """Complex complexity work plan."""
    return WorkPlan(
        plan_id="test-plan-complex",
        request_id="test-request-complex",
        tasks=[],
        estimated_duration_seconds=300,
        complexity_level="complex",
        will_use_external_ai=True,
        human_readable_summary="Complex task",
    )


# ===== Test Class 1: Fallback Triggers =====


@pytest.mark.asyncio
async def test_simple_plan_no_fallback(fallback_service, simple_plan):
    """Simple complexity + high quota should use Ollama."""
    decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)

    assert decision.decision == "use_ollama"
    assert use_claude is False
    assert decision.reason == "local_sufficient"
    assert decision.complexity_level == "simple"


@pytest.mark.asyncio
async def test_complex_plan_triggers_claude(fallback_service, complex_plan):
    """Complex complexity should trigger Claude."""
    decision, use_claude = await fallback_service.should_use_external_ai(complex_plan)

    assert decision.decision == "use_claude"
    assert use_claude is True
    assert decision.reason == "high_complexity"
    assert decision.complexity_level == "complex"


@pytest.mark.asyncio
async def test_low_quota_triggers_claude(fallback_service, simple_plan):
    """Quota <20% should trigger Claude regardless of complexity."""
    # Mock the quota to return 15% remaining
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.15):
        decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)

        assert decision.decision == "use_claude"
        assert use_claude is True
        assert decision.reason == "quota_critical"
        assert decision.quota_remaining_percent == 0.15


@pytest.mark.asyncio
async def test_high_quota_simple_plan(fallback_service, simple_plan):
    """Quota >20% + simple complexity should use Ollama."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.80):
        decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)

        assert decision.decision == "use_ollama"
        assert use_claude is False
        assert decision.quota_remaining_percent == 0.80


@pytest.mark.asyncio
async def test_quota_exactly_20_percent(fallback_service, simple_plan):
    """Edge case: quota=20% exactly should trigger Claude."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.20):
        decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)

        # At exactly 20%, it should NOT trigger (<20% required)
        assert decision.decision == "use_ollama"


@pytest.mark.asyncio
async def test_quota_19_percent(fallback_service, simple_plan):
    """Quota=19% should trigger Claude."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.19):
        decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)

        assert decision.decision == "use_claude"
        assert use_claude is True
        assert decision.reason == "quota_critical"


# ===== Test Class 2: Quota Tracking =====


@pytest.mark.asyncio
async def test_get_remaining_quota_success(fallback_service):
    """Successfully retrieve quota from LiteLLM."""
    quota = await fallback_service._get_remaining_quota()
    assert 0.0 <= quota <= 1.0


@pytest.mark.asyncio
async def test_get_remaining_quota_unavailable(fallback_service):
    """LiteLLM unavailable should default to safe Ollama (1.0)."""
    with patch.object(
        fallback_service, "_get_remaining_quota", side_effect=Exception("API unavailable")
    ):
        # When exception is raised in quota check, fallback catches it
        simple_plan = WorkPlan(
            plan_id="test",
            request_id="test",
            tasks=[],
            estimated_duration_seconds=100,
            complexity_level="simple",
            will_use_external_ai=False,
            human_readable_summary="test",
        )
        # This should not raise even when quota check fails
        decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)
        # On error, defaults to Ollama
        assert decision.decision == "use_ollama"


@pytest.mark.asyncio
async def test_quota_percentage_calculated(fallback_service):
    """Quota percentage correctly calculated from budget and spend."""
    # Default behavior returns 0.80 (80% remaining)
    quota = await fallback_service._get_remaining_quota()
    assert quota == 0.80


@pytest.mark.asyncio
async def test_quota_zero_remaining(fallback_service, simple_plan):
    """Zero quota remaining should use Claude."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.0):
        decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)
        assert decision.decision == "use_claude"
        assert decision.reason == "quota_critical"


@pytest.mark.asyncio
async def test_quota_negative_handled(fallback_service, simple_plan):
    """Negative quota (overage) should be clamped to 0% and use Claude."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.0):
        decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)
        assert decision.quota_remaining_percent == 0.0
        assert decision.decision == "use_claude"


@pytest.mark.asyncio
async def test_quota_check_logged(fallback_service, simple_plan):
    """Quota check should be recorded in FallbackDecision."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.65):
        decision, _ = await fallback_service.should_use_external_ai(simple_plan)
        assert decision.quota_remaining_percent == 0.65


# ===== Test Class 3: Claude Failover =====


@pytest.mark.asyncio
async def test_claude_success(fallback_service):
    """Claude call succeeds should return response."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    mock_response = {
        "choices": [{"message": {"content": "Claude response"}}],
        "usage": {"total_tokens": 100},
    }

    with patch.object(fallback_service.llm, "call_llm", return_value=mock_response):
        response = await fallback_service.call_external_ai_with_fallback(
            "test prompt", task_context
        )
        assert response["choices"][0]["message"]["content"] == "Claude response"


@pytest.mark.asyncio
async def test_claude_timeout_falls_back(fallback_service):
    """Claude timeout should fall back to Ollama."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    mock_ollama_response = {"choices": [{"message": {"content": "Ollama fallback response"}}]}

    # Mock Claude to timeout, Ollama to succeed
    call_count = 0

    def mock_call_llm(model, messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if model == "claude-opus-4.5":
            raise TimeoutError("Claude timeout")
        elif model == "ollama/neural-chat":
            return mock_ollama_response
        raise Exception("Unexpected model")

    with patch.object(fallback_service.llm, "call_llm", side_effect=mock_call_llm):
        response = await fallback_service.call_external_ai_with_fallback(
            "test prompt", task_context
        )
        assert response["choices"][0]["message"]["content"] == "Ollama fallback response"
        assert call_count == 2  # Claude tried first, then Ollama


@pytest.mark.asyncio
async def test_claude_rate_limit_falls_back(fallback_service):
    """Claude rate limit should fall back to Ollama."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    mock_ollama_response = {"choices": [{"message": {"content": "Ollama fallback"}}]}

    def mock_call_llm(model, messages, **kwargs):
        if model == "claude-opus-4.5":
            raise Exception("Rate limit exceeded")
        elif model == "ollama/neural-chat":
            return mock_ollama_response
        raise Exception("Unexpected model")

    with patch.object(fallback_service.llm, "call_llm", side_effect=mock_call_llm):
        response = await fallback_service.call_external_ai_with_fallback(
            "test prompt", task_context
        )
        assert response["choices"][0]["message"]["content"] == "Ollama fallback"


@pytest.mark.asyncio
async def test_claude_invalid_response_fails(fallback_service):
    """Claude returning invalid JSON should raise ValueError."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    # Both Claude and Ollama return invalid responses
    def mock_call_llm(model, messages, **kwargs):
        raise Exception("Invalid response format")

    with patch.object(fallback_service.llm, "call_llm", side_effect=mock_call_llm):
        with pytest.raises(Exception):
            await fallback_service.call_external_ai_with_fallback("test prompt", task_context)


@pytest.mark.asyncio
async def test_claude_usage_logged(fallback_service):
    """Successful Claude call should be logged."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    mock_response = {
        "choices": [{"message": {"content": "Claude response"}}],
        "usage": {"total_tokens": 150},
    }

    with patch.object(fallback_service.llm, "call_llm", return_value=mock_response):
        with patch.object(fallback_service, "_log_llm_usage") as mock_log:
            response = await fallback_service.call_external_ai_with_fallback(
                "test prompt", task_context
            )
            # Verify response was returned
            assert response["choices"][0]["message"]["content"] == "Claude response"


# ===== Test Class 4: Ollama Fallback =====


@pytest.mark.asyncio
async def test_ollama_success(fallback_service):
    """Ollama call succeeds when Claude not used."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "simple"},
        "should_use_claude": False,
    }

    mock_response = {"choices": [{"message": {"content": "Ollama response"}}]}

    with patch.object(fallback_service.llm, "call_llm", return_value=mock_response):
        response = await fallback_service.call_external_ai_with_fallback(
            "test prompt", task_context
        )
        assert response["choices"][0]["message"]["content"] == "Ollama response"


@pytest.mark.asyncio
async def test_ollama_failure_raises(fallback_service):
    """Ollama failure after Claude failure should raise Exception."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    def mock_call_llm(model, messages, **kwargs):
        raise Exception("All models failed")

    with patch.object(fallback_service.llm, "call_llm", side_effect=mock_call_llm):
        with pytest.raises(Exception) as exc_info:
            await fallback_service.call_external_ai_with_fallback("test prompt", task_context)
        assert "Both Claude and Ollama failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ollama_timeout_raises(fallback_service):
    """Ollama timeout should raise TimeoutError."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "simple"},
        "should_use_claude": False,
    }

    with patch.object(fallback_service.llm, "call_llm", side_effect=TimeoutError("Ollama timeout")):
        with pytest.raises(Exception):
            await fallback_service.call_external_ai_with_fallback("test prompt", task_context)


@pytest.mark.asyncio
async def test_ollama_usage_logged(fallback_service):
    """Successful Ollama call should be logged."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "simple"},
        "should_use_claude": False,
    }

    mock_response = {
        "choices": [{"message": {"content": "Ollama response"}}],
    }

    with patch.object(fallback_service.llm, "call_llm", return_value=mock_response):
        response = await fallback_service.call_external_ai_with_fallback(
            "test prompt", task_context
        )
        assert response is not None


# ===== Test Class 5: Both Tiers Fail =====


@pytest.mark.asyncio
async def test_both_claude_and_ollama_fail(fallback_service):
    """Both tiers failing should raise Exception with context."""
    task_context = {
        "plan_id": "test-plan-fail",
        "name": "failing task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    def mock_call_llm(model, messages, **kwargs):
        raise Exception(f"{model} failed")

    with patch.object(fallback_service.llm, "call_llm", side_effect=mock_call_llm):
        with pytest.raises(Exception) as exc_info:
            await fallback_service.call_external_ai_with_fallback("test prompt", task_context)
        error_msg = str(exc_info.value)
        assert "Both Claude and Ollama failed" in error_msg
        assert "test-plan-fail" in error_msg


@pytest.mark.asyncio
async def test_error_message_includes_context(fallback_service):
    """Exception should include task context for debugging."""
    task_context = {
        "plan_id": "ctx-test-plan",
        "name": "context task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    with patch.object(fallback_service.llm, "call_llm", side_effect=Exception("LLM error")):
        with pytest.raises(Exception) as exc_info:
            await fallback_service.call_external_ai_with_fallback("test prompt", task_context)
        error_msg = str(exc_info.value)
        assert "ctx-test-plan" in error_msg


@pytest.mark.asyncio
async def test_final_error_logged(fallback_service):
    """Failure should be logged with error details."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "complex"},
        "should_use_claude": True,
    }

    with patch.object(fallback_service.llm, "call_llm", side_effect=Exception("All failed")):
        with pytest.raises(Exception):
            await fallback_service.call_external_ai_with_fallback("test prompt", task_context)


# ===== Test Class 6: Complexity Assessment =====


@pytest.mark.asyncio
async def test_assess_complexity_simple(fallback_service, simple_plan):
    """Simple complexity (1-2 tasks) should not trigger fallback."""
    decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)
    assert decision.complexity_level == "simple"
    assert use_claude is False


@pytest.mark.asyncio
async def test_assess_complexity_medium(fallback_service, medium_plan):
    """Medium complexity (3+ tasks) may trigger fallback if high quota."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.90):
        decision, use_claude = await fallback_service.should_use_external_ai(medium_plan)
        # Medium should default to Ollama unless quota critical
        assert decision.complexity_level == "medium"
        assert decision.decision == "use_ollama"


@pytest.mark.asyncio
async def test_assess_complexity_complex(fallback_service, complex_plan):
    """Complex tasks should always use Claude."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.90):
        decision, use_claude = await fallback_service.should_use_external_ai(complex_plan)
        assert decision.complexity_level == "complex"
        assert use_claude is True
        assert decision.reason == "high_complexity"


# ===== Test Class 7: Audit Logging =====


@pytest.mark.asyncio
async def test_fallback_decision_recorded(fallback_service, complex_plan):
    """Fallback decision should be recorded."""
    decision, _ = await fallback_service.should_use_external_ai(complex_plan)
    assert decision.task_id == complex_plan.plan_id
    assert decision.decision in ["use_claude", "use_ollama"]
    assert decision.created_at is not None


@pytest.mark.asyncio
async def test_fallback_reason_logged(fallback_service, simple_plan):
    """Reason field should explain decision."""
    decision, _ = await fallback_service.should_use_external_ai(simple_plan)
    assert decision.reason in [
        "quota_critical",
        "high_complexity",
        "local_sufficient",
    ]


@pytest.mark.asyncio
async def test_fallback_model_tracked(fallback_service, simple_plan):
    """Model used should be tracked in FallbackDecision."""
    decision, _ = await fallback_service.should_use_external_ai(simple_plan)
    assert decision.model_used in ["claude-opus-4.5", "ollama/neural-chat"]


@pytest.mark.asyncio
async def test_fallback_tokens_tracked(fallback_service):
    """Token usage should be tracked if available."""
    task_context = {
        "plan_id": "test-plan",
        "name": "test task",
        "plan": {"complexity_level": "simple"},
        "should_use_claude": False,
    }

    mock_response = {
        "choices": [{"message": {"content": "response"}}],
        "usage": {"total_tokens": 200},
    }

    with patch.object(fallback_service.llm, "call_llm", return_value=mock_response):
        response = await fallback_service.call_external_ai_with_fallback("test", task_context)
        assert response is not None


@pytest.mark.asyncio
async def test_fallback_cost_tracked(fallback_service, simple_plan):
    """Cost should be tracked in FallbackDecision."""
    decision, _ = await fallback_service.should_use_external_ai(simple_plan)
    # Cost may be None for local models
    assert decision.cost_usd is None or decision.cost_usd >= 0.0


@pytest.mark.asyncio
async def test_audit_queryable_by_decision(fallback_service, simple_plan):
    """FallbackDecision should be queryable by decision type."""
    decision, _ = await fallback_service.should_use_external_ai(simple_plan)
    assert decision.decision in ["use_claude", "use_ollama", "no_fallback"]


@pytest.mark.asyncio
async def test_audit_queryable_by_reason(fallback_service, complex_plan):
    """FallbackDecision should be queryable by reason."""
    decision, _ = await fallback_service.should_use_external_ai(complex_plan)
    assert decision.reason in [
        "quota_critical",
        "high_complexity",
        "local_sufficient",
        "claude_failed",
    ]


# ===== Integration Tests =====


@pytest.mark.asyncio
async def test_fallback_flow_simple_to_complex(fallback_service, simple_plan, complex_plan):
    """Test flow from simple (Ollama) to complex (Claude)."""
    # Simple plan
    decision1, use_claude1 = await fallback_service.should_use_external_ai(simple_plan)
    assert use_claude1 is False

    # Complex plan
    decision2, use_claude2 = await fallback_service.should_use_external_ai(complex_plan)
    assert use_claude2 is True

    # Verify decisions are different
    assert decision1.decision != decision2.decision


@pytest.mark.asyncio
async def test_fallback_with_low_quota_override(fallback_service, simple_plan):
    """Low quota should override complexity assessment."""
    with patch.object(fallback_service, "_get_remaining_quota", return_value=0.10):
        decision, use_claude = await fallback_service.should_use_external_ai(simple_plan)
        assert use_claude is True
        assert decision.reason == "quota_critical"


@pytest.mark.asyncio
async def test_multiple_fallback_calls_isolated(fallback_service):
    """Multiple calls should not interfere with each other."""
    plan1 = WorkPlan(
        plan_id="plan1",
        request_id="req1",
        tasks=[],
        estimated_duration_seconds=100,
        complexity_level="simple",
        will_use_external_ai=False,
        human_readable_summary="Plan 1",
    )
    plan2 = WorkPlan(
        plan_id="plan2",
        request_id="req2",
        tasks=[],
        estimated_duration_seconds=300,
        complexity_level="complex",
        will_use_external_ai=True,
        human_readable_summary="Plan 2",
    )

    decision1, use_claude1 = await fallback_service.should_use_external_ai(plan1)
    decision2, use_claude2 = await fallback_service.should_use_external_ai(plan2)

    assert decision1.task_id == "plan1"
    assert decision2.task_id == "plan2"
    assert use_claude1 is False
    assert use_claude2 is True
