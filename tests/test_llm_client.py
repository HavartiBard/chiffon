"""Tests for LlamaClient - HTTP client for llama.cpp inference server."""
import os
import pytest
from unittest.mock import MagicMock, patch
import httpx

from chiffon.executor.llm_client import LlamaClient


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


def test_init_with_default_url():
    """LlamaClient defaults to localhost:8000 when no URL is provided and env is unset."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("LLAMA_SERVER_URL", None)
        client = LlamaClient()
    assert "localhost:8000" in client.base_url or "127.0.0.1:8000" in client.base_url


def test_init_with_custom_url():
    """LlamaClient accepts an explicit base_url."""
    client = LlamaClient(base_url="http://192.168.20.154:8000")
    assert "192.168.20.154:8000" in client.base_url


def test_init_reads_env_var():
    """LlamaClient reads LLAMA_SERVER_URL env var when no base_url is passed."""
    with patch.dict(os.environ, {"LLAMA_SERVER_URL": "http://gpu-box:9000"}):
        client = LlamaClient()
    assert client.base_url == "http://gpu-box:9000"


def test_init_explicit_url_overrides_env():
    """Explicit base_url takes precedence over environment variable."""
    with patch.dict(os.environ, {"LLAMA_SERVER_URL": "http://gpu-box:9000"}):
        client = LlamaClient(base_url="http://override:8000")
    assert client.base_url == "http://override:8000"


def test_init_default_model():
    """LlamaClient default model is 'local-model'."""
    client = LlamaClient()
    assert client.model == "local-model"


def test_init_custom_model():
    """LlamaClient accepts a custom model name."""
    client = LlamaClient(model="neural-chat-7b")
    assert client.model == "neural-chat-7b"


# ---------------------------------------------------------------------------
# _format_prompt tests
# ---------------------------------------------------------------------------


def test_formats_prompt_for_llama():
    """_format_prompt returns a dict with a 'prompt' key."""
    client = LlamaClient()
    result = client._format_prompt("This is a test prompt")
    assert isinstance(result, dict)
    assert "prompt" in result
    assert result["prompt"] == "This is a test prompt"


def test_format_prompt_includes_required_params():
    """_format_prompt includes n_predict, temperature, top_p, repeat_penalty, stop."""
    client = LlamaClient()
    result = client._format_prompt("hello")
    assert "n_predict" in result
    assert "temperature" in result
    assert "top_p" in result
    assert "repeat_penalty" in result
    assert "stop" in result


def test_format_prompt_stop_tokens():
    """_format_prompt stop tokens include '## ' and '\\n---'."""
    client = LlamaClient()
    result = client._format_prompt("hello")
    assert "## " in result["stop"]
    assert "\n---" in result["stop"]


# ---------------------------------------------------------------------------
# generate() tests — mock HTTP
# ---------------------------------------------------------------------------


def test_generate_posts_to_completion_endpoint():
    """generate() POSTs to /completion and returns the 'content' field."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": "Generated text here"}
    mock_response.raise_for_status.return_value = None

    with patch.object(client.client, "post", return_value=mock_response) as mock_post:
        result = client.generate("My prompt")

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "http://test-llama:8000/completion"
    assert result == "Generated text here"


def test_generate_passes_max_tokens():
    """generate() forwards max_tokens as n_predict in the request body."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": "ok"}
    mock_response.raise_for_status.return_value = None

    with patch.object(client.client, "post", return_value=mock_response) as mock_post:
        client.generate("prompt", max_tokens=512)

    payload = mock_post.call_args[1]["json"]
    assert payload["n_predict"] == 512


def test_generate_passes_temperature():
    """generate() forwards temperature in the request body."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": "ok"}
    mock_response.raise_for_status.return_value = None

    with patch.object(client.client, "post", return_value=mock_response) as mock_post:
        client.generate("prompt", temperature=0.2)

    payload = mock_post.call_args[1]["json"]
    assert payload["temperature"] == 0.2


def test_generate_default_parameters():
    """generate() uses max_tokens=4096 and temperature=0.7 by default."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": "ok"}
    mock_response.raise_for_status.return_value = None

    with patch.object(client.client, "post", return_value=mock_response) as mock_post:
        client.generate("prompt")

    payload = mock_post.call_args[1]["json"]
    assert payload["n_predict"] == 4096
    assert payload["temperature"] == 0.7


def test_generate_includes_stop_tokens():
    """generate() includes stop tokens in the request payload."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": "ok"}
    mock_response.raise_for_status.return_value = None

    with patch.object(client.client, "post", return_value=mock_response) as mock_post:
        client.generate("prompt")

    payload = mock_post.call_args[1]["json"]
    assert "## " in payload["stop"]
    assert "\n---" in payload["stop"]


def test_generate_returns_string():
    """generate() always returns a string."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": "some output"}
    mock_response.raise_for_status.return_value = None

    with patch.object(client.client, "post", return_value=mock_response):
        result = client.generate("prompt")

    assert isinstance(result, str)


def test_generate_raises_on_http_error():
    """generate() raises ValueError when the HTTP call fails."""
    client = LlamaClient(base_url="http://test-llama:8000")

    with patch.object(client.client, "post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(ValueError, match="Failed to call llama.cpp"):
            client.generate("prompt")


def test_generate_raises_on_bad_status():
    """generate() raises ValueError when the server returns a non-2xx status."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )

    with patch.object(client.client, "post", return_value=mock_response):
        with pytest.raises(ValueError, match="Failed to call llama.cpp"):
            client.generate("prompt")


def test_generate_method_exists_and_callable():
    """generate() is a callable method on LlamaClient."""
    client = LlamaClient()
    assert hasattr(client, "generate")
    assert callable(client.generate)


# ---------------------------------------------------------------------------
# health_check() tests — mock HTTP
# ---------------------------------------------------------------------------


def test_health_check_returns_true_on_200():
    """health_check() returns True when server responds 200."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch.object(client.client, "get", return_value=mock_response):
        result = client.health_check()

    assert result is True


def test_health_check_returns_false_on_non_200():
    """health_check() returns False when server responds with non-200 status."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.status_code = 503

    with patch.object(client.client, "get", return_value=mock_response):
        result = client.health_check()

    assert result is False


def test_health_check_returns_false_on_connection_error():
    """health_check() returns False (no exception) when server is unreachable."""
    client = LlamaClient(base_url="http://test-llama:8000")

    with patch.object(client.client, "get", side_effect=httpx.ConnectError("refused")):
        result = client.health_check()

    assert result is False


def test_health_check_returns_false_on_timeout():
    """health_check() returns False (no exception) on timeout."""
    client = LlamaClient(base_url="http://test-llama:8000")

    with patch.object(client.client, "get", side_effect=httpx.TimeoutException("timed out")):
        result = client.health_check()

    assert result is False


def test_health_check_calls_correct_endpoint():
    """health_check() GETs the /health endpoint."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch.object(client.client, "get", return_value=mock_response) as mock_get:
        client.health_check()

    mock_get.assert_called_once()
    url_called = mock_get.call_args[0][0]
    assert url_called == "http://test-llama:8000/health"


def test_health_check_never_raises():
    """health_check() must never raise any exception."""
    client = LlamaClient(base_url="http://test-llama:8000")

    with patch.object(client.client, "get", side_effect=Exception("unexpected error")):
        result = client.health_check()

    assert result is False


def test_health_check_uses_fast_timeout():
    """health_check() passes timeout=5.0 to the GET call, not the 5-minute client default."""
    client = LlamaClient(base_url="http://test-llama:8000")

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch.object(client.client, "get", return_value=mock_response) as mock_get:
        client.health_check()

    _, kwargs = mock_get.call_args
    assert kwargs.get("timeout") == 5.0
