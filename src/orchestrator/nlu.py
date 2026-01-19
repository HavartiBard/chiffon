"""Natural Language Understanding (NLU) layer for request parsing and decomposition.

Provides RequestDecomposer service that accepts user requests in natural language,
structures them into decomposed subtasks with confidence scoring, and detects
ambiguities and out-of-scope requests.
"""

import json
import logging
from typing import Optional
from uuid import uuid4

from src.common.litellm_client import LiteLLMClient
from src.common.models import DecomposedRequest, RequestParsingConfig, Subtask

logger = logging.getLogger(__name__)


class RequestDecomposer:
    """Service for decomposing natural language requests into structured work.

    Accepts user requests, uses Claude via LiteLLM to parse intent and break down
    into subtasks, detects ambiguities, identifies out-of-scope requests, and
    assesses complexity.
    """

    def __init__(
        self,
        llm_client: LiteLLMClient,
        config: Optional[RequestParsingConfig] = None,
    ):
        """Initialize RequestDecomposer.

        Args:
            llm_client: LiteLLMClient for LLM API calls
            config: RequestParsingConfig for NLU behavior (uses defaults if None)
        """
        self.llm = llm_client
        self.config = config or RequestParsingConfig()
        self.logger = logging.getLogger("orchestrator.nlu")

    async def decompose(self, request: str) -> DecomposedRequest:
        """Decompose a natural language request into structured work.

        Args:
            request: Natural language request text

        Returns:
            DecomposedRequest with parsed subtasks, ambiguities, out_of_scope

        Raises:
            ValueError: If request is empty/None or LLM response invalid
        """
        # Validate input
        if not request or not isinstance(request, str):
            raise ValueError("Request cannot be empty or None")

        # Generate request ID
        request_id = str(uuid4())

        try:
            # Build decomposition prompt
            prompt = self._build_decomposition_prompt(request)

            # Call Claude via LiteLLM
            self.logger.debug(f"Calling Claude to decompose request {request_id}")
            response = self.llm.call_llm(
                model="claude-opus-4.5",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000,
            )

            # Extract response content
            if not response or "choices" not in response:
                raise ValueError("Invalid LLM response structure")

            response_text = response["choices"][0]["message"]["content"]
            self.logger.debug(f"LLM response: {response_text}")

            # Parse JSON from response
            # LLM might include markdown code blocks, so strip them
            json_str = response_text
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]

            parsed = json.loads(json_str.strip())

            # Validate and construct subtasks
            subtasks_data = parsed.get("subtasks", [])
            subtasks = []
            for st in subtasks_data:
                subtask = Subtask(
                    order=st.get("order", len(subtasks) + 1),
                    name=st.get("name", ""),
                    intent=st.get("intent", ""),
                    confidence=float(st.get("confidence", 0.5)),
                    parameters=st.get("parameters"),
                )
                subtasks.append(subtask)

            # Extract ambiguities and out_of_scope
            ambiguities = parsed.get("ambiguities", [])
            out_of_scope = parsed.get("out_of_scope", [])

            # Assess complexity
            complexity_level = self._assess_complexity(subtasks)

            # Create DecomposedRequest
            decomposed = DecomposedRequest(
                request_id=request_id,
                original_request=request,
                subtasks=subtasks,
                ambiguities=ambiguities,
                out_of_scope=out_of_scope,
                complexity_level=complexity_level,
                decomposer_model="claude",
            )

            # Log results
            self.logger.info(
                f"Decomposed request {request_id} into {len(subtasks)} subtasks, "
                f"complexity={complexity_level}"
            )

            if ambiguities:
                self.logger.warning(
                    f"Request {request_id} has {len(ambiguities)} ambiguities: {ambiguities}"
                )

            if out_of_scope:
                self.logger.warning(
                    f"Request {request_id} has {len(out_of_scope)} out-of-scope items: {out_of_scope}"
                )

            return decomposed

        except json.JSONDecodeError as e:
            self.logger.error(
                f"Failed to parse JSON from LLM response for request {request_id}: {e}"
            )
            raise ValueError(
                f"Failed to parse decomposition response: {e}. "
                f"LLM response may not be valid JSON."
            )
        except Exception as e:
            self.logger.error(
                f"Error decomposing request {request_id}: {e}", exc_info=True
            )
            raise

    def _build_decomposition_prompt(self, request: str) -> str:
        """Build a structured prompt for request decomposition.

        Args:
            request: User request text

        Returns:
            Prompt text for Claude
        """
        prompt = f"""You are an intelligent orchestrator that breaks down user requests into executable subtasks.

Your job is to:
1. Parse the user's request
2. Identify the main intent(s)
3. Break down into 1-5 concrete subtasks
4. Flag any ambiguities
5. Identify capabilities you don't have

Known agent types and their capabilities:
- infra: Deploy services, run Ansible playbooks, manage Docker containers, configure infrastructure
- code: Generate code, review code, implement features
- research: Research topics, find information, analyze data
- desktop: Check system metrics, GPU status, resource availability

Example decomposition:
User: "Deploy Kuma and add portals to config"
Response: {{
  "subtasks": [
    {{"order": 1, "name": "Deploy Kuma Uptime", "intent": "deploy_kuma", "confidence": 0.95, "parameters": {{"service": "kuma"}}}},
    {{"order": 2, "name": "Add existing portals to config", "intent": "add_config", "confidence": 0.8, "parameters": {{"type": "portal_config"}}}}
  ],
  "ambiguities": [],
  "out_of_scope": []
}}

User request: "{request}"

Return ONLY valid JSON (no explanation) with this structure:
{{
  "subtasks": [
    {{"order": <int>, "name": "<str>", "intent": "<str>", "confidence": <0.0-1.0>, "parameters": <dict or null>}},
    ...
  ],
  "ambiguities": ["<str>", ...],
  "out_of_scope": ["<str>", ...]
}}"""
        return prompt

    def _assess_complexity(self, subtasks: list[Subtask]) -> str:
        """Assess the complexity level of decomposed subtasks.

        Args:
            subtasks: List of decomposed subtasks

        Returns:
            "simple", "medium", or "complex"
        """
        if not subtasks:
            return "simple"

        # Check for complex intents
        complex_intents = {"research", "code_gen", "architecture_review"}
        has_complex = any(st.intent in complex_intents for st in subtasks)

        if has_complex:
            return "complex"

        # Check number of subtasks
        if len(subtasks) >= 3:
            return "medium"

        # Default to simple
        return "simple"
