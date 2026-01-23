"""Tests for TaskMapper and CacheManager.

Tests cover:
- MappingResult validation
- CacheManager operations (lookup, cache, embeddings)
- TaskMapper exact match
- TaskMapper cached match
- TaskMapper semantic match
- TaskMapper no-match handling
- TaskMapper integration (full workflow)
"""

import hashlib
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pytest

from src.agents.infra_agent.cache_manager import CacheManager
from src.agents.infra_agent.task_mapper import (
    MappingResult,
    PlaybookMetadata,
    TaskMapper,
)
from src.common.models import PlaybookMapping

# --- Fixtures ---


@pytest.fixture
def sample_playbook_catalog():
    """Sample playbook catalog with varied services."""
    return [
        PlaybookMetadata(
            path="/ansible/kuma-deploy.yml",
            filename="kuma-deploy.yml",
            service="kuma",
            description="Deploy Kuma service mesh",
            required_vars=["kuma_version"],
            tags=["service-mesh", "networking"],
        ),
        PlaybookMetadata(
            path="/ansible/portainer-deploy.yml",
            filename="portainer-deploy.yml",
            service="portainer",
            description="Deploy Portainer container management",
            required_vars=["portainer_port"],
            tags=["containers", "management"],
        ),
        PlaybookMetadata(
            path="/ansible/monitoring-setup.yml",
            filename="monitoring-setup.yml",
            service="prometheus",
            description="Setup Prometheus and Grafana monitoring",
            required_vars=["prometheus_version", "grafana_version"],
            tags=["monitoring", "observability"],
        ),
    ]


@pytest.fixture
def mock_cache_manager():
    """Mock CacheManager for unit tests."""
    mock = AsyncMock(spec=CacheManager)
    mock.lookup_cached_mapping = AsyncMock(return_value=None)
    mock.cache_mapping = AsyncMock()
    mock.get_all_cached_embeddings = AsyncMock(return_value=[])
    return mock


@pytest.fixture
async def in_memory_db_session():
    """SQLite in-memory database session for integration tests."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.common.database import Base

    # Create in-memory SQLite database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Yield session
    async with async_session() as session:
        yield session

    # Cleanup
    await engine.dispose()


# --- Test MappingResult ---


class TestMappingResult:
    """Tests for MappingResult Pydantic model."""

    def test_valid_mapping_result(self):
        """Test valid MappingResult instantiation."""
        result = MappingResult(
            playbook_path="/ansible/kuma-deploy.yml",
            confidence=0.95,
            method="semantic",
            alternatives=[{"playbook_path": "/ansible/portainer-deploy.yml", "score": 0.82}],
        )
        assert result.playbook_path == "/ansible/kuma-deploy.yml"
        assert result.confidence == 0.95
        assert result.method == "semantic"
        assert len(result.alternatives) == 1

    def test_alternatives_can_be_empty(self):
        """Test alternatives list can be empty."""
        result = MappingResult(
            playbook_path="/ansible/kuma-deploy.yml",
            confidence=1.0,
            method="exact",
            alternatives=[],
        )
        assert result.alternatives == []

    def test_no_match_has_suggestion(self):
        """Test no-match result includes suggestion."""
        result = MappingResult(
            playbook_path=None,
            confidence=0.0,
            method="none",
            alternatives=[],
            suggestion="No matching playbook found. Options: ...",
        )
        assert result.playbook_path is None
        assert result.method == "none"
        assert result.suggestion is not None

    def test_confidence_bounds(self):
        """Test confidence is bounded between 0.0 and 1.0."""
        # Valid confidence
        result = MappingResult(playbook_path="/test.yml", confidence=0.85, method="semantic")
        assert result.confidence == 0.85

        # Invalid confidence should raise validation error
        with pytest.raises(ValueError):
            MappingResult(playbook_path="/test.yml", confidence=1.5, method="semantic")


# --- Test CacheManager ---


class TestCacheManager:
    """Tests for CacheManager operations."""

    @pytest.mark.asyncio
    async def test_lookup_nonexistent_returns_none(self, in_memory_db_session):
        """Test looking up non-existent intent returns None."""
        cache_manager = CacheManager(in_memory_db_session)
        result = await cache_manager.lookup_cached_mapping("Deploy Kuma")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_and_lookup(self, in_memory_db_session):
        """Test storing and retrieving a mapping."""
        cache_manager = CacheManager(in_memory_db_session)

        # Cache a mapping
        await cache_manager.cache_mapping(
            intent="Deploy Kuma",
            playbook_path="/ansible/kuma-deploy.yml",
            confidence=0.92,
            method="semantic",
        )

        # Look it up
        result = await cache_manager.lookup_cached_mapping("Deploy Kuma")
        assert result is not None
        assert result.playbook_path == "/ansible/kuma-deploy.yml"
        assert result.confidence == 0.92
        assert result.method == "semantic"

    @pytest.mark.asyncio
    async def test_intent_normalization(self, in_memory_db_session):
        """Test intents are normalized (case-insensitive)."""
        cache_manager = CacheManager(in_memory_db_session)

        # Cache with uppercase
        await cache_manager.cache_mapping(
            intent="Deploy KUMA",
            playbook_path="/ansible/kuma-deploy.yml",
            confidence=0.92,
            method="semantic",
        )

        # Look up with lowercase
        result = await cache_manager.lookup_cached_mapping("deploy kuma")
        assert result is not None
        assert result.playbook_path == "/ansible/kuma-deploy.yml"

    @pytest.mark.asyncio
    async def test_use_count_incremented(self, in_memory_db_session):
        """Test use_count increments on each lookup."""
        cache_manager = CacheManager(in_memory_db_session)

        # Cache a mapping
        await cache_manager.cache_mapping(
            intent="Deploy Kuma",
            playbook_path="/ansible/kuma-deploy.yml",
            confidence=0.92,
            method="semantic",
        )

        # Look up twice
        result1 = await cache_manager.lookup_cached_mapping("Deploy Kuma")
        result2 = await cache_manager.lookup_cached_mapping("Deploy Kuma")

        # use_count should be 3 (initial=1, +2 lookups)
        assert result2.use_count == 3

    @pytest.mark.asyncio
    async def test_confidence_threshold(self, in_memory_db_session):
        """Test only mappings with confidence >= 0.85 are returned."""
        cache_manager = CacheManager(in_memory_db_session)

        # Cache low-confidence mapping
        await cache_manager.cache_mapping(
            intent="Deploy Something",
            playbook_path="/ansible/something.yml",
            confidence=0.70,
            method="semantic",
        )

        # Should not be returned (below threshold)
        result = await cache_manager.lookup_cached_mapping("Deploy Something")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_cached_embeddings(self, in_memory_db_session):
        """Test retrieving all cached embeddings."""
        cache_manager = CacheManager(in_memory_db_session)

        # Cache with embedding
        embedding = [0.1, 0.2, 0.3]
        await cache_manager.cache_mapping(
            intent="Deploy Kuma",
            playbook_path="/ansible/kuma-deploy.yml",
            confidence=0.92,
            method="semantic",
            embedding=embedding,
        )

        # Retrieve embeddings
        embeddings = await cache_manager.get_all_cached_embeddings()
        assert len(embeddings) == 1
        assert embeddings[0][0] == "/ansible/kuma-deploy.yml"
        assert embeddings[0][1] == embedding


# --- Test TaskMapper Exact Match ---


class TestTaskMapperExactMatch:
    """Tests for TaskMapper exact matching."""

    @pytest.mark.asyncio
    async def test_exact_match_service_in_intent(self, mock_cache_manager, sample_playbook_catalog):
        """Test exact match when service name appears in intent."""
        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        result = await mapper.map_task_to_playbook("Deploy Kuma")
        assert result.playbook_path == "/ansible/kuma-deploy.yml"
        assert result.confidence == 1.0
        assert result.method == "exact"

    @pytest.mark.asyncio
    async def test_exact_match_case_insensitive(self, mock_cache_manager, sample_playbook_catalog):
        """Test exact match is case-insensitive."""
        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        result = await mapper.map_task_to_playbook("deploy KUMA")
        assert result.playbook_path == "/ansible/kuma-deploy.yml"
        assert result.method == "exact"

    @pytest.mark.asyncio
    async def test_exact_match_no_service(self, mock_cache_manager):
        """Test playbook without service field is skipped."""
        catalog = [
            PlaybookMetadata(
                path="/ansible/no-service.yml",
                filename="no-service.yml",
                service=None,  # No service
                description="Some playbook",
            )
        ]
        mapper = TaskMapper(mock_cache_manager, catalog)

        # Should not match (falls through to cached/semantic)
        mock_cache_manager.lookup_cached_mapping.return_value = None
        result = await mapper.map_task_to_playbook("Deploy something")
        assert result.method != "exact"

    @pytest.mark.asyncio
    async def test_exact_match_multiple_services(self, mock_cache_manager, sample_playbook_catalog):
        """Test returns first match when multiple services could match."""
        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        # "kuma" appears in catalog first
        result = await mapper.map_task_to_playbook("Setup kuma and portainer")
        assert result.playbook_path == "/ansible/kuma-deploy.yml"
        assert result.method == "exact"


# --- Test TaskMapper Cached Match ---


class TestTaskMapperCachedMatch:
    """Tests for TaskMapper cached matching."""

    @pytest.mark.asyncio
    async def test_cached_match_returns_stored(self, mock_cache_manager, sample_playbook_catalog):
        """Test cached match returns previously stored mapping."""
        # Setup mock to return cached mapping
        # Use an intent that won't trigger exact match (doesn't contain service names)
        cached_intent = "Deploy mesh networking platform"
        cached_mapping = PlaybookMapping(
            intent=cached_intent,
            intent_hash=hashlib.sha256(cached_intent.encode()).hexdigest(),
            playbook_path="/ansible/kuma-deploy.yml",
            confidence=0.90,
            match_method="semantic",
            created_at=datetime.utcnow(),
            last_used_at=datetime.utcnow(),
            use_count=5,
        )
        mock_cache_manager.lookup_cached_mapping.return_value = cached_mapping

        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        result = await mapper.map_task_to_playbook(cached_intent)
        assert result.playbook_path == "/ansible/kuma-deploy.yml"
        assert result.confidence == 0.90
        assert result.method == "cached"

    @pytest.mark.asyncio
    async def test_cached_match_updates_last_used(self, in_memory_db_session):
        """Test cached match updates last_used_at timestamp."""
        cache_manager = CacheManager(in_memory_db_session)

        # Cache a mapping
        await cache_manager.cache_mapping(
            intent="Deploy Portainer",
            playbook_path="/ansible/portainer-deploy.yml",
            confidence=0.91,
            method="semantic",
        )

        # Look it up (should update last_used_at)
        result1 = await cache_manager.lookup_cached_mapping("Deploy Portainer")
        first_used = result1.last_used_at

        # Look up again
        result2 = await cache_manager.lookup_cached_mapping("Deploy Portainer")
        second_used = result2.last_used_at

        # Second lookup should have later timestamp
        assert second_used >= first_used

    @pytest.mark.asyncio
    async def test_cached_match_low_confidence_skipped(
        self, mock_cache_manager, sample_playbook_catalog
    ):
        """Test cached mappings with confidence < 0.85 are not returned."""
        # Mock returns None for low-confidence
        mock_cache_manager.lookup_cached_mapping.return_value = None

        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        result = await mapper.map_task_to_playbook("Some low confidence intent")
        # Should fall through to semantic or none
        assert result.method != "cached"


# --- Test TaskMapper Semantic Match ---


class TestTaskMapperSemanticMatch:
    """Tests for TaskMapper semantic matching with FAISS."""

    @pytest.mark.asyncio
    async def test_semantic_match_similar_intent(self, mock_cache_manager, sample_playbook_catalog):
        """Test semantic match finds similar intent."""
        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        # Mock sentence-transformers and FAISS
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_embedder = Mock()
            # Return fixed embeddings
            mock_embedder.encode.return_value = np.array([[0.1, 0.2, 0.3, 0.4] * 96])  # 384 dims
            mock_st.return_value = mock_embedder

            with patch("faiss.IndexFlatIP") as mock_faiss:
                mock_index = Mock()
                # Simulate high-confidence match (score 0.90)
                mock_index.search.return_value = (
                    np.array([[0.90, 0.75, 0.60]]),  # scores
                    np.array([[0, 1, 2]]),  # indices
                )
                mock_faiss.return_value = mock_index

                # Use intent that won't trigger exact match
                result = await mapper.map_task_to_playbook("Deploy service mesh networking")

                assert result.playbook_path == "/ansible/kuma-deploy.yml"
                assert result.confidence >= 0.85
                assert result.method == "semantic"
                assert len(result.alternatives) <= 2  # Top 2 alternatives

    @pytest.mark.asyncio
    async def test_semantic_match_threshold_enforced(
        self, mock_cache_manager, sample_playbook_catalog
    ):
        """Test semantic matches below 0.85 threshold return no match."""
        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_embedder = Mock()
            mock_embedder.encode.return_value = np.array([[0.1, 0.2, 0.3, 0.4] * 96])
            mock_st.return_value = mock_embedder

            with patch("faiss.IndexFlatIP") as mock_faiss:
                mock_index = Mock()
                # Simulate low-confidence matches (all below 0.85)
                mock_index.search.return_value = (
                    np.array([[0.70, 0.65, 0.60]]),  # scores
                    np.array([[0, 1, 2]]),  # indices
                )
                mock_faiss.return_value = mock_index

                result = await mapper.map_task_to_playbook("Some random intent")

                assert result.method == "none"
                assert result.playbook_path is None
                assert result.suggestion is not None

    @pytest.mark.asyncio
    async def test_semantic_match_caches_result(self, mock_cache_manager, sample_playbook_catalog):
        """Test semantic matches are cached for future use."""
        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_embedder = Mock()
            mock_embedder.encode.return_value = np.array([[0.1, 0.2, 0.3, 0.4] * 96])
            mock_st.return_value = mock_embedder

            with patch("faiss.IndexFlatIP") as mock_faiss:
                mock_index = Mock()
                mock_index.search.return_value = (
                    np.array([[0.92, 0.80, 0.70]]),
                    np.array([[0, 1, 2]]),
                )
                mock_faiss.return_value = mock_index

                await mapper.map_task_to_playbook("Deploy service mesh")

                # Verify cache_mapping was called
                mock_cache_manager.cache_mapping.assert_called_once()
                call_args = mock_cache_manager.cache_mapping.call_args
                assert call_args.kwargs["confidence"] == 0.92
                assert call_args.kwargs["method"] == "semantic"

    @pytest.mark.asyncio
    async def test_semantic_match_returns_alternatives(
        self, mock_cache_manager, sample_playbook_catalog
    ):
        """Test semantic match returns top 3 alternatives."""
        mapper = TaskMapper(mock_cache_manager, sample_playbook_catalog)

        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_embedder = Mock()
            mock_embedder.encode.return_value = np.array([[0.1, 0.2, 0.3, 0.4] * 96])
            mock_st.return_value = mock_embedder

            with patch("faiss.IndexFlatIP") as mock_faiss:
                mock_index = Mock()
                # 3 matches
                mock_index.search.return_value = (
                    np.array([[0.92, 0.88, 0.80]]),
                    np.array([[0, 1, 2]]),
                )
                mock_faiss.return_value = mock_index

                result = await mapper.map_task_to_playbook("Deploy something")

                # Best match + 2 alternatives
                assert len(result.alternatives) == 2
                assert all("playbook_path" in alt for alt in result.alternatives)
                assert all("score" in alt for alt in result.alternatives)


# --- Test TaskMapper No Match ---


class TestTaskMapperNoMatch:
    """Tests for TaskMapper no-match handling."""

    @pytest.mark.asyncio
    async def test_no_match_returns_suggestion(self, mock_cache_manager):
        """Test no match returns helpful suggestion."""
        catalog = []  # Empty catalog
        mapper = TaskMapper(mock_cache_manager, catalog)

        result = await mapper.map_task_to_playbook("Deploy something")

        assert result.method == "none"
        assert result.playbook_path is None
        assert result.suggestion is not None
        assert "Options:" in result.suggestion

    @pytest.mark.asyncio
    async def test_no_match_extracts_service_name(self, mock_cache_manager):
        """Test suggestion includes likely service name."""
        catalog = []
        mapper = TaskMapper(mock_cache_manager, catalog)

        result = await mapper.map_task_to_playbook("Deploy myservice")

        assert result.suggestion is not None
        assert "myservice" in result.suggestion


# --- Test TaskMapper Integration ---


class TestTaskMapperIntegration:
    """Integration tests for TaskMapper full workflow."""

    @pytest.mark.asyncio
    async def test_hybrid_priority(self, in_memory_db_session, sample_playbook_catalog):
        """Test matching priority: exact > cached > semantic."""
        cache_manager = CacheManager(in_memory_db_session)
        mapper = TaskMapper(cache_manager, sample_playbook_catalog)

        # 1. First call: exact match wins
        result1 = await mapper.map_task_to_playbook("Deploy Kuma")
        assert result1.method == "exact"

        # 2. Cache a different intent that would semantically match "kuma-like"
        await cache_manager.cache_mapping(
            intent="Install service mesh infrastructure",
            playbook_path="/ansible/kuma-deploy.yml",
            confidence=0.90,
            method="semantic",
        )

        # 3. Query with cached intent: cached match wins
        result2 = await mapper.map_task_to_playbook("Install service mesh infrastructure")
        assert result2.method == "cached"

    @pytest.mark.asyncio
    async def test_full_workflow(self, in_memory_db_session, sample_playbook_catalog):
        """Test full workflow: semantic match -> cache -> second call uses cache."""
        cache_manager = CacheManager(in_memory_db_session)
        mapper = TaskMapper(cache_manager, sample_playbook_catalog)

        # Mock semantic search to return high-confidence match
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_embedder = Mock()
            mock_embedder.encode.return_value = np.array([[0.1, 0.2, 0.3, 0.4] * 96])
            mock_st.return_value = mock_embedder

            with patch("faiss.IndexFlatIP") as mock_faiss:
                mock_index = Mock()
                mock_index.search.return_value = (
                    np.array([[0.91, 0.80, 0.70]]),
                    np.array([[0, 1, 2]]),
                )
                mock_faiss.return_value = mock_index

                # First call: semantic match
                result1 = await mapper.map_task_to_playbook("Deploy service mesh networking")
                assert result1.method == "semantic"
                assert result1.confidence == 0.91

        # Second call: should use cached result
        result2 = await mapper.map_task_to_playbook("Deploy service mesh networking")
        assert result2.method == "cached"
        assert result2.confidence == 0.91
        assert result2.playbook_path == result1.playbook_path
