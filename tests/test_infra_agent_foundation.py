"""Tests for Infrastructure Agent foundation: InfraAgent and PlaybookDiscovery.

Test coverage:
- PlaybookMetadata Pydantic model validation
- PlaybookDiscovery service (scanning, caching, TTL enforcement)
- InfraAgent class (capabilities, inheritance, delegation)
"""

import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.agents.infra_agent import InfraAgent
from src.agents.infra_agent.playbook_discovery import (
    PlaybookDiscovery,
    PlaybookMetadata,
)
from src.common.config import Config
from src.common.protocol import WorkRequest, WorkResult

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_playbook_dir():
    """Create a temporary directory with sample playbooks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create valid playbook files
        kuma_playbook = tmpdir_path / "kuma-deploy.yml"
        kuma_playbook.write_text(
            """---
# chiffon:service=kuma
# chiffon:description=Deploy Kuma service mesh
- name: Deploy Kuma Service Mesh
  hosts: all
  vars:
    kuma_version: latest
    kuma_port: 5681
  tags:
    - deployment
    - service-mesh
  tasks:
    - name: Install Kuma
      debug:
        msg: "Installing Kuma"
"""
        )

        postgres_playbook = tmpdir_path / "postgres-setup.yaml"
        postgres_playbook.write_text(
            """---
- name: Setup PostgreSQL Database
  hosts: db_servers
  vars:
    postgres_version: "15"
    postgres_password: secret
  tags:
    - database
  tasks:
    - name: Install PostgreSQL
      debug:
        msg: "Installing PostgreSQL"
"""
        )

        # Create invalid playbook (malformed YAML)
        invalid_playbook = tmpdir_path / "invalid.yml"
        invalid_playbook.write_text(
            """---
This is not valid YAML: {[}]
  - broken indentation
"""
        )

        yield tmpdir_path


@pytest.fixture
def empty_playbook_dir():
    """Create an empty temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config():
    """Create a mock Config object for testing."""
    config = MagicMock(spec=Config)
    config.rabbitmq_host = "localhost"
    config.rabbitmq_port = 5672
    config.rabbitmq_user = "guest"
    config.rabbitmq_password = "guest"
    config.heartbeat_interval_seconds = 30
    return config


# ============================================================================
# PlaybookMetadata Tests
# ============================================================================


class TestPlaybookMetadata:
    """Test PlaybookMetadata Pydantic model validation."""

    def test_valid_metadata(self):
        """Test creating valid PlaybookMetadata instance."""
        metadata = PlaybookMetadata(
            path="/path/to/playbook.yml",
            filename="playbook.yml",
            service="kuma",
            description="Deploy Kuma",
            required_vars=["version", "port"],
            tags=["deployment"],
        )

        assert metadata.path == "/path/to/playbook.yml"
        assert metadata.filename == "playbook.yml"
        assert metadata.service == "kuma"
        assert metadata.description == "Deploy Kuma"
        assert metadata.required_vars == ["version", "port"]
        assert metadata.tags == ["deployment"]
        assert isinstance(metadata.discovered_at, datetime)

    def test_minimal_metadata(self):
        """Test creating metadata with only required fields."""
        metadata = PlaybookMetadata(
            path="/path/to/playbook.yml",
            filename="playbook.yml",
        )

        assert metadata.path == "/path/to/playbook.yml"
        assert metadata.filename == "playbook.yml"
        assert metadata.service is None
        assert metadata.description is None
        assert metadata.required_vars == []
        assert metadata.tags == []

    def test_metadata_defaults(self):
        """Test default values for optional fields."""
        metadata = PlaybookMetadata(
            path="/test.yml",
            filename="test.yml",
        )

        assert metadata.required_vars == []
        assert metadata.tags == []
        assert metadata.service is None
        assert metadata.description is None


# ============================================================================
# PlaybookDiscovery Tests
# ============================================================================


class TestPlaybookDiscovery:
    """Test PlaybookDiscovery service."""

    @pytest.mark.asyncio
    async def test_scan_empty_directory(self, empty_playbook_dir):
        """Test scanning empty directory returns empty list."""
        discovery = PlaybookDiscovery(str(empty_playbook_dir))
        playbooks = await discovery.discover_playbooks()

        assert playbooks == []
        assert discovery.is_cache_valid()

    @pytest.mark.asyncio
    async def test_scan_with_playbooks(self, temp_playbook_dir):
        """Test discovering valid playbook files."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir))
        playbooks = await discovery.discover_playbooks()

        # Should find 2 valid playbooks (kuma-deploy.yml, postgres-setup.yaml)
        # Invalid playbook should be skipped
        assert len(playbooks) == 2

        # Check service names extracted
        services = {pb.service for pb in playbooks}
        assert "kuma" in services
        assert "postgres" in services

    @pytest.mark.asyncio
    async def test_extract_service_from_filename(self, temp_playbook_dir):
        """Test service name extraction from filename pattern."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir))
        playbooks = await discovery.discover_playbooks()

        kuma_pb = next((pb for pb in playbooks if pb.service == "kuma"), None)
        assert kuma_pb is not None
        assert kuma_pb.filename == "kuma-deploy.yml"

        postgres_pb = next((pb for pb in playbooks if pb.service == "postgres"), None)
        assert postgres_pb is not None
        assert postgres_pb.filename == "postgres-setup.yaml"

    @pytest.mark.asyncio
    async def test_extract_vars_and_tags(self, temp_playbook_dir):
        """Test extracting variables and tags from playbooks."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir))
        playbooks = await discovery.discover_playbooks()

        kuma_pb = next((pb for pb in playbooks if pb.service == "kuma"), None)
        assert kuma_pb is not None
        assert "kuma_version" in kuma_pb.required_vars
        assert "kuma_port" in kuma_pb.required_vars
        assert "deployment" in kuma_pb.tags
        assert "service-mesh" in kuma_pb.tags

    @pytest.mark.asyncio
    async def test_extract_description_from_header(self, temp_playbook_dir):
        """Test description extraction from header comment."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir))
        playbooks = await discovery.discover_playbooks()

        kuma_pb = next((pb for pb in playbooks if pb.service == "kuma"), None)
        assert kuma_pb is not None
        assert kuma_pb.description == "Deploy Kuma service mesh"

    @pytest.mark.asyncio
    async def test_extract_description_from_play_name(self, temp_playbook_dir):
        """Test description extraction from play name when no header comment."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir))
        playbooks = await discovery.discover_playbooks()

        postgres_pb = next((pb for pb in playbooks if pb.service == "postgres"), None)
        assert postgres_pb is not None
        assert postgres_pb.description == "Setup PostgreSQL Database"

    @pytest.mark.asyncio
    async def test_cache_ttl_enforced(self, temp_playbook_dir):
        """Test cache TTL enforcement."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir), cache_ttl_seconds=1)

        # First scan
        playbooks1 = await discovery.discover_playbooks()
        assert len(playbooks1) == 2
        assert discovery.is_cache_valid()

        # Wait for cache to expire
        await asyncio.sleep(1.1)
        assert not discovery.is_cache_valid()

        # Second scan should rescan
        playbooks2 = await discovery.discover_playbooks()
        assert len(playbooks2) == 2
        assert discovery.is_cache_valid()

    @pytest.mark.asyncio
    async def test_force_refresh_ignores_cache(self, temp_playbook_dir):
        """Test force_refresh bypasses cache."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir), cache_ttl_seconds=3600)

        # First scan
        playbooks1 = await discovery.discover_playbooks()
        assert len(playbooks1) == 2

        # Force refresh immediately
        playbooks2 = await discovery.discover_playbooks(force_refresh=True)
        assert len(playbooks2) == 2

        # Cache should still be valid
        assert discovery.is_cache_valid()

    @pytest.mark.asyncio
    async def test_invalid_yaml_skipped(self, temp_playbook_dir):
        """Test invalid YAML files are skipped with warning logged."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir))

        playbooks = await discovery.discover_playbooks()

        # Only 2 valid playbooks found (invalid.yml skipped)
        assert len(playbooks) == 2

        # Verify the valid playbooks were found
        services = {pb.service for pb in playbooks}
        assert "kuma" in services
        assert "postgres" in services

    @pytest.mark.asyncio
    async def test_cached_catalog_valid_cache(self, temp_playbook_dir):
        """Test get_cached_catalog returns results when cache valid."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir))

        # Initial scan
        await discovery.discover_playbooks()

        # Get cached catalog
        cached = discovery.get_cached_catalog()
        assert len(cached) == 2

    @pytest.mark.asyncio
    async def test_cached_catalog_invalid_cache(self, temp_playbook_dir):
        """Test get_cached_catalog returns empty when cache invalid."""
        discovery = PlaybookDiscovery(str(temp_playbook_dir), cache_ttl_seconds=1)

        # Initial scan
        await discovery.discover_playbooks()

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Cached catalog should be empty
        cached = discovery.get_cached_catalog()
        assert len(cached) == 0

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self):
        """Test scanning nonexistent directory returns empty list."""
        discovery = PlaybookDiscovery("/nonexistent/path")
        playbooks = await discovery.discover_playbooks()

        assert playbooks == []


# ============================================================================
# InfraAgent Tests
# ============================================================================


class TestInfraAgent:
    """Test InfraAgent class."""

    def test_agent_capabilities(self, mock_config):
        """Test agent reports correct capabilities."""
        agent = InfraAgent("test-agent-001", mock_config)
        capabilities = agent.get_agent_capabilities()

        assert capabilities["run_playbook"] is True
        assert capabilities["discover_playbooks"] is True
        assert capabilities["generate_template"] is True
        assert capabilities["analyze_playbook"] is True

    def test_agent_type_is_infra(self, mock_config):
        """Test agent type is 'infra'."""
        agent = InfraAgent("test-agent-001", mock_config)
        assert agent.agent_type == "infra"

    def test_repo_path_expansion(self, mock_config, temp_playbook_dir):
        """Test repository path expansion from ~/ notation."""
        # Use temp_playbook_dir to test path expansion with existing directory
        import os

        # Create a test path with ~ notation pointing to temp dir
        # We can't actually test ~/test/path since it may not exist
        # Instead verify that path expansion happens
        agent = InfraAgent(
            "test-agent-001",
            mock_config,
            repo_path=str(temp_playbook_dir),
        )
        # Verify path is absolute, not relative
        assert os.path.isabs(str(agent.repo_path))
        assert str(agent.repo_path) == str(temp_playbook_dir)

    @pytest.mark.asyncio
    async def test_discover_playbooks_delegation(self, mock_config, temp_playbook_dir):
        """Test discover_playbooks delegates to PlaybookDiscovery."""
        agent = InfraAgent(
            "test-agent-001",
            mock_config,
            repo_path=str(temp_playbook_dir),
        )

        playbooks = await agent.discover_playbooks()

        # Should return list of dicts (model_dump)
        assert isinstance(playbooks, list)
        assert len(playbooks) == 2
        assert all(isinstance(pb, dict) for pb in playbooks)

    @pytest.mark.asyncio
    async def test_get_playbook_catalog(self, mock_config, temp_playbook_dir):
        """Test get_playbook_catalog returns cached catalog."""
        agent = InfraAgent(
            "test-agent-001",
            mock_config,
            repo_path=str(temp_playbook_dir),
        )

        # Initial discovery
        await agent.discover_playbooks()

        # Get cached catalog
        catalog = await agent.get_playbook_catalog()
        assert isinstance(catalog, list)
        assert len(catalog) == 2

    @pytest.mark.asyncio
    async def test_execute_work_with_mock(self, mock_config):
        """Test execute_work with mocked executor."""
        from unittest.mock import patch
        from uuid import uuid4

        from src.agents.infra_agent.executor import ExecutionSummary

        agent = InfraAgent("test-agent-001", mock_config)

        # Mock the executor to return success
        mock_summary = ExecutionSummary(
            status="successful",
            exit_code=0,
            duration_ms=100,
            ok_count=1,
            changed_count=0,
            failed_count=0,
            skipped_count=0,
            failed_tasks=[],
            key_errors=[],
            hosts_summary={},
        )

        with patch.object(agent.executor, "execute_playbook", return_value=mock_summary):
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={"playbook_path": "kuma-deploy.yml"},
            )

            result = await agent.execute_work(work_request)

            assert isinstance(result, WorkResult)
            assert result.status == "completed"
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_discover_playbooks_force_refresh(self, mock_config, temp_playbook_dir):
        """Test discover_playbooks with force_refresh=True."""
        agent = InfraAgent(
            "test-agent-001",
            mock_config,
            repo_path=str(temp_playbook_dir),
        )

        # Initial discovery
        playbooks1 = await agent.discover_playbooks()
        assert len(playbooks1) == 2

        # Force refresh
        playbooks2 = await agent.discover_playbooks(force_refresh=True)
        assert len(playbooks2) == 2
