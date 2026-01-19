"""Tests for LiteLLM client wrapper."""

import json
from unittest.mock import Mock, patch, MagicMock

import pytest
import requests

from src.common.litellm_client import LiteLLMClient, call_llm


class TestLiteLLMClient:
    """Test suite for LiteLLMClient class."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return LiteLLMClient(base_url="http://localhost:8001", timeout=30)

    def test_init(self):
        """Test client initialization."""
        client = LiteLLMClient(base_url="http://example.com", timeout=60)
        assert client.base_url == "http://example.com"
        assert client.timeout == 60

    def test_init_strips_trailing_slash(self):
        """Test that base_url is normalized."""
        client = LiteLLMClient(base_url="http://example.com/")
        assert client.base_url == "http://example.com"

    def test_headers_without_master_key(self):
        """Test headers without master key."""
        with patch.dict("os.environ", {}, clear=True):
            client = LiteLLMClient()
            headers = client._headers()
            assert "Content-Type" in headers
            assert headers["Content-Type"] == "application/json"
            assert "Authorization" not in headers

    def test_headers_with_master_key(self):
        """Test headers with master key."""
        with patch.dict("os.environ", {"LITELLM_MASTER_KEY": "test-key-123"}):
            client = LiteLLMClient()
            headers = client._headers()
            assert headers["Authorization"] == "Bearer test-key-123"

    @patch("src.common.litellm_client.requests.post")
    def test_call_llm_success(self, mock_post):
        """Test successful LLM call."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello, this is a test response"}}]
        }
        mock_post.return_value = mock_response

        client = LiteLLMClient()
        messages = [{"role": "user", "content": "Say hello"}]
        result = client.call_llm("claude-opus-4.5", messages)

        assert result["choices"][0]["message"]["content"] == "Hello, this is a test response"
        mock_post.assert_called_once()

    @patch("src.common.litellm_client.requests.post")
    def test_call_llm_with_temperature(self, mock_post):
        """Test LLM call with custom temperature."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "test"}}]}
        mock_post.return_value = mock_response

        client = LiteLLMClient()
        messages = [{"role": "user", "content": "test"}]
        result = client.call_llm("claude-opus-4.5", messages, temperature=0.3)

        # Verify temperature was passed in payload
        call_args = mock_post.call_args
        assert call_args[1]["json"]["temperature"] == 0.3

    @patch("src.common.litellm_client.requests.post")
    def test_call_llm_with_max_tokens(self, mock_post):
        """Test LLM call with max_tokens."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "test"}}]}
        mock_post.return_value = mock_response

        client = LiteLLMClient()
        messages = [{"role": "user", "content": "test"}]
        result = client.call_llm("claude-opus-4.5", messages, max_tokens=100)

        # Verify max_tokens was passed
        call_args = mock_post.call_args
        assert call_args[1]["json"]["max_tokens"] == 100

    @patch("src.common.litellm_client.requests.post")
    def test_call_llm_timeout(self, mock_post):
        """Test LLM call timeout handling."""
        mock_post.side_effect = requests.Timeout("Request timeout")

        client = LiteLLMClient()
        messages = [{"role": "user", "content": "test"}]

        with pytest.raises(requests.RequestException):
            client.call_llm("claude-opus-4.5", messages)

    @patch("src.common.litellm_client.requests.post")
    def test_call_llm_connection_error(self, mock_post):
        """Test LLM call connection error."""
        mock_post.side_effect = requests.ConnectionError("Connection failed")

        client = LiteLLMClient()
        messages = [{"role": "user", "content": "test"}]

        with pytest.raises(requests.RequestException):
            client.call_llm("claude-opus-4.5", messages)

    @patch("src.common.litellm_client.requests.post")
    def test_call_llm_http_error(self, mock_post):
        """Test LLM call HTTP error response."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.HTTPError("Unauthorized")
        mock_post.return_value = mock_response

        client = LiteLLMClient()
        messages = [{"role": "user", "content": "test"}]

        with pytest.raises(requests.RequestException):
            client.call_llm("claude-opus-4.5", messages)

    @patch("src.common.litellm_client.requests.get")
    def test_get_available_models_success(self, mock_get):
        """Test getting available models."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "claude-opus-4.5"},
                {"id": "gpt-4-turbo"},
                {"id": "ollama/neural-chat"},
            ]
        }
        mock_get.return_value = mock_response

        client = LiteLLMClient()
        models = client.get_available_models()

        assert models == ["claude-opus-4.5", "gpt-4-turbo", "ollama/neural-chat"]
        mock_get.assert_called_once()

    @patch("src.common.litellm_client.requests.get")
    def test_get_available_models_empty(self, mock_get):
        """Test getting available models when list is empty."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_get.return_value = mock_response

        client = LiteLLMClient()
        models = client.get_available_models()

        assert models == []

    @patch("src.common.litellm_client.requests.get")
    def test_get_available_models_malformed_response(self, mock_get):
        """Test handling of malformed model response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        client = LiteLLMClient()
        models = client.get_available_models()

        assert models == []

    @patch("src.common.litellm_client.requests.get")
    def test_get_available_models_error(self, mock_get):
        """Test error handling when fetching models."""
        mock_get.side_effect = requests.ConnectionError("Connection failed")

        client = LiteLLMClient()

        with pytest.raises(requests.RequestException):
            client.get_available_models()

    @patch("src.common.litellm_client.requests.get")
    def test_get_health_success(self, mock_get):
        """Test health check success."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        client = LiteLLMClient()
        health = client.get_health()

        assert health is True
        mock_get.assert_called_once()

    @patch("src.common.litellm_client.requests.get")
    def test_get_health_failure(self, mock_get):
        """Test health check failure."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        client = LiteLLMClient()
        health = client.get_health()

        assert health is False

    @patch("src.common.litellm_client.requests.get")
    def test_get_health_timeout(self, mock_get):
        """Test health check timeout."""
        mock_get.side_effect = requests.Timeout("Timeout")

        client = LiteLLMClient()
        health = client.get_health()

        assert health is False

    @patch("src.common.litellm_client.LiteLLMClient.call_llm")
    def test_call_llm_function(self, mock_client_call):
        """Test convenience function call_llm."""
        mock_client_call.return_value = {"choices": [{"message": {"content": "response"}}]}

        messages = [{"role": "user", "content": "test"}]
        result = call_llm("claude-opus-4.5", messages)

        assert result["choices"][0]["message"]["content"] == "response"
        mock_client_call.assert_called_once()

    @patch("src.common.litellm_client.LiteLLMClient.call_llm")
    def test_call_llm_function_with_params(self, mock_client_call):
        """Test convenience function with custom parameters."""
        mock_client_call.return_value = {"choices": [{"message": {"content": "response"}}]}

        messages = [{"role": "user", "content": "test"}]
        result = call_llm(
            "claude-opus-4.5",
            messages,
            temperature=0.5,
            base_url="http://custom.com",
            max_tokens=150,
        )

        # Verify parameters were passed correctly
        call_args = mock_client_call.call_args
        assert call_args[1]["temperature"] == 0.5
        assert call_args[1]["max_tokens"] == 150
