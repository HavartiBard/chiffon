"""Client for LM Studio inference server (OpenAI-compatible API)."""

import os
from typing import Optional

import httpx


class LlamaClient:
    """HTTP client wrapper for LM Studio's OpenAI-compatible API.

    Connects to a running LM Studio server and provides two operations:
    - generate(): submit a prompt and receive generated text
    - health_check(): verify the server is reachable (never raises)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "local-model",
    ) -> None:
        """Initialize the LM Studio client.

        Args:
            base_url: Base URL for the LM Studio server.  When omitted the
                      ``LMSTUDIO_URL`` environment variable is checked;
                      if that is also absent the default
                      ``http://spraycheese.lab.klsll.com:1234`` is used.
            model: Model name to pass along with requests (default: ``local-model``).
        """
        self.base_url = base_url or os.getenv(
            "LMSTUDIO_URL", "http://spraycheese.lab.klsll.com:1234"
        )
        self.model = model
        # 5-minute timeout covers long generation tasks
        self.client = httpx.Client(timeout=300.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_prompt(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> dict:
        """Format a raw prompt string into an OpenAI-compatible chat completions payload.

        Args:
            prompt: Raw prompt text to send to the model.
            max_tokens: Maximum number of tokens to generate (default: 4096).
            temperature: Sampling temperature (default: 0.7).

        Returns:
            Dict ready to JSON-encode and POST to ``/v1/chat/completions``.
        """
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
            "stop": ["## ", "\n---"],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Generate text from a prompt using the LM Studio server.

        Args:
            prompt: Input prompt text.
            max_tokens: Maximum number of tokens to generate (default: 4096).
            temperature: Sampling temperature (default: 0.7).

        Returns:
            Generated text as a plain string.

        Raises:
            ValueError: If the server is unreachable or returns an error status.
        """
        payload = self._format_prompt(prompt, max_tokens, temperature)

        try:
            response = self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise ValueError(f"Failed to call llama.cpp: {exc}") from exc

    def health_check(self) -> bool:
        """Check whether the LM Studio server is reachable.

        This method never raises; any exception is caught and treated as an
        unhealthy server.

        Returns:
            ``True`` if the server responds with HTTP 200, ``False`` otherwise.
        """
        try:
            response = self.client.get(f"{self.base_url}/v1/models", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def __del__(self) -> None:
        """Close the underlying HTTP client when the object is garbage-collected."""
        try:
            self.client.close()
        except Exception:
            pass
