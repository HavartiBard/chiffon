"""External AI fallback layer with quota awareness and graceful failure handling.

Manages intelligent routing between Claude (external) and Ollama (local) based on:
- Quota remaining (if <20%, force Claude usage to optimize usage)
- Task complexity (if complex, prefer Claude for better reasoning)
- Graceful fallback (Claude → Ollama → exception)
"""

import asyncio
import json
import logging
from typing import Optional, Tuple
from uuid import UUID

from src.common.config import Config
from src.common.litellm_client import LiteLLMClient
from src.common.models import FallbackDecision, WorkPlan

logger = logging.getLogger(__name__)


class ExternalAIFallback:
    """Manages Claude/Ollama routing with quota awareness and fallback handling."""

    def __init__(
        self,
        litellm_client: LiteLLMClient,
        config: Config,
        logger_instance: Optional[logging.Logger] = None,
    ):
        """Initialize fallback service.

        Args:
            litellm_client: LiteLLM client for API calls
            config: Configuration with quota thresholds
            logger_instance: Optional logger instance (uses module logger if None)
        """
        self.llm = litellm_client
        self.config = config
        self.logger = logger_instance or logger

        # Configuration thresholds
        self.quota_threshold_percent = 20  # Use Claude if <20% quota
        self.claude_timeout_seconds = 30
        self.ollama_timeout_seconds = 15

    async def should_use_external_ai(
        self, plan: WorkPlan
    ) -> Tuple[FallbackDecision, bool]:
        """Determine if external AI (Claude) should be used for a plan.

        Decision logic:
        1. If quota <20%: use Claude (force usage to preserve remaining budget)
        2. If complexity is complex: use Claude (better reasoning)
        3. Otherwise: use Ollama (local, cost-effective)

        Args:
            plan: WorkPlan with complexity assessment

        Returns:
            Tuple of (FallbackDecision record, should_use_claude boolean)
        """
        try:
            # Step 1: Check quota
            remaining_quota = await self._get_remaining_quota()
            quota_percent = remaining_quota * 100

            self.logger.info(f"Quota check: {quota_percent:.1f}% remaining")

            if remaining_quota < (self.quota_threshold_percent / 100.0):
                self.logger.warning(
                    f"Quota critical: {quota_percent:.1f}% remaining, "
                    "using Claude"
                )
                decision = FallbackDecision(
                    task_id=plan.plan_id,
                    decision="use_claude",
                    reason="quota_critical",
                    quota_remaining_percent=remaining_quota,
                    complexity_level=plan.complexity_level,
                    fallback_tier=0,
                    model_used="claude-opus-4.5",
                )
                return decision, True

            # Step 2: Check complexity
            if plan.complexity_level == "complex":
                self.logger.info(
                    f"Complex plan detected, using Claude for better reasoning"
                )
                decision = FallbackDecision(
                    task_id=plan.plan_id,
                    decision="use_claude",
                    reason="high_complexity",
                    quota_remaining_percent=remaining_quota,
                    complexity_level=plan.complexity_level,
                    fallback_tier=0,
                    model_used="claude-opus-4.5",
                )
                return decision, True

            # Default: use Ollama (local, cost-effective)
            self.logger.debug(
                f"Using Ollama for {plan.complexity_level} complexity plan"
            )
            decision = FallbackDecision(
                task_id=plan.plan_id,
                decision="use_ollama",
                reason="local_sufficient",
                quota_remaining_percent=remaining_quota,
                complexity_level=plan.complexity_level,
                fallback_tier=0,
                model_used="ollama/neural-chat",
            )
            return decision, False

        except Exception as e:
            self.logger.error(f"Error in should_use_external_ai: {e}")
            # On error, default to Ollama (safe fallback)
            decision = FallbackDecision(
                task_id=plan.plan_id,
                decision="use_ollama",
                reason="local_sufficient",
                quota_remaining_percent=1.0,
                complexity_level=plan.complexity_level,
                fallback_tier=0,
                model_used="ollama/neural-chat",
                error_message=str(e),
            )
            return decision, False

    async def call_external_ai_with_fallback(
        self, prompt: str, task_context: dict
    ) -> dict:
        """Call external AI with three-tier fallback (Claude → Ollama → exception).

        Tries Claude first (if should_use_external_ai=True), then falls back
        to Ollama if Claude fails, and raises exception if both fail.

        Args:
            prompt: The prompt to send to LLM
            task_context: Dict with task info (task_id, name, etc) for logging

        Returns:
            LLM response dict with choices[0].message.content

        Raises:
            Exception: If both Claude and Ollama fail
            ValueError: If LLM response is malformed
        """
        plan_id = task_context.get("plan_id", "unknown")
        task_name = task_context.get("name", "unknown task")

        try:
            # Determine if should use Claude
            plan_dict = task_context.get("plan", {})
            complexity = plan_dict.get("complexity_level", "medium")

            # For testing/fallback logic, allow override
            should_use_claude = task_context.get(
                "should_use_claude", complexity == "complex"
            )

            messages = [{"role": "user", "content": prompt}]

            # Tier 1: Try Claude
            if should_use_claude:
                self.logger.info(f"Calling Claude for {task_name}")
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.llm.call_llm,
                            model="claude-opus-4.5",
                            messages=messages,
                            temperature=0.7,
                            max_tokens=2000,
                        ),
                        timeout=self.claude_timeout_seconds,
                    )
                    self.logger.info(
                        f"Claude succeeded for {task_name}. Tokens: "
                        f"{response.get('usage', {}).get('total_tokens', 'unknown')}"
                    )
                    return response

                except asyncio.TimeoutError:
                    self.logger.warning(
                        f"Claude timeout ({self.claude_timeout_seconds}s) "
                        f"for {task_name}, falling back to Ollama"
                    )
                except Exception as e:
                    if "rate" in str(e).lower():
                        self.logger.warning(
                            f"Claude rate limited for {task_name}, "
                            f"falling back to Ollama"
                        )
                    else:
                        self.logger.warning(
                            f"Claude failed for {task_name}: {e}, "
                            f"falling back to Ollama"
                        )

            # Tier 2: Try Ollama (fallback)
            self.logger.info(f"Using Ollama fallback for {task_name}")
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.llm.call_llm,
                        model="ollama/neural-chat",
                        messages=messages,
                        temperature=0.7,
                        max_tokens=2000,
                    ),
                    timeout=self.ollama_timeout_seconds,
                )
                self.logger.info(f"Ollama fallback succeeded for {task_name}")
                return response

            except Exception as e:
                self.logger.error(
                    f"Ollama fallback failed for {task_name}: {e}"
                )

            # Tier 3: Both failed - raise exception
            raise Exception(
                f"Both Claude and Ollama failed for task {plan_id} ({task_name}). "
                f"See logs for details."
            )

        except ValueError as e:
            self.logger.error(f"Invalid LLM response for {task_name}: {e}")
            raise ValueError(f"Invalid response format: {e}")

    async def _get_remaining_quota(self) -> float:
        """Get remaining quota as fraction (0.0-1.0).

        Contacts LiteLLM to check user quota. If unavailable, defaults to 1.0
        (assume unlimited, safe fallback to Ollama).

        Returns:
            Remaining budget fraction (0.0-1.0)
        """
        try:
            # Note: This is a placeholder implementation.
            # In production, this would call a real quota endpoint.
            # For now, we'll simulate a quota check.
            # The endpoint would be something like:
            # POST /v1/user/quota with api_key

            # Simulated quota check (would call LiteLLM in production)
            # For testing: assume 80% remaining by default
            remaining = 0.80

            return remaining

        except Exception as e:
            self.logger.warning(
                f"Could not check quota: {e}; defaulting to Ollama (safe)"
            )
            return 1.0  # Assume unlimited, use Ollama

    def _log_fallback_decision(
        self, decision: FallbackDecision, task_id: UUID
    ) -> None:
        """Log fallback decision to audit trail.

        In production, would insert to database. For now, logs to application logger.

        Args:
            decision: The fallback decision
            task_id: Task ID for reference
        """
        self.logger.info(
            f"Fallback: {decision.decision} due to {decision.reason} "
            f"(quota: {decision.quota_remaining_percent:.1%}, "
            f"complexity: {decision.complexity_level})"
        )

    async def _log_llm_usage(
        self, model: str, task_context: dict, tokens: int, cost: float
    ) -> None:
        """Log LLM usage for cost tracking and audit.

        In production, would update Task record in database.

        Args:
            model: Model used (claude-opus-4.5, ollama/neural-chat)
            task_context: Task context dict
            tokens: Token count used
            cost: Cost in USD
        """
        task_id = task_context.get("plan_id", "unknown")
        task_name = task_context.get("name", "unknown")
        self.logger.info(
            f"Used {model} for {task_name} ({task_id}): "
            f"{tokens} tokens, ${cost:.4f}"
        )
