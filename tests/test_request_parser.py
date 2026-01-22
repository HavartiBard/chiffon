"""Comprehensive tests for request parser (RequestDecomposer).

Tests cover:
- Request decomposition (simple and complex)
- Complexity assessment
- Ambiguity detection
- Out-of-scope detection
- Error handling
"""

import json
from unittest.mock import Mock

import pytest

from src.common.models import (
    DecomposedRequest,
    RequestParsingConfig,
)
from src.orchestrator.nlu import RequestDecomposer

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_litellm_client():
    """Fixture returning mock LiteLLMClient."""
    client = Mock()
    return client


@pytest.fixture
def config():
    """Fixture returning default RequestParsingConfig."""
    return RequestParsingConfig()


@pytest.fixture
def decomposer(mock_litellm_client, config):
    """Fixture creating RequestDecomposer with mock client."""
    return RequestDecomposer(mock_litellm_client, config)


@pytest.fixture
def valid_decomposition_response():
    """Fixture with example JSON response structure."""
    return {
        "subtasks": [
            {
                "order": 1,
                "name": "Deploy Kuma Uptime",
                "intent": "deploy_kuma",
                "confidence": 0.95,
                "parameters": {"service": "kuma"},
            },
            {
                "order": 2,
                "name": "Add existing portals to config",
                "intent": "add_config",
                "confidence": 0.8,
                "parameters": {"type": "portal_config"},
            },
        ],
        "ambiguities": [],
        "out_of_scope": [],
    }


# ============================================================================
# Test Class 1: TestRequestDecomposition
# ============================================================================


class TestRequestDecomposition:
    """Tests for basic request decomposition functionality."""

    @pytest.mark.asyncio
    async def test_decompose_simple_request(self, decomposer, mock_litellm_client):
        """Test decomposing simple single-intent request."""
        # Arrange
        request = "Deploy Kuma"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy Kuma Uptime",
                    "intent": "deploy_kuma",
                    "confidence": 0.95,
                }
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert isinstance(result, DecomposedRequest)
        assert result.original_request == request
        assert len(result.subtasks) == 1
        assert result.subtasks[0].intent == "deploy_kuma"
        assert result.subtasks[0].confidence == 0.95
        assert result.complexity_level == "simple"
        assert result.decomposer_model == "claude"

    @pytest.mark.asyncio
    async def test_decompose_complex_request(self, decomposer, mock_litellm_client):
        """Test decomposing complex multi-step request."""
        # Arrange
        request = "Deploy Kuma and add portals and research alternatives"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy Kuma",
                    "intent": "deploy_kuma",
                    "confidence": 0.95,
                },
                {
                    "order": 2,
                    "name": "Add portals to config",
                    "intent": "add_config",
                    "confidence": 0.8,
                },
                {
                    "order": 3,
                    "name": "Research Kuma alternatives",
                    "intent": "research",
                    "confidence": 0.7,
                },
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert len(result.subtasks) == 3
        assert result.complexity_level == "complex"  # Has research intent
        assert result.subtasks[2].intent == "research"

    @pytest.mark.asyncio
    async def test_decompose_with_ambiguities(self, decomposer, mock_litellm_client):
        """Test request with detected ambiguities."""
        # Arrange
        request = "Set up something"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Set up unknown thing",
                    "intent": "deploy_service",
                    "confidence": 0.3,
                }
            ],
            "ambiguities": [
                "Unclear what 'something' refers to",
                "No specific service mentioned",
            ],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert len(result.ambiguities) == 2
        assert "Unclear what" in result.ambiguities[0]

    @pytest.mark.asyncio
    async def test_decompose_with_out_of_scope(self, decomposer, mock_litellm_client):
        """Test request with out-of-scope items."""
        # Arrange
        request = "Write a PhD thesis and deploy Kuma"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy Kuma",
                    "intent": "deploy_kuma",
                    "confidence": 0.9,
                }
            ],
            "ambiguities": [],
            "out_of_scope": ["PhD thesis writing"],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert len(result.out_of_scope) == 1
        assert "PhD" in result.out_of_scope[0]

    @pytest.mark.asyncio
    async def test_confidence_scoring(self, decomposer, mock_litellm_client):
        """Test that subtasks have valid confidence scores."""
        # Arrange
        request = "Deploy and configure"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy",
                    "intent": "deploy_kuma",
                    "confidence": 0.95,
                },
                {
                    "order": 2,
                    "name": "Configure",
                    "intent": "add_config",
                    "confidence": 0.6,
                },
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        for st in result.subtasks:
            assert 0.0 <= st.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_subtask_parameters(self, decomposer, mock_litellm_client):
        """Test that subtasks can have optional parameters."""
        # Arrange
        request = "Deploy Kuma with custom settings"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy Kuma",
                    "intent": "deploy_kuma",
                    "confidence": 0.9,
                    "parameters": {"env": "production", "replicas": 3},
                }
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert result.subtasks[0].parameters is not None
        assert result.subtasks[0].parameters["env"] == "production"


# ============================================================================
# Test Class 2: TestComplexityAssessment
# ============================================================================


class TestComplexityAssessment:
    """Tests for complexity assessment logic."""

    @pytest.mark.asyncio
    async def test_simple_complexity(self, decomposer, mock_litellm_client):
        """Test that 1-2 simple subtasks marked as simple."""
        # Arrange
        request = "Deploy Kuma"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy Kuma",
                    "intent": "deploy_kuma",
                    "confidence": 0.95,
                }
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert result.complexity_level == "simple"

    @pytest.mark.asyncio
    async def test_medium_complexity(self, decomposer, mock_litellm_client):
        """Test that 3+ subtasks marked as medium."""
        # Arrange
        request = "Deploy, configure, and monitor"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy",
                    "intent": "deploy_kuma",
                    "confidence": 0.9,
                },
                {
                    "order": 2,
                    "name": "Configure",
                    "intent": "add_config",
                    "confidence": 0.8,
                },
                {
                    "order": 3,
                    "name": "Monitor",
                    "intent": "check_status",
                    "confidence": 0.8,
                },
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert result.complexity_level == "medium"

    @pytest.mark.asyncio
    async def test_complex_complexity(self, decomposer, mock_litellm_client):
        """Test that research/code_gen intents marked as complex."""
        # Arrange
        request = "Deploy and research alternatives"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy",
                    "intent": "deploy_kuma",
                    "confidence": 0.9,
                },
                {
                    "order": 2,
                    "name": "Research",
                    "intent": "research",
                    "confidence": 0.7,
                },
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert result.complexity_level == "complex"


# ============================================================================
# Test Class 3: TestAmbiguityDetection
# ============================================================================


class TestAmbiguityDetection:
    """Tests for ambiguity detection."""

    @pytest.mark.asyncio
    async def test_vague_request_flagged(self, decomposer, mock_litellm_client):
        """Test that vague requests are flagged as ambiguous."""
        # Arrange
        request = "Do something with the system"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Unknown action",
                    "intent": "unknown",
                    "confidence": 0.2,
                }
            ],
            "ambiguities": ["Unclear what action to perform"],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert len(result.ambiguities) > 0

    @pytest.mark.asyncio
    async def test_clear_request_no_ambiguities(self, decomposer, mock_litellm_client):
        """Test that clear requests have no ambiguities."""
        # Arrange
        request = "Deploy Kuma"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy Kuma Uptime",
                    "intent": "deploy_kuma",
                    "confidence": 0.95,
                }
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert len(result.ambiguities) == 0

    @pytest.mark.asyncio
    async def test_conflicting_parameters(self, decomposer, mock_litellm_client):
        """Test conflicting parameter detection."""
        # Arrange
        request = "Deploy Kuma on staging and production"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy to both",
                    "intent": "deploy_kuma",
                    "confidence": 0.6,
                }
            ],
            "ambiguities": ["Unclear whether to deploy to staging, production, or both"],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert len(result.ambiguities) > 0


# ============================================================================
# Test Class 4: TestOutOfScopeDetection
# ============================================================================


class TestOutOfScopeDetection:
    """Tests for out-of-scope request detection."""

    @pytest.mark.asyncio
    async def test_unknown_agent_type(self, decomposer, mock_litellm_client):
        """Test that unknown agent type is marked out-of-scope."""
        # Arrange
        request = "Train a machine learning model"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Train ML model",
                    "intent": "ml_training",
                    "confidence": 0.5,
                }
            ],
            "ambiguities": [],
            "out_of_scope": ["ML model training not supported"],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert len(result.out_of_scope) > 0

    @pytest.mark.asyncio
    async def test_known_agents_in_scope(self, decomposer, mock_litellm_client):
        """Test that known agents are in scope."""
        # Arrange
        request = "Deploy Kuma and check GPU status"
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy Kuma",
                    "intent": "deploy_kuma",
                    "confidence": 0.95,
                },
                {
                    "order": 2,
                    "name": "Check GPU status",
                    "intent": "gpu_status",
                    "confidence": 0.9,
                },
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose(request)

        # Assert
        assert len(result.out_of_scope) == 0


# ============================================================================
# Test Class 5: TestErrorHandling
# ============================================================================


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_empty_request(self, decomposer):
        """Test that empty request raises ValueError."""
        # Act & Assert
        with pytest.raises(ValueError, match="Request cannot be empty"):
            await decomposer.decompose("")

    @pytest.mark.asyncio
    async def test_none_request(self, decomposer):
        """Test that None request raises ValueError."""
        # Act & Assert
        with pytest.raises(ValueError, match="Request cannot be empty"):
            await decomposer.decompose(None)

    @pytest.mark.asyncio
    async def test_invalid_json_from_llm(self, decomposer, mock_litellm_client):
        """Test handling of invalid JSON from LLM."""
        # Arrange
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": "This is not valid JSON"}}]
        }

        # Act & Assert
        with pytest.raises(ValueError, match="Failed to parse"):
            await decomposer.decompose("Deploy Kuma")

    @pytest.mark.asyncio
    async def test_llm_timeout(self, decomposer, mock_litellm_client):
        """Test handling of LLM timeout."""
        # Arrange
        mock_litellm_client.call_llm.side_effect = Exception("Request timed out")

        # Act & Assert
        with pytest.raises(Exception, match="timed out"):
            await decomposer.decompose("Deploy Kuma")

    @pytest.mark.asyncio
    async def test_llm_api_error(self, decomposer, mock_litellm_client):
        """Test handling of LLM API error."""
        # Arrange
        mock_litellm_client.call_llm.side_effect = Exception("API error: 500 Server Error")

        # Act & Assert
        with pytest.raises(Exception, match="API error"):
            await decomposer.decompose("Deploy Kuma")

    @pytest.mark.asyncio
    async def test_markdown_code_block_parsing(self, decomposer, mock_litellm_client):
        """Test that markdown code blocks are stripped from JSON."""
        # Arrange
        response_data = {
            "subtasks": [
                {
                    "order": 1,
                    "name": "Deploy",
                    "intent": "deploy_kuma",
                    "confidence": 0.95,
                }
            ],
            "ambiguities": [],
            "out_of_scope": [],
        }
        markdown_response = f"```json\n{json.dumps(response_data)}\n```"
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": markdown_response}}]
        }

        # Act
        result = await decomposer.decompose("Deploy Kuma")

        # Assert
        assert isinstance(result, DecomposedRequest)
        assert len(result.subtasks) == 1

    @pytest.mark.asyncio
    async def test_empty_subtasks_list(self, decomposer, mock_litellm_client):
        """Test handling of empty subtasks list."""
        # Arrange
        response_data = {
            "subtasks": [],
            "ambiguities": [],
            "out_of_scope": [],
        }
        mock_litellm_client.call_llm.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        # Act
        result = await decomposer.decompose("Something weird")

        # Assert
        assert len(result.subtasks) == 0
        assert result.complexity_level == "simple"

    @pytest.mark.asyncio
    async def test_missing_response_choices(self, decomposer, mock_litellm_client):
        """Test handling of malformed LLM response."""
        # Arrange
        mock_litellm_client.call_llm.return_value = {"data": "invalid"}

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid LLM response"):
            await decomposer.decompose("Deploy Kuma")
