"""Python client wrapper for LiteLLM API."""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class LiteLLMClient:
    """Client for interacting with LiteLLM proxy service."""

    def __init__(self, base_url: str = "http://localhost:8001", timeout: int = 30):
        """Initialize LiteLLM client.

        Args:
            base_url: Base URL of LiteLLM service (default: localhost:8001)
            timeout: Request timeout in seconds (default: 30)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.master_key = os.getenv("LITELLM_MASTER_KEY")

    def _headers(self) -> Dict[str, str]:
        """Get request headers with authorization if available."""
        headers = {"Content-Type": "application/json"}
        if self.master_key:
            headers["Authorization"] = f"Bearer {self.master_key}"
        return headers

    def call_llm(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Make a call to LiteLLM chat completions endpoint.

        Args:
            model: Model name (e.g., 'claude-opus-4.5', 'gpt-4-turbo', 'ollama/neural-chat')
            messages: List of message dicts with 'role' and 'content' keys
            temperature: Sampling temperature (0.0-1.0, default: 0.7)
            max_tokens: Maximum tokens in response (optional)

        Returns:
            Response dict with choices[0].message.content

        Raises:
            requests.RequestException: On timeout, connection error, or HTTP error
        """
        try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if max_tokens:
                payload["max_tokens"] = max_tokens

            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()

            result = response.json()
            logger.debug(f"LiteLLM response for {model}: {result}")
            return result

        except requests.RequestException as e:
            logger.error(f"Error calling LiteLLM: {e}")
            raise

    def get_available_models(self) -> List[str]:
        """Get list of available models from LiteLLM.

        Returns:
            List of model names

        Raises:
            requests.RequestException: On timeout or connection error
        """
        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()

            result = response.json()
            # Extract model names from response
            # LiteLLM returns dict with 'data' key containing list of models
            if isinstance(result, dict) and "data" in result:
                models = [m.get("id") for m in result["data"] if "id" in m]
                return models
            return []

        except requests.RequestException as e:
            logger.error(f"Error fetching models from LiteLLM: {e}")
            raise

    def get_health(self) -> bool:
        """Check health of LiteLLM service.

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            response = requests.get(
                f"{self.base_url}/health",
                headers=self._headers(),
                timeout=self.timeout,
            )
            return response.status_code == 200

        except requests.RequestException:
            logger.debug("LiteLLM health check failed")
            return False


def call_llm(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    base_url: str = "http://localhost:8001",
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Convenience function for one-off LiteLLM API calls.

    Args:
        model: Model name (e.g., 'claude-opus-4.5')
        messages: List of message dicts
        temperature: Sampling temperature (default: 0.7)
        base_url: LiteLLM service URL (default: localhost:8001)
        max_tokens: Maximum tokens in response (optional)

    Returns:
        Response dict from LiteLLM

    Raises:
        requests.RequestException: On timeout or connection error
    """
    client = LiteLLMClient(base_url=base_url, timeout=30)
    return client.call_llm(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
