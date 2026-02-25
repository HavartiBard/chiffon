"""Client for local llama.cpp inference server."""

import os
from typing import Optional

import httpx


class LlamaClient:
    """HTTP client wrapper for llama.cpp's OpenAI-compatible API.

    Connects to a running llama.cpp server and provides two operations:
    - generate(): submit a prompt and receive generated text
    - health_check(): verify the server is reachable (never raises)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "local-model",
    ) -> None:
        """Initialize the Llama client.

        Args:
            base_url: Base URL for the llama.cpp server.  When omitted the
                      ``LLAMA_SERVER_URL`` environment variable is checked;
                      if that is also absent the default
                      ``http://localhost:8000`` is used.
            model: Model name to pass along with requests (default: ``local-model``).
        """
        self.base_url = base_url or os.getenv(
            "LLAMA_SERVER_URL", "http://localhost:8000"
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
        """Format a raw prompt string into a llama.cpp /completion payload.

        Args:
            prompt: Raw prompt text to send to the model.
            max_tokens: Maximum number of tokens to generate (default: 4096).
            temperature: Sampling temperature (default: 0.7).

        Returns:
            Dict ready to JSON-encode and POST to ``/completion``.
        """
        return {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
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
        """Generate text from a prompt using the local llama.cpp server.

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
                f"{self.base_url}/completion",
                json=payload,
            )
            response.raise_for_status()
            return response.json().get("content", "")
        except httpx.HTTPError as exc:
            raise ValueError(f"Failed to call llama.cpp: {exc}") from exc

    def health_check(self) -> bool:
        """Check whether the llama.cpp server is reachable.

        This method never raises; any exception is caught and treated as an
        unhealthy server.

        Returns:
            ``True`` if the server responds with HTTP 200, ``False`` otherwise.
        """
        try:
            response = self.client.get(f"{self.base_url}/health", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def __del__(self) -> None:
        """Close the underlying HTTP client when the object is garbage-collected."""
        try:
            self.client.close()
        except Exception:
            pass
